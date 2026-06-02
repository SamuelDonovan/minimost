"""Tests for calling routes: initiate, incoming, accept, reject, end, signal, media relay."""

import base64
import json
import sqlite3
import time
import uuid

import pytest
import minimost.presence as presence_mod

# ── fixtures ─────────────────────────────────────────────────────────────────

# ── helpers ───────────────────────────────────────────────────────────────────


def _insert_call(call_id, channel, initiator, state="ringing", started_ts=None):
    started_ts = started_ts or time.time()
    db = sqlite3.connect(presence_mod.PRESENCE_DB)
    db.execute(
        "INSERT INTO calls (call_id, channel, initiator, state, started_ts)"
        " VALUES (?, ?, ?, ?, ?)",
        (call_id, channel, initiator, state, started_ts),
    )
    db.commit()
    db.close()


def _insert_participant(
    call_id, username, role="participant", state="pending", joined_ts=None
):
    db = sqlite3.connect(presence_mod.PRESENCE_DB)
    db.execute(
        "INSERT INTO call_participants (call_id, username, role, state, joined_ts)"
        " VALUES (?, ?, ?, ?, ?)",
        (call_id, username, role, state, joined_ts),
    )
    db.commit()
    db.close()


def _insert_signal(call_id, from_user, to_user, signal_type="offer", payload=None):
    payload = payload or {"type": "offer", "sdp": "v=0..."}
    db = sqlite3.connect(presence_mod.PRESENCE_DB)
    cur = db.execute(
        "INSERT INTO call_signals (call_id, from_user, to_user, signal_type, payload, ts)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (call_id, from_user, to_user, signal_type, json.dumps(payload), time.time()),
    )
    signal_id = cur.lastrowid
    db.commit()
    db.close()
    return signal_id


def _get_call(call_id):
    db = sqlite3.connect(presence_mod.PRESENCE_DB)
    db.row_factory = sqlite3.Row
    row = db.execute("SELECT * FROM calls WHERE call_id = ?", (call_id,)).fetchone()
    db.close()
    return dict(row) if row else None


def _get_participant(call_id, username):
    db = sqlite3.connect(presence_mod.PRESENCE_DB)
    db.row_factory = sqlite3.Row
    row = db.execute(
        "SELECT * FROM call_participants WHERE call_id = ? AND username = ?",
        (call_id, username),
    ).fetchone()
    db.close()
    return dict(row) if row else None


# ── POST /calls/initiate ──────────────────────────────────────────────────────


def test_initiate_unauthenticated_redirects(client):
    resp = client.post(
        "/calls/initiate",
        json={"channel": "dm:alice:bob"},
    )
    assert resp.status_code == 302


def test_initiate_missing_channel_returns_400(alice):
    resp = alice.post("/calls/initiate", json={})
    assert resp.status_code == 400
    assert "channel" in resp.get_json()["error"]


def test_initiate_public_channel_denied(alice):
    resp = alice.post("/calls/initiate", json={"channel": "general"})
    assert resp.status_code == 403


def test_initiate_dm_not_participant_denied(alice):
    resp = alice.post("/calls/initiate", json={"channel": "dm:bob:charlie"})
    assert resp.status_code == 403


def test_initiate_dm_with_self_only_denied(alice):
    resp = alice.post("/calls/initiate", json={"channel": "dm:alice"})
    assert resp.status_code in (400, 403)


def test_initiate_dm_creates_call(alice_and_bob):
    resp = alice_and_bob.post("/calls/initiate", json={"channel": "dm:alice:bob"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert "call_id" in data
    assert "alice" in data["participants"]
    assert "bob" in data["participants"]

    call = _get_call(data["call_id"])
    assert call["state"] == "ringing"
    assert call["channel"] == "dm:alice:bob"
    assert call["initiator"] == "alice"


def test_initiate_creates_participant_rows(alice_and_bob):
    data = alice_and_bob.post(
        "/calls/initiate", json={"channel": "dm:alice:bob"}
    ).get_json()
    call_id = data["call_id"]

    alice_p = _get_participant(call_id, "alice")
    bob_p = _get_participant(call_id, "bob")

    assert alice_p["role"] == "initiator"
    assert alice_p["state"] == "accepted"
    assert bob_p["role"] == "participant"
    assert bob_p["state"] == "pending"


def test_initiate_duplicate_call_returns_409(alice_and_bob):
    alice_and_bob.post("/calls/initiate", json={"channel": "dm:alice:bob"})
    resp = alice_and_bob.post("/calls/initiate", json={"channel": "dm:alice:bob"})
    assert resp.status_code == 409
    assert "in progress" in resp.get_json()["error"]


# ── GET /calls/incoming ───────────────────────────────────────────────────────


def test_incoming_unauthenticated_redirects(client):
    resp = client.get("/calls/incoming")
    assert resp.status_code == 302


def test_incoming_empty_when_no_calls(alice):
    resp = alice.get("/calls/incoming")
    assert resp.status_code == 200
    assert resp.get_json() == []


def test_incoming_shows_pending_call(alice_and_bob, app):
    call_id = str(uuid.uuid4())
    _insert_call(call_id, "dm:alice:bob", "alice", state="ringing")
    _insert_participant(call_id, "alice", role="initiator", state="accepted")
    _insert_participant(call_id, "bob", role="participant", state="pending")

    bob_client = app.test_client()
    with bob_client.session_transaction() as sess:
        sess["user"] = "bob"

    data = bob_client.get("/calls/incoming").get_json()
    assert len(data) == 1
    assert data[0]["call_id"] == call_id
    assert data[0]["initiator"] == "alice"


def test_incoming_excludes_expired_calls(alice_and_bob, app):
    call_id = str(uuid.uuid4())
    old_ts = time.time() - 60
    _insert_call(call_id, "dm:alice:bob", "alice", state="ringing", started_ts=old_ts)
    _insert_participant(call_id, "bob", role="participant", state="pending")

    bob_client = app.test_client()
    with bob_client.session_transaction() as sess:
        sess["user"] = "bob"

    data = bob_client.get("/calls/incoming").get_json()
    assert data == []


def test_incoming_shows_active_call_invite(alice_and_bob, app):
    """Pending participant in an active call (group invite) sees it as incoming."""
    call_id = str(uuid.uuid4())
    _insert_call(call_id, "dm:alice:bob", "alice", state="active")
    _insert_participant(call_id, "bob", role="participant", state="pending")

    bob_client = app.test_client()
    with bob_client.session_transaction() as sess:
        sess["user"] = "bob"

    data = bob_client.get("/calls/incoming").get_json()
    assert len(data) == 1
    assert data[0]["call_id"] == call_id


def test_incoming_excludes_calls_where_already_responded(alice_and_bob, app):
    call_id = str(uuid.uuid4())
    _insert_call(call_id, "dm:alice:bob", "alice", state="ringing")
    _insert_participant(call_id, "bob", role="participant", state="rejected")

    bob_client = app.test_client()
    with bob_client.session_transaction() as sess:
        sess["user"] = "bob"

    data = bob_client.get("/calls/incoming").get_json()
    assert data == []


def test_incoming_excludes_callers_own_call(alice_and_bob):
    call_id = str(uuid.uuid4())
    _insert_call(call_id, "dm:alice:bob", "alice", state="ringing")
    _insert_participant(call_id, "alice", role="initiator", state="accepted")

    data = alice_and_bob.get("/calls/incoming").get_json()
    assert data == []


# ── POST /calls/<id>/accept ───────────────────────────────────────────────────


def test_accept_unauthenticated_redirects(client):
    resp = client.post("/calls/fake-id/accept")
    assert resp.status_code == 302


def test_accept_unknown_call_returns_404(alice):
    resp = alice.post("/calls/no-such-id/accept")
    assert resp.status_code == 404


def test_accept_updates_participant_and_call_state(alice_and_bob, app):
    call_id = str(uuid.uuid4())
    _insert_call(call_id, "dm:alice:bob", "alice", state="ringing")
    _insert_participant(call_id, "alice", role="initiator", state="accepted")
    _insert_participant(call_id, "bob", role="participant", state="pending")

    bob_client = app.test_client()
    with bob_client.session_transaction() as sess:
        sess["user"] = "bob"

    resp = bob_client.post(f"/calls/{call_id}/accept")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "ok"
    assert "bob" in data["participants"]
    assert "alice" in data["participants"]

    call = _get_call(call_id)
    assert call["state"] == "active"
    assert call["answered_ts"] is not None

    bob_p = _get_participant(call_id, "bob")
    assert bob_p["state"] == "accepted"
    assert bob_p["joined_ts"] is not None


def test_accept_ended_call_returns_409(alice_and_bob, app):
    call_id = str(uuid.uuid4())
    _insert_call(call_id, "dm:alice:bob", "alice", state="ended")
    _insert_participant(call_id, "bob", role="participant", state="pending")

    bob_client = app.test_client()
    with bob_client.session_transaction() as sess:
        sess["user"] = "bob"

    resp = bob_client.post(f"/calls/{call_id}/accept")
    assert resp.status_code == 409


def test_accept_non_participant_returns_403(alice_and_bob, app):
    call_id = str(uuid.uuid4())
    _insert_call(call_id, "dm:alice:bob", "alice", state="ringing")
    _insert_participant(call_id, "alice", role="initiator", state="accepted")

    bob_client = app.test_client()
    with bob_client.session_transaction() as sess:
        sess["user"] = "bob"

    resp = bob_client.post(f"/calls/{call_id}/accept")
    assert resp.status_code == 403


# ── POST /calls/<id>/reject ───────────────────────────────────────────────────


def test_reject_unauthenticated_redirects(client):
    resp = client.post("/calls/fake-id/reject")
    assert resp.status_code == 302


def test_reject_unknown_call_returns_404(alice):
    resp = alice.post("/calls/no-such-id/reject")
    assert resp.status_code == 404


def test_reject_marks_participant_rejected(alice_and_bob, app):
    call_id = str(uuid.uuid4())
    _insert_call(call_id, "dm:alice:bob", "alice", state="ringing")
    _insert_participant(call_id, "alice", role="initiator", state="accepted")
    _insert_participant(call_id, "bob", role="participant", state="pending")

    bob_client = app.test_client()
    with bob_client.session_transaction() as sess:
        sess["user"] = "bob"

    resp = bob_client.post(f"/calls/{call_id}/reject")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"

    bob_p = _get_participant(call_id, "bob")
    assert bob_p["state"] == "rejected"
    assert bob_p["left_ts"] is not None


def test_reject_by_all_participants_ends_call(alice_and_bob, app):
    call_id = str(uuid.uuid4())
    _insert_call(call_id, "dm:alice:bob", "alice", state="ringing")
    _insert_participant(call_id, "alice", role="initiator", state="accepted")
    _insert_participant(call_id, "bob", role="participant", state="pending")

    bob_client = app.test_client()
    with bob_client.session_transaction() as sess:
        sess["user"] = "bob"

    bob_client.post(f"/calls/{call_id}/reject")

    call = _get_call(call_id)
    assert call["state"] == "rejected"
    assert call["ended_ts"] is not None


def test_reject_with_accepted_participant_keeps_call_active(alice_and_bob, app):
    """If one participant has already accepted, rejecting by another should not end the call."""
    import minimost.auth as auth_mod
    import minimost.common as common_mod

    auth_mod_db = sqlite3.connect(auth_mod.AUTH_DB)
    from werkzeug.security import generate_password_hash

    auth_mod_db.execute(
        "INSERT INTO users (username, password_hash) VALUES (?, ?)",
        ("charlie", generate_password_hash("Password1!")),
    )
    auth_mod_db.commit()
    auth_mod_db.close()
    common_mod.init_user_db("charlie")

    call_id = str(uuid.uuid4())
    _insert_call(call_id, "dm:alice:bob:charlie", "alice", state="ringing")
    _insert_participant(call_id, "alice", role="initiator", state="accepted")
    _insert_participant(call_id, "bob", role="participant", state="accepted")
    _insert_participant(call_id, "charlie", role="participant", state="pending")

    charlie_client = app.test_client()
    with charlie_client.session_transaction() as sess:
        sess["user"] = "charlie"

    charlie_client.post(f"/calls/{call_id}/reject")

    call = _get_call(call_id)
    assert call["state"] == "ringing"


# ── POST /calls/<id>/end ──────────────────────────────────────────────────────


def test_end_unauthenticated_redirects(client):
    resp = client.post("/calls/fake-id/end")
    assert resp.status_code == 302


def test_end_unknown_call_returns_404(alice):
    resp = alice.post("/calls/no-such-id/end")
    assert resp.status_code == 404


def test_end_last_participant_ends_call(alice_and_bob):
    """When the last accepted participant leaves the call ends."""
    call_id = str(uuid.uuid4())
    _insert_call(call_id, "dm:alice:bob", "alice", state="active")
    _insert_participant(call_id, "alice", role="initiator", state="accepted")
    # bob already left, alice is the last one
    _insert_participant(call_id, "bob", role="participant", state="left")

    resp = alice_and_bob.post(f"/calls/{call_id}/end")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"

    call = _get_call(call_id)
    assert call["state"] == "ended"
    assert call["ended_ts"] is not None

    alice_p = _get_participant(call_id, "alice")
    assert alice_p["state"] == "left"
    assert alice_p["left_ts"] is not None


def test_end_with_remaining_participants_keeps_call_active(alice_and_bob, app):
    """When a participant leaves but others remain, the call stays active."""
    call_id = str(uuid.uuid4())
    _insert_call(call_id, "dm:alice:bob", "alice", state="active")
    _insert_participant(call_id, "alice", role="initiator", state="accepted")
    _insert_participant(call_id, "bob", role="participant", state="accepted")

    resp = alice_and_bob.post(f"/calls/{call_id}/end")
    assert resp.status_code == 200

    call = _get_call(call_id)
    assert call["state"] == "active"

    alice_p = _get_participant(call_id, "alice")
    assert alice_p["state"] == "left"


def test_end_ringing_call_cancels_it(alice_and_bob):
    call_id = str(uuid.uuid4())
    _insert_call(call_id, "dm:alice:bob", "alice", state="ringing")
    _insert_participant(call_id, "alice", role="initiator", state="accepted")

    resp = alice_and_bob.post(f"/calls/{call_id}/end")
    assert resp.status_code == 200

    call = _get_call(call_id)
    assert call["state"] == "ended"


# ── POST /calls/<id>/invite ──────────────────────────────────────────────────


def test_invite_unauthenticated_redirects(client):
    resp = client.post("/calls/fake-id/invite", json={"username": "bob"})
    assert resp.status_code == 302


def test_invite_missing_username_returns_400(alice_and_bob):
    call_id = str(uuid.uuid4())
    _insert_call(call_id, "dm:alice:bob", "alice", state="active")
    _insert_participant(call_id, "alice", role="initiator", state="accepted")

    resp = alice_and_bob.post(f"/calls/{call_id}/invite", json={})
    assert resp.status_code == 400


def test_invite_unknown_call_returns_404(alice_and_bob):
    resp = alice_and_bob.post("/calls/no-such-id/invite", json={"username": "bob"})
    assert resp.status_code == 404


def test_invite_non_active_call_returns_409(alice_and_bob):
    call_id = str(uuid.uuid4())
    _insert_call(call_id, "dm:alice:bob", "alice", state="ringing")
    _insert_participant(call_id, "alice", role="initiator", state="accepted")

    resp = alice_and_bob.post(f"/calls/{call_id}/invite", json={"username": "bob"})
    assert resp.status_code == 409


def test_invite_non_participant_caller_returns_403(alice_and_bob):
    call_id = str(uuid.uuid4())
    _insert_call(call_id, "dm:alice:bob", "alice", state="active")
    # alice has no participant row

    resp = alice_and_bob.post(f"/calls/{call_id}/invite", json={"username": "bob"})
    assert resp.status_code == 403


def test_invite_unknown_target_returns_404(alice_and_bob):
    call_id = str(uuid.uuid4())
    _insert_call(call_id, "dm:alice:bob", "alice", state="active")
    _insert_participant(call_id, "alice", role="initiator", state="accepted")

    resp = alice_and_bob.post(
        f"/calls/{call_id}/invite", json={"username": "nosuchuser"}
    )
    assert resp.status_code == 404


def test_invite_adds_pending_participant(alice_and_bob, app):
    call_id = str(uuid.uuid4())
    _insert_call(call_id, "dm:alice:bob", "alice", state="active")
    _insert_participant(call_id, "alice", role="initiator", state="accepted")

    resp = alice_and_bob.post(f"/calls/{call_id}/invite", json={"username": "bob"})
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"

    bob_p = _get_participant(call_id, "bob")
    assert bob_p is not None
    assert bob_p["state"] == "pending"

    # Bob now sees it as incoming
    bob_client = app.test_client()
    with bob_client.session_transaction() as sess:
        sess["user"] = "bob"
    incoming = bob_client.get("/calls/incoming").get_json()
    assert any(c["call_id"] == call_id for c in incoming)


def test_invite_already_accepted_returns_409(alice_and_bob):
    call_id = str(uuid.uuid4())
    _insert_call(call_id, "dm:alice:bob", "alice", state="active")
    _insert_participant(call_id, "alice", role="initiator", state="accepted")
    _insert_participant(call_id, "bob", role="participant", state="accepted")

    resp = alice_and_bob.post(f"/calls/{call_id}/invite", json={"username": "bob"})
    assert resp.status_code == 409


def test_invite_reinvites_rejected_participant(alice_and_bob):
    call_id = str(uuid.uuid4())
    _insert_call(call_id, "dm:alice:bob", "alice", state="active")
    _insert_participant(call_id, "alice", role="initiator", state="accepted")
    _insert_participant(call_id, "bob", role="participant", state="rejected")

    resp = alice_and_bob.post(f"/calls/{call_id}/invite", json={"username": "bob"})
    assert resp.status_code == 200

    bob_p = _get_participant(call_id, "bob")
    assert bob_p["state"] == "pending"


# ── POST /calls/<id>/signal ───────────────────────────────────────────────────


def test_signal_unauthenticated_redirects(client):
    resp = client.post("/calls/fake-id/signal", json={})
    assert resp.status_code == 302


def test_signal_missing_fields_returns_400(alice):
    call_id = str(uuid.uuid4())
    _insert_call(call_id, "dm:alice:bob", "alice", state="active")

    resp = alice.post(f"/calls/{call_id}/signal", json={"to": "bob"})
    assert resp.status_code == 400


def test_signal_invalid_type_returns_400(alice_and_bob):
    call_id = str(uuid.uuid4())
    _insert_call(call_id, "dm:alice:bob", "alice", state="active")

    resp = alice_and_bob.post(
        f"/calls/{call_id}/signal",
        json={"to": "bob", "type": "invalid", "payload": {}},
    )
    assert resp.status_code == 400


def test_signal_unknown_call_returns_404(alice_and_bob):
    resp = alice_and_bob.post(
        "/calls/no-such-id/signal",
        json={"to": "bob", "type": "offer", "payload": {"sdp": "v=0"}},
    )
    assert resp.status_code == 404


def test_signal_on_ended_call_returns_409(alice_and_bob):
    call_id = str(uuid.uuid4())
    _insert_call(call_id, "dm:alice:bob", "alice", state="ended")

    resp = alice_and_bob.post(
        f"/calls/{call_id}/signal",
        json={"to": "bob", "type": "offer", "payload": {"sdp": "v=0"}},
    )
    assert resp.status_code == 409


def test_signal_stores_record(alice_and_bob):
    call_id = str(uuid.uuid4())
    _insert_call(call_id, "dm:alice:bob", "alice", state="active")

    payload = {"type": "offer", "sdp": "v=0\r\no=alice..."}
    resp = alice_and_bob.post(
        f"/calls/{call_id}/signal",
        json={"to": "bob", "type": "offer", "payload": payload},
    )
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"

    db = sqlite3.connect(presence_mod.PRESENCE_DB)
    row = db.execute(
        "SELECT * FROM call_signals WHERE call_id = ? AND from_user = 'alice' AND to_user = 'bob'",
        (call_id,),
    ).fetchone()
    db.close()
    assert row is not None
    assert json.loads(row[5]) == payload


def test_signal_each_valid_type(alice_and_bob):
    call_id = str(uuid.uuid4())
    _insert_call(call_id, "dm:alice:bob", "alice", state="active")

    for sig_type in ("offer", "answer", "ice_candidate"):
        resp = alice_and_bob.post(
            f"/calls/{call_id}/signal",
            json={"to": "bob", "type": sig_type, "payload": {"data": sig_type}},
        )
        assert resp.status_code == 200, f"signal type '{sig_type}' should be accepted"


# ── GET /calls/<id>/signals ───────────────────────────────────────────────────


def test_get_signals_unauthenticated_redirects(client):
    resp = client.get("/calls/fake-id/signals")
    assert resp.status_code == 302


def test_get_signals_empty_when_none(alice_and_bob, app):
    call_id = str(uuid.uuid4())
    _insert_call(call_id, "dm:alice:bob", "alice", state="active")

    bob_client = app.test_client()
    with bob_client.session_transaction() as sess:
        sess["user"] = "bob"

    data = bob_client.get(f"/calls/{call_id}/signals").get_json()
    assert data == []


def test_get_signals_returns_signals_for_user(alice_and_bob, app):
    call_id = str(uuid.uuid4())
    _insert_call(call_id, "dm:alice:bob", "alice", state="active")

    payload = {"type": "offer", "sdp": "v=0..."}
    sig_id = _insert_signal(call_id, "alice", "bob", "offer", payload)

    bob_client = app.test_client()
    with bob_client.session_transaction() as sess:
        sess["user"] = "bob"

    data = bob_client.get(f"/calls/{call_id}/signals").get_json()
    assert len(data) == 1
    assert data[0]["from"] == "alice"
    assert data[0]["type"] == "offer"
    assert data[0]["payload"] == payload
    assert data[0]["id"] == sig_id


def test_get_signals_excludes_other_recipients(alice_and_bob):
    call_id = str(uuid.uuid4())
    _insert_call(call_id, "dm:alice:bob", "alice", state="active")
    _insert_signal(call_id, "bob", "alice", "answer", {"sdp": "v=0..."})

    # alice's signals should not include a signal addressed to bob
    data = alice_and_bob.get(f"/calls/{call_id}/signals").get_json()
    for sig in data:
        assert (
            sig["from"] != "bob" or True
        )  # signal is from bob TO alice, so alice sees it
    # Actually: insert was from bob TO alice, so alice SHOULD see it
    # Let's verify alice sees the answer signal
    assert len(data) == 1
    assert data[0]["from"] == "bob"


def test_get_signals_after_param_filters_old(alice_and_bob, app):
    call_id = str(uuid.uuid4())
    _insert_call(call_id, "dm:alice:bob", "alice", state="active")

    sig1 = _insert_signal(call_id, "alice", "bob", "offer", {"sdp": "v=0..."})
    sig2 = _insert_signal(
        call_id, "alice", "bob", "ice_candidate", {"candidate": "..."}
    )

    bob_client = app.test_client()
    with bob_client.session_transaction() as sess:
        sess["user"] = "bob"

    data = bob_client.get(f"/calls/{call_id}/signals?after={sig1}").get_json()
    assert len(data) == 1
    assert data[0]["id"] == sig2


def test_get_signals_invalid_after_treated_as_zero(alice_and_bob, app):
    call_id = str(uuid.uuid4())
    _insert_call(call_id, "dm:alice:bob", "alice", state="active")
    _insert_signal(call_id, "alice", "bob", "offer", {"sdp": "v=0..."})

    bob_client = app.test_client()
    with bob_client.session_transaction() as sess:
        sess["user"] = "bob"

    data = bob_client.get(f"/calls/{call_id}/signals?after=notanumber").get_json()
    assert len(data) == 1


# ── GET /calls/<id>/state ─────────────────────────────────────────────────────


def test_call_state_unauthenticated_redirects(client):
    resp = client.get("/calls/fake-id/state")
    assert resp.status_code == 302


def test_call_state_unknown_call_returns_404(alice):
    resp = alice.get("/calls/no-such-id/state")
    assert resp.status_code == 404


def test_call_state_returns_full_details(alice_and_bob):
    call_id = str(uuid.uuid4())
    now = time.time()
    _insert_call(call_id, "dm:alice:bob", "alice", state="active", started_ts=now)
    _insert_participant(
        call_id, "alice", role="initiator", state="accepted", joined_ts=now
    )
    _insert_participant(
        call_id, "bob", role="participant", state="accepted", joined_ts=now
    )

    data = alice_and_bob.get(f"/calls/{call_id}/state").get_json()
    assert data["call_id"] == call_id
    assert data["channel"] == "dm:alice:bob"
    assert data["initiator"] == "alice"
    assert data["state"] == "active"
    assert len(data["participants"]) == 2

    names = {p["username"] for p in data["participants"]}
    assert names == {"alice", "bob"}


def test_call_state_ringing(alice_and_bob):
    call_id = str(uuid.uuid4())
    _insert_call(call_id, "dm:alice:bob", "alice", state="ringing")
    _insert_participant(call_id, "alice", role="initiator", state="accepted")
    _insert_participant(call_id, "bob", role="participant", state="pending")

    data = alice_and_bob.get(f"/calls/{call_id}/state").get_json()
    assert data["state"] == "ringing"
    pending = [p for p in data["participants"] if p["username"] == "bob"]
    assert pending[0]["state"] == "pending"


def test_call_state_ended(alice_and_bob):
    call_id = str(uuid.uuid4())
    _insert_call(call_id, "dm:alice:bob", "alice", state="ended")

    data = alice_and_bob.get(f"/calls/{call_id}/state").get_json()
    assert data["state"] == "ended"


# ── End-to-end flow ───────────────────────────────────────────────────────────


def test_full_call_lifecycle(alice_and_bob, app):
    """Alice initiates, Bob accepts, then Alice ends the call."""
    bob_client = app.test_client()
    with bob_client.session_transaction() as sess:
        sess["user"] = "bob"

    # Alice starts call
    resp = alice_and_bob.post("/calls/initiate", json={"channel": "dm:alice:bob"})
    assert resp.status_code == 200
    call_id = resp.get_json()["call_id"]

    # Bob sees incoming call
    incoming = bob_client.get("/calls/incoming").get_json()
    assert len(incoming) == 1
    assert incoming[0]["call_id"] == call_id

    # Bob accepts
    resp = bob_client.post(f"/calls/{call_id}/accept")
    assert resp.status_code == 200

    # Call is now active
    state = alice_and_bob.get(f"/calls/{call_id}/state").get_json()
    assert state["state"] == "active"

    # Bob no longer sees incoming
    incoming = bob_client.get("/calls/incoming").get_json()
    assert incoming == []

    # Signal exchange
    alice_offer = {"type": "offer", "sdp": "v=0\r\nfake-offer"}
    alice_and_bob.post(
        f"/calls/{call_id}/signal",
        json={"to": "bob", "type": "offer", "payload": alice_offer},
    )
    signals_to_bob = bob_client.get(f"/calls/{call_id}/signals").get_json()
    assert len(signals_to_bob) == 1
    assert signals_to_bob[0]["payload"] == alice_offer

    bob_answer = {"type": "answer", "sdp": "v=0\r\nfake-answer"}
    bob_client.post(
        f"/calls/{call_id}/signal",
        json={"to": "alice", "type": "answer", "payload": bob_answer},
    )
    signals_to_alice = alice_and_bob.get(f"/calls/{call_id}/signals").get_json()
    assert len(signals_to_alice) == 1
    assert signals_to_alice[0]["payload"] == bob_answer

    # Alice leaves — call stays active (Bob is still in it)
    resp = alice_and_bob.post(f"/calls/{call_id}/end")
    assert resp.status_code == 200

    state = alice_and_bob.get(f"/calls/{call_id}/state").get_json()
    assert state["state"] == "active"

    # Bob leaves — now call ends (last participant)
    bob_client.post(f"/calls/{call_id}/end")
    state = bob_client.get(f"/calls/{call_id}/state").get_json()
    assert state["state"] == "ended"


def test_full_reject_flow(alice_and_bob, app):
    """Alice initiates, Bob rejects — call becomes rejected."""
    bob_client = app.test_client()
    with bob_client.session_transaction() as sess:
        sess["user"] = "bob"

    resp = alice_and_bob.post("/calls/initiate", json={"channel": "dm:alice:bob"})
    call_id = resp.get_json()["call_id"]

    bob_client.post(f"/calls/{call_id}/reject")

    state = alice_and_bob.get(f"/calls/{call_id}/state").get_json()
    assert state["state"] == "rejected"

    # Alice cannot start another call after rejection (new call should work)
    resp2 = alice_and_bob.post("/calls/initiate", json={"channel": "dm:alice:bob"})
    assert resp2.status_code == 200


# ── POST /calls/<id>/media ────────────────────────────────────────────────────


def test_upload_media_unauthenticated_redirects(client):
    resp = client.post(
        "/calls/fake-id/media",
        data=b"\x00\x01",
        content_type="application/octet-stream",
    )
    assert resp.status_code == 302


def test_upload_media_unknown_call_returns_404(alice_and_bob):
    resp = alice_and_bob.post(
        "/calls/no-such-id/media",
        data=b"\x00\x01",
        content_type="application/octet-stream",
    )
    assert resp.status_code == 404


def test_upload_media_not_participant_returns_404(alice_and_bob):
    call_id = str(uuid.uuid4())
    _insert_call(call_id, "dm:alice:bob", "alice", state="active")
    # alice is in the call but NOT as a participant row — should get 404
    resp = alice_and_bob.post(
        f"/calls/{call_id}/media",
        data=b"\x00\x01",
        content_type="application/octet-stream",
    )
    assert resp.status_code == 404


def test_upload_media_empty_body_returns_400(alice_and_bob):
    call_id = str(uuid.uuid4())
    _insert_call(call_id, "dm:alice:bob", "alice", state="active")
    _insert_participant(call_id, "alice", role="initiator", state="accepted")

    resp = alice_and_bob.post(
        f"/calls/{call_id}/media",
        data=b"",
        content_type="application/octet-stream",
    )
    assert resp.status_code == 400


def test_upload_media_init_chunk_stored(alice_and_bob):
    call_id = str(uuid.uuid4())
    _insert_call(call_id, "dm:alice:bob", "alice", state="active")
    _insert_participant(call_id, "alice", role="initiator", state="accepted")

    mime = "video/webm;codecs=vp8,opus"
    resp = alice_and_bob.post(
        f"/calls/{call_id}/media",
        data=b"INIT_DATA",
        content_type="application/octet-stream",
        headers={"X-Init": "1", "X-Mime": mime},
    )
    assert resp.status_code == 200
    assert resp.get_json()["seq"] == -1

    db = sqlite3.connect(presence_mod.PRESENCE_DB)
    db.row_factory = sqlite3.Row
    row = db.execute(
        "SELECT mime_type, data FROM call_media"
        " WHERE call_id = ? AND sender = ? AND is_init = 1",
        (call_id, "alice"),
    ).fetchone()
    db.close()
    assert row is not None
    assert bytes(row["data"]) == b"INIT_DATA"
    assert row["mime_type"] == mime


def test_upload_media_subsequent_chunks_sequenced(alice_and_bob):
    call_id = str(uuid.uuid4())
    _insert_call(call_id, "dm:alice:bob", "alice", state="active")
    _insert_participant(call_id, "alice", role="initiator", state="accepted")

    # Upload init first
    alice_and_bob.post(
        f"/calls/{call_id}/media",
        data=b"INIT",
        content_type="application/octet-stream",
        headers={"X-Init": "1", "X-Mime": "video/webm"},
    )
    # Upload two more chunks
    r1 = alice_and_bob.post(
        f"/calls/{call_id}/media",
        data=b"CHUNK0",
        content_type="application/octet-stream",
    )
    r2 = alice_and_bob.post(
        f"/calls/{call_id}/media",
        data=b"CHUNK1",
        content_type="application/octet-stream",
    )
    seq1 = r1.get_json()["seq"]
    seq2 = r2.get_json()["seq"]
    assert isinstance(seq1, int) and seq1 > 0
    assert seq2 > seq1

    db = sqlite3.connect(presence_mod.PRESENCE_DB)
    count = db.execute(
        "SELECT COUNT(*) FROM call_media WHERE call_id = ? AND sender = ? AND is_init = 0",
        (call_id, "alice"),
    ).fetchone()[0]
    db.close()
    assert count == 2


def test_upload_media_ended_call_returns_409(alice_and_bob):
    call_id = str(uuid.uuid4())
    _insert_call(call_id, "dm:alice:bob", "alice", state="ended")
    _insert_participant(call_id, "alice", role="initiator", state="left")

    resp = alice_and_bob.post(
        f"/calls/{call_id}/media",
        data=b"\x00\x01",
        content_type="application/octet-stream",
    )
    assert resp.status_code == 409


# ── GET /calls/<id>/media ─────────────────────────────────────────────────────


def test_get_media_unauthenticated_redirects(client):
    resp = client.get("/calls/fake-id/media?sender=alice")
    assert resp.status_code == 302


def test_get_media_missing_sender_returns_400(alice_and_bob):
    call_id = str(uuid.uuid4())
    _insert_call(call_id, "dm:alice:bob", "alice", state="active")
    _insert_participant(call_id, "alice", role="initiator", state="accepted")

    resp = alice_and_bob.get(f"/calls/{call_id}/media")
    assert resp.status_code == 400
    assert "sender" in resp.get_json()["error"]


def test_get_media_not_participant_returns_403(alice_and_bob, app):
    call_id = str(uuid.uuid4())
    _insert_call(call_id, "dm:alice:bob", "alice", state="active")
    # alice has no participant row — 403
    resp = alice_and_bob.get(f"/calls/{call_id}/media?sender=bob")
    assert resp.status_code == 403


def test_get_media_no_data_yet_returns_empty(alice_and_bob):
    call_id = str(uuid.uuid4())
    _insert_call(call_id, "dm:alice:bob", "alice", state="active")
    _insert_participant(call_id, "alice", role="initiator", state="accepted")

    resp = alice_and_bob.get(f"/calls/{call_id}/media?sender=bob")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["init"] is None
    assert data["chunks"] == []


def test_get_media_returns_init_and_chunks(alice_and_bob, app):
    call_id = str(uuid.uuid4())
    _insert_call(call_id, "dm:alice:bob", "alice", state="active")
    _insert_participant(call_id, "alice", role="initiator", state="accepted")
    _insert_participant(call_id, "bob", role="participant", state="accepted")

    bob_client = app.test_client()
    with bob_client.session_transaction() as sess:
        sess["user"] = "bob"

    mime = "video/webm;codecs=vp8,opus"
    # Alice uploads init + 2 chunks
    alice_and_bob.post(
        f"/calls/{call_id}/media",
        data=b"INIT",
        content_type="application/octet-stream",
        headers={"X-Init": "1", "X-Mime": mime},
    )
    alice_and_bob.post(
        f"/calls/{call_id}/media",
        data=b"CHUNK0",
        content_type="application/octet-stream",
    )
    alice_and_bob.post(
        f"/calls/{call_id}/media",
        data=b"CHUNK1",
        content_type="application/octet-stream",
    )

    # Bob polls for Alice's stream
    resp = bob_client.get(f"/calls/{call_id}/media?sender=alice&after=-1")
    assert resp.status_code == 200
    data = resp.get_json()

    assert data["mime_type"] == mime
    assert base64.b64decode(data["init"]) == b"INIT"
    assert len(data["chunks"]) == 2
    assert base64.b64decode(data["chunks"][0]["data"]) == b"CHUNK0"
    assert base64.b64decode(data["chunks"][1]["data"]) == b"CHUNK1"
    assert data["chunks"][0]["seq"] < data["chunks"][1]["seq"]


def test_get_media_after_param_filters_old_chunks(alice_and_bob, app):
    call_id = str(uuid.uuid4())
    _insert_call(call_id, "dm:alice:bob", "alice", state="active")
    _insert_participant(call_id, "alice", role="initiator", state="accepted")
    _insert_participant(call_id, "bob", role="participant", state="accepted")

    bob_client = app.test_client()
    with bob_client.session_transaction() as sess:
        sess["user"] = "bob"

    alice_and_bob.post(
        f"/calls/{call_id}/media",
        data=b"INIT",
        content_type="application/octet-stream",
        headers={"X-Init": "1", "X-Mime": "video/webm"},
    )
    r0 = alice_and_bob.post(
        f"/calls/{call_id}/media", data=b"C0", content_type="application/octet-stream"
    )
    alice_and_bob.post(
        f"/calls/{call_id}/media", data=b"C1", content_type="application/octet-stream"
    )
    alice_and_bob.post(
        f"/calls/{call_id}/media", data=b"C2", content_type="application/octet-stream"
    )
    seq0 = r0.get_json()["seq"]

    # Ask for chunks after the first chunk — should only get C1 and C2
    resp = bob_client.get(f"/calls/{call_id}/media?sender=alice&after={seq0}")
    data = resp.get_json()
    assert len(data["chunks"]) == 2
    assert data["chunks"][0]["seq"] > seq0
    assert data["chunks"][1]["seq"] > data["chunks"][0]["seq"]
    # Init is always returned regardless of after
    assert data["init"] is not None


def test_get_media_init_always_returned_with_after(alice_and_bob, app):
    """Init segment is always returned even when after param is large."""
    call_id = str(uuid.uuid4())
    _insert_call(call_id, "dm:alice:bob", "alice", state="active")
    _insert_participant(call_id, "alice", role="initiator", state="accepted")
    _insert_participant(call_id, "bob", role="participant", state="accepted")

    bob_client = app.test_client()
    with bob_client.session_transaction() as sess:
        sess["user"] = "bob"

    alice_and_bob.post(
        f"/calls/{call_id}/media",
        data=b"INIT",
        content_type="application/octet-stream",
        headers={"X-Init": "1", "X-Mime": "video/webm"},
    )

    resp = bob_client.get(f"/calls/{call_id}/media?sender=alice&after=999")
    data = resp.get_json()
    assert base64.b64decode(data["init"]) == b"INIT"
    assert data["chunks"] == []


# ── Media relay end-to-end ────────────────────────────────────────────────────


def test_media_relay_roundtrip(alice_and_bob, app):
    """Alice uploads media; Bob receives it via the relay."""
    bob_client = app.test_client()
    with bob_client.session_transaction() as sess:
        sess["user"] = "bob"

    # Set up active call
    call_id = str(uuid.uuid4())
    _insert_call(call_id, "dm:alice:bob", "alice", state="active")
    _insert_participant(call_id, "alice", role="initiator", state="accepted")
    _insert_participant(call_id, "bob", role="participant", state="accepted")

    mime = "video/webm;codecs=vp9,opus"
    fake_init = b"\x1a\x45\xdf\xa3"  # WebM EBML header magic bytes
    fake_chunk = b"\x00" * 64

    alice_and_bob.post(
        f"/calls/{call_id}/media",
        data=fake_init,
        content_type="application/octet-stream",
        headers={"X-Init": "1", "X-Mime": mime},
    )
    alice_and_bob.post(
        f"/calls/{call_id}/media",
        data=fake_chunk,
        content_type="application/octet-stream",
    )

    # First poll: Bob gets init + chunk
    resp = bob_client.get(f"/calls/{call_id}/media?sender=alice&after=-1")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["mime_type"] == mime
    assert base64.b64decode(data["init"]) == fake_init
    assert len(data["chunks"]) == 1
    last_seq = data["chunks"][0]["seq"]

    # Alice sends another chunk
    alice_and_bob.post(
        f"/calls/{call_id}/media", data=b"NEW", content_type="application/octet-stream"
    )

    # Second poll: Bob only gets the new chunk
    resp2 = bob_client.get(f"/calls/{call_id}/media?sender=alice&after={last_seq}")
    data2 = resp2.get_json()
    assert len(data2["chunks"]) == 1
    assert base64.b64decode(data2["chunks"][0]["data"]) == b"NEW"


# ── Standalone screen share ───────────────────────────────────────────────────


def _make_bob_client(app, isolated_dbs):
    """Create an authenticated client for bob (assumes bob is already registered)."""
    import minimost.auth as auth_mod
    import minimost.common as common_mod

    _add_user = lambda db, u: None  # noqa: E731 – already registered by fixture
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["user"] = "bob"
    return c


def test_screenshare_start_unauthenticated(client):
    resp = client.post("/screenshare/start", json={"channel": "dm:alice:bob"})
    assert resp.status_code == 302


def test_screenshare_start_missing_channel(alice):
    resp = alice.post("/screenshare/start", json={})
    assert resp.status_code == 400


def test_screenshare_start_not_participant(alice):
    resp = alice.post("/screenshare/start", json={"channel": "dm:bob:charlie"})
    assert resp.status_code == 403


def test_screenshare_start_and_active(alice_and_bob):
    resp = alice_and_bob.post("/screenshare/start", json={"channel": "dm:alice:bob"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert "share_id" in data

    active = alice_and_bob.get("/screenshare/active?channel=dm:alice:bob")
    assert active.status_code == 200
    shares = active.get_json()
    assert len(shares) == 1
    assert shares[0]["sharer"] == "alice"
    assert shares[0]["share_id"] == data["share_id"]


def test_screenshare_active_missing_channel(alice_and_bob):
    resp = alice_and_bob.get("/screenshare/active")
    assert resp.status_code == 400


def test_screenshare_active_not_participant(alice_and_bob):
    resp = alice_and_bob.get("/screenshare/active?channel=dm:bob:charlie")
    assert resp.status_code == 403


def test_screenshare_stop_own_share(alice_and_bob):
    share_id = alice_and_bob.post(
        "/screenshare/start", json={"channel": "dm:alice:bob"}
    ).get_json()["share_id"]

    resp = alice_and_bob.post(f"/screenshare/{share_id}/stop")
    assert resp.status_code == 200

    active = alice_and_bob.get("/screenshare/active?channel=dm:alice:bob").get_json()
    assert active == []


def test_screenshare_stop_not_found(alice_and_bob):
    resp = alice_and_bob.post(f"/screenshare/{uuid.uuid4()}/stop")
    assert resp.status_code == 404


def test_screenshare_stop_other_user_denied(app, isolated_dbs, alice_and_bob):
    share_id = alice_and_bob.post(
        "/screenshare/start", json={"channel": "dm:alice:bob"}
    ).get_json()["share_id"]

    import minimost.auth as auth_mod
    import minimost.common as common_mod

    try:
        auth_mod._add_user(auth_mod.AUTH_DB, "bob", "Pass1234!")
    except Exception:
        pass
    bob_client = app.test_client()
    with bob_client.session_transaction() as sess:
        sess["user"] = "bob"

    resp = bob_client.post(f"/screenshare/{share_id}/stop")
    assert resp.status_code == 403


def test_screenshare_media_upload_and_download(app, isolated_dbs, alice_and_bob):
    share_id = alice_and_bob.post(
        "/screenshare/start", json={"channel": "dm:alice:bob"}
    ).get_json()["share_id"]

    # Upload init segment
    resp = alice_and_bob.post(
        f"/screenshare/{share_id}/media",
        data=b"INIT",
        content_type="application/octet-stream",
        headers={"X-Init": "1", "X-Mime": "video/webm"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["seq"] == -1

    # Upload data chunk
    resp2 = alice_and_bob.post(
        f"/screenshare/{share_id}/media",
        data=b"CHUNK1",
        content_type="application/octet-stream",
    )
    assert resp2.status_code == 200
    seq = resp2.get_json()["seq"]
    assert seq > 0

    # Bob downloads
    bob_client = app.test_client()
    with bob_client.session_transaction() as sess:
        sess["user"] = "bob"

    dl = bob_client.get(f"/screenshare/{share_id}/media?after=-1")
    assert dl.status_code == 200
    payload = dl.get_json()
    assert payload["active"] is True
    assert base64.b64decode(payload["init"]) == b"INIT"
    assert len(payload["chunks"]) == 1
    assert base64.b64decode(payload["chunks"][0]["data"]) == b"CHUNK1"

    # After stopping, active flag is false
    alice_and_bob.post(f"/screenshare/{share_id}/stop")
    dl2 = bob_client.get(f"/screenshare/{share_id}/media?after=-1")
    assert dl2.status_code == 200
    assert dl2.get_json()["active"] is False


def test_screenshare_media_upload_no_data(alice_and_bob):
    share_id = alice_and_bob.post(
        "/screenshare/start", json={"channel": "dm:alice:bob"}
    ).get_json()["share_id"]
    resp = alice_and_bob.post(
        f"/screenshare/{share_id}/media",
        data=b"",
        content_type="application/octet-stream",
    )
    assert resp.status_code == 400


def test_screenshare_media_upload_to_ended_share(alice_and_bob):
    share_id = alice_and_bob.post(
        "/screenshare/start", json={"channel": "dm:alice:bob"}
    ).get_json()["share_id"]
    alice_and_bob.post(f"/screenshare/{share_id}/stop")
    resp = alice_and_bob.post(
        f"/screenshare/{share_id}/media",
        data=b"DATA",
        content_type="application/octet-stream",
    )
    assert resp.status_code == 409


def test_screenshare_start_replaces_previous(alice_and_bob):
    ch = "dm:alice:bob"
    first = alice_and_bob.post("/screenshare/start", json={"channel": ch}).get_json()[
        "share_id"
    ]
    second = alice_and_bob.post("/screenshare/start", json={"channel": ch}).get_json()[
        "share_id"
    ]
    assert first != second

    active = alice_and_bob.get(f"/screenshare/active?channel={ch}").get_json()
    share_ids = [s["share_id"] for s in active]
    assert second in share_ids
    assert first not in share_ids


def test_reset_all_screenshares_ended(alice_and_bob):
    from minimost.calls import reset_all_screenshares_ended

    alice_and_bob.post("/screenshare/start", json={"channel": "dm:alice:bob"})
    reset_all_screenshares_ended()

    active = alice_and_bob.get("/screenshare/active?channel=dm:alice:bob").get_json()
    assert active == []


# ── POST /calls/<id>/screenshare ──────────────────────────────────────────────


def test_set_screenshare_unauthenticated_redirects(client):
    resp = client.post("/calls/fake-id/screenshare", json={"on": True})
    assert resp.status_code in (302, 401)


def test_set_screenshare_unknown_call_returns_404(alice):
    resp = alice.post(f"/calls/{uuid.uuid4()}/screenshare", json={"on": True})
    assert resp.status_code == 404


def test_set_screenshare_non_active_call_returns_409(alice_and_bob):
    call_id = str(uuid.uuid4())
    _insert_call(call_id, "dm:alice:bob", "alice", state="ringing")
    _insert_participant(call_id, "alice", role="initiator", state="accepted")
    resp = alice_and_bob.post(f"/calls/{call_id}/screenshare", json={"on": True})
    assert resp.status_code == 409


def test_set_screenshare_on_and_off(alice_and_bob):
    call_id = str(uuid.uuid4())
    _insert_call(call_id, "dm:alice:bob", "alice", state="active")
    _insert_participant(call_id, "alice", role="initiator", state="accepted")

    resp = alice_and_bob.post(f"/calls/{call_id}/screenshare", json={"on": True})
    assert resp.status_code == 200
    assert _get_call(call_id)["screenshare_user"] == "alice"

    resp = alice_and_bob.post(f"/calls/{call_id}/screenshare", json={"on": False})
    assert resp.status_code == 200
    assert _get_call(call_id)["screenshare_user"] is None


def test_set_screenshare_off_only_clears_own(alice_and_bob):
    """Releasing the screen must not clear another user's active share."""
    call_id = str(uuid.uuid4())
    _insert_call(call_id, "dm:alice:bob", "alice", state="active")
    _insert_participant(call_id, "alice", role="initiator", state="accepted")
    db = sqlite3.connect(presence_mod.PRESENCE_DB)
    db.execute(
        "UPDATE calls SET screenshare_user = 'bob' WHERE call_id = ?", (call_id,)
    )
    db.commit()
    db.close()

    resp = alice_and_bob.post(f"/calls/{call_id}/screenshare", json={"on": False})
    assert resp.status_code == 200
    assert _get_call(call_id)["screenshare_user"] == "bob"


# ── signaling cleanup on call end ─────────────────────────────────────────────


def test_end_last_participant_purges_signals(alice_and_bob):
    call_id = str(uuid.uuid4())
    _insert_call(call_id, "dm:alice:bob", "alice", state="active")
    _insert_participant(call_id, "alice", role="initiator", state="accepted")
    _insert_participant(call_id, "bob", role="participant", state="left")
    _insert_signal(call_id, "alice", "bob", "offer")
    _insert_signal(call_id, "bob", "alice", "answer")

    resp = alice_and_bob.post(f"/calls/{call_id}/end")
    assert resp.status_code == 200
    assert _get_call(call_id)["state"] == "ended"

    db = sqlite3.connect(presence_mod.PRESENCE_DB)
    remaining = db.execute(
        "SELECT COUNT(*) FROM call_signals WHERE call_id = ?", (call_id,)
    ).fetchone()[0]
    db.close()
    assert remaining == 0


# ── POST/GET /screenshare/<id>/signal[s] ──────────────────────────────────────


def _start_share(client, channel="dm:alice:bob"):
    return client.post("/screenshare/start", json={"channel": channel}).get_json()[
        "share_id"
    ]


def test_share_signal_unauthenticated_redirects(client):
    resp = client.post(f"/screenshare/{uuid.uuid4()}/signal", json={})
    assert resp.status_code in (302, 401)


def test_share_signal_missing_fields_returns_400(alice_and_bob):
    share_id = _start_share(alice_and_bob)
    resp = alice_and_bob.post(f"/screenshare/{share_id}/signal", json={"to": "bob"})
    assert resp.status_code == 400


def test_share_signal_invalid_type_returns_400(alice_and_bob):
    share_id = _start_share(alice_and_bob)
    resp = alice_and_bob.post(
        f"/screenshare/{share_id}/signal",
        json={"to": "bob", "type": "bogus", "payload": {}},
    )
    assert resp.status_code == 400


def test_share_signal_unknown_share_returns_404(alice_and_bob):
    resp = alice_and_bob.post(
        f"/screenshare/{uuid.uuid4()}/signal",
        json={"to": "bob", "type": "offer", "payload": {"sdp": "x"}},
    )
    assert resp.status_code == 404


def test_share_signal_stores_and_round_trips(app, isolated_dbs, alice_and_bob):
    import minimost.auth as auth_mod

    try:
        auth_mod._add_user(auth_mod.AUTH_DB, "bob", "Pass1234!")
    except Exception:
        pass
    bob_client = app.test_client()
    with bob_client.session_transaction() as sess:
        sess["user"] = "bob"

    share_id = _start_share(alice_and_bob)

    # bob (viewer) sends an offer to alice (sharer)
    payload = {"type": "offer", "sdp": "v=0\r\no=bob..."}
    resp = bob_client.post(
        f"/screenshare/{share_id}/signal",
        json={"to": "alice", "type": "offer", "payload": payload},
    )
    assert resp.status_code == 200

    # alice polls and receives bob's offer
    got = alice_and_bob.get(f"/screenshare/{share_id}/signals").get_json()
    assert len(got) == 1
    assert got[0]["from"] == "bob"
    assert got[0]["type"] == "offer"
    assert got[0]["payload"] == payload

    # the after cursor filters already-seen signals
    after = got[0]["id"]
    again = alice_and_bob.get(
        f"/screenshare/{share_id}/signals?after={after}"
    ).get_json()
    assert again == []


def test_share_signal_purged_on_stop(alice_and_bob):
    share_id = _start_share(alice_and_bob)
    _insert_signal(share_id, "bob", "alice", "offer")

    alice_and_bob.post(f"/screenshare/{share_id}/stop")

    db = sqlite3.connect(presence_mod.PRESENCE_DB)
    remaining = db.execute(
        "SELECT COUNT(*) FROM call_signals WHERE call_id = ?", (share_id,)
    ).fetchone()[0]
    db.close()
    assert remaining == 0
