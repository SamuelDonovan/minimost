"""Tests for session inactivity timeout and security response headers.

Covers ASD STIG APSC-DV-000070 (15-minute inactivity timeout) and the
defensive HTTP headers added for APSC-DV-002500 (clickjacking, MIME sniffing,
referrer/CSP).
"""

import time

from minimost import _PASSIVE_ENDPOINTS, _SESSION_IDLE_SECONDS


def _audit_text():
    import minimost.audit as audit
    import os

    if not os.path.exists(audit.AUDIT_LOG):
        return ""
    with open(audit.AUDIT_LOG, encoding="utf-8") as fh:
        return fh.read()


# --- Security headers -------------------------------------------------------


def test_security_headers_present_on_login(client):
    r = client.get("/login")
    assert r.headers.get("X-Frame-Options") == "DENY"
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("Referrer-Policy") == "no-referrer"
    csp = r.headers.get("Content-Security-Policy", "")
    assert "frame-ancestors 'none'" in csp
    assert "default-src 'self'" in csp


def test_security_headers_present_on_authenticated_json(alice):
    r = alice.get("/channels")
    assert r.status_code == 200
    assert r.headers.get("X-Frame-Options") == "DENY"
    assert "Content-Security-Policy" in r.headers


def test_hsts_absent_when_tls_skipped(client):
    # conftest sets MINIMOST_SKIP_TLS=1, so HSTS must not be advertised (it would
    # otherwise pin browsers to HTTPS against a plain-HTTP/proxy deployment).
    assert "Strict-Transport-Security" not in client.get("/login").headers


# --- Inactivity timeout -----------------------------------------------------


def test_idle_session_is_terminated_and_audited(alice):
    with alice.session_transaction() as s:
        s["_last_active"] = time.time() - (_SESSION_IDLE_SECONDS + 5)
    r = alice.get("/channels")
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/login")
    with alice.session_transaction() as s:
        assert "user" not in s
    assert "event=session_timeout" in _audit_text()


def test_active_session_within_window_is_not_terminated(alice):
    with alice.session_transaction() as s:
        s["_last_active"] = time.time() - 60  # one minute ago: well inside 15 min
    r = alice.get("/channels")
    assert r.status_code == 200


def test_user_interaction_refreshes_the_timer(alice):
    old = time.time() - 120
    with alice.session_transaction() as s:
        s["_last_active"] = old
    alice.get("/channels")  # an active (non-passive) endpoint
    with alice.session_transaction() as s:
        assert s["_last_active"] > old


def test_background_poll_does_not_refresh_the_timer(alice):
    # /online_users is a passive poller; hitting it must not extend the session,
    # or an unattended-but-open tab would never time out.
    assert "chat.online_users" in _PASSIVE_ENDPOINTS
    marker = time.time() - 120
    with alice.session_transaction() as s:
        s["_last_active"] = marker
    alice.get("/online_users")
    with alice.session_transaction() as s:
        assert s["_last_active"] == marker
