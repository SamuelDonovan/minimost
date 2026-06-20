"""Tests for the Server-Sent Events push stream (``minimost.events``)."""

import sqlite3
import time

import pytest


@pytest.fixture
def fast_stream(monkeypatch):
    """Make /events terminate almost immediately so a test can read its body.

    The stream normally runs for five minutes; here we cap it well under a
    second and shorten the tick so the whole response can be consumed by the
    test client without blocking.
    """
    import minimost.events as events

    monkeypatch.setattr(events, "_MAX_STREAM_SECONDS", 0.4)
    monkeypatch.setattr(events, "_TICK_SECONDS", 0.02)
    monkeypatch.setattr(events, "_KEEPALIVE_SECONDS", 0.05)
    return events


def _insert_message(channel, sender, content):
    from minimost.common import init_messages_db, shared_db_path

    init_messages_db()
    db = sqlite3.connect(str(shared_db_path()))
    db.execute("PRAGMA journal_mode=WAL")
    db.execute(
        "INSERT INTO messages (channel, sender, content, content_type, ts)"
        " VALUES (?, ?, ?, ?, ?)",
        (channel, sender, content, "", time.time()),
    )
    db.commit()
    db.close()


def test_events_requires_auth(client):
    """An unauthenticated request is redirected to the login page."""
    resp = client.get("/events")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_events_is_an_event_stream(alice, fast_stream):
    """The endpoint advertises text/event-stream and a reconnect interval."""
    resp = alice.get("/events?channel=general&after=0")
    assert resp.status_code == 200
    assert resp.mimetype == "text/event-stream"
    body = resp.get_data(as_text=True)
    assert "retry: 3000" in body


def test_events_emits_initial_global_state(alice, fast_stream):
    """Global collectors fire on the first tick even with no channel activity."""
    body = alice.get("/events?channel=general&after=0").get_data(as_text=True)
    # Sidebar/presence state is pushed without the client asking for each piece.
    assert "event: online_users" in body
    assert "event: unread_count" in body
    assert "event: dms" in body


def test_events_pushes_new_channel_message(alice, fast_stream):
    """A message already in the channel is delivered as a ``messages`` event."""
    _insert_message("general", "bob", "hello over sse")
    body = alice.get("/events?channel=general&after=0").get_data(as_text=True)
    assert "event: messages" in body
    assert "hello over sse" in body
    # The messages frame carries an ``id:`` so an auto-reconnect can resume.
    assert "id: " in body


def test_events_resumes_from_last_event_id(alice, fast_stream):
    """A future ``Last-Event-ID`` header suppresses the backlog on reconnect.

    The browser echoes the last id it saw when EventSource auto-reconnects;
    the server must resume from that cursor rather than replay history.
    """
    _insert_message("general", "bob", "replay me")
    body = alice.get(
        "/events?channel=general&after=0",
        headers={"Last-Event-ID": repr(time.time() + 10_000)},
    ).get_data(as_text=True)
    assert "replay me" not in body


def test_events_message_cursor_excludes_old_rows(alice, fast_stream):
    """``after`` in the future suppresses the backlog (only newer rows stream)."""
    _insert_message("general", "bob", "ancient history")
    future = time.time() + 10_000
    body = alice.get(f"/events?channel=general&after={future}").get_data(as_text=True)
    assert "ancient history" not in body


def test_events_without_channel_still_streams_globals(alice, fast_stream):
    """A stream opened with no channel skips channel collectors but not globals."""
    body = alice.get("/events").get_data(as_text=True)
    assert "event: online_users" in body
    # No channel → no messages/typing/read_receipts frames.
    assert "event: messages" not in body
    assert "event: typing" not in body


# ── Change counter (write-gating) ─────────────────────────────────────────────


def test_event_signal_bump_and_read():
    """The shared change counter increments monotonically on each bump."""
    import minimost.presence as presence

    before = presence.read_event_signal()
    presence.bump_event_signal()
    assert presence.read_event_signal() == before + 1


def test_state_changing_post_bumps_signal(alice):
    """A successful POST to a data blueprint wakes streams via the counter."""
    import minimost.presence as presence

    before = presence.read_event_signal()
    resp = alice.post("/presence", json={"state": "active"})
    assert resp.status_code < 400
    assert presence.read_event_signal() > before


def test_read_only_get_does_not_bump_signal(alice):
    """A GET must not bump the counter — only state changes should wake streams."""
    import minimost.presence as presence

    before = presence.read_event_signal()
    alice.get("/online_users")
    assert presence.read_event_signal() == before
