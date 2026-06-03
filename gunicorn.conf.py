# gunicorn.conf.py
import multiprocessing
import os
import shutil
import socket
import subprocess  # nosec B404
import sys
import tempfile

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

import logging
import re as _re


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
pythonpath = "src"

# --------------------------------------------------------------------
# TLS / HTTPS  (required for WebRTC calling)
# --------------------------------------------------------------------
# Certificates are generated automatically on first run using the system
# openssl binary.  If generation fails a warning is printed and gunicorn
# starts without TLS (calls will not work in that case).


def _generate_certs(cert_path, key_path):
    openssl_bin = shutil.which("openssl")
    if not openssl_bin:
        print(
            "WARNING: openssl not found on PATH; cannot generate TLS certificates.\n"
            "WARNING: Calls will not work without HTTPS. Install openssl and restart.",
            file=sys.stderr,
        )
        return False

    hostname = socket.gethostname()
    try:
        local_ip = socket.gethostbyname(hostname)
    except socket.gaierror:
        local_ip = None

    san_parts = ["DNS:localhost", f"DNS:{hostname}", "IP:127.0.0.1"]
    if local_ip and local_ip != "127.0.0.1":
        san_parts.append(f"IP:{local_ip}")
    san = ",".join(san_parts)

    openssl_conf = (
        "[req]\n"
        "distinguished_name = req_dn\n"
        "x509_extensions   = v3_req\n"
        "prompt            = no\n"
        "\n"
        "[req_dn]\n"
        "CN = minimost\n"
        "\n"
        "[v3_req]\n"
        f"subjectAltName = {san}\n"
    )

    with tempfile.NamedTemporaryFile(mode="w", suffix=".cnf", delete=False) as tmp:
        tmp.write(openssl_conf)
        conf_path = tmp.name

    try:
        result = subprocess.run(  # nosec B603
            [
                openssl_bin,
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-keyout",
                key_path,
                "-out",
                cert_path,
                "-days",
                "3650",
                "-nodes",
                "-config",
                conf_path,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )
    finally:
        os.unlink(conf_path)

    if result.returncode != 0:
        print(
            "WARNING: Failed to generate TLS certificates.\n"
            f"WARNING: {result.stderr.strip()}\n"
            "WARNING: Calls will not work without HTTPS.",
            file=sys.stderr,
        )
        return False

    print(f"Generated TLS certificates ({cert_path}, {key_path}).")
    return True


_cert_path = "cert.pem"
_key_path = "key.pem"

if not (os.path.exists(_cert_path) and os.path.exists(_key_path)):
    _generate_certs(_cert_path, _key_path)

if os.path.exists(_cert_path) and os.path.exists(_key_path):
    certfile = _cert_path
    keyfile = _key_path
else:
    print(
        "WARNING: Running without TLS — calls will not work without HTTPS.",
        file=sys.stderr,
    )

# --------------------------------------------------------------------
# Environment variables (optional)
# --------------------------------------------------------------------
