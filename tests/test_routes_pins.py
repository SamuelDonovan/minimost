"""Tests for pinned messages: GET /pins/<channel> and POST /pin/<msg_id>."""

import sqlite3
import time

import minimost.chat as chat_mod
import minimost.clean as clean_mod
import minimost.common as common_mod


def _insert_message(channel="general", sender="alice", content="hello", ts=None):
    ts = ts or time.time()
    db = sqlite3.connect(str(common_mod.shared_db_path()))
    cur = db.execute(
        "INSERT INTO messages (channel, sender, content, ts) VALUES (?, ?, ?, ?)",
        (channel, sender, content, ts),
    )
    msg_id = cur.lastrowid
    db.commit()
    db.close()
    return msg_id


def _pin_rows():
    db = sqlite3.connect(str(common_mod.shared_db_path()))
    rows = db.execute(
        "SELECT message_id, channel, pinned_by FROM pins ORDER BY message_id"
    ).fetchall()
    db.close()
    return rows


# ── POST /pin/<msg_id> ────────────────────────────────────────────────────────


def test_pin_requires_auth(client):
    resp = client.post("/pin/1")
    assert resp.status_code == 302


def test_pin_adds_row_and_returns_list(alice):
    msg_id = _insert_message(content="the important one")

    resp = alice.post(f"/pin/{msg_id}")

    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data) == 1
    assert data[0]["id"] == msg_id
    assert data[0]["pinned_by"] == "alice"
    assert data[0]["content"] == "the important one"
    assert _pin_rows() == [(msg_id, "general", "alice")]


def test_pin_toggles_off_on_second_call(alice):
    msg_id = _insert_message()

    alice.post(f"/pin/{msg_id}")
    resp = alice.post(f"/pin/{msg_id}")

    assert resp.status_code == 200
    assert resp.get_json() == []
    assert _pin_rows() == []


def test_pin_is_not_restricted_to_the_author(alice_and_bob):
    """Pinning is channel-wide, so anyone in the channel may pin anyone's
    message — unlike edit and delete, which are author-only."""
    msg_id = _insert_message(sender="bob", content="bob's message")

    resp = alice_and_bob.post(f"/pin/{msg_id}")

    assert resp.status_code == 200
    assert _pin_rows() == [(msg_id, "general", "alice")]


def test_anyone_in_the_channel_may_unpin(app, alice_and_bob):
    """A pin belongs to the channel, so bob can remove one alice set."""
    msg_id = _insert_message()
    alice_and_bob.post(f"/pin/{msg_id}")

    bob = app.test_client()
    with bob.session_transaction() as sess:
        sess["user"] = "bob"
    resp = bob.post(f"/pin/{msg_id}")

    assert resp.status_code == 200
    assert _pin_rows() == []


def test_pin_unknown_message_is_404(alice):
    assert alice.post("/pin/999999").status_code == 404


def test_pin_deleted_message_is_404(alice):
    msg_id = _insert_message()
    db = sqlite3.connect(str(common_mod.shared_db_path()))
    db.execute("UPDATE messages SET deleted = 1 WHERE id = ?", (msg_id,))
    db.commit()
    db.close()

    assert alice.post(f"/pin/{msg_id}").status_code == 404
    assert _pin_rows() == []


def test_pin_in_inaccessible_channel_is_404(alice):
    """A message in a DM alice is not part of must not be pinnable — that would
    be a way to probe conversations she cannot read."""
    msg_id = _insert_message(channel="dm:bob:carol", sender="bob")

    assert alice.post(f"/pin/{msg_id}").status_code == 404
    assert _pin_rows() == []


def test_pin_in_private_channel_the_user_is_not_in_is_404(alice):
    msg_id = _insert_message(channel="private:1", sender="bob")

    assert alice.post(f"/pin/{msg_id}").status_code == 404
    assert _pin_rows() == []


def test_pin_cap_rejects_further_pins(alice, monkeypatch):
    monkeypatch.setattr(chat_mod, "MAX_PINS_PER_CHANNEL", 2)

    first = alice.post(f"/pin/{_insert_message(content='a')}")
    second = alice.post(f"/pin/{_insert_message(content='b')}")
    over = alice.post(f"/pin/{_insert_message(content='c')}")

    assert first.status_code == 200
    assert second.status_code == 200
    assert over.status_code == 409
    assert len(_pin_rows()) == 2


def test_unpin_still_works_at_the_cap(alice, monkeypatch):
    """The cap is checked only when adding, so a full channel is not stuck."""
    monkeypatch.setattr(chat_mod, "MAX_PINS_PER_CHANNEL", 1)
    msg_id = _insert_message()
    alice.post(f"/pin/{msg_id}")

    resp = alice.post(f"/pin/{msg_id}")

    assert resp.status_code == 200
    assert _pin_rows() == []


def test_pin_content_is_truncated(alice, monkeypatch):
    monkeypatch.setattr(chat_mod, "PIN_PREVIEW_CHARS", 10)
    msg_id = _insert_message(content="x" * 500)

    data = alice.post(f"/pin/{msg_id}").get_json()

    assert data[0]["content"] == "x" * 10


# ── GET /pins/<channel> ───────────────────────────────────────────────────────


def test_get_pins_requires_auth(client):
    assert client.get("/pins/general").status_code == 302


def test_get_pins_empty_by_default(alice):
    resp = alice.get("/pins/general")
    assert resp.status_code == 200
    assert resp.get_json() == []


def test_get_pins_forbidden_for_inaccessible_channel(alice):
    assert alice.get("/pins/dm:bob:carol").status_code == 403


def test_get_pins_is_scoped_to_one_channel(alice):
    here = _insert_message(channel="general", content="here")
    there = _insert_message(channel="software", content="there")
    alice.post(f"/pin/{here}")
    alice.post(f"/pin/{there}")

    data = alice.get("/pins/general").get_json()

    assert [p["id"] for p in data] == [here]


def test_get_pins_newest_pinned_first(alice):
    first = _insert_message(content="first")
    second = _insert_message(content="second")
    alice.post(f"/pin/{first}")
    alice.post(f"/pin/{second}")

    data = alice.get("/pins/general").get_json()

    assert [p["id"] for p in data] == [second, first]


def test_deleting_a_pinned_message_drops_it_from_the_list(alice):
    """The pin row survives the soft delete, but the message stops appearing —
    the list joins against `messages` and excludes tombstones."""
    msg_id = _insert_message(sender="alice")
    alice.post(f"/pin/{msg_id}")

    assert alice.post(f"/delete/{msg_id}").status_code == 200

    assert alice.get("/pins/general").get_json() == []


def test_get_pins_visible_to_every_channel_member(app, alice_and_bob):
    """Pins are channel state, not a personal bookmark list."""
    msg_id = _insert_message()
    alice_and_bob.post(f"/pin/{msg_id}")

    bob = app.test_client()
    with bob.session_transaction() as sess:
        sess["user"] = "bob"

    assert [p["id"] for p in bob.get("/pins/general").get_json()] == [msg_id]


def test_pins_work_in_a_dm_the_user_is_part_of(alice_and_bob):
    channel = "dm:alice:bob"
    msg_id = _insert_message(channel=channel, sender="bob")

    assert alice_and_bob.post(f"/pin/{msg_id}").status_code == 200
    assert [p["id"] for p in alice_and_bob.get(f"/pins/{channel}").get_json()] == [
        msg_id
    ]


# ── Retention cleanup ─────────────────────────────────────────────────────────


def test_retention_prunes_orphaned_pins(alice):
    """A pin whose message is removed by retention must not survive it."""
    kept = _insert_message(content="kept")
    purged = _insert_message(content="purged")
    alice.post(f"/pin/{kept}")
    alice.post(f"/pin/{purged}")

    db = sqlite3.connect(str(common_mod.shared_db_path()))
    db.execute("DELETE FROM messages WHERE id = ?", (purged,))
    db.commit()
    clean_mod._prune_orphan_rows(db)
    db.commit()
    db.close()

    assert [row[0] for row in _pin_rows()] == [kept]
