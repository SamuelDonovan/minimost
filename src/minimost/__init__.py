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
from contextlib import suppress
from pathlib import Path

from flask import Flask, abort, request, session

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

    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

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
    def inject_version():
        """Inject the application version into every template context.

        :returns: A dict mapping ``"app_version"`` to the version string.
        :rtype: dict
        """
        return {"app_version": _APP_VERSION}

    app.register_blueprint(auth_bp)
    app.register_blueprint(calls_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(presence_bp)

    presence.reset_all_offline()

    return app
