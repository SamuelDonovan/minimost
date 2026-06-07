"""Tests for chat routes: messages, send, edit, delete, react, search, etc."""

import io
import json
import sqlite3
import time

import minimost.auth as auth_mod
import minimost.chat as chat_mod
import minimost.common as common_mod
import minimost.presence as presence_mod
from werkzeug.security import generate_password_hash


def _add_user(username, password="Password1!"):
    db = sqlite3.connect(auth_mod.AUTH_DB)
    db.execute(
        "INSERT INTO users (username, password_hash) VALUES (?, ?)",
        (username, generate_password_hash(password)),
    )
    db.commit()
    db.close()
    common_mod.init_user_db(username)


def _insert_message(username, channel="general", content="hello", ts=None, sender=None):
    ts = ts or time.time()
    sender = sender or username
    db = sqlite3.connect(str(common_mod.user_db_path(username)))
    db.execute(
        "INSERT INTO messages (channel, sender, content, ts, read) VALUES (?, ?, ?, ?, 0)",
        (channel, sender, content, ts),
    )
    db.commit()
    row = db.execute(
        "SELECT id FROM messages WHERE ts=? AND channel=?", (ts, channel)
    ).fetchone()
    db.close()
    return row[0], ts


# ── GET / (index) ─────────────────────────────────────────────────────────────


def test_index_unauthenticated(client):
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.location


def test_index_authenticated(alice):
    resp = alice.get("/")
    assert resp.status_code == 200


# ── GET /channels ─────────────────────────────────────────────────────────────


def test_channels_unauthenticated(client):
    resp = client.get("/channels")
    assert resp.status_code == 302


def test_channels_returns_list(alice):
    resp = alice.get("/channels")
    assert resp.status_code == 200
    data = resp.get_json()
    assert isinstance(data, list)
    assert "general" in data


# ── GET /channel_unreads ──────────────────────────────────────────────────────


def test_channel_unreads_empty(alice):
    resp = alice.get("/channel_unreads")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "general" in data
    assert data["general"] == 0


def test_channel_unreads_counts(alice_and_bob, app):
    _add_user("charlie")
    ts = time.time()
    alice_db = sqlite3.connect(str(common_mod.user_db_path("alice")))
    alice_db.execute(
        "INSERT INTO messages (channel, sender, content, ts, read) VALUES (?, ?, ?, ?, 0)",
        (
            "general",
            "bob",
            "hi",
            ts,
        ),
    )
    alice_db.commit()
    alice_db.close()
    resp = alice_and_bob.get("/channel_unreads")
    data = resp.get_json()
    assert data["general"] == 1


# ── GET /unread_count ─────────────────────────────────────────────────────────


def test_unread_count_zero(alice):
    resp = alice.get("/unread_count")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["count"] == 0


def test_unread_count_with_dm(alice):
    db = sqlite3.connect(str(common_mod.user_db_path("alice")))
    db.execute(
        "INSERT INTO messages (channel, sender, content, ts, read) VALUES (?, ?, ?, ?, 0)",
        ("dm:alice:bob", "bob", "hey", time.time()),
    )
    db.commit()
    db.close()
    resp = alice.get("/unread_count")
    data = resp.get_json()
    assert data["count"] == 1


# ── GET /dms ──────────────────────────────────────────────────────────────────


def test_dms_empty(alice):
    resp = alice.get("/dms")
    assert resp.status_code == 200
    assert resp.get_json() == []


def test_dms_returns_conversations(alice):
    db = sqlite3.connect(str(common_mod.user_db_path("alice")))
    db.execute(
        "INSERT INTO messages (channel, sender, content, ts, read) VALUES (?, ?, ?, ?, 0)",
        ("dm:alice:bob", "bob", "hi", time.time()),
    )
    db.commit()
    db.close()
    data = alice.get("/dms").get_json()
    assert len(data) == 1
    assert data[0]["channel"] == "dm:alice:bob"
    assert "bob" in data[0]["users"]


# ── GET /online_users ─────────────────────────────────────────────────────────


def test_online_users_empty(alice):
    resp = alice.get("/online_users")
    assert resp.status_code == 200
    assert resp.get_json() == {}


def test_online_users_shows_recent(alice):
    pdb = sqlite3.connect(presence_mod.PRESENCE_DB)
    pdb.execute(
        "INSERT OR REPLACE INTO presence (user, last_seen, state) VALUES (?, ?, ?)",
        ("alice", int(time.time()), "active"),
    )
    pdb.commit()
    pdb.close()
    data = alice.get("/online_users").get_json()
    assert data.get("alice") == "active"


# ── GET /messages/<channel> ───────────────────────────────────────────────────


def test_messages_unauthenticated(client):
    resp = client.get("/messages/general")
    assert resp.status_code == 302


def test_messages_empty_channel(alice):
    resp = alice.get("/messages/general?after=0")
    assert resp.status_code == 200
    assert resp.get_json() == []


def test_messages_returns_messages(alice):
    _insert_message("alice", "general", "test msg")
    data = alice.get("/messages/general?after=0").get_json()
    assert len(data) == 1
    assert data[0]["content"] == "test msg"


def test_messages_after_filter(alice):
    t1 = time.time() - 10
    t2 = time.time()
    _insert_message("alice", "general", "old", ts=t1)
    _insert_message("alice", "general", "new", ts=t2)
    data = alice.get(f"/messages/general?after={t1 + 1}").get_json()
    contents = [m["content"] for m in data]
    assert "new" in contents
    assert "old" not in contents


def test_messages_nan_after(alice):
    _insert_message("alice", "general", "msg")
    data = alice.get("/messages/general?after=NaN").get_json()
    assert len(data) == 1


def test_messages_invalid_after(alice):
    _insert_message("alice", "general", "msg")
    data = alice.get("/messages/general?after=abc").get_json()
    assert len(data) == 1


def test_messages_includes_reactions(alice):
    msg_id, ts = _insert_message("alice", "general", "react me")
    pdb = sqlite3.connect(presence_mod.PRESENCE_DB)
    pdb.execute(
        "INSERT INTO message_reactions (channel, msg_ts, emoji, reactor) VALUES (?, ?, ?, ?)",
        ("general", ts, "thumbs_up", "alice"),
    )
    pdb.commit()
    pdb.close()
    data = alice.get("/messages/general?after=0").get_json()
    assert data[0]["reactions"] is not None
    rx = json.loads(data[0]["reactions"])
    assert "thumbs_up" in rx


def test_messages_deleted_tombstone(alice):
    msg_id, ts = _insert_message("alice", "general", "bye")
    db = sqlite3.connect(str(common_mod.user_db_path("alice")))
    db.execute(
        "UPDATE messages SET deleted=1, deleted_ts=? WHERE id=?",
        (time.time(), msg_id),
    )
    db.commit()
    db.close()
    data = alice.get("/messages/general?after=0").get_json()
    deleted = [m for m in data if m["deleted"]]
    assert len(deleted) == 1


# ── POST /send/<channel> ──────────────────────────────────────────────────────


def test_send_unauthenticated(client):
    resp = client.post("/send/general", data={"text": "hi"})
    assert resp.status_code == 302


def test_send_forbidden_channel(alice):
    resp = alice.post("/send/secret-channel", data={"text": "hi"})
    assert resp.status_code == 403


def test_send_empty(alice):
    resp = alice.post("/send/general", data={"text": ""})
    assert resp.status_code == 400


def test_send_text_message(alice):
    resp = alice.post("/send/general", data={"text": "hello world"})
    assert resp.status_code == 200
    assert resp.data == b"ok"


def test_send_stores_in_db(alice):
    alice.post("/send/general", data={"text": "stored msg"})
    db = sqlite3.connect(str(common_mod.user_db_path("alice")))
    row = db.execute("SELECT content FROM messages WHERE channel='general'").fetchone()
    db.close()
    assert row is not None
    assert row[0] == "stored msg"


def test_send_propagates_to_all_users(alice_and_bob):
    alice_and_bob.post("/send/general", data={"text": "broadcast"})
    bob_db = sqlite3.connect(str(common_mod.user_db_path("bob")))
    row = bob_db.execute(
        "SELECT content FROM messages WHERE channel='general'"
    ).fetchone()
    bob_db.close()
    assert row is not None
    assert row[0] == "broadcast"


def test_send_dm_channel(alice_and_bob):
    resp = alice_and_bob.post("/send/dm:alice:bob", data={"text": "private"})
    assert resp.status_code == 200


def test_send_dm_forbidden_for_outsider(alice_and_bob):
    resp = alice_and_bob.post("/send/dm:bob:charlie", data={"text": "hack"})
    assert resp.status_code == 403


def test_send_with_reply_to(alice):
    msg_id, _ = _insert_message("alice", "general", "parent")
    resp = alice.post(
        "/send/general", data={"text": "reply", "reply_to_id": str(msg_id)}
    )
    assert resp.status_code == 200


def test_send_with_invalid_reply_to(alice):
    resp = alice.post(
        "/send/general", data={"text": "reply", "reply_to_id": "notanint"}
    )
    assert resp.status_code == 200


def test_send_file(alice, tmp_path):
    import minimost.chat as chat

    orig_upload = chat.UPLOAD_DIR
    chat.UPLOAD_DIR.mkdir(exist_ok=True)
    img = io.BytesIO(b"\xff\xd8\xff" + b"\x00" * 10)
    resp = alice.post(
        "/send/general",
        data={"text": "", "files": (img, "photo.jpg")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200


def test_send_file_any_extension(alice):
    import minimost.chat as chat

    chat.UPLOAD_DIR.mkdir(exist_ok=True)
    exe = io.BytesIO(b"MZ" + b"\x00" * 10)
    resp = alice.post(
        "/send/general",
        data={"text": "", "files": (exe, "document.exe")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200


def test_send_file_too_large(alice):
    import minimost.chat as chat

    orig = chat._max_upload_size_bytes
    chat._max_upload_size_bytes = lambda: 5  # 5 bytes limit
    try:
        big = io.BytesIO(b"\x00" * 10)
        resp = alice.post(
            "/send/general",
            data={"text": "", "files": (big, "big.bin")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 413
    finally:
        chat._max_upload_size_bytes = orig


# ── GET /message/<id> ─────────────────────────────────────────────────────────


def test_get_message_found(alice):
    msg_id, _ = _insert_message("alice", "general", "single")
    resp = alice.get(f"/message/{msg_id}")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["content"] == "single"


def test_get_message_not_found(alice):
    resp = alice.get("/message/99999")
    assert resp.status_code == 404


# ── GET /files/<filename> ─────────────────────────────────────────────────────


def test_files_unauthenticated(client):
    resp = client.get("/files/something.jpg")
    assert resp.status_code == 302


def test_files_serves_file(alice):
    fname = "test_img.jpg"
    (chat_mod.UPLOAD_DIR / fname).write_bytes(b"\xff\xd8\xff")
    resp = alice.get(f"/files/{fname}")
    assert resp.status_code == 200
    resp.close()  # release the send_file handle so it isn't GC'd as a ResourceWarning
    (chat_mod.UPLOAD_DIR / fname).unlink()


# ── GET /search_messages ──────────────────────────────────────────────────────


def test_search_empty_query(alice):
    resp = alice.get("/search_messages?q=")
    assert resp.status_code == 200
    assert resp.get_json() == []


def test_search_no_results(alice):
    _insert_message("alice", "general", "hello")
    data = alice.get("/search_messages?q=zzz").get_json()
    assert data == []


def test_search_finds_match(alice):
    _insert_message("alice", "general", "find me please")
    data = alice.get("/search_messages?q=find me").get_json()
    assert len(data) == 1
    assert data[0]["content"] == "find me please"


def test_search_no_filters_returns_empty(alice):
    _insert_message("alice", "general", "hello")
    assert alice.get("/search_messages").get_json() == []


def test_search_filter_by_sender(alice):
    _insert_message("alice", "general", "from alice", sender="alice")
    _insert_message("alice", "general", "from bob", sender="bob")
    data = alice.get("/search_messages?from=bob").get_json()
    assert [m["content"] for m in data] == ["from bob"]


def test_search_filter_by_sender_is_case_insensitive(alice):
    _insert_message("alice", "general", "from bob", sender="bob")
    data = alice.get("/search_messages?from=BOB").get_json()
    assert len(data) == 1


def test_search_filter_by_channel(alice):
    _insert_message("alice", "general", "in general")
    _insert_message("alice", "random", "in random")
    data = alice.get("/search_messages?channel=random").get_json()
    assert [m["content"] for m in data] == ["in random"]


def test_search_filter_by_date_range(alice):
    _insert_message("alice", "general", "old", ts=1000.0)
    _insert_message("alice", "general", "mid", ts=2000.0)
    _insert_message("alice", "general", "new", ts=3000.0)
    data = alice.get("/search_messages?start=1500&end=2500").get_json()
    assert [m["content"] for m in data] == ["mid"]


def test_search_filters_combine(alice):
    _insert_message("alice", "general", "keep", sender="bob", ts=2000.0)
    _insert_message("alice", "general", "wrong sender", sender="carol", ts=2000.0)
    _insert_message("alice", "random", "wrong channel", sender="bob", ts=2000.0)
    _insert_message("alice", "general", "too old", sender="bob", ts=100.0)
    data = alice.get("/search_messages?from=bob&channel=general&start=1000").get_json()
    assert [m["content"] for m in data] == ["keep"]


def test_search_ignores_invalid_date(alice):
    """A non-numeric date bound is dropped rather than rejected."""
    _insert_message("alice", "general", "hello")
    data = alice.get("/search_messages?q=hello&start=notanumber").get_json()
    assert len(data) == 1


def test_search_matches_mid_word_substring(alice):
    """The trigram index keeps substring (not just whole-word) matching."""
    _insert_message("alice", "general", "hello world")
    data = alice.get("/search_messages?q=ell").get_json()
    assert [m["content"] for m in data] == ["hello world"]


def test_search_short_query_falls_back_to_like(alice):
    """Queries shorter than the trigram width still match via the LIKE scan."""
    _insert_message("alice", "general", "hi there")
    data = alice.get("/search_messages?q=hi").get_json()
    assert [m["content"] for m in data] == ["hi there"]


def test_search_index_reflects_edits(alice):
    """Editing a message re-indexes it: new text matches, old text does not."""
    msg_id, _ = _insert_message("alice", "general", "original wording")
    alice.post(f"/edit/{msg_id}", data={"text": "replacement wording"})
    assert alice.get("/search_messages?q=replacement").get_json()
    assert alice.get("/search_messages?q=original").get_json() == []


def test_search_index_reflects_hard_delete(alice):
    """A hard-deleted row leaves the search index (via the delete trigger)."""
    db = sqlite3.connect(str(common_mod.user_db_path("alice")))
    db.execute(
        "INSERT INTO messages (channel, sender, content, ts, read) VALUES "
        "('general', 'alice', 'ephemeral note', 1.0, 0)"
    )
    db.commit()
    db.execute("DELETE FROM messages WHERE content = 'ephemeral note'")
    db.commit()
    db.close()
    assert alice.get("/search_messages?q=ephemeral").get_json() == []


# ── POST /edit/<id> ───────────────────────────────────────────────────────────


def test_edit_unauthenticated(client):
    resp = client.post("/edit/1", data={"text": "new"})
    assert resp.status_code == 302


def test_edit_success(alice):
    msg_id, _ = _insert_message("alice", "general", "original")
    resp = alice.post(f"/edit/{msg_id}", data={"text": "edited"})
    assert resp.status_code == 200
    assert resp.data == b"ok"


def test_edit_updates_content(alice):
    msg_id, _ = _insert_message("alice", "general", "original")
    alice.post(f"/edit/{msg_id}", data={"text": "new text"})
    db = sqlite3.connect(str(common_mod.user_db_path("alice")))
    row = db.execute(
        "SELECT content, edited FROM messages WHERE id=?", (msg_id,)
    ).fetchone()
    db.close()
    assert row[0] == "new text"
    assert row[1] == 1


def test_edit_forbidden_for_other_user(alice_and_bob, app):
    _insert_message("bob", "general", "bobs msg")
    bob_db = sqlite3.connect(str(common_mod.user_db_path("bob")))
    bob_row = bob_db.execute(
        "SELECT id FROM messages WHERE content='bobs msg'"
    ).fetchone()
    bob_db.close()

    resp = alice_and_bob.post(f"/edit/{bob_row[0]}", data={"text": "hacked"})
    assert resp.status_code == 403


def test_edit_not_found(alice):
    resp = alice.post("/edit/99999", data={"text": "x"})
    assert resp.status_code == 403


def test_edit_propagates_to_other_users(alice_and_bob):
    ts = time.time()
    for user in ("alice", "bob"):
        db = sqlite3.connect(str(common_mod.user_db_path(user)))
        db.execute(
            "INSERT INTO messages (channel, sender, content, ts, read) VALUES (?,?,?,?,0)",
            ("general", "alice", "original", ts),
        )
        db.commit()
        db.close()

    alice_db = sqlite3.connect(str(common_mod.user_db_path("alice")))
    msg_id = alice_db.execute("SELECT id FROM messages WHERE ts=?", (ts,)).fetchone()[0]
    alice_db.close()

    alice_and_bob.post(f"/edit/{msg_id}", data={"text": "edited"})

    bob_db = sqlite3.connect(str(common_mod.user_db_path("bob")))
    row = bob_db.execute("SELECT content FROM messages WHERE ts=?", (ts,)).fetchone()
    bob_db.close()
    assert row[0] == "edited"


# ── POST /delete/<id> ─────────────────────────────────────────────────────────


def test_delete_unauthenticated(client):
    resp = client.post("/delete/1")
    assert resp.status_code == 302


def test_delete_success(alice):
    msg_id, _ = _insert_message("alice", "general", "bye")
    resp = alice.post(f"/delete/{msg_id}")
    assert resp.status_code == 200
    assert resp.data == b"ok"


def test_delete_marks_deleted(alice):
    msg_id, _ = _insert_message("alice", "general", "bye")
    alice.post(f"/delete/{msg_id}")
    db = sqlite3.connect(str(common_mod.user_db_path("alice")))
    row = db.execute("SELECT deleted FROM messages WHERE id=?", (msg_id,)).fetchone()
    db.close()
    assert row[0] == 1


def test_delete_forbidden_for_other_user(alice_and_bob):
    ts = time.time()
    db = sqlite3.connect(str(common_mod.user_db_path("alice")))
    db.execute(
        "INSERT INTO messages (channel, sender, content, ts, read) VALUES (?,?,?,?,0)",
        ("general", "bob", "bob msg", ts),
    )
    db.commit()
    row_id = db.execute("SELECT id FROM messages WHERE ts=?", (ts,)).fetchone()[0]
    db.close()
    resp = alice_and_bob.post(f"/delete/{row_id}")
    assert resp.status_code == 403


def test_delete_not_found(alice):
    resp = alice.post("/delete/99999")
    assert resp.status_code == 403


# ── POST /react/<id> ──────────────────────────────────────────────────────────


def test_react_unauthenticated(client):
    resp = client.post("/react/1", data={"reaction": "thumbs_up"})
    assert resp.status_code == 302


def test_react_invalid_reaction(alice):
    msg_id, _ = _insert_message("alice", "general", "msg")
    resp = alice.post(f"/react/{msg_id}", data={"reaction": "not_a_real_emoji_xyz"})
    assert resp.status_code == 400


def test_react_not_found(alice):
    valid = next(iter(chat_mod.VALID_REACTIONS)) if chat_mod.VALID_REACTIONS else None
    if valid is None:
        return
    resp = alice.post("/react/99999", data={"reaction": valid})
    assert resp.status_code == 404


def test_react_success(alice):
    valid = next(iter(chat_mod.VALID_REACTIONS)) if chat_mod.VALID_REACTIONS else None
    if valid is None:
        return
    msg_id, _ = _insert_message("alice", "general", "msg")
    resp = alice.post(f"/react/{msg_id}", data={"reaction": valid})
    assert resp.status_code == 200
    data = resp.get_json()
    assert valid in data


def test_react_toggle_removes(alice):
    valid = next(iter(chat_mod.VALID_REACTIONS)) if chat_mod.VALID_REACTIONS else None
    if valid is None:
        return
    msg_id, _ = _insert_message("alice", "general", "msg")
    alice.post(f"/react/{msg_id}", data={"reaction": valid})
    resp = alice.post(f"/react/{msg_id}", data={"reaction": valid})
    data = resp.get_json()
    assert valid not in data or "alice" not in data.get(valid, [])


# ── POST /mark_read/<channel> ─────────────────────────────────────────────────


def test_mark_read_unauthenticated(client):
    resp = client.post("/mark_read/general")
    assert resp.status_code == 302


def test_mark_read_returns_204(alice):
    resp = alice.post("/mark_read/general")
    assert resp.status_code == 204


def test_mark_read_updates_messages(alice):
    db = sqlite3.connect(str(common_mod.user_db_path("alice")))
    db.execute(
        "INSERT INTO messages (channel, sender, content, ts, read) VALUES (?,?,?,?,0)",
        ("general", "bob", "unread", time.time()),
    )
    db.commit()
    db.close()
    alice.post("/mark_read/general")
    db = sqlite3.connect(str(common_mod.user_db_path("alice")))
    row = db.execute(
        "SELECT read FROM messages WHERE channel='general' AND sender='bob'"
    ).fetchone()
    db.close()
    assert row[0] == 1


def test_mark_read_inserts_receipts(alice):
    ts = time.time()
    db = sqlite3.connect(str(common_mod.user_db_path("alice")))
    db.execute(
        "INSERT INTO messages (channel, sender, content, ts, read) VALUES (?,?,?,?,0)",
        ("general", "bob", "msg", ts),
    )
    db.commit()
    db.close()
    alice.post("/mark_read/general")
    pdb = sqlite3.connect(presence_mod.PRESENCE_DB)
    row = pdb.execute(
        "SELECT reader FROM read_receipts WHERE channel='general' AND msg_ts=?", (ts,)
    ).fetchone()
    pdb.close()
    assert row is not None
    assert row[0] == "alice"


def test_mark_read_no_unread_messages(alice):
    resp = alice.post("/mark_read/general")
    assert resp.status_code == 204


# ── GET /read_receipts/<channel> ──────────────────────────────────────────────


def test_read_receipts_empty(alice):
    data = alice.get("/read_receipts/general").get_json()
    assert data == {}


def test_read_receipts_returns_data(alice):
    ts = time.time()
    pdb = sqlite3.connect(presence_mod.PRESENCE_DB)
    pdb.execute(
        "INSERT INTO read_receipts (channel, msg_ts, reader) VALUES (?,?,?)",
        ("general", ts, "alice"),
    )
    pdb.commit()
    pdb.close()
    data = alice.get("/read_receipts/general").get_json()
    assert str(ts) in data
    assert "alice" in data[str(ts)]


# ── GET /users ────────────────────────────────────────────────────────────────


def test_users_unauthenticated(client):
    resp = client.get("/users")
    assert resp.status_code == 302


def test_users_excludes_self(alice_and_bob):
    data = alice_and_bob.get("/users").get_json()
    assert "alice" not in data
    assert "bob" in data


# ── GET /link_preview ─────────────────────────────────────────────────────────


def test_link_preview_empty_url(alice):
    resp = alice.get("/link_preview?url=")
    assert resp.status_code == 200
    assert resp.get_json() == {}


def test_link_preview_missing_url(alice):
    resp = alice.get("/link_preview")
    assert resp.status_code == 200
    assert resp.get_json() == {}


def test_link_preview_ssrf_blocked(alice):
    resp = alice.get("/link_preview?url=http://192.168.1.1/")
    assert resp.get_json() == {}


def test_link_preview_unauthenticated(client):
    resp = client.get("/link_preview?url=https://example.com")
    assert resp.status_code == 302


# ── POST /delete_account ──────────────────────────────────────────────────────


def test_delete_account_unauthenticated(client):
    resp = client.post("/delete_account", json={"type": "soft", "password": "x"})
    assert resp.status_code == 302


def test_delete_account_invalid_type(alice):
    resp = alice.post(
        "/delete_account", json={"type": "purge", "password": "Password1!"}
    )
    assert resp.status_code == 400


def test_delete_account_wrong_password(alice):
    resp = alice.post("/delete_account", json={"type": "soft", "password": "wrong"})
    assert resp.status_code == 403


def test_delete_account_soft(alice):
    _insert_message("alice", "general", "to be anonymised")
    resp = alice.post(
        "/delete_account", json={"type": "soft", "password": "Password1!"}
    )
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"
    # Message still exists but sender renamed
    db = sqlite3.connect(str(common_mod.user_db_path("alice")))
    row = db.execute("SELECT sender FROM messages WHERE channel='general'").fetchone()
    db.close()
    assert row[0] == "Deleted User"


def test_delete_account_hard(alice):
    _insert_message("alice", "general", "to be deleted")
    resp = alice.post(
        "/delete_account", json={"type": "hard", "password": "Password1!"}
    )
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"


def test_delete_account_soft_cleans_presence(alice):
    import minimost.presence as pres

    db = sqlite3.connect(pres.PRESENCE_DB)
    db.execute(
        "INSERT OR IGNORE INTO presence (user, state, last_seen) VALUES ('alice','active',0)"
    )
    db.commit()
    db.close()
    alice.post("/delete_account", json={"type": "soft", "password": "Password1!"})
    db = sqlite3.connect(pres.PRESENCE_DB)
    row = db.execute("SELECT * FROM presence WHERE user='alice'").fetchone()
    db.close()
    assert row is None


# ── Message append (send within 300 s groups messages) ───────────────────────


def test_send_appends_to_recent_message(alice):
    import time as _time

    ts = _time.time() - 10  # 10 s ago — within 300 s window
    db = sqlite3.connect(str(common_mod.user_db_path("alice")))
    db.execute(
        "INSERT INTO messages (channel, sender, content, ts, read) VALUES (?,?,?,?,0)",
        ("general", "alice", "first line", ts),
    )
    db.commit()
    db.close()
    resp = alice.post("/send/general", data={"text": "second line"})
    assert resp.status_code == 200
    db = sqlite3.connect(str(common_mod.user_db_path("alice")))
    row = db.execute("SELECT content FROM messages WHERE channel='general'").fetchone()
    db.close()
    assert "first line\nsecond line" == row[0]


def test_send_does_not_append_old_message(alice):
    import time as _time

    ts = _time.time() - 400  # older than 300 s
    db = sqlite3.connect(str(common_mod.user_db_path("alice")))
    db.execute(
        "INSERT INTO messages (channel, sender, content, ts, read) VALUES (?,?,?,?,0)",
        ("general", "alice", "old message", ts),
    )
    db.commit()
    db.close()
    alice.post("/send/general", data={"text": "new message"})
    db = sqlite3.connect(str(common_mod.user_db_path("alice")))
    rows = db.execute(
        "SELECT content FROM messages WHERE channel='general' ORDER BY ts"
    ).fetchall()
    db.close()
    assert len(rows) == 2


# ── GET /files/<filename> — attachment download ───────────────────────────────


def test_files_attachment_content_disposition(alice):
    """UUID-prefixed filenames expose the original name as the download name."""
    # 32 hex chars + underscore + original name
    fname = "a" * 32 + "_report.pdf"
    (chat_mod.UPLOAD_DIR / fname).write_bytes(b"%PDF")
    resp = alice.get(f"/files/{fname}?download=1")
    assert resp.status_code == 200
    resp.close()  # release the send_file handle so it isn't GC'd as a ResourceWarning
    (chat_mod.UPLOAD_DIR / fname).unlink()


# ── GET /file_preview/<filename> ─────────────────────────────────────────────


def test_file_preview_unauthenticated(client):
    resp = client.get("/file_preview/hello.py")
    assert resp.status_code == 302


def test_file_preview_unknown_extension(alice):
    fname = "image.jpg"
    (chat_mod.UPLOAD_DIR / fname).write_bytes(b"\xff\xd8")
    resp = alice.get(f"/file_preview/{fname}")
    assert resp.status_code == 200
    assert resp.get_json() == {}
    (chat_mod.UPLOAD_DIR / fname).unlink()


def test_file_preview_text_file(alice):
    fname = "script.py"
    (chat_mod.UPLOAD_DIR / fname).write_text("print('hello')", encoding="utf-8")
    resp = alice.get(f"/file_preview/{fname}")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "content" in data or "lines" in data or data != {}
    (chat_mod.UPLOAD_DIR / fname).unlink()


def test_file_preview_bad_filename(alice):
    resp = alice.get("/file_preview/")
    assert resp.status_code in (404, 302, 308)


def test_file_preview_missing_file(alice):
    resp = alice.get("/file_preview/nonexistent.py")
    assert resp.status_code == 200
    assert resp.get_json() == {}


# ── @-mentions ────────────────────────────────────────────────────────────────


def test_extract_mentions_matches_members(alice_and_bob):
    mentions = chat_mod.extract_mentions("hey @bob and @nobody", "general")
    assert mentions == ["bob"]


def test_extract_mentions_case_insensitive(alice_and_bob):
    assert chat_mod.extract_mentions("yo @BOB", "general") == ["bob"]


def test_extract_mentions_ignores_emails(alice_and_bob):
    assert chat_mod.extract_mentions("mail me at foo@bob.com", "general") == []


def test_extract_mentions_empty_text(alice_and_bob):
    assert chat_mod.extract_mentions("", "general") == []
    assert chat_mod.extract_mentions("no pings here", "general") == []


def test_send_stores_mentions(alice_and_bob):
    alice_and_bob.post("/send/general", data={"text": "ping @bob"})
    db = sqlite3.connect(str(common_mod.user_db_path("bob")))
    row = db.execute("SELECT mentions FROM messages WHERE channel='general'").fetchone()
    db.close()
    assert json.loads(row[0]) == ["bob"]


def test_send_no_mentions_stores_null(alice_and_bob):
    alice_and_bob.post("/send/general", data={"text": "plain message"})
    db = sqlite3.connect(str(common_mod.user_db_path("bob")))
    row = db.execute("SELECT mentions FROM messages WHERE channel='general'").fetchone()
    db.close()
    assert row[0] is None


def test_messages_returns_mentions(alice_and_bob):
    alice_and_bob.post("/send/general", data={"text": "ping @bob"})
    data = alice_and_bob.get("/messages/general?after=0").get_json()
    assert json.loads(data[0]["mentions"]) == ["bob"]


def test_edit_updates_mentions(alice_and_bob):
    alice_and_bob.post("/send/general", data={"text": "no ping"})
    msg = alice_and_bob.get("/messages/general?after=0").get_json()[0]
    alice_and_bob.post(f"/edit/{msg['id']}", data={"text": "now @bob"})
    db = sqlite3.connect(str(common_mod.user_db_path("bob")))
    row = db.execute("SELECT mentions FROM messages WHERE channel='general'").fetchone()
    db.close()
    assert json.loads(row[0]) == ["bob"]


def test_channel_members_excludes_self(alice_and_bob):
    data = alice_and_bob.get("/channel_members/general").get_json()
    assert "bob" in data
    assert "alice" not in data


def test_channel_members_forbidden(alice_and_bob):
    resp = alice_and_bob.get("/channel_members/dm:bob:charlie")
    assert resp.status_code == 403


def test_channel_members_dm(alice_and_bob):
    data = alice_and_bob.get("/channel_members/dm:alice:bob").get_json()
    assert data == ["bob"]


def test_extract_mentions_everyone(alice_and_bob):
    assert chat_mod.extract_mentions("hey @everyone", "general") == [
        chat_mod.MENTION_EVERYONE
    ]


def test_extract_mentions_everyone_overrides_others(alice_and_bob):
    # @everyone already covers every member, so it collapses other mentions.
    assert chat_mod.extract_mentions("@bob @everyone", "general") == [
        chat_mod.MENTION_EVERYONE
    ]


def test_send_everyone_stores_sentinel(alice_and_bob):
    alice_and_bob.post("/send/general", data={"text": "listen up @everyone"})
    db = sqlite3.connect(str(common_mod.user_db_path("bob")))
    row = db.execute("SELECT mentions FROM messages WHERE channel='general'").fetchone()
    db.close()
    assert json.loads(row[0]) == [chat_mod.MENTION_EVERYONE]
