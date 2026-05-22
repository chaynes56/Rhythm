if (!window.dash_clientside) {
    window.dash_clientside = {};
}

// Suppress noisy Plotly/React internal warnings that are not actionable.
(function() {
    var SUPPRESS = [
        'Support for defaultProps will be removed from function components',
        "Can't perform a React state update on a component that hasn't mounted yet",
    ];
    var _warn = console.warn.bind(console);
    var _error = console.error.bind(console);
    function shouldSuppress(args) {
        var msg = args[0];
        if (typeof msg !== 'string') return false;
        return SUPPRESS.some(function(s) { return msg.indexOf(s) !== -1; });
    }
    console.warn  = function() { if (!shouldSuppress(arguments)) _warn.apply(console, arguments); };
    console.error = function() { if (!shouldSuppress(arguments)) _error.apply(console, arguments); };
}());

// Timing constants
const INITIAL_WARMUP_SECONDS = 4;      // silent warmup duration on page load (Stage 2)
const FIRST_TONE_DELAY_SECONDS = 0.15; // scheduling buffer before first audio tone
const MIN_COUNT_IN_PERIOD_SEC = 3;     // minimum count-in duration before recording starts

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
let metronomeAutoStartedByRecording = false;
let lastToggleTimestamp = 0;
let lastToggleWasStart = false;
let preserveMetronomeStartOffset = false;
let metronomeTrackBuffer = null;
let metronomeDecodePromise = null;  // shared Promise to avoid concurrent duplicate decodes
let calibrationTrackBuffer = null;
let calibrationDecodePromise = null;
let calibrationFirstBeatMs = 0;
let warmupCompleted = false;
let metronomeSourceNode = null;
let metronomeGainNode = null;
let pendingMetronomeTrackUrl = null;
let pendingStart = false;
let recordingDelayTimeout = null;
let recordingTimeout = null;
let recordingWarningTimeout = null;
let recordingStream = null;
let pendingRecordingRequestId = 0;
let currentRecordingPhase = 'idle';
let calibrationMode = false;
let calibrationWarmupMeasures = 3;  // 3 for auto-cal (cold pipeline), 1 for manual (already warm)
let calibrationRecordingEnded = false;  // snapshotted synchronously so stop-event handler routes correctly
let exerciseSchedule = null;  // null = free mode; set to {schedule, duration, spb} in exercise mode
let lastExerciseCellId = null;
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
    const btn = document.getElementById('metronome-btn');
    if (btn) {
        btn.textContent = isPlaying ? 'Stop Metronome' : 'Start Metronome';
        btn.disabled = false;
        btn.className = btn.className
            .replace(/\bbtn-primary\b/g, '')
            .replace(/\bbtn-secondary\b/g, '')
            .replace(/\bbtn-warning\b/g, '')
            .trim() + (isPlaying ? ' btn-secondary' : ' btn-primary');
    }
    if (!isPlaying) {
        resetBeatIndicators();
    }
}

function setMetronomeWarmingUpState(isWarmingUp) {
    const btn = document.getElementById('metronome-btn');
    if (!btn) return;
    if (isWarmingUp) {
        btn.textContent = 'Warming Up...';
        btn.disabled = false;
        btn.className = btn.className
            .replace(/\bbtn-primary\b/g, '')
            .replace(/\bbtn-secondary\b/g, '')
            .replace(/\bbtn-warning\b/g, '')
            .trim() + ' btn-warning';
    } else if (!metronomeScheduler) {
        btn.textContent = 'Start Metronome';
        btn.disabled = false;
        btn.className = btn.className
            .replace(/\bbtn-warning\b/g, '')
            .replace(/\bbtn-secondary\b/g, '')
            .trim() + ' btn-primary';
    }
}

function resetBeatIndicators() {
    if (exerciseSchedule) {
        if (lastExerciseCellId) {
            const prev = document.getElementById(lastExerciseCellId);
            if (prev) {
                const parts = lastExerciseCellId.split('-');
                const colIdx = parseInt(parts[parts.length - 1], 10);
                prev.style.backgroundColor = colIdx % 2 === 1 ? '#e8e8e8' : '#ffffff';
                prev.style.color = '';
                prev.style.outline = '';
            }
            lastExerciseCellId = null;
        }
        return;
    }
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

function highlightExercisePosition(patternIdx, measureIdx, subIdx) {
    const cellId = `ex-cell-${patternIdx}-${measureIdx}-${subIdx}`;
    if (cellId === lastExerciseCellId) return;
    if (lastExerciseCellId) {
        const prev = document.getElementById(lastExerciseCellId);
        if (prev) {
            const parts = lastExerciseCellId.split('-');
            const colIdx = parseInt(parts[parts.length - 1], 10);
            prev.style.backgroundColor = colIdx % 2 === 1 ? '#e8e8e8' : '#ffffff';
            prev.style.color = '';
            prev.style.outline = '';
        }
    }
    const cell = document.getElementById(cellId);
    if (cell) {
        cell.style.backgroundColor = '#198754';
        cell.style.color = '#ffffff';
        cell.style.outline = '2px solid #198754';
    }
    lastExerciseCellId = cellId;
}

function setExerciseSchedule(data) {
    exerciseSchedule = data || null;
    lastExerciseCellId = null;
    console.log('setExerciseSchedule:', exerciseSchedule
        ? `${exerciseSchedule.schedule.length} entries, duration=${exerciseSchedule.duration}s, spb=${exerciseSchedule.spb}`
        : 'none (free mode)');
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
        // Decode any pending metronome track now that we have a context
        if (pendingMetronomeTrackUrl && !metronomeTrackBuffer) {
            _decodeMetronomeTrack(pendingMetronomeTrackUrl);
        }
    }
    return audioContext;
}

function _decodeMetronomeTrack(dataUrl) {
    if (!audioContext) return Promise.resolve(null);
    // Return the in-flight promise if decode is already running for this URL,
    // so concurrent callers share one decode instead of doing duplicate work.
    if (metronomeDecodePromise) return metronomeDecodePromise;
    const base64 = dataUrl.split(',')[1];
    const binary = atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    metronomeDecodePromise = audioContext.decodeAudioData(bytes.buffer.slice(0)).then(buffer => {
        if (dataUrl === pendingMetronomeTrackUrl) {
            metronomeTrackBuffer = buffer;
            console.log(`Metronome track decoded: ${buffer.duration.toFixed(1)}s at ${buffer.sampleRate}Hz`);
            if (pendingStart) {
                pendingStart = false;
                startMetronomePlayback({preserveOffset: false}).catch(err => {
                    console.error('pendingStart auto-start failed:', err);
                    setMetronomePlayingState(false);
                });
            } else {
                setMetronomeWarmingUpState(false);
            }
        }
        return buffer;
    }).catch(err => {
        console.error('Metronome track decode error:', err);
        return null;
    }).finally(() => {
        metronomeDecodePromise = null;
    });
    return metronomeDecodePromise;
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

function stopMetronomePlayback() {
    if (metronomeInterval) {
        clearInterval(metronomeInterval);
    }
    metronomeInterval = null;
    metronomeScheduler = null;

    if (metronomeSourceNode) {
        try { metronomeSourceNode.stop(); } catch (e) {}
        try { metronomeSourceNode.disconnect(); } catch (e) {}
        metronomeSourceNode = null;
    }
    if (metronomeGainNode) {
        try { metronomeGainNode.disconnect(); } catch (e) {}
        metronomeGainNode = null;
    }

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

    pendingStart = false;
    preserveMetronomeStartOffset = false;
    setMetronomePlayingState(false);
    console.log('Stopped metronome');
}

function startMetronomePlayback(options = {}) {
    const {preserveOffset = false, bufferOffsetOverride = null} = options;
    const ctx = ensureAudioContext();

    if (ctx.state === 'suspended') {
        ctx.resume().catch(err => console.warn('AudioContext resume failed:', err));
    }

    const startScheduler = async () => {
        if (!metronomeTrackBuffer) {
            console.error('startMetronomePlayback: no track buffer');
            return {firstBeatDelayMs: 0, secondsPerBeat: 60 / metronomeState.tempo, outputLatencyMs: 0};
        }

        const secondsPerBeat = 60.0 / metronomeState.tempo;
        const beatsPerMeasure = metronomeState.beatsPerMeasure;
        const measuresPerPattern = metronomeState.measuresPerPattern;
        const measureDuration = secondsPerBeat * beatsPerMeasure;

        // Page-load warmup (Stage 2) has already opened the audio pipeline,
        // so no silence primer is needed here -- just scheduling headroom.
        const startTime = ctx.currentTime + FIRST_TONE_DELAY_SECONDS;

        // Measure output latency so the visual indicator fires when the user hears the tone,
        // not when it is scheduled. Audio reaches the speaker at startTime + outputLatency;
        // delaying indicatorStartTime by the same amount aligns the visual with the heard beat.
        let outputLatencySeconds = 0;
        try {
            const ts = ctx.getOutputTimestamp();
            if (ts && ts.contextTime > 0 && ctx.currentTime > ts.contextTime) {
                const measured = ctx.currentTime - ts.contextTime;
                // Reject stale values (e.g. after a suspended context resumes,
                // contextTime can lag by seconds making this huge)
                if (measured > 0 && measured < 0.200) {
                    outputLatencySeconds = measured;
                }
            }
        } catch (e) { /* getOutputTimestamp not supported */ }
        // Fall back to the browser-reported estimate when the timestamp is unavailable
        if (outputLatencySeconds <= 0) {
            outputLatencySeconds = (ctx.outputLatency || 0) + (ctx.baseLatency || 0);
        }
        const indicatorStartTime = startTime + outputLatencySeconds;
        console.log(`startMetronomePlayback: outputLatency=${(outputLatencySeconds * 1000).toFixed(1)}ms, indicatorStartTime offset by latency`);

        // For recording count-in: start buffer at the measure that is countInMeasures before beat 0
        const countInMeasure = preserveOffset ? (measuresPerPattern - 1) : 0;
        const bufferOffset = bufferOffsetOverride !== null ? bufferOffsetOverride : countInMeasure * measureDuration;

        metronomeState.beatCount = 0;
        metronomeState.measureCount = 0;
        preserveMetronomeStartOffset = false;
        resetBeatIndicators();

        const source = ctx.createBufferSource();
            const gainNode = ctx.createGain();
            source.buffer = metronomeTrackBuffer;
            source.loop = true;
            source.loopStart = 0;
            source.loopEnd = metronomeTrackBuffer.duration;
            // Play at normal volume throughout (calibration warmup + measurement).
            // Audible warmup tones prime the OS audio pipeline; near-silent warmup
            // (0.003) was leaving the hardware cold and causing a systematic ~51ms
            // timing offset in auto-calibration.
            gainNode.gain.setValueAtTime(metronomeState.volume, ctx.currentTime);
            source.connect(gainNode);
            gainNode.connect(ctx.destination);
            source.start(startTime, bufferOffset);
            metronomeSourceNode = source;
            metronomeGainNode = gainNode;

            let lastBeatIdx = -1;
            let lastExerciseSchedIdx = -1;
            const totalBeatsPerPattern = beatsPerMeasure * measuresPerPattern;
            metronomeScheduler = setInterval(() => {
                if (!metronomeSourceNode) return;
                const now = ctx.currentTime;
                if (now < indicatorStartTime) return;
                const elapsed = (now - indicatorStartTime) + bufferOffset;
                if (exerciseSchedule && exerciseSchedule.schedule && exerciseSchedule.schedule.length > 0) {
                    const sched = exerciseSchedule.schedule;
                    const posInCycle = elapsed % exerciseSchedule.duration;
                    let lo = 0, hi = sched.length - 1, found = 0;
                    while (lo <= hi) {
                        const mid = (lo + hi) >> 1;
                        if (sched[mid].time <= posInCycle) { found = mid; lo = mid + 1; }
                        else hi = mid - 1;
                    }
                    if (found !== lastExerciseSchedIdx) {
                        lastExerciseSchedIdx = found;
                        const { isBeat, patternIdx, measureIdx, subIdx } = sched[found];
                        if (isBeat) highlightExercisePosition(patternIdx, measureIdx, subIdx);
                    }
                } else {
                    const beatIdx = Math.floor(elapsed / secondsPerBeat);
                    if (beatIdx !== lastBeatIdx) {
                        lastBeatIdx = beatIdx;
                        const beatInPattern = beatIdx % totalBeatsPerPattern;
                        const posInMeasure = beatInPattern % beatsPerMeasure;
                        const posInPattern = Math.floor(beatInPattern / beatsPerMeasure);
                        highlightBeatIndicator(posInPattern, posInMeasure);
                    }
                }
            }, 10);

            metronomeInterval = metronomeScheduler;
            setMetronomePlayingState(true);
            console.log(`startMetronomePlayback: buffer ${metronomeTrackBuffer.duration.toFixed(1)}s, offset=${bufferOffset.toFixed(3)}s`);

            return {firstBeatDelayMs: FIRST_TONE_DELAY_SECONDS * 1000, secondsPerBeat, outputLatencyMs: outputLatencySeconds * 1000};
    };

    if (ctx.state === 'suspended') {
        return ctx.resume().then(() => {
            console.log('AudioContext resumed successfully');
            return startScheduler();
        }).catch(err => {
            console.error('Failed to resume AudioContext:', err);
            return {firstBeatDelayMs: 0, secondsPerBeat: 60.0 / metronomeState.tempo};
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
                    console.log('Converted to WAV, trimmed pre-roll, length:', dataUrl.length);
                    if (calibrationRecordingEnded) {
                        calibrationRecordingEnded = false;
                        window.calibrationRecordedAudio = dataUrl;
                        clickHiddenButton('calibration-process-btn');
                    } else {
                        window.lastRecordedAudio = dataUrl;
                        window.recordedAudioData = dataUrl;
                        clickHiddenButton('audio-process-btn');
                    }
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
    calibrationMode = false;
    calibrationRecordingEnded = false;
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

        // For calibration: stop after exactly 2 measurement measures + 1s buffer,
        // regardless of how long getUserMedia or startMetronomePlayback took.
        // For normal recording: 10-minute safety limit.
        const isCalibration = calibrationMode;
        let maxRecordingTime;
        if (isCalibration) {
            const secondsPerBeat = 60.0 / metronomeState.tempo;
            maxRecordingTime = Math.round((2 * metronomeState.beatsPerMeasure * secondsPerBeat + 1.0) * 1000);
            console.log(`Calibration recording: scheduled stop in ${maxRecordingTime}ms`);
        } else {
            maxRecordingTime = 600000;
        }

        recordingTimeout = setTimeout(() => {
            if (mediaRecorder && mediaRecorder.state === 'recording') {
                if (isCalibration) {
                    console.log('Calibration recording: scheduled stop reached');
                    // Reset calibrationMode synchronously before stop() so that any
                    // immediate metronome start (user clicking the button while the
                    // stop-event chain is still async) does not apply the silent
                    // warmup gain schedule.
                    calibrationRecordingEnded = true;
                    calibrationMode = false;
                } else {
                    console.log('Automatic stop: Recording reached maximum time limit (10 minutes)');
                    window.recorderControls.playEndAlarm();
                    window.recorderControls.showAutoStopMessage();
                }
                mediaRecorder.stop();
                cleanupRecordingStream();
                if (metronomeAutoStartedByRecording) {
                    stopMetronomePlayback();
                    metronomeAutoStartedByRecording = false;
                }
                setRecordingPhase('idle');
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
    // Manual stop: calibration is incomplete, clear both flags so stop-event handler
    // routes to the normal recording path and calibrationMode does not linger.
    calibrationMode = false;
    calibrationRecordingEnded = false;
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

            // Compute count-in and buffer offset before starting the metronome,
            // so the buffer always starts at the measure that is countInMeasures
            // before beat 0, guaranteeing the recording starts at the beginning of the pattern.
            const _spb = 60.0 / metronomeState.tempo;
            const _measureDuration = metronomeState.beatsPerMeasure * _spb;
            let countInMeasures;
            if (calibrationMode) {
                countInMeasures = calibrationWarmupMeasures;
            } else {
                countInMeasures = Math.max(1, Math.ceil(MIN_COUNT_IN_PERIOD_SEC / _measureDuration));
            }
            // Buffer starts countInMeasures before beat 0, wrapping within the pattern.
            const bufferStartMeasure = patternMeasures > 1
                ? ((patternMeasures - (countInMeasures % patternMeasures)) % patternMeasures)
                : 0;
            const recordingBufferOffset = bufferStartMeasure * _measureDuration;

            metronomeState.beatCount = bufferStartMeasure * metronomeState.beatsPerMeasure;
            metronomeState.measureCount = bufferStartMeasure;
            preserveMetronomeStartOffset = false;
            console.log(`Count-in: ${countInMeasures} measures, buffer starts at measure ${bufferStartMeasure + 1} of ${patternMeasures}`);

            startMetronomePlayback({bufferOffsetOverride: recordingBufferOffset}).then(({
                                                                                    firstBeatDelayMs,
                                                                                    secondsPerBeat,
                                                                                    outputLatencyMs = 0
                                                                                }) => {
                if (requestId !== pendingRecordingRequestId || currentRecordingPhase !== 'delay') {
                    return;
                }

                // outputLatencyMs intentionally excluded: cold-start AudioContext measures
                // near-zero latency while warm recordings measure the true ~50ms value,
                // causing a systematic offset in cal_s. By anchoring both calibration and
                // normal recordings to the scheduled beat (not the heard beat), cal_s
                // captures the full acoustic offset consistently regardless of context state.
                const measureDelayMs = firstBeatDelayMs + (countInMeasures * metronomeState.beatsPerMeasure * secondsPerBeat * 1000) - RECORDING_PRE_ROLL_MS;
                console.log(`startRecordingWithCountIn: measureDelayMs=${measureDelayMs.toFixed(1)}ms (outputLatencyMs=${outputLatencyMs.toFixed(1)}ms excluded from delay)`);
                recordingDelayTimeout = setTimeout(() => beginActiveRecording(requestId), measureDelayMs);
            });
        })
        .catch(err => {
            console.error('Error accessing microphone:', err);
            alert('Error accessing microphone: ' + err.message);
            cancelPendingRecording();
        });
}

function loadCalibrationTrack(payload) {
    if (!payload || !payload.data_url) return;
    if (calibrationDecodePromise) return;
    if (!audioContext || audioContext.state === 'closed') {
        try {
            audioContext = new (window.AudioContext || window['webkitAudioContext'])();
        } catch (e) {
            console.warn('loadCalibrationTrack: could not create AudioContext:', e);
            return;
        }
    }
    calibrationFirstBeatMs = payload.first_beat_ms || 0;
    const base64 = payload.data_url.split(',')[1];
    const binary = atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    calibrationDecodePromise = audioContext.decodeAudioData(bytes.buffer.slice(0)).then(buffer => {
        calibrationTrackBuffer = buffer;
        console.log(`Calibration track decoded: ${buffer.duration.toFixed(2)}s, first beat at ${calibrationFirstBeatMs}ms`);
    }).catch(err => {
        console.error('Calibration track decode error:', err);
    }).finally(() => {
        calibrationDecodePromise = null;
    });
}

function loadMetronomeTrack(dataUrl) {
    pendingMetronomeTrackUrl = dataUrl;
    metronomeTrackBuffer = null;
    metronomeDecodePromise = null;
    // Create an AudioContext eagerly (it will be suspended until a user gesture resumes
    // it, but decodeAudioData works regardless of playback state).  This lets the
    // 30-second buffer decode in the background so the first metronome click is instant.
    if (!audioContext || audioContext.state === 'closed') {
        try {
            audioContext = new (window.AudioContext || window['webkitAudioContext'])();
            console.log('loadMetronomeTrack: created AudioContext for eager decode');
        } catch (e) {
            console.warn('loadMetronomeTrack: could not create AudioContext eagerly:', e);
        }
    }
    if (audioContext && audioContext.state !== 'closed') {
        _decodeMetronomeTrack(dataUrl);
    }
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

            const now = Date.now();
            const msSinceLast = now - lastToggleTimestamp;
            // Suppress spurious Dash double-fire: a "stop" arriving within 2s of a "start"
            if (lastToggleWasStart && is_playing && msSinceLast < 2000) {
                console.log('toggleMetronome: suppressed spurious stop (', msSinceLast, 'ms after start)');
                return;
            }
            lastToggleTimestamp = now;
            lastToggleWasStart = !is_playing;

            updateMetronomeState(tempo, beatsPerMeasure, measuresPerPattern, volume, hiToneOn, onlyLowTone);

            if (!is_playing) {
                if (pendingStart) {
                    // User clicked "Warming Up..." to cancel the pending start
                    pendingStart = false;
                    setMetronomePlayingState(false);
                    return false;
                }
                // Create and resume AudioContext synchronously while still in the
                // user-gesture handler, before any async operations that could lose
                // the gesture context (important for autoplay policy on Plotly cloud).
                const ctx = ensureAudioContext();
                if (ctx.state === 'suspended') {
                    ctx.resume().catch(err => console.warn('toggleMetronome: pre-resume failed:', err));
                }
                metronomeAutoStartedByRecording = false;
                stopMetronomePlayback();
                if (!metronomeTrackBuffer) {
                    pendingStart = true;
                    setMetronomeWarmingUpState(true);
                    return false;
                }
                startMetronomePlayback({preserveOffset: false}).catch(err => {
                    console.error('startMetronomePlayback rejected:', err);
                });
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
        loadMetronomeTrack: function(dataUrl) {
            loadMetronomeTrack(dataUrl);
        },

        startCalibration: function() {
            if (currentRecordingPhase !== 'idle') {
                cancelPendingRecording();
            }
            if (!calibrationTrackBuffer) {
                console.error('startCalibration: calibration track not decoded yet');
                return;
            }

            calibrationMode = true;
            calibrationRecordingEnded = false;
            pendingRecordingRequestId += 1;
            const requestId = pendingRecordingRequestId;
            setRecordingPhase('delay');

            const calibBtn = document.getElementById('calibrate-btn');
            if (calibBtn) {
                calibBtn.textContent = 'Calibrating...';
                calibBtn.disabled = true;
                calibBtn.className = calibBtn.className
                    .replace(/\bbtn-warning\b|\bbtn-primary\b/g, '')
                    .trim() + ' btn-secondary';
            }

            const ctx = ensureAudioContext();

            navigator.mediaDevices.getUserMedia({
                audio: {echoCancellation: false, noiseSuppression: false, autoGainControl: false, sampleRate: {ideal: 48000}}
            }).then(stream => {
                if (requestId !== pendingRecordingRequestId) {
                    stream.getTracks().forEach(t => t.stop());
                    return Promise.resolve();
                }
                recordingStream = stream;
                configureMediaRecorder(stream);

                stopMetronomePlayback();
                metronomeAutoStartedByRecording = true;

                // Await resume so ctx.currentTime is live before scheduling audio.
                // If ctx was auto-suspended by the browser, source.start() with a
                // stale frozen ctx.currentTime causes the track to fire late relative
                // to the wall-clock recording setTimeout, producing a ~100ms cal_s error.
                return ctx.resume();
            }).then(() => {
                if (requestId !== pendingRecordingRequestId) return;

                // Play calibration track (one-shot, no loop)
                const gainNode = ctx.createGain();
                gainNode.gain.setValueAtTime(1.0, ctx.currentTime);
                const source = ctx.createBufferSource();
                source.buffer = calibrationTrackBuffer;
                source.connect(gainNode);
                gainNode.connect(ctx.destination);
                source.start(ctx.currentTime + FIRST_TONE_DELAY_SECONDS);
                metronomeSourceNode = source;
                metronomeGainNode = gainNode;

                // Delay recording so that after PRE_ROLL trim, beat 1 aligns with t=0
                const recordDelayMs = Math.max(0,
                    FIRST_TONE_DELAY_SECONDS * 1000 + calibrationFirstBeatMs - RECORDING_PRE_ROLL_MS
                );
                recordingDelayTimeout = setTimeout(() => {
                    if (requestId !== pendingRecordingRequestId) return;
                    recordingDiagnostics.lastChunkTime = Date.now();
                    mediaRecorder.start(100);
                    setRecordingPhase('recording');

                    const calDurationMs = calibrationTrackBuffer.duration * 1000 + 500;
                    recordingTimeout = setTimeout(() => {
                        if (mediaRecorder && mediaRecorder.state === 'recording') {
                            calibrationRecordingEnded = true;
                            calibrationMode = false;
                            mediaRecorder.stop();
                            cleanupRecordingStream();
                            stopMetronomePlayback();
                            metronomeAutoStartedByRecording = false;
                            setRecordingPhase('idle');
                        }
                    }, calDurationMs);
                }, recordDelayMs);

            }).catch(err => {
                console.error('startCalibration failed:', err);
                calibrationMode = false;
                calibrationRecordingEnded = false;
                setRecordingPhase('idle');
                const btn = document.getElementById('calibrate-btn');
                if (btn) {
                    btn.textContent = 'Calibrate';
                    btn.disabled = false;
                    btn.className = btn.className.replace(/\bbtn-secondary\b/g, '').trim() + ' btn-warning';
                }
            });

            // Safety net
            setTimeout(() => {
                if (calibrationMode || currentRecordingPhase !== 'idle') {
                    console.log('startCalibration: safety-net stop');
                    calibrationMode = false;
                    calibrationRecordingEnded = false;
                    stopActiveRecording();
                }
            }, 20000);
        },

        reconfigureMetronome: function (isPlaying, tempo, beatsPerMeasure, measuresPerPattern, volume, hiToneOn, onlyLowTone) {
            if (!isPlaying) return;

            // Stop any in-progress recording
            if (currentRecordingPhase === 'recording') {
                stopActiveRecording();
            } else if (currentRecordingPhase === 'delay') {
                cancelPendingRecording();
            }

            // Detect track-affecting parameter changes BEFORE updating state.
            // If the precomputed track will change, discard the stale buffer so
            // startMetronomePlayback uses the per-tone fallback (which derives
            // tones from metronomeState directly and is always correct).
            // loadMetronomeTrack will silently update metronomeTrackBuffer once
            // the server delivers the new track.
            const trackParamsChanged = (
                Number(tempo) !== metronomeState.tempo ||
                Number(beatsPerMeasure) !== metronomeState.beatsPerMeasure ||
                Number(measuresPerPattern) !== metronomeState.measuresPerPattern ||
                !!hiToneOn !== metronomeState.hiToneOn ||
                !!onlyLowTone !== metronomeState.onlyLowTone
            );

            updateMetronomeState(tempo, beatsPerMeasure, measuresPerPattern, volume, hiToneOn, onlyLowTone);
            metronomeAutoStartedByRecording = false;
            stopMetronomePlayback();

            if (trackParamsChanged) {
                metronomeTrackBuffer = null;
                metronomeDecodePromise = null;
                pendingMetronomeTrackUrl = null;
                console.log('reconfigureMetronome: track params changed, waiting for new track');
            } else {
                startMetronomePlayback({preserveOffset: false}).catch(err => {
                    console.error('reconfigureMetronome: startMetronomePlayback rejected:', err);
                });
            }
        },

        triggerPermissionDialog: function () {
            console.log("Triggering permission dialog and starting warmup...");
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
                    console.log("Permission granted; running warmup...");
                    const ctx = ensureAudioContext();
                    if (ctx.state === 'suspended') {
                        ctx.resume().catch(err => console.warn('warmup: resume failed:', err));
                    }

                    // Route mic through a muted node to keep the input pipeline active
                    const micSource = ctx.createMediaStreamSource(stream);
                    const muteNode = ctx.createGain();
                    muteNode.gain.value = 0;
                    micSource.connect(muteNode);
                    muteNode.connect(ctx.destination);

                    // Play a silent buffer to open the output pipeline
                    const warmupSamples = Math.ceil(ctx.sampleRate * INITIAL_WARMUP_SECONDS);
                    const warmupBuf = ctx.createBuffer(1, warmupSamples, ctx.sampleRate);
                    const warmupSrc = ctx.createBufferSource();
                    warmupSrc.buffer = warmupBuf;
                    warmupSrc.connect(ctx.destination);
                    warmupSrc.start(ctx.currentTime);

                    setTimeout(() => {
                        stream.getTracks().forEach(t => t.stop());
                        micSource.disconnect();
                        muteNode.disconnect();
                        warmupCompleted = true;

                        const outMs = Math.round((ctx.outputLatency || 0) * 1000);
                        const inMs  = Math.round((ctx.inputLatency  || 0) * 1000);
                        const baseMs = Math.round((ctx.baseLatency  || 0) * 1000);
                        const sr = ctx.sampleRate;
                        console.log(
                            `Warmup complete: sampleRate=${sr}Hz` +
                            `, outputLatency=${outMs}ms` +
                            `, inputLatency=${inMs}ms` +
                            `, baseLatency=${baseMs}ms`
                        );

                        // Signal warmup completion with platform info for Stage 3 context store
                        const platformKey = [navigator.userAgent, sr, outMs, inMs].join('|');
                        const platformInfo = JSON.stringify({
                            platform_key: platformKey,
                            sample_rate: sr,
                            output_latency_ms: outMs,
                            input_latency_ms: inMs,
                            base_latency_ms: baseMs,
                        });
                        setDashInputValue('warmup-info-store', platformInfo);
                    }, INITIAL_WARMUP_SECONDS * 1000);
                })
                .catch(err => {
                    console.warn("Permission trigger failed (user may have denied):", err);
                });
        },

        setExerciseSchedule: function(data) { setExerciseSchedule(data); },

        loadCalibrationTrack: function(dataUrl) { loadCalibrationTrack(dataUrl); },
    };

    // These properties are called from Dash clientside_callbacks embedded in main.py
    void window.recorderControls.reconfigureMetronome;
    void window.recorderControls.loadMetronomeTrack;
    void window.recorderControls.loadCalibrationTrack;
    void window.recorderControls.startCalibration;
    void window.recorderControls.setExerciseSchedule;
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
                // Clear confidence indicator when user edits the calibration value box
                const calInput = document.getElementById('calibration-value');
                if (calInput) {
                    calInput.addEventListener('change', () => {
                        const conf = document.getElementById('calibration-confidence');
                        if (conf) conf.textContent = '';
                    });
                }
            }, 1000);
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
