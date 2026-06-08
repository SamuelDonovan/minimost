"""Tests targeting specific uncovered branches."""

import runpy
import sqlite3
import time
from unittest.mock import patch

import minimost.chat as chat_mod
import minimost.common as common_mod
import minimost.preview as preview

# ── preview._is_safe_url exception branch ────────────────────────────────────


def test_is_safe_url_parse_exception():
    with patch("urllib.parse.urlparse", side_effect=Exception("bad")):
        result = preview._is_safe_url("http://example.com/")
    assert result is False


# ── clean.py __main__ guard ───────────────────────────────────────────────────


def test_clean_main_guard(tmp_path, monkeypatch):
    import sys

    monkeypatch.chdir(tmp_path)
    (tmp_path / "uploads").mkdir(exist_ok=True)
    monkeypatch.delitem(sys.modules, "minimost.clean", raising=False)
    runpy.run_module("minimost.clean", run_name="__main__", alter_sys=False)


# ── __main__.py __main__ guard ────────────────────────────────────────────────


def test_main_module_guard():
    with patch("sys.argv", ["minimost"]):
        with patch("flask.Flask.run"):
            runpy.run_module("minimost.__main__", run_name="__main__", alter_sys=False)


# ── chat.py send: sender not in recipients branch ────────────────────────────


def test_send_sender_not_in_channel_users(alice):
    """Covers 'if sender not in recipients: recipients.append(sender)' in send."""
    common_mod.init_user_db("bob")
    with patch("minimost.chat.channel_users", return_value=["bob"]):
        resp = alice.post("/send/general", data={"text": "hi"})
    assert resp.status_code == 200


# ── chat.py edit: editor not in recipients branch ────────────────────────────


def test_edit_editor_not_in_channel_users(alice):
    """Covers 'if editor not in recipients: recipients.append(editor)' in edit."""
    common_mod.init_user_db("bob")
    ts = time.time()
    db = sqlite3.connect(str(common_mod.shared_db_path()))
    db.execute(
        "INSERT INTO messages (channel, sender, content, ts) VALUES (?, ?, ?, ?)",
        ("general", "alice", "original", ts),
    )
    db.commit()
    msg_id = db.execute("SELECT id FROM messages WHERE ts=?", (ts,)).fetchone()[0]
    db.close()

    with patch("minimost.chat.channel_users", return_value=["bob"]):
        resp = alice.post(f"/edit/{msg_id}", data={"text": "edited"})
    assert resp.status_code == 200


# ── chat.py delete: deleter not in recipients branch ─────────────────────────


def test_delete_deleter_not_in_channel_users(alice):
    """Covers 'if deleter not in recipients: recipients.append(deleter)' in delete."""
    common_mod.init_user_db("bob")
    ts = time.time()
    db = sqlite3.connect(str(common_mod.shared_db_path()))
    db.execute(
        "INSERT INTO messages (channel, sender, content, ts) VALUES (?, ?, ?, ?)",
        ("general", "alice", "bye", ts),
    )
    db.commit()
    msg_id = db.execute("SELECT id FROM messages WHERE ts=?", (ts,)).fetchone()[0]
    db.close()

    with patch("minimost.chat.channel_users", return_value=["bob"]):
        resp = alice.post(f"/delete/{msg_id}")
    assert resp.status_code == 200


# ── chat.py react: user not in recipients branch ──────────────────────────────


def test_react_user_not_in_channel_users(alice):
    """Covers 'if user not in recipients: recipients.append(user)' in react."""
    valid = next(iter(chat_mod.VALID_REACTIONS)) if chat_mod.VALID_REACTIONS else None
    if valid is None:
        return

    common_mod.init_user_db("bob")
    ts = time.time()
    db = sqlite3.connect(str(common_mod.shared_db_path()))
    db.execute(
        "INSERT INTO messages (channel, sender, content, ts) VALUES (?, ?, ?, ?)",
        ("general", "alice", "msg", ts),
    )
    db.commit()
    msg_id = db.execute("SELECT id FROM messages WHERE ts=?", (ts,)).fetchone()[0]
    db.close()

    with patch("minimost.chat.channel_users", return_value=["bob"]):
        resp = alice.post(f"/react/{msg_id}", data={"reaction": valid})
    assert resp.status_code == 200
