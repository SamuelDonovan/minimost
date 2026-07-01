"""Tests for the password-policy hardening (ASD STIG APSC-DV-001940 family).

Covers the minimum length (APSC-DV-001955), the required lowercase character
(APSC-DV-001960), the reuse prohibition (APSC-DV-001980), and the minimum /
maximum password-age controls (APSC-DV-001990 / 002000), plus the
:func:`minimost.auth._password_policy` reader semantics.
"""

import json
import secrets
import sqlite3
import time

from werkzeug.security import generate_password_hash

import minimost.auth as auth_mod

# A password that satisfies the full policy: >= 15 chars with an uppercase,
# lowercase, digit, and special character.
GOOD = "Password1!longer"


# ── Helpers ───────────────────────────────────────────────────────────────────


def _signup(client, user, pw=GOOD):
    return client.post(
        "/signup",
        data={"username": user, "password": pw, "confirm_password": pw},
        follow_redirects=False,
    )


def _backdate(user, seconds):
    """Age *user*'s ``password_set_ts`` by *seconds* so age checks can be driven."""
    db = sqlite3.connect(auth_mod.AUTH_DB)
    db.execute(
        "UPDATE users SET password_set_ts = ? WHERE username = ?",
        (time.time() - seconds, user),
    )
    db.commit()
    db.close()


def _change(client, user, current, new):
    """Change *user*'s password after satisfying the minimum-age window."""
    _backdate(user, 2 * 86400)
    return client.post(
        "/change-password",
        data={
            "current_password": current,
            "new_password": new,
            "confirm_password": new,
        },
    )


def _use_policy(monkeypatch, tmp_path, **overrides):
    """Point ``_password_policy`` at a temp settings.json with *overrides*.

    The bundled ``settings.json`` ships the age controls disabled (``0``), so a
    test that needs minimum/maximum age *enforced* writes its own settings file.
    Keys not listed fall back to the built-in code defaults.
    """
    settings = tmp_path / "policy_settings.json"
    settings.write_text(json.dumps(overrides))
    monkeypatch.setattr(auth_mod, "_SETTINGS_FILE", settings)


def _insert_token(user):
    token = secrets.token_urlsafe(32)
    db = sqlite3.connect(auth_mod.AUTH_DB)
    db.execute(
        "INSERT INTO password_reset_tokens (token, username, expires_ts, used)"
        " VALUES (?, ?, ?, 0)",
        (token, user, time.time() + 3600),
    )
    db.commit()
    db.close()
    return token


# ── Complexity: length (APSC-DV-001955) and lowercase (APSC-DV-001960) ─────────


def test_signup_rejects_password_under_15(client):
    # 14 chars: every complexity rule satisfied, one short of the minimum.
    resp = _signup(client, "u1", "Password1!abcd")
    assert resp.status_code == 200
    assert b"at least 15 characters" in resp.data


def test_signup_requires_lowercase(client):
    resp = _signup(client, "u1", "PASSWORD1!LONGER")
    assert resp.status_code == 200
    assert b"lowercase" in resp.data


def test_signup_accepts_compliant_password(client):
    resp = _signup(client, "u1")
    assert resp.status_code == 302


# ── Reuse prohibition on change / reset (APSC-DV-001980) ───────────────────────


def test_change_rejects_reused_password(client):
    _signup(client, "u1")
    resp = _change(client, "u1", GOOD, GOOD)
    assert resp.status_code == 400
    assert "last 5 passwords" in resp.get_json()["error"]


def test_reuse_window_is_exactly_the_last_five(client):
    _signup(client, "u1")  # history: [GOOD]
    rotation = [
        "Passw0rd!aaaaaa",
        "Passw0rd!bbbbbb",
        "Passw0rd!cccccc",
        "Passw0rd!dddddd",
    ]
    current = GOOD
    for pw in rotation:
        assert _change(client, "u1", current, pw).status_code == 200
        current = pw
    # History now holds the last five: [GOOD, a, b, c, d]; reusing GOOD is barred.
    assert _change(client, "u1", current, GOOD).status_code == 400
    # One more change pushes GOOD out of the window, so it becomes reusable.
    newest = "Passw0rd!eeeeee"
    assert _change(client, "u1", current, newest).status_code == 200
    assert _change(client, "u1", newest, GOOD).status_code == 200


def test_reset_prohibits_reuse(client):
    _signup(client, "u1")  # history: [GOOD]
    token = _insert_token("u1")
    resp = client.post(
        f"/reset-password/{token}",
        data={"password": GOOD, "confirm_password": GOOD},
    )
    assert resp.status_code == 200
    assert b"last 5 passwords" in resp.data


# ── Minimum age (APSC-DV-001990) ───────────────────────────────────────────────


def test_change_blocked_within_min_age(client, monkeypatch, tmp_path):
    _use_policy(monkeypatch, tmp_path, password_min_age_hours=24)
    _signup(client, "u1")  # password_set_ts = now
    new = "Different2!longer"
    resp = client.post(
        "/change-password",
        data={"current_password": GOOD, "new_password": new, "confirm_password": new},
    )
    assert resp.status_code == 400
    assert "too recently" in resp.get_json()["error"]


def test_change_allowed_after_min_age(client, monkeypatch, tmp_path):
    _use_policy(monkeypatch, tmp_path, password_min_age_hours=24)
    _signup(client, "u1")
    _backdate("u1", 2 * 86400)  # older than the 24h minimum age
    new = "Different2!longer"
    resp = client.post(
        "/change-password",
        data={"current_password": GOOD, "new_password": new, "confirm_password": new},
    )
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True


def test_reset_is_exempt_from_min_age(client, monkeypatch, tmp_path):
    _use_policy(monkeypatch, tmp_path, password_min_age_hours=24)
    _signup(client, "u1")  # password_set_ts = now (would block a change)
    token = _insert_token("u1")
    new = "Different2!longer"
    resp = client.post(
        f"/reset-password/{token}",
        data={"password": new, "confirm_password": new},
    )
    assert resp.status_code == 200
    assert b"updated" in resp.data.lower() or b"success" in resp.data.lower()


# ── Maximum age (APSC-DV-002000) ───────────────────────────────────────────────


def test_login_refused_when_password_expired(client, monkeypatch, tmp_path):
    _use_policy(monkeypatch, tmp_path, password_max_age_days=60)
    _signup(client, "u1")
    client.get("/logout")
    _backdate("u1", 61 * 86400)  # older than the 60-day maximum
    resp = client.post(
        "/login", data={"username": "u1", "password": GOOD}, follow_redirects=False
    )
    assert resp.status_code == 200
    assert b"expired" in resp.data
    with client.session_transaction() as sess:
        assert "user" not in sess  # no session established


def test_login_ok_within_max_age(client, monkeypatch, tmp_path):
    _use_policy(monkeypatch, tmp_path, password_max_age_days=60)
    _signup(client, "u1")
    client.get("/logout")
    resp = client.post(
        "/login", data={"username": "u1", "password": GOOD}, follow_redirects=False
    )
    assert resp.status_code == 302


def test_login_ok_when_password_set_ts_missing(client):
    # A row without password_set_ts (a pre-feature account inserted directly) is
    # grandfathered in rather than treated as already expired.
    db = sqlite3.connect(auth_mod.AUTH_DB)
    db.execute(
        "INSERT INTO users (username, password_hash) VALUES (?, ?)",
        ("legacy", generate_password_hash(GOOD)),
    )
    db.commit()
    db.close()
    resp = client.post(
        "/login", data={"username": "legacy", "password": GOOD}, follow_redirects=False
    )
    assert resp.status_code == 302


# ── _password_policy reader semantics ──────────────────────────────────────────


def test_policy_reads_shipped_settings():
    # Reflects the bundled settings.json: length and reuse ship enforced, while
    # the two age controls ship disabled (0) as a documented risk acceptance.
    p = auth_mod._password_policy()
    assert p["min_length"] == 15
    assert p["history_count"] == 5
    assert p["min_age_seconds"] == 0
    assert p["max_age_seconds"] == 0


def test_policy_reads_enabled_age_values(tmp_path, monkeypatch):
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps({"password_min_age_hours": 24, "password_max_age_days": 60})
    )
    monkeypatch.setattr(auth_mod, "_SETTINGS_FILE", settings)
    p = auth_mod._password_policy()
    assert p["min_age_seconds"] == 24 * 3600
    assert p["max_age_seconds"] == 60 * 86400


def test_policy_min_length_cannot_be_lowered(tmp_path, monkeypatch):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"password_min_length": 4}))
    monkeypatch.setattr(auth_mod, "_SETTINGS_FILE", settings)
    assert auth_mod._password_policy()["min_length"] == 15


def test_policy_min_length_can_be_raised(tmp_path, monkeypatch):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"password_min_length": 20}))
    monkeypatch.setattr(auth_mod, "_SETTINGS_FILE", settings)
    assert auth_mod._password_policy()["min_length"] == 20


def test_policy_zero_disables_reuse_and_age(tmp_path, monkeypatch):
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "password_history_count": 0,
                "password_min_age_hours": 0,
                "password_max_age_days": 0,
            }
        )
    )
    monkeypatch.setattr(auth_mod, "_SETTINGS_FILE", settings)
    p = auth_mod._password_policy()
    assert p["history_count"] == 0
    assert p["min_age_seconds"] == 0
    assert p["max_age_seconds"] == 0


def test_policy_falls_back_when_settings_unreadable(tmp_path, monkeypatch):
    monkeypatch.setattr(auth_mod, "_SETTINGS_FILE", tmp_path / "missing.json")
    p = auth_mod._password_policy()
    assert p["min_length"] == 15
    assert p["history_count"] == 5
