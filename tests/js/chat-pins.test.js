/**
 * Tests for chat-pins.js
 *
 * chat-pins.js grabs its topbar elements at load time and leans on globals
 * defined elsewhere (channel, escapeHtml, messagePreviewText, showToast,
 * revealMessage), so the markup and those stubs are put in place first.
 */

const { loadScript } = require("./loadScript");

// Mirrors the .msg structure _buildMsgHtml produces, down to the parts
// paintPinMarkers reaches for: .msg-content-col, .msg-body and .pin-btn.
function addMessage(id, { system = false } = {}) {
  const el = document.createElement("div");
  el.className = system ? "msg system-msg" : "msg";
  el.id = `msg-${id}`;
  el.innerHTML =
    '<div class="msg-content-col">' +
    '<div class="msg-header"><span class="msg-actions">' +
    '<button class="pin-btn" aria-pressed="false"></button>' +
    "</span></div>" +
    '<div class="msg-body">text</div>' +
    "</div>";
  document.getElementById("chat").appendChild(el);
  return el;
}

function pin(id, overrides = {}) {
  return {
    id,
    channel: "general",
    sender: "bob",
    content: `message ${id}`,
    filename: null,
    ts: 1000 + id,
    pinned_by: "alice",
    pinned_ts: 2000 + id,
    ...overrides,
  };
}

beforeAll(() => {
  document.body.innerHTML = `
    <div id="topbar-pins">
      <button id="pins-btn" style="display:none" aria-expanded="false">
        <span id="pins-count"></span>
      </button>
      <div id="pins-panel"><div id="pins-list"></div></div>
    </div>
    <div id="chat"></div>`;

  global.channel = "general";
  global.escapeHtml = (t) =>
    String(t)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;");
  global.messagePreviewText = (c, n) => String(c).slice(0, n);
  global.showToast = jest.fn();
  global.revealMessage = jest.fn();

  loadScript("chat-pins.js");
});

beforeEach(() => {
  jest.clearAllMocks();
  global.channel = "general";
  document.getElementById("chat").innerHTML = "";
  // Reset module state through its own entry point rather than by reaching
  // into internals.
  applyPins([]);
  closePinsPanel();
});

// ── applyPins ─────────────────────────────────────────────────────────────────

describe("applyPins()", () => {
  test("shows the button with a count once something is pinned", () => {
    applyPins([pin(1), pin(2)]);
    const btn = document.getElementById("pins-btn");
    expect(btn.style.display).toBe("");
    expect(document.getElementById("pins-count").textContent).toBe("2");
    expect(btn.title).toBe("2 pinned messages");
  });

  test("singular title for a single pin", () => {
    applyPins([pin(1)]);
    expect(document.getElementById("pins-btn").title).toBe("1 pinned message");
  });

  test("hides the button when nothing is pinned", () => {
    applyPins([pin(1)]);
    applyPins([]);
    expect(document.getElementById("pins-btn").style.display).toBe("none");
    expect(document.getElementById("pins-count").textContent).toBe("");
  });

  test("drops a payload for a channel the user has already left", () => {
    applyPins([pin(1)], "software");
    expect(document.getElementById("pins-btn").style.display).toBe("none");
  });

  test("tolerates a non-array payload", () => {
    expect(() => applyPins(null)).not.toThrow();
    expect(document.getElementById("pins-btn").style.display).toBe("none");
  });

  test("closes the panel when the last pin goes away", () => {
    applyPins([pin(1)]);
    openPinsPanel();
    expect(
      document.getElementById("topbar-pins").classList.contains("open"),
    ).toBe(true);
    applyPins([]);
    expect(
      document.getElementById("topbar-pins").classList.contains("open"),
    ).toBe(false);
  });
});

// ── paintPinMarkers ───────────────────────────────────────────────────────────

describe("paintPinMarkers()", () => {
  test("marks a pinned message and names who pinned it", () => {
    const el = addMessage(1);
    applyPins([pin(1, { pinned_by: "carol" })]);

    expect(el.classList.contains("pinned")).toBe(true);
    expect(el.querySelector(".pin-marker").textContent).toBe("Pinned by carol");
    const btn = el.querySelector(".pin-btn");
    expect(btn.classList.contains("active")).toBe(true);
    expect(btn.getAttribute("aria-pressed")).toBe("true");
    expect(btn.title).toBe("Unpin");
  });

  test("puts the marker above the body, not in the header", () => {
    const el = addMessage(1);
    applyPins([pin(1)]);

    const col = el.querySelector(".msg-content-col");
    const marker = col.querySelector(".pin-marker");
    expect(marker.parentElement).toBe(col);
    expect(marker.nextElementSibling.className).toBe("msg-body");
  });

  test("leaves an unpinned message alone", () => {
    const el = addMessage(1);
    applyPins([pin(2)]);

    expect(el.classList.contains("pinned")).toBe(false);
    expect(el.querySelector(".pin-marker")).toBeNull();
    expect(el.querySelector(".pin-btn").title).toBe("Pin to channel");
  });

  test("removes the marker when a message is unpinned", () => {
    const el = addMessage(1);
    applyPins([pin(1)]);
    applyPins([]);

    expect(el.classList.contains("pinned")).toBe(false);
    expect(el.querySelector(".pin-marker")).toBeNull();
    expect(el.querySelector(".pin-btn").getAttribute("aria-pressed")).toBe(
      "false",
    );
  });

  test("does not duplicate the marker on a repeated paint", () => {
    const el = addMessage(1);
    applyPins([pin(1)]);
    applyPins([pin(1)]);

    expect(el.querySelectorAll(".pin-marker")).toHaveLength(1);
  });

  test("updates the marker when a different person re-pins", () => {
    const el = addMessage(1);
    applyPins([pin(1, { pinned_by: "alice" })]);
    applyPins([pin(1, { pinned_by: "dave" })]);

    expect(el.querySelector(".pin-marker").textContent).toBe("Pinned by dave");
  });

  test("skips non-message nodes handed over by the append path", () => {
    const divider = document.createElement("div");
    divider.className = "date-divider";
    divider.id = "date-x";
    document.getElementById("chat").appendChild(divider);

    expect(() => paintPinMarkers([divider])).not.toThrow();
    expect(divider.classList.contains("pinned")).toBe(false);
  });

  test("paints only the nodes it is given", () => {
    const painted = addMessage(1);
    const untouched = addMessage(2);
    // Seed the pin list without painting, then paint one node.
    applyPins([pin(1), pin(2)]);
    untouched.classList.remove("pinned");
    untouched.querySelector(".pin-marker").remove();

    paintPinMarkers([painted]);

    expect(painted.classList.contains("pinned")).toBe(true);
    expect(untouched.classList.contains("pinned")).toBe(false);
  });
});

// ── renderPins / panel ────────────────────────────────────────────────────────

describe("the pins panel", () => {
  test("lists each pin with its sender and pinner", () => {
    applyPins([pin(1, { sender: "bob", pinned_by: "alice" })]);
    openPinsPanel();

    const rows = document.querySelectorAll("#pins-list .pin-item");
    expect(rows).toHaveLength(1);
    expect(rows[0].querySelector(".pin-item-meta").textContent).toContain(
      "bob",
    );
    expect(rows[0].querySelector(".pin-item-meta").textContent).toContain(
      "pinned by alice",
    );
    expect(rows[0].querySelector(".pin-item-text").textContent).toBe(
      "message 1",
    );
  });

  test("shows an empty state when there is nothing to list", () => {
    renderPins();
    expect(document.querySelector("#pins-list .pins-empty").textContent).toBe(
      "Nothing pinned here yet",
    );
  });

  test("labels a file-only pin as an attachment", () => {
    applyPins([pin(1, { content: "", filename: "report.pdf" })]);
    openPinsPanel();
    expect(document.querySelector(".pin-item-text").textContent).toBe(
      "[attachment]",
    );
  });

  test("escapes a sender name rather than rendering it as markup", () => {
    applyPins([pin(1, { sender: "<img src=x>" })]);
    openPinsPanel();
    expect(document.querySelector("#pins-list img")).toBeNull();
  });

  test("clicking a row jumps to the message and closes the panel", () => {
    applyPins([pin(1)]);
    openPinsPanel();

    document.querySelector(".pin-item").click();

    expect(revealMessage).toHaveBeenCalledWith("general", 1, 1001);
    expect(
      document.getElementById("topbar-pins").classList.contains("open"),
    ).toBe(false);
  });

  test("the unpin button posts and does not also jump to the message", () => {
    global.fetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve([]),
    });
    applyPins([pin(1)]);
    openPinsPanel();

    document.querySelector(".pin-item-unpin").click();

    expect(fetch).toHaveBeenCalledWith("/pin/1", { method: "POST" });
    expect(revealMessage).not.toHaveBeenCalled();
  });

  test("toggling opens and closes", () => {
    applyPins([pin(1)]);
    const wrap = document.getElementById("topbar-pins");

    togglePinsPanel();
    expect(wrap.classList.contains("open")).toBe(true);
    expect(
      document.getElementById("pins-btn").getAttribute("aria-expanded"),
    ).toBe("true");

    togglePinsPanel();
    expect(wrap.classList.contains("open")).toBe(false);
  });

  test("a click outside closes it", () => {
    applyPins([pin(1)]);
    openPinsPanel();

    document
      .getElementById("chat")
      .dispatchEvent(new globalThis.MouseEvent("click", { bubbles: true }));

    expect(
      document.getElementById("topbar-pins").classList.contains("open"),
    ).toBe(false);
  });

  test("a click inside leaves it open", () => {
    applyPins([pin(1)]);
    openPinsPanel();

    document
      .getElementById("pins-list")
      .dispatchEvent(new globalThis.MouseEvent("click", { bubbles: true }));

    expect(
      document.getElementById("topbar-pins").classList.contains("open"),
    ).toBe(true);
  });

  test("Escape closes it", () => {
    applyPins([pin(1)]);
    openPinsPanel();

    document.dispatchEvent(
      new globalThis.KeyboardEvent("keydown", { key: "Escape" }),
    );

    expect(
      document.getElementById("topbar-pins").classList.contains("open"),
    ).toBe(false);
  });
});

// ── togglePin ─────────────────────────────────────────────────────────────────

describe("togglePin()", () => {
  test("posts and repaints from the response", async () => {
    global.fetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve([pin(1)]),
    });
    const el = addMessage(1);

    await togglePin(1);

    expect(fetch).toHaveBeenCalledWith("/pin/1", { method: "POST" });
    expect(el.classList.contains("pinned")).toBe(true);
    expect(showToast).toHaveBeenCalledWith("Message pinned");
  });

  test("reports an unpin when the message was already pinned", async () => {
    applyPins([pin(1)]);
    global.fetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve([]),
    });

    await togglePin(1);

    expect(showToast).toHaveBeenCalledWith("Message unpinned");
  });

  test("explains a rejected pin at the channel cap", async () => {
    global.fetch.mockResolvedValue({ ok: false, status: 409 });

    await togglePin(1);

    expect(showToast).toHaveBeenCalledWith(
      "This channel has reached its pin limit — unpin one first",
    );
  });

  test("reports any other failure", async () => {
    global.fetch.mockResolvedValue({ ok: false, status: 404 });

    await togglePin(1);

    expect(showToast).toHaveBeenCalledWith("Could not pin that message");
  });

  test("reports a network failure", async () => {
    global.fetch.mockRejectedValue(new Error("offline"));

    await togglePin(1);

    expect(showToast).toHaveBeenCalledWith("Could not pin that message");
  });

  test("accepts an id passed as a string", async () => {
    global.fetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve([pin(1)]),
    });

    await togglePin("1");

    expect(fetch).toHaveBeenCalledWith("/pin/1", { method: "POST" });
  });
});

// ── refreshPins ───────────────────────────────────────────────────────────────

describe("refreshPins()", () => {
  test("loads the open channel's pins", async () => {
    global.fetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve([pin(1)]),
    });

    await refreshPins();

    expect(fetch).toHaveBeenCalledWith("/pins/general");
    expect(document.getElementById("pins-count").textContent).toBe("1");
  });

  test("clears the previous channel's pins before the request lands", () => {
    applyPins([pin(1)]);
    let resolve;
    global.fetch.mockReturnValue(
      new Promise((r) => {
        resolve = r;
      }),
    );

    refreshPins();

    expect(document.getElementById("pins-btn").style.display).toBe("none");
    resolve({ ok: true, json: () => Promise.resolve([]) });
  });

  test("encodes a channel identifier containing separators", async () => {
    global.channel = "dm:alice:bob";
    global.fetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve([]),
    });

    await refreshPins();

    expect(fetch).toHaveBeenCalledWith("/pins/dm%3Aalice%3Abob");
  });

  test("survives a failed load", async () => {
    global.fetch.mockRejectedValue(new Error("offline"));

    await expect(refreshPins()).resolves.toBeUndefined();
    expect(document.getElementById("pins-btn").style.display).toBe("none");
  });

  test("ignores a response that arrives after a channel switch", async () => {
    let resolve;
    global.fetch.mockReturnValue(
      new Promise((r) => {
        resolve = r;
      }),
    );
    const inFlight = refreshPins();
    global.channel = "software";
    resolve({ ok: true, json: () => Promise.resolve([pin(1)]) });
    await inFlight;

    expect(document.getElementById("pins-btn").style.display).toBe("none");
  });
});
