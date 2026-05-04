#!python3
# Copyright 2026 Christopher T. Haynes. See the project LICENSE file.

import base64
import io
import json
import os
import tempfile
import warnings
from pathlib import Path
from time import time as time_now

import dash_bootstrap_components as dbc
import librosa
import numpy as np
import plotly.graph_objects as go
import soundfile as sf
from dash import Dash, ctx, dcc, html, Input, no_update, Output, State, clientside_callback
from dash.exceptions import PreventUpdate
from ruamel.yaml import YAML
from scipy.signal import welch as scipy_welch, resample as scipy_resample, find_peaks

# Suppress librosa deprecation warnings to clean up console output
warnings.filterwarnings("ignore", category=FutureWarning, module="librosa")

WAVEFORM_DISPLAY_SHIFT_SECONDS = 0.025  # increase when pulses are late
RECORDING_PRE_ROLL_SECONDS = 0.200
WAVEFORM_DISPLAY_SMOOTHING_WINDOW = 9
WAVEFORM_DISPLAY_DOWNSAMPLE_FACTOR = 12
AUDIO_STOP_CLICK_TRIM_SECONDS = 0.25
BEAT_MIN_AMPLITUDE_FRACTION = 0.4  # drop beats < this fraction of the normalized peak
BEAT_MIN_SPACING_SECONDS = 0.05  # drop beats within this many seconds of a prior beat
METRONOME_END_MARGIN_SECONDS = 0.1  # exclude metronome ticks within this many seconds of
# the audio end (avoids counting a beat at the recording cutoff)

# False to disable spectrum computation and hide the spectrum display area
SHOW_SPECTRUM = False
# False to hide the onset envelope overlay on the waveform
SHOW_ONSET_ENVELOPE = True

# dict: name -> (green cutoff, orange cutoff) red above orange cutoff in ms of
# mean absolute deviation
TRAINING_LEVEL = dict(Advanced=(7.5, 15), Intermediate=(10, 15), Novice=(15, 30))
# Deviation graph color thresholds (millisecond absolute deviation)
DEVIATION_WARN_MS = 10  # green below this, orange at or above
DEVIATION_ALERT_MS = 20  # orange below this, red at or above

# Spectrum analysis
FFT_DOWNSAMPLE_RATE = 4000  # Hz — resample target; Nyquist = 2 kHz
FFT_MIN_WINDOW_SECONDS = 10.0  # s — min Welch segment length (~0.1 Hz low-end resolution)
FFT_MIN_DISPLAY_FREQ_HZ = 0.5  # Hz — lower display limit
FFT_MAX_DISPLAY_FREQ_HZ = 1000  # Hz — upper display limit
FFT_SEGMENT_OVERLAP = 0.5  # fraction — Welch segment overlap
FFT_DISPLAY_POINTS = 500  # log-spaced output points for serialization
SPECTRUM_GRAPH_HEIGHT_PX = 160  # px
SPECTRUM_GRAPH_WIDTH_PX = 500  # px

METRONOME_SAMPLE_RATE = 22050
METRONOME_TICK_DURATION = 0.04  # seconds
METRONOME_TARGET_LOOP_SECONDS = 30.0
METRONOME_MAX_LOOP_SECONDS = 300.0
_METRONOME_TONE_FREQS = {'low': 294, 'mid': 440, 'high': 587}


def _make_metronome_tick(sr, tone_type):
    n = int(sr * METRONOME_TICK_DURATION)
    t = np.arange(n) / sr
    return np.sin(2 * np.pi * _METRONOME_TONE_FREQS[tone_type] * t) * np.exp(-40 * t)


def compute_metronome_track(tempo, beats_per_measure, measures_per_pattern, play_hi, play_only_low):
    sr = METRONOME_SAMPLE_RATE
    seconds_per_beat = 60.0 / tempo
    pattern_duration = seconds_per_beat * beats_per_measure * measures_per_pattern
    n_patterns = max(1, round(METRONOME_TARGET_LOOP_SECONDS / pattern_duration))
    while n_patterns * pattern_duration > METRONOME_MAX_LOOP_SECONDS:
        n_patterns -= 1
    n_patterns = max(1, n_patterns)
    track_samples = round(n_patterns * pattern_duration * sr)
    track = np.zeros(track_samples)
    for p in range(n_patterns):
        for m in range(measures_per_pattern):
            for b in range(beats_per_measure):
                if b == 0 and m == 0:
                    tone_type, should_play = 'low', True
                elif b == 0:
                    tone_type, should_play = 'mid', not bool(play_only_low)
                else:
                    tone_type = 'high'
                    should_play = bool(play_hi) and not bool(play_only_low)
                if not should_play:
                    continue
                beat_time = ((p * measures_per_pattern + m) * beats_per_measure + b) * seconds_per_beat
                start = round(beat_time * sr)
                tick = _make_metronome_tick(sr, tone_type)
                end = min(start + len(tick), track_samples)
                track[start:end] += tick[:end - start]
    peak = np.max(np.abs(track))
    if peak > 0:
        track *= 0.9 / peak
    buf = io.BytesIO()
    sf.write(buf, track, sr, format='WAV', subtype='PCM_16')
    buf.seek(0)
    return 'data:audio/wav;base64,' + base64.b64encode(buf.read()).decode()


RECORDER_INLINE_SCRIPT = (Path(__file__).parent / "recorder.js").read_text(
    encoding="utf-8").replace("</script>", r"<\/script>")

DEFAULT_SETTINGS_YAML = """
training-level: Novice
subdivisions-per-beat: 4
recording-vol: 1.0
playback-vol: 1.0
measures-per-pattern: 1
beats-per-measure: 4
play-hi-tone: true
play-only-low-tone: false
tempo-slider: 120
metronome-vol: 0.5
custom-exercises: |-
"""

_yaml = YAML(typ='safe', pure=True)
settings = _yaml.load(DEFAULT_SETTINGS_YAML)


def load_audio_from_bytes(audio_bytes, max_duration=600, timeout_seconds=120):
    """
    Load audio from bytes with timeout and size limits.

    Args:
        audio_bytes: Raw audio bytes from recording
        max_duration: Maximum allowed audio duration in seconds (default 10 min)
        timeout_seconds: Timeout for librosa.load (default 120 sec)

    Returns:
        tuple: (y, sr) audio array and sample rate, or None if fails
    """
    import threading

    result: dict = {"y": None, "sr": None, "error": ""}

    def load_with_librosa():
        try:
            # Detect a format from magic bytes
            suffix = '.webm'  # default
            if audio_bytes.startswith(b'RIFF') and b'WAVE' in audio_bytes[:12]:
                suffix = '.wav'
                print("Detected WAV format from magic bytes")
            elif audio_bytes.startswith(b'\xff\xfb') or audio_bytes.startswith(
                    b'\xff\xfa'):
                suffix = '.mp3'
                print("Detected MP3 format from magic bytes")
            else:
                print(f"Unknown format, magic bytes: {audio_bytes[:4].hex()}")

            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name
            try:
                print(
                    f"load_audio_from_bytes: Loading with librosa (audio size: {len(audio_bytes)} bytes, format: {suffix}, timeout: {timeout_seconds}s)...")
                # Try with different backends if available
                try:
                    y, sr = librosa.load(tmp_path, sr=None)
                except Exception as e1:
                    print(
                        f"load_audio_from_bytes: First attempt failed: {type(e1).__name__}: {e1}")
                    try:
                        y, sr = librosa.load(tmp_path, sr=None, mono=True)
                    except Exception as e2:
                        print(
                            f"load_audio_from_bytes: Second attempt failed: {type(e2).__name__}: {e2}")
                        result[
                            "error"] = f"Could not load audio: {type(e2).__name__}: {e2}"
                        return

                # Check if we successfully loaded audio
                if y is None or sr is None:
                    result["error"] = "Audio data is corrupted or in unsupported format"
                    print(f"load_audio_from_bytes: {result['error']}")
                    return

                # Check duration
                duration = len(y) / sr
                if duration > max_duration:
                    result[
                        "error"] = f"Recording too long ({duration:.1f}s > {max_duration}s max)"
                    print(f"load_audio_from_bytes: {result['error']}")
                else:
                    result["y"] = y
                    result["sr"] = sr
                    print(
                        f"load_audio_from_bytes: Loaded successfully, duration={duration:.1f}s, sr={sr}")
            finally:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
        except Exception as e:
            result["error"] = str(e)
            print(f"load_audio_from_bytes: Error: {e}")

    # Try with increased timeout
    thread = threading.Thread(target=load_with_librosa)
    thread.daemon = True
    thread.start()
    thread.join(timeout=timeout_seconds)

    if thread.is_alive():
        result["error"] = f"Audio loading timeout (>{timeout_seconds}s)"
        print(f"load_audio_from_bytes: TIMEOUT after {timeout_seconds} seconds")
        return None

    if result["error"]:
        print(f"load_audio_from_bytes: Final error: {result['error']}")
        return None

    if result["y"] is None or result["sr"] is None:
        print(f"load_audio_from_bytes: Result is missing y or sr")
        return None

    return result["y"], result["sr"]


def normalize_waveform_for_display(y: np.ndarray) -> np.ndarray:
    """
    Symmetrically clip around zero using the smaller side magnitude,
    then normalize to [-1, 1].
    """
    if y.size == 0:
        return y

    max_pos = float(np.max(y))
    max_neg = float(abs(np.min(y)))
    clip_bound = min(max_pos, max_neg)

    # Fallback if one side is near zero
    if clip_bound <= 1e-12:
        peak = float(np.max(np.abs(y)))
        if peak <= 1e-12:
            return np.zeros_like(y, dtype=np.float32)
        return (y / peak).astype(np.float32)

    y_clipped = np.clip(y, -clip_bound, clip_bound)
    y_norm = (y_clipped / clip_bound).astype(np.float32)
    return y_norm


def smooth_waveform_for_display(y: np.ndarray,
                                window_size: int = WAVEFORM_DISPLAY_SMOOTHING_WINDOW) -> np.ndarray:
    """
    Light smoothing for display before downsampling.
    """
    if y.size == 0:
        return y

    window_size = max(1, int(window_size))
    if window_size <= 1 or y.size < window_size:
        return y.astype(np.float32, copy=False)

    if window_size % 2 == 0:
        window_size += 1

    kernel = np.full(window_size, 1.0 / window_size, dtype=np.float32)
    y_float = np.asarray(y, dtype=np.float32)
    y_smooth = np.convolve(y_float, kernel, mode="same")
    return np.asarray(y_smooth, dtype=np.float32)


def downsample_waveform_preserve_peaks(time: np.ndarray, y: np.ndarray,
                                       factor: int = WAVEFORM_DISPLAY_DOWNSAMPLE_FACTOR) -> \
        tuple[np.ndarray, np.ndarray]:
    """
    Downsample waveform for plotting while preserving local min/max peaks.
    """
    factor = max(1, int(factor))
    if factor <= 1 or len(y) <= factor:
        return time, y

    bucket_size = factor
    time_out: list[float] = []
    y_out: list[float] = []

    for start in range(0, len(y), bucket_size):
        end = min(start + bucket_size, len(y))
        chunk = y[start:end]
        chunk_time = time[start:end]
        if chunk.size == 0:
            continue

        min_idx = int(np.argmin(chunk))
        max_idx = int(np.argmax(chunk))
        ordered = sorted((min_idx, max_idx)) if min_idx != max_idx else [min_idx]
        for idx in ordered:
            time_out.append(float(chunk_time[idx]))
            y_out.append(float(chunk[idx]))

    return np.array(time_out), np.array(y_out, dtype=np.float32)


def trim_audio_tail(y: np.ndarray, sr: int,
                    trim_seconds: float = AUDIO_STOP_CLICK_TRIM_SECONDS) -> np.ndarray:
    if y.size == 0 or trim_seconds <= 0 or sr <= 0:
        return y

    trim_samples = int(round(float(sr) * float(trim_seconds)))
    if trim_samples <= 0 or trim_samples >= len(y):
        return y

    return y[:-trim_samples]


def serialize_audio_to_base64_wav(y: np.ndarray, sr: int) -> str:
    with io.BytesIO() as buffer:
        sf.write(buffer, y, sr, format="WAV", subtype="PCM_16")
        wav_bytes = buffer.getvalue()
    encoded = base64.b64encode(wav_bytes).decode("ascii")
    return f"data:audio/wav;base64,{encoded}"


def detect_onsets_rms(y: np.ndarray, sr: int,
                      hop_ms: float = 1.0,
                      smooth_ms: float = 5.0) -> tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    """
    Detect percussion onsets using positive first-difference of a smoothed RMS envelope.

    Designed for downsampled recordings (e.g. 4 kHz) where librosa's minimum hop_length
    gives ~16 ms frame resolution — too coarse for timing feedback. Returns ~1 ms
    resolution at 4 kHz.

    Returns:
        onset_times: detected onset times in seconds
        onset_frames: corresponding frame indices into onset_env_norm
        onset_env_norm: normalized onset-strength envelope (for waveform display)
        hop: hop size in samples
    """
    hop = max(1, int(round(sr * hop_ms / 1000)))
    smooth_frames = max(1, int(round(smooth_ms / hop_ms)))

    n_frames = len(y) // hop
    if n_frames < 2:
        empty = np.zeros(1, dtype=np.float32)
        return np.array([]), np.array([], dtype=int), empty, hop

    frames = y[:n_frames * hop].reshape(n_frames, hop).astype(np.float32)
    rms = np.sqrt(np.mean(frames ** 2, axis=1))

    if smooth_frames > 1:
        kernel = np.full(smooth_frames, 1.0 / smooth_frames, dtype=np.float32)
        rms = np.asarray(np.convolve(rms, kernel, mode='same'), dtype=np.float32)

    # Onset strength = positive first-difference of smoothed RMS
    onset_strength = np.maximum(0.0, np.diff(rms, prepend=rms[:1]))
    peak = float(onset_strength.max())
    onset_env_norm: np.ndarray = np.asarray(onset_strength / (peak + 1e-12), dtype=np.float32)

    min_distance_frames = max(1, int(BEAT_MIN_SPACING_SECONDS * 1000 / hop_ms))
    onset_frames_arr, _ = find_peaks(
        onset_env_norm,
        height=BEAT_MIN_AMPLITUDE_FRACTION,
        distance=min_distance_frames,
    )
    onset_times = onset_frames_arr * hop / sr

    return onset_times, onset_frames_arr, onset_env_norm, hop


def filter_beat_times(beat_times: np.ndarray, onset_env_norm: np.ndarray,
                      onset_frames: np.ndarray) -> np.ndarray:
    """
    Remove beats that fail either quality criterion (applied in order):
      1. Onset envelope value at the detected frame < BEAT_MIN_AMPLITUDE_FRACTION of peak.
         Uses the normalized onset envelope (peaks at 1.0), not the raw waveform, to avoid
         sampling a near-zero instantaneous value on an oscillating signal.
      2. Beat follows a prior surviving beat by less than BEAT_MIN_SPACING_SECONDS.
         (Primary spacing enforcement is via the `wait` arg in onset_detect; this is a safety net.)
    """
    if len(beat_times) == 0:
        return beat_times

    frames = np.clip(onset_frames, 0, len(onset_env_norm) - 1)
    amplitudes = onset_env_norm[frames]

    kept: list[float] = []
    last_kept_time = -np.inf
    for t, amp in zip(beat_times, amplitudes):
        if amp < BEAT_MIN_AMPLITUDE_FRACTION:
            print(
                f"  drop beat t={t:.3f}s onset_env={amp:.3f} (below amplitude threshold {BEAT_MIN_AMPLITUDE_FRACTION})")
            continue
        if t - last_kept_time < BEAT_MIN_SPACING_SECONDS:
            print(
                f"  drop beat t={t:.3f}s onset_env={amp:.3f} (within {(t - last_kept_time) * 1000:.1f}ms of prior beat)")
            continue
        kept.append(t)
        last_kept_time = t
    return np.array(kept, dtype=np.float64)


def compute_spectrum(y: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray]:
    """
    Compute power spectral density via Welch's method.
    Downsamples to FFT_DOWNSAMPLE_RATE, uses segments of at least
    FFT_MIN_WINDOW_SECONDS padded to the next power of two.
    Returns (freqs, psd) log-spaced over (0, FFT_MAX_DISPLAY_FREQ_HZ].
    """
    sr_int = int(round(float(sr)))
    if sr_int > FFT_DOWNSAMPLE_RATE:
        n_out = int(round(len(y) * FFT_DOWNSAMPLE_RATE / sr_int))
        y_ds = scipy_resample(y.astype(np.float32), n_out)
        sr_ds = FFT_DOWNSAMPLE_RATE
    else:
        y_ds = y.astype(np.float32)
        sr_ds = sr_int

    min_samples = int(FFT_MIN_WINDOW_SECONDS * sr_ds)
    nperseg = int(2 ** np.ceil(np.log2(max(min_samples, 8))))

    if len(y_ds) < nperseg:
        y_ds = np.pad(y_ds, (0, nperseg - len(y_ds)))

    noverlap = int(nperseg * FFT_SEGMENT_OVERLAP)
    freqs_raw, psd_raw = scipy_welch(
        y_ds, fs=sr_ds, nperseg=nperseg, noverlap=noverlap,
        window='hann', detrend='constant', scaling='density',
    )

    mask = (freqs_raw >= FFT_MIN_DISPLAY_FREQ_HZ) & (
            freqs_raw <= FFT_MAX_DISPLAY_FREQ_HZ)
    freqs_raw = freqs_raw[mask]
    psd_raw = np.maximum(psd_raw[mask], 1e-24)

    if len(freqs_raw) == 0:
        return np.array([]), np.array([])

    display_freqs = np.logspace(
        np.log10(freqs_raw[0]), np.log10(freqs_raw[-1]), FFT_DISPLAY_POINTS
    )
    display_psd = np.maximum(np.interp(display_freqs, freqs_raw, psd_raw), 1e-24)
    return display_freqs, display_psd


def build_spectrum_figure(freqs: np.ndarray, psd: np.ndarray) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=freqs, y=psd,
        mode='lines',
        line=dict(color='purple', width=1),
        showlegend=False,
    ))
    fig.update_layout(
        xaxis=dict(type='log', title='Hz', range=[np.log10(FFT_MIN_DISPLAY_FREQ_HZ),
                                                  np.log10(FFT_MAX_DISPLAY_FREQ_HZ)]),
        yaxis=dict(type='log', title='Power'),
        dragmode='pan',
        template='plotly_white',
        margin=dict(l=45, r=10, t=10, b=40),
    )
    return fig


def build_waveform_figure(y: np.ndarray, sr: int, metronome_times: np.ndarray,
                          beat_times: np.ndarray, beats_per_measure: int,
                          onset_env_norm: np.ndarray | None = None,
                          hop_length: int = 512,
                          measures_per_pattern: int = 1,
                          subdivisions_per_beat: int = 1) -> go.Figure:
    duration = len(y) / sr if sr else 0.0
    time = np.linspace(0, duration, num=len(y),
                       endpoint=False) - WAVEFORM_DISPLAY_SHIFT_SECONDS
    y_for_display = smooth_waveform_for_display(y)
    time_display, y_display = downsample_waveform_preserve_peaks(time, y_for_display)
    y_peak = float(np.max(np.abs(y_display)))
    if y_peak > 1e-12:
        y_display = (y_display / y_peak).astype(np.float32)

    if y_display.size == 0:
        y_display = np.array([0.0], dtype=np.float32)
        time_display = np.array([0.0], dtype=np.float32)

    y_max = float(np.max(y_display))
    y_min = float(np.min(y_display))

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=time_display, y=y_display, name="Waveform",
                             line=dict(color='blue')))

    if onset_env_norm is not None and len(onset_env_norm) > 0:
        env_times = librosa.frames_to_time(
            np.arange(len(onset_env_norm)), sr=sr, hop_length=hop_length
        ) - WAVEFORM_DISPLAY_SHIFT_SECONDS
        # Scale envelope to the positive half of the waveform y-range
        env_scaled = onset_env_norm * y_max
        fig.add_trace(go.Scatter(
            x=env_times, y=env_scaled,
            name="Onset env",
            line=dict(color='magenta', width=1),
            opacity=0.7,
        ))

    mpp = max(1, int(measures_per_pattern or 1))
    pattern_len = beats_per_measure * mpp
    pattern_x, measure_x, beat_x = [], [], []
    for i, t in enumerate(metronome_times):
        if i % pattern_len == 0:
            pattern_x.append(t)
        elif i % beats_per_measure == 0:
            measure_x.append(t)
        else:
            beat_x.append(t)
    fig.add_trace(go.Scatter(
        x=pattern_x, y=[y_max * 1.1] * len(pattern_x),
        mode='markers', name='Pattern',
        marker=dict(color='red', symbol='diamond'),
    ))
    fig.add_trace(go.Scatter(
        x=measure_x, y=[y_max * 1.1] * len(measure_x),
        mode='markers', name='Measure',
        marker=dict(color='orange', symbol='diamond'),
    ))
    fig.add_trace(go.Scatter(
        x=beat_x, y=[y_max * 1.05] * len(beat_x),
        mode='markers', name='Beat',
        marker=dict(color='royalblue', symbol='diamond'),
    ))

    if subdivisions_per_beat > 1 and len(metronome_times) > 1:
        sub_times = []
        for i in range(len(metronome_times) - 1):
            beat_dur = metronome_times[i + 1] - metronome_times[i]
            for s in range(1, subdivisions_per_beat):
                sub_times.append(
                    metronome_times[i] + s * beat_dur / subdivisions_per_beat)
        # Extrapolate subdivisions after the last beat
        last_beat_dur = metronome_times[-1] - metronome_times[-2]
        for s in range(1, subdivisions_per_beat):
            sub_times.append(metronome_times[-1] + s * last_beat_dur / subdivisions_per_beat)
        fig.add_trace(go.Scatter(
            x=sub_times,
            y=[y_max * 1.05] * len(sub_times),
            mode='markers',
            name='Subdivision',
            marker=dict(color='black', symbol='line-ns', size=6,
                        line=dict(color='black', width=1.5)),
        ))

    fig.add_trace(go.Scatter(
        x=beat_times,
        y=[y_min * 1.1] * len(beat_times),
        mode='markers',
        name='Pulses',
        marker=dict(color='green', symbol='circle')
    ))

    fig.update_layout(
        xaxis_title="Time (s)",
        yaxis_title="Normalized Amplitude",
        yaxis_range=[-1.1, 1.1],
        yaxis_fixedrange=True,
        dragmode="zoom",
        template="plotly_white",
        margin=dict(l=60, r=20, t=20, b=40),
    )
    fig.update_xaxes(
        range=[-WAVEFORM_DISPLAY_SHIFT_SECONDS,
               duration - WAVEFORM_DISPLAY_SHIFT_SECONDS],
        autorange=False,
    )
    return fig


def build_beat_indicator_boxes(beats_per_measure: int, measures_per_pattern: int = 1) -> \
        list[html.Div]:
    beats = max(1, int(beats_per_measure or 1))
    measures = max(1, int(measures_per_pattern or 1))

    rows = []
    for m in range(measures):
        row = html.Div(
            [
                html.Div(
                    str(b + 1),
                    id=f"beat-box-{m}-{b}",
                    className="beat-indicator-box d-flex align-items-center justify-content-center",
                    style={
                        "width": "28px",
                        "height": "28px",
                        "border": "1px solid #adb5bd",
                        "borderRadius": "4px",
                        "backgroundColor": "#f8f9fa",
                        "color": "#495057",
                        "fontSize": "0.8rem",
                        "fontWeight": "600",
                    }
                )
                for b in range(beats)
            ],
            className="d-flex gap-1 align-items-center mb-1"
        )
        rows.append(row)
    return rows


app = Dash(
    __name__,
    external_stylesheets=[dbc.themes.BOOTSTRAP],
)

app.index_string = f"""
<!DOCTYPE html>
<html>
    <head>
        {{%metas%}}
        <title>{{%title%}}</title>
        {{%favicon%}}
        {{%css%}}
        <script>{RECORDER_INLINE_SCRIPT}</script>
    </head>
    <body>
        {{%app_entry%}}
        <footer>
            {{%config%}}
            {{%scripts%}}
            {{%renderer%}}
        </footer>
    </body>
</html>
"""

app.layout = dbc.Container([
    html.Div(
        html.A("Help", href="https://github.com/chaynes56/Rhythm/blob/main/README.md",
               target="_blank",
               style={"fontSize": "1.1rem", "fontWeight": "600"}),
        style={"position": "absolute", "top": "10px", "right": "20px", "zIndex": "1000"}
    ),
    dbc.Row([
        dbc.Col(html.H1("Rhythm Analysis"), className="text-center mb-4"),
    ], className="position-relative"),

    # Waveform first, full width
    dbc.Row([
        dbc.Col([
            dcc.Graph(
                id="waveform-graph",
                style={"height": "260px", "visibility": "hidden"},
                # ~6:1+ on typical desktop widths
                config=dict(scrollZoom=False, displayModeBar=True,  # type: ignore[arg-type]
                            modeBarButtonsToRemove=["pan2d", "select2d", "lasso2d",
                                                    "autoScale2d"], displaylogo=False),
            ),
        ], width=12)
    ], className="mb-0"),

    # Deviation graph — aligned under waveform
    dbc.Row([
        dbc.Col([
            dcc.Graph(
                id="deviation-graph",
                style={"height": "260px", "visibility": "hidden"},
                config={"staticPlot": True},  # type: ignore[arg-type]
            ),
        ], width=12)
    ], className="mb-4"),

    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("Analysis"),
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col([
                            html.Label("Training Level", className="small"),
                            dcc.Dropdown(
                                id="training-level",
                                options=[{"label": k, "value": k} for k in
                                         TRAINING_LEVEL],
                                value=settings["training-level"],
                                clearable=False,
                                style={"width": "140px"},
                            ),
                        ], width="auto"),
                        dbc.Col([
                            html.Label("Subdivisions / Beat", className="small"),
                            dcc.Dropdown(
                                id="subdivisions-per-beat",
                                options=[{"label": str(i), "value": i} for i in
                                         range(1, 7)],
                                value=settings["subdivisions-per-beat"],
                                clearable=False,
                                style={"width": "110px"},
                            ),
                        ], width="auto"),
                        dbc.Col(
                            dcc.Markdown(
                                id="analysis-data-block",
                                style={"width": "350px", "height": "200px"},
                            ),
                            width="auto"
                        ),
                        dbc.Col(
                            dcc.Graph(
                                id="interval-histogram",
                                style={"height": "200px", "width": "350px",
                                       "display": "none"},
                                config={"staticPlot": True},  # type: ignore[arg-type]
                            ),
                            width="auto",
                        ),
                        dbc.Col(
                            html.Div(id="subdivision-table-container"),
                            width="auto",
                        ),
                        *([dbc.Col(
                            dcc.Graph(
                                id="spectrum-graph",
                                style={
                                    "height": f"{SPECTRUM_GRAPH_HEIGHT_PX}px",
                                    "width": f"{SPECTRUM_GRAPH_WIDTH_PX}px",
                                    "visibility": "hidden",
                                },
                                config={"scrollZoom": True, "displayModeBar": False},  # type: ignore[arg-type]
                            ),
                            width="auto",
                        )] if SHOW_SPECTRUM else []),
                    ], align="start", className="g-3"),
                    html.P(id="process-status", className="mt-1 fw-bold fs-6"),
                ]),
            ], className="mb-4"),
        ], width=12)
    ]),

    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("Recording \u2014 Playback \u2014 Settings"),
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col([
                            dbc.Button("Start Recording", id="record-btn",
                                       color="danger", className="me-2"),
                            dbc.Button("Play Recording", id="play-btn", color="success",
                                       className="me-2"),
                            dbc.Button("Save Recording", id="save-btn", color="primary",
                                       className="me-2"),
                            dbc.Button("Load Recording", id="load-btn", color="info",
                                       className="me-2"),
                            dbc.Button("Save Settings", id="save-settings-btn",
                                       color="secondary", className="me-2"),
                            dbc.Button("Load Settings", id="load-settings-btn",
                                       color="secondary", className="me-2"),
                            dbc.Button("Calibrate", id="calibrate-btn",
                                       color="warning"),
                        ], width=12),
                    ], className="mb-2"),
                    dcc.Checklist(id="is-recording", options=[
                        {"label": "Recording", "value": "recording"}], value=[],
                                  style={"display": "none"}),
                    dcc.Checklist(id="is-playing",
                                  options=[{"label": "Playing", "value": "playing"}],
                                  value=[], style={"display": "none"}),
                    dbc.Row([
                        dbc.Col([
                            html.Label("Recording Volume", className="small"),
                            dcc.Slider(min=0, max=1, step=0.1, value=settings["recording-vol"],
                                       id="recording-vol"),
                        ], width=6),
                        dbc.Col([
                            html.Label("Playback Volume", className="small"),
                            dcc.Slider(min=0, max=1, step=0.1, value=settings["playback-vol"],
                                       id="playback-vol"),
                        ], width=6),
                    ]),
                    html.Div(id="status-msg", className="mt-2"),
                ]),
            ], className="mb-4"),
            dbc.Card([
                dbc.CardHeader("Metronome"),
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col([
                            dbc.Button("Start Metronome", id="metronome-btn",
                                       color="primary"),
                        ], width="auto"),
                        dbc.Col([
                            html.Label("Measures / Pattern", className="small"),
                            dcc.Dropdown(
                                id="measures-per-pattern",
                                options=[{"label": str(i), "value": i} for i in
                                         range(1, 9)],
                                value=settings["measures-per-pattern"],
                                clearable=False,
                                style={"width": "90px"},
                            ),
                            html.Label("Beats / Measure", className="small mt-2"),
                            dcc.Dropdown(
                                id="beats-per-measure",
                                options=[{"label": str(i), "value": i} for i in
                                         range(1, 17)],
                                value=settings["beats-per-measure"],
                                clearable=False,
                                style={"width": "90px"},
                            ),
                        ], width="auto"),
                        dbc.Col([
                            dbc.Switch(
                                id="play-hi-tone",
                                label="Play High Tone",
                                value=settings["play-hi-tone"],
                                style={"marginTop": "20px"}
                            ),
                            dbc.Switch(
                                id="play-only-low-tone",
                                label="Play Only Low Tone",
                                value=settings["play-only-low-tone"],
                            ),
                        ], width="auto"),
                        dbc.Col([
                            html.Label("Beat", className="small d-block"),
                            html.Div(
                                id="beat-indicator-container",
                                children=build_beat_indicator_boxes(settings["beats-per-measure"], settings["measures-per-pattern"]),
                                className="d-flex flex-column",
                            ),
                        ], width="auto"),
                    ], align="end", className="mb-3"),
                    dcc.Checklist(id="is-metronome-playing",
                                  options=[{"label": "Playing", "value": "playing"}],
                                  value=[], style={"display": "none"}),
                    dbc.Row([
                        dbc.Col([
                            html.Label("Tempo (BPM)", className="small"),
                            dcc.Slider(min=40, max=240, step=1, value=settings["tempo-slider"],
                                       id="tempo-slider",
                                       marks={i: str(i) for i in range(40, 241, 40)}),
                        ], width=6),
                        dbc.Col([
                            html.Label("Metronome Volume", className="small"),
                            dcc.Slider(min=0, max=1, step=0.1, value=settings["metronome-vol"],
                                       id="metronome-vol"),
                        ], width=6),
                    ]),
                ]),
            ]),
        ], width=12),
    ]),

    # Hidden components for data storage and communication
    dcc.Store(id="audio-store"),
    dcc.Store(id="recording-phase-store", data="idle"),
    dcc.Store(id="waveform-visible-store", data=False),
    dcc.Store(id="metronome-points-store"),
    dcc.Store(id="pulse-points-store"),
    dcc.Store(id="audio-data-store"),
    dcc.Store(id="record-command-store"),
    dcc.Store(id="metronome-command-store"),
    dbc.Button("Playback Ended", id="playback-ended-btn",
               style={"display": "none"}, n_clicks=0),
    dcc.Input(id="playback-sync", type="text", style={"display": "none"}),
    dcc.Input(id="recording-phase-sync", type="text", value="idle",
              style={"display": "none"}),
    dcc.Input(id="metronome-state-sync", type="text", value="",
              style={"display": "none"}),
    dbc.Button("Process", id="audio-process-btn", style={"display": "none"},
               n_clicks=0),
    dbc.Button("Calibration Process", id="calibration-process-btn",
               style={"display": "none"}, n_clicks=0),
    dcc.Download(id="download-audio"),
    dcc.Upload(id="upload-audio", style={"display": "none"}),
    dcc.Download(id="download-settings"),
    dcc.Store(id="settings-raw-store"),
    dcc.Store(id="metronome-track-store"),
    dcc.Store(id="calibration-audio-data-store"),
    dcc.Store(id="calibration-offset-store"),
    dcc.Store(id="calibration-command-store"),
    dcc.Interval(id="auto-calibrate-interval", interval=3000, n_intervals=0,
                 max_intervals=1),
], fluid=True)

# Calibration clientside callbacks
clientside_callback(
    """
    function(n_clicks, tempo, beats, measures, volume, hiTone, onlyLow) {
        if (n_clicks && window.recorderControls && window.recorderControls.startCalibration) {
            window.recorderControls.startCalibration(
                tempo, beats, measures, volume, !!hiTone, !!onlyLow);
        }
        return window.dash_clientside.no_update;
    }
    """,
    Output("calibration-command-store", "data"),
    Input("calibrate-btn", "n_clicks"),
    State("tempo-slider", "value"),
    State("beats-per-measure", "value"),
    State("measures-per-pattern", "value"),
    State("metronome-vol", "value"),
    State("play-hi-tone", "value"),
    State("play-only-low-tone", "value"),
    prevent_initial_call=True,
)

clientside_callback(
    """
    function(n_intervals, tempo, beats, measures, volume, hiTone, onlyLow, existing) {
        if (n_intervals > 0 && (existing === null || existing === undefined)) {
            if (window.recorderControls && window.recorderControls.startCalibration) {
                window.recorderControls.startCalibration(
                    tempo, beats, measures, volume, !!hiTone, !!onlyLow);
            }
        }
        return window.dash_clientside.no_update;
    }
    """,
    Output("calibration-command-store", "data", allow_duplicate=True),
    Input("auto-calibrate-interval", "n_intervals"),
    State("tempo-slider", "value"),
    State("beats-per-measure", "value"),
    State("measures-per-pattern", "value"),
    State("metronome-vol", "value"),
    State("play-hi-tone", "value"),
    State("play-only-low-tone", "value"),
    State("calibration-offset-store", "data"),
    prevent_initial_call=True,
)

clientside_callback(
    """
    function(n_clicks) {
        if (window.calibrationRecordedAudio) {
            const result = window.calibrationRecordedAudio;
            window.calibrationRecordedAudio = null;
            return result;
        }
        return null;
    }
    """,
    Output("calibration-audio-data-store", "data"),
    Input("calibration-process-btn", "n_clicks"),
)


@app.callback(
    Output("calibration-offset-store", "data"),
    Output("process-status", "children", allow_duplicate=True),
    Input("calibration-audio-data-store", "data"),
    State("tempo-slider", "value"),
    prevent_initial_call=True,
)
def process_calibration(base64_audio, tempo):
    if not base64_audio:
        raise PreventUpdate
    try:
        if ',' in base64_audio:
            _, data = base64_audio.split(',', 1)
        else:
            data = base64_audio
        audio_bytes = base64.b64decode(data)

        try:
            with io.BytesIO(audio_bytes) as f:
                y, sr = sf.read(f)
        except Exception:
            result = load_audio_from_bytes(audio_bytes)
            if result is None:
                return no_update, "Calibration failed: could not load audio"
            y, sr = result

        if len(y.shape) > 1:
            y = y.mean(axis=1)
        y = trim_audio_tail(np.asarray(y, dtype=np.float32), sr)
        y = normalize_waveform_for_display(y)

        beat_times, _, _, _ = detect_onsets_rms(y, sr)
        beat_times = beat_times - WAVEFORM_DISPLAY_SHIFT_SECONDS

        if len(beat_times) < 2:
            return no_update, "Calibration failed: too few beats detected"

        seconds_per_beat = 60.0 / (tempo or 120)
        phase_offset_s = float(np.median(beat_times % seconds_per_beat))
        offset_ms = round(phase_offset_s * 1000, 1)
        print(f"process_calibration: offset={offset_ms}ms from {len(beat_times)} beats")
        return offset_ms, f"Calibrated: {offset_ms} ms offset"
    except Exception as e:
        print(f"process_calibration error: {e}")
        return no_update, f"Calibration failed: {e}"


@app.callback(
    Output("metronome-track-store", "data"),
    Input("tempo-slider", "value"),
    Input("beats-per-measure", "value"),
    Input("measures-per-pattern", "value"),
    Input("play-hi-tone", "value"),
    Input("play-only-low-tone", "value"),
)
def update_metronome_track(tempo, beats_per_measure, measures_per_pattern, play_hi, play_only_low):
    try:
        data_url = compute_metronome_track(
            tempo or 120,
            beats_per_measure or 4,
            measures_per_pattern or 1,
            bool(play_hi),
            bool(play_only_low),
        )
        print(f"update_metronome_track: {beats_per_measure}/{measures_per_pattern} at {tempo} BPM")
        return data_url
    except Exception as e:
        print(f"update_metronome_track error: {e}")
        raise PreventUpdate


# Clientside callbacks for recording and playback
clientside_callback(
    """
    function(n_clicks, recording_phase, tempo, beats, measuresPerPattern, volume, playHiTone, playOnlyLowTone) {
        if (!window.recorderControls) {
            console.error("recorder.js not loaded");
            return window.dash_clientside.no_update;
        }
        if (n_clicks) {
            window.recorderControls.toggleRecording(
                n_clicks,
                recording_phase,
                tempo,
                beats,
                measuresPerPattern,
                volume,
                !!playHiTone,
                !!playOnlyLowTone  // true = only low tone plays
            );
        }
        return window.dash_clientside.no_update;
    }
    """,
    Output("record-command-store", "data"),
    Input("record-btn", "n_clicks"),
    State("recording-phase-store", "data"),
    State("tempo-slider", "value"),
    State("beats-per-measure", "value"),
    State("measures-per-pattern", "value"),
    State("metronome-vol", "value"),
    State("play-hi-tone", "value"),
    State("play-only-low-tone", "value"),
    prevent_initial_call=True,
)

clientside_callback(
    """
    function(n_clicks, volume, playing_status) {
        if (!window.recorderControls) {
            console.error("recorder.js not loaded");
            return playing_status;
        }
        const isPlaying = playing_status.length > 0;
        const result = window.recorderControls.playAudio(n_clicks, volume, isPlaying);
        return result ? ['playing'] : [];
    }
    """,
    Output("is-playing", "value"),
    Input("play-btn", "n_clicks"),
    State("playback-vol", "value"),
    State("is-playing", "value"),
)

clientside_callback(
    """
    function(n_clicks, playing_status, tempo, beats, measures_per_pattern, volume, play_hi_tone, play_only_low_tone) {
        if (!window.recorderControls) {
            console.error("recorder.js not loaded");
            return window.dash_clientside.no_update;
        }
        const isPlaying = playing_status.length > 0;
        if (n_clicks) {
            window.recorderControls.toggleMetronome(
                n_clicks, isPlaying, tempo, beats, measures_per_pattern, volume,
                !!play_hi_tone, !!play_only_low_tone
            );
        }
        return window.dash_clientside.no_update;
    }
    """,
    Output("metronome-command-store", "data"),
    Input("metronome-btn", "n_clicks"),
    State("is-metronome-playing", "value"),
    State("tempo-slider", "value"),
    State("beats-per-measure", "value"),
    State("measures-per-pattern", "value"),
    State("metronome-vol", "value"),
    State("play-hi-tone", "value"),
    State("play-only-low-tone", "value"),
    prevent_initial_call=True,
)

clientside_callback(
    """
    function(tempo, beats, measuresPerPattern, volume, playHiTone, playOnlyLowTone, isPlaying) {
        if (!window.recorderControls) return window.dash_clientside.no_update;
        const playing = isPlaying && isPlaying.length > 0;
        window.recorderControls.reconfigureMetronome(
            playing, tempo, beats, measuresPerPattern, volume, !!playHiTone, !!playOnlyLowTone
        );
        return window.dash_clientside.no_update;
    }
    """,
    Output("metronome-command-store", "data", allow_duplicate=True),
    Input("tempo-slider", "value"),
    Input("beats-per-measure", "value"),
    Input("measures-per-pattern", "value"),
    Input("metronome-vol", "value"),
    Input("play-hi-tone", "value"),
    Input("play-only-low-tone", "value"),
    State("is-metronome-playing", "value"),
    prevent_initial_call=True,
)

clientside_callback(
    """
    function(trackData) {
        if (trackData && window.recorderControls && window.recorderControls.loadMetronomeTrack) {
            window.recorderControls.loadMetronomeTrack(trackData);
        }
        return window.dash_clientside.no_update;
    }
    """,
    Output("metronome-command-store", "data", allow_duplicate=True),
    Input("metronome-track-store", "data"),
    prevent_initial_call=True,
)

clientside_callback(
    """
    function(phaseValue) {
        if (!phaseValue) {
            return window.dash_clientside.no_update;
        }
        return phaseValue;
    }
    """,
    Output("recording-phase-store", "data"),
    Input("recording-phase-sync", "value"),
)

clientside_callback(
    """
    function(phaseValue) {
        return phaseValue === 'recording' ? ['recording'] : [];
    }
    """,
    Output("is-recording", "value"),
    Input("recording-phase-store", "data"),
)

clientside_callback(
    """
    function(metronomeStateValue) {
        return metronomeStateValue === 'playing' ? ['playing'] : [];
    }
    """,
    Output("is-metronome-playing", "value"),
    Input("metronome-state-sync", "value"),
)

clientside_callback(
    """
    function(n_clicks) {
        if (window.recordedAudioData) {
            console.log("Clientside: Sending recorded audio to store, length:", window.recordedAudioData.length);
            const result = window.recordedAudioData;
            window.recordedAudioData = null;  // Clear it after sending
            return result;
        }
        return null;
    }
    """,
    Output("audio-data-store", "data"),
    Input("audio-process-btn", "n_clicks"),
)

clientside_callback(
    """
    function(audio_json) {
        if (audio_json) {
            try {
                const data = JSON.parse(audio_json);
                if (data && data.audio) {
                    window.lastRecordedAudio = data.audio;
                    console.log("Updated window.lastRecordedAudio from audio-store");
                }
            } catch (e) {
                console.error("Error parsing audio_json in clientside callback:", e);
            }
        }
        return "";
    }
    """,
    Output("playback-sync", "value"),
    Input("audio-store", "data"),
)

clientside_callback(
    """
    function(recording_phase) {
        if (recording_phase && recording_phase !== 'idle') {
            return false;
        }
        return window.dash_clientside.no_update;
    }
    """,
    Output("waveform-visible-store", "data", allow_duplicate=True),
    Input("recording-phase-store", "data"),
    prevent_initial_call=True,
)

clientside_callback(
    """
    function(n_clicks, playing_status) {
        if (!n_clicks) {
            return playing_status;
        }
        return [];
    }
    """,
    Output("is-playing", "value", allow_duplicate=True),
    Input("playback-ended-btn", "n_clicks"),
    State("is-playing", "value"),
    prevent_initial_call=True,
)

clientside_callback(
    """
    function(recording_phase, waveform_visible) {
        const baseStyle = {
            height: '260px',
            visibility: 'hidden'
        };

        if (recording_phase && recording_phase !== 'idle') {
            return baseStyle;
        }

        if (waveform_visible) {
            return {
                height: '260px',
                visibility: 'visible'
            };
        }

        return baseStyle;
    }
    """,
    Output("waveform-graph", "style"),
    Input("recording-phase-store", "data"),
    Input("waveform-visible-store", "data"),
)

if SHOW_SPECTRUM:
    clientside_callback(
        f"""
        function(waveform_visible) {{
            const v = waveform_visible ? 'visible' : 'hidden';
            return [
                {{ visibility: v }},
                {{ height: '{SPECTRUM_GRAPH_HEIGHT_PX}px', width: '{SPECTRUM_GRAPH_WIDTH_PX}px', visibility: v }},
            ];
        }}
        """,
        Output("analysis-data-block", "style"),
        Output("spectrum-graph", "style"),
        Input("waveform-visible-store", "data"),
    )
else:
    clientside_callback(
        """
        function(waveform_visible) {
            return { width: '350px', visibility: waveform_visible ? 'visible' : 'hidden' };
        }
        """,
        Output("analysis-data-block", "style"),
        Input("waveform-visible-store", "data"),
    )

clientside_callback(
    """
    function(waveform_visible) {
        return { height: '260px', visibility: waveform_visible ? 'visible' : 'hidden' };
    }
    """,
    Output("deviation-graph", "style"),
    Input("waveform-visible-store", "data"),
)

clientside_callback(
    """
    function(waveform_visible) {
        return { display: waveform_visible ? 'block' : 'none' };
    }
    """,
    Output("subdivision-table-container", "style"),
    Input("waveform-visible-store", "data"),
)

clientside_callback(
    """
    function(waveform_visible) {
        return { height: '200px', width: '350px', display: waveform_visible ? 'block' : 'none' };
    }
    """,
    Output("interval-histogram", "style"),
    Input("waveform-visible-store", "data"),
)


@app.callback(
    Output("beat-indicator-container", "children"),
    Input("beats-per-measure", "value"),
    Input("measures-per-pattern", "value"),
)
def update_beat_indicator_boxes(beats_per_measure, measures_per_pattern):
    return build_beat_indicator_boxes(beats_per_measure, measures_per_pattern)


# noinspection PyUnusedLocal
@app.callback(
    Output("status-msg", "children", allow_duplicate=True),
    Input("record-btn", "n_clicks"),
    prevent_initial_call=True
)
def clear_msg_on_record(n_clicks):
    """Clear the status message when a user clicks the record button"""
    return ""


# noinspection PyUnusedLocal
@app.callback(
    Output("status-msg", "children", allow_duplicate=True),
    Input("play-btn", "n_clicks"),
    prevent_initial_call=True
)
def clear_msg_on_play(n_clicks):
    """Clear status message when a user clicks the play button"""
    return ""


# noinspection PyUnusedLocal
@app.callback(
    Output("status-msg", "children", allow_duplicate=True),
    Input("save-btn", "n_clicks"),
    prevent_initial_call=True
)
def clear_msg_on_save(n_clicks):
    """Clear the status message when the user clicks the save button"""
    return ""


# noinspection PyUnusedLocal
@app.callback(
    Output("status-msg", "children", allow_duplicate=True),
    Input("load-btn", "n_clicks"),
    prevent_initial_call=True
)
def clear_msg_on_load(n_clicks):
    """Clear the status message when the user clicks the load button"""
    return ""



@app.callback(
    Output("record-btn", "children"),
    Output("record-btn", "color"),
    Input("recording-phase-store", "data")
)
def update_record_button(recording_phase):
    if recording_phase == "delay":
        return "Measure Delay", "warning"
    if recording_phase == "recording":
        return "Stop Recording", "secondary"
    return "Start Recording", "danger"


@app.callback(
    Output("play-btn", "children"),
    Output("play-btn", "color"),
    Input("is-playing", "value")
)
def update_play_button(playing_value):
    if "playing" in playing_value:
        return "Stop Playback", "secondary"
    return "Play Recording", "success"


if SHOW_SPECTRUM:
    @app.callback(
        Output("spectrum-graph", "figure"),
        Input("audio-store", "data"),
    )
    def update_spectrum(audio_json):
        if not audio_json:
            return go.Figure()
        try:
            data = json.loads(audio_json)
            freqs = np.array(data.get("spectrum_freqs", []))
            psd = np.array(data.get("spectrum_psd", []))
            if len(freqs) == 0:
                return go.Figure()
            return build_spectrum_figure(freqs, psd)
        except Exception as e:
            print(f"update_spectrum: {e}")
            return go.Figure()


@app.callback(
    Output("process-status", "children"),
    Input("audio-data-store", "data"),
    prevent_initial_call=True,
)
def show_analyzing_message(data):
    if not data:
        raise PreventUpdate
    return "Analyzing\u2026"


@app.callback(
    Output("analysis-data-block", "children"),
    Output("process-status", "children", allow_duplicate=True),
    Input("audio-store", "data"),
    Input("waveform-graph", "relayoutData"),
    State("subdivisions-per-beat", "value"),
    prevent_initial_call=True,
)
def update_analysis(audio_json, relayout_data, subdivisions_per_beat):
    if not audio_json:
        return "", ""
    try:
        data = json.loads(audio_json)
        all_beat_times = data.get("beat_times", [])
        all_metronome_times = data.get("metronome_times", [])

        # Determine a zoom window from relayoutData; fall back to full recording.
        # Ignore stale zoom if triggered by new audio arriving.
        t_start, t_end = None, None
        if relayout_data and ctx.triggered_id != "audio-store":
            if "xaxis.range[0]" in relayout_data:
                t_start = relayout_data["xaxis.range[0]"]
                t_end = relayout_data["xaxis.range[1]"]
            elif "xaxis.range" in relayout_data:
                t_start, t_end = relayout_data["xaxis.range"]

        if t_start is not None and t_end is not None:
            beat_times = [t for t in all_beat_times if t_start <= t <= t_end]
            metronome_times = [t for t in all_metronome_times if t_start <= t <= t_end]
            window_note = f" (zoomed window {t_start:.1f}–{t_end:.1f}s)"
        else:
            beat_times = all_beat_times
            metronome_times = all_metronome_times
            window_note = ""

        beat_count = len(metronome_times)
        pulse_count = len(beat_times)
        dt = 60 / data.get("tempo") / subdivisions_per_beat  # seconds per subdivision
        if pulse_count == 0:
            return f"No pulses detected in **{beat_count}** beats{window_note}.", ""
        deviations = np.array([((t - dt / 2) % dt - dt / 2) * 1000 for t in beat_times])
        mean = deviations.mean()
        std = deviations.std()
        maximum = deviations.max()
        median = np.median(deviations)
        markdown_text = f"""**{pulse_count}** pulses detected in **{beat_count}**
        beats{window_note}, which is **{(pulse_count / beat_count):.2f}** pulses per
        beat. The following statistics reflect time deviations from the start of
        each **{round(dt * 1000)}** ms subdivision: **{round(mean)}** mean,
        **{round(median)}** median, **{round(std)}** std dev, **{round(maximum)}** max 
        (ms)"""
        return markdown_text, ""
    except Exception as exc:
        print(f"update_analysis: {exc}")
        return "", ""


@app.callback(
    Output("subdivision-table-container", "children"),
    Input("audio-store", "data"),
    Input("waveform-graph", "relayoutData"),
    Input("training-level", "value"),
    State("subdivisions-per-beat", "value"),
    prevent_initial_call=True,
)
def update_subdivision_table(audio_json, relayout_data, training_level, subdivisions_per_beat):
    if not audio_json:
        return None
    try:
        data = json.loads(audio_json)
        all_beat_times = np.array(data.get("beat_times", []))
        tempo = data.get("tempo")
        bpm = int(data.get("beats_per_measure") or 4)
        mpp = int(data.get("measures_per_pattern") or 1)

        if not tempo or len(all_beat_times) == 0:
            return None

        spb = int(subdivisions_per_beat or 1)
        dt = 60.0 / tempo / spb  # seconds per subdivision
        warn_ms, alert_ms = TRAINING_LEVEL.get(training_level, TRAINING_LEVEL["Novice"])

        # Filter by zoom window if applicable
        beat_times = all_beat_times
        if relayout_data and ctx.triggered_id != "audio-store":
            if "xaxis.range[0]" in relayout_data:
                t0, t1 = relayout_data["xaxis.range[0]"], relayout_data[
                    "xaxis.range[1]"]
                beat_times = all_beat_times[
                    (all_beat_times >= t0) & (all_beat_times <= t1)]
            elif "xaxis.range" in relayout_data:
                t0, t1 = relayout_data["xaxis.range"]
                beat_times = all_beat_times[
                    (all_beat_times >= t0) & (all_beat_times <= t1)]

        if len(beat_times) == 0:
            return None

        deviations_ms = np.array(
            [((t - dt / 2) % dt - dt / 2) * 1000 for t in beat_times])

        subs_per_measure = bpm * spb
        # cell_devs[measure][beat][sub] = list of abs deviations
        cell_devs = [[[[] for _ in range(spb)] for _ in range(bpm)] for _ in range(mpp)]

        for t, dev in zip(beat_times, deviations_ms):
            nearest_n = int(round(t / dt))
            if nearest_n < 0:
                continue
            measure_idx = (nearest_n // subs_per_measure) % mpp
            pos_in_measure = nearest_n % subs_per_measure
            beat_idx = pos_in_measure // spb
            sub_idx = pos_in_measure % spb
            if 0 <= measure_idx < mpp and 0 <= beat_idx < bpm and 0 <= sub_idx < spb:
                cell_devs[measure_idx][beat_idx][sub_idx].append(dev)

        def cell_bg(deviations):
            if not deviations:
                return "#e8e8e8"
            if abs(float(np.mean(deviations))) < warn_ms:
                return "#c8e6c9"  # light green
            if abs(float(np.mean(deviations))) < alert_ms:
                return "#ffe0b2"  # light orange
            return "#ffcdd2"  # light red

        def cell_text(deviations):
            if not deviations:
                return "\u2014"
            return str(round(float(np.mean(deviations))))

        base_cell = {"textAlign": "center", "padding": "3px 6px",
                     "fontSize": "0.75rem", "minWidth": "30px"}
        base_th = {"textAlign": "center", "padding": "2px 4px",
                   "fontSize": "0.75rem", "borderBottom": "1px solid #aaa",
                   "background": "#f5f5f5"}

        def beat_border(beat_index):
            """Thicker right border between beats; thin on last."""
            return "2px solid #666" if beat_index < bpm - 1 else "1px solid #bbb"

        # Header row: beat labels spanning spb columns
        header_cells = [html.Th("", style={**base_th, "minWidth": "30px"})]
        for b in range(bpm):
            header_cells.append(html.Th(
                f"B{b + 1}", colSpan=spb,
                style={**base_th, "borderRight": beat_border(b)},
            ))

        rows = [html.Tr(header_cells)]

        # Sub-header row when spb > 1
        if spb > 1:
            sub_cells = [html.Th("", style={**base_th, "fontSize": "0.65rem"})]
            for b in range(bpm):
                for s in range(spb):
                    is_last = (s == spb - 1)
                    sub_cells.append(html.Th(
                        str(s + 1),
                        style={**base_th, "fontSize": "0.65rem", "color": "#888",
                               "borderRight": beat_border(
                                   b) if is_last else "1px solid #ddd"},
                    ))
            rows.append(html.Tr(sub_cells))

        # Data rows
        for m in range(mpp):
            row_cells = [html.Td(
                f"M{m + 1}",
                style={"padding": "2px 5px", "fontSize": "0.75rem",
                       "fontWeight": "600", "borderRight": "1px solid #bbb",
                       "whiteSpace": "nowrap", "background": "#f5f5f5"},
            )]
            for b in range(bpm):
                for s in range(spb):
                    devs = cell_devs[m][b][s]
                    is_last = (s == spb - 1)
                    row_cells.append(html.Td(
                        cell_text(devs),
                        style={**base_cell,
                               "backgroundColor": cell_bg(devs),
                               "borderRight": beat_border(
                                   b) if is_last else "1px solid #ddd",
                               "borderBottom": "1px solid #ddd"},
                    ))
            rows.append(html.Tr(row_cells))

        table = html.Table(
            rows,
            style={"borderCollapse": "collapse", "border": "1px solid #aaa"},
        )
        return html.Div(table, style={"overflowX": "auto"})
    except Exception as e:
        print(f"update_subdivision_table: {e}")
        return None


@app.callback(
    Output("interval-histogram", "figure"),
    Input("audio-store", "data"),
    Input("waveform-graph", "relayoutData"),
    prevent_initial_call=True,
)
def update_interval_histogram(audio_json, relayout_data):
    if not audio_json:
        return go.Figure()
    try:
        data = json.loads(audio_json)
        all_beat_times = np.array(data.get("beat_times", []))
        if len(all_beat_times) < 2:
            return go.Figure()

        beat_times = all_beat_times
        if relayout_data and ctx.triggered_id != "audio-store":
            if "xaxis.range[0]" in relayout_data:
                t0, t1 = relayout_data["xaxis.range[0]"], relayout_data["xaxis.range[1]"]
                beat_times = all_beat_times[(all_beat_times >= t0) & (all_beat_times <= t1)]
            elif "xaxis.range" in relayout_data:
                t0, t1 = relayout_data["xaxis.range"]
                beat_times = all_beat_times[(all_beat_times >= t0) & (all_beat_times <= t1)]

        if len(beat_times) < 2:
            return go.Figure()

        intervals_ms = np.diff(beat_times) * 1000
        print(f"update_interval_histogram: {len(beat_times)} pulses, {len(intervals_ms)} intervals")
        print(f"  sorted intervals (ms): {sorted(round(x, 1) for x in intervals_ms.tolist())}")

        fig = go.Figure(go.Histogram(
            x=intervals_ms,
            xbins=dict(size=1),
            marker=dict(color="steelblue"),
        ))
        fig.update_layout(
            xaxis_title="Interval (ms)",
            yaxis_title="Count",
            template="plotly_white",
            margin=dict(l=50, r=20, t=20, b=40),
        )
        return fig
    except Exception as e:
        print(f"update_interval_histogram: {e}")
        return go.Figure()


@app.callback(
    Output("deviation-graph", "figure"),
    Input("audio-store", "data"),
    Input("waveform-graph", "relayoutData"),
    Input("training-level", "value"),
    State("subdivisions-per-beat", "value"),
    prevent_initial_call=True,
)
def update_deviation_graph(audio_json, relayout_data, training_level, subdivisions_per_beat):
    if not audio_json:
        return go.Figure()
    try:
        data = json.loads(audio_json)
        beat_times = np.array(data.get("beat_times", []))
        tempo = data.get("tempo")
        duration = data.get("duration")
        if not tempo or len(beat_times) == 0:
            return go.Figure()

        spb = int(subdivisions_per_beat or 1)
        warn_ms, alert_ms = TRAINING_LEVEL.get(training_level, TRAINING_LEVEL["Novice"])
        dt = 60.0 / tempo / spb  # seconds per subdivision
        dt_ms = dt * 1000  # ms per subdivision

        deviations = np.array(
            [((t - dt / 2) % dt - dt / 2) * 1000 for t in beat_times]
        )
        abs_dev = np.abs(deviations)

        dot_colors = np.where(
            abs_dev < warn_ms, 'green',
            np.where(abs_dev < alert_ms, 'orange', 'red')
        )
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=beat_times, y=[0.0] * len(beat_times),
            mode='markers', name='Pulses',
            marker=dict(color=dot_colors.tolist(), size=6, symbol='circle'),
            showlegend=False,
        ))
        categories = [
            ('green', f'< {warn_ms} ms',
             abs_dev < warn_ms),
            ('orange', f'{warn_ms}–{alert_ms} ms',
             (abs_dev >= warn_ms) & (abs_dev < alert_ms)),
            ('red', f'≥ {alert_ms} ms',
             abs_dev >= alert_ms),
        ]
        for color, label, mask in categories:
            x_values, y_values = [], []
            for t, d in zip(beat_times[mask], deviations[mask]):
                x_values += [t, t, None]
                y_values += [0.0, d, None]
            fig.add_trace(go.Scatter(
                x=x_values, y=y_values,
                mode='lines', name=label,
                line=dict(color=color, width=2),
            ))

        # Default x range matches the waveform (full recording, with display shift)
        full_x_range = (
            [-WAVEFORM_DISPLAY_SHIFT_SECONDS, duration - WAVEFORM_DISPLAY_SHIFT_SECONDS]
            if duration else None
        )
        # Sync x range with waveform zoom
        x_range = full_x_range
        if relayout_data and ctx.triggered_id != "audio-store":
            if "xaxis.range[0]" in relayout_data:
                x_range = [relayout_data["xaxis.range[0]"],
                           relayout_data["xaxis.range[1]"]]
            elif "xaxis.range" in relayout_data:
                x_range = relayout_data["xaxis.range"]
            elif "xaxis.autorange" in relayout_data:
                x_range = full_x_range

        fig.add_hline(y=0, line_width=1, line_color="gray", line_dash="dot")
        fig.update_layout(
            xaxis_title="Time (s)",
            yaxis_title="Early \u2014 milliseconds \u2014 Late",
            yaxis_range=[-dt_ms / 2, dt_ms / 2],
            yaxis_fixedrange=True,
            dragmode=False,
            template="plotly_white",
            margin=dict(l=60, r=20, t=20, b=40),
        )
        if x_range:
            fig.update_xaxes(range=x_range, autorange=False)
        return fig
    except Exception as e:
        print(f"update_deviation_graph: {e}")
        return go.Figure()


@app.callback(
    Output("audio-store", "data"),
    Output("waveform-visible-store", "data"),
    Output("waveform-graph", "figure"),
    Output("status-msg", "children", allow_duplicate=True),
    Input("audio-data-store", "data"),
    State("tempo-slider", "value"),
    State("beats-per-measure", "value"),
    State("measures-per-pattern", "value"),
    State("subdivisions-per-beat", "value"),
    State("calibration-offset-store", "data"),
    prevent_initial_call=True
)
def process_audio(base64_audio, tempo, beats_per_measure, measures_per_pattern,
                  subdivisions_per_beat, calibration_offset_ms):
    print(f"\n{'=' * 60}")
    print(f"PROCESS_AUDIO CALLBACK TRIGGERED!")
    print(f"audio_len={len(base64_audio) if base64_audio else 0}")
    print(f"tempo={tempo}, beats_per_measure={beats_per_measure}")
    print(f"{'=' * 60}\n")

    if not base64_audio:
        print("process_audio: empty payload, skipping callback")
        raise PreventUpdate

    try:
        # Extract data from base64
        if ',' in base64_audio:
            header, data = base64_audio.split(',')
        else:
            data = base64_audio

        audio_bytes = base64.b64decode(data)
        print(f"process_audio: Decoded audio size: {len(audio_bytes)} bytes")

        # Try soundfile first (WAV), then librosa for WebM/OGG
        try:
            with io.BytesIO(audio_bytes) as f:
                y, sr = sf.read(f)
            print(
                f"process_audio: Loaded with soundfile, sr={sr}, duration={len(y) / sr:.2f}s")
        except Exception as sf_error:
            # If the soundfile fails, try librosa which can handle WebM, OGG, etc.
            print(f"Soundfile failed: {sf_error}. Trying librosa...")

            # For large recordings, use timeout
            result = load_audio_from_bytes(audio_bytes)
            if result is None:
                # Don't show an error message for auto-stop timeout - just log it
                print(
                    f"process_audio: Audio loading timeout (likely due to large file size)")
                return None, False, go.Figure(), ""

            if not isinstance(result, tuple) or result[0] is None or result[1] is None:
                msg = "Error: Failed to process audio. Recording may be corrupted or in unsupported format."
                return None, False, go.Figure(), msg

            y, sr = result
            print(
                f"process_audio: Loaded with librosa, sr={sr}, duration={len(y) / sr:.2f}s")

        # Convert to mono and trim stop-click tail before display/analysis/save
        if len(y.shape) > 1:
            y = y.mean(axis=1)
        y = trim_audio_tail(np.asarray(y, dtype=np.float32), sr)
        if SHOW_SPECTRUM:
            try:
                spec_freqs, spec_psd = compute_spectrum(y, sr)
            except Exception as spec_err:
                print(f"process_audio: spectrum failed: {spec_err}")
                spec_freqs, spec_psd = np.array([]), np.array([])
        else:
            spec_freqs, spec_psd = np.array([]), np.array([])
        trimmed_audio_base64 = serialize_audio_to_base64_wav(y, sr)
        y = normalize_waveform_for_display(y)

        # Pulse analysis — RMS envelope positive first-difference at ~1 ms resolution
        beat_times, onset_frames, onset_env_norm, hop_length = detect_onsets_rms(y, sr)
        print(
            f"process_audio: detect_onsets_rms found {len(beat_times)} onsets" +
            (f", range [{beat_times.min():.2f}, {beat_times.max():.2f}]s"
             if len(beat_times) else ""))
        beat_times = beat_times - WAVEFORM_DISPLAY_SHIFT_SECONDS

        # Metronome points for analysis/saving (shifted by calibration offset)
        duration = len(y) / sr
        seconds_per_beat = 60.0 / tempo
        cal_s = (calibration_offset_ms or 0) / 1000.0
        metronome_times = np.arange(cal_s, duration - METRONOME_END_MARGIN_SECONDS,
                                    seconds_per_beat)
        # For waveform display, omit cal_s: WAVEFORM_DISPLAY_SHIFT_SECONDS already
        # compensates D_setup, and cal_s (measured from speaker→mic) doesn't apply
        # to hand hits.
        metronome_times_display = np.arange(0, duration - METRONOME_END_MARGIN_SECONDS,
                                            seconds_per_beat)
        print(f"process_audio: calibration_offset={calibration_offset_ms}ms, cal_s={cal_s:.4f}s")

        fig = build_waveform_figure(y, sr, metronome_times_display, beat_times,
                                    beats_per_measure,
                                    onset_env_norm if SHOW_ONSET_ENVELOPE else None,
                                    hop_length,
                                    measures_per_pattern,
                                    subdivisions_per_beat)
        fig.update_layout(uirevision=str(time_now()))

        # Prepare data for saving
        save_data = {
            "audio": trimmed_audio_base64,
            "tempo": tempo,
            "beats_per_measure": beats_per_measure,
            "measures_per_pattern": measures_per_pattern,
            "metronome_times": metronome_times.tolist(),
            "beat_times": beat_times.tolist(),
            "spectrum_freqs": spec_freqs.tolist(),
            "spectrum_psd": spec_psd.tolist(),
            "duration": duration,
        }

        # Log success but don't show a message (waveform appearing is enough feedback)
        print(
            f"process_audio: Successfully processed recording, duration={duration:.2f}s")
        return json.dumps(save_data), True, fig, ""
    except PreventUpdate:
        raise
    except Exception as e:
        error_msg = f"Error processing audio: {e}"
        print(error_msg)
        import traceback
        traceback.print_exc()
        # Don't show an error message to the user - just log it
        return None, False, go.Figure(), ""


# noinspection PyUnusedLocal
@app.callback(
    Output("download-audio", "data"),
    Input("save-btn", "n_clicks"),
    State("audio-store", "data"),
    prevent_initial_call=True
)
def save_recording(n_clicks, audio_json):
    if not audio_json:
        return None
    return dict(content=audio_json, filename="recording.json")


@app.callback(
    Output("audio-store", "data", allow_duplicate=True),
    Output("waveform-visible-store", "data", allow_duplicate=True),
    Output("waveform-graph", "figure", allow_duplicate=True),
    Output("status-msg", "children"),
    Input("upload-audio", "contents"),
    State("beats-per-measure", "value"),
    State("subdivisions-per-beat", "value"),
    State("calibration-offset-store", "data"),
    prevent_initial_call=True
)
def load_recording(contents, beats_per_measure_slider, subdivisions_per_beat,
                   calibration_offset_ms):
    if not contents:
        return None, False, go.Figure(), ""

    try:
        print(f"load_recording: contents length = {len(contents) if contents else 0}")
        content_type, content_string = contents.split(',')
        print(f"load_recording: content_type = {content_type}")
        decoded = base64.b64decode(content_string)
        print(f"load_recording: decoded length = {len(decoded)}")

        try:
            data = json.loads(decoded.decode('utf-8'))
            print(
                f"load_recording: JSON parsed successfully, keys = {list(data.keys())}")
        except UnicodeDecodeError as e:
            print(f"load_recording: UnicodeDecodeError: {e}")
            return None, False, go.Figure(), "Error: Uploaded file is not a valid JSON recording saved by this app."
        except json.JSONDecodeError as e:
            print(f"load_recording: JSONDecodeError: {e}")
            return None, False, go.Figure(), "Error: Uploaded file contains invalid JSON."

        base64_audio = data["audio"]
        # Set global for playback
        # This will be passed to recorder.js if we use another clientside callback or similar.
        # But here we are on the server side. We need to pass it to JS.
        if ',' in base64_audio:
            header, audio_data = base64_audio.split(',')
        else:
            audio_data = base64_audio

        audio_bytes = base64.b64decode(audio_data)
        print(f"load_recording: Decoded audio size: {len(audio_bytes)} bytes")

        # Load with librosa (handles more formats than soundfile)
        try:
            with io.BytesIO(audio_bytes) as f:
                y, sr = sf.read(f)
            print(f"load_recording: Loaded with soundfile, sr={sr}")
        except Exception as sf_error:
            # If the soundfile fails, try librosa which can handle WebM, OGG, etc.
            print(f"Soundfile failed: {sf_error}. Trying librosa with timeout...")

            # For large recordings, use timeout
            result = load_audio_from_bytes(audio_bytes)
            if result is None:
                return None, False, go.Figure(), "Error: Recording too long or corrupted. Max length is 10 minutes."

            if not isinstance(result, tuple) or result[0] is None or result[1] is None:
                return None, False, go.Figure(), "Error: Failed to load recording. File may be corrupted or in unsupported format."

            y, sr = result
            print(f"load_recording: Loaded with librosa, sr={sr}")

        if len(y.shape) > 1:
            y = y.mean(axis=1)
        if SHOW_SPECTRUM:
            try:
                spec_freqs, spec_psd = compute_spectrum(y, sr)
                data["spectrum_freqs"] = spec_freqs.tolist()
                data["spectrum_psd"] = spec_psd.tolist()
            except Exception as spec_err:
                print(f"load_recording: spectrum failed: {spec_err}")

        _, _, onset_env_norm, hop_length = detect_onsets_rms(y, sr)

        y = normalize_waveform_for_display(y)

        duration = len(y) / sr

        tempo_saved = data.get("tempo", 120)
        seconds_per_beat_saved = 60.0 / (tempo_saved or 120)
        beat_times = np.array(data.get("beat_times", []))
        bpm = data.get("beats_per_measure", beats_per_measure_slider)
        mpp = data.get("measures_per_pattern", 1)
        metronome_times_display = np.arange(0, duration - METRONOME_END_MARGIN_SECONDS,
                                            seconds_per_beat_saved)
        fig = build_waveform_figure(y, sr, metronome_times_display, beat_times, bpm,
                                    onset_env_norm if SHOW_ONSET_ENVELOPE else None,
                                    hop_length,
                                    measures_per_pattern=mpp,
                                    subdivisions_per_beat=subdivisions_per_beat)

        print(
            f"load_recording: Successfully processed audio, duration={duration:.2f}s, sr={sr}")
        print(
            f"load_recording: Returning data with {len(metronome_times_display)} metronome points, {len(beat_times)} beat points")

        data["duration"] = duration
        # Don't show a success message (waveform appearing is enough feedback)
        return json.dumps(data), True, fig, ""
    except Exception as e:
        print(f"Error loading recording: {e}")
        # Don't show the error message to the user
        return None, False, go.Figure(), ""


clientside_callback(
    """
    function(n_clicks) {
        if (n_clicks) {
            document.querySelector('#upload-audio input').click();
        }
        return n_clicks;
    }
    """,
    Output("load-btn", "n_clicks"),
    Input("load-btn", "n_clicks"),
)

clientside_callback(
    """
    function(n_clicks) {
        if (n_clicks) {
            var fileInput = document.createElement('input');
            fileInput.type = 'file';
            fileInput.accept = '.yaml,.yml';
            fileInput.onchange = function(e) {
                var file = e.target.files[0];
                if (!file) return;
                var reader = new FileReader();
                reader.onload = function(evt) {
                    window.dash_clientside.set_props('settings-raw-store', {
                        data: {content: evt.target.result, ts: Date.now()}
                    });
                };
                reader.readAsText(file);
            };
            fileInput.click();
        }
        return n_clicks;
    }
    """,
    Output("load-settings-btn", "n_clicks"),
    Input("load-settings-btn", "n_clicks"),
)


@app.callback(
    Output("download-settings", "data"),
    Input("save-settings-btn", "n_clicks"),
    State("training-level", "value"),
    State("subdivisions-per-beat", "value"),
    State("recording-vol", "value"),
    State("playback-vol", "value"),
    State("measures-per-pattern", "value"),
    State("beats-per-measure", "value"),
    State("play-hi-tone", "value"),
    State("play-only-low-tone", "value"),
    State("tempo-slider", "value"),
    State("metronome-vol", "value"),
    prevent_initial_call=True,
)
def save_settings(n_clicks, training_level, subdivisions, rec_vol, play_vol,
                  measures, beats, play_hi, play_only_low, tempo, metro_vol):
    current = {
        "training-level": training_level,
        "subdivisions-per-beat": subdivisions,
        "recording-vol": rec_vol,
        "playback-vol": play_vol,
        "measures-per-pattern": measures,
        "beats-per-measure": beats,
        "play-hi-tone": bool(play_hi),
        "play-only-low-tone": bool(play_only_low),
        "tempo-slider": tempo,
        "metronome-vol": metro_vol,
    }
    buf = io.StringIO()
    _yaml_out = YAML()
    _yaml_out.dump(current, buf)
    return dict(content=buf.getvalue(), filename="rhythm_settings.yaml")


@app.callback(
    Output("training-level", "value"),
    Output("subdivisions-per-beat", "value"),
    Output("recording-vol", "value"),
    Output("playback-vol", "value"),
    Output("measures-per-pattern", "value"),
    Output("beats-per-measure", "value"),
    Output("play-hi-tone", "value"),
    Output("play-only-low-tone", "value"),
    Output("tempo-slider", "value"),
    Output("metronome-vol", "value"),
    Output("status-msg", "children", allow_duplicate=True),
    Input("settings-raw-store", "data"),
    prevent_initial_call=True,
)
def load_settings(data):
    if data is None:
        raise PreventUpdate
    no_change = (no_update,) * 10
    try:
        text = data["content"]
        loaded = _yaml.load(text)
        if not isinstance(loaded, dict):
            raise ValueError("Settings file did not contain a YAML mapping")
        training_level_val = loaded.get("training-level", settings["training-level"])
        print(f"load_settings: loaded keys = {list(loaded.keys())}, training-level = {training_level_val!r}")
        return (
            training_level_val,
            loaded.get("subdivisions-per-beat", settings["subdivisions-per-beat"]),
            loaded.get("recording-vol", settings["recording-vol"]),
            loaded.get("playback-vol", settings["playback-vol"]),
            loaded.get("measures-per-pattern", settings["measures-per-pattern"]),
            loaded.get("beats-per-measure", settings["beats-per-measure"]),
            loaded.get("play-hi-tone", settings["play-hi-tone"]),
            loaded.get("play-only-low-tone", settings["play-only-low-tone"]),
            loaded.get("tempo-slider", settings["tempo-slider"]),
            loaded.get("metronome-vol", settings["metronome-vol"]),
            "",
        )
    except Exception as e:
        print(f"load_settings error: {e}")
        return (*no_change, f"Failed to load settings: {e}")


if __name__ == '__main__':
    app.run(debug=True, port=8006)
