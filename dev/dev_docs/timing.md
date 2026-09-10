# Rhythm Analyzer -- Timing and Calibration

Deep dive into the timing model, calibration algorithm, and known quirks.
See also the `Audio Timing Issues` reference memory and [architecture.md](architecture.md).

---

## The Core Problem

The app plays a metronome through the speaker and records the microphone.
To align the detected pulses with the metronome beat grid, it needs to know
the offset between "metronome click scheduled at t=0" and "when that sound
appears in the microphone recording".

This offset has several components:
- **Output latency**: time from AudioContext schedule to speaker (10-80 ms typical).
- **Acoustic path**: speaker to microphone propagation (~1-3 ms in a room).
- **Input latency**: microphone ADC buffering (10-50 ms typical).
- **Count-in alignment**: the recording starts after N count-in beats; the
  JS code tries to begin the recording exactly at beat 1, but scheduling
  imprecision adds a small error.

Rather than measuring each component separately, the app measures the total
round-trip offset via a calibration recording.

---

## Calibration Algorithm

### Step 1: Play calibration track

`compute_calibration_track()` builds a WAV at startup:
- `CALIBRATION_WARMUP_MS` (200 ms) of silence
- `CALIBRATION_BEATS` (10) sine-wave ticks at `CALIBRATION_BPM` (200 BPM)
- Beat period: `60 / 200 = 0.3 s`

`first_beat_ms = CALIBRATION_WARMUP_MS = 200 ms`

The calibration track is played exactly once (no loop). The browser records the
microphone simultaneously.

### Step 2: Time recording start relative to beat 1

In `startCalibration()` (recorder.js):

```
recordDelayMs = FIRST_TONE_DELAY_SECONDS * 1000 + calibrationFirstBeatMs - RECORDING_PRE_ROLL_MS
             = 150 ms + 200 ms - 200 ms
             = 150 ms
```

`mediaRecorder.start()` fires at `recordDelayMs` after the track begins playing.
The first `RECORDING_PRE_ROLL_MS` (200 ms) of the recording is trimmed by
`encodeWAV` / `rawData.slice(preRollSamples)` in the recorder.

After trimming: the recording's t=0 corresponds to beat 1 of the calibration
track (the 200 ms silence prefix is absorbed by the pre-roll period).

### Step 3: Compute phase offset

`process_calibration()` (Python):

```python
residuals = beat_times % seconds_per_beat               # [0, spb)
residuals = where(residuals > spb/2, residuals - spb, residuals)  # (-spb/2, spb/2]
phase_offset_s = float(median(residuals))
offset_ms = round(phase_offset_s * 1000)
```

`beat_times` are detected with `detect_onsets_rms`. Each beat falls somewhere
within one subdivision period. The median residual mod the period is the
systematic offset. Wrapping to (-spb/2, spb/2] handles the case where
the offset is nearly one full period (e.g., the first beat lands just before t=0).

### Step 4: Apply calibration in analysis

Everywhere `metronome_times` is constructed:
```python
metronome_times = arange(cal_s, duration - METRONOME_END_MARGIN_SECONDS, seconds_per_beat)
```

`cal_s` shifts the entire metronome grid so that beat 1 of the grid aligns
with where the speaker output actually arrives in the recording.

Deviation formula:
```python
dt = seconds_per_beat / subdivisions_per_beat
dev_ms = ((t - cal_s - dt/2) % dt - dt/2) * 1000
```

The `- dt/2` shift centers the window on the beat: deviations are reported
as negative (early) or positive (late) relative to the center of each subdivision.

---

## Observed Cal_s Values and Their Meaning

| System state | Measured cal_s | Explanation |
|---|---|---|
| Normal warm browser | ~0 ms | AudioContext.outputLatency roughly matches true latency |
| Cold browser startup | ~+161 ms | API over-reports latency; actual audio arrives earlier than scheduled |
| Plotly Cloud / some Linux | ~-164 ms | API under-reports latency; actual audio arrives later |
| After audio pipeline reopens | Any of the above | Hardware re-init adds unpredictable offset |

All three values produce correct analysis because `cal_s` is measured per-session
and applied uniformly to both the metronome grid and the deviation formula.

---

## Display vs. Analysis Metronome Times

Two metronome arrays exist:

| Array | Formula | Purpose |
|---|---|---|
| `metronome_times` | `arange(cal_s, duration-0.1, spb)` | Analysis: absolute times stored in audio-store JSON |
| `metronome_times_display` | `arange(cal_s % spb, duration-0.1, spb)` | Display: beat markers on waveform, shifted to positive x-axis |

`display_offset = cal_s % seconds_per_beat` shifts the waveform origin so beat 1
appears near x=0 regardless of cal_s polarity. The waveform x-axis is:
```python
time = linspace(0, duration, len(y)) - (WAVEFORM_DISPLAY_SHIFT_SECONDS + display_offset)
```

Beat markers on the waveform: `mt = metronome_times_display - display_offset`
Pulse markers on the waveform: `beat_times - display_offset`

Both are shifted by the same `display_offset`, so their visual alignment is correct.

---

## Known Timing Quirks

### Cold-browser first tone dropped

On first audio use after OS restart, the hardware audio device takes 50-200 ms
to open. The `triggerPermissionDialog` warmup (8 s of silent audio) primes the
output pipeline, so by the time the metronome plays the first real tone the
device is already open.

`FIRST_TONE_DELAY_SECONDS = 0.15` (150 ms) adds scheduling headroom for the
first tone so AudioContext has time to schedule it before it needs to be played.
Previous value was 20 ms; increased to 150 ms because cold-start latency could
exceed 20 ms on some systems.

### Dash double-fire on metronome toggle

When the metronome-btn is clicked, the async chain
`AudioContext.resume -> state sync -> Dash callback` causes `toggleMetronome` to
fire twice: once for Start, once spuriously for Stop.

Guard in `toggleMetronome`:
```javascript
if (lastToggleWasStart && is_playing && msSinceLast < 2000) {
    // suppress
}
```

This suppresses a Stop that arrives within 2 s of a Start. The 2 s window is
conservative; in practice the double-fire arrives within ~200 ms.

### OutputLatency API unreliability

`AudioContext.outputLatency` reports the *estimated* output latency but is wrong
in two systematic ways:
1. Cold context: reports ~0 ms but actual latency is 50-200 ms.
2. Some browsers: reports a fixed hardware buffer size ignoring driver buffering.

For this reason, the app uses calibration measurement rather than the API.
The API value is still used for the visual beat indicator offset
(`indicatorStartTime`) to align the flashing beat box with the heard tone, not
the scheduled tone. This is cosmetic and does not affect analysis.

### Calibration warms up the audio pipeline

Early versions tried near-silent calibration (volume 0.003) to avoid acoustic
interference, but this left the hardware cold and produced ~51 ms systematic
offset. Current version plays calibration at full `metronome.volume`.

The acoustic bleed from speaker to microphone during calibration IS the signal
being measured. Both microphone and speaker output are expected to be active.

### RECORDING_PRE_ROLL_MS and the timing anchor

`RECORDING_PRE_ROLL_MS = 200 ms` is removed from the front of every recording
(normal and calibration). This pre-roll ensures:
- Normal recording: the recording buffer includes a clean "before beat 1" region.
  The OS microphone driver buffers are fully open before any audio is captured.
- Calibration: by choosing `recordDelayMs` such that the pre-roll precisely
  covers `FIRST_TONE_DELAY_SECONDS + calibrationFirstBeatMs`, after trimming
  the recording's t=0 aligns with calibration beat 1.

`outputLatencyMs` is intentionally excluded from `measureDelayMs` in
`startRecordingWithCountIn`. The comment explains: cold-start contexts measure
near-zero outputLatency while warm contexts measure ~50 ms, causing a systematic
cal_s difference if included. By anchoring to the *scheduled* beat (not the
*heard* beat), both calibration and normal recordings use the same reference,
so cal_s correctly captures the full acoustic offset.

### Calibration safety net

A 20 s timeout kills a hanging calibration if `mediaRecorder.stop()` never fires
(e.g., getUserMedia succeeds but the stop event hangs). The safety net is stored
in `calibrationSafetyNetTimeout` and is canceled when the next calibration starts.
A prior bug had the safety net from a previous run fire mid-calibration and corrupt
`calibrationRecordingEnded`. The fix: always cancel the previous safety net at the
top of `startCalibration()`.

### Auto-calibration platform persistence

After successful calibration, `user-context` (localStorage) stores:
```json
{"platform_key": "...", "calibration_offset_ms": -164, "timestamp": "..."}
```

`platform_key` is `navigator.userAgent + "|" + sampleRate + "|" + outputLatencyMs + "|" + inputLatencyMs`.

On page reload, if the platform key matches, calibration is restored silently
without running the calibration recording again. This is efficient but means
that a genuine change in audio hardware (plugging in an external DAC) may
use a stale calibration until the user clicks Calibrate manually.

---

## Calibration Failure Mode Analysis

`CALIBRATION_FAIL_STD = 1.5 ms` is very tight. Failure cases:

1. **Environmental noise**: a loud sound during calibration produces a spurious
   onset. With 10 beats, one outlier shifts the median by up to ~half-period (150 ms).
   The std explodes and calibration fails. Median is somewhat robust; removing the
   top 1-2 outliers (IQR-based) before computing std would make it more robust.

2. **Mic too far from speaker**: amplitude of the calibration click may fall below
   `BEAT_MIN_AMPLITUDE_FRACTION`. If fewer than 2 beats detected, error:
   "Calibration failed: too few beats detected".

3. **Recording started late**: if `getUserMedia` takes longer than `recordDelayMs`,
   the recording window misses beat 1. The remaining 9 beats may still compute
   a valid offset, but the std may be elevated if the captured portion starts
   mid-beat.

4. **Browser cold start still warm-up incomplete**: if warmup took longer than
   `INITIAL_WARMUP_SECONDS` (8 s), auto-calibration fires before the pipeline
   is stable. This is rare but possible on slow hardware.

---

## Recommendations for Calibration Improvement

1. **Raise CALIBRATION_FAIL_STD to 3-5 ms with outlier trimming:**
   ```python
   q25, q75 = np.percentile(residuals, [25, 75])
   iqr = q75 - q25
   clean = residuals[np.abs(residuals - np.median(residuals)) < 2 * iqr]
   std_ms = round(np.std(clean) * 1000, 1)
   CALIBRATION_FAIL_STD = 3.0  # ms
   ```

2. **Verify beat count matches expected:** If `len(beat_times)` < 8 of the expected
   10, log a warning but don't necessarily fail -- 6+ beats is enough for a stable median.

3. **Cross-check against CALIBRATION_BPM:**
   ```python
   measured_bpm = 60 / np.median(np.diff(beat_times))
   if abs(measured_bpm - CALIBRATION_BPM) > 5:
       # something is very wrong -- decoding drift or wrong track
       return error
   ```

4. **Platform key granularity:** Consider excluding `inputLatencyMs` from the
   platform key; it is often 0 or varies between sessions on the same hardware.
   The current key may produce spurious cache misses and trigger unnecessary
   re-calibration.

---

*End of timing.md*
