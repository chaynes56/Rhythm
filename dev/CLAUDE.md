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

Dependencies are managed via `pyproject.toml` with a virtual env at `.venv/`.
Python 3.13+ required (matches Plotly cloud runtime).


## Architecture

This is a **Plotly/Dash** web app (single file: `app/main.py`) for percussion/rhythm 
analysis. Deployed to Plotly cloud (URL in README.md). 

### Two-layer design: Python server + JavaScript client

**`app/main.py`** handles:
- Dash layout and server-side callbacks
- Audio processing via `librosa` and `soundfile` (onset detection, waveform building)
- Load/save of recordings (JSON with embedded base64 WAV + metronome metadata)

**`app/recorder.js`** handles:
- Microphone capture via an inline AudioWorklet (`CAPTURE_WORKLET_SOURCE`, loaded from a
  Blob URL). The worklet tags every PCM chunk with its audio-clock frame position;
  recordings are sliced at the exact frame where beat 1 was scheduled
  (`recordStartFrame`). MediaRecorder and wall-clock setTimeout are NOT in the sync
  path -- timers only flip UI phase and schedule stops.
- Metronome playback via Web Audio API (with HTMLAudio fallback for Safari only — Chrome, including on Plotly cloud, uses the per-tone WebAudio fallback)
- Recording countdown delay (one measure count-in before capture begins; capture starts
  at the beginning of the count-in so the input pipeline settles before beat 1)
- In-browser WAV encoding (`encodeWAV`) — captured PCM is downsampled to 4kHz via
  OfflineAudioContext and encoded as WAV before sending to Python

### How recorder.js is loaded

**Inlined into HTML** via `load_inline_script()`, not served as a normal Dash asset. `assets_ignore=r"recorder(?:_bundle)?\.js"` tells Dash to skip the file. Every JS change requires a **server restart**, not just browser refresh.

### JS → Python data flow

Dash hidden components act as a message bus:

1. Recording stops → capture sliced at beat-1 frame → JS encodes WAV → `window.recordedAudioData`
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
- Since the AudioWorklet capture rewrite (2026-09), playback scheduling and recording
  slicing share the AudioContext clock, so `cal_s` measures ONLY the physical
  output+input latency (typically ~10-50ms) and should be stable per
  device/browser. Historical note: under the old MediaRecorder + setTimeout path,
  `cal_s` swung between ~−164ms and ~+161ms depending on cold/warm pipeline state,
  because MediaRecorder's capture-start latency varied per recording.

### Known timing quirks

- **Cold-browser first tone dropped:** On first audio use after OS restart, the hardware audio device takes 50–200ms to open. A 150ms silent primer buffer in `startMetronomePlayback → startScheduler` forces the device open before the first real tone fires. `firstToneDelaySeconds` is 150ms (not the original 20ms) for the same reason.
- **Dash double-fire:** `toggleMetronome` fires twice on click (async AudioContext resume → state sync → Dash callback chain). Handled by directional debounce: suppress Stop arriving within 2s of a Start.

---

## Last session -- 2026-09-06 (3) (cross-platform robustness; wireless warning)

**Reframed from "shrink the warmup" to cross-platform robustness.** Claude had
cut INITIAL_WARMUP_SECONDS 8 -> 2 based on first-principles reasoning plus one
dev machine. User pushed back: the app must work across a wide variety of
user hardware/software, unsupported platforms should be recognized and
signaled, recalibration should happen automatically or be advised, and a few
seconds of startup delay does not matter. **Warmup reverted to 8s** (comment
records why: users have Bluetooth, layered Windows drivers, slow hardware;
the first auto-calibration measures physical latency that must be settled).

**Unsupported-platform signaling (recorder.js).** Previously a denied mic or
old browser left the buttons on "Warming Up..." forever with no message
(warmup-info-store never fires). Now capability checks run before warmup --
getUserMedia/secure context, Web Audio, AudioWorklet -- and each failure
relabels record-btn/calibrate-btn to "Recording Unavailable"/"Unavailable"
with specific advice (`signalAudioUnavailable`). getUserMedia errors are
mapped by err.name: NotAllowedError/SecurityError -> permission blocked,
NotFoundError/OverconstrainedError -> no mic. Mobile UAs get a non-blocking
advisory.

**Automatic recalibration on device change (recorder.js).** `devicechange`
listener, debounced 1.5s: when idle, re-runs triggerPermissionDialog, which
re-fingerprints the new device combo and then restores that combo's stored
calibration or auto-calibrates. Mid-recording/playback it advises instead.
platformInfo gained a `seq` field so an identical fingerprint still re-fires
the Dash callbacks (otherwise buttons stay disabled after a re-run).

**Calibration failure advice + fallback (main.py).** `platform_entry()`
helper added. Failures now always produce actionable guidance (not just in
debug mode), and fall back to the stored platform offset when one exists --
including the stale-entry case, on the reasoning that a months-old measured
offset beats an unmeasured zero.

**Capture dropouts surfaced (recorder.js).** Input gaps >= 20ms in a
recording now warn the user that pulses may be missing (was console-only).
Calibration gaps are left to the std-based failure path.

**Wireless/Bluetooth detection and warning (recorder.js).** Confirmed the
May-2026 Opus assessment: Bluetooth is the worst case because opening the
mic forces A2DP -> HFP/HSP (changes output latency mid-session, drops to
telephony sample rate), the headset runs its own clock (real drift over long
recordings, unlike wired), and A2DP buffering is renegotiated dynamically.
`WIRELESS_NAME_PATTERN` matches device labels plus a sampleRate <= 24000
HFP check, and also inspects the default audiooutput device (playback can be
wireless when the mic is not). Warns, never blocks. Regex validated against
21 realistic labels: no false positives on Blue Yeti / Shure MV7 /
Scarlett 2i2 / Realtek. A bare `Headset (` pattern was deliberately removed
-- Windows labels wired USB/Realtek headsets that way and it caught nothing
the other patterns miss.

**Not verified on hardware:** old browsers, mobile, and actual Bluetooth
behavior. Covered by design (conservative warmup, capability gates,
per-device fingerprints, advisory warnings) rather than by test.

## Previous session -- 2026-09-06 (2) (store-and-skip calibration, 8299f14)

**Store-and-skip calibration flow completed (main.py, recorder.js).** The
skeleton (local `user-context` store, warmup-triggered restore-or-auto-cal,
context write on calibration success) existed but never worked reliably.
Four defects fixed:

- **Unstable platform key (root cause):** the key included outputLatency /
  inputLatency readings, which fluctuate between page loads (cold vs warm),
  so stored keys rarely matched and auto-cal re-ran every load. Key is now
  stable identifiers only: userAgent + sampleRate + mic device label (read
  from the warmup stream before tracks stop).
- **Platform-keyed storage:** `user-context` is now
  `{platforms: {key: {calibration_offset_ms, std_ms, source, timestamp}}}`,
  pruned to 5 newest (`updated_user_context()` helper). Switching mics no
  longer clobbers other devices' calibrations. Legacy flat shape = miss,
  which also retires MediaRecorder-era offsets automatically.
- **30-day staleness expiry** in the restore clientside callback; stale ->
  auto-calibrate.
- **Restore indicator + manual persistence:** confidence span shows
  "(saved today / Nd ago)" on restore; manual edits to the ms box persist
  per-platform as source "manual", with an echo guard (restore and
  process_calibration write the same input programmatically; only a genuine
  >=0.5ms change is persisted).

**User-verified:** restore and manual-edit persistence both work across
reloads in Chrome.

**Follow-ups:** shrink 8s warmup; validate Safari (worklet needs 14.1+) and
Firefox.

## Previous session -- 2026-09-06 (audio: sample-indexed AudioWorklet capture, 5922821)

**Root cause of persistent record/playback sync errors identified and fixed
(recorder.js).** User asked to improve on the May 2026 Opus chat advice
(dev/AI/Claude/Audio Timing Issues.md), which covered warmup and calibration
persistence but not the structural flaw: playback was scheduled on the
AudioContext clock while recording started via wall-clock setTimeout +
MediaRecorder.start(), whose capture-start latency is unspecified and varies
PER RECORDING. That per-recording variance is what per-session cal_s could
not correct -- hence the +/-160ms cold/warm swings and Safari failures.

**Fix: inline AudioWorklet capture on the same AudioContext.** Every captured
PCM chunk is tagged with its audio-clock frame; the recording is sliced at
the exact frame where beat 1 was scheduled (recordStartFrame). MediaRecorder,
setTimeout, the 200ms pre-roll, and the opus decode round-trip are all gone
from the sync path. Capture starts at count-in start so the input pipeline
settles before beat 1. Calibration uses the same path; routing (recording vs
calibration) is now an explicit parameter, replacing the
calibrationRecordingEnded flag and orphaned-audio handling. JS/Dash
interface unchanged; main.py untouched.

**Measured result: calibration repeated within 2ms across three runs**
(previously swung 100ms+ between cold and warm starts). cal_s now measures
only physical output+input latency, so it should be stable per
device/browser -- the store-and-skip-calibration idea from the May chat is
now sound. Stale saved calibrations from the MediaRecorder era must be
re-run once.

**Follow-ups worth considering:** shrink the 8s page-load warmup (its main
job was stabilizing variance the worklet eliminates); enable persistent
per-platform calibration storage; validate on Safari (worklet needs 14.1+)
and Firefox.

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

### Commit Hygiene
- Never include WAV samples, .DS_Store, or other binary/system files in commits
- Review `git status` and stage files explicitly rather than using `git add .`
- Confirm the staged file list with the user before committing when adding new file types

### Dev Server
- This project uses Flask/Dash with Werkzeug; the auto-reloader can leave orphaned processes serving stale JS
- Before debugging frontend behavior, kill stray server processes (`pkill -f 'python.*app'` or check `lsof -i :PORT`) and do a hard reload
- Prefer running with reloader disabled when diagnosing client-server issues

### Linting & Types
- Run lint/type checks after edits to Python (Pyright) and JS files; the project has had repeated lint cleanup sessions
- For Pyright type-narrowing issues, prefer refactoring with `in` checks or subscript access over adding type annotations that can cascade new warnings
- Use `mcp__ide__getDiagnostics` to surface issues before committing