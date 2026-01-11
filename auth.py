# From the python standard library
import sqlite3
from hashlib import sha256
import time

# From Flask 
from flask import session, redirect, url_for, request, render_template

# Local Imports
import common

def hash_password(password: str) -> str:
    return sha256(password.encode("utf-8")).hexdigest()

@common.app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]

        db = sqlite3.connect(common.AUTH_DB)
        row = db.execute(
            "SELECT password_hash FROM users WHERE username = ?",
            (username,)
        ).fetchone()
        db.close()

        if not row or row[0] != hash_password(password):
            # Delay to prevent users from brute forcing others passwords
            time.sleep(1)
            return render_template("login.html", error="Invalid credentials")

        session["user"] = username
        common.init_user_db(username)
        return redirect("/")

    return render_template("login.html")

@common.app.route("/logout")
@common.login_required
def logout():
    session.clear()
    return redirect(url_for("login"))

@common.app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]
        confirm = request.form["confirm_password"]

        if not username or not password:
            return render_template("signup.html", error="Missing fields")

        if password != confirm:
            return render_template(
                "signup.html",
                error="Passwords do not match"
            )

        db = sqlite3.connect(common.AUTH_DB)
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
        common.init_user_db(username)

        session["user"] = username
        return redirect("/")

    return render_template("signup.html")

def init_auth_db():
    db = sqlite3.connect(common.AUTH_DB)
    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL
        )
    """)
    db.commit()
    db.close()

init_auth_db()
