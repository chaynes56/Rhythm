if (!window.dash_clientside) {
    window.dash_clientside = {};
}

const METRONOME_TONE_DURATION_S = 0.04; // seconds
// start recording this many ms before measure end to let audio startup settle
const RECORDING_PRE_ROLL_MS = 200;

let mediaRecorder;
let audioChunks = [];
let audioContext;
let metronomeInterval;
let metronomeScheduler = null; // Web Audio scheduler for precise timing
let currentAudio = null;
let lastPlayNClicks = null;  // null = not yet seen; sync to current n_clicks on first call
let activeMetronomeNodes = [];
let activeMetronomeAudios = [];
let metronomeClickBuffers = null;
let metronomeBufferContext = null;
let metronomeAudioUrls = null;
let metronomeAutoStartedByRecording = false;
let preserveMetronomeStartOffset = false;
let recordingDelayTimeout = null;
let recordingTimeout = null;
let recordingWarningTimeout = null;
let recordingStream = null;
let pendingRecordingRequestId = 0;
let currentRecordingPhase = 'idle';
let metronomeState = {
    beatCount: 0,
    measureCount: 0,
    measuresPerPattern: 1,
    beatsPerMeasure: 4,
    volume: 0.5,
    tempo: 120,
    hiToneOn: true,
    onlyLowTone: false
};
let toneFrequency = {
    low: 294,
    mid: 440,
    high: 587
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

function cleanupMetronomeNode(nodeRecord) {
    activeMetronomeNodes = activeMetronomeNodes.filter(node => node !== nodeRecord);
}

function cleanupMetronomeAudio(audio) {
    activeMetronomeAudios = activeMetronomeAudios.filter(item => item !== audio);
}

function clickHiddenButton(buttonId) {
    const button = document.getElementById(buttonId);
    if (!button) {
        return;
    }

    button.click();
}

function setDashInputValue(elementId, value) {
    const input = document.getElementById(elementId);
    if (!input) {
        console.warn(`Missing Dash sync input: ${elementId}`);
        return;
    }

    const nextValue = value == null ? '' : String(value);
    const prototype = Object.getPrototypeOf(input);
    const valueSetter = Object.getOwnPropertyDescriptor(prototype, 'value')?.set
        || Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;

    if (valueSetter) {
        valueSetter.call(input, nextValue);
    } else {
        input.value = nextValue;
    }

    input.dispatchEvent(new Event('input', {bubbles: true}));
    input.dispatchEvent(new Event('change', {bubbles: true}));
}

function setRecordingPhase(phase) {
    currentRecordingPhase = phase || 'idle';
    setDashInputValue('recording-phase-sync', currentRecordingPhase);
}

function setMetronomePlayingState(isPlaying) {
    setDashInputValue('metronome-state-sync', isPlaying ? 'playing' : '');
    if (!isPlaying) {
        resetBeatIndicators();
    }
}

function resetBeatIndicators() {
    const beatsPerMeasure = Math.max(1, Number(metronomeState.beatsPerMeasure) || 1);
    const measuresPerPattern = Math.max(1, Number(metronomeState.measuresPerPattern) || 1);
    for (let m = 0; m < measuresPerPattern; m++) {
        for (let b = 0; b < beatsPerMeasure; b++) {
            const box = document.getElementById(`beat-box-${m}-${b}`);
            if (!box) {
                continue;
            }
            box.style.backgroundColor = '#f8f9fa';
            box.style.color = '#495057';
            box.style.borderColor = '#adb5bd';
        }
    }
}

function highlightBeatIndicator(activeMeasureIndex, activeBeatIndex) {
    const beatsPerMeasure = Math.max(1, Number(metronomeState.beatsPerMeasure) || 1);
    const measuresPerPattern = Math.max(1, Number(metronomeState.measuresPerPattern) || 1);
    for (let m = 0; m < measuresPerPattern; m++) {
        for (let b = 0; b < beatsPerMeasure; b++) {
            const box = document.getElementById(`beat-box-${m}-${b}`);
            if (!box) {
                continue;
            }

            if (m === activeMeasureIndex && b === activeBeatIndex) {
                box.style.backgroundColor = '#198754';
                box.style.color = '#ffffff';
                box.style.borderColor = '#198754';
            } else {
                box.style.backgroundColor = '#f8f9fa';
                box.style.color = '#495057';
                box.style.borderColor = '#adb5bd';
            }
        }
    }
}

function clearRecordingTimers() {
    if (recordingDelayTimeout) {
        clearTimeout(recordingDelayTimeout);
        recordingDelayTimeout = null;
    }
    if (recordingTimeout) {
        clearTimeout(recordingTimeout);
        recordingTimeout = null;
    }
    if (recordingWarningTimeout) {
        clearTimeout(recordingWarningTimeout);
        recordingWarningTimeout = null;
    }
}

function cleanupRecordingStream() {
    if (recordingStream) {
        try {
            recordingStream.getTracks().forEach(track => track.stop());
        } catch (err) {
            console.warn('Error stopping recording stream:', err);
        }
        recordingStream = null;
    }
}

function ensureAudioContext() {
    if (!audioContext || audioContext.state === 'closed') {
        console.log('Creating new AudioContext...');
        audioContext = new (window.AudioContext || window['webkitAudioContext'])();
    }
    return audioContext;
}

function updateMetronomeState(tempo, beatsPerMeasure, measuresPerPattern, volume, hiToneOn, onlyLowTone) {
    const parsedTempo = Number(tempo);
    const parsedBeats = Number(beatsPerMeasure);
    const parsedMeasures = Number(measuresPerPattern);
    const parsedVolume = Number(volume);

    metronomeState.tempo = Number.isFinite(parsedTempo) && parsedTempo > 0 ? parsedTempo : 120;
    metronomeState.beatsPerMeasure = Number.isFinite(parsedBeats) && parsedBeats > 0 ? parsedBeats : 4;
    metronomeState.measuresPerPattern = Number.isFinite(parsedMeasures) && parsedMeasures > 0 ? parsedMeasures : 1;
    metronomeState.volume = Number.isFinite(parsedVolume) ? parsedVolume : 0.5;
    metronomeState.hiToneOn = (hiToneOn !== false);
    metronomeState.onlyLowTone = !!onlyLowTone;
}

function getMetronomeBeatState() {
    const positionInMeasure = metronomeState.beatCount % metronomeState.beatsPerMeasure;
    const positionInPattern = metronomeState.measureCount % metronomeState.measuresPerPattern;

    let toneKey = 'high';
    let shouldPlay = true;

    if (positionInMeasure === 0 && positionInPattern === 0) {
        toneKey = 'low';
    } else if (positionInMeasure === 0) {
        toneKey = 'mid';
        if (metronomeState.onlyLowTone) shouldPlay = false;
    } else {
        if (metronomeState.onlyLowTone || !metronomeState.hiToneOn) shouldPlay = false;
    }

    return {positionInMeasure, toneKey, shouldPlay};
}

function advanceMetronomePosition(positionInMeasure) {
    const positionInPattern = metronomeState.measureCount % metronomeState.measuresPerPattern;
    highlightBeatIndicator(positionInPattern, positionInMeasure);
    metronomeState.beatCount += 1;
    if (metronomeState.beatCount % metronomeState.beatsPerMeasure === 0) {
        metronomeState.measureCount += 1;
    }
}

function playScheduledTone(scheduledTime = null) {
    try {
        const ctx = ensureAudioContext();
        if (ctx.state === 'closed') {
            console.error('AudioContext is closed, cannot play tone');
            return;
        }

        ensureMetronomeClickBuffers(ctx);

        const {positionInMeasure, toneKey, shouldPlay} = getMetronomeBeatState();
        const toneTime = (Number.isFinite(scheduledTime) && scheduledTime >= ctx.currentTime)
            ? scheduledTime
            : ctx.currentTime;

        if (shouldPlay) {
            const source = ctx.createBufferSource();
            const gain = ctx.createGain();

            source.buffer = metronomeClickBuffers[toneKey];

            gain.gain.cancelScheduledValues(toneTime);
            gain.gain.setValueAtTime(0.0001, toneTime);
            gain.gain.linearRampToValueAtTime(metronomeState.volume, toneTime + 0.005);
            gain.gain.exponentialRampToValueAtTime(0.0001, toneTime + METRONOME_TONE_DURATION_S);

            source.connect(gain);
            gain.connect(ctx.destination);

            const nodeRecord = {source, gain, onEnded: null};
            const onEnded = () => {
                try {
                    source.disconnect();
                    gain.disconnect();
                } catch (disconnectErr) {
                    console.warn('Metronome node disconnect warning:', disconnectErr);
                }
                cleanupMetronomeNode(nodeRecord);
            };
            nodeRecord.onEnded = onEnded;
            activeMetronomeNodes.push(nodeRecord);
            source.addEventListener('ended', onEnded);

            source.start(toneTime);
        }

        advanceMetronomePosition(positionInMeasure);
    } catch (err) {
        console.error('Error playing tone:', err);
    }
}

function playHtmlTone() {
    try {
        ensureMetronomeAudioUrls();
        const {positionInMeasure, toneKey, shouldPlay} = getMetronomeBeatState();

        if (shouldPlay) {
            const audio = new Audio();
            audio.src = /** @type {string} */ (metronomeAudioUrls[toneKey]);
            audio.preload = 'auto';
            audio.volume = metronomeState.volume;
            // Add playsinline just in case, though it's for video
            audio.setAttribute('playsinline', 'true');
            activeMetronomeAudios.push(audio);
            audio.addEventListener('ended', () => cleanupMetronomeAudio(audio), {once: true});
            const playPromise = audio.play();
            if (playPromise !== undefined) {
                playPromise.catch(err => {
                    console.error('HTMLAudio metronome playback error:', err);
                    cleanupMetronomeAudio(audio);
                });
            }
        }

        advanceMetronomePosition(positionInMeasure);
    } catch (err) {
        console.error('Error playing HTMLAudio metronome tone:', err);
    }
}

function stopMetronomePlayback() {
    if (metronomeInterval) {
        clearInterval(metronomeInterval);
    }
    metronomeInterval = null;
    metronomeScheduler = null;

    activeMetronomeNodes.forEach(({source, gain, onEnded}) => {
        try {
            if (onEnded) source.removeEventListener('ended', onEnded);
            source.stop();
        } catch (stopErr) {
            console.warn('Metronome node stop warning:', stopErr);
        }
        try {
            source.disconnect();
            gain.disconnect();
        } catch (disconnectErr) {
            console.warn('Metronome node disconnect warning:', disconnectErr);
        }
    });
    activeMetronomeNodes = [];

    activeMetronomeAudios.forEach(audio => {
        try {
            audio.pause();
            audio.currentTime = 0;
        } catch (audioErr) {
            console.warn('Metronome audio stop warning:', audioErr);
        }
    });
    activeMetronomeAudios = [];

    preserveMetronomeStartOffset = false;
    setMetronomePlayingState(false);
    console.log('Stopped metronome');
}

function startMetronomePlayback(options = {}) {
    const {preserveOffset = false} = options;
    const ctx = ensureAudioContext();
    const secondsPerBeat = 60.0 / metronomeState.tempo;
    const useHtmlAudioMetronome = shouldUseHtmlAudioMetronome();

    // In Safari, we might need to "unlock" the audio context and HTML audio.
    if (ctx.state === 'suspended') {
        ctx.resume().catch(err => console.warn('AudioContext resume failed:', err));
    }

    const startScheduler = () => {
        if (preserveOffset) {
            console.log('Preserving recording-start metronome offset', {
                beatCount: metronomeState.beatCount,
                measureCount: metronomeState.measureCount
            });
        } else {
            metronomeState.beatCount = 0;
            metronomeState.measureCount = 0;
        }

        preserveMetronomeStartOffset = false;
        resetBeatIndicators();

        console.log(`Starting metronome with Web Audio scheduler at ${metronomeState.tempo} BPM (${secondsPerBeat.toFixed(3)}s per beat)`);

        if (useHtmlAudioMetronome) {
            console.log('Using HTMLAudio metronome fallback', {
                host: window.location ? window.location.hostname : '',
                userAgent: navigator.userAgent || ''
            });
            playHtmlTone();
            let nextScheduledTimeMs = performance.now() + (secondsPerBeat * 1000);

            metronomeScheduler = setInterval(() => {
                try {
                    const nowMs = performance.now();
                    while (nextScheduledTimeMs <= nowMs + 30) {
                        playHtmlTone();
                        nextScheduledTimeMs += secondsPerBeat * 1000;
                    }
                } catch (err) {
                    console.error('Error in HTMLAudio metronome scheduler:', err);
                }
            }, 20);

            metronomeInterval = metronomeScheduler;
            setMetronomePlayingState(true);
            return {firstBeatDelayMs: 0, secondsPerBeat};
        }

        const firstToneDelaySeconds = 0.02;
        const startTime = ctx.currentTime + firstToneDelaySeconds;
        playScheduledTone(startTime);

        let nextBeatIndex = 1;
        metronomeScheduler = setInterval(() => {
            try {
                const now = ctx.currentTime;
                while (startTime + nextBeatIndex * secondsPerBeat <= now + 0.100) {
                    playScheduledTone(startTime + nextBeatIndex * secondsPerBeat);
                    nextBeatIndex++;
                }
            } catch (err) {
                console.error('Error in metronome scheduler:', err);
            }
        }, 25);

        metronomeInterval = metronomeScheduler;
        setMetronomePlayingState(true);
        return {firstBeatDelayMs: firstToneDelaySeconds * 1000, secondsPerBeat};
    };

    if (ctx.state === 'suspended') {
        console.log('Resuming suspended AudioContext before starting metronome...');
        return ctx.resume().then(() => {
            console.log('AudioContext resumed successfully');
            return startScheduler();
        }).catch(err => {
            console.error('Failed to resume AudioContext:', err);
            return {firstBeatDelayMs: 0, secondsPerBeat};
        });
    }

    return Promise.resolve(startScheduler());
}

function buildRecorderOptions() {
    const types = [
        'audio/wav',
        'audio/webm',
        'audio/webm;codecs=opus',
        'audio/ogg;codecs=opus',
        'audio/ogg',
        'audio/mp4'
    ];

    const options = {
        audioBitsPerSecond: 128000
    };

    for (const type of types) {
        if (MediaRecorder.isTypeSupported(type)) {
            console.log('Using supported MIME type:', type);
            options.mimeType = type;
            break;
        }
    }

    if (!options.mimeType) {
        console.warn('No supported MIME type found, using default');
    }

    return options;
}

function configureMediaRecorder(stream) {
    mediaRecorder = new MediaRecorder(stream, buildRecorderOptions());
    audioChunks = [];
    recordingDiagnostics = {
        chunks: [],
        lastChunkTime: Date.now(),
        totalDuration: 0,
        gapDetected: false,
        largestGap: 0
    };

    mediaRecorder.addEventListener('dataavailable', event => {
        audioChunks.push(event.data);

        const now = Date.now();
        const timeSinceLastChunk = now - recordingDiagnostics.lastChunkTime;
        recordingDiagnostics.chunks.push({
            size: event.data.size,
            timeSinceLastChunk: timeSinceLastChunk,
            timestamp: now
        });
        recordingDiagnostics.lastChunkTime = now;
        recordingDiagnostics.totalDuration += timeSinceLastChunk;

        if (timeSinceLastChunk > 250) {
            recordingDiagnostics.gapDetected = true;
            recordingDiagnostics.largestGap = Math.max(recordingDiagnostics.largestGap, timeSinceLastChunk);
            console.warn(`Recording gap detected: ${timeSinceLastChunk}ms (chunk size: ${event.data.size} bytes)`);
        }
    });

    mediaRecorder.addEventListener('stop', () => {
        clearRecordingTimers();
        console.log('Recording stopped. Processing audio...');
        console.log('=== RECORDING BUFFER DIAGNOSTICS ===');
        console.log(`Total chunks: ${audioChunks.length}`);
        console.log(`Total duration: ${recordingDiagnostics.totalDuration}ms`);
        console.log(`Gap detected: ${recordingDiagnostics.gapDetected}`);
        console.log(`Largest gap: ${recordingDiagnostics.largestGap}ms`);
        console.log('Chunk sizes:', recordingDiagnostics.chunks.map(c => c.size).join(', '));
        console.log('====================================');

        const reader = new FileReader();
        const audioBlob = new Blob(audioChunks, {type: mediaRecorder.mimeType});
        const decodeCtx = new (window.AudioContext || window['webkitAudioContext'])();
        reader.readAsArrayBuffer(audioBlob);
        reader.addEventListener('loadend', () => {
            const RECORD_SAMPLE_RATE = 4000;
            const RECORD_LPF_HZ = 1800;
            const arrayBuffer = /** @type {ArrayBuffer} */ (reader.result);
            decodeCtx.decodeAudioData(arrayBuffer).then((audioBuffer) => {
                const targetLength = Math.ceil(audioBuffer.duration * RECORD_SAMPLE_RATE);
                const offlineCtx = new OfflineAudioContext(1, targetLength, RECORD_SAMPLE_RATE);
                const source = offlineCtx.createBufferSource();
                source.buffer = audioBuffer;
                const lpf = offlineCtx.createBiquadFilter();
                lpf.type = 'lowpass';
                lpf.frequency.value = RECORD_LPF_HZ;
                source.connect(lpf);
                lpf.connect(offlineCtx.destination);
                source.start();
                return offlineCtx.startRendering();
            }).then((renderedBuffer) => {
                const rawData = renderedBuffer.getChannelData(0);
                const preRollSamples = Math.round(RECORD_SAMPLE_RATE * RECORDING_PRE_ROLL_MS / 1000);
                const trimmedData = rawData.slice(preRollSamples);
                const wavData = encodeWAV(trimmedData, RECORD_SAMPLE_RATE);
                const wavBlob = new Blob([wavData], {type: 'audio/wav'});

                const wavReader = new FileReader();
                wavReader.readAsDataURL(wavBlob);
                wavReader.addEventListener('loadend', () => {
                    const dataUrl = /** @type {string} */ (wavReader.result);
                    window.lastRecordedAudio = dataUrl;
                    window.recordedAudioData = dataUrl;
                    console.log('Converted to WAV, trimmed pre-roll, length:', dataUrl.length);
                    clickHiddenButton('audio-process-btn');
                });
            }).catch((err) => {
                console.error('decodeAudioData failed:', err);
            }).finally(() => {
                if (decodeCtx && decodeCtx.state !== 'closed') {
                    decodeCtx.close().catch(() => {
                    });
                }
            });
        });
    });
}

function cancelPendingRecording() {
    pendingRecordingRequestId += 1;
    clearRecordingTimers();
    cleanupRecordingStream();
    if (mediaRecorder && mediaRecorder.state !== 'inactive') {
        try {
            mediaRecorder.stop();
        } catch (err) {
            console.warn('Error stopping inactive recorder:', err);
        }
    }
    mediaRecorder = null;

    if (metronomeAutoStartedByRecording) {
        stopMetronomePlayback();
        metronomeAutoStartedByRecording = false;
    }
    setRecordingPhase('idle');
}

function beginActiveRecording(requestId) {
    if (requestId !== pendingRecordingRequestId || currentRecordingPhase !== 'delay' || !mediaRecorder) {
        return;
    }

    try {
        recordingDiagnostics.lastChunkTime = Date.now();
        mediaRecorder.start(100);
        console.log('MediaRecorder started with timeslice=100ms after measure delay');
        setRecordingPhase('recording');

        const maxRecordingTime = 600000;

        recordingTimeout = setTimeout(() => {
            if (mediaRecorder && mediaRecorder.state === 'recording') {
                console.log('Automatic stop: Recording reached maximum time limit (10 minutes)');
                window.recorderControls.playEndAlarm();
                mediaRecorder.stop();
                cleanupRecordingStream();
                if (metronomeAutoStartedByRecording) {
                    stopMetronomePlayback();
                    metronomeAutoStartedByRecording = false;
                }
                setRecordingPhase('idle');
                window.recorderControls.showAutoStopMessage();
            }
        }, maxRecordingTime);
    } catch (err) {
        console.error('Error starting delayed recording:', err);
        cancelPendingRecording();
    }
}

function stopActiveRecording() {
    console.log('Stopping recording...');
    clearRecordingTimers();

    if (mediaRecorder && mediaRecorder.state === 'recording') {
        mediaRecorder.stop();
    }

    cleanupRecordingStream();
    if (metronomeAutoStartedByRecording) {
        stopMetronomePlayback();
        metronomeAutoStartedByRecording = false;
    }
    setRecordingPhase('idle');
}

function startRecordingWithCountIn(tempo, beatsPerMeasure, measuresPerPattern, volume, hiToneOn, onlyLowTone) {
    console.log('Starting recording with measure delay...', {
        tempo,
        beatsPerMeasure,
        measuresPerPattern,
        volume,
        hiToneOn
    });

    setRecordingPhase('delay');
    clearRecordingTimers();
    pendingRecordingRequestId += 1;
    const requestId = pendingRecordingRequestId;

    updateMetronomeState(tempo, beatsPerMeasure, measuresPerPattern, volume, hiToneOn, onlyLowTone);

    const audioConstraints = {
        audio: {
            echoCancellation: false,
            noiseSuppression: false,
            autoGainControl: false,
            sampleRate: {ideal: 48000}
        }
    };

    navigator.mediaDevices.getUserMedia(audioConstraints)
        .then(stream => {
            if (requestId !== pendingRecordingRequestId || currentRecordingPhase !== 'delay') {
                stream.getTracks().forEach(track => track.stop());
                return;
            }

            recordingStream = stream;
            configureMediaRecorder(stream);

            stopMetronomePlayback();
            metronomeAutoStartedByRecording = true;

            const patternMeasures = metronomeState.measuresPerPattern || 1;
            if (patternMeasures > 1) {
                metronomeState.beatCount = (patternMeasures - 1) * metronomeState.beatsPerMeasure;
                metronomeState.measureCount = patternMeasures - 1;
                preserveMetronomeStartOffset = true;
                console.log('Pattern offset: starting at measure', metronomeState.measureCount + 1, 'of pattern');
            } else {
                metronomeState.beatCount = 0;
                metronomeState.measureCount = 0;
                preserveMetronomeStartOffset = false;
            }

            startMetronomePlayback({preserveOffset: patternMeasures > 1}).then(({
                                                                                    firstBeatDelayMs,
                                                                                    secondsPerBeat
                                                                                }) => {
                if (requestId !== pendingRecordingRequestId || currentRecordingPhase !== 'delay') {
                    return;
                }

                const measureDelayMs = firstBeatDelayMs + (metronomeState.beatsPerMeasure * secondsPerBeat * 1000) - RECORDING_PRE_ROLL_MS;
                recordingDelayTimeout = setTimeout(() => beginActiveRecording(requestId), measureDelayMs);
            });
        })
        .catch(err => {
            console.error('Error accessing microphone:', err);
            alert('Error accessing microphone: ' + err.message);
            cancelPendingRecording();
        });
}

function isSafariBrowser() {
    const ua = navigator.userAgent || "";
    return /Safari/i.test(ua) && !/Chrome|Chromium|CriOS|GSA|Firefox|FxiOS|Edg\//i.test(ua);
}

function shouldUseHtmlAudioMetronome() {
    const host = (window.location && window.location.hostname) ? window.location.hostname : "";
    const ua = navigator.userAgent || "";
    const isFirefox = /Firefox|FxiOS/i.test(ua);
    const safariLike = isSafariBrowser();
    const isPlotlyCloud = /(?:^|\.)(?:plotly\.app|dash\.app|plotly\.host)$/i.test(host);
    const useHtmlFallback = safariLike || (isPlotlyCloud && !isFirefox);

    console.log(`shouldUseHtmlAudioMetronome: host=${host}, safariLike=${safariLike}, isPlotlyCloud=${isPlotlyCloud}, isFirefox=${isFirefox}, useHtmlFallback=${useHtmlFallback}`);

    // Safari local works with the HTMLAudio fallback, and Safari on plotly.app
    // may present a UA string that misses the narrower Safari test.
    return useHtmlFallback;
}

function createClickSamples(frequency, duration = METRONOME_TONE_DURATION_S, sampleRate = 44100) {
    const frameCount = Math.floor(sampleRate * duration);
    const samples = new Float32Array(frameCount);

    for (let i = 0; i < frameCount; i++) {
        const t = i / sampleRate;
        const env = Math.exp(-40 * t);
        samples[i] = Math.sin(2 * Math.PI * frequency * t) * env;
    }

    return samples;
}

function ensureMetronomeAudioUrls() {
    if (metronomeAudioUrls) {
        return;
    }

    const buildUrl = (frequency) => {
        const wavBuffer = encodeWAV(createClickSamples(frequency), 44100);
        const blob = new Blob([wavBuffer], {type: 'audio/wav'});
        return URL.createObjectURL(blob);
    };

    metronomeAudioUrls = {
        low: buildUrl(toneFrequency.low),
        mid: buildUrl(toneFrequency.mid),
        high: buildUrl(toneFrequency.high)
    };
}

function createClickBuffer(ctx, frequency, duration = METRONOME_TONE_DURATION_S) {
    const sampleRate = ctx.sampleRate;
    const frameCount = Math.floor(sampleRate * duration);
    const buffer = ctx.createBuffer(1, frameCount, sampleRate);
    const data = buffer.getChannelData(0);

    for (let i = 0; i < frameCount; i++) {
        const t = i / sampleRate;
        // Fast attack, exponential-like decay for a short click.
        const env = Math.exp(-40 * t);
        data[i] = Math.sin(2 * Math.PI * frequency * t) * env;
    }

    return buffer;
}

function ensureMetronomeClickBuffers(ctx) {
    if (metronomeClickBuffers && metronomeBufferContext === ctx) {
        return;
    }

    metronomeClickBuffers = {
        low: createClickBuffer(ctx, toneFrequency.low),
        mid: createClickBuffer(ctx, toneFrequency.mid),
        high: createClickBuffer(ctx, toneFrequency.high)
    };
    metronomeBufferContext = ctx;
}

try {
    window.recorderControls = {
        toggleRecording: function (n_clicks, recordingPhase, tempo, beatsPerMeasure, measuresPerPattern, volume, hiToneOn, onlyLowTone) {
            console.log('toggleRecording: n_clicks=', n_clicks, 'recordingPhase=', recordingPhase);
            if (!n_clicks) {
                return currentRecordingPhase === 'recording';
            }

            const phase = recordingPhase || currentRecordingPhase || 'idle';
            if (phase === 'delay') {
                console.log('Cancelling measure delay');
                cancelPendingRecording();
                return false;
            }

            if (phase === 'recording') {
                stopActiveRecording();
                return false;
            }

            startRecordingWithCountIn(tempo, beatsPerMeasure, measuresPerPattern, volume, hiToneOn, onlyLowTone);
            return true;
        },

        playAudio: function (n_clicks, volume, is_playing) {
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

            // Only start playback on a genuinely new button click. This prevents
            // auto-playback after a hot-reload reconnect, where is_playing resets to
            // false (memory store cleared) but window.lastRecordedAudio still holds
            // the previous recording and the stale n_clicks value re-fires the callback.
            // On the very first call after script load we sync lastPlayNClicks to the
            // current n_clicks without acting, so only a subsequent increment triggers play.
            if (lastPlayNClicks === null) {
                lastPlayNClicks = n_clicks || 0;
                return false;
            }
            if (!is_playing && window.lastRecordedAudio && n_clicks > lastPlayNClicks) {
                lastPlayNClicks = n_clicks;
                currentAudio = new Audio(window.lastRecordedAudio);
                currentAudio.volume = (volume !== undefined && volume !== null) ? volume : 1.0;
                console.log("Playing audio with volume:", currentAudio.volume);

                currentAudio.addEventListener('ended', () => {
                    console.log("Audio playback ended");
                    currentAudio = null;
                    clickHiddenButton('playback-ended-btn');
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

        toggleMetronome: function (n_clicks, is_playing, tempo, beatsPerMeasure, measuresPerPattern, volume, hiToneOn, onlyLowTone) {
            console.log("toggleMetronome: n_clicks=", n_clicks, "is_playing=", is_playing, "tempo=", tempo,
                "beatsPerMeasure=", beatsPerMeasure, "measuresPerPattern=", measuresPerPattern,
                "volume=", volume, "hiToneOn=", hiToneOn, "onlyLowTone=", onlyLowTone);

            if (!n_clicks) return is_playing;

            updateMetronomeState(tempo, beatsPerMeasure, measuresPerPattern, volume, hiToneOn, onlyLowTone);

            if (!is_playing) {
                metronomeAutoStartedByRecording = false;
                stopMetronomePlayback();
                startMetronomePlayback({preserveOffset: false});
                return true;
            }

            metronomeAutoStartedByRecording = false;
            stopMetronomePlayback();
            return false;
        },

        playEndAlarm: function () {
            try {
                if (!audioContext || audioContext.state === 'closed') {
                    audioContext = new (window.AudioContext || window['webkitAudioContext'])();
                }
                if (audioContext.state === 'suspended') {
                    audioContext.resume();
                }
                // Three descending tones — loud and unmistakable
                const tones = [
                    {freq: 1200, delay: 0.0, dur: 0.25},
                    {freq: 900, delay: 0.3, dur: 0.25},
                    {freq: 600, delay: 0.6, dur: 0.5},
                ];
                tones.forEach(({freq, delay, dur}) => {
                    const osc = audioContext.createOscillator();
                    const gain = audioContext.createGain();
                    osc.type = 'square';
                    osc.frequency.setValueAtTime(freq, audioContext.currentTime + delay);
                    gain.gain.setValueAtTime(0.8, audioContext.currentTime + delay);
                    gain.gain.exponentialRampToValueAtTime(0.01, audioContext.currentTime + delay + dur);
                    osc.connect(gain);
                    gain.connect(audioContext.destination);
                    osc.start(audioContext.currentTime + delay);
                    osc.stop(audioContext.currentTime + delay + dur);
                });
                console.log("Played end alarm");
            } catch (err) {
                console.error("Error playing end alarm:", err);
            }
        },

        showAutoStopMessage: function () {
            try {
                const statusMsg = document.getElementById('status-msg');
                if (statusMsg) {
                    statusMsg.textContent = 'Auto-stop: Recording reached 60-second limit. Processing audio...';
                    console.log("Displayed auto-stop message");
                }
            } catch (err) {
                console.error("Error showing auto-stop message:", err);
            }
        },
        reconfigureMetronome: function (isPlaying, tempo, beatsPerMeasure, measuresPerPattern, volume, hiToneOn, onlyLowTone) {
            if (!isPlaying) return;

            // Stop any in-progress recording
            if (currentRecordingPhase === 'recording') {
                stopActiveRecording();
            } else if (currentRecordingPhase === 'delay') {
                cancelPendingRecording();
            }

            updateMetronomeState(tempo, beatsPerMeasure, measuresPerPattern, volume, hiToneOn, onlyLowTone);
            metronomeAutoStartedByRecording = false;
            stopMetronomePlayback();
            startMetronomePlayback({preserveOffset: false});
        },

        triggerPermissionDialog: function () {
            console.log("Triggering permission dialog silently...");
            const audioConstraints = {
                audio: {
                    echoCancellation: false,
                    noiseSuppression: false,
                    autoGainControl: false,
                    sampleRate: {ideal: 48000}
                }
            };

            navigator.mediaDevices.getUserMedia(audioConstraints)
                .then(stream => {
                    console.log("Permission granted or already present (silent trigger)");
                    stream.getTracks().forEach(track => track.stop());
                })
                .catch(err => {
                    console.warn("Silent permission trigger failed (user may have denied):", err);
                });
        }
    };

    // reconfigureMetronome is called from a Dash clientside_callback embedded in main.py
    void window.recorderControls.reconfigureMetronome;
    window.dash_clientside = window.dash_clientside || {};
    window.dash_clientside.recorder = window.recorderControls;
    console.log("recorder.js: recorderControls initialized successfully.");

// Trigger permission dialog on load
    if (typeof window !== 'undefined') {
        window.addEventListener('load', () => {
            setTimeout(() => {
                if (window.recorderControls && window.recorderControls.triggerPermissionDialog) {
                    window.recorderControls.triggerPermissionDialog();
                }
            }, 1000); // Short delay to ensure browser context is ready
        });
    }
} catch (initErr) {
    console.error("recorder.js: CRITICAL - failed to initialize recorder namespace:", initErr, initErr.stack);
    // Install stubs so Dash doesn't cascade-crash on undefined.method() calls
    window.recorderControls = {
        toggleRecording: function () {
            console.error("recorder not initialized");
            return false;
        },
        playAudio: function () {
            console.error("recorder not initialized");
            return false;
        },
        toggleMetronome: function () {
            console.error("recorder not initialized");
            return false;
        },
        playEndAlarm: function () {
        },
        showAutoStopMessage: function () {
        }
    };
    window.dash_clientside = window.dash_clientside || {};
    window.dash_clientside.recorder = window.recorderControls;
}

console.log("recorder.js loaded successfully. recorderControls is ready.");
