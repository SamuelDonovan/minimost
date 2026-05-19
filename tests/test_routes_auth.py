"""Tests for auth routes: login, logout, signup."""

import sqlite3
from unittest.mock import patch
from werkzeug.security import generate_password_hash

import minimost.auth as auth_mod
import minimost.common as common_mod


def _add_user(username, password="Password1!"):
    db = sqlite3.connect(auth_mod.AUTH_DB)
    db.execute(
        "INSERT INTO users (username, password_hash) VALUES (?, ?)",
        (username, generate_password_hash(password)),
    )
    db.commit()
    db.close()
    common_mod.init_user_db(username)


# ── GET /login ────────────────────────────────────────────────────────────────


def test_login_get(client):
    resp = client.get("/login")
    assert resp.status_code == 200
    assert b"login" in resp.data.lower()


def test_login_html_alias(client):
    resp = client.get("/login.html")
    assert resp.status_code == 200


# ── POST /login ───────────────────────────────────────────────────────────────


def test_login_post_invalid_credentials(client):
    _add_user("alice")
    with patch("minimost.auth.time.sleep"):
        resp = client.post(
            "/login",
            data={"username": "alice", "password": "wrongpass"},
        )
    assert resp.status_code == 200
    assert b"Invalid credentials" in resp.data


def test_login_post_unknown_user(client):
    with patch("minimost.auth.time.sleep"):
        resp = client.post(
            "/login",
            data={"username": "nobody", "password": "Password1!"},
        )
    assert resp.status_code == 200
    assert b"Invalid credentials" in resp.data


def test_login_post_success(client):
    _add_user("alice")
    resp = client.post(
        "/login",
        data={"username": "alice", "password": "Password1!"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.location == "/"


def test_login_post_sets_session(client):
    _add_user("alice")
    client.post("/login", data={"username": "alice", "password": "Password1!"})
    with client.session_transaction() as sess:
        assert sess.get("user") == "alice"


# ── GET /logout ───────────────────────────────────────────────────────────────


def test_logout_unauthenticated(client):
    resp = client.get("/logout", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.location


def test_logout_clears_session(alice):
    alice.get("/logout")
    with alice.session_transaction() as sess:
        assert "user" not in sess


def test_logout_redirects_to_login(alice):
    resp = alice.get("/logout", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.location


# ── GET /signup ───────────────────────────────────────────────────────────────


def test_signup_get(client):
    resp = client.get("/signup")
    assert resp.status_code == 200


# ── POST /signup ──────────────────────────────────────────────────────────────


def test_signup_validation_error(client):
    resp = client.post(
        "/signup",
        data={"username": "x", "password": "weak", "confirm_password": "weak"},
    )
    assert resp.status_code == 200
    assert b"error" in resp.data.lower() or resp.status_code == 200


def test_signup_passwords_mismatch(client):
    resp = client.post(
        "/signup",
        data={
            "username": "alice",
            "password": "Password1!",
            "confirm_password": "Password1!!",
        },
    )
    assert resp.status_code == 200


def test_signup_success(client):
    resp = client.post(
        "/signup",
        data={
            "username": "newuser",
            "password": "Password1!",
            "confirm_password": "Password1!",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.location == "/"


def test_signup_creates_user_in_db(client):
    client.post(
        "/signup",
        data={
            "username": "newuser",
            "password": "Password1!",
            "confirm_password": "Password1!",
        },
    )
    db = sqlite3.connect(auth_mod.AUTH_DB)
    row = db.execute("SELECT username FROM users WHERE username='newuser'").fetchone()
    db.close()
    assert row is not None


def test_signup_duplicate_user(client):
    _add_user("alice")
    resp = client.post(
        "/signup",
        data={
            "username": "alice",
            "password": "Password1!",
            "confirm_password": "Password1!",
        },
    )
    assert resp.status_code == 200
    assert b"already exists" in resp.data


def test_signup_sets_session(client):
    client.post(
        "/signup",
        data={
            "username": "newuser",
            "password": "Password1!",
            "confirm_password": "Password1!",
        },
    )
    with client.session_transaction() as sess:
        assert sess.get("user") == "newuser"


def test_signup_seeds_history(client):
    """New user gets public channel history from existing user's DB."""
    _add_user("existing")
    import time

    existing_db = sqlite3.connect(str(common_mod.user_db_path("existing")))
    existing_db.execute(
        "INSERT INTO messages (channel, sender, content, ts, read) VALUES (?, ?, ?, ?, ?)",
        ("general", "existing", "hello world", time.time(), 1),
    )
    existing_db.commit()
    existing_db.close()

    client.post(
        "/signup",
        data={
            "username": "newuser",
            "password": "Password1!",
            "confirm_password": "Password1!",
        },
    )

    new_db = sqlite3.connect(str(common_mod.user_db_path("newuser")))
    count = new_db.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    new_db.close()
    assert count == 1
