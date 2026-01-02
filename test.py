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

# Shared helpers
# presence
USER_STATUS = {}  # username -> last active timestamp
ONLINE_WINDOW = 30  # seconds

def now():
    return time()

def get_db(username: str):
    db = sqlite3.connect(common.user_db_path(username))
    db.row_factory = sqlite3.Row
    return db

def all_users():
    db = sqlite3.connect(common.AUTH_DB)
    rows = db.execute("SELECT username FROM users").fetchall()
    db.close()
    return [r[0] for r in rows]

def is_online(user: str) -> bool:
    return (now() - USER_STATUS.get(user, 0)) < ONLINE_WINDOW

# Channel Helpers
def normalize_dm(users: list[str]) -> str:
    users = sorted(set(users))
    return "dm:" + ":".join(users)

def channel_users(channel: str) -> list[str]:
    if channel.startswith("dm:"):
        return channel.split(":")[1:]
    return all_users()

# Channels endpoint
CHANNELS = ["general", "random", "dev"]

@common.app.route("/channels")
@common.login_required
def channels():
    return jsonify(CHANNELS)

# DM list for sidebar
@common.app.route("/dms")
@common.login_required
def dms():
    user = session["user"]
    db = get_db(user)

    rows = db.execute("""
        SELECT DISTINCT channel
        FROM messages
        WHERE channel LIKE 'dm:%'
        ORDER BY channel
    """).fetchall()
    db.close()

    result = []
    for r in rows:
        users = r["channel"].split(":")[1:]
        others = [u for u in users if u != user]
        result.append({
            "channel": r["channel"],
            "users": others
        })

    return jsonify(result)

# Presence endpoint
@common.app.route("/online_users")
@common.login_required
def online_users():
    return jsonify([u for u in all_users() if is_online(u)])

# Fetch messages
@common.app.route("/messages/<channel>")
@common.login_required
def messages(channel):
    user = session["user"]
    after = float(request.args.get("after", 0))

    db = get_db(user)
    rows = db.execute("""
        SELECT id, channel, sender, content, ts
        FROM messages
        WHERE channel = ? AND ts > ?
        ORDER BY ts
    """, (channel, after)).fetchall()
    db.close()

    USER_STATUS[user] = now()
    return jsonify([dict(r) for r in rows])

# Send
@common.app.route("/send/<channel>", methods=["POST"])
@common.login_required
def send(channel):
    sender = session["user"]
    text = (request.form.get("text") or "").rstrip()
    if not text:
        return "empty", 400

    ts = now()
    recipients = channel_users(channel)
    if sender not in recipients:
        recipients.append(sender)

    for r in recipients:
        common.init_user_db(r)
        db = get_db(r)
        db.execute("""
            INSERT INTO messages (channel, sender, content, ts)
            VALUES (?, ?, ?, ?)
        """, (channel, sender, text, ts))
        db.commit()
        db.close()

    USER_STATUS[sender] = ts
    return "ok"

# Edit message
@common.app.route("/edit/<int:msg_id>", methods=["POST"])
@common.login_required
def edit(msg_id):
    user = session["user"]
    new_text = request.form.get("text", "").strip()

    db = get_db(user)
    row = db.execute(
        "SELECT sender FROM messages WHERE id = ?",
        (msg_id,)
    ).fetchone()

    if not row or row["sender"] != user:
        db.close()
        return "forbidden", 403

    db.execute(
        "UPDATE messages SET content = ? WHERE id = ?",
        (new_text, msg_id)
    )
    db.commit()
    db.close()
    return "ok"

@common.app.route("/")
@common.login_required
def index():
    return render_template("chat.html")

if __name__ == "__main__":
    common.app.run(host=socket.gethostname(), port=6767, debug=True)

