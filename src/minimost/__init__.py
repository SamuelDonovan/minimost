"""
minimost
========

Flask application factory for the MiniMost chat platform.

This module is the primary entry point for the MiniMost application. It exposes
:func:`create_app`, which constructs a fully-configured :class:`flask.Flask`
instance ready to serve HTTP requests.

Typical usage in development::

    from minimost import create_app

    app = create_app()
    app.run(host="127.0.0.1", port=5000)

Typical usage with a WSGI server such as Gunicorn::

    gunicorn "minimost:create_app()" --config gunicorn.conf.py

Module-level attributes
-----------------------
_APP_VERSION : str
    The package version string, resolved once at import time by
    :func:`_read_version`.  Available in every Jinja2 template as
    ``{{ app_version }}``.
"""

import re
import secrets
import threading
import time
from contextlib import suppress
from pathlib import Path

from flask import Flask, abort, request, session

from . import calls as calls_mod
from . import common, database, presence
from .auth import auth_bp
from .calls import calls_bp
from .chat import chat_bp
from .presence import presence_bp

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent.parent


def _read_version() -> str:
    """Return the installed package version string.

    The version is resolved in two stages:

    1. **importlib.metadata** — works when the package has been installed via
       ``pip install`` (editable or otherwise).
    2. **pyproject.toml parsing** — fallback for environments where the package
       metadata is not available (e.g. running directly from the source tree
       without installing).

    If both stages fail the string ``"unknown"`` is returned so the application
    always has a displayable value.

    :returns: The version string, for example ``"0.1.0"``, or ``"unknown"``
              if the version cannot be determined.
    :rtype: str
    """
    with suppress(Exception):
        from importlib.metadata import version

        return version("minimost")
    with suppress(Exception):
        toml = (_PROJECT_ROOT / "pyproject.toml").read_text()
        m = re.search(r'^version\s*=\s*"([^"]+)"', toml, re.MULTILINE)
        if m:
            return m.group(1)
    return "unknown"


_APP_VERSION = _read_version()

_SETTINGS_FILE = _PROJECT_ROOT / "settings.json"


def _max_upload_size_mb() -> int:
    """Return the configured max upload size in MB (default 25)."""
    import json

    with suppress(Exception):
        data = json.loads(_SETTINGS_FILE.read_text())
        value = data.get("max_upload_size_mb")
        if isinstance(value, (int, float)) and value > 0:
            return int(value)
    return 25


def _max_avatar_size_mb() -> int:
    """Return the configured max avatar size in MB (default 5)."""
    import json

    with suppress(Exception):
        data = json.loads(_SETTINGS_FILE.read_text())
        value = data.get("max_avatar_size_mb")
        if isinstance(value, (int, float)) and value > 0:
            return int(value)
    return 5


def create_app():
    """Create and configure the MiniMost Flask application.

    This is the canonical *application factory* used by every execution path —
    the CLI entry point (:mod:`minimost.__main__`), the Gunicorn WSGI
    configuration, and any test suite that imports the package.

    The factory performs the following steps in order:

    1. **Instantiate** a :class:`flask.Flask` application object.
    2. **Provision the secret key** — read from ``secret.key`` in the project
       root, generating a fresh 64-character hex token if the file does not
       exist.  The secret key is required for Flask's signed session cookies.
    3. **Set upload limit** to 16 MiB via ``MAX_CONTENT_LENGTH``.  Requests
       that exceed this size are rejected by Flask before the route handler
       runs.
    4. **Inject the version** into every Jinja2 template context via a context
       processor, making ``{{ app_version }}`` available in all templates.
    5. **Register blueprints** — :data:`auth_bp <minimost.auth.auth_bp>`,
       :data:`chat_bp <minimost.chat.chat_bp>`, and
       :data:`presence_bp <minimost.presence.presence_bp>`.

    The ``auth.db`` and ``presence.db`` databases are also initialised as a
    side effect of importing :mod:`minimost.database` and
    :mod:`minimost.presence` at module load time.

    :returns: A configured :class:`flask.Flask` application instance.
    :rtype: flask.Flask

    Example::

        app = create_app()
        with app.test_client() as client:
            response = client.get("/login")
            assert response.status_code == 200
    """
    app = Flask(__name__)

    key_file = _PROJECT_ROOT / "secret.key"
    if not key_file.exists():
        key_file.write_text(secrets.token_hex(32))
    app.secret_key = key_file.read_text().strip()

    _upload_mb = _max_upload_size_mb()
    _avatar_mb = _max_avatar_size_mb()
    app.config["MAX_CONTENT_LENGTH"] = _upload_mb * 1024 * 1024

    def _csrf_token() -> str:
        """Return a per-session CSRF token, generating one if absent."""
        if "_csrf_token" not in session:
            session["_csrf_token"] = secrets.token_hex(32)
        return session["_csrf_token"]  # type: ignore[return-value]

    app.jinja_env.globals["csrf_token"] = _csrf_token

    @app.before_request
    def _enforce_csrf():
        # Only validate on state-changing methods and only when CSRF is enabled.
        if not app.config.get("CSRF_ENABLED", True):
            return
        if request.method in ("GET", "HEAD", "OPTIONS", "TRACE"):
            return
        # Chat and presence routes are API endpoints protected by session auth;
        # CSRF validation applies only to the HTML form routes in the auth blueprint.
        if request.blueprint != "auth":
            return
        expected = session.get("_csrf_token", "")
        submitted = request.form.get("csrf_token", "")
        if not expected or not secrets.compare_digest(expected, submitted):
            abort(403)

    @app.context_processor
    def inject_globals():
        """Inject global template variables."""
        return {
            "app_version": _APP_VERSION,
            "max_upload_mb": _upload_mb,
            "max_avatar_mb": _avatar_mb,
        }

    app.register_blueprint(auth_bp)
    app.register_blueprint(calls_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(presence_bp)

    presence.reset_all_offline()
    calls_mod.reset_all_calls_ended()
    calls_mod.reset_all_screenshares_ended()

    _start_cleanup_scheduler()

    return app


def _start_cleanup_scheduler(
    interval_hours: int = 24, days: int = 30, message_days: int = 770
) -> None:
    """Start a daemon thread that periodically purges old upload files.

    Runs :func:`minimost.clean.delete_files_older_than` once shortly after
    startup and then every *interval_hours* hours.  The thread is a daemon so
    it exits automatically when the server process shuts down — no teardown
    required.

    The retention period is read from the ``"image_retention_days"`` key in
    ``settings.json`` at each run, so changes to the file take effect on the
    next scheduled cleanup without restarting the server.  If the key is
    absent or the file cannot be read, *days* is used as the fallback.

    Multiple Gunicorn workers each start their own thread; concurrent runs are
    safe because :func:`~minimost.clean.delete_files_older_than` tolerates
    ``FileNotFoundError`` on files already removed by another worker.

    :param interval_hours: Hours between cleanup runs.  Defaults to ``24``.
    :param days: Fallback retention period in days if ``settings.json`` does
        not specify ``"image_retention_days"``.  Defaults to ``30``.
    """
    upload_dir = _PROJECT_ROOT / "uploads"
    users_dir = _PROJECT_ROOT / "users"
    settings_file = _PROJECT_ROOT / "settings.json"

    def _read_retention() -> tuple:
        with suppress(Exception):
            import json

            data = json.loads(settings_file.read_text())
            img = data.get("image_retention_days")
            fil = data.get("file_retention_days")
            msg = data.get("message_retention_days")
            img = img if isinstance(img, int) and img > 0 else days
            fil = fil if isinstance(fil, int) and fil > 0 else days
            msg = msg if isinstance(msg, int) and msg > 0 else message_days
            return img, fil, msg
        return days, days, message_days

    def _loop() -> None:
        time.sleep(300)  # short initial delay — let the server finish starting
        while True:
            try:
                from .clean import delete_files_older_than, delete_messages_older_than

                image_days, file_days, msg_days = _read_retention()
                delete_files_older_than(
                    str(upload_dir),
                    image_days=image_days,
                    file_days=file_days,
                )
                delete_messages_older_than(str(users_dir), days=msg_days)
            except (
                Exception
            ):  # nosec B110 — cleanup failure must not crash the daemon thread
                pass
            time.sleep(interval_hours * 3600)

    thread = threading.Thread(target=_loop, daemon=True, name="minimost-cleanup")
    thread.start()
