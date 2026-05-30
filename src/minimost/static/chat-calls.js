// ── Calling ───────────────────────────────────────────────────────────────────

let activeCallId        = null;
let incomingCallData    = null;
let localStream         = null;
let callTimerInterval   = null;
let callStartTime       = null;
let callStatePollId     = null;
let audioMuted          = false;
let ringAudio           = null;
let callingAudio        = null;
let ringTimeoutId       = null;
let incomingRingTimeout = null;
const RING_TIMEOUT_MS   = 30000;
let _notifiedShareId    = null;

// Per-participant remote state: username → { audioPollId, audioPollingActive,
//   lastAudioSeq, audioNextPlayTime, vadAnalyser, vadPollId, tileEl }
const remoteParticipants = new Map();
let sharedAudioCtx       = null;   // one AudioContext for all remote audio
let audioCaptureCleaner  = null;   // tears down the sender-side capture graph

// HTTP media relay — screen share (sender side)
let screenStream         = null;
let screenRecorder       = null;
let screenEnabled        = false;
// HTTP media relay — screen share (receiver side)
let currentScreenSender  = null;   // username whose :screen track we're receiving
let screenPollId         = null;
let lastScreenSeq        = -1;
let screenInitReceived   = false;
let screenPollingActive  = false;
let screenMediaSource    = null;
let screenSourceBuffer   = null;
let screenPendingChunks  = [];
let screenMediaAbortCtrl = null;

// Invite panel: all users list cached for filtering
let _inviteAllUsers      = [];

// ── Standalone screen share ────────────────────────────────────────────────────
// Sharer side
let standaloneShareId     = null;
let standaloneShareStream = null;
let standaloneShareRec    = null;
let standaloneFirstChunk  = true;
let standaloneShareChain  = Promise.resolve();
// Viewer side
let viewShareId           = null;
let viewShareDownId       = null;
let viewShareLastSeq      = -1;
let viewShareInitReceived = false;
let viewShareMediaSource  = null;
let viewShareSourceBuffer = null;
let viewSharePending      = [];
let viewShareAbortCtrl    = null;
let viewSharePollingActive = false;
// Shared: the most recently polled active share (other than ours) for this channel
let _currentRemoteShare   = null;

function updateCallButton() {
    const btn = document.getElementById("call-btn");
    if (!btn) return;
    const eligible = channel.startsWith("dm:") || channel.startsWith("private:");
    btn.style.display = eligible ? "inline-flex" : "none";
    const sbtn = document.getElementById("topbar-share-btn");
    if (sbtn) sbtn.style.display = eligible ? "inline-flex" : "none";
}

// ── Incoming call UI ──────────────────────────────────────────────────────────

function openIncomingCallUI(callData) {
    incomingCallData = callData;
    document.getElementById("call-caller-name").textContent = callData.initiator;
    document.getElementById("call-incoming").style.display = "flex";
    if (!notifMuted) {
        const a = new Audio("/static/receiving_call.mp3");
        a.loop = true;
        a.play().catch(() => {});
        ringAudio = a;
    }
    incomingRingTimeout = setTimeout(closeIncomingCallUI, RING_TIMEOUT_MS);
    if (nativeNotifEnabled && "Notification" in globalThis && Notification.permission === "granted") {
        new Notification("Incoming Call — MiniMost", {
            body: `${callData.initiator} is calling you`,
            icon: "/static/web-app-manifest-192x192.png",
            tag: "minimost-call",
        });
    }
}

function closeIncomingCallUI() {
    if (incomingRingTimeout) { clearTimeout(incomingRingTimeout); incomingRingTimeout = null; }
    document.getElementById("call-incoming").style.display = "none";
    if (ringAudio) { ringAudio.pause(); ringAudio = null; }
    incomingCallData = null;
}

// ── Active call UI ────────────────────────────────────────────────────────────

function openActiveCallUI() {
    document.getElementById("call-participants-grid").innerHTML = "";
    document.getElementById("call-panel").style.display = "flex";
}

function closeActiveCallUI() {
    document.getElementById("call-panel").style.display = "none";
    document.getElementById("call-participants-grid").innerHTML = "";
    document.getElementById("call-invite-panel").style.display = "none";
    document.getElementById("call-timer").textContent = "0:00";
    const ab = document.getElementById("call-mute-audio-btn");
    ab.classList.remove("muted");
    ab.title = "Mute";
    audioMuted = false;
    screenEnabled = false;
    const sb = document.getElementById("call-screen-btn");
    if (sb) { sb.classList.remove("active"); sb.classList.add("muted"); sb.title = "Share screen"; }
    document.getElementById("call-panel").classList.remove("screen-share-active");
}

function _startCallTimer() {
    callStartTime = Date.now();
    callTimerInterval = setInterval(() => {
        const s = Math.floor((Date.now() - callStartTime) / 1000);
        const m = Math.floor(s / 60);
        document.getElementById("call-timer").textContent =
            `${m}:${(s % 60).toString().padStart(2, "0")}`;
    }, 1000);
}

function _stopCallTimer() {
    clearInterval(callTimerInterval);
    callTimerInterval = null;
}

// ── Media helpers ─────────────────────────────────────────────────────────────

async function _getLocalMedia() {
    return await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
}

function _pickVideoMimeType() {
    const candidates = [
        "video/webm;codecs=vp9",
        "video/webm;codecs=vp8",
        "video/webm",
    ];
    for (const t of candidates) {
        if (typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported(t)) return t;
    }
    return "";
}

async function _startMediaCapture(callId) {
    if (!localStream) return;

    // ── Audio capture via ScriptProcessorNode → raw Int16 PCM ──────────────────
    // ScriptProcessorNode fires every ~85 ms (4096 samples @ 48 kHz) and runs on
    // the main thread, so fetch() is safe to call directly inside the handler.
    // A muted GainNode is required to keep the audio graph active without
    // playing the local microphone through the speaker.
    const audioTracks = localStream.getAudioTracks();
    if (audioTracks.length > 0) {
        try {
            const captureCtx = new AudioContext();
            const audioStream = new MediaStream(audioTracks);
            const source    = captureCtx.createMediaStreamSource(audioStream);
            const processor = captureCtx.createScriptProcessor(4096, 1, 1);
            const sink      = captureCtx.createGain();
            const micAnalyser = captureCtx.createAnalyser();
            micAnalyser.fftSize = 256;
            sink.gain.value = 0;
            source.connect(micAnalyser);
            source.connect(processor);
            processor.connect(sink);
            sink.connect(captureCtx.destination);

            const micLevelEl  = document.getElementById("call-mic-level");
            const micLevelBuf = new Uint8Array(micAnalyser.frequencyBinCount);
            const micLevelPoll = setInterval(() => {
                if (!activeCallId || !micLevelEl) return;
                micAnalyser.getByteTimeDomainData(micLevelBuf);
                let sum = 0;
                for (const s of micLevelBuf) sum += Math.abs(s - 128);
                micLevelEl.style.height = Math.min(100, (sum / micLevelBuf.length) * 5) + "%";
            }, 50);

            let firstChunk  = true;
            let uploadChain = Promise.resolve();
            const rate      = captureCtx.sampleRate;

            processor.onaudioprocess = (evt) => {
                if (!activeCallId) return;
                const float32 = evt.inputBuffer.getChannelData(0);
                const int16   = new Int16Array(float32.length);
                for (let i = 0; i < float32.length; i++) {
                    int16[i] = Math.max(-32768, Math.min(32767, float32[i] * 32768));
                }
                const buf     = int16.buffer.slice(0);
                const isFirst = firstChunk;
                if (firstChunk) firstChunk = false;

                uploadChain = uploadChain.then(async () => {
                    try {
                        if (isFirst) {
                            await fetch(`/calls/${callId}/media`, {
                                method: "POST",
                                headers: { "Content-Type": "application/octet-stream", "X-Track": "audio", "X-Init": "1", "X-Mime": `pcm16/${rate}` },
                                body: buf,
                            });
                        } else {
                            await fetch(`/calls/${callId}/media`, {
                                method: "POST",
                                headers: { "Content-Type": "application/octet-stream", "X-Track": "audio" },
                                body: buf,
                            });
                        }
                    } catch { /* ignore network errors */ }
                });
            };

            audioCaptureCleaner = () => {
                clearInterval(micLevelPoll);
                if (micLevelEl) micLevelEl.style.height = "0%";
                source.disconnect();
                processor.disconnect();
                sink.disconnect();
                captureCtx.close().catch(() => {});
            };
        } catch (e) {
            console.warn("Audio capture setup failed:", e);
        }
    }
}

function _stopMediaCapture() {
    if (audioCaptureCleaner) { audioCaptureCleaner(); audioCaptureCleaner = null; }
}

function _b64ToBuffer(b64) {
    const bin = atob(b64);
    const arr = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) arr[i] = bin.codePointAt(i);
    return arr.buffer;
}

// ── Per-participant audio + VAD ────────────────────────────────────────────────

function _playPcmChunkFor(pState, arrayBuffer) {
    if (!sharedAudioCtx) return;
    const samples = Math.floor(arrayBuffer.byteLength / 2);
    if (samples === 0) return;
    const int16   = new Int16Array(arrayBuffer, 0, samples);
    const float32 = new Float32Array(samples);
    for (let i = 0; i < samples; i++) float32[i] = int16[i] / 32768;
    const buf = sharedAudioCtx.createBuffer(1, samples, sharedAudioCtx.sampleRate);
    buf.getChannelData(0).set(float32);
    const src = sharedAudioCtx.createBufferSource();
    src.buffer = buf;
    src.connect(pState.vadAnalyser || sharedAudioCtx.destination);
    const now = sharedAudioCtx.currentTime;
    if (pState.audioNextPlayTime < now - 0.3 || pState.audioNextPlayTime > now + 0.5) {
        pState.audioNextPlayTime = now + 0.05;
    }
    src.start(pState.audioNextPlayTime);
    pState.audioNextPlayTime += buf.duration;
}

function _startParticipantPolling(username, pState) {
    pState.lastAudioSeq       = -1;
    pState.audioPollingActive = false;
    pState.audioNextPlayTime  = 0;

    pState.audioPollId = setInterval(async () => {
        if (!activeCallId || pState.audioPollingActive) return;
        pState.audioPollingActive = true;
        try {
            const sender = encodeURIComponent(username + ":audio");
            const resp = await fetch(
                `/calls/${activeCallId}/media?sender=${sender}&after=${pState.lastAudioSeq}`
            );
            if (!resp.ok) return;
            const data = await resp.json();
            if (data.init && !pState.vadAnalyser) {
                const rate = parseInt((data.mime_type || "pcm16/48000").split("/")[1]) || 48000;
                if (!sharedAudioCtx) {
                    try { sharedAudioCtx = new AudioContext({ sampleRate: rate }); }
                    catch { sharedAudioCtx = new AudioContext(); }
                }
                pState.vadAnalyser = sharedAudioCtx.createAnalyser();
                pState.vadAnalyser.fftSize = 256;
                pState.vadAnalyser.connect(sharedAudioCtx.destination);
            }
            const chunks = data.chunks || [];
            if (chunks.length > 0) {
                pState.lastAudioSeq = chunks[chunks.length - 1].seq;
                const toPlay = chunks.length > 2 ? chunks.slice(-2) : chunks;
                for (const chunk of toPlay) _playPcmChunkFor(pState, _b64ToBuffer(chunk.data));
            }
        } catch { /* ignore transient errors */ }
        finally { pState.audioPollingActive = false; }
    }, 100);

    pState.vadPollId = setInterval(() => {
        const ring = pState.tileEl?.querySelector(".call-speaking-ring");
        if (!ring) return;
        if (!pState.vadAnalyser) { ring.classList.remove("speaking"); return; }
        const buf = new Uint8Array(pState.vadAnalyser.frequencyBinCount);
        pState.vadAnalyser.getByteFrequencyData(buf);
        let sum = 0;
        for (const v of buf) sum += v;
        ring.classList.toggle("speaking", sum / buf.length > 8);
    }, 100);
}

// ── Participant tile management ────────────────────────────────────────────────

function _createParticipantTile(username) {
    const tile = document.createElement("div");
    tile.className = "call-participant-tile";
    tile.dataset.username = username;

    const avatarWrap = document.createElement("div");
    avatarWrap.className = "call-participant-avatar";

    const ring = document.createElement("div");
    ring.className = "call-speaking-ring";
    avatarWrap.appendChild(ring);
    avatarWrap.appendChild(makeAvatarWrap(username, 100));

    const nameEl = document.createElement("span");
    nameEl.className = "call-participant-name";
    nameEl.textContent = username;

    tile.appendChild(avatarWrap);
    tile.appendChild(nameEl);
    document.getElementById("call-participants-grid").appendChild(tile);
    return tile;
}

function _updateCallGrid() {
    const n = remoteParticipants.size;
    const grid = document.getElementById("call-participants-grid");
    if (!grid) return;
    if (n <= 1)      grid.style.gridTemplateColumns = "1fr";
    else if (n === 2) grid.style.gridTemplateColumns = "1fr 1fr";
    else              grid.style.gridTemplateColumns = "1fr 1fr";
}

function _addRemoteParticipant(username) {
    if (remoteParticipants.has(username)) return;
    const tile = _createParticipantTile(username);
    const pState = {
        audioPollId: null, audioPollingActive: false,
        lastAudioSeq: -1,  audioNextPlayTime: 0,
        vadAnalyser: null,  vadPollId: null,
        tileEl: tile,
    };
    remoteParticipants.set(username, pState);
    _startParticipantPolling(username, pState);
    _updateCallGrid();
}

function _removeRemoteParticipant(username) {
    const pState = remoteParticipants.get(username);
    if (!pState) return;
    clearInterval(pState.audioPollId);
    clearInterval(pState.vadPollId);
    if (pState.tileEl) pState.tileEl.remove();
    remoteParticipants.delete(username);
    // Only play the departure sound when the call is still ongoing — activeCallId
    // is null during full teardown (_cleanupCall), so this won't fire then.
    if (activeCallId) {
        const lc = new Audio("/static/left_call.mp3"); lc.volume = 0.4; lc.play().catch(() => {});
    }
    // If this participant was screensharing, dismiss the screen view immediately
    // rather than waiting for the next _pollCallState tick.
    if (username === currentScreenSender) {
        _stopScreenReceiving();
        currentScreenSender = null;
        lastScreenSeq       = -1;
        screenInitReceived  = false;
    }
    _updateCallGrid();
}

function _removeAllParticipants() {
    for (const username of [...remoteParticipants.keys()]) {
        _removeRemoteParticipant(username);
    }
    if (sharedAudioCtx) { sharedAudioCtx.close().catch(() => {}); sharedAudioCtx = null; }
}

// ── Screen receive polling (sender set by state poll via currentScreenSender) ──

function _startScreenPoll() {
    lastScreenSeq       = -1;
    screenInitReceived  = false;
    screenPollingActive = false;
    screenPendingChunks = [];
    screenMediaSource   = null;
    screenSourceBuffer  = null;
    screenPollId = setInterval(_pollScreenMedia, 500);
}

function _stopScreenPoll() {
    clearInterval(screenPollId);
    screenPollId = null;
    screenPollingActive = false;
    _stopScreenReceiving();
}

// ── Screen share ──────────────────────────────────────────────────────────────

function _appendNextScreenChunk() {
    if (!screenSourceBuffer || screenSourceBuffer.updating || screenPendingChunks.length === 0) return;
    const buf = screenPendingChunks.shift();
    try {
        screenSourceBuffer.appendBuffer(buf);
    } catch (e) {
        if (e.name === "QuotaExceededError" && screenSourceBuffer.buffered.length > 0) {
            screenPendingChunks.unshift(buf);
            try {
                const last  = screenSourceBuffer.buffered.length - 1;
                const start = screenSourceBuffer.buffered.start(last);
                const end   = screenSourceBuffer.buffered.end(last);
                if (end - start > 10) screenSourceBuffer.remove(start, end - 5);
            } catch { /* ignore */ }
        } else {
            setTimeout(_appendNextScreenChunk, 0);
        }
    }
}

function _enqueueScreenChunk(buf) {
    screenPendingChunks.push(buf);
    if (screenSourceBuffer && !screenSourceBuffer.updating) _appendNextScreenChunk();
}

function _initScreenMediaSource(mimeType) {
    if (screenMediaAbortCtrl) screenMediaAbortCtrl.abort();
    screenMediaAbortCtrl = new AbortController();
    const { signal } = screenMediaAbortCtrl;

    const videoEl = document.getElementById("call-screen-video");
    screenMediaSource = new MediaSource();
    videoEl.src = URL.createObjectURL(screenMediaSource);
    videoEl.play().catch(() => {});

    videoEl.addEventListener("waiting", () => {
        if (screenSourceBuffer && !screenSourceBuffer.updating && screenPendingChunks.length > 0) {
            _appendNextScreenChunk();
        }
        videoEl.play().catch(() => {});
    }, { signal });

    screenMediaSource.addEventListener("sourceopen", () => {
        try {
            screenSourceBuffer = screenMediaSource.addSourceBuffer(mimeType);
            screenSourceBuffer.addEventListener("updateend", () => {
                if (screenPendingChunks.length > 0) {
                    _appendNextScreenChunk();
                } else if (screenSourceBuffer.buffered.length > 0) {
                    // Queue drained — seek to live edge if significantly behind.
                    const last = screenSourceBuffer.buffered.length - 1;
                    const end  = screenSourceBuffer.buffered.end(last);
                    if (end - videoEl.currentTime > 1.5) {
                        videoEl.currentTime = end - 0.1;
                    }
                    const head   = screenSourceBuffer.buffered.start(last);
                    const cutoff = end - 3.0;
                    if (cutoff > head + 0.05) {
                        try { screenSourceBuffer.remove(head, cutoff); } catch { /* ignore */ }
                        return;
                    }
                }
                videoEl.play().catch(() => {});
            }, { signal });
            _appendNextScreenChunk();
        } catch (e) {
            console.warn("Screen MediaSource setup failed:", e);
        }
    }, { once: true, signal });
}

function _stopScreenReceiving() {
    if (screenMediaAbortCtrl) { screenMediaAbortCtrl.abort(); screenMediaAbortCtrl = null; }
    screenMediaSource   = null;
    screenSourceBuffer  = null;
    screenPendingChunks = [];
    screenInitReceived  = false;
    const sv = document.getElementById("call-screen-video");
    if (sv && sv.src && sv.src.startsWith("blob:")) {
        URL.revokeObjectURL(sv.src);
        sv.removeAttribute("src");
        sv.load();
    }
    document.getElementById("call-panel").classList.remove("screen-share-active");
}

async function _pollScreenMedia() {
    if (!activeCallId || !currentScreenSender || currentScreenSender === CURRENT_USER || screenPollingActive) return;
    screenPollingActive = true;
    try {
        const sender = encodeURIComponent(currentScreenSender + ":screen");
        const resp = await fetch(
            `/calls/${activeCallId}/media?sender=${sender}&after=${lastScreenSeq}`
        );
        if (!resp.ok) return;
        const data = await resp.json();

        if (data.init) {
            if (data.mime_type === "screen/off" && screenInitReceived) {
                _stopScreenReceiving();
            } else if (!screenInitReceived && data.mime_type !== "screen/off") {
                screenInitReceived = true;
                _initScreenMediaSource(data.mime_type || "video/webm");
                document.getElementById("call-panel").classList.add("screen-share-active");
                _enqueueScreenChunk(_b64ToBuffer(data.init));
            }
        }

        for (const chunk of (data.chunks || [])) {
            lastScreenSeq = Math.max(lastScreenSeq, chunk.seq);
            if (screenInitReceived) _enqueueScreenChunk(_b64ToBuffer(chunk.data));
        }
    } catch { /* ignore transient errors */ }
    finally {
        screenPollingActive = false;
    }
}

function _startScreenCapture(callId, displayStream) {
    const videoTracks = displayStream.getVideoTracks();
    if (videoTracks.length === 0) {
        console.error("Screen share stream has no video tracks.");
        displayStream.getTracks().forEach(t => t.stop());
        return false;
    }

    screenStream = displayStream;
    const videoMime = _pickVideoMimeType();
    let screenFirstChunk = true;
    let screenChain = Promise.resolve();
    try {
        screenRecorder = new MediaRecorder(displayStream, videoMime ? { mimeType: videoMime } : {});
    } catch {
        try {
            screenRecorder = new MediaRecorder(displayStream);
        } catch (e) {
            console.error("MediaRecorder unavailable for screen stream:", e);
            displayStream.getTracks().forEach(t => t.stop());
            screenStream = null;
            return false;
        }
    }
    screenRecorder.ondataavailable = (evt) => {
        if (!evt.data || evt.data.size === 0 || !activeCallId) return;
        const isFirst = screenFirstChunk;
        if (isFirst) screenFirstChunk = false;
        evt.data.arrayBuffer().then(buf => {
            if (isFirst) {
                // Init segment must arrive before any data chunk so the remote
                // can bootstrap its SourceBuffer.  Only init is sequenced.
                const mime = screenRecorder?.mimeType || "video/webm";
                screenChain = screenChain.then(() =>
                    fetch(`/calls/${callId}/media`, {
                        method: "POST",
                        headers: {
                            "Content-Type": "application/octet-stream",
                            "X-Track": "screen",
                            "X-Init": "1",
                            "X-Mime": mime,
                        },
                        body: buf,
                    }).catch(() => {})
                );
            } else {
                // Data chunks are fire-and-forget so a slow upload cannot
                // cause subsequent chunks to accumulate upload delay.
                fetch(`/calls/${callId}/media`, {
                    method: "POST",
                    headers: { "Content-Type": "application/octet-stream", "X-Track": "screen" },
                    body: buf,
                }).catch(() => {});
            }
        });
    };
    // Handle the user clicking the browser's native "Stop sharing" button
    videoTracks[0].addEventListener("ended", () => {
        if (screenEnabled) toggleScreenShare();
    });
    screenRecorder.start(500);
    return true;
}

function _stopScreenCapture() {
    if (screenRecorder && screenRecorder.state !== "inactive") screenRecorder.stop();
    screenRecorder = null;
    if (screenStream) { screenStream.getTracks().forEach(t => t.stop()); screenStream = null; }
    // Signal to the remote side that screen sharing has stopped
    if (activeCallId) {
        fetch(`/calls/${activeCallId}/media`, {
            method: "POST",
            headers: {
                "Content-Type": "application/octet-stream",
                "X-Track": "screen",
                "X-Init": "1",
                "X-Mime": "screen/off",
            },
            body: new Uint8Array([0]),
        }).catch(() => {});
    }
}

async function toggleScreenShare() {
    if (!localStream || !activeCallId) return;
    const btn = document.getElementById("call-screen-btn");
    if (screenEnabled) {
        screenEnabled = false;
        _stopScreenCapture();
        btn.classList.remove("active");
        btn.classList.add("muted");
        btn.title = "Share screen";
    } else {
        // getDisplayMedia must be called directly in the user-gesture handler —
        // calling it from a nested async function drops the activation token in
        // some browsers, causing a NotAllowedError.
        if (!navigator.mediaDevices?.getDisplayMedia) {
            alert("Your browser does not support screen sharing.");
            return;
        }
        let displayStream;
        try {
            displayStream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: false });
        } catch (e) {
            console.warn("Screen share failed:", e);
            return;
        }
        if (!displayStream) return;
        let ok = false;
        try {
            ok = _startScreenCapture(activeCallId, displayStream);
        } catch (e) {
            console.error("Screen capture setup failed:", e);
            displayStream.getTracks().forEach(t => t.stop());
        }
        if (!ok) return;
        screenEnabled = true;
        btn.classList.add("active");
        btn.classList.remove("muted");
        btn.title = "Stop sharing screen";
    }
}

// ── Standalone screen share ────────────────────────────────────────────────────

async function toggleStandaloneScreenShare() {
    if (standaloneShareId) {
        await _stopStandaloneShare();
    } else {
        // getDisplayMedia must be called directly in the user-gesture handler
        if (!navigator.mediaDevices?.getDisplayMedia) {
            alert("Your browser does not support screen sharing.");
            return;
        }
        let displayStream;
        try {
            displayStream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: false });
        } catch (e) {
            console.warn("Screen share cancelled:", e);
            return;
        }
        if (!displayStream) return;
        await _startStandaloneShare(displayStream);
    }
}

async function _startStandaloneShare(displayStream) {
    const videoTracks = displayStream.getVideoTracks();
    if (videoTracks.length === 0) {
        displayStream.getTracks().forEach(t => t.stop());
        return;
    }

    // Register share on server first
    const resp = await fetch("/screenshare/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ channel }),
    }).catch(() => null);
    if (!resp || !resp.ok) {
        displayStream.getTracks().forEach(t => t.stop());
        return;
    }
    const { share_id } = await resp.json();
    standaloneShareId     = share_id;
    standaloneShareStream = displayStream;
    standaloneFirstChunk  = true;
    standaloneShareChain  = Promise.resolve();

    const videoMime = _pickVideoMimeType();
    try {
        standaloneShareRec = new MediaRecorder(displayStream, videoMime ? { mimeType: videoMime } : {});
    } catch {
        try { standaloneShareRec = new MediaRecorder(displayStream); } catch (e) {
            console.error("MediaRecorder unavailable for standalone share:", e);
            displayStream.getTracks().forEach(t => t.stop());
            standaloneShareId = null;
            standaloneShareStream = null;
            return;
        }
    }

    standaloneShareRec.ondataavailable = (evt) => {
        if (!evt.data || evt.data.size === 0 || !standaloneShareId) return;
        const id = standaloneShareId;
        const isFirst = standaloneFirstChunk;
        if (isFirst) standaloneFirstChunk = false;
        evt.data.arrayBuffer().then(buf => {
            const headers = { "Content-Type": "application/octet-stream" };
            if (isFirst) {
                headers["X-Init"] = "1";
                headers["X-Mime"] = standaloneShareRec?.mimeType || "video/webm";
                // Init segment must complete before data chunks so the receiver
                // can initialise its SourceBuffer; subsequent chunks are fire-and-forget.
                standaloneShareChain = standaloneShareChain.then(() =>
                    fetch(`/screenshare/${id}/media`, { method: "POST", headers, body: buf })
                        .catch(() => {})
                );
            } else {
                fetch(`/screenshare/${id}/media`, { method: "POST", headers, body: buf })
                    .catch(() => {});
            }
        });
    };

    // Handle user clicking the browser's native "Stop sharing" button
    videoTracks[0].addEventListener("ended", () => {
        if (standaloneShareId) _stopStandaloneShare();
    });

    standaloneShareRec.start(500);

    // Force the browser to flush the init segment early so the viewer can
    // bootstrap its SourceBuffer ~400 ms sooner than the first 500 ms tick.
    setTimeout(() => {
        if (standaloneShareRec && standaloneShareRec.state === "recording") {
            standaloneShareRec.requestData();
        }
    }, 100);

    const sbtn = document.getElementById("topbar-share-btn");
    if (sbtn) { sbtn.classList.add("active"); sbtn.title = "Stop sharing"; }
}

async function _stopStandaloneShare() {
    const id = standaloneShareId;
    standaloneShareId = null;
    if (standaloneShareRec && standaloneShareRec.state !== "inactive") {
        standaloneShareRec.stop();
    }
    standaloneShareRec    = null;
    standaloneFirstChunk  = true;
    if (standaloneShareStream) {
        standaloneShareStream.getTracks().forEach(t => t.stop());
        standaloneShareStream = null;
    }
    if (id) await fetch(`/screenshare/${id}/stop`, { method: "POST" }).catch(() => {});
    const sbtn = document.getElementById("topbar-share-btn");
    if (sbtn) { sbtn.classList.remove("active"); sbtn.title = "Share screen"; }
}

// Polled every 1 s to detect when someone else starts/stops sharing.
async function refreshScreenShares() {
    if (!channel || (!channel.startsWith("dm:") && !channel.startsWith("private:"))) return;
    let shares;
    try {
        const resp = await fetch(`/screenshare/active?channel=${encodeURIComponent(channel)}`);
        if (!resp.ok) return;
        shares = await resp.json();
    } catch { return; }

    const others = shares.filter(s => s.sharer !== CURRENT_USER);

    if (others.length === 0) {
        // No one else is sharing — hide banner and close viewer if open
        _currentRemoteShare = null;
        document.getElementById("screenshare-banner").style.display = "none";
        if (viewShareId) closeShareViewer();
        return;
    }

    const share = others[0];
    _currentRemoteShare = share;

    // Update banner text
    const banner = document.getElementById("screenshare-banner");
    document.getElementById("screenshare-banner-text").textContent =
        `${share.sharer} is sharing their screen`;

    if (viewShareId === share.share_id) {
        // Already viewing this share — keep viewer open, hide banner
        banner.style.display = "none";
        return;
    }

    if (viewShareId && viewShareId !== share.share_id) {
        // A different share started while we were viewing another — switch
        closeShareViewer();
    }

    // Show the banner (not auto-opening the viewer to avoid surprise)
    document.getElementById("screenshare-banner-view-btn").style.display = "inline-flex";
    banner.style.display = "flex";

    if (document.hidden && share.share_id !== _notifiedShareId &&
            nativeNotifEnabled && "Notification" in globalThis && Notification.permission === "granted") {
        _notifiedShareId = share.share_id;
        new Notification("Screen Share — MiniMost", {
            body: `${share.sharer} is sharing their screen`,
            icon: "/static/web-app-manifest-192x192.png",
            tag: "minimost-screenshare",
        });
    }
}

function openShareViewer() {
    const share = _currentRemoteShare;
    if (!share) return;
    viewShareId            = share.share_id;
    viewShareLastSeq       = -1;
    viewShareInitReceived  = false;
    viewSharePending       = [];
    viewSharePollingActive = false;

    document.getElementById("screenshare-viewer-label").textContent =
        `${share.sharer} is sharing their screen`;
    document.getElementById("screenshare-viewer").style.display = "flex";
    document.getElementById("screenshare-banner").style.display = "none";

    _initShareMediaSource();
    viewShareDownId = setInterval(_pollShareViewerMedia, 500);
}

function closeShareViewer() {
    if (viewShareDownId) { clearInterval(viewShareDownId); viewShareDownId = null; }
    if (viewShareAbortCtrl) { viewShareAbortCtrl.abort(); viewShareAbortCtrl = null; }
    if (viewShareMediaSource && viewShareMediaSource.readyState === "open") {
        try { viewShareMediaSource.endOfStream(); } catch { /* ignore */ }
    }
    viewShareId            = null;
    viewShareMediaSource   = null;
    viewShareSourceBuffer  = null;
    viewSharePending       = [];
    viewShareInitReceived  = false;
    viewSharePollingActive = false;
    const el = document.getElementById("screenshare-viewer-video");
    if (el.src && el.src.startsWith("blob:")) URL.revokeObjectURL(el.src);
    el.removeAttribute("src");
    el.load();
    document.getElementById("screenshare-viewer").style.display = "none";
    // Show banner again if share is still active
    if (_currentRemoteShare) {
        document.getElementById("screenshare-banner").style.display = "flex";
    }
}

function _initShareMediaSource() {
    const videoEl = document.getElementById("screenshare-viewer-video");
    const ctrl = new AbortController();
    viewShareAbortCtrl = ctrl;
    const ms = new MediaSource();
    viewShareMediaSource = ms;
    if (videoEl.src?.startsWith("blob:")) URL.revokeObjectURL(videoEl.src);
    videoEl.src = URL.createObjectURL(ms);

    // Fire first poll as soon as MediaSource is open instead of waiting up to
    // 500 ms for the setInterval tick, cutting initial latency significantly.
    ms.addEventListener("sourceopen", () => { _pollShareViewerMedia(); }, { once: true });

    // If the video stalls (e.g. pending queue was temporarily empty), drive
    // any queued chunks through and resume playback.
    videoEl.addEventListener("waiting", () => {
        _appendNextShareChunk();
        if (videoEl.paused) videoEl.play().catch(() => {});
    }, { signal: ctrl.signal });
}

// Called once, after the first poll response supplies the real MIME type.
function _createShareSourceBuffer(mimeType) {
    const ms = viewShareMediaSource;
    if (!ms || ms.readyState !== "open") return false;
    const videoEl = document.getElementById("screenshare-viewer-video");
    const signal  = viewShareAbortCtrl?.signal;
    let sb;
    try {
        sb = ms.addSourceBuffer(mimeType);
    } catch {
        try { sb = ms.addSourceBuffer("video/webm"); } catch { return false; }
    }
    sb.mode = "segments";
    viewShareSourceBuffer = sb;

    sb.addEventListener("updateend", () => {
        // ① Seek to live edge BEFORE enqueueing more data.
        //    If we called _appendNextShareChunk() first it would set
        //    sb.updating = true and the seek check would never execute.
        if (sb.buffered.length > 0) {
            // Use the LAST buffered range — the init segment always has timestamps
            // near 0 while late-joiner data chunks sit at a much later timestamp,
            // producing two separate ranges. end(0) would point to the init range,
            // not the live edge.
            const last = sb.buffered.length - 1;
            const end  = sb.buffered.end(last);
            if (end - videoEl.currentTime > 0.2) videoEl.currentTime = end - 0.05;
            // Trim old data from the start of the live range (last range).
            const head   = sb.buffered.start(last);
            const cutoff = end - 2.0;
            if (cutoff > head + 0.05) {
                // ② remove() triggers another updateend which then appends.
                try { sb.remove(head, cutoff); } catch { /* ignore */ }
                return;
            }
        }
        _appendNextShareChunk();
        if (videoEl.paused) videoEl.play().catch(() => {});
    }, signal ? { signal } : {});

    // Safety net: if the player drifts behind the live edge jump it forward.
    videoEl.addEventListener("timeupdate", () => {
        if (!viewShareSourceBuffer || viewShareSourceBuffer.updating) return;
        if (sb.buffered.length === 0) return;
        const last = sb.buffered.length - 1;
        const end  = sb.buffered.end(last);
        if (end - videoEl.currentTime > 1.0) videoEl.currentTime = end - 0.05;
    }, signal ? { signal } : {});

    return true;
}

function _appendNextShareChunk() {
    const sb = viewShareSourceBuffer;
    if (!sb || sb.updating) return;
    if (viewSharePending.length === 0) return;
    if (viewShareMediaSource?.readyState !== "open") return;
    // ③ Peek before shifting — if appendBuffer throws the chunk stays in the queue.
    const chunk = viewSharePending[0];
    try {
        sb.appendBuffer(chunk);
        viewSharePending.shift();
    } catch (e) {
        if (e.name === "QuotaExceededError" && sb.buffered.length > 0) {
            const last  = sb.buffered.length - 1;
            const start = sb.buffered.start(last);
            const end   = sb.buffered.end(last);
            if (end - start > 2) {
                try { sb.remove(start, end - 1); } catch { /* ignore */ }
            }
        }
    }
}

async function _pollShareViewerMedia() {
    if (!viewShareId) return;
    if (viewSharePollingActive) return;
    viewSharePollingActive = true;
    let payload;
    try {
        const resp = await fetch(`/screenshare/${viewShareId}/media?after=${viewShareLastSeq}`);
        if (!resp.ok) { viewSharePollingActive = false; return; }
        payload = await resp.json();
    } catch { viewSharePollingActive = false; return; }
    viewSharePollingActive = false;

    if (payload.active === false) { closeShareViewer(); return; }

    if (payload.init && !viewShareInitReceived) {
        // MediaSource may not be open yet on the very first poll — retry next tick.
        if (viewShareMediaSource?.readyState !== "open") return;
        const mimeType = payload.mime_type || "video/webm";
        if (!_createShareSourceBuffer(mimeType)) return;
        viewShareInitReceived = true;
        viewSharePending.unshift(_b64ToBuffer(payload.init));
    }
    for (const chunk of payload.chunks) {
        viewShareLastSeq = chunk.seq;
        viewSharePending.push(_b64ToBuffer(chunk.data));
    }
    _appendNextShareChunk();
}

// Clean up standalone share state when switching channels
function _cleanupStandaloneShare() {
    if (standaloneShareId) _stopStandaloneShare();
    if (viewShareId) closeShareViewer();
    _currentRemoteShare = null;
    document.getElementById("screenshare-banner").style.display = "none";
}

// ── Call actions ──────────────────────────────────────────────────────────────

function _requireSecureContext() {
    if (globalThis.isSecureContext && navigator.mediaDevices) return true;
    alert("Calling requires a secure connection (HTTPS). MiniMost generates a self-signed certificate automatically on first run — check that you are connecting via https://.");
    return false;
}

async function startCall() {
    if (activeCallId) return;
    if (!_requireSecureContext()) return;

    // Acquire the microphone BEFORE creating the call on the server.
    // If we created the call first and then getUserMedia timed out or was denied,
    // the catch block would call /end while Alice is the only accepted participant,
    // ending the call immediately — giving Bob only a few seconds of ring time.
    try {
        localStream = await _getLocalMedia();
    } catch (err) {
        console.warn("Microphone access denied:", err);
        alert("Could not access your microphone. Please check your browser permissions.");
        return;
    }

    const resp = await fetch("/calls/initiate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ channel }),
    });
    if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        alert(err.error || "Could not start call");
        if (localStream) { localStream.getTracks().forEach(t => t.stop()); localStream = null; }
        return;
    }

    const data = await resp.json();
    activeCallId = data.call_id;

    try {
        openActiveCallUI();
        _startCallTimer();
        if (!notifMuted) {
            callingAudio = new Audio("/static/calling.mp3");
            callingAudio.volume = 0.4;
            callingAudio.loop = true;
            callingAudio.play().catch(() => {});
        }
        await _startMediaCapture(activeCallId);
        _startScreenPoll();
        _startCallStatePolling();
        ringTimeoutId = setTimeout(_handleRingTimeout, RING_TIMEOUT_MS);
    } catch (err) {
        console.error("Call setup failed:", err);
        const callId = activeCallId;
        activeCallId = null;
        await fetch(`/calls/${callId}/end`, { method: "POST" }).catch(() => {});
        _cleanupCall();
    }
}

async function _handleRingTimeout() {
    ringTimeoutId = null;
    if (!activeCallId) return;
    const callId = activeCallId;
    activeCallId = null;
    await fetch(`/calls/${callId}/end`, { method: "POST" }).catch(() => {});
    document.getElementById("call-timer").textContent = "No answer";
    const hu2 = new Audio("/static/hang_up.mp3"); hu2.volume = 0.4; hu2.play().catch(() => {});
    setTimeout(_cleanupCall, 2000);
}

async function acceptCall() {
    if (!incomingCallData) return;
    if (!_requireSecureContext()) { closeIncomingCallUI(); return; }

    const { call_id, initiator } = incomingCallData;

    const resp = await fetch(`/calls/${call_id}/accept`, { method: "POST" });
    closeIncomingCallUI();
    if (!resp.ok) return;
    activeCallId = call_id;

    try {
        localStream = await _getLocalMedia();
        openActiveCallUI();
        _startCallTimer();
        await _startMediaCapture(activeCallId);
        _startScreenPoll();
        _startCallStatePolling();
    } catch (err) {
        console.error("Call accept failed:", err);
        const callId = activeCallId;
        activeCallId = null;
        await fetch(`/calls/${callId}/end`, { method: "POST" }).catch(() => {});
        _cleanupCall();
    }
}

async function rejectCall() {
    if (!incomingCallData) return;
    const { call_id } = incomingCallData;
    closeIncomingCallUI();
    await fetch(`/calls/${call_id}/reject`, { method: "POST" }).catch(() => {});
}

async function endCall() {
    if (!activeCallId) return;
    const callId = activeCallId;
    activeCallId = null;
    await fetch(`/calls/${callId}/end`, { method: "POST" }).catch(() => {});
    const hu1 = new Audio("/static/hang_up.mp3"); hu1.volume = 0.4; hu1.play().catch(() => {});
    _cleanupCall();
}

function _cleanupCall() {
    if (callingAudio) { callingAudio.pause(); callingAudio = null; }
    if (ringTimeoutId) { clearTimeout(ringTimeoutId); ringTimeoutId = null; }
    _stopCallTimer();
    clearInterval(callStatePollId); callStatePollId = null;
    _removeAllParticipants();
    _stopScreenPoll();
    currentScreenSender = null;
    _stopMediaCapture();
    if (screenEnabled) { _stopScreenCapture(); screenEnabled = false; }
    closeActiveCallUI();
    if (localStream) { localStream.getTracks().forEach(t => t.stop()); localStream = null; }
}

function toggleAudioMute() {
    if (!localStream) return;
    audioMuted = !audioMuted;
    localStream.getAudioTracks().forEach(t => { t.enabled = !audioMuted; });
    const btn = document.getElementById("call-mute-audio-btn");
    btn.classList.toggle("muted", audioMuted);
    btn.title = audioMuted ? "Unmute" : "Mute";
}


// ── Call-state polling (3 s) — detects remote hang-up ────────────────────────

function _startCallStatePolling() {
    callStatePollId = setInterval(_pollCallState, 3000);
}

async function _pollCallState() {
    if (!activeCallId) return;
    try {
        const resp = await fetch(`/calls/${activeCallId}/state`);
        if (!resp.ok) return;
        const data = await resp.json();

        if (data.state === "active" && ringTimeoutId) {
            clearTimeout(ringTimeoutId);
            ringTimeoutId = null;
            if (callingAudio) { callingAudio.pause(); callingAudio = null; }
            const ca1 = new Audio("/static/call_accepted.mp3"); ca1.volume = 0.4; ca1.play().catch(() => {});
        }

        if (data.state === "ended" || data.state === "rejected") {
            activeCallId = null;
            const hu3 = new Audio("/static/hang_up.mp3"); hu3.volume = 0.4; hu3.play().catch(() => {});
            _cleanupCall();
            return;
        }

        // Diff accepted participants (excluding self)
        const accepted = new Set(
            (data.participants || [])
                .filter(p => p.username !== CURRENT_USER && p.state === "accepted")
                .map(p => p.username)
        );
        for (const u of accepted) {
            if (!remoteParticipants.has(u)) _addRemoteParticipant(u);
        }
        for (const u of [...remoteParticipants.keys()]) {
            if (!accepted.has(u)) _removeRemoteParticipant(u);
        }

        // Screenshare sender from server state
        const newSender = data.screenshare_user || null;
        if (newSender !== currentScreenSender) {
            _stopScreenReceiving();
            lastScreenSeq       = -1;
            screenInitReceived  = false;
            currentScreenSender = newSender;
        }
        // Force-stop our own screenshare if someone else took over
        if (screenEnabled && newSender && newSender !== CURRENT_USER) {
            screenEnabled = false;
            _stopScreenCapture();
            const sb = document.getElementById("call-screen-btn");
            if (sb) { sb.classList.remove("active"); sb.classList.add("muted"); sb.title = "Share screen"; }
        }
    } catch { /* ignore transient errors */ }
}

// ── Call invite panel ─────────────────────────────────────────────────────────

async function toggleCallInvitePanel() {
    const panel = document.getElementById("call-invite-panel");
    if (panel.style.display !== "none") {
        panel.style.display = "none";
        return;
    }
    // Fetch all users, cache them
    if (_inviteAllUsers.length === 0) {
        try {
            const r = await fetch("/users");
            _inviteAllUsers = r.ok ? await r.json() : [];
        } catch { _inviteAllUsers = []; }
    }
    document.getElementById("call-invite-search").value = "";
    _renderCallInviteList("");
    panel.style.display = "block";
    document.getElementById("call-invite-search").focus();
}

function filterCallInviteList(query) {
    _renderCallInviteList(query);
}

function _renderCallInviteList(query) {
    const list = document.getElementById("call-invite-list");
    list.innerHTML = "";
    const alreadyIn = new Set([CURRENT_USER, ...remoteParticipants.keys()]);
    const candidates = _inviteAllUsers.filter(u => !alreadyIn.has(u));

    let matches;
    if (!query) {
        matches = candidates.map(u => ({ user: u, indices: [] }));
    } else {
        matches = candidates
            .map(u => ({ user: u, result: fuzzySearch(query, u) }))
            .filter(({ result }) => result !== null)
            .sort((a, b) => b.result.score - a.result.score)
            .map(({ user, result }) => ({ user, indices: result.indices }));
    }

    if (matches.length === 0) {
        const empty = document.createElement("div");
        empty.style.cssText = "padding:12px;color:#888;font-size:13px;text-align:center";
        empty.textContent = query ? "No matches" : "Everyone is already in the call";
        list.appendChild(empty);
        return;
    }
    for (const { user, indices } of matches) {
        const item = document.createElement("div");
        item.className = "call-invite-item";
        item.appendChild(makeAvatarWrap(user, 28));
        const name = document.createElement("span");
        name.innerHTML = indices.length ? highlightFuzzyMatch(user, indices) : escapeHtml(user);
        item.appendChild(name);
        item.onclick = () => _sendCallInvite(user, item);
        list.appendChild(item);
    }
}

async function _sendCallInvite(username, itemEl) {
    if (!activeCallId) return;
    const status = document.createElement("span");
    status.className = "invite-status";
    status.textContent = "Calling…";
    itemEl.appendChild(status);
    itemEl.style.pointerEvents = "none";
    try {
        const resp = await fetch(`/calls/${activeCallId}/invite`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username }),
        });
        status.textContent = resp.ok ? "Invited" : "Failed";
    } catch {
        status.textContent = "Failed";
    }
}

// ── Incoming call polling (1 s) ───────────────────────────────────────────────

function pollIncomingCalls() {
    if (activeCallId) return;
    fetch("/calls/incoming")
        .then(r => r.ok ? r.json() : [])
        .then(calls => {
            if (incomingCallData) {
                const stillRinging = calls.some(c => c.call_id === incomingCallData.call_id);
                if (!stillRinging) closeIncomingCallUI();
                return;
            }
            if (calls.length > 0) openIncomingCallUI(calls[0]);
        })
        .catch(() => {});
}

// Close invite panel when clicking outside it
document.getElementById("call-panel").addEventListener("click", (e) => {
    const panel = document.getElementById("call-invite-panel");
    const btn   = document.getElementById("call-invite-btn");
    if (panel.style.display !== "none"
        && !panel.contains(e.target)
        && !btn.contains(e.target)) {
        panel.style.display = "none";
    }
});

