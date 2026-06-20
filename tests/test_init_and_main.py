"""Tests for __init__.py and __main__.py."""

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

    with patch.object(minimost, "_PROJECT_ROOT", tmp_path):
        minimost.create_app()
    assert (tmp_path / "secret.key").exists()


def test_create_app_reuses_existing_secret_key(tmp_path):
    import minimost

    key_file = tmp_path / "secret.key"
    key_file.write_text("my-fixed-secret-key")
    with patch.object(minimost, "_PROJECT_ROOT", tmp_path):
        app = minimost.create_app()
    assert app.secret_key == "my-fixed-secret-key"


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
