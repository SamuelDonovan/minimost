"""
minimost.ratelimit
===================

Dependency-free, in-process abuse throttling for MiniMost.

This module provides the two primitives the application uses to blunt
denial-of-service (DoS) attempts from authenticated and unauthenticated clients
alike, using nothing beyond the Python standard library and Flask:

* :class:`RateLimiter` — a thread-safe **sliding-window** counter.  Each call to
  :meth:`RateLimiter.hit` records one event against a key (an IP address or a
  username) and reports whether that key has exceeded its allowance over the
  trailing window.  The :func:`rate_limit` decorator wraps a Flask view with
  this check so a flood of requests to expensive endpoints (login, signup,
  message send, uploads) is rejected with ``429 Too Many Requests`` instead of
  tying up workers or CPU.

* :class:`ConcurrencyLimiter` — a thread-safe count of *currently held*
  resources per key.  It backs the cap on simultaneous Server-Sent Events
  streams per user (:mod:`minimost.events`), so one actor cannot pin every
  worker thread by opening connections that never close.

Scope and limitations
----------------------
The counters live **in the worker process**, so with several Gunicorn workers
the effective ceiling is ``limit × workers``.  That is deliberate: the goal is
to stop pathological abuse cheaply with zero new dependencies and no shared
store on the hot path, not to enforce a globally exact quota.  For a hard,
cross-worker ceiling, put a reverse proxy in front (e.g. Nginx ``limit_req`` /
``limit_conn``); these in-process limits complement that layer rather than
replace it.

Configuration
-------------
Limits are generous by default — tuned so ordinary interactive use never trips
them — and can be overridden in ``settings.json`` (re-read, cached by mtime, so
edits take effect without a restart):

* ``rate_limit_enabled`` — master on/off switch (default ``true``).  Read once
  in :func:`minimost.create_app` into ``app.config["RATELIMIT_ENABLED"]``.
* ``rate_limits`` — an object mapping an action name to a ``[max, window_seconds]``
  pair, overriding the matching entry in :data:`DEFAULT_LIMITS`.
* ``max_event_streams_per_user`` — the per-user concurrent ``/events`` cap
  (default :data:`DEFAULT_MAX_EVENT_STREAMS`).
"""

import json
import threading
import time as _time
from collections import deque
from functools import wraps
from pathlib import Path

from flask import Response, current_app, request, session

# Default per-action limits as ``name -> (max_events, window_seconds)``.  These
# are intentionally high: a normal person logs in occasionally, signs up once,
# and chats in bursts well below these rates.  They exist only to cap abuse.
#
#   login          60/min  per IP   — credential brute-force is additionally
#                                      bounded per-account by the lockout in
#                                      minimost.auth; this caps CPU/thread abuse.
#   signup         20/hour per IP   — account-creation flood (the classic
#                                      "make many accounts" DoS).
#   password_reset 30/hour per IP   — another PBKDF2-hashing endpoint.
#   send          240/min  per user — message + attachment flood (4/s sustained).
#   avatar         60/hour per user — avatar upload churn.
#   create_channel 60/hour per user — private-channel creation spam.
DEFAULT_LIMITS = {
    "login": (60, 60),
    "signup": (20, 3600),
    "password_reset": (30, 3600),
    "send": (240, 60),
    "avatar": (60, 3600),
    "create_channel": (60, 3600),
}

# Default cap on concurrently-open /events SSE streams per user. A browser holds
# one stream per open tab, so this allows a comfortable dozen tabs while still
# stopping a single actor from pinning every worker thread.
DEFAULT_MAX_EVENT_STREAMS = 12

# Keys with no recorded event newer than this many seconds are dropped during an
# occasional sweep so the counter dict cannot grow without bound as clients
# churn. It must be at least as large as the longest configured window so a
# still-relevant key is never discarded.
_GC_HORIZON_SECONDS = 3600

# settings.json is bundled inside the package (src/minimost/); _HERE is the
# package directory.
_HERE = Path(__file__).resolve().parent
_SETTINGS_FILE = _HERE / "settings.json"


class RateLimiter:
    """A thread-safe sliding-window rate limiter keyed by arbitrary strings.

    Each key maps to a :class:`collections.deque` of monotonic timestamps for
    the events seen within the trailing window; expired timestamps are evicted
    lazily on the next :meth:`hit`.  All state is in-process and guarded by a
    single lock, so the limiter is safe to share across Gunicorn ``gthread``
    worker threads.
    """

    def __init__(self):
        self._events = {}
        self._lock = threading.Lock()
        self._ops = 0

    def hit(self, key, limit, window):
        """Record one event for *key* and report whether it is allowed.

        :param key: The identity being limited (e.g. ``"login:1.2.3.4"``).
        :param limit: Maximum number of events permitted within *window*.
        :param window: Trailing window length in seconds.
        :returns: ``(allowed, retry_after)`` — *allowed* is ``False`` when the
            key has already reached *limit* events in the window (the event is
            **not** recorded in that case), and *retry_after* is a whole-second
            hint for the ``Retry-After`` header (``0`` when allowed).
        :rtype: tuple[bool, int]
        """
        now = _time.monotonic()
        cutoff = now - window
        with self._lock:
            self._ops += 1
            if self._ops % 4096 == 0:
                self._gc(now)
            dq = self._events.get(key)
            if dq is None:
                dq = deque()
                self._events[key] = dq
            while dq and dq[0] <= cutoff:
                dq.popleft()
            if len(dq) >= limit:
                retry = window - (now - dq[0])
                return False, max(1, int(retry) + 1)
            dq.append(now)
            return True, 0

    def _gc(self, now):
        """Drop keys idle longer than the GC horizon. Caller holds the lock."""
        horizon = now - _GC_HORIZON_SECONDS
        stale = [k for k, dq in self._events.items() if not dq or dq[-1] <= horizon]
        for k in stale:
            del self._events[k]

    def reset(self):
        """Forget all recorded events (used between tests)."""
        with self._lock:
            self._events.clear()
            self._ops = 0


class ConcurrencyLimiter:
    """A thread-safe count of currently-held resources per key.

    Unlike :class:`RateLimiter`, which counts events over time, this tracks how
    many resources (e.g. open SSE streams) a key holds *right now*:
    :meth:`acquire` takes a slot if one is free and :meth:`release` returns it.
    """

    def __init__(self):
        self._counts = {}
        self._lock = threading.Lock()

    def acquire(self, key, limit):
        """Take a slot for *key* if fewer than *limit* are held.

        :returns: ``True`` if a slot was acquired, ``False`` if *key* is already
            at *limit*.
        :rtype: bool
        """
        with self._lock:
            held = self._counts.get(key, 0)
            if held >= limit:
                return False
            self._counts[key] = held + 1
            return True

    def release(self, key):
        """Return a previously acquired slot for *key* (never goes negative)."""
        with self._lock:
            held = self._counts.get(key, 0)
            if held <= 1:
                self._counts.pop(key, None)
            else:
                self._counts[key] = held - 1

    def reset(self):
        """Forget all held slots (used between tests)."""
        with self._lock:
            self._counts.clear()


# Process-wide singletons shared by every request thread.
_rate_limiter = RateLimiter()
_stream_limiter = ConcurrencyLimiter()

# settings.json cache, refreshed when the file's mtime changes so the hot paths
# (e.g. /send) do not re-parse the file on every request.
_settings_cache = {"mtime": None, "data": {}}


def reset_all():
    """Reset both limiters. Intended for test isolation."""
    _rate_limiter.reset()
    _stream_limiter.reset()


def _load_settings():
    """Return parsed ``settings.json``, cached by file mtime.

    Any read or parse error yields an empty dict so callers fall back to the
    built-in defaults.
    """
    try:
        mtime = _SETTINGS_FILE.stat().st_mtime
    except OSError:
        return {}
    if _settings_cache["mtime"] != mtime:
        try:
            _settings_cache["data"] = json.loads(_SETTINGS_FILE.read_text())
        except (OSError, ValueError):
            _settings_cache["data"] = {}
        _settings_cache["mtime"] = mtime
    return _settings_cache["data"]


def _is_number(value):
    """True for a real int/float (rejecting ``bool``, which is an ``int``)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def limit_for(name):
    """Return the ``(max_events, window_seconds)`` limit for action *name*.

    Falls back to :data:`DEFAULT_LIMITS` when no valid override is present in the
    ``rate_limits`` object of ``settings.json``.
    """
    limit, window = DEFAULT_LIMITS[name]
    overrides = _load_settings().get("rate_limits")
    if isinstance(overrides, dict):
        spec = overrides.get(name)
        if (
            isinstance(spec, (list, tuple))
            and len(spec) == 2
            and _is_number(spec[0])
            and spec[0] > 0
            and _is_number(spec[1])
            and spec[1] > 0
        ):
            limit, window = int(spec[0]), float(spec[1])
    return limit, window


def max_event_streams():
    """Return the per-user concurrent ``/events`` cap from settings (or default)."""
    value = _load_settings().get("max_event_streams_per_user")
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return DEFAULT_MAX_EVENT_STREAMS


def _enabled():
    """True unless the app has disabled limiting via ``RATELIMIT_ENABLED``."""
    try:
        return current_app.config.get("RATELIMIT_ENABLED", True)
    except RuntimeError:  # no application context (e.g. a bare unit test)
        return True


def client_ip():
    """Return the remote address for the current request, or ``"unknown"``.

    Behind a reverse proxy this is the proxy's address unless the proxy is
    configured to forward the real client IP and the app is set up to trust it;
    see the deployment docs.
    """
    return request.remote_addr or "unknown"


def rate_limit_message(retry_after):
    """Return a friendly 'slow down' message naming the wait in whole seconds.

    Shared by every throttled response (plain text, rendered HTML, and JSON) so
    the wording the user sees is identical however the route reports the limit.
    """
    seconds = max(1, int(retry_after))
    unit = "second" if seconds == 1 else "seconds"
    return "You're doing that too quickly. Please wait {0} {1} and try again.".format(
        seconds, unit
    )


def _too_many(retry_after):
    """Build the default plain-text ``429`` response with a ``Retry-After`` header."""
    return Response(
        rate_limit_message(retry_after),
        status=429,
        headers={"Retry-After": str(retry_after)},
    )


def rate_limit(name, by="ip", on_limit=None):
    """Decorate a Flask view so calls to it are throttled per *name*.

    :param name: Key into :data:`DEFAULT_LIMITS` (and the ``rate_limits``
        settings override) selecting this endpoint's allowance.
    :param by: ``"ip"`` to key the limit on the client IP (for unauthenticated
        endpoints like login/signup), or ``"user"`` to key it on the logged-in
        username, falling back to the IP when there is no session.
    :param on_limit: Optional callable ``on_limit(retry_after)`` returning the
        Flask response to send when the limit is hit, instead of the default
        plain-text ``429``. Use it to surface the limit the way the caller
        expects — a re-rendered HTML form with an inline error, or a JSON error
        for a ``fetch`` endpoint. :func:`rate_limit_message` builds the standard
        wording, and callers should keep the ``429`` status and ``Retry-After``
        header (e.g. ``(render_template(...), 429, {"Retry-After": str(r)})``).
    :returns: The wrapped view, which returns ``429`` once the limit is hit and
        otherwise calls through unchanged.  Limiting is skipped entirely when
        ``app.config["RATELIMIT_ENABLED"]`` is false.

    Apply it *below* :func:`minimost.auth.login_required` so authenticated
    ``by="user"`` endpoints see the established session::

        @chat_bp.route("/send/<channel>", methods=["POST"])
        @auth.login_required
        @ratelimit.rate_limit("send", by="user")
        def send(channel):
            ...
    """

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if _enabled():
                if by == "user":
                    ident = session.get("user") or client_ip()
                else:
                    ident = client_ip()
                limit, window = limit_for(name)
                allowed, retry = _rate_limiter.hit(
                    "{0}:{1}".format(name, ident), limit, window
                )
                if not allowed:
                    if on_limit is not None:
                        return on_limit(retry)
                    return _too_many(retry)
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def acquire_stream(user):
    """Try to take an ``/events`` stream slot for *user*.

    :returns: ``True`` if the user is below the concurrent-stream cap (a slot is
        now held and must be released with :func:`release_stream`), ``False`` if
        they are already at the cap.
    :rtype: bool
    """
    return _stream_limiter.acquire("events:{0}".format(user), max_event_streams())


def release_stream(user):
    """Release an ``/events`` stream slot previously taken for *user*."""
    _stream_limiter.release("events:{0}".format(user))
