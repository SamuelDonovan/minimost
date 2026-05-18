"""Tests for presence routes: typing and presence updates."""
import sqlite3
import time

import minimost.presence as presence_mod


# ── POST /typing/<channel> ────────────────────────────────────────────────────

def test_typing_unauthenticated_returns_204(client):
    resp = client.post("/typing/general")
    assert resp.status_code == 204


def test_typing_authenticated_stores_record(alice):
    resp = alice.post("/typing/general")
    assert resp.status_code == 204
    db = sqlite3.connect(presence_mod.PRESENCE_DB)
    row = db.execute(
        "SELECT user, channel FROM typing WHERE user='alice' AND channel='general'"
    ).fetchone()
    db.close()
    assert row is not None


# ── GET /typing/<channel> ─────────────────────────────────────────────────────

def test_typing_get_unauthenticated(client):
    resp = client.get("/typing/general")
    assert resp.status_code == 200
    assert resp.get_json() == []


def test_typing_get_no_one_typing(alice):
    data = alice.get("/typing/general").get_json()
    assert data == []


def test_typing_get_shows_others(alice_and_bob, app):
    now = int(time.time())
    pdb = sqlite3.connect(presence_mod.PRESENCE_DB)
    pdb.execute(
        "INSERT OR REPLACE INTO typing (user, channel, ts) VALUES (?, ?, ?)",
        ("bob", "general", now),
    )
    pdb.commit()
    pdb.close()
    data = alice_and_bob.get("/typing/general").get_json()
    assert "bob" in data


def test_typing_get_excludes_self(alice):
    now = int(time.time())
    pdb = sqlite3.connect(presence_mod.PRESENCE_DB)
    pdb.execute(
        "INSERT OR REPLACE INTO typing (user, channel, ts) VALUES (?, ?, ?)",
        ("alice", "general", now),
    )
    pdb.commit()
    pdb.close()
    data = alice.get("/typing/general").get_json()
    assert "alice" not in data


def test_typing_get_excludes_stale(alice_and_bob):
    old_ts = int(time.time()) - 10
    pdb = sqlite3.connect(presence_mod.PRESENCE_DB)
    pdb.execute(
        "INSERT OR REPLACE INTO typing (user, channel, ts) VALUES (?, ?, ?)",
        ("bob", "general", old_ts),
    )
    pdb.commit()
    pdb.close()
    data = alice_and_bob.get("/typing/general").get_json()
    assert "bob" not in data


# ── POST /presence ────────────────────────────────────────────────────────────

def test_presence_unauthenticated_returns_204(client):
    resp = client.post(
        "/presence", json={"state": "active"}, content_type="application/json"
    )
    assert resp.status_code == 204


def test_presence_valid_state(alice):
    resp = alice.post("/presence", json={"state": "active"})
    assert resp.status_code == 204
    db = sqlite3.connect(presence_mod.PRESENCE_DB)
    row = db.execute("SELECT state FROM presence WHERE user='alice'").fetchone()
    db.close()
    assert row is not None
    assert row[0] == "active"


def test_presence_invalid_state(alice):
    resp = alice.post("/presence", json={"state": "flying"})
    assert resp.status_code == 204
    db = sqlite3.connect(presence_mod.PRESENCE_DB)
    row = db.execute("SELECT state FROM presence WHERE user='alice'").fetchone()
    db.close()
    assert row is None


def test_presence_all_valid_states(alice):
    for state in ("active", "idle", "hidden", "offline"):
        alice.post("/presence", json={"state": state})
        db = sqlite3.connect(presence_mod.PRESENCE_DB)
        row = db.execute("SELECT state FROM presence WHERE user='alice'").fetchone()
        db.close()
        assert row[0] == state


def test_presence_no_json_body(alice):
    resp = alice.post("/presence", data="", content_type="application/json")
    assert resp.status_code == 204


# ── update_presence (direct) ──────────────────────────────────────────────────

def test_update_presence_valid():
    presence_mod.update_presence("testuser", "active")
    db = sqlite3.connect(presence_mod.PRESENCE_DB)
    row = db.execute("SELECT state FROM presence WHERE user='testuser'").fetchone()
    db.close()
    assert row is not None
    assert row[0] == "active"


def test_update_presence_invalid_state():
    presence_mod.update_presence("testuser", "invisible")
    db = sqlite3.connect(presence_mod.PRESENCE_DB)
    row = db.execute("SELECT state FROM presence WHERE user='testuser'").fetchone()
    db.close()
    assert row is None
