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

// Parse an event payload and forward it to a render function, swallowing a
// malformed frame rather than letting it throw out of the event loop.
function _bindEvent(es, name, handler) {
  es.addEventListener(name, (e) => {
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

  // Global events, independent of the open channel.
  _bindEvent(es, "online_users", applyOnlineUsers);
  _bindEvent(es, "dms", applyDMs);
  _bindEvent(es, "channel_unreads", applyChannelUnreads);
  _bindEvent(es, "private_channels", applyPrivateChannels);
  _bindEvent(es, "mentions", applyMentions);
  _bindEvent(es, "unread_count", applyUnreadCount);
  _bindEvent(es, "incoming_calls", applyIncomingCalls);

  es.onerror = () => {
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
