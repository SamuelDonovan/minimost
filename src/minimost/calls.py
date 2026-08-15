"""
minimost.calls
==============

Voice/video calling over WebRTC, with the call lifecycle and signaling in SQLite.

All call state lives in the shared ``presence.db``.  Three tables (created
by :func:`init_calls_tables`, called from :func:`minimost.presence._init_tables`)
store the lifecycle of every call:

* ``calls`` — one row per call: channel, initiator, lifecycle state, and
  timestamps.
* ``call_participants`` — one row per (call_id, username): role, acceptance
  state, and join/leave timestamps.  Designed to support future group calls
  without schema changes.
* ``call_signals`` — WebRTC signaling relay: offer/answer/ICE-candidate
  messages exchanged between participants during peer-connection setup.

Media travels **peer-to-peer over WebRTC** (``RTCPeerConnection``).  Flask's
role is limited to the call lifecycle state machine (the ``calls`` and
``call_participants`` tables) and to relaying signaling messages via
``POST /calls/<id>/signal`` / ``GET /calls/<id>/signals``.  Because the app
is LAN-only, ICE relies on host candidates with no STUN/TURN servers.

Module-level attributes
-----------------------
calls_bp : flask.Blueprint
    The Flask Blueprint for all call routes.  Registered in
    :func:`minimost.create_app`.
"""

import json
import sqlite3
import time
import uuid

from flask import Blueprint, jsonify, request, session

from . import auth
from . import presence as presence_mod

calls_bp = Blueprint("calls", __name__)

_WAL = "PRAGMA journal_mode=WAL"
_INCREMENTAL_VACUUM = "PRAGMA incremental_vacuum"
_RINGING_TIMEOUT = 30

# How long a participant's presence heartbeat may go quiet before we stop
# believing they are still on a call.  The client heartbeats every 30s, but
# browsers throttle timers hard in backgrounded tabs, so this is deliberately
# several missed beats rather than one.
_PRESENCE_STALE = 120

# How long a participant's *in-call* heartbeat may go quiet before the same
# applies.  Presence alone is not enough: it keeps ticking from any open tab, so
# a browser that navigated away from the call — or crashed the page but not the
# process — still looks alive by presence while nobody is on the call at all.
# The state poll every client runs every 3s while it is in a call is the signal
# that actually tracks call membership; twenty missed polls is the threshold.
_CALL_HEARTBEAT_STALE = 60

# How quiet a participant must have gone before another participant's report
# that they have vanished is acted on (see ``/calls/<id>/gone``).  Comfortably
# longer than the 3s state poll, so a live participant is never evicted, and
# far shorter than :data:`_CALL_HEARTBEAT_STALE`, which is what the server
# falls back on when nobody is left to report anything.
_GONE_CORROBORATION = 12

# An accepted participant whose in-call heartbeat is still fresh.
# ``last_seen_ts`` falls back to ``joined_ts`` for rows written before the
# column existed, so an upgraded database does not evict everybody at once.
_SQL_LIVE_ACCEPTED = (
    " p.state = 'accepted' AND COALESCE(p.last_seen_ts, p.joined_ts, 0) >= ?"
)
# The sweep is the last resort — it ends a call outright — so it asks for both
# heartbeats before deciding somebody is gone.
_SQL_LIVE_PARTICIPANT = _SQL_LIVE_ACCEPTED + " AND COALESCE(pr.last_seen, 0) >= ?"

_SQL_CALL_STATE = "SELECT state FROM calls WHERE call_id = ?"
_SQL_DELETE_SIGNALS = "DELETE FROM call_signals WHERE call_id = ?"
_SQL_PARTICIPANT = (
    "SELECT state FROM call_participants WHERE call_id = ? AND username = ?"
)
_ERR_NOT_FOUND = "call not found"
_ERR_CHANNEL_REQUIRED = "channel required"
_ERR_ACCESS_DENIED = "access denied"
_ERR_CALL_NOT_ACTIVE = "call is not active"
_ERR_SHARE_NOT_FOUND = "not found"

_SQL_CLEAR_SCREENSHARE = (
    "UPDATE calls SET screenshare_user = NULL"
    " WHERE call_id = ? AND screenshare_user = ?"
)


def _db():
    db = sqlite3.connect(presence_mod.PRESENCE_DB)
    db.row_factory = sqlite3.Row
    db.execute(_WAL)
    return db


def _format_duration(seconds: float) -> str:
    """Render a call length the way a person would say it."""
    total = max(0, int(seconds))
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def _post_call_notice(call, now: float) -> None:
    """Leave a record of a finished call in the channel it happened in.

    A call used to vanish without trace: someone who missed the thirty-second
    ring came back to a channel that looked like nothing had happened, and a
    conversation that took place on a call left nothing behind to refer to.
    One system line — the same kind the channel already uses for renames and
    joins — is enough to close both gaps.

    Only ever touches the message database, never ``presence.db``: it runs
    while the caller still holds an open write transaction there, and a second
    connection reaching for the same file would simply sit on the busy timeout.

    Failures are swallowed. A call ending is the important part; a note about
    it is not worth propagating an error from the message database into.

    :param call: Row with ``channel``, ``initiator`` and ``answered_ts``.
    :param now: The moment the call ended.
    """
    try:
        from .common import shared_db_path, init_messages_db

        if call["answered_ts"]:
            text = "Call ended · " + _format_duration(now - call["answered_ts"])
        else:
            text = f"Missed call from {call['initiator']}"

        init_messages_db()
        db = sqlite3.connect(str(shared_db_path()))
        try:
            db.execute(_WAL)
            db.execute(
                "INSERT INTO messages (channel, sender, content, content_type, ts)"
                " VALUES (?, 'system', ?, 'system', ?)",
                (call["channel"], text, now),
            )
            db.commit()
        finally:
            db.close()
    except Exception:  # nosec B110 - a notice must never break a hang-up
        pass


def _live_members(db, call_id: str, now: float, exclude: str = "") -> int:
    """Count who could still be talking on *call_id*.

    A call needs two people, and both halves of that count have to mean
    something.  "On it" is an accepted participant whose in-call heartbeat is
    still fresh — a row left behind by a browser that died is not somebody to
    hold a call open for, because nothing is ever going to POST ``/end`` for
    it, and the channel stays blocked against every later call while it sits
    there.  "Could still join" is an invitation that is still ringing;
    ``/calls/incoming`` stops offering it after :data:`_RINGING_TIMEOUT`, and
    it should stop counting at the same moment.

    :param exclude: A username to leave out — the person leaving, whose row
        has not been updated yet, or has just been.
    :returns: How many people the call still has.
    :rtype: int
    """
    started_ts = db.execute(
        "SELECT started_ts FROM calls WHERE call_id = ?", (call_id,)
    ).fetchone()["started_ts"]
    return db.execute(
        "SELECT COUNT(*) FROM call_participants p"  # nosec B608
        " WHERE p.call_id = ? AND p.username != ? AND ("
        + _SQL_LIVE_ACCEPTED  # a constant fragment; every value is bound below
        + "   OR (p.state = 'pending' AND COALESCE(p.invited_ts, ?) >= ?)"
        " )",
        (
            call_id,
            exclude,
            now - _CALL_HEARTBEAT_STALE,
            started_ts,
            now - _RINGING_TIMEOUT,
        ),
    ).fetchone()[0]


def _finish_call(db, call_id: str, now: float, state: str = "ended") -> bool:
    """Move a live call to its final state, exactly once.

    Several paths can be the one that ends a call — the last participant
    leaving, the ring timing out, the staleness sweep — and two of them can
    race.  Making the transition conditional on the call still being live means
    whichever gets there first does the signalling cleanup and posts the
    channel notice, and the loser does nothing.

    Does not commit — the caller owns the transaction.

    :returns: ``True`` if this call was the one that ended it.
    :rtype: bool
    """
    changed = db.execute(
        "UPDATE calls SET state = ?, ended_ts = ?"
        " WHERE call_id = ? AND state IN ('ringing', 'active')",
        (state, now, call_id),
    ).rowcount
    if not changed:
        return False
    db.execute(_SQL_DELETE_SIGNALS, (call_id,))
    call = db.execute(
        "SELECT channel, initiator, answered_ts FROM calls WHERE call_id = ?",
        (call_id,),
    ).fetchone()
    if call:
        _post_call_notice(call, now)
    return True


def _sweep_stale_calls(db) -> None:
    """End calls that no client is going to end for us.

    A call only ends when a participant POSTs ``/calls/<id>/end``.  If the
    browser that would have sent it is gone — tab closed mid-call, laptop
    lid shut, wifi dropped — the row stays ``'ringing'`` or ``'active'``
    indefinitely, and because a channel may hold only one live call at a
    time, that wedges calling in the channel until the server restarts.

    Two cases are reconciled here, both keyed off state the server already
    has, so no extra client bookkeeping is required:

    * **Unanswered** — a ``'ringing'`` call older than
      :data:`_RINGING_TIMEOUT`.  ``/calls/incoming`` already hides these
      from the callee, so this just makes the stored state agree.
    * **Abandoned** — an ``'active'`` call in which *no* accepted participant
      is still live, where live means both heartbeats are fresh: presence
      (:data:`_PRESENCE_STALE`) *and* the in-call state poll
      (:data:`_CALL_HEARTBEAT_STALE`).  Presence on its own is not enough —
      it keeps ticking for as long as any tab is open, so a browser that
      merely navigated away from the call still looked like a participant
      and held the channel against every later call indefinitely.  One
      genuinely live participant is enough to keep the call.

    Does not commit — the caller owns the transaction.

    :param db: An open connection to ``presence.db``.
    """
    now = time.time()

    stale = [
        row["call_id"]
        for row in db.execute(
            "SELECT call_id FROM calls WHERE state = 'ringing' AND started_ts < ?",
            (now - _RINGING_TIMEOUT,),
        )
    ]

    # An active call survives while any accepted participant is still live;
    # NULL last_seen (a user with no presence row yet) counts as stale.  Calls
    # with no accepted participants at all are swept too.
    stale += [
        row["call_id"]
        for row in db.execute(
            "SELECT c.call_id FROM calls c"  # nosec B608
            " WHERE c.state = 'active'"
            " AND NOT EXISTS ("
            "   SELECT 1 FROM call_participants p"
            "   LEFT JOIN presence pr ON pr.user = p.username"
            # A constant fragment; both timestamps are bound below.
            "   WHERE p.call_id = c.call_id AND" + _SQL_LIVE_PARTICIPANT + " )",
            (now - _CALL_HEARTBEAT_STALE, now - _PRESENCE_STALE),
        )
    ]

    for call_id in stale:
        _finish_call(db, call_id, now)


def reset_all_screenshares_ended() -> None:
    """Mark every active standalone screen share as ``'ended'``.

    Called once at application startup so stale share records from a previous
    server run do not block new shares.
    """
    db = sqlite3.connect(presence_mod.PRESENCE_DB)
    db.execute(_WAL)
    now = time.time()
    db.execute(
        "UPDATE screenshares SET state = 'ended', ended_ts = ? WHERE state = 'active'",
        (now,),
    )
    db.commit()
    db.execute(_INCREMENTAL_VACUUM)
    db.close()


def reset_all_calls_ended() -> None:
    """Mark every in-progress call as ``'ended'`` and clear stale signaling.

    Called once at application startup so that stale ``'ringing'`` or
    ``'active'`` call records from a previous server run do not block new
    calls in the same channels.
    """
    db = sqlite3.connect(presence_mod.PRESENCE_DB)
    db.execute(_WAL)
    now = time.time()
    db.execute(
        "UPDATE calls SET state = 'ended', ended_ts = ?"
        " WHERE state IN ('ringing', 'active')",
        (now,),
    )
    # Clear stale WebRTC signaling rows from a previous server run.  This table
    # is shared by both calls and standalone screen shares (keyed by share_id),
    # so a single unconditional delete covers both.
    db.execute("DELETE FROM call_signals")
    db.commit()
    db.execute(_INCREMENTAL_VACUUM)
    db.close()


def _participants_for_channel(channel: str) -> list:
    """Return the list of usernames who belong to *channel*.

    * **DM channels** (``"dm:user1:user2:..."``): parsed from the channel
      string.
    * **Private channels** (``"private:<id>"``): looked up via the
      ``private_channel_members`` table.
    * **Public channels**: not callable; returns ``[]``.

    :param channel: The channel identifier.
    :type channel: str
    :returns: List of usernames in the channel, or ``[]`` for public channels.
    :rtype: list of str
    """
    if channel.startswith("dm:"):
        return channel.split(":")[1:]
    if channel.startswith("private:"):
        from .chat import get_private_channel_members

        try:
            return get_private_channel_members(int(channel.split(":")[1]))
        except (ValueError, IndexError):
            return []
    return []


@calls_bp.route("/calls/initiate", methods=["POST"])
@auth.login_required
def initiate_call():
    """Initiate a new call in a channel.

    Route: ``POST /calls/initiate``

    Creates a call record in ``'ringing'`` state and adds participant rows for
    every member of the channel.  The initiator is immediately marked
    ``'accepted'``; all other participants begin as ``'pending'``.

    Request body (JSON):
        **channel** (str): The channel to call in.  Must be a DM or private
        channel that the current user belongs to.

    :returns: JSON with ``call_id`` (str) and ``participants`` (list of str).
    :rtype: flask.Response (application/json)
    """
    user = session["user"]
    data = request.get_json(silent=True) or {}
    channel = data.get("channel", "").strip()

    if not channel:
        return jsonify({"error": _ERR_CHANNEL_REQUIRED}), 400

    participants = _participants_for_channel(channel)
    if not participants or user not in participants:
        return jsonify({"error": _ERR_ACCESS_DENIED}), 403

    others = [p for p in participants if p != user]
    if not others:
        return jsonify({"error": "no other participants in channel"}), 400

    now = time.time()
    call_id = str(uuid.uuid4())

    db = _db()
    try:
        # Retire calls nobody is left to end before deciding this channel is
        # busy, so a crashed or closed browser cannot lock the channel out of
        # calling until the next server restart.
        _sweep_stale_calls(db)

        existing = db.execute(
            "SELECT call_id FROM calls WHERE channel = ? AND state IN ('ringing', 'active')",
            (channel,),
        ).fetchone()
        if existing:
            return (
                jsonify({"error": "a call is already in progress in this channel"}),
                409,
            )

        db.execute(
            "INSERT INTO calls (call_id, channel, initiator, state, started_ts)"
            " VALUES (?, ?, ?, 'ringing', ?)",
            (call_id, channel, user, now),
        )
        db.execute(
            "INSERT INTO call_participants"
            " (call_id, username, role, state, joined_ts, last_seen_ts)"
            " VALUES (?, ?, 'initiator', 'accepted', ?, ?)",
            (call_id, user, now, now),
        )
        for other in others:
            db.execute(
                "INSERT INTO call_participants"
                " (call_id, username, role, state, invited_ts)"
                " VALUES (?, ?, 'participant', 'pending', ?)",
                (call_id, other, now),
            )
        db.commit()
    finally:
        db.close()

    return jsonify({"call_id": call_id, "participants": participants})


@calls_bp.route("/calls/incoming", methods=["GET"])
@auth.login_required
def incoming_calls():
    """Return calls currently ringing for the current user.

    Route: ``GET /calls/incoming``

    Pushed to the client (and polled as a fallback) to surface the
    incoming-call notification.  Returns live calls in which the current user
    is a ``'pending'`` participant whose invitation is still ringing — younger
    than :data:`_RINGING_TIMEOUT`, measured from when *they* were invited, so
    someone pulled into a call that has been running for an hour still rings.
    Bounding it this way also stops an invitation nobody answered from ringing
    for the rest of the call's life.

    :returns: JSON array of call objects with ``call_id``, ``channel``,
        ``initiator``, and ``started_ts``.
    :rtype: flask.Response (application/json)
    """
    user = session["user"]
    cutoff = time.time() - _RINGING_TIMEOUT

    db = _db()
    rows = db.execute(
        """
        SELECT c.call_id, c.channel, c.initiator, c.started_ts
          FROM calls c
          JOIN call_participants cp ON c.call_id = cp.call_id
         WHERE cp.username = ?
           AND cp.state   = 'pending'
           AND c.state IN ('ringing', 'active')
           AND COALESCE(cp.invited_ts, c.started_ts) >= ?
        """,
        (user, cutoff),
    ).fetchall()
    db.close()

    return jsonify(
        [
            {
                "call_id": r["call_id"],
                "channel": r["channel"],
                "initiator": r["initiator"],
                "started_ts": r["started_ts"],
            }
            for r in rows
        ]
    )


@calls_bp.route("/calls/active", methods=["GET"])
@auth.login_required
def active_call_for_channel():
    """Return the call currently running in a channel, if there is one.

    Route: ``GET /calls/active?channel=<channel>``

    Lets a channel member discover a call that is already under way — one they
    were never rung for, or whose ring they missed — so the client can offer to
    join it instead of leaving them with no way in.

    :returns: JSON with ``call`` set to the call object, or ``null`` when the
        channel has no live call.
    :rtype: flask.Response (application/json)
    """
    user = session["user"]
    channel = request.args.get("channel", "").strip()
    if not channel:
        return jsonify({"error": _ERR_CHANNEL_REQUIRED}), 400

    members = _participants_for_channel(channel)
    if not members or user not in members:
        return jsonify({"error": _ERR_ACCESS_DENIED}), 403

    db = _db()
    try:
        _sweep_stale_calls(db)
        db.commit()
        row = db.execute(
            "SELECT call_id, initiator, state, started_ts FROM calls"
            " WHERE channel = ? AND state IN ('ringing', 'active')",
            (channel,),
        ).fetchone()
        if not row:
            return jsonify({"call": None})

        on_call = [
            r["username"]
            for r in db.execute(
                "SELECT username FROM call_participants"
                " WHERE call_id = ? AND state = 'accepted'",
                (row["call_id"],),
            )
        ]
    finally:
        db.close()

    return jsonify(
        {
            "call": {
                "call_id": row["call_id"],
                "initiator": row["initiator"],
                "state": row["state"],
                "started_ts": row["started_ts"],
                "participants": on_call,
                # Whether *this* user is already on it, so the client knows to
                # offer "Join" rather than nothing at all.
                "joined": user in on_call,
            }
        }
    )


@calls_bp.route("/calls/<call_id>/accept", methods=["POST"])
@auth.login_required
def accept_call(call_id):
    """Accept an incoming call.

    Route: ``POST /calls/<call_id>/accept``

    Updates the current user's participant record to ``'accepted'`` and
    transitions the call to ``'active'``.

    :param call_id: UUID of the call.
    :type call_id: str
    :returns: JSON with ``status`` and ``participants`` (list of accepted
        usernames).
    :rtype: flask.Response (application/json)
    """
    user = session["user"]
    now = time.time()

    db = _db()
    try:
        call = db.execute(_SQL_CALL_STATE, (call_id,)).fetchone()
        if not call:
            return jsonify({"error": _ERR_NOT_FOUND}), 404
        if call["state"] not in ("ringing", "active"):
            return jsonify({"error": "call is no longer available"}), 409

        participant = db.execute(
            _SQL_PARTICIPANT,
            (call_id, user),
        ).fetchone()
        if not participant:
            # Not invited, but the call is happening in a channel this user
            # belongs to — let them walk in. Missing the 30-second ring (tab
            # closed, stepped away, rejected by accident) otherwise locked a
            # member out of their own channel's call until somebody thought to
            # invite them by hand.
            channel = db.execute(
                "SELECT channel FROM calls WHERE call_id = ?", (call_id,)
            ).fetchone()["channel"]
            if user not in _participants_for_channel(channel):
                return jsonify({"error": "not a participant in this call"}), 403
            db.execute(
                "INSERT INTO call_participants"
                " (call_id, username, role, state, invited_ts)"
                " VALUES (?, ?, 'participant', 'pending', ?)",
                (call_id, user, now),
            )

        db.execute(
            "UPDATE call_participants"
            " SET state = 'accepted', joined_ts = ?, last_seen_ts = ?"
            " WHERE call_id = ? AND username = ?",
            (now, now, call_id, user),
        )
        db.execute(
            "UPDATE calls SET state = 'active', answered_ts = ? WHERE call_id = ?",
            (now, call_id),
        )

        # Someone accepting may be *re*-joining a call they earlier left, and
        # signalling rows live until the whole call ends. Their old offers,
        # answers and ICE candidates describe peer connections that no longer
        # exist, so drop everything exchanged with this user before they get a
        # fresh cursor below — otherwise the replay renegotiates their new
        # connections into a dead end.
        db.execute(
            "DELETE FROM call_signals"
            " WHERE call_id = ? AND (to_user = ? OR from_user = ?)",
            (call_id, user, user),
        )

        accepted = db.execute(
            "SELECT username FROM call_participants"
            " WHERE call_id = ? AND state = 'accepted'",
            (call_id,),
        ).fetchall()
        # The client starts its signal poll from here. Seeding it with the
        # newest existing id stops a joiner from replaying the history of a
        # call that has been running for a while.
        last_signal_id = (
            db.execute(
                "SELECT COALESCE(MAX(id), 0) FROM call_signals WHERE call_id = ?",
                (call_id,),
            ).fetchone()[0]
            or 0
        )
        db.commit()
    finally:
        db.close()

    return jsonify(
        {
            "status": "ok",
            "participants": [r["username"] for r in accepted],
            "last_signal_id": last_signal_id,
        }
    )


@calls_bp.route("/calls/<call_id>/reject", methods=["POST"])
@auth.login_required
def reject_call(call_id):
    """Reject an incoming call.

    Route: ``POST /calls/<call_id>/reject``

    Marks the current user's participant record as ``'rejected'``.  When all
    non-initiator participants have rejected, the call transitions to
    ``'rejected'``.

    :param call_id: UUID of the call.
    :type call_id: str
    :returns: JSON with ``status``.
    :rtype: flask.Response (application/json)
    """
    user = session["user"]
    now = time.time()

    db = _db()
    try:
        call = db.execute(
            "SELECT state, initiator FROM calls WHERE call_id = ?", (call_id,)
        ).fetchone()
        if not call:
            return jsonify({"error": _ERR_NOT_FOUND}), 404

        db.execute(
            "UPDATE call_participants SET state = 'rejected', left_ts = ?"
            " WHERE call_id = ? AND username = ?",
            (now, call_id, user),
        )

        pending_count = db.execute(
            "SELECT COUNT(*) FROM call_participants"
            " WHERE call_id = ? AND state = 'pending'",
            (call_id,),
        ).fetchone()[0]

        accepted_others = db.execute(
            "SELECT COUNT(*) FROM call_participants"
            " WHERE call_id = ? AND state = 'accepted' AND username != ?",
            (call_id, call["initiator"]),
        ).fetchone()[0]

        if pending_count == 0 and accepted_others == 0:
            _finish_call(db, call_id, now, state="rejected")

        db.commit()
    finally:
        db.close()

    return jsonify({"status": "ok"})


@calls_bp.route("/calls/<call_id>/end", methods=["POST"])
@auth.login_required
def end_call(call_id):
    """End or leave a call.

    Route: ``POST /calls/<call_id>/end``

    Marks the current user's participant record as ``'left'``.  The call
    itself ends only once fewer than two participants remain who are on it or
    could still join it — so leaving a two-person call ends it, while leaving
    a larger one lets the rest carry on.  Any other participants see the
    result on their next state poll.

    :param call_id: UUID of the call.
    :type call_id: str
    :returns: JSON with ``status``.
    :rtype: flask.Response (application/json)
    """
    user = session["user"]
    now = time.time()

    db = _db()
    try:
        call = db.execute(_SQL_CALL_STATE, (call_id,)).fetchone()
        if not call:
            return jsonify({"error": _ERR_NOT_FOUND}), 404

        db.execute(
            "UPDATE call_participants SET state = 'left', left_ts = ?"
            " WHERE call_id = ? AND username = ?",
            (now, call_id, user),
        )

        # If the leaver was screensharing, clear it so remaining participants
        # stop receiving their frozen last frame.
        db.execute(
            _SQL_CLEAR_SCREENSHARE,
            (call_id, user),
        )

        # Their signalling rows describe peer connections that just died. Drop
        # them now so they cannot be replayed if this user rejoins, and so a
        # long call does not accumulate the debris of everyone who passed
        # through it.
        db.execute(
            "DELETE FROM call_signals"
            " WHERE call_id = ? AND (to_user = ? OR from_user = ?)",
            (call_id, user, user),
        )

        if _live_members(db, call_id, now, exclude=user) < 2:
            _finish_call(db, call_id, now)

        db.commit()
        db.execute(_INCREMENTAL_VACUUM)
    finally:
        db.close()

    return jsonify({"status": "ok"})


@calls_bp.route("/calls/<call_id>/gone", methods=["POST"])
@auth.login_required
def report_participant_gone(call_id):
    """Report a participant whose connection died without them leaving.

    Route: ``POST /calls/<call_id>/gone``

    A browser that crashes, loses its network, or is closed before the unload
    beacon gets out leaves an ``'accepted'`` row nobody will ever clear.  The
    server can only notice that by waiting out :data:`_CALL_HEARTBEAT_STALE`,
    which leaves the channel unable to host a new call for up to a minute after
    everyone has actually gone.  The remaining participants know sooner: their
    peer connection failed and did not recover within its grace period.  This
    lets them say so.

    The report is corroborated, not trusted: it is only acted on when the
    server has *also* not heard from the reported participant for
    :data:`_GONE_CORROBORATION` seconds, so a participant cannot use it to
    evict somebody who is plainly still there.

    Request body (JSON):
        **username** (str): The participant believed to be gone.

    :param call_id: UUID of the call.
    :type call_id: str
    :returns: JSON with ``status`` — ``"removed"`` when the row was cleared,
        ``"ignored"`` when the reported participant still looks live.
    :rtype: flask.Response (application/json)
    """
    user = session["user"]
    target = (request.get_json(silent=True) or {}).get("username", "").strip()
    if not target or target == user:
        return jsonify({"error": "username required"}), 400

    now = time.time()
    db = _db()
    try:
        reporter = db.execute(_SQL_PARTICIPANT, (call_id, user)).fetchone()
        if not reporter or reporter["state"] != "accepted":
            return jsonify({"error": "not a participant"}), 403

        removed = db.execute(
            "UPDATE call_participants SET state = 'left', left_ts = ?"
            " WHERE call_id = ? AND username = ? AND state = 'accepted'"
            " AND COALESCE(last_seen_ts, joined_ts, 0) < ?",
            (now, call_id, target, now - _GONE_CORROBORATION),
        ).rowcount
        if not removed:
            db.commit()
            return jsonify({"status": "ignored"})

        db.execute(_SQL_CLEAR_SCREENSHARE, (call_id, target))
        db.execute(
            "DELETE FROM call_signals"
            " WHERE call_id = ? AND (to_user = ? OR from_user = ?)",
            (call_id, target, target),
        )
        if _live_members(db, call_id, now) < 2:
            _finish_call(db, call_id, now)
        db.commit()
    finally:
        db.close()

    return jsonify({"status": "removed"})


@calls_bp.route("/calls/<call_id>/invite", methods=["POST"])
@auth.login_required
def invite_to_call(call_id):
    """Invite a registered user to an active call.

    Route: ``POST /calls/<call_id>/invite``

    Any accepted participant may invite any registered user.  If the target
    was previously a participant (rejected or left) their row is reset to
    ``'pending'`` so they receive an incoming-call notification again.

    Request body (JSON):
        **username** (str): The user to invite.

    :param call_id: UUID of the call.
    :type call_id: str
    :returns: JSON with ``status``.
    :rtype: flask.Response (application/json)
    """
    user = session["user"]
    data = request.get_json(silent=True) or {}
    target = data.get("username", "").strip()

    if not target:
        return jsonify({"error": "username required"}), 400
    if target == user:
        return jsonify({"error": "cannot invite yourself"}), 400

    db = _db()
    try:
        call = db.execute(_SQL_CALL_STATE, (call_id,)).fetchone()
        if not call:
            return jsonify({"error": _ERR_NOT_FOUND}), 404
        if call["state"] != "active":
            return jsonify({"error": _ERR_CALL_NOT_ACTIVE}), 409

        caller_p = db.execute(_SQL_PARTICIPANT, (call_id, user)).fetchone()
        if not caller_p or caller_p["state"] != "accepted":
            return jsonify({"error": "not a participant"}), 403

        # Verify target user exists
        auth_db = sqlite3.connect(auth.AUTH_DB)
        auth_db.row_factory = sqlite3.Row
        target_row = auth_db.execute(
            "SELECT username FROM users WHERE username = ?", (target,)
        ).fetchone()
        auth_db.close()
        if not target_row:
            return jsonify({"error": "user not found"}), 404

        existing = db.execute(_SQL_PARTICIPANT, (call_id, target)).fetchone()
        if existing:
            if existing["state"] == "accepted":
                return jsonify({"error": "user already in call"}), 409
            if existing["state"] == "pending":
                return jsonify({"status": "ok"})
            # Reset rejected/left participant so they ring again
            db.execute(
                "UPDATE call_participants"
                " SET state = 'pending', left_ts = NULL, invited_ts = ?"
                " WHERE call_id = ? AND username = ?",
                (time.time(), call_id, target),
            )
        else:
            db.execute(
                "INSERT INTO call_participants"
                " (call_id, username, role, state, invited_ts)"
                " VALUES (?, ?, 'participant', 'pending', ?)",
                (call_id, target, time.time()),
            )
        db.commit()
    finally:
        db.close()

    return jsonify({"status": "ok"})


@calls_bp.route("/calls/<call_id>/signal", methods=["POST"])
@auth.login_required
def send_signal(call_id):
    """Send a WebRTC signaling message to another participant.

    Route: ``POST /calls/<call_id>/signal``

    Stores an offer, answer, or ICE candidate in the ``call_signals`` table.
    The recipient retrieves pending signals by polling
    ``GET /calls/<call_id>/signals``.

    Request body (JSON):
        **to** (str): Recipient username.
        **type** (str): ``"offer"``, ``"answer"``, or ``"ice_candidate"``.
        **payload** (object): The SDP object or ICE candidate dict.

    :param call_id: UUID of the call.
    :type call_id: str
    :returns: JSON with ``status``.
    :rtype: flask.Response (application/json)
    """
    user = session["user"]
    data = request.get_json(silent=True) or {}

    to_user = data.get("to")
    signal_type = data.get("type")
    payload = data.get("payload")

    if (
        not to_user
        or signal_type not in ("offer", "answer", "ice_candidate")
        or payload is None
    ):
        return (
            jsonify(
                {
                    "error": "to, type (offer/answer/ice_candidate), and payload are required"
                }
            ),
            400,
        )

    db = _db()
    try:
        call = db.execute(_SQL_CALL_STATE, (call_id,)).fetchone()
        if not call:
            return jsonify({"error": _ERR_NOT_FOUND}), 404
        if call["state"] == "ended":
            return jsonify({"error": "call has ended"}), 409

        db.execute(
            "INSERT INTO call_signals"
            " (call_id, from_user, to_user, signal_type, payload, ts)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (call_id, user, to_user, signal_type, json.dumps(payload), time.time()),
        )
        db.commit()
    finally:
        db.close()

    return jsonify({"status": "ok"})


@calls_bp.route("/calls/<call_id>/signals", methods=["GET"])
@auth.login_required
def get_signals(call_id):
    """Return WebRTC signals directed at the current user.

    Route: ``GET /calls/<call_id>/signals?after=<id>``

    Polled by the client during call setup to receive the remote offer,
    answer, and any ICE candidates.  Pass the ``id`` of the last signal
    already processed as ``?after=`` to avoid re-processing old messages.

    :param call_id: UUID of the call.
    :type call_id: str
    :query after: ID of the last signal already received (default 0).
    :returns: JSON array of signal objects with ``id``, ``from``, ``type``,
        ``payload``, and ``ts``.
    :rtype: flask.Response (application/json)
    """
    user = session["user"]
    try:
        after_id = int(request.args.get("after", 0))
    except ValueError:
        after_id = 0

    db = _db()
    rows = db.execute(
        """
        SELECT id, from_user, signal_type, payload, ts
          FROM call_signals
         WHERE call_id = ? AND to_user = ? AND id > ?
         ORDER BY id ASC
        """,
        (call_id, user, after_id),
    ).fetchall()
    db.close()

    return jsonify(
        [
            {
                "id": r["id"],
                "from": r["from_user"],
                "type": r["signal_type"],
                "payload": json.loads(r["payload"]),
                "ts": r["ts"],
            }
            for r in rows
        ]
    )


@calls_bp.route("/calls/<call_id>/screenshare", methods=["POST"])
@auth.login_required
def set_screenshare(call_id):
    """Record whether the current user is sharing their screen in this call.

    Route: ``POST /calls/<call_id>/screenshare``

    Under the WebRTC transport the screen video travels peer-to-peer, so this
    endpoint exists only to record *who* is sharing.  Sharing is per
    participant — any number of people may share at the same time — and is
    stored in ``call_participants.sharing``.  Clients read the resulting
    ``screensharers`` list from ``GET /calls/<call_id>/state`` to label the
    stage tiles and to notice a share that ended without a WebRTC track event.

    ``calls.screenshare_user`` is still maintained as the most recent sharer so
    older clients keep working; it is never the source of truth.

    Request body (JSON):
        **on** (bool): ``true`` when starting to share, ``false`` when stopping.

    :param call_id: UUID of the call.
    :type call_id: str
    :returns: JSON with ``status``.
    :rtype: flask.Response (application/json)
    """
    user = session["user"]
    data = request.get_json(silent=True) or {}
    on = bool(data.get("on"))

    db = _db()
    try:
        call = db.execute(_SQL_CALL_STATE, (call_id,)).fetchone()
        participant = db.execute(_SQL_PARTICIPANT, (call_id, user)).fetchone()
        if not call or not participant:
            return jsonify({"error": _ERR_NOT_FOUND}), 404
        if call["state"] != "active":
            return jsonify({"error": _ERR_CALL_NOT_ACTIVE}), 409

        db.execute(
            "UPDATE call_participants SET sharing = ?"
            " WHERE call_id = ? AND username = ?",
            (1 if on else 0, call_id, user),
        )
        if on:
            db.execute(
                "UPDATE calls SET screenshare_user = ? WHERE call_id = ?",
                (user, call_id),
            )
        else:
            db.execute(_SQL_CLEAR_SCREENSHARE, (call_id, user))
        db.commit()
    finally:
        db.close()

    return jsonify({"status": "ok"})


@calls_bp.route("/calls/<call_id>/state", methods=["GET"])
@auth.login_required
def call_state(call_id):
    """Return the current state of a call.

    Route: ``GET /calls/<call_id>/state``

    Polled every few seconds by active participants to detect remote hang-ups,
    people joining or leaving, screen shares starting or stopping, and other
    state transitions (``'ended'``, ``'rejected'``).

    :param call_id: UUID of the call.
    :type call_id: str
    :returns: JSON object with call metadata, a ``participants`` list (each
        with a ``sharing`` flag) and ``screensharers``, the usernames of every
        participant currently sharing a screen.
    :rtype: flask.Response (application/json)
    """
    db = _db()
    _CALL_COLS = (
        "SELECT call_id, channel, initiator, state, started_ts,"
        " answered_ts, ended_ts, screenshare_user"
        " FROM calls WHERE call_id = ?"
    )
    call = db.execute(_CALL_COLS, (call_id,)).fetchone()
    if not call:
        db.close()
        return jsonify({"error": _ERR_NOT_FOUND}), 404

    # This poll *is* the in-call heartbeat.  Every participant runs it every few
    # seconds for as long as they are on the call and stops the moment they are
    # not, which makes it the one signal that tracks call membership rather than
    # merely having a tab open — see :data:`_CALL_HEARTBEAT_STALE`.
    db.execute(
        "UPDATE call_participants SET last_seen_ts = ?"
        " WHERE call_id = ? AND username = ? AND state = 'accepted'",
        (time.time(), call_id, session["user"]),
    )
    db.commit()

    if (
        call["state"] == "ringing"
        and time.time() - call["started_ts"] > _RINGING_TIMEOUT
    ):
        now = time.time()
        _finish_call(db, call_id, now, state="rejected")
        db.execute(
            "UPDATE call_participants SET state = 'rejected', left_ts = ?"
            " WHERE call_id = ? AND state = 'pending'",
            (now, call_id),
        )
        db.commit()
        # This route is a GET, so the app's after_request bump does not cover
        # it; nudge the SSE streams by hand or the missed-call line waits for
        # the message collector's slow reconcile.
        presence_mod.bump_event_signal()
        call = db.execute(_CALL_COLS, (call_id,)).fetchone()

    participants = db.execute(
        "SELECT username, role, state, joined_ts, left_ts, sharing"
        " FROM call_participants WHERE call_id = ?",
        (call_id,),
    ).fetchall()
    db.close()

    # Someone who has left is not sharing any more, whatever their row says.
    screensharers = [
        p["username"] for p in participants if p["sharing"] and p["state"] == "accepted"
    ]

    return jsonify(
        {
            "call_id": call["call_id"],
            "channel": call["channel"],
            "initiator": call["initiator"],
            "state": call["state"],
            "started_ts": call["started_ts"],
            "answered_ts": call["answered_ts"],
            "ended_ts": call["ended_ts"],
            "screenshare_user": call["screenshare_user"],
            "screensharers": screensharers,
            "participants": [
                {
                    "username": p["username"],
                    "role": p["role"],
                    "state": p["state"],
                    "joined_ts": p["joined_ts"],
                    "left_ts": p["left_ts"],
                    "sharing": bool(p["sharing"]),
                }
                for p in participants
            ],
        }
    )


# ── Standalone screen share ────────────────────────────────────────────────────


@calls_bp.route("/screenshare/start", methods=["POST"])
@auth.login_required
def start_screenshare():
    """Start a standalone screen share in a channel.

    Route: ``POST /screenshare/start``

    Creates a ``screenshares`` record in ``'active'`` state.  Unlike calls,
    no acceptance by viewers is required — any channel member can watch
    immediately by polling ``GET /screenshare/active``.

    Any previous active share by the same user in the same channel is
    automatically ended.

    Request body (JSON):
        **channel** (str): The DM or private channel to share into.

    :returns: JSON with ``share_id`` (str).
    :rtype: flask.Response (application/json)
    """
    user = session["user"]
    data = request.get_json(silent=True) or {}
    channel = data.get("channel", "").strip()
    if not channel:
        return jsonify({"error": _ERR_CHANNEL_REQUIRED}), 400
    participants = _participants_for_channel(channel)
    if participants and user not in participants:
        return jsonify({"error": _ERR_ACCESS_DENIED}), 403
    now = time.time()
    share_id = str(uuid.uuid4())
    db = _db()
    try:
        db.execute(
            "UPDATE screenshares SET state = 'ended', ended_ts = ?"
            " WHERE channel = ? AND sharer = ? AND state = 'active'",
            (now, channel, user),
        )
        db.execute(
            "INSERT INTO screenshares (share_id, channel, sharer, state, started_ts)"
            " VALUES (?, ?, ?, 'active', ?)",
            (share_id, channel, user, now),
        )
        db.commit()
    finally:
        db.close()
    return jsonify({"share_id": share_id})


@calls_bp.route("/screenshare/<share_id>/stop", methods=["POST"])
@auth.login_required
def stop_screenshare(share_id):
    """End a standalone screen share.

    Route: ``POST /screenshare/<share_id>/stop``

    Marks the share as ``'ended'`` and clears its signaling rows.  Only the
    sharer may call this endpoint.

    :param share_id: UUID of the screen share.
    :type share_id: str
    :returns: JSON with ``status``.
    :rtype: flask.Response (application/json)
    """
    user = session["user"]
    now = time.time()
    db = _db()
    try:
        share = db.execute(
            "SELECT sharer FROM screenshares WHERE share_id = ?", (share_id,)
        ).fetchone()
        if not share:
            return jsonify({"error": "share not found"}), 404
        if share["sharer"] != user:
            return jsonify({"error": _ERR_ACCESS_DENIED}), 403
        db.execute(
            "UPDATE screenshares SET state = 'ended', ended_ts = ? WHERE share_id = ?",
            (now, share_id),
        )
        # call_signals is shared with calls; standalone-share rows are keyed by
        # the share_id in the call_id column.
        db.execute(_SQL_DELETE_SIGNALS, (share_id,))
        db.commit()
        db.execute(_INCREMENTAL_VACUUM)
    finally:
        db.close()
    return jsonify({"status": "ok"})


@calls_bp.route("/screenshare/active", methods=["GET"])
@auth.login_required
def active_screenshares():
    """Return all active screen shares in a channel.

    Route: ``GET /screenshare/active?channel=<channel>``

    Polled every second by the client to detect when a channel member starts
    or stops sharing their screen.  Returns shares for all users, including
    the caller's own share if they are currently sharing.

    Query parameters:
        **channel** (str): The channel to query.  Required.

    :returns: JSON array of share objects with ``share_id``, ``channel``,
        ``sharer``, and ``started_ts``.
    :rtype: flask.Response (application/json)
    """
    user = session["user"]
    channel = request.args.get("channel", "").strip()
    if not channel:
        return jsonify({"error": _ERR_CHANNEL_REQUIRED}), 400
    participants = _participants_for_channel(channel)
    if participants and user not in participants:
        return jsonify({"error": _ERR_ACCESS_DENIED}), 403
    db = _db()
    rows = db.execute(
        "SELECT share_id, channel, sharer, started_ts"
        " FROM screenshares WHERE channel = ? AND state = 'active'",
        (channel,),
    ).fetchall()
    db.close()
    return jsonify(
        [
            {
                "share_id": r["share_id"],
                "channel": r["channel"],
                "sharer": r["sharer"],
                "started_ts": r["started_ts"],
            }
            for r in rows
        ]
    )


@calls_bp.route("/screenshare/<share_id>/signal", methods=["POST"])
@auth.login_required
def send_share_signal(share_id):
    """Send a WebRTC signaling message for a standalone screen share.

    Route: ``POST /screenshare/<share_id>/signal``

    Mirrors :func:`send_signal` but for the viewer-initiated one-to-many
    screen-share topology.  Viewers send an ``offer`` (and ICE candidates) to
    the sharer; the sharer replies with an ``answer`` (and ICE candidates).
    Rows are stored in the shared ``call_signals`` table keyed by *share_id*
    in the ``call_id`` column.

    Request body (JSON):
        **to** (str): Recipient username (the sharer, or a specific viewer).
        **type** (str): ``"offer"``, ``"answer"``, or ``"ice_candidate"``.
        **payload** (object): The SDP object or ICE candidate dict.

    :param share_id: UUID of the screen share.
    :type share_id: str
    :returns: JSON with ``status``.
    :rtype: flask.Response (application/json)
    """
    user = session["user"]
    data = request.get_json(silent=True) or {}
    to_user = data.get("to")
    signal_type = data.get("type")
    payload = data.get("payload")

    if (
        not to_user
        or signal_type not in ("offer", "answer", "ice_candidate")
        or payload is None
    ):
        return (
            jsonify(
                {
                    "error": "to, type (offer/answer/ice_candidate), and payload are required"
                }
            ),
            400,
        )

    db = _db()
    try:
        share = db.execute(
            "SELECT channel, state FROM screenshares WHERE share_id = ?", (share_id,)
        ).fetchone()
        if not share:
            return jsonify({"error": _ERR_SHARE_NOT_FOUND}), 404
        if share["state"] != "active":
            return jsonify({"error": "share is not active"}), 409
        participants = _participants_for_channel(share["channel"])
        if participants and user not in participants:
            return jsonify({"error": _ERR_ACCESS_DENIED}), 403

        db.execute(
            "INSERT INTO call_signals"
            " (call_id, from_user, to_user, signal_type, payload, ts)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (share_id, user, to_user, signal_type, json.dumps(payload), time.time()),
        )
        db.commit()
    finally:
        db.close()

    return jsonify({"status": "ok"})


@calls_bp.route("/screenshare/<share_id>/signals", methods=["GET"])
@auth.login_required
def get_share_signals(share_id):
    """Return screen-share signaling messages directed at the current user.

    Route: ``GET /screenshare/<share_id>/signals?after=<id>``

    Polled by both the sharer (to discover new viewer offers and ICE) and each
    viewer (to receive the answer and ICE).  Pass the ``id`` of the last signal
    already processed as ``?after=``.

    :param share_id: UUID of the screen share.
    :type share_id: str
    :query after: ID of the last signal already received (default 0).
    :returns: JSON array of signal objects with ``id``, ``from``, ``type``,
        ``payload``, and ``ts``.
    :rtype: flask.Response (application/json)
    """
    user = session["user"]
    try:
        after_id = int(request.args.get("after", 0))
    except ValueError:
        after_id = 0

    db = _db()
    rows = db.execute(
        """
        SELECT id, from_user, signal_type, payload, ts
          FROM call_signals
         WHERE call_id = ? AND to_user = ? AND id > ?
         ORDER BY id ASC
        """,
        (share_id, user, after_id),
    ).fetchall()
    db.close()

    return jsonify(
        [
            {
                "id": r["id"],
                "from": r["from_user"],
                "type": r["signal_type"],
                "payload": json.loads(r["payload"]),
                "ts": r["ts"],
            }
            for r in rows
        ]
    )
