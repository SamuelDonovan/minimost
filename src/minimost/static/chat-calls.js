// ── Calling ───────────────────────────────────────────────────────────────────
//
// Media travels peer-to-peer over WebRTC (RTCPeerConnection).  The Flask
// backend only owns the call lifecycle state machine (calls / call_participants)
// and relays signaling via /calls/<id>/signal[s].  Because MiniMost is LAN-only
// we configure ICE with no STUN/TURN servers and rely on host candidates.

let activeCallId = null;
let incomingCallData = null;
let localStream = null;
let callTimerInterval = null;
let callStartTime = null;
let callStatePollId = null;
let audioMuted = false;
let ringAudio = null;
let callingAudio = null;
let ringTimeoutId = null;
let incomingRingTimeout = null;
const RING_TIMEOUT_MS = 30000;
let _notifiedShareId = null;

// LAN-only.  Point ICE at the STUN server bundled with the app (served from the
// same host the page was loaded from) so peers gather a real-IP server-reflexive
// candidate.  This avoids the mDNS `.local` host candidates that fail to resolve
// on LANs without avahi/Bonjour.  No public STUN/TURN — works air-gapped.
const RTC_CONFIG = {
  iceServers:
    typeof STUN_PORT !== "undefined" && STUN_PORT
      ? [{ urls: `stun:${globalThis.location.hostname}:${STUN_PORT}` }]
      : [],
};

// Surface ICE/connection state in the console.  On a LAN the most common cause of
// a black screen is ICE failing because browsers emit `*.local` mDNS host
// candidates that the peer's OS cannot resolve (no avahi/Bonjour running).
function _logPeerState(pc, label) {
  let sawMdns = false;
  pc.addEventListener("icecandidate", ({ candidate }) => {
    if (candidate?.candidate?.toLowerCase().includes(".local")) sawMdns = true;
  });
  pc.addEventListener("iceconnectionstatechange", () => {
    const s = pc.iceConnectionState;
    if (s === "connected" || s === "completed") {
      console.info(`WebRTC ICE ${s} (${label})`);
    } else if (s === "failed") {
      // .local candidates are normal; only call them out once the
      // connection actually fails, since the srflx candidate from the
      // bundled STUN server should otherwise win.
      console.warn(
        `WebRTC ICE failed (${label}).` +
          (sawMdns
            ? " No server-reflexive candidate connected — verify the bundled" +
              " STUN server's UDP port is reachable from both peers."
            : " Check that both peers are on the same subnet and UDP is not blocked."),
      );
    } else if (s === "disconnected") {
      console.warn(`WebRTC ICE disconnected (${label})`);
    }
  });
}

// Per-participant remote state: username → {
//   tileEl, pc, polite, makingOffer, ignoreOffer, pendingCandidates,
//   audioEl, vadAnalyser, vadPollId, screenSender }
const remoteParticipants = new Map();
let sharedAudioCtx = null; // one AudioContext for all remote-audio VAD taps

// In-call signaling poll
let callSignalPollId = null;
let lastCallSignalId = 0;
let _callSignalPolling = false;

// In-call screen share (sender side)
let screenStream = null;
let screenEnabled = false;
// In-call screen share (receiver side) — the username whose video we're showing
let currentScreenSender = null;

// Invite panel: all users list cached for filtering
let _inviteAllUsers = [];

// ── Standalone screen share ────────────────────────────────────────────────────
// Sharer side
let standaloneShareId = null;
let standaloneShareStream = null;
let standaloneSignalPollId = null;
let standaloneLastSignalId = 0;
let _standaloneSignalPolling = false;
const standaloneViewerPeers = new Map(); // viewer username → RTCPeerConnection
const standaloneViewerPending = new Map(); // viewer username → buffered ICE candidates
// Viewer side
let viewShareId = null;
let viewSharePc = null;
let viewShareSignalPollId = null;
let viewShareLastSignalId = 0;
let _viewerSignalPolling = false;
let viewSharePending = []; // ICE candidates buffered pre-answer
// Shared: the most recently polled active share (other than ours) for this channel
let _currentRemoteShare = null;

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
  if (
    nativeNotifEnabled &&
    "Notification" in globalThis &&
    Notification.permission === "granted"
  ) {
    new Notification("Incoming Call — MiniMost", {
      body: `${callData.initiator} is calling you`,
      icon: "/static/web-app-manifest-192x192.png",
      tag: "minimost-call",
    });
  }
}

function closeIncomingCallUI() {
  if (incomingRingTimeout) {
    clearTimeout(incomingRingTimeout);
    incomingRingTimeout = null;
  }
  document.getElementById("call-incoming").style.display = "none";
  if (ringAudio) {
    ringAudio.pause();
    ringAudio = null;
  }
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
  if (sb) {
    sb.classList.remove("active");
    sb.classList.add("muted");
    sb.title = "Share screen";
  }
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
  return await navigator.mediaDevices.getUserMedia({
    audio: true,
    video: false,
  });
}

// ── Local microphone level meter ────────────────────────────────────────────────
// Drives the #call-mic-level bar so a user can see their own mic is working.

let micMeterCtx = null;
let micMeterPollId = null;

// Resume a suspended AudioContext, retrying on the next user gesture if the
// autoplay policy blocks the immediate attempt (more common on Windows Chrome,
// where the context can start suspended after the getUserMedia await).
function _resumeAudioContext(ctx) {
  if (ctx?.state !== "suspended" || !ctx.resume) return;
  ctx.resume().catch(() => {
    const onGesture = () => {
      ctx.resume().catch(() => {});
      document.removeEventListener("pointerdown", onGesture);
    };
    document.addEventListener("pointerdown", onGesture, { once: true });
  });
}

function _startMicLevelMeter() {
  const micLevelEl = document.getElementById("call-mic-level");
  if (!micLevelEl || !localStream) return;
  const audioTracks = localStream.getAudioTracks();
  if (audioTracks.length === 0) {
    console.warn(
      "No local audio track captured — the microphone was not granted.",
    );
    return;
  }

  // Diagnostics: a track that is muted/ended at the source still counts as a
  // "successful" getUserMedia but produces silence.  On Windows this usually
  // means the browser lacks OS-level microphone permission, or the wrong input
  // device is the default.  Log the chosen device + its state so the cause is
  // visible in the console.
  const track = audioTracks[0];
  console.info(
    `Local mic: "${track.label || "(unnamed)"}" enabled=${track.enabled} ` +
      `muted=${track.muted} state=${track.readyState}`,
  );
  track.addEventListener?.("mute", () =>
    console.warn(
      "Local microphone track was muted by the system. No audio will be sent. " +
        "Check the OS microphone permission for your browser and the selected input device.",
    ),
  );

  try {
    micMeterCtx = new AudioContext();
    _resumeAudioContext(micMeterCtx);
    const source = micMeterCtx.createMediaStreamSource(
      new MediaStream(audioTracks),
    );
    const analyser = micMeterCtx.createAnalyser();
    analyser.fftSize = 256;
    source.connect(analyser);
    const buf = new Uint8Array(analyser.frequencyBinCount);
    micMeterPollId = setInterval(() => {
      if (!activeCallId) return;
      // If the context got suspended (autoplay policy), keep trying — until
      // it runs, getByteTimeDomainData only returns silence.
      if (micMeterCtx.state === "suspended") {
        _resumeAudioContext(micMeterCtx);
        return;
      }
      analyser.getByteTimeDomainData(buf);
      let sum = 0;
      for (const s of buf) sum += Math.abs(s - 128);
      // A muted (disabled) track emits silence, so this naturally falls to 0.
      micLevelEl.style.height = Math.min(100, (sum / buf.length) * 5) + "%";
    }, 50);
  } catch (e) {
    console.warn("Mic level meter setup failed:", e);
  }
}

function _stopMicLevelMeter() {
  if (micMeterPollId) {
    clearInterval(micMeterPollId);
    micMeterPollId = null;
  }
  const micLevelEl = document.getElementById("call-mic-level");
  if (micLevelEl) micLevelEl.style.height = "0%";
  if (micMeterCtx) {
    micMeterCtx.close().catch(() => {});
    micMeterCtx = null;
  }
}

// ── In-call signaling ──────────────────────────────────────────────────────────

function _sendCallSignal(toUser, type, payload) {
  if (!activeCallId) return Promise.resolve();
  return fetch(`/calls/${activeCallId}/signal`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ to: toUser, type, payload }),
  }).catch(() => {});
}

function _startCallSignaling() {
  lastCallSignalId = 0;
  _callSignalPolling = false;
  callSignalPollId = setInterval(_pollCallSignals, 600);
}

function _stopCallSignaling() {
  clearInterval(callSignalPollId);
  callSignalPollId = null;
  _callSignalPolling = false;
}

async function _pollCallSignals() {
  if (!activeCallId || _callSignalPolling) return;
  _callSignalPolling = true;
  try {
    const resp = await fetch(
      `/calls/${activeCallId}/signals?after=${lastCallSignalId}`,
    );
    if (!resp.ok) return;
    const signals = await resp.json();
    for (const sig of signals) {
      lastCallSignalId = Math.max(lastCallSignalId, sig.id);
      await _handleCallSignal(sig);
    }
  } catch {
    /* ignore transient errors */
  } finally {
    _callSignalPolling = false;
  }
}

async function _handleCallSignal(sig) {
  const u = sig.from;
  if (!remoteParticipants.has(u)) _addRemoteParticipant(u);
  const pState = remoteParticipants.get(u);
  if (!pState?.pc) return;
  const pc = pState.pc;
  try {
    if (sig.type === "ice_candidate") {
      if (pc.remoteDescription) {
        await pc.addIceCandidate(sig.payload).catch(() => {});
      } else {
        pState.pendingCandidates.push(sig.payload);
      }
      return;
    }
    // offer / answer — an SDP description (perfect negotiation)
    const desc = sig.payload;
    const offerCollision =
      desc.type === "offer" &&
      (pState.makingOffer || pc.signalingState !== "stable");
    pState.ignoreOffer = !pState.polite && offerCollision;
    if (pState.ignoreOffer) return;

    await pc.setRemoteDescription(desc);
    for (const c of pState.pendingCandidates)
      await pc.addIceCandidate(c).catch(() => {});
    pState.pendingCandidates = [];

    if (desc.type === "offer") {
      await pc.setLocalDescription();
      await _sendCallSignal(u, pc.localDescription.type, pc.localDescription);
    }
  } catch (e) {
    console.warn("Signal handling error:", e);
  }
}

// ── Peer-connection management ──────────────────────────────────────────────────

function _createPeerConnection(username, pState) {
  const pc = new RTCPeerConnection(RTC_CONFIG);

  if (localStream) {
    for (const track of localStream.getAudioTracks())
      pc.addTrack(track, localStream);
  }
  // A late joiner during an active screen share must also receive the screen.
  if (screenEnabled && screenStream) {
    for (const track of screenStream.getVideoTracks()) {
      pState.screenSender = pc.addTrack(track, screenStream);
    }
  }

  pc.onnegotiationneeded = async () => {
    try {
      pState.makingOffer = true;
      await pc.setLocalDescription();
      await _sendCallSignal(
        username,
        pc.localDescription.type,
        pc.localDescription,
      );
    } catch (e) {
      console.warn("Negotiation error:", e);
    } finally {
      pState.makingOffer = false;
    }
  };

  pc.onicecandidate = ({ candidate }) => {
    if (candidate)
      _sendCallSignal(username, "ice_candidate", candidate.toJSON());
  };

  pc.ontrack = (e) => _handleRemoteTrack(username, e);

  pc.onconnectionstatechange = () => {
    if (pc.connectionState === "failed") {
      try {
        pc.restartIce();
      } catch {
        /* not supported */
      }
    }
  };
  _logPeerState(pc, `call:${username}`);

  return pc;
}

function _handleRemoteTrack(username, e) {
  const pState = remoteParticipants.get(username);
  if (!pState) return;
  const stream = e.streams[0] || new MediaStream([e.track]);
  if (e.track.kind === "audio") {
    _attachRemoteAudio(pState, stream);
  } else if (e.track.kind === "video") {
    _attachRemoteScreen(username, e.track, stream);
  }
}

function _attachRemoteAudio(pState, stream) {
  if (!pState.audioEl) {
    const a = document.createElement("audio");
    a.autoplay = true;
    a.setAttribute("playsinline", "");
    a.style.display = "none";
    document.body.appendChild(a);
    pState.audioEl = a;
  }
  pState.audioEl.srcObject = stream;
  pState.audioEl.play().catch(() => {});
  _setupVad(pState, stream);
}

function _setupVad(pState, stream) {
  try {
    if (!sharedAudioCtx) sharedAudioCtx = new AudioContext();
    if (sharedAudioCtx.state === "suspended")
      sharedAudioCtx.resume().catch(() => {});
    const src = sharedAudioCtx.createMediaStreamSource(stream);
    const analyser = sharedAudioCtx.createAnalyser();
    analyser.fftSize = 256;
    src.connect(analyser); // tap only — playback is handled by the <audio> element
    pState.vadAnalyser = analyser;
  } catch (e) {
    console.warn("VAD setup failed:", e);
  }
}

function _attachRemoteScreen(username, track, stream) {
  currentScreenSender = username;
  const videoEl = document.getElementById("call-screen-video");
  videoEl.srcObject = stream;
  videoEl.play().catch(() => {});
  document.getElementById("call-panel").classList.add("screen-share-active");
  track.addEventListener("ended", () => _clearRemoteScreen(username));
  track.addEventListener("mute", () => _clearRemoteScreen(username));
}

function _clearRemoteScreen(username) {
  if (username && currentScreenSender && username !== currentScreenSender)
    return;
  const videoEl = document.getElementById("call-screen-video");
  if (videoEl.srcObject) videoEl.srcObject = null;
  document.getElementById("call-panel").classList.remove("screen-share-active");
  currentScreenSender = null;
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
  if (n <= 1) grid.style.gridTemplateColumns = "1fr";
  else grid.style.gridTemplateColumns = "1fr 1fr";
}

function _startVadPoll(pState) {
  pState.vadPollId = setInterval(() => {
    const ring = pState.tileEl?.querySelector(".call-speaking-ring");
    if (!ring) return;
    if (!pState.vadAnalyser) {
      ring.classList.remove("speaking");
      return;
    }
    const buf = new Uint8Array(pState.vadAnalyser.frequencyBinCount);
    pState.vadAnalyser.getByteFrequencyData(buf);
    let sum = 0;
    for (const v of buf) sum += v;
    ring.classList.toggle("speaking", sum / buf.length > 8);
  }, 100);
}

function _addRemoteParticipant(username) {
  if (remoteParticipants.has(username)) return;
  const tile = _createParticipantTile(username);
  const pState = {
    tileEl: tile,
    pc: null,
    // Deterministic, opposite on the two ends → exactly one polite peer.
    polite: CURRENT_USER < username,
    makingOffer: false,
    ignoreOffer: false,
    pendingCandidates: [],
    audioEl: null,
    vadAnalyser: null,
    vadPollId: null,
    screenSender: null,
  };
  remoteParticipants.set(username, pState);
  pState.pc = _createPeerConnection(username, pState);
  _startVadPoll(pState);
  _updateCallGrid();
}

function _removeRemoteParticipant(username) {
  const pState = remoteParticipants.get(username);
  if (!pState) return;
  clearInterval(pState.vadPollId);
  if (pState.pc) {
    try {
      pState.pc.close();
    } catch {
      /* ignore */
    }
  }
  if (pState.audioEl) {
    pState.audioEl.srcObject = null;
    pState.audioEl.remove();
  }
  if (pState.tileEl) pState.tileEl.remove();
  remoteParticipants.delete(username);
  // Only play the departure sound when the call is still ongoing — activeCallId
  // is null during full teardown (_cleanupCall), so this won't fire then.
  if (activeCallId) {
    const lc = new Audio("/static/left_call.mp3");
    lc.volume = 0.4;
    lc.play().catch(() => {});
  }
  if (username === currentScreenSender) _clearRemoteScreen(username);
  _updateCallGrid();
}

function _removeAllParticipants() {
  for (const username of remoteParticipants.keys()) {
    _removeRemoteParticipant(username);
  }
  if (sharedAudioCtx) {
    sharedAudioCtx.close().catch(() => {});
    sharedAudioCtx = null;
  }
}

// ── In-call screen share ────────────────────────────────────────────────────────

async function toggleScreenShare() {
  if (!localStream || !activeCallId) return;
  const btn = document.getElementById("call-screen-btn");
  if (screenEnabled) {
    _stopInCallScreenShare();
    btn.classList.remove("active");
    btn.classList.add("muted");
    btn.title = "Share screen";
    return;
  }
  // getDisplayMedia must run directly in the user-gesture handler — calling it
  // from a nested async helper drops the activation token in some browsers.
  if (!navigator.mediaDevices?.getDisplayMedia) {
    alert("Your browser does not support screen sharing.");
    return;
  }
  let displayStream;
  try {
    displayStream = await navigator.mediaDevices.getDisplayMedia({
      video: true,
      audio: false,
    });
  } catch (e) {
    console.warn("Screen share failed:", e);
    return;
  }
  if (!displayStream || displayStream.getVideoTracks().length === 0) {
    displayStream?.getTracks().forEach((t) => t.stop());
    return;
  }

  screenStream = displayStream;
  screenEnabled = true;
  const track = displayStream.getVideoTracks()[0];

  for (const pState of remoteParticipants.values()) {
    if (pState.pc)
      pState.screenSender = pState.pc.addTrack(track, screenStream);
  }
  // Record who is sharing (drives the single-sharer policy + viewer label).
  fetch(`/calls/${activeCallId}/screenshare`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ on: true }),
  }).catch(() => {});

  // Handle the user clicking the browser's native "Stop sharing" button.
  track.addEventListener("ended", () => {
    if (screenEnabled) toggleScreenShare();
  });

  btn.classList.add("active");
  btn.classList.remove("muted");
  btn.title = "Stop sharing screen";
}

function _stopInCallScreenShare() {
  screenEnabled = false;
  for (const pState of remoteParticipants.values()) {
    if (pState.pc && pState.screenSender) {
      try {
        pState.pc.removeTrack(pState.screenSender);
      } catch {
        /* ignore */
      }
      pState.screenSender = null;
    }
  }
  if (screenStream) {
    screenStream.getTracks().forEach((t) => t.stop());
    screenStream = null;
  }
  if (activeCallId) {
    fetch(`/calls/${activeCallId}/screenshare`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ on: false }),
    }).catch(() => {});
  }
}

// ── Standalone screen share (sharer → many viewers) ─────────────────────────────

function _sendShareSignal(shareId, toUser, type, payload) {
  return fetch(`/screenshare/${shareId}/signal`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ to: toUser, type, payload }),
  }).catch(() => {});
}

async function toggleStandaloneScreenShare() {
  if (standaloneShareId) {
    await _stopStandaloneShare();
    return;
  }
  if (!navigator.mediaDevices?.getDisplayMedia) {
    alert("Your browser does not support screen sharing.");
    return;
  }
  let displayStream;
  try {
    displayStream = await navigator.mediaDevices.getDisplayMedia({
      video: true,
      audio: false,
    });
  } catch (e) {
    console.warn("Screen share cancelled:", e);
    return;
  }
  if (!displayStream) return;
  await _startStandaloneShare(displayStream);
}

async function _startStandaloneShare(displayStream) {
  if (displayStream.getVideoTracks().length === 0) {
    displayStream.getTracks().forEach((t) => t.stop());
    return;
  }
  const resp = await fetch("/screenshare/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ channel }),
  }).catch(() => null);
  if (!resp?.ok) {
    displayStream.getTracks().forEach((t) => t.stop());
    return;
  }
  const { share_id } = await resp.json();
  standaloneShareId = share_id;
  standaloneShareStream = displayStream;
  standaloneLastSignalId = 0;
  _standaloneSignalPolling = false;
  standaloneViewerPeers.clear();
  standaloneSignalPollId = setInterval(_pollStandaloneSignals, 600);

  displayStream.getVideoTracks()[0].addEventListener("ended", () => {
    if (standaloneShareId) _stopStandaloneShare();
  });

  const sbtn = document.getElementById("topbar-share-btn");
  if (sbtn) {
    sbtn.classList.add("active");
    sbtn.title = "Stop sharing";
  }
}

async function _pollStandaloneSignals() {
  if (!standaloneShareId || _standaloneSignalPolling) return;
  _standaloneSignalPolling = true;
  try {
    const resp = await fetch(
      `/screenshare/${standaloneShareId}/signals?after=${standaloneLastSignalId}`,
    );
    if (!resp.ok) return;
    const signals = await resp.json();
    for (const sig of signals) {
      standaloneLastSignalId = Math.max(standaloneLastSignalId, sig.id);
      await _handleSharerSignal(sig);
    }
  } catch {
    /* ignore transient errors */
  } finally {
    _standaloneSignalPolling = false;
  }
}

function _addShareCandidate(viewer, pc, candidate) {
  if (pc?.remoteDescription) {
    pc.addIceCandidate(candidate).catch(() => {});
    return;
  }
  // A candidate can outrace the offer it belongs to (trickle ICE + unordered
  // POSTs).  Buffer it until the offer creates the peer and sets the remote
  // description, else the sharer gets no remote candidates and ICE fails.
  if (!standaloneViewerPending.has(viewer))
    standaloneViewerPending.set(viewer, []);
  standaloneViewerPending.get(viewer).push(candidate);
}

function _createViewerPeer(viewer) {
  const pc = new RTCPeerConnection(RTC_CONFIG);
  standaloneViewerPeers.set(viewer, pc);
  pc.onicecandidate = ({ candidate }) => {
    if (candidate)
      _sendShareSignal(
        standaloneShareId,
        viewer,
        "ice_candidate",
        candidate.toJSON(),
      );
  };
  _logPeerState(pc, `share→${viewer}`);
  return pc;
}

async function _flushPendingShareCandidates(viewer, pc) {
  const pending = standaloneViewerPending.get(viewer);
  if (!pending) return;
  for (const c of pending) await pc.addIceCandidate(c).catch(() => {});
  standaloneViewerPending.delete(viewer);
}

async function _attachScreenTrack(pc) {
  // Answer-with-media: attach our screen track to the transceiver the viewer's
  // recvonly offer created (via replaceTrack) so the answer advertises a
  // sendonly video m-line.  Adding before setRemoteDescription can leave the
  // track unassociated → viewer sees black.
  const track = standaloneShareStream.getVideoTracks()[0];
  if (!track) return;
  const tcv = pc
    .getTransceivers()
    .find((t) => t.receiver?.track?.kind === "video");
  if (tcv) {
    await tcv.sender.replaceTrack(track);
    try {
      tcv.direction = "sendonly";
    } catch {
      /* read-only in old browsers */
    }
  } else {
    pc.addTrack(track, standaloneShareStream);
  }
}

async function _answerViewerOffer(viewer, sig) {
  if (!standaloneShareStream) return;
  const pc = standaloneViewerPeers.get(viewer) || _createViewerPeer(viewer);
  try {
    await pc.setRemoteDescription(sig.payload);
    await _flushPendingShareCandidates(viewer, pc);
    await _attachScreenTrack(pc);
    await pc.setLocalDescription();
    await _sendShareSignal(
      standaloneShareId,
      viewer,
      pc.localDescription.type,
      pc.localDescription,
    );
  } catch (e) {
    console.warn("Sharer answer failed:", e);
  }
}

async function _handleSharerSignal(sig) {
  if (sig.type === "ice_candidate") {
    _addShareCandidate(
      sig.from,
      standaloneViewerPeers.get(sig.from),
      sig.payload,
    );
  } else if (sig.type === "offer") {
    await _answerViewerOffer(sig.from, sig);
  }
}

async function _stopStandaloneShare() {
  const id = standaloneShareId;
  standaloneShareId = null;
  if (standaloneSignalPollId) {
    clearInterval(standaloneSignalPollId);
    standaloneSignalPollId = null;
  }
  for (const pc of standaloneViewerPeers.values()) {
    try {
      pc.close();
    } catch {
      /* ignore */
    }
  }
  standaloneViewerPeers.clear();
  standaloneViewerPending.clear();
  if (standaloneShareStream) {
    standaloneShareStream.getTracks().forEach((t) => t.stop());
    standaloneShareStream = null;
  }
  if (id)
    await fetch(`/screenshare/${id}/stop`, { method: "POST" }).catch(() => {});
  const sbtn = document.getElementById("topbar-share-btn");
  if (sbtn) {
    sbtn.classList.remove("active");
    sbtn.title = "Share screen";
  }
}

// Polled every 1 s to detect when someone else starts/stops sharing.
async function refreshScreenShares() {
  if (
    !channel ||
    (!channel.startsWith("dm:") && !channel.startsWith("private:"))
  )
    return;
  let shares;
  try {
    const resp = await fetch(
      `/screenshare/active?channel=${encodeURIComponent(channel)}`,
    );
    if (!resp.ok) return;
    shares = await resp.json();
  } catch {
    return;
  }

  const others = shares.filter((s) => s.sharer !== CURRENT_USER);

  if (others.length === 0) {
    _currentRemoteShare = null;
    document.getElementById("screenshare-banner").style.display = "none";
    if (viewShareId) closeShareViewer();
    return;
  }

  const share = others[0];
  _currentRemoteShare = share;

  const banner = document.getElementById("screenshare-banner");
  document.getElementById("screenshare-banner-text").textContent =
    `${share.sharer} is sharing their screen`;

  if (viewShareId === share.share_id) {
    banner.style.display = "none";
    return;
  }
  if (viewShareId && viewShareId !== share.share_id) {
    closeShareViewer();
  }

  document.getElementById("screenshare-banner-view-btn").style.display =
    "inline-flex";
  banner.style.display = "flex";

  if (
    document.hidden &&
    share.share_id !== _notifiedShareId &&
    nativeNotifEnabled &&
    "Notification" in globalThis &&
    Notification.permission === "granted"
  ) {
    _notifiedShareId = share.share_id;
    new Notification("Screen Share — MiniMost", {
      body: `${share.sharer} is sharing their screen`,
      icon: "/static/web-app-manifest-192x192.png",
      tag: "minimost-screenshare",
    });
  }
}

// ── Standalone screen share (viewer side) ───────────────────────────────────────

function openShareViewer() {
  const share = _currentRemoteShare;
  if (!share) return;
  viewShareId = share.share_id;
  viewShareLastSignalId = 0;
  viewSharePending = [];
  _viewerSignalPolling = false;

  document.getElementById("screenshare-viewer-label").textContent =
    `${share.sharer} is sharing their screen`;
  document.getElementById("screenshare-viewer").style.display = "flex";
  document.getElementById("screenshare-banner").style.display = "none";

  _startShareViewerConnection(share);
}

async function _startShareViewerConnection(share) {
  const pc = new RTCPeerConnection(RTC_CONFIG);
  viewSharePc = pc;
  pc.addTransceiver("video", { direction: "recvonly" });

  pc.ontrack = (e) => {
    const videoEl = document.getElementById("screenshare-viewer-video");
    videoEl.srcObject = e.streams[0] || new MediaStream([e.track]);
    videoEl.play().catch(() => {});
  };
  pc.onicecandidate = ({ candidate }) => {
    if (candidate)
      _sendShareSignal(
        viewShareId,
        share.sharer,
        "ice_candidate",
        candidate.toJSON(),
      );
  };
  _logPeerState(pc, `view:${share.sharer}`);

  viewShareSignalPollId = setInterval(_pollViewerSignals, 600);

  try {
    await pc.setLocalDescription(await pc.createOffer());
    await _sendShareSignal(
      viewShareId,
      share.sharer,
      pc.localDescription.type,
      pc.localDescription,
    );
  } catch (e) {
    console.warn("Viewer offer failed:", e);
  }
}

async function _pollViewerSignals() {
  if (!viewShareId || !viewSharePc || _viewerSignalPolling) return;
  _viewerSignalPolling = true;
  try {
    const resp = await fetch(
      `/screenshare/${viewShareId}/signals?after=${viewShareLastSignalId}`,
    );
    if (!resp.ok) return;
    const signals = await resp.json();
    for (const sig of signals) {
      viewShareLastSignalId = Math.max(viewShareLastSignalId, sig.id);
      if (sig.type === "answer") {
        await viewSharePc.setRemoteDescription(sig.payload);
        for (const c of viewSharePending)
          await viewSharePc.addIceCandidate(c).catch(() => {});
        viewSharePending = [];
      } else if (sig.type === "ice_candidate") {
        if (viewSharePc.remoteDescription) {
          await viewSharePc.addIceCandidate(sig.payload).catch(() => {});
        } else {
          viewSharePending.push(sig.payload);
        }
      }
    }
  } catch {
    /* ignore transient errors */
  } finally {
    _viewerSignalPolling = false;
  }
}

function closeShareViewer() {
  if (viewShareSignalPollId) {
    clearInterval(viewShareSignalPollId);
    viewShareSignalPollId = null;
  }
  if (viewSharePc) {
    try {
      viewSharePc.close();
    } catch {
      /* ignore */
    }
    viewSharePc = null;
  }
  viewShareId = null;
  viewSharePending = [];
  const el = document.getElementById("screenshare-viewer-video");
  if (el.srcObject) el.srcObject = null;
  el.removeAttribute("src");
  document.getElementById("screenshare-viewer").style.display = "none";
  if (_currentRemoteShare) {
    document.getElementById("screenshare-banner").style.display = "flex";
  }
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
  alert(
    "Calling requires a secure connection (HTTPS). MiniMost generates a self-signed certificate automatically on first run — check that you are connecting via https://.",
  );
  return false;
}

async function startCall() {
  if (activeCallId) return;
  if (!_requireSecureContext()) return;

  // Acquire the microphone BEFORE creating the call on the server.  If we
  // created the call first and then getUserMedia timed out or was denied, the
  // catch block would call /end while we are the only accepted participant,
  // ending the call immediately and giving the callee only seconds of ring time.
  try {
    localStream = await _getLocalMedia();
  } catch (err) {
    console.warn("Microphone access denied:", err);
    alert(
      "Could not access your microphone. Please check your browser permissions.",
    );
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
    if (localStream) {
      localStream.getTracks().forEach((t) => t.stop());
      localStream = null;
    }
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
    _startMicLevelMeter();
    _startCallSignaling();
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
  const hu2 = new Audio("/static/hang_up.mp3");
  hu2.volume = 0.4;
  hu2.play().catch(() => {});
  setTimeout(_cleanupCall, 2000);
}

async function acceptCall() {
  if (!incomingCallData) return;
  if (!_requireSecureContext()) {
    closeIncomingCallUI();
    return;
  }

  const { call_id } = incomingCallData;

  const resp = await fetch(`/calls/${call_id}/accept`, { method: "POST" });
  closeIncomingCallUI();
  if (!resp.ok) return;
  activeCallId = call_id;

  try {
    localStream = await _getLocalMedia();
    openActiveCallUI();
    _startCallTimer();
    _startMicLevelMeter();
    _startCallSignaling();
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
  const hu1 = new Audio("/static/hang_up.mp3");
  hu1.volume = 0.4;
  hu1.play().catch(() => {});
  _cleanupCall();
}

function _cleanupCall() {
  if (callingAudio) {
    callingAudio.pause();
    callingAudio = null;
  }
  if (ringTimeoutId) {
    clearTimeout(ringTimeoutId);
    ringTimeoutId = null;
  }
  _stopCallTimer();
  _stopMicLevelMeter();
  clearInterval(callStatePollId);
  callStatePollId = null;
  _stopCallSignaling();
  if (screenEnabled) _stopInCallScreenShare();
  _removeAllParticipants();
  currentScreenSender = null;
  _clearRemoteScreen(null);
  closeActiveCallUI();
  if (localStream) {
    localStream.getTracks().forEach((t) => t.stop());
    localStream = null;
  }
}

function toggleAudioMute() {
  if (!localStream) return;
  audioMuted = !audioMuted;
  localStream.getAudioTracks().forEach((t) => {
    t.enabled = !audioMuted;
  });
  const btn = document.getElementById("call-mute-audio-btn");
  btn.classList.toggle("muted", audioMuted);
  btn.title = audioMuted ? "Unmute" : "Mute";
}

// ── Call-state polling (3 s) — detects accepts, hang-ups, screen share ────────

function _startCallStatePolling() {
  callStatePollId = setInterval(_pollCallState, 3000);
}

function _diffParticipants(accepted) {
  for (const u of accepted) {
    if (!remoteParticipants.has(u)) _addRemoteParticipant(u);
  }
  for (const u of remoteParticipants.keys()) {
    if (!accepted.has(u)) _removeRemoteParticipant(u);
  }
}

function _handleScreenshareState(newSender) {
  // Enforce single sharer: if someone else claimed the screen, drop ours.
  if (screenEnabled && newSender && newSender !== CURRENT_USER) {
    _stopInCallScreenShare();
    const sb = document.getElementById("call-screen-btn");
    if (sb) {
      sb.classList.remove("active");
      sb.classList.add("muted");
      sb.title = "Share screen";
    }
  }
  // Backup for the WebRTC track 'ended'/'mute' events: if the server says no
  // one is sharing but we are still showing a screen, hide it.
  if (!newSender && currentScreenSender)
    _clearRemoteScreen(currentScreenSender);
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
      if (callingAudio) {
        callingAudio.pause();
        callingAudio = null;
      }
      const ca1 = new Audio("/static/call_accepted.mp3");
      ca1.volume = 0.4;
      ca1.play().catch(() => {});
    }

    if (data.state === "ended" || data.state === "rejected") {
      activeCallId = null;
      const hu3 = new Audio("/static/hang_up.mp3");
      hu3.volume = 0.4;
      hu3.play().catch(() => {});
      _cleanupCall();
      return;
    }

    const accepted = new Set(
      (data.participants || [])
        .filter((p) => p.username !== CURRENT_USER && p.state === "accepted")
        .map((p) => p.username),
    );
    _diffParticipants(accepted);
    _handleScreenshareState(data.screenshare_user || null);
  } catch {
    /* ignore transient errors */
  }
}

// ── Call invite panel ─────────────────────────────────────────────────────────

async function toggleCallInvitePanel() {
  const panel = document.getElementById("call-invite-panel");
  if (panel.style.display !== "none") {
    panel.style.display = "none";
    return;
  }
  if (_inviteAllUsers.length === 0) {
    try {
      const r = await fetch("/users");
      _inviteAllUsers = r.ok ? await r.json() : [];
    } catch {
      _inviteAllUsers = [];
    }
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
  const candidates = _inviteAllUsers.filter((u) => !alreadyIn.has(u));

  let matches;
  if (query) {
    matches = candidates
      .map((u) => ({ user: u, result: fuzzySearch(query, u) }))
      .filter(({ result }) => result !== null)
      .sort((a, b) => b.result.score - a.result.score)
      .map(({ user, result }) => ({ user, indices: result.indices }));
  } else {
    matches = candidates.map((u) => ({ user: u, indices: [] }));
  }

  if (matches.length === 0) {
    const empty = document.createElement("div");
    empty.style.cssText =
      "padding:12px;color:#888;font-size:13px;text-align:center";
    empty.textContent = query
      ? "No matches"
      : "Everyone is already in the call";
    list.appendChild(empty);
    return;
  }
  for (const { user, indices } of matches) {
    const item = document.createElement("div");
    item.className = "call-invite-item";
    item.appendChild(makeAvatarWrap(user, 28));
    const name = document.createElement("span");
    name.innerHTML = indices.length
      ? highlightFuzzyMatch(user, indices)
      : escapeHtml(user);
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
    .then((r) => (r.ok ? r.json() : []))
    .then((calls) => {
      if (incomingCallData) {
        const stillRinging = calls.some(
          (c) => c.call_id === incomingCallData.call_id,
        );
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
  const btn = document.getElementById("call-invite-btn");
  if (
    panel.style.display !== "none" &&
    !panel.contains(e.target) &&
    !btn.contains(e.target)
  ) {
    panel.style.display = "none";
  }
});
