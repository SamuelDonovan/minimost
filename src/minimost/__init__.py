import re
import secrets
from pathlib import Path

from flask import Flask

from . import common, database
from .auth import auth_bp
from .chat import chat_bp
from .presence import presence_bp

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent.parent


def _read_version() -> str:
    try:
        from importlib.metadata import version

        return version("minimost")
    except Exception:
        pass
    try:
        toml = (_PROJECT_ROOT / "pyproject.toml").read_text()
        m = re.search(r'^version\s*=\s*"([^"]+)"', toml, re.MULTILINE)
        if m:
            return m.group(1)
    except Exception:
        pass
    return "unknown"


_APP_VERSION = _read_version()


def create_app():
    app = Flask(__name__)

    key_file = _PROJECT_ROOT / "secret.key"
    if not key_file.exists():
        key_file.write_text(secrets.token_hex(32))
    app.secret_key = key_file.read_text().strip()

    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

    @app.context_processor
    def inject_version():
        return {"app_version": _APP_VERSION}

    app.register_blueprint(auth_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(presence_bp)
    return app
