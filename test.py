# From the python standard library
from time import time
import socket 
import sqlite3
import os
import re

# From Flask 
from flask import (
    request, jsonify, render_template, send_from_directory, session, redirect
)

# Local Imports
import common
import auth 

# presence
USER_STATUS = {}  # username -> last active timestamp
ONLINE_TIMEOUT = 30  # seconds

def search_users(query):
    db = sqlite3.connect(common.AUTH_DB)
    db.row_factory = sqlite3.Row
    cur = db.cursor()
    cur.execute(
        "SELECT username FROM users WHERE username LIKE ?",
        ('%' + query + '%',)
    )
    rows = cur.fetchall()
    db.close()
    return [r["username"] for r in rows]

def get_db(username: str):
    db = sqlite3.connect(common.user_db_path(username))
    db.row_factory = sqlite3.Row
    return db

def all_users():
    db = sqlite3.connect(common.AUTH_DB)
    rows = db.execute("SELECT username FROM users").fetchall()
    db.close()
    return [r[0] for r in rows]

def channel_recipients(channel: str):
    if channel.startswith("dm:"):
        _, u1, u2 = channel.split(":")
        return [u1, u2]
    else:
        return all_users()

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

USERS = {}


UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# In-memory storage
CHANNELS = {
    "general": [],
    "random": [],
    "dev": []
}

@common.app.route("/")
@common.login_required
def index():
    return render_template("chat.html")

@common.app.route("/channels")
def channels():
    return jsonify(list(CHANNELS.keys()))

@common.app.route("/online_users")
@common.login_required
def online_users():
    return jsonify([u for u in USERS if is_online(u)])

@common.app.route("/messages/<channel>")
@common.login_required
def messages(channel):
    user = session["user"]
    after = float(request.args.get("after", 0))

    db = get_db(user)
    cur = db.execute(
        """
        SELECT id, channel, sender, content, filename, ts
        FROM messages
        WHERE channel = ? AND ts > ?
        ORDER BY ts
        """,
        (channel, after)
    )
    rows = [dict(r) for r in cur.fetchall()]
    db.close()

    USER_STATUS[user] = time()
    return jsonify(rows)

@common.app.route("/send/<channel>", methods=["POST"])
@common.login_required
def send(channel):
    user = session["user"]
    text = (
        request.form.get("msg")
        or request.form.get("text")
        or ""
    ).strip()

    ts = time()

    recipients = channel_recipients(channel)
    if not recipients:
        return "no recipients", 400

    for recipient in recipients:
        common.init_user_db(recipient)
        db = get_db(recipient)
        db.execute(
            """
            INSERT INTO messages (channel, sender, content, ts)
            VALUES (?, ?, ?, ?)
            """,
            (channel, user, text, ts)
        )
        db.commit()
        db.close()

    USER_STATUS[user] = ts
    return "ok"

@common.app.route("/edit/<int:msg_id>", methods=["POST"])
@common.login_required
def edit(msg_id):
    user = session["user"]
    new_text = request.form["text"]

    db = get_db(user)
    db.execute(
        """
        UPDATE messages
        SET content = ?
        WHERE id = ? AND sender = ?
        """,
        (new_text, msg_id, user)
    )
    db.commit()
    db.close()

    return "ok"

def dm_channel(user1: str, user2: str) -> str:
    a, b = sorted([user1, user2])
    return f"dm:{a}:{b}"

def dm_recipients(channel: str) -> list[str]:
    if not channel.startswith("dm:"):
        return []  # Not a DM
    _, u1, u2 = channel.split(":")
    return [u1, u2]

@common.app.route("/send/dm/<target>", methods=["POST"])
@common.login_required
def send_dm(target):
    sender = session["user"]
    text = (request.form.get("msg") or request.form.get("text") or "").strip()
    if not text:
        return "empty message", 400

    channel = dm_channel(sender, target)
    ts = time()

    for recipient in dm_recipients(channel):
        common.init_user_db(recipient)
        db = get_db(recipient)
        db.execute(
            "INSERT INTO messages (channel, sender, content, ts) VALUES (?, ?, ?, ?)",
            (channel, sender, text, ts)
        )
        db.commit()
        db.close()

    USER_STATUS[sender] = ts
    return "ok"

@common.app.route("/messages/dm/<other_user>")
@common.login_required
def fetch_dm_messages(other_user):
    user = session["user"]
    channel = dm_channel(user, other_user)
    since = float(request.args.get("since", 0))

    db = get_db(user)
    rows = db.execute(
        "SELECT sender, content, ts FROM messages WHERE channel=? AND ts>? ORDER BY ts",
        (channel, since)
    ).fetchall()
    db.close()

    messages = [{"sender": r[0], "content": r[1], "ts": r[2]} for r in rows]
    return jsonify(messages)

@common.app.route("/search_users")
@common.login_required
def search_users():
    q = request.args.get("q", "").strip().lower()
    if not q:
        return jsonify([])

    db = sqlite3.connect(common.AUTH_DB)
    users = [row[0] for row in db.execute(
        "SELECT username FROM users WHERE lower(username) LIKE ? LIMIT 10",
        (f"%{q}%",)
    ).fetchall()]
    db.close()

    # exclude current user
    users = [u for u in users if u != session["user"]]
    return jsonify(users)

@common.app.route("/dms")
@common.login_required
def dms():
    user = session["user"]
    seen = set()
    result = []

    for other in USERS:
        if other != user:
            ch = dm_channel(user, other)
            if other not in seen:
                result.append({"user": other, "channel": ch})
                seen.add(other)

    return jsonify(result)

@common.app.route("/dm/<other>")
@common.login_required
def start_dm(other):
    user = session["user"]

    if other not in USERS or other == user:
        return redirect("/")

    channel = dm_channel(user, other)
    CHANNELS.setdefault(channel, [])

    return redirect(f"/#/{channel}")

@common.app.route("/users")
def users():
    search = request.args.get("search", "")
    if not search:
        return jsonify([])
    matches = search_users(search)
    return jsonify(matches)

@common.app.route("/files/<path:name>")
@common.login_required
def files(name):
    return send_from_directory(UPLOAD_DIR, name)

if __name__ == "__main__":
    common.app.run(host=socket.gethostname(), port=6767, debug=True)

