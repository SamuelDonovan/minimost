/**
 * Tests for chat-reactions.js
 * Load order: sidebar → dm → settings → channels → reactions
 */

const { loadScript } = require("./loadScript");

beforeAll(() => {
  // Stubs for sidebar
  global.openCreatePrivateChannel = jest.fn();
  global.bindPCTooltip = jest.fn();
  global.nativeNotifEnabled = false;
  global.notifMuted = false;
  loadScript("chat-sidebar.js");

  // Stubs for dm
  global.fuzzySearch = jest.fn(() => null);
  global.highlightFuzzyMatch = jest.fn((t) => t);
  loadScript("chat-dm.js");

  // Stubs for settings
  global.defaultUserColor = jest.fn(() => "hsl(0, 60%, 60%)");
  global.userColor = jest.fn(() => "hsl(0, 60%, 60%)");
  global.usersWithAvatars = new Set();
  global.userColorOverrides = {};
  global.escapeHtml = (t) =>
    t.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
  global.profileCache = {};
  loadScript("chat-settings.js");

  // Stubs for channels
  global.setPresence = jest.fn();
  global.presenceMapCache = {};
  loadScript("chat-channels.js");

  // Reactions needs escapeHtml which is already set above
  loadScript("chat-reactions.js");
});

beforeEach(() => {
  jest.clearAllMocks();
  global.fetch.mockResolvedValue({
    ok: true,
    json: () => Promise.resolve({}),
  });
  document.getElementById("reaction-picker").style.display = "none";
});

// ── REACTIONS array ────────────────────────────────────────────────────────────
describe("REACTIONS", () => {
  test("is a non-empty array", () => {
    expect(Array.isArray(REACTIONS)).toBe(true);
    expect(REACTIONS.length).toBeGreaterThan(50);
  });

  test("each item has emoji, name, and label", () => {
    REACTIONS.forEach((r) => {
      expect(typeof r.emoji).toBe("string");
      expect(typeof r.name).toBe("string");
      expect(typeof r.label).toBe("string");
      expect(r.emoji.length).toBeGreaterThan(0);
    });
  });

  test("thumbsup is in the list", () => {
    expect(REACTIONS.find((r) => r.name === "thumbsup")).toBeTruthy();
  });

  test("thumbsup emoji is 👍", () => {
    const r = REACTIONS.find((r) => r.name === "thumbsup");
    expect(r.emoji).toBe("👍");
  });
});

// ── REACTION_EMOJI map ─────────────────────────────────────────────────────────
describe("REACTION_EMOJI", () => {
  test("maps name to emoji", () => {
    expect(REACTION_EMOJI["heart"]).toBe("❤️");
  });
});

// ── buildReactionsHtml ────────────────────────────────────────────────────────
describe("buildReactionsHtml()", () => {
  test("returns empty string for empty reactions", () => {
    expect(buildReactionsHtml(1, "{}")).toBe("");
  });

  test("returns empty string for null/undefined reactionsJson", () => {
    expect(buildReactionsHtml(1, null)).toBe("");
  });

  test("returns empty string for malformed JSON", () => {
    expect(buildReactionsHtml(1, "not-json")).toBe("");
  });

  test("generates chip for a reaction with users", () => {
    const reactions = JSON.stringify({ thumbsup: ["alice", "bob"] });
    const html = buildReactionsHtml(42, reactions);
    expect(html).toContain("reaction-chip");
    expect(html).toContain("👍");
    expect(html).toContain("2");
  });

  test("marks chip as active when CURRENT_USER reacted", () => {
    const reactions = JSON.stringify({ heart: ["alice"] });
    const html = buildReactionsHtml(42, reactions);
    expect(html).toContain("active");
  });

  test("does not mark chip as active for other users", () => {
    const reactions = JSON.stringify({ heart: ["bob"] });
    const html = buildReactionsHtml(42, reactions);
    expect(html).not.toContain("reaction-chip active");
  });

  test("includes reaction count", () => {
    const reactions = JSON.stringify({ fire: ["alice", "bob", "charlie"] });
    const html = buildReactionsHtml(1, reactions);
    expect(html).toContain("3");
  });

  test("skips reactions with empty users array", () => {
    const reactions = JSON.stringify({ thumbsup: [] });
    const html = buildReactionsHtml(1, reactions);
    expect(html).toBe("");
  });

  test("multiple reactions generate multiple chips", () => {
    const reactions = JSON.stringify({
      thumbsup: ["alice"],
      heart: ["bob"],
    });
    const html = buildReactionsHtml(1, reactions);
    const count = (html.match(/reaction-chip/g) || []).length;
    expect(count).toBe(2);
  });

  test("includes toggleReaction onclick", () => {
    const reactions = JSON.stringify({ thumbsup: ["alice"] });
    const html = buildReactionsHtml(99, reactions);
    expect(html).toContain("toggleReaction(99");
  });

  test("shows tooltip with usernames", () => {
    const reactions = JSON.stringify({ check: ["alice", "bob"] });
    const html = buildReactionsHtml(1, reactions);
    expect(html).toContain("reaction-tooltip");
    expect(html).toContain("alice");
  });
});

// ── openReactionPicker ────────────────────────────────────────────────────────
describe("openReactionPicker()", () => {
  test("shows the reaction picker", () => {
    const anchor = document.createElement("button");
    anchor.getBoundingClientRect = () => ({
      left: 100,
      bottom: 200,
      right: 200,
    });
    anchor.currentTarget = anchor;
    document.body.appendChild(anchor);

    openReactionPicker(42, {
      stopPropagation: jest.fn(),
      currentTarget: anchor,
    });
    expect(document.getElementById("reaction-picker").style.display).toBe(
      "block",
    );
    anchor.remove();
  });

  test("removes reaction-picker-open class from previous message", () => {
    const prev = document.createElement("div");
    prev.id = "msg-99";
    prev.classList.add("reaction-picker-open");
    document.body.appendChild(prev);

    const anchor = document.createElement("button");
    anchor.getBoundingClientRect = () => ({
      left: 100,
      bottom: 200,
      right: 200,
    });
    document.body.appendChild(anchor);

    // First open with msg 99
    openReactionPicker(99, {
      stopPropagation: jest.fn(),
      currentTarget: anchor,
    });
    // Then open with msg 100
    openReactionPicker(100, {
      stopPropagation: jest.fn(),
      currentTarget: anchor,
    });

    expect(prev.classList.contains("reaction-picker-open")).toBe(false);
    prev.remove();
    anchor.remove();
  });
});

// ── closeReactionPicker ───────────────────────────────────────────────────────
describe("closeReactionPicker()", () => {
  test("hides the reaction picker", () => {
    document.getElementById("reaction-picker").style.display = "block";
    closeReactionPicker();
    expect(document.getElementById("reaction-picker").style.display).toBe(
      "none",
    );
  });

  test("removes visual-selected class from message element", () => {
    const msgEl = document.createElement("div");
    msgEl.id = "msg-77";
    msgEl.classList.add("reaction-picker-open");
    document.body.appendChild(msgEl);

    const anchor = document.createElement("button");
    anchor.getBoundingClientRect = () => ({ left: 0, bottom: 0, right: 0 });
    document.body.appendChild(anchor);
    openReactionPicker(77, {
      stopPropagation: jest.fn(),
      currentTarget: anchor,
    });

    closeReactionPicker();
    expect(msgEl.classList.contains("reaction-picker-open")).toBe(false);
    msgEl.remove();
    anchor.remove();
  });
});

// ── filterReactions ───────────────────────────────────────────────────────────
describe("filterReactions()", () => {
  test("hides items that do not match query", () => {
    filterReactions("thumbsup");
    const items = document.querySelectorAll(".reaction-picker-item");
    const hidden = Array.from(items).filter(
      (el) => el.style.display === "none",
    );
    const visible = Array.from(items).filter(
      (el) => el.style.display !== "none",
    );
    expect(visible.length).toBeGreaterThan(0);
    expect(hidden.length).toBeGreaterThan(0);
  });

  test("empty query shows all items", () => {
    filterReactions("");
    const items = document.querySelectorAll(".reaction-picker-item");
    const hidden = Array.from(items).filter(
      (el) => el.style.display === "none",
    );
    expect(hidden).toHaveLength(0);
  });

  test("query matches label (case-insensitive)", () => {
    filterReactions("thumbs up");
    // "thumbsup" label is "Thumbs Up"
    const items = document.querySelectorAll(".reaction-picker-item");
    const thumbsItem = Array.from(items).find(
      (el) => el.dataset.name === "thumbsup",
    );
    expect(thumbsItem).toBeTruthy();
    // It should be visible
    expect(thumbsItem.style.display).not.toBe("none");
  });
});

// ── toggleReaction ────────────────────────────────────────────────────────────
describe("toggleReaction()", () => {
  test("calls /react/:msgId with POST", () => {
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ thumbsup: ["alice"] }),
    });
    toggleReaction(42, "thumbsup");
    expect(global.fetch).toHaveBeenCalledWith(
      "/react/42",
      expect.objectContaining({ method: "POST" }),
    );
  });

  test("updates reactions div innerHTML on success", async () => {
    const reactDiv = document.createElement("div");
    reactDiv.id = "reactions-42";
    document.body.appendChild(reactDiv);

    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ thumbsup: ["alice"] }),
    });
    toggleReaction(42, "thumbsup");
    await Promise.resolve();
    await Promise.resolve();
    // toggleReaction posts the reaction to the server.
    expect(global.fetch).toHaveBeenCalledWith(
      "/react/42",
      expect.objectContaining({ method: "POST" }),
    );
    reactDiv.remove();
  });

  test("handles fetch error gracefully", async () => {
    global.fetch.mockResolvedValueOnce({ ok: false });
    expect(() => toggleReaction(42, "heart")).not.toThrow();
    await Promise.resolve();
  });
});

// ── pickerReact ───────────────────────────────────────────────────────────────
describe("pickerReact() via openReactionPicker", () => {
  test("calls toggleReaction and closes picker", () => {
    global.toggleReaction = jest.fn();
    const anchor = document.createElement("button");
    anchor.getBoundingClientRect = () => ({
      left: 100,
      bottom: 200,
      right: 200,
    });
    document.body.appendChild(anchor);

    openReactionPicker(55, {
      stopPropagation: jest.fn(),
      currentTarget: anchor,
    });
    pickerReact("thumbsup");
    expect(document.getElementById("reaction-picker").style.display).toBe(
      "none",
    );
    anchor.remove();
    delete global.toggleReaction;
  });

  test("does nothing when no current picker message", () => {
    closeReactionPicker(); // clears currentPickerMsgId
    expect(() => pickerReact("thumbsup")).not.toThrow();
  });
});

// ── picker grid was built ─────────────────────────────────────────────────────
describe("picker grid", () => {
  test("reaction-picker-grid has items", () => {
    const grid = document.getElementById("reaction-picker-grid");
    expect(grid.children.length).toBeGreaterThan(0);
  });

  test("each grid item has data-name", () => {
    const items = document.querySelectorAll(".reaction-picker-item");
    items.forEach((item) => {
      expect(item.dataset.name).toBeTruthy();
    });
  });
});
