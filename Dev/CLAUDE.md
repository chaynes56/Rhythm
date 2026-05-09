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
- Metronome playback via Web Audio API (with HTMLAudio fallback for Safari/Plotly cloud)
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

## Last session — 2026-05-08/09

**Typecheck warnings fixed (3de518b):** Two "Unused property" warnings in `recorder.js` (`loadMetronomeTrack`, `startCalibration`) cleared by adding `void window.recorderControls.X` references matching the existing pattern for `reconfigureMetronome`. Properties are called from Dash clientside callbacks in `main.py` which the IDE can't see cross-file.

**Zoom-reset alignment fixed — confirmed working (fe6d259):** `[deviation]` debug output diagnosed the root cause: after double-click reset, Plotly switches the waveform to autorange (adds ~5% padding) but the deviation graph was set to exact data bounds → both ends off. Fix: invisible anchor traces at `[-shift, duration-shift]` added to deviation figure so its autorange spans the full recording; `xaxis.autorange` branch now sets `x_range = None` → `fig.update_xaxes(autorange=True)` to match waveform behaviour. Added `automargin=False` to both graphs' y-axes for pixel-level parity on first display. Debug print removed.

**Startup calibration warmup approach changed (in progress, not yet field-tested):** 1.5s silent primer in `firstToneDelaySeconds` reverted to 0.15s (same as normal). Root cause: silence doesn't exercise the OS audio driver the same way as real audio content — pipeline stays cold. Fix: calibration now uses 2 count-in measures (`countInMeasures = calibrationMode ? 2 : 1` in `startRecordingWithCountIn`) so 2 full measures of real metronome tones warm the pipeline before the first measured beat. `autoStopMs` updated accordingly (500 + 150 + 2×measure + 4 beats + 500ms).

**ruamel.yaml → pyyaml:** Plotly cloud lacked `ruamel.yaml`. Replaced `from ruamel.yaml import YAML` with `import yaml`; `YAML(typ='safe').load()` → `yaml.safe_load()`; `YAML().dump()` → `yaml.dump(..., default_flow_style=False)`. `uv add pyyaml && uv remove ruamel-yaml` updated `pyproject.toml`.

**Open:** startup auto-calibration accuracy with 2-measure warmup (field test pending); metronome length guard re-implementation; histogram wider + x-axis ticks.

**To update this stub:** replace the content above with a fresh summary after each commit.
