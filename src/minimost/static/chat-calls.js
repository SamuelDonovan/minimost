// ── Calling & screen sharing ─────────────────────────────────────────────────
//
// Media travels peer-to-peer over WebRTC (RTCPeerConnection) in a full mesh:
// every participant holds one connection to every other, so an N-person call
// carries N-1 connections per browser.  The Flask backend only owns the call
// lifecycle state machine (calls / call_participants) and relays signaling via
// /calls/<id>/signal[s].
//
// Screen sharing is per participant rather than per call: any number of people
// may share at once, and each share rides as an extra video track on the
// sharer's existing peer connections, so it needs no separate signalling path.
// The server's `screensharers` list is only a backstop for shares that stop
// without the WebRTC track events firing.
//
// The UI is rendered from state by _renderCall(): every change (someone joins,
// mutes, starts sharing, gets pinned) mutates the maps below and re-renders.
// Tiles are kept in `callTiles` and *moved* between the spotlight and the grid
// rather than rebuilt, so a <video> never loses its stream to a re-render.

let activeCallId = null;
let incomingCallData = null;
let localStream = null;
let callTimerInterval = null;
let callStartTime = null;
let callStatePollId = null;
let callState = "ringing";
let audioMuted = false;
let ringAudio = null;
let callingAudio = null;
let ringTimeoutId = null;
let incomingRingTimeout = null;
const RING_TIMEOUT_MS = 30000;
// How long a peer connection may stay down before we conclude the peer is gone
// rather than briefly unreachable. Generous enough to ride out a wifi roam.
const PEER_GONE_GRACE_MS = 15000;
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

// A LAN has bandwidth to spare and shared screens are full of small text, so
// bias the encoder hard towards legible detail over a high frame rate.
const SCREEN_CONSTRAINTS = {
  video: {
    frameRate: { ideal: 15, max: 30 },
    width: { max: 2560 },
    height: { max: 1440 },
  },
};
const SCREEN_MAX_BITRATE = 6_000_000;

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
//   pc, dc, polite, makingOffer, ignoreOffer, pendingCandidates, audioEl,
//   vadAnalyser, speaking, muted, remoteSharing, screenStream, screenSenders,
//   connState, goneTimer }
const remoteParticipants = new Map();
// Invitees whose phone is still ringing — shown as dimmed tiles so the caller
// can see the invite landed instead of staring at an unchanged grid.
const pendingInvitees = new Set();
let sharedAudioCtx = null; // one AudioContext for all remote-audio VAD taps
let speakingPollId = null; // one interval drives every tile's speaking ring

// Rendered tiles, keyed "user:<name>" / "screen:<name>".
const callTiles = new Map();
let pinnedTileKey = null; // user's explicit spotlight choice
let callLayout = "auto"; // "auto" (spotlight shares) | "grid" | "stage"
let callMinimized = false;
let focusScreenKey = null; // newest share, spotlighted while layout is auto
let _facesKey = ""; // avoids rebuilding the header face pile every render

// In-call signaling poll
let callSignalPollId = null;
let lastCallSignalId = 0;
let _callSignalPolling = false;

// In-call screen share (sender side)
let screenStream = null;
let screenEnabled = false;

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
// Viewer side — one entry per share being watched, so several people can share
// into a channel at once and be watched side by side.
const shareViewers = new Map(); // share_id → {sharer, pc, tileEl, videoEl, lastSignalId, polling, pending}
let shareViewerPollId = null;
let viewerFocusShareId = null; // which watched share sits on the stage
let viewShareId = null; // non-null while the viewer overlay is open
// The active shares by other people in this channel, most recent first.
let _currentRemoteShares = [];
let _currentRemoteShare = null;
let _bannerKey = ""; // avoids rebuilding the banner's avatars on every poll

// ── Inline icons ──────────────────────────────────────────────────────────────

const _SVG_NS = "http://www.w3.org/2000/svg";

// Build an <svg> from raw path data.  Tile badges are rendered from state, and
// innerHTML on a per-render path is exactly the habit that turns one careless
// interpolation into stored XSS, so the markup is constructed instead.
function _icon(size, paths) {
  const svg = document.createElementNS(_SVG_NS, "svg");
  svg.setAttribute("width", size);
  svg.setAttribute("height", size);
  svg.setAttribute("viewBox", "0 0 16 16");
  svg.setAttribute("fill", "currentColor");
  svg.setAttribute("aria-hidden", "true");
  for (const d of paths) {
    const path = document.createElementNS(_SVG_NS, "path");
    path.setAttribute("d", d);
    svg.appendChild(path);
  }
  return svg;
}

const _PATH_MIC_OFF = [
  "M13 8c0 .564-.094 1.107-.266 1.613l-.814-.814A4.02 4.02 0 0 0 12 8V7a.5.5 0 0 1 1 0v1zm-5 4c.818 0 1.578-.245 2.212-.667l.718.719a4.973 4.973 0 0 1-2.43.923V15h3a.5.5 0 0 1 0 1h-7a.5.5 0 0 1 0-1h3v-2.025A5 5 0 0 1 3 8V7a.5.5 0 0 1 1 0v1a4 4 0 0 0 4 4zm3-9v4.879L5.158 2.037A3.001 3.001 0 0 1 11 3z",
  "M9.486 10.607 5 6.12V8a3 3 0 0 0 4.486 2.607zM1.146 1.146a.5.5 0 0 1 .708 0l14 14a.5.5 0 0 1-.708.708l-14-14a.5.5 0 0 1 0-.708z",
];
const _PATH_SCREEN = [
  "M6 12c0 .667-.083 1.167-.25 1.5H5a.5.5 0 0 0 0 1h6a.5.5 0 0 0 0-1h-.75c-.167-.333-.25-.833-.25-1.5h4c.667 0 2-.4 2-2V4c0-1.6-1.333-2-2-2H2C1.333 2 0 2.4 0 4v6c0 1.6 1.333 2 2 2h4z",
];
const _PATH_PIN = [
  "M9.828.722a.5.5 0 0 1 .354.146l4.95 4.95a.5.5 0 0 1 0 .707c-.48.48-1.072.588-1.503.588-.177 0-.335-.018-.46-.039l-3.134 3.134a5.927 5.927 0 0 1 .16 1.013c.046.702-.032 1.687-.72 2.375a.5.5 0 0 1-.707 0l-2.829-2.828-3.182 3.182c-.195.195-1.219.902-1.414.707-.195-.195.512-1.22.707-1.414l3.182-3.182-2.828-2.829a.5.5 0 0 1 0-.707c.688-.688 1.673-.767 2.375-.72a5.922 5.922 0 0 1 1.013.16l3.134-3.133a2.772 2.772 0 0 1-.04-.461c0-.43.108-1.022.589-1.503a.5.5 0 0 1 .353-.146z",
];

function updateCallButton() {
  const btn = document.getElementById("call-btn");
  if (!btn) return;
  const eligible = channel.startsWith("dm:") || channel.startsWith("private:");
  btn.style.display = eligible ? "inline-flex" : "none";
  const sbtn = document.getElementById("topbar-share-btn");
  if (sbtn) sbtn.style.display = eligible ? "inline-flex" : "none";
}

// The channel's human name, matching the label the topbar and empty state use.
function _channelLabel(ch) {
  if (!ch) return "Call";
  if (ch.startsWith("dm:")) {
    const parts = ch.split(":").slice(1);
    const others = parts.filter((u) => u !== CURRENT_USER);
    return (others.length ? others : parts).join(", ");
  }
  if (ch.startsWith("private:")) {
    return (
      (typeof privateChannelMap !== "undefined" && privateChannelMap[ch]) || ch
    );
  }
  return "#" + ch;
}

// ── Incoming call UI ──────────────────────────────────────────────────────────

function openIncomingCallUI(callData) {
  incomingCallData = callData;
  document.getElementById("call-caller-name").textContent = callData.initiator;

  const slot = document.getElementById("call-incoming-avatar-slot");
  if (slot) {
    slot.replaceChildren(makeAvatarWrap(callData.initiator, 54, null, false));
  }
  const ctx = document.getElementById("call-incoming-context");
  if (ctx) {
    // A group call is a different decision from a one-to-one call, so say where
    // it is coming from rather than only who started it.
    const label = _channelLabel(callData.channel);
    ctx.textContent =
      callData.channel && callData.channel.startsWith("private:")
        ? `in ${label}`
        : "";
  }

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
  callTiles.clear();
  pinnedTileKey = null;
  focusScreenKey = null;
  callLayout = "auto";
  callMinimized = false;
  _facesKey = "";
  document.getElementById("call-participants-grid").innerHTML = "";
  const stage = document.getElementById("call-stage");
  if (stage) stage.innerHTML = "";
  const panel = document.getElementById("call-panel");
  panel.classList.remove("minimized", "has-stage");
  panel.style.display = "flex";
  _renderCall();
}

function closeActiveCallUI() {
  const panel = document.getElementById("call-panel");
  panel.style.display = "none";
  panel.classList.remove("minimized", "has-stage", "is-ringing");
  document.getElementById("call-participants-grid").innerHTML = "";
  const stage = document.getElementById("call-stage");
  if (stage) stage.innerHTML = "";
  callTiles.clear();
  pendingInvitees.clear();
  pinnedTileKey = null;
  focusScreenKey = null;
  callMinimized = false;
  document.getElementById("call-invite-panel").style.display = "none";
  document.getElementById("call-timer").textContent = "0:00";
  const ab = document.getElementById("call-mute-audio-btn");
  ab.classList.remove("muted");
  ab.title = "Mute (M)";
  audioMuted = false;
  screenEnabled = false;
  const sb = document.getElementById("call-screen-btn");
  if (sb) {
    sb.classList.remove("active");
    sb.title = "Share your screen (S)";
  }
  if (document.fullscreenElement === panel) document.exitFullscreen?.();
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

// ── Call surface rendering ────────────────────────────────────────────────────

// Everything that should be on screen right now, in display order: shared
// screens first (they are what people are looking at), then the people.
function _tileSpecs() {
  const specs = [];
  if (screenEnabled && screenStream) {
    specs.push({
      key: `screen:${CURRENT_USER}`,
      kind: "screen",
      user: CURRENT_USER,
      self: true,
    });
  }
  for (const [user, pState] of remoteParticipants) {
    if (pState.screenStream) {
      specs.push({ key: `screen:${user}`, kind: "screen", user });
    }
  }
  specs.push({
    key: `user:${CURRENT_USER}`,
    kind: "user",
    user: CURRENT_USER,
    self: true,
  });
  for (const user of remoteParticipants.keys()) {
    specs.push({ key: `user:${user}`, kind: "user", user });
  }
  for (const user of pendingInvitees) {
    if (user === CURRENT_USER || remoteParticipants.has(user)) continue;
    specs.push({ key: `user:${user}`, kind: "user", user, pending: true });
  }
  return specs;
}

// Which tile, if any, gets the big spotlight.  A pin always wins: once someone
// says "keep showing me this", a new share must not yank the view away.
function _stageKey(specs) {
  if (callMinimized) return null;
  const keys = new Set(specs.map((s) => s.key));
  if (pinnedTileKey && keys.has(pinnedTileKey)) return pinnedTileKey;
  if (callLayout === "grid") return null;

  const screens = specs.filter((s) => s.kind === "screen");
  if (screens.length) {
    if (focusScreenKey && keys.has(focusScreenKey)) return focusScreenKey;
    // Prefer someone else's screen: you are already looking at your own.
    return (screens.find((s) => !s.self) || screens[0]).key;
  }
  if (callLayout === "stage") {
    const other = specs.find((s) => s.kind === "user" && !s.self);
    return (other || specs[0])?.key || null;
  }
  return null;
}

function _createTile(spec) {
  const tile = document.createElement("div");
  tile.className = "call-tile" + (spec.kind === "screen" ? " is-screen" : "");
  tile.dataset.key = spec.key;

  if (spec.kind === "screen") {
    const video = document.createElement("video");
    video.className = "call-tile-video";
    video.autoplay = true;
    video.setAttribute("playsinline", "");
    // Your own screen is a local preview; leaving it audible would echo.
    video.muted = spec.self;
    tile.appendChild(video);
  } else {
    const avatar = document.createElement("div");
    avatar.className = "call-tile-avatar";
    avatar.appendChild(makeAvatarWrap(spec.user, 88, null, false));
    tile.appendChild(avatar);
  }

  const badges = document.createElement("div");
  badges.className = "call-tile-badges";
  tile.appendChild(badges);

  const footer = document.createElement("div");
  footer.className = "call-tile-footer";
  const name = document.createElement("span");
  name.className = "call-tile-name";
  const state = document.createElement("span");
  state.className = "call-tile-state";
  footer.append(name, state);
  tile.appendChild(footer);

  const pin = document.createElement("button");
  pin.type = "button";
  pin.className = "call-tile-pin";
  pin.title = "Pin to the spotlight";
  pin.setAttribute("aria-label", "Pin to the spotlight");
  pin.appendChild(_icon(12, _PATH_PIN));
  pin.addEventListener("click", (e) => {
    e.stopPropagation();
    togglePinTile(spec.key);
  });
  tile.appendChild(pin);

  tile.addEventListener("click", () => togglePinTile(spec.key));
  return tile;
}

function _badge(cls, paths, title) {
  const el = document.createElement("span");
  el.className = "call-badge" + (cls ? " " + cls : "");
  el.title = title;
  el.appendChild(_icon(12, paths));
  return el;
}

function _tileStateText(spec, pState) {
  if (spec.pending) return "Ringing…";
  if (spec.self || !pState) return "";
  if (pState.connState === "connecting" || pState.connState === "new")
    return "Connecting…";
  if (pState.connState === "disconnected" || pState.connState === "failed")
    return "Reconnecting…";
  return "";
}

function _updateTile(el, spec) {
  const pState = remoteParticipants.get(spec.user);
  const nameEl = el.querySelector(".call-tile-name");
  const badges = el.querySelector(".call-tile-badges");

  if (spec.kind === "screen") {
    nameEl.textContent = spec.self ? "Your screen" : `${spec.user}’s screen`;
    const video = el.querySelector("video");
    const stream = spec.self ? screenStream : pState?.screenStream;
    if (stream && video.srcObject !== stream) {
      video.srcObject = stream;
      video.play().catch(() => {});
    }
  } else {
    nameEl.textContent = spec.self ? "You" : spec.user;
    el.querySelector(".call-tile-state").textContent = _tileStateText(
      spec,
      pState,
    );
    badges.replaceChildren();
    if (spec.self ? audioMuted : pState?.muted) {
      badges.appendChild(
        _badge(
          "danger",
          _PATH_MIC_OFF,
          `${spec.self ? "You are" : spec.user + " is"} muted`,
        ),
      );
    }
    if (spec.self ? screenEnabled : pState?.remoteSharing) {
      badges.appendChild(_badge("", _PATH_SCREEN, "Sharing a screen"));
    }
  }
  el.classList.toggle("pending", !!spec.pending);
  el.classList.toggle("pinned", pinnedTileKey === spec.key);
}

function _renderCallHeader(specs) {
  const title = document.getElementById("call-header-title");
  if (!title) return;
  title.textContent = _channelLabel(channel);

  const people = 1 + remoteParticipants.size;
  const waiting = specs.filter((s) => s.pending).length;
  const count = document.getElementById("call-people-count");
  if (count) {
    count.textContent =
      `${people} ${people === 1 ? "person" : "people"}` +
      (waiting ? ` · ${waiting} ringing` : "");
  }

  const status = document.getElementById("call-status-text");
  if (status) {
    const sharing = specs.filter((s) => s.kind === "screen").length;
    if (remoteParticipants.size === 0 && callState === "ringing") {
      status.textContent = "Ringing…";
    } else if (sharing > 1) {
      status.textContent = `${sharing} screens shared`;
    } else if (sharing === 1) {
      status.textContent = "Screen shared";
    } else {
      status.textContent = "Connected";
    }
  }
  document
    .getElementById("call-panel")
    .classList.toggle(
      "is-ringing",
      remoteParticipants.size === 0 && callState === "ringing",
    );

  // The face pile is images; only rebuild it when the membership changes.
  const faces = document.getElementById("call-header-faces");
  if (!faces) return;
  const members = [CURRENT_USER, ...remoteParticipants.keys()];
  const key = members.join(",");
  if (key === _facesKey) return;
  _facesKey = key;
  faces.replaceChildren(
    ...members.slice(0, 5).map((u) => makeAvatarWrap(u, 24, null, false)),
  );
}

function _renderCall() {
  const grid = document.getElementById("call-participants-grid");
  const stage = document.getElementById("call-stage");
  const panel = document.getElementById("call-panel");
  if (!grid || !stage || !panel) return;

  const specs = _tileSpecs();
  const wanted = new Set(specs.map((s) => s.key));

  for (const [key, el] of callTiles) {
    if (wanted.has(key)) continue;
    el.remove();
    callTiles.delete(key);
  }
  if (pinnedTileKey && !wanted.has(pinnedTileKey)) pinnedTileKey = null;
  if (focusScreenKey && !wanted.has(focusScreenKey)) focusScreenKey = null;

  const stageKey = _stageKey(specs);
  panel.classList.toggle("has-stage", !!stageKey);

  const gridOrder = [];
  for (const spec of specs) {
    let el = callTiles.get(spec.key);
    if (!el) {
      el = _createTile(spec);
      callTiles.set(spec.key, el);
    }
    _updateTile(el, spec);
    if (spec.key === stageKey) {
      // appendChild *moves* the node, so the <video> keeps playing its stream.
      if (el.parentElement !== stage) stage.appendChild(el);
    } else {
      gridOrder.push(el);
    }
  }
  // Re-append only when the order actually differs — every move is a reflow,
  // and re-rendering runs on every mute/join/share event.
  const current = [...grid.children];
  const sameOrder =
    current.length === gridOrder.length &&
    current.every((el, i) => el === gridOrder[i]);
  if (!sameOrder) grid.append(...gridOrder);
  grid.classList.toggle("multi", gridOrder.length > 1);

  const layoutBtn = document.getElementById("call-layout-btn");
  if (layoutBtn) {
    layoutBtn.classList.toggle("on", callLayout !== "auto");
    layoutBtn.title =
      callLayout === "grid"
        ? "Layout: grid (V)"
        : callLayout === "stage"
          ? "Layout: spotlight (V)"
          : "Layout: automatic (V)";
  }
  _renderCallHeader(specs);
}

// ── Layout controls ───────────────────────────────────────────────────────────

function togglePinTile(key) {
  pinnedTileKey = pinnedTileKey === key ? null : key;
  _renderCall();
}

function cycleCallLayout() {
  callLayout =
    callLayout === "auto" ? "grid" : callLayout === "grid" ? "stage" : "auto";
  pinnedTileKey = null;
  _renderCall();
}

// Minimizing keeps the call running while handing the channel back — the whole
// point of a call inside a chat app is being able to talk *and* type.
function toggleCallMinimized(force) {
  callMinimized = force === undefined ? !callMinimized : !!force;
  document
    .getElementById("call-panel")
    .classList.toggle("minimized", callMinimized);
  if (callMinimized) {
    document.getElementById("call-invite-panel").style.display = "none";
    if (document.fullscreenElement) document.exitFullscreen?.();
  }
  _renderCall();
}

function _toggleFullscreen(el) {
  if (!el?.requestFullscreen) return;
  if (document.fullscreenElement === el) {
    document.exitFullscreen?.();
  } else {
    el.requestFullscreen().catch(() => {});
  }
}

function toggleCallFullscreen() {
  _toggleFullscreen(document.getElementById("call-panel"));
}

function toggleShareViewerFullscreen() {
  _toggleFullscreen(document.getElementById("screenshare-viewer"));
}

// ── Media helpers ─────────────────────────────────────────────────────────────

async function _getLocalMedia() {
  return await navigator.mediaDevices.getUserMedia({
    audio: true,
    video: false,
  });
}

// Text on a shared screen survives scaling far better than motion does, so tell
// the encoder that and give it the headroom to use.
function _tuneScreenTrack(track) {
  if (!track) return;
  try {
    track.contentHint = "detail";
  } catch {
    /* not supported */
  }
}

function _tuneScreenSender(sender) {
  try {
    const params = sender.getParameters();
    params.encodings = params.encodings?.length ? params.encodings : [{}];
    for (const enc of params.encodings) enc.maxBitrate = SCREEN_MAX_BITRATE;
    sender.setParameters(params).catch(() => {});
  } catch {
    /* older browsers (and non-simulcast senders) reject this; harmless */
  }
}

// ── Local microphone level meter ────────────────────────────────────────────────
// Drives the #call-mic-level bar so a user can see their own mic is working.

let micMeterCtx = null;
let micMeterPollId = null;
let micMeterAnalyser = null;

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
    micMeterAnalyser = analyser;
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
  micMeterAnalyser = null;
  const micLevelEl = document.getElementById("call-mic-level");
  if (micLevelEl) micLevelEl.style.height = "0%";
  if (micMeterCtx) {
    micMeterCtx.close().catch(() => {});
    micMeterCtx = null;
  }
}

// ── Speaking detection ────────────────────────────────────────────────────────
// One interval walks every analyser rather than one timer per participant, so a
// ten-person call still costs a single 100 ms tick.

function _analyserLevel(analyser) {
  if (!analyser) return 0;
  const buf = new Uint8Array(analyser.frequencyBinCount);
  analyser.getByteFrequencyData(buf);
  let sum = 0;
  for (const v of buf) sum += v;
  return sum / buf.length;
}

function _setTileSpeaking(key, speaking) {
  const tile = callTiles.get(key);
  if (tile) tile.classList.toggle("speaking", speaking);
}

function _startSpeakingPoll() {
  if (speakingPollId) return;
  speakingPollId = setInterval(() => {
    for (const [user, pState] of remoteParticipants) {
      _setTileSpeaking(`user:${user}`, _analyserLevel(pState.vadAnalyser) > 8);
    }
    _setTileSpeaking(
      `user:${CURRENT_USER}`,
      !audioMuted && _analyserLevel(micMeterAnalyser) > 8,
    );
  }, 100);
}

function _stopSpeakingPoll() {
  clearInterval(speakingPollId);
  speakingPollId = null;
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

// ── Peer metadata channel ─────────────────────────────────────────────────────
// Mute and share state have to reach the other tiles somehow.  A negotiated
// data channel rides the peer connection that already exists — no extra server
// round trip, and it disappears with the peer instead of needing cleanup.

function _openMetaChannel(pState) {
  let dc;
  try {
    dc = pState.pc.createDataChannel("meta", { negotiated: true, id: 0 });
  } catch {
    return null; // no data-channel support: tiles simply show less
  }
  dc.onopen = () => _sendSelfState(pState);
  dc.onmessage = (e) => {
    let msg;
    try {
      msg = JSON.parse(e.data);
    } catch {
      return;
    }
    if (msg.t !== "state") return;
    pState.muted = !!msg.muted;
    pState.remoteSharing = !!msg.sharing;
    _renderCall();
  };
  return dc;
}

function _sendSelfState(pState) {
  if (pState?.dc?.readyState !== "open") return;
  try {
    pState.dc.send(
      JSON.stringify({ t: "state", muted: audioMuted, sharing: screenEnabled }),
    );
  } catch {
    /* channel closed under us */
  }
}

function _broadcastSelfState() {
  for (const pState of remoteParticipants.values()) _sendSelfState(pState);
}

// ── Peer-connection management ──────────────────────────────────────────────────

function _createPeerConnection(username, pState) {
  const pc = new RTCPeerConnection(RTC_CONFIG);
  pState.pc = pc;

  if (localStream) {
    for (const track of localStream.getAudioTracks())
      pc.addTrack(track, localStream);
  }
  // A late joiner during an active screen share must also receive the screen.
  if (screenEnabled && screenStream) {
    for (const track of screenStream.getVideoTracks()) {
      const sender = pc.addTrack(track, screenStream);
      pState.screenSenders.push(sender);
      _tuneScreenSender(sender);
    }
  }
  pState.dc = _openMetaChannel(pState);

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
    // Already torn down — never arm a timer for a participant who has gone.
    if (remoteParticipants.get(username) !== pState) return;
    const state = pc.connectionState;
    pState.connState = state;
    _renderCall();

    if (state === "connected") {
      clearTimeout(pState.goneTimer);
      pState.goneTimer = null;
      _sendSelfState(pState);
      return;
    }
    // "closed" means we tore the connection down ourselves; only a peer that
    // dropped out from under us is interesting here.
    if (state !== "failed" && state !== "disconnected") return;

    if (state === "failed") {
      try {
        pc.restartIce();
      } catch {
        /* not supported */
      }
    }
    // A blip recovers; a browser that closed, crashed or left the network
    // never will, and no /calls/<id>/end is coming for it. Give the ICE
    // restart a grace period, then treat the peer as departed — otherwise
    // this side sits in a call with a corpse, holding the channel with it.
    if (!pState.goneTimer) {
      pState.goneTimer = setTimeout(() => {
        pState.goneTimer = null;
        if (["connected", "completed"].includes(pc.connectionState)) return;
        _handlePeerGone(username);
      }, PEER_GONE_GRACE_MS);
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

// A remote video track is always a screen share: MiniMost calls are audio-only,
// so nothing else puts video on the wire.
function _attachRemoteScreen(username, track, stream) {
  const pState = remoteParticipants.get(username);
  if (!pState) return;
  pState.screenStream = stream;
  pState.remoteSharing = true;
  focusScreenKey = `screen:${username}`;
  track.addEventListener("ended", () => _clearRemoteScreen(username));
  track.addEventListener("mute", () => _clearRemoteScreen(username));
  _renderCall();
}

function _clearRemoteScreen(username) {
  const pState = remoteParticipants.get(username);
  if (!pState?.screenStream) return;
  pState.screenStream = null;
  pState.remoteSharing = false;
  if (focusScreenKey === `screen:${username}`) focusScreenKey = null;
  if (pinnedTileKey === `screen:${username}`) pinnedTileKey = null;
  _renderCall();
}

// ── Participant management ─────────────────────────────────────────────────────

function _addRemoteParticipant(username) {
  if (remoteParticipants.has(username)) return;
  const pState = {
    pc: null,
    dc: null,
    // Deterministic, opposite on the two ends → exactly one polite peer.
    polite: CURRENT_USER < username,
    makingOffer: false,
    ignoreOffer: false,
    pendingCandidates: [],
    audioEl: null,
    vadAnalyser: null,
    muted: false,
    remoteSharing: false,
    screenStream: null,
    screenSenders: [],
    connState: "new",
    // Armed while this peer's connection is down; see onconnectionstatechange.
    goneTimer: null,
  };
  remoteParticipants.set(username, pState);
  pendingInvitees.delete(username);
  _createPeerConnection(username, pState);
  _startSpeakingPoll();
  _renderCall();
}

function _removeRemoteParticipant(username) {
  const pState = remoteParticipants.get(username);
  if (!pState) return;
  clearTimeout(pState.goneTimer);
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
  remoteParticipants.delete(username);
  // Only play the departure sound when the call is still ongoing — activeCallId
  // is null during full teardown (_cleanupCall), so this won't fire then.
  if (activeCallId) {
    const lc = new Audio("/static/left_call.mp3");
    lc.volume = 0.4;
    lc.play().catch(() => {});
  }
  _renderCall();
}

function _handlePeerGone(username) {
  if (!remoteParticipants.has(username)) return;
  _removeRemoteParticipant(username);
  // Last peer standing: the call is over whatever the server still believes,
  // and endCall() tells it so, which frees the channel for the next call.
  if (activeCallId && remoteParticipants.size === 0) endCall();
}

function _removeAllParticipants() {
  for (const username of remoteParticipants.keys()) {
    _removeRemoteParticipant(username);
  }
  _stopSpeakingPoll();
  if (sharedAudioCtx) {
    sharedAudioCtx.close().catch(() => {});
    sharedAudioCtx = null;
  }
}

// ── In-call screen share ────────────────────────────────────────────────────────
// Every participant may share at the same time; each share is just another
// video track on the connections that already carry their voice.

function _setScreenButton(on) {
  const btn = document.getElementById("call-screen-btn");
  if (!btn) return;
  btn.classList.toggle("active", on);
  btn.title = on ? "Stop sharing your screen (S)" : "Share your screen (S)";
}

async function toggleScreenShare() {
  if (!localStream || !activeCallId) return;
  if (screenEnabled) {
    _stopInCallScreenShare();
    return;
  }
  // getDisplayMedia must run directly in the user-gesture handler — calling it
  // from a nested async helper drops the activation token in some browsers.
  if (!navigator.mediaDevices?.getDisplayMedia) {
    showToast("Your browser does not support screen sharing.");
    return;
  }
  let displayStream;
  try {
    displayStream = await navigator.mediaDevices.getDisplayMedia({
      ...SCREEN_CONSTRAINTS,
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
  _tuneScreenTrack(track);

  for (const pState of remoteParticipants.values()) {
    if (!pState.pc) continue;
    const sender = pState.pc.addTrack(track, screenStream);
    pState.screenSenders.push(sender);
    _tuneScreenSender(sender);
  }
  // Record that we are sharing, so late joiners and the other clients' state
  // polls agree with what the tracks are doing.
  fetch(`/calls/${activeCallId}/screenshare`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ on: true }),
  }).catch(() => {});

  // Handle the user clicking the browser's native "Stop sharing" button.
  track.addEventListener("ended", () => {
    if (screenEnabled) _stopInCallScreenShare();
  });

  _setScreenButton(true);
  focusScreenKey = `screen:${CURRENT_USER}`;
  _broadcastSelfState();
  _renderCall();
}

function _stopInCallScreenShare() {
  screenEnabled = false;
  for (const pState of remoteParticipants.values()) {
    for (const sender of pState.screenSenders) {
      try {
        pState.pc?.removeTrack(sender);
      } catch {
        /* ignore */
      }
    }
    pState.screenSenders = [];
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
  _setScreenButton(false);
  if (focusScreenKey === `screen:${CURRENT_USER}`) focusScreenKey = null;
  if (pinnedTileKey === `screen:${CURRENT_USER}`) pinnedTileKey = null;
  _broadcastSelfState();
  _renderCall();
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
    showToast("Your browser does not support screen sharing.");
    return;
  }
  let displayStream;
  try {
    // Tab/window audio, where the browser offers it, makes a shared demo or
    // video actually watchable.  Browsers that don't support it just return
    // no audio track.
    displayStream = await navigator.mediaDevices.getDisplayMedia({
      ...SCREEN_CONSTRAINTS,
      audio: true,
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

  _tuneScreenTrack(displayStream.getVideoTracks()[0]);
  displayStream.getVideoTracks()[0].addEventListener("ended", () => {
    if (standaloneShareId) _stopStandaloneShare();
  });

  const sbtn = document.getElementById("topbar-share-btn");
  if (sbtn) {
    sbtn.classList.add("active");
    sbtn.title = "Stop sharing";
  }
  _renderShareBanner();
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

async function _attachShareTrack(pc, kind, track, allowAdd) {
  if (!track) return;
  // Answer-with-media: attach our track to the transceiver the viewer's
  // recvonly offer created (via replaceTrack) so the answer advertises a
  // sendonly m-line.  Adding before setRemoteDescription can leave the
  // track unassociated → viewer sees black.
  const tcv = pc
    .getTransceivers()
    .find((t) => t.receiver?.track?.kind === kind);
  if (tcv) {
    if (tcv.sender?.track === track) return; // already attached; a renegotiation
    await tcv.sender.replaceTrack(track);
    try {
      tcv.direction = "sendonly";
    } catch {
      /* read-only in old browsers */
    }
    return;
  }
  // No transceiver of this kind: only the video track is worth adding one for.
  // Adding an audio m-line the viewer never offered would need a second
  // negotiation round in the middle of answering this one.
  if (allowAdd) pc.addTrack(track, standaloneShareStream);
}

async function _attachScreenTrack(pc) {
  await _attachShareTrack(
    pc,
    "video",
    standaloneShareStream.getVideoTracks()[0],
    true,
  );
  // System/tab audio, when the browser captured any — a shared video or demo
  // is half the story without it.
  await _attachShareTrack(
    pc,
    "audio",
    standaloneShareStream.getAudioTracks?.()[0],
    false,
  );
  for (const sender of pc.getSenders?.() || []) {
    if (sender.track?.kind === "video") _tuneScreenSender(sender);
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
  _renderShareBanner();
}

// Polled to detect when someone else starts/stops sharing (the SSE stream
// normally beats it to it — see applyScreenShares).
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

  applyScreenShares(shares);
}

// React to the set of active screen shares for the open channel. Shared by the
// fetcher above and the SSE "screenshares" event (chat-events.js).
function applyScreenShares(shares) {
  if (
    !channel ||
    (!channel.startsWith("dm:") && !channel.startsWith("private:"))
  )
    return;

  _currentRemoteShares = (shares || []).filter(
    (s) => s.sharer !== CURRENT_USER,
  );
  _currentRemoteShare = _currentRemoteShares[0] || null;

  _renderShareBanner();
  _notifyNewShare();

  // The viewer is open: follow the channel, so a second person sharing shows up
  // beside the first and a sharer who stops disappears without a manual close.
  if (viewShareId) {
    _syncShareViewers();
    if (shareViewers.size === 0) closeShareViewer();
  }
}

function _renderShareBanner() {
  const banner = document.getElementById("screenshare-banner");
  if (!banner) return;
  const text = document.getElementById("screenshare-banner-text");
  const viewBtn = document.getElementById("screenshare-banner-view-btn");
  const stopBtn = document.getElementById("screenshare-banner-stop-btn");
  const faces = document.getElementById("screenshare-banner-avatars");
  const others = _currentRemoteShares;

  // While watching, the banner would just repeat the overlay's own header.
  if (others.length === 0 || viewShareId) {
    if (standaloneShareId && others.length === 0) {
      text.textContent = "You are sharing your screen";
      _bannerKey = "";
      if (faces) faces.replaceChildren();
      if (viewBtn) viewBtn.style.display = "none";
      if (stopBtn) stopBtn.style.display = "inline-flex";
      banner.style.display = "flex";
      return;
    }
    banner.style.display = "none";
    return;
  }

  const names = others.map((s) => s.sharer);
  text.textContent =
    names.length === 1
      ? `${names[0]} is sharing their screen`
      : `${names.slice(0, 2).join(", ")}${names.length > 2 ? ` and ${names.length - 2} more` : ""} are sharing their screens`;
  // The face pile is <img> elements; rebuilding it on every poll would refetch
  // them, so only touch it when the set of sharers actually changes.
  const facesKey = names.join(",");
  if (faces && facesKey !== _bannerKey) {
    _bannerKey = facesKey;
    faces.replaceChildren(
      ...names.slice(0, 3).map((u) => makeAvatarWrap(u, 20, null, false)),
    );
  }
  if (viewBtn) {
    viewBtn.style.display = "inline-flex";
    viewBtn.textContent = "";
    viewBtn.append(
      _icon(13, [
        "M16 8s-3-5.5-8-5.5S0 8 0 8s3 5.5 8 5.5S16 8 16 8zM1.173 8a13.133 13.133 0 0 1 1.66-2.043C4.12 4.668 5.88 3.5 8 3.5c2.12 0 3.879 1.168 5.168 2.457A13.133 13.133 0 0 1 14.828 8c-.058.087-.122.183-.195.288-.335.48-.83 1.12-1.465 1.755C11.879 11.332 10.119 12.5 8 12.5c-2.12 0-3.879-1.168-5.168-2.457A13.134 13.134 0 0 1 1.172 8z",
        "M8 5.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5zM4.5 8a3.5 3.5 0 1 1 7 0 3.5 3.5 0 0 1-7 0z",
      ]),
      names.length === 1 ? " Watch" : ` Watch (${names.length})`,
    );
  }
  if (stopBtn)
    stopBtn.style.display = standaloneShareId ? "inline-flex" : "none";
  banner.style.display = "flex";
}

function _notifyNewShare() {
  const share = _currentRemoteShare;
  if (
    !share ||
    !document.hidden ||
    share.share_id === _notifiedShareId ||
    !nativeNotifEnabled ||
    !("Notification" in globalThis) ||
    Notification.permission !== "granted"
  )
    return;
  _notifiedShareId = share.share_id;
  new Notification("Screen Share — MiniMost", {
    body: `${share.sharer} is sharing their screen`,
    icon: "/static/web-app-manifest-192x192.png",
    tag: "minimost-screenshare",
  });
}

// ── Standalone screen share (viewer side) ───────────────────────────────────────
// Watching is one peer connection per share, so several people sharing into a
// channel at once are all watchable — one on the stage, the rest live in the
// strip below, click to swap.

function openShareViewer() {
  if (_currentRemoteShares.length === 0) return;
  viewShareId = _currentRemoteShares[0].share_id;
  viewerFocusShareId = viewShareId;
  document.getElementById("screenshare-viewer").style.display = "flex";
  _syncShareViewers();
  _renderShareBanner();
}

function _syncShareViewers() {
  const wanted = new Map(_currentRemoteShares.map((s) => [s.share_id, s]));
  for (const id of [...shareViewers.keys()]) {
    if (!wanted.has(id)) _teardownShareViewer(id);
  }
  for (const [id, share] of wanted) {
    if (!shareViewers.has(id)) _startShareViewerConnection(share);
  }
  if (!shareViewers.has(viewerFocusShareId)) {
    viewerFocusShareId = shareViewers.keys().next().value || null;
  }
  viewShareId = viewerFocusShareId;
  if (!shareViewerPollId && shareViewers.size) {
    shareViewerPollId = setInterval(_pollViewerSignals, 600);
  }
  _renderShareViewer();
}

function _createShareTile(share) {
  const tile = document.createElement("div");
  tile.className = "ss-tile";
  tile.dataset.share = share.share_id;

  const video = document.createElement("video");
  video.autoplay = true;
  video.setAttribute("playsinline", "");
  tile.appendChild(video);

  const status = document.createElement("div");
  status.className = "ss-tile-status";
  const spinner = document.createElement("span");
  spinner.className = "c-spinner";
  status.append(spinner, `Connecting to ${share.sharer}…`);
  tile.appendChild(status);

  const name = document.createElement("span");
  name.className = "ss-tile-name";
  name.textContent = share.sharer;
  tile.appendChild(name);

  tile.addEventListener("click", () => {
    viewerFocusShareId = share.share_id;
    viewShareId = share.share_id;
    _renderShareViewer();
  });
  return tile;
}

function _renderShareViewer() {
  const stage = document.getElementById("screenshare-viewer-stage");
  const strip = document.getElementById("screenshare-viewer-strip");
  const label = document.getElementById("screenshare-viewer-label");
  if (!stage || !strip) return;

  const stripOrder = [];
  for (const [id, viewer] of shareViewers) {
    if (id === viewerFocusShareId) {
      if (viewer.tileEl.parentElement !== stage)
        stage.appendChild(viewer.tileEl);
    } else {
      stripOrder.push(viewer.tileEl);
    }
  }
  const current = [...strip.children];
  const sameOrder =
    current.length === stripOrder.length &&
    current.every((el, i) => el === stripOrder[i]);
  if (!sameOrder) strip.append(...stripOrder);

  if (label) {
    const focused = shareViewers.get(viewerFocusShareId);
    const extra = shareViewers.size - 1;
    label.textContent = focused
      ? `${focused.sharer} is sharing their screen` +
        (extra > 0
          ? ` · ${extra} other share${extra > 1 ? "s" : ""} below`
          : "")
      : "";
  }
}

function _startShareViewerConnection(share) {
  const pc = new RTCPeerConnection(RTC_CONFIG);
  const tileEl = _createShareTile(share);
  const viewer = {
    sharer: share.sharer,
    pc,
    tileEl,
    videoEl: tileEl.querySelector("video"),
    lastSignalId: 0,
    polling: false,
    pending: [],
  };
  shareViewers.set(share.share_id, viewer);

  // recvonly on both kinds: audio only arrives if the sharer's browser captured
  // system/tab audio, and an unused transceiver costs nothing.
  pc.addTransceiver("video", { direction: "recvonly" });
  try {
    pc.addTransceiver("audio", { direction: "recvonly" });
  } catch {
    /* ignore */
  }

  pc.ontrack = (e) => {
    const stream = e.streams[0] || new MediaStream([e.track]);
    if (viewer.videoEl.srcObject !== stream) {
      viewer.videoEl.srcObject = stream;
      viewer.videoEl.play().catch(() => {});
    }
    tileEl.classList.add("live");
  };
  pc.onicecandidate = ({ candidate }) => {
    if (candidate)
      _sendShareSignal(
        share.share_id,
        share.sharer,
        "ice_candidate",
        candidate.toJSON(),
      );
  };
  _logPeerState(pc, `view:${share.sharer}`);

  (async () => {
    try {
      await pc.setLocalDescription(await pc.createOffer());
      await _sendShareSignal(
        share.share_id,
        share.sharer,
        pc.localDescription.type,
        pc.localDescription,
      );
    } catch (e) {
      console.warn("Viewer offer failed:", e);
    }
  })();
  return viewer;
}

async function _pollViewerSignals() {
  for (const [id, viewer] of shareViewers) {
    if (viewer.polling) continue;
    viewer.polling = true;
    try {
      const resp = await fetch(
        `/screenshare/${id}/signals?after=${viewer.lastSignalId}`,
      );
      if (!resp.ok) continue;
      const signals = await resp.json();
      for (const sig of signals) {
        viewer.lastSignalId = Math.max(viewer.lastSignalId, sig.id);
        await _handleViewerSignal(viewer, sig);
      }
    } catch {
      /* ignore transient errors */
    } finally {
      viewer.polling = false;
    }
  }
}

async function _handleViewerSignal(viewer, sig) {
  const pc = viewer.pc;
  if (sig.type === "answer") {
    await pc.setRemoteDescription(sig.payload);
    for (const c of viewer.pending) await pc.addIceCandidate(c).catch(() => {});
    viewer.pending = [];
  } else if (sig.type === "ice_candidate") {
    if (pc.remoteDescription) {
      await pc.addIceCandidate(sig.payload).catch(() => {});
    } else {
      viewer.pending.push(sig.payload);
    }
  }
}

function _teardownShareViewer(shareId) {
  const viewer = shareViewers.get(shareId);
  if (!viewer) return;
  try {
    viewer.pc.close();
  } catch {
    /* ignore */
  }
  if (viewer.videoEl?.srcObject) viewer.videoEl.srcObject = null;
  viewer.tileEl.remove();
  shareViewers.delete(shareId);
}

function closeShareViewer() {
  if (shareViewerPollId) {
    clearInterval(shareViewerPollId);
    shareViewerPollId = null;
  }
  for (const id of [...shareViewers.keys()]) _teardownShareViewer(id);
  viewShareId = null;
  viewerFocusShareId = null;
  const overlay = document.getElementById("screenshare-viewer");
  if (document.fullscreenElement === overlay) document.exitFullscreen?.();
  overlay.style.display = "none";
  _renderShareBanner();
}

// Clean up standalone share state when switching channels
function _cleanupStandaloneShare() {
  if (standaloneShareId) _stopStandaloneShare();
  if (viewShareId) closeShareViewer();
  _currentRemoteShares = [];
  _currentRemoteShare = null;
  document.getElementById("screenshare-banner").style.display = "none";
}

// ── Call actions ──────────────────────────────────────────────────────────────

function _requireSecureContext() {
  if (globalThis.isSecureContext && navigator.mediaDevices) return true;
  showToast(
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
    showToast(
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
    showToast(err.error || "Could not start call");
    if (localStream) {
      localStream.getTracks().forEach((t) => t.stop());
      localStream = null;
    }
    return;
  }

  const data = await resp.json();
  activeCallId = data.call_id;
  callState = "ringing";

  try {
    // Everyone the channel just rang gets a dimmed tile until they answer.
    for (const user of data.participants || []) {
      if (user !== CURRENT_USER) pendingInvitees.add(user);
    }
    openActiveCallUI();
    _startCallTimer();
    if (!notifMuted) {
      callingAudio = new Audio("/static/calling.mp3");
      callingAudio.volume = 0.4;
      callingAudio.loop = true;
      callingAudio.play().catch(() => {});
    }
    _startMicLevelMeter();
    _startSpeakingPoll();
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
  const status = document.getElementById("call-status-text");
  if (status) status.textContent = "No answer";
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
  callState = "active";

  try {
    localStream = await _getLocalMedia();
    openActiveCallUI();
    _startCallTimer();
    _startMicLevelMeter();
    _startSpeakingPoll();
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
  _stopSpeakingPoll();
  clearInterval(callStatePollId);
  callStatePollId = null;
  _stopCallSignaling();
  if (screenEnabled) _stopInCallScreenShare();
  _removeAllParticipants();
  callState = "ringing";
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
  btn.title = audioMuted ? "Unmute (M)" : "Mute (M)";
  _broadcastSelfState();
  _renderCall();
}

// ── Call-state polling (3 s) — detects accepts, hang-ups, screen shares ───────

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

// Reconcile the shares the server knows about with the video tracks we are
// actually receiving.  Tracks are the fast path; this catches the share that
// stopped without an 'ended'/'mute' event ever reaching us.
function _handleScreenshareState(sharers) {
  const sharing = new Set(
    Array.isArray(sharers) ? sharers : sharers ? [sharers] : [],
  );
  for (const [user, pState] of remoteParticipants) {
    if (pState.screenStream && !sharing.has(user)) _clearRemoteScreen(user);
  }
}

async function _pollCallState() {
  if (!activeCallId) return;
  try {
    const resp = await fetch(`/calls/${activeCallId}/state`);
    if (!resp.ok) return;
    const data = await resp.json();
    callState = data.state;

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

    const participants = data.participants || [];
    const accepted = new Set(
      participants
        .filter((p) => p.username !== CURRENT_USER && p.state === "accepted")
        .map((p) => p.username),
    );
    pendingInvitees.clear();
    for (const p of participants) {
      if (p.username !== CURRENT_USER && p.state === "pending")
        pendingInvitees.add(p.username);
    }
    _diffParticipants(accepted);

    // Everyone else is gone but the call is still marked active — the other
    // side's browser died without ending it, so no /end will ever arrive.
    // Don't sit in an empty call with the timer running; hang up locally,
    // which also releases the channel for the next call.
    if (data.state === "active" && accepted.size === 0) {
      await endCall();
      return;
    }

    _handleScreenshareState(
      data.screensharers ||
        (data.screenshare_user ? [data.screenshare_user] : []),
    );
    _renderCall();
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
  panel.style.display = "flex";
  document.getElementById("call-invite-search").focus();
}

function filterCallInviteList(query) {
  _renderCallInviteList(query);
}

function _renderCallInviteList(query) {
  const list = document.getElementById("call-invite-list");
  list.innerHTML = "";
  const alreadyIn = new Set([
    CURRENT_USER,
    ...remoteParticipants.keys(),
    ...pendingInvitees,
  ]);
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
    empty.className = "call-invite-empty";
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
    if (resp.ok) {
      pendingInvitees.add(username);
      _renderCall();
    }
  } catch {
    status.textContent = "Failed";
  }
}

// ── Incoming call polling (1 s) ───────────────────────────────────────────────

function pollIncomingCalls() {
  if (activeCallId) return;
  fetch("/calls/incoming")
    .then((r) => (r.ok ? r.json() : []))
    .then(applyIncomingCalls)
    .catch(() => {});
}

// React to the set of currently-ringing calls from a /calls/incoming payload.
// Shared by the fetcher above and the SSE "incoming_calls" event.
function applyIncomingCalls(calls) {
  if (activeCallId) return;
  if (incomingCallData) {
    const stillRinging = calls.some(
      (c) => c.call_id === incomingCallData.call_id,
    );
    if (!stillRinging) closeIncomingCallUI();
    return;
  }
  if (calls.length > 0) openIncomingCallUI(calls[0]);
}

// ── Keyboard shortcuts ────────────────────────────────────────────────────────
// Only while the call panel is the foreground surface, and never while the user
// is typing — the invite search box lives inside the panel.

function _callShortcutTarget(e) {
  const panel = document.getElementById("call-panel");
  if (!panel || panel.style.display === "none") return null;
  const t = e.target;
  if (t?.matches?.("input, textarea, select, [contenteditable='true']"))
    return null;
  return panel;
}

document.addEventListener(
  "keydown",
  (e) => {
    if (e.ctrlKey || e.metaKey || e.altKey) return;

    // Esc closes the share viewer wherever it is open.
    if (e.key === "Escape" && viewShareId) {
      closeShareViewer();
      e.stopPropagation();
      e.preventDefault();
      return;
    }
    if (!_callShortcutTarget(e)) return;

    const key = e.key.toLowerCase();
    const actions = {
      m: toggleAudioMute,
      s: toggleScreenShare,
      a: toggleCallInvitePanel,
      v: cycleCallLayout,
      f: toggleCallFullscreen,
      escape: () => toggleCallMinimized(!callMinimized),
    };
    const action = actions[key];
    if (!action) return;
    // Minimized, the panel is a dock over a usable channel — the keys belong
    // to the chat again, apart from Esc to bring the call back.
    if (callMinimized && key !== "escape") return;
    e.stopPropagation();
    e.preventDefault();
    action();
  },
  true,
);

// Leaving the page mid-call would otherwise leave the call row live until the
// server's own staleness sweep catches it, and a channel holds only one call at
// a time — so the other party could not call straight back.  `pagehide` is the
// event that still fires on mobile (where tabs are frozen rather than unloaded),
// and sendBeacon survives the teardown that would abort a normal fetch.
globalThis.addEventListener("pagehide", () => {
  if (activeCallId) navigator.sendBeacon(`/calls/${activeCallId}/end`);
  if (standaloneShareId)
    navigator.sendBeacon(`/screenshare/${standaloneShareId}/stop`);
});

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
