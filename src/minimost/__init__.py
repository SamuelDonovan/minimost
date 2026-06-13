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

import os
import secrets
import threading
import time
from contextlib import suppress
from pathlib import Path

from flask import Flask, abort, request, send_file, session

from . import calls as calls_mod
from . import chat as chat_mod
from . import common, database, presence
from .auth import auth_bp
from .calls import calls_bp
from .chat import chat_bp
from .presence import presence_bp

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent.parent


def _read_version() -> str:
    """Return the package version string.

    The version lives in :mod:`minimost._version`, which ships inside the
    package and is therefore importable from an installed wheel and on every
    supported Python version (unlike ``importlib.metadata``, which is 3.8+).
    The same module is the build-time source of truth via the dynamic-version
    config in ``pyproject.toml``.

    If the module cannot be imported for any reason, the string ``"unknown"``
    is returned so the application always has a displayable value.

    :returns: The version string, for example ``"0.1.0"``, or ``"unknown"``
              if the version cannot be determined.
    :rtype: str
    """
    with suppress(Exception):
        from ._version import __version__

        return __version__
    return "unknown"


_APP_VERSION = _read_version()

# settings.json is bundled inside the package (src/minimost/) so it ships in
# the wheel; _HERE is the package directory.
_SETTINGS_FILE = _HERE / "settings.json"


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


def _stun_port() -> int:
    """Return the configured STUN UDP port (default 3478).

    The bundled STUN server lets LAN WebRTC peers gather a real-IP
    server-reflexive candidate, avoiding the mDNS ``.local`` host-candidate
    resolution that otherwise breaks calls on LANs without avahi/Bonjour.
    """
    import json

    from .stun import DEFAULT_STUN_PORT

    with suppress(Exception):
        data = json.loads(_SETTINGS_FILE.read_text())
        value = data.get("stun_port")
        if isinstance(value, int) and 0 < value < 65536:
            return value
    return DEFAULT_STUN_PORT


def _provision_tls(app) -> None:
    """Generate the self-signed TLS cert/key once, for any WSGI server.

    Historically only the development server and the bundled Gunicorn config
    generated certificates, so running MiniMost under another WSGI server
    (waitress, uWSGI, mod_wsgi, …) silently meant no HTTPS — and therefore no
    voice/video calling.  Doing it here means *any* server that loads
    ``minimost:create_app()`` gets certificates provisioned, with no
    server-specific glue.

    Generation is idempotent (see :func:`minimost.certs.ensure_certs`) and the
    resolved paths are stored in ``app.config['TLS_CERT_FILE']`` and
    ``['TLS_KEY_FILE']`` so a launcher can point its TLS listener at them.  Note
    that generating the files does **not** terminate TLS — the WSGI server still
    has to be configured to serve HTTPS using these paths.

    Set ``MINIMOST_SKIP_TLS=1`` to skip generation entirely, e.g. when TLS is
    terminated upstream by a reverse proxy, or under the test suite.

    :param app: The Flask application whose config receives the cert paths.
    """
    if os.environ.get("MINIMOST_SKIP_TLS"):
        return
    from .certs import ensure_certs

    # Use the process working directory (matching the Gunicorn config and the
    # documented data-directory model) so it resolves correctly under an
    # installed wheel, where the package dir is typically read-only.
    cert, key = ensure_certs(Path.cwd())
    if cert and key:
        app.config["TLS_CERT_FILE"] = str(cert)
        app.config["TLS_KEY_FILE"] = str(key)


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
    _stun = _stun_port()
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
            "stun_port": _stun,
        }

    @app.route("/sw.js", methods=["GET"])
    def service_worker():
        """Serve the PWA service worker from the root scope.

        The ``Service-Worker-Allowed: /`` header lets a script served from
        ``/sw.js`` control the entire origin, so the installed PWA hides the
        browser URL bar across all routes.
        """
        return (
            app.send_static_file("sw.js"),
            200,
            {
                "Content-Type": "application/javascript",
                "Service-Worker-Allowed": "/",
            },
        )

    @app.route("/ca.pem", methods=["GET"])
    def download_ca_cert():
        """Serve the local CA certificate so clients can trust this server.

        Importing this public certificate into the browser/OS trust store makes
        the self-signed TLS leaf MiniMost serves trusted, which clears the
        "Not secure" warning and lets the installed PWA hide the URL bar. Only
        the public CA cert is exposed; the signing key (``ca-key.pem``) never
        leaves the server. ``ca.pem`` lives in the working directory alongside
        ``cert.pem``/``key.pem`` (see ``gunicorn.conf.py``).
        """
        ca_path = Path.cwd() / "ca.pem"
        if not ca_path.is_file():
            abort(404)
        return send_file(
            ca_path,
            mimetype="application/x-pem-file",
            as_attachment=True,
            download_name="minimost-ca.pem",
        )

    app.register_blueprint(auth_bp)
    app.register_blueprint(calls_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(presence_bp)

    presence.reset_all_offline()
    calls_mod.reset_all_calls_ended()
    calls_mod.reset_all_screenshares_ended()
    _migrate_search_indexes()
    _provision_tls(app)

    from .stun import start_stun_server

    start_stun_server(_stun)

    _start_cleanup_scheduler()

    return app


def _migrate_search_indexes() -> None:
    """Ensure the shared message database and its search index exist at boot.

    :func:`~minimost.common.init_messages_db` is idempotent and builds (then
    rebuilds, once) the FTS5 trigram index if it is missing, so calling it at
    startup transparently upgrades a database that predates the index. Runs once
    per worker at boot.
    """
    with suppress(Exception):
        common.init_messages_db()


def _start_cleanup_scheduler(
    interval_hours: int = 24,
    days: int = 30,
    message_days: int = 770,
    initial_delay_seconds: int = 5,
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

    Two optional size caps are also honoured each run: ``"max_upload_dir_size_mb"``
    bounds the total size of ``uploads/`` (oldest files deleted first), and
    ``"max_message_db_size_mb"`` bounds the shared ``messages.db`` (oldest
    messages deleted first).  Either is disabled when its key is absent or
    non-positive.

    Multiple Gunicorn workers each start their own thread; concurrent runs are
    safe because :func:`~minimost.clean.delete_files_older_than` tolerates
    ``FileNotFoundError`` on files already removed by another worker.

    :param interval_hours: Hours between cleanup runs.  Defaults to ``24``.
    :param days: Fallback retention period in days if ``settings.json`` does
        not specify ``"image_retention_days"``.  Defaults to ``30``.
    :param message_days: Fallback retention period in days for messages if
        ``settings.json`` does not specify ``"message_retention_days"``.
    :param initial_delay_seconds: Seconds to wait after startup before the first
        cleanup run, giving the server time to finish booting.  Defaults to
        ``5``.
    """
    # Resolve the data directories from the live module attributes (rather than
    # ``_PROJECT_ROOT``) so the worker honours any monkeypatched paths — this is
    # what keeps the test suite's cleanup runs confined to their temp dirs
    # instead of touching the real ``users/`` and ``uploads/`` directories.
    upload_dir = chat_mod.UPLOAD_DIR
    users_dir = common.DB_DIR
    settings_file = _HERE / "settings.json"

    def _read_retention() -> tuple:
        with suppress(Exception):
            import json

            data = json.loads(settings_file.read_text())
            img = data.get("image_retention_days")
            fil = data.get("file_retention_days")
            msg = data.get("message_retention_days")
            upload_mb = data.get("max_upload_dir_size_mb")
            db_mb = data.get("max_message_db_size_mb")
            img = img if isinstance(img, int) and img > 0 else days
            fil = fil if isinstance(fil, int) and fil > 0 else days
            msg = msg if isinstance(msg, int) and msg > 0 else message_days

            # A size cap of 0 / absent / invalid disables that cap (None).
            def _cap(value):
                return value if isinstance(value, (int, float)) and value > 0 else None

            return img, fil, msg, _cap(upload_mb), _cap(db_mb)
        return days, days, message_days, None, None

    def _loop() -> None:
        time.sleep(initial_delay_seconds)  # let the server finish starting
        while True:
            try:
                from .clean import (
                    delete_files_older_than,
                    delete_files_over_size,
                    delete_messages_older_than,
                    delete_messages_over_size,
                )

                (
                    image_days,
                    file_days,
                    msg_days,
                    max_upload_mb,
                    max_db_mb,
                ) = _read_retention()
                # Age-based cleanup first, then trim by size whatever remains.
                delete_files_older_than(
                    str(upload_dir),
                    image_days=image_days,
                    file_days=file_days,
                )
                if max_upload_mb:
                    delete_files_over_size(str(upload_dir), max_size_mb=max_upload_mb)
                delete_messages_older_than(str(users_dir), days=msg_days)
                if max_db_mb:
                    delete_messages_over_size(
                        str(common.shared_db_path()), max_size_mb=max_db_mb
                    )
            except (
                Exception
            ):  # nosec B110 — cleanup failure must not crash the daemon thread
                pass
            time.sleep(interval_hours * 3600)

    thread = threading.Thread(target=_loop, daemon=True, name="minimost-cleanup")
    thread.start()
