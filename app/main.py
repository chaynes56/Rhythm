#!/usr/bin/env python3
# Copyright 2026 Christopher T. Haynes. See the project LICENSE file.

import base64
import io
import json
import os
import tempfile
import warnings
from pathlib import Path

import dash_bootstrap_components as dbc
import librosa
import numpy as np
import plotly.graph_objects as go
import soundfile as sf
from dash import Dash, dcc, html, Input, Output, State, clientside_callback
from dash.exceptions import PreventUpdate
from scipy.signal import welch as scipy_welch, resample as scipy_resample

# Suppress librosa deprecation warnings to clean up console output
warnings.filterwarnings("ignore", category=FutureWarning, module="librosa")

WAVEFORM_DISPLAY_SHIFT_SECONDS = 0.040
WAVEFORM_DISPLAY_SMOOTHING_WINDOW = 9
WAVEFORM_DISPLAY_DOWNSAMPLE_FACTOR = 12
AUDIO_STOP_CLICK_TRIM_SECONDS = 0.25

# Spectrum analysis
FFT_DOWNSAMPLE_RATE = 4000  # Hz — resample target; Nyquist = 2 kHz
FFT_MIN_WINDOW_SECONDS = 10.0  # s — min Welch segment length (~0.1 Hz low-end resolution)
FFT_MIN_DISPLAY_FREQ_HZ = 0.5  # Hz — lower display limit
FFT_MAX_DISPLAY_FREQ_HZ = 1000  # Hz — upper display limit
FFT_SEGMENT_OVERLAP = 0.5  # fraction — Welch segment overlap
FFT_DISPLAY_POINTS = 500  # log-spaced output points for serialization
SPECTRUM_GRAPH_HEIGHT_PX = 160  # px
SPECTRUM_GRAPH_WIDTH_PX = 500  # px

RECORDER_INLINE_SCRIPT = (Path(__file__).parent / "recorder.js").read_text(
    encoding="utf-8").replace("</script>", r"<\/script>")


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

    kernel = np.ones(window_size, dtype=np.float32) / float(window_size)
    y_smooth = np.convolve(y.astype(np.float32, copy=False), kernel, mode="same")
    return y_smooth.astype(np.float32, copy=False)


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
        xaxis=dict(type='log', title='Hz', range=[np.log10(FFT_MIN_DISPLAY_FREQ_HZ), np.log10(FFT_MAX_DISPLAY_FREQ_HZ)]),
        yaxis=dict(type='log', title='Power'),
        dragmode='pan',
        template='plotly_white',
        margin=dict(l=45, r=10, t=10, b=40),
    )
    return fig


def build_waveform_figure(y: np.ndarray, sr: int, metronome_times: np.ndarray,
                          beat_times: np.ndarray, beats_per_measure: int) -> go.Figure:
    duration = len(y) / sr if sr else 0.0
    time = np.linspace(0, duration, num=len(y), endpoint=False)
    time = time - WAVEFORM_DISPLAY_SHIFT_SECONDS
    y_for_display = smooth_waveform_for_display(y)
    time_display, y_display = downsample_waveform_preserve_peaks(time, y_for_display)

    if y_display.size == 0:
        y_display = np.array([0.0], dtype=np.float32)
        time_display = np.array([0.0], dtype=np.float32)

    y_max = float(np.max(y_display))
    y_min = float(np.min(y_display))

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=time_display, y=y_display, name="Waveform",
                             line=dict(color='blue')))

    metronome_colors = ['red' if i % beats_per_measure == 0 else 'orange' for i in
                        range(len(metronome_times))]
    fig.add_trace(go.Scatter(
        x=metronome_times,
        y=[y_max * 1.1 if i % beats_per_measure == 0 else y_max * 1.05 for i in
           range(len(metronome_times))],
        mode='markers',
        name='Beats',
        marker=dict(color=metronome_colors, symbol='diamond')
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
        dragmode="pan",
        template="plotly_white",
        margin=dict(l=40, r=20, t=20, b=40),
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
               target="_blank"),
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
                config={
                    "scrollZoom": True,
                    "displayModeBar": True,
                    "modeBarButtonsToRemove": ["pan2d", "select2d", "lasso2d",
                                               "autoScale2d"],
                    "displaylogo": False
                },
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
                            html.Label("Subdivisions / beat", className="small"),
                            dcc.Dropdown(
                                id="subdivisions-per-beat",
                                options=[{"label": str(i), "value": i} for i in
                                         range(1, 7)],
                                value=4,
                                clearable=False,
                                style={"width": "110px"},
                            ),
                        ], width="auto"),
                        dbc.Col(
                            html.Div([
                                html.Div([
                                    html.Span("—", id="counts",
                                              className="fw-semibold me-2"),
                                    html.Span("Beats / Pulses",
                                              className="small text-muted"),
                                ]),
                                html.Div("Subdivision deviation time stats",
                                         className="small text-muted fst-italic"),
                                html.Div([
                                    html.Span("—", id="pulse-count",
                                              className="fw-semibold me-2"),
                                    html.Span("mean / std in milliseconds",
                                              className="small text-muted"),
                                ]),
                            ], id="analysis-data-block"),
                            width="auto"
                        ),
                        dbc.Col(
                            dcc.Graph(
                                id="spectrum-graph",
                                style={
                                    "height": f"{SPECTRUM_GRAPH_HEIGHT_PX}px",
                                    "width": f"{SPECTRUM_GRAPH_WIDTH_PX}px",
                                    "visibility": "hidden",
                                },
                                config={"scrollZoom": True, "displayModeBar": False},
                            ),
                            width="auto",
                        ),
                    ], align="center", className="g-3"),
                ]),
            ], className="mb-4"),
        ], width=12)
    ]),

    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("Recording & Playback"),
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col([
                            dbc.Button("Start Recording", id="record-btn",
                                       color="danger", className="me-2"),
                            dbc.Button("Play Recording", id="play-btn", color="success",
                                       className="me-2"),
                            dbc.Button("Save Recording", id="save-btn", color="primary",
                                       className="me-2"),
                            dbc.Button("Load Recording", id="load-btn", color="info"),
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
                            dcc.Slider(min=0, max=1, step=0.1, value=1.0,
                                       id="recording-vol"),
                        ], width=6),
                        dbc.Col([
                            html.Label("Playback Volume", className="small"),
                            dcc.Slider(min=0, max=1, step=0.1, value=1.0,
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
                                value=1,
                                clearable=False,
                                style={"width": "90px"},
                            ),
                        ], width="auto"),
                        dbc.Col([
                            html.Label("Beats / Measure", className="small"),
                            dcc.Dropdown(
                                id="beats-per-measure",
                                options=[{"label": str(i), "value": i} for i in
                                         range(1, 17)],
                                value=4,
                                clearable=False,
                                style={"width": "90px"},
                            ),
                        ], width="auto"),
                        dbc.Col([
                            dbc.Switch(
                                id="play-hi-tone",
                                label="Play High Tone",
                                value=True,
                                style={"marginTop": "20px"}
                            ),
                        ], width="auto"),
                        dbc.Col([
                            html.Label("Beat", className="small d-block"),
                            html.Div(
                                id="beat-indicator-container",
                                children=build_beat_indicator_boxes(4, 1),
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
                            dcc.Slider(min=40, max=240, step=1, value=120,
                                       id="tempo-slider",
                                       marks={i: str(i) for i in range(40, 241, 40)}),
                        ], width=6),
                        dbc.Col([
                            html.Label("Metronome Volume", className="small"),
                            dcc.Slider(min=0, max=1, step=0.1, value=0.5,
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
    dcc.Download(id="download-audio"),
    dcc.Upload(id="upload-audio", style={"display": "none"}),
], fluid=True)

# Clientside callbacks for recording and playback
clientside_callback(
    """
    function(n_clicks, recording_phase, tempo, beats, measuresPerPattern, volume, playHiTone) {
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
                !!playHiTone
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
    function(n_clicks, playing_status, tempo, beats, measures_per_pattern, volume, play_hi_tone) {
        if (!window.recorderControls) {
            console.error("recorder.js not loaded");
            return window.dash_clientside.no_update;
        }
        const isPlaying = playing_status.length > 0;
        const hi_tone_on = !!play_hi_tone;
        if (n_clicks) {
            window.recorderControls.toggleMetronome(
            n_clicks, isPlaying, tempo, beats, measures_per_pattern, volume, hi_tone_on
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


# Debug callback to watch audio-data-store changes
@app.callback(
    Output("playback-sync", "value", allow_duplicate=True),
    Input("audio-data-store", "data"),
    prevent_initial_call=True
)
def debug_audio_store(data):
    if not data:
        raise PreventUpdate
    print(f"DEBUG: audio-data-store changed! Data length: {len(data)}")
    return f"audio-store-update-{len(data)}"


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
    Output("metronome-btn", "children"),
    Output("metronome-btn", "color"),
    Input("is-metronome-playing", "value")
)
def update_metronome_button(playing_value):
    if "playing" in playing_value:
        return "Stop Metronome", "secondary"
    return "Start Metronome", "primary"


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
    Output("counts", "children"),
    Output("pulse-count", "children"),
    Input("audio-store", "data"),
    State("subdivisions-per-beat", "value"),
)
def update_analysis_counts(audio_json, subdivisions_per_beat):
    if not audio_json:
        return "—", "—"
    try:
        data = json.loads(audio_json)
        beat_count = len(data.get("metronome_times", []))
        beat_times = data.get("beat_times", [])
        pulse_count = len(beat_times)
        # beats_per_measure = data.get("beats_per_measure")
        dt = 60 / data.get("tempo") / subdivisions_per_beat  # seconds per subdivision
        # deviations from the start of each subdivision in milliseconds
        deviations = np.array([((t - dt / 2) % dt - dt / 2) * 1000 for t in beat_times])
        mean = deviations.mean()
        std = deviations.std()
        maximum = deviations.max()  # TODO display max and median
        median = np.median(beat_times)
        return f"{beat_count} / {pulse_count}", f"{round(mean)} / {round(std)}"
    except Exception as exc:
        print(f"update_analysis_counts: {exc}")
        return "—", "—"


@app.callback(
    Output("audio-store", "data"),
    Output("waveform-visible-store", "data"),
    Output("waveform-graph", "figure"),
    Output("status-msg", "children", allow_duplicate=True),
    Input("audio-data-store", "data"),
    State("tempo-slider", "value"),
    State("beats-per-measure", "value"),
    prevent_initial_call=True
)
def process_audio(base64_audio, tempo, beats_per_measure):
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
                return None, False, go.Figure(), "Error: Failed to process audio. Recording may be corrupted or in unsupported format."

            y, sr = result
            print(
                f"process_audio: Loaded with librosa, sr={sr}, duration={len(y) / sr:.2f}s")

        # Convert to mono and trim stop-click tail before display/analysis/save
        if len(y.shape) > 1:
            y = y.mean(axis=1)
        y = trim_audio_tail(np.asarray(y, dtype=np.float32), sr)
        try:
            spec_freqs, spec_psd = compute_spectrum(y, sr)
        except Exception as spec_err:
            print(f"process_audio: spectrum failed: {spec_err}")
            spec_freqs, spec_psd = np.array([]), np.array([])
        trimmed_audio_base64 = serialize_audio_to_base64_wav(y, sr)
        y = normalize_waveform_for_display(y)

        # Pulse analysis
        onset_env = librosa.onset.onset_strength(y=y, sr=sr)

        # These 2 lines of code are causing a worker crash on cloud,
        # log shows numba/llvmlite JIT compile path.
        # tempo_detected, beats = librosa.beat.beat_track(onset_envelope=onset_env, sr=sr, bpm=tempo)
        # beat_times = librosa.frames_to_time(beats, sr=sr)
        # ...So replacing beat tracking with simpler onset detection
        onset_frames = librosa.onset.onset_detect(
            onset_envelope=onset_env,
            sr=sr,
            units="frames",
            backtrack=False
        )
        beat_times = librosa.frames_to_time(onset_frames, sr=sr)

        # Metronome points (ideal points based on tempo)
        duration = len(y) / sr
        seconds_per_beat = 60.0 / tempo
        metronome_times = np.arange(0, duration, seconds_per_beat)

        fig = build_waveform_figure(y, sr, metronome_times, beat_times,
                                    beats_per_measure)

        # Prepare data for saving
        save_data = {
            "audio": trimmed_audio_base64,
            "tempo": tempo,
            "beats_per_measure": beats_per_measure,
            "metronome_times": metronome_times.tolist(),
            "beat_times": beat_times.tolist(),
            "spectrum_freqs": spec_freqs.tolist(),
            "spectrum_psd": spec_psd.tolist(),
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
    prevent_initial_call=True
)
def load_recording(contents, beats_per_measure_slider):
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
        try:
            spec_freqs, spec_psd = compute_spectrum(y, sr)
            data["spectrum_freqs"] = spec_freqs.tolist()
            data["spectrum_psd"] = spec_psd.tolist()
        except Exception as spec_err:
            print(f"load_recording: spectrum failed: {spec_err}")
        y = normalize_waveform_for_display(y)

        duration = len(y) / sr

        metronome_times = np.array(data.get("metronome_times", []))
        beat_times = np.array(data.get("beat_times", []))
        bpm = data.get("beats_per_measure", beats_per_measure_slider)
        fig = build_waveform_figure(y, sr, metronome_times, beat_times, bpm)

        print(
            f"load_recording: Successfully processed audio, duration={duration:.2f}s, sr={sr}")
        print(
            f"load_recording: Returning data with {len(metronome_times)} metronome points, {len(beat_times)} beat points")

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

if __name__ == '__main__':
    app.run(debug=True, port=8006)
