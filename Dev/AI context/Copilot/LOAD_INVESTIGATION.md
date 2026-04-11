# Load Recording - Investigation Status

## Current Status: 🔍 UNDER INVESTIGATION

## What We Know

### ✅ Load Recording Function Works
The debug output shows that `load_recording()` is **working correctly**:
```
load_recording: contents length = 539733
load_recording: content_type = data:application/json;base64
load_recording: decoded length = 404776
load_recording: JSON parsed successfully, keys = ['audio', 'tempo', 'beats_per_measure', 'metronome_times', 'beat_times']
load_recording: Successfully processed audio, duration=X.XXs, sr=XXXXX
load_recording: Returning data with X metronome points, X beat points
```

### ⚠️ Mysterious Second Process Call
After successful loading, there's a second `process_audio` call with different audio:
```
process_audio: n_clicks=1, audio_len=404136  # Original recording
process_audio: n_clicks=2, audio_len=142416  # Different audio - WHY?
```

## Possible Causes

### 1. User Interaction After Loading
- User clicks "Play Recording" after loading → triggers audio processing
- User starts a new recording after loading
- User interacts with controls that trigger processing

### 2. Callback Chain Reaction
- `load_recording` updates `audio-store`
- Clientside callback updates `window.lastRecordedAudio`
- Something triggers `audio-data-store` update
- Which triggers `process_audio` callback

### 3. Browser/File Upload Behavior
- Multiple file selection or drag-drop
- Browser auto-processing uploaded files
- File upload component behavior

## Next Steps for Testing

### Test 1: Clean Load Test
1. **Start fresh**: Clear browser cache, restart app
2. **Record**: Make a 5-second recording
3. **Save**: Download the JSON file
4. **Clear**: Delete the recording (start over)
5. **Load**: Upload the saved JSON file
6. **Check console**: Look for the debug output
7. **Observe**: Does waveform appear? Can you play it?

### Test 2: Interaction Test
1. Load a recording successfully
2. **Don't touch anything** - wait 10 seconds
3. Check if `process_audio` gets called again
4. If not, try clicking "Play Recording"
5. Check if that triggers the second process call

### Test 3: Browser Console Investigation
1. Open browser DevTools (F12)
2. Go to Console tab
3. Load a recording
4. Watch for any JavaScript errors or unexpected calls
5. Check Network tab for unexpected requests

## Expected Debug Output

### Success Case
```
load_recording: contents length = XXXXXX
load_recording: content_type = data:application/json;base64
load_recording: decoded length = XXXXXX
load_recording: JSON parsed successfully, keys = ['audio', 'tempo', 'beats_per_measure', 'metronome_times', 'beat_times']
load_recording: Successfully processed audio, duration=X.XXs, sr=XXXXX
load_recording: Returning data with X metronome points, X beat points
```

### Failure Case
```
load_recording: Error loading recording: [specific error message]
```

## What to Look For

### ✅ Good Signs
- `load_recording: JSON parsed successfully`
- `load_recording: Successfully processed audio`
- Waveform appears in the graph
- Status shows "Recording loaded successfully"
- Play button works

### ❌ Bad Signs
- Second `process_audio` call with different audio length
- JavaScript errors in console
- Waveform doesn't update
- Status shows error message
- Play button doesn't work

## Current Hypothesis

The load function is working, but something is triggering a second recording process after loading. This could be:
- User accidentally starting a new recording
- Browser behavior with file uploads
- Callback chain reaction

## Action Required

**Please test the load functionality** and share:
1. The complete console output during loading
2. What you observe on screen (waveform appears? play works?)
3. Any user actions you take after loading

This will help identify the root cause of the "second process call" issue.

---

**Status**: 🔍 AWAITING TEST RESULTS
**Next**: User testing with detailed console logging
