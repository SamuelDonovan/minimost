# From the python standard library
from time import time
import socket 
import sqlite3
import os
import re
import uuid 

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

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

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
CHANNELS = ["general", "off-topic", "dev"]

@common.app.route("/channels")
@common.login_required
def channels():
    return jsonify(CHANNELS)

@common.app.route("/unread_count")
@common.login_required
def unread_count():
    user = session["user"]
    db = get_db(user)

    row = db.execute("""
        SELECT
            COALESCE(SUM(
                CASE
                    WHEN read = 0 AND sender != ?
                    THEN 1 ELSE 0
                END
            ), 0) AS unread
        FROM messages
        WHERE channel LIKE 'dm:%'
          AND (
                channel LIKE 'dm:' || ? || ':%'
             OR channel LIKE 'dm:%:' || ?
             OR channel LIKE 'dm:%:' || ? || ':%'
          )
    """, (user, user, user, user)).fetchone()

    count = row["unread"]
    return {"count": count}


# DM list for sidebar
@common.app.route("/dms")
@common.login_required
def dms():
    user = session["user"]
    db = get_db(user)

    rows = db.execute("""
        SELECT
            channel,
            MAX(ts) AS last_ts,
            COALESCE(SUM(
                CASE
                    WHEN read = 0 AND sender != ?
                    THEN 1 ELSE 0
                END
            ), 0) AS unread
        FROM messages
        WHERE channel LIKE 'dm:%'
          AND (
                channel LIKE 'dm:' || ? || ':%'
             OR channel LIKE 'dm:%:' || ?
             OR channel LIKE 'dm:%:' || ? || ':%'
          )
        GROUP BY channel
        ORDER BY last_ts DESC
    """, (user, user, user, user)).fetchall()

    db.close()

    result = []
    for r in rows:
        users = r["channel"].split(":")[1:]
        others = [u for u in users if u != user]

        result.append({
            "channel": r["channel"],
            "users": others,
            "unread": int(r["unread"])  # 🔑 ensure JS-safe
        })

    return jsonify(result)

# Presence endpoint
@common.app.route("/online_users")
def online_users():
    now = time()
    return jsonify([u for u, ts in USER_STATUS.items() if now - ts < 60])

# Fetch messages
@common.app.route("/messages/<channel>")
@common.login_required
def messages(channel):
    user = session["user"]
    after = float(request.args.get("after", 0))

    db = get_db(user)
    rows = db.execute("""
        SELECT id, channel, sender, content, filename, ts, edited
        FROM messages
        WHERE channel = ?
          AND (
                ts > ?
                OR edited = 1
              )
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

    files = request.files.getlist("files")
    filenames = []

    for f in files:
        # 🔒 Guard: ensure this is a FileStorage
        if not hasattr(f, "filename"):
            continue

        if not f.filename:
            continue

        ext = os.path.splitext(f.filename)[1] or ".png"
        filename = f"{uuid.uuid4().hex}{ext}"

        f.save(os.path.join(UPLOAD_DIR, filename))
        filenames.append(filename)

    # prevent empty messages
    if not text and not filenames:
        return "empty", 400

    ts = now()
    recipients = channel_users(channel)
    if sender not in recipients:
        recipients.append(sender)

    if not recipients:
        return "no recipients", 400

    for r in recipients:
        db = get_db(r)
        # insert ONE message row (text only)
        db.execute("""
            INSERT INTO messages (channel, sender, content, filename, ts, read)
            VALUES (?, ?, ?, NULL, ?, 0)
        """, (channel, sender, text, ts))

# insert image rows (no text)
        for filename in filenames:
            db.execute("""
                INSERT INTO messages (channel, sender, content, filename, ts)
                VALUES (?, ?, '', ?, ?)
            """, (channel, sender, filename, ts))

        db.commit()
        db.close()

    USER_STATUS[sender] = ts
    return "ok"

@common.app.route("/files/<path:filename>")
@common.login_required
def files(filename):
    return send_from_directory("uploads", filename)

# Search messages
@common.app.route("/search_messages")
@common.login_required
def search_messages():
    user = session["user"]
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify([])

    db = get_db(user)

    # Search in all messages (limit results for performance)
    cur = db.execute(
        """
        SELECT id, channel, sender, content, ts
        FROM messages
        WHERE content LIKE ?
        ORDER BY ts DESC
        LIMIT 50
        """,
        (f"%{query}%",)
    )
    results = [dict(r) for r in cur.fetchall()]
    db.close()
    return jsonify(results)

# Edit message
@common.app.route("/edit/<int:msg_id>", methods=["POST"])
@common.login_required
def edit(msg_id):
    editor = session["user"]
    new_text = request.form.get("text", "").strip()

    # 1. Fetch message metadata from editor DB
    db = get_db(editor)
    row = db.execute(
        "SELECT channel, sender, ts FROM messages WHERE id = ?",
        (msg_id,)
    ).fetchone()
    db.close()

    if not row or row["sender"] != editor:
        return "forbidden", 403

    channel = row["channel"]
    ts = row["ts"]

    # 2. Determine all recipients
    recipients = channel_users(channel)
    if editor not in recipients:
        recipients.append(editor)

    # 3. Update the message in each recipient DB using timestamp
    for r in recipients:
        db = get_db(r)
        db.execute(
            "UPDATE messages SET content = ?, edited = 1 WHERE channel = ? AND sender = ? AND ts = ?",
            (new_text, channel, editor, ts)
        )
        db.commit()
        db.close()

    return "ok"

@common.app.route("/mark_read/<channel>", methods=["POST"])
@common.login_required
def mark_read(channel):
    user = session["user"]
    db = get_db(user)

    db.execute("""
        UPDATE messages
        SET read = 1
        WHERE channel = ?
          AND sender != ?
    """, (channel, user))

    db.commit()
    db.close()
    return "", 204


@common.app.route("/users")
@common.login_required
def users():
    """Return all usernames except the current user"""
    me = session["user"]
    users = [u for u in all_users() if u != me]
    return jsonify(users)

@common.app.route("/")
@common.login_required
def index():
    return render_template("chat.html")

if __name__ == "__main__":
    common.app.run(host="0.0.0.0", port=6767, debug=True)

