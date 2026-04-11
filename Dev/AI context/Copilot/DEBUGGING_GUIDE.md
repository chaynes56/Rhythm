# Rhythm App - Debugging Guide

## Browser Console Logs to Monitor

When testing, open Browser Developer Tools (F12) and check the Console tab for these logs:

### Recording Flow
```javascript
toggleRecording: n_clicks=1, is_recording=false
Starting recording...
toggleRecording: n_clicks=2, is_recording=true
Stopping recording...
Recording stopped. Processing audio...
Updating audio-data-store...
Clicking audio-process-btn...
```

### Playback Flow
```javascript
playAudio: n_clicks=1, volume=1.0, lastRecordedAudio exists: true
Playing audio with volume: 1.0
```

### Expected Python Console Output
```
process_audio: n_clicks=1, audio_len=XXXXX
Recording processed successfully
```

---

## Common Issues & Solutions

### Issue: "Could not find audio-data-store element."
**Symptoms**: Nothing happens after recording stops, no waveform displayed
**Cause**: DOM selector can't find input element
**Solution**:
1. Open Browser DevTools (F12)
2. Go to Console tab
3. Run: `document.querySelector('input[id="audio-data-store"]')`
4. Should return the input element, not null
5. Check browser console for error messages

**Check**: The selector `input[id="audio-data-store"]` should NOT use `#audio-data-store input`

### Issue: "No recording available to play"
**Symptoms**: Click Play button, nothing happens
**Cause**: window.lastRecordedAudio is not set
**Solution**:
1. Make sure a recording was successfully completed
2. Check Browser Console for "Updating audio-data-store..." message
3. Verify: `window.lastRecordedAudio` exists in console
4. Check if audio data was processed (look for "Recording processed successfully" message)

### Issue: Waveform shows but no metronome/pulse markers
**Symptoms**: Blue waveform visible, but no colored markers
**Cause**: Beat tracking failed or tempo setting issue
**Solution**:
1. Try a different tempo value
2. Ensure recording has clear audio (not just silence)
3. Check Python console for librosa errors
4. Verify beats_per_measure is set correctly (1-16)

### Issue: Save button downloads empty file
**Symptoms**: Download works but file is invalid or empty
**Cause**: audio-store data not populated
**Solution**:
1. Ensure recording was processed (waveform visible)
2. Check that status message shows "Recording processed successfully"
3. In Browser Console, verify: `dash._stores['audio-store'].data` has content
4. Try recording again and immediately save

### Issue: Load button doesn't open file picker
**Symptoms**: Click Load Recording, nothing happens
**Cause**: Upload input selector issue
**Solution**:
1. Open Browser DevTools (F12)
2. Check Console for errors
3. Run: `document.querySelector('#upload-audio input')`
4. Should return upload input element
5. Manually test: `document.querySelector('#upload-audio input').click()`

---

## Network & Browser Console Checks

### Check Clientside Callback Execution
In Browser Console:
```javascript
// Should show these functions exist
window.dash_clientside.recorder.toggleRecording
window.dash_clientside.recorder.playAudio
window.dash_clientside.recorder.toggleMetronome

// Test toggle recording manually
window.dash_clientside.recorder.toggleRecording(1, false)  // Should return true (start)
window.dash_clientside.recorder.toggleRecording(2, true)   // Should return false (stop)
```

### Check Dash Callback Execution
Check Network tab in DevTools (F12):
1. Look for XHR/Fetch requests
2. After recording stops, should see callback requests
3. Response should contain processed audio and figure data
4. Status should be 200 OK

### Check Audio Data Format
In Browser Console:
```javascript
// Get last recorded audio sample
window.lastRecordedAudio.substring(0, 100)
// Should start with: "data:audio/wav;base64,UklGR..."
```

---

## Performance Considerations

### Large Recording Issues
If recording is very long (>1 minute):

1. **Audio Processing**: May take 5-10 seconds
   - Look for "Recording processed successfully" message
   - Graph downsampling happens automatically for >10k samples
   - This is normal - wait for processing to complete

2. **Browser Memory**: Very long recordings (>10 minutes)
   - May slow down playback
   - Consider splitting into smaller recordings
   - Save after each segment

3. **Metronome Points**: For very long recordings
   - Many markers may clutter the graph
   - Use graph zoom/pan controls
   - Adjust tempo to change marker density

---

## Step-by-Step Testing Procedure

### Test 1: Basic Recording & Display
```
1. Load app in browser
2. Click "Start Recording"
3. Speak clearly for 5-10 seconds
4. Click "Stop Recording"
5. ✓ Waveform should appear immediately
6. ✓ Should see "Recording processed successfully" message
7. ✓ Blue line = waveform
8. ✓ Red diamond = measure downbeat (beat 1)
9. ✓ Orange diamonds = other beats
10. ✓ Green circles = pulse points (detected beats)
```

### Test 2: Playback with Volume Control
```
1. After recording displays (from Test 1)
2. Drag "Playback" volume slider to 0.5
3. Click "Play Recording"
4. ✓ Audio plays at 50% volume
5. Drag slider to 1.0
6. Click "Play Recording" again
7. ✓ Audio plays at 100% volume
8. Verify volume changes correctly
```

### Test 3: Save & Load
```
1. After recording displays (from Test 1)
2. Click "Save Recording"
3. ✓ JSON file downloads (recording.json)
4. Click "Load Recording"
5. ✓ File picker opens
6. Select the saved recording.json
7. ✓ Waveform reappears with all markers
8. ✓ Status message shows "Recording loaded successfully"
9. Click "Play Recording"
10. ✓ Audio plays correctly
```

### Test 4: Metronome
```
1. On app home page
2. Set Tempo to 120 BPM
3. Set Beats per Measure to 4
4. Set Metronome Volume to 0.5
5. Click "Start Metronome"
6. ✓ Should hear: LOW tone, HIGH tone, HIGH tone, HIGH tone, repeat
7. ✓ Button changes to "Stop Metronome" (secondary color)
8. Change Tempo to 180
9. ✓ Tones play faster
10. Click "Stop Metronome"
11. ✓ Tones stop, button returns to "Start Metronome"
```

---

## Quick Reference: File Locations

| Component | File | Key Lines |
|-----------|------|-----------|
| Main app | `app/main.py` | 1-375 |
| JavaScript | `app/assets/recorder.js` | 1-140 |
| Recording toggle | main.py | 85-97 |
| Play button | main.py | 99-108 |
| Audio processing | main.py | 166-266 |
| Save recording | main.py | 268-277 |
| Load recording | main.py | 279-357 |
| Metronome | main.py | 110-124 |
| Input selector fix | recorder.js | 38 |
| Play function | recorder.js | 80-94 |

---

## Error Messages You Might See

### "No audio data to process"
- Recording didn't complete successfully
- Check browser console for MediaRecorder errors
- Verify microphone permission was granted

### "Error processing audio: <error>"
- Librosa beat tracking failed
- Usually due to poor audio quality
- Try recording in quieter environment
- Check Python console for full error

### "Error: Uploaded file is not a valid JSON recording"
- File was not saved by this app
- Use only files downloaded from "Save Recording"
- Check file extension is .json

### "Error loading recording: <error>"
- Corrupted save file
- Re-record and save again
- Check console for details

---

## When Everything Fails: Reset Steps

1. Clear browser cache (Ctrl+Shift+Delete)
2. Close and reopen browser
3. Reload app page (F5)
4. Stop app: Ctrl+C in terminal
5. Start app fresh: `python app/main.py`
6. Try simple 2-3 second recording
7. Check browser console for any errors
8. Check Python console for processing logs

---

## Tips for Clean Recordings

1. **Quiet Environment**: Minimize background noise
2. **Consistent Volume**: Maintain steady speaking/playing volume
3. **Clear Sounds**: Play clear, distinct beats or strokes
4. **Duration**: 5-30 seconds is ideal for beat tracking
5. **Avoid Silence**: Minimize long silent parts
6. **Microphone**: Use device's built-in mic or USB mic
7. **Browser**: Chrome, Edge, Firefox all support MediaRecorder

---

Status: Complete ✓ All debugging guides in place

