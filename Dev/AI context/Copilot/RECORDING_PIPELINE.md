# Rhythm App - Complete Recording Pipeline

## Architecture Overview

### Components
1. **JavaScript (recorder.js)**
   - `toggleRecording()` - Manages MediaRecorder API
   - `playAudio()` - Plays audio from window.lastRecordedAudio
   - `toggleMetronome()` - Generates metronome tones

2. **HTML/Layout (main.py)**
   - Record, Play, Save, Load buttons
   - Hidden input for audio data (audio-data-store)
   - Hidden button for triggering processing (audio-process-btn)
   - Stores for audio data and visualization

3. **Python Callbacks (main.py)**
   - `process_audio()` - Processes recorded audio, generates waveform
   - `save_recording()` - Downloads processed audio as JSON
   - `load_recording()` - Loads previously saved recordings
   - Button state management callbacks

4. **Clientside Callbacks (Python + JavaScript)**
   - Toggle record button state
   - Toggle metronome button state
   - Sync audio-store to window.lastRecordedAudio for playback

---

## Complete Recording Flow

### Phase 1: Recording
```
User clicks "Start Recording"
    ↓
record-btn.n_clicks incremented
    ↓
Clientside callback: toggleRecording(n_clicks, is_recording)
    ↓
navigator.mediaDevices.getUserMedia({ audio: true })
    ↓
User grants microphone permission
    ↓
mediaRecorder starts recording
    ↓
is-recording value changes to ['recording']
    ↓
record-btn updates: "Stop Recording" (secondary color)
    ↓
User speaks/makes sounds
    ↓
mediaRecorder captures audio in chunks
    ↓
User clicks "Stop Recording"
    ↓
record-btn.n_clicks incremented
    ↓
Clientside callback: toggleRecording(n_clicks, is_recording)
    ↓
mediaRecorder.stop() called
    ↓
mediaRecorder fires "stop" event
```

### Phase 2: Audio Processing
```
MediaRecorder.stop event triggered
    ↓
"stop" event listener (recorder.js line 27)
    ↓
Audio chunks → Blob with type 'audio/wav'
    ↓
FileReader.readAsDataURL(audioBlob)
    ↓
reader.onloadend fires (recorder.js line 32)
    ↓
base64data = reader.result
    ↓
window.lastRecordedAudio = base64data
    ↓
Find: <input id="audio-data-store" /> (recorder.js line 38)
    ↓
Update input.value = base64data
    ↓
Dispatch 'input' and 'change' events
    ↓
Dash detects input value change
    ↓
Wait 100ms (recorder.js line 48)
    ↓
Click audio-process-btn
    ↓
audio-process-btn.n_clicks incremented
    ↓
process_audio() Python callback triggered
```

### Phase 3: Audio Analysis & Visualization
```
process_audio(n_clicks, base64_audio, tempo, beats_per_measure)
    ↓
Validate base64_audio exists
    ↓
Decode base64 data
    ↓
Load with soundfile: y, sr = sf.read()
    ↓
Convert stereo to mono if needed
    ↓
Perform onset strength analysis: librosa.onset.onset_strength()
    ↓
Beat tracking: librosa.beat.beat_track()
    ↓
Get beat times: librosa.frames_to_time()
    ↓
Calculate metronome times from tempo
    ↓
Downsample for display if needed
    ↓
Create waveform figure:
    - Blue line: waveform
    - Red diamond markers: measure downbeats
    - Orange diamonds: other beats
    - Green circles: pulse (detected beat) points
    ↓
Prepare save data dictionary:
    {
        "audio": base64_audio,
        "tempo": tempo,
        "beats_per_measure": beats_per_measure,
        "metronome_times": [...],
        "beat_times": [...]
    }
    ↓
Return:
    - audio_json (JSON stringified save data)
    - figure (Plotly waveform graph)
    - "Recording processed successfully" (status message)
    ↓
Outputs updated:
    - audio-store.data = json.dumps(save_data)
    - waveform-graph.figure = fig
    - status-msg.children = "Recording processed successfully"
```

### Phase 4: Playback Synchronization
```
audio-store.data changes
    ↓
Clientside callback triggers (main.py line 143)
    ↓
JavaScript receives audio_json
    ↓
Parse JSON to get data.audio
    ↓
window.lastRecordedAudio = data.audio
    ↓
Update playback-sync dummy output
```

### Phase 5: Play Recording
```
User clicks "Play Recording"
    ↓
play-btn.n_clicks incremented
    ↓
Clientside callback: playAudio(n_clicks, volume)
    ↓
Check if window.lastRecordedAudio exists
    ↓
Create Audio object: new Audio(base64_data_url)
    ↓
Set audio.volume from playback-vol slider
    ↓
Call audio.play()
    ↓
Browser plays audio to user
```

### Phase 6: Save Recording
```
User clicks "Save Recording"
    ↓
save-btn.n_clicks incremented
    ↓
save_recording() callback triggered
    ↓
Check if audio-store.data exists
    ↓
Return dict:
    {
        "content": audio_json,
        "filename": "recording.json"
    }
    ↓
dcc.Download triggers download
    ↓
Browser saves recording.json file
```

### Phase 7: Load Recording
```
User clicks "Load Recording"
    ↓
Clientside callback (main.py line 361)
    ↓
Simulate click on hidden dcc.Upload input
    ↓
File picker opens
    ↓
User selects recording.json file
    ↓
upload-audio.contents receives file data
    ↓
load_recording() Python callback triggered
    ↓
Parse file content (base64 string)
    ↓
base64 decode to get JSON
    ↓
json.loads() to parse recording data
    ↓
Extract audio and timing information
    ↓
Decode audio and load with soundfile
    ↓
Regenerate waveform figure with loaded data
    ↓
Return:
    - Restored audio data
    - Restored waveform figure
    - "Recording loaded successfully" status message
    ↓
waveform-graph updated with loaded recording
```

---

## Key Technical Details

### Why dcc.Input Instead of html.Input?
- Dash 4.x removed html.Input
- dcc.Input provides React-controlled input component
- Dash properly tracks value changes for callbacks
- Rendering: `<input id="audio-data-store" type="text" />`

### Why Complex Input Update in JavaScript?
- React-controlled inputs have special value setter
- Direct assignment won't trigger Dash callbacks
- Solution: Use native property descriptor to set value
- Dispatch events to signal change

### Audio Format
- MediaRecorder captures as WebM/WAV blob
- Converted to data URL (base64 string)
- Format: `data:audio/wav;base64,<encoded_data>`
- Stored in both window.lastRecordedAudio and audio-store
- Allows playback via Audio API and saving as JSON

### Why Status Messages?
- Users need feedback that processing succeeded
- Helps debugging when issues occur
- Shows in status-msg div above graph

---

## Verification Checklist

✅ JavaScript loads recorder.js from assets
✅ dcc.Input renders with correct selector
✅ Recording triggers button state changes
✅ Audio processing callback receives base64 data
✅ Librosa beat tracking works
✅ Waveform figure generates correctly
✅ Audio-store persists save data
✅ Playback syncs audio to window object
✅ Play button triggers Audio API
✅ Save button downloads JSON
✅ Load button opens file picker
✅ Load callback restores visualization

---

## Status: COMPLETE ✅

All components are properly integrated and tested.
The recording pipeline is fully functional from start to finish.

