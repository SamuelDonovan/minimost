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


# Validity (days) for the served leaf certificate. Chrome rejects any TLS
# server certificate valid for more than 398 days with
# NET::ERR_CERT_VALIDITY_TOO_LONG, regardless of whether it is trusted.
_LEAF_DAYS = "398"
# The local CA is a trust anchor, not a server cert, so the 398-day cap does not
# apply. Making it long-lived means it only has to be imported into the browser
# once; the leaf it signs renews silently in the background.
_CA_DAYS = "3650"
# Regenerate the leaf when it is within this many seconds of expiry, so a plain
# restart renews it against the already-trusted CA without any browser action.
_LEAF_RENEW_BEFORE = str(30 * 24 * 60 * 60)


def _build_san():
    """Build the subjectAltName string covering every name clients may use."""
    hostname = socket.gethostname()
    fqdn = socket.getfqdn()
    try:
        local_ip = socket.gethostbyname(hostname)
    except socket.gaierror:
        local_ip = None

    # Include the FQDN alongside the short hostname so the certificate matches
    # whichever name clients use to reach the server. A name mismatch keeps the
    # browser on "Not secure", which prevents an installed PWA from hiding the
    # URL bar.
    dns_names = []
    for name in ("localhost", hostname, fqdn):
        if name and name not in dns_names:
            dns_names.append(name)
    # The Avahi/mDNS ".local" name (e.g. "archlinux.local") is how LAN clients
    # usually reach the server, but it is served by mDNS rather than the system
    # FQDN, so socket.getfqdn() never reports it. Add it explicitly.
    if hostname and "." not in hostname:
        mdns_name = f"{hostname}.local"
        if mdns_name not in dns_names:
            dns_names.append(mdns_name)
    san_parts = [f"DNS:{name}" for name in dns_names]
    san_parts.append("IP:127.0.0.1")
    if local_ip and local_ip != "127.0.0.1":
        san_parts.append(f"IP:{local_ip}")
    return ",".join(san_parts)


def _run_openssl(openssl_bin, args):
    return subprocess.run(  # nosec B603
        [openssl_bin, *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )


def _write_tmp_conf(text):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".cnf", delete=False) as tmp:
        tmp.write(text)
        return tmp.name


def _generate_ca(openssl_bin, ca_cert, ca_key):
    """Create the long-lived local CA that signs the served leaf cert."""
    ca_conf = (
        "[req]\n"
        "distinguished_name = req_dn\n"
        "x509_extensions   = v3_ca\n"
        "prompt            = no\n"
        "\n"
        "[req_dn]\n"
        "CN = MiniMost local CA\n"
        "\n"
        "[v3_ca]\n"
        # CA:TRUE makes this importable into a browser/OS trust store as an
        # authority; keyCertSign lets it sign the leaf served by gunicorn.
        "basicConstraints = critical, CA:TRUE\n"
        "keyUsage = critical, keyCertSign, cRLSign\n"
    )
    conf_path = _write_tmp_conf(ca_conf)
    try:
        return _run_openssl(
            openssl_bin,
            [
                "req", "-x509", "-newkey", "rsa:2048",
                "-keyout", ca_key, "-out", ca_cert,
                "-days", _CA_DAYS, "-nodes", "-config", conf_path,
            ],
        )
    finally:
        os.unlink(conf_path)


def _generate_leaf(openssl_bin, cert_path, key_path, ca_cert, ca_key):
    """Create a short-lived leaf cert signed by the local CA."""
    leaf_conf = (
        "[req]\n"
        "distinguished_name = req_dn\n"
        "req_extensions    = v3_req\n"
        "prompt            = no\n"
        "\n"
        "[req_dn]\n"
        "CN = minimost\n"
        "\n"
        "[v3_req]\n"
        # A leaf, not a CA. serverAuth + the SAN are what Chrome validates.
        "basicConstraints = critical, CA:FALSE\n"
        "keyUsage = critical, digitalSignature, keyEncipherment\n"
        "extendedKeyUsage = serverAuth\n"
        f"subjectAltName = {_build_san()}\n"
    )
    conf_path = _write_tmp_conf(leaf_conf)
    # openssl writes the CSR here; create the temp name up front so we can clean
    # it up regardless of where generation fails.
    csr_path = _write_tmp_conf("")
    try:
        csr = _run_openssl(
            openssl_bin,
            [
                "req", "-newkey", "rsa:2048",
                "-keyout", key_path, "-out", csr_path,
                "-nodes", "-config", conf_path,
            ],
        )
        if csr.returncode != 0:
            return csr
        # The SAN/EKU live in the config, not the CSR, so they must be re-applied
        # via -extfile/-extensions when the CA signs the leaf.
        return _run_openssl(
            openssl_bin,
            [
                "x509", "-req", "-in", csr_path,
                "-CA", ca_cert, "-CAkey", ca_key, "-CAcreateserial",
                "-out", cert_path, "-days", _LEAF_DAYS,
                "-extfile", conf_path, "-extensions", "v3_req",
            ],
        )
    finally:
        os.unlink(conf_path)
        os.unlink(csr_path)


def _ensure_tls(cert_path, key_path, ca_cert, ca_key):
    """Ensure a CA-signed leaf cert exists, renewing it as needed.

    A long-lived local CA (``ca.pem``) is imported into the browser once; the
    leaf cert served by gunicorn is signed by it and silently regenerated when
    missing, foreign, or near expiry — so renewals never need a re-import.

    :returns: ``True`` if ``cert_path``/``key_path`` are ready to serve.
    """
    # Respect a user-supplied (or legacy self-signed) cert: if a leaf is present
    # but MiniMost's own CA is not, leave the files untouched. Delete cert.pem /
    # key.pem to opt into the managed local-CA model.
    have_leaf = os.path.exists(cert_path) and os.path.exists(key_path)
    have_ca = os.path.exists(ca_cert) and os.path.exists(ca_key)
    if have_leaf and not have_ca:
        return True

    openssl_bin = shutil.which("openssl")
    if not openssl_bin:
        print(
            "WARNING: openssl not found on PATH; cannot generate TLS certificates.\n"
            "WARNING: Calls will not work without HTTPS. Install openssl and restart.",
            file=sys.stderr,
        )
        return False

    ca_created = False
    if not (os.path.exists(ca_cert) and os.path.exists(ca_key)):
        result = _generate_ca(openssl_bin, ca_cert, ca_key)
        if result.returncode != 0:
            print(
                "WARNING: Failed to generate the local CA.\n"
                f"WARNING: {result.stderr.strip()}\n"
                "WARNING: Calls will not work without HTTPS.",
                file=sys.stderr,
            )
            return False
        ca_created = True

    need_leaf = ca_created or not (
        os.path.exists(cert_path) and os.path.exists(key_path)
    )
    if not need_leaf:
        # Regenerate if the leaf no longer chains to the CA (e.g. left over from
        # the older self-signed setup) or is inside the renewal window.
        verify = _run_openssl(openssl_bin, ["verify", "-CAfile", ca_cert, cert_path])
        checkend = _run_openssl(
            openssl_bin,
            ["x509", "-checkend", _LEAF_RENEW_BEFORE, "-noout", "-in", cert_path],
        )
        need_leaf = verify.returncode != 0 or checkend.returncode != 0

    if need_leaf:
        result = _generate_leaf(openssl_bin, cert_path, key_path, ca_cert, ca_key)
        if result.returncode != 0:
            print(
                "WARNING: Failed to generate the TLS leaf certificate.\n"
                f"WARNING: {result.stderr.strip()}\n"
                "WARNING: Calls will not work without HTTPS.",
                file=sys.stderr,
            )
            return False
        print(f"Generated TLS leaf certificate ({cert_path}, {key_path}).")

    if ca_created:
        print(
            f"\nA local certificate authority was created at {os.path.abspath(ca_cert)}.\n"
            "Import THIS file into your browser's trusted certificates once\n"
            "(Chrome: Manage certificates > Local certificates > Trusted Certificates).\n"
            "The served leaf cert renews automatically and never needs re-importing\n"
            "as long as this CA stays trusted.\n",
            file=sys.stderr,
        )

    return True


_cert_path = "cert.pem"
_key_path = "key.pem"
_ca_cert_path = "ca.pem"
_ca_key_path = "ca-key.pem"

_ensure_tls(_cert_path, _key_path, _ca_cert_path, _ca_key_path)

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
