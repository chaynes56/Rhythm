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

**Calibration silent warmup fix (5ed849b):** Prior attempt (per-tone path) was dead code — `startCalibration` never nulls the precomputed buffer, so `startMetronomePlayback` always takes the buffer path. Fix: schedule gain ramps on `metronomeGainNode` in the buffer path (0.02 during warmup, linearRamp to 1.0 at measurement start). Auto-calibration passes `warmupMeasures=3`; manual passes `warmupMeasures=1` (pipeline already warm). `startCalibration` accepts param; `autoStopMs` scales accordingly. Field-tested — excellent results in Safari and Chrome.

**Debug mode (5ed849b):** `is_debug_mode(store_val)` checks 3 sources: `app.server.debug`, `DEBUG_MODE` env var, YAML `debug-mode` setting. Save always writes `false`. In debug mode, `process_calibration` builds full waveform+analytics from the calibration recording (same `audio-store` format as `process_audio`). Both calibration paths now show "Calibrating..." immediately.

**IPI deviation dots (5ed849b):** For each pulse i>0, y = deviation of `beat_times[i]-beat_times[i-1]` from nearest subdivision interval. Immune to calibration offset. Royalblue, size 10, rendered on top of existing size-6 colored dots. Legend reorganised: "Relative to metronome" group (green/orange/red bars) + "Relative to previous pulse" group (IPI dot), via Plotly `legendgrouptitle_text`.

**exercises.py (5ed849b):** Exercise dict now `{total_beats, patterns}` for upcoming metronome length guard.

**Open:** Exercises Stage 2 (UI layout: dropdown, pattern table, Play Subdivisions toggle); metronome length guard re-implementation.

**To update this stub:** replace the content above with a fresh summary after each commit.
