# From the python standard library
from time import time
import sqlite3
import os
import uuid 
from typing import List

# From Flask 
from flask import (
    request, jsonify, render_template, send_from_directory, session, Blueprint
)

# Local Imports
import common
import presence 
import auth 

chat_bp = Blueprint("chat", __name__)

# Shared helpers
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

def get_db(username: str):
    db = sqlite3.connect(common.user_db_path(username))
    db.row_factory = sqlite3.Row
    try:
        db.execute("ALTER TABLE messages ADD COLUMN deleted_ts REAL")
        db.commit()
    except sqlite3.OperationalError:
        pass
    return db

def all_users():
    db = sqlite3.connect(auth.AUTH_DB)
    rows = db.execute("SELECT username FROM users").fetchall()
    db.close()
    return [r[0] for r in rows]

# Channel Helpers
def normalize_dm(users: List[str]) -> str:
    users = sorted(set(users))
    return "dm:" + ":".join(users)

def channel_users(channel: str) -> List[str]:
    if channel.startswith("dm:"):
        return channel.split(":")[1:]
    return all_users()

# Channels endpoint
CHANNELS = ["general", "off-topic", "dev"]

@chat_bp.route("/channels")
@auth.login_required
def channels():
    return jsonify(CHANNELS)

@chat_bp.route("/unread_count")
@auth.login_required
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
@chat_bp.route("/dms")
@auth.login_required
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
@chat_bp.route("/online_users")
def online_users():
    presence_timeout = 3600 
    cutoff = int(time()) - presence_timeout 
    db = sqlite3.connect(presence.PRESENCE_DB)
    db.row_factory = sqlite3.Row

    rows = db.execute("""
        SELECT user, state
        FROM presence
        WHERE last_seen >= ?
    """, (cutoff,)).fetchall()

    db.close()

    # Normalize usernames and states
    return jsonify({
        row["user"].lower(): row["state"].lower()
        for row in rows
    })

# Fetch messages
@chat_bp.route("/messages/<channel>")
@auth.login_required
def messages(channel):
    user = session["user"]
    after = float(request.args.get("after", 0))

    db = get_db(user)
    rows = db.execute("""
        SELECT
            id,
            channel,
            sender,
            content,
            filename,
            ts,
            edited,
            edited_ts,
            deleted,
            deleted_ts
        FROM messages
        WHERE channel = ?
          AND (
                (deleted = 0 AND (ts > ? OR (edited = 1 AND edited_ts > ?)))
                OR (deleted = 1 AND deleted_ts > ?)
              )
        ORDER BY ts
    """, (channel, after, after, after)).fetchall()
    db.close()

    return jsonify([dict(r) for r in rows])


# Send
@chat_bp.route("/send/<channel>", methods=["POST"])
@auth.login_required
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

    ts = time()
    recipients = channel_users(channel)
    if sender not in recipients:
        recipients.append(sender)

    if not recipients:
        return "no recipients", 400

    for r in recipients:
        db = get_db(r)
        if text:
            db.execute("""
                INSERT INTO messages (channel, sender, content, filename, ts, read)
                VALUES (?, ?, ?, NULL, ?, 0)
            """, (channel, sender, text, ts))

        for filename in filenames:
            db.execute("""
                INSERT INTO messages (channel, sender, content, filename, ts, read)
                VALUES (?, ?, '', ?, ?, 0)
            """, (channel, sender, filename, ts))

        db.commit()
        db.close()

    return "ok"

@chat_bp.route("/files/<path:filename>")
@auth.login_required
def files(filename):
    return send_from_directory("uploads", filename)

# Search messages
@chat_bp.route("/search_messages")
@auth.login_required
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
          AND deleted = 0
        ORDER BY ts DESC
        LIMIT 50
        """,
        (f"%{query}%",)
    )
    results = [dict(r) for r in cur.fetchall()]
    db.close()
    return jsonify(results)

# Edit message
@chat_bp.route("/edit/<int:msg_id>", methods=["POST"])
@auth.login_required
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
        edited_time = time()
        db.execute(
            """
            UPDATE messages
            SET content = ?, edited = 1, edited_ts = ?
            WHERE channel = ? AND sender = ? AND ts = ? AND filename IS NULL
            """,
            (new_text, edited_time, channel, editor, ts)
        )
        db.commit()
        db.close()

    return "ok"

# Delete message (soft delete)
@chat_bp.route("/delete/<int:msg_id>", methods=["POST"])
@auth.login_required
def delete_message(msg_id):
    deleter = session["user"]

    db = get_db(deleter)
    row = db.execute(
        "SELECT channel, sender, ts FROM messages WHERE id = ?",
        (msg_id,)
    ).fetchone()
    db.close()

    if not row or row["sender"] != deleter:
        return "forbidden", 403

    channel = row["channel"]
    ts = row["ts"]
    deleted_time = time()

    recipients = channel_users(channel)
    if deleter not in recipients:
        recipients.append(deleter)

    for r in recipients:
        db = get_db(r)
        db.execute(
            """
            UPDATE messages
            SET deleted = 1, deleted_ts = ?
            WHERE channel = ? AND sender = ? AND ts = ?
            """,
            (deleted_time, channel, deleter, ts)
        )
        db.commit()
        db.close()

    return "ok"

@chat_bp.route("/mark_read/<channel>", methods=["POST"])
@auth.login_required
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


@chat_bp.route("/users")
@auth.login_required
def users():
    """Return all usernames except the current user"""
    me = session["user"]
    users = [u for u in all_users() if u != me]
    return jsonify(users)

@chat_bp.route("/")
@auth.login_required
def index():
    return render_template("chat.html")

