if (!window.dash_clientside) {
    window.dash_clientside = {};
}

let mediaRecorder;
let audioChunks = [];
let audioContext;
let metronomeInterval;
let currentAudio = null; // Track current playing audio

window.dash_clientside.recorder = {
    toggleRecording: function(n_clicks, is_recording) {
        console.log("toggleRecording: n_clicks=", n_clicks, "is_recording=", is_recording);
        if (!n_clicks) return is_recording;

                if (!is_recording) {
            console.log("Starting recording...");
            navigator.mediaDevices.getUserMedia({ audio: true })
                .then(stream => {
                    // Prefer a more compatible MIME type if possible
                    const types = [
                        'audio/webm;codecs=opus',
                        'audio/ogg;codecs=opus',
                        'audio/webm',
                        'audio/ogg',
                        'audio/mp4',
                        'audio/wav'
                    ];
                    
                    let options = {};
                    for (const type of types) {
                        if (MediaRecorder.isTypeSupported(type)) {
                            console.log("Using supported MIME type:", type);
                            options.mimeType = type;
                            break;
                        }
                    }
                    
                    mediaRecorder = new MediaRecorder(stream, options);
                    mediaRecorder.start();
                    audioChunks = [];

                    // Set up automatic stop after 60 seconds with 5-second warning
                    const maxRecordingTime = 60000; // 60 seconds
                    const warningTime = 55000; // 55 seconds - warn user 5 seconds before stop
                    let warningGiven = false;

                    const recordingTimeout = setTimeout(() => {
                        if (mediaRecorder && mediaRecorder.state === 'recording') {
                            console.log("Automatic stop: Recording reached maximum time limit (60 seconds)");
                            // Play stop beep - half second alert tone
                            window.dash_clientside.recorder.playStopBeep();
                            mediaRecorder.stop();
                            // Stop all tracks to release microphone
                            stream.getTracks().forEach(track => track.stop());
                            // Update UI with auto-stop message
                            window.dash_clientside.recorder.showAutoStopMessage();
                        }
                    }, maxRecordingTime);

                    // Give warning at 55 seconds
                    const warningTimeout = setTimeout(() => {
                        if (mediaRecorder && mediaRecorder.state === 'recording' && !warningGiven) {
                            warningGiven = true;
                            console.log("Warning: Recording will auto-stop in 5 seconds");
                            window.dash_clientside.recorder.playWarningBeep();
                        }
                    }, warningTime);

                    mediaRecorder.addEventListener("dataavailable", event => {
                        audioChunks.push(event.data);
                    });

                    mediaRecorder.addEventListener("stop", () => {
                        clearTimeout(recordingTimeout); // Clear the timeout if manually stopped
                        clearTimeout(warningTimeout); // Clear the warning timeout too
                        console.log("Recording stopped. Processing audio...");
                        
                        // Try to find if we can use a more compatible MIME type
                        let mimeType = mediaRecorder.mimeType || 'audio/webm';
                        console.log("Actual MIME type recorded:", mimeType);
                        
                        const audioBlob = new Blob(audioChunks, { type: mimeType });
                        const reader = new FileReader();
                        reader.readAsDataURL(audioBlob);
                        reader.onloadend = () => {
                            const base64data = reader.result;
                            window.lastRecordedAudio = base64data;
                            console.log("Base64 data created, length:", base64data.length);

                            // Find the input element. dcc.Input with id="audio-data-store"
                            // dcc.Input renders as an input element directly
                            const dataInput = document.querySelector('input[id="audio-data-store"]');

                            if (dataInput) {
                                console.log("Updating audio-data-store...");
                                // This is a hack for React-controlled inputs to trigger Dash's listener
                                const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
                                nativeInputValueSetter.call(dataInput, base64data);
                                dataInput.dispatchEvent(new Event('input', { bubbles: true }));
                                dataInput.dispatchEvent(new Event('change', { bubbles: true }));

                                setTimeout(() => {
                                    const hiddenBtn = document.getElementById('audio-process-btn');
                                    if (hiddenBtn) {
                                        console.log("Clicking audio-process-btn...");
                                        hiddenBtn.click();
                                        // Also try using the button's onclick event
                                        if (hiddenBtn.onclick) {
                                            hiddenBtn.onclick();
                                        }
                                    } else {
                                        console.error("Could not find audio-process-btn element");
                                    }
                                }, 100);
                            } else {
                                console.error("Could not find audio-data-store element.");
                            }
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
                // Stop all tracks to release microphone
                if (mediaRecorder.stream) {
                    mediaRecorder.stream.getTracks().forEach(track => track.stop());
                }
            }
            return false;
        }
    },

    playAudio: function(n_clicks, volume, is_playing) {
        console.log("playAudio: n_clicks=", n_clicks, "volume=", volume, "is_playing=", is_playing, "lastRecordedAudio exists:", !!window.lastRecordedAudio);

        // If currently playing, stop it
        if (is_playing && currentAudio) {
            console.log("Stopping current playback");
            currentAudio.pause();
            currentAudio.currentTime = 0;
            currentAudio = null;
            return false; // Not playing anymore
        }

        // If not playing and we have audio, start playing
        if (!is_playing && window.lastRecordedAudio) {
            currentAudio = new Audio(window.lastRecordedAudio);
            currentAudio.volume = (volume !== undefined && volume !== null) ? volume : 1.0;
            console.log("Playing audio with volume:", currentAudio.volume);

            currentAudio.addEventListener('ended', () => {
                console.log("Audio playback ended");
                currentAudio = null;
                // Note: We can't directly update the Dash state from here
                // The button will be updated when clicked again
            });

            currentAudio.play().catch(err => {
                console.error("Playback error:", err);
                console.error("Error message:", err.message);
                currentAudio = null;
            });

            return true; // Now playing
        } else if (!window.lastRecordedAudio) {
            console.warn("No recording available to play");
        }

        return is_playing; // Return current state if no action taken
    },

    toggleMetronome: function(n_clicks, is_playing, tempo, beatsPerMeasure, volume) {
        if (!n_clicks) return is_playing;

        // Reinitialize or recover AudioContext if needed
        if (!audioContext || audioContext.state === 'closed') {
            console.log("Creating new AudioContext...");
            audioContext = new (window.AudioContext || window.webkitAudioContext)();
        }

        // Resume suspended context
        if (audioContext.state === 'suspended') {
            console.log("Resuming suspended AudioContext...");
            audioContext.resume().then(() => {
                console.log("AudioContext resumed successfully");
            }).catch(err => {
                console.error("Failed to resume AudioContext:", err);
            });
        }

        if (!is_playing) {
            let beatCount = 0;
            const secondsPerBeat = 60.0 / tempo;
            
            const playTone = () => {
                try {
                    // Double-check context state before playing
                    if (audioContext.state === 'closed') {
                        console.error("AudioContext is closed, cannot play tone");
                        return;
                    }

                    if (audioContext.state === 'suspended') {
                        console.log("Context suspended during playback, resuming...");
                        audioContext.resume();
                    }

                    const osc = audioContext.createOscillator();
                    const gain = audioContext.createGain();

                    osc.type = 'sine';
                    osc.frequency.setValueAtTime(beatCount % beatsPerMeasure === 0 ? 220 : 440, audioContext.currentTime);

                    gain.gain.setValueAtTime(volume, audioContext.currentTime);
                    gain.gain.exponentialRampToValueAtTime(0.001, audioContext.currentTime + 0.1);

                    osc.connect(gain);
                    gain.connect(audioContext.destination);

                    osc.start(audioContext.currentTime);
                    osc.stop(audioContext.currentTime + 0.1);

                    beatCount++;
                } catch (err) {
                    console.error("Error playing tone:", err);
                }
            };

            console.log("Starting metronome at", tempo, "BPM");
            playTone();
            metronomeInterval = setInterval(playTone, secondsPerBeat * 1000);
            return true;
        } else {
            if (metronomeInterval) {
                clearInterval(metronomeInterval);
                console.log("Stopped metronome");
            }
            return false;
        }
    },

    playStopBeep: function() {
        /**
         * Play a half-second stop alert beep (low to high frequency sweep)
         */
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
            // Sweep from 800Hz to 1200Hz over half second for alert
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
        /**
         * Play a warning beep to alert user that recording will auto-stop soon
         */
        try {
            if (!audioContext || audioContext.state === 'closed') {
                audioContext = new (window.AudioContext || window.webkitAudioContext)();
            }

            if (audioContext.state === 'suspended') {
                audioContext.resume();
            }

            // Two quick beeps
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

            playBeep(1000, 0);      // First beep at 1000Hz
            playBeep(1200, 0.2);    // Second beep at 1200Hz

            console.log("Played warning beep");
        } catch (err) {
            console.error("Error playing warning beep:", err);
        }
    },

    showAutoStopMessage: function() {
        /**
         * Update UI to show that auto-stop occurred
         * Triggered when recording reaches time limit
         */
        try {
            const statusMsg = document.getElementById('status-msg');
            if (statusMsg) {
                // Create a temporary message that will be overwritten by actual processing
                statusMsg.textContent = 'Auto-stop: Recording reached 60-second limit. Processing audio...';
                console.log("Displayed auto-stop message");
            }
        } catch (err) {
            console.error("Error showing auto-stop message:", err);
        }
    }
};
