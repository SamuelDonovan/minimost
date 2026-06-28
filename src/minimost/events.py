"""
minimost.events
===============

Server-Sent Events (SSE) push stream that replaces the legacy HTTP pollers.

Historically the browser opened roughly a dozen ``setInterval`` pollers (new
messages every 500 ms, presence/typing/unread badges every 1-5 s, incoming
calls, screen shares, …).  Each was a fresh authenticated HTTP request, so an
idle tab fired ~11 requests per second forever.

This module collapses all of that into **one** long-lived ``GET /events``
connection per tab.  The handler holds the request open and, on a short
internal tick, re-reads the same shared SQLite state the old endpoints read and
flushes an SSE event only when something actually changed.  Because every
Gunicorn worker sees the same on-disk databases (``messages.db`` /
``presence.db``), an event written by one worker is visible to a stream held
open in another — no extra cross-process bus is needed.

Design notes
------------
* **Worker model.**  A held-open stream occupies one worker thread for its
  whole lifetime, so the server must run Gunicorn's ``gthread`` worker class
  with a generous ``threads`` count (see ``minimost.gunicorn_conf``).  Capacity
  is ``workers * threads`` concurrent tabs.
* **No new dependencies.**  Pure Flask streaming response; the browser's native
  ``EventSource`` handles reconnection.
* **Single source of truth.**  The per-event collectors call the very same view
  functions the REST endpoints expose, so the pushed payloads are byte-for-byte
  what a poll would have returned.  Only ``/messages`` needs a cursor, so it
  goes through :func:`minimost.chat.messages_since`.
* **Reconcile floor.**  The message collector is write-driven, but it also
  re-queries at least every :data:`_MESSAGE_RECONCILE_SECONDS` even with no
  observed write.  That is the safety net for a dropped counter bump
  (``bump_event_signal`` swallows its own errors): a lost wake delays delivery
  by at most one reconcile instead of stranding the message.
* **Self-recycle.**  Each stream returns after :data:`_MAX_STREAM_SECONDS` plus
  up to :data:`_MAX_STREAM_JITTER_SECONDS` of jitter; ``EventSource`` reconnects
  automatically.  This bounds the lifetime of any half-closed connection that
  might otherwise pin a thread, and the jitter keeps tabs that connected
  together (e.g. just after a restart) from recycling in lockstep.
"""

import json
import secrets
import sqlite3
import time

from flask import (
    Blueprint,
    Response,
    current_app,
    request,
    session,
    stream_with_context,
)

from . import auth, calls, chat, presence, ratelimit

events_bp = Blueprint("events", __name__)

# How long a single stream is held before it returns and the client reconnects.
# Bounds the lifetime of any half-closed socket that slipped past disconnect
# detection and would otherwise pin a worker thread indefinitely.
_MAX_STREAM_SECONDS = 300

# Random extra lifetime added per stream. Without it, every tab that connected
# at server start would recycle in lockstep, producing a synchronised reconnect
# storm every _MAX_STREAM_SECONDS. Spreading recycle times over a window
# de-synchronises them.
_MAX_STREAM_JITTER_SECONDS = 60

# Internal loop cadence. Each tick the stream reads only the shared change
# counter (one cheap single-row SELECT); the expensive per-user collectors run
# only when that counter moved, so this can be small for low latency without
# adding idle query load.
_TICK_SECONDS = 0.1

# Floor on how often the message collector re-queries, even under a burst of
# writes bumping the counter every tick.
_MESSAGE_MIN_INTERVAL = 0.1

# Safety net for the message collector. Messages are otherwise purely
# write-driven (a new row pushes only because the writing request bumped the
# shared counter). A bump that is ever lost — bump_event_signal swallows its
# errors — would otherwise strand the message until some unrelated write woke
# the stream. Re-querying at least this often, even with no observed write,
# bounds that worst case to one interval.
_MESSAGE_RECONCILE_SECONDS = 30.0

# A comment line is sent at least this often so proxies and the browser keep the
# otherwise-idle connection open.
_KEEPALIVE_SECONDS = 15


def _sse(event, data, event_id=None):
    """Format one SSE event frame. *data* must already be a JSON string.

    When *event_id* is given it is emitted as the frame's ``id:``. The browser
    echoes the most recent id back in the ``Last-Event-ID`` header when it
    auto-reconnects, which lets the message stream resume from exactly where it
    left off instead of replaying history (see :func:`events`).
    """
    if event_id is None:
        return "event: {0}\ndata: {1}\n\n".format(event, data)
    return "id: {0}\nevent: {1}\ndata: {2}\n\n".format(event_id, event, data)


def _json_text(view_return):
    """Normalise a Flask view return value to a compact JSON string.

    Views in this project return either a :class:`flask.Response` (from
    ``jsonify``), a bare ``list``/``dict``, or a ``(body, status)`` tuple for
    errors.  Error tuples are reported as ``None`` so the caller skips them.
    """
    if isinstance(view_return, tuple):
        # (body, status) — an error path (forbidden/required); don't push it.
        return None
    if isinstance(view_return, Response):
        return view_return.get_data(as_text=True).rstrip("\n")
    return json.dumps(view_return, separators=(",", ":"))


def _safe_text(collector, *args):
    """Run a collector and return its JSON text, or ``None`` to skip emitting.

    A collector that raises (e.g. a transient SQLite lock) must never tear down
    the whole stream — the next tick simply tries again.
    """
    try:
        return _json_text(collector(*args))
    except Exception:  # noqa: BLE001 — a single bad tick must not kill the stream
        return None


def _safe_messages(channel, user, after):
    """Run the message collector, returning ``[]`` on a transient failure.

    The cursor-based message query is the one collector whose result the loop
    consumes directly (to advance the cursor and build the event id), so it
    can't go through :func:`_safe_text`. It needs the same guarantee, though: a
    single bad tick (e.g. a transient SQLite lock) must not propagate out of the
    generator and tear the whole stream down — the next tick simply tries again.
    """
    try:
        return chat.messages_since(channel, user, after)
    except Exception:  # noqa: BLE001 — a single bad tick must not kill the stream
        return []


def _parse_after(raw):
    """Parse the ``after`` cursor query param the way ``/messages`` does."""
    if not raw or raw.lower() == "nan":
        return 0.0
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _advance_cursor(after, msgs):
    """Advance the message cursor past every timestamp in *msgs*.

    Mirrors the client's ``lastTs`` bookkeeping so an edit or reaction (which
    bumps ``edited_ts`` / ``reactions_ts``) is delivered exactly once.
    """
    for m in msgs:
        for key in ("ts", "edited_ts", "deleted_ts", "reactions_ts"):
            value = m.get(key)
            if value and value > after:
                after = value
    return after


# Collectors: (event name, min-interval seconds, time_driven, fn).
#
# ``min-interval`` caps how often a collector re-runs (so a write storm can't
# query every tick). ``time_driven`` collectors ALSO run without a write, on
# that interval, because their result decays on its own: typing rows expire
# after 5 s, presence goes stale after an hour, and a call ring times out — none
# of which is a database write. Everything else is purely write-driven and runs
# only when the shared change counter moved, so an idle stream issues no
# per-user queries at all.
#
# Channel-independent collectors. Each fn returns a Flask view result; we emit
# only when its JSON changes.
_GLOBAL_COLLECTORS = (
    ("online_users", 1.0, True, chat.online_users),
    ("dms", 0.5, False, chat.dms),
    ("channel_unreads", 0.5, False, chat.channel_unreads),
    ("private_channels", 1.0, False, chat.list_private_channels),
    ("mentions", 1.0, False, chat.mentions),
    ("unread_count", 1.0, False, chat.unread_count),
    ("incoming_calls", 1.0, True, calls.incoming_calls),
)

# Collectors scoped to the stream's current channel.  ``active_screenshares``
# reads ``request.args['channel']`` itself, which the /events URL supplies.
_CHANNEL_COLLECTORS = (
    ("typing", 1.0, True, lambda ch: presence.typing_get(ch)),
    ("read_receipts", 0.5, False, lambda ch: chat.read_receipts(ch)),
    # active_screenshares() reads request.args['channel'] itself; the stream URL
    # carries it, so the channel argument is accepted but unused here.
    ("screenshares", 0.5, False, lambda _ch: calls.active_screenshares()),
)


@events_bp.route("/events")
@auth.login_required
def events():
    """Hold a Server-Sent Events stream open, pushing change-based updates.

    Route: ``GET /events?channel=<channel>&after=<ts>``

    Replaces every interval poller with one connection.  ``channel`` is the tab's
    currently-open channel (the client reconnects with a new value when the user
    switches channels); ``after`` is the client's last-seen message timestamp so
    the stream only sends newer rows.

    Emits named SSE events — ``messages``, ``typing``, ``read_receipts``,
    ``online_users``, ``dms``, ``channel_unreads``, ``private_channels``,
    ``mentions``, ``unread_count``, ``incoming_calls`` and ``screenshares`` —
    each carrying the same JSON the matching REST endpoint returns.

    :returns: A ``text/event-stream`` streaming response.
    :rtype: flask.Response
    """
    user = session["user"]

    # Each held-open stream pins one worker thread for its whole lifetime, so an
    # actor who opens many streams could exhaust the pool and lock everyone out.
    # Cap the number a single user may hold at once; the browser uses one per
    # open tab, so the default ceiling allows plenty of real tabs. A slot is
    # taken here and released in the generator's finally when the stream ends.
    cap_streams = current_app.config.get("RATELIMIT_ENABLED", True)
    if cap_streams and not ratelimit.acquire_stream(user):
        return Response(
            "too many open event streams; close other tabs and retry",
            status=429,
            headers={"Retry-After": "5"},
        )

    channel = request.args.get("channel", "") or ""
    after = _parse_after(request.args.get("after"))
    # On an automatic reconnect the browser re-requests the original URL but
    # also sends back the last id it saw; resume from that cursor so a recycled
    # stream doesn't replay every message since the connection first opened.
    resume = _parse_after(request.headers.get("Last-Event-ID"))
    if resume > after:
        after = resume
    channel_ok = bool(channel) and chat.is_valid_channel(channel, user)

    def generate():
        nonlocal after
        # Tell the browser how long to wait before reconnecting after a drop.
        yield "retry: 3000\n\n"

        # One long-lived connection for the per-tick counter read keeps that hot
        # path off the connect/close cost the view-function collectors pay.
        signal_conn = None
        try:
            signal_conn = sqlite3.connect(presence.PRESENCE_DB)
            signal_conn.execute("PRAGMA journal_mode=WAL")
        except Exception:  # noqa: BLE001 — fall back to per-read connections
            signal_conn = None

        try:
            start = time.monotonic()
            # Per-stream lifetime, jittered so tabs that connected together do
            # not all recycle in the same instant.
            max_seconds = _MAX_STREAM_SECONDS + secrets.randbelow(
                _MAX_STREAM_JITTER_SECONDS + 1
            )
            next_due = {}
            last_sent = {}
            last_keepalive = start
            last_gen = None  # None forces a full initial sweep on the first tick

            while time.monotonic() - start < max_seconds:
                now = time.monotonic()

                # The only work every tick: read the shared change counter. A
                # move means some worker committed a state change; an unchanged
                # value means write-driven collectors can be skipped entirely.
                gen = presence.read_event_signal(signal_conn)
                wrote = last_gen is None or gen != last_gen
                last_gen = gen

                # Messages are cursor-based and write-driven, with a slow
                # time-driven floor (_MESSAGE_RECONCILE_SECONDS) as a safety net
                # against a lost counter bump. _MESSAGE_MIN_INTERVAL still caps
                # how often a write storm can re-query.
                reconcile = now >= next_due.get("messages_floor", 0)
                if (
                    channel_ok
                    and (wrote or reconcile)
                    and now >= next_due.get("messages", 0)
                ):
                    next_due["messages"] = now + _MESSAGE_MIN_INTERVAL
                    next_due["messages_floor"] = now + _MESSAGE_RECONCILE_SECONDS
                    msgs = _safe_messages(channel, user, after)
                    if msgs:
                        after = _advance_cursor(after, msgs)
                        yield _sse(
                            "messages",
                            json.dumps(msgs, separators=(",", ":")),
                            event_id=repr(after),
                        )

                # Channel-scoped state (typing, receipts, screen shares).
                if channel_ok:
                    for name, interval, time_driven, collector in _CHANNEL_COLLECTORS:
                        if (wrote or time_driven) and now >= next_due.get(name, 0):
                            next_due[name] = now + interval
                            text = _safe_text(collector, channel)
                            if text is not None and text != last_sent.get(name):
                                last_sent[name] = text
                                yield _sse(name, text)

                # Global state (presence, sidebar badges, incoming calls).
                for name, interval, time_driven, collector in _GLOBAL_COLLECTORS:
                    if (wrote or time_driven) and now >= next_due.get(name, 0):
                        next_due[name] = now + interval
                        text = _safe_text(collector)
                        if text is not None and text != last_sent.get(name):
                            last_sent[name] = text
                            yield _sse(name, text)

                if now - last_keepalive >= _KEEPALIVE_SECONDS:
                    last_keepalive = now
                    yield ": keep-alive\n\n"

                time.sleep(_TICK_SECONDS)
        finally:
            if signal_conn is not None:
                signal_conn.close()
            if cap_streams:
                ratelimit.release_stream(user)

    headers = {
        "Cache-Control": "no-cache",
        # Disable response buffering on nginx-style proxies so events flush live.
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    }
    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers=headers,
    )
