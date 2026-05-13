# From the python standard library
from functools import wraps
import sqlite3
from hashlib import sha256
import secrets
import time

# From Flask
from flask import session, redirect, request, render_template, Blueprint

# Local Imports
import common
import presence
import email_utils

AUTH_DB = "auth.db"

auth_bp = Blueprint("auth", __name__)

def hash_password(password: str) -> str:
    return sha256(password.encode("utf-8")).hexdigest()

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if "user" not in session:
            return redirect("/login")
        return fn(*args, **kwargs)
    return wrapper

@auth_bp.route("/login", methods=["GET", "POST"])
@auth_bp.route("/login.html", methods=["GET", "POST"])
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
            # Delay to prevent brute-forcing
            time.sleep(3)
            return render_template("login.html", error="Invalid credentials")

        session["user"] = username
        common.init_user_db(username)
        return redirect("/")

    return render_template("login.html")

@auth_bp.route("/logout")
@login_required
def logout():
    user = session.get("user")
    presence.update_presence(user, "offline")
    session.clear()
    return redirect("/login")

@auth_bp.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]
        confirm  = request.form["confirm_password"]
        email    = request.form.get("email", "").strip()

        if not username or not password:
            return render_template("signup.html", error="Missing fields")

        if password != confirm:
            return render_template("signup.html", error="Passwords do not match")

        if not email or "@" not in email:
            return render_template("signup.html", error="A valid email address is required")

        db = sqlite3.connect(AUTH_DB)
        try:
            db.execute(
                "INSERT INTO users (username, password_hash, email) VALUES (?, ?, ?)",
                (username, hash_password(password), email)
            )
            db.commit()
        except sqlite3.IntegrityError:
            db.close()
            return render_template("signup.html", error="User already exists")

        db.close()
        common.init_user_db(username)
        session["user"] = username
        return redirect("/")

    return render_template("signup.html")

@auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        username = request.form["username"].strip()

        db = sqlite3.connect(AUTH_DB)
        db.execute("DELETE FROM reset_tokens WHERE expires_at < ?", (time.time(),))

        row = db.execute(
            "SELECT email FROM users WHERE username = ?",
            (username,)
        ).fetchone()

        if row and row[0]:
            token      = secrets.token_urlsafe(32)
            expires_at = time.time() + 3600
            db.execute(
                "INSERT OR REPLACE INTO reset_tokens (token, username, expires_at) VALUES (?, ?, ?)",
                (token, username, expires_at)
            )
            db.commit()
            reset_link = request.host_url.rstrip("/") + f"/reset/{token}"
            email_utils.send_reset_email(row[0], username, reset_link)

        db.close()

        # Always show the same page to prevent username enumeration
        return render_template("reset_confirm.html")

    return render_template("forgot_password.html")

@auth_bp.route("/reset/<token>")
def reset_account(token):
    db = sqlite3.connect(AUTH_DB)
    row = db.execute(
        "SELECT username, expires_at FROM reset_tokens WHERE token = ?",
        (token,)
    ).fetchone()

    if not row or row[1] < time.time():
        db.close()
        return render_template("reset_done.html", expired=True)

    username = row[0]
    db.execute("DELETE FROM users WHERE username = ?", (username,))
    db.execute("DELETE FROM reset_tokens WHERE token = ?", (token,))
    db.commit()
    db.close()

    return render_template("reset_done.html", expired=False, username=username)
