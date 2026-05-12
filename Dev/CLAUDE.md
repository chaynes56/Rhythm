# CLAUDE.md

Guidance for Claude Code. Read this at session start. Full session history is in `Dev/AI/Claude/MEMORY.md` (local only, not in git) — read it when older context matters.

## Running the App

```bash
python app/main.py          # runs on http://localhost:8006 in debug mode
```

Dependencies are managed via `app/pyproject.toml` with a virtual env at `.venv/`. Python 3.14+ required.

## Architecture

This is a **Plotly/Dash** web app (single file: `app/main.py`) for percussion/rhythm analysis. Deployed to Plotly cloud (URL in README.md).

### Two-layer design: Python server + JavaScript client

**`app/main.py`** handles:
- Dash layout and server-side callbacks
- Audio processing via `librosa` and `soundfile` (onset detection, waveform building)
- Load/save of recordings (JSON with embedded base64 WAV + metronome metadata)

**`app/assets/recorder.js`** handles:
- Microphone access (`MediaRecorder` API)
- Metronome playback via Web Audio API (with HTMLAudio fallback for Safari only — Chrome, including on Plotly cloud, uses the per-tone WebAudio fallback)
- Recording countdown delay (one measure count-in before capture begins)
- In-browser WAV encoding (`encodeWAV`) — recorded blobs are decoded and re-encoded as WAV before sending to Python

### How recorder.js is loaded

**Inlined into HTML** via `load_inline_script()`, not served as a normal Dash asset. `assets_ignore=r"recorder(?:_bundle)?\.js"` tells Dash to skip the file. Every JS change requires a **server restart**, not just browser refresh.

### JS → Python data flow

Dash hidden components act as a message bus:

1. Recording stops → JS encodes WAV → `window.recordedAudioData`
2. JS clicks hidden `#audio-process-btn`
3. `audio-data-store` clientside callback pushes data to Dash store
4. Python `process_audio` fires, runs librosa analysis → waveform figure + JSON blob → `audio-store`
5. Other callbacks read `audio-store` to update UI

Recording phase state (`idle` / `delay` / `recording`) synced through `#recording-phase-sync` hidden input via `setDashInputValue()` (fires React synthetic events).

### Audio processing

`librosa.beat.beat_track` intentionally disabled — crashes Plotly cloud worker (numba/llvmlite JIT). Uses `librosa.onset.onset_detect` instead.

Waveform pipeline: raw audio → `trim_audio_tail` → `normalize_waveform_for_display` → `smooth_waveform_for_display` → `downsample_waveform_preserve_peaks` → Plotly figure with metronome beat markers (red/orange diamonds) and detected pulse markers (green circles).

### Calibration and timing model

The app measures output latency to synchronise recording start with metronome beat 1. Because Web Audio's `outputLatency` API is unreliable on many systems, a **calibration recording** is used instead:

- Calibration plays one measure with `onlyLowTone=true` (speaker → mic) and measures `median(beat_times % seconds_per_beat)`, normalised to `(−spb/2, spb/2]` → `cal_s` (seconds).
- `cal_s` is saved in every recording's JSON as `calibration_offset_ms`.
- All analysis (deviation formulas, subdivision assignment, `metronome_times_display`) applies `t − cal_s` to correct for the recording-start offset.
- `cal_s` varies by system state: ~0ms when API reports latency accurately, ~−164ms when API under-reports (~0ms measured vs ~337ms actual), ~+161ms when API over-reports on cold browser startup. All values produce correct analysis because `cal_s` is measured and saved per session.

### Known timing quirks

- **Cold-browser first tone dropped:** On first audio use after OS restart, the hardware audio device takes 50–200ms to open. A 150ms silent primer buffer in `startMetronomePlayback → startScheduler` forces the device open before the first real tone fires. `firstToneDelaySeconds` is 150ms (not the original 20ms) for the same reason.
- **Dash double-fire:** `toggleMetronome` fires twice on click (async AudioContext resume → state sync → Dash callback chain). Handled by directional debounce: suppress Stop arriving within 2s of a Start.

---

## Last session — 2026-05-11

**Exercises Stage 2b (uncommitted):** JS cell highlighting + load_recording context restore:
- recorder.js: `exerciseSchedule` global, `highlightExercisePosition(m, s)`, `setExerciseSchedule(data)` (exposed on recorderControls); buffer-path 10ms poll does binary search on schedule to find current subdivision and highlights `ex-cell-0-{m}-{s}`; `advanceMetronomePosition` handles per-tone fallback; `resetBeatIndicators` handles exercise mode
- `compute_exercise_schedule` now includes `spb` key; `exercise-schedule-store` + `update_exercise_schedule` callback + clientside callback push schedule to JS on exercise/tempo change
- `load_recording` now has 5 outputs including `exercise-select` value (restored from `exercise_name` in recording JSON)

**Exercises Stage 2a (efc9ecb):** exercise-select dropdown, beats-measures-controls hide/show, exercise pattern table, play-subdivisions toggle, custom-exercises-text textarea, metronome track uses exercise patterns, settings save/load.

**Open:** commit 2b; then Stage 2c (parse error feedback, subdivision table SPB auto-set from exercise).

**To update this stub:** replace the content above with a fresh summary after each commit.
- `exercise-select` dropdown in Metronome card; options rebuilt from `custom-exercises-text` textarea (Settings card) via `update_exercise_options`.
- `update_exercise_ui` callback: hides `beats-measures-controls` div, shows `play-subdivisions-col` div, fires `dbc.Alert` if exercise > 300s, sets beats/measures dropdowns to exercise values on selection.
- `build_exercise_table(exercise_name, custom_text)`: HTML table with subdivision header row + measure rows; cell IDs `ex-cell-{pat_idx}-{m_idx}-{col_idx}` for future JS highlighting.
- `update_metronome_track`: now accepts `exercise-select`, `play-subdivisions`, `custom-exercises-text`; passes exercise patterns to `compute_metronome_track`.
- `save_settings`/`load_settings`: persist `exercise-name` and `custom-exercises`.
- `process_audio`: saves `exercise_name` in audio-store JSON.

**Open:** commit this; then Stage 2b (JS cell highlighting, `compute_exercise_schedule` -> JS store, restore exercise on load_recording).

**To update this stub:** replace the content above with a fresh summary after each commit.
