"""
minimost.__main__
=================

Command-line entry point for the MiniMost development server.

This module is invoked either through the ``minimost`` console script
installed by ``pip``, or directly with ``python -m minimost``.  It parses
command-line arguments and starts the Flask built-in WSGI server.

.. note::

   The built-in server is intended for **development and small private
   networks** only.  For production use, run MiniMost behind Gunicorn or
   another WSGI server — see :doc:`/deployment`.

Usage::

    # Default: binds to 127.0.0.1:5000
    minimost

    # Accessible from the local network on port 8080
    minimost --host 0.0.0.0 --port 8080

    # Equivalent without installation
    python -m minimost --host 0.0.0.0 --port 8080

    # Generate a password reset URL for a user (admin command)
    minimost reset-password <username> [--expires MINUTES] [--base-url URL]
"""

import argparse
import os
import secrets
import sqlite3
import sys
import time
from pathlib import Path

from minimost import create_app

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _ensure_certs():
    """Ensure a CA-signed TLS leaf cert exists in the project root.

    A long-lived local CA (``ca.pem``) is generated once and imported into the
    browser's trusted certificates by the user.  The leaf cert served by the
    dev server (``cert.pem``) is signed by that CA and silently regenerated
    when missing, foreign, or near expiry, so renewals never need a re-import.
    The leaf covers ``localhost``, the machine's short hostname, its FQDN, its
    Avahi/mDNS ``.local`` name, and its local IP via Subject Alternative Names.

    Chrome rejects any server certificate valid for more than 398 days, so the
    leaf is capped there; the CA, being a trust anchor rather than a server
    cert, is exempt and made long-lived.

    :returns: ``(cert_path, key_path)`` as :class:`pathlib.Path` objects on
        success, or ``(None, None)`` if generation is skipped or fails.  In
        the failure case a warning is printed to stderr but the caller should
        continue running without TLS.
    :rtype: tuple[Path, Path] | tuple[None, None]
    """
    import shutil
    import socket
    import subprocess  # nosec B404
    import tempfile

    cert_path = _PROJECT_ROOT / "cert.pem"
    key_path = _PROJECT_ROOT / "key.pem"
    ca_cert = _PROJECT_ROOT / "ca.pem"
    ca_key = _PROJECT_ROOT / "ca-key.pem"

    # Respect a user-supplied (or legacy self-signed) cert: if a leaf is present
    # but MiniMost's own CA is not, leave the files untouched. Delete cert.pem /
    # key.pem to opt into the managed local-CA model.
    if cert_path.exists() and key_path.exists() and not (
        ca_cert.exists() and ca_key.exists()
    ):
        return cert_path, key_path

    openssl_bin = shutil.which("openssl")
    if not openssl_bin:
        print(
            "WARNING: openssl not found on PATH; cannot generate TLS certificates.\n"
            "WARNING: Calls will not work without HTTPS. Install openssl and restart.",
            file=sys.stderr,
        )
        return None, None

    def run(args):
        return subprocess.run(  # nosec B603
            [openssl_bin, *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )

    def write_tmp(text):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".cnf", delete=False) as tmp:
            tmp.write(text)
            return tmp.name

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
    san = ",".join(san_parts)

    # --- Ensure the long-lived local CA exists (import-once trust anchor) ---
    ca_created = False
    if not (ca_cert.exists() and ca_key.exists()):
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
            # CA:TRUE makes this importable as an authority; keyCertSign lets it
            # sign the leaf served by the dev server.
            "basicConstraints = critical, CA:TRUE\n"
            "keyUsage = critical, keyCertSign, cRLSign\n"
        )
        conf_path = write_tmp(ca_conf)
        try:
            result = run(
                [
                    "req", "-x509", "-newkey", "rsa:2048",
                    "-keyout", str(ca_key), "-out", str(ca_cert),
                    "-days", "3650", "-nodes", "-config", conf_path,
                ]
            )
        finally:
            os.unlink(conf_path)
        if result.returncode != 0:
            print(
                "WARNING: Failed to generate the local CA.\n"
                f"WARNING: {result.stderr.strip()}\n"
                "WARNING: Calls will not work without HTTPS.",
                file=sys.stderr,
            )
            return None, None
        ca_created = True

    # --- Decide whether the leaf needs (re)generating ---
    need_leaf = ca_created or not (cert_path.exists() and key_path.exists())
    if not need_leaf:
        # Regenerate if the leaf no longer chains to the CA (e.g. left over from
        # the older self-signed setup) or expires within 30 days.
        verify = run(["verify", "-CAfile", str(ca_cert), str(cert_path)])
        checkend = run(
            ["x509", "-checkend", str(30 * 24 * 60 * 60), "-noout", "-in", str(cert_path)]
        )
        need_leaf = verify.returncode != 0 or checkend.returncode != 0

    if need_leaf:
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
            f"subjectAltName = {san}\n"
        )
        conf_path = write_tmp(leaf_conf)
        csr_path = write_tmp("")
        try:
            csr = run(
                [
                    "req", "-newkey", "rsa:2048",
                    "-keyout", str(key_path), "-out", csr_path,
                    "-nodes", "-config", conf_path,
                ]
            )
            # The SAN/EKU live in the config, not the CSR, so they must be
            # re-applied via -extfile/-extensions when the CA signs the leaf.
            # Chrome caps server certs at 398 days, so the leaf stays under it.
            result = (
                csr
                if csr.returncode != 0
                else run(
                    [
                        "x509", "-req", "-in", csr_path,
                        "-CA", str(ca_cert), "-CAkey", str(ca_key), "-CAcreateserial",
                        "-out", str(cert_path), "-days", "398",
                        "-extfile", conf_path, "-extensions", "v3_req",
                    ]
                )
            )
        finally:
            os.unlink(conf_path)
            os.unlink(csr_path)
        if result.returncode != 0:
            print(
                "WARNING: Failed to generate the TLS leaf certificate.\n"
                f"WARNING: {result.stderr.strip()}\n"
                "WARNING: Calls will not work without HTTPS.",
                file=sys.stderr,
            )
            return None, None
        print(f"Generated TLS leaf certificate (cert.pem, key.pem) in {_PROJECT_ROOT}.")

    if ca_created:
        print(
            f"\nA local certificate authority was created at {ca_cert}.\n"
            "Import THIS file into your browser's trusted certificates once\n"
            "(Chrome: Manage certificates > Local certificates > Trusted Certificates).\n"
            "The served leaf cert renews automatically and never needs re-importing\n"
            "as long as this CA stays trusted.",
            file=sys.stderr,
        )

    return cert_path, key_path


def main():
    """Parse arguments and dispatch to the appropriate command.

    With no subcommand (or unrecognised first argument), starts the MiniMost
    development server.  Pass ``reset-password`` as the first argument to
    generate a password reset URL instead.

    Command-line arguments (server mode):

    ``--host`` : str, optional
        The IP address or hostname to bind to.  Defaults to ``127.0.0.1``
        (loopback only).  Use ``0.0.0.0`` to accept connections on all
        network interfaces.

    ``--port`` : int, optional
        The TCP port to listen on.  Defaults to ``5000``.

    :raises SystemExit: If unrecognised arguments are passed.
    """
    if len(sys.argv) > 1 and sys.argv[1] == "reset-password":
        _cmd_reset_password(sys.argv[2:])
        return

    parser = argparse.ArgumentParser(
        description="Run the MiniMost server",
        epilog=(
            "Admin commands (run without starting the server):\n"
            "  minimost reset-password <username> [--expires MINUTES] [--base-url URL]\n"
            "                        Generate a one-time password reset URL for a user\n"
            "\n"
            "Run 'minimost reset-password --help' for details."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--host", default="127.0.0.1", help="Address to listen on (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--port", type=int, default=5000, help="Port to listen on (default: 5000)"
    )
    args = parser.parse_args()

    cert, key = _ensure_certs()
    ssl_context = (str(cert), str(key)) if cert else None

    app = create_app()
    app.run(host=args.host, port=args.port, debug=False, ssl_context=ssl_context)


def _send_reset_dm(username: str, expires_minutes: int) -> None:
    """Insert a system notification DM into the user's message database."""
    from minimost.common import user_db_path

    db_path = user_db_path(username)
    if not db_path.exists():
        return
    channel = "dm:" + ":".join(sorted(["system", username]))
    minutes_word = "minute" if expires_minutes == 1 else "minutes"
    message = (
        f"A password reset has been requested for your account. "
        f"The reset link will expire in {expires_minutes} {minutes_word}. "
        f"If you did not request this, please contact your administrators."
    )
    db = sqlite3.connect(str(db_path))
    db.execute("PRAGMA journal_mode=WAL")
    db.execute(
        "INSERT INTO messages (channel, sender, content, content_type, ts, read)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (channel, "system", message, "system", time.time(), 0),
    )
    db.commit()
    db.close()


def _cmd_reset_password(argv):
    """Generate a one-time password reset URL for a registered user.

    Stores a cryptographically secure token in ``auth.db``, sends the user a
    system DM notifying them that a reset was requested, and prints the reset
    URL to stdout.

    :param argv: Argument list (everything after ``reset-password``).
    :type argv: list of str
    """
    parser = argparse.ArgumentParser(
        prog="minimost reset-password",
        description="Generate a password reset URL for a registered user",
    )
    parser.add_argument("username", help="Username to generate a reset link for")
    parser.add_argument(
        "--expires",
        type=int,
        default=60,
        metavar="MINUTES",
        help="Minutes until the link expires (default: 60)",
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:5000",
        help="Base URL of the server (default: http://127.0.0.1:5000)",
    )
    args = parser.parse_args(argv)

    # Import here to avoid pulling Flask into the top-level import just for the
    # reset-password path, and to ensure auth.db schema is initialised.
    from minimost.database import init_auth_db
    from minimost.auth import AUTH_DB

    _WAL = "PRAGMA journal_mode=WAL"
    init_auth_db()

    db = sqlite3.connect(AUTH_DB)
    db.execute(_WAL)
    # Match case-insensitively and use the stored spelling for the token so the
    # generated link targets the account regardless of the case typed.
    row = db.execute(
        "SELECT username FROM users WHERE username = ? COLLATE NOCASE",
        (args.username,),
    ).fetchone()
    if not row:
        print(f"Error: user '{args.username}' does not exist", file=sys.stderr)
        db.close()
        sys.exit(1)
    username = row[0]

    token = secrets.token_urlsafe(32)
    expires_ts = time.time() + args.expires * 60

    db.execute(
        "INSERT INTO password_reset_tokens (token, username, expires_ts, used)"
        " VALUES (?, ?, ?, 0)",
        (token, username, expires_ts),
    )
    db.commit()
    db.close()

    _send_reset_dm(username, args.expires)

    url = f"{args.base_url.rstrip('/')}/reset-password/{token}"
    minutes_word = "minute" if args.expires == 1 else "minutes"
    print(
        f"Password reset URL for '{username}'"
        f" (expires in {args.expires} {minutes_word}):"
    )
    print(url)


if __name__ == "__main__":
    main()
