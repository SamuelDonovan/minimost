import os
import uuid
from time import time
from flask import (
    Flask, request, jsonify, render_template_string, render_template, send_from_directory
)
import os
import re
import hashlib
import secrets
from flask import session, redirect, url_for
from time import time
from functools import wraps

# presence
USER_STATUS = {}  # username -> last active timestamp
ONLINE_TIMEOUT = 30  # seconds

import sqlite3
from pathlib import Path

DB_DIR = Path("users")
DB_DIR.mkdir(exist_ok=True)

import sqlite3
from hashlib import sha256

AUTH_DB = "auth.db"

def search_users(query):
    db = sqlite3.connect(AUTH_DB)
    db.row_factory = sqlite3.Row
    cur = db.cursor()
    cur.execute(
        "SELECT username FROM users WHERE username LIKE ?",
        ('%' + query + '%',)
    )
    rows = cur.fetchall()
    db.close()
    return [r["username"] for r in rows]


def init_auth_db():
    db = sqlite3.connect(AUTH_DB)
    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL
        )
    """)
    db.commit()
    db.close()

init_auth_db()

def hash_password(password: str) -> str:
    return sha256(password.encode("utf-8")).hexdigest()

def user_db_path(username: str) -> Path:
    return DB_DIR / f"{username}.db"

def get_db(username: str):
    db = sqlite3.connect(user_db_path(username))
    db.row_factory = sqlite3.Row
    return db

def init_user_db(username: str):
    path = user_db_path(username)
    db = sqlite3.connect(path)
    cur = db.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        channel TEXT NOT NULL,
        sender TEXT NOT NULL,
        content TEXT,
        filename TEXT,
        ts REAL
    )
    """)

    db.commit()
    db.close()

def all_users():
    db = sqlite3.connect(AUTH_DB)
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

def hash_password_salt(password: str, salt: bytes | None = None):
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
    salt, pwd_hash = hash_password_salt(password)
    USERS[username] = {
        "salt": salt,
        "hash": pwd_hash
    }



def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if "user" not in session:
            return redirect("/login")
        return fn(*args, **kwargs)
    return wrapper

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

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]

        if not username or not password:
            return render_template("signup.html", error="Missing fields")

        db = sqlite3.connect(AUTH_DB)
        try:
            db.execute(
                "INSERT INTO users VALUES (?, ?)",
                (username, hash_password(password))
            )
            db.commit()
        except sqlite3.IntegrityError:
            db.close()
            return render_template("signup.html", error="User already exists")

        db.close()

        # create per-user chat DB
        init_user_db(username)

        session["user"] = username
        return redirect("/")

    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]

        db = sqlite3.connect(AUTH_DB)
        row = db.execute(
            "SELECT password_hash FROM users WHERE username = ?",
            (username,)
        ).fetchone()
        db.close()

        if not row or row[0] != hash_password(password):
            return render_template("login.html", error="Invalid credentials")

        session["user"] = username
        init_user_db(username)
        return redirect("/")

    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/")
@login_required
def index():
    return render_template("chat.html")

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

from time import time

@app.route("/send/<channel>", methods=["POST"])
@login_required
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
        init_user_db(recipient)
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

@app.route("/edit/<int:msg_id>", methods=["POST"])
@login_required
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

@app.route("/dms")
@login_required
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

@app.route("/dm/<other>")
@login_required
def start_dm(other):
    user = session["user"]

    if other not in USERS or other == user:
        return redirect("/")

    channel = dm_channel(user, other)
    CHANNELS.setdefault(channel, [])

    return redirect(f"/#/{channel}")

@app.route("/users")
def users():
    search = request.args.get("search", "")
    if not search:
        return jsonify([])
    matches = search_users(search)
    return jsonify(matches)

@app.route("/files/<path:name>")
@login_required
def files(name):
    return send_from_directory(UPLOAD_DIR, name)

if __name__ == "__main__":
    app.run(host="archlinux", port=6767, debug=True)

