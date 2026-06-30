"""Tests for the generic custom error handlers (ASD STIG APSC-DV-002880/002890).

Error responses must be generic — no stack trace, framework version, or request
detail in the body — and content-negotiated between HTML and JSON.
"""

import os


def _audit_text():
    import minimost.audit as audit

    if not os.path.exists(audit.AUDIT_LOG):
        return ""
    with open(audit.AUDIT_LOG, encoding="utf-8") as fh:
        return fh.read()


def test_404_html_is_generic(client):
    resp = client.get("/this-route-does-not-exist")
    assert resp.status_code == 404
    body = resp.get_data(as_text=True)
    assert "The requested resource was not found." in body
    # No framework internals / stack trace leak.
    for leak in ("Traceback", "Werkzeug", "werkzeug", 'File "'):
        assert leak not in body


def test_404_returns_json_when_negotiated(client):
    resp = client.get(
        "/this-route-does-not-exist", headers={"Accept": "application/json"}
    )
    assert resp.status_code == 404
    assert resp.get_json() == {"error": "The requested resource was not found."}


def test_405_method_not_allowed_is_generic(client):
    # /send/<channel> is POST-only; a GET matches the URL but not the method.
    resp = client.get("/send/general")
    assert resp.status_code == 405
    assert "Method not allowed." in resp.get_data(as_text=True)


def test_413_payload_too_large(app):
    app.config["MAX_CONTENT_LENGTH"] = 100
    c = app.test_client()
    resp = c.post("/login", data={"field": "x" * 500})
    assert resp.status_code == 413
    assert "too large" in resp.get_data(as_text=True)


def test_500_does_not_leak_and_is_audited(app):
    app.config["PROPAGATE_EXCEPTIONS"] = False

    @app.route("/__raise_for_test")
    def _raise():
        raise RuntimeError("SECRET internal detail that must not leak")

    resp = app.test_client().get("/__raise_for_test")
    assert resp.status_code == 500
    body = resp.get_data(as_text=True)
    assert "SECRET internal detail" not in body
    assert "Traceback" not in body
    assert "An internal error occurred." in body
    # The server error is recorded in the audit trail (admin-only detail).
    assert "event=server_error" in _audit_text()


def test_500_json_negotiated(app):
    app.config["PROPAGATE_EXCEPTIONS"] = False

    @app.route("/__raise_json")
    def _raise():
        raise RuntimeError("boom")

    resp = app.test_client().get(
        "/__raise_json", headers={"Accept": "application/json"}
    )
    assert resp.status_code == 500
    assert resp.get_json() == {
        "error": "An internal error occurred. Please try again later."
    }
