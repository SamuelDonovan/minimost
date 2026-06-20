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
import logging
import secrets
import sqlite3
import sys
import time

from minimost import create_app


class _DisconnectLogFilter(logging.Filter):
    """Suppress the dev server's traceback for client disconnects mid-stream.

    The SSE endpoint (``GET /events``) holds a long-lived response open. When a
    browser closes it — on tab close, navigation, or the stream's periodic
    recycle — the dev server's next socket write raises ``BrokenPipeError`` and
    draining the request then raises ``ssl.SSLError`` (UNEXPECTED_EOF). On
    OpenSSL 3 that EOF surfaces as a plain ``ssl.SSLError`` rather than the
    ``ssl.SSLEOFError`` Werkzeug lists in ``connection_dropped_errors``, so
    ``run_wsgi`` falls through to its generic handler and logs the full
    traceback via the ``werkzeug`` logger — on *every* disconnect.

    That log call happens inside ``run_wsgi``, so it cannot be intercepted by a
    request handler; we drop it at the logger instead. Only records that are
    BOTH an "Error on request" AND carry a client-disconnect signature are
    suppressed, so genuine application tracebacks are still logged in full.
    """

    _DISCONNECT_SIGNS = (
        "UNEXPECTED_EOF_WHILE_READING",
        "BrokenPipeError",
        "Broken pipe",
        "ConnectionResetError",
        "ConnectionAbortedError",
    )

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if "Error on request" not in message:
            return True
        return not any(sign in message for sign in self._DISCONNECT_SIGNS)


def _silence_stream_disconnect_logs() -> None:
    """Attach :class:`_DisconnectLogFilter` to the ``werkzeug`` logger once."""
    logger = logging.getLogger("werkzeug")
    if not any(isinstance(f, _DisconnectLogFilter) for f in logger.filters):
        logger.addFilter(_DisconnectLogFilter())


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

    # create_app() provisions the TLS certificate (shared by every WSGI server)
    # and records the resolved paths in app.config; the dev server just consumes
    # them. Set MINIMOST_SKIP_TLS=1 to serve plain HTTP.
    app = create_app()
    # Tell templates they are being served by the connection-closing built-in
    # server so the ``stylesheet`` macro inlines CSS into the page instead of
    # linking it. Under the dev server a separate stylesheet request can be lost
    # to a connection reset on heavy refresh; inlining removes the request
    # entirely. Gunicorn never sets this, so it keeps serving cacheable links.
    app.config["DEV_SERVER"] = True
    cert = app.config.get("TLS_CERT_FILE")
    key = app.config.get("TLS_KEY_FILE")
    ssl_context = (cert, key) if cert and key else None
    # Swallow the BrokenPipe/SSL-EOF traceback the dev server would otherwise log
    # every time a browser closes the long-lived /events SSE connection.
    _silence_stream_disconnect_logs()
    # threaded=True gives every connection its own thread. Without it the
    # built-in server handles one connection at a time — the long-lived /events
    # SSE stream would then block every other request for that tab, and a burst
    # of parallel asset/API requests on load would serialise behind it.
    app.run(
        host=args.host,
        port=args.port,
        debug=False,
        ssl_context=ssl_context,
        threaded=True,
    )


def _send_reset_dm(username: str, expires_minutes: int) -> None:
    """Insert a system notification DM into the shared message database."""
    from minimost.common import shared_db_path, init_messages_db

    init_messages_db()
    channel = "dm:" + ":".join(sorted(["system", username]))
    minutes_word = "minute" if expires_minutes == 1 else "minutes"
    message = (
        f"A password reset has been requested for your account. "
        f"The reset link will expire in {expires_minutes} {minutes_word}. "
        f"If you did not request this, please contact your administrators."
    )
    db = sqlite3.connect(str(shared_db_path()))
    db.execute("PRAGMA journal_mode=WAL")
    db.execute(
        "INSERT INTO messages (channel, sender, content, content_type, ts)"
        " VALUES (?, ?, ?, ?, ?)",
        (channel, "system", message, "system", time.time()),
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
