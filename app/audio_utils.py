#!python3
# Copyright 2026 Christopher T. Haynes. See the project LICENSE file.
#
# Pure audio-processing utilities with no Dash dependencies.
# Imported by main.py; can also be used and tested independently.

import base64
import io
import librosa
import numpy as np
import os
from pathlib import Path
import plotly.graph_objects as go
import soundfile as sf
import tempfile
from concurrent.futures import ThreadPoolExecutor
import warnings
from scipy.signal import find_peaks, resample as scipy_resample, welch as scipy_welch
from exercises import voicing_code
try:
    from data_samples import SAMPLES as _EMBEDDED_SAMPLES
except ImportError:
    _EMBEDDED_SAMPLES: dict[str, dict[str, str]] = {}

warnings.filterwarnings("ignore", category=FutureWarning, module="librosa")

# ---------------------------------------------------------------------------
# Timing and calibration constants
# ---------------------------------------------------------------------------

CALIBRATION_BPM = 200        # fixed BPM used for all calibration recordings
CALIBRATION_BEATS = 10       # number of beats in the calibration track
CALIBRATION_TONE = 'high'    # tone type for calibration ticks
CALIBRATION_WARMUP_MS = 200  # silence prefix in the calibration track (ms)
CALIBRATION_FAIL_STD = 1.5   # std threshold (ms) above which calibration is rejected

# ---------------------------------------------------------------------------
# Waveform display constants
# ---------------------------------------------------------------------------

# shifts waveform/pulses left to align with beat markers
WAVEFORM_DISPLAY_SHIFT_SECONDS = 0.002
WAVEFORM_DISPLAY_SMOOTHING_WINDOW = 9
WAVEFORM_DISPLAY_DOWNSAMPLE_FACTOR = 12
AUDIO_STOP_CLICK_TRIM_SECONDS = 0.25
# clip bound: ignore top remaining % of |y| samples
WAVEFORM_TRANSIENT_CLIP_PERCENTILE = 98.0

# Onset / beat filtering
BEAT_MIN_AMPLITUDE_FRACTION = 0.4  # drop beats < this fraction of the robust peak reference
BEAT_MIN_SPACING_SECONDS = 0.080   # drop beats within this many seconds of a prior beat
ONSET_ROBUST_PEAK_RANK = 3         # use Nth largest onset peak as envelope reference (skips outliers)

# ---------------------------------------------------------------------------
# Spectrum analysis constants
# ---------------------------------------------------------------------------

FFT_DOWNSAMPLE_RATE = 4000      # Hz — resample target; Nyquist = 2 kHz
FFT_MIN_WINDOW_SECONDS = 10.0   # s — min Welch segment length (~0.1 Hz low-end resolution)
FFT_MIN_DISPLAY_FREQ_HZ = 0.5   # Hz — lower display limit
FFT_MAX_DISPLAY_FREQ_HZ = 1000  # Hz — upper display limit
FFT_SEGMENT_OVERLAP = 0.5       # fraction — Welch segment overlap
FFT_DISPLAY_POINTS = 500        # log-spaced output points for serialization

# ---------------------------------------------------------------------------
# Metronome constants
# ---------------------------------------------------------------------------

# name -> (synth, voicing_code), where synth = (frequency_hz, duration_s, volume_%)
METRONOME_TONES: dict[str, tuple[tuple[int, float, float], str]] = {
    'low':  ((294,  0.040, 100), 'B'),
    'mid':  ((440,  0.040, 100), 'l'),
    'high': ((587,  0.040, 100), 'h'),
    'quiet': ((587,  0.040, 25), 'q'),
    'mute': ((587,  0.040, 50), 'm'),
    'sub':  ((1200, 0.010, 100), ''),
}

METRONOME_SAMPLE_RATE = 22050
METRONOME_TARGET_LOOP_SECONDS = 30.0
METRONOME_MAX_LOOP_SECONDS = 300.0


# ---------------------------------------------------------------------------
# Audio loading
# ---------------------------------------------------------------------------

def load_audio_from_bytes(audio_bytes, max_duration=600, timeout_seconds=120):
    """Load audio from bytes with timeout and size limits. Returns (y, sr) or None."""
    def _detect_suffix(data):
        if data.startswith(b'RIFF') and b'WAVE' in data[:12]:
            print("Detected WAV format from magic bytes")
            return '.wav'
        if data.startswith(b'\xff\xfb') or data.startswith(b'\xff\xfa'):
            print("Detected MP3 format from magic bytes")
            return '.mp3'
        print(f"Unknown format, magic bytes: {data[:4].hex()}")
        return '.webm'

    def _load():
        suffix = _detect_suffix(audio_bytes)
        print(f"load_audio_from_bytes: Loading (size: {len(audio_bytes)} bytes,"
              f" format: {suffix}, timeout: {timeout_seconds}s)...")
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name
        try:
            try:
                y, sr = librosa.load(tmp_path, sr=None)
            except Exception as e1:
                print(f"load_audio_from_bytes: First attempt failed: {type(e1).__name__}: {e1}")
                y, sr = librosa.load(tmp_path, sr=None, mono=True)
            duration = len(y) / sr
            if duration > max_duration:
                raise ValueError(f"Recording too long ({duration:.1f}s > {max_duration}s max)")
            print(f"load_audio_from_bytes: Loaded successfully, duration={duration:.1f}s, sr={sr}")
            return y, sr
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_load)
        try:
            return future.result(timeout=timeout_seconds)
        except TimeoutError:
            print(f"load_audio_from_bytes: TIMEOUT after {timeout_seconds} seconds")
            return None
        except Exception as e:
            print(f"load_audio_from_bytes: Error: {e}")
            return None


# ---------------------------------------------------------------------------
# Waveform processing
# ---------------------------------------------------------------------------

def normalize_waveform_for_display(y: np.ndarray) -> np.ndarray:
    """
    Clip at the WAVEFORM_TRANSIENT_CLIP_PERCENTILE percentile of |y|, then normalize
    to [-1, 1].  Brief loud transients (environmental noise, performance flourishes)
    that would otherwise compress the display are hard-clipped to ±1.
    """
    if y.size == 0:
        return y

    clip_bound = float(np.percentile(np.abs(y), WAVEFORM_TRANSIENT_CLIP_PERCENTILE))
    if clip_bound <= 1e-12:
        return np.zeros_like(y, dtype=np.float32)

    return np.clip(y / clip_bound, -1.0, 1.0).astype(np.float32)


def smooth_waveform_for_display(y: np.ndarray,
                                window_size: int = WAVEFORM_DISPLAY_SMOOTHING_WINDOW) -> np.ndarray:
    """Light smoothing for display before downsampling."""
    if y.size == 0:
        return y

    window_size = max(1, int(window_size))
    if window_size <= 1 or y.size < window_size:
        return y.astype(np.float32, copy=False)

    if window_size % 2 == 0:
        window_size += 1

    kernel = np.full(window_size, 1.0 / window_size, dtype=np.float32)
    y_float = np.asarray(y, dtype=np.float32)
    return np.asarray(np.convolve(y_float, kernel, mode="same"), dtype=np.float32)


def downsample_waveform_preserve_peaks(time: np.ndarray, y: np.ndarray,
                                       factor: int = WAVEFORM_DISPLAY_DOWNSAMPLE_FACTOR) -> \
        tuple[np.ndarray, np.ndarray]:
    """Downsample waveform for plotting while preserving local min/max peaks."""
    factor = max(1, int(factor))
    if factor <= 1 or len(y) <= factor:
        return time, y

    time_out: list[float] = []
    y_out: list[float] = []

    for start in range(0, len(y), factor):
        end = min(start + factor, len(y))
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


# ---------------------------------------------------------------------------
# Onset / beat detection
# ---------------------------------------------------------------------------

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

    onset_strength = np.maximum(0.0, np.diff(rms, prepend=rms[:1]))

    min_distance_frames = max(1, int(BEAT_MIN_SPACING_SECONDS * 1000 / hop_ms))

    # Normalize by the Nth largest candidate peak so that 1-2 loud transients
    # don't compress all normal beats below the amplitude threshold.
    candidates, _ = find_peaks(onset_strength, distance=min_distance_frames)
    if len(candidates) >= ONSET_ROBUST_PEAK_RANK:
        ref = float(np.sort(onset_strength[candidates])[::-1][ONSET_ROBUST_PEAK_RANK - 1])
    else:
        ref = float(onset_strength.max())
    onset_env_norm: np.ndarray = np.asarray(onset_strength / max(ref, 1e-12), dtype=np.float32)

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
            print(f"  drop beat t={t:.3f}s onset_env={amp:.3f}"
                  f" (below amplitude threshold {BEAT_MIN_AMPLITUDE_FRACTION})")
            continue
        if t - last_kept_time < BEAT_MIN_SPACING_SECONDS:
            print(f"  drop beat t={t:.3f}s onset_env={amp:.3f}"
                  f" (within {(t - last_kept_time) * 1000:.1f}ms of prior beat)")
            continue
        kept.append(t)
        last_kept_time = t
    return np.array(kept, dtype=np.float64)


# ---------------------------------------------------------------------------
# Spectrum analysis
# ---------------------------------------------------------------------------

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
    effective = max(min(min_samples, len(y_ds)), 8)
    nperseg = int(2 ** np.ceil(np.log2(effective)))

    if len(y_ds) < nperseg:
        y_ds = np.pad(y_ds, (0, nperseg - len(y_ds)))

    noverlap = int(nperseg * FFT_SEGMENT_OVERLAP)
    freqs_raw, psd_raw = scipy_welch(
        y_ds, fs=sr_ds, nperseg=nperseg, noverlap=noverlap,
        window='hann', detrend='constant', scaling='density',
    )

    mask = (freqs_raw >= FFT_MIN_DISPLAY_FREQ_HZ) & (freqs_raw <= FFT_MAX_DISPLAY_FREQ_HZ)
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


# ---------------------------------------------------------------------------
# Figure builders
# ---------------------------------------------------------------------------

def build_waveform_figure(y: np.ndarray, sr: int, metronome_times: np.ndarray,
                          beat_times: np.ndarray, beats_per_measure: int,
                          onset_env_norm: np.ndarray | None = None,
                          hop_length: int = 512,
                          measures_per_pattern: int = 1,
                          subdivisions_per_beat: int = 1,
                          display_offset: float = 0.0) -> go.Figure:
    duration = len(y) / sr if sr else 0.0
    # display_offset shifts the time origin so beat 1 appears at x≈0
    shift = WAVEFORM_DISPLAY_SHIFT_SECONDS + display_offset
    time = np.linspace(0, duration, num=len(y), endpoint=False) - shift
    mt = metronome_times - display_offset  # shifted metronome positions
    y_for_display = smooth_waveform_for_display(y)
    time_display, y_display = downsample_waveform_preserve_peaks(time, y_for_display)
    y_peak = float(np.max(np.abs(y_display)))
    if y_peak > 1e-12:
        y_display = (y_display / y_peak).astype(np.float32)

    if y_display.size == 0:
        y_display = np.array([0.0], dtype=np.float32)
        time_display = np.array([0.0], dtype=np.float32)

    # Fixed positions: y-axis range is always [-1.1, 1.1]; don't let waveform
    # amplitude asymmetry (signed max vs signed min) move the markers around.
    y_max = 1.0
    y_min = -1.0

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=time_display, y=y_display, name="Waveform",
                             line=dict(color='blue')))

    if onset_env_norm is not None and len(onset_env_norm) > 0:
        env_times = librosa.frames_to_time(
            np.arange(len(onset_env_norm)), sr=sr, hop_length=hop_length
        ) - shift
        env_scaled = onset_env_norm * y_max
        fig.add_trace(go.Scatter(
            x=env_times, y=env_scaled,
            name="Onset env",
            line=dict(color='magenta', width=1),
            opacity=0.7,
        ))
        fig.add_hline(
            y=BEAT_MIN_AMPLITUDE_FRACTION * y_max,
            line=dict(color='magenta', width=1, dash='dot'),
            opacity=0.5,
        )

    mpp = max(1, int(measures_per_pattern or 1))
    pattern_len = beats_per_measure * mpp
    pattern_x, measure_x, beat_x = [], [], []
    for i, t in enumerate(mt):
        pos = i % pattern_len
        if pos == 0:
            pattern_x.append(t)
        elif pos % beats_per_measure == 0:
            measure_x.append(t)
        else:
            beat_x.append(t)
    pattern_name = 'Pattern' if mpp > 1 else 'Measure'
    pattern_color = 'red' if mpp > 1 else 'orange'
    fig.add_trace(go.Scatter(
        x=pattern_x, y=[y_max * 1.1] * len(pattern_x),
        mode='markers', name=pattern_name,
        marker=dict(color=pattern_color, symbol='diamond'),
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

    if subdivisions_per_beat > 1 and len(mt) > 1:
        durs = np.append(np.diff(mt), mt[-1] - mt[-2])
        fracs = np.arange(1, subdivisions_per_beat) / subdivisions_per_beat
        sub_times = (mt[:, None] + durs[:, None] * fracs).ravel().tolist()
        fig.add_trace(go.Scatter(
            x=sub_times,
            y=[y_max * 1.05] * len(sub_times),
            mode='markers',
            name='Subdivision',
            marker=dict(color='black', symbol='line-ns', size=6,
                        line=dict(color='black', width=1.5)),
        ))

    fig.add_trace(go.Scatter(
        x=beat_times - display_offset,
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
        margin=dict(l=60, r=230, t=20, b=40),
    )
    fig.update_xaxes(range=[-shift, duration - shift], autorange=False)
    fig.update_yaxes(automargin=False)
    return fig


# ---------------------------------------------------------------------------
# Metronome track generation
# ---------------------------------------------------------------------------


_sample_cache: dict[tuple[str, str, int], np.ndarray] = {}
_load_log: list[str] = []


def flush_load_log() -> list[str]:
    msgs = list(_load_log)
    _load_log.clear()
    return msgs


def _make_synth_tick(sr: int, tone_type: str) -> np.ndarray:
    (freq, duration, volume), _voicing = METRONOME_TONES[tone_type]
    n = int(sr * duration)
    t = np.arange(n) / sr
    return np.sin(2 * np.pi * freq * t) * np.exp(-40 * t) * (volume / 100.0)


def _load_sample(vs: str, name: str, sr: int, fallback_tone: str = 'high') -> np.ndarray:
    key = (vs, name, sr)
    if key in _sample_cache:
        return _sample_cache[key]
    path = Path(__file__).parent / "assets" / vs / f"{name}.wav"
    try:
        if path.exists():
            data, file_sr = sf.read(str(path), dtype='float32', always_2d=False)
            source = str(path)
        elif vs in _EMBEDDED_SAMPLES and name in _EMBEDDED_SAMPLES[vs]:
            wav_bytes = base64.b64decode(_EMBEDDED_SAMPLES[vs][name])
            data, file_sr = sf.read(io.BytesIO(wav_bytes), dtype='float32', always_2d=False)
            source = f"embedded:{vs}/{name}"
        elif name != 'high':
            _load_log.append(f"fallback: {vs}/{name} -> {vs}/high")
            result = _load_sample(vs, 'high', sr, fallback_tone)
            _sample_cache[key] = result
            return result
        else:
            data_dir = path.parent
            contents = sorted(data_dir.glob("*")) if data_dir.exists() else []
            detail = [f.name for f in contents] or ["(empty)"]
            raise FileNotFoundError(f"not found: {path} (dir: {detail})")
        if file_sr != sr:
            data = librosa.resample(data, orig_sr=file_sr, target_sr=sr)
        _load_log.append(f"loaded: {source}")
    except Exception as e:
        msg = f"FAILED: {path} -- {e}"
        _load_log.append(msg)
        print(f"_load_sample: {msg} -- falling back to synthesized")
        data = _make_synth_tick(sr, fallback_tone)
    _sample_cache[key] = data
    return data


def _get_tick(sr: int, tone_type: str, vs: str = 'synthesized',
              vc_char: str | None = None) -> np.ndarray:
    vs = vs.lower()
    if vs == 'synthesized':
        return _make_synth_tick(sr, tone_type)
    char = vc_char if vc_char else METRONOME_TONES[tone_type][1]
    if not char:  # 'sub' has no VC char; keep synthesized
        return _make_synth_tick(sr, tone_type)
    name = voicing_code[char]['name'] if char in voicing_code else char
    return _load_sample(vs, name, sr, fallback_tone=tone_type)


def compute_calibration_track() -> dict:
    """Precomputed one-shot calibration track: silent warmup prefix + fixed beats.

    Returns {"data_url": "<WAV base64 data URL>", "first_beat_ms": <int>}.
    first_beat_ms is the offset within the track where beat 1 starts; JS uses it
    to time recording start without needing to know CALIBRATION_WARMUP_MS directly.
    """
    sr = METRONOME_SAMPLE_RATE
    seconds_per_beat = 60.0 / CALIBRATION_BPM
    warmup_samples = round(CALIBRATION_WARMUP_MS / 1000 * sr)
    beat_samples = round(seconds_per_beat * sr)
    total_samples = warmup_samples + CALIBRATION_BEATS * beat_samples
    track = np.zeros(total_samples)
    for i in range(CALIBRATION_BEATS):
        start = warmup_samples + i * beat_samples
        tick = _make_synth_tick(sr, CALIBRATION_TONE)
        end = min(start + len(tick), total_samples)
        track[start:end] += tick[:end - start]
    peak = np.max(np.abs(track))
    if peak > 0:
        track *= 0.9 / peak
    buf = io.BytesIO()
    sf.write(buf, track, sr, format='WAV', subtype='PCM_16')
    buf.seek(0)
    data_url = 'data:audio/wav;base64,' + base64.b64encode(buf.read()).decode()
    return {"data_url": data_url, "first_beat_ms": CALIBRATION_WARMUP_MS}


def _metro_tone(b: int, m: int, play_hi: bool, play_only_low: bool) -> tuple[str, bool]:
    """Return (tone_type, should_play) for beat b of measure m in a pattern."""
    if b == 0 and m == 0:
        return 'low', True
    if b == 0:
        return 'mid', not play_only_low
    return 'high', play_hi and not play_only_low


def compute_metronome_track(tempo, beats_per_measure, measures_per_pattern, play_hi,
                             play_only_low, exercise_patterns=None, play_subdivisions=False,
                             play_tones=False, char_tone_map=None, play_only_tones=False,
                             metro_vs='synthesized', exercise_vs='synthesized'):
    sr = METRONOME_SAMPLE_RATE
    seconds_per_beat = 60.0 / tempo

    if exercise_patterns:
        pat_durations = [
            seconds_per_beat * pat['beats_per_measure'] * len(pat['measures'])
            for pat in exercise_patterns
        ]
        cycle_duration = sum(pat_durations)
        n_cycles = max(1, round(METRONOME_TARGET_LOOP_SECONDS / cycle_duration))
        while n_cycles > 1 and n_cycles * cycle_duration > METRONOME_MAX_LOOP_SECONDS:
            n_cycles -= 1
        track_samples = round(n_cycles * cycle_duration * sr)
        track = np.zeros(track_samples)

        for c in range(n_cycles):
            pat_offset = c * cycle_duration
            for pi, pat in enumerate(exercise_patterns):
                bpm_p = pat['beats_per_measure']
                mpp_p = len(pat['measures'])
                spb_p = pat['subdivisions_per_beat']
                seconds_per_sub_p = seconds_per_beat / spb_p
                for m in range(mpp_p):
                    for b in range(bpm_p):
                        beat_time = pat_offset + (m * bpm_p + b) * seconds_per_beat
                        metro_tone, metro_play = _metro_tone(b, m, play_hi, play_only_low)
                        for s in range(spb_p):
                            t_sub = beat_time + s * seconds_per_sub_p
                            char = pat['measures'][m][b * spb_p + s]
                            if play_only_tones:
                                if char == '.':
                                    continue
                                tone_type = char_tone_map.get(char, 'high') if char_tone_map else 'high'
                                tick = _get_tick(sr, tone_type, exercise_vs, vc_char=char)
                            elif play_tones and char_tone_map and char != '.':
                                tone_type = char_tone_map.get(char, 'high')
                                tick = _get_tick(sr, tone_type, exercise_vs, vc_char=char)
                            elif s == 0 and metro_play:
                                tick = _get_tick(sr, metro_tone, metro_vs)
                            elif s > 0 and play_subdivisions:
                                tick = _get_tick(sr, 'sub', metro_vs)
                            else:
                                continue
                            start = round(t_sub * sr)
                            end = min(start + len(tick), track_samples)
                            track[start:end] += tick[:end - start]
                pat_offset += pat_durations[pi]
    else:
        pattern_duration = seconds_per_beat * beats_per_measure * measures_per_pattern
        n_patterns = max(1, round(METRONOME_TARGET_LOOP_SECONDS / pattern_duration))
        while n_patterns > 1 and n_patterns * pattern_duration > METRONOME_MAX_LOOP_SECONDS:
            n_patterns -= 1
        track_samples = round(n_patterns * pattern_duration * sr)
        track = np.zeros(track_samples)

        for p in range(n_patterns):
            for m in range(measures_per_pattern):
                for b in range(beats_per_measure):
                    tone_type, should_play = _metro_tone(b, m, play_hi, play_only_low)
                    if should_play:
                        beat_time = ((p * measures_per_pattern + m) * beats_per_measure + b) * seconds_per_beat
                        start = round(beat_time * sr)
                        tick = _get_tick(sr, tone_type, metro_vs)
                        end = min(start + len(tick), track_samples)
                        track[start:end] += tick[:end - start]

    peak = np.max(np.abs(track))
    if peak > 0:
        track *= 0.9 / peak
    buf = io.BytesIO()
    sf.write(buf, track, sr, format='WAV', subtype='PCM_16')
    buf.seek(0)
    return 'data:audio/wav;base64,' + base64.b64encode(buf.read()).decode()
