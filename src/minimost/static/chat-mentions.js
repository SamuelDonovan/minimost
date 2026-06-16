// chat-mentions.js
// ================
// @-mention support: an autocomplete dropdown over the message box that lists
// the other members of the current channel, plus rendering of @username pills
// and highlighting of messages that mention the current user.
//
// Mention storage and validation happen server-side (see chat.extract_mentions
// and the /channel_members endpoint); this file is purely the client UI.

// Lowercased-username -> canonical-username, used to decide whether an @token
// in a message is a real user (and therefore should render as a pill).
const KNOWN_USERS = new Map();

function registerKnownUser(name) {
  if (name) KNOWN_USERS.set(name.toLowerCase(), name);
}

// Resolve an @token to its canonical username, or null if not a known user.
function mentionLookup(name) {
  return KNOWN_USERS.get((name || "").toLowerCase()) || null;
}

// Seed the known-user map from /users (everyone but me) plus myself, so pills
// render even before the mention dropdown has fetched a channel's members.
registerKnownUser(CURRENT_USER);
fetch("/users")
  .then((r) => (r.ok ? r.json() : []))
  .then((users) => users.forEach(registerKnownUser))
  .catch(() => {});

// Wrap @username tokens (for known users only) in styled pills. Operates on
// already-escaped+linkified HTML; the leading-character capture group keeps us
// from matching inside emails (foo@bar) and URLs (.../@handle). The reserved
// keyword @everyone always renders as a pill.
function applyMentionPills(html) {
  return html.replace(/(^|[^\w@/])@([A-Za-z0-9_-]+)/g, (full, pre, name) => {
    if (name.toLowerCase() === "everyone") {
      return `${pre}<span class="mention mention-me mention-everyone">@everyone</span>`;
    }
    const real = mentionLookup(name);
    if (!real) return full;
    const meClass = real === CURRENT_USER ? " mention-me" : "";
    return `${pre}<span class="mention${meClass}">@${real}</span>`;
  });
}

// True if message m mentions the current user (m.mentions is a JSON array
// string produced by the backend). The "@everyone" sentinel mentions the
// whole channel, but not the sender's own copy.
function isMentioned(m) {
  if (!m.mentions) return false;
  let list;
  try {
    list = JSON.parse(m.mentions);
  } catch {
    return false;
  }
  if (list.includes("@everyone")) return m.sender !== CURRENT_USER;
  return list.includes(CURRENT_USER);
}

// Fire a native OS notification for a message that mentions the current user.
// Unlike the unread-message notification, this fires even when the page is
// focused (a mention is worth surfacing immediately). Honors the native
// notification toggle and the browser permission; the sound is handled
// separately by the caller so it can honor the sound toggle.
function notifyMention(m) {
  if (!nativeNotifEnabled) return;
  if (!("Notification" in globalThis) || Notification.permission !== "granted")
    return;
  globalThis.lastMentionNotifAt = Date.now();
  const n = new Notification(`${m.sender} mentioned you — MiniMost`, {
    body: (m.content || "").slice(0, 140),
    icon: "/static/web-app-manifest-192x192.png",
    tag: "minimost-mention",
    renotify: true,
  });
  n.onclick = () => {
    globalThis.focus();
    n.close();
  };
}

// --- Autocomplete dropdown ---------------------------------------------------

const mentionBox = document.getElementById("mention-suggestions");

let mentionMembers = []; // members of mentionMembersChannel
let mentionMembersChannel = null; // channel mentionMembers was fetched for
let mentionMatches = []; // currently displayed candidate usernames
let mentionIndex = -1; // highlighted suggestion (-1 = none)
let mentionStart = -1; // caret offset of the '@' being completed

// Fetch (and cache) the mentionable members for the active channel.
async function ensureMentionMembers() {
  if (mentionMembersChannel === channel) return;
  mentionMembersChannel = channel;
  try {
    const r = await fetch(`/channel_members/${channel}`);
    mentionMembers = r.ok ? await r.json() : [];
  } catch {
    mentionMembers = [];
  }
  mentionMembers.forEach(registerKnownUser);
}

function hideMentions() {
  mentionBox.style.display = "none";
  mentionIndex = -1;
  mentionStart = -1;
  mentionMatches = [];
}

function updateMentionHighlight() {
  Array.from(mentionBox.children).forEach((el, i) => {
    el.classList.toggle("active", i === mentionIndex);
    if (i === mentionIndex) el.scrollIntoView({ block: "nearest" });
  });
}

// Inspect the text before the caret; if it ends in an @token, return
// {start, query}, otherwise null. A mention token starts at the beginning of
// the line or after whitespace.
function activeMentionToken() {
  const caret = msgBox.selectionStart;
  if (caret !== msgBox.selectionEnd) return null; // ignore active selections
  const before = msgBox.value.slice(0, caret);
  const match = /(?:^|\s)@([A-Za-z0-9_-]*)$/.exec(before);
  if (!match) return null;
  return { start: caret - match[1].length - 1, query: match[1] };
}

async function refreshMentions() {
  const token = activeMentionToken();
  if (!token) {
    hideMentions();
    return;
  }

  await ensureMentionMembers();
  // The channel may have changed while awaiting; re-validate the token.
  const current = activeMentionToken();
  if (!current) {
    hideMentions();
    return;
  }

  mentionStart = current.start;
  const q = current.query.toLowerCase();
  // "everyone" is offered alongside the real members as a channel-wide ping.
  const candidates = ["everyone", ...mentionMembers];
  const ranked = candidates
    .map((u) => ({
      user: u,
      result: q ? fuzzySearch(q, u) : { score: 0, indices: [] },
    }))
    .filter(({ result }) => result !== null)
    .sort((a, b) => b.result.score - a.result.score);

  mentionMatches = ranked.map((m) => m.user);
  if (!mentionMatches.length) {
    hideMentions();
    return;
  }

  mentionBox.innerHTML = "";
  ranked.forEach(({ user, result }, idx) => {
    const div = document.createElement("div");
    div.className = "autocomplete-suggestion mention-suggestion";
    const label = document.createElement("span");
    if (user === "everyone") {
      div.classList.add("mention-suggestion-everyone");
      const icon = document.createElement("span");
      icon.className = "mention-everyone-icon";
      icon.textContent = "@";
      div.appendChild(icon);
      label.innerHTML = `${highlightFuzzyMatch("everyone", result.indices)}<span class="mention-suggestion-hint">Notify the whole channel</span>`;
    } else {
      div.appendChild(makeAvatarWrap(user, 22, null, false));
      label.innerHTML = highlightFuzzyMatch(user, result.indices);
    }
    div.appendChild(label);
    div.onmousedown = (e) => {
      e.preventDefault(); // keep focus in the textarea
      acceptMention(idx);
    };
    mentionBox.appendChild(div);
  });

  mentionIndex = 0;
  updateMentionHighlight();
  mentionBox.style.display = "block";
}

// Replace the @token under the caret with the chosen username + trailing space.
function acceptMention(idx) {
  const user = mentionMatches[idx];
  if (user === undefined || mentionStart < 0) return;
  const caret = msgBox.selectionStart;
  const before = msgBox.value.slice(0, mentionStart);
  const after = msgBox.value.slice(caret);
  const insert = `@${user} `;
  msgBox.value = before + insert + after;
  const pos = before.length + insert.length;
  msgBox.setSelectionRange(pos, pos);
  hideMentions();
  updateSendState();
  msgBox.focus();
}

msgBox.addEventListener("input", refreshMentions);
msgBox.addEventListener("click", refreshMentions);

// Capture-phase so this runs before the bubble-phase send-on-Enter handler:
// while the dropdown is open, Enter/Tab accept and arrows navigate instead.
msgBox.addEventListener(
  "keydown",
  (e) => {
    if (mentionBox.style.display !== "block" || !mentionMatches.length) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      e.stopPropagation();
      mentionIndex = (mentionIndex + 1) % mentionMatches.length;
      updateMentionHighlight();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      e.stopPropagation();
      mentionIndex =
        (mentionIndex - 1 + mentionMatches.length) % mentionMatches.length;
      updateMentionHighlight();
    } else if (e.key === "Enter" || e.key === "Tab") {
      e.preventDefault();
      e.stopPropagation();
      acceptMention(Math.max(mentionIndex, 0));
    } else if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      hideMentions();
    }
  },
  true,
);

msgBox.addEventListener("blur", () => setTimeout(hideMentions, 100));

// --- Mentions channel --------------------------------------------------------
// A virtual "Mentions" entry in the sidebar that lists every unread message
// mentioning the current user (across all channels they can read), newest
// first. Clicking a listed message jumps to it in its real channel; reading the
// real channel advances that channel's read watermark, so the mention drops off
// the list on the next poll. Viewing this list never marks anything read.
//
// MENTIONS_CHANNEL is a sentinel that never reaches the /messages backend —
// switchChannel and fetchMessages special-case it (see chat.html).
const MENTIONS_CHANNEL = "mentions";

// Latest /mentions payload, shared between the sidebar badge and the list view.
let mentionItems = [];

// Poll /mentions, refresh the sidebar entry, and (if the view is open) re-render
// it so read mentions disappear live.
function fetchMentions() {
  return fetch("/mentions")
    .then((r) => (r.ok ? r.json() : []))
    .then((items) => {
      mentionItems = items;
      renderMentionsSidebar();
      if (channel === MENTIONS_CHANNEL) renderMentionsView();
    })
    .catch(() => {});
}

// Insert/update the single "Mentions" sidebar entry at the top of the dynamic
// sidebar. Hidden entirely when there are no unread mentions.
function renderMentionsSidebar() {
  const sb = document.getElementById("sidebar-dynamic");
  if (!sb) return;
  let item = document.getElementById("mentions-sidebar-item");

  if (!mentionItems.length) {
    item?.remove();
    // If the user is parked on an emptied Mentions view, reflect that.
    if (channel === MENTIONS_CHANNEL) renderMentionsView();
    return;
  }

  if (!item) {
    item = document.createElement("div");
    item.className = "sidebar-item";
    item.id = "mentions-sidebar-item";
    item.dataset.channel = MENTIONS_CHANNEL;
    item.onpointerup = (e) => {
      e.preventDefault();
      switchChannel(MENTIONS_CHANNEL);
    };
  }
  // Always keep it pinned to the very top, even after a sidebar rebuild.
  if (sb.firstChild !== item) sb.insertBefore(item, sb.firstChild);

  item.innerHTML = "";
  const labelSpan = document.createElement("span");
  labelSpan.className = "label";
  labelSpan.textContent = "@ Mentions";
  item.appendChild(labelSpan);

  const badge = document.createElement("span");
  badge.className = "unread-badge";
  badge.textContent = mentionItems.length;
  item.appendChild(badge);

  if (channel === MENTIONS_CHANNEL) item.classList.add("active");
}

// Switch the main pane to the read-only Mentions list. Hides the composer and
// channel-specific controls (you can't post to or call within Mentions).
function openMentionsChannel() {
  if (globalThis.fetchController) {
    globalThis.fetchController.abort();
    globalThis.fetchController = null;
  }
  cancelReply();
  setChannel(MENTIONS_CHANNEL);
  closeSidebar();

  document.getElementById("chat").innerHTML = "";
  const ti = document.getElementById("typing-indicator");
  if (ti) {
    ti.innerHTML = "";
    ti.className = "";
  }

  document.getElementById("chan").innerText = "Mentions";
  const chanHash = document.querySelector(".chan-hash");
  if (chanHash) chanHash.style.visibility = "hidden";
  const nameBar = document.getElementById("private-ch-name-bar");
  if (nameBar) nameBar.style.display = "none";
  const membersBtn = document.getElementById("members-btn");
  if (membersBtn) membersBtn.style.display = "none";
  document.getElementById("call-btn").style.display = "none";
  document.getElementById("topbar-share-btn").style.display = "none";
  document.getElementById("input").style.display = "none";

  renderMentionsView();
  updateSidebarActive();
}

// Render the cached mentions as a list of read-only cards into #chat. Clicking a
// card jumps to the real message. Empty state covers the list clearing while the
// user is looking at it.
function renderMentionsView() {
  const chat = document.getElementById("chat");
  if (!chat) return;
  chat.innerHTML = "";

  if (!mentionItems.length) {
    const empty = document.createElement("div");
    empty.className = "mentions-empty";
    empty.textContent = "No unread mentions";
    chat.appendChild(empty);
    return;
  }

  mentionItems.forEach((m) => {
    const card = document.createElement("div");
    card.className = "mention-list-item";
    card.onclick = () => _goToMention(m.channel, m.id);

    const avatar = makeAvatarWrap(m.sender, 32);
    card.appendChild(avatar);

    const col = document.createElement("div");
    col.className = "mention-list-col";

    const meta = document.createElement("div");
    meta.className = "mention-list-meta";
    const name = document.createElement("span");
    name.className = "mention-list-sender";
    name.style.color = userColor(m.sender);
    name.textContent = m.sender;
    const chan = document.createElement("span");
    chan.className = "mention-list-chan";
    chan.textContent = _searchChannelLabel(m.channel);
    const when = document.createElement("span");
    when.className = "mention-list-time";
    when.textContent = new Date(m.ts * 1000).toLocaleString([], {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
    meta.appendChild(name);
    meta.appendChild(chan);
    meta.appendChild(when);
    col.appendChild(meta);

    const body = document.createElement("div");
    body.className = "mention-list-text";
    if (m.content?.trim()) {
      body.innerHTML = applyMentionPills(formatText(m.content));
    } else if (m.filename) {
      body.textContent = "📎 attachment";
    }
    col.appendChild(body);

    card.appendChild(col);
    chat.appendChild(card);
  });
}

// Jump to a mentioned message in its real channel. switchChannel marks that
// channel read (so the mention clears on the next poll); the short delay lets
// the channel's messages render before we scroll. Mirrors _goToSearchResult.
function _goToMention(ch, id) {
  switchChannel(ch);
  setTimeout(() => scrollToMsg(id), 200);
}
