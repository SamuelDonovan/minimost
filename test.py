import os
import uuid
from time import time
from flask import (
    Flask, request, jsonify, render_template_string,
    send_from_directory
)
import os
import re
import hashlib
import secrets
from flask import session, redirect, url_for

# presence
USER_STATUS = {}  # username -> last active timestamp
ONLINE_TIMEOUT = 30  # seconds

from time import time

def is_online(user: str) -> bool:
    last = USER_STATUS.get(user)
    if not last:
        return False
    return time() - last < ONLINE_TIMEOUT


def dm_channel(u1: str, u2: str) -> str:
    a, b = sorted([u1, u2])
    return f"dm:{a}:{b}"

def is_dm(channel: str) -> bool:
    return channel.startswith("dm:")

def user_can_access(channel: str, user: str) -> bool:
    if not is_dm(channel):
        return True
    _, u1, u2 = channel.split(":")
    return user in (u1, u2)


def secure_filename(name: str) -> str:
    name = os.path.basename(name)
    name = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
    return name[:255]

def hash_password(password: str, salt: bytes | None = None):
    if salt is None:
        salt = secrets.token_bytes(16)
    pwd_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode(),
        salt,
        100_000
    )
    return salt, pwd_hash

def verify_password(password: str, salt: bytes, stored_hash: bytes) -> bool:
    check = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode(),
        salt,
        100_000
    )
    return secrets.compare_digest(check, stored_hash)

USERS = {}

def create_user(username: str, password: str):
    salt, pwd_hash = hash_password(password)
    USERS[username] = {
        "salt": salt,
        "hash": pwd_hash
    }

# Demo users
create_user("alice", "")
create_user("bob", "")
create_user("bob2", "hunter2")

from functools import wraps

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper

LOGIN_HTML = """
<!doctype html>
<title>Login</title>
<style>
body { font-family: sans-serif; background:#1e1e1e; color:#ddd; }
form { margin: 100px auto; width: 300px; }
input, button {
    width: 100%;
    margin-top: 8px;
    padding: 6px;
    background:#2d2d2d;
    color:#ddd;
    border:1px solid #444;
}
</style>

<form method="POST">
  <h2>MiniChat Login</h2>
  <input name="username" placeholder="Username">
  <input name="password" type="password" placeholder="Password">
  <button>Login</button>
  {% if error %}<p style="color:red">{{ error }}</p>{% endif %}
</form>
"""

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# In-memory storage
CHANNELS = {
    "general": [],
    "random": [],
    "dev": []
}

MAX_MESSAGES = 500


HTML = """
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>MiniChat</title>
<style>
body {
    margin: 0;
    font-family: sans-serif;
    background: #1e1e1e;
    color: #ddd;
    display: flex;
    height: 100vh;
}
#topbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    background: #2d2d2d;
    padding: 6px 10px;
    border-bottom: 1px solid #444;
}
#topbar input, #topbar button {
    margin-left: 4px;
}
#sidebar {
    width: 200px;
    background: #252526;
    padding: 10px;
}
#sidebar div {
    padding: 6px;
    cursor: pointer;
}
#sidebar div.active {
    background: #007acc;
}
#main {
    flex: 1;
    display: flex;
    flex-direction: column;
}
#chat {
    flex: 1;
    overflow-y: auto;
    padding: 10px;
}
.msg {
    margin-bottom: 8px;
}
.user {
    font-weight: bold;
    color: #6cf;
}
.time {
    color: #888;
    font-size: 0.8em;
}
button, input {
    background: #2d2d2d;
    color: #ddd;
    border: 1px solid #444;
}
#input {
    padding: 10px;
}
a { color: #9cdcfe; }
</style>
</head>
<body>

<div id="sidebar"></div>

<div id="main">
    <div id="topbar">
        <div>
            User: <b>{{ session["user"] }}</b>
            <a href="/logout">(logout)</a>
        </div>

        <div>
            Channel: <span id="chan"></span>
        </div>

        <div>
            DM:
            <input id="dm_user" placeholder="username" style="width:90px">
            <button onclick="startDM()">Go</button>
        </div>
    </div>

    <div id="chat"></div>

    <div id="input">
        <input id="msg" style="width:60%">
        <input type="file" id="file">
        <button onclick="send()">Send</button>
    </div>
</div>

<script>
let channel = "general";
let lastTs = 0;

function updateSidebarActive() {
    const divs = document.querySelectorAll("#sidebar div");
    divs.forEach(d => {
        d.classList.remove("active");
        if (d.dataset.channel === channel) {
            d.classList.add("active");
        }
    });
}

function loadChannels() {
    const sb = document.getElementById("sidebar");
    sb.innerHTML = "";

    const chTitle = document.createElement("b");
    chTitle.innerText = "Channels";
    sb.appendChild(chTitle);

    const dmTitle = document.createElement("b");
    dmTitle.innerText = "Direct Messages";

    Promise.all([
        fetch("/channels").then(r => r.json()),
        fetch("/dms").then(r => r.json()),
        fetch("/online_users").then(r => r.json())
    ]).then(([chs, dms, onlineUsers]) => {
        // Render normal channels
        chs.forEach(c => {
            const d = document.createElement("div");
            d.innerText = "# " + c;
            d.dataset.channel = c;
            d.className = (c === channel) ? "active" : "";
            d.onclick = () => switchChannel(c);
            sb.appendChild(d);
        });

        // DM section
        const hr = document.createElement("hr");
        sb.appendChild(hr);
        sb.appendChild(dmTitle);

        dms.forEach(dm => {
            const d = document.createElement("div");
            const online = onlineUsers.includes(dm.user);
            d.innerText = "@ " + dm.user + (online ? " ●" : " ○");
            d.style.color = online ? "#6cf" : "#888";
            d.dataset.channel = dm.channel;
            d.className = (dm.channel === channel) ? "active" : "";
            d.onclick = () => switchChannel(dm.channel);
            sb.appendChild(d);
        });
    });
}

function startDM() {
    const u = document.getElementById("dm_user").value.trim();
    if (!u) return;
    window.location = "/dm/" + encodeURIComponent(u);
}

function channelLabel(c) {
    if (c.startsWith("dm:")) {
        return "@ " + c.split(":").find(x => x !== "{{ session['user'] }}");
    }
    return "# " + c;
}

function switchChannel(c) {
    channel = c;
    lastTs = 0;
    document.getElementById("chat").innerHTML = "";
    document.getElementById("chan").innerText = channelLabel(c);
    fetchMessages();
    updateSidebarActive()
}

function fetchMessages() {
    fetch(`/messages/${channel}?since=${lastTs}`)
        .then(r=>r.json())
        .then(data=>{
            const chat = document.getElementById("chat");
            data.forEach(m=>{
                const d = document.createElement("div");
                d.className = "msg";
                d.innerHTML =
                    `<span class="time">[${new Date(m.ts*1000).toLocaleTimeString()}]</span>
                     <span class="user">${m.user}</span>: 
                     <span id="text-${m.id}">${m.text}</span>
                     ${m.file ? `<br><a href="/files/${m.file}" target="_blank">${m.file}</a>` : ""}
                     ${m.user === "{{ session['user'] }}" ?
                        `<button onclick="editMsg('${m.id}')">edit</button>` : ""}`;
                chat.appendChild(d);
                lastTs = Math.max(lastTs, m.ts);
            });
            chat.scrollTop = chat.scrollHeight;
        });
}

function send() {
    const text = document.getElementById("msg").value;
    const file = document.getElementById("file").files[0];

    if (!text && !file) return; // prevent empty sends

    const form = new FormData();
    form.append("text", text);
    if (file) form.append("file", file);

    fetch(`/send/${channel}`, {method:"POST", body: form});

    document.getElementById("msg").value = "";
    document.getElementById("file").value = "";
}

function editMsg(id) {
    const span = document.getElementById("text-" + id);
    const old = span.innerText;
    const input = document.createElement("input");
    input.value = old;
    input.onblur = ()=>{
        fetch(`/edit/${channel}/${id}`, {
            method:"POST",
            headers: {"Content-Type":"application/json"},
            body: JSON.stringify({text: input.value})
        });
        span.innerText = input.value;
        span.style.display = "inline";
        input.remove();
    };
    span.style.display = "none";
    span.parentNode.insertBefore(input, span);
    input.focus();
}

document.addEventListener("DOMContentLoaded", () => {
    if (!channel) channel = "general";
    loadChannels();
    switchChannel(channel);
    setInterval(fetchMessages, 1000); // polling
});
</script>
</body>
</html>
"""

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = request.form["username"]
        pw = request.form["password"]

        record = USERS.get(user)
        if record and verify_password(pw, record["salt"], record["hash"]):
            session["user"] = user
            return redirect(url_for("index"))

        return render_template_string(LOGIN_HTML, error="Invalid login")

    return render_template_string(LOGIN_HTML)

@app.route("/logout")
@login_required
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/")
@login_required
def index():
    return render_template_string(HTML, rand=int(time()) % 1000)

@app.route("/channels")
def channels():
    return jsonify(list(CHANNELS.keys()))

@app.route("/online_users")
@login_required
def online_users():
    return jsonify([u for u in USERS if is_online(u)])

@app.route("/messages/<channel>")
@login_required
def messages(channel):
    user = session["user"]
    USER_STATUS[session['user']] = time()

    if not user_can_access(channel, user):
        return jsonify([]), 403

    since = float(request.args.get("since", 0))
    return jsonify([m for m in CHANNELS.get(channel, []) if m["ts"] > since])

@app.route("/send/<channel>", methods=["POST"])
@login_required
def send(channel):
    user = session["user"]

    if not user_can_access(channel, user):
        return ("Forbidden", 403)

    if channel not in CHANNELS:
        CHANNELS[channel] = []

    text = request.form.get("text", "")
    file = request.files.get("file")

    fname = None
    if file and file.filename:
        fname = f"{uuid.uuid4()}_{secure_filename(file.filename)}"
        file.save(os.path.join(UPLOAD_DIR, fname))

    CHANNELS[channel].append({
        "id": str(uuid.uuid4()),
        "user": user,
        "text": text,
        "file": fname,
        "ts": time()
    })

    del CHANNELS[channel][:-MAX_MESSAGES]
    return ("", 204)

@app.route("/edit/<channel>/<mid>", methods=["POST"])
@login_required
def edit(channel, mid):
    user = session["user"]
    text = request.json["text"]

    for m in CHANNELS[channel]:
        if m["id"] == mid and m["user"] == user:
            m["text"] = text
            break
    return ("", 204)

@app.route("/dms")
@login_required
def dms():
    user = session["user"]
    seen = set()
    result = []

    for c in CHANNELS:
        if is_dm(c):
            _, u1, u2 = c.split(":")
            if user in (u1, u2):
                other = u2 if user == u1 else u1
                if other not in seen:
                    result.append({"channel": c, "user": other})
                    seen.add(other)

    return jsonify(result)

@app.route("/dm/<other>")
@login_required
def start_dm(other):
    user = session["user"]

    if other not in USERS or other == user:
        return redirect("/")

    channel = dm_channel(user, other)
    CHANNELS.setdefault(channel, [])

    return redirect(f"/#/{channel}")

@app.route("/files/<path:name>")
@login_required
def files(name):
    return send_from_directory(UPLOAD_DIR, name)

if __name__ == "__main__":
    app.run(host="archlinux", port=6767, debug=True)

