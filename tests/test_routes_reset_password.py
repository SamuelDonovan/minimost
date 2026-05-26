"""Tests for password reset: CLI command and web routes."""

import sqlite3
import time

import pytest
from werkzeug.security import check_password_hash, generate_password_hash

import minimost.auth as auth_mod
import minimost.common as common_mod

# ── Helpers ───────────────────────────────────────────────────────────────────


def _add_user(username, password="Password1!"):
    db = sqlite3.connect(auth_mod.AUTH_DB)
    db.execute(
        "INSERT INTO users (username, password_hash) VALUES (?, ?)",
        (username, generate_password_hash(password)),
    )
    db.commit()
    db.close()
    common_mod.init_user_db(username)


def _insert_token(username, expires_delta=3600, used=0):
    """Insert a reset token and return the token string."""
    import secrets

    token = secrets.token_urlsafe(32)
    db = sqlite3.connect(auth_mod.AUTH_DB)
    db.execute(
        "INSERT INTO password_reset_tokens (token, username, expires_ts, used)"
        " VALUES (?, ?, ?, ?)",
        (token, username, time.time() + expires_delta, used),
    )
    db.commit()
    db.close()
    return token


def _get_password_hash(username):
    db = sqlite3.connect(auth_mod.AUTH_DB)
    row = db.execute(
        "SELECT password_hash FROM users WHERE username = ?", (username,)
    ).fetchone()
    db.close()
    return row[0] if row else None


def _token_used(token):
    db = sqlite3.connect(auth_mod.AUTH_DB)
    row = db.execute(
        "SELECT used FROM password_reset_tokens WHERE token = ?", (token,)
    ).fetchone()
    db.close()
    return bool(row and row[0])


# ── GET /reset-password/<token> ───────────────────────────────────────────────


def test_reset_form_valid_token(client):
    _add_user("alice")
    token = _insert_token("alice")
    resp = client.get(f"/reset-password/{token}")
    assert resp.status_code == 200
    assert b"Set new password" in resp.data


def test_reset_form_invalid_token(client):
    resp = client.get("/reset-password/notarealtoken")
    assert resp.status_code == 200
    assert b"invalid" in resp.data.lower() or b"expired" in resp.data.lower()


def test_reset_form_expired_token(client):
    _add_user("alice")
    token = _insert_token("alice", expires_delta=-1)
    resp = client.get(f"/reset-password/{token}")
    assert resp.status_code == 200
    assert b"invalid" in resp.data.lower() or b"expired" in resp.data.lower()


def test_reset_form_used_token(client):
    _add_user("alice")
    token = _insert_token("alice", used=1)
    resp = client.get(f"/reset-password/{token}")
    assert resp.status_code == 200
    assert b"invalid" in resp.data.lower() or b"expired" in resp.data.lower()


# ── POST /reset-password/<token> ──────────────────────────────────────────────


def test_reset_post_success(client):
    _add_user("alice")
    token = _insert_token("alice")
    resp = client.post(
        f"/reset-password/{token}",
        data={"password": "NewPass1!", "confirm_password": "NewPass1!"},
    )
    assert resp.status_code == 200
    assert b"updated" in resp.data.lower() or b"success" in resp.data.lower()


def test_reset_post_updates_password_hash(client):
    _add_user("alice", password="Password1!")
    token = _insert_token("alice")
    client.post(
        f"/reset-password/{token}",
        data={"password": "NewPass1!", "confirm_password": "NewPass1!"},
    )
    new_hash = _get_password_hash("alice")
    assert new_hash is not None
    assert check_password_hash(new_hash, "NewPass1!")
    assert not check_password_hash(new_hash, "Password1!")


def test_reset_post_marks_token_used(client):
    _add_user("alice")
    token = _insert_token("alice")
    client.post(
        f"/reset-password/{token}",
        data={"password": "NewPass1!", "confirm_password": "NewPass1!"},
    )
    assert _token_used(token)


def test_reset_post_token_cannot_be_reused(client):
    _add_user("alice")
    token = _insert_token("alice")
    client.post(
        f"/reset-password/{token}",
        data={"password": "NewPass1!", "confirm_password": "NewPass1!"},
    )
    resp = client.post(
        f"/reset-password/{token}",
        data={"password": "AnotherPass1!", "confirm_password": "AnotherPass1!"},
    )
    assert resp.status_code == 200
    assert b"invalid" in resp.data.lower() or b"expired" in resp.data.lower()


def test_reset_post_invalid_token(client):
    resp = client.post(
        "/reset-password/notarealtoken",
        data={"password": "NewPass1!", "confirm_password": "NewPass1!"},
    )
    assert resp.status_code == 200
    assert b"invalid" in resp.data.lower() or b"expired" in resp.data.lower()


def test_reset_post_expired_token(client):
    _add_user("alice")
    token = _insert_token("alice", expires_delta=-1)
    resp = client.post(
        f"/reset-password/{token}",
        data={"password": "NewPass1!", "confirm_password": "NewPass1!"},
    )
    assert resp.status_code == 200
    assert b"invalid" in resp.data.lower() or b"expired" in resp.data.lower()


def test_reset_post_password_too_short(client):
    _add_user("alice")
    token = _insert_token("alice")
    resp = client.post(
        f"/reset-password/{token}",
        data={"password": "Short1!", "confirm_password": "Short1!"},
    )
    assert resp.status_code == 200
    assert b"8 characters" in resp.data


def test_reset_post_no_uppercase(client):
    _add_user("alice")
    token = _insert_token("alice")
    resp = client.post(
        f"/reset-password/{token}",
        data={"password": "newpass1!", "confirm_password": "newpass1!"},
    )
    assert resp.status_code == 200
    assert b"uppercase" in resp.data


def test_reset_post_no_number(client):
    _add_user("alice")
    token = _insert_token("alice")
    resp = client.post(
        f"/reset-password/{token}",
        data={"password": "NewPassword!", "confirm_password": "NewPassword!"},
    )
    assert resp.status_code == 200
    assert b"number" in resp.data


def test_reset_post_no_special(client):
    _add_user("alice")
    token = _insert_token("alice")
    resp = client.post(
        f"/reset-password/{token}",
        data={"password": "NewPassword1", "confirm_password": "NewPassword1"},
    )
    assert resp.status_code == 200
    assert b"special" in resp.data


def test_reset_post_passwords_mismatch(client):
    _add_user("alice")
    token = _insert_token("alice")
    resp = client.post(
        f"/reset-password/{token}",
        data={"password": "NewPass1!", "confirm_password": "NewPass1!!"},
    )
    assert resp.status_code == 200
    assert b"match" in resp.data


# ── CLI: minimost reset-password ──────────────────────────────────────────────


def test_cli_reset_unknown_user(capsys):
    from minimost.__main__ import _cmd_reset_password

    with pytest.raises(SystemExit) as exc:
        _cmd_reset_password(["nobody"])
    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "does not exist" in captured.err


def test_cli_reset_creates_token():
    _add_user("alice")
    from minimost.__main__ import _cmd_reset_password

    _cmd_reset_password(["alice"])

    db = sqlite3.connect(auth_mod.AUTH_DB)
    row = db.execute(
        "SELECT token FROM password_reset_tokens WHERE username = 'alice'"
    ).fetchone()
    db.close()
    assert row is not None


def test_cli_reset_prints_url(capsys):
    _add_user("alice")
    from minimost.__main__ import _cmd_reset_password

    _cmd_reset_password(["alice", "--base-url", "http://chat.example.com"])
    captured = capsys.readouterr()
    assert "http://chat.example.com/reset-password/" in captured.out


def test_cli_reset_custom_expiry():
    _add_user("alice")
    from minimost.__main__ import _cmd_reset_password

    before = time.time()
    _cmd_reset_password(["alice", "--expires", "30"])
    after = time.time()

    db = sqlite3.connect(auth_mod.AUTH_DB)
    row = db.execute(
        "SELECT expires_ts FROM password_reset_tokens WHERE username = 'alice'"
    ).fetchone()
    db.close()
    assert before + 29 * 60 <= row[0] <= after + 31 * 60


def test_cli_reset_sends_dm():
    _add_user("alice")
    from minimost.__main__ import _cmd_reset_password

    _cmd_reset_password(["alice"])

    user_db = sqlite3.connect(str(common_mod.user_db_path("alice")))
    row = user_db.execute(
        "SELECT sender, content_type FROM messages WHERE sender = 'system'"
    ).fetchone()
    user_db.close()
    assert row is not None
    assert row[1] == "system"


def test_cli_reset_no_dm_when_no_user_db():
    """If user DB hasn't been created yet, the token is still stored."""
    _add_user("alice")
    # Don't call init_user_db — simulate a user with no DB file
    db_path = common_mod.user_db_path("alice")
    if db_path.exists():
        db_path.unlink()

    from minimost.__main__ import _cmd_reset_password

    _cmd_reset_password(["alice"])

    db = sqlite3.connect(auth_mod.AUTH_DB)
    row = db.execute(
        "SELECT token FROM password_reset_tokens WHERE username = 'alice'"
    ).fetchone()
    db.close()
    assert row is not None


def test_cli_reset_singular_minute(capsys):
    _add_user("alice")
    from minimost.__main__ import _cmd_reset_password

    _cmd_reset_password(["alice", "--expires", "1"])
    captured = capsys.readouterr()
    assert "1 minute)" in captured.out
