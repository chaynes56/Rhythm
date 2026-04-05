#!/usr/bin/env python3
# Copyright 2026 Christopher T. Haynes. See the project LICENSE file.

from dash import Dash, dcc, html, Input, Output, State, clientside_callback
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import numpy as np
import base64
import io
import soundfile as sf
import librosa
import json
import warnings

# Suppress librosa deprecation warnings to clean up console output
warnings.filterwarnings("ignore", category=FutureWarning, module="librosa")

app = Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])

app.layout = dbc.Container([
    dbc.Row([
        dbc.Col(html.H1("Rhythm App"), className="text-center mb-4")
    ]),
    
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("Recording & Playback"),
                dbc.CardBody([
                    dbc.Button("Start Recording", id="record-btn", color="danger", className="me-2"),
                    dbc.Button("Play Recording", id="play-btn", color="success", className="me-2"),
                    dbc.Button("Save Recording", id="save-btn", color="primary", className="me-2"),
                    dbc.Button("Load Recording", id="load-btn", color="info"),
                    dcc.Checklist(id="is-recording", options=[{"label": "Recording", "value": "recording"}], value=[], style={'display': 'none'}),
                    html.Div(id="status-msg", className="mt-2")
                ])
            ], className="mb-4"),
            
            dbc.Card([
                dbc.CardHeader("Metronome Settings"),
                dbc.CardBody([
                    dbc.Button("Start Metronome", id="metronome-btn", color="primary", className="mb-3 w-100"),
                    dcc.Checklist(id="is-metronome-playing", options=[{"label": "Playing", "value": "playing"}], value=[], style={'display': 'none'}),
                    dbc.Row([
                        dbc.Col([
                            html.Label("Tempo (BPM)"),
                            dcc.Slider(min=40, max=240, step=1, value=120, id="tempo-slider", marks={i: str(i) for i in range(40, 241, 40)}),
                        ], width=6),
                        dbc.Col([
                            html.Label("Beats per Measure"),
                            dcc.Input(type="number", value=4, min=1, max=16, id="beats-per-measure"),
                        ], width=6),
                    ]),
                    dbc.Row([
                        dbc.Col([
                            html.Label("Volumes"),
                            html.Div([
                                html.Label("Metronome", className="small"),
                                dcc.Slider(min=0, max=1, step=0.1, value=0.5, id="metronome-vol"),
                                html.Label("Recording", className="small"),
                                dcc.Slider(min=0, max=1, step=0.1, value=1.0, id="recording-vol"),
                                html.Label("Playback", className="small"),
                                dcc.Slider(min=0, max=1, step=0.1, value=1.0, id="playback-vol"),
                            ])
                        ])
                    ])
                ])
            ])
        ], width=4),
        
        dbc.Col([
            dcc.Graph(id="waveform-graph", config={'scrollZoom': True, 'displayModeBar': True, 'modeBarButtonsToRemove': ['pan2d', 'select2d', 'lasso2d', 'autoScale2d'], 'displaylogo': False}),
        ], width=8)
    ]),
    
    # Hidden components for data storage and communication
    dcc.Store(id="audio-store"),
    dcc.Store(id="metronome-points-store"),
    dcc.Store(id="pulse-points-store"),
    dcc.Input(id="audio-data-store", type="text", style={'display': 'none'}, persistence=False),
    dcc.Input(id="playback-sync", type="text", style={'display': 'none'}),
    dbc.Button("Process", id="audio-process-btn", style={'display': 'none'}, n_clicks=0),
    dcc.Download(id="download-audio"),
    dcc.Upload(id="upload-audio", style={'display': 'none'})
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
    function(n_clicks, volume) {
        return window.dash_clientside.recorder.playAudio(n_clicks, volume);
    }
    """,
    Output("play-btn", "n_clicks"),
    Input("play-btn", "n_clicks"),
    State("playback-vol", "value"),
)

clientside_callback(
    """
    function(n_clicks, playing_status, tempo, beats, volume) {
        const isPlaying = playing_status.length > 0;
        const result = window.dash_clientside.recorder.toggleMetronome(n_clicks, isPlaying, tempo, beats, volume);
        return result ? ['playing'] : [];
    }
    """,
    Output("is-metronome-playing", "value"),
    Input("metronome-btn", "n_clicks"),
    State("is-metronome-playing", "value"),
    State("tempo-slider", "value"),
    State("beats-per-measure", "value"),
    State("metronome-vol", "value"),
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
    Output("audio-store", "data"),
    Output("waveform-graph", "figure"),
    Output("status-msg", "children", allow_duplicate=True),
    Input("audio-process-btn", "n_clicks"),
    State("audio-data-store", "value"),
    State("tempo-slider", "value"),
    State("beats-per-measure", "value"),
    prevent_initial_call=True
)
def process_audio(n_clicks, base64_audio, tempo, beats_per_measure):
    print(f"process_audio: n_clicks={n_clicks}, audio_len={len(base64_audio) if base64_audio else 0}")

    if not base64_audio:
        status_msg = "No audio data to process"
        print(f"status_msg: {status_msg}")
        return None, go.Figure(), status_msg

    try:
        # Extract data from base64
        if ',' in base64_audio:
            header, data = base64_audio.split(',')
        else:
            data = base64_audio
            
        audio_bytes = base64.b64decode(data)
        
        # Load with librosa (handles more formats than soundfile)
        # Try soundfile first for better performance with WAV files
        try:
            with io.BytesIO(audio_bytes) as f:
                y, sr = sf.read(f)
        except Exception as sf_error:
            # If soundfile fails, try librosa which can handle WebM, OGG, etc.
            print(f"Soundfile failed: {sf_error}. Trying librosa...")
            # Save to temporary location for librosa to read
            import tempfile
            with tempfile.NamedTemporaryFile(delete=False, suffix='.webm') as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name
            try:
                y, sr = librosa.load(tmp_path, sr=None)
            finally:
                import os
                os.unlink(tmp_path)

        # If stereo, convert to mono
        if len(y.shape) > 1:
            y = y.mean(axis=1)
            
        # Pulse analysis
        onset_env = librosa.onset.onset_strength(y=y, sr=sr)
        # limit by tempo
        tempo_detected, beats = librosa.beat.beat_track(onset_envelope=onset_env, sr=sr, bpm=tempo)
        beat_times = librosa.frames_to_time(beats, sr=sr)
        
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
            yaxis_title="Amplitude",
            dragmode='pan',
            template='plotly_white'
        )
        
        # Prepare data for saving
        save_data = {
            "audio": base64_audio,
            "tempo": tempo,
            "beats_per_measure": beats_per_measure,
            "metronome_times": metronome_times.tolist(),
            "beat_times": beat_times.tolist()
        }
        
        return json.dumps(save_data), fig, "Recording processed successfully"
    except Exception as e:
        error_msg = f"Error processing audio: {e}"
        print(error_msg)
        status_msg = error_msg
        return None, go.Figure(), status_msg

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
        # Load with librosa (handles more formats than soundfile)
        try:
            with io.BytesIO(audio_bytes) as f:
                y, sr = sf.read(f)
        except Exception as sf_error:
            # If soundfile fails, try librosa which can handle WebM, OGG, etc.
            print(f"Soundfile failed: {sf_error}. Trying librosa...")
            import tempfile
            with tempfile.NamedTemporaryFile(delete=False, suffix='.webm') as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name
            try:
                y, sr = librosa.load(tmp_path, sr=None)
            finally:
                import os
                os.unlink(tmp_path)

        if len(y.shape) > 1:
            y = y.mean(axis=1)
        
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
        
        fig.update_layout(xaxis_title="Time (s)", yaxis_title="Amplitude", dragmode='pan', template='plotly_white')
        
        print(f"load_recording: Successfully processed audio, duration={duration:.2f}s, sr={sr}")
        print(f"load_recording: Returning data with {len(metronome_times)} metronome points, {len(beat_times)} beat points")
        
        return json.dumps(data), fig, "Recording loaded successfully"
    except Exception as e:
        print(f"Error loading recording: {e}")
        return None, go.Figure(), f"Error loading recording: {str(e)}"

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

