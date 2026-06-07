// ── Global constants expected by the scripts ──────────────────────────────────
global.CURRENT_USER = "alice";
global.MAX_UPLOAD_MB = 25;
global.MAX_AVATAR_MB = 5;
global.channel = "general";

// ── Cross-file globals set by inline HTML script ───────────────────────────────
global.knownMessages = new Map();
global.privateChannelMap = {};
global.privateChannelMembers = {};
global.fetchController = null;
global.lastTs = 0;
global.unread = new Set();
global.forceScrollToBottom = false;

// ── Font-size constants (referenced in chat-search.js and chat-settings.js) ───
global.CHAT_FONT_MIN = 11;
global.CHAT_FONT_MAX = 22;
global.CHAT_FONT_DEFAULT = 14;

// ── Local storage mock ────────────────────────────────────────────────────────
const _lsStore = {};
global.localStorage = {
  getItem: (k) => (_lsStore[k] !== undefined ? _lsStore[k] : null),
  setItem: (k, v) => {
    _lsStore[k] = String(v);
  },
  removeItem: (k) => {
    delete _lsStore[k];
  },
  clear: () => {
    Object.keys(_lsStore).forEach((k) => delete _lsStore[k]);
  },
};

// ── fetch mock ────────────────────────────────────────────────────────────────
const _defaultFetchResponse = () =>
  Promise.resolve({
    ok: true,
    json: () => Promise.resolve({}),
    text: () => Promise.resolve(""),
  });
global.fetch = jest.fn(_defaultFetchResponse);

// _defaultFetchResponse is used by setup-after.js (setupFilesAfterEnv) to
// restore the safe fetch default after every test.

// ── Audio / Media mocks ───────────────────────────────────────────────────────
global.AudioContext = jest.fn().mockImplementation(() => ({
  sampleRate: 48000,
  currentTime: 0,
  destination: {},
  createAnalyser: jest.fn(() => ({
    fftSize: 256,
    frequencyBinCount: 128,
    connect: jest.fn(),
    getByteTimeDomainData: jest.fn(),
    getByteFrequencyData: jest.fn(),
  })),
  createBuffer: jest.fn((ch, len, rate) => ({
    getChannelData: jest.fn(() => new Float32Array(len)),
  })),
  createBufferSource: jest.fn(() => ({
    buffer: null,
    connect: jest.fn(),
    start: jest.fn(),
  })),
  createMediaStreamSource: jest.fn(() => ({
    connect: jest.fn(),
    disconnect: jest.fn(),
  })),
  audioWorklet: {
    addModule: jest.fn(() => Promise.resolve()),
  },
  close: jest.fn(() => Promise.resolve()),
}));

global.AudioWorkletNode = jest.fn().mockImplementation(() => ({
  port: { onmessage: null, postMessage: jest.fn() },
  connect: jest.fn(),
  disconnect: jest.fn(),
}));

global.MediaRecorder = jest.fn().mockImplementation(() => ({
  state: "inactive",
  mimeType: "video/webm",
  start: jest.fn(),
  stop: jest.fn(),
  requestData: jest.fn(),
  ondataavailable: null,
}));
global.MediaRecorder.isTypeSupported = jest.fn(() => false);

global.MediaSource = jest.fn().mockImplementation(() => ({
  readyState: "closed",
  addSourceBuffer: jest.fn(() => ({
    updating: false,
    buffered: { length: 0, start: jest.fn(), end: jest.fn() },
    mode: "segments",
    appendBuffer: jest.fn(),
    remove: jest.fn(),
    addEventListener: jest.fn(),
  })),
  endOfStream: jest.fn(),
  addEventListener: jest.fn(),
}));

global.URL.createObjectURL = jest.fn(() => "blob:mock-url");
global.URL.revokeObjectURL = jest.fn();

// ── WebRTC mocks ──────────────────────────────────────────────────────────────
global.MediaStream = jest.fn().mockImplementation((tracks = []) => ({
  _tracks: tracks,
  getTracks: jest.fn(() => tracks),
  getAudioTracks: jest.fn(() => tracks.filter((t) => t.kind === "audio")),
  getVideoTracks: jest.fn(() => tracks.filter((t) => t.kind === "video")),
  addTrack: jest.fn(),
  removeTrack: jest.fn(),
}));

global.RTCPeerConnection = jest.fn().mockImplementation(() => ({
  localDescription: null,
  remoteDescription: null,
  signalingState: "stable",
  connectionState: "new",
  onnegotiationneeded: null,
  onicecandidate: null,
  ontrack: null,
  onconnectionstatechange: null,
  addEventListener: jest.fn(),
  removeEventListener: jest.fn(),
  getTransceivers: jest.fn(() => []),
  addTrack: jest.fn(() => ({ track: null })),
  removeTrack: jest.fn(),
  addTransceiver: jest.fn(),
  createOffer: jest.fn(() => Promise.resolve({ type: "offer", sdp: "" })),
  createAnswer: jest.fn(() => Promise.resolve({ type: "answer", sdp: "" })),
  setLocalDescription: jest.fn(function () {
    this.localDescription = { type: "offer", sdp: "" };
    return Promise.resolve();
  }),
  setRemoteDescription: jest.fn(function (d) {
    this.remoteDescription = d;
    return Promise.resolve();
  }),
  addIceCandidate: jest.fn(() => Promise.resolve()),
  restartIce: jest.fn(),
  close: jest.fn(),
}));

global.RTCSessionDescription = jest.fn().mockImplementation((d) => d);

// jsdom does not implement HTMLMediaElement playback.
HTMLMediaElement.prototype.play = jest.fn(() => Promise.resolve());
HTMLMediaElement.prototype.pause = jest.fn();

// ── Notification mock ─────────────────────────────────────────────────────────
global.Notification = jest.fn();
global.Notification.permission = "default";
global.Notification.requestPermission = jest.fn(() =>
  Promise.resolve("granted"),
);

// ── navigator mocks ───────────────────────────────────────────────────────────
global.navigator.sendBeacon = jest.fn();
global.navigator.mediaDevices = {
  getUserMedia: jest.fn(() =>
    Promise.resolve({
      getAudioTracks: jest.fn(() => [{ enabled: true, stop: jest.fn() }]),
      getVideoTracks: jest.fn(() => [
        { stop: jest.fn(), addEventListener: jest.fn() },
      ]),
      getTracks: jest.fn(() => [{ stop: jest.fn() }]),
    }),
  ),
  getDisplayMedia: jest.fn(() =>
    Promise.resolve({
      getVideoTracks: jest.fn(() => [
        { stop: jest.fn(), addEventListener: jest.fn() },
      ]),
      getAudioTracks: jest.fn(() => []),
      getTracks: jest.fn(() => [{ stop: jest.fn() }]),
    }),
  ),
};

// ── atob mock (jsdom supports it; be explicit for clarity) ────────────────────
if (!global.atob) {
  global.atob = (b64) => Buffer.from(b64, "base64").toString("binary");
}

// ── AbortController mock (provided by jsdom, but make explicit) ───────────────
if (!global.AbortController) {
  global.AbortController = class {
    constructor() {
      this.signal = {};
    }
    abort() {}
  };
}

// ── requestAnimationFrame mock ────────────────────────────────────────────────
global.requestAnimationFrame = jest.fn((cb) => setTimeout(cb, 0));

// ── scrollIntoView mock (not implemented in jsdom) ───────────────────────────
Element.prototype.scrollIntoView = jest.fn();

// ── canvas mock (needed for initFavicon) ──────────────────────────────────────
HTMLCanvasElement.prototype.getContext = jest.fn(() => ({
  beginPath: jest.fn(),
  arc: jest.fn(),
  fill: jest.fn(),
  drawImage: jest.fn(),
  fillText: jest.fn(),
  measureText: jest.fn(() => ({ width: 10 })),
  set fillStyle(_) {},
  get fillStyle() {
    return "#000";
  },
  set font(_) {},
  get font() {
    return "";
  },
  set textAlign(_) {},
  set textBaseline(_) {},
}));
HTMLCanvasElement.prototype.toDataURL = jest.fn(
  () => "data:image/png;base64,fake",
);
HTMLCanvasElement.prototype.toBlob = jest.fn((cb) => cb(new Blob()));

// ── IntersectionObserver mock ─────────────────────────────────────────────────
global.IntersectionObserver = jest.fn().mockImplementation(() => ({
  observe: jest.fn(),
  unobserve: jest.fn(),
  disconnect: jest.fn(),
}));

// ── clipboard mock ────────────────────────────────────────────────────────────
global.navigator.clipboard = {
  writeText: jest.fn(() => Promise.resolve()),
};

// ── Audio mock ────────────────────────────────────────────────────────────────
global.Audio = jest.fn().mockImplementation(() => ({
  play: jest.fn(() => Promise.resolve()),
  pause: jest.fn(),
  loop: false,
  volume: 1,
  src: "",
}));

// ── Build all DOM elements the scripts reference at top-level ─────────────────
const IDS = [
  // DM
  "dm-modal",
  "dm-users",
  "dm-suggestions",
  "dm-start",
  "dm-cancel",
  "new-dm-btn",
  // Search
  "msg-search-modal",
  "msg-search-input",
  "msg-search-results",
  "msg-search-btn",
  "msg-search-close",
  "msg-search-from",
  "msg-search-from-suggestions",
  "msg-search-channel",
  "msg-search-start",
  "msg-search-end",
  // Private channels
  "create-private-ch-modal",
  "rename-private-ch-modal",
  "private-ch-name",
  "private-ch-name-error",
  "private-ch-members-input",
  "private-ch-suggestions",
  "add-member-input",
  "add-member-suggestions",
  "pc-member-list",
  "private-ch-create-cancel",
  "private-ch-create-btn",
  "rename-ch-cancel-btn",
  "rename-ch-submit-btn",
  "rename-ch-input",
  "rename-ch-name-error",
  "add-member-submit-btn",
  // Settings
  "settings-modal",
  "settings-name-color",
  "settings-notif-sounds",
  "settings-native-notif",
  "settings-enter-key",
  "settings-save-btn",
  "settings-color-preview",
  "settings-bio",
  "settings-avatar-img",
  "settings-avatar-input",
  "settings-delete-password",
  "settings-delete-error",
  "settings-delete-warning",
  "settings-delete-title",
  "account-delete-view",
  "account-main-view",
  "settings-enter-to-send",
  "native-notif-hint",
  "settings-cancel-btn",
  "settings-color-reset",
  "settings-bio-count",
  "settings-font-size",
  "settings-font-size-label",
  "settings-avatar-btn",
  "settings-avatar-file",
  "settings-avatar-remove",
  "settings-avatar-preview",
  "settings-color-preview-name",
  "color-swatches",
  "settings-delete-confirm-btn",
  "notif-bell-slash",
  "native-bell-slash",
  // Members (users) modal + top-bar icon
  "users-modal",
  "users-list",
  "users-search",
  "users-modal-search",
  "users-modal-title",
  "users-modal-add",
  "users-modal-leave",
  "members-btn",
  "members-count",
  // Reactions
  "reaction-picker",
  "reaction-picker-grid",
  "reaction-search",
  "reaction-grid",
  // Sidebar
  "sidebar-dynamic",
  "sidebar",
  "sidebar-backdrop",
  // Calls
  "call-btn",
  "topbar-share-btn",
  "call-mic-level",
  "screenshare-viewer",
  "screenshare-banner",
  "screenshare-banner-text",
  "screenshare-banner-view-btn",
  "screenshare-viewer-label",
  "call-screen-btn",
  "call-invite-list",
  "call-invite-search",
  "call-status",
  "call-participants",
  "call-actions",
  "call-panel",
  "call-participants-grid",
  "call-invite-panel",
  "call-invite-btn",
  "call-timer",
  "call-mute-audio-btn",
  "call-incoming",
  "call-caller-name",
  // Chat
  "vim-mode-indicator",
  "chan",
  "chat",
  "topbar-channel",
  "msg",
  "input",
  "fileInput",
  "image-preview",
  "private-ch-sidebar-header",
  "private-ch-controls",
  "private-ch-name-bar",
  // Account
  "account-btn",
  "account-avatar",
  "account-modal",
  "account-modal-avatar",
  "account-save-btn",
  "account-signout-btn",
  "account-presence-options",
  // Typing indicator (used in applyChatFontSize)
  "typing-indicator",
  // Help
  "help-modal",
  // Misc referenced in chat-sidebar
  "pc-member-tooltip",
  // channels rename
  "rename-ch-input",
  "rename-ch-name-error",
];

IDS.forEach((id) => {
  if (!document.getElementById(id)) {
    const el = document.createElement("div");
    el.id = id;
    // Give form elements appropriate tag names
    if (
      id.includes("input") ||
      id.endsWith("-search") ||
      id === "dm-users" ||
      id === "private-ch-name" ||
      id === "private-ch-members-input" ||
      id === "add-member-input" ||
      id === "rename-ch-input" ||
      id === "settings-name-color" ||
      id === "settings-bio" ||
      id === "settings-delete-password" ||
      id === "settings-enter-key" ||
      id === "msg-search-input" ||
      id === "settings-font-size" ||
      id === "msg-search-from" ||
      id === "msg-search-start" ||
      id === "msg-search-end" ||
      id === "settings-avatar-file" ||
      id === "users-modal-search"
    ) {
      const input = document.createElement("input");
      input.id = id;
      input.type = id === "settings-avatar-file" ? "file" : "text";
      document.body.appendChild(input);
    } else if (
      id === "settings-enter-key" ||
      id === "settings-font-size" ||
      id === "msg-search-channel"
    ) {
      const sel = document.createElement("select");
      sel.id = id;
      document.body.appendChild(sel);
    } else if (
      id.endsWith("-btn") ||
      id.endsWith("-cancel") ||
      id.endsWith("-start") ||
      id === "new-dm-btn" ||
      id === "msg-search-close"
    ) {
      const btn = document.createElement("button");
      btn.id = id;
      document.body.appendChild(btn);
    } else if (
      id === "settings-notif-sounds" ||
      id === "settings-native-notif"
    ) {
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.id = id;
      document.body.appendChild(cb);
    } else {
      el.id = id;
      document.body.appendChild(el);
    }
  }
});

// Fix a few elements that need to be proper form controls
["settings-enter-key"].forEach((id) => {
  const existing = document.getElementById(id);
  if (existing && existing.tagName !== "SELECT") {
    existing.remove();
    const sel = document.createElement("select");
    sel.id = id;
    document.body.appendChild(sel);
  }
});

["settings-font-size"].forEach((id) => {
  const existing = document.getElementById(id);
  if (existing && existing.tagName !== "INPUT") {
    existing.remove();
    const inp = document.createElement("input");
    inp.type = "range";
    inp.id = id;
    inp.value = "14";
    document.body.appendChild(inp);
  }
});

// ── Stub functions that the loaded scripts call into other files ───────────────
global.switchChannel = jest.fn();
global.focusMessageInput = jest.fn();
global.openDmModal = jest.fn();
global.closeDm = jest.fn();
global.openCreatePrivateChannel = jest.fn();
global.refreshPrivateChannels = jest.fn();
global.updateSidebarActive = jest.fn();
global.makeAvatarWrap = jest.fn((username, size) => {
  const wrap = document.createElement("div");
  wrap.className = "avatar-wrap";
  const av = document.createElement("div");
  av.className = "avatar";
  const dot = document.createElement("div");
  dot.className = "avatar-presence";
  dot.dataset.username = username;
  wrap.appendChild(av);
  wrap.appendChild(dot);
  return wrap;
});
global.applyPresenceDot = jest.fn();
global.renderAccountAvatar = jest.fn();
global._setInitials = jest.fn();
global._showDmHoverCard = jest.fn();
global._hideDmHoverCard = jest.fn();
global.profileCache = {};
global.startFaviconFlash = jest.fn();
global.stopFaviconFlash = jest.fn();
global.closeHelp = jest.fn();
global.openHelp = jest.fn();
global.deleteMsg = jest.fn();
global.startEdit = jest.fn();
global.startReply = jest.fn();
global.applyChatFontSize = jest.fn();
global.cancelDeleteConfirm = jest.fn();
global._refreshUserAvatar = jest.fn();
global.toggleStandaloneScreenShare = jest.fn();
global.startCall = jest.fn();
global.nativeNotifEnabled = false;
global.notifMuted = false;
global.fetchMessages = jest.fn();
global.fetchTyping = jest.fn();
global.fetchReadReceipts = jest.fn();
global.pollIncomingCalls = jest.fn();
global.refreshScreenShares = jest.fn();
global.setPresence = jest.fn();

// ── Video elements (need .load() method) ─────────────────────────────────────
["call-screen-video", "screenshare-viewer-video"].forEach((id) => {
  if (!document.getElementById(id)) {
    const video = document.createElement("video");
    video.id = id;
    video.load = jest.fn();
    video.play = jest.fn(() => Promise.resolve());
    document.body.appendChild(video);
  }
});

// link elements for favicon
const linkEl = document.createElement("link");
linkEl.rel = "icon";
linkEl.href = "http://localhost/favicon.ico";
document.head.appendChild(linkEl);
