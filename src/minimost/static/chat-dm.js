// Direct Messages
const dmModal = document.getElementById("dm-modal");
const dmUsersInput = document.getElementById("dm-users");
const dmSuggestions = document.getElementById("dm-suggestions");

dmUsersInput.addEventListener("input", updateSuggestions);

document.addEventListener("click", (e) => {
  if (!dmUsersInput.contains(e.target) && !dmSuggestions.contains(e.target)) {
    dmSuggestions.style.display = "none";
    suggestionIndex = -1;
  }
});

dmUsersInput.addEventListener("keydown", (e) => {
  const items = dmSuggestions.children;
  const suggestionsVisible = dmSuggestions.style.display === "block";
  const typingUser = isTypingUsername();

  // TAB → autocomplete
  if (e.key === "Tab" && suggestionsVisible && items.length) {
    e.preventDefault();
    selectSuggestion(Math.max(suggestionIndex, 0));
    return;
  }

  // ENTER behavior
  if (e.key === "Enter") {
    e.preventDefault();

    // If typing a username and suggestions exist → autocomplete
    if (typingUser && suggestionsVisible && items.length) {
      selectSuggestion(Math.max(suggestionIndex, 0));
      return;
    }

    // Otherwise → start DM
    document.getElementById("dm-start").click();
    return;
  }

  // Navigation only if suggestions are visible
  if (!suggestionsVisible) return;

  if (e.key === "ArrowDown") {
    e.preventDefault();
    suggestionIndex = (suggestionIndex + 1) % items.length;
    updateActiveSuggestion();
  } else if (e.key === "ArrowUp") {
    e.preventDefault();
    suggestionIndex = (suggestionIndex - 1 + items.length) % items.length;
    updateActiveSuggestion();
  } else if (e.key === "Escape") {
    dmSuggestions.style.display = "none";
    suggestionIndex = -1;
  }
});

function updateActiveSuggestion() {
  const items = dmSuggestions.children;

  Array.from(items).forEach((el, i) => {
    el.classList.toggle("active", i === suggestionIndex);
  });
}

// Shared across chat-dm.js, chat-channels.js, and chat-search.js (classic
// scripts on the same page); kept on `window` so every file references the same
// binding explicitly rather than relying on an implicit global.
globalThis.allUsers = [];
globalThis.usersLoaded = false;
let suggestionIndex = -1;

function resetDmSuggestions() {
  suggestionIndex = -1;
}
let currentSuggestions = [];

async function openDmModal() {
  openModal(dmModal, {
    label: "Start a direct message",
    focus: dmUsersInput,
  });

  // Fetch users once (or remove this guard if you want to refresh every time)
  if (!globalThis.usersLoaded) {
    try {
      const resp = await fetch("/users");
      if (resp.ok) {
        globalThis.allUsers = await resp.json();
        globalThis.usersLoaded = true;
      } else {
        console.error("Failed to fetch users");
      }
    } catch (err) {
      console.error("Error fetching users:", err);
    }
  }
}

function resetDmModal() {
  dmUsersInput.value = "";
  dmSuggestions.style.display = "none";
  suggestionIndex = -1;
}

// Fetch users when the DM modal is opened
document.getElementById("new-dm-btn").onclick = async () => {
  openDmModal();
};

function updateSuggestions() {
  if (!globalThis.usersLoaded) return;

  const raw = dmUsersInput.value;
  const parts = raw.split(",").map((p) => p.trim());
  const lastPart = parts[parts.length - 1].toLowerCase();

  suggestionIndex = -1;

  if (!lastPart) {
    dmSuggestions.style.display = "none";
    return;
  }

  const alreadyAdded = parts.slice(0, -1);
  const matches = globalThis.allUsers
    .filter((u) => !alreadyAdded.includes(u))
    .map((u) => ({ user: u, result: fuzzySearch(lastPart, u) }))
    .filter(({ result }) => result !== null)
    .sort((a, b) => b.result.score - a.result.score);

  currentSuggestions = matches.map((m) => m.user);

  if (!currentSuggestions.length) {
    dmSuggestions.style.display = "none";
    return;
  }

  dmSuggestions.innerHTML = "";

  matches.forEach(({ user, result }, idx) => {
    const div = document.createElement("div");
    div.className = "autocomplete-suggestion";
    div.innerHTML = highlightFuzzyMatch(user, result.indices);
    div.onclick = () => selectSuggestion(idx);
    dmSuggestions.appendChild(div);
  });

  dmSuggestions.style.display = "block";
}

function focusMessageInput() {
  // ✅ Scroll chat to bottom
  const chatContainer = document.getElementById("chat");
  if (chatContainer) {
    chatContainer.scrollTop = chatContainer.scrollHeight;
  }
  setTimeout(() => {
    const msgInput = document.getElementById("msg");
    if (msgInput) {
      msgInput.focus();
      // Place cursor at the end of any existing text
      msgInput.setSelectionRange(msgInput.value.length, msgInput.value.length);
    }
  }, 10); // Slight delay ensures DOM updates (e.g., fetchMessages) are complete
}

function isTypingUsername() {
  const parts = dmUsersInput.value.split(",");
  const last = parts[parts.length - 1];
  return last.trim().length > 0;
}

function selectSuggestion(idx) {
  const raw = dmUsersInput.value;
  const parts = raw.split(",").map((p) => p.trim());

  parts[parts.length - 1] = currentSuggestions[idx];
  dmUsersInput.value = parts.join(", ") + ", ";

  dmSuggestions.style.display = "none";
  suggestionIndex = -1;
  dmUsersInput.focus();
}

function closeDmModal() {
  closeModal(dmModal);
}

document.getElementById("dm-cancel").onclick = closeDmModal;

// DM conversations the user has opened but not yet posted to. /dms derives its
// list from the messages table, so an empty conversation has no row there and
// applyDMs() would prune it from the sidebar the moment the user navigated
// away — losing the DM with no way back except starting it over. Held here
// (and in localStorage, so a reload doesn't lose it either) until the first
// message makes the server aware of it or the user closes it.
const PENDING_DMS_KEY = `pendingDms:${CURRENT_USER}`;

function loadPendingDms() {
  try {
    const raw = localStorage.getItem(PENDING_DMS_KEY);
    return new Set(raw ? JSON.parse(raw) : []);
  } catch {
    return new Set();
  }
}

globalThis.pendingDms = loadPendingDms();

function savePendingDms() {
  try {
    localStorage.setItem(
      PENDING_DMS_KEY,
      JSON.stringify([...globalThis.pendingDms]),
    );
  } catch {
    // Storage full or blocked — the in-memory set still works for this session.
  }
}

function addPendingDm(dmChannel) {
  globalThis.pendingDms.add(dmChannel);
  savePendingDms();
}

function dropPendingDm(dmChannel) {
  if (globalThis.pendingDms.delete(dmChannel)) savePendingDms();
}

document.getElementById("dm-start").onclick = () => {
  const raw = dmUsersInput.value.trim();
  if (!raw) return;

  const typed = raw
    .split(",")
    .map((u) => u.trim())
    .filter(Boolean);

  if (!typed.length) return;

  // A DM channel is addressed by name, so a typo or the wrong capitalisation
  // ("Bob" for the account "bob") used to open a perfectly ordinary-looking
  // conversation that nobody was on the other end of. Resolve every name
  // against the real account list and refuse the ones that don't exist.
  const canonical = new Map(
    [...globalThis.allUsers, CURRENT_USER].map((u) => [u.toLowerCase(), u]),
  );
  // If /users hasn't landed yet there is nothing to check against; let it
  // through and rely on the server's own rejection rather than refusing every
  // name because the list is late.
  const unknown = globalThis.usersLoaded
    ? typed.filter((u) => !canonical.has(u.toLowerCase()))
    : [];
  if (unknown.length) {
    showToast(
      unknown.length === 1
        ? `There's no account named "${unknown[0]}".`
        : `No accounts named: ${unknown.join(", ")}.`,
    );
    return;
  }

  const users = [
    ...new Set(typed.map((u) => canonical.get(u.toLowerCase()) || u)),
  ];

  if (!users.includes(CURRENT_USER)) {
    users.push(CURRENT_USER);
  }

  if (users.length < 2) {
    showToast("Pick someone to message.");
    return;
  }

  // Sort by code unit, NOT localeCompare: the server canonicalises the same
  // channel with Python's sorted() (chat.normalize_dm), which orders by code
  // point — so "Bob" sorts before "alice". A locale-aware collation would put
  // them the other way round and build a channel name the server disagrees
  // with. Usernames are [A-Za-z0-9_-] (auth._USERNAME_RE), so code unit and
  // code point orderings coincide here.
  users.sort((a, b) => {
    if (a === b) return 0;
    return a < b ? -1 : 1;
  });

  const dmChannel = "dm:" + users.join(":");

  resetDmModal();
  closeDmModal();

  addPendingDm(dmChannel);
  refreshDMs();

  switchChannel(dmChannel);

  focusMessageInput();
};

async function closeDm(dmChannel) {
  const resp = await fetch("/dms/close", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ channel: dmChannel }),
  });
  if (!resp.ok) return;
  dropPendingDm(dmChannel);
  if (channel === dmChannel) switchChannel("general");
  document.querySelector(`[data-channel="${dmChannel}"]`)?.remove();
}

// ── Private Channel Tooltip ──────────────────────────────────────────────────

let _pcTooltipHideTimer = null;
let _pcTooltipShowTimer = null;

function _cancelPCTooltipHide() {
  if (_pcTooltipHideTimer) {
    clearTimeout(_pcTooltipHideTimer);
    _pcTooltipHideTimer = null;
  }
}

function _cancelPCTooltipShow() {
  if (_pcTooltipShowTimer) {
    clearTimeout(_pcTooltipShowTimer);
    _pcTooltipShowTimer = null;
  }
}

function _schedulePCTooltipHide() {
  _cancelPCTooltipShow();
  _cancelPCTooltipHide();
  _pcTooltipHideTimer = setTimeout(() => {
    const tooltip = document.getElementById("pc-member-tooltip");
    if (tooltip) tooltip.style.display = "none";
  }, 120);
}

function showPCTooltip(el) {
  _cancelPCTooltipShow();
  _cancelPCTooltipHide();
  const tooltip = document.getElementById("pc-member-tooltip");
  if (!tooltip) return;
  const ch = el.dataset.channel;
  const members = privateChannelMembers[ch] || [];
  if (!members.length) return;

  tooltip.innerHTML = "";
  members.forEach((username) => {
    const row = document.createElement("div");
    row.className = "tooltip-member";
    row.appendChild(makeAvatarWrap(username, 22));
    const name = document.createElement("span");
    name.textContent = username;
    row.appendChild(name);
    tooltip.appendChild(row);
  });

  const rect = el.getBoundingClientRect();
  tooltip.style.top = rect.top + "px";
  tooltip.style.left = rect.right + 6 + "px";
  tooltip.style.display = "block";
}

function hidePCTooltip() {
  const tooltip = document.getElementById("pc-member-tooltip");
  if (tooltip) tooltip.style.display = "none";
}

function bindPCTooltip(el) {
  el.onmouseenter = () => {
    _cancelPCTooltipHide();
    _pcTooltipShowTimer = setTimeout(() => {
      if (el.matches(":hover")) showPCTooltip(el);
    }, 3000);
  };
  el.onmouseleave = _schedulePCTooltipHide;
}

document.addEventListener("DOMContentLoaded", () => {
  const tooltip = document.getElementById("pc-member-tooltip");
  if (tooltip) {
    tooltip.addEventListener("mouseenter", _cancelPCTooltipHide);
    tooltip.addEventListener("mouseleave", _schedulePCTooltipHide);
  }
});
