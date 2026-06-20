"""
minimost.gunicorn_conf
======================

Importable Gunicorn configuration for MiniMost, shipped inside the wheel.

Because this module is part of the installed package, it can be used directly
without a checkout of the source tree::

    gunicorn "minimost:create_app()" -c python:minimost.gunicorn_conf

It sets sensible production defaults (bind address, the ``gthread`` worker
model required by the SSE push stream, access-log filtering for the
high-frequency call and ``/events`` endpoints) and provisions TLS via
:func:`minimost.certs.ensure_certs`, generating ``ca.pem``/``cert.pem`` in the
current working directory on first run.

The repository's top-level ``gunicorn.conf.py`` is a thin shim that re-exports
everything here, so running from a source checkout behaves identically.
"""

import logging
import multiprocessing
import re as _re
from minimost.certs import ensure_certs

# --------------------------------------------------------------------
# Server socket
# --------------------------------------------------------------------
bind = "0.0.0.0:6767"
# If behind nginx, use a unix socket instead:
# bind = "unix:/run/gunicorn.sock"

# --------------------------------------------------------------------
# Workers
# --------------------------------------------------------------------
# The SSE push stream (minimost.events) holds one connection open per browser
# tab for its whole lifetime, so MiniMost runs Gunicorn's threaded worker:
# each held stream parks one thread, and concurrent-tab capacity is
# ``workers * threads``. ``gthread`` ships inside Gunicorn — this is a
# worker-class change, NOT a new dependency. Size ``threads`` to the peak number
# of simultaneously-connected tabs plus headroom for the short
# send/typing/presence requests; the defaults below comfortably fit a small
# private-LAN deployment (cpu_count workers x 100 threads of held streams).
worker_class = "gthread"
workers = max(2, multiprocessing.cpu_count())
threads = 100
# Generous so a worker whose threads are busy holding streams is not reaped;
# gthread's arbiter heartbeat runs off the request threads, so long-lived
# streams don't trip the timeout the way a blocking sync worker would.
timeout = 120
keepalive = 2

# --------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------
loglevel = "info"

accesslog = "-"  # stdout (systemd captures this)
errorlog = "-"  # stderr

# Or file-based logging:
# accesslog = "/var/log/gunicorn/access.log"
# errorlog = "/var/log/gunicorn/error.log"


class _SuppressCallPolling(logging.Filter):
    """Drop access-log lines for the high-frequency / long-lived endpoints.

    During an active call, /calls/<id>/media and /calls/<id>/state are hit
    multiple times per second by every participant.  The /events SSE stream is
    opened (and reconnected every few minutes) by every browser tab.  Logging
    each request floods stdout and adds unnecessary I/O on the worker threads.
    """

    _RE = _re.compile(r"/calls/[^/ ]+/(?:media|state)\b|/calls/incoming\b|/events\b")

    def filter(self, record: logging.LogRecord) -> bool:
        return not self._RE.search(record.getMessage())


def on_starting(_server) -> None:  # noqa: ANN001
    logging.getLogger("gunicorn.access").addFilter(_SuppressCallPolling())


# --------------------------------------------------------------------
# Process naming
# --------------------------------------------------------------------
proc_name = "gunicorn-flask-app"

# --------------------------------------------------------------------
# Security / misc
# --------------------------------------------------------------------
preload_app = True
# Recycling a worker after N requests would drop every SSE stream it is holding
# at once (each stream is a single, very long-lived request), causing a
# reconnect storm. Disable request-count recycling; streams self-recycle every
# 5 minutes instead (see minimost.events._MAX_STREAM_SECONDS).
max_requests = 0
max_requests_jitter = 0

# --------------------------------------------------------------------
# Paths (set to your data directory where databases and uploads live)
# --------------------------------------------------------------------
# chdir = "/srv/minimost"

# --------------------------------------------------------------------
# TLS / HTTPS  (required for WebRTC calling)
# --------------------------------------------------------------------
# A local CA and a server certificate signed by it are generated automatically
# on first run in pure Python (stdlib only, no openssl binary; see
# minimost.certs). The leaf renews itself; clients import ca.pem once. If
# generation fails a warning is printed and gunicorn starts without TLS (calls
# will not work in that case).
_cert, _key = ensure_certs()

if _cert and _key:
    certfile = str(_cert)
    keyfile = str(_key)
else:
    import sys

    print(
        "WARNING: Running without TLS — calls will not work without HTTPS.",
        file=sys.stderr,
    )
