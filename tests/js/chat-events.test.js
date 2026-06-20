/**
 * Tests for chat-events.js (the Server-Sent Events client).
 */

const { loadScript } = require("./loadScript");

// Minimal EventSource stand-in: records the URL, captures handlers registered
// with addEventListener, and lets a test synthesise incoming events.
class FakeEventSource {
  constructor(url) {
    this.url = url;
    this.readyState = 0; // CONNECTING
    this.handlers = {};
    this.closed = false;
    FakeEventSource.instances.push(this);
  }
  addEventListener(name, fn) {
    this.handlers[name] = fn;
  }
  close() {
    this.readyState = FakeEventSource.CLOSED;
    this.closed = true;
  }
  emit(name, data) {
    if (this.handlers[name]) this.handlers[name]({ data });
  }
}
FakeEventSource.CLOSED = 2;
FakeEventSource.instances = [];

const APPLY_FNS = [
  "applyMessages",
  "applyTyping",
  "applyReadReceipts",
  "applyScreenShares",
  "applyOnlineUsers",
  "applyDMs",
  "applyChannelUnreads",
  "applyPrivateChannels",
  "applyMentions",
  "applyUnreadCount",
  "applyIncomingCalls",
];

beforeAll(() => {
  global.EventSource = FakeEventSource;
  loadScript("chat-events.js");
});

beforeEach(() => {
  FakeEventSource.instances = [];
  APPLY_FNS.forEach((name) => {
    global[name] = jest.fn();
  });
  global.channel = "general";
  global.lastTs = 0;
});

function lastStream() {
  return FakeEventSource.instances[FakeEventSource.instances.length - 1];
}

describe("connectEvents()", () => {
  test("opens /events scoped to the current channel and cursor", () => {
    global.channel = "general";
    global.lastTs = 42;
    connectEvents();
    expect(lastStream().url).toBe("/events?channel=general&after=42");
  });

  test("closes a previous stream when reconnecting", () => {
    connectEvents();
    const first = lastStream();
    connectEvents();
    expect(first.closed).toBe(true);
    expect(lastStream()).not.toBe(first);
  });

  test("routes a messages event to applyMessages with the stream's channel", () => {
    global.channel = "general";
    connectEvents();
    lastStream().emit("messages", JSON.stringify([{ id: 1 }]));
    expect(applyMessages).toHaveBeenCalledWith([{ id: 1 }], "general");
  });

  test("routes a global event to its render function", () => {
    connectEvents();
    lastStream().emit("online_users", JSON.stringify({ alice: "active" }));
    expect(applyOnlineUsers).toHaveBeenCalledWith({ alice: "active" });
  });

  test("swallows a malformed frame instead of throwing", () => {
    connectEvents();
    expect(() => lastStream().emit("dms", "not-json")).not.toThrow();
    expect(applyDMs).not.toHaveBeenCalled();
  });
});

describe("closeEvents()", () => {
  test("closes the active stream", () => {
    connectEvents();
    const es = lastStream();
    closeEvents();
    expect(es.closed).toBe(true);
  });
});
