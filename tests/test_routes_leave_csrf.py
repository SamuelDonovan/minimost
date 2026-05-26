"""Tests for leave-private-channel route and CSRF enforcement.

Covers:
  POST /private_channels/<id>/leave
  __init__._enforce_csrf (lines 137-146)
"""

import json
import sqlite3

from werkzeug.security import generate_password_hash

import minimost.auth as auth_mod
import minimost.common as common_mod
import minimost.presence as presence_mod

# ── helpers ───────────────────────────────────────────────────────────────────


def _add_user(username, password="Password1!"):
    db = sqlite3.connect(auth_mod.AUTH_DB)
    db.execute(
        "INSERT INTO users (username, password_hash) VALUES (?, ?)",
        (username, generate_password_hash(password)),
    )
    db.commit()
    db.close()
    common_mod.init_user_db(username)


def _create_channel(client, name, members=None):
    payload = {"name": name}
    if members is not None:
        payload["members"] = members
    return client.post(
        "/private_channels/create",
        data=json.dumps(payload),
        content_type="application/json",
    )


def _get_user_messages(username, channel):
    db = sqlite3.connect(str(common_mod.user_db_path(username)))
    rows = db.execute(
        "SELECT sender, content, content_type FROM messages WHERE channel=?",
        (channel,),
    ).fetchall()
    db.close()
    return rows


def _get_pdb_members(channel_id):
    pdb = sqlite3.connect(presence_mod.PRESENCE_DB)
    rows = pdb.execute(
        "SELECT username FROM private_channel_members WHERE channel_id=?",
        (channel_id,),
    ).fetchall()
    pdb.close()
    return [r[0] for r in rows]


# ── POST /private_channels/<id>/leave ────────────────────────────────────────


def test_leave_unauthenticated(client):
    resp = client.post("/private_channels/1/leave")
    assert resp.status_code == 302


def test_leave_success(alice):
    channel_id = _create_channel(alice, "solo").get_json()["id"]
    resp = alice.post(f"/private_channels/{channel_id}/leave")
    assert resp.status_code == 200
    assert resp.data == b"ok"


def test_leave_removes_from_members(alice):
    channel_id = _create_channel(alice, "leaveme").get_json()["id"]
    alice.post(f"/private_channels/{channel_id}/leave")
    members = _get_pdb_members(channel_id)
    assert "alice" not in members


def test_leave_forbidden_non_member(alice_and_bob, app):
    channel_id = _create_channel(alice_and_bob, "alicechan").get_json()["id"]
    _add_user("charlie")
    charlie = app.test_client()
    with charlie.session_transaction() as sess:
        sess["user"] = "charlie"
    resp = charlie.post(f"/private_channels/{channel_id}/leave")
    assert resp.status_code == 403


def test_leave_sends_system_message_to_remaining(alice_and_bob):
    channel_id = _create_channel(alice_and_bob, "withbob", members=["bob"]).get_json()[
        "id"
    ]
    ch = f"private:{channel_id}"

    alice_and_bob.post(f"/private_channels/{channel_id}/leave")

    rows = _get_user_messages("bob", ch)
    system_msgs = [r for r in rows if r[2] == "system"]
    assert any("alice has left the channel" in r[1] for r in system_msgs)


def test_leave_no_system_message_when_last_member(alice):
    """When the last member leaves, there are no remaining members to notify."""
    channel_id = _create_channel(alice, "lastman").get_json()["id"]
    ch = f"private:{channel_id}"

    alice.post(f"/private_channels/{channel_id}/leave")

    # alice's own DB should have no system message about leaving
    rows = _get_user_messages("alice", ch)
    leave_msgs = [r for r in rows if r[2] == "system" and "has left" in (r[1] or "")]
    assert len(leave_msgs) == 0


def test_leave_channel_no_longer_listed(alice):
    channel_id = _create_channel(alice, "byebye").get_json()["id"]
    alice.post(f"/private_channels/{channel_id}/leave")
    data = alice.get("/private_channels").get_json()
    ids = [c["id"] for c in data]
    assert channel_id not in ids


def test_leave_system_message_content(alice_and_bob):
    """System message should name the leaving user."""
    channel_id = _create_channel(
        alice_and_bob, "namechecked", members=["bob"]
    ).get_json()["id"]
    ch = f"private:{channel_id}"

    alice_and_bob.post(f"/private_channels/{channel_id}/leave")

    rows = _get_user_messages("bob", ch)
    system_msgs = [r for r in rows if r[2] == "system"]
    assert any(r[1] == "alice has left the channel" for r in system_msgs)


def test_leave_does_not_affect_other_members_list(alice_and_bob):
    """After alice leaves, bob should still be a member."""
    channel_id = _create_channel(alice_and_bob, "bobstays", members=["bob"]).get_json()[
        "id"
    ]

    alice_and_bob.post(f"/private_channels/{channel_id}/leave")

    members = _get_pdb_members(channel_id)
    assert "bob" in members
    assert "alice" not in members


# ── CSRF enforcement (_enforce_csrf) ─────────────────────────────────────────


def _csrf_app(isolated_dbs):
    """Create an app with CSRF_ENABLED=True."""
    from minimost import create_app

    application = create_app()
    application.config["TESTING"] = True
    application.config["CSRF_ENABLED"] = True
    return application


def test_csrf_get_request_passes_through(isolated_dbs):
    """GET requests are exempt from CSRF validation (lines 137-138)."""
    app = _csrf_app(isolated_dbs)
    c = app.test_client()
    resp = c.get("/login")
    # Login page renders (200) — not blocked by CSRF
    assert resp.status_code == 200


def test_csrf_non_auth_blueprint_passes_through(isolated_dbs):
    """POST to a non-auth blueprint (chat) skips CSRF (lines 141-142)."""
    app = _csrf_app(isolated_dbs)
    _add_user("alice")
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["user"] = "alice"
    # POST to a chat route — no CSRF token needed
    resp = c.post("/send/general", data={"text": "hello"})
    assert resp.status_code == 200


def test_csrf_missing_token_on_auth_post_aborts_403(isolated_dbs):
    """POST to auth blueprint with no CSRF token → 403 (line 146)."""
    app = _csrf_app(isolated_dbs)
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["_csrf_token"] = "expected-token"
    resp = c.post("/login", data={"username": "x", "password": "y"})
    assert resp.status_code == 403


def test_csrf_wrong_token_on_auth_post_aborts_403(isolated_dbs):
    """POST to auth blueprint with wrong CSRF token → 403."""
    app = _csrf_app(isolated_dbs)
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["_csrf_token"] = "expected-token"
    resp = c.post(
        "/login",
        data={"username": "x", "password": "y", "csrf_token": "wrong-token"},
    )
    assert resp.status_code == 403


def test_csrf_valid_token_on_auth_post_proceeds(isolated_dbs):
    """POST to auth blueprint with correct CSRF token is not blocked."""
    app = _csrf_app(isolated_dbs)
    _add_user("alice")
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["_csrf_token"] = "good-token"
    resp = c.post(
        "/login",
        data={
            "username": "alice",
            "password": "Password1!",
            "csrf_token": "good-token",
        },
    )
    # Successful login → redirect to /
    assert resp.status_code == 302
    assert resp.location in ("/", "http://localhost/")


def test_csrf_head_request_passes_through(isolated_dbs):
    """HEAD requests are exempt from CSRF (included in the GET/HEAD/OPTIONS/TRACE group)."""
    app = _csrf_app(isolated_dbs)
    c = app.test_client()
    resp = c.head("/login")
    assert resp.status_code in (200, 405)  # either fine, not 403
