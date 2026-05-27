"""
minimost.presence
=================

Real-time presence tracking, typing indicators, read receipts, message
reactions, and private channel membership — all backed by the shared
``presence.db`` SQLite database.

This module manages all **transient shared state** in MiniMost.  Because
MiniMost stores per-user message history in individual SQLite files, a
separate shared database is needed for data that all users must see
simultaneously: who is typing, who is online, who has read a message,
what reactions a message has received, and which users belong to each
private channel.

**``presence.db`` tables:**

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Table
     - Purpose
   * - ``presence``
     - One row per user: ``last_seen`` (epoch) and ``state`` (active/idle/
       hidden/offline).  Updated on every presence heartbeat.
   * - ``typing``
     - One row per (user, channel) pair.  Timestamp is updated on each
       keystroke.  Rows older than 5 s are considered stale.
   * - ``read_receipts``
     - Permanent record of (channel, msg_ts, reader) triples written when a
       user calls ``/mark_read/<channel>``.
   * - ``message_reactions``
     - One row per (channel, msg_ts, emoji, reactor) combination.  Toggled
       atomically by ``/react/<msg_id>``.
   * - ``private_channels``
     - One row per private channel: ``name``, ``created_by``, and
       ``created_ts``.  The auto-increment ``id`` forms the channel
       identifier used throughout the app (``"private:<id>"``).
   * - ``private_channel_members``
     - One row per (channel_id, username) pair.  Records ``joined_ts`` and
       ``history_start_ts`` (the timestamp from which a member can see
       messages; ``NULL`` means from the beginning of the channel).

The tables are created at module import time by :func:`_init_tables`.

Module-level attributes
-----------------------
presence_bp : flask.Blueprint
    The Flask Blueprint for presence routes.  Registered in
    :func:`minimost.create_app`.

PRESENCE_DB : str
    Absolute path to the shared ``presence.db`` SQLite file.

_VALID_STATES : set of str
    Allowed presence state values: ``{"active", "idle", "hidden", "offline"}``.
"""

# From the python standard library
import time
import sqlite3
from pathlib import Path

# From Flask
from flask import session, request, Blueprint

presence_bp = Blueprint("presence", __name__)

_VALID_STATES = {"active", "idle", "hidden", "offline"}
_WAL = "PRAGMA journal_mode=WAL"

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent.parent
PRESENCE_DB = str(_PROJECT_ROOT / "presence.db")


def _init_tables():
    """Create all required tables in ``presence.db`` if they do not exist.

    Called unconditionally at module import time.  Uses
    ``CREATE TABLE IF NOT EXISTS`` throughout, so repeated calls are safe.

    **Tables created:**

    * ``presence`` — tracks each user's last-seen timestamp and state.
    * ``typing`` — records when a user was last observed typing in a channel.
    * ``read_receipts`` — permanent log of which users have read which
      messages.
    * ``message_reactions`` — stores each (channel, message, emoji, user)
      reaction tuple.
    * ``private_channels`` — one row per private channel with name, creator,
      and creation timestamp.
    * ``private_channel_members`` — one row per (channel_id, username) pair
      recording membership and join timestamp.

    :returns: None
    """
    db = sqlite3.connect(PRESENCE_DB)
    db.execute(_WAL)
    db.execute("""
        CREATE TABLE IF NOT EXISTS presence (
            user TEXT PRIMARY KEY,
            last_seen INTEGER NOT NULL,
            state TEXT NOT NULL
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS typing (
            user    TEXT NOT NULL,
            channel TEXT NOT NULL,
            ts      INTEGER NOT NULL,
            PRIMARY KEY (user, channel)
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS read_receipts (
            channel TEXT NOT NULL,
            msg_ts  REAL NOT NULL,
            reader  TEXT NOT NULL,
            PRIMARY KEY (channel, msg_ts, reader)
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS message_reactions (
            channel TEXT NOT NULL,
            msg_ts  REAL NOT NULL,
            emoji   TEXT NOT NULL,
            reactor TEXT NOT NULL,
            PRIMARY KEY (channel, msg_ts, emoji, reactor)
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS private_channels (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT NOT NULL,
            created_by TEXT NOT NULL,
            created_ts REAL NOT NULL
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS private_channel_members (
            channel_id       INTEGER NOT NULL,
            username         TEXT NOT NULL,
            joined_ts        REAL NOT NULL,
            history_start_ts REAL,
            PRIMARY KEY (channel_id, username),
            FOREIGN KEY (channel_id) REFERENCES private_channels(id)
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS calls (
            call_id     TEXT PRIMARY KEY,
            channel     TEXT NOT NULL,
            initiator   TEXT NOT NULL,
            state       TEXT NOT NULL DEFAULT 'ringing',
            started_ts  REAL NOT NULL,
            answered_ts REAL,
            ended_ts    REAL
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS call_participants (
            call_id   TEXT NOT NULL,
            username  TEXT NOT NULL,
            role      TEXT NOT NULL DEFAULT 'participant',
            state     TEXT NOT NULL DEFAULT 'pending',
            joined_ts REAL,
            left_ts   REAL,
            PRIMARY KEY (call_id, username),
            FOREIGN KEY (call_id) REFERENCES calls(call_id)
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS call_signals (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            call_id     TEXT NOT NULL,
            from_user   TEXT NOT NULL,
            to_user     TEXT NOT NULL,
            signal_type TEXT NOT NULL,
            payload     TEXT NOT NULL,
            ts          REAL NOT NULL
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS call_media (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            call_id   TEXT NOT NULL,
            sender    TEXT NOT NULL,
            is_init   INTEGER NOT NULL DEFAULT 0,
            mime_type TEXT,
            data      BLOB NOT NULL,
            ts        REAL NOT NULL
        )
    """)
    db.execute("""
        CREATE INDEX IF NOT EXISTS call_media_idx
            ON call_media (call_id, sender, is_init, id)
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS screenshares (
            share_id   TEXT PRIMARY KEY,
            channel    TEXT NOT NULL,
            sharer     TEXT NOT NULL,
            state      TEXT NOT NULL DEFAULT 'active',
            started_ts REAL NOT NULL,
            ended_ts   REAL
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS share_media (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            share_id  TEXT NOT NULL,
            is_init   INTEGER NOT NULL DEFAULT 0,
            mime_type TEXT,
            data      BLOB NOT NULL,
            ts        REAL NOT NULL
        )
    """)
    db.execute("""
        CREATE INDEX IF NOT EXISTS share_media_idx
            ON share_media (share_id, is_init, id)
    """)
    db.commit()
    db.close()


_init_tables()


@presence_bp.route("/typing/<channel>", methods=["POST"])
def typing_start(channel):
    """Record that the current user is typing in a channel.

    Route: ``POST /typing/<channel>``

    Does **not** require the ``@login_required`` decorator — if the session
    is missing, the request is silently dropped (``204 No Content``) rather
    than redirecting to the login page.  This avoids a redirect loop when the
    client sends typing notifications for a brief period after a session
    expiry.

    The timestamp is written to the ``typing`` table using
    ``INSERT OR REPLACE``, so the row for ``(user, channel)`` is updated in
    place on each call.

    :param channel: The channel name or DM identifier.
    :type channel: str
    :returns: Empty body with HTTP 204 No Content.
    :rtype: flask.Response
    """
    user = session.get("user")
    if user:
        now = int(time.time())
        db = sqlite3.connect(PRESENCE_DB)
        db.execute(_WAL)
        db.execute(
            "INSERT OR REPLACE INTO typing (user, channel, ts) VALUES (?, ?, ?)",
            (user, channel, now),
        )
        db.commit()
        db.close()
    return "", 204


@presence_bp.route("/typing/<channel>", methods=["GET"])
def typing_get(channel):
    """Return the list of users currently typing in a channel.

    Route: ``GET /typing/<channel>``

    A user is considered to be "currently typing" if their ``ts`` in the
    ``typing`` table is within the last **5 seconds**.  The current user is
    excluded from the result so they never see their own typing indicator.

    The client polls this endpoint every second and displays a
    ``"<user> is typing…"`` banner in the chat area.

    :param channel: The channel name or DM identifier.
    :type channel: str
    :returns: JSON array of usernames who are currently typing,
        e.g. ``["alice", "bob"]``.  Returns ``[]`` if the session is
        missing or no one is typing.
    :rtype: flask.Response (application/json)
    """
    user = session.get("user")
    if not user:
        return []
    cutoff = int(time.time()) - 5
    db = sqlite3.connect(PRESENCE_DB)
    db.execute(_WAL)
    rows = db.execute(
        "SELECT user FROM typing WHERE channel = ? AND ts >= ? AND user != ?",
        (channel, cutoff, user),
    ).fetchall()
    db.close()
    return [r[0] for r in rows]


@presence_bp.route("/presence", methods=["POST"])
def presence():
    """Update the current user's presence state.

    Route: ``POST /presence``

    Accepts a JSON body with a ``state`` key.  Valid values are defined by
    :data:`_VALID_STATES`: ``"active"``, ``"idle"``, ``"hidden"``,
    ``"offline"``.

    The client sends this request:

    * Immediately when the page's ``visibilitychange`` event fires
      (``"hidden"`` when the tab goes to the background,
      ``"active"`` when it returns).
    * After detecting 5 minutes of keyboard/mouse inactivity (``"idle"``).
    * On a 30-second heartbeat to keep ``last_seen`` fresh.

    Silently returns ``204`` if the session is missing or the state is
    invalid.

    Request body (JSON):
        **state** (str): One of ``"active"``, ``"idle"``, ``"hidden"``,
        ``"offline"``.

    :returns: Empty body with HTTP 204 No Content.
    :rtype: flask.Response
    """
    user = session.get("user")
    if user:
        data = request.get_json(silent=True) or {}
        state = data.get("state")
        update_presence(user, state)
    return "", 204


def reset_all_offline() -> None:
    """Set every user's presence state to ``"offline"`` in ``presence.db``.

    Called once at application startup so that stale presence records from a
    previous server run (e.g. users who were ``"active"`` or ``"hidden"`` when
    the server was stopped) do not mislead other users.

    :returns: None
    """
    db = sqlite3.connect(PRESENCE_DB)
    db.execute(_WAL)
    db.execute("UPDATE presence SET state = 'offline'")
    db.commit()
    db.close()


def update_presence(user: str, state) -> None:
    """Write a presence record directly to ``presence.db``.

    This function is the shared implementation used by both the
    ``/presence`` HTTP route and the :func:`minimost.auth.logout` view
    (which sets the user's state to ``"offline"`` before clearing the
    session).

    If *state* is not in :data:`_VALID_STATES` the function returns
    immediately without writing anything.

    :param user: The username whose presence should be updated.
    :type user: str
    :param state: New presence state — one of ``"active"``, ``"idle"``,
        ``"hidden"``, ``"offline"``.
    :type state: str
    :returns: None
    """
    if state not in _VALID_STATES:
        return
    now = int(time.time())
    db = sqlite3.connect(PRESENCE_DB)
    db.execute(_WAL)
    db.execute(
        "INSERT OR REPLACE INTO presence (user, last_seen, state) VALUES (?, ?, ?)",
        (user, now, state),
    )
    db.commit()
    db.close()
