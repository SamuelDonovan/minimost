# From the python standard library
from functools import wraps
import sqlite3
from hashlib import sha256
import time

# From Flask
from flask import session, redirect, request, render_template, Blueprint

# Local Imports
from . import common
from . import presence

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
            "SELECT password_hash FROM users WHERE username = ?", (username,)
        ).fetchone()
        db.close()

        if not row or row[0] != hash_password(password):
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

        if password != confirm:
            return render_template("signup.html", error="Passwords do not match")

        db = sqlite3.connect(AUTH_DB)
        try:
            db.execute(
                "INSERT INTO users VALUES (?, ?)", (username, hash_password(password))
            )
            db.commit()
        except sqlite3.IntegrityError:
            db.close()
            return render_template("signup.html", error="User already exists")

        db.close()

        # create per-user chat DB
        common.init_user_db(username)

        session["user"] = username
        return redirect("/")

    return render_template("signup.html")
