/**
 * Rendering, signalling and screen-share tests for chat-calls.js.
 *
 * chat-calls.test.js loads the script against the flat element list setup.js
 * builds, which has no #call-stage and none of the header nodes — so
 * _renderCall() returns at its first guard and the whole call surface (tiles,
 * stage, header, share viewer) never runs.  This file rebuilds the nested
 * structure chat.html actually ships before loading the script, so that surface
 * is exercised, and drives the peer-connection, signalling and screen-share
 * paths through the mocks in setup.js.
 */

const { loadScript } = require("./loadScript");

// ── DOM ───────────────────────────────────────────────────────────────────────

function el(tag, id, parent) {
  const node = document.createElement(tag);
  if (id) node.id = id;
  (parent || document.body).appendChild(node);
  return node;
}

// Rebuild the call surface with the nesting chat.html uses: the invite panel and
// the controls live inside #call-panel (the click-outside handler depends on
// it), and the stage sits beside the grid inside #call-body.
function buildCallDom() {
  const ids = [
    "screenshare-banner",
    "screenshare-banner-avatars",
    "screenshare-banner-text",
    "screenshare-banner-view-btn",
    "screenshare-banner-stop-btn",
    "screenshare-viewer",
    "screenshare-viewer-label",
    "screenshare-viewer-stage",
    "screenshare-viewer-strip",
    "call-incoming",
    "call-incoming-avatar-slot",
    "call-caller-name",
    "call-incoming-context",
    "call-panel",
    "call-header-title",
    "call-status-text",
    "call-timer",
    "call-people-count",
    "call-header-faces",
    "call-layout-btn",
    "call-stage",
    "call-participants-grid",
    "call-mute-audio-btn",
    "call-mic-level",
    "call-screen-btn",
    "call-invite-btn",
    "call-invite-panel",
    "call-invite-search",
    "call-invite-list",
    "call-btn",
    "topbar-share-btn",
  ];
  for (const id of ids) document.getElementById(id)?.remove();

  const banner = el("div", "screenshare-banner");
  banner.style.display = "none";
  el("div", "screenshare-banner-avatars", banner);
  el("span", "screenshare-banner-text", banner);
  el("button", "screenshare-banner-view-btn", banner);
  el("button", "screenshare-banner-stop-btn", banner);

  const viewer = el("div", "screenshare-viewer");
  viewer.style.display = "none";
  el("span", "screenshare-viewer-label", viewer);
  el("div", "screenshare-viewer-stage", viewer);
  el("div", "screenshare-viewer-strip", viewer);

  const incoming = el("div", "call-incoming");
  incoming.style.display = "none";
  el("div", "call-incoming-avatar-slot", incoming);
  el("span", "call-caller-name", incoming);
  el("span", "call-incoming-context", incoming);

  const panel = el("div", "call-panel");
  panel.style.display = "none";
  const header = el("div", "call-header", panel);
  el("div", "call-header-title", header);
  el("span", "call-status-text", header);
  el("span", "call-timer", header);
  el("span", "call-people-count", header);
  el("div", "call-header-faces", header);
  el("button", "call-layout-btn", header);
  const body = el("div", "call-body", panel);
  el("div", "call-stage", body);
  el("div", "call-participants-grid", body);
  const controls = el("div", "call-controls", panel);
  const mute = el("button", "call-mute-audio-btn", controls);
  el("div", "call-mic-level", mute);
  el("button", "call-screen-btn", controls);
  el("button", "call-invite-btn", controls);
  const invite = el("div", "call-invite-panel", panel);
  invite.style.display = "none";
  el("input", "call-invite-search", invite);
  el("div", "call-invite-list", invite);

  el("button", "call-btn");
  el("button", "topbar-share-btn");
}

// ── Test helpers ──────────────────────────────────────────────────────────────

function track(kind, extra = {}) {
  return {
    kind,
    enabled: true,
    label: "Fake " + kind,
    readyState: "live",
    stop: jest.fn(),
    addEventListener: jest.fn(),
    ...extra,
  };
}

function stream(tracks) {
  return {
    getTracks: () => tracks,
    getAudioTracks: () => tracks.filter((t) => t.kind === "audio"),
    getVideoTracks: () => tracks.filter((t) => t.kind === "video"),
  };
}

// A participant with a peer connection, as _addRemoteParticipant would build it.
function addPeer(name) {
  _addRemoteParticipant(name);
  return remoteParticipants.get(name);
}

function tileFor(key) {
  return callTiles.get(key);
}

beforeAll(() => {
  buildCallDom();

  global.showToast = jest.fn();
  global.escapeHtml = (t) =>
    t.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
  global.fuzzySearch = jest.fn((q, t) =>
    t.toLowerCase().includes(q.toLowerCase())
      ? { score: 1, indices: [0] }
      : null,
  );
  global.highlightFuzzyMatch = jest.fn((t) => `<b>${t}</b>`);
  global.privateChannelMap = { "private:1": "Team Rocket" };
  global.isSecureContext = true;
  // The other suite leaves STUN_PORT undefined, so this one covers the branch
  // that actually points ICE at the bundled STUN server.
  global.STUN_PORT = 3478;

  loadScript("chat-calls.js");
});

beforeEach(() => {
  jest.clearAllMocks();
  global.channel = "dm:alice:bob";
  global.notifMuted = true;
  global.nativeNotifEnabled = false;
  global.activeCallId = null;

  _diffParticipants(new Set());
  pendingInvitees.clear();
  callTiles.clear();
  shareViewers.clear();
  standaloneViewerPeers.clear();
  standaloneViewerPending.clear();

  global.localStream = null;
  global.screenStream = null;
  global.screenEnabled = false;
  global.audioMuted = false;
  global.pinnedTileKey = null;
  global.focusScreenKey = null;
  global.callLayout = "auto";
  global.callMinimized = false;
  global.callState = "ringing";
  global.standaloneShareId = null;
  global.standaloneShareStream = null;
  global.viewShareId = null;
  global.viewerFocusShareId = null;
  global._currentRemoteShares = [];
  global._currentRemoteShare = null;
  global._notifiedShareId = null;
  global._facesKey = "";
  global._bannerKey = "";
  global._inviteAllUsers = [];

  document.getElementById("call-participants-grid").innerHTML = "";
  document.getElementById("call-stage").innerHTML = "";
  document.getElementById("screenshare-viewer-stage").innerHTML = "";
  document.getElementById("screenshare-viewer-strip").innerHTML = "";
  document.getElementById("call-panel").className = "";
  document.getElementById("call-panel").style.display = "none";
  // toggleCallInvitePanel() closes rather than fetches when the panel is open,
  // so a panel left open by one test would swallow the next one's fetch.
  document.getElementById("call-invite-panel").style.display = "none";
  document.getElementById("call-invite-list").innerHTML = "";
});

afterEach(() => {
  // Every start* helper arms an interval; leaving one running lets a later test
  // (or the coverage report) race against a poll.
  _stopSpeakingPoll();
  _stopMicLevelMeter();
  _stopCallSignaling();
  _stopCallTimer();
  clearInterval(callStatePollId);
  clearInterval(shareViewerPollId);
  clearInterval(standaloneSignalPollId);
  global.callStatePollId = null;
  global.shareViewerPollId = null;
  global.standaloneSignalPollId = null;
});

// ── _channelLabel ─────────────────────────────────────────────────────────────

describe("_channelLabel()", () => {
  test("names the other person in a DM", () => {
    expect(_channelLabel("dm:alice:bob")).toBe("bob");
  });

  test("lists every other member of a group DM", () => {
    expect(_channelLabel("dm:alice:bob:carol")).toBe("bob, carol");
  });

  test("falls back to all members when only self is present", () => {
    expect(_channelLabel("dm:alice")).toBe("alice");
  });

  test("uses the private channel's display name", () => {
    expect(_channelLabel("private:1")).toBe("Team Rocket");
  });

  test("falls back to the raw id for an unknown private channel", () => {
    expect(_channelLabel("private:99")).toBe("private:99");
  });

  test("prefixes a public channel with #", () => {
    expect(_channelLabel("general")).toBe("#general");
  });

  test("returns a generic label for no channel", () => {
    expect(_channelLabel("")).toBe("Call");
  });
});

// ── _tileSpecs ────────────────────────────────────────────────────────────────

describe("_tileSpecs()", () => {
  test("always includes a tile for the local user", () => {
    const specs = _tileSpecs();
    expect(specs).toEqual([
      { key: "user:alice", kind: "user", user: "alice", self: true },
    ]);
  });

  test("puts a self screen share ahead of the people", () => {
    global.screenEnabled = true;
    global.screenStream = stream([track("video")]);
    const specs = _tileSpecs();
    expect(specs[0]).toMatchObject({ key: "screen:alice", self: true });
    expect(specs.map((s) => s.kind)).toEqual(["screen", "user"]);
  });

  test("adds a screen tile for each remote sharer", () => {
    addPeer("bob").screenStream = stream([track("video")]);
    addPeer("carol");
    const keys = _tileSpecs().map((s) => s.key);
    expect(keys).toEqual([
      "screen:bob",
      "user:alice",
      "user:bob",
      "user:carol",
    ]);
  });

  test("marks invitees who have not answered as pending", () => {
    pendingInvitees.add("dave");
    const spec = _tileSpecs().find((s) => s.user === "dave");
    expect(spec).toMatchObject({ kind: "user", pending: true });
  });

  test("does not duplicate an invitee who has since joined", () => {
    addPeer("bob");
    pendingInvitees.add("bob");
    expect(_tileSpecs().filter((s) => s.key === "user:bob")).toHaveLength(1);
  });

  test("never renders the local user as a pending invitee", () => {
    pendingInvitees.add(CURRENT_USER);
    expect(_tileSpecs().filter((s) => s.user === CURRENT_USER)).toHaveLength(1);
  });
});

// ── _stageKey ─────────────────────────────────────────────────────────────────

describe("_stageKey()", () => {
  test("is empty while minimized", () => {
    global.callMinimized = true;
    expect(_stageKey(_tileSpecs())).toBeNull();
  });

  test("honours a pin over everything else", () => {
    addPeer("bob").screenStream = stream([track("video")]);
    global.pinnedTileKey = "user:bob";
    expect(_stageKey(_tileSpecs())).toBe("user:bob");
  });

  test("ignores a pin on a tile that has gone", () => {
    global.pinnedTileKey = "user:ghost";
    expect(_stageKey(_tileSpecs())).toBeNull();
  });

  test("spotlights nothing in grid layout", () => {
    addPeer("bob").screenStream = stream([track("video")]);
    global.callLayout = "grid";
    expect(_stageKey(_tileSpecs())).toBeNull();
  });

  test("prefers someone else's screen over your own", () => {
    global.screenEnabled = true;
    global.screenStream = stream([track("video")]);
    addPeer("bob").screenStream = stream([track("video")]);
    expect(_stageKey(_tileSpecs())).toBe("screen:bob");
  });

  test("falls back to your own screen when it is the only one", () => {
    global.screenEnabled = true;
    global.screenStream = stream([track("video")]);
    expect(_stageKey(_tileSpecs())).toBe("screen:alice");
  });

  test("follows the newest share while the layout is automatic", () => {
    addPeer("bob").screenStream = stream([track("video")]);
    addPeer("carol").screenStream = stream([track("video")]);
    global.focusScreenKey = "screen:carol";
    expect(_stageKey(_tileSpecs())).toBe("screen:carol");
  });

  test("spotlights the other person in stage layout", () => {
    addPeer("bob");
    global.callLayout = "stage";
    expect(_stageKey(_tileSpecs())).toBe("user:bob");
  });

  test("spotlights yourself in stage layout when alone", () => {
    global.callLayout = "stage";
    expect(_stageKey(_tileSpecs())).toBe("user:alice");
  });

  test("spotlights nobody in automatic layout with no screens", () => {
    addPeer("bob");
    expect(_stageKey(_tileSpecs())).toBeNull();
  });
});

// ── Tile rendering ────────────────────────────────────────────────────────────

describe("_renderCall() tiles", () => {
  test("creates one tile per participant", () => {
    addPeer("bob");
    _renderCall();
    const grid = document.getElementById("call-participants-grid");
    expect(grid.children).toHaveLength(2);
    expect(callTiles.has("user:alice")).toBe(true);
    expect(callTiles.has("user:bob")).toBe(true);
  });

  test("labels the local tile 'You'", () => {
    _renderCall();
    expect(
      tileFor("user:alice").querySelector(".call-tile-name").textContent,
    ).toBe("You");
  });

  test("labels a remote tile with the username", () => {
    addPeer("bob");
    _renderCall();
    expect(
      tileFor("user:bob").querySelector(".call-tile-name").textContent,
    ).toBe("bob");
  });

  test("removes the tile of a participant who left", () => {
    addPeer("bob");
    _renderCall();
    _diffParticipants(new Set());
    _renderCall();
    expect(callTiles.has("user:bob")).toBe(false);
    expect(document.querySelector('[data-key="user:bob"]')).toBeNull();
  });

  test("reuses the same element across renders so video keeps playing", () => {
    addPeer("bob");
    _renderCall();
    const first = tileFor("user:bob");
    _renderCall();
    expect(tileFor("user:bob")).toBe(first);
  });

  test("gives a screen tile a muted local video element", () => {
    global.screenEnabled = true;
    global.screenStream = stream([track("video")]);
    _renderCall();
    const video = tileFor("screen:alice").querySelector("video");
    expect(video).not.toBeNull();
    expect(video.muted).toBe(true);
    expect(tileFor("screen:alice").className).toContain("is-screen");
  });

  test("names a remote screen after its owner", () => {
    addPeer("bob").screenStream = stream([track("video")]);
    _renderCall();
    expect(
      tileFor("screen:bob").querySelector(".call-tile-name").textContent,
    ).toBe("bob’s screen");
  });

  test("marks the grid as multi only with more than one grid tile", () => {
    const grid = document.getElementById("call-participants-grid");
    _renderCall();
    expect(grid.classList.contains("multi")).toBe(false);
    addPeer("bob");
    _renderCall();
    expect(grid.classList.contains("multi")).toBe(true);
  });

  test("moves the spotlighted tile onto the stage", () => {
    addPeer("bob").screenStream = stream([track("video")]);
    _renderCall();
    const stage = document.getElementById("call-stage");
    expect(stage.children).toHaveLength(1);
    expect(stage.firstChild.dataset.key).toBe("screen:bob");
    expect(document.getElementById("call-panel").classList).toContain(
      "has-stage",
    );
  });

  test("drops a stale pin and focus when their tiles disappear", () => {
    addPeer("bob").screenStream = stream([track("video")]);
    global.pinnedTileKey = "screen:bob";
    global.focusScreenKey = "screen:bob";
    _diffParticipants(new Set());
    _renderCall();
    expect(pinnedTileKey).toBeNull();
    expect(focusScreenKey).toBeNull();
  });

  test("shows the pin state on the pinned tile", () => {
    addPeer("bob");
    global.pinnedTileKey = "user:bob";
    _renderCall();
    expect(tileFor("user:bob").classList.contains("pinned")).toBe(true);
  });

  test("titles the layout button for each layout", () => {
    const btn = document.getElementById("call-layout-btn");
    _renderCall();
    expect(btn.title).toBe("Layout: automatic (V)");
    expect(btn.classList.contains("on")).toBe(false);
    global.callLayout = "grid";
    _renderCall();
    expect(btn.title).toBe("Layout: grid (V)");
    expect(btn.classList.contains("on")).toBe(true);
    global.callLayout = "stage";
    _renderCall();
    expect(btn.title).toBe("Layout: spotlight (V)");
  });
});

// ── Tile badges and status text ───────────────────────────────────────────────

describe("tile badges", () => {
  test("badges the local tile when you are muted", () => {
    global.audioMuted = true;
    _renderCall();
    const badge = tileFor("user:alice").querySelector(".call-badge");
    expect(badge.title).toBe("You are muted");
    expect(badge.classList.contains("danger")).toBe(true);
  });

  test("badges a remote tile when that peer is muted", () => {
    addPeer("bob").muted = true;
    _renderCall();
    expect(tileFor("user:bob").querySelector(".call-badge").title).toBe(
      "bob is muted",
    );
  });

  test("badges a peer who is sharing a screen", () => {
    addPeer("bob").remoteSharing = true;
    _renderCall();
    expect(tileFor("user:bob").querySelector(".call-badge").title).toBe(
      "Sharing a screen",
    );
  });

  test("clears badges once the peer unmutes", () => {
    const p = addPeer("bob");
    p.muted = true;
    _renderCall();
    p.muted = false;
    _renderCall();
    expect(tileFor("user:bob").querySelectorAll(".call-badge")).toHaveLength(0);
  });

  test("builds badge icons as SVG rather than markup", () => {
    global.audioMuted = true;
    _renderCall();
    const svg = tileFor("user:alice").querySelector(".call-badge svg");
    expect(svg.namespaceURI).toBe("http://www.w3.org/2000/svg");
    expect(svg.querySelectorAll("path").length).toBeGreaterThan(0);
  });
});

describe("_tileStateText()", () => {
  test("shows a pending invitee as ringing", () => {
    expect(_tileStateText({ pending: true }, null)).toBe("Ringing…");
  });

  test("shows nothing for your own tile", () => {
    expect(_tileStateText({ self: true }, null)).toBe("");
  });

  test("shows connecting while the peer connection comes up", () => {
    expect(_tileStateText({}, { connState: "connecting" })).toBe("Connecting…");
    expect(_tileStateText({}, { connState: "new" })).toBe("Connecting…");
  });

  test("shows reconnecting when the peer connection drops", () => {
    expect(_tileStateText({}, { connState: "disconnected" })).toBe(
      "Reconnecting…",
    );
    expect(_tileStateText({}, { connState: "failed" })).toBe("Reconnecting…");
  });

  test("shows nothing once connected", () => {
    expect(_tileStateText({}, { connState: "connected" })).toBe("");
  });

  test("reaches the tile through a render", () => {
    pendingInvitees.add("dave");
    _renderCall();
    expect(
      tileFor("user:dave").querySelector(".call-tile-state").textContent,
    ).toBe("Ringing…");
    expect(tileFor("user:dave").classList.contains("pending")).toBe(true);
  });
});

// ── Header ────────────────────────────────────────────────────────────────────

describe("_renderCallHeader()", () => {
  test("titles the header with the channel", () => {
    _renderCall();
    expect(document.getElementById("call-header-title").textContent).toBe(
      "bob",
    );
  });

  test("counts one person when alone", () => {
    _renderCall();
    expect(document.getElementById("call-people-count").textContent).toBe(
      "1 person",
    );
  });

  test("counts people and ringing invitees", () => {
    addPeer("bob");
    pendingInvitees.add("dave");
    _renderCall();
    expect(document.getElementById("call-people-count").textContent).toBe(
      "2 people · 1 ringing",
    );
  });

  test("says ringing while nobody has answered", () => {
    global.callState = "ringing";
    _renderCall();
    expect(document.getElementById("call-status-text").textContent).toBe(
      "Ringing…",
    );
    expect(document.getElementById("call-panel").classList).toContain(
      "is-ringing",
    );
  });

  test("says connected once someone joins", () => {
    addPeer("bob");
    global.callState = "active";
    _renderCall();
    expect(document.getElementById("call-status-text").textContent).toBe(
      "Connected",
    );
    expect(document.getElementById("call-panel").classList).not.toContain(
      "is-ringing",
    );
  });

  test("counts a single shared screen", () => {
    addPeer("bob").screenStream = stream([track("video")]);
    _renderCall();
    expect(document.getElementById("call-status-text").textContent).toBe(
      "Screen shared",
    );
  });

  test("counts several shared screens", () => {
    addPeer("bob").screenStream = stream([track("video")]);
    addPeer("carol").screenStream = stream([track("video")]);
    _renderCall();
    expect(document.getElementById("call-status-text").textContent).toBe(
      "2 screens shared",
    );
  });

  test("builds the face pile from the members", () => {
    addPeer("bob");
    _renderCall();
    expect(document.getElementById("call-header-faces").children).toHaveLength(
      2,
    );
  });

  test("leaves the face pile alone when the membership is unchanged", () => {
    addPeer("bob");
    _renderCall();
    makeAvatarWrap.mockClear();
    _renderCall();
    expect(makeAvatarWrap).not.toHaveBeenCalled();
  });

  test("caps the face pile at five", () => {
    for (const u of ["b", "c", "d", "e", "f", "g"]) addPeer(u);
    _renderCall();
    expect(document.getElementById("call-header-faces").children).toHaveLength(
      5,
    );
  });
});

// ── Layout controls ───────────────────────────────────────────────────────────

describe("layout controls", () => {
  test("togglePinTile pins then unpins", () => {
    addPeer("bob");
    togglePinTile("user:bob");
    expect(pinnedTileKey).toBe("user:bob");
    togglePinTile("user:bob");
    expect(pinnedTileKey).toBeNull();
  });

  test("clicking a tile pins it", () => {
    addPeer("bob");
    _renderCall();
    tileFor("user:bob").dispatchEvent(new Event("click"));
    expect(pinnedTileKey).toBe("user:bob");
  });

  test("clicking the pin button pins without bubbling", () => {
    addPeer("bob");
    _renderCall();
    const tileClick = jest.fn();
    tileFor("user:bob").addEventListener("click", tileClick);
    tileFor("user:bob")
      .querySelector(".call-tile-pin")
      .dispatchEvent(new Event("click", { bubbles: true }));
    expect(pinnedTileKey).toBe("user:bob");
    expect(tileClick).not.toHaveBeenCalled();
  });

  test("cycleCallLayout walks auto → grid → stage → auto", () => {
    cycleCallLayout();
    expect(callLayout).toBe("grid");
    cycleCallLayout();
    expect(callLayout).toBe("stage");
    cycleCallLayout();
    expect(callLayout).toBe("auto");
  });

  test("cycling the layout drops the pin", () => {
    global.pinnedTileKey = "user:alice";
    cycleCallLayout();
    expect(pinnedTileKey).toBeNull();
  });

  test("toggleCallMinimized flips and marks the panel", () => {
    toggleCallMinimized();
    expect(callMinimized).toBe(true);
    expect(document.getElementById("call-panel").classList).toContain(
      "minimized",
    );
    toggleCallMinimized();
    expect(callMinimized).toBe(false);
  });

  test("toggleCallMinimized accepts an explicit state", () => {
    toggleCallMinimized(false);
    expect(callMinimized).toBe(false);
    toggleCallMinimized(true);
    expect(callMinimized).toBe(true);
  });

  test("minimizing closes the invite panel", () => {
    document.getElementById("call-invite-panel").style.display = "flex";
    toggleCallMinimized(true);
    expect(document.getElementById("call-invite-panel").style.display).toBe(
      "none",
    );
  });
});

describe("fullscreen helpers", () => {
  afterEach(() => {
    delete document.fullscreenElement;
    delete document.exitFullscreen;
  });

  test("does nothing when the browser has no fullscreen API", () => {
    expect(() => toggleCallFullscreen()).not.toThrow();
  });

  test("requests fullscreen for the call panel", () => {
    const panel = document.getElementById("call-panel");
    panel.requestFullscreen = jest.fn(() => Promise.resolve());
    document.fullscreenElement = null;
    toggleCallFullscreen();
    expect(panel.requestFullscreen).toHaveBeenCalled();
    delete panel.requestFullscreen;
  });

  test("exits fullscreen when the panel already owns it", () => {
    const panel = document.getElementById("call-panel");
    panel.requestFullscreen = jest.fn(() => Promise.resolve());
    document.exitFullscreen = jest.fn();
    document.fullscreenElement = panel;
    toggleCallFullscreen();
    expect(document.exitFullscreen).toHaveBeenCalled();
    expect(panel.requestFullscreen).not.toHaveBeenCalled();
    delete panel.requestFullscreen;
  });

  test("toggles fullscreen for the share viewer overlay", () => {
    const overlay = document.getElementById("screenshare-viewer");
    overlay.requestFullscreen = jest.fn(() => Promise.resolve());
    document.fullscreenElement = null;
    toggleShareViewerFullscreen();
    expect(overlay.requestFullscreen).toHaveBeenCalled();
    delete overlay.requestFullscreen;
  });

  test("minimizing leaves fullscreen", () => {
    const panel = document.getElementById("call-panel");
    document.exitFullscreen = jest.fn();
    document.fullscreenElement = panel;
    toggleCallMinimized(true);
    expect(document.exitFullscreen).toHaveBeenCalled();
  });
});

// ── Peer connections ──────────────────────────────────────────────────────────

describe("_createPeerConnection()", () => {
  test("adds the local audio track to a new peer", () => {
    const audio = track("audio");
    global.localStream = stream([audio]);
    const p = addPeer("bob");
    expect(p.pc.addTrack).toHaveBeenCalledWith(audio, localStream);
  });

  test("sends an existing screen share to a late joiner", () => {
    const video = track("video");
    global.screenEnabled = true;
    global.screenStream = stream([video]);
    const p = addPeer("bob");
    expect(p.pc.addTrack).toHaveBeenCalledWith(video, screenStream);
    expect(p.screenSenders).toHaveLength(1);
  });

  test("picks exactly one polite peer by username order", () => {
    expect(addPeer("bob").polite).toBe(true);
    expect(addPeer("aardvark").polite).toBe(false);
  });

  test("offers when negotiation is needed", async () => {
    const p = addPeer("bob");
    global.activeCallId = "c1";
    await p.pc.onnegotiationneeded();
    expect(p.makingOffer).toBe(false);
    expect(fetch).toHaveBeenCalledWith(
      "/calls/c1/signal",
      expect.objectContaining({ method: "POST" }),
    );
  });

  test("survives a failed negotiation", async () => {
    const p = addPeer("bob");
    p.pc.setLocalDescription = jest.fn(() => Promise.reject(new Error("nope")));
    await p.pc.onnegotiationneeded();
    expect(p.makingOffer).toBe(false);
  });

  test("relays local ICE candidates to the peer", () => {
    const p = addPeer("bob");
    global.activeCallId = "c1";
    p.pc.onicecandidate({ candidate: { toJSON: () => ({ candidate: "x" }) } });
    expect(fetch).toHaveBeenCalledWith(
      "/calls/c1/signal",
      expect.objectContaining({ method: "POST" }),
    );
  });

  test("ignores the end-of-candidates signal", () => {
    const p = addPeer("bob");
    global.activeCallId = "c1";
    p.pc.onicecandidate({ candidate: null });
    expect(fetch).not.toHaveBeenCalled();
  });

  test("_sendCallSignal is a no-op with no active call", async () => {
    await _sendCallSignal("bob", "offer", {});
    expect(fetch).not.toHaveBeenCalled();
  });
});

describe("connection state changes", () => {
  test("clears the gone timer and shares state once connected", () => {
    const p = addPeer("bob");
    p.goneTimer = setTimeout(() => {}, 10000);
    p.pc.connectionState = "connected";
    p.pc.onconnectionstatechange();
    expect(p.connState).toBe("connected");
    expect(p.goneTimer).toBeNull();
  });

  test("restarts ICE when the connection fails", () => {
    const p = addPeer("bob");
    p.pc.connectionState = "failed";
    p.pc.onconnectionstatechange();
    expect(p.pc.restartIce).toHaveBeenCalled();
    expect(p.goneTimer).not.toBeNull();
    clearTimeout(p.goneTimer);
  });

  test("arms the grace timer when the connection drops", () => {
    const p = addPeer("bob");
    p.pc.connectionState = "disconnected";
    p.pc.onconnectionstatechange();
    expect(p.pc.restartIce).not.toHaveBeenCalled();
    expect(p.goneTimer).not.toBeNull();
    clearTimeout(p.goneTimer);
  });

  test("ignores a closed connection", () => {
    const p = addPeer("bob");
    p.pc.connectionState = "closed";
    p.pc.onconnectionstatechange();
    expect(p.goneTimer).toBeNull();
  });

  test("does not arm a timer for a participant already torn down", () => {
    const p = addPeer("bob");
    const handler = p.pc.onconnectionstatechange;
    _removeRemoteParticipant("bob");
    p.pc.connectionState = "failed";
    handler();
    expect(p.goneTimer).toBeNull();
  });

  test("drops a peer that never comes back", () => {
    jest.useFakeTimers();
    try {
      const p = addPeer("bob");
      global.activeCallId = null;
      p.pc.connectionState = "failed";
      p.pc.onconnectionstatechange();
      jest.advanceTimersByTime(20000);
      expect(remoteParticipants.has("bob")).toBe(false);
    } finally {
      jest.useRealTimers();
    }
  });

  test("keeps a peer that recovers before the grace period ends", () => {
    jest.useFakeTimers();
    try {
      const p = addPeer("bob");
      p.pc.connectionState = "failed";
      p.pc.onconnectionstatechange();
      p.pc.connectionState = "connected";
      jest.advanceTimersByTime(20000);
      expect(remoteParticipants.has("bob")).toBe(true);
    } finally {
      jest.useRealTimers();
    }
  });
});

describe("_logPeerState()", () => {
  function pcWithListeners() {
    const listeners = {};
    return {
      iceConnectionState: "new",
      addEventListener: (type, fn) => {
        listeners[type] = fn;
      },
      fire: (type, arg) => listeners[type]?.(arg),
    };
  }

  test("logs a successful ICE connection", () => {
    const info = jest.spyOn(console, "info").mockImplementation(() => {});
    const pc = pcWithListeners();
    _logPeerState(pc, "peer");
    pc.iceConnectionState = "connected";
    pc.fire("iceconnectionstatechange");
    expect(info).toHaveBeenCalledWith(expect.stringContaining("connected"));
    info.mockRestore();
  });

  test("blames mDNS candidates when ICE fails after seeing them", () => {
    const warn = jest.spyOn(console, "warn").mockImplementation(() => {});
    const pc = pcWithListeners();
    _logPeerState(pc, "peer");
    pc.fire("icecandidate", {
      candidate: { candidate: "candidate:1 x.LOCAL" },
    });
    pc.iceConnectionState = "failed";
    pc.fire("iceconnectionstatechange");
    expect(warn).toHaveBeenCalledWith(
      expect.stringContaining("server-reflexive"),
    );
    warn.mockRestore();
  });

  test("suggests the network when ICE fails with no mDNS candidates", () => {
    const warn = jest.spyOn(console, "warn").mockImplementation(() => {});
    const pc = pcWithListeners();
    _logPeerState(pc, "peer");
    pc.fire("icecandidate", { candidate: null });
    pc.iceConnectionState = "failed";
    pc.fire("iceconnectionstatechange");
    expect(warn).toHaveBeenCalledWith(expect.stringContaining("same subnet"));
    warn.mockRestore();
  });

  test("warns on a disconnect", () => {
    const warn = jest.spyOn(console, "warn").mockImplementation(() => {});
    const pc = pcWithListeners();
    _logPeerState(pc, "peer");
    pc.iceConnectionState = "disconnected";
    pc.fire("iceconnectionstatechange");
    expect(warn).toHaveBeenCalledWith(expect.stringContaining("disconnected"));
    warn.mockRestore();
  });
});

// ── Meta data channel ─────────────────────────────────────────────────────────

describe("meta data channel", () => {
  test("opens a negotiated channel per peer", () => {
    const p = addPeer("bob");
    expect(p.pc.createDataChannel).toHaveBeenCalledWith("meta", {
      negotiated: true,
      id: 0,
    });
    expect(p.dc).not.toBeNull();
  });

  test("tolerates a browser without data channels", () => {
    RTCPeerConnection.mockImplementationOnce(() => ({
      addEventListener: jest.fn(),
      addTrack: jest.fn(),
      createDataChannel: () => {
        throw new Error("unsupported");
      },
    }));
    const p = addPeer("bob");
    expect(p.dc).toBeNull();
  });

  test("sends our state when the channel opens", () => {
    global.audioMuted = true;
    const p = addPeer("bob");
    p.dc.readyState = "open";
    p.dc.onopen();
    expect(JSON.parse(p.dc.send.mock.calls[0][0])).toEqual({
      t: "state",
      muted: true,
      sharing: false,
    });
  });

  test("applies a peer's state message and re-renders", () => {
    const p = addPeer("bob");
    p.dc.onmessage({ data: JSON.stringify({ t: "state", muted: true }) });
    expect(p.muted).toBe(true);
    expect(tileFor("user:bob").querySelector(".call-badge").title).toBe(
      "bob is muted",
    );
  });

  test("ignores malformed channel traffic", () => {
    const p = addPeer("bob");
    expect(() => p.dc.onmessage({ data: "not json" })).not.toThrow();
    expect(() => p.dc.onmessage({ data: '{"t":"other"}' })).not.toThrow();
    expect(p.muted).toBe(false);
  });

  test("does not send over a channel that is not open", () => {
    const p = addPeer("bob");
    p.dc.readyState = "connecting";
    _sendSelfState(p);
    expect(p.dc.send).not.toHaveBeenCalled();
  });

  test("swallows a send on a channel closed under us", () => {
    const p = addPeer("bob");
    p.dc.readyState = "open";
    p.dc.send = jest.fn(() => {
      throw new Error("closed");
    });
    expect(() => _sendSelfState(p)).not.toThrow();
  });

  test("broadcasts to every peer", () => {
    const bob = addPeer("bob");
    const carol = addPeer("carol");
    for (const p of [bob, carol]) p.dc.readyState = "open";
    _broadcastSelfState();
    expect(bob.dc.send).toHaveBeenCalled();
    expect(carol.dc.send).toHaveBeenCalled();
  });
});

// ── Remote tracks ─────────────────────────────────────────────────────────────

describe("remote tracks", () => {
  test("attaches remote audio to a hidden element and taps it for VAD", () => {
    const p = addPeer("bob");
    const s = stream([]);
    p.pc.ontrack({ track: track("audio"), streams: [s] });
    expect(p.audioEl).not.toBeNull();
    expect(p.audioEl.style.display).toBe("none");
    expect(p.vadAnalyser).not.toBeNull();
  });

  test("reuses the audio element on renegotiation", () => {
    const p = addPeer("bob");
    p.pc.ontrack({ track: track("audio"), streams: [stream([])] });
    const first = p.audioEl;
    p.pc.ontrack({ track: track("audio"), streams: [stream([])] });
    expect(p.audioEl).toBe(first);
  });

  test("wraps a bare track with no stream", () => {
    const p = addPeer("bob");
    p.pc.ontrack({ track: track("audio"), streams: [] });
    expect(MediaStream).toHaveBeenCalled();
  });

  test("ignores a track for a participant who has gone", () => {
    const p = addPeer("bob");
    const handler = p.pc.ontrack;
    _removeRemoteParticipant("bob");
    expect(() =>
      handler({ track: track("audio"), streams: [stream([])] }),
    ).not.toThrow();
  });

  test("survives an AudioContext that refuses to start", () => {
    const warn = jest.spyOn(console, "warn").mockImplementation(() => {});
    global.sharedAudioCtx = null;
    AudioContext.mockImplementationOnce(() => {
      throw new Error("no audio");
    });
    const p = addPeer("bob");
    p.pc.ontrack({ track: track("audio"), streams: [stream([])] });
    expect(warn).toHaveBeenCalledWith("VAD setup failed:", expect.any(Error));
    warn.mockRestore();
  });

  test("treats a remote video track as a screen share", () => {
    const p = addPeer("bob");
    p.pc.ontrack({ track: track("video"), streams: [stream([])] });
    expect(p.remoteSharing).toBe(true);
    expect(focusScreenKey).toBe("screen:bob");
    expect(callTiles.has("screen:bob")).toBe(true);
  });

  test("clears the screen when the remote track ends", () => {
    const p = addPeer("bob");
    const videoTrack = track("video");
    const listeners = {};
    videoTrack.addEventListener = (type, fn) => {
      listeners[type] = fn;
    };
    p.pc.ontrack({ track: videoTrack, streams: [stream([])] });
    global.pinnedTileKey = "screen:bob";
    listeners.ended();
    expect(p.screenStream).toBeNull();
    expect(p.remoteSharing).toBe(false);
    expect(focusScreenKey).toBeNull();
    expect(pinnedTileKey).toBeNull();
  });

  test("clearing a screen nobody is sharing does nothing", () => {
    addPeer("bob");
    expect(() => _clearRemoteScreen("bob")).not.toThrow();
    expect(() => _clearRemoteScreen("nobody")).not.toThrow();
  });
});

// ── Signalling ────────────────────────────────────────────────────────────────

describe("_handleCallSignal()", () => {
  test("adds an unknown sender as a participant", async () => {
    await _handleCallSignal({ from: "bob", type: "offer", payload: {} });
    expect(remoteParticipants.has("bob")).toBe(true);
  });

  test("buffers ICE candidates that arrive before the offer", async () => {
    const p = addPeer("bob");
    await _handleCallSignal({
      from: "bob",
      type: "ice_candidate",
      payload: { candidate: "c" },
    });
    expect(p.pendingCandidates).toHaveLength(1);
    expect(p.pc.addIceCandidate).not.toHaveBeenCalled();
  });

  test("applies ICE candidates once the remote description is set", async () => {
    const p = addPeer("bob");
    p.pc.remoteDescription = { type: "offer" };
    await _handleCallSignal({
      from: "bob",
      type: "ice_candidate",
      payload: { candidate: "c" },
    });
    expect(p.pc.addIceCandidate).toHaveBeenCalled();
  });

  test("answers an offer", async () => {
    global.activeCallId = "c1";
    const p = addPeer("bob");
    await _handleCallSignal({
      from: "bob",
      type: "offer",
      payload: { type: "offer" },
    });
    expect(p.pc.setRemoteDescription).toHaveBeenCalled();
    expect(p.pc.setLocalDescription).toHaveBeenCalled();
    expect(fetch).toHaveBeenCalledWith("/calls/c1/signal", expect.anything());
  });

  test("flushes buffered candidates after the description lands", async () => {
    const p = addPeer("bob");
    p.pendingCandidates = [{ candidate: "a" }, { candidate: "b" }];
    await _handleCallSignal({
      from: "bob",
      type: "answer",
      payload: { type: "answer" },
    });
    expect(p.pc.addIceCandidate).toHaveBeenCalledTimes(2);
    expect(p.pendingCandidates).toHaveLength(0);
  });

  test("an impolite peer ignores a colliding offer", async () => {
    const p = addPeer("aardvark"); // CURRENT_USER > name → impolite
    p.makingOffer = true;
    await _handleCallSignal({
      from: "aardvark",
      type: "offer",
      payload: { type: "offer" },
    });
    expect(p.ignoreOffer).toBe(true);
    expect(p.pc.setRemoteDescription).not.toHaveBeenCalled();
  });

  test("a polite peer yields to a colliding offer", async () => {
    const p = addPeer("bob"); // CURRENT_USER < name → polite
    p.pc.signalingState = "have-local-offer";
    await _handleCallSignal({
      from: "bob",
      type: "offer",
      payload: { type: "offer" },
    });
    expect(p.ignoreOffer).toBe(false);
    expect(p.pc.setRemoteDescription).toHaveBeenCalled();
  });

  test("does not answer an answer", async () => {
    const p = addPeer("bob");
    await _handleCallSignal({
      from: "bob",
      type: "answer",
      payload: { type: "answer" },
    });
    expect(p.pc.setLocalDescription).not.toHaveBeenCalled();
  });

  test("logs and swallows a signalling failure", async () => {
    const warn = jest.spyOn(console, "warn").mockImplementation(() => {});
    const p = addPeer("bob");
    p.pc.setRemoteDescription = jest.fn(() => Promise.reject(new Error("bad")));
    await _handleCallSignal({
      from: "bob",
      type: "offer",
      payload: { type: "offer" },
    });
    expect(warn).toHaveBeenCalledWith(
      "Signal handling error:",
      expect.any(Error),
    );
    warn.mockRestore();
  });

  test("ignores a signal for a peer with no connection", async () => {
    addPeer("bob").pc = null;
    await expect(
      _handleCallSignal({ from: "bob", type: "offer", payload: {} }),
    ).resolves.toBeUndefined();
  });
});

describe("_pollCallSignals()", () => {
  test("does nothing without an active call", async () => {
    await _pollCallSignals();
    expect(fetch).not.toHaveBeenCalled();
  });

  test("dispatches each signal and tracks the cursor", async () => {
    global.activeCallId = "c1";
    global.lastCallSignalId = 0;
    addPeer("bob");
    fetch.mockResolvedValueOnce({
      ok: true,
      json: () =>
        Promise.resolve([
          { id: 4, from: "bob", type: "ice_candidate", payload: {} },
          { id: 7, from: "bob", type: "ice_candidate", payload: {} },
        ]),
    });
    await _pollCallSignals();
    expect(lastCallSignalId).toBe(7);
  });

  test("gives up quietly on a failed poll", async () => {
    global.activeCallId = "c1";
    fetch.mockResolvedValueOnce({ ok: false });
    await expect(_pollCallSignals()).resolves.toBeUndefined();
    expect(_callSignalPolling).toBe(false);
  });

  test("does not overlap two polls", async () => {
    global.activeCallId = "c1";
    global._callSignalPolling = true;
    await _pollCallSignals();
    expect(fetch).not.toHaveBeenCalled();
    global._callSignalPolling = false;
  });

  test("starting signalling resets the cursor", () => {
    global.lastCallSignalId = 99;
    _startCallSignaling();
    expect(lastCallSignalId).toBe(0);
    expect(callSignalPollId).not.toBeNull();
    _stopCallSignaling();
    expect(callSignalPollId).toBeNull();
  });
});

// ── Mic meter and speaking detection ──────────────────────────────────────────

describe("microphone level meter", () => {
  test("does nothing without a local stream", () => {
    global.localStream = null;
    expect(() => _startMicLevelMeter()).not.toThrow();
    expect(micMeterPollId).toBeNull();
  });

  test("warns when getUserMedia granted no audio track", () => {
    const warn = jest.spyOn(console, "warn").mockImplementation(() => {});
    global.localStream = stream([]);
    _startMicLevelMeter();
    expect(warn).toHaveBeenCalledWith(
      expect.stringContaining("microphone was not granted"),
    );
    warn.mockRestore();
  });

  test("logs the chosen input device and drives the meter", () => {
    const info = jest.spyOn(console, "info").mockImplementation(() => {});
    global.localStream = stream([track("audio")]);
    _startMicLevelMeter();
    expect(info).toHaveBeenCalledWith(expect.stringContaining("Local mic:"));
    expect(micMeterPollId).not.toBeNull();
    info.mockRestore();
  });

  test("warns if the system mutes the input track", () => {
    const warn = jest.spyOn(console, "warn").mockImplementation(() => {});
    const listeners = {};
    const audio = track("audio", {
      addEventListener: (type, fn) => {
        listeners[type] = fn;
      },
    });
    global.localStream = stream([audio]);
    _startMicLevelMeter();
    listeners.mute();
    expect(warn).toHaveBeenCalledWith(
      expect.stringContaining("muted by the system"),
    );
    warn.mockRestore();
  });

  test("survives an AudioContext that will not start", () => {
    const warn = jest.spyOn(console, "warn").mockImplementation(() => {});
    global.localStream = stream([track("audio")]);
    AudioContext.mockImplementationOnce(() => {
      throw new Error("blocked");
    });
    _startMicLevelMeter();
    expect(warn).toHaveBeenCalledWith(
      "Mic level meter setup failed:",
      expect.any(Error),
    );
    warn.mockRestore();
  });

  test("stopping resets the bar and closes the context", () => {
    global.localStream = stream([track("audio")]);
    _startMicLevelMeter();
    _stopMicLevelMeter();
    expect(micMeterPollId).toBeNull();
    expect(micMeterCtx).toBeNull();
    expect(document.getElementById("call-mic-level").style.height).toBe("0%");
  });

  test("retries a suspended context on the next pointer gesture", () => {
    const ctx = {
      state: "suspended",
      resume: jest.fn(() => Promise.reject(new Error("blocked"))),
    };
    _resumeAudioContext(ctx);
    return Promise.resolve().then(() => {
      ctx.resume.mockClear();
      ctx.resume.mockReturnValue(Promise.resolve());
      document.dispatchEvent(new Event("pointerdown"));
      expect(ctx.resume).toHaveBeenCalled();
    });
  });

  test("leaves a running context alone", () => {
    const ctx = { state: "running", resume: jest.fn() };
    _resumeAudioContext(ctx);
    expect(ctx.resume).not.toHaveBeenCalled();
  });
});

describe("speaking detection", () => {
  test("reads zero from a missing analyser", () => {
    expect(_analyserLevel(null)).toBe(0);
  });

  test("averages the frequency data", () => {
    const analyser = {
      frequencyBinCount: 4,
      getByteFrequencyData: (buf) => buf.fill(40),
    };
    expect(_analyserLevel(analyser)).toBe(40);
  });

  test("rings the tile of whoever is speaking", () => {
    jest.useFakeTimers();
    try {
      const p = addPeer("bob");
      p.vadAnalyser = {
        frequencyBinCount: 4,
        getByteFrequencyData: (buf) => buf.fill(50),
      };
      _renderCall();
      _startSpeakingPoll();
      jest.advanceTimersByTime(150);
      expect(tileFor("user:bob").classList.contains("speaking")).toBe(true);
    } finally {
      jest.useRealTimers();
      _stopSpeakingPoll();
    }
  });

  test("never rings your own tile while muted", () => {
    jest.useFakeTimers();
    try {
      global.audioMuted = true;
      global.micMeterAnalyser = {
        frequencyBinCount: 4,
        getByteFrequencyData: (buf) => buf.fill(90),
      };
      _renderCall();
      _startSpeakingPoll();
      jest.advanceTimersByTime(150);
      expect(tileFor("user:alice").classList.contains("speaking")).toBe(false);
    } finally {
      jest.useRealTimers();
      _stopSpeakingPoll();
      global.micMeterAnalyser = null;
    }
  });

  test("only ever arms one poll", () => {
    _startSpeakingPoll();
    const id = speakingPollId;
    _startSpeakingPoll();
    expect(speakingPollId).toBe(id);
    _stopSpeakingPoll();
    expect(speakingPollId).toBeNull();
  });

  test("ignores a tile that is not rendered", () => {
    expect(() => _setTileSpeaking("user:ghost", true)).not.toThrow();
  });
});

// ── In-call screen share ──────────────────────────────────────────────────────

describe("toggleScreenShare()", () => {
  beforeEach(() => {
    global.localStream = stream([track("audio")]);
    global.activeCallId = "c1";
  });

  test("does nothing outside a call", async () => {
    global.activeCallId = null;
    await toggleScreenShare();
    expect(navigator.mediaDevices.getDisplayMedia).not.toHaveBeenCalled();
  });

  test("tells the user when the browser cannot share", async () => {
    const saved = navigator.mediaDevices.getDisplayMedia;
    navigator.mediaDevices.getDisplayMedia = undefined;
    await toggleScreenShare();
    expect(showToast).toHaveBeenCalledWith(
      "Your browser does not support screen sharing.",
    );
    navigator.mediaDevices.getDisplayMedia = saved;
  });

  test("stays quiet when the picker is cancelled", async () => {
    const warn = jest.spyOn(console, "warn").mockImplementation(() => {});
    navigator.mediaDevices.getDisplayMedia.mockRejectedValueOnce(
      new Error("cancelled"),
    );
    await toggleScreenShare();
    expect(screenEnabled).toBe(false);
    warn.mockRestore();
  });

  test("stops a capture that yielded no video", async () => {
    const dead = track("video");
    navigator.mediaDevices.getDisplayMedia.mockResolvedValueOnce({
      getVideoTracks: () => [],
      getTracks: () => [dead],
    });
    await toggleScreenShare();
    expect(dead.stop).toHaveBeenCalled();
    expect(screenEnabled).toBe(false);
  });

  test("adds the screen track to every peer and tells the server", async () => {
    const p = addPeer("bob");
    const video = track("video");
    p.pc.addTrack.mockReturnValue({
      track: video,
      getParameters: () => ({ encodings: [{}] }),
      setParameters: jest.fn(() => Promise.resolve()),
    });
    navigator.mediaDevices.getDisplayMedia.mockResolvedValueOnce(
      stream([video]),
    );
    await toggleScreenShare();
    expect(screenEnabled).toBe(true);
    expect(video.contentHint).toBe("detail");
    expect(p.screenSenders).toHaveLength(1);
    expect(fetch).toHaveBeenCalledWith(
      "/calls/c1/screenshare",
      expect.objectContaining({ body: JSON.stringify({ on: true }) }),
    );
    expect(document.getElementById("call-screen-btn").title).toBe(
      "Stop sharing your screen (S)",
    );
    expect(focusScreenKey).toBe("screen:alice");
  });

  test("stops sharing on a second toggle", async () => {
    const video = track("video");
    navigator.mediaDevices.getDisplayMedia.mockResolvedValueOnce(
      stream([video]),
    );
    await toggleScreenShare();
    await toggleScreenShare();
    expect(screenEnabled).toBe(false);
    expect(video.stop).toHaveBeenCalled();
    expect(fetch).toHaveBeenCalledWith(
      "/calls/c1/screenshare",
      expect.objectContaining({ body: JSON.stringify({ on: false }) }),
    );
    expect(document.getElementById("call-screen-btn").title).toBe(
      "Share your screen (S)",
    );
  });

  test("the browser's own stop button ends the share", async () => {
    const listeners = {};
    const video = track("video", {
      addEventListener: (type, fn) => {
        listeners[type] = fn;
      },
    });
    navigator.mediaDevices.getDisplayMedia.mockResolvedValueOnce(
      stream([video]),
    );
    await toggleScreenShare();
    listeners.ended();
    expect(screenEnabled).toBe(false);
  });

  test("removes the screen senders from every peer when stopping", async () => {
    const p = addPeer("bob");
    const sender = { getParameters: () => ({}), setParameters: jest.fn() };
    p.pc.addTrack.mockReturnValue(sender);
    navigator.mediaDevices.getDisplayMedia.mockResolvedValueOnce(
      stream([track("video")]),
    );
    await toggleScreenShare();
    global.pinnedTileKey = "screen:alice";
    _stopInCallScreenShare();
    expect(p.pc.removeTrack).toHaveBeenCalledWith(sender);
    expect(p.screenSenders).toHaveLength(0);
    expect(pinnedTileKey).toBeNull();
  });
});

describe("screen encoder tuning", () => {
  test("ignores a missing track", () => {
    expect(() => _tuneScreenTrack(null)).not.toThrow();
  });

  test("raises the bitrate ceiling on the sender", () => {
    const params = { encodings: [{}] };
    const sender = {
      getParameters: () => params,
      setParameters: jest.fn(() => Promise.resolve()),
    };
    _tuneScreenSender(sender);
    expect(params.encodings[0].maxBitrate).toBe(6000000);
  });

  test("creates an encoding entry when the sender has none", () => {
    const params = { encodings: [] };
    const sender = {
      getParameters: () => params,
      setParameters: jest.fn(() => Promise.resolve()),
    };
    _tuneScreenSender(sender);
    expect(sender.setParameters).toHaveBeenCalled();
  });

  test("tolerates a sender that rejects parameters", () => {
    const sender = {
      getParameters: () => {
        throw new Error("unsupported");
      },
    };
    expect(() => _tuneScreenSender(sender)).not.toThrow();
  });
});

// ── Standalone screen share (sharer) ──────────────────────────────────────────

describe("toggleStandaloneScreenShare()", () => {
  test("tells the user when the browser cannot share", async () => {
    const saved = navigator.mediaDevices.getDisplayMedia;
    navigator.mediaDevices.getDisplayMedia = undefined;
    await toggleStandaloneScreenShare();
    expect(showToast).toHaveBeenCalledWith(
      "Your browser does not support screen sharing.",
    );
    navigator.mediaDevices.getDisplayMedia = saved;
  });

  test("stays quiet when the picker is cancelled", async () => {
    const warn = jest.spyOn(console, "warn").mockImplementation(() => {});
    navigator.mediaDevices.getDisplayMedia.mockRejectedValueOnce(
      new Error("cancelled"),
    );
    await toggleStandaloneScreenShare();
    expect(standaloneShareId).toBeNull();
    warn.mockRestore();
  });

  test("registers the share and starts polling for viewers", async () => {
    fetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ share_id: "s1" }),
    });
    const video = track("video");
    navigator.mediaDevices.getDisplayMedia.mockResolvedValueOnce(
      stream([video]),
    );
    await toggleStandaloneScreenShare();
    expect(standaloneShareId).toBe("s1");
    expect(video.contentHint).toBe("detail");
    expect(standaloneSignalPollId).not.toBeNull();
    expect(document.getElementById("topbar-share-btn").title).toBe(
      "Stop sharing",
    );
  });

  test("stops a capture with no video track", async () => {
    const dead = track("audio");
    await _startStandaloneShare({
      getVideoTracks: () => [],
      getTracks: () => [dead],
    });
    expect(dead.stop).toHaveBeenCalled();
    expect(standaloneShareId).toBeNull();
  });

  test("releases the capture when the server refuses", async () => {
    fetch.mockResolvedValueOnce({ ok: false });
    const video = track("video");
    await _startStandaloneShare(stream([video]));
    expect(video.stop).toHaveBeenCalled();
    expect(standaloneShareId).toBeNull();
  });

  test("a second toggle stops the share", async () => {
    fetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ share_id: "s1" }),
    });
    const video = track("video");
    navigator.mediaDevices.getDisplayMedia.mockResolvedValueOnce(
      stream([video]),
    );
    await toggleStandaloneScreenShare();
    await toggleStandaloneScreenShare();
    expect(standaloneShareId).toBeNull();
    expect(video.stop).toHaveBeenCalled();
    expect(fetch).toHaveBeenCalledWith("/screenshare/s1/stop", {
      method: "POST",
    });
    expect(document.getElementById("topbar-share-btn").title).toBe(
      "Share screen",
    );
  });

  test("the browser's own stop button ends the share", async () => {
    const listeners = {};
    const video = track("video", {
      addEventListener: (type, fn) => {
        listeners[type] = fn;
      },
    });
    fetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ share_id: "s1" }),
    });
    await _startStandaloneShare(stream([video]));
    listeners.ended();
    expect(standaloneShareId).toBeNull();
  });

  test("closes every viewer connection when stopping", async () => {
    global.standaloneShareId = "s1";
    const pc = { close: jest.fn() };
    standaloneViewerPeers.set("bob", pc);
    standaloneViewerPending.set("bob", [{}]);
    await _stopStandaloneShare();
    expect(pc.close).toHaveBeenCalled();
    expect(standaloneViewerPeers.size).toBe(0);
    expect(standaloneViewerPending.size).toBe(0);
  });
});

describe("sharer signalling", () => {
  test("does not poll without a share", async () => {
    await _pollStandaloneSignals();
    expect(fetch).not.toHaveBeenCalled();
  });

  test("tracks the signal cursor", async () => {
    global.standaloneShareId = "s1";
    global.standaloneLastSignalId = 0;
    fetch.mockResolvedValueOnce({
      ok: true,
      json: () =>
        Promise.resolve([
          { id: 2, from: "bob", type: "ice_candidate", payload: {} },
        ]),
    });
    await _pollStandaloneSignals();
    expect(standaloneLastSignalId).toBe(2);
  });

  test("gives up quietly on a failed poll", async () => {
    global.standaloneShareId = "s1";
    fetch.mockResolvedValueOnce({ ok: false });
    await _pollStandaloneSignals();
    expect(_standaloneSignalPolling).toBe(false);
  });

  test("buffers a candidate that outruns its offer", () => {
    _addShareCandidate("bob", undefined, { candidate: "c" });
    expect(standaloneViewerPending.get("bob")).toHaveLength(1);
    _addShareCandidate("bob", undefined, { candidate: "d" });
    expect(standaloneViewerPending.get("bob")).toHaveLength(2);
  });

  test("applies a candidate once the peer has a description", () => {
    const pc = {
      remoteDescription: {},
      addIceCandidate: jest.fn(() => Promise.resolve()),
    };
    _addShareCandidate("bob", pc, { candidate: "c" });
    expect(pc.addIceCandidate).toHaveBeenCalled();
    expect(standaloneViewerPending.has("bob")).toBe(false);
  });

  test("flushing with nothing buffered is a no-op", async () => {
    const pc = { addIceCandidate: jest.fn(() => Promise.resolve()) };
    await _flushPendingShareCandidates("bob", pc);
    expect(pc.addIceCandidate).not.toHaveBeenCalled();
  });

  test("answers a viewer offer with the screen track", async () => {
    global.standaloneShareId = "s1";
    const video = track("video");
    global.standaloneShareStream = stream([video]);
    standaloneViewerPending.set("bob", [{ candidate: "c" }]);
    await _handleSharerSignal({
      from: "bob",
      type: "offer",
      payload: { type: "offer" },
    });
    const pc = standaloneViewerPeers.get("bob");
    expect(pc.setRemoteDescription).toHaveBeenCalled();
    expect(pc.setLocalDescription).toHaveBeenCalled();
    expect(fetch).toHaveBeenCalledWith(
      "/screenshare/s1/signal",
      expect.objectContaining({ method: "POST" }),
    );
    expect(standaloneViewerPending.has("bob")).toBe(false);
  });

  test("ignores a viewer offer when nothing is being shared", async () => {
    global.standaloneShareStream = null;
    await _handleSharerSignal({ from: "bob", type: "offer", payload: {} });
    expect(standaloneViewerPeers.size).toBe(0);
  });

  test("logs a failed answer", async () => {
    const warn = jest.spyOn(console, "warn").mockImplementation(() => {});
    global.standaloneShareId = "s1";
    global.standaloneShareStream = stream([track("video")]);
    RTCPeerConnection.mockImplementationOnce(() => ({
      addEventListener: jest.fn(),
      setRemoteDescription: () => Promise.reject(new Error("bad sdp")),
    }));
    await _answerViewerOffer("bob", { payload: {} });
    expect(warn).toHaveBeenCalledWith(
      "Sharer answer failed:",
      expect.any(Error),
    );
    warn.mockRestore();
  });

  test("relays the sharer's own ICE candidates", () => {
    global.standaloneShareId = "s1";
    const pc = _createViewerPeer("bob");
    pc.onicecandidate({ candidate: { toJSON: () => ({}) } });
    expect(fetch).toHaveBeenCalledWith(
      "/screenshare/s1/signal",
      expect.anything(),
    );
    pc.onicecandidate({ candidate: null });
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});

describe("_attachShareTrack()", () => {
  test("ignores a missing track", async () => {
    const pc = { getTransceivers: () => [] };
    await expect(_attachShareTrack(pc, "video", null, true)).resolves.toBe(
      undefined,
    );
  });

  test("replaces the track on the viewer's recvonly transceiver", async () => {
    const t = track("video");
    const tcv = {
      receiver: { track: { kind: "video" } },
      sender: { track: null, replaceTrack: jest.fn(() => Promise.resolve()) },
      direction: "recvonly",
    };
    const pc = { getTransceivers: () => [tcv] };
    await _attachShareTrack(pc, "video", t, true);
    expect(tcv.sender.replaceTrack).toHaveBeenCalledWith(t);
    expect(tcv.direction).toBe("sendonly");
  });

  test("does nothing when the track is already attached", async () => {
    const t = track("video");
    const tcv = {
      receiver: { track: { kind: "video" } },
      sender: { track: t, replaceTrack: jest.fn() },
    };
    await _attachShareTrack({ getTransceivers: () => [tcv] }, "video", t, true);
    expect(tcv.sender.replaceTrack).not.toHaveBeenCalled();
  });

  test("adds a video track when the viewer offered no transceiver", async () => {
    const pc = { getTransceivers: () => [], addTrack: jest.fn() };
    const t = track("video");
    await _attachShareTrack(pc, "video", t, true);
    expect(pc.addTrack).toHaveBeenCalled();
  });

  test("never adds an audio m-line the viewer did not offer", async () => {
    const pc = { getTransceivers: () => [], addTrack: jest.fn() };
    await _attachShareTrack(pc, "audio", track("audio"), false);
    expect(pc.addTrack).not.toHaveBeenCalled();
  });

  test("tunes the video sender after attaching", async () => {
    const setParameters = jest.fn(() => Promise.resolve());
    const pc = {
      getTransceivers: () => [],
      addTrack: jest.fn(),
      getSenders: () => [
        {
          track: { kind: "video" },
          getParameters: () => ({ encodings: [{}] }),
          setParameters,
        },
      ],
    };
    global.standaloneShareStream = stream([track("video"), track("audio")]);
    await _attachScreenTrack(pc);
    expect(setParameters).toHaveBeenCalled();
  });
});

// ── Share banner ──────────────────────────────────────────────────────────────

describe("applyScreenShares() / _renderShareBanner()", () => {
  test("ignores shares in a public channel", () => {
    global.channel = "general";
    applyScreenShares([{ share_id: "s1", sharer: "bob" }]);
    expect(_currentRemoteShares).toHaveLength(0);
  });

  test("hides the banner when nobody is sharing", () => {
    applyScreenShares([]);
    expect(document.getElementById("screenshare-banner").style.display).toBe(
      "none",
    );
  });

  test("never counts your own share as a remote one", () => {
    applyScreenShares([{ share_id: "s1", sharer: CURRENT_USER }]);
    expect(_currentRemoteShares).toHaveLength(0);
  });

  test("names a single sharer", () => {
    applyScreenShares([{ share_id: "s1", sharer: "bob" }]);
    const banner = document.getElementById("screenshare-banner");
    expect(banner.style.display).toBe("flex");
    expect(document.getElementById("screenshare-banner-text").textContent).toBe(
      "bob is sharing their screen",
    );
    expect(
      document.getElementById("screenshare-banner-view-btn").textContent,
    ).toContain("Watch");
  });

  test("names two sharers", () => {
    applyScreenShares([
      { share_id: "s1", sharer: "bob" },
      { share_id: "s2", sharer: "carol" },
    ]);
    expect(document.getElementById("screenshare-banner-text").textContent).toBe(
      "bob, carol are sharing their screens",
    );
    expect(
      document.getElementById("screenshare-banner-view-btn").textContent,
    ).toContain("Watch (2)");
  });

  test("summarises more than two sharers", () => {
    applyScreenShares(
      ["bob", "carol", "dave", "erin"].map((u, i) => ({
        share_id: "s" + i,
        sharer: u,
      })),
    );
    expect(document.getElementById("screenshare-banner-text").textContent).toBe(
      "bob, carol and 2 more are sharing their screens",
    );
  });

  test("caps the banner face pile at three and reuses it", () => {
    const shares = ["bob", "carol", "dave", "erin"].map((u, i) => ({
      share_id: "s" + i,
      sharer: u,
    }));
    applyScreenShares(shares);
    expect(
      document.getElementById("screenshare-banner-avatars").children,
    ).toHaveLength(3);
    makeAvatarWrap.mockClear();
    applyScreenShares(shares);
    expect(makeAvatarWrap).not.toHaveBeenCalled();
  });

  test("offers a stop button while you are also sharing", () => {
    global.standaloneShareId = "s9";
    applyScreenShares([{ share_id: "s1", sharer: "bob" }]);
    expect(
      document.getElementById("screenshare-banner-stop-btn").style.display,
    ).toBe("inline-flex");
  });

  test("says so when only you are sharing", () => {
    global.standaloneShareId = "s9";
    applyScreenShares([]);
    expect(document.getElementById("screenshare-banner-text").textContent).toBe(
      "You are sharing your screen",
    );
    expect(
      document.getElementById("screenshare-banner-view-btn").style.display,
    ).toBe("none");
  });

  test("hides the banner while the viewer overlay is open", () => {
    applyScreenShares([{ share_id: "s1", sharer: "bob" }]);
    openShareViewer();
    expect(document.getElementById("screenshare-banner").style.display).toBe(
      "none",
    );
    closeShareViewer();
  });

  test("closes the viewer once every sharer stops", () => {
    applyScreenShares([{ share_id: "s1", sharer: "bob" }]);
    openShareViewer();
    applyScreenShares([]);
    expect(viewShareId).toBeNull();
    expect(document.getElementById("screenshare-viewer").style.display).toBe(
      "none",
    );
  });
});

describe("_notifyNewShare()", () => {
  afterEach(() => {
    delete document.hidden;
    Notification.permission = "default";
  });

  function hide() {
    Object.defineProperty(document, "hidden", {
      value: true,
      configurable: true,
    });
  }

  test("notifies once for a new share in a hidden tab", () => {
    hide();
    global.nativeNotifEnabled = true;
    Notification.permission = "granted";
    applyScreenShares([{ share_id: "s1", sharer: "bob" }]);
    expect(Notification).toHaveBeenCalledWith(
      "Screen Share — MiniMost",
      expect.objectContaining({ body: "bob is sharing their screen" }),
    );
    applyScreenShares([{ share_id: "s1", sharer: "bob" }]);
    expect(Notification).toHaveBeenCalledTimes(1);
  });

  test("stays silent while the tab is visible", () => {
    global.nativeNotifEnabled = true;
    Notification.permission = "granted";
    applyScreenShares([{ share_id: "s1", sharer: "bob" }]);
    expect(Notification).not.toHaveBeenCalled();
  });

  test("stays silent without permission", () => {
    hide();
    global.nativeNotifEnabled = true;
    Notification.permission = "denied";
    applyScreenShares([{ share_id: "s1", sharer: "bob" }]);
    expect(Notification).not.toHaveBeenCalled();
  });
});

describe("refreshScreenShares()", () => {
  test("skips channels that cannot host a share", async () => {
    global.channel = "general";
    await refreshScreenShares();
    expect(fetch).not.toHaveBeenCalled();
  });

  test("applies the shares the server reports", async () => {
    fetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve([{ share_id: "s1", sharer: "bob" }]),
    });
    await refreshScreenShares();
    expect(_currentRemoteShare).toMatchObject({ sharer: "bob" });
  });

  test("ignores a failed request", async () => {
    fetch.mockResolvedValueOnce({ ok: false });
    await refreshScreenShares();
    expect(_currentRemoteShares).toHaveLength(0);
  });

  test("ignores a network error", async () => {
    fetch.mockRejectedValueOnce(new Error("offline"));
    await expect(refreshScreenShares()).resolves.toBeUndefined();
  });
});

// ── Share viewer ──────────────────────────────────────────────────────────────

describe("share viewer", () => {
  afterEach(() => {
    closeShareViewer();
  });

  test("does nothing when there is nothing to watch", () => {
    openShareViewer();
    expect(document.getElementById("screenshare-viewer").style.display).toBe(
      "none",
    );
  });

  test("opens a connection per share and offers to the sharer", () => {
    applyScreenShares([{ share_id: "s1", sharer: "bob" }]);
    openShareViewer();
    expect(document.getElementById("screenshare-viewer").style.display).toBe(
      "flex",
    );
    expect(shareViewers.size).toBe(1);
    const viewer = shareViewers.get("s1");
    expect(viewer.pc.addTransceiver).toHaveBeenCalledWith("video", {
      direction: "recvonly",
    });
    expect(shareViewerPollId).not.toBeNull();
  });

  test("puts the focused share on the stage and the rest in the strip", () => {
    applyScreenShares([
      { share_id: "s1", sharer: "bob" },
      { share_id: "s2", sharer: "carol" },
    ]);
    openShareViewer();
    expect(
      document.getElementById("screenshare-viewer-stage").children,
    ).toHaveLength(1);
    expect(
      document.getElementById("screenshare-viewer-strip").children,
    ).toHaveLength(1);
    expect(
      document.getElementById("screenshare-viewer-label").textContent,
    ).toBe("bob is sharing their screen · 1 other share below");
  });

  test("pluralises the count of other shares", () => {
    applyScreenShares(
      ["bob", "carol", "dave"].map((u, i) => ({
        share_id: "s" + i,
        sharer: u,
      })),
    );
    openShareViewer();
    expect(
      document.getElementById("screenshare-viewer-label").textContent,
    ).toContain("2 other shares below");
  });

  test("clicking a strip tile swaps it onto the stage", () => {
    applyScreenShares([
      { share_id: "s1", sharer: "bob" },
      { share_id: "s2", sharer: "carol" },
    ]);
    openShareViewer();
    shareViewers.get("s2").tileEl.dispatchEvent(new Event("click"));
    expect(viewerFocusShareId).toBe("s2");
    expect(
      document.getElementById("screenshare-viewer-stage").firstChild.dataset
        .share,
    ).toBe("s2");
  });

  test("names each tile after its sharer", () => {
    applyScreenShares([{ share_id: "s1", sharer: "bob" }]);
    openShareViewer();
    const tile = shareViewers.get("s1").tileEl;
    expect(tile.querySelector(".ss-tile-name").textContent).toBe("bob");
    expect(tile.querySelector(".ss-tile-status").textContent).toContain(
      "Connecting to bob…",
    );
  });

  test("marks a tile live once its track arrives", () => {
    applyScreenShares([{ share_id: "s1", sharer: "bob" }]);
    openShareViewer();
    const viewer = shareViewers.get("s1");
    viewer.pc.ontrack({ track: track("video"), streams: [stream([])] });
    expect(viewer.tileEl.classList.contains("live")).toBe(true);
  });

  test("relays the viewer's ICE candidates to the sharer", () => {
    applyScreenShares([{ share_id: "s1", sharer: "bob" }]);
    openShareViewer();
    fetch.mockClear();
    shareViewers
      .get("s1")
      .pc.onicecandidate({ candidate: { toJSON: () => ({}) } });
    expect(fetch).toHaveBeenCalledWith(
      "/screenshare/s1/signal",
      expect.anything(),
    );
  });

  test("tears down a share that stops and keeps the rest", () => {
    applyScreenShares([
      { share_id: "s1", sharer: "bob" },
      { share_id: "s2", sharer: "carol" },
    ]);
    openShareViewer();
    const gone = shareViewers.get("s1");
    applyScreenShares([{ share_id: "s2", sharer: "carol" }]);
    expect(gone.pc.close).toHaveBeenCalled();
    expect(shareViewers.size).toBe(1);
    expect(viewerFocusShareId).toBe("s2");
  });

  test("closing tears down every connection", () => {
    applyScreenShares([{ share_id: "s1", sharer: "bob" }]);
    openShareViewer();
    const viewer = shareViewers.get("s1");
    closeShareViewer();
    expect(viewer.pc.close).toHaveBeenCalled();
    expect(shareViewers.size).toBe(0);
    expect(shareViewerPollId).toBeNull();
    expect(viewShareId).toBeNull();
  });

  test("tearing down an unknown share is a no-op", () => {
    expect(() => _teardownShareViewer("nope")).not.toThrow();
  });

  test("logs a failed viewer offer", async () => {
    const warn = jest.spyOn(console, "warn").mockImplementation(() => {});
    RTCPeerConnection.mockImplementationOnce(() => ({
      addEventListener: jest.fn(),
      addTransceiver: jest.fn(),
      createOffer: () => Promise.reject(new Error("no")),
    }));
    _startShareViewerConnection({ share_id: "s1", sharer: "bob" });
    await new Promise((r) => setTimeout(r, 0));
    expect(warn).toHaveBeenCalledWith(
      "Viewer offer failed:",
      expect.any(Error),
    );
    warn.mockRestore();
  });
});

describe("viewer signalling", () => {
  function viewer() {
    return {
      pc: new RTCPeerConnection(),
      lastSignalId: 0,
      polling: false,
      pending: [],
    };
  }

  test("applies an answer and flushes buffered candidates", async () => {
    const v = viewer();
    v.pending = [{ candidate: "a" }];
    await _handleViewerSignal(v, {
      type: "answer",
      payload: { type: "answer" },
    });
    expect(v.pc.setRemoteDescription).toHaveBeenCalled();
    expect(v.pc.addIceCandidate).toHaveBeenCalledTimes(1);
    expect(v.pending).toHaveLength(0);
  });

  test("buffers candidates that beat the answer", async () => {
    const v = viewer();
    await _handleViewerSignal(v, {
      type: "ice_candidate",
      payload: { candidate: "a" },
    });
    expect(v.pending).toHaveLength(1);
    expect(v.pc.addIceCandidate).not.toHaveBeenCalled();
  });

  test("applies candidates once the answer has landed", async () => {
    const v = viewer();
    v.pc.remoteDescription = { type: "answer" };
    await _handleViewerSignal(v, {
      type: "ice_candidate",
      payload: { candidate: "a" },
    });
    expect(v.pc.addIceCandidate).toHaveBeenCalled();
  });

  test("polls each watched share and tracks its cursor", async () => {
    const v = viewer();
    shareViewers.set("s1", v);
    fetch.mockResolvedValueOnce({
      ok: true,
      json: () =>
        Promise.resolve([
          { id: 5, type: "answer", payload: { type: "answer" } },
        ]),
    });
    await _pollViewerSignals();
    expect(v.lastSignalId).toBe(5);
    expect(v.polling).toBe(false);
    shareViewers.clear();
  });

  test("skips a share whose poll is still in flight", async () => {
    const v = viewer();
    v.polling = true;
    shareViewers.set("s1", v);
    await _pollViewerSignals();
    expect(fetch).not.toHaveBeenCalled();
    shareViewers.clear();
  });

  test("ignores a failed poll", async () => {
    const v = viewer();
    shareViewers.set("s1", v);
    fetch.mockResolvedValueOnce({ ok: false });
    await _pollViewerSignals();
    expect(v.lastSignalId).toBe(0);
    shareViewers.clear();
  });
});

describe("_cleanupStandaloneShare()", () => {
  test("stops your share and closes the viewer", () => {
    global.standaloneShareId = "s1";
    applyScreenShares([{ share_id: "s2", sharer: "bob" }]);
    openShareViewer();
    _cleanupStandaloneShare();
    expect(standaloneShareId).toBeNull();
    expect(viewShareId).toBeNull();
    expect(_currentRemoteShares).toHaveLength(0);
    expect(document.getElementById("screenshare-banner").style.display).toBe(
      "none",
    );
  });
});

// ── Call lifecycle ────────────────────────────────────────────────────────────

describe("acceptCall()", () => {
  test("does nothing without an incoming call", async () => {
    global.incomingCallData = null;
    await acceptCall();
    expect(fetch).not.toHaveBeenCalled();
  });

  test("refuses over an insecure connection", async () => {
    global.incomingCallData = { call_id: "c1", initiator: "bob" };
    global.isSecureContext = false;
    await acceptCall();
    expect(showToast).toHaveBeenCalled();
    expect(activeCallId).toBeNull();
    global.isSecureContext = true;
  });

  test("joins the call and opens the panel", async () => {
    global.incomingCallData = { call_id: "c1", initiator: "bob" };
    fetch.mockResolvedValueOnce({ ok: true });
    await acceptCall();
    expect(activeCallId).toBe("c1");
    expect(callState).toBe("active");
    expect(document.getElementById("call-panel").style.display).toBe("flex");
    await endCall();
  });

  test("stays out of the call when the server refuses", async () => {
    global.incomingCallData = { call_id: "c1", initiator: "bob" };
    fetch.mockResolvedValueOnce({ ok: false });
    await acceptCall();
    expect(activeCallId).toBeNull();
  });

  test("hangs up when the microphone cannot be opened", async () => {
    const error = jest.spyOn(console, "error").mockImplementation(() => {});
    global.incomingCallData = { call_id: "c1", initiator: "bob" };
    fetch.mockResolvedValueOnce({ ok: true });
    navigator.mediaDevices.getUserMedia.mockRejectedValueOnce(
      new Error("denied"),
    );
    await acceptCall();
    expect(activeCallId).toBeNull();
    expect(fetch).toHaveBeenCalledWith("/calls/c1/end", { method: "POST" });
    error.mockRestore();
  });
});

describe("rejectCall()", () => {
  test("does nothing without an incoming call", async () => {
    global.incomingCallData = null;
    await rejectCall();
    expect(fetch).not.toHaveBeenCalled();
  });

  test("tells the server and closes the overlay", async () => {
    openIncomingCallUI({ call_id: "c1", initiator: "bob" });
    await rejectCall();
    expect(fetch).toHaveBeenCalledWith("/calls/c1/reject", { method: "POST" });
    expect(document.getElementById("call-incoming").style.display).toBe("none");
  });
});

describe("_handleRingTimeout()", () => {
  test("does nothing once the call has gone", async () => {
    global.activeCallId = null;
    await _handleRingTimeout();
    expect(fetch).not.toHaveBeenCalled();
  });

  test("ends an unanswered call and says so", async () => {
    jest.useFakeTimers();
    try {
      global.activeCallId = "c1";
      await _handleRingTimeout();
      expect(fetch).toHaveBeenCalledWith("/calls/c1/end", { method: "POST" });
      expect(document.getElementById("call-timer").textContent).toBe(
        "No answer",
      );
      expect(document.getElementById("call-status-text").textContent).toBe(
        "No answer",
      );
      jest.advanceTimersByTime(3000);
      expect(document.getElementById("call-panel").style.display).toBe("none");
    } finally {
      jest.useRealTimers();
    }
  });
});

describe("_pollCallState()", () => {
  function stateResponse(data) {
    fetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve(data),
    });
  }

  test("does nothing without an active call", async () => {
    await _pollCallState();
    expect(fetch).not.toHaveBeenCalled();
  });

  test("ignores a failed request", async () => {
    global.activeCallId = "c1";
    fetch.mockResolvedValueOnce({ ok: false });
    await _pollCallState();
    expect(activeCallId).toBe("c1");
  });

  test("stops ringing once the call goes active", async () => {
    global.activeCallId = "c1";
    global.ringTimeoutId = setTimeout(() => {}, 60000);
    global.callingAudio = { pause: jest.fn() };
    stateResponse({
      state: "active",
      participants: [{ username: "bob", state: "accepted" }],
    });
    await _pollCallState();
    expect(ringTimeoutId).toBeNull();
    expect(callingAudio).toBeNull();
    expect(remoteParticipants.has("bob")).toBe(true);
  });

  test("tears the call down when the server says it ended", async () => {
    global.activeCallId = "c1";
    stateResponse({ state: "ended" });
    await _pollCallState();
    expect(activeCallId).toBeNull();
    expect(document.getElementById("call-panel").style.display).toBe("none");
  });

  test("tears the call down when it was rejected", async () => {
    global.activeCallId = "c1";
    stateResponse({ state: "rejected" });
    await _pollCallState();
    expect(activeCallId).toBeNull();
  });

  test("tracks who is still ringing", async () => {
    global.activeCallId = "c1";
    stateResponse({
      state: "ringing",
      participants: [
        { username: "bob", state: "accepted" },
        { username: "dave", state: "pending" },
        { username: CURRENT_USER, state: "accepted" },
      ],
    });
    await _pollCallState();
    expect([...pendingInvitees]).toEqual(["dave"]);
    expect(remoteParticipants.has("bob")).toBe(true);
  });

  test("hangs up rather than sitting alone in an active call", async () => {
    global.activeCallId = "c1";
    stateResponse({ state: "active", participants: [] });
    await _pollCallState();
    expect(activeCallId).toBeNull();
  });

  test("clears a screen the server no longer lists", async () => {
    global.activeCallId = "c1";
    const p = addPeer("bob");
    p.screenStream = stream([track("video")]);
    stateResponse({
      state: "active",
      participants: [{ username: "bob", state: "accepted" }],
      screensharers: [],
    });
    await _pollCallState();
    expect(p.screenStream).toBeNull();
  });

  test("accepts the older single-sharer field", async () => {
    global.activeCallId = "c1";
    const p = addPeer("bob");
    p.screenStream = stream([track("video")]);
    stateResponse({
      state: "active",
      participants: [{ username: "bob", state: "accepted" }],
      screenshare_user: "bob",
    });
    await _pollCallState();
    expect(p.screenStream).not.toBeNull();
  });

  test("swallows a network error", async () => {
    global.activeCallId = "c1";
    fetch.mockRejectedValueOnce(new Error("offline"));
    await expect(_pollCallState()).resolves.toBeUndefined();
  });
});

describe("_handlePeerGone()", () => {
  test("ignores a peer that already left", () => {
    expect(() => _handlePeerGone("ghost")).not.toThrow();
  });

  test("keeps the call alive while other peers remain", () => {
    global.activeCallId = "c1";
    addPeer("bob");
    addPeer("carol");
    _handlePeerGone("bob");
    expect(activeCallId).toBe("c1");
    expect(remoteParticipants.has("bob")).toBe(false);
  });

  test("ends the call when the last peer disappears", () => {
    global.activeCallId = "c1";
    addPeer("bob");
    _handlePeerGone("bob");
    expect(activeCallId).toBeNull();
  });
});

describe("_removeAllParticipants()", () => {
  test("closes every connection and the shared audio context", () => {
    const p = addPeer("bob");
    p.pc.ontrack({ track: track("audio"), streams: [stream([])] });
    const audioEl = p.audioEl;
    _startSpeakingPoll();
    _removeAllParticipants();
    expect(remoteParticipants.size).toBe(0);
    expect(p.pc.close).toHaveBeenCalled();
    expect(audioEl.isConnected).toBe(false);
    expect(speakingPollId).toBeNull();
    expect(sharedAudioCtx).toBeNull();
  });

  test("tolerates a connection that refuses to close", () => {
    const p = addPeer("bob");
    p.pc.close = jest.fn(() => {
      throw new Error("already closed");
    });
    expect(() => _removeRemoteParticipant("bob")).not.toThrow();
  });

  test("removing an unknown participant is a no-op", () => {
    expect(() => _removeRemoteParticipant("ghost")).not.toThrow();
  });
});

describe("toggleAudioMute()", () => {
  test("does nothing without a microphone", () => {
    global.localStream = null;
    toggleAudioMute();
    expect(audioMuted).toBe(false);
  });

  test("disables the track and marks the button", () => {
    const audio = track("audio");
    global.localStream = stream([audio]);
    toggleAudioMute();
    expect(audioMuted).toBe(true);
    expect(audio.enabled).toBe(false);
    const btn = document.getElementById("call-mute-audio-btn");
    expect(btn.classList.contains("muted")).toBe(true);
    expect(btn.title).toBe("Unmute (M)");
    toggleAudioMute();
    expect(audioMuted).toBe(false);
    expect(audio.enabled).toBe(true);
    expect(btn.title).toBe("Mute (M)");
  });
});

// ── Invite panel ──────────────────────────────────────────────────────────────

describe("call invite panel", () => {
  test("loads the user list once and opens", async () => {
    fetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve(["alice", "bob", "carol"]),
    });
    await toggleCallInvitePanel();
    expect(document.getElementById("call-invite-panel").style.display).toBe(
      "flex",
    );
    expect(_inviteAllUsers).toEqual(["alice", "bob", "carol"]);
    fetch.mockClear();
    await toggleCallInvitePanel(); // closes
    await toggleCallInvitePanel(); // reopens without refetching
    expect(fetch).not.toHaveBeenCalled();
  });

  test("falls back to an empty list when /users fails", async () => {
    fetch.mockResolvedValueOnce({ ok: false });
    await toggleCallInvitePanel();
    expect(_inviteAllUsers).toEqual([]);
  });

  test("falls back to an empty list on a network error", async () => {
    fetch.mockRejectedValueOnce(new Error("offline"));
    await toggleCallInvitePanel();
    expect(_inviteAllUsers).toEqual([]);
  });

  test("lists everyone who is not already in the call", () => {
    global._inviteAllUsers = ["alice", "bob", "carol"];
    addPeer("bob");
    _renderCallInviteList("");
    const list = document.getElementById("call-invite-list");
    expect(list.children).toHaveLength(1);
    expect(list.textContent).toContain("carol");
  });

  test("excludes invitees who are still ringing", () => {
    global._inviteAllUsers = ["alice", "bob"];
    pendingInvitees.add("bob");
    _renderCallInviteList("");
    expect(
      document
        .getElementById("call-invite-list")
        .querySelector(".call-invite-empty").textContent,
    ).toBe("Everyone is already in the call");
  });

  test("filters by the search query", () => {
    global._inviteAllUsers = ["bob", "carol"];
    filterCallInviteList("car");
    const list = document.getElementById("call-invite-list");
    expect(list.children).toHaveLength(1);
    expect(list.innerHTML).toContain("<b>carol</b>");
  });

  test("says so when the query matches nobody", () => {
    global._inviteAllUsers = ["bob"];
    filterCallInviteList("zzz");
    expect(
      document
        .getElementById("call-invite-list")
        .querySelector(".call-invite-empty").textContent,
    ).toBe("No matches");
  });

  test("invites a user and shows them ringing", async () => {
    global.activeCallId = "c1";
    global._inviteAllUsers = ["carol"];
    _renderCallInviteList("");
    const item = document.getElementById("call-invite-list").firstChild;
    fetch.mockResolvedValueOnce({ ok: true });
    await item.onclick();
    expect(fetch).toHaveBeenCalledWith(
      "/calls/c1/invite",
      expect.objectContaining({ body: JSON.stringify({ username: "carol" }) }),
    );
    expect(item.querySelector(".invite-status").textContent).toBe("Invited");
    expect(pendingInvitees.has("carol")).toBe(true);
  });

  test("reports a refused invite", async () => {
    global.activeCallId = "c1";
    global._inviteAllUsers = ["carol"];
    _renderCallInviteList("");
    const item = document.getElementById("call-invite-list").firstChild;
    fetch.mockResolvedValueOnce({ ok: false });
    await item.onclick();
    expect(item.querySelector(".invite-status").textContent).toBe("Failed");
    expect(pendingInvitees.has("carol")).toBe(false);
  });

  test("reports a failed invite request", async () => {
    global.activeCallId = "c1";
    global._inviteAllUsers = ["carol"];
    _renderCallInviteList("");
    const item = document.getElementById("call-invite-list").firstChild;
    fetch.mockRejectedValueOnce(new Error("offline"));
    await item.onclick();
    expect(item.querySelector(".invite-status").textContent).toBe("Failed");
  });

  test("does not invite outside a call", async () => {
    await _sendCallInvite("carol", document.createElement("div"));
    expect(fetch).not.toHaveBeenCalled();
  });

  test.each([
    ["closes when clicking outside it", "call-participants-grid", "none"],
    ["stays open when clicking inside it", "call-invite-list", "flex"],
    ["stays open when clicking its own button", "call-invite-btn", "flex"],
  ])("%s", (_name, clickedId, expected) => {
    document.getElementById("call-invite-panel").style.display = "flex";
    document
      .getElementById(clickedId)
      .dispatchEvent(new Event("click", { bubbles: true }));
    expect(document.getElementById("call-invite-panel").style.display).toBe(
      expected,
    );
  });
});

// ── Incoming calls ────────────────────────────────────────────────────────────

describe("applyIncomingCalls()", () => {
  test("ignores incoming calls while already in one", () => {
    global.activeCallId = "c1";
    applyIncomingCalls([{ call_id: "c2", initiator: "bob" }]);
    expect(document.getElementById("call-incoming").style.display).toBe("none");
  });

  test("opens the overlay for the first ringing call", () => {
    applyIncomingCalls([{ call_id: "c2", initiator: "bob" }]);
    expect(document.getElementById("call-incoming").style.display).toBe("flex");
    expect(document.getElementById("call-caller-name").textContent).toBe("bob");
    closeIncomingCallUI();
  });

  test("closes the overlay when the caller gives up", () => {
    applyIncomingCalls([{ call_id: "c2", initiator: "bob" }]);
    applyIncomingCalls([]);
    expect(document.getElementById("call-incoming").style.display).toBe("none");
  });

  test("leaves the overlay alone while the call still rings", () => {
    applyIncomingCalls([{ call_id: "c2", initiator: "bob" }]);
    applyIncomingCalls([{ call_id: "c2", initiator: "bob" }]);
    expect(document.getElementById("call-incoming").style.display).toBe("flex");
    closeIncomingCallUI();
  });

  test("says which private channel a group call came from", () => {
    openIncomingCallUI({
      call_id: "c1",
      initiator: "bob",
      channel: "private:1",
    });
    expect(document.getElementById("call-incoming-context").textContent).toBe(
      "in Team Rocket",
    );
    closeIncomingCallUI();
  });

  test("adds no context for a one-to-one call", () => {
    openIncomingCallUI({
      call_id: "c1",
      initiator: "bob",
      channel: "dm:alice:bob",
    });
    expect(document.getElementById("call-incoming-context").textContent).toBe(
      "",
    );
    closeIncomingCallUI();
  });

  test("rings and shows a notification when enabled", () => {
    global.notifMuted = false;
    global.nativeNotifEnabled = true;
    Notification.permission = "granted";
    openIncomingCallUI({ call_id: "c1", initiator: "bob" });
    expect(Audio).toHaveBeenCalledWith("/static/receiving_call.mp3");
    expect(Notification).toHaveBeenCalledWith(
      "Incoming Call — MiniMost",
      expect.objectContaining({ body: "bob is calling you" }),
    );
    closeIncomingCallUI();
    Notification.permission = "default";
  });

  test("stops the ring when the overlay closes", () => {
    global.notifMuted = false;
    openIncomingCallUI({ call_id: "c1", initiator: "bob" });
    const audio = ringAudio;
    closeIncomingCallUI();
    expect(audio.pause).toHaveBeenCalled();
    expect(ringAudio).toBeNull();
    expect(incomingCallData).toBeNull();
  });
});

describe("pollIncomingCalls()", () => {
  test("does not poll during a call", () => {
    global.activeCallId = "c1";
    pollIncomingCalls();
    expect(fetch).not.toHaveBeenCalled();
  });

  test("opens the overlay for what the server reports", async () => {
    fetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve([{ call_id: "c9", initiator: "bob" }]),
    });
    pollIncomingCalls();
    await new Promise((r) => setTimeout(r, 0));
    expect(document.getElementById("call-caller-name").textContent).toBe("bob");
    closeIncomingCallUI();
  });

  test("ignores a failed poll", async () => {
    fetch.mockResolvedValueOnce({ ok: false });
    pollIncomingCalls();
    await new Promise((r) => setTimeout(r, 0));
    expect(document.getElementById("call-incoming").style.display).toBe("none");
  });
});

// ── Keyboard shortcuts ────────────────────────────────────────────────────────

describe("keyboard shortcuts", () => {
  function press(key, target) {
    const e = new KeyboardEvent("keydown", {
      key,
      bubbles: true,
      cancelable: true,
    });
    (target || document.body).dispatchEvent(e);
    return e;
  }

  beforeEach(() => {
    document.getElementById("call-panel").style.display = "flex";
    global.localStream = stream([track("audio")]);
  });

  test("ignores keys while the panel is closed", () => {
    document.getElementById("call-panel").style.display = "none";
    press("m");
    expect(audioMuted).toBe(false);
  });

  test("M toggles the microphone", () => {
    const e = press("m");
    expect(audioMuted).toBe(true);
    expect(e.defaultPrevented).toBe(true);
  });

  test("V cycles the layout", () => {
    press("v");
    expect(callLayout).toBe("grid");
  });

  test("Escape minimizes and restores", () => {
    press("Escape");
    expect(callMinimized).toBe(true);
    press("Escape");
    expect(callMinimized).toBe(false);
  });

  test("only Escape works while minimized", () => {
    toggleCallMinimized(true);
    press("m");
    expect(audioMuted).toBe(false);
    press("Escape");
    expect(callMinimized).toBe(false);
  });

  test("ignores unbound keys", () => {
    const e = press("q");
    expect(e.defaultPrevented).toBe(false);
  });

  test("ignores modified keys", () => {
    const e = new KeyboardEvent("keydown", {
      key: "m",
      ctrlKey: true,
      bubbles: true,
      cancelable: true,
    });
    document.body.dispatchEvent(e);
    expect(audioMuted).toBe(false);
  });

  test("never steals keys from the invite search box", () => {
    press("m", document.getElementById("call-invite-search"));
    expect(audioMuted).toBe(false);
  });

  test("Escape closes the share viewer first", () => {
    applyScreenShares([{ share_id: "s1", sharer: "bob" }]);
    openShareViewer();
    press("Escape");
    expect(viewShareId).toBeNull();
    expect(callMinimized).toBe(false);
  });
});

describe("pagehide", () => {
  test("ends an active call and share with a beacon", () => {
    global.activeCallId = "c1";
    global.standaloneShareId = "s1";
    globalThis.dispatchEvent(new Event("pagehide"));
    expect(navigator.sendBeacon).toHaveBeenCalledWith("/calls/c1/end");
    expect(navigator.sendBeacon).toHaveBeenCalledWith("/screenshare/s1/stop");
  });

  test("sends nothing when there is nothing to end", () => {
    globalThis.dispatchEvent(new Event("pagehide"));
    expect(navigator.sendBeacon).not.toHaveBeenCalled();
  });
});

// ── Call timer ────────────────────────────────────────────────────────────────

describe("call timer", () => {
  test("counts up in minutes and seconds", () => {
    jest.useFakeTimers();
    try {
      _startCallTimer();
      jest.advanceTimersByTime(65000);
      expect(document.getElementById("call-timer").textContent).toBe("1:05");
      _stopCallTimer();
      expect(callTimerInterval).toBeNull();
    } finally {
      jest.useRealTimers();
    }
  });
});
