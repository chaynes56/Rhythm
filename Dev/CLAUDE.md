# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the App

```bash
python app/main.py          # runs on http://localhost:8006 in debug mode
```

Dependencies are managed via `app/pyproject.toml` with a virtual env at `.venv/`. Python 3.14+ required.

## Architecture

This is a **Plotly/Dash** web app (single file: `app/main.py`) for percussion/rhythm analysis. The app is deployed to the Plotly cloud at the URL in README.md.

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

The script is **inlined into the HTML** via `load_inline_script()` rather than served as a normal Dash asset. This avoids double-loading: `assets_ignore=r"recorder(?:_bundle)?\.js"` tells Dash to skip the file.

### JS → Python data flow

Dash hidden components act as a message bus between JS and Python:

1. Recording stops → JS encodes WAV, stores in `window.recordedAudioData`
2. JS clicks hidden `#audio-process-btn`
3. `audio-data-store` clientside callback reads `window.recordedAudioData` and pushes it to the Dash store
4. Python `process_audio` callback fires, runs librosa analysis, returns waveform figure + JSON blob to `audio-store`
5. Other callbacks read `audio-store` to update UI (beat counts, waveform visibility)

Recording phase state (`idle` / `delay` / `recording`) is synced through `#recording-phase-sync` hidden input using `setDashInputValue()`, which manually fires React synthetic events to trigger Dash updates.

### Audio processing note

`librosa.beat.beat_track` is intentionally disabled (see comment in `process_audio`) — it crashes the Plotly cloud worker due to numba/llvmlite JIT compilation. Onset detection (`librosa.onset.onset_detect`) is used instead.

### Waveform display pipeline

Raw audio → `trim_audio_tail` → `normalize_waveform_for_display` → `smooth_waveform_for_display` → `downsample_waveform_preserve_peaks` → Plotly figure with overlaid metronome beat markers (red/orange diamonds) and detected pulse markers (green circles).

## Recent commits

**aff27d9** — Ghost notes use `'.'` voicing character (was space); pattern lines must match exact subdivision count (no silent padding). `WAVEFORM_DISPLAY_SHIFT_SECONDS` tuned 0.017→0.025. Subdivision markers extrapolated past last beat. Scroll zoom disabled on waveform. *Metronome beats display fixed; analysis timing still being worked on.*