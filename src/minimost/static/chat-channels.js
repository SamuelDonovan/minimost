// ── Private Channels ──────────────────────────────────────────────────────────


const createPrivateChModal = document.getElementById("create-private-ch-modal");
const renamePrivateChModal = document.getElementById("rename-private-ch-modal");
const privateMembersModal  = document.getElementById("private-ch-members-modal");

const privateChNameInput    = document.getElementById("private-ch-name");
const privateChMembersInput = document.getElementById("private-ch-members-input");
const privateChSuggestions  = document.getElementById("private-ch-suggestions");
const addMemberInput        = document.getElementById("add-member-input");
const addMemberSuggestions  = document.getElementById("add-member-suggestions");

let pcSuggestionIndex = -1;
let pcCurrentSuggestions = [];
let addMemberSuggIndex = -1;
let addMemberCurrentSuggestions = [];

const MAX_CHANNEL_NAME_LEN = 80;

function openCreatePrivateChannel() {
    createPrivateChModal.style.display = "block";
    privateChNameInput.value = "";
    privateChMembersInput.value = "";
    privateChSuggestions.style.display = "none";
    document.getElementById("private-ch-name-error").textContent = "";
    if (!usersLoaded) {
        fetch("/users").then(r => r.json()).then(u => { allUsers = u; usersLoaded = true; });
    }
    privateChNameInput.focus();
}

document.getElementById("private-ch-create-cancel").onclick = () => {
    createPrivateChModal.style.display = "none";
};

document.getElementById("private-ch-create-btn").onclick = async () => {
    const name = privateChNameInput.value.trim();
    const nameError = document.getElementById("private-ch-name-error");
    nameError.textContent = "";
    if (!name) { privateChNameInput.focus(); return; }
    if (name.length > MAX_CHANNEL_NAME_LEN) {
        nameError.textContent = `Channel name must be ${MAX_CHANNEL_NAME_LEN} characters or fewer (${name.length}/${MAX_CHANNEL_NAME_LEN}).`;
        privateChNameInput.focus();
        return;
    }

    const raw = privateChMembersInput.value;
    const members = raw.split(",").map(u => u.trim()).filter(Boolean);

    const resp = await fetch("/private_channels/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, members })
    });

    if (!resp.ok) {
        alert("Failed to create channel: " + await resp.text());
        return;
    }

    const data = await resp.json();
    createPrivateChModal.style.display = "none";
    privateChannelMap[data.channel] = data.name;
    loadSidebar();
    switchChannel(data.channel);
    focusMessageInput();
};

privateChMembersInput.addEventListener("input", () => {
    if (!usersLoaded) return;
    const raw = privateChMembersInput.value;
    const parts = raw.split(",").map(p => p.trim());
    const lastPart = parts[parts.length - 1].toLowerCase();
    pcSuggestionIndex = -1;
    if (!lastPart) { privateChSuggestions.style.display = "none"; return; }
    const already = parts.slice(0, -1);
    const matches = allUsers
        .filter(u => !already.includes(u))
        .map(u => ({ user: u, result: fuzzySearch(lastPart, u) }))
        .filter(({ result }) => result !== null)
        .sort((a, b) => b.result.score - a.result.score);
    pcCurrentSuggestions = matches.map(m => m.user);
    if (!pcCurrentSuggestions.length) { privateChSuggestions.style.display = "none"; return; }
    privateChSuggestions.innerHTML = "";
    matches.forEach(({ user, result }, idx) => {
        const div = document.createElement("div");
        div.className = "autocomplete-suggestion";
        div.innerHTML = highlightFuzzyMatch(user, result.indices);
        div.onclick = () => selectPCSuggestion(idx);
        privateChSuggestions.appendChild(div);
    });
    privateChSuggestions.style.display = "block";
});

function selectPCSuggestion(idx) {
    const raw = privateChMembersInput.value;
    const parts = raw.split(",").map(p => p.trim());
    parts[parts.length - 1] = pcCurrentSuggestions[idx];
    privateChMembersInput.value = parts.join(", ") + ", ";
    privateChSuggestions.style.display = "none";
    pcSuggestionIndex = -1;
    privateChMembersInput.focus();
}

privateChMembersInput.addEventListener("keydown", e => {
    const items = privateChSuggestions.children;
    const visible = privateChSuggestions.style.display === "block";
    if (e.key === "Tab" && visible && items.length) {
        e.preventDefault();
        selectPCSuggestion(Math.max(pcSuggestionIndex, 0));
        return;
    }
    if (e.key === "Enter") {
        e.preventDefault();
        if (visible && items.length) { selectPCSuggestion(Math.max(pcSuggestionIndex, 0)); return; }
        document.getElementById("private-ch-create-btn").click();
        return;
    }
    if (!visible) return;
    if (e.key === "ArrowDown") {
        e.preventDefault();
        pcSuggestionIndex = (pcSuggestionIndex + 1) % items.length;
        Array.from(items).forEach((el, i) => el.classList.toggle("active", i === pcSuggestionIndex));
    } else if (e.key === "ArrowUp") {
        e.preventDefault();
        pcSuggestionIndex = (pcSuggestionIndex - 1 + items.length) % items.length;
        Array.from(items).forEach((el, i) => el.classList.toggle("active", i === pcSuggestionIndex));
    } else if (e.key === "Escape") {
        privateChSuggestions.style.display = "none";
        pcSuggestionIndex = -1;
    }
});

document.addEventListener("click", e => {
    if (!privateChMembersInput.contains(e.target) && !privateChSuggestions.contains(e.target)) {
        privateChSuggestions.style.display = "none";
    }
});

// Rename channel
function openRenameChannel() {
    if (!channel.startsWith("private:")) return;
    renamePrivateChModal.style.display = "block";
    document.getElementById("rename-ch-name-error").textContent = "";
    const renameInput = document.getElementById("rename-ch-input");
    renameInput.value = privateChannelMap[channel] || "";
    renameInput.focus();
    renameInput.select();
}

document.getElementById("rename-ch-cancel-btn").onclick = () => {
    renamePrivateChModal.style.display = "none";
};

document.getElementById("rename-ch-submit-btn").onclick = async () => {
    if (!channel.startsWith("private:")) return;
    const channelId = channel.split(":")[1];
    const name = document.getElementById("rename-ch-input").value.trim();
    const renameError = document.getElementById("rename-ch-name-error");
    renameError.textContent = "";
    if (!name) return;
    if (name.length > MAX_CHANNEL_NAME_LEN) {
        renameError.textContent = `Channel name must be ${MAX_CHANNEL_NAME_LEN} characters or fewer (${name.length}/${MAX_CHANNEL_NAME_LEN}).`;
        document.getElementById("rename-ch-input").focus();
        return;
    }

    const resp = await fetch(`/private_channels/${channelId}/rename`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name })
    });

    if (!resp.ok) {
        alert("Failed to rename channel: " + await resp.text());
        return;
    }

    privateChannelMap[channel] = name;
    document.getElementById("chan").innerText = "";
    const nameBarText = document.getElementById("private-ch-name-bar-text");
    if (nameBarText) nameBarText.textContent = name;
    renamePrivateChModal.style.display = "none";
    refreshPrivateChannels();
};

document.getElementById("rename-ch-input").addEventListener("keydown", e => {
    if (e.key === "Enter") document.getElementById("rename-ch-submit-btn").click();
    if (e.key === "Escape") renamePrivateChModal.style.display = "none";
});

// Members modal
function openChannelMembers() {
    if (!channel.startsWith("private:")) return;
    privateMembersModal.style.display = "block";
    const channelId = channel.split(":")[1];
    document.getElementById("members-modal-title").textContent =
        "Members: " + (privateChannelMap[channel] || channel);
    document.getElementById("add-member-input").value = "";
    addMemberSuggestions.style.display = "none";
    if (!usersLoaded) {
        fetch("/users").then(r => r.json()).then(u => { allUsers = u; usersLoaded = true; });
    }
    loadChannelMembers(channelId);
}

function loadChannelMembers(channelId) {
    fetch(`/private_channels/${channelId}/members`)
        .then(r => r.json())
        .then(members => {
            const list = document.getElementById("members-list");
            list.innerHTML = "";
            members.forEach(m => {
                const div = document.createElement("div");
                div.className = "members-list-item";
                div.style.display = "flex";
                div.style.alignItems = "center";
                div.style.gap = "8px";
                div.appendChild(makeAvatarWrap(m.username, 28));
                const label = document.createElement("span");
                label.textContent = m.username + (m.username === CURRENT_USER ? " (you)" : "");
                div.appendChild(label);
                list.appendChild(div);
            });
        });
}

document.getElementById("members-modal-close-btn").onclick = () => {
    privateMembersModal.style.display = "none";
};

async function leaveChannel() {
    if (!channel.startsWith("private:")) return;
    const name = privateChannelMap[channel] || channel;
    if (!confirm(`Leave "${name}"?`)) return;
    const channelId = channel.split(":")[1];

    const resp = await fetch(`/private_channels/${channelId}/leave`, { method: "POST" });
    if (!resp.ok) {
        alert("Failed to leave channel: " + await resp.text());
        return;
    }

    privateMembersModal.style.display = "none";
    delete privateChannelMap[channel];
    delete privateChannelMembers[channel];
    switchChannel("general");
    refreshPrivateChannels();
}


addMemberInput.addEventListener("input", () => {
    if (!usersLoaded) return;
    const q = addMemberInput.value.trim().toLowerCase();
    addMemberSuggIndex = -1;
    if (!q) { addMemberSuggestions.style.display = "none"; return; }
    const matches = allUsers
        .map(u => ({ user: u, result: fuzzySearch(q, u) }))
        .filter(({ result }) => result !== null)
        .sort((a, b) => b.result.score - a.result.score);
    addMemberCurrentSuggestions = matches.map(m => m.user);
    if (!addMemberCurrentSuggestions.length) { addMemberSuggestions.style.display = "none"; return; }
    addMemberSuggestions.innerHTML = "";
    matches.forEach(({ user, result }, idx) => {
        const div = document.createElement("div");
        div.className = "autocomplete-suggestion";
        div.style.display = "flex";
        div.style.alignItems = "center";
        div.style.gap = "6px";
        const dot = document.createElement("span");
        dot.className = "presence-inline";
        setPresence(dot, presenceMapCache[user] || "offline");
        const label = document.createElement("span");
        label.innerHTML = highlightFuzzyMatch(user, result.indices);
        div.appendChild(dot);
        div.appendChild(label);
        div.onclick = () => selectAddMemberSuggestion(idx);
        addMemberSuggestions.appendChild(div);
    });
    addMemberSuggestions.style.display = "block";
});

function selectAddMemberSuggestion(idx) {
    addMemberInput.value = addMemberCurrentSuggestions[idx];
    addMemberSuggestions.style.display = "none";
    addMemberSuggIndex = -1;
    addMemberInput.focus();
}

addMemberInput.addEventListener("keydown", e => {
    const items = addMemberSuggestions.children;
    const visible = addMemberSuggestions.style.display === "block";
    if (e.key === "Tab" && visible && items.length) {
        e.preventDefault();
        selectAddMemberSuggestion(Math.max(addMemberSuggIndex, 0));
        return;
    }
    if (e.key === "Enter") {
        e.preventDefault();
        if (visible && items.length) { selectAddMemberSuggestion(Math.max(addMemberSuggIndex, 0)); return; }
        document.getElementById("add-member-submit-btn").click();
        return;
    }
    if (!visible) return;
    if (e.key === "ArrowDown") {
        e.preventDefault();
        addMemberSuggIndex = (addMemberSuggIndex + 1) % items.length;
        Array.from(items).forEach((el, i) => el.classList.toggle("active", i === addMemberSuggIndex));
    } else if (e.key === "ArrowUp") {
        e.preventDefault();
        addMemberSuggIndex = (addMemberSuggIndex - 1 + items.length) % items.length;
        Array.from(items).forEach((el, i) => el.classList.toggle("active", i === addMemberSuggIndex));
    } else if (e.key === "Escape") {
        addMemberSuggestions.style.display = "none";
        addMemberSuggIndex = -1;
    }
});

document.addEventListener("click", e => {
    if (!addMemberInput.contains(e.target) && !addMemberSuggestions.contains(e.target)) {
        addMemberSuggestions.style.display = "none";
    }
});

document.getElementById("add-member-submit-btn").onclick = async () => {
    if (!channel.startsWith("private:")) return;
    const channelId = channel.split(":")[1];
    const username = addMemberInput.value.trim();
    if (!username) { addMemberInput.focus(); return; }

    const resp = await fetch(`/private_channels/${channelId}/add_member`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username })
    });

    if (!resp.ok) {
        const msg = await resp.text();
        alert("Failed to add member: " + msg);
        return;
    }

    addMemberInput.value = "";
    loadChannelMembers(channelId);
};

