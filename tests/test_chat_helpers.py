"""Tests for chat module helper functions."""

import sqlite3

import minimost.auth as auth_mod
import minimost.chat as chat_mod
import minimost.common as common_mod
from werkzeug.security import generate_password_hash


def _add_user(username):
    db = sqlite3.connect(auth_mod.AUTH_DB)
    db.execute(
        "INSERT INTO users (username, password_hash) VALUES (?, ?)",
        (username, generate_password_hash("pw")),
    )
    db.commit()
    db.close()
    common_mod.init_user_db(username)


# ── normalize_dm ──────────────────────────────────────────────────────────────


def test_normalize_dm_sorts():
    assert chat_mod.normalize_dm(["bob", "alice"]) == "dm:alice:bob"


def test_normalize_dm_already_sorted():
    assert chat_mod.normalize_dm(["alice", "bob"]) == "dm:alice:bob"


def test_normalize_dm_deduplicates():
    assert chat_mod.normalize_dm(["alice", "alice"]) == "dm:alice"


def test_normalize_dm_three_users():
    result = chat_mod.normalize_dm(["charlie", "alice", "bob"])
    assert result == "dm:alice:bob:charlie"


# ── channel_users ─────────────────────────────────────────────────────────────


def test_channel_users_dm():
    users = chat_mod.channel_users("dm:alice:bob")
    assert "alice" in users
    assert "bob" in users


def test_channel_users_public():
    _add_user("alice")
    _add_user("bob")
    users = chat_mod.channel_users("general")
    assert "alice" in users
    assert "bob" in users


# ── is_valid_channel ──────────────────────────────────────────────────────────


def test_is_valid_channel_public_in_list():
    assert chat_mod.is_valid_channel("general", "alice") is True


def test_is_valid_channel_public_not_in_list():
    assert chat_mod.is_valid_channel("secret-room", "alice") is False


def test_is_valid_channel_dm_participant():
    assert chat_mod.is_valid_channel("dm:alice:bob", "alice") is True


def test_is_valid_channel_dm_not_participant():
    assert chat_mod.is_valid_channel("dm:alice:bob", "charlie") is False


def test_is_valid_channel_dm_too_few_parts():
    assert chat_mod.is_valid_channel("dm:alice", "alice") is False


# ── all_users ─────────────────────────────────────────────────────────────────


def test_all_users_empty():
    users = chat_mod.all_users()
    assert users == []


def test_all_users_returns_all():
    _add_user("alice")
    _add_user("bob")
    users = chat_mod.all_users()
    assert set(users) == {"alice", "bob"}


# ── get_db ────────────────────────────────────────────────────────────────────


def test_get_db_returns_connection():
    common_mod.init_user_db("alice")
    db = chat_mod.get_db("alice")
    assert db is not None
    db.close()


def test_get_db_row_factory():
    common_mod.init_user_db("alice")
    db = chat_mod.get_db("alice")
    assert db.row_factory == sqlite3.Row
    db.close()


# ── _load_channels ────────────────────────────────────────────────────────────


def test_load_channels_from_file(tmp_path, monkeypatch):
    settings_file = tmp_path / "settings.json"
    settings_file.write_text('{"channels": ["alpha", "beta"]}')
    monkeypatch.setattr(chat_mod, "_SETTINGS_FILE", settings_file)
    result = chat_mod._load_channels()
    assert result == ["alpha", "beta"]


def test_load_channels_fallback_on_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(chat_mod, "_SETTINGS_FILE", tmp_path / "no_file.json")
    result = chat_mod._load_channels()
    assert result == ["general"]


def test_load_channels_fallback_on_invalid_json(tmp_path, monkeypatch):
    bad_file = tmp_path / "settings.json"
    bad_file.write_text("not json{{{")
    monkeypatch.setattr(chat_mod, "_SETTINGS_FILE", bad_file)
    result = chat_mod._load_channels()
    assert result == ["general"]


# ── _load_valid_reactions ─────────────────────────────────────────────────────


def test_valid_reactions_contains_expected():
    assert "thumbsup" in chat_mod.VALID_REACTIONS
    assert "heart" in chat_mod.VALID_REACTIONS
    assert "fire" in chat_mod.VALID_REACTIONS


def test_valid_reactions_rejects_unknown():
    assert "readme" not in chat_mod.VALID_REACTIONS
    assert "unknown_emoji" not in chat_mod.VALID_REACTIONS


def test_valid_reactions_is_nonempty_set():
    assert isinstance(chat_mod.VALID_REACTIONS, set)
    assert len(chat_mod.VALID_REACTIONS) > 0


# ── _save_uploaded_files ──────────────────────────────────────────────────────


def test_save_uploaded_files_empty():
    result = chat_mod._save_uploaded_files([])
    assert result == []


def test_save_uploaded_files_no_filename():
    from unittest.mock import MagicMock

    f = MagicMock()
    f.filename = ""
    result = chat_mod._save_uploaded_files([f])
    assert result == []


def test_save_uploaded_files_invalid_extension():
    from unittest.mock import MagicMock

    f = MagicMock()
    f.filename = "script.exe"
    result = chat_mod._save_uploaded_files([f])
    assert result == []


def test_save_uploaded_files_valid_extension():
    from unittest.mock import MagicMock

    f = MagicMock()
    f.filename = "photo.png"
    f.save = MagicMock()
    result = chat_mod._save_uploaded_files([f])
    assert len(result) == 1
    assert result[0].endswith(".png")


def test_save_uploaded_files_no_hasattr_filename():
    result = chat_mod._save_uploaded_files([object()])
    assert result == []
