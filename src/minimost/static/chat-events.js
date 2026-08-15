// Server-Sent Events client.
//
// One long-lived EventSource connection replaces the dozen interval pollers the
// app used to run. The server (minimost.events) holds GET /events open and
// pushes a named event whenever the relevant shared state changes; each handler
// below hands the payload to the very same render function the old poller used,
// so the UI behaviour is unchanged — only the transport differs.
//
// The stream is scoped to the open channel for message/typing/read-receipt/
// screen-share events, so connectEvents() is re-invoked on every channel switch
// to re-point it. The browser's native EventSource reconnects automatically
// after a dropped connection or the server's periodic stream recycle.

let _eventSource = null;

// ── Connection status ───────────────────────────────────────────────────────
// EventSource reconnects silently, which is the right transport behaviour but
// the wrong user experience: a server that has gone down looks identical to a
// channel where nobody is talking. The banner is only raised once a reconnect
// has actually failed to land, so the server's routine stream recycle — which
// briefly trips onerror every few minutes — never flashes it.
//
// The grace comfortably clears the server's `retry: 3000`, so an ordinary
// recycle reconnects well inside it. The instant case is covered separately by
// the browser's own `offline` event, which needs no waiting.
const _RECONNECT_GRACE_MS = 8000;
let _connGraceTimer = null;

function _setConnectionBanner(down) {
  const banner = document.getElementById("connection-banner");
  if (banner) banner.hidden = !down;
}

// Call when a frame arrives or the stream opens: the link is demonstrably up.
function _markConnected() {
  clearTimeout(_connGraceTimer);
  _connGraceTimer = null;
  _setConnectionBanner(false);
}

// Call when the stream errors. Waits out the grace period before complaining,
// so only an outage the user could actually notice raises the banner.
function _markMaybeDisconnected() {
  if (_connGraceTimer) return;
  _connGraceTimer = setTimeout(() => {
    _connGraceTimer = null;
    _setConnectionBanner(true);
  }, _RECONNECT_GRACE_MS);
}

// The browser knowing it is offline is immediate and certain — no grace needed.
globalThis.addEventListener?.("offline", () => {
  clearTimeout(_connGraceTimer);
  _connGraceTimer = null;
  _setConnectionBanner(true);
});
globalThis.addEventListener?.("online", () => {
  // Don't clear the banner yet: being back on a network is not the same as the
  // server answering. Re-open the stream and let its onopen confirm.
  connectEvents();
});

// Parse an event payload and forward it to a render function, swallowing a
// malformed frame rather than letting it throw out of the event loop.
function _bindEvent(es, name, handler) {
  es.addEventListener(name, (e) => {
    // Any frame at all proves the stream is alive, even one that fails to
    // parse — that is a payload problem, not a connectivity one.
    _markConnected();
    let data;
    try {
      data = JSON.parse(e.data);
    } catch {
      return;
    }
    handler(data);
  });
}

function connectEvents() {
  // Ancient browsers without EventSource keep working via the one-shot loads in
  // switchChannel/loadSidebar; they just won't receive live push updates.
  if (typeof EventSource === "undefined") return;

  closeEvents();

  // Capture the channel this stream is opened for; message events render only
  // into it, so a late frame after a channel switch is dropped by applyMessages.
  const streamChannel = channel;
  const params = new URLSearchParams({
    channel: streamChannel || "",
    after: String(lastTs || 0),
  });
  const es = new EventSource(`/events?${params.toString()}`);
  _eventSource = es;

  // Channel-scoped events.
  _bindEvent(es, "messages", (d) => applyMessages(d, streamChannel));
  _bindEvent(es, "typing", applyTyping);
  _bindEvent(es, "read_receipts", applyReadReceipts);
  _bindEvent(es, "screenshares", applyScreenShares);
  _bindEvent(es, "active_call", applyActiveCall);

  // Global events, independent of the open channel.
  _bindEvent(es, "online_users", applyOnlineUsers);
  _bindEvent(es, "dms", applyDMs);
  _bindEvent(es, "channel_unreads", applyChannelUnreads);
  _bindEvent(es, "private_channels", applyPrivateChannels);
  _bindEvent(es, "mentions", applyMentions);
  _bindEvent(es, "unread_count", applyUnreadCount);
  _bindEvent(es, "incoming_calls", applyIncomingCalls);

  es.onopen = _markConnected;

  es.onerror = () => {
    if (_eventSource === es) _markMaybeDisconnected();
    // A normal stream end (the server recycles each stream every few minutes)
    // leaves readyState === CONNECTING and EventSource reconnects on its own
    // using the server-sent `retry:` interval. Only a hard CLOSED state needs a
    // manual re-open, and only if this is still the active stream.
    if (es.readyState === EventSource.CLOSED && _eventSource === es) {
      _eventSource = null;
      setTimeout(connectEvents, 3000);
    }
  };
}

function closeEvents() {
  if (_eventSource) {
    _eventSource.close();
    _eventSource = null;
  }
}

// Expose globals for the inline switchChannel handler in chat.html.
globalThis.connectEvents = connectEvents;
globalThis.closeEvents = closeEvents;
