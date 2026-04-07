if (!window.dash_clientside) {
    window.dash_clientside = {};
}

let mediaRecorder;
let audioChunks = [];
let audioContext;
let metronomeInterval;
let currentAudio = null;

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
            navigator.mediaDevices.getUserMedia({ audio: true })
                .then(stream => {
                    const types = [
                        'audio/wav',
                        'audio/webm',
                        'audio/webm;codecs=opus',
                        'audio/ogg;codecs=opus',
                        'audio/ogg',
                        'audio/mp4'
                    ];

                    let options = {};
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
                    mediaRecorder.start();
                    audioChunks = [];

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
                    });

                    mediaRecorder.addEventListener("stop", () => {
                        clearTimeout(recordingTimeout);
                        clearTimeout(warningTimeout);
                        console.log("Recording stopped. Processing audio...");

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

    toggleMetronome: function(n_clicks, is_playing, tempo, beatsPerMeasure, volume) {
        console.log("toggleMetronome: n_clicks=", n_clicks, "is_playing=", is_playing, "tempo=", tempo, "beatsPerMeasure=", beatsPerMeasure, "volume=", volume);

        if (!n_clicks) return is_playing;

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
            let beatCount = 0;
            const secondsPerBeat = 60.0 / tempo;

            const playTone = () => {
                try {
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