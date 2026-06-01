#!python3
# Copyright 2026 Christopher T. Haynes. See the project LICENSE file.

VERSION = "0.1.5"

import base64
import io
import json
import os
from pathlib import Path
from datetime import datetime, timezone
from time import time as time_now

import dash_bootstrap_components as dbc
import numpy as np
import plotly.graph_objects as go
import soundfile as sf
from dash import Dash, ctx, dcc, html, Input, no_update, Output, State, clientside_callback
from dash.exceptions import PreventUpdate
import yaml


def _yaml_str_presenter(dumper, data):
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


yaml.add_representer(str, _yaml_str_presenter)

from exercises import make_exercises, exercises as builtin_exercises, voicing_code

# Session-scoped custom exercises, populated by load_settings.
_custom_exercises: dict = {}
_custom_exercises_text: str = ""

from audio_utils import (
    CALIBRATION_BPM,
    CALIBRATION_BEATS,
    CALIBRATION_FAIL_STD,
    METRONOME_MAX_LOOP_SECONDS,
    WAVEFORM_DISPLAY_SHIFT_SECONDS,
    build_spectrum_figure,
    build_waveform_figure,
    compute_calibration_track,
    compute_metronome_track,
    compute_spectrum,
    detect_onsets_rms,
    load_audio_from_bytes,
    normalize_waveform_for_display,
    serialize_audio_to_base64_wav,
    trim_audio_tail,
)

METRONOME_END_MARGIN_SECONDS = 0.1  # exclude metronome ticks within this many seconds of
# the audio end (avoids counting a beat at the recording cutoff)

# False to hide the onset envelope overlay on the waveform
SHOW_ONSET_ENVELOPE = True

# dict: name -> (green cutoff, orange cutoff) red above orange cutoff in ms of
# mean absolute deviation
TRAINING_LEVEL = dict(Advanced=(7.5, 15), Intermediate=(10, 15), Novice=(15, 30))

SPECTRUM_GRAPH_HEIGHT_PX = 160  # px
SPECTRUM_GRAPH_WIDTH_PX = 500  # px

def is_debug_mode(store_val=None) -> bool:
    """True if any debug source is active: Flask debug flag, DEBUG_MODE env var, or YAML setting."""
    if app.server.debug:
        return True
    if os.environ.get("DEBUG_MODE", "").strip().lower() == "true":
        return True
    if store_val:
        return bool(store_val)
    return False



def compute_exercise_schedule(exercise_patterns, tempo):
    """Return schedule for one full exercise cycle across all patterns.

    Each entry: {time, patternIdx, measureIdx, subIdx, isBeat}
    subIdx is position within the measure string (0 .. bpm*spb-1).
    """
    seconds_per_beat = 60.0 / tempo
    schedule = []
    t = 0.0
    for pi, pat in enumerate(exercise_patterns):
        bpm = pat['beats_per_measure']
        mpp = len(pat['measures'])
        spb = pat['subdivisions_per_beat']
        seconds_per_sub = seconds_per_beat / spb
        for m in range(mpp):
            for b in range(bpm):
                for s in range(spb):
                    sub_idx = b * spb + s
                    global_sub = (m * bpm + b) * spb + s
                    schedule.append({
                        'time': round(t + global_sub * seconds_per_sub, 6),
                        'patternIdx': pi,
                        'measureIdx': m,
                        'subIdx': sub_idx,
                        'isBeat': s == 0,
                    })
        t += bpm * mpp * seconds_per_beat
    return {
        'schedule': schedule,
        'duration': round(t, 6),
        'spb': exercise_patterns[0]['subdivisions_per_beat'],
    }


RECORDER_INLINE_SCRIPT = (Path(__file__).parent / "recorder.js").read_text(
    encoding="utf-8").replace("</script>", r"<\/script>")


DEFAULT_SETTINGS_YAML = """
debug-mode: false
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
exercise-name: ~
custom-exercises: |-
show-intervals: false
show-spectrum: false
"""

settings = yaml.safe_load(DEFAULT_SETTINGS_YAML)



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


def get_all_exercises():
    return _custom_exercises | builtin_exercises


def build_exercise_table(exercise_name: str) -> list:
    all_ex = get_all_exercises()
    if exercise_name not in all_ex:
        return []
    ex = all_ex[exercise_name]

    base ={"textAlign": "center", "padding": "3px 12px",
            "border": "1px solid #ccc", "minWidth": "48px",
            "fontSize": "1.5rem", "fontFamily": "monospace"}

    result = []
    for pat_idx, pat in enumerate(ex["patterns"]):
        sub_line = pat["subdivision_line"]
        header_cells = []
        for col_idx, ch in enumerate(sub_line):
            bg = "#d8d8d8" if col_idx % 2 == 1 else "#f0f0f0"
            header_cells.append(html.Th(
                ch, style={**base, "backgroundColor": bg, "fontWeight": "bold"}
            ))

        rows = [html.Tr(header_cells)]
        for m_idx, measure in enumerate(pat["measures"]):
            cells = []
            for col_idx, ch in enumerate(measure):
                bg = "#e8e8e8" if col_idx % 2 == 1 else "#ffffff"
                cells.append(html.Td(
                    ch,
                    id=f"ex-cell-{pat_idx}-{m_idx}-{col_idx}",
                    style={**base, "backgroundColor": bg},
                ))
            rows.append(html.Tr(cells))

        result.append(html.Table(
            html.Tbody(rows), style={"borderCollapse": "collapse", "marginBottom": "4px"}
        ))
    return result


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
        html.A("Help", href="https://chaynes56.github.io/Rhythm/#/",
               target="_blank",
               style={"fontSize": "1.1rem", "fontWeight": "600"}),
        style={"position": "absolute", "top": "10px", "right": "20px", "zIndex": "1000"}
    ),
    dbc.Row([
        dbc.Col(html.H1("Rhythm Analyzer"), className="text-center mb-4"),
    ], className="position-relative"),

    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("Analysis"),
                dbc.CardBody([
                    dcc.Graph(
                        id="waveform-graph",
                        style={"height": "260px", "visibility": "hidden"},
                        config=dict(scrollZoom=False, displayModeBar=True, doubleClick='reset',  # type: ignore[arg-type]
                                    modeBarButtonsToRemove=["pan2d", "select2d", "lasso2d",
                                                            "autoScale2d"], displaylogo=False),
                        className="mb-0",
                    ),
                    dcc.Graph(
                        id="deviation-graph",
                        style={"height": "260px", "visibility": "hidden"},
                        config={"staticPlot": True},  # type: ignore[arg-type]
                        className="mb-3",
                    ),
                    dbc.Row([
                        dbc.Col([
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
                                dbc.Col([
                                    dbc.Switch(id="show-intervals", label="Show Intervals", value=False, className="mb-1"),
                                    dbc.Switch(id="show-spectrum", label="Show Spectrum", value=False),
                                ], width="auto"),
                            ], className="g-2 mb-2", align="center"),
                            dcc.Markdown(id="analysis-data-block"),
                        ], width="auto"),
                        dbc.Col(
                            dbc.Row([
                                dbc.Col(
                                    dcc.Graph(
                                        id="interval-histogram",
                                        style={"height": "200px", "width": "525px",
                                               "display": "none"},
                                        config={"staticPlot": True},  # type: ignore[arg-type]
                                    ),
                                    width="auto",
                                ),
                                dbc.Col(
                                    dcc.Graph(
                                        id="spectrum-graph",
                                        style={
                                            "height": f"{SPECTRUM_GRAPH_HEIGHT_PX}px",
                                            "width": f"{SPECTRUM_GRAPH_WIDTH_PX}px",
                                            "display": "none",
                                        },
                                        config={"staticPlot": True},  # type: ignore[arg-type]
                                    ),
                                    width="auto",
                                ),
                            ], className="g-3 flex-wrap"),
                            width="auto",
                        ),
                    ], align="start", className="g-3"),
                    dbc.Row([
                        dbc.Col(
                            html.Div(id="subdivision-table-container"),
                            width="auto",
                        ),
                    ], className="mt-2"),
                ]),
            ], className="mb-4"),
        ], width=12)
    ]),

    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("Recordings \u2014 Settings \u2014 Calibration"),
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col([
                            dbc.Button("Warming Up...", id="record-btn",
                                       color="danger", className="me-2", disabled=True),
                            dbc.DropdownMenu(
                                label="Recordings",
                                children=[
                                    dbc.DropdownMenuItem("Play Recording", id="play-btn"),
                                    dbc.DropdownMenuItem("Save Recording", id="save-btn"),
                                    dbc.DropdownMenuItem("Load Recording", id="load-btn"),
                                ],
                                color="primary",
                                className="me-2 d-inline-block",
                            ),
                            dbc.DropdownMenu(
                                label="Settings",
                                children=[
                                    dbc.DropdownMenuItem("Save Settings", id="save-settings-btn"),
                                    dbc.DropdownMenuItem("Load Settings", id="load-settings-btn"),
                                    dbc.DropdownMenuItem("Default Settings", id="default-settings-btn"),
                                ],
                                color="secondary",
                                className="me-2 d-inline-block",
                            ),
                            dbc.Button("Warming Up...", id="calibrate-btn",
                                       color="warning", className="me-1", disabled=True),
                            dcc.Input(
                                id="calibration-value",
                                type="number", min=-999, max=999, step=1,
                                debounce=True, placeholder="ms",
                                style={"width": "65px", "display": "inline-block",
                                       "verticalAlign": "middle"},
                            ),
                            html.Span(
                                id="calibration-confidence",
                                style={"marginLeft": "6px", "fontSize": "0.82em",
                                       "color": "#6c757d", "verticalAlign": "middle"},
                            ),
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
                    html.Div(id="status-msg", className="mt-2 fw-bold"),
                ]),
            ], className="mb-4"),
            dbc.Card([
                dbc.CardHeader("Metronome"),
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col([
                            html.Div([
                                html.Label("Exercise", className="small"),
                                dcc.Dropdown(
                                    id="exercise-select",
                                    options=[{"label": "None", "value": ""}] +
                                            [{"label": k, "value": k} for k in builtin_exercises],
                                    value=settings.get("exercise-name") or "",
                                    clearable=False,
                                    style={"width": "175px"},
                                ),
                            ]),
                            html.Div([
                                html.Label("Exercise Voicing", className="small mt-2"),
                                dcc.Dropdown(
                                    id="exercise-voicing",
                                    options=[{"label": "Synthesized", "value": "synthesized"}],
                                    value="synthesized",
                                    clearable=False,
                                    style={"width": "175px"},
                                ),
                            ], id="exercise-voicing-col", style={"display": "none"}),
                            html.Div([
                                html.Label("Metronome Voicing", className="small mt-2"),
                                dcc.Dropdown(
                                    id="metronome-voicing",
                                    options=[{"label": "Synthesized", "value": "synthesized"}],
                                    value="synthesized",
                                    clearable=False,
                                    style={"width": "175px"},
                                ),
                            ]),
                            html.Div(
                                dbc.Button("Start Metronome", id="metronome-btn",
                                           color="primary"),
                                className="d-grid mt-3",
                            ),
                        ], width="auto",
                           className="align-self-stretch d-flex flex-column justify-content-between"),
                        dbc.Col(
                            html.Div(id="exercise-length-alert"),
                            width="auto",
                        ),
                        dbc.Col([
                            html.Div(
                                id="beats-measures-controls",
                                children=[
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
                                ]
                            ),
                        ], width="auto"),
                        dbc.Col([
                            html.Div(
                                dbc.Switch(
                                    id="play-tones",
                                    label="Play Exercise Tones",
                                    value=False,
                                ),
                                id="play-tones-col",
                                style={"display": "none"},
                            ),
                            html.Div(
                                dbc.Switch(
                                    id="play-only-tones",
                                    label="Play Only Exercise Tones",
                                    value=False,
                                ),
                                id="play-only-tones-col",
                                style={"display": "none"},
                            ),
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
                            html.Div(
                                dbc.Switch(
                                    id="play-subdivisions",
                                    label="Play Subdivisions",
                                    value=False,
                                ),
                                id="play-subdivisions-col",
                                style={"display": "none"},
                            ),
                        ], width="auto"),
                        dbc.Col([
                            html.Label("Beat", id="beat-label", className="small d-block"),
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
    dcc.Store(id="local-settings-store", storage_type="local"),
    dcc.Store(id="startup-applied-store", storage_type="memory", data=False),
    dcc.Store(id="metronome-track-store"),
    dcc.Store(id="calibration-audio-data-store"),
    dcc.Store(id="calibration-offset-store"),
    dcc.Store(id="calibration-track-store", data=compute_calibration_track()),
    dcc.Store(id="calibration-command-store"),
    dcc.Store(id="debug-mode-store", data=False),
    dcc.Store(id="exercise-schedule-store"),
    dcc.Store(id="error-beep-sink"),
    dcc.Store(id="user-context", storage_type="local"),
    dcc.Input(id="warmup-info-store", type="text", value="",
              style={"display": "none"}),
], fluid=True)

# Calibration clientside callbacks

clientside_callback(
    """
    function(trackData) {
        if (trackData && window.recorderControls && window.recorderControls.loadCalibrationTrack) {
            window.recorderControls.loadCalibrationTrack(trackData);
        }
        return window.dash_clientside.no_update;
    }
    """,
    Output("calibration-command-store", "data"),
    Input("calibration-track-store", "data"),
)

clientside_callback(
    """
    function(n_clicks) {
        if (n_clicks && window.recorderControls && window.recorderControls.startCalibration) {
            window.recorderControls.startCalibration();
        }
        return window.dash_clientside.no_update;
    }
    """,
    Output("calibration-command-store", "data", allow_duplicate=True),
    Input("calibrate-btn", "n_clicks"),
    prevent_initial_call=True,
)

clientside_callback(
    """
    function(warmupInfo, userContext) {
        var nu = window.dash_clientside.no_update;
        if (!warmupInfo) return [nu, nu, nu];
        var info;
        try { info = JSON.parse(warmupInfo); } catch(e) { return [nu, nu, nu]; }

        if (userContext && userContext.platform_key === info.platform_key
                && userContext.calibration_offset_ms != null) {
            // Silently restore calibration for this platform
            var conf = (userContext.confidence_ms != null)
                ? ('±' + userContext.confidence_ms + ' ms') : '';
            return [userContext.calibration_offset_ms, userContext.calibration_offset_ms, conf];
        }

        // No stored calibration for this platform -- run auto-calibration after warmup
        if (window.recorderControls && window.recorderControls.startCalibration) {
            window.recorderControls.startCalibration();
        }
        return [nu, nu, nu];
    }
    """,
    Output("calibration-offset-store", "data", allow_duplicate=True),
    Output("calibration-value", "value", allow_duplicate=True),
    Output("calibration-confidence", "children", allow_duplicate=True),
    Input("warmup-info-store", "value"),
    State("user-context", "data"),
    prevent_initial_call=True,
)

clientside_callback(
    """
    function(n_clicks) {
        // Restore calibrate button when audio is ready to process
        const btn = document.getElementById('calibrate-btn');
        if (btn && btn.textContent === 'Calibrating...') {
            btn.textContent = 'Calibrate';
            btn.disabled = false;
            btn.className = btn.className.replace(/\bbtn-secondary\b/g, '').trim() + ' btn-warning';
        }
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
    Output("status-msg", "children", allow_duplicate=True),
    Output("audio-store", "data", allow_duplicate=True),
    Output("waveform-visible-store", "data", allow_duplicate=True),
    Output("waveform-graph", "figure", allow_duplicate=True),
    Output("calibration-value", "value"),
    Output("calibration-confidence", "children"),
    Output("user-context", "data", allow_duplicate=True),
    Input("calibration-audio-data-store", "data"),
    State("debug-mode-store", "data"),
    State("warmup-info-store", "value"),
    prevent_initial_call=True,
)
def process_calibration(base64_audio, debug_mode_store, warmup_info_str):
    if not base64_audio:
        raise PreventUpdate
    nu8 = (no_update,) * 8
    try:
        if ',' in base64_audio:
            _, data = base64_audio.split(',', 1)
        else:
            data = base64_audio
        audio_bytes = base64.b64decode(data)

        try:
            with io.BytesIO(audio_bytes) as f:
                y, sr = sf.read(f)
        except (sf.SoundFileError, OSError, ValueError):
            result = load_audio_from_bytes(audio_bytes)
            if result is None:
                return no_update, "Calibration failed: could not load audio", *nu8[2:]
            y, sr = result

        if len(y.shape) > 1:
            y = y.mean(axis=1)
        y = trim_audio_tail(np.asarray(y, dtype=np.float32), sr)
        y = normalize_waveform_for_display(y)

        beat_times, _, _, _ = detect_onsets_rms(y, sr)
        beat_times = beat_times - WAVEFORM_DISPLAY_SHIFT_SECONDS

        if len(beat_times) < 2:
            return no_update, "Calibration failed: too few beats detected", *nu8[2:]

        seconds_per_beat = 60.0 / CALIBRATION_BPM
        residuals = beat_times % seconds_per_beat
        residuals = np.where(residuals > seconds_per_beat / 2, residuals - seconds_per_beat, residuals)
        phase_offset_s = float(np.median(residuals))
        offset_ms = round(phase_offset_s * 1000)
        std_ms = round(float(np.std(residuals)) * 1000, 1)
        print(f"process_calibration: offset={offset_ms}ms std={std_ms}ms from {len(beat_times)} beats")
        debug = is_debug_mode(debug_mode_store)
        failed = std_ms >= CALIBRATION_FAIL_STD

        if failed:
            fail_str = f"Calibration failure: {offset_ms} +/- {std_ms} ms"
            confidence_display = html.Span(fail_str, style={"color": "#dc3545"})
            msg = fail_str if debug else ""
        else:
            confidence_display = f"±{std_ms} ms" if debug else ""
            msg = f"Calibrated: {offset_ms} ms (std {std_ms} ms)" if debug else ""

        # Build user-context update only on success
        new_context = no_update
        if not failed:
            try:
                if warmup_info_str:
                    info = json.loads(warmup_info_str)
                    new_context = {
                        "platform_key": info.get("platform_key", ""),
                        "calibration_offset_ms": offset_ms,
                        "confidence_ms": std_ms,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
            except (json.JSONDecodeError, AttributeError):
                pass

        if not failed and not debug:
            return offset_ms, msg, no_update, no_update, no_update, offset_ms, confidence_display, new_context

        # Failure or debug: show calibration waveform with beat markers
        duration = len(y) / sr
        bpm = 4
        mpp = CALIBRATION_BEATS // bpm
        spb = 1
        cal_s = phase_offset_s
        metro_display = np.arange(cal_s % seconds_per_beat,
                                  duration - METRONOME_END_MARGIN_SECONDS,
                                  seconds_per_beat)
        metro_times = np.arange(cal_s, duration - METRONOME_END_MARGIN_SECONDS, seconds_per_beat)
        fig = build_waveform_figure(y, sr, metro_display, beat_times, bpm,
                                    None, 512, mpp, spb,
                                    display_offset=cal_s % seconds_per_beat)
        fig.update_layout(uirevision=str(time_now()))
        save_data = {
            "audio": base64_audio,
            "tempo": CALIBRATION_BPM,
            "beats_per_measure": bpm,
            "measures_per_pattern": mpp,
            "calibration_offset_ms": offset_ms,
            "metronome_times": metro_times.tolist(),
            "beat_times": beat_times.tolist(),
            "spectrum_freqs": [],
            "spectrum_psd": [],
            "duration": duration,
        }
        cal_out = no_update if failed else offset_ms
        return cal_out, msg, json.dumps(save_data), True, fig, cal_out, confidence_display, new_context
    except Exception as e:
        print(f"process_calibration error: {e}")
        return no_update, f"Calibration failed: {e}", *nu8[2:]


@app.callback(
    Output("calibration-offset-store", "data", allow_duplicate=True),
    Input("calibration-value", "value"),
    prevent_initial_call=True,
)
def calibration_value_edited(value):
    if value is None:
        raise PreventUpdate
    return float(value)


@app.callback(
    Output("metronome-track-store", "data"),
    Output("status-msg", "children", allow_duplicate=True),
    Input("tempo-slider", "value"),
    Input("beats-per-measure", "value"),
    Input("measures-per-pattern", "value"),
    Input("play-hi-tone", "value"),
    Input("play-only-low-tone", "value"),
    Input("exercise-select", "value"),
    Input("play-subdivisions", "value"),
    Input("play-tones", "value"),
    Input("play-only-tones", "value"),
    prevent_initial_call="initial_duplicate",
)
def update_metronome_track(tempo, beats_per_measure, measures_per_pattern, play_hi, play_only_low,
                           exercise_name, play_subdivisions, play_tones, play_only_tones):
    try:
        t = tempo or 120
        exercise_patterns = None
        if exercise_name:
            all_ex = get_all_exercises()
            if exercise_name in all_ex:
                ex = all_ex[exercise_name]
                total_seconds = ex["total_beats"] * (60.0 / t)
                if total_seconds > METRONOME_MAX_LOOP_SECONDS:
                    return no_update, (
                        f"Exercise too long at {t} BPM "
                        f"({total_seconds:.0f}s; limit {int(METRONOME_MAX_LOOP_SECONDS / 60)} min)."
                    )
                exercise_patterns = ex["patterns"]

        char_tone_map = {ch: v['tone'] for ch, v in voicing_code.items()}
        data_url = compute_metronome_track(
            t,
            beats_per_measure or 4,
            measures_per_pattern or 1,
            bool(play_hi),
            bool(play_only_low),
            exercise_patterns=exercise_patterns,
            play_subdivisions=bool(play_subdivisions),
            play_tones=bool(play_tones),
            char_tone_map=char_tone_map,
            play_only_tones=bool(play_only_tones),
        )
        print(f"update_metronome_track: {beats_per_measure}/{measures_per_pattern} at {t} BPM, exercise={exercise_name!r}")
        return data_url, no_update
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
    function(n_clicks, playing_status, tempo, beats, measures_per_pattern, volume, play_hi_tone, play_only_low_tone, recording_phase) {
        if (!window.recorderControls) {
            console.error("recorder.js not loaded");
            return window.dash_clientside.no_update;
        }
        if (n_clicks) {
            if (recording_phase === "recording" || recording_phase === "delay") {
                window.recorderControls.toggleRecording(
                    n_clicks, recording_phase, tempo, beats, measures_per_pattern,
                    volume, !!play_hi_tone, !!play_only_low_tone
                );
            } else {
                const isPlaying = playing_status.length > 0;
                window.recorderControls.toggleMetronome(
                    n_clicks, isPlaying, tempo, beats, measures_per_pattern, volume,
                    !!play_hi_tone, !!play_only_low_tone
                );
            }
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
    State("recording-phase-store", "data"),
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
    prevent_initial_call=True,
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
    """
    function(waveform_visible) {
        return { visibility: waveform_visible ? 'visible' : 'hidden' };
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
    function(waveform_visible, show_intervals) {
        const show = waveform_visible && show_intervals;
        return { height: '200px', width: '525px', display: show ? 'block' : 'none' };
    }
    """,
    Output("interval-histogram", "style"),
    Input("waveform-visible-store", "data"),
    Input("show-intervals", "value"),
)

clientside_callback(
    f"""
    function(waveform_visible, show_spectrum) {{
        const show = waveform_visible && show_spectrum;
        return {{ height: '{SPECTRUM_GRAPH_HEIGHT_PX}px', width: '{SPECTRUM_GRAPH_WIDTH_PX}px', display: show ? 'block' : 'none' }};
    }}
    """,
    Output("spectrum-graph", "style"),
    Input("waveform-visible-store", "data"),
    Input("show-spectrum", "value"),
)


def build_exercise_voicing_key(exercise_name: str) -> str:
    all_ex = get_all_exercises()
    if exercise_name not in all_ex:
        return "Beat"
    ex = all_ex[exercise_name]
    chars_used = set()
    for pat in ex["patterns"]:
        for measure in pat["measures"]:
            chars_used.update(measure)
    items = [f"{ch} = {voicing_code[ch]['name']}" for ch in voicing_code if ch in chars_used]
    return "Voicing key: " + ", ".join(items)


@app.callback(
    Output("beat-indicator-container", "children"),
    Output("beat-label", "children"),
    Input("beats-per-measure", "value"),
    Input("measures-per-pattern", "value"),
    Input("exercise-select", "value"),
)
def update_beat_indicator_boxes(beats_per_measure, measures_per_pattern, exercise_name):
    if exercise_name:
        return (build_exercise_table(exercise_name),
                (  # "Use non-dominant hand in gray columns\n" +
                 build_exercise_voicing_key(exercise_name)))
    return build_beat_indicator_boxes(beats_per_measure, measures_per_pattern), "Beat"



@app.callback(
    Output("beats-measures-controls", "style"),
    Output("play-tones-col", "style"),
    Output("play-only-tones-col", "style"),
    Output("play-subdivisions-col", "style"),
    Output("exercise-voicing-col", "style"),
    Output("exercise-length-alert", "children"),
    Output("beats-per-measure", "value", allow_duplicate=True),
    Output("measures-per-pattern", "value", allow_duplicate=True),
    Output("subdivisions-per-beat", "value", allow_duplicate=True),
    Input("exercise-select", "value"),
    Input("tempo-slider", "value"),
    prevent_initial_call=True,
)
def update_exercise_ui(exercise_name, tempo):
    hidden = {"display": "none"}
    show = {"display": "block"}
    if not exercise_name:
        return show, hidden, hidden, show, hidden, None, no_update, no_update, no_update

    all_ex = get_all_exercises()
    if exercise_name not in all_ex:
        return show, hidden, hidden, show, hidden, None, no_update, no_update, no_update
    ex = all_ex[exercise_name]

    alert = None
    if tempo:
        duration = ex["total_beats"] * (60.0 / tempo)
        if duration > METRONOME_MAX_LOOP_SECONDS:
            alert = dbc.Alert(
                f"Exercise ({duration:.0f}s at {tempo} BPM) exceeds 5-min limit.",
                color="warning", dismissable=True, className="mb-0 py-1 small",
            )

    show = {"display": "block"}
    if ctx.triggered_id == "exercise-select":
        pat = ex["patterns"][0]
        return (hidden, show, show, show, show, alert,
                pat["beats_per_measure"], len(pat["measures"]), pat["subdivisions_per_beat"])
    return hidden, show, show, show, show, alert, no_update, no_update, no_update


@app.callback(
    Output("play-tones", "value"),
    Output("play-only-tones", "value"),
    Input("play-only-tones", "value"),
    Input("play-tones", "value"),
    prevent_initial_call=True,
)
def enforce_tone_toggle_exclusion(play_only_tones, play_tones):
    triggered = ctx.triggered_id
    if triggered == "play-only-tones" and play_only_tones:
        return False, no_update
    if triggered == "play-tones" and play_tones:
        return no_update, False
    return no_update, no_update


@app.callback(
    Output("exercise-schedule-store", "data"),
    Input("exercise-select", "value"),
    Input("tempo-slider", "value"),
)
def update_exercise_schedule(exercise_name, tempo):
    if not exercise_name:
        return None
    all_ex = get_all_exercises()
    if exercise_name not in all_ex:
        return None
    ex = all_ex[exercise_name]
    return compute_exercise_schedule(ex["patterns"], tempo or 120)


clientside_callback(
    """
    function(scheduleData) {
        if (window.recorderControls && window.recorderControls.setExerciseSchedule) {
            window.recorderControls.setExerciseSchedule(scheduleData);
        }
        return window.dash_clientside.no_update;
    }
    """,
    Output("metronome-command-store", "data", allow_duplicate=True),
    Input("exercise-schedule-store", "data"),
    prevent_initial_call=True,
)


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


clientside_callback(
    """
    function(msg) {
        if (!msg || typeof msg !== 'string') return window.dash_clientside.no_update;
        const lower = msg.toLowerCase();
        const isError = lower.includes('error') || lower.includes('invalid') ||
                        lower.includes('failed') || lower.includes('syntax');
        if (isError) {
            try {
                const ac = new (window.AudioContext || window.webkitAudioContext)();
                const osc = ac.createOscillator();
                const gain = ac.createGain();
                osc.connect(gain);
                gain.connect(ac.destination);
                osc.type = 'sine';
                osc.frequency.value = 220;
                gain.gain.setValueAtTime(0.5, ac.currentTime);
                gain.gain.linearRampToValueAtTime(0, ac.currentTime + 0.7);
                osc.start(ac.currentTime);
                osc.stop(ac.currentTime + 0.7);
            } catch(e) {}
        }
        return window.dash_clientside.no_update;
    }
    """,
    Output("error-beep-sink", "data"),
    Input("status-msg", "children"),
    prevent_initial_call=True,
)


clientside_callback(
    """
    function(warmupInfo) {
        const done = warmupInfo && warmupInfo.length > 0;
        return [
            !done,
            done ? 'Start Recording' : 'Warming Up...',
            !done,
            done ? 'Calibrate' : 'Warming Up...'
        ];
    }
    """,
    Output("record-btn", "disabled"),
    Output("record-btn", "children", allow_duplicate=True),
    Output("calibrate-btn", "disabled", allow_duplicate=True),
    Output("calibrate-btn", "children", allow_duplicate=True),
    Input("warmup-info-store", "value"),
    prevent_initial_call='initial_duplicate',
)


@app.callback(
    Output("record-btn", "children", allow_duplicate=True),
    Output("record-btn", "color"),
    Output("metronome-btn", "children"),
    Output("metronome-btn", "disabled"),
    Input("recording-phase-store", "data"),
    State("is-metronome-playing", "value"),
    prevent_initial_call=True,
)
def update_record_button(recording_phase, metro_playing):
    if recording_phase == "delay":
        return "Counting in...", "warning", "Stop Recording", False
    if recording_phase == "recording":
        return "Stop Recording", "secondary", "Stop Recording", False
    metro_label = "Stop Metronome" if metro_playing else "Start Metronome"
    return "Start Recording", "danger", metro_label, False


@app.callback(
    Output("play-btn", "children"),
    Input("is-playing", "value")
)
def update_play_button(playing_value):
    if "playing" in playing_value:
        return "Stop Playback"
    return "Play Recording"


@app.callback(
    Output("spectrum-graph", "figure"),
    Input("audio-store", "data"),
    Input("waveform-graph", "relayoutData"),
    prevent_initial_call=True,
)
def update_spectrum(audio_json, relayout_data):
    if not audio_json:
        return go.Figure()
    try:
        data = json.loads(audio_json)
        if relayout_data and ctx.triggered_id != "audio-store":
            t0, t1 = None, None
            if "xaxis.range[0]" in relayout_data:
                t0, t1 = float(relayout_data["xaxis.range[0]"]), float(relayout_data["xaxis.range[1]"])
            elif "xaxis.range" in relayout_data:
                t0, t1 = relayout_data["xaxis.range"]
            if t0 is not None:
                audio_b64 = data.get("audio", "")
                if audio_b64:
                    audio_data = audio_b64.split(",", 1)[-1] if "," in audio_b64 else audio_b64
                    with io.BytesIO(base64.b64decode(audio_data)) as f:
                        y, sr = sf.read(f)
                    if len(y.shape) > 1:
                        y = y.mean(axis=1)
                    i0 = max(0, int(t0 * sr))
                    i1 = min(len(y), int(t1 * sr))
                    y_slice = y[i0:i1]
                    freqs, psd = compute_spectrum(y_slice, sr)
                    if len(freqs) > 0:
                        return build_spectrum_figure(freqs, psd)
        freqs = np.array(data.get("spectrum_freqs", []))
        psd = np.array(data.get("spectrum_psd", []))
        if len(freqs) == 0:
            return go.Figure()
        return build_spectrum_figure(freqs, psd)
    except Exception as e:
        print(f"update_spectrum: {e}")
        return go.Figure()


@app.callback(
    Output("status-msg", "children", allow_duplicate=True),
    Input("audio-data-store", "data"),
    prevent_initial_call=True,
)
def show_analyzing_message(data):
    if not data:
        raise PreventUpdate
    return "Analyzing\u2026"


@app.callback(
    Output("analysis-data-block", "children"),
    Output("status-msg", "children", allow_duplicate=True),
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
        cal_s = data.get("calibration_offset_ms", 0) / 1000.0
        if pulse_count == 0:
            return f"No pulses detected in **{beat_count}** beats{window_note}.", ""
        deviations = np.array([((t - cal_s - dt / 2) % dt - dt / 2) * 1000 for t in beat_times])
        mean = deviations.mean()
        std = deviations.std()
        maximum = deviations.max()
        minimum = deviations.min()
        median = np.median(deviations)
        markdown_text = f"""**{pulse_count}** pulses detected in **{beat_count}**
        beats{window_note}, which is **{(pulse_count / beat_count):.2f}** pulses per
        beat. The following statistics reflect time deviations from the start of
        each **{round(dt * 1000)}** ms subdivision: **{round(mean)}** mean,
        **{round(median)}** median, **{round(std)}** std dev, **{round(minimum)}** min, 
        **{round(maximum)}** max (ms)"""
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
        cal_s = data.get("calibration_offset_ms", 0) / 1000.0
        warn_ms, alert_ms = TRAINING_LEVEL.get(training_level, TRAINING_LEVEL["Novice"])

        exercise_name = data.get("exercise_name") or ""
        all_ex = get_all_exercises()

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

        if exercise_name and exercise_name in all_ex:
            ex = all_ex[exercise_name]
            # Exercise mode: stacked tables (one per pattern) matching metronome layout.
            # Header uses subdivision_line chars; cells show "median:n".
            seconds_per_beat = 60.0 / tempo
            patterns = ex["patterns"]

            pat_starts = []
            t_acc = 0.0
            for pat in patterns:
                pat_starts.append(t_acc)
                t_acc += pat["beats_per_measure"] * len(pat["measures"]) * seconds_per_beat
            cycle_duration = t_acc

            # cell_devs_by_pat[pi][m_idx][sub_pos] = list of deviations (ms)
            cell_devs_by_pat = []
            for pat in patterns:
                pat_mpp_i = len(pat["measures"])
                pat_spm_i = pat["beats_per_measure"] * pat["subdivisions_per_beat"]
                cell_devs_by_pat.append(
                    [[[] for _ in range(pat_spm_i)] for _ in range(pat_mpp_i)])

            for t in beat_times:
                pos = (t - cal_s) % cycle_duration
                for pi, pat in enumerate(patterns):
                    pat_bpm_i = pat["beats_per_measure"]
                    pat_spb_i = pat["subdivisions_per_beat"]
                    pat_mpp_i = len(pat["measures"])
                    pat_spm_i = pat_bpm_i * pat_spb_i
                    pat_dt_i = seconds_per_beat / pat_spb_i
                    pat_dur_i = pat_bpm_i * pat_mpp_i * seconds_per_beat
                    if pat_starts[pi] <= pos < pat_starts[pi] + pat_dur_i:
                        local_t = pos - pat_starts[pi]
                        nearest_n = int(round(local_t / pat_dt_i))
                        total_subs = pat_bpm_i * pat_mpp_i * pat_spb_i
                        nearest_n = max(0, min(nearest_n, total_subs - 1))
                        m_idx = nearest_n // pat_spm_i
                        sub_pos = nearest_n % pat_spm_i
                        dev_ms = (local_t - nearest_n * pat_dt_i) * 1000
                        cell_devs_by_pat[pi][m_idx][sub_pos].append(dev_ms)
                        break

            def cell_bg_ex(d, cell_pat, cell_m_idx, cell_sub_pos):
                if not d:
                    return "#e8e8e8"
                row_idx = cell_m_idx % len(cell_pat["measures"])
                if cell_sub_pos < len(cell_pat["measures"][row_idx]) and cell_pat["measures"][row_idx][cell_sub_pos] == '.':
                    return "#c0392b"
                med = abs(float(np.median(d)))
                if med < warn_ms:
                    return "#c8e6c9"
                if med < alert_ms:
                    return "#ffe0b2"
                return "#ffcdd2"

            def cell_text_ex(d):
                if not d:
                    return "\u2014"
                med = int(round(float(np.median(d))))
                return f"{med}:{len(d)}"

            base_cell_ex = {"textAlign": "center", "padding": "3px 6px",
                            "border": "1px solid #ccc", "minWidth": "52px",
                            "fontSize": "0.75rem", "fontFamily": "monospace"}
            base_th_ex = {"textAlign": "center", "padding": "2px 4px",
                          "border": "1px solid #ccc", "minWidth": "52px",
                          "fontSize": "0.75rem", "fontFamily": "monospace",
                          "borderBottom": "1px solid #aaa"}
            label_style = {"padding": "2px 5px", "fontSize": "0.75rem",
                           "fontWeight": "600", "borderRight": "1px solid #bbb",
                           "whiteSpace": "nowrap", "background": "#f5f5f5",
                           "minWidth": "30px"}

            tables = []
            for pi, pat in enumerate(patterns):
                sub_line = pat["subdivision_line"]
                pat_mpp_i = len(pat["measures"])
                pat_spm_i = pat["beats_per_measure"] * pat["subdivisions_per_beat"]

                header_cells = [html.Th("", style={**base_th_ex,
                                                   "background": "#f5f5f5",
                                                   "minWidth": "30px",
                                                   "border": "none"})]
                for col_idx, ch in enumerate(sub_line):
                    bg = "#d8d8d8" if col_idx % 2 == 1 else "#f0f0f0"
                    header_cells.append(html.Th(
                        ch, style={**base_th_ex, "backgroundColor": bg,
                                   "fontWeight": "bold"}
                    ))
                rows = [html.Tr(header_cells)]

                for m_idx in range(pat_mpp_i):
                    row_cells = [html.Td(f"M{m_idx + 1}", style=label_style)]
                    for sub_pos in range(pat_spm_i):
                        devs = cell_devs_by_pat[pi][m_idx][sub_pos]
                        bg = cell_bg_ex(devs, pat, m_idx, sub_pos)
                        txt = cell_text_ex(devs)
                        cell_style = {**base_cell_ex, "backgroundColor": bg}
                        if bg == "#c0392b":
                            cell_style["color"] = "#ffffff"
                        row_cells.append(html.Td(txt, style=cell_style))
                    rows.append(html.Tr(row_cells))

                tables.append(html.Table(
                    html.Tbody(rows),
                    style={"borderCollapse": "collapse", "border": "1px solid #aaa",
                           "marginBottom": "8px"},
                ))

            title = html.P(
                "Median pulse deviation relative to beat : number of pulses",
                style={"fontSize": "0.75rem", "marginBottom": "4px", "color": "#444",
                       "fontStyle": "italic"}
            )
            return html.Div([title] + tables, style={"overflowX": "auto"})

        # Free metronome mode: single table with beat/sub header rows and mean deviation.
        dt = 60.0 / tempo / spb
        deviations_ms = np.array(
            [((t - cal_s - dt / 2) % dt - dt / 2) * 1000 for t in beat_times])

        subs_per_measure = bpm * spb
        cell_devs = [[[[] for _ in range(spb)] for _ in range(bpm)] for _ in range(mpp)]

        for t, dev in zip(beat_times, deviations_ms):
            nearest_n = int(round((t - cal_s) / dt))
            if nearest_n < 0:
                continue
            measure_idx = (nearest_n // subs_per_measure) % mpp
            pos_in_measure = nearest_n % subs_per_measure
            beat_idx = pos_in_measure // spb
            sub_idx = pos_in_measure % spb
            if 0 <= measure_idx < mpp and 0 <= beat_idx < bpm and 0 <= sub_idx < spb:
                cell_devs[measure_idx][beat_idx][sub_idx].append(dev)

        def cell_bg(deviations, _m_idx, _b_idx, _s_idx):
            if not deviations:
                return "#e8e8e8"
            if abs(float(np.mean(deviations))) < warn_ms:
                return "#c8e6c9"
            if abs(float(np.mean(deviations))) < alert_ms:
                return "#ffe0b2"
            return "#ffcdd2"

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
            return "2px solid #666" if beat_index < bpm - 1 else "1px solid #bbb"

        header_cells = [html.Th("", style={**base_th, "minWidth": "30px"})]
        for b in range(bpm):
            header_cells.append(html.Th(
                f"B{b + 1}", colSpan=spb,
                style={**base_th, "borderRight": beat_border(b)},
            ))

        rows = [html.Tr(header_cells)]

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
                    bg = cell_bg(devs, m, b, s)
                    cell_style = {**base_cell,
                                  "backgroundColor": bg,
                                  "borderRight": beat_border(b) if is_last else "1px solid #ddd",
                                  "borderBottom": "1px solid #ddd"}
                    if bg == "#c0392b":
                        cell_style["color"] = "#ffffff"
                    row_cells.append(html.Td(cell_text(devs), style=cell_style))
            rows.append(html.Tr(row_cells))

        table = html.Table(
            html.Tbody(rows),
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
            xaxis_title="Intervals between pulses (ms)",
            yaxis_title="Count",
            template="plotly_white",
            margin=dict(l=50, r=20, t=20, b=40),
        )
        fig.update_xaxes(tickmode="auto", nticks=10, tickformat=".0f")
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
        cal_s = data.get("calibration_offset_ms", 0) / 1000.0
        seconds_per_beat = 60.0 / tempo
        display_offset = cal_s % seconds_per_beat
        shift = WAVEFORM_DISPLAY_SHIFT_SECONDS + display_offset
        x_times = beat_times - display_offset  # calibration-corrected x positions

        deviations = np.array(
            [((t - cal_s - dt / 2) % dt - dt / 2) * 1000 for t in beat_times]
        )
        abs_dev = np.abs(deviations)

        dot_colors = np.where(
            abs_dev < warn_ms, 'green',
            np.where(abs_dev < alert_ms, 'orange', 'red')
        )

        # Inter-pulse interval (IPI) deviations — immune to calibration errors.
        # For pulse i, compute: interval from pulse i-1 → i, find nearest subdivision
        # count, y = deviation from that expected interval.
        if len(beat_times) > 1:
            ipis = np.diff(beat_times)
            n_subs = np.round(ipis / dt)
            ipi_dev_ms = (ipis - n_subs * dt) * 1000
            ipi_x = x_times[1:]
        else:
            ipi_dev_ms = np.array([])
            ipi_x = np.array([])

        fig = go.Figure()
        # Base dots at y=0, colored by absolute deviation (no legend entry)
        fig.add_trace(go.Scatter(
            x=x_times, y=[0.0] * len(x_times),
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
        # Invisible header trace so legend shows "Rel. to metronome" above the color bars.
        # legendgrouptitle_text is unreliable in the bundled Plotly.js for single-trace groups,
        # so the same invisible-header approach used by the IPI group is applied here.
        fig.add_trace(go.Scatter(
            x=[None], y=[None],
            mode='markers',
            name='Rel. to metronome',
            marker=dict(size=0, opacity=0),
            legendgroup='metronome',
            showlegend=True,
        ))
        for i, (color, label, mask) in enumerate(categories):
            x_values, y_values = [], []
            for xt, d in zip(x_times[mask], deviations[mask]):
                x_values += [xt, xt, None]
                y_values += [0.0, d, None]
            fig.add_trace(go.Scatter(
                x=x_values, y=y_values,
                mode='lines', name=label,
                line=dict(color=color, width=2),
                legendgroup='metronome',
            ))

        # IPI legend: invisible header trace puts text above the blue dot.
        fig.add_trace(go.Scatter(
            x=[None], y=[None],
            mode='markers',
            name='Rel. to prev. pulse',
            marker=dict(size=0, opacity=0),
            legendgroup='ipi',
            showlegend=True,
        ))
        # IPI deviation dots — larger, royalblue, drawn on top
        fig.add_trace(go.Scatter(
            x=ipi_x, y=ipi_dev_ms.tolist() if len(ipi_dev_ms) else [],
            mode='markers',
            name=' ',
            marker=dict(color='royalblue', size=10, symbol='circle'),
            legendgroup='ipi',
        ))

        # Compute anchor x_max to match the waveform's actual rightmost data point.
        # The waveform draws metronome markers (and subdivision markers beyond mt[-1]),
        # so it autoranges wider than duration-shift. The anchor must reach the same
        # extent so that zoom-reset autorange aligns both graphs.
        mt_all = np.array(data.get("metronome_times", [])) - display_offset
        x_anchor_max = duration - shift if duration else 0.0
        if len(mt_all) > 0:
            x_anchor_max = max(x_anchor_max, float(mt_all[-1]))
            if len(mt_all) > 1 and spb > 1:
                last_beat_dur = float(mt_all[-1] - mt_all[-2])
                x_anchor_max = max(x_anchor_max,
                                   float(mt_all[-1]) + (spb - 1) / spb * last_beat_dur)

        # Initial display range matches the waveform's initial fixed range exactly.
        full_x_range = (
            [-shift, duration - shift]
            if duration else None
        )
        # Anchor range extends to the waveform's full data extent (for autorange alignment).
        anchor_range = [-shift, x_anchor_max] if duration else None

        # Invisible anchor traces so autorange covers the waveform's full data extent.
        if anchor_range:
            fig.add_trace(go.Scatter(
                x=anchor_range, y=[0.0, 0.0],
                mode='markers',
                marker=dict(size=0, opacity=0),
                showlegend=False,
                hoverinfo='skip',
            ))

        # Sync x range with waveform zoom.
        # On double-click reset, Plotly fires xaxis.autorange in relayoutData.
        # Replicate the waveform's 5% padding explicitly so both graphs use identical ranges.
        x_range = full_x_range
        if relayout_data and ctx.triggered_id != "audio-store":
            if "xaxis.autorange" in relayout_data:
                if anchor_range:
                    lo, hi = anchor_range
                    pad = 0.05 * (hi - lo)
                    x_range = [lo - pad, hi + pad]
                else:
                    x_range = full_x_range
            elif "xaxis.range[0]" in relayout_data:
                x_range = [relayout_data["xaxis.range[0]"],
                           relayout_data["xaxis.range[1]"]]
            elif "xaxis.range" in relayout_data:
                x_range = relayout_data["xaxis.range"]

        all_abs = np.concatenate([np.abs(deviations),
                                   np.abs(ipi_dev_ms) if len(ipi_dev_ms) else np.array([])])
        y_bound = max(float(np.max(all_abs)) if len(all_abs) else 0.0, 10.0)

        fig.add_hline(y=0, line_width=1, line_color="gray", line_dash="dot")
        fig.update_layout(
            xaxis_title="Time (s)",
            yaxis_title="Early \u2014 milliseconds \u2014 Late",
            yaxis_range=[-y_bound, y_bound],
            yaxis_fixedrange=True,
            dragmode=False,
            template="plotly_white",
            margin=dict(l=60, r=230, t=20, b=40),
            legend=dict(traceorder='normal', groupclick='toggleitem',
                        grouptitlefont=dict(size=12)),
        )
        if x_range is not None:
            fig.update_xaxes(range=x_range, autorange=False)
        fig.update_yaxes(automargin=False)
        return fig
    except Exception as e:
        print(f"update_deviation_graph: {e}")
        return go.Figure()


@app.callback(
    Output("audio-store", "data"),
    Output("waveform-visible-store", "data"),
    Output("waveform-graph", "figure"),
    Output("status-msg", "children"),
    Input("audio-data-store", "data"),
    State("tempo-slider", "value"),
    State("beats-per-measure", "value"),
    State("measures-per-pattern", "value"),
    State("subdivisions-per-beat", "value"),
    State("calibration-offset-store", "data"),
    State("exercise-select", "value"),
    prevent_initial_call=True
)
def process_audio(base64_audio, tempo, beats_per_measure, measures_per_pattern,
                  subdivisions_per_beat, calibration_offset_ms, exercise_name):
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
        try:
            spec_freqs, spec_psd = compute_spectrum(y, sr)
        except Exception as spec_err:
            print(f"process_audio: spectrum failed: {spec_err}")
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
        seconds_per_beat = 60.0 / (tempo or 120)
        cal_s = (calibration_offset_ms or 0) / 1000.0
        metronome_times = np.arange(cal_s, duration - METRONOME_END_MARGIN_SECONDS,
                                    seconds_per_beat)
        metronome_times_display = np.arange(cal_s % seconds_per_beat,
                                            duration - METRONOME_END_MARGIN_SECONDS,
                                            seconds_per_beat)
        print(f"process_audio: calibration_offset={calibration_offset_ms}ms, cal_s={cal_s:.4f}s")

        fig = build_waveform_figure(y, sr, metronome_times_display, beat_times,
                                    beats_per_measure,
                                    onset_env_norm if SHOW_ONSET_ENVELOPE else None,
                                    hop_length,
                                    measures_per_pattern,
                                    subdivisions_per_beat,
                                    display_offset=cal_s % seconds_per_beat)
        fig.update_layout(uirevision=str(time_now()))

        # Prepare data for saving
        save_data = {
            "audio": trimmed_audio_base64,
            "tempo": tempo,
            "beats_per_measure": beats_per_measure,
            "measures_per_pattern": measures_per_pattern,
            "calibration_offset_ms": calibration_offset_ms or 0,
            "metronome_times": metronome_times.tolist(),
            "beat_times": beat_times.tolist(),
            "spectrum_freqs": spec_freqs.tolist(),
            "spectrum_psd": spec_psd.tolist(),
            "duration": duration,
            "exercise_name": exercise_name or None,
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
    Output("status-msg", "children", allow_duplicate=True),
    Output("exercise-select", "value", allow_duplicate=True),
    Input("upload-audio", "contents"),
    State("beats-per-measure", "value"),
    State("subdivisions-per-beat", "value"),
    State("calibration-offset-store", "data"),
    prevent_initial_call=True
)
def load_recording(contents, beats_per_measure_slider, subdivisions_per_beat,
                   _calibration_offset_ms):
    if not contents:
        return None, False, go.Figure(), "", no_update

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
            return None, False, go.Figure(), "Error: Uploaded file is not a valid JSON recording saved by this app.", no_update
        except json.JSONDecodeError as e:
            print(f"load_recording: JSONDecodeError: {e}")
            return None, False, go.Figure(), "Error: Uploaded file contains invalid JSON.", no_update

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
                return None, False, go.Figure(), "Error: Recording too long or corrupted. Max length is 10 minutes.", no_update

            if not isinstance(result, tuple) or result[0] is None or result[1] is None:
                return None, False, go.Figure(), "Error: Failed to load recording. File may be corrupted or in unsupported format.", no_update

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

        _, _, onset_env_norm, hop_length = detect_onsets_rms(y, sr)

        y = normalize_waveform_for_display(y)

        duration = len(y) / sr

        tempo_saved = data.get("tempo", 120)
        seconds_per_beat_saved = 60.0 / (tempo_saved or 120)
        beat_times = np.array(data.get("beat_times", []))
        bpm = data.get("beats_per_measure", beats_per_measure_slider)
        mpp = data.get("measures_per_pattern", 1)
        cal_s_saved = data.get("calibration_offset_ms", 0) / 1000.0
        metronome_times_display = np.arange(cal_s_saved % seconds_per_beat_saved,
                                            duration - METRONOME_END_MARGIN_SECONDS,
                                            seconds_per_beat_saved)
        fig = build_waveform_figure(y, sr, metronome_times_display, beat_times, bpm,
                                    onset_env_norm if SHOW_ONSET_ENVELOPE else None,
                                    hop_length,
                                    measures_per_pattern=mpp,
                                    subdivisions_per_beat=subdivisions_per_beat,
                                    display_offset=cal_s_saved % seconds_per_beat_saved)

        print(
            f"load_recording: Successfully processed audio, duration={duration:.2f}s, sr={sr}")
        print(
            f"load_recording: Returning data with {len(metronome_times_display)} metronome points, {len(beat_times)} beat points")

        data["duration"] = duration
        exercise_name = data.get("exercise_name") or ""
        # Don't show a success message (waveform appearing is enough feedback)
        return json.dumps(data), True, fig, "", exercise_name
    except Exception as e:
        print(f"Error loading recording: {e}")
        return None, False, go.Figure(), "", no_update


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
    State("exercise-select", "value"),
    State("show-intervals", "value"),
    State("show-spectrum", "value"),
    prevent_initial_call=True,
)
def save_settings(_n_clicks, training_level, subdivisions, rec_vol, play_vol,
                  measures, beats, play_hi, play_only_low, tempo, metro_vol,
                  exercise_name, show_intervals, show_spectrum):
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
        "debug-mode": False,  # always saved as false; enable via env var or Flask debug flag
        "exercise-name": exercise_name or None,
        "custom-exercises": _custom_exercises_text,
        "show-intervals": bool(show_intervals),
        "show-spectrum": bool(show_spectrum),
    }
    buf = io.StringIO()
    yaml.dump(current, buf, default_flow_style=False, sort_keys=False)
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
    Output("debug-mode-store", "data", allow_duplicate=True),
    Output("exercise-select", "value"),
    Output("exercise-select", "options", allow_duplicate=True),
    Output("show-intervals", "value", allow_duplicate=True),
    Output("show-spectrum", "value", allow_duplicate=True),
    Input("settings-raw-store", "data"),
    prevent_initial_call=True,
)
def load_settings(data):
    if data is None:
        raise PreventUpdate
    no_change = (no_update,) * 16  # 10 settings + status-msg + debug-mode-store + exercise-select + options + 2 toggles
    try:
        text = data["content"]
        try:
            loaded = yaml.safe_load(text)
        except yaml.YAMLError as ye:
            mark = getattr(ye, "problem_mark", None)
            line_num = getattr(mark, "line", None)
            loc = f" at line {line_num}" if line_num is not None else ""
            prob = getattr(ye, "problem", str(ye))
            err = [no_update] * 16
            err[10] = f"Invalid YAML syntax{loc}: {prob}"
            return tuple(err)
        if not isinstance(loaded, dict):
            raise ValueError("Settings file did not contain a YAML mapping")
        training_level_val = loaded.get("training-level", settings["training-level"])
        print(f"load_settings: loaded keys = {list(loaded.keys())}, training-level = {training_level_val!r}")

        bad_keys: list[str] = []

        def safe_num(key: str, default):
            val = loaded.get(key, default)
            try:
                return type(default)(val)
            except (TypeError, ValueError):
                bad_keys.append(key)
                return default

        global _custom_exercises, _custom_exercises_text
        custom_text = loaded.get("custom-exercises", "") or ""
        error_parts: list[str] = []
        if custom_text.strip():
            try:
                parsed = make_exercises(custom_text)
                _custom_exercises = parsed
                _custom_exercises_text = custom_text
            except (ValueError, IndexError) as e:
                error_parts.append(f"Custom exercises parse error: {e}")
        else:
            _custom_exercises = {}
            _custom_exercises_text = ""
        new_options = (
            [{"label": "None", "value": ""}]
            + [{"label": k, "value": k} for k in get_all_exercises()]
        )

        subdiv   = safe_num("subdivisions-per-beat", settings["subdivisions-per-beat"])
        rec_vol  = safe_num("recording-vol",         settings["recording-vol"])
        play_vol = safe_num("playback-vol",           settings["playback-vol"])
        mpp      = safe_num("measures-per-pattern",  settings["measures-per-pattern"])
        bpm      = safe_num("beats-per-measure",      settings["beats-per-measure"])
        tempo    = safe_num("tempo-slider",           settings["tempo-slider"])
        metro_vol = safe_num("metronome-vol",         settings["metronome-vol"])

        if bad_keys:
            error_parts.append("Invalid setting for: " + ", ".join(bad_keys))
        status_msg = "; ".join(error_parts)

        return (
            training_level_val,
            subdiv, rec_vol, play_vol, mpp, bpm,
            loaded.get("play-hi-tone",      settings["play-hi-tone"]),
            loaded.get("play-only-low-tone", settings["play-only-low-tone"]),
            tempo, metro_vol,
            status_msg,
            bool(loaded.get("debug-mode", False)),
            loaded.get("exercise-name") or "",
            new_options,
            bool(loaded.get("show-intervals", False)),
            bool(loaded.get("show-spectrum", False)),
        )
    except Exception as e:
        print(f"load_settings error: {e}")
        return no_change


# Auto-save every settings change to localStorage.
clientside_callback(
    """
    function(trainingLevel, subdivisions, recVol, playVol, measures, beats,
             playHi, playOnlyLow, tempo, metroVol, exerciseName,
             showIntervals, showSpectrum) {
        return {
            'training-level': trainingLevel,
            'subdivisions-per-beat': subdivisions,
            'recording-vol': recVol,
            'playback-vol': playVol,
            'measures-per-pattern': measures,
            'beats-per-measure': beats,
            'play-hi-tone': playHi,
            'play-only-low-tone': playOnlyLow,
            'tempo-slider': tempo,
            'metronome-vol': metroVol,
            'exercise-name': exerciseName || null,
            'show-intervals': showIntervals,
            'show-spectrum': showSpectrum,
        };
    }
    """,
    Output("local-settings-store", "data"),
    Input("training-level", "value"),
    Input("subdivisions-per-beat", "value"),
    Input("recording-vol", "value"),
    Input("playback-vol", "value"),
    Input("measures-per-pattern", "value"),
    Input("beats-per-measure", "value"),
    Input("play-hi-tone", "value"),
    Input("play-only-low-tone", "value"),
    Input("tempo-slider", "value"),
    Input("metronome-vol", "value"),
    Input("exercise-select", "value"),
    Input("show-intervals", "value"),
    Input("show-spectrum", "value"),
    prevent_initial_call=True,
)

# On page load, restore last-saved settings from localStorage.
# Uses set_props (same pattern as load-settings file picker) so settings-raw-store
# has a single formal owner.  startup-applied-store (memory) breaks the loop:
# after load_settings updates the components, auto-save re-writes local-settings-store
# which re-triggers this callback -- but the flag is already True so it no-ops.
clientside_callback(
    """
    function(localData, startupApplied) {
        if (startupApplied || !localData) {
            return window.dash_clientside.no_update;
        }
        function toYamlVal(v) {
            if (v === null || v === undefined || v === '') return '~';
            if (typeof v === 'boolean') return v ? 'true' : 'false';
            if (typeof v === 'number') return String(v);
            return JSON.stringify(String(v));
        }
        var lines = Object.entries(localData).map(function(kv) {
            return kv[0] + ': ' + toYamlVal(kv[1]);
        });
        window.dash_clientside.set_props('settings-raw-store', {
            data: {content: lines.join('\\n'), ts: Date.now()}
        });
        return true;
    }
    """,
    Output("startup-applied-store", "data"),
    Input("local-settings-store", "data"),
    State("startup-applied-store", "data"),
    prevent_initial_call=False,
)


@app.callback(
    Output("settings-raw-store", "data"),
    Input("default-settings-btn", "n_clicks"),
    prevent_initial_call=True,
)
def default_settings(_n_clicks):
    return {"content": DEFAULT_SETTINGS_YAML, "ts": 0}


if __name__ == '__main__':
    print(f"Rhythm Analyzer version {VERSION} starting up...")
    app.run(debug=True, port=8006, use_reloader=False)
