let notifMuted = localStorage.getItem('notifMuted') === 'true';
let nativeNotifEnabled = localStorage.getItem('nativeNotifEnabled') !== 'false';

// ── Settings ──────────────────────────────────────────────────────────────────

const COLOR_PRESETS = [
    // Reds
    "#ff4d4d", "#e06c75", "#d62828", "#c9184a", "#ff0054", "#ff6666",
    // Pinks & rose
    "#ff6b9d", "#f72585", "#ff8fa3", "#f48fb1", "#ff85a1", "#e91e8c",
    // Oranges & coral
    "#fb5607", "#ff7f2a", "#e76f51", "#ff6f61", "#ff9500", "#ff8c42",
    // Yellows & amber
    "#d19a66", "#e5c07b", "#ffd93d", "#ffb703", "#f9c74f", "#e9c46a",
    // Lime & chartreuse
    "#c5e063", "#b5e48c", "#a7c957", "#90be6d", "#8fc93a", "#d4e157",
    // Greens
    "#98c379", "#6bcb77", "#52b788", "#2dc653", "#80ed99", "#b7e4c7",
    // Teals & mint
    "#43aa8b", "#57cc99", "#2ec4b6", "#14b8a6", "#4ecdc4", "#a8dadc",
    // Sky blues & cyans
    "#56b6c2", "#00b4d8", "#48cae4", "#90e0ef", "#ade8f4", "#0096c7",
    // Blues
    "#61afef", "#4d96ff", "#3a86ff", "#4895ef", "#4361ee", "#0891b2",
    // Indigo & blue-violet
    "#6741d9", "#7c3aed", "#845ef7", "#6c5ce7", "#6c63ff", "#a78bfa",
    // Purples & violets
    "#c678dd", "#7209b7", "#9d4edd", "#b5179e", "#d0a0f0", "#7b2ff7",
    // Lavender & neutrals
    "#da77f2", "#e2d9f3", "#c0b9dd", "#ffffff", "#cccccc", "#aaaaaa",
];

const settingsModal = document.getElementById("settings-modal");
let _settingsUseDefault = false;
let _pendingAvatarBlob = null;
let _removeAvatar = false;

function _resizeImage(file, size, onDone) {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
        URL.revokeObjectURL(url);
        const canvas = document.createElement("canvas");
        canvas.width = size;
        canvas.height = size;
        const ctx = canvas.getContext("2d");
        const srcMin = Math.min(img.width, img.height);
        const sx = (img.width - srcMin) / 2;
        const sy = (img.height - srcMin) / 2;
        ctx.drawImage(img, sx, sy, srcMin, srcMin, 0, 0, size, size);
        canvas.toBlob(blob => onDone(blob), "image/jpeg", 0.88);
    };
    img.src = url;
}

function _populateAvatarPreview(srcBlob) {
    const previewDiv = document.getElementById("settings-avatar-preview");
    previewDiv.innerHTML = "";
    const wrap = makeAvatarWrap(CURRENT_USER, 64);
    wrap.querySelector(".avatar-presence")?.remove();
    if (srcBlob) {
        const inner = wrap.querySelector(".avatar");
        inner.innerHTML = "";
        const img = document.createElement("img");
        img.className = "avatar-img";
        img.src = URL.createObjectURL(srcBlob);
        inner.appendChild(img);
    }
    previewDiv.appendChild(wrap);
}

document.getElementById("settings-avatar-btn").addEventListener("click", () => {
    document.getElementById("settings-avatar-file").click();
});

document.getElementById("settings-avatar-file").addEventListener("change", e => {
    const file = e.target.files[0];
    if (!file) return;
    if (file.size > MAX_AVATAR_MB * 1024 * 1024) {
        alert(`Avatar image must be under ${MAX_AVATAR_MB} MB.`);
        e.target.value = "";
        return;
    }
    _removeAvatar = false;
    _resizeImage(file, 128, blob => {
        _pendingAvatarBlob = blob;
        _populateAvatarPreview(blob);
    });
    e.target.value = "";
});

document.getElementById("settings-avatar-remove").addEventListener("click", () => {
    _pendingAvatarBlob = null;
    _removeAvatar = true;
    // Show initials preview (force, ignoring current avatar)
    const previewDiv = document.getElementById("settings-avatar-preview");
    previewDiv.innerHTML = "";
    const wrap = document.createElement("div");
    wrap.className = "avatar-wrap";
    wrap.style.cssText = "width:64px;height:64px";
    const inner = document.createElement("div");
    inner.className = "avatar";
    _setInitials(inner, CURRENT_USER, 64);
    wrap.appendChild(inner);
    previewDiv.appendChild(wrap);
});

function _buildColorSwatches(currentColor) {
    const container = document.getElementById("color-swatches");
    container.innerHTML = "";
    COLOR_PRESETS.forEach(hex => {
        const sw = document.createElement("button");
        sw.className = "color-swatch" + (hex.toLowerCase() === currentColor?.toLowerCase() ? " selected" : "");
        sw.style.background = hex;
        sw.title = hex;
        sw.addEventListener("click", () => {
            document.getElementById("settings-name-color").value = hex;
            _settingsUseDefault = false;
            _updateColorPreview(hex);
            container.querySelectorAll(".color-swatch").forEach(s =>
                s.classList.toggle("selected", s.title.toLowerCase() === hex.toLowerCase())
            );
        });
        container.appendChild(sw);
    });
}

function _updateColorPreview(color) {
    const preview = document.getElementById("settings-color-preview-name");
    preview.textContent = CURRENT_USER;
    preview.style.color = color;
}

async function openSettings() {
    const resp = await fetch("/settings");
    const cfg = await resp.json();
    const currentColor = cfg.name_color || defaultUserColor(CURRENT_USER);

    _settingsUseDefault = !cfg.name_color;
    _pendingAvatarBlob = null;
    _removeAvatar = false;
    document.getElementById("settings-name-color").value =
        cfg.name_color || defaultUserColor(CURRENT_USER);
    _updateColorPreview(currentColor);
    _buildColorSwatches(cfg.name_color);
    _populateAvatarPreview(null);

    const bio = cfg.bio || "";
    const bioEl = document.getElementById("settings-bio");
    bioEl.value = bio;
    document.getElementById("settings-bio-count").textContent = bio.length;

    const fontSize = Number.parseFloat(localStorage.getItem("chatFontSize")) || CHAT_FONT_DEFAULT;
    const fontSlider = document.getElementById("settings-font-size");
    fontSlider.value = Math.round(Math.min(CHAT_FONT_MAX, Math.max(CHAT_FONT_MIN, fontSize)));
    document.getElementById("settings-font-size-label").textContent = `(${fontSlider.value}px)`;

    const enterToSend = localStorage.getItem("enterToSend") !== "false";
    document.getElementById("settings-enter-key").value = enterToSend ? "send" : "newline";

    document.getElementById("settings-notif-sounds").checked = !notifMuted;
    _updateNotifSoundIcon();

    const notifDenied = !("Notification" in globalThis) || Notification.permission === "denied";
    const nativeToggle = document.getElementById("settings-native-notif");
    nativeToggle.checked = nativeNotifEnabled && !notifDenied;
    nativeToggle.disabled = notifDenied;
    document.getElementById("native-notif-hint").style.display = notifDenied ? "" : "none";
    _updateNativeNotifIcon();

    settingsModal.style.display = "flex";
}

document.getElementById("settings-bio").addEventListener("input", e => {
    document.getElementById("settings-bio-count").textContent = e.target.value.length;
});

function _updateNotifSoundIcon() {
    const on = document.getElementById("settings-notif-sounds").checked;
    document.getElementById("notif-bell-slash").style.display = on ? "none" : "";
}
document.getElementById("settings-notif-sounds").addEventListener("change", _updateNotifSoundIcon);

function _updateNativeNotifIcon() {
    const on = document.getElementById("settings-native-notif").checked;
    document.getElementById("native-bell-slash").style.display = on ? "none" : "";
}
document.getElementById("settings-native-notif").addEventListener("change", async function() {
    if (this.checked && "Notification" in globalThis && Notification.permission === "default") {
        const perm = await Notification.requestPermission();
        if (perm !== "granted") {
            this.checked = false;
            document.getElementById("native-notif-hint").style.display = "";
        }
    }
    _updateNativeNotifIcon();
});

document.getElementById("settings-font-size").addEventListener("input", e => {
    document.getElementById("settings-font-size-label").textContent = `(${e.target.value}px)`;
    applyChatFontSize(Number(e.target.value));
});

document.getElementById("settings-name-color").addEventListener("input", e => {
    _settingsUseDefault = false;
    _updateColorPreview(e.target.value);
    document.querySelectorAll(".color-swatch").forEach(s =>
        s.classList.toggle("selected", s.title.toLowerCase() === e.target.value.toLowerCase())
    );
});

document.getElementById("settings-color-reset").addEventListener("click", () => {
    _settingsUseDefault = true;
    const def = defaultUserColor(CURRENT_USER);
    document.getElementById("settings-name-color").value = def;
    _updateColorPreview(def);
    document.querySelectorAll(".color-swatch").forEach(s => s.classList.remove("selected"));
});

document.getElementById("settings-cancel-btn").addEventListener("click", () => {
    settingsModal.style.display = "none";
});

document.getElementById("settings-save-btn").addEventListener("click", async () => {
    // Avatar
    if (_pendingAvatarBlob) {
        const fd = new FormData();
        fd.append("avatar", _pendingAvatarBlob, "avatar.jpg");
        const r = await fetch("/avatar", { method: "POST", body: fd });
        if (r.ok) {
            usersWithAvatars.add(CURRENT_USER);
            _refreshUserAvatar(CURRENT_USER);
        }
        _pendingAvatarBlob = null;
    } else if (_removeAvatar) {
        const r = await fetch("/avatar", { method: "DELETE" });
        if (r.ok) {
            usersWithAvatars.delete(CURRENT_USER);
            _refreshUserAvatar(CURRENT_USER);
        }
        _removeAvatar = false;
    }

    // Font size
    const fontSize = Number(document.getElementById("settings-font-size").value);
    localStorage.setItem("chatFontSize", fontSize);
    applyChatFontSize(fontSize);

    // Enter key behavior
    const enterToSend = document.getElementById("settings-enter-key").value === "send";
    localStorage.setItem("enterToSend", enterToSend);

    // Notification sounds mute
    notifMuted = !document.getElementById("settings-notif-sounds").checked;
    localStorage.setItem("notifMuted", notifMuted);

    // Native OS notifications
    nativeNotifEnabled = document.getElementById("settings-native-notif").checked;
    localStorage.setItem("nativeNotifEnabled", nativeNotifEnabled);

    // Name color + bio
    const color = _settingsUseDefault ? null : document.getElementById("settings-name-color").value;
    const bio = document.getElementById("settings-bio").value.trim().slice(0, 160) || null;
    const resp = await fetch("/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name_color: color, bio })
    });

    if (!resp.ok) {
        alert("Failed to save settings.");
        return;
    }

    delete profileCache[CURRENT_USER];

    if (color) {
        userColorOverrides[CURRENT_USER] = color;
    } else {
        delete userColorOverrides[CURRENT_USER];
    }

    const applied = color || defaultUserColor(CURRENT_USER);
    document.querySelectorAll(".user").forEach(el => {
        if (el.textContent === CURRENT_USER) el.style.color = applied;
    });

    settingsModal.style.display = "none";
});

settingsModal.addEventListener("click", e => {
    if (e.target === settingsModal) {
        cancelDeleteConfirm();
        settingsModal.style.display = "none";
    }
});

// ── Account deletion ──────────────────────────────────────────────────────────

let _deleteType = null;

const _deleteInfo = {
    soft: {
        title: "Soft Delete Account",
        warning: `<p>Your login credentials will be permanently removed and your messages will be
            re-attributed to <strong>Deleted User</strong>. You will no longer be able to log in
            or recover your account.</p>
            <p>Message content and chat history will remain visible to other users.</p>`,
        btnLabel: "Soft Delete My Account",
    },
    hard: {
        title: "Hard Delete Account",
        warning: `<p>Your account <strong>and every message you have ever sent</strong> will be
            permanently and irreversibly deleted from all channels and conversations.</p>
            <p>This action cannot be undone under any circumstances.</p>`,
        btnLabel: "Permanently Delete Everything",
    },
};

function showDeleteConfirm(type) {
    _deleteType = type;
    const info = _deleteInfo[type];
    document.getElementById("settings-delete-title").textContent = info.title;
    document.getElementById("settings-delete-warning").innerHTML = info.warning;
    document.getElementById("settings-delete-confirm-btn").textContent = info.btnLabel;
    document.getElementById("settings-delete-password").value = "";
    document.getElementById("settings-delete-error").style.display = "none";
    document.getElementById("settings-main-view").style.display = "none";
    document.getElementById("settings-delete-view").style.display = "block";
    document.getElementById("settings-delete-password").focus();
}

function cancelDeleteConfirm() {
    _deleteType = null;
    document.getElementById("settings-delete-view").style.display = "none";
    document.getElementById("settings-main-view").style.display = "block";
}

async function confirmDelete() {
    const password = document.getElementById("settings-delete-password").value;
    const errEl = document.getElementById("settings-delete-error");
    if (!password) {
        errEl.textContent = "Please enter your password.";
        errEl.style.display = "block";
        return;
    }
    const btn = document.getElementById("settings-delete-confirm-btn");
    btn.disabled = true;
    btn.textContent = "Deleting…";
    try {
        const resp = await fetch("/delete_account", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ type: _deleteType, password }),
        });
        if (resp.ok) {
            globalThis.location.href = "/login";
        } else {
            const data = await resp.json().catch(() => ({}));
            errEl.textContent = data.error || "Deletion failed. Please try again.";
            errEl.style.display = "block";
            btn.disabled = false;
            btn.textContent = _deleteInfo[_deleteType].btnLabel;
        }
    } catch {
        errEl.textContent = "Network error. Please try again.";
        errEl.style.display = "block";
        btn.disabled = false;
        btn.textContent = _deleteInfo[_deleteType].btnLabel;
    }
}

// ── Users Modal ───────────────────────────────────────────────────────────────

const usersModal = document.getElementById("users-modal");
let _usersModalRows = []; // { username, nameEl, row } — populated after fetch

async function openUsersModal() {
    usersModal.style.display = "block";
    const searchEl = document.getElementById("users-modal-search");
    searchEl.value = "";
    const list = document.getElementById("users-list");
    list.innerHTML = '<div class="users-list-loading">Loading…</div>';

    let others;
    try {
        const r = await fetch("/users");
        others = await r.json();
    } catch {
        list.innerHTML = '<div class="users-list-loading">Failed to load members.</div>';
        return;
    }

    const allUsernames = [CURRENT_USER, ...others];

    const profiles = await Promise.all(allUsernames.map(u => {
        if (profileCache[u]) return Promise.resolve(profileCache[u]);
        return fetch(`/profile/${encodeURIComponent(u)}`)
            .then(r => r.ok ? r.json() : null)
            .then(d => { if (d) { profileCache[u] = d; } return d; })
            .catch(() => null);
    }));

    list.innerHTML = "";
    _usersModalRows = [];
    allUsernames.forEach((u, i) => {
        const profile = profiles[i];
        const color = userColor(u);

        const row = document.createElement("div");
        row.className = "users-list-row";

        const avatarWrap = makeAvatarWrap(u, 40);
        avatarWrap.style.flexShrink = "0";

        const info = document.createElement("div");
        info.className = "users-list-info";

        const name = document.createElement("span");
        name.className = "users-list-name";
        name.style.color = color;
        name.textContent = u + (u === CURRENT_USER ? " (you)" : "");
        info.appendChild(name);
        _usersModalRows.push({ username: u, nameEl: name, row });

        if (profile?.bio) {
            const bio = document.createElement("p");
            bio.className = "users-list-bio";
            bio.textContent = profile.bio;
            info.appendChild(bio);
        }

        row.appendChild(avatarWrap);
        row.appendChild(info);

        if (u !== CURRENT_USER) {
            const dmCh = "dm:" + [u, CURRENT_USER].sort((a, b) => a.localeCompare(b)).join(":");

            const actions = document.createElement("div");
            actions.className = "users-list-actions";

            const dmBtn = document.createElement("button");
            dmBtn.className = "icon-btn";
            dmBtn.title = "Direct message";
            dmBtn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" viewBox="0 0 16 16"><path d="M2.678 11.894a1 1 0 0 1 .287.801 11 11 0 0 1-.398 2c1.395-.323 2.247-.697 2.634-.893a1 1 0 0 1 .71-.074A8 8 0 0 0 8 14c3.996 0 7-2.807 7-6s-3.004-6-7-6-7 2.808-7 6c0 1.468.617 2.83 1.678 3.894zm-.493 3.905a22 22 0 0 1-.713.129c-.2.032-.352-.176-.273-.362a10 10 0 0 0 .244-.637l.003-.01c.248-.72.45-1.548.524-2.319C.743 11.37 0 9.76 0 8c0-3.866 3.582-7 8-7s8 3.134 8 7-3.582 7-8 7a9 9 0 0 1-2.347-.306c-.52.263-1.639.742-3.468 1.105z"/></svg>`;
            dmBtn.onclick = () => { closeUsersModal(); switchChannel(dmCh); focusMessageInput(); };

            const callBtn = document.createElement("button");
            callBtn.className = "icon-btn";
            callBtn.title = "Start call";
            callBtn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" viewBox="0 0 16 16"><path fill-rule="evenodd" d="M1.885.511a1.745 1.745 0 0 1 2.61.163L6.29 2.98c.329.423.445.974.315 1.494l-.547 2.19a.678.678 0 0 0 .178.643l2.457 2.457a.678.678 0 0 0 .644.178l2.189-.547a1.745 1.745 0 0 1 1.494.315l2.306 1.794c.829.645.905 1.87.163 2.611l-1.034 1.034c-.74.74-1.846 1.065-2.877.702a18.634 18.634 0 0 1-7.01-4.42 18.634 18.634 0 0 1-4.42-7.009c-.362-1.03-.037-2.137.703-2.877L1.885.511z"/></svg>`;
            callBtn.onclick = () => { closeUsersModal(); switchChannel(dmCh); startCall(); };

            const ssBtn = document.createElement("button");
            ssBtn.className = "icon-btn";
            ssBtn.title = "Share screen";
            ssBtn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" viewBox="0 0 16 16"><path d="M0 4s0-2 2-2h12s2 0 2 2v6s0 2-2 2h-4c0 .667.083 1.167.25 1.5H11a.5.5 0 0 1 0 1H5a.5.5 0 0 1 0-1h.75c.167-.333.25-.833.25-1.5H2s-2 0-2-2zm1.398-.855A1.002 1.002 0 0 0 1 4v6c0 .255.098.292.412.637C1.574 10.89 1.851 11 2 11h12c.149 0 .426-.11.588-.363C14.902 10.292 15 10.255 15 10V4c0-.255-.098-.292-.412-.637C14.426 3.11 14.149 3 14 3H2c-.149 0-.426.11-.588.363z"/></svg>`;
            ssBtn.onclick = () => { closeUsersModal(); switchChannel(dmCh); toggleStandaloneScreenShare(); };

            actions.appendChild(dmBtn);
            actions.appendChild(callBtn);
            actions.appendChild(ssBtn);
            row.appendChild(actions);
        }

        list.appendChild(row);
    });
    document.getElementById("users-modal-search").focus();
}

function filterUsersModal(query) {
    for (const { username, nameEl, row } of _usersModalRows) {
        const isSelf = username === CURRENT_USER;
        const suffix = isSelf ? " (you)" : "";
        if (!query) {
            row.style.display = "";
            nameEl.innerHTML = escapeHtml(username) + suffix;
            continue;
        }
        const result = fuzzySearch(query, username);
        if (result) {
            row.style.display = "";
            nameEl.innerHTML = highlightFuzzyMatch(username, result.indices) + suffix;
        } else {
            row.style.display = "none";
        }
    }
}

function closeUsersModal() {
    usersModal.style.display = "none";
}

usersModal.addEventListener("click", e => {
    if (e.target === usersModal) usersModal.style.display = "none";
});

