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

## Last session -- 2026-05-12

**This commit:** beat/deviation graph alignment fixes, warmup volume, beat highlight timing, beat filter spacing.

- **Waveform/deviation alignment:** both graphs now use `margin=dict(l=60, r=230, ...)` so plot areas are equal width regardless of legend text.
- **Zoom restore alignment (main.py `update_deviation_graph`):** `xaxis.autorange` check now comes first in relayout_data handling, before `xaxis.range[0]`. Plotly sends both on double-click reset; wrong order was applying stale zoom range to deviation graph while waveform reset.
- **Deviation graph legend:** IPI trace `name=' '` (single space, not empty string -- empty suppresses group title), `legendgrouptitle_text='Relative to<br>prev. pulse'`, `grouptitlefont=dict(size=12)` for uniform font size.
- **Beat highlight timing (recorder.js):** `indicatorStartTime = startTime + outputLatencySeconds` so visual fires when user hears the tone, not when scheduled.
- **Highlight guard (recorder.js):** `if (entry.isBeat)` before `highlightExercisePosition` -- subdivisions never highlight.
- **Calibration warmup volume (recorder.js):** 0.02 -> 0.003 in three places (per-tone fallback x2, buffer gainNode x2).
- **`BEAT_MIN_SPACING_SECONDS` (audio_utils.py):** 0.05 -> 0.065 (65ms minimum gap between detected pulses).
- **`DEFAULT_SETTINGS_YAML`:** `exercise-name: |-` instead of `null` (avoids null in YAML default).
- **UI:** exercise dropdown label "None (free metronome)" -> "None"; metronome `legendgrouptitle_text` uses `<br>` for line break.

**Open:** Stage 2c -- subdivision table SPB auto-set from exercise's first pattern when exercise mode is active.

**To update this stub:** replace the content above with a fresh summary after each commit.
