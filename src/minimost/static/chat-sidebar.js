let userColorOverrides = {};
// Shared with chat-settings.js and chat.html (its `.has()` reads live there);
// kept on `window` so the cross-file global is referenced explicitly.
window.usersWithAvatars = new Set();
let presenceMapCache = {};
let hasUnreadChannels = false;
let privateChannelUnreadCount = 0;

// Sidebar loading
async function loadSidebar() {
  const sb = document.getElementById("sidebar-dynamic");
  sb.innerHTML = "";

  const [chs, privateChannels, dms, colors, avatars, onlineUsers] =
    await Promise.all([
      fetch("/channels").then((r) => r.json()),
      fetch("/private_channels").then((r) => r.json()),
      fetch("/dms").then((r) => r.json()),
      fetch("/user_colors").then((r) => r.json()),
      fetch("/user_avatars").then((r) => r.json()),
      fetch("/online_users").then((r) => r.json()),
    ]);
  {
    userColorOverrides = colors;
    window.usersWithAvatars = new Set(avatars);
    presenceMapCache = onlineUsers;

    // Public channels
    const chTitle = document.createElement("b");
    chTitle.innerText = "Public Channels";
    sb.appendChild(chTitle);

    chs.forEach((c) => {
      sidebarEntry("# " + c, c);
    });

    sb.appendChild(document.createElement("hr"));

    // Private channels
    const privateHeader = document.createElement("div");
    privateHeader.id = "private-ch-sidebar-header";
    privateHeader.className = "sidebar-section-header";
    const privateTitleEl = document.createElement("b");
    privateTitleEl.textContent = "Private Channels";
    const newPCBtn = document.createElement("button");
    newPCBtn.className = "icon-btn sidebar-new-btn";
    newPCBtn.title = "New private channel";
    newPCBtn.textContent = "+";
    newPCBtn.onclick = openCreatePrivateChannel;
    privateHeader.appendChild(privateTitleEl);
    privateHeader.appendChild(newPCBtn);
    sb.appendChild(privateHeader);

    privateChannels.forEach((pc) => {
      privateChannelMap[pc.channel] = pc.name;
      privateChannelMembers[pc.channel] = pc.members || [];
      const el = sidebarEntry(pc.name, pc.channel, pc.unread);
      bindPCTooltip(el);
    });

    sb.appendChild(document.createElement("hr"));

    // DMs
    const dmHeader = document.createElement("div");
    dmHeader.className = "sidebar-section-header";
    const dmTitleEl = document.createElement("b");
    dmTitleEl.textContent = "Direct Messages";
    const newDmBtn = document.createElement("button");
    newDmBtn.className = "icon-btn sidebar-new-btn";
    newDmBtn.title = "New direct message";
    newDmBtn.textContent = "+";
    newDmBtn.onclick = openDmModal;
    dmHeader.appendChild(dmTitleEl);
    dmHeader.appendChild(newDmBtn);
    sb.appendChild(dmHeader);

    refreshChannels();
    dms.forEach((dm) => {
      const label = "@ " + dm.users.join(", ");
      sidebarEntry(label, dm.channel);
    });

    // ensure highlight is correct after rebuild
    updateSidebarActive();

    // Build the topbar account avatar now that avatars + presence are known.
    renderAccountAvatar();

    // Upgrade any avatars (e.g. messages) that rendered with initials before
    // the /user_avatars fetch above resolved, so they show the real image
    // without waiting for a channel switch.
    refreshAvatarImages();
  }
}

function refreshChannels() {
  fetch("/channel_unreads")
    .then((r) => r.json())
    .then((counts) => {
      hasUnreadChannels = Object.values(counts).some((c) => c > 0);
      channelUnreadCount = Object.values(counts).reduce((a, b) => a + b, 0);
      updateTitleBadge(
        channelUnreadCount + privateChannelUnreadCount + lastUnreadCount,
      );

      for (const [ch, count] of Object.entries(counts)) {
        const el = document.querySelector(`[data-channel="${ch}"]`);
        if (!el) continue;
        let badge = el.querySelector(".unread-badge");
        if (count > 0) {
          if (!badge) {
            badge = document.createElement("span");
            badge.className = "unread-badge";
            el.appendChild(badge);
          }
          badge.textContent = count;
        } else if (badge) {
          badge.remove();
        }
      }

      if (hasUnreadChannels || privateChannelUnreadCount > 0) {
        startFaviconFlash();
      } else if (lastUnreadCount === 0) {
        stopFaviconFlash();
      }

      maybeNotifyUnread();
    });
}

function refreshPrivateChannels() {
  fetch("/private_channels")
    .then((r) => r.json())
    .then((channels) => {
      const sb = document.getElementById("sidebar-dynamic");
      const header = document.getElementById("private-ch-sidebar-header");
      if (!header) return;

      const seen = new Set();
      let insertAfter = header;

      channels.forEach((pc) => {
        privateChannelMap[pc.channel] = pc.name;
        privateChannelMembers[pc.channel] = pc.members || [];
        const el = sidebarEntry(pc.name, pc.channel, pc.unread);
        bindPCTooltip(el);
        seen.add(pc.channel);
        sb.insertBefore(el, insertAfter.nextSibling);
        insertAfter = el;
      });

      sb.querySelectorAll(".sidebar-private").forEach((el) => {
        if (!seen.has(el.dataset.channel)) el.remove();
      });

      privateChannelUnreadCount = channels.reduce((s, pc) => s + pc.unread, 0);
      updateTitleBadge(
        channelUnreadCount + privateChannelUnreadCount + lastUnreadCount,
      );

      if (channel.startsWith("private:") && privateChannelMap[channel]) {
        const updatedName = privateChannelMap[channel];
        document.getElementById("chan").innerText = "";
        const nbt = document.getElementById("private-ch-name-bar-text");
        if (nbt) nbt.textContent = updatedName;
      }

      if (privateChannelUnreadCount > 0 || hasUnreadChannels) {
        startFaviconFlash();
      } else if (lastUnreadCount === 0) {
        stopFaviconFlash();
      }

      maybeNotifyUnread();
      updateSidebarActive();
    });
}

function refreshDMs() {
  fetch("/dms")
    .then((r) => r.json())
    .then((dms) => {
      const sb = document.getElementById("sidebar-dynamic");

      const dmHeader = Array.from(sb.children).find(
        (e) =>
          e.classList?.contains("sidebar-section-header") &&
          e.querySelector("b")?.textContent === "Direct Messages",
      );
      if (!dmHeader) return;

      const seen = new Set();

      let insertAfter = dmHeader;

      dms.forEach((dm) => {
        const label = "@ " + dm.users.join(", ");
        const el = sidebarEntry(label, dm.channel, dm.unread);

        seen.add(dm.channel);

        sb.insertBefore(el, insertAfter.nextSibling);
        insertAfter = el;
      });

      // Remove stale DMs only
      sb.querySelectorAll(".sidebar-dm").forEach((el) => {
        if (!seen.has(el.dataset.channel)) {
          el.remove();
        }
      });

      updateSidebarActive();
    });
}

// Presence
let currentPresence = "offline";

function sendPresence(state) {
  if (state === currentPresence) return;
  currentPresence = state;
  fetch("/presence", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ state }),
  });
}

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") {
    reconcileOnActive();
  } else if (currentPresence !== "hidden") {
    // sendBeacon is more reliable than fetch when the tab is being hidden —
    // browsers (especially on Windows) may cancel in-flight fetch requests
    // the moment the tab becomes invisible.
    currentPresence = "hidden";
    navigator.sendBeacon(
      "/presence",
      new Blob([JSON.stringify({ state: "hidden" })], {
        type: "application/json",
      }),
    );
  }
});

// Regaining window focus (e.g. alt-tabbing back) doesn't fire visibilitychange,
// so reconcile here too — otherwise an unread badge on the channel the user is
// already looking at would linger.
window.addEventListener("focus", () => {
  if (document.visibilityState === "visible") reconcileOnActive();
});

window.addEventListener("pagehide", () => {
  navigator.sendBeacon(
    "/presence",
    new Blob([JSON.stringify({ state: "offline" })], {
      type: "application/json",
    }),
  );
});

let lastActivity = Date.now();
let idleSent = false;

function setIdleSent(v) {
  idleSent = v;
}

["mousemove", "keydown", "mousedown", "touchstart"].forEach((evt) =>
  document.addEventListener(evt, () => {
    lastActivity = Date.now();

    sendPresence("active");
    if (idleSent) {
      sendPresence("active");
      idleSent = false;
    }
  }),
);

// Browsers only show OS notifications once permission is granted, and the
// prompt must be triggered by a user gesture. The native-notification setting
// defaults to on, but the only place that ever called requestPermission was the
// settings toggle's "turn on" path — which never runs when it starts on. So ask
// on the first interaction (unless the user has already granted or denied it).
let _notifPermAsked = false;
function ensureNotifPermission() {
  if (_notifPermAsked) return;
  if (!nativeNotifEnabled || !("Notification" in globalThis)) return;
  if (Notification.permission !== "default") return;
  _notifPermAsked = true;
  Notification.requestPermission().catch(() => {});
}
["pointerdown", "keydown"].forEach((evt) =>
  document.addEventListener(evt, ensureNotifPermission),
);

function setPresence(presenceEl, state) {
  switch (state) {
    case "active":
      presenceEl.textContent = " ●";
      presenceEl.style.color = "#6cf";
      break;
    case "idle":
    case "hidden":
      presenceEl.textContent = " ●";
      presenceEl.style.color = "#fc6";
      break;
    default: // offline
      presenceEl.textContent = " ●";
      presenceEl.style.color = "#555";
  }
}

function refreshPresence() {
  fetch("/online_users")
    .then((r) => r.json())
    .then((presenceMap) => {
      presenceMapCache = presenceMap;

      document
        .querySelectorAll(".avatar-presence[data-username]")
        .forEach((dot) => {
          applyPresenceDot(dot, presenceMap[dot.dataset.username] || "offline");
        });
    });
}

let baseTitle = document.title;
let lastUnreadCount = 0;
let channelUnreadCount = 0;

// True when the page is genuinely in front of the user — visible *and* the
// window/tab has OS focus. Anything else (another tab, another window, or a
// minimised browser) counts as inactive and should raise alerts.
function pageActive() {
  return document.visibilityState === "visible" && document.hasFocus();
}

// Play the alert sound, debounced so the per-channel poll (fetchMessages) and
// the cross-channel unread watcher (maybeNotifyUnread) can't both fire for the
// same incoming message.
let lastNotifSoundAt = 0;
function playNotifSound() {
  if (notifMuted) return;
  const now = Date.now();
  if (now - lastNotifSoundAt < 1000) return;
  lastNotifSoundAt = now;
  new Audio("/static/notification.mp3").play().catch(() => {});
}

function sendDesktopNotification(count) {
  if (!("Notification" in globalThis) || Notification.permission !== "granted")
    return;
  if (!nativeNotifEnabled) return;
  if (pageActive()) return;
  new Notification("MiniMost", {
    body: `You have ${count} unread message${count === 1 ? "" : "s"}`,
    icon: "/static/web-app-manifest-192x192.png",
    tag: "minimost-unread",
    renotify: true,
  });
}

// Cross-channel new-message watcher. Polling only fetches the active channel,
// so messages in *other* channels surface only as unread-count changes.
// Whenever the grand total (DMs + public + private) rises while the page is
// inactive, fire one debounced sound + native notification. A short settle
// window after load suppresses alerts for messages that were already unread
// before this tab opened (the three counts arrive from separate pollers).
let lastNotifiedTotal = 0;
let lastMentionNotifAt = 0;
const notifReadyAt = Date.now() + 6000;

function grandTotalUnread() {
  return channelUnreadCount + privateChannelUnreadCount + lastUnreadCount;
}

function maybeNotifyUnread() {
  const total = grandTotalUnread();
  if (
    Date.now() >= notifReadyAt &&
    total > lastNotifiedTotal &&
    !pageActive()
  ) {
    playNotifSound();
    // Skip the generic notification if a specific mention notification just
    // fired for the same message (avoids stacking two notifications).
    if (Date.now() - lastMentionNotifAt > 2000) sendDesktopNotification(total);
  }
  lastNotifiedTotal = total;
}

// Mark the active channel read and refresh every unread badge. Called when the
// page becomes active again — background polling deliberately leaves messages
// unread, so this is what reconciles the sidebar once the user returns.
function reconcileOnActive() {
  sendPresence("active");
  fetchMessages();
  fetch(`/mark_read/${channel}`, { method: "POST" }).then(() => {
    refreshChannels();
    refreshPrivateChannels();
    refreshTotalUnreadCount();
  });
}

function updateTitleBadge(count) {
  if (count > 0) {
    document.title = `(${count}) ${baseTitle}`;
  } else {
    document.title = baseTitle;
  }
}

function updateAppBadge(count) {
  if (!("setAppBadge" in navigator)) return;

  if (count > 0) {
    navigator.setAppBadge(count).catch(() => {});
  } else {
    navigator.clearAppBadge().catch(() => {});
  }
}

// Favicon flash for unread notifications
let normalFavicon = null;
let notifFavicon = null;
let faviconFlashInterval = null;
let faviconState = false;

function initFavicon() {
  const link = document.querySelector("link[rel='icon']");
  if (!link) return;
  normalFavicon = link.href;
  // Build notification favicon synchronously via canvas so it's ready immediately
  const sz = 32;
  const canvas = document.createElement("canvas");
  canvas.width = sz;
  canvas.height = sz;
  const ctx = canvas.getContext("2d");
  ctx.beginPath();
  ctx.arc(sz / 2, sz / 2, 12, 0, 2 * Math.PI);
  ctx.fillStyle = "#e74c3c";
  ctx.fill();
  notifFavicon = canvas.toDataURL();
}

function setFaviconHref(href) {
  document.querySelectorAll("link[rel='icon']").forEach((el) => {
    el.href = href;
  });
}

function startFaviconFlash() {
  if (faviconFlashInterval || !notifFavicon) return;
  faviconFlashInterval = setInterval(() => {
    faviconState = !faviconState;
    setFaviconHref(faviconState ? notifFavicon : normalFavicon);
  }, 1000);
}

function stopFaviconFlash() {
  clearInterval(faviconFlashInterval);
  faviconFlashInterval = null;
  faviconState = false;
  if (normalFavicon) setFaviconHref(normalFavicon);
}

function refreshTotalUnreadCount() {
  fetch("/unread_count")
    .then((r) => r.json())
    .then((data) => {
      lastUnreadCount = data.count;
      updateTitleBadge(
        channelUnreadCount + privateChannelUnreadCount + lastUnreadCount,
      );
      updateAppBadge(lastUnreadCount);
      if (
        lastUnreadCount > 0 ||
        hasUnreadChannels ||
        privateChannelUnreadCount > 0
      ) {
        startFaviconFlash();
      } else {
        stopFaviconFlash();
      }
      maybeNotifyUnread();
    });
}

function sidebarEntry(label, channelName, unread = 0) {
  const sb = document.getElementById("sidebar-dynamic");

  let d = sb.querySelector(`[data-channel="${channelName}"]`);
  if (!d) {
    d = document.createElement("div");
    d.className = "sidebar-item";
    d.dataset.channel = channelName;
    sb.appendChild(d);
  }

  d.innerHTML = "";

  const labelSpan = document.createElement("span");
  labelSpan.className = "label";
  labelSpan.textContent = label;

  if (channelName.startsWith("dm:")) {
    d.classList.add("sidebar-dm");

    const avatarUser =
      channelName
        .split(":")
        .slice(1)
        .find((u) => u !== CURRENT_USER) || CURRENT_USER;
    const avatarWrap = makeAvatarWrap(avatarUser, 28);
    // Use .on* assignment so repeated calls to sidebarEntry don't stack listeners.
    avatarWrap.onmouseenter = () => _showDmHoverCard(avatarWrap, avatarUser);
    avatarWrap.onmouseleave = _hideDmHoverCard;
    d.appendChild(avatarWrap);
    d.appendChild(labelSpan);

    const closeBtn = document.createElement("button");
    closeBtn.className = "dm-close-btn";
    closeBtn.title = "Close conversation";
    closeBtn.textContent = "×";
    closeBtn.addEventListener("pointerup", (e) => {
      e.stopPropagation();
      closeDm(channelName);
    });
    d.appendChild(closeBtn);
  } else {
    d.appendChild(labelSpan);
  }

  if (channelName.startsWith("private:")) {
    d.classList.add("sidebar-private");
  }

  if (unread > 0) {
    const badge = document.createElement("span");
    badge.className = "unread-badge";
    badge.textContent = unread;
    d.appendChild(badge);
  }

  d.onpointerup = (e) => {
    e.preventDefault();
    switchChannel(channelName);
  };

  return d;
}

// Mobile sidebar drawer
function openSidebar() {
  document.getElementById("sidebar").classList.add("sidebar-open");
  document.getElementById("sidebar-backdrop").classList.add("sidebar-open");
}
function closeSidebar() {
  document.getElementById("sidebar").classList.remove("sidebar-open");
  document.getElementById("sidebar-backdrop").classList.remove("sidebar-open");
}
function toggleSidebar() {
  document.getElementById("sidebar").classList.contains("sidebar-open")
    ? closeSidebar()
    : openSidebar();
}
