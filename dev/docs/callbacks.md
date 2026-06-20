# Rhythm Analyzer -- Callback Reference

All Dash callbacks (Python server callbacks and clientside callbacks) in
`app/main.py` as of version 0.1.9.

---

## Hidden Dash Component IDs (message bus)

### dcc.Store components

| ID | Storage | Written by | Read by | Purpose |
|---|---|---|---|---|
| `audio-store` | memory | `process_audio`, `load_recording`, `process_calibration` (debug) | `update_analysis`, `update_subdivision_table`, `update_deviation_graph`, `update_interval_histogram`, `update_spectrum`, clientside (playback sync) | Full recording JSON blob |
| `recording-phase-store` | memory | clientside from `recording-phase-sync` | clientside (visibility, is-recording) | "idle" / "delay" / "recording" |
| `waveform-visible-store` | memory | `process_audio`, `load_recording`, `process_calibration` (debug), clientside (phase change) | clientside (graph visibility) | bool: show analysis section |
| `metronome-points-store` | memory | nothing | nothing | **dead store -- can be removed** |
| `pulse-points-store` | memory | nothing | nothing | **dead store -- can be removed** |
| `audio-data-store` | memory | clientside from `audio-process-btn` | `process_audio`, `show_analyzing_message` | Raw base64 WAV from JS after recording |
| `record-command-store` | memory | clientside (sink, no_update) | nothing | Sink for record button clientside callbacks |
| `metronome-command-store` | memory | clientside (sink, no_update) | nothing | Sink for metronome clientside callbacks |
| `settings-raw-store` | memory | `load_settings_btn` clientside, `default_settings`, startup clientside | `load_settings` | {content: yaml_string, ts: epoch_ms} |
| `local-settings-store` | local | auto-save clientside | startup restore clientside | Persisted settings dict (no custom-exercises) |
| `startup-applied-store` | memory | startup restore clientside | startup restore clientside | bool: prevents double-apply loop |
| `metronome-track-store` | memory | `update_metronome_track` | clientside -> loadMetronomeTrack | base64 WAV data URL for metronome loop |
| `calibration-audio-data-store` | memory | clientside from `calibration-process-btn` | `process_calibration` | Raw base64 WAV from calibration recording |
| `calibration-offset-store` | memory | `process_calibration`, `calibration_value_edited`, startup restore clientside | `process_audio`, `load_recording` | float: calibration offset in ms |
| `calibration-track-store` | memory | computed at module import (`compute_calibration_track()`) | clientside -> loadCalibrationTrack | {data_url, first_beat_ms} |
| `calibration-command-store` | memory | clientside (sink) | nothing | Sink for calibration control clientsides |
| `debug-mode-store` | memory | `load_settings` | `process_calibration`, `is_debug_mode()` | bool |
| `exercise-schedule-store` | memory | `update_exercise_schedule` | clientside -> setExerciseSchedule | {schedule, duration, spb} |
| `error-beep-sink` | memory | clientside (sink) | nothing | Sink for error beep clientsides |
| `server-log-store` | memory | `update_metronome_track`, `flush_load_log` | clientside -> console.log | list of load log messages |
| `error-store` | memory | Python callbacks (on exception), clientside `reportJsError` | clientside (show error row, beep) | Error string |
| `user-context` | local | `process_calibration` | warmup-info-store clientside | {platform_key, calibration_offset_ms, timestamp} |

### Hidden dcc.Input components

| ID | Written by | Read by | Purpose |
|---|---|---|---|
| `recording-phase-sync` | `setRecordingPhase()` in recorder.js | clientside -> `recording-phase-store` | JS -> Dash phase bridge |
| `metronome-state-sync` | `setMetronomePlayingState()` in recorder.js | clientside -> `is-metronome-playing` | JS -> Dash metronome state bridge |
| `warmup-info-store` | `triggerPermissionDialog()` in recorder.js | calibration restore clientside, warmup-buttons clientside | JSON string: platform info after warmup |
| `playback-sync` | clientside from `audio-store` | (value unused; side effect only) | Pushes audio data URL to `window.lastRecordedAudio` |

### Hidden dbc.Button components

| ID | Clicked by | Triggers | Purpose |
|---|---|---|---|
| `audio-process-btn` | recorder.js after recording ends | clientside -> `audio-data-store` | Signal: pull audio from `window.recordedAudioData` |
| `calibration-process-btn` | recorder.js after calibration ends | clientside -> `calibration-audio-data-store` | Signal: pull audio from `window.calibrationRecordedAudio` |
| `playback-ended-btn` | recorder.js `currentAudio.ended` event | clientside -> `is-playing = []` | Signal: playback has ended |

### Other hidden components

| ID | Type | Purpose |
|---|---|---|
| `is-recording` | dcc.Checklist (hidden) | bool state: are we recording? |
| `is-playing` | dcc.Checklist (hidden) | bool state: is playback running? |
| `is-metronome-playing` | dcc.Checklist (hidden) | bool state: is metronome running? |
| `upload-audio` | dcc.Upload (hidden) | File picker for Load JSON |
| `download-audio` | dcc.Download | Triggers Save as JSON download |
| `download-wav` | dcc.Download | Triggers Export as WAV download |
| `download-settings` | dcc.Download | Triggers Save Settings download |

---

## Python Server Callbacks

### process_calibration

```
Input:  calibration-audio-data-store.data
State:  debug-mode-store.data, warmup-info-store.value
Output: calibration-offset-store.data
        status-msg.children
        audio-store.data           (debug/failure path only)
        waveform-visible-store.data (debug/failure path only)
        waveform-graph.figure       (debug/failure path only)
        calibration-value.value
        calibration-confidence.children
        user-context.data
```

Decodes audio, detects beats, computes phase_offset_s = median(beat_times % spb)
wrapped to (-spb/2, spb/2]. Rejects if std >= CALIBRATION_FAIL_STD (1.5 ms).
On success saves offset_ms and updates localStorage user-context with platform_key.

Error messages:
- "Calibration failed: could not load audio"
- "Calibration failed: too few beats detected" (if fewer than 2 beats)
- "Calibration failure: {offset} +/- {std} ms" (if std too high, shown in red span)
- "Calibration failed: {e}" (exception path)

### calibration_value_edited

```
Input:  calibration-value.value
Output: calibration-offset-store.data
```

Converts numeric input to float and writes to offset store. Allows manual override
of auto-calibration.

### update_metronome_track

```
Input:  tempo-slider.value, beats-per-measure.value, measures-per-pattern.value,
        play-hi-tone.value, play-only-low-tone.value, exercise-select.value,
        play-subdivisions.value, play-tones.value, play-only-tones.value,
        metronome-voicing.value, exercise-voicing.value
Output: metronome-track-store.data
        status-msg.children (error path)
        server-log-store.data (sample load log)
        error-store.data (exception path)
```

Calls `compute_metronome_track()` with all parameters. Returns base64 WAV data URL.
Error message: "Metronome track failed: {e}"
Length error: "Exercise too long at {t} BPM ({s}s; limit 5 min)."

### update_beat_indicator_boxes

```
Input:  beats-per-measure.value, measures-per-pattern.value, exercise-select.value
Output: beat-indicator-container.children
        beat-label.children
```

Free mode: `build_beat_indicator_boxes(beats, measures)` -- colored boxes by beat/measure.
Exercise mode: `build_exercise_table(exercise_name)` -- the notation grid.
Label is "Beat" in free mode, voicing key string in exercise mode.

### update_exercise_ui

```
Input:  exercise-select.value, tempo-slider.value
Output: beats-measures-controls.style
        play-tones-col.style
        play-only-tones-col.style
        play-subdivisions-col.style
        exercise-voicing-col.style
        exercise-length-alert.children
        beats-per-measure.value       (allow_duplicate)
        measures-per-pattern.value    (allow_duplicate)
        subdivisions-per-beat.value   (allow_duplicate)
```

Hides beats/measures dropdowns when exercise selected (they are set from exercise data).
Shows exercise-specific controls. Issues a dbc.Alert if exercise exceeds 5-min limit.
On exercise-select trigger: sets beats, measures, subdivisions from exercise pattern[0].

### enforce_tone_toggle_exclusion

```
Input:  play-only-tones.value, play-tones.value
Output: play-tones.value, play-only-tones.value
```

Mutual exclusion: turning on play-only-tones turns off play-tones and vice versa.

### update_exercise_schedule

```
Input:  exercise-select.value, tempo-slider.value
Output: exercise-schedule-store.data
```

Returns None in free mode. In exercise mode calls `compute_exercise_schedule(patterns, tempo)`.
Result: `{schedule: [{time, patternIdx, measureIdx, subIdx, isBeat}, ...], duration, spb}`.

### clear_msg_on_record / clear_msg_on_play / clear_msg_on_save / clear_msg_on_load

Four trivial callbacks that clear `status-msg` when user clicks the respective button.

### update_record_button

```
Input:  recording-phase-store.data
State:  is-metronome-playing.value
Output: record-btn.children, record-btn.color
        metronome-btn.children, metronome-btn.disabled
```

| Phase | record-btn label | record-btn color | metronome-btn label |
|---|---|---|---|
| idle | Start Recording | danger (red) | Start/Stop Metronome |
| delay | Counting in... | warning (yellow) | Stop Recording |
| recording | Stop Recording | secondary (gray) | Stop Recording |

### update_play_button

```
Input:  is-playing.value
Output: play-btn.children
```

"Play Recording" or "Stop Playback".

### update_spectrum

```
Input:  audio-store.data, waveform-graph.relayoutData
Output: spectrum-graph.figure, error-store.data
```

If triggered by relayoutData zoom: re-extracts audio from audio-store, slices the
waveform array to the zoom window, recomputes spectrum on that slice.
Otherwise uses precomputed `spectrum_freqs` / `spectrum_psd` from audio-store JSON.

### show_analyzing_message

```
Input:  audio-data-store.data
Output: status-msg.children
```

Returns "Analyzing..." immediately when audio data arrives. Replaced by
process_audio's output.

### update_analysis

```
Input:  audio-store.data, waveform-graph.relayoutData, subdivisions-per-beat.value
Output: analysis-data-block.children, status-msg.children, error-store.data
```

Computes deviation statistics for visible pulses. Deviation formula:
`dev = ((t - cal_s - dt/2) % dt - dt/2) * 1000 ms` where `dt = spb / tempo`.
Respects zoom window from relayoutData (ignores on audio-store trigger).
Returns Markdown text with bold numbers.

### update_subdivision_table

```
Input:  audio-store.data, waveform-graph.relayoutData,
        training-level.value, subdivisions-per-beat.value
Output: subdivision-table-container.children, error-store.data
```

See architecture.md -- Subdivision Table section for cell logic details.

### update_interval_histogram

```
Input:  audio-store.data, waveform-graph.relayoutData, show-intervals.value
Output: interval-histogram.figure, error-store.data
```

Histogram of `diff(beat_times) * 1000` ms. Bin width = 1 ms.

### update_deviation_graph

```
Input:  audio-store.data, waveform-graph.relayoutData, training-level.value
State:  subdivisions-per-beat.value
Output: deviation-graph.figure, error-store.data
```

Two series: metronome-relative deviation lines, IPI (inter-pulse interval) dots.
X-axis synchronized with waveform zoom. Invisible anchor traces keep autorange
consistent on zoom reset (double-click).

### process_audio

```
Input:  audio-data-store.data
State:  tempo-slider.value, beats-per-measure.value, measures-per-pattern.value,
        subdivisions-per-beat.value, calibration-offset-store.data, exercise-select.value
Output: audio-store.data
        waveform-visible-store.data
        waveform-graph.figure
        status-msg.children
        error-store.data
```

Main audio processing pipeline. See architecture.md for full pipeline description.
Error messages:
- "Error processing audio: {e}"
- "Error: Failed to process audio. Recording may be corrupted..."

### save_recording

```
Input:  save-btn.n_clicks
State:  audio-store.data
Output: download-audio.data
```

Returns `{content: json_string, filename: "recording.json"}`.

### export_wav

```
Input:  export-wav-btn.n_clicks
State:  audio-store.data
Output: download-wav.data
```

Extracts base64 WAV from audio-store, decodes, returns raw bytes via `dcc.send_bytes`.

### load_recording

```
Input:  upload-audio.contents
State:  beats-per-measure.value, subdivisions-per-beat.value, calibration-offset-store.data
Output: audio-store.data
        waveform-visible-store.data
        waveform-graph.figure
        status-msg.children
        exercise-select.value
        error-store.data
```

Decodes JSON file, loads embedded audio, rebuilds waveform figure using saved
`calibration_offset_ms`, `tempo`, `beat_times`, `metronome_times_display`.
Error messages:
- "Error: Uploaded file is not a valid JSON recording saved by this app."
- "Error: Uploaded file contains invalid JSON."
- "Error: Recording too long or corrupted..."
- "Load recording failed: {e}"

### save_settings

```
Input:  save-settings-btn.n_clicks
State:  (all 15 setting components)
Output: download-settings.data
```

YAML dump of current settings. Always saves `debug-mode: false`.

### load_settings

```
Input:  settings-raw-store.data
Output: (18 outputs: all setting components + status-msg + debug-mode-store +
         exercise-select + exercise-select.options + show-intervals + show-spectrum +
         metronome-voicing + exercise-voicing + error-store)
```

Parses YAML, validates types, calls `make_exercises(custom_text)`, updates
global `_custom_exercises` / `_custom_exercises_text`. Updates exercise dropdown
options to include custom exercises.
Error messages written to error-store:
- "Invalid YAML syntax at line N: {problem}"
- "Invalid setting for: {key1}, {key2}"
- "Custom exercises parse error: {e}"
- "Load settings failed: {e}"

### default_settings

```
Input:  default-settings-btn.n_clicks
Output: settings-raw-store.data
```

Writes `{content: DEFAULT_SETTINGS_YAML, ts: 0}` which triggers load_settings.

---

## Clientside Callbacks (abbreviated)

| Trigger | Output | JS action |
|---|---|---|
| `calibration-track-store.data` | `calibration-command-store.data` | `recorderControls.loadCalibrationTrack(trackData)` |
| `calibrate-btn.n_clicks` | `calibration-command-store.data` | `recorderControls.startCalibration()` |
| `warmup-info-store.value` | `calibration-offset-store.data`, `calibration-value.value`, `calibration-confidence.children` | Restore saved cal from user-context, or trigger auto-cal |
| `calibration-process-btn.n_clicks` | `calibration-audio-data-store.data` | Pull `window.calibrationRecordedAudio` |
| `record-btn.n_clicks` | `record-command-store.data` | `recorderControls.toggleRecording(...)` |
| `play-btn.n_clicks` | `is-playing.value` | `recorderControls.playAudio(...)` |
| `metronome-btn.n_clicks` | `metronome-command-store.data` | `recorderControls.toggleRecording()` or `toggleMetronome()` |
| tempo/beats/measures/vol/hi/low (Input x6) | `metronome-command-store.data` | `recorderControls.reconfigureMetronome(...)` |
| `metronome-track-store.data` | `metronome-command-store.data` | `recorderControls.loadMetronomeTrack(dataUrl)` |
| `exercise-schedule-store.data` | `metronome-command-store.data` | `recorderControls.setExerciseSchedule(data)` |
| `recording-phase-sync.value` | `recording-phase-store.data` | Pass-through |
| `recording-phase-store.data` | `is-recording.value` | `== 'recording' ? ['recording'] : []` |
| `metronome-state-sync.value` | `is-metronome-playing.value` | `== 'playing' ? ['playing'] : []` |
| `audio-process-btn.n_clicks` | `audio-data-store.data` | Pull `window.recordedAudioData` |
| `audio-store.data` | `playback-sync.value` | Push `data.audio` to `window.lastRecordedAudio` |
| `recording-phase-store.data` | `waveform-visible-store.data` | `false` if phase != 'idle' |
| `playback-ended-btn.n_clicks` | `is-playing.value` | `[]` (stop playing state) |
| `recording-phase-store.data` + `waveform-visible-store.data` | `waveform-graph.style` | Show/hide with height |
| `waveform-visible-store.data` | `analysis-data-block.style` | display block/none |
| `waveform-visible-store.data` | `deviation-graph.style` | Show/hide with height |
| `waveform-visible-store.data` | `subdivision-table-container.style` | display block/none |
| `waveform-visible-store.data` + `show-intervals.value` | `interval-histogram.style` | Show/hide |
| `waveform-visible-store.data` + `show-spectrum.value` | `spectrum-graph.style` | Show/hide |
| `status-msg.children` | `error-beep-sink.data` | 220 Hz beep if msg contains error keywords |
| `server-log-store.data` | `error-beep-sink.data` | console.log each message |
| `error-store.data` | `error-msg-text.children`, `error-msg-row.style` | Show/hide error row |
| `error-clear-btn.n_clicks` | `error-store.data` | `""` |
| `error-store.data` | `error-beep-sink.data` | 220 Hz beep |
| `warmup-info-store.value` | `record-btn.disabled`, `record-btn.children`, `calibrate-btn.disabled`, `calibrate-btn.children` | Enable/disable with "Warming Up..." / ready labels |
| `load-btn.n_clicks` | `load-btn.n_clicks` | Click `#upload-audio input` |
| `load-settings-btn.n_clicks` | `load-settings-btn.n_clicks` | File picker, read YAML, `set_props('settings-raw-store', ...)` |
| (all 13 settings inputs) | `local-settings-store.data` | Pack dict to localStorage |
| `local-settings-store.data` + `startup-applied-store.data` | `startup-applied-store.data` | On startup: `set_props('settings-raw-store', ...)` |

---

*End of callbacks.md*
