if (!window.dash_clientside) {
    window.dash_clientside = {};
}

let mediaRecorder;
let audioChunks = [];
let audioContext;
let metronomeInterval;
let metronomeScheduler = null; // Web Audio scheduler for precise timing
let currentAudio = null;
let metronomeState = {
    beatCount: 0,
    measureCount: 0,
    measuresPerPattern: 1,
    beatsPerMeasure: 4,
    volume: 0.5,
    tempo: 120,
    hiToneOn: true
};
let toneFrequency = {
    low: 220,
    mid: 440,
    high: 880
};

// Diagnostics: Track recording buffer health
let recordingDiagnostics = {
    chunks: [],
    lastChunkTime: 0,
    totalDuration: 0,
    gapDetected: false,
    largestGap: 0
};

function encodeWAV(samples, sampleRate) {
    const buffer = new ArrayBuffer(44 + samples.length * 2);
    const view = new DataView(buffer);

    // WAV header
    const writeString = (offset, string) => {
        for (let i = 0; i < string.length; i++) {
            view.setUint8(offset + i, string.charCodeAt(i));
        }
    };

    writeString(0, 'RIFF');
    view.setUint32(4, 36 + samples.length * 2, true);
    writeString(8, 'WAVE');
    writeString(12, 'fmt ');
    view.setUint32(16, 16, true); // subchunk1Size
    view.setUint16(20, 1, true); // PCM format
    view.setUint16(22, 1, true); // mono
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * 2, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);
    writeString(36, 'data');
    view.setUint32(40, samples.length * 2, true);

    let offset = 44;
    for (let i = 0; i < samples.length; i++, offset += 2) {
        const s = Math.max(-1, Math.min(1, samples[i]));
        view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
    }

    return buffer;
}

window.dash_clientside.recorder = {
    toggleRecording: function(n_clicks, is_recording) {
        console.log("toggleRecording: n_clicks=", n_clicks, "is_recording=", is_recording);
        if (!n_clicks) return is_recording;

        if (!is_recording) {
            console.log("Starting recording...");

            // Auto-start metronome if not already playing
            // If patterns > 1, start at the beginning of the last measure in the pattern
            if (!metronomeInterval) {
                console.log("Auto-starting metronome with recording...");
                const measuresPerPattern = metronomeState.measuresPerPattern || 1;
                if (measuresPerPattern > 1) {
                    // Set up to start at the beginning of the last measure of the pattern
                    metronomeState.beatCount = (measuresPerPattern - 1) * metronomeState.beatsPerMeasure;
                    metronomeState.measureCount = measuresPerPattern - 1;
                    console.log("Pattern offset: starting at measure", metronomeState.measureCount + 1, "of pattern");
                }
                // Trigger metronome start by clicking the button
                const metronomeBtn = document.getElementById('metronome-btn');
                if (metronomeBtn) {
                    metronomeBtn.click();
                }
            }

            // Request specific audio constraints to ensure consistent audio stream
            const audioConstraints = {
                audio: {
                    echoCancellation: false,
                    noiseSuppression: false,
                    autoGainControl: false,
                    sampleRate: 48000  // Standard sample rate; browser will use closest available
                }
            };

            navigator.mediaDevices.getUserMedia(audioConstraints)
                .then(stream => {
                    const types = [
                        'audio/wav',
                        'audio/webm',
                        'audio/webm;codecs=opus',
                        'audio/ogg;codecs=opus',
                        'audio/ogg',
                        'audio/mp4'
                    ];

                    let options = {
                        audioBitsPerSecond: 128000  // Ensure consistent bitrate
                    };
                    let selectedMimeType = null;
                    for (const type of types) {
                        if (MediaRecorder.isTypeSupported(type)) {
                            console.log("Using supported MIME type:", type);
                            selectedMimeType = type;
                            options.mimeType = type;
                            break;
                        }
                    }

                    if (!selectedMimeType) {
                        console.warn("No supported MIME type found, using default");
                    }

                    mediaRecorder = new MediaRecorder(stream, options);

                    // Reset diagnostics for this recording session
                    recordingDiagnostics = {
                        chunks: [],
                        lastChunkTime: Date.now(),
                        totalDuration: 0,
                        gapDetected: false,
                        largestGap: 0
                    };

                    // Use small timeslice to ensure continuous, consistent chunks
                    // This prevents buffer buildup and ensures even audio capture
                    mediaRecorder.start(100);  // 100ms timeslice for consistent chunks
                    audioChunks = [];
                    console.log("MediaRecorder started with timeslice=100ms, constraints:", audioConstraints);

                    const maxRecordingTime = 60000;
                    const warningTime = 55000;
                    let warningGiven = false;

                    const recordingTimeout = setTimeout(() => {
                        if (mediaRecorder && mediaRecorder.state === 'recording') {
                            console.log("Automatic stop: Recording reached maximum time limit (60 seconds)");
                            window.dash_clientside.recorder.playStopBeep();
                            mediaRecorder.stop();
                            stream.getTracks().forEach(track => track.stop());
                            window.dash_clientside.recorder.showAutoStopMessage();
                        }
                    }, maxRecordingTime);

                    const warningTimeout = setTimeout(() => {
                        if (mediaRecorder && mediaRecorder.state === 'recording' && !warningGiven) {
                            warningGiven = true;
                            console.log("Warning: Recording will auto-stop in 5 seconds");
                            window.dash_clientside.recorder.playWarningBeep();
                        }
                    }, warningTime);

                    mediaRecorder.addEventListener("dataavailable", event => {
                        audioChunks.push(event.data);

                        // Diagnostics: Track chunk timing
                        const now = Date.now();
                        const timeSinceLastChunk = now - recordingDiagnostics.lastChunkTime;
                        recordingDiagnostics.chunks.push({
                            size: event.data.size,
                            timeSinceLastChunk: timeSinceLastChunk,
                            timestamp: now
                        });
                        recordingDiagnostics.lastChunkTime = now;
                        recordingDiagnostics.totalDuration += timeSinceLastChunk;

                        // Detect gaps (>250ms would indicate dropout)
                        if (timeSinceLastChunk > 250) {
                            recordingDiagnostics.gapDetected = true;
                            recordingDiagnostics.largestGap = Math.max(recordingDiagnostics.largestGap, timeSinceLastChunk);
                            console.warn(`Recording gap detected: ${timeSinceLastChunk}ms (chunk size: ${event.data.size} bytes)`);
                        }
                    });

                    mediaRecorder.addEventListener("stop", () => {
                        clearTimeout(recordingTimeout);
                        clearTimeout(warningTimeout);
                        console.log("Recording stopped. Processing audio...");

                        // Log buffer diagnostics
                        console.log("=== RECORDING BUFFER DIAGNOSTICS ===");
                        console.log(`Total chunks: ${audioChunks.length}`);
                        console.log(`Total duration: ${recordingDiagnostics.totalDuration}ms`);
                        console.log(`Gap detected: ${recordingDiagnostics.gapDetected}`);
                        console.log(`Largest gap: ${recordingDiagnostics.largestGap}ms`);
                        console.log(`Chunk sizes:`, recordingDiagnostics.chunks.map(c => c.size).join(', '));
                        console.log("====================================");

                        // Convert WebM chunks to PCM and then to WAV
                        const reader = new FileReader();
                        const audioBlob = new Blob(audioChunks, { type: mediaRecorder.mimeType });

                        // Create audio context to decode and re-encode as WAV
                        const audioContext = new (window.AudioContext || window.webkitAudioContext)();
                        reader.readAsArrayBuffer(audioBlob);
                        reader.onloadend = () => {
                            audioContext.decodeAudioData(reader.result, (audioBuffer) => {
                                // Get raw PCM data
                                const rawData = audioBuffer.getChannelData(0); // mono
                                const wavData = encodeWAV(Array.from(rawData), audioBuffer.sampleRate);
                                const wavBlob = new Blob([wavData], { type: 'audio/wav' });

                                const wavReader = new FileReader();
                                wavReader.readAsDataURL(wavBlob);
                                wavReader.onloadend = () => {
                                    window.lastRecordedAudio = wavReader.result;
                                    window.recordedAudioData = wavReader.result;
                                    console.log("Converted to WAV, length:", wavReader.result.length);

                                    const hiddenBtn = document.getElementById('audio-process-btn');
                                    if (hiddenBtn) {
                                        hiddenBtn.click();
                                    }
                                };
                            });
                        };
                    });
                }).catch(err => {
                    console.error("Error accessing microphone:", err);
                    alert("Error accessing microphone: " + err.message);
                });
            return true;
        } else {
            console.log("Stopping recording...");
            if (mediaRecorder && mediaRecorder.state !== "inactive") {
                mediaRecorder.stop();
                if (mediaRecorder.stream) {
                    mediaRecorder.stream.getTracks().forEach(track => track.stop());
                }
            }
            return false;
        }
    },

    playAudio: function(n_clicks, volume, is_playing) {
        console.log("playAudio: n_clicks=", n_clicks, "volume=", volume, "is_playing=", is_playing, "lastRecordedAudio exists:", !!window.lastRecordedAudio);

        // If Dash says playing but the audio already ended, reset state.
        if (is_playing && !currentAudio) {
            return false;
        }

        if (is_playing && currentAudio) {
            console.log("Stopping current playback");
            currentAudio.pause();
            currentAudio.currentTime = 0;
            currentAudio = null;
            return false;
        }

        if (!is_playing && window.lastRecordedAudio) {
            currentAudio = new Audio(window.lastRecordedAudio);
            currentAudio.volume = (volume !== undefined && volume !== null) ? volume : 1.0;
            console.log("Playing audio with volume:", currentAudio.volume);

            currentAudio.addEventListener('ended', () => {
                console.log("Audio playback ended");
                currentAudio = null;
            });

            currentAudio.play().catch(err => {
                console.error("Playback error:", err);
                currentAudio = null;
            });

            return true;
        } else if (!window.lastRecordedAudio) {
            console.warn("No recording available to play");
        }

        return is_playing;
    },

    toggleMetronome: function(n_clicks, is_playing, tempo, beatsPerMeasure, measuresPerPattern, volume, hiToneOn) {
        console.log("toggleMetronome: n_clicks=", n_clicks, "is_playing=", is_playing, "tempo=", tempo,
                    "beatsPerMeasure=", beatsPerMeasure, "measuresPerPattern=", measuresPerPattern,
                    "volume=", volume, "hiToneOn=", hiToneOn);

        if (!n_clicks) return is_playing;

        // Defensive defaults to avoid silent output from undefined/null state values.
        tempo = Number.isFinite(tempo) ? tempo : 120;
        beatsPerMeasure = Number.isFinite(beatsPerMeasure) ? beatsPerMeasure : 4;
        measuresPerPattern = Number.isFinite(measuresPerPattern) ? measuresPerPattern : 1;
        volume = Number.isFinite(volume) ? volume : 0.5;
        hiToneOn = (hiToneOn !== false);

        // Store current state for later use
        metronomeState.tempo = tempo;
        metronomeState.beatsPerMeasure = beatsPerMeasure;
        metronomeState.measuresPerPattern = measuresPerPattern;
        metronomeState.volume = volume;
        metronomeState.hiToneOn = hiToneOn;

        if (!audioContext || audioContext.state === 'closed') {
            console.log("Creating new AudioContext...");
            audioContext = new (window.AudioContext || window.webkitAudioContext)();
        }

        if (audioContext.state === 'suspended') {
            console.log("Resuming suspended AudioContext...");
            audioContext.resume().then(() => {
                console.log("AudioContext resumed successfully");
            }).catch(err => {
                console.error("Failed to resume AudioContext:", err);
            });
        }

        if (!is_playing) {
            metronomeState.beatCount = 0;
            metronomeState.measureCount = 0;
            const secondsPerBeat = 60.0 / tempo;

            // Warm up the context and prepare for scheduling
            console.log(`Starting metronome with Web Audio scheduler at ${tempo} BPM (${secondsPerBeat.toFixed(3)}s per beat)`);

            const playTone = (scheduledTime = null) => {
                try {
                    if (audioContext.state === 'closed') {
                        console.error("AudioContext is closed, cannot play tone");
                        return;
                    }

                    if (audioContext.state === 'suspended') {
                        console.log("Context suspended during playback, resuming...");
                        audioContext.resume();
                    }

                    const toneTime = (Number.isFinite(scheduledTime) && scheduledTime >= audioContext.currentTime)
                        ? scheduledTime
                        : audioContext.currentTime;

                    const osc = audioContext.createOscillator();
                    const gain = audioContext.createGain();

                    let frequency = toneFrequency.high;
                    let shouldPlay = true;

                    const positionInMeasure = metronomeState.beatCount % metronomeState.beatsPerMeasure;
                    const positionInPattern = metronomeState.measureCount % metronomeState.measuresPerPattern;

                    // Determine tone type
                    if (positionInMeasure === 0 && positionInPattern === 0) {
                        // First beat of pattern: low tone
                        frequency = toneFrequency.low;
                    } else if (positionInMeasure === 0) {
                        // First beat of measure (not pattern start): mid-tone
                        frequency = toneFrequency.mid;
                    } else if (!metronomeState.hiToneOn) {
                        // Not a measure-start beat and hi-tone is off: silence
                        shouldPlay = false;
                    }

                    if (shouldPlay) {
                        osc.type = 'sine';
                        osc.frequency.setValueAtTime(frequency, toneTime);

                        gain.gain.setValueAtTime(metronomeState.volume, toneTime);
                        gain.gain.exponentialRampToValueAtTime(0.001, toneTime + 0.1);

                        osc.connect(gain);
                        gain.connect(audioContext.destination);

                        osc.start(toneTime);
                        osc.stop(toneTime + 0.1);
                    }

                    metronomeState.beatCount++;
                    if (metronomeState.beatCount % metronomeState.beatsPerMeasure === 0) {
                        metronomeState.measureCount++;
                    }
                } catch (err) {
                    console.error("Error playing tone:", err);
                }
            };

            // Play first beat immediately to minimize startup delay
            playTone();

            // Use Web Audio scheduler for subsequent beats (much more accurate than setInterval)
            // Schedule next beat times using audioContext.currentTime for precise timing
            let nextScheduledTime = audioContext.currentTime + secondsPerBeat;

            metronomeScheduler = setInterval(() => {
                try {
                    const now = audioContext.currentTime;
                    // Schedule all beats that are due (handles brief interruptions)
                    while (nextScheduledTime <= now + 0.050) {  // 50ms lookahead
                        // Always trigger each due beat exactly once.
                        // If overdue, play immediately; if in lookahead window, schedule precisely.
                        playTone(nextScheduledTime);
                        nextScheduledTime += secondsPerBeat;
                    }
                } catch (err) {
                    console.error("Error in metronome scheduler:", err);
                }
            }, secondsPerBeat * 500);  // Check frequency: half the beat interval for precision

            metronomeInterval = metronomeScheduler; // Keep for compatibility
            return true;
        } else {
            if (metronomeInterval) {
                clearInterval(metronomeInterval);
                metronomeInterval = null;
                metronomeScheduler = null;
                console.log("Stopped metronome");
            }
            return false;
        }
    },

    playStopBeep: function() {
        try {
            if (!audioContext || audioContext.state === 'closed') {
                audioContext = new (window.AudioContext || window.webkitAudioContext)();
            }

            if (audioContext.state === 'suspended') {
                audioContext.resume();
            }

            const osc = audioContext.createOscillator();
            const gain = audioContext.createGain();

            osc.type = 'sine';
            osc.frequency.setValueAtTime(800, audioContext.currentTime);
            osc.frequency.linearRampToValueAtTime(1200, audioContext.currentTime + 0.5);

            gain.gain.setValueAtTime(0.5, audioContext.currentTime);
            gain.gain.exponentialRampToValueAtTime(0.01, audioContext.currentTime + 0.5);

            osc.connect(gain);
            gain.connect(audioContext.destination);

            osc.start(audioContext.currentTime);
            osc.stop(audioContext.currentTime + 0.5);

            console.log("Played stop beep");
        } catch (err) {
            console.error("Error playing stop beep:", err);
        }
    },

    playWarningBeep: function() {
        try {
            if (!audioContext || audioContext.state === 'closed') {
                audioContext = new (window.AudioContext || window.webkitAudioContext)();
            }

            if (audioContext.state === 'suspended') {
                audioContext.resume();
            }

            const playBeep = (frequency, delay) => {
                const osc = audioContext.createOscillator();
                const gain = audioContext.createGain();

                osc.type = 'sine';
                osc.frequency.setValueAtTime(frequency, audioContext.currentTime + delay);

                gain.gain.setValueAtTime(0.3, audioContext.currentTime + delay);
                gain.gain.exponentialRampToValueAtTime(0.01, audioContext.currentTime + delay + 0.15);

                osc.connect(gain);
                gain.connect(audioContext.destination);

                osc.start(audioContext.currentTime + delay);
                osc.stop(audioContext.currentTime + delay + 0.15);
            };

            playBeep(1000, 0);
            playBeep(1200, 0.2);

            console.log("Played warning beep");
        } catch (err) {
            console.error("Error playing warning beep:", err);
        }
    },

    showAutoStopMessage: function() {
        try {
            const statusMsg = document.getElementById('status-msg');
            if (statusMsg) {
                statusMsg.textContent = 'Auto-stop: Recording reached 60-second limit. Processing audio...';
                console.log("Displayed auto-stop message");
            }
        } catch (err) {
            console.error("Error showing auto-stop message:", err);
        }
    }
};

console.log("recorder.js loaded successfully. window.dash_clientside.recorder is ready.");