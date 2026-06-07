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
  lastMentionNotifAt = Date.now();
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
