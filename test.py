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
create_user("alice", "password123")
create_user("bob", "hunter2")

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
    <div style="padding: 6px">
        User: <b>{{ session["user"] }}</b>
<a href="/logout">logout</a>
        Channel: <span id="chan"></span>
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

function loadChannels() {
    fetch("/channels").then(r=>r.json()).then(chs=>{
        const sb = document.getElementById("sidebar");
        sb.innerHTML = "";
        chs.forEach(c=>{
            const d = document.createElement("div");
            d.innerText = "# " + c;
            if (c === channel) d.className = "active";
            d.onclick = ()=>switchChannel(c);
            sb.appendChild(d);
        });
    });
}

function switchChannel(c) {
    channel = c;
    lastTs = 0;
    document.getElementById("chat").innerHTML = "";
    document.getElementById("chan").innerText = "#" + c;
    loadChannels();
}

function fetchMessages() {
    fetch(`/messages/${channel}?since=${lastTs}`)
        .then(r=>r.json())
        .then(data=>{
            console.log("DEBUG: fetched messages:", data);
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

setInterval(fetchMessages, 1000);
loadChannels();
switchChannel("general");
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

@app.route("/messages/<channel>")
@login_required
def messages(channel):
    since = float(request.args.get("since", 0))
    return jsonify([m for m in CHANNELS[channel] if m["ts"] > since])

@app.route("/send/<channel>", methods=["POST"])
@login_required
def send(channel):
    user = session["user"]
    text = request.form.get("text", "")
    file = request.files.get("file")

    fname = None
    if file:
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

@app.route("/files/<path:name>")
@login_required
def files(name):
    return send_from_directory(UPLOAD_DIR, name)

if __name__ == "__main__":
    app.run(host="archlinux", port=6767, debug=True)

