"""Tests for settings, avatar, user-colour, and DM-close routes.

Covers:
  GET  /user_colors
  GET  /settings
  POST /settings
  GET  /user_avatars
  GET  /avatar/<username>
  POST /avatar
  DELETE /avatar
  POST /dms/close
"""

import io
import json
import sqlite3

import minimost.auth as auth_mod
import minimost.chat as chat_mod
import minimost.common as common_mod

# ── helpers ───────────────────────────────────────────────────────────────────


def _set_name_color(username, color):
    db = sqlite3.connect(auth_mod.AUTH_DB)
    db.execute(
        "INSERT INTO user_settings (username, name_color) VALUES (?, ?)"
        " ON CONFLICT(username) DO UPDATE SET name_color = excluded.name_color",
        (username, color),
    )
    db.commit()
    db.close()


def _set_avatar_file(username, filename):
    db = sqlite3.connect(auth_mod.AUTH_DB)
    db.execute(
        "INSERT INTO user_settings (username, avatar_file) VALUES (?, ?)"
        " ON CONFLICT(username) DO UPDATE SET avatar_file = excluded.avatar_file",
        (username, filename),
    )
    db.commit()
    db.close()


def _get_avatar_file(username):
    db = sqlite3.connect(auth_mod.AUTH_DB)
    row = db.execute(
        "SELECT avatar_file FROM user_settings WHERE username = ?", (username,)
    ).fetchone()
    db.close()
    return row[0] if row else None


# ── GET /user_colors ──────────────────────────────────────────────────────────


def test_user_colors_unauthenticated(client):
    resp = client.get("/user_colors")
    assert resp.status_code == 302


def test_user_colors_empty(alice):
    resp = alice.get("/user_colors")
    assert resp.status_code == 200
    assert resp.get_json() == {}


def test_user_colors_returns_set_colors(alice):
    _set_name_color("alice", "#ff0000")
    resp = alice.get("/user_colors")
    data = resp.get_json()
    assert data["alice"] == "#ff0000"


def test_user_colors_excludes_null(alice):
    # Insert a row with NULL name_color — should not appear in result
    db = sqlite3.connect(auth_mod.AUTH_DB)
    db.execute(
        "INSERT INTO user_settings (username, name_color) VALUES (?, NULL)"
        " ON CONFLICT(username) DO NOTHING",
        ("alice",),
    )
    db.commit()
    db.close()
    resp = alice.get("/user_colors")
    data = resp.get_json()
    assert "alice" not in data


def test_user_colors_multiple_users(alice_and_bob):
    _set_name_color("alice", "#aabbcc")
    _set_name_color("bob", "#112233")
    resp = alice_and_bob.get("/user_colors")
    data = resp.get_json()
    assert data["alice"] == "#aabbcc"
    assert data["bob"] == "#112233"


# ── GET /settings ─────────────────────────────────────────────────────────────


def test_get_settings_unauthenticated(client):
    resp = client.get("/settings")
    assert resp.status_code == 302


def test_get_settings_default_null(alice):
    resp = alice.get("/settings")
    assert resp.status_code == 200
    assert resp.get_json()["name_color"] is None


def test_get_settings_returns_color(alice):
    _set_name_color("alice", "#123456")
    resp = alice.get("/settings")
    assert resp.get_json()["name_color"] == "#123456"


# ── POST /settings ────────────────────────────────────────────────────────────


def test_save_settings_unauthenticated(client):
    resp = client.post(
        "/settings",
        data=json.dumps({"name_color": "#ff0000"}),
        content_type="application/json",
    )
    assert resp.status_code == 302


def test_save_settings_valid_color(alice):
    resp = alice.post(
        "/settings",
        data=json.dumps({"name_color": "#abcdef"}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.data == b"ok"
    assert _get_color("alice") == "#abcdef"


def test_save_settings_invalid_color(alice):
    resp = alice.post(
        "/settings",
        data=json.dumps({"name_color": "notacolor"}),
        content_type="application/json",
    )
    assert resp.status_code == 400


def test_save_settings_invalid_color_short_hex(alice):
    resp = alice.post(
        "/settings",
        data=json.dumps({"name_color": "#fff"}),
        content_type="application/json",
    )
    assert resp.status_code == 400


def test_save_settings_null_color_clears(alice):
    _set_name_color("alice", "#ff0000")
    resp = alice.post(
        "/settings",
        data=json.dumps({"name_color": None}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert _get_color("alice") is None


def test_save_settings_empty_body_no_crash(alice):
    resp = alice.post("/settings", data="{}", content_type="application/json")
    assert resp.status_code == 200


def test_save_settings_roundtrip(alice):
    alice.post(
        "/settings",
        data=json.dumps({"name_color": "#aabbcc"}),
        content_type="application/json",
    )
    resp = alice.get("/settings")
    assert resp.get_json()["name_color"] == "#aabbcc"


def _get_color(username):
    db = sqlite3.connect(auth_mod.AUTH_DB)
    row = db.execute(
        "SELECT name_color FROM user_settings WHERE username = ?", (username,)
    ).fetchone()
    db.close()
    return row[0] if row else None


# ── GET /user_avatars ─────────────────────────────────────────────────────────


def test_user_avatars_unauthenticated(client):
    resp = client.get("/user_avatars")
    assert resp.status_code == 302


def test_user_avatars_empty(alice):
    resp = alice.get("/user_avatars")
    assert resp.status_code == 200
    assert resp.get_json() == []


def test_user_avatars_returns_users_with_avatars(alice):
    _set_avatar_file("alice", "somefile.jpg")
    resp = alice.get("/user_avatars")
    assert "alice" in resp.get_json()


def test_user_avatars_excludes_null(alice):
    # Row exists but avatar_file is NULL — should not appear
    db = sqlite3.connect(auth_mod.AUTH_DB)
    db.execute(
        "INSERT INTO user_settings (username, avatar_file) VALUES (?, NULL)"
        " ON CONFLICT(username) DO NOTHING",
        ("alice",),
    )
    db.commit()
    db.close()
    resp = alice.get("/user_avatars")
    assert "alice" not in resp.get_json()


# ── GET /avatar/<username> ────────────────────────────────────────────────────


def test_get_avatar_unauthenticated(client):
    resp = client.get("/avatar/alice")
    assert resp.status_code == 302


def test_get_avatar_no_entry(alice):
    resp = alice.get("/avatar/alice")
    assert resp.status_code == 404


def test_get_avatar_null_file(alice):
    # Row exists but avatar_file is NULL
    db = sqlite3.connect(auth_mod.AUTH_DB)
    db.execute(
        "INSERT INTO user_settings (username, avatar_file) VALUES (?, NULL)"
        " ON CONFLICT(username) DO NOTHING",
        ("alice",),
    )
    db.commit()
    db.close()
    resp = alice.get("/avatar/alice")
    assert resp.status_code == 404


def test_get_avatar_returns_image(alice, tmp_path, monkeypatch):
    avatar_dir = tmp_path / "avatars"
    avatar_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(chat_mod, "AVATAR_DIR", avatar_dir)

    fname = "test_avatar.jpg"
    (avatar_dir / fname).write_bytes(b"\xff\xd8\xff" + b"\x00" * 10)
    _set_avatar_file("alice", fname)

    resp = alice.get("/avatar/alice")
    assert resp.status_code == 200
    resp.close()  # release the send_file handle so it isn't GC'd as a ResourceWarning


# ── POST /avatar ──────────────────────────────────────────────────────────────


def test_upload_avatar_unauthenticated(client):
    resp = client.post("/avatar")
    assert resp.status_code == 302


def test_upload_avatar_no_file(alice):
    resp = alice.post("/avatar", data={}, content_type="multipart/form-data")
    assert resp.status_code == 400


def test_upload_avatar_success(alice, tmp_path, monkeypatch):
    avatar_dir = tmp_path / "avatars"
    avatar_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(chat_mod, "AVATAR_DIR", avatar_dir)

    img = io.BytesIO(b"\xff\xd8\xff" + b"\x00" * 10)
    resp = alice.post(
        "/avatar",
        data={"avatar": (img, "photo.jpg")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    assert resp.data == b"ok"


def test_upload_avatar_stores_filename_in_db(alice, tmp_path, monkeypatch):
    avatar_dir = tmp_path / "avatars"
    avatar_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(chat_mod, "AVATAR_DIR", avatar_dir)

    img = io.BytesIO(b"\xff\xd8\xff" + b"\x00" * 10)
    alice.post(
        "/avatar",
        data={"avatar": (img, "photo.jpg")},
        content_type="multipart/form-data",
    )
    assert _get_avatar_file("alice") is not None


def test_upload_avatar_replaces_old_file(alice, tmp_path, monkeypatch):
    avatar_dir = tmp_path / "avatars"
    avatar_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(chat_mod, "AVATAR_DIR", avatar_dir)

    # Create old avatar file and record it
    old_fname = "old_avatar.jpg"
    (avatar_dir / old_fname).write_bytes(b"\xff\xd8\xff")
    _set_avatar_file("alice", old_fname)

    img = io.BytesIO(b"\xff\xd8\xff" + b"\x00" * 10)
    alice.post(
        "/avatar",
        data={"avatar": (img, "new.jpg")},
        content_type="multipart/form-data",
    )

    # Old file should be deleted
    assert not (avatar_dir / old_fname).exists()
    # New file is different
    new_fname = _get_avatar_file("alice")
    assert new_fname != old_fname


def test_upload_avatar_old_file_missing_no_crash(alice, tmp_path, monkeypatch):
    """FileNotFoundError when deleting old avatar is handled gracefully."""
    avatar_dir = tmp_path / "avatars"
    avatar_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(chat_mod, "AVATAR_DIR", avatar_dir)

    # Record a filename that doesn't exist on disk
    _set_avatar_file("alice", "ghost.jpg")

    img = io.BytesIO(b"\xff\xd8\xff" + b"\x00" * 10)
    resp = alice.post(
        "/avatar",
        data={"avatar": (img, "new.jpg")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200


# ── DELETE /avatar ────────────────────────────────────────────────────────────


def test_delete_avatar_unauthenticated(client):
    resp = client.delete("/avatar")
    assert resp.status_code == 302


def test_delete_avatar_no_avatar_set(alice):
    resp = alice.delete("/avatar")
    assert resp.status_code == 200
    assert resp.data == b"ok"


def test_delete_avatar_clears_db(alice, tmp_path, monkeypatch):
    avatar_dir = tmp_path / "avatars"
    avatar_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(chat_mod, "AVATAR_DIR", avatar_dir)

    fname = "to_delete.jpg"
    (avatar_dir / fname).write_bytes(b"\xff\xd8\xff")
    _set_avatar_file("alice", fname)

    resp = alice.delete("/avatar")
    assert resp.status_code == 200
    assert _get_avatar_file("alice") is None
    assert not (avatar_dir / fname).exists()


def test_delete_avatar_file_missing_no_crash(alice, tmp_path, monkeypatch):
    """FileNotFoundError when deleting avatar file is handled gracefully."""
    avatar_dir = tmp_path / "avatars"
    avatar_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(chat_mod, "AVATAR_DIR", avatar_dir)

    _set_avatar_file("alice", "ghost.jpg")

    resp = alice.delete("/avatar")
    assert resp.status_code == 200


# ── POST /dms/close ───────────────────────────────────────────────────────────


def test_close_dm_unauthenticated(client):
    resp = client.post(
        "/dms/close",
        data=json.dumps({"channel": "dm:alice:bob"}),
        content_type="application/json",
    )
    assert resp.status_code == 302


def test_close_dm_success(alice_and_bob):
    resp = alice_and_bob.post(
        "/dms/close",
        data=json.dumps({"channel": "dm:alice:bob"}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.data == b"ok"


def test_close_dm_invalid_channel(alice):
    resp = alice.post(
        "/dms/close",
        data=json.dumps({"channel": "general"}),
        content_type="application/json",
    )
    assert resp.status_code == 400


def test_close_dm_empty_channel(alice):
    resp = alice.post(
        "/dms/close",
        data=json.dumps({"channel": ""}),
        content_type="application/json",
    )
    assert resp.status_code == 400


def test_close_dm_forbidden_not_participant(alice_and_bob):
    # alice tries to close a DM she is not part of
    resp = alice_and_bob.post(
        "/dms/close",
        data=json.dumps({"channel": "dm:bob:charlie"}),
        content_type="application/json",
    )
    assert resp.status_code == 403


def test_close_dm_hides_from_dms_list(alice_and_bob):
    """After closing, the DM should not appear in GET /dms."""
    ch = "dm:alice:bob"
    # Send a message first so the DM appears
    alice_and_bob.post(f"/send/{ch}", data={"text": "hello"})

    # Verify it appears
    dms_before = alice_and_bob.get("/dms").get_json()
    assert any(d["channel"] == ch for d in dms_before)

    # Close it
    alice_and_bob.post(
        "/dms/close",
        data=json.dumps({"channel": ch}),
        content_type="application/json",
    )

    dms_after = alice_and_bob.get("/dms").get_json()
    assert not any(d["channel"] == ch for d in dms_after)


def test_close_dm_reappears_after_new_message(alice_and_bob, app):
    """Closing a DM and then receiving a new message should resurface it."""
    ch = "dm:alice:bob"
    alice_and_bob.post(f"/send/{ch}", data={"text": "first"})

    alice_and_bob.post(
        "/dms/close",
        data=json.dumps({"channel": ch}),
        content_type="application/json",
    )

    # Bob sends a new message (written directly to alice's DB after the hidden_ts)
    import time as time_mod

    db = sqlite3.connect(str(common_mod.user_db_path("alice")))
    db.execute(
        "INSERT INTO messages (channel, sender, content, ts, read) VALUES (?,?,?,?,0)",
        (ch, "bob", "resurface me", time_mod.time() + 1),
    )
    db.commit()
    db.close()

    dms = alice_and_bob.get("/dms").get_json()
    assert any(d["channel"] == ch for d in dms)
