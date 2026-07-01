"""Tests for __init__.py and __main__.py."""

import os
import sys
from unittest.mock import patch, MagicMock

# ── _read_version ─────────────────────────────────────────────────────────────


def test_read_version_from_version_module():
    import minimost
    import minimost._version

    assert minimost._read_version() == minimost._version.__version__


def test_read_version_fallback_unknown():
    import minimost

    # Simulate the _version module being unimportable (e.g. a corrupted install).
    with patch.dict(sys.modules, {"minimost._version": None}):
        assert minimost._read_version() == "unknown"


# ── create_app ────────────────────────────────────────────────────────────────


def test_create_app_returns_flask_app(app):
    from flask import Flask

    assert isinstance(app, Flask)


def test_create_app_registers_blueprints(app):
    rules = [r.rule for r in app.url_map.iter_rules()]
    assert "/login" in rules
    assert "/messages/<channel>" in rules
    assert "/typing/<channel>" in rules


def test_create_app_max_content_length(app):
    assert app.config["MAX_CONTENT_LENGTH"] == 25 * 1024 * 1024


def test_create_app_has_secret_key(app):
    assert app.secret_key is not None
    assert len(app.secret_key) > 0


def test_create_app_version_in_context(app):
    with app.test_request_context("/"):
        ctx_proc = [p for p in app.template_context_processors[None]]
        for proc in ctx_proc:
            result = proc()
            if "app_version" in result:
                assert isinstance(result["app_version"], str)
                break


def test_create_app_creates_secret_key_file(tmp_path):
    import minimost

    # secret.key lives in the data root; MINIMOST_DATA_DIR points it at tmp_path.
    with patch.dict(os.environ, {"MINIMOST_DATA_DIR": str(tmp_path)}):
        minimost.create_app()
    assert (tmp_path / "secret.key").exists()


def test_create_app_reuses_existing_secret_key(tmp_path):
    import minimost

    key_file = tmp_path / "secret.key"
    key_file.write_text("my-fixed-secret-key")
    with patch.dict(os.environ, {"MINIMOST_DATA_DIR": str(tmp_path)}):
        app = minimost.create_app()
    assert app.secret_key == "my-fixed-secret-key"


def test_static_cache_bust_token_is_content_hash_not_timestamp(app):
    """``url_for('static', …)`` must bust caches with a content hash, not an
    mtime — an mtime is a Unix timestamp that DAST flags as disclosure."""
    import re

    from flask import url_for

    with app.test_request_context("/"):
        # conftest.py serves the real static folder, so favicon.svg exists.
        url = url_for("static", filename="favicon.svg")
    match = re.search(r"\?v=([^&]+)", url)
    assert match, "expected a ?v= cache-bust token on static URLs"
    token = match.group(1)
    # A short lowercase hex digest — never a bare 10-digit epoch timestamp.
    assert re.fullmatch(r"[0-9a-f]{12}", token)
    assert not re.fullmatch(r"\d{10}", token)


# ── main ──────────────────────────────────────────────────────────────────────


def test_main_default_args():
    from minimost.__main__ import main

    # No TLS paths in config -> the dev server runs plain HTTP (ssl_context=None).
    mock_app = MagicMock()
    mock_app.config = {}
    with patch("minimost.__main__.create_app", return_value=mock_app):
        with patch("sys.argv", ["minimost"]):
            main()
    mock_app.run.assert_called_once_with(
        host="127.0.0.1", port=5000, debug=False, ssl_context=None, threaded=True
    )


def test_main_custom_args():
    from minimost.__main__ import main

    mock_app = MagicMock()
    mock_app.config = {}
    with patch("minimost.__main__.create_app", return_value=mock_app):
        with patch("sys.argv", ["minimost", "--host", "0.0.0.0", "--port", "8080"]):
            main()
    mock_app.run.assert_called_once_with(
        host="0.0.0.0", port=8080, debug=False, ssl_context=None, threaded=True
    )


def test_main_uses_tls_paths_from_config():
    from minimost.__main__ import main

    # When create_app provisioned certs, the dev server serves them over HTTPS.
    mock_app = MagicMock()
    mock_app.config = {"TLS_CERT_FILE": "cert.pem", "TLS_KEY_FILE": "key.pem"}
    with patch("minimost.__main__.create_app", return_value=mock_app):
        with patch("sys.argv", ["minimost"]):
            main()
    mock_app.run.assert_called_once_with(
        host="127.0.0.1",
        port=5000,
        debug=False,
        ssl_context=("cert.pem", "key.pem"),
        threaded=True,
    )


# ── _DisconnectLogFilter ──────────────────────────────────────────────────────


def _werkzeug_record(message):
    import logging

    return logging.LogRecord("werkzeug", logging.ERROR, __file__, 0, message, (), None)


def test_disconnect_filter_drops_client_disconnect_tracebacks():
    from minimost.__main__ import _DisconnectLogFilter

    f = _DisconnectLogFilter()
    ssl_eof = (
        "Error on request:\nTraceback (most recent call last):\n"
        "ssl.SSLError: [SSL: UNEXPECTED_EOF_WHILE_READING] unexpected eof"
    )
    broken_pipe = "Error on request:\n...\nBrokenPipeError: [Errno 32] Broken pipe"
    assert f.filter(_werkzeug_record(ssl_eof)) is False
    assert f.filter(_werkzeug_record(broken_pipe)) is False


def test_disconnect_filter_keeps_real_errors_and_access_logs():
    from minimost.__main__ import _DisconnectLogFilter

    f = _DisconnectLogFilter()
    real_error = "Error on request:\nTraceback ...\nValueError: boom"
    access_log = '127.0.0.1 - - [..] "GET /events HTTP/1.1" 200 -'
    assert f.filter(_werkzeug_record(real_error)) is True
    assert f.filter(_werkzeug_record(access_log)) is True


def test_silence_stream_disconnect_logs_is_idempotent():
    import logging

    from minimost.__main__ import (
        _DisconnectLogFilter,
        _silence_stream_disconnect_logs,
    )

    logger = logging.getLogger("werkzeug")
    saved = list(logger.filters)
    try:
        logger.filters = [
            f for f in logger.filters if not isinstance(f, _DisconnectLogFilter)
        ]
        _silence_stream_disconnect_logs()
        _silence_stream_disconnect_logs()
        installed = [f for f in logger.filters if isinstance(f, _DisconnectLogFilter)]
        assert len(installed) == 1
    finally:
        logger.filters = saved
