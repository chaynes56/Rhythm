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
                    mediaRecorder = new MediaRecorder(stream);
                    mediaRecorder.start();
                    audioChunks = [];

                    // Set up automatic stop after 45 seconds (before 60 second timeout)
                    const maxRecordingTime = 45000; // 45 seconds
                    const recordingTimeout = setTimeout(() => {
                        if (mediaRecorder && mediaRecorder.state === 'recording') {
                            console.log("Automatic stop: Recording reached maximum time limit");
                            mediaRecorder.stop();
                            // Stop all tracks to release microphone
                            stream.getTracks().forEach(track => track.stop());
                        }
                    }, maxRecordingTime);

                    mediaRecorder.addEventListener("dataavailable", event => {
                        audioChunks.push(event.data);
                    });

                    mediaRecorder.addEventListener("stop", () => {
                        clearTimeout(recordingTimeout); // Clear the timeout if manually stopped
                        console.log("Recording stopped. Processing audio...");
                        // Try to use the format the browser actually recorded in
                        const mimeType = mediaRecorder.mimeType || 'audio/wav';
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
    }
};
