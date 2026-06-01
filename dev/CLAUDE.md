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

## Last session -- 2026-05-31

**Voicing feature -- planning and Stage 1 (audio_utils.py, not yet committed):**

Codec decisions: WAV, 16-bit PCM, mono, individual files per VC per VS. Confirmed
server-side Python loads samples (current architecture extended). Plotly cloud
re-upload and file-count are non-issues. Full plan written to
`dev/AI/Claude/Voicing-plan.md`.

Stage 1 changes to `audio_utils.py`:
- Added `pathlib.Path` import.
- Added `_sample_cache: dict[tuple, np.ndarray] = {}` at module level.
- Renamed `_make_metronome_tick` -> `_make_synth_tick`.
- Added `_load_sample(vs, vc_char, sr)`: loads `app/data/{VS}/{vc_char}.wav`,
  resamples to `sr` if needed, caches; falls back to synthesized 'high' on missing file.
- Added `_get_tick(sr, tone_type, vs='synthesized', vc_char=None)`: routes to
  `_make_synth_tick` for Synthesized or sub with no VC char, else `_load_sample`.
- Extended `compute_metronome_track` signature with `metro_vs='synthesized'` and
  `exercise_vs='synthesized'`; all internal tick calls use `_get_tick` with the
  appropriate VS. Exercise note ticks pass `vc_char=char` so samples are looked up
  by VC character directly.
- `compute_calibration_track` uses `_make_synth_tick` (always synthesized).
- Verified: synthesized path output identical to pre-change baseline.

**Open:** Stage 2 (main.py: dropdown options, callback inputs, settings save/load).
User still needs to generate WAV files and place in `app/data/Djembe/` and
`app/data/Darbuka/`.

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
