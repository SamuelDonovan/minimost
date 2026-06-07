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
window.allUsers = [];
window.usersLoaded = false;
let suggestionIndex = -1;

function resetDmSuggestions() {
  suggestionIndex = -1;
}
let currentSuggestions = [];

async function openDmModal() {
  dmModal.style.display = "block";
  dmUsersInput.focus();

  // Fetch users once (or remove this guard if you want to refresh every time)
  if (!window.usersLoaded) {
    try {
      const resp = await fetch("/users");
      if (resp.ok) {
        window.allUsers = await resp.json();
        window.usersLoaded = true;
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
  if (!window.usersLoaded) return;

  const raw = dmUsersInput.value;
  const parts = raw.split(",").map((p) => p.trim());
  const lastPart = parts[parts.length - 1].toLowerCase();

  suggestionIndex = -1;

  if (!lastPart) {
    dmSuggestions.style.display = "none";
    return;
  }

  const alreadyAdded = parts.slice(0, -1);
  const matches = window.allUsers
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

document.getElementById("dm-cancel").onclick = () => {
  dmModal.style.display = "none";
};

document.getElementById("dm-start").onclick = () => {
  const raw = dmUsersInput.value.trim();
  if (!raw) return;

  const users = raw
    .split(",")
    .map((u) => u.trim())
    .filter(Boolean);

  if (!users.length) return;

  if (!users.includes(CURRENT_USER)) {
    users.push(CURRENT_USER);
  }

  users.sort();

  const dmChannel = "dm:" + users.join(":");

  resetDmModal();
  dmModal.style.display = "none";

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
