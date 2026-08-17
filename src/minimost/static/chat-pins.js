// Pinned messages.
//
// A pin belongs to the channel, not to the person who set it: everyone in the
// channel sees the same list and any member may unpin. That makes the server
// the only source of truth here — this file never mutates the list locally.
// Every path (pinning, unpinning, someone else pinning) ends the same way: the
// POST's own response, or the `pins` SSE event, hands back the channel's whole
// list and applyPins() repaints from it.
//
// Three surfaces render from that one payload:
//   * the topbar button's count badge,
//   * the dropdown panel listing each pin (click to jump to it), and
//   * a "Pinned" marker on the message itself, where it is in the transcript.

let pinnedMessages = [];
// message id -> pin, for the O(1) lookups the marker repaint needs. A Map
// rather than a Set of ids because the marker names who pinned it.
let pinsById = new Map();

// Same glyph as the topbar button and the per-message action, so the three read
// as one feature.
const PIN_MARKER_SVG =
  '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" fill="currentColor" viewBox="0 0 16 16" aria-hidden="true">' +
  '<path d="M4.146.146A.5.5 0 0 1 4.5 0h7a.5.5 0 0 1 .5.5c0 .68-.342 1.174-.646 1.479-.126.125-.25.224-.354.298v4.431l.078.048c.203.127.476.314.751.555C12.36 7.775 13 8.527 13 9.5a.5.5 0 0 1-.5.5h-4v4.5c0 .276-.224 1.5-.5 1.5s-.5-1.224-.5-1.5V10h-4a.5.5 0 0 1-.5-.5c0-.973.64-1.725 1.17-2.189A6 6 0 0 1 5 6.708V2.277a3 3 0 0 1-.354-.298C4.342 1.674 4 1.179 4 .5a.5.5 0 0 1 .146-.354"/>' +
  "</svg>";

const pinsWrap = document.getElementById("topbar-pins");
const pinsBtn = document.getElementById("pins-btn");
const pinsCount = document.getElementById("pins-count");
const pinsList = document.getElementById("pins-list");

// ── Rendering ────────────────────────────────────────────────────────────────

// The button is hidden entirely at zero rather than shown with a 0 badge: an
// empty channel should not carry a control that can only report emptiness.
function _renderPinsButton() {
  if (!pinsBtn) return;
  const n = pinnedMessages.length;
  pinsBtn.style.display = n ? "" : "none";
  if (pinsCount) pinsCount.textContent = n ? String(n) : "";
  pinsBtn.title = n === 1 ? "1 pinned message" : `${n} pinned messages`;
  pinsBtn.setAttribute("aria-label", pinsBtn.title);
}

function _pinRowHtml(pin) {
  const when = new Date(pin.pinned_ts * 1000).toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
  let preview;
  if (pin.content?.trim()) {
    preview = escapeHtml(messagePreviewText(pin.content, 140));
  } else if (pin.filename) {
    preview = "<em>[attachment]</em>";
  } else {
    preview = "<em>[no text]</em>";
  }
  return (
    `<div class="pin-item-meta">` +
    `<b>${escapeHtml(pin.sender)}</b> · pinned by ${escapeHtml(pin.pinned_by)} · ${when}` +
    `</div>` +
    `<div class="pin-item-text">${preview}</div>`
  );
}

function renderPins() {
  if (!pinsList) return;
  pinsList.innerHTML = "";

  if (!pinnedMessages.length) {
    const empty = document.createElement("div");
    empty.className = "pins-empty";
    empty.textContent = "Nothing pinned here yet";
    pinsList.appendChild(empty);
    return;
  }

  pinnedMessages.forEach((pin) => {
    const row = document.createElement("div");
    row.className = "pin-item";
    row.dataset.msgId = String(pin.id);
    row.innerHTML = _pinRowHtml(pin);

    // Unpin lives on the row rather than only on the message, so a pin whose
    // message has scrolled out of the loaded window can still be removed
    // without hunting for it first.
    const unpin = document.createElement("button");
    unpin.className = "pin-item-unpin";
    unpin.type = "button";
    unpin.title = "Unpin";
    unpin.setAttribute("aria-label", `Unpin message from ${pin.sender}`);
    unpin.textContent = "×";
    unpin.onclick = (e) => {
      // Without this the row's own handler fires too and jumps to the message
      // the user just asked to remove from the list.
      e.stopPropagation();
      togglePin(pin.id);
    };
    row.appendChild(unpin);

    row.onclick = () => {
      closePinsPanel();
      revealMessage(pin.channel, pin.id, pin.ts);
    };
    pinsList.appendChild(row);
  });
}

// Add or remove the "Pinned by X" caption above a message's body. Lives in
// .msg-content-col rather than the header because a grouped message's header is
// positioned out to the top-right corner, where a caption would land on top of
// the text of the message above it.
function _setPinMarker(el, pin) {
  const col = el.querySelector(".msg-content-col");
  if (!col) return;
  let marker = col.querySelector(".pin-marker");
  if (!pin) {
    marker?.remove();
    return;
  }
  if (!marker) {
    marker = document.createElement("div");
    marker.className = "pin-marker";
    marker.innerHTML = PIN_MARKER_SVG;
    marker.appendChild(document.createTextNode(""));
    // Above the body, below the header. insertBefore(node, null) appends, so a
    // message somehow rendered without a body still gets its marker.
    col.insertBefore(marker, col.querySelector(".msg-body"));
  }
  // Written as a text node, never as markup: pinned_by is a username.
  marker.lastChild.nodeValue = `Pinned by ${pin.pinned_by}`;
}

// Toggle the pinned state shown on the messages themselves. Pass *nodes* to
// paint only a freshly rendered batch; with no argument every loaded message is
// re-checked, which is what a change to the pin list needs. Both are bounded by
// the loaded window, the same reasoning rebuildDateDividers() runs on.
function paintPinMarkers(nodes = null) {
  const els = nodes || document.querySelectorAll("#chat .msg:not(.system-msg)");
  els.forEach((el) => {
    // The append path hands over its whole tail, which includes date dividers.
    if (!el.classList?.contains("msg")) return;
    const pin = pinsById.get(Number(el.id.replace("msg-", "")));
    el.classList.toggle("pinned", !!pin);
    _setPinMarker(el, pin);
    const btn = el.querySelector(".pin-btn");
    if (btn) {
      btn.classList.toggle("active", !!pin);
      btn.title = pin ? "Unpin" : "Pin to channel";
      btn.setAttribute("aria-pressed", String(!!pin));
    }
  });
}

// ── Server state ─────────────────────────────────────────────────────────────

// Entry point for both the SSE `pins` event and the one-shot fetch on channel
// switch. *forChannel* is the channel the payload was requested for; a payload
// whose channel is no longer the open one is dropped rather than painted, which
// is what stops an in-flight response landing after a channel switch. It
// defaults to the open channel, i.e. "this list is for what is on screen now".
function applyPins(data, forChannel = channel) {
  if (forChannel !== channel) return;
  pinnedMessages = Array.isArray(data) ? data : [];
  pinsById = new Map(pinnedMessages.map((p) => [p.id, p]));
  _renderPinsButton();
  paintPinMarkers();
  // Only rebuild the list while it is on screen; otherwise the next open does
  // it. Rebuilding a hidden panel would also drop the user's scroll position
  // in it for no visible gain.
  if (pinsWrap?.classList.contains("open")) renderPins();
  // A channel whose last pin just went away has nothing left to show.
  if (!pinnedMessages.length) closePinsPanel();
}

// First paint for a channel. The SSE stream pushes every later change, so this
// runs once per switch rather than on a timer.
function refreshPins() {
  const requested = channel;
  // Clear immediately: the outgoing channel's pins must not linger in the
  // badge or on screen while this request is in flight.
  pinnedMessages = [];
  pinsById = new Map();
  _renderPinsButton();
  closePinsPanel();

  return fetch(`/pins/${encodeURIComponent(requested)}`)
    .then((r) => (r.ok ? r.json() : null))
    .then((data) => {
      if (data) applyPins(data, requested);
    })
    .catch(() => {
      // A failed first load is self-correcting: the SSE stream pushes the
      // channel's pins on the next change, and the connection banner is what
      // reports a link that is actually down.
    });
}

function togglePin(msgId) {
  const id = Number(msgId);
  // Captured now, not read when the response lands: a user who pins and then
  // immediately switches channel would otherwise have the outgoing channel's
  // list painted over the incoming one.
  const requested = channel;
  return fetch(`/pin/${id}`, { method: "POST" })
    .then((r) => {
      if (r.status === 409) {
        showToast("This channel has reached its pin limit — unpin one first");
        return null;
      }
      if (!r.ok) {
        showToast("Could not pin that message");
        return null;
      }
      return r.json();
    })
    .then((data) => {
      if (!data) return;
      // The response is the authoritative post-toggle list, so paint from it
      // rather than waiting for the stream to come round.
      const wasPinned = pinsById.has(id);
      applyPins(data, requested);
      // Confirm only what the user is still looking at; the toast for a channel
      // they have left would be noise about somewhere else.
      if (requested === channel) {
        showToast(wasPinned ? "Message unpinned" : "Message pinned");
      }
    })
    .catch(() => showToast("Could not pin that message"));
}

// ── Panel ────────────────────────────────────────────────────────────────────

function openPinsPanel() {
  if (!pinsWrap || pinsWrap.classList.contains("open")) return;
  renderPins();
  pinsWrap.classList.add("open");
  pinsBtn?.setAttribute("aria-expanded", "true");
}

function closePinsPanel() {
  if (!pinsWrap?.classList.contains("open")) return;
  pinsWrap.classList.remove("open");
  pinsBtn?.setAttribute("aria-expanded", "false");
}

function togglePinsPanel() {
  if (pinsWrap?.classList.contains("open")) closePinsPanel();
  else openPinsPanel();
}

// Click anywhere outside closes the panel, matching the search panel and the
// emoji pickers.
document.addEventListener("click", (e) => {
  if (!pinsWrap?.classList.contains("open")) return;
  if (!pinsWrap.contains(e.target)) closePinsPanel();
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closePinsPanel();
});

// Referenced from inline onclick handlers in chat.html and from the visual-mode
// key handler in chat-search.js, both of which resolve against globalThis.
globalThis.togglePin = togglePin;
globalThis.togglePinsPanel = togglePinsPanel;
globalThis.applyPins = applyPins;
globalThis.refreshPins = refreshPins;
globalThis.paintPinMarkers = paintPinMarkers;
globalThis.closePinsPanel = closePinsPanel;
