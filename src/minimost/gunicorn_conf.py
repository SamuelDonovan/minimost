"""
minimost.gunicorn_conf
======================

Importable Gunicorn configuration for MiniMost, shipped inside the wheel.

Because this module is part of the installed package, it can be used directly
without a checkout of the source tree::

    gunicorn "minimost:create_app()" -c python:minimost.gunicorn_conf

It sets sensible production defaults (bind address, worker count, access-log
filtering for the high-frequency call endpoints) and provisions TLS via
:func:`minimost.certs.ensure_certs`, generating ``ca.pem``/``cert.pem`` in the
current working directory on first run.

The repository's top-level ``gunicorn.conf.py`` is a thin shim that re-exports
everything here, so running from a source checkout behaves identically.
"""

import logging
import multiprocessing
import re as _re
from pathlib import Path

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
workers = multiprocessing.cpu_count() * 2 + 1
worker_class = "sync"
threads = 1
timeout = 30
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
    """Drop access-log lines for the high-frequency call-media endpoints.

    During an active call, /calls/<id>/media and /calls/<id>/state are hit
    multiple times per second by every participant.  Logging each request
    floods stdout and adds unnecessary I/O on the worker threads.
    """

    _RE = _re.compile(r"/calls/[^/ ]+/(?:media|state)\b|/calls/incoming\b")

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
max_requests = 1000
max_requests_jitter = 50

# --------------------------------------------------------------------
# Paths (set to your data directory where databases and uploads live)
# --------------------------------------------------------------------
# chdir = "/srv/minimost"

# --------------------------------------------------------------------
# TLS / HTTPS  (required for WebRTC calling)
# --------------------------------------------------------------------
# A local CA and a server certificate signed by it are generated automatically
# on first run using the system openssl binary (see minimost.certs). The leaf
# renews itself; clients import ca.pem once. If generation fails a warning is
# printed and gunicorn starts without TLS (calls will not work in that case).
_cert, _key = ensure_certs(Path.cwd())

if _cert and _key:
    certfile = str(_cert)
    keyfile = str(_key)
else:
    import sys

    print(
        "WARNING: Running without TLS — calls will not work without HTTPS.",
        file=sys.stderr,
    )
