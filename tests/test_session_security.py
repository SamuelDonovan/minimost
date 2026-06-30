"""Tests for session inactivity timeout and security response headers.

Covers ASD STIG APSC-DV-000070 (15-minute inactivity timeout) and the
defensive HTTP headers added for APSC-DV-002500 (clickjacking, MIME sniffing,
referrer/CSP).
"""

import time

from minimost import _PASSIVE_ENDPOINTS, _session_idle_seconds, _SESSION_IDLE_SECONDS


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
    # Pin a short window so the test is independent of the shipped default.
    alice.application.config["SESSION_IDLE_SECONDS"] = 15 * 60
    with alice.session_transaction() as s:
        s["_last_active"] = time.time() - (15 * 60 + 5)
    r = alice.get("/channels")
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/login")
    with alice.session_transaction() as s:
        assert "user" not in s
    assert "event=session_timeout" in _audit_text()


def test_active_session_within_window_is_not_terminated(alice):
    alice.application.config["SESSION_IDLE_SECONDS"] = 15 * 60
    with alice.session_transaction() as s:
        s["_last_active"] = time.time() - 60  # one minute ago: well inside window
    r = alice.get("/channels")
    assert r.status_code == 200


def test_user_interaction_refreshes_the_timer(alice):
    old = time.time() - 120
    with alice.session_transaction() as s:
        s["_last_active"] = old
    alice.get("/channels")  # an active (non-passive) endpoint
    with alice.session_transaction() as s:
        assert s["_last_active"] > old


def test_shipped_default_idle_window_is_two_weeks(client):
    # The bundled settings.json ships a 2-week default for usability (outside the
    # STIG band by design — set session_idle_minutes to 15 for APSC-DV-000070).
    assert _session_idle_seconds() == 14 * 24 * 60 * 60
    assert client.application.config["SESSION_IDLE_SECONDS"] == 14 * 24 * 60 * 60


def test_fallback_constant_is_the_stig_baseline():
    # If settings.json is ever unreadable the timeout fails closed to 15 minutes.
    assert _SESSION_IDLE_SECONDS == 15 * 60


def test_idle_timeout_respects_configured_window(app):
    # The window is read live from config, so a longer setting keeps an
    # otherwise-stale session alive.
    app.config["SESSION_IDLE_SECONDS"] = 3600  # one hour
    c = app.test_client()
    with c.session_transaction() as s:
        s["user"] = "alice"
        s["_last_active"] = time.time() - (16 * 60)  # 16 min: inside the hour
    assert c.get("/channels").status_code == 200


def test_zero_minutes_disables_idle_timeout_in_reader(tmp_path, monkeypatch):
    import json
    import minimost

    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"session_idle_minutes": 0}))
    monkeypatch.setattr(minimost, "_SETTINGS_FILE", settings)
    assert _session_idle_seconds() == 0
    # Any non-positive value disables it, too.
    settings.write_text(json.dumps({"session_idle_minutes": -5}))
    assert _session_idle_seconds() == 0


def test_disabled_idle_timeout_never_logs_out(app):
    # session_idle_minutes=0 -> SESSION_IDLE_SECONDS=0: a session idle for a year
    # must survive and must not emit a session_timeout audit record.
    app.config["SESSION_IDLE_SECONDS"] = 0
    before = _audit_text()
    c = app.test_client()
    with c.session_transaction() as s:
        s["user"] = "alice"
        s["_last_active"] = time.time() - 365 * 24 * 3600
    assert c.get("/channels").status_code == 200
    with c.session_transaction() as s:
        assert s.get("user") == "alice"
    assert _audit_text() == before  # no new audit records


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


# --- Session ID rotation / fixation (APSC-DV-002250) ------------------------


def _signup(client, username, password="Password1!"):
    client.post(
        "/signup",
        data={"username": username, "password": password, "confirm_password": password},
    )


def test_login_regenerates_session_and_drops_fixed_session(client):
    _signup(client, "carol")
    client.get("/logout")
    # An attacker fixes a session value and a known session id in the browser.
    with client.session_transaction() as s:
        s["planted"] = "evil"
        s["_sid"] = "attacker-known-sid"
    client.post("/login", data={"username": "carol", "password": "Password1!"})
    with client.session_transaction() as s:
        assert s.get("user") == "carol"
        assert "planted" not in s  # the fixed session was discarded
        assert s.get("_sid") not in (None, "attacker-known-sid")  # regenerated


def test_login_uses_a_fresh_session_id_each_time(client):
    _signup(client, "dave")
    client.get("/logout")
    client.post("/login", data={"username": "dave", "password": "Password1!"})
    with client.session_transaction() as s:
        first = s["_sid"]
    client.get("/logout")
    client.post("/login", data={"username": "dave", "password": "Password1!"})
    with client.session_transaction() as s:
        assert s["_sid"] != first


def test_password_change_rotates_session_id_but_stays_logged_in(client):
    _signup(client, "erin")  # signup logs the user in
    with client.session_transaction() as s:
        before = s["_sid"]
    resp = client.post(
        "/change-password",
        data={
            "current_password": "Password1!",
            "new_password": "Password2!",
            "confirm_password": "Password2!",
        },
    )
    assert resp.status_code == 200
    with client.session_transaction() as s:
        assert s.get("user") == "erin"  # still authenticated
        assert s["_sid"] != before  # identifier rotated
