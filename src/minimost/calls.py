"""
minimost.calls
==============

Voice/video calling with HTTP media relay.

All call state lives in the shared ``presence.db``.  Three tables (created
by :func:`init_calls_tables`, called from :func:`minimost.presence._init_tables`)
store the lifecycle of every call:

* ``calls`` — one row per call: channel, initiator, lifecycle state, and
  timestamps.
* ``call_participants`` — one row per (call_id, username): role, acceptance
  state, and join/leave timestamps.  Designed to support future group calls
  without schema changes.
* ``call_signals`` — kept for backwards compatibility; not used by the
  HTTP relay frontend.

Media is relayed through Flask: each participant uploads ``MediaRecorder``
chunks via ``POST /calls/<id>/media`` and the remote side polls
``GET /calls/<id>/media`` to receive them.  This avoids WebRTC P2P and
UDP entirely, making calls work even behind restrictive firewalls.

Module-level attributes
-----------------------
calls_bp : flask.Blueprint
    The Flask Blueprint for all call routes.  Registered in
    :func:`minimost.create_app`.
"""

import base64
import json
import sqlite3
import time
import uuid

from flask import Blueprint, jsonify, request, session

from . import auth
from . import presence as presence_mod

calls_bp = Blueprint("calls", __name__)

_WAL = "PRAGMA journal_mode=WAL"
_RINGING_TIMEOUT = 30


def _db():
    db = sqlite3.connect(presence_mod.PRESENCE_DB)
    db.row_factory = sqlite3.Row
    db.execute(_WAL)
    return db


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
        return jsonify({"error": "channel required"}), 400

    participants = _participants_for_channel(channel)
    if not participants or user not in participants:
        return jsonify({"error": "access denied"}), 403

    others = [p for p in participants if p != user]
    if not others:
        return jsonify({"error": "no other participants in channel"}), 400

    now = time.time()
    call_id = str(uuid.uuid4())

    db = _db()
    try:
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
            "INSERT INTO call_participants (call_id, username, role, state, joined_ts)"
            " VALUES (?, ?, 'initiator', 'accepted', ?)",
            (call_id, user, now),
        )
        for other in others:
            db.execute(
                "INSERT INTO call_participants (call_id, username, role, state)"
                " VALUES (?, ?, 'participant', 'pending')",
                (call_id, other),
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

    Polled by the client every second to surface the incoming-call
    notification.  Only returns calls in the ``'ringing'`` state where the
    current user is a ``'pending'`` participant and the call was started
    within the last :data:`_RINGING_TIMEOUT` seconds.

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
         WHERE cp.username   = ?
           AND cp.state      = 'pending'
           AND c.state       = 'ringing'
           AND c.started_ts >= ?
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
        call = db.execute(
            "SELECT state FROM calls WHERE call_id = ?", (call_id,)
        ).fetchone()
        if not call:
            return jsonify({"error": "call not found"}), 404
        if call["state"] not in ("ringing", "active"):
            return jsonify({"error": "call is no longer available"}), 409

        participant = db.execute(
            "SELECT state FROM call_participants WHERE call_id = ? AND username = ?",
            (call_id, user),
        ).fetchone()
        if not participant:
            return jsonify({"error": "not a participant in this call"}), 403

        db.execute(
            "UPDATE call_participants SET state = 'accepted', joined_ts = ?"
            " WHERE call_id = ? AND username = ?",
            (now, call_id, user),
        )
        db.execute(
            "UPDATE calls SET state = 'active', answered_ts = ? WHERE call_id = ?",
            (now, call_id),
        )
        accepted = db.execute(
            "SELECT username FROM call_participants"
            " WHERE call_id = ? AND state = 'accepted'",
            (call_id,),
        ).fetchall()
        db.commit()
    finally:
        db.close()

    return jsonify({"status": "ok", "participants": [r["username"] for r in accepted]})


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
            return jsonify({"error": "call not found"}), 404

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
            db.execute(
                "UPDATE calls SET state = 'rejected', ended_ts = ? WHERE call_id = ?",
                (now, call_id),
            )

        db.commit()
    finally:
        db.close()

    return jsonify({"status": "ok"})


@calls_bp.route("/calls/<call_id>/end", methods=["POST"])
@auth.login_required
def end_call(call_id):
    """End or leave a call.

    Route: ``POST /calls/<call_id>/end``

    Marks the current user's participant record as ``'left'`` and sets the
    overall call state to ``'ended'``.  Any other participants will see the
    call end on their next state poll.

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
            "SELECT state FROM calls WHERE call_id = ?", (call_id,)
        ).fetchone()
        if not call:
            return jsonify({"error": "call not found"}), 404

        db.execute(
            "UPDATE call_participants SET state = 'left', left_ts = ?"
            " WHERE call_id = ? AND username = ?",
            (now, call_id, user),
        )
        db.execute(
            "UPDATE calls SET state = 'ended', ended_ts = ? WHERE call_id = ?",
            (now, call_id),
        )
        # Free stored media so presence.db doesn't grow unboundedly
        db.execute("DELETE FROM call_media WHERE call_id = ?", (call_id,))
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
        call = db.execute(
            "SELECT state FROM calls WHERE call_id = ?", (call_id,)
        ).fetchone()
        if not call:
            return jsonify({"error": "call not found"}), 404
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


@calls_bp.route("/calls/<call_id>/state", methods=["GET"])
@auth.login_required
def call_state(call_id):
    """Return the current state of a call.

    Route: ``GET /calls/<call_id>/state``

    Polled every few seconds by active participants to detect remote hang-ups
    or other state transitions (``'ended'``, ``'rejected'``).

    :param call_id: UUID of the call.
    :type call_id: str
    :returns: JSON object with call metadata and a ``participants`` list.
    :rtype: flask.Response (application/json)
    """
    db = _db()
    call = db.execute(
        "SELECT call_id, channel, initiator, state, started_ts, answered_ts, ended_ts"
        " FROM calls WHERE call_id = ?",
        (call_id,),
    ).fetchone()
    if not call:
        db.close()
        return jsonify({"error": "call not found"}), 404

    participants = db.execute(
        "SELECT username, role, state, joined_ts, left_ts"
        " FROM call_participants WHERE call_id = ?",
        (call_id,),
    ).fetchall()
    db.close()

    return jsonify(
        {
            "call_id": call["call_id"],
            "channel": call["channel"],
            "initiator": call["initiator"],
            "state": call["state"],
            "started_ts": call["started_ts"],
            "answered_ts": call["answered_ts"],
            "ended_ts": call["ended_ts"],
            "participants": [
                {
                    "username": p["username"],
                    "role": p["role"],
                    "state": p["state"],
                    "joined_ts": p["joined_ts"],
                    "left_ts": p["left_ts"],
                }
                for p in participants
            ],
        }
    )


@calls_bp.route("/calls/<call_id>/media", methods=["POST"])
@auth.login_required
def upload_media(call_id):
    """Receive a binary media chunk from a call participant.

    Route: ``POST /calls/<call_id>/media``

    Accepts raw binary data (``application/octet-stream``) from a
    ``MediaRecorder`` running in the browser.  The first chunk must be sent
    with ``?init=1&mime=<mimeType>``; it is stored separately (``is_init=1``)
    and always returned to polling receivers so they can initialise their
    ``SourceBuffer``.  Subsequent chunks are stored with ``is_init=0`` and
    identified by their SQLite auto-increment ``id``.

    All chunks are stored in the shared ``presence.db`` ``call_media`` table
    so that every gunicorn worker can read what any other worker wrote.

    Query parameters:
        **init** (str, optional): Set to ``"1"`` to mark this as the
        initialisation segment.
        **mime** (str, optional): The ``MediaRecorder`` MIME type, e.g.
        ``"video/webm;codecs=vp8,opus"``.  Required when ``init=1``.

    :param call_id: UUID of the call.
    :type call_id: str
    :returns: JSON with ``status`` and ``seq`` (-1 for the init segment,
        auto-increment row id for data chunks).
    :rtype: flask.Response (application/json)
    """
    user = session["user"]
    is_init = request.args.get("init", "0") == "1"
    mime_type = request.args.get("mime", "video/webm")
    track = request.args.get("track", "")
    sender = f"{user}:{track}" if track else user
    data = request.get_data()

    if not data:
        return jsonify({"error": "no data"}), 400

    db = _db()
    try:
        call = db.execute(
            "SELECT state FROM calls WHERE call_id = ?", (call_id,)
        ).fetchone()
        participant = db.execute(
            "SELECT state FROM call_participants WHERE call_id = ? AND username = ?",
            (call_id, user),
        ).fetchone()

        if not call or not participant:
            return jsonify({"error": "call not found"}), 404
        if call["state"] not in ("ringing", "active"):
            return jsonify({"error": "call is not active"}), 409

        now = time.time()
        if is_init:
            db.execute(
                "DELETE FROM call_media WHERE call_id = ? AND sender = ? AND is_init = 1",
                (call_id, sender),
            )
            db.execute(
                "INSERT INTO call_media (call_id, sender, is_init, mime_type, data, ts)"
                " VALUES (?, ?, 1, ?, ?, ?)",
                (call_id, sender, mime_type, data, now),
            )
            db.commit()
            return jsonify({"status": "ok", "seq": -1})

        cursor = db.execute(
            "INSERT INTO call_media (call_id, sender, is_init, data, ts)"
            " VALUES (?, ?, 0, ?, ?)",
            (call_id, sender, data, now),
        )
        seq = cursor.lastrowid
        db.commit()
    finally:
        db.close()

    return jsonify({"status": "ok", "seq": seq})


@calls_bp.route("/calls/<call_id>/media", methods=["GET"])
@auth.login_required
def get_media(call_id):
    """Return buffered media chunks uploaded by a specific sender.

    Route: ``GET /calls/<call_id>/media?sender=<user>&after=<seq>``

    Polled every 500 ms by the receiving participant.  Always returns the
    most-recent initialisation segment (so late-joining receivers can
    bootstrap their ``SourceBuffer``) plus any data chunks whose SQLite
    ``id`` is greater than ``after``.

    All chunks are read from the shared ``presence.db`` ``call_media``
    table, so this works correctly across all gunicorn workers.

    Query parameters:
        **sender** (str): Username of the participant whose stream to
        receive.  Required.
        **after** (int, optional): ``id`` of the last data chunk already
        processed.  Defaults to ``-1`` (return all buffered chunks).

    :param call_id: UUID of the call.
    :type call_id: str
    :returns: JSON with ``mime_type``, ``init`` (base64 or null), and
        ``chunks`` (list of ``{seq, data}`` objects).
    :rtype: flask.Response (application/json)
    """
    user = session["user"]
    sender = request.args.get("sender", "").strip()
    try:
        after_seq = int(request.args.get("after", -1))
    except ValueError:
        after_seq = -1

    if not sender:
        return jsonify({"error": "sender required"}), 400

    db = _db()
    try:
        participant = db.execute(
            "SELECT state FROM call_participants WHERE call_id = ? AND username = ?",
            (call_id, user),
        ).fetchone()
        if not participant:
            return jsonify({"error": "not a participant"}), 403

        init_row = db.execute(
            "SELECT mime_type, data FROM call_media"
            " WHERE call_id = ? AND sender = ? AND is_init = 1"
            " ORDER BY id DESC LIMIT 1",
            (call_id, sender),
        ).fetchone()

        chunk_rows = db.execute(
            "SELECT id, data FROM call_media"
            " WHERE call_id = ? AND sender = ? AND is_init = 0 AND id > ?"
            " ORDER BY id ASC LIMIT 20",
            (call_id, sender, after_seq),
        ).fetchall()
    finally:
        db.close()

    init_b64 = base64.b64encode(bytes(init_row["data"])).decode() if init_row else None
    mime_type = init_row["mime_type"] if init_row else None

    return jsonify(
        {
            "mime_type": mime_type,
            "init": init_b64,
            "chunks": [
                {"seq": r["id"], "data": base64.b64encode(bytes(r["data"])).decode()}
                for r in chunk_rows
            ],
        }
    )
