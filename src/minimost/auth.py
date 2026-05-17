# From the python standard library
import re
from functools import wraps
import sqlite3
import time
from pathlib import Path

# From Flask
from flask import session, redirect, request, render_template, Blueprint
from werkzeug.security import generate_password_hash, check_password_hash

# Local Imports
from . import common
from . import presence

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent.parent
AUTH_DB = str(_PROJECT_ROOT / "auth.db")

_USERNAME_RE = re.compile(r"[A-Za-z0-9_\-]{1,32}")

auth_bp = Blueprint("auth", __name__)


def hash_password(password: str) -> str:
    return generate_password_hash(password)


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
        db.execute("PRAGMA journal_mode=WAL")
        row = db.execute(
            "SELECT password_hash FROM users WHERE username = ?", (username,)
        ).fetchone()
        db.close()

        if not row or not check_password_hash(row[0], password):
            # Delay to prevent users from brute forcing others passwords
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
        confirm = request.form["confirm_password"]

        if not username or not password:
            return render_template("signup.html", error="Missing fields")

        if not _USERNAME_RE.fullmatch(username):
            return render_template(
                "signup.html",
                error="Username may only contain letters, numbers, hyphens, and underscores (1–32 characters)",
            )

        if password != confirm:
            return render_template("signup.html", error="Passwords do not match")

        db = sqlite3.connect(AUTH_DB)
        db.execute("PRAGMA journal_mode=WAL")
        try:
            db.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (username, hash_password(password)),
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
