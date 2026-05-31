"""Tests for private channel routes and helpers.

Covers:
  POST /private_channels/create
  GET  /private_channels
  POST /private_channels/<id>/rename
  POST /private_channels/<id>/add_member
  GET  /private_channels/<id>/members
  Helper: get_private_channel_members
  Helper: channel_users (private branch)
  Helper: is_valid_channel (private branch)
  Integration: POST /send/private:<id>
"""

import json
import sqlite3
import time

from werkzeug.security import generate_password_hash

import minimost.auth as auth_mod
import minimost.chat as chat_mod
import minimost.common as common_mod
import minimost.presence as presence_mod

# ── Helpers ───────────────────────────────────────────────────────────────────


def _add_user(username, password="Password1!"):
    """Register a user in auth.db and create their message DB."""
    db = sqlite3.connect(auth_mod.AUTH_DB)
    db.execute(
        "INSERT INTO users (username, password_hash) VALUES (?, ?)",
        (username, generate_password_hash(password)),
    )
    db.commit()
    db.close()
    common_mod.init_user_db(username)


def _make_bob_client(app):
    """Return an authenticated test client for bob (must already be registered)."""
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["user"] = "bob"
    return c


def _create_channel(client, name, members=None):
    """POST /private_channels/create and return parsed JSON."""
    payload = {"name": name}
    if members is not None:
        payload["members"] = members
    resp = client.post(
        "/private_channels/create",
        data=json.dumps(payload),
        content_type="application/json",
    )
    return resp


def _get_pdb_members(channel_id):
    """Read private_channel_members rows directly from presence.db."""
    pdb = sqlite3.connect(presence_mod.PRESENCE_DB)
    rows = pdb.execute(
        "SELECT username FROM private_channel_members WHERE channel_id=?",
        (channel_id,),
    ).fetchall()
    pdb.close()
    return [r[0] for r in rows]


def _get_user_messages(username, channel):
    """Return all messages for a user in a channel from their DB."""
    db = sqlite3.connect(str(common_mod.user_db_path(username)))
    rows = db.execute(
        "SELECT sender, content, content_type FROM messages WHERE channel=?",
        (channel,),
    ).fetchall()
    db.close()
    return rows


# ── POST /private_channels/create ────────────────────────────────────────────


def test_create_private_channel_unauthenticated(client):
    resp = _create_channel(client, "secret")
    assert resp.status_code == 302
    assert "/login" in resp.location


def test_create_private_channel_success(alice):
    resp = _create_channel(alice, "my-channel")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["name"] == "my-channel"
    assert "id" in data
    assert data["channel"] == f"private:{data['id']}"


def test_create_private_channel_no_name(alice):
    resp = _create_channel(alice, "")
    assert resp.status_code == 400


def test_create_private_channel_no_name_whitespace(alice):
    resp = client_post_json(alice, "/private_channels/create", {"name": "   "})
    assert resp.status_code == 400


def test_create_private_channel_creator_always_added(alice):
    """Creator must appear in members even when not in the members list."""
    resp = _create_channel(alice, "team", members=[])
    assert resp.status_code == 200
    channel_id = resp.get_json()["id"]
    members = _get_pdb_members(channel_id)
    assert "alice" in members


def test_create_private_channel_with_members(alice_and_bob):
    resp = _create_channel(alice_and_bob, "squad", members=["bob"])
    assert resp.status_code == 200
    channel_id = resp.get_json()["id"]
    members = _get_pdb_members(channel_id)
    assert "alice" in members
    assert "bob" in members


def test_create_private_channel_creator_not_duplicated(alice):
    """Creator listed in members should not appear twice."""
    resp = _create_channel(alice, "solo", members=["alice"])
    assert resp.status_code == 200
    channel_id = resp.get_json()["id"]
    members = _get_pdb_members(channel_id)
    assert members.count("alice") == 1


def test_create_private_channel_returns_correct_channel_string(alice):
    resp = _create_channel(alice, "cstring")
    data = resp.get_json()
    assert data["channel"] == f"private:{data['id']}"


def test_create_private_channel_no_json_body(alice):
    """Missing body should trigger a 400 because name is absent."""
    resp = alice.post("/private_channels/create", content_type="application/json")
    assert resp.status_code == 400


# ── GET /private_channels ─────────────────────────────────────────────────────


def test_list_private_channels_unauthenticated(client):
    resp = client.get("/private_channels")
    assert resp.status_code == 302


def test_list_private_channels_empty(alice):
    resp = alice.get("/private_channels")
    assert resp.status_code == 200
    assert resp.get_json() == []


def test_list_private_channels_shows_members_channel(alice):
    _create_channel(alice, "visible")
    data = alice.get("/private_channels").get_json()
    assert len(data) == 1
    assert data[0]["name"] == "visible"


def test_list_private_channels_hides_other_channels(alice_and_bob, app):
    """Channels alice is not a member of must not appear in her list."""
    _add_user("charlie")
    charlie = app.test_client()
    with charlie.session_transaction() as sess:
        sess["user"] = "charlie"
    _create_channel(charlie, "charlies-private")

    data = alice_and_bob.get("/private_channels").get_json()
    names = [ch["name"] for ch in data]
    assert "charlies-private" not in names


def test_list_private_channels_response_shape(alice):
    _create_channel(alice, "shaped")
    data = alice.get("/private_channels").get_json()
    ch = data[0]
    assert "id" in ch
    assert "channel" in ch
    assert "name" in ch
    assert "unread" in ch
    assert "members" in ch


def test_list_private_channels_unread_zero_initially(alice):
    _create_channel(alice, "fresh")
    data = alice.get("/private_channels").get_json()
    assert data[0]["unread"] == 0


def test_list_private_channels_unread_count(alice_and_bob):
    """Unread count reflects messages from others with read=0, deleted=0."""
    resp = _create_channel(alice_and_bob, "chatroom", members=["bob"])
    channel_id = resp.get_json()["id"]
    ch = f"private:{channel_id}"

    # Insert an unread message from bob into alice's DB
    db = sqlite3.connect(str(common_mod.user_db_path("alice")))
    db.execute(
        "INSERT INTO messages (channel, sender, content, ts, read) VALUES (?,?,?,?,0)",
        (ch, "bob", "hey alice", time.time()),
    )
    db.commit()
    db.close()

    data = alice_and_bob.get("/private_channels").get_json()
    alice_ch = next(c for c in data if c["id"] == channel_id)
    assert alice_ch["unread"] == 1


def test_list_private_channels_own_messages_not_counted_as_unread(alice):
    """Alice's own messages in her DB should not inflate her unread count."""
    resp = _create_channel(alice, "self-chat")
    channel_id = resp.get_json()["id"]
    ch = f"private:{channel_id}"

    db = sqlite3.connect(str(common_mod.user_db_path("alice")))
    db.execute(
        "INSERT INTO messages (channel, sender, content, ts, read) VALUES (?,?,?,?,0)",
        (ch, "alice", "my own msg", time.time()),
    )
    db.commit()
    db.close()

    data = alice.get("/private_channels").get_json()
    alice_ch = next(c for c in data if c["id"] == channel_id)
    assert alice_ch["unread"] == 0


def test_list_private_channels_deleted_messages_not_counted(alice_and_bob):
    """Deleted messages must not increase the unread count."""
    resp = _create_channel(alice_and_bob, "delroom", members=["bob"])
    channel_id = resp.get_json()["id"]
    ch = f"private:{channel_id}"

    db = sqlite3.connect(str(common_mod.user_db_path("alice")))
    db.execute(
        "INSERT INTO messages (channel, sender, content, ts, read, deleted) VALUES (?,?,?,?,0,1)",
        (ch, "bob", "deleted msg", time.time()),
    )
    db.commit()
    db.close()

    data = alice_and_bob.get("/private_channels").get_json()
    alice_ch = next(c for c in data if c["id"] == channel_id)
    assert alice_ch["unread"] == 0


def test_list_private_channels_members_field(alice_and_bob):
    resp = _create_channel(alice_and_bob, "withbob", members=["bob"])
    channel_id = resp.get_json()["id"]
    data = alice_and_bob.get("/private_channels").get_json()
    ch = next(c for c in data if c["id"] == channel_id)
    assert "alice" in ch["members"]
    assert "bob" in ch["members"]


# ── POST /private_channels/<id>/rename ───────────────────────────────────────


def test_rename_private_channel_unauthenticated(client):
    resp = client_post_json(client, "/private_channels/1/rename", {"name": "new"})
    assert resp.status_code == 302


def test_rename_private_channel_success(alice):
    channel_id = _create_channel(alice, "oldname").get_json()["id"]
    resp = client_post_json(
        alice, f"/private_channels/{channel_id}/rename", {"name": "newname"}
    )
    assert resp.status_code == 200
    assert resp.data == b"ok"


def test_rename_private_channel_reflected_in_list(alice):
    channel_id = _create_channel(alice, "before").get_json()["id"]
    client_post_json(alice, f"/private_channels/{channel_id}/rename", {"name": "after"})
    data = alice.get("/private_channels").get_json()
    ch = next(c for c in data if c["id"] == channel_id)
    assert ch["name"] == "after"


def test_rename_private_channel_forbidden_non_member(alice_and_bob, app):
    """Non-member must receive 403."""
    channel_id = _create_channel(alice_and_bob, "alicechan").get_json()["id"]
    _add_user("charlie")
    charlie = app.test_client()
    with charlie.session_transaction() as sess:
        sess["user"] = "charlie"
    resp = client_post_json(
        charlie, f"/private_channels/{channel_id}/rename", {"name": "hack"}
    )
    assert resp.status_code == 403


def test_rename_private_channel_empty_name(alice):
    channel_id = _create_channel(alice, "notempty").get_json()["id"]
    resp = client_post_json(
        alice, f"/private_channels/{channel_id}/rename", {"name": ""}
    )
    assert resp.status_code == 400


def test_rename_private_channel_whitespace_name(alice):
    channel_id = _create_channel(alice, "notempty2").get_json()["id"]
    resp = client_post_json(
        alice, f"/private_channels/{channel_id}/rename", {"name": "   "}
    )
    assert resp.status_code == 400


def test_rename_private_channel_member_can_rename(alice_and_bob):
    """Any member (not just creator) should be able to rename."""
    channel_id = _create_channel(alice_and_bob, "shared", members=["bob"]).get_json()[
        "id"
    ]
    bob = _make_bob_client(alice_and_bob.application)
    resp = client_post_json(
        bob, f"/private_channels/{channel_id}/rename", {"name": "renamed-by-bob"}
    )
    assert resp.status_code == 200


# ── POST /private_channels/<id>/add_member ────────────────────────────────────


def test_add_member_unauthenticated(client):
    resp = client_post_json(
        client, "/private_channels/1/add_member", {"username": "bob"}
    )
    assert resp.status_code == 302


def test_add_member_success(alice_and_bob):
    channel_id = _create_channel(alice_and_bob, "growable").get_json()["id"]
    resp = client_post_json(
        alice_and_bob, f"/private_channels/{channel_id}/add_member", {"username": "bob"}
    )
    assert resp.status_code == 200
    assert resp.data == b"ok"


def test_add_member_appears_in_members(alice_and_bob):
    channel_id = _create_channel(alice_and_bob, "growing").get_json()["id"]
    client_post_json(
        alice_and_bob, f"/private_channels/{channel_id}/add_member", {"username": "bob"}
    )
    members = _get_pdb_members(channel_id)
    assert "bob" in members


def test_add_member_forbidden_non_member(alice_and_bob, app):
    channel_id = _create_channel(alice_and_bob, "restricted").get_json()["id"]
    _add_user("charlie")
    charlie = app.test_client()
    with charlie.session_transaction() as sess:
        sess["user"] = "charlie"
    resp = client_post_json(
        charlie, f"/private_channels/{channel_id}/add_member", {"username": "alice"}
    )
    assert resp.status_code == 403


def test_add_member_empty_username(alice):
    channel_id = _create_channel(alice, "nouserchan").get_json()["id"]
    resp = client_post_json(
        alice, f"/private_channels/{channel_id}/add_member", {"username": ""}
    )
    assert resp.status_code == 400


def test_add_member_user_not_found(alice):
    channel_id = _create_channel(alice, "ghostchan").get_json()["id"]
    resp = client_post_json(
        alice,
        f"/private_channels/{channel_id}/add_member",
        {"username": "doesnotexist"},
    )
    assert resp.status_code == 404


def test_add_member_already_member(alice_and_bob):
    channel_id = _create_channel(alice_and_bob, "dupechan", members=["bob"]).get_json()[
        "id"
    ]
    resp = client_post_json(
        alice_and_bob, f"/private_channels/{channel_id}/add_member", {"username": "bob"}
    )
    assert resp.status_code == 409


def test_add_member_system_message_sent_to_all_members(alice_and_bob):
    """System message must land in every member's DB (including the new member)."""
    channel_id = _create_channel(alice_and_bob, "announce").get_json()["id"]
    _add_user("charlie")
    ch = f"private:{channel_id}"

    client_post_json(
        alice_and_bob,
        f"/private_channels/{channel_id}/add_member",
        {"username": "charlie"},
    )

    expected_content = "alice added charlie to this channel"
    for username in ("alice", "charlie"):
        rows = _get_user_messages(username, ch)
        system_msgs = [r for r in rows if r[2] == "system"]
        assert any(
            r[1] == expected_content for r in system_msgs
        ), f"system message missing from {username}'s DB"


def test_add_member_system_message_content_type(alice_and_bob):
    """System messages must have content_type='system'."""
    channel_id = _create_channel(alice_and_bob, "syscheck").get_json()["id"]
    _add_user("dave")
    ch = f"private:{channel_id}"

    client_post_json(
        alice_and_bob,
        f"/private_channels/{channel_id}/add_member",
        {"username": "dave"},
    )

    rows = _get_user_messages("alice", ch)
    assert any(r[2] == "system" for r in rows)


def test_add_member_new_member_can_receive_messages(alice_and_bob):
    """After being added, the new member should appear in channel_users."""
    channel_id = _create_channel(alice_and_bob, "livetest").get_json()["id"]
    _add_user("eve")
    client_post_json(
        alice_and_bob, f"/private_channels/{channel_id}/add_member", {"username": "eve"}
    )
    ch = f"private:{channel_id}"
    users = chat_mod.channel_users(ch)
    assert "eve" in users


def test_add_member_no_json_body(alice):
    channel_id = _create_channel(alice, "nojson").get_json()["id"]
    resp = alice.post(
        f"/private_channels/{channel_id}/add_member",
        content_type="application/json",
    )
    assert resp.status_code == 400


# ── GET /private_channels/<id>/members ───────────────────────────────────────


def test_members_route_unauthenticated(client):
    resp = client.get("/private_channels/1/members")
    assert resp.status_code == 302


def test_members_route_success(alice):
    channel_id = _create_channel(alice, "memberstest").get_json()["id"]
    resp = alice.get(f"/private_channels/{channel_id}/members")
    assert resp.status_code == 200
    data = resp.get_json()
    assert isinstance(data, list)
    usernames = [m["username"] for m in data]
    assert "alice" in usernames


def test_members_route_response_shape(alice):
    channel_id = _create_channel(alice, "shapedmembers").get_json()["id"]
    data = alice.get(f"/private_channels/{channel_id}/members").get_json()
    assert all("username" in m for m in data)


def test_members_route_forbidden_non_member(alice_and_bob, app):
    channel_id = _create_channel(alice_and_bob, "private").get_json()["id"]
    _add_user("charlie")
    charlie = app.test_client()
    with charlie.session_transaction() as sess:
        sess["user"] = "charlie"
    resp = charlie.get(f"/private_channels/{channel_id}/members")
    assert resp.status_code == 403


def test_members_route_shows_all_members(alice_and_bob):
    channel_id = _create_channel(alice_and_bob, "bothhere", members=["bob"]).get_json()[
        "id"
    ]
    data = alice_and_bob.get(f"/private_channels/{channel_id}/members").get_json()
    usernames = [m["username"] for m in data]
    assert "alice" in usernames
    assert "bob" in usernames


def test_members_route_after_add(alice_and_bob):
    """New member must appear in /members after add_member succeeds."""
    channel_id = _create_channel(alice_and_bob, "addthencheck").get_json()["id"]
    _add_user("frank")
    client_post_json(
        alice_and_bob,
        f"/private_channels/{channel_id}/add_member",
        {"username": "frank"},
    )
    data = alice_and_bob.get(f"/private_channels/{channel_id}/members").get_json()
    usernames = [m["username"] for m in data]
    assert "frank" in usernames


# ── Helper: get_private_channel_members ──────────────────────────────────────


def test_get_private_channel_members_returns_list(alice):
    channel_id = _create_channel(alice, "helper-test").get_json()["id"]
    members = chat_mod.get_private_channel_members(channel_id)
    assert isinstance(members, list)
    assert "alice" in members


def test_get_private_channel_members_empty_for_unknown_id():
    members = chat_mod.get_private_channel_members(999999)
    assert members == []


def test_get_private_channel_members_multiple(alice_and_bob):
    channel_id = _create_channel(alice_and_bob, "multi", members=["bob"]).get_json()[
        "id"
    ]
    members = chat_mod.get_private_channel_members(channel_id)
    assert set(members) == {"alice", "bob"}


# ── Helper: channel_users (private branch) ───────────────────────────────────


def test_channel_users_private_returns_members(alice_and_bob):
    channel_id = _create_channel(alice_and_bob, "cu-test", members=["bob"]).get_json()[
        "id"
    ]
    users = chat_mod.channel_users(f"private:{channel_id}")
    assert "alice" in users
    assert "bob" in users


def test_channel_users_private_unknown_id():
    users = chat_mod.channel_users("private:999999")
    assert users == []


def test_channel_users_private_malformed_id():
    users = chat_mod.channel_users("private:notanint")
    assert users == []


def test_channel_users_private_missing_id():
    """'private:' with no trailing segment should not crash."""
    users = chat_mod.channel_users("private:")
    assert users == []


# ── Helper: is_valid_channel (private branch) ────────────────────────────────


def test_is_valid_channel_private_member(alice):
    channel_id = _create_channel(alice, "valid-priv").get_json()["id"]
    assert chat_mod.is_valid_channel(f"private:{channel_id}", "alice") is True


def test_is_valid_channel_private_non_member(alice_and_bob):
    channel_id = _create_channel(alice_and_bob, "nonmember-priv").get_json()["id"]
    _add_user("charlie")
    assert chat_mod.is_valid_channel(f"private:{channel_id}", "charlie") is False


def test_is_valid_channel_private_unknown_id():
    assert chat_mod.is_valid_channel("private:999999", "alice") is False


def test_is_valid_channel_private_malformed_id():
    assert chat_mod.is_valid_channel("private:notanint", "alice") is False


def test_is_valid_channel_private_missing_id():
    assert chat_mod.is_valid_channel("private:", "alice") is False


# ── Integration: POST /send/private:<id> ─────────────────────────────────────


def test_send_private_channel_member_succeeds(alice_and_bob):
    channel_id = _create_channel(alice_and_bob, "sendchan", members=["bob"]).get_json()[
        "id"
    ]
    resp = alice_and_bob.post(
        f"/send/private:{channel_id}", data={"text": "hello private"}
    )
    assert resp.status_code == 200


def test_send_private_channel_non_member_forbidden(alice_and_bob, app):
    channel_id = _create_channel(alice_and_bob, "alicechan2").get_json()["id"]
    _add_user("charlie")
    charlie = app.test_client()
    with charlie.session_transaction() as sess:
        sess["user"] = "charlie"
    resp = charlie.post(f"/send/private:{channel_id}", data={"text": "hack"})
    assert resp.status_code == 403


def test_send_private_channel_stored_in_member_db(alice_and_bob):
    channel_id = _create_channel(
        alice_and_bob, "storechan", members=["bob"]
    ).get_json()["id"]
    ch = f"private:{channel_id}"
    alice_and_bob.post(f"/send/{ch}", data={"text": "stored message"})
    rows = _get_user_messages("alice", ch)
    assert any(r[1] == "stored message" for r in rows)


def test_send_private_channel_propagates_to_all_members(alice_and_bob):
    channel_id = _create_channel(
        alice_and_bob, "broadcast", members=["bob"]
    ).get_json()["id"]
    ch = f"private:{channel_id}"
    alice_and_bob.post(f"/send/{ch}", data={"text": "broadcast msg"})
    bob_rows = _get_user_messages("bob", ch)
    assert any(r[1] == "broadcast msg" for r in bob_rows)


def test_send_private_channel_new_member_receives_messages(alice_and_bob):
    """After being added, the new member's DB is in channel_users so future /send works."""
    channel_id = _create_channel(alice_and_bob, "postjoin", members=["bob"]).get_json()[
        "id"
    ]
    _add_user("grace")
    ch = f"private:{channel_id}"

    client_post_json(
        alice_and_bob,
        f"/private_channels/{channel_id}/add_member",
        {"username": "grace"},
    )

    alice_and_bob.post(f"/send/{ch}", data={"text": "welcome grace"})

    grace_rows = _get_user_messages("grace", ch)
    # The system message + the welcome message should both be there
    text_msgs = [r for r in grace_rows if r[2] != "system"]
    assert any(r[1] == "welcome grace" for r in text_msgs)


# ── Edge cases ────────────────────────────────────────────────────────────────


def test_create_multiple_channels_independent(alice):
    id1 = _create_channel(alice, "ch-one").get_json()["id"]
    id2 = _create_channel(alice, "ch-two").get_json()["id"]
    assert id1 != id2
    data = alice.get("/private_channels").get_json()
    assert len(data) == 2


def test_rename_does_not_affect_other_channels(alice):
    id1 = _create_channel(alice, "stable").get_json()["id"]
    id2 = _create_channel(alice, "tochange").get_json()["id"]
    client_post_json(alice, f"/private_channels/{id2}/rename", {"name": "changed"})
    data = alice.get("/private_channels").get_json()
    stable = next(c for c in data if c["id"] == id1)
    assert stable["name"] == "stable"


def test_list_channels_ordered_by_id(alice):
    for name in ("alpha", "beta", "gamma"):
        _create_channel(alice, name)
    data = alice.get("/private_channels").get_json()
    ids = [c["id"] for c in data]
    assert ids == sorted(ids)


# ── Internal utility used by tests ───────────────────────────────────────────


def client_post_json(c, path, payload):
    """POST *path* with a JSON body using test client *c*."""
    return c.post(
        path,
        data=json.dumps(payload),
        content_type="application/json",
    )


# ── Name length validation ────────────────────────────────────────────────────


def test_create_private_channel_name_too_long(alice):
    import minimost.chat as chat_mod

    long_name = "x" * (chat_mod.MAX_CHANNEL_NAME_LEN + 1)
    resp = _create_channel(alice, long_name)
    assert resp.status_code == 400


def test_rename_private_channel_name_too_long(alice):
    import minimost.chat as chat_mod

    channel_id = _create_channel(alice, "valid").get_json()["id"]
    long_name = "x" * (chat_mod.MAX_CHANNEL_NAME_LEN + 1)
    resp = client_post_json(
        alice, f"/private_channels/{channel_id}/rename", {"name": long_name}
    )
    assert resp.status_code == 400
