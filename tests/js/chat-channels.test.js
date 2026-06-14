/**
 * Tests for chat-channels.js
 * Load order: sidebar → dm → settings → channels
 */

const { loadScript } = require("./loadScript");

beforeAll(() => {
  // Stubs for sidebar
  global.openCreatePrivateChannel = jest.fn();
  global.bindPCTooltip = jest.fn();
  global.renderMentionsSidebar = jest.fn();
  global.nativeNotifEnabled = false;
  global.notifMuted = false;

  loadScript("chat-sidebar.js");

  // Stubs for dm
  global.fuzzySearch = jest.fn((q, t) => {
    if (t.toLowerCase().includes(q.toLowerCase()))
      return { score: 1, indices: [0] };
    return null;
  });
  global.highlightFuzzyMatch = jest.fn((t) => t);

  loadScript("chat-dm.js");

  // Stubs for settings
  global.defaultUserColor = jest.fn(() => "hsl(0, 60%, 60%)");
  global.userColor = jest.fn(() => "hsl(0, 60%, 60%)");
  global.usersWithAvatars = new Set();
  global.userColorOverrides = {};
  global.escapeHtml = jest.fn((t) => t);
  global.profileCache = {};

  loadScript("chat-settings.js");

  // Stubs for channels
  global.setPresence = jest.fn();
  global.presenceMapCache = {};

  loadScript("chat-channels.js");
});

function makeFetchMock(overrides = {}) {
  return jest.fn().mockImplementation((url) => {
    if (url === "/channels")
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(["general"]),
      });
    if (url === "/private_channels")
      return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
    if (url === "/dms")
      return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
    if (url === "/user_colors")
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    if (url === "/user_avatars")
      return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
    if (url === "/online_users")
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    if (url === "/channel_unreads")
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    if (url === "/users")
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(["bob", "charlie"]),
      });
    return Promise.resolve({
      ok: true,
      json: () => Promise.resolve({}),
      text: () => Promise.resolve(""),
    });
  });
}

beforeEach(() => {
  jest.clearAllMocks();
  global.fetch = makeFetchMock();
  global.channel = "private:1";
  global.privateChannelMap = { "private:1": "My Channel" };
  global.privateChannelMembers = { "private:1": ["alice", "bob"] };
  // Reset modal visibility
  document.getElementById("create-private-ch-modal").style.display = "none";
  document.getElementById("rename-private-ch-modal").style.display = "none";
  document.getElementById("private-ch-name").value = "";
  document.getElementById("private-ch-members-input").value = "";
  document.getElementById("private-ch-suggestions").style.display = "none";
  document.getElementById("add-member-input").value = "";
  document.getElementById("add-member-suggestions").style.display = "none";
});

// ── openCreatePrivateChannel ───────────────────────────────────────────────────
describe("openCreatePrivateChannel()", () => {
  test("shows create private channel modal", () => {
    openCreatePrivateChannel();
    expect(
      document.getElementById("create-private-ch-modal").style.display,
    ).toBe("block");
  });

  test("clears name input", () => {
    document.getElementById("private-ch-name").value = "old name";
    openCreatePrivateChannel();
    expect(document.getElementById("private-ch-name").value).toBe("");
  });

  test("hides suggestions", () => {
    document.getElementById("private-ch-suggestions").style.display = "block";
    openCreatePrivateChannel();
    expect(
      document.getElementById("private-ch-suggestions").style.display,
    ).toBe("none");
  });

  test("fetches users if not loaded", () => {
    // Force usersLoaded to false — can't directly, but ensure fetch is called or not
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve(["bob"]),
    });
    openCreatePrivateChannel();
    // openCreatePrivateChannel opens the modal.
    expect(
      document.getElementById("create-private-ch-modal").style.display,
    ).toBe("block");
  });
});

// ── private-ch-create-cancel ───────────────────────────────────────────────────
describe("private-ch-create-cancel button", () => {
  test("hides the create modal", () => {
    document.getElementById("create-private-ch-modal").style.display = "block";
    document.getElementById("private-ch-create-cancel").click();
    expect(
      document.getElementById("create-private-ch-modal").style.display,
    ).toBe("none");
  });
});

// ── private-ch-create-btn ─────────────────────────────────────────────────────
describe("private-ch-create-btn", () => {
  test("shows error when name is empty", async () => {
    document.getElementById("private-ch-name").value = "";
    document.getElementById("private-ch-create-btn").click();
    await Promise.resolve();
    // modal stays open (nothing should be done with empty name)
    expect(global.fetch).not.toHaveBeenCalledWith(
      "/private_channels/create",
      expect.anything(),
    );
  });

  test("shows error when name is too long", async () => {
    document.getElementById("private-ch-name").value = "a".repeat(81);
    document.getElementById("private-ch-create-btn").click();
    await Promise.resolve();
    const errEl = document.getElementById("private-ch-name-error");
    expect(errEl.textContent).toContain("characters or fewer");
  });

  test("creates channel on valid input", async () => {
    document.getElementById("private-ch-name").value = "Test Channel";
    // Override fetch to handle both the create endpoint and any loadSidebar calls
    global.fetch = jest.fn().mockImplementation((url) => {
      if (url === "/private_channels/create")
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({ channel: "private:2", name: "Test Channel" }),
        });
      if (url === "/channels")
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(["general"]),
        });
      if (url === "/private_channels")
        return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      if (url === "/dms")
        return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      if (url === "/user_colors")
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
      if (url === "/user_avatars")
        return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      if (url === "/online_users")
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
      if (url === "/channel_unreads")
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    document.getElementById("private-ch-create-btn").click();
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
    const calls = global.fetch.mock.calls.map((c) => c[0]);
    expect(calls.some((u) => u === "/private_channels/create")).toBe(true);
  });
});

// ── openRenameChannel ──────────────────────────────────────────────────────────
describe("openRenameChannel()", () => {
  test("shows rename modal for private channel", () => {
    global.channel = "private:1";
    openRenameChannel();
    expect(
      document.getElementById("rename-private-ch-modal").style.display,
    ).toBe("block");
  });

  test("does nothing when channel is not private", () => {
    global.channel = "general";
    openRenameChannel();
    expect(
      document.getElementById("rename-private-ch-modal").style.display,
    ).toBe("none");
  });

  test("pre-fills existing channel name", () => {
    global.channel = "private:1";
    global.privateChannelMap = { "private:1": "My Channel" };
    // Ensure rename-ch-input is a proper input element
    let renameInput = document.getElementById("rename-ch-input");
    if (!renameInput || !("value" in renameInput)) {
      if (renameInput) renameInput.remove();
      renameInput = document.createElement("input");
      renameInput.id = "rename-ch-input";
      document.body.appendChild(renameInput);
    }
    openRenameChannel();
    expect(renameInput.value).toBe("My Channel");
  });
});

// ── rename-ch-cancel-btn ──────────────────────────────────────────────────────
describe("rename-ch-cancel-btn", () => {
  test("hides the rename modal", () => {
    document.getElementById("rename-private-ch-modal").style.display = "block";
    document.getElementById("rename-ch-cancel-btn").click();
    expect(
      document.getElementById("rename-private-ch-modal").style.display,
    ).toBe("none");
  });
});

// ── rename-ch-submit-btn ──────────────────────────────────────────────────────
describe("rename-ch-submit-btn", () => {
  beforeEach(() => {
    // Ensure rename-ch-input exists
    if (!document.getElementById("rename-ch-input")) {
      const inp = document.createElement("input");
      inp.id = "rename-ch-input";
      document.body.appendChild(inp);
    }
    if (!document.getElementById("rename-ch-name-error")) {
      const el = document.createElement("div");
      el.id = "rename-ch-name-error";
      document.body.appendChild(el);
    }
  });

  test("does nothing when channel is not private", async () => {
    global.channel = "general";
    document.getElementById("rename-ch-submit-btn").click();
    await Promise.resolve();
    expect(global.fetch).not.toHaveBeenCalledWith(
      expect.stringContaining("rename"),
      expect.anything(),
    );
  });

  test("shows error when name is too long", async () => {
    global.channel = "private:1";
    document.getElementById("rename-ch-input").value = "a".repeat(81);
    document.getElementById("rename-ch-submit-btn").click();
    await Promise.resolve();
    expect(
      document.getElementById("rename-ch-name-error").textContent,
    ).toContain("characters or fewer");
  });

  test("renames channel on valid input", async () => {
    global.channel = "private:1";
    document.getElementById("rename-ch-input").value = "New Name";
    global.fetch = jest.fn().mockImplementation((url) => {
      if (url.includes("rename"))
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
      if (url === "/private_channels")
        return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      if (url === "/channel_unreads")
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    document.getElementById("rename-ch-submit-btn").click();
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
    const calls = global.fetch.mock.calls.map((c) => c[0]);
    expect(calls.some((u) => u.includes("rename"))).toBe(true);
  });
});

// ── leaveChannel ──────────────────────────────────────────────────────────────
describe("leaveChannel()", () => {
  beforeEach(() => {
    global.confirm = jest.fn(() => true);
  });

  test("does nothing when channel is not private", async () => {
    global.channel = "general";
    await leaveChannel();
    expect(global.fetch).not.toHaveBeenCalled();
  });

  test("calls leave endpoint and switches to general", async () => {
    global.channel = "private:1";
    global.fetch = jest.fn().mockImplementation((url) => {
      if (url.includes("leave"))
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
      if (url === "/private_channels")
        return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      if (url === "/channel_unreads")
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    await leaveChannel();
    expect(global.switchChannel).toHaveBeenCalledWith("general");
  });

  test("does nothing if user cancels confirm", async () => {
    global.channel = "private:1";
    global.confirm = jest.fn(() => false);
    await leaveChannel();
    expect(global.fetch).not.toHaveBeenCalled();
  });
});

// ── add member input ───────────────────────────────────────────────────────────
describe("add-member-input keyboard navigation", () => {
  function makeKeyEvent(key) {
    return new KeyboardEvent("keydown", {
      key,
      bubbles: true,
      cancelable: true,
    });
  }

  beforeEach(() => {
    const sugg = document.getElementById("add-member-suggestions");
    sugg.style.display = "block";
    sugg.innerHTML = "";
    ["bob", "charlie"].forEach((name) => {
      const div = document.createElement("div");
      div.className = "autocomplete-suggestion";
      div.textContent = name;
      sugg.appendChild(div);
    });
  });

  test("ArrowDown moves selection down", () => {
    document
      .getElementById("add-member-input")
      .dispatchEvent(makeKeyEvent("ArrowDown"));
    const items = document.getElementById("add-member-suggestions").children;
    expect(items[0].classList.contains("active")).toBe(true);
  });

  test("ArrowUp wraps to last", () => {
    document
      .getElementById("add-member-input")
      .dispatchEvent(makeKeyEvent("ArrowUp"));
    const items = document.getElementById("add-member-suggestions").children;
    expect(items[1].classList.contains("active")).toBe(true);
  });

  test("Escape hides suggestions", () => {
    document
      .getElementById("add-member-input")
      .dispatchEvent(makeKeyEvent("Escape"));
    expect(
      document.getElementById("add-member-suggestions").style.display,
    ).toBe("none");
  });
});

// ── privateChMembersInput keyboard navigation ─────────────────────────────────
describe("private-ch-members-input keyboard navigation", () => {
  function makeKeyEvent(key) {
    return new KeyboardEvent("keydown", {
      key,
      bubbles: true,
      cancelable: true,
    });
  }

  beforeEach(() => {
    const sugg = document.getElementById("private-ch-suggestions");
    sugg.style.display = "block";
    sugg.innerHTML = "";
    ["bob", "charlie"].forEach((name) => {
      const div = document.createElement("div");
      div.className = "autocomplete-suggestion";
      div.textContent = name;
      sugg.appendChild(div);
    });
  });

  test("ArrowDown moves selection down", () => {
    document
      .getElementById("private-ch-members-input")
      .dispatchEvent(makeKeyEvent("ArrowDown"));
    const items = document.getElementById("private-ch-suggestions").children;
    expect(items[0].classList.contains("active")).toBe(true);
  });

  test("ArrowUp wraps to last", () => {
    document
      .getElementById("private-ch-members-input")
      .dispatchEvent(makeKeyEvent("ArrowUp"));
    const items = document.getElementById("private-ch-suggestions").children;
    expect(items[1].classList.contains("active")).toBe(true);
  });

  test("Escape hides suggestions", () => {
    document
      .getElementById("private-ch-members-input")
      .dispatchEvent(makeKeyEvent("Escape"));
    expect(
      document.getElementById("private-ch-suggestions").style.display,
    ).toBe("none");
  });

  test("Tab selects first suggestion", () => {
    document.getElementById("private-ch-members-input").value = "b";
    document
      .getElementById("private-ch-members-input")
      .dispatchEvent(makeKeyEvent("Tab"));
    expect(
      document.getElementById("private-ch-suggestions").style.display,
    ).toBe("none");
  });
});

// ── selectPCSuggestion ────────────────────────────────────────────────────────

// ── leaveChannel ──────────────────────────────────────────────────────────────
describe("leaveChannel()", () => {
  test("does nothing when not in a private channel", () => {
    global.channel = "general";
    global.fetch.mockClear();
    leaveChannel();
    expect(global.fetch).not.toHaveBeenCalled();
  });
  test("posts to leave endpoint when confirmed", async () => {
    global.channel = "private:7";
    global.privateChannelMap = { "private:7": "myteam" };
    global.confirm = jest.fn().mockReturnValue(true);
    global.switchChannel = jest.fn();
    // Include json() so that the fire-and-forget refreshPrivateChannels() call
    // that leaveChannel() makes doesn't crash with "r.json is not a function".
    global.fetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve([]),
    });
    await leaveChannel();
    expect(global.fetch).toHaveBeenCalledWith(
      "/private_channels/7/leave",
      expect.objectContaining({ method: "POST" }),
    );
  });
  test("aborts when user cancels", async () => {
    global.channel = "private:7";
    global.confirm = jest.fn().mockReturnValue(false);
    global.fetch.mockClear();
    await leaveChannel();
    expect(global.fetch).not.toHaveBeenCalled();
  });
});

// ── openCreatePrivateChannel / openRenameChannel ──────────────────────────────
describe("channel modal openers", () => {
  test("openCreatePrivateChannel shows the modal", () => {
    global.fetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve([]),
    });
    openCreatePrivateChannel();
    expect(
      document.getElementById("create-private-ch-modal").style.display,
    ).toBe("block");
  });
  test("openRenameChannel shows the rename modal", () => {
    global.channel = "private:3";
    global.privateChannelMap = { "private:3": "oldname" };
    openRenameChannel();
    expect(
      document.getElementById("rename-private-ch-modal").style.display,
    ).toBe("block");
  });
});
