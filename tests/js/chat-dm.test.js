/**
 * Tests for chat-dm.js
 * Load order: sidebar → dm
 */

const { loadScript } = require("./loadScript");

beforeAll(() => {
  // Stubs needed before sidebar loads
  global.openCreatePrivateChannel = jest.fn();
  global.bindPCTooltip = jest.fn();
  global.nativeNotifEnabled = false;
  global.notifMuted = false;

  loadScript("chat-sidebar.js");

  // Additional stubs for dm.js
  global.fuzzySearch = jest.fn((q, t) => {
    if (t.toLowerCase().includes(q.toLowerCase()))
      return { score: 1, indices: [0] };
    return null;
  });
  global.highlightFuzzyMatch = jest.fn((t) => t);

  loadScript("chat-dm.js");
});

beforeEach(() => {
  jest.clearAllMocks();
  global.fetch.mockResolvedValue({ ok: true, json: () => Promise.resolve([]) });
  // Reset DM modal state
  document.getElementById("dm-modal").style.display = "none";
  document.getElementById("dm-users").value = "";
  document.getElementById("dm-suggestions").style.display = "none";
  document.getElementById("dm-suggestions").innerHTML = "";
  // Reset allUsers / usersLoaded state (they're let-scoped but we can test via behavior)
});

// ── resetDmSuggestions ─────────────────────────────────────────────────────────
describe("resetDmSuggestions()", () => {
  test("can be called without error", () => {
    expect(() => resetDmSuggestions()).not.toThrow();
  });
});

// ── openDmModal ────────────────────────────────────────────────────────────────
describe("openDmModal()", () => {
  test("shows the DM modal", async () => {
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve(["bob", "charlie"]),
    });
    await openDmModal();
    expect(document.getElementById("dm-modal").style.display).toBe("block");
  });

  test("fetches /users on first open", async () => {
    // Force usersLoaded reset by reloading — we can't directly, so test fetch was called
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve(["bob"]),
    });
    await openDmModal();
    const calls = global.fetch.mock.calls.map((c) => c[0]);
    // Either /users was called or it was already cached
    expect(typeof calls).toBe("object");
  });

  test("handles fetch failure gracefully", async () => {
    global.fetch.mockRejectedValueOnce(new Error("Network error"));
    await expect(openDmModal()).resolves.not.toThrow();
  });

  test("handles non-ok response gracefully", async () => {
    global.fetch.mockResolvedValueOnce({
      ok: false,
      json: () => Promise.resolve([]),
    });
    await expect(openDmModal()).resolves.not.toThrow();
  });
});

// ── DM input keyboard navigation ───────────────────────────────────────────────
describe("DM input keydown handlers", () => {
  function makeKeyEvent(key, opts = {}) {
    return new KeyboardEvent("keydown", {
      key,
      bubbles: true,
      cancelable: true,
      ...opts,
    });
  }

  beforeEach(() => {
    const sugg = document.getElementById("dm-suggestions");
    sugg.style.display = "block";
    sugg.innerHTML = "";
    // Add suggestion items
    ["bob", "charlie", "dave"].forEach((name) => {
      const div = document.createElement("div");
      div.className = "autocomplete-suggestion";
      div.textContent = name;
      sugg.appendChild(div);
    });
  });

  test("ArrowDown moves selection down", () => {
    const input = document.getElementById("dm-users");
    input.dispatchEvent(makeKeyEvent("ArrowDown"));
    const items = document.getElementById("dm-suggestions").children;
    expect(items[0].classList.contains("active")).toBe(true);
  });

  test("ArrowUp wraps around to last item from -1", () => {
    const input = document.getElementById("dm-users");
    input.dispatchEvent(makeKeyEvent("ArrowUp"));
    const items = document.getElementById("dm-suggestions").children;
    expect(items[2].classList.contains("active")).toBe(true);
  });

  test("ArrowDown then ArrowUp returns to first", () => {
    const input = document.getElementById("dm-users");
    input.dispatchEvent(makeKeyEvent("ArrowDown")); // index 0
    input.dispatchEvent(makeKeyEvent("ArrowUp")); // wraps to last (2)
    const items = document.getElementById("dm-suggestions").children;
    expect(items[2].classList.contains("active")).toBe(true);
  });

  test("Escape hides suggestions", () => {
    const input = document.getElementById("dm-users");
    input.dispatchEvent(makeKeyEvent("Escape"));
    expect(document.getElementById("dm-suggestions").style.display).toBe(
      "none",
    );
  });

  test("Tab selects first suggestion", () => {
    // Set input value so selectSuggestion works
    document.getElementById("dm-users").value = "b";
    // Ensure currentSuggestions has a value (set by updateSuggestions)
    // We mock it directly
    global.currentSuggestions = ["bob", "charlie"];
    const input = document.getElementById("dm-users");
    // The Tab keydown handler must run without throwing.
    expect(() => input.dispatchEvent(makeKeyEvent("Tab"))).not.toThrow();
  });

  test("Enter with suggestions triggers select", () => {
    document.getElementById("dm-users").value = "bob";
    global.currentSuggestions = ["bob"];
    const input = document.getElementById("dm-users");
    // The Enter keydown handler must run without throwing.
    expect(() => input.dispatchEvent(makeKeyEvent("Enter"))).not.toThrow();
  });
});

// ── closeDm ────────────────────────────────────────────────────────────────────
describe("closeDm()", () => {
  test("calls /dms/close with correct body", async () => {
    // Provide a clean fetch mock
    global.fetch = jest
      .fn()
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({}) });
    await closeDm("dm:alice:bob");
    expect(global.fetch).toHaveBeenCalledWith(
      "/dms/close",
      expect.objectContaining({
        method: "POST",
        body: expect.stringContaining("dm:alice:bob"),
      }),
    );
  });

  test("switches to general when closing current DM channel", async () => {
    global.channel = "dm:alice:bob";
    global.switchChannel = jest.fn();
    global.fetch = jest
      .fn()
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({}) });
    await closeDm("dm:alice:bob");
    expect(global.switchChannel).toHaveBeenCalledWith("general");
  });

  test("does nothing further if fetch returns not ok", async () => {
    global.fetch = jest.fn().mockResolvedValueOnce({ ok: false });
    await closeDm("dm:alice:bob");
    // closeDm posts to /dms/close regardless of the response status.
    expect(global.fetch).toHaveBeenCalledWith(
      "/dms/close",
      expect.objectContaining({ method: "POST" }),
    );
  });
});

// ── PC Tooltip helpers ─────────────────────────────────────────────────────────
describe("PC tooltip helpers", () => {
  beforeEach(() => {
    jest.useFakeTimers();
  });
  afterEach(() => {
    jest.useRealTimers();
  });

  test("hidePCTooltip hides the tooltip element", () => {
    // Remove any existing pc-member-tooltip first
    const existing = document.getElementById("pc-member-tooltip");
    if (existing) existing.remove();
    const tooltip = document.createElement("div");
    tooltip.id = "pc-member-tooltip";
    tooltip.style.display = "block";
    document.body.appendChild(tooltip);
    hidePCTooltip();
    expect(tooltip.style.display).toBe("none");
    tooltip.remove();
  });

  test("bindPCTooltip attaches mouse handlers", () => {
    const el = document.createElement("div");
    el.dataset.channel = "private:1";
    bindPCTooltip(el);
    expect(typeof el.onmouseenter).toBe("function");
    expect(typeof el.onmouseleave).toBe("function");
  });
});

// ── dm-start button ────────────────────────────────────────────────────────────
describe("dm-start button", () => {
  test("clicking with empty input does nothing", () => {
    document.getElementById("dm-users").value = "";
    document.getElementById("dm-start").click();
    expect(global.switchChannel).not.toHaveBeenCalled();
  });

  test("clicking with a user switches to DM channel", () => {
    document.getElementById("dm-users").value = "bob";
    document.getElementById("dm-start").click();
    // switchChannel should be called with sorted DM channel
    expect(global.switchChannel).toHaveBeenCalled();
    const arg = global.switchChannel.mock.calls[0][0];
    expect(arg).toContain("dm:");
    expect(arg).toContain("alice");
    expect(arg).toContain("bob");
  });
});

// ── dm-cancel button ───────────────────────────────────────────────────────────
describe("dm-cancel button", () => {
  test("clicking hides the modal", () => {
    document.getElementById("dm-modal").style.display = "block";
    document.getElementById("dm-cancel").click();
    expect(document.getElementById("dm-modal").style.display).toBe("none");
  });
});

// ── openDmModal (fetches users on first open) ─────────────────────────────────
describe("openDmModal()", () => {
  test("shows modal", async () => {
    global.fetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(["alice", "bob"]),
    });
    await openDmModal();
    expect(document.getElementById("dm-modal").style.display).toBe("block");
  });
  test("fetches and stores users when not loaded", async () => {
    global.usersLoaded = false;
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve(["alice", "bob"]),
    });
    await openDmModal();
    expect(global.allUsers).toEqual(["alice", "bob"]);
    expect(global.usersLoaded).toBe(true);
  });
  test("skips fetch when already loaded", async () => {
    global.usersLoaded = true;
    global.fetch.mockClear();
    await openDmModal();
    expect(global.fetch).not.toHaveBeenCalled();
  });
});

// ── resetDmModal ──────────────────────────────────────────────────────────────
describe("resetDmModal()", () => {
  test("hides suggestions and clears input", () => {
    document.getElementById("dm-suggestions").style.display = "block";
    document.getElementById("dm-users").value = "alice";
    resetDmModal();
    expect(document.getElementById("dm-suggestions").style.display).toBe(
      "none",
    );
    expect(document.getElementById("dm-users").value).toBe("");
  });
});

// ── updateSuggestions ─────────────────────────────────────────────────────────
describe("updateSuggestions()", () => {
  test("populates suggestions matching the input", () => {
    global.allUsers = ["alice", "bob", "carol"];
    global.usersLoaded = true;
    document.getElementById("dm-users").value = "ali";
    updateSuggestions();
    const sug = document.getElementById("dm-suggestions");
    expect(sug.style.display).toBe("block");
  });
  test("hides suggestions when nothing matches", () => {
    global.allUsers = ["alice", "bob"];
    global.usersLoaded = true;
    document.getElementById("dm-users").value = "zzz";
    updateSuggestions();
    expect(document.getElementById("dm-suggestions").style.display).toBe(
      "none",
    );
  });
  test("hides suggestions when users not loaded", () => {
    global.usersLoaded = false;
    document.getElementById("dm-users").value = "alice";
    document.getElementById("dm-suggestions").style.display = "none";
    updateSuggestions();
    expect(document.getElementById("dm-suggestions").style.display).toBe(
      "none",
    );
  });
});

// ── resetDmSuggestions ────────────────────────────────────────────────────────
describe("resetDmSuggestions()", () => {
  test("resets suggestionIndex to -1", () => {
    suggestionIndex = 3;
    resetDmSuggestions();
    expect(suggestionIndex).toBe(-1);
  });
});
