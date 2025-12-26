import os
import uuid
from time import time
from flask import (
    Flask, request, jsonify, render_template_string,
    send_from_directory
)
import os
import re

def secure_filename(name: str) -> str:
    name = os.path.basename(name)
    name = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
    return name[:255]

app = Flask(__name__)

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
        User: <input id="user" value="user{{ rand }}">
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
            const chat = document.getElementById("chat");
            data.forEach(m=>{
                const d = document.createElement("div");
                d.className = "msg";
                d.innerHTML =
                    `<span class="time">[${new Date(m.ts*1000).toLocaleTimeString()}]</span>
                     <span class="user">${m.user}</span>: 
                     <span id="text-${m.id}">${m.text}</span>
                     ${m.file ? `<br><a href="/files/${m.file}" target="_blank">${m.file}</a>` : ""}
                     ${m.user === document.getElementById("user").value ?
                        `<button onclick="editMsg('${m.id}')">edit</button>` : ""}`;
                chat.appendChild(d);
                lastTs = Math.max(lastTs, m.ts);
            });
            chat.scrollTop = chat.scrollHeight;
        });
}

function send() {
    const user = document.getElementById("user").value;
    const text = document.getElementById("msg").value;
    const file = document.getElementById("file").files[0];

    const form = new FormData();
    form.append("user", user);
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

@app.route("/")
def index():
    return render_template_string(HTML, rand=int(time()) % 1000)

@app.route("/channels")
def channels():
    return jsonify(list(CHANNELS.keys()))

@app.route("/messages/<channel>")
def messages(channel):
    since = float(request.args.get("since", 0))
    return jsonify([m for m in CHANNELS[channel] if m["ts"] > since])

@app.route("/send/<channel>", methods=["POST"])
def send(channel):
    user = request.form["user"]
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
def edit(channel, mid):
    text = request.json["text"]
    for m in CHANNELS[channel]:
        if m["id"] == mid:
            m["text"] = text
            break
    return ("", 204)

@app.route("/files/<path:name>")
def files(name):
    return send_from_directory(UPLOAD_DIR, name)

if __name__ == "__main__":
    app.run(debug=True)

