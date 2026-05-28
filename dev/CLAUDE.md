# CLAUDE.md

Guidance for Claude Code. Read this at session start. Full session history is in `dev/AI/Claude/MEMORY.md` (local only, not in git) — read it when older context matters.

## Interaction style and limits

If a task is taking many tool calls with no visible evidence of progress -- roughly
15 minutes of work without a clear milestone -- stop and report status rather than
continuing silently. Exceptions: the user has already approved a plan, or the task
is a routine wrap-up/commit/summary sequence.

## Running the App

```bash
python app/main.py          # runs on http://localhost:8006 in debug mode
```

Dependencies are managed via `app/pyproject.toml` with a virtual env at `.venv/`. 
Python 3.14+ required. 


## Architecture

This is a **Plotly/Dash** web app (single file: `app/main.py`) for percussion/rhythm 
analysis. Deployed to Plotly cloud (URL in README.md). 

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

## Last session -- 2026-05-28

**Calibration failure detection (main.py + audio_utils.py, cc304ff):**

- `CALIBRATION_FAIL_STD = 1.5` ms added to `audio_utils.py` (user later edited from 2 to 1.5).
- `std_ms` restored to `.1f` float format (`round(..., 1)`); was integer after previous session.
- On failure (`std_ms >= CALIBRATION_FAIL_STD`): show red `html.Span` "Calibration failure:
  <median> +/- <std> ms" in the `calibration-confidence` span; do not update
  `calibration-value`, `calibration-offset-store`, or `user-context`.
- Confidence string (`±{std_ms} ms`) now shown only in debug mode on successful calibration;
  empty string returned in non-debug success path.
- Waveform analysis always shown on failure (debug or not); skipped on non-debug success.
  Achieved by restructuring: single waveform-building block shared by failure and debug-success
  paths; `cal_out = no_update if failed else offset_ms` controls whether value updates.

**Move dev/Notes.md -> docs/DevNotes.md (cc304ff):**

- File moved and docs/README.md updated (collaboration section links to DevNotes).

**Open:** None.

**To update this stub:** replace the content above with a fresh summary after each commit.

---

## Debugging Approach

- Diagnose root cause before proposing fixes; avoid speculative patches like adding many path candidates or combining detectors without evidence.
- When a fix regresses other behavior (e.g., timing, alignment), stop and investigate state/side effects before iterating further.
- Prefer minimal, targeted changes over broad refactors when debugging.

## Audio/Rhythm App Conventions

- When changing sample rate or hop_length, update ALL librosa calls consistently: frames_to_time, onset_detect, n_fft scaling.
- Beat filtering should use the smoothed onset envelope, not instantaneous waveform values.
- Any shift/offset constant must be applied to both beat_times and the waveform display.
- Centralize defaults in the settings dict rather than hardcoding.

## Session Wrap-Up Behavior

- When the user says they want to wrap up, commit notes, or update memory files: do ONLY that. Do not start new exploration or investigation.
- Confirm scope before running additional Read/Bash/Grep commands at end of session.

## Tooling Preferences

- For Python venv/dependency issues, prefer running `uv venv` directly when requested rather than suggesting shell-level VIRTUAL_ENV workarounds.
- Respect IDE-native solutions (e.g., PyCharm interpreter settings) over global shell hacks.
