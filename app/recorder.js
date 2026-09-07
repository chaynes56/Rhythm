const VERSION = "0.1.9";

// Auto-reload when Dash assets fail to load on browser startup.
// Brave (and other Chromium browsers) restore session tabs immediately, which can
// race with Flask debug-mode's reloader restarting its worker -- the HTML is served
// but _dash-component-suites/... requests return 500, breaking React/Plotly.
//
// Two failure modes are handled:
//   1. Static <script> tag failures  -> capture-phase 'error' event on window
//   2. Webpack async chunk failures  -> 'unhandledrejection' (ChunkLoadError)
//      These are Dash components loaded at runtime via dynamic import(), e.g.
//      async-dropdown.js.  They never reach the <script> error listener.
//
// Both trigger the same recovery: poll /_dash-dependencies until the server
// responds 200, then reload.  Loop prevention: performance.navigation.type
// tells us if THIS load was itself a programmatic reload; if so we skip
// registration.  (sessionStorage is avoided -- Brave restores it across
// browser restarts, defeating a flag written there.)
(function() {
    try {
        const nav = performance.getEntriesByType('navigation');
        if (nav.length && nav[0].type === 'reload') return;
    } catch (e) {}

    let reloading = false;

    function triggerReload(reason) {
        if (reloading) return;
        reloading = true;
        console.warn('Rhythm: ' + reason + ' -- polling /_dash-dependencies before reload');
        let attempts = 0;
        function poll() {
            if (attempts++ > 30) {
                console.error('Rhythm: server unresponsive after 30 s -- giving up on auto-reload');
                return;
            }
            fetch('/_dash-dependencies')
                .then(function(r) {
                    if (r.ok) {
                        console.warn('Rhythm: server ready -- reloading');
                        window.location.reload();
                    } else {
                        console.warn('Rhythm: /_dash-dependencies returned ' + r.status + ', retrying in 1 s');
                        setTimeout(poll, 1000);
                    }
                })
                .catch(function(err) {
                    console.warn('Rhythm: fetch /_dash-dependencies failed (' + err + '), retrying in 1 s');
                    setTimeout(poll, 1000);
                });
        }
        setTimeout(poll, 500);
    }

    // Static <script> tag load failures (e.g. plotly.min.js returns 500).
    window.addEventListener('error', function(ev) {
        const t = ev.target;
        if (t && t.tagName === 'SCRIPT') {
            triggerReload('Dash script load failed (' + (t.src || 'unknown') + ')');
        }
    }, true /* capture phase -- resource errors do not bubble */);

    // Webpack async chunk failures (e.g. async-dropdown.js, async-graph.js).
    // These are thrown as ChunkLoadError by the webpack runtime and surface as
    // unhandled promise rejections -- the <script> error listener never sees them.
    window.addEventListener('unhandledrejection', function(ev) {
        const msg = ev.reason ? String(ev.reason.message || ev.reason) : '';
        if (msg.indexOf('Loading chunk') !== -1) {
            triggerReload('Webpack chunk load failed (' + msg + ')');
        }
    });
}());

if (!window.dash_clientside) {
    window.dash_clientside = {};
}

// Suppress noisy Plotly/React internal warnings that are not actionable.
(function() {
    const SUPPRESS = [
        'Support for defaultProps will be removed from function components',
        "Can't perform a React state update on a component that hasn't mounted yet",
    ];
    const _warn = console.warn.bind(console);
    const _error = console.error.bind(console);
    function shouldSuppress(args) {
        const msg = args[0];
        if (typeof msg !== 'string') return false;
        return SUPPRESS.some(function(s) { return msg.indexOf(s) !== -1; });
    }
    console.warn  = function() { if (!shouldSuppress(arguments)) _warn.apply(console, arguments); };
    console.error = function() { if (!shouldSuppress(arguments)) _error.apply(console, arguments); };
}());

// App-level error routing.  Add substrings to SUPPRESSED_JS_ERRORS to keep a specific
// error in the browser console but out of the UI error display.
const SUPPRESSED_JS_ERRORS = [
    // Example: 'Error playing end alarm'
];

function reportJsError(message) {
    const msg = String(message);
    console.error('[error]', msg);
    if (SUPPRESSED_JS_ERRORS.some(function(p) { return msg.includes(p); })) return;
    try {
        window.dash_clientside.set_props('error-store', {data: 'JS: ' + msg});
    } catch (e) { /* set_props not yet available on early errors */ }
}

window.addEventListener('unhandledrejection', function(ev) {
    const reason = ev.reason;
    // ChunkLoadError is handled by the auto-reload IIFE above -- skip it here.
    const msg = reason ? String(reason.message || reason) : 'Unhandled promise rejection';
    if (msg.indexOf('Loading chunk') !== -1) return;
    reportJsError(msg);
});

// Timing constants
const INITIAL_WARMUP_SECONDS = 8;      // silent warmup duration on page load
// (Stage 2)
const FIRST_TONE_DELAY_SECONDS = 0.15; // scheduling buffer before first audio tone
const MIN_COUNT_IN_PERIOD_SEC = 3;     // minimum count-in duration before recording starts

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
let calibrationSafetyNetTimeout = null;  // timer ID for the per-calibration safety net; canceled on new start
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
// Sample-indexed capture state (see CAPTURE_WORKLET_SOURCE below)
let captureNode = null;
let captureSource = null;
let captureChunks = [];
let captureActive = false;
let captureSampleRate = 48000;
let captureStopResolve = null;
let recordStartFrame = 0;  // audio-clock frame where the kept recording begins (t=0 after slicing)

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

// ---------------------------------------------------------------------------
// Sample-indexed capture (AudioWorklet)
//
// Recording runs on the SAME AudioContext clock as metronome playback.  The
// worklet tags every captured chunk with its audio-clock frame position, so
// the recording is later sliced at the exact frame where playback was
// scheduled (recordStartFrame).  This keeps MediaRecorder and wall-clock
// setTimeout out of the sync path entirely: the only residual playback/record
// offset is the physical output+input latency, which the acoustic calibration
// measures and which is stable for a given device/browser.
// ---------------------------------------------------------------------------
const CAPTURE_WORKLET_SOURCE = `
class RhythmCaptureProcessor extends AudioWorkletProcessor {
    constructor() {
        super();
        this.CHUNK_FRAMES = 16384;
        this.acc = new Float32Array(this.CHUNK_FRAMES);
        this.accLen = 0;
        this.accStartFrame = -1;
        this.stopped = false;
        this.port.onmessage = (e) => {
            if (e.data === 'stop') {
                this.flush();
                this.stopped = true;
                this.port.postMessage({type: 'done'});
            }
        };
    }
    flush() {
        if (this.accLen > 0) {
            const samples = this.acc.slice(0, this.accLen);
            this.port.postMessage(
                {type: 'chunk', frameStart: this.accStartFrame, samples: samples},
                [samples.buffer]
            );
            this.accLen = 0;
            this.accStartFrame = -1;
        }
    }
    process(inputs) {
        if (this.stopped) return false;
        const input = inputs[0];
        if (!input || input.length === 0) return true;  // stream not delivering yet
        const ch = input[0];
        // If input delivery had a gap, flush so every chunk stays contiguous.
        if (this.accLen > 0 && currentFrame !== this.accStartFrame + this.accLen) {
            this.flush();
        }
        let offset = 0;
        while (offset < ch.length) {
            if (this.accLen === 0) this.accStartFrame = currentFrame + offset;
            const n = Math.min(ch.length - offset, this.CHUNK_FRAMES - this.accLen);
            this.acc.set(ch.subarray(offset, offset + n), this.accLen);
            this.accLen += n;
            offset += n;
            if (this.accLen === this.CHUNK_FRAMES) this.flush();
        }
        return true;
    }
}
registerProcessor('rhythm-capture', RhythmCaptureProcessor);
`;

function ensureCaptureWorklet(ctx) {
    if (!ctx.audioWorklet) {
        return Promise.reject(new Error(
            'AudioWorklet not supported -- please use a current Chrome, Firefox, or Safari'));
    }
    if (!ctx._rhythmCaptureModulePromise) {
        const blobUrl = URL.createObjectURL(
            new Blob([CAPTURE_WORKLET_SOURCE], {type: 'application/javascript'}));
        ctx._rhythmCaptureModulePromise = ctx.audioWorklet.addModule(blobUrl)
            .finally(() => URL.revokeObjectURL(blobUrl));
    }
    return ctx._rhythmCaptureModulePromise;
}

function startCapture(ctx, stream) {
    return ensureCaptureWorklet(ctx).then(() => {
        // Each run owns its chunk array via closure, so late messages from a
        // torn-down worklet can never leak into a subsequent capture.
        const chunks = [];
        captureChunks = chunks;
        captureSampleRate = ctx.sampleRate;
        captureSource = ctx.createMediaStreamSource(stream);
        captureNode = new AudioWorkletNode(ctx, 'rhythm-capture', {
            numberOfInputs: 1,
            numberOfOutputs: 1,
            outputChannelCount: [1],
            channelCount: 1,
            channelCountMode: 'explicit',
        });
        captureNode.port.onmessage = (e) => {
            const msg = e.data;
            if (msg && msg.type === 'chunk') {
                chunks.push(msg);
            } else if (msg && msg.type === 'done' && captureStopResolve) {
                const resolve = captureStopResolve;
                captureStopResolve = null;
                resolve();
            }
        };
        captureSource.connect(captureNode);
        // The worklet outputs silence; connecting it to the destination keeps it
        // pulled by the render graph so process() runs every quantum.
        captureNode.connect(ctx.destination);
        captureActive = true;
        console.log(`startCapture: worklet capture running at ${captureSampleRate}Hz`);
    });
}

// Ask the worklet to flush its partial chunk, then tear down the nodes.
// Resolves with the captured chunks; captureChunks stays populated until the
// next startCapture so callers can still assemble after teardown.
function stopCapture() {
    captureActive = false;
    const chunks = captureChunks;  // snapshot: a new startCapture reassigns the global
    if (!captureNode) {
        return Promise.resolve(chunks);
    }
    const node = captureNode;
    const source = captureSource;
    captureNode = null;
    captureSource = null;
    const done = new Promise((resolve) => {
        captureStopResolve = resolve;
        // Fallback in case the worklet never answers (context closed, etc.)
        setTimeout(() => {
            if (captureStopResolve) {
                captureStopResolve = null;
                resolve();
            }
        }, 1000);
    });
    node.port.postMessage('stop');
    return done.then(() => {
        try { source.disconnect(); } catch (e) {}
        try { node.disconnect(); } catch (e) {}
        return chunks;
    });
}

function discardCapture() {
    const chunks = captureChunks;
    stopCapture().then(() => {
        // Free memory, but never clobber a capture that started after this call.
        if (captureChunks === chunks) captureChunks = [];
    });
}

// Assemble chunks into one Float32Array starting at startFrame.  Chunks are
// contiguous runs tagged with their frame position; any input-delivery gaps
// stay zero-filled (silence) so downstream timing is unaffected.
function assembleCapture(chunks, startFrame) {
    if (!chunks.length) return null;
    let firstFrame = Infinity;
    let endFrame = 0;
    for (const c of chunks) {
        firstFrame = Math.min(firstFrame, c.frameStart);
        endFrame = Math.max(endFrame, c.frameStart + c.samples.length);
    }
    if (endFrame <= startFrame) return null;
    if (firstFrame > startFrame) {
        console.warn(`assembleCapture: capture began ${firstFrame - startFrame} frames` +
            ' after the target start -- padding with silence');
    }
    const out = new Float32Array(endFrame - startFrame);
    let covered = 0;
    for (const c of chunks) {
        const to = c.frameStart + c.samples.length;
        if (to <= startFrame) continue;
        const from = Math.max(c.frameStart, startFrame);
        out.set(c.samples.subarray(from - c.frameStart), from - startFrame);
        covered += to - from;
    }
    const gapFrames = (endFrame - Math.max(startFrame, firstFrame)) - covered;
    if (gapFrames > 0) {
        console.warn(`assembleCapture: ${gapFrames} frames of input gaps filled with silence`);
    }
    return out;
}

function restoreCalibrateButton() {
    const btn = document.getElementById('calibrate-btn');
    if (btn && btn.textContent === 'Calibrating...') {
        btn.textContent = 'Calibrate';
        btn.disabled = false;
        btn.className = btn.className.replace(/\bbtn-secondary\b/g, '').trim() + ' btn-warning';
    }
}

// Downsample captured PCM to the analysis rate, encode as WAV, and route to
// the calibration or normal processing chain in main.py.
function processCapturedAudio(samples, sourceSampleRate, route) {
    const RECORD_SAMPLE_RATE = 4000;
    const RECORD_LPF_HZ = 1800;
    const targetLength = Math.ceil(samples.length / sourceSampleRate * RECORD_SAMPLE_RATE);
    let offlineCtx;
    let srcBuffer;
    try {
        offlineCtx = new OfflineAudioContext(1, targetLength, RECORD_SAMPLE_RATE);
        srcBuffer = new AudioBuffer({
            length: samples.length, numberOfChannels: 1, sampleRate: sourceSampleRate});
    } catch (err) {
        reportJsError('processCapturedAudio setup failed: ' + err);
        if (route === 'calibration') restoreCalibrateButton();
        return;
    }
    srcBuffer.copyToChannel(samples, 0);
    const src = offlineCtx.createBufferSource();
    src.buffer = srcBuffer;
    const lpf = offlineCtx.createBiquadFilter();
    lpf.type = 'lowpass';
    lpf.frequency.value = RECORD_LPF_HZ;
    src.connect(lpf);
    lpf.connect(offlineCtx.destination);
    src.start();
    offlineCtx.startRendering().then((rendered) => {
        const wavData = encodeWAV(rendered.getChannelData(0), RECORD_SAMPLE_RATE);
        const wavBlob = new Blob([wavData], {type: 'audio/wav'});
        const reader = new FileReader();
        reader.readAsDataURL(wavBlob);
        reader.addEventListener('loadend', () => {
            const dataUrl = /** @type {string} */ (reader.result);
            console.log(`processCapturedAudio: ${route} WAV ready, length ${dataUrl.length}`);
            if (route === 'calibration') {
                window.calibrationRecordedAudio = dataUrl;
                clickHiddenButton('calibration-process-btn');
            } else {
                window.lastRecordedAudio = dataUrl;
                window.recordedAudioData = dataUrl;
                clickHiddenButton('audio-process-btn');
            }
        });
    }).catch((err) => {
        reportJsError('processCapturedAudio render failed: ' + err);
        if (route === 'calibration') restoreCalibrateButton();
    });
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
        if (currentRecordingPhase === 'idle') {
            btn.textContent = isPlaying ? 'Stop Metronome' : 'Start Metronome';
        }
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
    } else if (!metronomeScheduler && currentRecordingPhase === 'idle') {
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
            // Auto-start if the user was waiting (pendingStart), or if the standalone
            // metronome is already playing with a stale buffer (e.g. voicing changed
            // while the metronome was running -- restart it with the new track).
            const standaloneIsPlaying = !!metronomeSourceNode && !metronomeAutoStartedByRecording;
            if (pendingStart || standaloneIsPlaying) {
                pendingStart = false;
                if (standaloneIsPlaying) stopMetronomePlayback();
                startMetronomePlayback({preserveOffset: false}).catch(err => {
                    reportJsError('pendingStart auto-start failed: ' + err);
                    setMetronomePlayingState(false);
                });
            } else {
                setMetronomeWarmingUpState(false);
            }
        }
        return buffer;
    }).catch(err => {
        reportJsError('Metronome track decode error: ' + err);
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
            reportJsError('startMetronomePlayback: no track buffer');
            return {firstBeatDelayMs: 0, secondsPerBeat: 60 / metronomeState.tempo, outputLatencyMs: 0, startTime: null};
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

            // startTime is the exact audio-clock time the buffer begins playing;
            // recording start frames are computed from it (see startRecordingWithCountIn).
            return {firstBeatDelayMs: FIRST_TONE_DELAY_SECONDS * 1000, secondsPerBeat, outputLatencyMs: outputLatencySeconds * 1000, startTime};
    };

    if (ctx.state === 'suspended') {
        return ctx.resume().then(() => {
            console.log('AudioContext resumed successfully');
            return startScheduler();
        }).catch(err => {
            reportJsError('Failed to resume AudioContext: ' + err);
            return {firstBeatDelayMs: 0, secondsPerBeat: 60.0 / metronomeState.tempo, startTime: null};
        });
    }

    return Promise.resolve(startScheduler());
}

function cancelPendingRecording() {
    pendingRecordingRequestId += 1;
    clearRecordingTimers();
    if (calibrationSafetyNetTimeout !== null) {
        clearTimeout(calibrationSafetyNetTimeout);
        calibrationSafetyNetTimeout = null;
    }
    discardCapture();
    cleanupRecordingStream();
    if (metronomeAutoStartedByRecording) {
        stopMetronomePlayback();
        metronomeAutoStartedByRecording = false;
    }
    calibrationMode = false;
    setRecordingPhase('idle');
}

function beginActiveRecording(requestId) {
    if (requestId !== pendingRecordingRequestId || currentRecordingPhase !== 'delay' || !captureActive) {
        return;
    }
    // Capture alignment is frame-indexed on the audio clock; this timer only
    // flips the UI phase and schedules the 10-minute safety stop.
    setRecordingPhase('recording');
    console.log('Recording window open (frame-indexed capture)');
    recordingTimeout = setTimeout(() => {
        if (requestId !== pendingRecordingRequestId || currentRecordingPhase !== 'recording') {
            return;
        }
        console.log('Automatic stop: Recording reached maximum time limit (10 minutes)');
        window.recorderControls.playEndAlarm();
        window.recorderControls.showAutoStopMessage();
        finishActiveRecording('recording');
    }, 600000);
}

// Stop capture, slice at recordStartFrame, and hand off for processing.
function finishActiveRecording(route) {
    clearRecordingTimers();
    const startFrame = recordStartFrame;
    const sampleRate = captureSampleRate;
    stopCapture().then((chunks) => {
        const samples = assembleCapture(chunks, startFrame);
        if (captureChunks === chunks) captureChunks = [];
        if (!samples) {
            reportJsError('Recording produced no audio (no mic input captured)');
            if (route === 'calibration') restoreCalibrateButton();
            return;
        }
        console.log(`finishActiveRecording: ${route}, ${samples.length} samples` +
            ` (${(samples.length / sampleRate).toFixed(2)}s) from frame ${startFrame}`);
        processCapturedAudio(samples, sampleRate, route);
    });
    cleanupRecordingStream();
    if (metronomeAutoStartedByRecording) {
        stopMetronomePlayback();
        metronomeAutoStartedByRecording = false;
    }
    calibrationMode = false;
    setRecordingPhase('idle');
}

function stopActiveRecording() {
    console.log('Stopping recording...');
    if (calibrationMode) {
        // Manual stop mid-calibration: a partial calibration track is useless,
        // so discard rather than processing it (matches the old MediaRecorder
        // path, which also discarded incomplete calibrations).
        clearRecordingTimers();
        discardCapture();
        cleanupRecordingStream();
        if (metronomeAutoStartedByRecording) {
            stopMetronomePlayback();
            metronomeAutoStartedByRecording = false;
        }
        calibrationMode = false;
        setRecordingPhase('idle');
        restoreCalibrateButton();
        return;
    }
    finishActiveRecording('recording');
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

    const ctx = ensureAudioContext();
    if (ctx.state === 'suspended') {
        ctx.resume().catch(err => console.warn('startRecordingWithCountIn: resume failed:', err));
    }

    navigator.mediaDevices.getUserMedia(audioConstraints)
        .then(stream => {
            if (requestId !== pendingRecordingRequestId || currentRecordingPhase !== 'delay') {
                stream.getTracks().forEach(track => track.stop());
                return;
            }

            recordingStream = stream;

            // Capture starts now, during the count-in, so the input pipeline has
            // the full count-in (>= 3s) to reach steady state before beat 1.
            return startCapture(ctx, stream).then(() => {
                if (requestId !== pendingRecordingRequestId || currentRecordingPhase !== 'delay') {
                    discardCapture();
                    return;
                }

                stopMetronomePlayback();
                metronomeAutoStartedByRecording = true;

                const patternMeasures = metronomeState.measuresPerPattern || 1;

                // Compute count-in and buffer offset before starting the metronome,
                // so the buffer always starts at the measure that is countInMeasures
                // before beat 0, guaranteeing the recording starts at the beginning of the pattern.
                const _spb = 60.0 / metronomeState.tempo;
                const _measureDuration = metronomeState.beatsPerMeasure * _spb;
                const countInMeasures = Math.max(1, Math.ceil(MIN_COUNT_IN_PERIOD_SEC / _measureDuration));
                // Buffer starts countInMeasures before beat 0, wrapping within the pattern.
                const bufferStartMeasure = patternMeasures > 1
                    ? ((patternMeasures - (countInMeasures % patternMeasures)) % patternMeasures)
                    : 0;
                const recordingBufferOffset = bufferStartMeasure * _measureDuration;

                metronomeState.beatCount = bufferStartMeasure * metronomeState.beatsPerMeasure;
                metronomeState.measureCount = bufferStartMeasure;
                preserveMetronomeStartOffset = false;
                console.log(`Count-in: ${countInMeasures} measures, buffer starts at measure ${bufferStartMeasure + 1} of ${patternMeasures}`);

                return startMetronomePlayback({bufferOffsetOverride: recordingBufferOffset}).then(({startTime, secondsPerBeat}) => {
                    if (requestId !== pendingRecordingRequestId || currentRecordingPhase !== 'delay') {
                        return;
                    }
                    if (startTime == null) {
                        reportJsError('startRecordingWithCountIn: metronome failed to start');
                        cancelPendingRecording();
                        return;
                    }

                    // Beat 1 of the pattern, on the audio clock.  The capture is
                    // sliced at exactly this frame -- no wall-clock timing is in
                    // the sync path, so the scheduled-playback/recording alignment
                    // is sample-accurate.  The remaining physical output+input
                    // latency is what cal_s measures.
                    const recordStartTime = startTime + countInMeasures * metronomeState.beatsPerMeasure * secondsPerBeat;
                    recordStartFrame = Math.round(recordStartTime * ctx.sampleRate);
                    const uiDelayMs = Math.max(0, (recordStartTime - ctx.currentTime) * 1000);
                    console.log(`startRecordingWithCountIn: beat 1 at t=${recordStartTime.toFixed(3)}s` +
                        ` (frame ${recordStartFrame}), UI phase flips in ${uiDelayMs.toFixed(0)}ms`);
                    recordingDelayTimeout = setTimeout(() => beginActiveRecording(requestId), uiDelayMs);
                });
            });
        })
        .catch(err => {
            reportJsError('Recording setup failed: ' + (err.message || err));
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
    const { first_beat_ms, data_url } = payload;
    calibrationFirstBeatMs = first_beat_ms || 0;
    const base64 = data_url.split(',')[1];
    const binary = atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    calibrationDecodePromise = audioContext.decodeAudioData(bytes.buffer.slice(0)).then(buffer => {
        calibrationTrackBuffer = buffer;
        console.log(`Calibration track decoded: ${buffer.duration.toFixed(2)}s, first beat at ${calibrationFirstBeatMs}ms`);
    }).catch(err => {
        reportJsError('Calibration track decode error: ' + err);
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
                    reportJsError('Playback error: ' + err);
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
                    reportJsError('Metronome start failed: ' + err);
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
                reportJsError('Error playing end alarm: ' + err);
            }
        },

        showAutoStopMessage: function () {
            try {
                const statusMsg = document.getElementById('status-msg');
                if (statusMsg) {
                    statusMsg.textContent = 'Auto-stop: Recording reached 10-minute limit. Processing audio...';
                    console.log("Displayed auto-stop message");
                }
            } catch (err) {
                reportJsError('Error showing auto-stop message: ' + err);
            }
        },
        loadMetronomeTrack: function(dataUrl) {
            loadMetronomeTrack(dataUrl);
        },

        startCalibration: function() {
            // Cancel any stale safety net from a previous calibration run before
            // doing anything else -- this is the primary guard against old timers
            // interfering with the new calibration.
            if (calibrationSafetyNetTimeout !== null) {
                clearTimeout(calibrationSafetyNetTimeout);
                calibrationSafetyNetTimeout = null;
            }

            if (currentRecordingPhase !== 'idle') {
                cancelPendingRecording();
            }
            if (!calibrationTrackBuffer) {
                reportJsError('startCalibration: calibration track not decoded yet');
                return;
            }

            calibrationMode = true;
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

                stopMetronomePlayback();
                metronomeAutoStartedByRecording = true;

                // Await resume so ctx.currentTime is live before scheduling audio.
                // With a suspended context, source.start() against a stale frozen
                // ctx.currentTime would fire the track at the wrong audio-clock time.
                return ctx.resume().then(() => startCapture(ctx, stream));
            }).then(() => {
                if (requestId !== pendingRecordingRequestId || !captureActive) {
                    discardCapture();
                    return;
                }

                // Play calibration track (one-shot, no loop)
                const gainNode = ctx.createGain();
                gainNode.gain.setValueAtTime(1.0, ctx.currentTime);
                const source = ctx.createBufferSource();
                source.buffer = calibrationTrackBuffer;
                source.connect(gainNode);
                gainNode.connect(ctx.destination);
                const trackStartTime = ctx.currentTime + FIRST_TONE_DELAY_SECONDS;
                source.start(trackStartTime);
                metronomeSourceNode = source;
                metronomeGainNode = gainNode;

                // Slice the capture so t=0 is nominal beat 1 of the track,
                // exact on the audio clock.
                const beatOneTime = trackStartTime + calibrationFirstBeatMs / 1000;
                recordStartFrame = Math.round(beatOneTime * ctx.sampleRate);

                // UI phase flip at beat 1 (cosmetic; capture is frame-indexed)
                recordingDelayTimeout = setTimeout(() => {
                    if (requestId !== pendingRecordingRequestId || currentRecordingPhase !== 'delay') return;
                    setRecordingPhase('recording');
                }, Math.max(0, (beatOneTime - ctx.currentTime) * 1000));

                // Stop shortly after the track ends
                const stopDelayMs = (trackStartTime + calibrationTrackBuffer.duration + 0.5 - ctx.currentTime) * 1000;
                recordingTimeout = setTimeout(() => {
                    if (requestId !== pendingRecordingRequestId) return;
                    // Normal completion -- cancel the safety net before finishing
                    // so no stale timer can race with the async processing chain.
                    if (calibrationSafetyNetTimeout !== null) {
                        clearTimeout(calibrationSafetyNetTimeout);
                        calibrationSafetyNetTimeout = null;
                    }
                    console.log('Calibration recording: scheduled stop reached');
                    finishActiveRecording('calibration');
                }, stopDelayMs);

            }).catch(err => {
                reportJsError('startCalibration failed: ' + err);
                cancelPendingRecording();
                restoreCalibrateButton();
            });

            // Safety net: stored so the NEXT startCalibration call can cancel it.
            // Without this, stale timers from earlier calibrations fire during later
            // ones and interfere (the historic hang bug).
            calibrationSafetyNetTimeout = setTimeout(() => {
                calibrationSafetyNetTimeout = null;
                console.log('[CAL-DIAG] safety-net fired: calibrationMode=' + calibrationMode
                    + ' phase=' + currentRecordingPhase);
                if (calibrationMode || currentRecordingPhase !== 'idle') {
                    console.log('[CAL-DIAG] safety-net discarding stuck calibration');
                    cancelPendingRecording();
                    restoreCalibrateButton();
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
                    reportJsError('reconfigureMetronome: startMetronome rejected: ' + err);
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

                    // Preload the capture worklet module so the first recording
                    // doesn't pay the addModule latency.
                    ensureCaptureWorklet(ctx).catch(err => console.warn('warmup: worklet preload failed:', err));

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
    reportJsError('recorder.js init failed: ' + initErr);
    // Install stubs so Dash doesn't cascade-crash on undefined.method() calls
    window.recorderControls = {
        toggleRecording: function () {
            reportJsError('recorder not initialized');
            return false;
        },
        playAudio: function () {
            reportJsError('recorder not initialized');
            return false;
        },
        toggleMetronome: function () {
            reportJsError('recorder not initialized');
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

console.log(`recorder.js version ${VERSION} loaded successfully. recorderControls is ready.`);
