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
import secrets
import sqlite3
import sys
import time
from pathlib import Path

from minimost import create_app

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _ensure_certs():
    """Ensure a CA-signed TLS leaf cert exists in the project root.

    Thin wrapper around :func:`minimost.certs.ensure_certs`; see that function
    for the full CA + leaf provisioning and auto-renewal behaviour.  Kept as a
    module-level function so it stays an easy patch point in tests.

    :returns: ``(cert_path, key_path)`` as :class:`pathlib.Path` objects on
        success, or ``(None, None)`` if generation is skipped or fails.
    :rtype: tuple[Path, Path] | tuple[None, None]
    """
    from minimost.certs import ensure_certs

    return ensure_certs(_PROJECT_ROOT)


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
