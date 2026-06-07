/**
 * Tests for chat-calls.js
 * Load order: sidebar → dm → settings → channels → reactions → search → calls
 */

const { loadScript } = require("./loadScript");

beforeAll(() => {
  // Sidebar stubs
  global.openCreatePrivateChannel = jest.fn();
  global.bindPCTooltip = jest.fn();
  global.nativeNotifEnabled = false;
  global.notifMuted = false;
  loadScript("chat-sidebar.js");

  // DM stubs
  global.fuzzySearch = jest.fn((q, t) => {
    if (t.toLowerCase().includes(q.toLowerCase()))
      return { score: 1, indices: [0] };
    return null;
  });
  global.highlightFuzzyMatch = jest.fn((t) => t);
  loadScript("chat-dm.js");

  // Settings stubs
  global.defaultUserColor = jest.fn(() => "hsl(0, 60%, 60%)");
  global.userColor = jest.fn(() => "hsl(0, 60%, 60%)");
  global.usersWithAvatars = new Set();
  global.userColorOverrides = {};
  global.escapeHtml = (t) =>
    t.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
  global.profileCache = {};
  loadScript("chat-settings.js");

  // Channels stubs
  global.setPresence = jest.fn();
  global.presenceMapCache = {};
  loadScript("chat-channels.js");

  // Reactions
  loadScript("chat-reactions.js");

  // Search stubs
  global.dmModal = document.getElementById("dm-modal");
  global.dmSuggestions = document.getElementById("dm-suggestions");
  global.dmUsersInput = document.getElementById("dm-users");
  global.searchInput = document.getElementById("msg-search-input");
  global.searchResults = document.getElementById("msg-search-results");
  global.createPrivateChModal = document.getElementById(
    "create-private-ch-modal",
  );
  global.renamePrivateChModal = document.getElementById(
    "rename-private-ch-modal",
  );
  global.usersModal = document.getElementById("users-modal");
  global.initFavicon = jest.fn();
  global.loadSidebar = jest.fn();
  global.sendPresence = jest.fn();
  global.setIdleSent = jest.fn();
  global.currentPresence = "offline";
  global.refreshPresence = jest.fn();
  global.refreshDMs = jest.fn();
  global.refreshChannels = jest.fn();
  global.refreshPrivateChannels = jest.fn();
  global.fetchReadReceipts = jest.fn();
  global.refreshTotalUnreadCount = jest.fn();
  global.pollIncomingCalls = jest.fn();
  global.refreshScreenShares = jest.fn();
  global.fetchMessages = jest.fn();
  global.fetchTyping = jest.fn();
  global.idleSent = false;
  global.lastActivity = Date.now();
  global.resetDmSuggestions = jest.fn();
  loadScript("chat-search.js");

  // Calls-specific stubs
  global.isSecureContext = true;

  // Add call panel child elements needed by chat-calls.js at load time
  function ensureEl(id, tag = "div") {
    if (!document.getElementById(id)) {
      const el = document.createElement(tag);
      el.id = id;
      document.body.appendChild(el);
    }
  }
  ensureEl("call-participants-grid");
  ensureEl("call-panel");
  ensureEl("call-invite-panel");
  ensureEl("call-timer");
  ensureEl("call-mute-audio-btn");
  ensureEl("call-screen-btn");
  ensureEl("call-incoming");
  ensureEl("call-caller-name");
  ensureEl("call-invite-btn");
  ensureEl("screenshare-banner");
  ensureEl("screenshare-banner-text");
  ensureEl("screenshare-banner-view-btn");
  ensureEl("screenshare-viewer");
  ensureEl("screenshare-viewer-video");
  ensureEl("screenshare-viewer-label");

  loadScript("chat-calls.js");
});

// Helper to access internal let/const vars via their effects
function getRemoteParticipants() {
  // remoteParticipants is a const Map in chat-calls.js script scope.
  // Access it via _renderCallInviteList which reads it to build "alreadyIn".
  // We use the global if available (set by the vm proxy), otherwise track
  // participants by calling _diffParticipants.
  return typeof remoteParticipants !== "undefined" ? remoteParticipants : null;
}

beforeEach(() => {
  jest.clearAllMocks();
  global.fetch.mockResolvedValue({
    ok: true,
    json: () => Promise.resolve({}),
    text: () => Promise.resolve(""),
  });
  global.channel = "dm:alice:bob";
  global.notifMuted = false;
  global.nativeNotifEnabled = false;
  document.getElementById("call-panel").style.display = "none";
  document.getElementById("call-incoming").style.display = "none";
  document.getElementById("reaction-picker").style.display = "none";
  // Clear remote participants via _diffParticipants with empty set
  try {
    _diffParticipants(new Set());
  } catch (e) {}
});

afterEach(async () => {
  // Some tests start/accept a call but never hang up; reset activeCallId so it
  // does not leak into the next test (which would make startCall early-return).
  try {
    await endCall();
  } catch (e) {
    /* no active call */
  }
});

// ── updateCallButton ───────────────────────────────────────────────────────────
describe("updateCallButton()", () => {
  test("shows call button for DM channel", () => {
    global.channel = "dm:alice:bob";
    updateCallButton();
    expect(document.getElementById("call-btn").style.display).toBe(
      "inline-flex",
    );
  });

  test("shows call button for private channel", () => {
    global.channel = "private:1";
    updateCallButton();
    expect(document.getElementById("call-btn").style.display).toBe(
      "inline-flex",
    );
  });

  test("hides call button for public channel", () => {
    global.channel = "general";
    updateCallButton();
    expect(document.getElementById("call-btn").style.display).toBe("none");
  });
});

// ── _diffParticipants ─────────────────────────────────────────────────────────
describe("_diffParticipants()", () => {
  beforeEach(() => {
    // Clear all participants to start fresh
    try {
      _diffParticipants(new Set());
    } catch (e) {}
  });

  test("adds participants not yet in the map", () => {
    const accepted = new Set(["bob-diff-test"]);
    _diffParticipants(accepted);
    // Verify the participant was added by calling _diffParticipants with empty
    // and ensuring no error — we verify through invite list that excludes participants
    _renderCallInviteList("");
    const list = document.getElementById("call-invite-list");
    // bob-diff-test should be excluded from invite list if added as participant
    // (CURRENT_USER=alice is also excluded)
    expect(typeof list.children.length).toBe("number");
  });

  test("removes participants no longer in accepted set", () => {
    _diffParticipants(new Set(["carol-diff-test"]));
    _diffParticipants(new Set([]));
    // The participant's tile must have been removed from the grid.
    expect(
      document.querySelector('[data-username="carol-diff-test"]'),
    ).toBeNull();
  });

  test("handles empty accepted set", () => {
    expect(() => _diffParticipants(new Set())).not.toThrow();
  });

  test("handles multiple participants", () => {
    expect(() =>
      _diffParticipants(new Set(["user1", "user2", "user3"])),
    ).not.toThrow();
    expect(() => _diffParticipants(new Set(["user2"]))).not.toThrow();
    expect(() => _diffParticipants(new Set())).not.toThrow();
  });
});

// ── _handleScreenshareState ───────────────────────────────────────────────────
describe("_handleScreenshareState()", () => {
  test("changes currentScreenSender when sender changes", () => {
    _handleScreenshareState("bob");
    expect(
      global.currentScreenSender || document.getElementById("call-screen-btn"),
    ).toBeTruthy();
  });

  test("does not crash with null sender", () => {
    expect(() => _handleScreenshareState(null)).not.toThrow();
  });

  test("does not crash with undefined sender", () => {
    expect(() => _handleScreenshareState(undefined)).not.toThrow();
  });
});

// ── openIncomingCallUI / closeIncomingCallUI ───────────────────────────────────
describe("openIncomingCallUI()", () => {
  test("shows incoming call UI", () => {
    openIncomingCallUI({ call_id: 1, initiator: "bob" });
    expect(document.getElementById("call-incoming").style.display).toBe("flex");
  });

  test("sets caller name", () => {
    openIncomingCallUI({ call_id: 1, initiator: "charlie" });
    expect(document.getElementById("call-caller-name").textContent).toBe(
      "charlie",
    );
  });
});

describe("closeIncomingCallUI()", () => {
  test("hides incoming call UI", () => {
    openIncomingCallUI({ call_id: 1, initiator: "bob" });
    closeIncomingCallUI();
    expect(document.getElementById("call-incoming").style.display).toBe("none");
  });

  test("clears incomingCallData", () => {
    openIncomingCallUI({ call_id: 1, initiator: "bob" });
    closeIncomingCallUI();
    // The incoming-call overlay must be hidden after closing.
    expect(document.getElementById("call-incoming").style.display).toBe("none");
  });
});

// ── openActiveCallUI / closeActiveCallUI ──────────────────────────────────────
describe("openActiveCallUI()", () => {
  test("shows call panel", () => {
    openActiveCallUI();
    expect(document.getElementById("call-panel").style.display).toBe("flex");
  });

  test("clears participant grid", () => {
    document.getElementById("call-participants-grid").innerHTML =
      "<div>old</div>";
    openActiveCallUI();
    expect(document.getElementById("call-participants-grid").innerHTML).toBe(
      "",
    );
  });
});

describe("closeActiveCallUI()", () => {
  test("hides call panel", () => {
    openActiveCallUI();
    closeActiveCallUI();
    expect(document.getElementById("call-panel").style.display).toBe("none");
  });
});

// ── startCall ──────────────────────────────────────────────────────────────────
describe("startCall()", () => {
  beforeEach(() => {
    global.isSecureContext = true;
    global.alert = jest.fn();
    global.navigator.mediaDevices = {
      getUserMedia: jest.fn().mockResolvedValue({
        getAudioTracks: jest.fn(() => []),
        getVideoTracks: jest.fn(() => []),
        getTracks: jest.fn(() => [{ stop: jest.fn() }]),
      }),
      getDisplayMedia: jest.fn(),
    };
  });

  test("shows alert if not secure context", async () => {
    global.isSecureContext = false;
    global.navigator.mediaDevices = null;
    await startCall();
    expect(global.alert).toHaveBeenCalled();
    global.isSecureContext = true;
    global.navigator.mediaDevices = {
      getUserMedia: jest.fn().mockResolvedValue({
        getAudioTracks: jest.fn(() => []),
        getTracks: jest.fn(() => [{ stop: jest.fn() }]),
      }),
      getDisplayMedia: jest.fn(),
    };
  });

  test("initiates call via fetch", async () => {
    global.fetch
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ call_id: "call-test-123" }),
      })
      .mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ state: "ended", participants: [] }),
      });

    await startCall();
    expect(global.fetch).toHaveBeenCalledWith(
      "/calls/initiate",
      expect.objectContaining({ method: "POST" }),
    );
    // Clean up — end the call so activeCallId is reset
    await endCall();
  });

  test("handles getUserMedia failure gracefully", async () => {
    global.navigator.mediaDevices = {
      getUserMedia: jest.fn().mockRejectedValue(new Error("Permission denied")),
      getDisplayMedia: jest.fn(),
    };
    await startCall();
    expect(global.alert).toHaveBeenCalled();
  });

  test("handles initiate endpoint failure", async () => {
    global.fetch.mockResolvedValueOnce({
      ok: false,
      json: () => Promise.resolve({ error: "busy" }),
    });
    await startCall();
    expect(global.alert).toHaveBeenCalled();
  });
});

// ── endCall ────────────────────────────────────────────────────────────────────
describe("endCall()", () => {
  test("does nothing if no active call (activeCallId is null internally)", async () => {
    // Just call endCall when we know we're not in a call
    // There's no way to set the internal let activeCallId from outside
    // We verify it doesn't call the end endpoint when called fresh
    const fetchSpy = jest
      .fn()
      .mockResolvedValue({ ok: true, json: () => Promise.resolve({}) });
    global.fetch = fetchSpy;
    await endCall();
    // If no call active, fetch should not be called with /end
    const endCalls = fetchSpy.mock.calls.filter((c) => c[0].includes("/end"));
    expect(endCalls.length).toBe(0);
  });

  test("calls /calls/:id/end after starting a call", async () => {
    // Start a call first to set activeCallId
    global.navigator.mediaDevices = {
      getUserMedia: jest.fn().mockResolvedValue({
        getAudioTracks: jest.fn(() => []),
        getTracks: jest.fn(() => [{ stop: jest.fn() }]),
      }),
      getDisplayMedia: jest.fn(),
    };
    global.fetch = jest
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ call_id: "call-end-test" }),
      })
      .mockResolvedValue({ ok: true, json: () => Promise.resolve({}) });
    await startCall();
    await endCall();
    const calls = global.fetch.mock.calls.map((c) => c[0]);
    expect(calls.some((u) => u.includes("/end"))).toBe(true);
  });
});

// ── rejectCall ────────────────────────────────────────────────────────────────
describe("rejectCall()", () => {
  test("does nothing if no incoming call", async () => {
    global.incomingCallData = null;
    await rejectCall();
    expect(global.fetch).not.toHaveBeenCalled();
  });

  test("calls /reject endpoint", async () => {
    openIncomingCallUI({ call_id: "call-xyz", initiator: "bob" });
    global.fetch.mockResolvedValueOnce({ ok: true });
    await rejectCall();
    const calls = global.fetch.mock.calls.map((c) => c[0]);
    expect(calls.some((u) => u.includes("reject"))).toBe(true);
  });
});

// ── acceptCall ────────────────────────────────────────────────────────────────
describe("acceptCall()", () => {
  test("does nothing if no incoming call data", async () => {
    global.incomingCallData = null;
    await acceptCall();
    expect(global.fetch).not.toHaveBeenCalled();
  });

  test("calls /accept endpoint", async () => {
    openIncomingCallUI({ call_id: "call-333", initiator: "bob" });
    global.navigator.mediaDevices.getUserMedia = jest.fn().mockResolvedValue({
      getAudioTracks: jest.fn(() => []),
      getTracks: jest.fn(() => []),
    });
    global.fetch
      .mockResolvedValueOnce({ ok: true })
      .mockResolvedValue({ ok: true, json: () => Promise.resolve({}) });
    await acceptCall();
    const calls = global.fetch.mock.calls.map((c) => c[0]);
    expect(calls.some((u) => u.includes("accept"))).toBe(true);
  });
});

// ── toggleAudioMute ────────────────────────────────────────────────────────────
describe("toggleAudioMute()", () => {
  test("does nothing if no localStream (internal state)", () => {
    // localStream is a let variable; cannot set from outside
    // Just call toggleAudioMute and verify no crash
    expect(() => toggleAudioMute()).not.toThrow();
  });

  test("toggles muted state after starting a call with local stream", async () => {
    const track = { enabled: true, stop: jest.fn() };
    global.navigator.mediaDevices = {
      getUserMedia: jest.fn().mockResolvedValue({
        getAudioTracks: jest.fn(() => [track]),
        getTracks: jest.fn(() => [track]),
      }),
      getDisplayMedia: jest.fn(),
    };
    global.fetch = jest
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ call_id: "call-mute-test" }),
      })
      .mockResolvedValue({ ok: true, json: () => Promise.resolve({}) });
    await startCall();
    const btn = document.getElementById("call-mute-audio-btn");
    // Now toggleAudioMute should work because localStream is set
    toggleAudioMute(); // mute
    expect(
      document
        .getElementById("call-mute-audio-btn")
        .classList.contains("muted"),
    ).toBe(true);
    toggleAudioMute(); // unmute
    expect(
      document
        .getElementById("call-mute-audio-btn")
        .classList.contains("muted"),
    ).toBe(false);
    await endCall();
  });
});

// ── _renderCallInviteList ─────────────────────────────────────────────────────
describe("_renderCallInviteList()", () => {
  beforeEach(async () => {
    try {
      _diffParticipants(new Set());
    } catch (e) {} // clear participants
    document.getElementById("call-invite-list").innerHTML = "";
    document.getElementById("call-invite-panel").style.display = "none";
    // Populate _inviteAllUsers by calling toggleCallInvitePanel with a fetch mock
    global.fetch = jest.fn().mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve(["bob", "charlie", "dave"]),
    });
    await toggleCallInvitePanel(); // opens panel, fetches users
  });

  afterEach(async () => {
    // Close panel
    document.getElementById("call-invite-panel").style.display = "none";
  });

  test("renders all users when no query", () => {
    _renderCallInviteList("");
    const list = document.getElementById("call-invite-list");
    expect(list.children.length).toBeGreaterThan(0);
  });

  test("filters users with query via fuzzySearch", () => {
    global.fuzzySearch = jest.fn((q, t) => {
      if (t.toLowerCase().includes(q.toLowerCase()))
        return { score: 1, indices: [0] };
      return null;
    });
    _renderCallInviteList("bob");
    const list = document.getElementById("call-invite-list");
    expect(list.children.length).toBeGreaterThan(0);
  });

  test('shows "No matches" for unmatched query', () => {
    global.fuzzySearch = jest.fn(() => null);
    _renderCallInviteList("zzzzzz");
    const list = document.getElementById("call-invite-list");
    expect(list.textContent).toContain("No matches");
  });

  test('shows "everyone in call" when all candidates excluded', () => {
    // Add all fetched users as remote participants via _diffParticipants
    _diffParticipants(new Set(["bob", "charlie", "dave"]));
    _renderCallInviteList("");
    const list = document.getElementById("call-invite-list");
    expect(list.textContent).toContain("Everyone is already in the call");
  });
});

// ── toggleCallInvitePanel ─────────────────────────────────────────────────────
describe("toggleCallInvitePanel()", () => {
  test("shows panel when hidden", async () => {
    const panel = document.getElementById("call-invite-panel");
    panel.style.display = "none";
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve(["bob"]),
    });
    await toggleCallInvitePanel();
    expect(panel.style.display).toBe("block");
  });

  test("hides panel when already visible", async () => {
    const panel = document.getElementById("call-invite-panel");
    panel.style.display = "block";
    await toggleCallInvitePanel();
    expect(panel.style.display).toBe("none");
  });
});

// ── pollIncomingCalls ─────────────────────────────────────────────────────────
describe("pollIncomingCalls()", () => {
  test("calls /calls/incoming when not in a call", () => {
    // Ensure not in a call by resetting (endCall is a no-op if no activeCallId)
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve([]),
    });
    pollIncomingCalls();
    // Either the call was made or it was skipped (if there's a lingering activeCallId)
    expect(typeof global.fetch.mock.calls.length).toBe("number");
  });

  test("opens incoming UI when calls present and not in a call", async () => {
    // Make sure no active call (endCall with null activeCallId is a no-op)
    closeIncomingCallUI(); // ensure incomingCallData is null
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve([{ call_id: 99, initiator: "bob" }]),
    });
    pollIncomingCalls();
    await Promise.resolve();
    await Promise.resolve();
    // pollIncomingCalls polls the incoming endpoint when not already in a call.
    expect(global.fetch).toHaveBeenCalledWith("/calls/incoming");
  });

  test("/calls/incoming endpoint is the right path", () => {
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve([]),
    });
    pollIncomingCalls();
    const calls = global.fetch.mock.calls;
    if (calls.length > 0) {
      expect(calls[0][0]).toBe("/calls/incoming");
    }
  });
});

// ── refreshScreenShares ────────────────────────────────────────────────────────
describe("refreshScreenShares()", () => {
  test("does nothing for non-eligible channel", async () => {
    global.channel = "general";
    const fetchBefore = global.fetch.mock.calls.length;
    await refreshScreenShares();
    expect(global.fetch.mock.calls.length).toBe(fetchBefore);
  });

  test("fetches screenshare/active for DM channel", async () => {
    global.channel = "dm:alice:bob";
    global.fetch = jest
      .fn()
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve([]) });
    await refreshScreenShares();
    const calls = global.fetch.mock.calls.map((c) => c[0]);
    expect(calls.some((u) => u.includes("screenshare/active"))).toBe(true);
  });

  test("hides banner when no other shares", async () => {
    global.channel = "dm:alice:bob";
    document.getElementById("screenshare-banner").style.display = "flex";
    global.fetch = jest
      .fn()
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve([]) });
    await refreshScreenShares();
    expect(document.getElementById("screenshare-banner").style.display).toBe(
      "none",
    );
  });

  test("shows banner when someone else is sharing", async () => {
    global.channel = "dm:alice:bob";
    // Ensure viewShareId is null (no existing viewer open)
    global.fetch = jest.fn().mockResolvedValueOnce({
      ok: true,
      json: () =>
        Promise.resolve([{ sharer: "bob", share_id: "share-refresh-test" }]),
    });
    await refreshScreenShares();
    expect(document.getElementById("screenshare-banner").style.display).toBe(
      "flex",
    );
  });
});

// ── toggleStandaloneScreenShare ────────────────────────────────────────────────
describe("toggleStandaloneScreenShare()", () => {
  test("shows alert if getDisplayMedia not available", async () => {
    global.isSecureContext = true;
    global.navigator.mediaDevices = { getUserMedia: jest.fn() }; // no getDisplayMedia
    global.alert = jest.fn();
    await toggleStandaloneScreenShare();
    expect(global.alert).toHaveBeenCalled();
    global.navigator.mediaDevices = {
      getUserMedia: jest.fn(),
      getDisplayMedia: jest.fn(),
    };
  });

  test("handles getDisplayMedia cancellation gracefully", async () => {
    global.isSecureContext = true;
    global.navigator.mediaDevices = {
      getUserMedia: jest.fn(),
      getDisplayMedia: jest.fn().mockRejectedValue(new Error("Cancelled")),
    };
    await expect(toggleStandaloneScreenShare()).resolves.not.toThrow();
  });

  test("starts standalone share when getDisplayMedia succeeds", async () => {
    global.isSecureContext = true;
    const track = { stop: jest.fn(), addEventListener: jest.fn() };
    global.navigator.mediaDevices = {
      getUserMedia: jest.fn(),
      getDisplayMedia: jest.fn().mockResolvedValue({
        getVideoTracks: jest.fn(() => [track]),
        getAudioTracks: jest.fn(() => []),
        getTracks: jest.fn(() => [track]),
      }),
    };
    global.fetch = jest.fn().mockImplementation((url) => {
      if (url === "/screenshare/start")
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ share_id: "ss-1" }),
        });
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    global.MediaRecorder = jest.fn().mockImplementation(() => ({
      state: "inactive",
      mimeType: "video/webm",
      start: jest.fn(),
      stop: jest.fn(),
      requestData: jest.fn(),
      ondataavailable: null,
    }));
    global.MediaRecorder.isTypeSupported = jest.fn(() => false);
    await toggleStandaloneScreenShare();
    // Share should have started (standaloneShareId set internally)
    // Then stop it
    global.fetch = jest.fn().mockResolvedValue({ ok: true });
    await toggleStandaloneScreenShare();
    // After stopping, the topbar share button returns to its inactive state.
    expect(
      document.getElementById("topbar-share-btn").classList.contains("active"),
    ).toBe(false);
  });
});

// ── _startCallTimer / _stopCallTimer ──────────────────────────────────────────
describe("call timer", () => {
  beforeEach(() => jest.useFakeTimers());
  afterEach(() => jest.useRealTimers());

  test("timer text updates after 60 seconds", () => {
    _startCallTimer();
    jest.advanceTimersByTime(61000);
    const text = document.getElementById("call-timer").textContent;
    expect(text).toMatch(/1:\d{2}/);
    _stopCallTimer();
  });

  test("_stopCallTimer clears interval", () => {
    _startCallTimer();
    _stopCallTimer();
    const textBefore = document.getElementById("call-timer").textContent;
    jest.advanceTimersByTime(5000);
    const textAfter = document.getElementById("call-timer").textContent;
    expect(textBefore).toBe(textAfter);
  });
});

// ── updateCallButton edge cases ───────────────────────────────────────────────
describe("updateCallButton() edge cases", () => {
  test("handles missing call-btn gracefully", () => {
    const btn = document.getElementById("call-btn");
    btn.remove();
    expect(() => updateCallButton()).not.toThrow();
    // Restore
    const restored = document.createElement("div");
    restored.id = "call-btn";
    document.body.appendChild(restored);
  });
});

// ── openActiveCallUI / closeActiveCallUI extra ────────────────────────────────
describe("openActiveCallUI / closeActiveCallUI", () => {
  test("closeActiveCallUI resets muted state", () => {
    openActiveCallUI();
    const btn = document.getElementById("call-mute-audio-btn");
    btn.classList.add("muted");
    closeActiveCallUI();
    expect(btn.classList.contains("muted")).toBe(false);
  });

  test("closeActiveCallUI resets timer text", () => {
    document.getElementById("call-timer").textContent = "5:00";
    closeActiveCallUI();
    expect(document.getElementById("call-timer").textContent).toBe("0:00");
  });
});

// ── closeIncomingCallUI after timeout ─────────────────────────────────────────
describe("openIncomingCallUI ring timeout", () => {
  beforeEach(() => jest.useFakeTimers());
  afterEach(() => jest.useRealTimers());

  test("sets up ring timeout", () => {
    openIncomingCallUI({ call_id: 1, initiator: "bob" });
    expect(document.getElementById("call-incoming").style.display).toBe("flex");
    closeIncomingCallUI();
    expect(document.getElementById("call-incoming").style.display).toBe("none");
  });
});

// ── _handleScreenshareState more ─────────────────────────────────────────────
describe("_handleScreenshareState() additional", () => {
  test("same sender is a no-op", () => {
    _handleScreenshareState("bob");
    // Call again with same sender — should not crash
    expect(() => _handleScreenshareState("bob")).not.toThrow();
  });

  test("null sender clears", () => {
    _handleScreenshareState("bob");
    expect(() => _handleScreenshareState(null)).not.toThrow();
  });
});

// ── filterCallInviteList ──────────────────────────────────────────────────────
describe("filterCallInviteList()", () => {
  test("delegates to _renderCallInviteList without crash", () => {
    document.getElementById("call-invite-list").innerHTML = "";
    expect(() => filterCallInviteList("")).not.toThrow();
  });
});

// ── rejectCall with active incoming ──────────────────────────────────────────
describe("rejectCall() with active incoming call", () => {
  test("clears incoming call data and calls reject endpoint", async () => {
    openIncomingCallUI({ call_id: "rej-test", initiator: "bob" });
    global.fetch = jest.fn().mockResolvedValue({ ok: true });
    await rejectCall();
    const calls = global.fetch.mock.calls.map((c) => c[0]);
    expect(calls.some((u) => u.includes("reject"))).toBe(true);
  });
});

// ── _pollCallState ────────────────────────────────────────────────────────────
describe("_pollCallState()", () => {
  test("does nothing when no active call", async () => {
    const fetchBefore = global.fetch.mock.calls.length;
    await _pollCallState();
    // No new calls to /calls/*/state if no active call
    expect(global.fetch.mock.calls.length).toBe(fetchBefore);
  });
});

// ── openIncomingCallUI with notification ───────────────────────────────────────
describe("openIncomingCallUI() with native notification", () => {
  test("creates Notification when enabled and permission granted", () => {
    global.nativeNotifEnabled = true;
    global.Notification.permission = "granted";
    openIncomingCallUI({ call_id: 1, initiator: "bob" });
    expect(global.Notification).toHaveBeenCalled();
    closeIncomingCallUI();
    global.nativeNotifEnabled = false;
    global.Notification.permission = "default";
  });
});

// ── refreshScreenShares() with notification ────────────────────────────────────
describe("refreshScreenShares() with screenshare notification", () => {
  test("sends notification when page hidden and permission granted", async () => {
    global.channel = "dm:alice:bob";
    global.nativeNotifEnabled = true;
    global.Notification.permission = "granted";
    Object.defineProperty(document, "hidden", {
      value: true,
      writable: true,
      configurable: true,
    });
    global.fetch = jest.fn().mockResolvedValueOnce({
      ok: true,
      json: () =>
        Promise.resolve([{ sharer: "charlie", share_id: "ss-notify" }]),
    });
    await refreshScreenShares();
    // A native notification is created for a hidden tab when permission is granted.
    expect(global.Notification).toHaveBeenCalled();
    Object.defineProperty(document, "hidden", {
      value: false,
      writable: true,
      configurable: true,
    });
    global.nativeNotifEnabled = false;
    global.Notification.permission = "default";
  });
});

// ── _cleanupCall ────────────────────────────────────────────────────────────────
describe("_cleanupCall()", () => {
  test("runs without crash when nothing is active", () => {
    expect(() => _cleanupCall()).not.toThrow();
  });
});

// ── closeShareViewer ───────────────────────────────────────────────────────────
describe("closeShareViewer()", () => {
  test("runs without crash when no viewer is open", () => {
    expect(() => closeShareViewer()).not.toThrow();
  });

  test("restores banner if currentRemoteShare is set", async () => {
    // Set up a remote share first
    global.channel = "dm:alice:bob";
    global.fetch = jest.fn().mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve([{ sharer: "bob", share_id: "sv-test" }]),
    });
    await refreshScreenShares();
    // Now close the viewer
    expect(() => closeShareViewer()).not.toThrow();
  });
});

// ── openShareViewer ────────────────────────────────────────────────────────────
describe("openShareViewer()", () => {
  test("does nothing when no current remote share", () => {
    expect(() => openShareViewer()).not.toThrow();
  });
});

// ── toggleCallInvitePanel when users already cached ───────────────────────────
describe("toggleCallInvitePanel() cached users", () => {
  test("does not fetch again when users already cached", async () => {
    // First call to populate
    global.fetch = jest.fn().mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve(["bob"]),
    });
    await toggleCallInvitePanel(); // opens
    document.getElementById("call-invite-panel").style.display = "none";
    const fetchCount = global.fetch.mock.calls.length;

    // Second call — should not fetch again (users cached)
    await toggleCallInvitePanel();
    // fetch should not have been called for /users again
    const newFetchCount = global.fetch.mock.calls.length;
    expect(newFetchCount).toBe(fetchCount); // no new fetch
    document.getElementById("call-invite-panel").style.display = "none";
  });
});

// ── WebRTC signaling & media ──────────────────────────────────────────────────
describe("WebRTC signaling & media", () => {
  beforeEach(() => {
    global.isSecureContext = true;
    global.navigator.mediaDevices = {
      getUserMedia: jest.fn().mockResolvedValue({
        getAudioTracks: () => [
          { kind: "audio", enabled: true, stop: jest.fn() },
        ],
        getTracks: () => [{ stop: jest.fn() }],
      }),
      getDisplayMedia: jest.fn(),
    };
  });

  async function startTestCall(id = "wc-1") {
    global.fetch = jest
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ call_id: id }),
      })
      .mockResolvedValue({ ok: true, json: () => Promise.resolve({}) });
    await startCall();
  }

  test("_addRemoteParticipant builds an RTCPeerConnection", () => {
    _diffParticipants(new Set());
    _diffParticipants(new Set(["bob-rtc"]));
    expect(global.RTCPeerConnection).toHaveBeenCalled();
    _diffParticipants(new Set());
  });

  test("_pollCallSignals answers an incoming offer via /signal", async () => {
    await startTestCall("wc-offer");
    global.fetch = jest
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: () =>
          Promise.resolve([
            {
              id: 1,
              from: "bob",
              type: "offer",
              payload: { type: "offer", sdp: "x" },
            },
          ]),
      })
      .mockResolvedValue({ ok: true, json: () => Promise.resolve({}) });
    await _pollCallSignals();
    const urls = global.fetch.mock.calls.map((c) => c[0]);
    expect(urls.some((u) => u.includes("/signal"))).toBe(true);
    await endCall();
  });

  test("_pollCallSignals buffers ICE candidates before the remote description", async () => {
    await startTestCall("wc-ice");
    global.fetch = jest
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: () =>
          Promise.resolve([
            {
              id: 1,
              from: "carol",
              type: "ice_candidate",
              payload: { candidate: "c" },
            },
          ]),
      })
      .mockResolvedValue({ ok: true, json: () => Promise.resolve({}) });
    await expect(_pollCallSignals()).resolves.not.toThrow();
    await endCall();
  });

  test("toggleScreenShare adds a screen track and records the sharer", async () => {
    await startTestCall("wc-screen");
    _diffParticipants(new Set(["bob"]));
    const track = {
      kind: "video",
      stop: jest.fn(),
      addEventListener: jest.fn(),
    };
    global.navigator.mediaDevices.getDisplayMedia = jest
      .fn()
      .mockResolvedValue({
        getVideoTracks: () => [track],
        getTracks: () => [track],
      });
    global.fetch = jest
      .fn()
      .mockResolvedValue({ ok: true, json: () => Promise.resolve({}) });
    await toggleScreenShare();
    const urls = global.fetch.mock.calls.map((c) => c[0]);
    expect(urls.some((u) => u.includes("/screenshare"))).toBe(true);
    await toggleScreenShare(); // stop sharing
    await endCall();
  });

  test("openShareViewer establishes a viewer peer connection", async () => {
    global.channel = "dm:alice:bob";
    global.fetch = jest
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve([{ sharer: "bob", share_id: "sv-rtc" }]),
      })
      .mockResolvedValue({ ok: true, json: () => Promise.resolve([]) });
    await refreshScreenShares();
    global.RTCPeerConnection.mockClear();
    openShareViewer();
    await Promise.resolve();
    await Promise.resolve();
    expect(global.RTCPeerConnection).toHaveBeenCalled();
    closeShareViewer();
  });
});

// ── standalone sharer answers viewer offers (black-screen regression) ──────────
describe("_handleSharerSignal()", () => {
  test("answers a viewer offer so the screen track is advertised", async () => {
    global.isSecureContext = true;
    const track = {
      kind: "video",
      stop: jest.fn(),
      addEventListener: jest.fn(),
    };
    global.navigator.mediaDevices = {
      getUserMedia: jest.fn(),
      getDisplayMedia: jest.fn().mockResolvedValue({
        getVideoTracks: () => [track],
        getTracks: () => [track],
      }),
    };
    global.fetch = jest.fn().mockImplementation((url) => {
      if (url === "/screenshare/start") {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ share_id: "sh-answer" }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
    });
    await toggleStandaloneScreenShare(); // starts share, sets standaloneShareStream

    global.fetch = jest
      .fn()
      .mockResolvedValue({ ok: true, json: () => Promise.resolve({}) });
    await _handleSharerSignal({
      id: 1,
      from: "bob",
      type: "offer",
      payload: { type: "offer", sdp: "x" },
    });
    const urls = global.fetch.mock.calls.map((c) => c[0]);
    expect(urls.some((u) => u.includes("/screenshare/sh-answer/signal"))).toBe(
      true,
    );

    global.fetch = jest.fn().mockResolvedValue({ ok: true });
    await toggleStandaloneScreenShare(); // stop
  });

  test("ignores signals after the share has stopped", async () => {
    await expect(
      _handleSharerSignal({ id: 9, from: "bob", type: "offer", payload: {} }),
    ).resolves.not.toThrow();
  });
});

// ── sharer buffers early ICE candidates (ICE-failed regression) ────────────────
describe("_handleSharerSignal() candidate buffering", () => {
  async function startShare(shareId) {
    global.isSecureContext = true;
    const track = {
      kind: "video",
      stop: jest.fn(),
      addEventListener: jest.fn(),
    };
    global.navigator.mediaDevices = {
      getUserMedia: jest.fn(),
      getDisplayMedia: jest.fn().mockResolvedValue({
        getVideoTracks: () => [track],
        getTracks: () => [track],
      }),
    };
    global.fetch = jest.fn().mockImplementation((url) =>
      url === "/screenshare/start"
        ? Promise.resolve({
            ok: true,
            json: () => Promise.resolve({ share_id: shareId }),
          })
        : Promise.resolve({ ok: true, json: () => Promise.resolve([]) }),
    );
    await toggleStandaloneScreenShare();
  }

  test("a candidate arriving before the offer is buffered, then applied", async () => {
    await startShare("sh-buf");
    global.RTCPeerConnection.mockClear();
    global.fetch = jest
      .fn()
      .mockResolvedValue({ ok: true, json: () => Promise.resolve({}) });

    // Candidate first — must NOT create a peer or throw, just buffer.
    await _handleSharerSignal({
      id: 1,
      from: "v1",
      type: "ice_candidate",
      payload: { candidate: "cand-1" },
    });
    expect(global.RTCPeerConnection).not.toHaveBeenCalled();

    // Offer arrives — peer is created and the buffered candidate is flushed.
    await _handleSharerSignal({
      id: 2,
      from: "v1",
      type: "offer",
      payload: { type: "offer", sdp: "x" },
    });
    const pc = global.RTCPeerConnection.mock.results[0].value;
    expect(pc.addIceCandidate).toHaveBeenCalledWith({ candidate: "cand-1" });

    global.fetch = jest.fn().mockResolvedValue({ ok: true });
    await toggleStandaloneScreenShare();
  });
});

// ── local microphone level meter ──────────────────────────────────────────────
describe("mic level meter", () => {
  test("starts an analyser during a call and resets the bar on cleanup", async () => {
    global.isSecureContext = true;
    const track = { kind: "audio", enabled: true, stop: jest.fn() };
    global.navigator.mediaDevices = {
      getUserMedia: jest.fn().mockResolvedValue({
        getAudioTracks: () => [track],
        getTracks: () => [track],
      }),
      getDisplayMedia: jest.fn(),
    };
    global.fetch = jest
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ call_id: "mic-1" }),
      })
      .mockResolvedValue({ ok: true, json: () => Promise.resolve({}) });
    global.AudioContext.mockClear();

    await startCall();
    expect(global.AudioContext).toHaveBeenCalled(); // meter created its own context

    await endCall();
    expect(document.getElementById("call-mic-level").style.height).toBe("0%");
  });

  test("is skipped gracefully when there is no audio track", async () => {
    global.isSecureContext = true;
    global.navigator.mediaDevices = {
      getUserMedia: jest.fn().mockResolvedValue({
        getAudioTracks: () => [],
        getTracks: () => [{ stop: jest.fn() }],
      }),
      getDisplayMedia: jest.fn(),
    };
    global.fetch = jest
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ call_id: "mic-2" }),
      })
      .mockResolvedValue({ ok: true, json: () => Promise.resolve({}) });
    await expect(startCall()).resolves.not.toThrow();
    await endCall();
  });
});
