"""Tests for the security audit logging module (minimost.audit).

The ``isolated_dbs`` autouse fixture in conftest points ``audit.AUDIT_LOG`` at a
file inside the per-test ``tmp_path``, so each test reads back exactly the
records it produced without touching a real audit trail.
"""

import minimost.audit as audit


def _read_log():
    """Return the lines currently in the per-test audit log (or [])."""
    import os

    if not os.path.exists(audit.AUDIT_LOG):
        return []
    with open(audit.AUDIT_LOG, encoding="utf-8") as fh:
        return [line.rstrip("\n") for line in fh if line.strip()]


def test_log_event_writes_all_required_fields():
    audit.log_event("login", "success", user="alice", source="10.0.0.5")
    lines = _read_log()
    assert len(lines) == 1
    record = lines[0]
    # ISO-8601 UTC timestamp prefix (YYYY-MM-DDTHH:MM:SSZ).
    ts = record.split(" ", 1)[0]
    assert ts.endswith("Z") and ts[4] == "-" and ts[13] == ":"
    assert "event=login" in record
    assert "outcome=success" in record
    assert "user=alice" in record
    assert "src=10.0.0.5" in record


def test_missing_user_and_source_render_as_dash():
    audit.log_event("logout", "success")
    record = _read_log()[0]
    assert "user=-" in record
    assert "src=-" in record


def test_detail_is_quoted():
    audit.log_event(
        "access_denied", "failure", user="bob", source="x", detail="POST /send/general"
    )
    record = _read_log()[0]
    assert 'detail="POST /send/general"' in record


def test_control_characters_are_neutralised():
    # A newline smuggled through a field must not split the record into two.
    audit.log_event(
        "login", "failure", user="evil\nevent=login outcome=success", source="x"
    )
    lines = _read_log()
    assert len(lines) == 1
    assert "\n" not in lines[0].replace("\n", "")  # single physical line
    assert "evil event=login outcome=success" in lines[0]


def test_oversized_field_is_truncated():
    audit.log_event("login", "failure", user="a" * 500, source="x")
    record = _read_log()[0]
    assert "..." in record


def test_convenience_wrappers_set_event_and_outcome():
    cases = [
        (lambda: audit.login_success("u"), "event=login", "outcome=success"),
        (lambda: audit.login_failure("u"), "event=login", "outcome=failure"),
        (lambda: audit.logout("u"), "event=logout", "outcome=success"),
        (
            lambda: audit.account_lockout("u"),
            "event=account_lockout",
            "outcome=success",
        ),
        (lambda: audit.account_created("u"), "event=account_create", "outcome=success"),
        (
            lambda: audit.account_deleted("u", "hard"),
            "event=account_remove",
            "outcome=success",
        ),
        (
            lambda: audit.password_changed("u"),
            "event=password_change",
            "outcome=success",
        ),
        (lambda: audit.password_reset("u"), "event=password_reset", "outcome=success"),
        (
            lambda: audit.access_denied("u", "r"),
            "event=access_denied",
            "outcome=failure",
        ),
    ]
    for fn, event, outcome in cases:
        fn()
    lines = _read_log()
    assert len(lines) == len(cases)
    for (_, event, outcome), line in zip(cases, lines):
        assert event in line and outcome in line


def test_password_change_failure_outcome():
    audit.password_changed("u", outcome="failure")
    assert "event=password_change" in _read_log()[0]
    assert "outcome=failure" in _read_log()[0]


def test_account_deleted_records_type():
    audit.account_deleted("u", "soft")
    assert 'detail="type=soft"' in _read_log()[0]


def test_client_ip_none_outside_request_context():
    assert audit._client_ip() is None


def test_repointing_audit_log_reconfigures_handler(tmp_path):
    other = str(tmp_path / "other-audit.log")
    audit.AUDIT_LOG = other  # conftest restores the original via monkeypatch
    audit.log_event("login", "success", user="u", source="x")
    with open(other, encoding="utf-8") as fh:
        assert "event=login" in fh.read()


def test_failed_login_post_is_audited(client):
    client.post("/login", data={"username": "ghost", "password": "wrong"})
    records = "\n".join(_read_log())
    assert "event=login" in records
    assert "outcome=failure" in records
    assert "user=ghost" in records


def test_forbidden_channel_access_is_audited(alice):
    # alice is not a member of this private channel, so the route returns 403,
    # which the central after_request hook records as an access denial.
    resp = alice.get("/messages/private:99999")
    assert resp.status_code == 403
    records = "\n".join(_read_log())
    assert "event=access_denied" in records
    assert "user=alice" in records
