#!/usr/bin/env python3
# Copyright 2026 Christopher T. Haynes. See the project LICENSE file.

from dash import Dash, dcc, html, Input, Output, State, clientside_callback
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import numpy as np
import base64
import io
import soundfile as sf
import librosa
import json
import warnings
import tempfile
import os

# Suppress librosa deprecation warnings to clean up console output
warnings.filterwarnings("ignore", category=FutureWarning, module="librosa")

def load_audio_from_bytes(audio_bytes, max_duration=600, timeout_seconds=120):
    """
    Load audio from bytes with timeout and size limits.

    Args:
        audio_bytes: Raw audio bytes from recording
        max_duration: Maximum allowed audio duration in seconds (default 10 min)
        timeout_seconds: Timeout for librosa.load (default 120 sec for recordings up to 60s)

    Returns:
        tuple: (y, sr) audio array and sample rate, or None if fails
    """
    import threading

    result: dict = {"y": None, "sr": None, "error": ""}

    def load_with_librosa():
        try:
            # Detect format from magic bytes
            suffix = '.webm'  # default
            if audio_bytes.startswith(b'RIFF') and b'WAVE' in audio_bytes[:12]:
                suffix = '.wav'
                print("Detected WAV format from magic bytes")
            elif audio_bytes.startswith(b'\xff\xfb') or audio_bytes.startswith(b'\xff\xfa'):
                suffix = '.mp3'
                print("Detected MP3 format from magic bytes")
            else:
                print(f"Unknown format, magic bytes: {audio_bytes[:4].hex()}")

            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name
            try:
                print(f"load_audio_from_bytes: Loading with librosa (audio size: {len(audio_bytes)} bytes, format: {suffix}, timeout: {timeout_seconds}s)...")
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
                    result["error"] = f"Recording too long ({duration:.1f}s > {max_duration}s max)"
                    print(f"load_audio_from_bytes: {result['error']}")
                else:
                    result["y"] = y
                    result["sr"] = sr
                    print(f"load_audio_from_bytes: Loaded successfully, duration={duration:.1f}s, sr={sr}")
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


app = Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])

app.layout = dbc.Container([
    dbc.Row([
        dbc.Col(html.H1("Rhythm Analysis App"), className="text-center mb-4")
    ]),

    # Waveform first, full width
    dbc.Row([
        dbc.Col([
            dcc.Graph(
                id="waveform-graph",
                style={"height": "260px"},  # ~6:1+ on typical desktop widths
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
                dbc.CardHeader("Recording & Playback"),
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col([
                            dbc.Button("Start Recording", id="record-btn", color="danger", className="me-2"),
                            dbc.Button("Play Recording", id="play-btn", color="success", className="me-2"),
                            dbc.Button("Save Recording", id="save-btn", color="primary", className="me-2"),
                            dbc.Button("Load Recording", id="load-btn", color="info"),
                        ], width=12),
                    ], className="mb-2"),
                    dcc.Checklist(id="is-recording", options=[{"label": "Recording", "value": "recording"}], value=[], style={"display": "none"}),
                    dcc.Checklist(id="is-playing", options=[{"label": "Playing", "value": "playing"}], value=[], style={"display": "none"}),
                    dbc.Row([
                        dbc.Col([
                            html.Label("Recording Volume", className="small"),
                            dcc.Slider(min=0, max=1, step=0.1, value=1.0, id="recording-vol"),
                        ], width=6),
                        dbc.Col([
                            html.Label("Playback Volume", className="small"),
                            dcc.Slider(min=0, max=1, step=0.1, value=1.0, id="playback-vol"),
                        ], width=6),
                    ]),
                    html.Div(id="status-msg", className="mt-2"),
                ]),
            ], className="mb-4"),
            dbc.Card([
                dbc.CardHeader("Metronome Settings"),
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col([
                            dbc.Button("Start Metronome", id="metronome-btn", color="primary"),
                        ], width="auto"),
                        dbc.Col([
                            html.Label("Measures / Pattern", className="small"),
                            dcc.Dropdown(
                                id="measures-per-pattern",
                                options=[{"label": str(i), "value": i} for i in range(1, 9)],
                                value=1,
                                clearable=False,
                                style={"width": "90px"},
                            ),
                        ], width="auto"),
                        dbc.Col([
                            html.Label("Beats / Measure", className="small"),
                            dcc.Dropdown(
                                id="beats-per-measure",
                                options=[{"label": str(i), "value": i} for i in range(1, 13)],
                                value=4,
                                clearable=False,
                                style={"width": "90px"},
                            ),
                        ], width="auto"),
                        dbc.Col([
                            dcc.Checklist(
                                id="play-hi-tone",
                                options=[{"label": "Play Hi Tone", "value": "on"}],
                                value=["on"],
                                style={"marginTop": "20px"}
                            ),
                        ], width="auto"),
                    ], align="end", className="mb-3"),
                    dcc.Checklist(id="is-metronome-playing", options=[{"label": "Playing", "value": "playing"}], value=[], style={"display": "none"}),
                    dbc.Row([
                        dbc.Col([
                            html.Label("Tempo (BPM)", className="small"),
                            dcc.Slider(min=40, max=240, step=1, value=120, id="tempo-slider", marks={i: str(i) for i in range(40, 241, 40)}),
                        ], width=6),
                        dbc.Col([
                            html.Label("Metronome Volume", className="small"),
                            dcc.Slider(min=0, max=1, step=0.1, value=0.5, id="metronome-vol"),
                        ], width=6),
                    ]),
                ]),
            ]),
        ], width=12),
    ]),

    # Hidden components for data storage and communication
    dcc.Store(id="audio-store"),
    dcc.Store(id="metronome-points-store"),
    dcc.Store(id="pulse-points-store"),
    dcc.Store(id="audio-data-store"),
    dcc.Input(id="playback-sync", type="text", style={"display": "none"}),
    dbc.Button("Process", id="audio-process-btn", style={"display": "none"}, n_clicks=0),
    dcc.Download(id="download-audio"),
    dcc.Upload(id="upload-audio", style={"display": "none"}),
], fluid=True)

# Clientside callbacks for recording and playback
clientside_callback(
    """
    function(n_clicks, recording_status) {
        if (n_clicks) {
            return window.dash_clientside.recorder.toggleRecording(n_clicks, recording_status.length > 0) ? ['recording'] : [];
        }
        return recording_status;
    }
    """,
    Output("is-recording", "value"),
    Input("record-btn", "n_clicks"),
    State("is-recording", "value"),
)

clientside_callback(
    """
    function(n_clicks, volume, playing_status) {
        const isPlaying = playing_status.length > 0;
        const result = window.dash_clientside.recorder.playAudio(n_clicks, volume, isPlaying);
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
        const isPlaying = playing_status.length > 0;
        const hi_tone_on = play_hi_tone && play_hi_tone.length > 0;
        const result = window.dash_clientside.recorder.toggleMetronome(
            n_clicks, isPlaying, tempo, beats, measures_per_pattern, volume, hi_tone_on
        );
        return result ? ['playing'] : [];
    }
    """,
    Output("is-metronome-playing", "value"),
    Input("metronome-btn", "n_clicks"),
    State("is-metronome-playing", "value"),
    State("tempo-slider", "value"),
    State("beats-per-measure", "value"),
    State("measures-per-pattern", "value"),
    State("metronome-vol", "value"),
    State("play-hi-tone", "value"),
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
    Output("status-msg", "children", allow_duplicate=True),
    Input("play-btn", "n_clicks"),
    prevent_initial_call=True
)
def clear_msg_on_play(n_clicks):
    """Clear status message when user clicks play button"""
    return ""

@app.callback(
    Output("status-msg", "children", allow_duplicate=True),
    Input("save-btn", "n_clicks"),
    prevent_initial_call=True
)
def clear_msg_on_save(n_clicks):
    """Clear status message when user clicks save button"""
    return ""

@app.callback(
    Output("status-msg", "children", allow_duplicate=True),
    Input("load-btn", "n_clicks"),
    prevent_initial_call=True
)
def clear_msg_on_load(n_clicks):
    """Clear status message when user clicks load button"""
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
    Input("is-recording", "value")
)
def update_record_button(recording_value):
    if "recording" in recording_value:
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
    Output("audio-store", "data"),
    Output("waveform-graph", "figure"),
    Output("status-msg", "children", allow_duplicate=True),
    Input("audio-data-store", "data"),
    State("tempo-slider", "value"),
    State("beats-per-measure", "value"),
    prevent_initial_call=True
)
def process_audio(base64_audio, tempo, beats_per_measure):
    print(f"\n{'='*60}")
    print(f"PROCESS_AUDIO CALLBACK TRIGGERED!")
    print(f"audio_len={len(base64_audio) if base64_audio else 0}")
    print(f"tempo={tempo}, beats_per_measure={beats_per_measure}")
    print(f"{'='*60}\n")

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
            print(f"process_audio: Loaded with soundfile, sr={sr}, duration={len(y)/sr:.2f}s")
        except Exception as sf_error:
            # If soundfile fails, try librosa which can handle WebM, OGG, etc.
            print(f"Soundfile failed: {sf_error}. Trying librosa...")

            # For large recordings, use timeout
            result = load_audio_from_bytes(audio_bytes)
            if result is None:
                # Don't show error message for auto-stop timeout - just log it
                print(f"process_audio: Audio loading timeout (likely due to large file size)")
                return None, go.Figure(), ""

            if not isinstance(result, tuple) or result[0] is None or result[1] is None:
                return None, go.Figure(), "Error: Failed to process audio. Recording may be corrupted or in unsupported format."

            y, sr = result
            print(f"process_audio: Loaded with librosa, sr={sr}, duration={len(y)/sr:.2f}s")

        # Convert to mono if stereo, then normalize for display
        if len(y.shape) > 1:
            y = y.mean(axis=1)
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

        # Create waveform figure
        time = np.linspace(0, duration, num=len(y))
        # Downsample for display if too large
        if len(y) > 10000:
            skip = len(y) // 10000
            time_display = time[::skip]
            y_display = y[::skip]
        else:
            time_display = time
            y_display = y

        fig = go.Figure()
        fig.add_trace(go.Scatter(x=time_display, y=y_display, name="Waveform", line=dict(color='blue')))

        # Add metronome points
        metronome_colors = ['red' if i % beats_per_measure == 0 else 'orange' for i in range(len(metronome_times))]
        fig.add_trace(go.Scatter(
            x=metronome_times,
            y=[max(y_display)*1.1 if i % beats_per_measure == 0 else max(y_display)*1.05 for i in range(len(metronome_times))],
            mode='markers',
            name='Metronome',
            marker=dict(color=metronome_colors, symbol='diamond')
        ))

        # Add pulse points
        fig.add_trace(go.Scatter(
            x=beat_times,
            y=[min(y_display)*1.1] * len(beat_times),
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

        # Prepare data for saving
        save_data = {
            "audio": base64_audio,
            "tempo": tempo,
            "beats_per_measure": beats_per_measure,
            "metronome_times": metronome_times.tolist(),
            "beat_times": beat_times.tolist()
        }

        # Log success but don't show message (waveform appearing is enough feedback)
        print(f"process_audio: Successfully processed recording, duration={duration:.2f}s")
        return json.dumps(save_data), fig, ""
    except PreventUpdate:
        raise
    except Exception as e:
        error_msg = f"Error processing audio: {e}"
        print(error_msg)
        import traceback
        traceback.print_exc()
        # Don't show error message to user - just log it
        return None, go.Figure(), ""

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
    Output("waveform-graph", "figure", allow_duplicate=True),
    Output("status-msg", "children"),
    Input("upload-audio", "contents"),
    State("tempo-slider", "value"),
    State("beats-per-measure", "value"),
    prevent_initial_call=True
)
def load_recording(contents, tempo_slider, beats_per_measure_slider):
    if not contents:
        return None, go.Figure(), ""
    
    try:
        print(f"load_recording: contents length = {len(contents) if contents else 0}")
        content_type, content_string = contents.split(',')
        print(f"load_recording: content_type = {content_type}")
        decoded = base64.b64decode(content_string)
        print(f"load_recording: decoded length = {len(decoded)}")

        try:
            data = json.loads(decoded.decode('utf-8'))
            print(f"load_recording: JSON parsed successfully, keys = {list(data.keys())}")
        except UnicodeDecodeError as e:
            print(f"load_recording: UnicodeDecodeError: {e}")
            return None, go.Figure(), "Error: Uploaded file is not a valid JSON recording saved by this app."
        except json.JSONDecodeError as e:
            print(f"load_recording: JSONDecodeError: {e}")
            return None, go.Figure(), "Error: Uploaded file contains invalid JSON."

        base64_audio = data["audio"]
        # Set global for playback
        # This will be passed to recorder.js if we use another clientside callback or similar.
        # But here we are in server side. We need to pass it to JS.
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
            # If soundfile fails, try librosa which can handle WebM, OGG, etc.
            print(f"Soundfile failed: {sf_error}. Trying librosa with timeout...")
            
            # For large recordings, use timeout
            result = load_audio_from_bytes(audio_bytes)
            if result is None:
                return None, go.Figure(), "Error: Recording too long or corrupted. Max length is 10 minutes."

            if not isinstance(result, tuple) or result[0] is None or result[1] is None:
                return None, go.Figure(), "Error: Failed to load recording. File may be corrupted or in unsupported format."

            y, sr = result
            print(f"load_recording: Loaded with librosa, sr={sr}")

        if len(y.shape) > 1:
            y = y.mean(axis=1)
        y = normalize_waveform_for_display(y)

        duration = len(y) / sr
        time = np.linspace(0, duration, num=len(y))
        if len(y) > 10000:
            skip = len(y) // 10000
            time_display = time[::skip]
            y_display = y[::skip]
        else:
            time_display = time
            y_display = y
            
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=time_display, y=y_display, name="Waveform", line=dict(color='blue')))
        
        metronome_times = np.array(data.get("metronome_times", []))
        beat_times = np.array(data.get("beat_times", []))
        bpm = data.get("beats_per_measure", beats_per_measure_slider)
        
        if len(metronome_times) > 0:
            metronome_colors = ['red' if i % bpm == 0 else 'orange' for i in range(len(metronome_times))]
            fig.add_trace(go.Scatter(
                x=metronome_times, 
                y=[max(y_display)*1.1 if i % bpm == 0 else max(y_display)*1.05 for i in range(len(metronome_times))],
                mode='markers',
                name='Metronome',
                marker=dict(color=metronome_colors, symbol='diamond')
            ))
        
        if len(beat_times) > 0:
            fig.add_trace(go.Scatter(
                x=beat_times,
                y=[min(y_display)*1.1] * len(beat_times),
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

        print(f"load_recording: Successfully processed audio, duration={duration:.2f}s, sr={sr}")
        print(f"load_recording: Returning data with {len(metronome_times)} metronome points, {len(beat_times)} beat points")
        
        # Don't show success message (waveform appearing is enough feedback)
        return json.dumps(data), fig, ""
    except Exception as e:
        print(f"Error loading recording: {e}")
        # Don't show error message to user
        return None, go.Figure(), ""

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

