# Recording Limit and Play Button Toggle Fixes

## Issues Addressed

### 1. Recording Timeout Issues (15-20 second limit)
**Problem**: Recordings longer than 15 seconds would fail with timeout errors, wasting the recording.

**Root Cause**: Librosa audio processing was timing out after 30 seconds for longer recordings.

**Solution**:
- Increased timeout from 30 to 60 seconds in `load_audio_from_bytes()`
- Added `mono=True` fallback for faster processing
- Added automatic recording stop after 45 seconds to prevent timeout failures
- This ensures recordings are automatically stopped before hitting the processing limit

### 2. Play Button Toggle Functionality
**Problem**: Play button didn't toggle to "Stop Playback" like the record button does for "Stop Recording", allowing multiple playbacks to overlap.

**Solution**:
- Added `is-playing` state checklist to track playback status
- Modified `playAudio()` JavaScript function to handle play/stop toggle
- Added `currentAudio` variable to track the currently playing audio element
- Added callback to update play button text and color based on playback state
- Play button now shows "Stop Playback" when playing and "Play Recording" when stopped

## Technical Changes

### main.py
- Added `is-playing` checklist component
- Added `update_play_button()` callback
- Modified `load_audio_from_bytes()` with increased timeout and mono fallback
- Updated play button clientside callback to pass and return playing state

### recorder.js
- Added `currentAudio` global variable to track playing audio
- Modified `playAudio()` to handle toggle functionality:
  - If currently playing, stops playback
  - If not playing, starts new playback
  - Properly manages audio element lifecycle
- Added automatic recording timeout (45 seconds) in `toggleRecording()`

## Testing Results

- ✅ Recordings now automatically stop at 45 seconds, preventing wasted recordings
- ✅ Processing timeout increased to 60 seconds for longer recordings
- ✅ Play button now toggles between "Play Recording" and "Stop Playback"
- ✅ Multiple simultaneous playbacks prevented
- ✅ Audio state properly managed and cleaned up

## Why 45 Second Auto-Stop

The 45-second automatic stop ensures recordings complete processing before hitting the 60-second timeout. This gives users longer recordings (up to ~1 minute) while preventing the frustrating experience of recordings failing after completion.</content>
<parameter name="filePath">/Users/cth/Dev/PycharmProjects/Rhythm/Dev/Copilot/RECORDING_LIMITS_AND_PLAY_TOGGLE_FIX.md
