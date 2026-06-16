/**
 * Tests for chat-mentions.js
 *
 * chat-mentions.js references several globals defined elsewhere (CURRENT_USER,
 * channel, msgBox, updateSendState, fuzzySearch, highlightFuzzyMatch,
 * makeAvatarWrap, nativeNotifEnabled). We stub them before loading the script.
 */

const { loadScript } = require("./loadScript");

let msgBox;

beforeAll(() => {
  // The mention dropdown container the script grabs at load time.
  const box = document.createElement("div");
  box.id = "mention-suggestions";
  document.body.appendChild(box);

  // msgBox is normally the composer <textarea> from the inline page script.
  msgBox = document.createElement("textarea");
  msgBox.id = "msg";
  document.body.appendChild(msgBox);
  global.msgBox = msgBox;

  global.channel = "general";
  global.updateSendState = jest.fn();
  global.fuzzySearch = jest.fn((q, t) =>
    t.toLowerCase().includes(q.toLowerCase())
      ? { score: 1, indices: [] }
      : null,
  );
  global.highlightFuzzyMatch = jest.fn((t) => t);
  global.makeAvatarWrap = jest.fn((u) => {
    const d = document.createElement("div");
    d.className = "avatar-wrap";
    d.dataset.user = u;
    return d;
  });
  global.nativeNotifEnabled = false;

  loadScript("chat-mentions.js");
});

beforeEach(() => {
  jest.clearAllMocks();
  global.fetch.mockResolvedValue({ ok: true, json: () => Promise.resolve([]) });
  document.getElementById("mention-suggestions").style.display = "none";
});

// ── isMentioned ───────────────────────────────────────────────────────────────
describe("isMentioned()", () => {
  test("true when current user is in the mention list", () => {
    expect(
      isMentioned({ mentions: JSON.stringify(["alice"]), sender: "bob" }),
    ).toBe(true);
  });

  test("false when current user is not mentioned", () => {
    expect(
      isMentioned({ mentions: JSON.stringify(["bob"]), sender: "bob" }),
    ).toBe(false);
  });

  test("@everyone mentions every recipient", () => {
    expect(
      isMentioned({ mentions: JSON.stringify(["@everyone"]), sender: "bob" }),
    ).toBe(true);
  });

  test("@everyone does not alert the sender on their own copy", () => {
    expect(
      isMentioned({ mentions: JSON.stringify(["@everyone"]), sender: "alice" }),
    ).toBe(false);
  });

  test("false when mentions is null", () => {
    expect(isMentioned({ mentions: null, sender: "bob" })).toBe(false);
  });

  test("false on malformed JSON", () => {
    expect(isMentioned({ mentions: "not-json", sender: "bob" })).toBe(false);
  });
});

// ── applyMentionPills ─────────────────────────────────────────────────────────
describe("applyMentionPills()", () => {
  beforeAll(() => {
    registerKnownUser("bob");
  });

  test("wraps a known user in a mention pill", () => {
    expect(applyMentionPills("hey @bob")).toBe(
      'hey <span class="mention">@bob</span>',
    );
  });

  test("flags a mention of the current user with mention-me", () => {
    expect(applyMentionPills("@alice")).toContain('class="mention mention-me"');
  });

  test("@everyone always renders as a pill", () => {
    expect(applyMentionPills("@everyone go")).toContain("mention-everyone");
  });

  test("leaves unknown users untouched", () => {
    expect(applyMentionPills("@nobody")).toBe("@nobody");
  });

  test("does not match inside an email address", () => {
    expect(applyMentionPills("mail foo@bob.com")).toBe("mail foo@bob.com");
  });

  test("does not match inside a URL path", () => {
    const url = "http://x.com/@bob";
    expect(applyMentionPills(url)).toBe(url);
  });
});

// ── notifyMention ─────────────────────────────────────────────────────────────
describe("notifyMention()", () => {
  afterEach(() => {
    global.nativeNotifEnabled = false;
    global.Notification.permission = "default";
  });

  test("does nothing when native notifications are disabled", () => {
    global.nativeNotifEnabled = false;
    global.Notification.permission = "granted";
    notifyMention({ sender: "bob", content: "hi @alice" });
    expect(global.Notification).not.toHaveBeenCalled();
  });

  test("does nothing without granted permission", () => {
    global.nativeNotifEnabled = true;
    global.Notification.permission = "default";
    notifyMention({ sender: "bob", content: "hi @alice" });
    expect(global.Notification).not.toHaveBeenCalled();
  });

  test("fires a notification when enabled and permitted", () => {
    global.nativeNotifEnabled = true;
    global.Notification.permission = "granted";
    notifyMention({ sender: "bob", content: "hi @alice" });
    expect(global.Notification).toHaveBeenCalledWith(
      expect.stringContaining("mentioned you"),
      expect.objectContaining({ body: "hi @alice", tag: "minimost-mention" }),
    );
  });
});

// ── activeMentionToken (via dropdown behaviour) ───────────────────────────────
describe("@-token detection", () => {
  test("opens the dropdown while typing an @token", async () => {
    global.fetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(["bob"]),
    });
    msgBox.value = "hey @bo";
    msgBox.setSelectionRange(7, 7);
    await refreshMentions();
    expect(document.getElementById("mention-suggestions").style.display).toBe(
      "block",
    );
  });

  test("offers @everyone as a candidate", async () => {
    global.fetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(["bob"]),
    });
    msgBox.value = "@every";
    msgBox.setSelectionRange(6, 6);
    await refreshMentions();
    const box = document.getElementById("mention-suggestions");
    expect(box.textContent).toContain("everyone");
  });

  test("hides the dropdown when there is no @token", async () => {
    msgBox.value = "plain text";
    msgBox.setSelectionRange(10, 10);
    await refreshMentions();
    expect(document.getElementById("mention-suggestions").style.display).toBe(
      "none",
    );
  });
});

// ── Mentions channel ──────────────────────────────────────────────────────────
describe("mentions channel", () => {
  beforeAll(() => {
    // DOM the mentions view / sidebar entry touch.
    for (const id of [
      "sidebar-dynamic",
      "chat",
      "chan",
      "typing-indicator",
      "private-ch-name-bar",
      "members-btn",
      "call-btn",
      "topbar-share-btn",
      "input",
    ]) {
      const el = document.createElement("div");
      el.id = id;
      document.body.appendChild(el);
    }
    const hash = document.createElement("span");
    hash.className = "chan-hash";
    document.body.appendChild(hash);

    // Cross-file globals the new code calls.
    global.switchChannel = jest.fn();
    global.scrollToMsg = jest.fn();
    global.updateSidebarActive = jest.fn();
    global.cancelReply = jest.fn();
    global.closeSidebar = jest.fn();
    // setChannel lives in chat.html's inline script; mirror its behaviour of
    // updating the shared `channel` global so assertions can read it back.
    global.setChannel = jest.fn((c) => {
      global.channel = c;
    });
    global.userColor = jest.fn(() => "#abc");
    global.formatText = jest.fn((t) => t);
    global._searchChannelLabel = jest.fn((ch) => `label:${ch}`);
  });

  beforeEach(() => {
    global.channel = "general";
    mentionItems = [];
    document.getElementById("sidebar-dynamic").innerHTML = "";
    document.getElementById("chat").innerHTML = "";
    document.getElementById("input").style.display = "";
  });

  test("renderMentionsSidebar adds a badge with the unread count", () => {
    mentionItems = [
      { id: 1, channel: "general", sender: "bob", content: "hi @alice", ts: 1 },
      { id: 2, channel: "general", sender: "bob", content: "yo @alice", ts: 2 },
    ];
    renderMentionsSidebar();
    const item = document.getElementById("mentions-sidebar-item");
    expect(item).not.toBeNull();
    expect(item.dataset.channel).toBe(MENTIONS_CHANNEL);
    expect(item.querySelector(".unread-badge").textContent).toBe("2");
  });

  test("renderMentionsSidebar removes the entry when there are no mentions", () => {
    mentionItems = [
      { id: 1, channel: "general", sender: "bob", content: "hi", ts: 1 },
    ];
    renderMentionsSidebar();
    expect(document.getElementById("mentions-sidebar-item")).not.toBeNull();
    mentionItems = [];
    renderMentionsSidebar();
    expect(document.getElementById("mentions-sidebar-item")).toBeNull();
  });

  test("renderMentionsSidebar pins the entry to the top of the sidebar", () => {
    const sb = document.getElementById("sidebar-dynamic");
    sb.appendChild(document.createElement("b")); // pre-existing content
    mentionItems = [
      { id: 1, channel: "general", sender: "bob", content: "hi @alice", ts: 1 },
    ];
    renderMentionsSidebar();
    expect(sb.firstChild.id).toBe("mentions-sidebar-item");
  });

  test("renderMentionsView lists each mention as a clickable card", () => {
    mentionItems = [
      {
        id: 7,
        channel: "general",
        sender: "bob",
        content: "look @alice",
        ts: 1,
      },
    ];
    renderMentionsView();
    const cards = document.querySelectorAll(".mention-list-item");
    expect(cards.length).toBe(1);
    expect(cards[0].textContent).toContain("bob");
    expect(cards[0].textContent).toContain("label:general");
    cards[0].onclick();
    expect(switchChannel).toHaveBeenCalledWith("general");
  });

  test("renderMentionsView shows an empty state when there are no mentions", () => {
    mentionItems = [];
    renderMentionsView();
    expect(document.querySelector(".mentions-empty")).not.toBeNull();
  });

  test("_goToMention switches channel then scrolls to the message", () => {
    jest.useFakeTimers();
    _goToMention("dm:alice:bob", 42);
    expect(switchChannel).toHaveBeenCalledWith("dm:alice:bob");
    jest.runAllTimers();
    expect(scrollToMsg).toHaveBeenCalledWith(42);
    jest.useRealTimers();
  });

  test("openMentionsChannel hides the composer and renders the view", () => {
    mentionItems = [
      { id: 1, channel: "general", sender: "bob", content: "hi @alice", ts: 1 },
    ];
    openMentionsChannel();
    expect(channel).toBe(MENTIONS_CHANNEL);
    expect(document.getElementById("input").style.display).toBe("none");
    expect(document.getElementById("chan").innerText).toBe("Mentions");
    expect(document.querySelectorAll(".mention-list-item").length).toBe(1);
  });

  test("fetchMentions caches the payload and refreshes the sidebar", async () => {
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: () =>
        Promise.resolve([
          {
            id: 1,
            channel: "general",
            sender: "bob",
            content: "@alice",
            ts: 1,
          },
        ]),
    });
    await fetchMentions();
    expect(mentionItems.length).toBe(1);
    expect(document.getElementById("mentions-sidebar-item")).not.toBeNull();
  });
});
