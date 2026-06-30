# MiniMost — ASD STIG Compliance Plan

This document tracks MiniMost's conformance to the **Application Security and
Development (ASD) STIG, V6R1** (DISA / cyber.mil) — the STIG that applies to
custom-developed applications. Scope is limited to the shippable code under
`src/minimost/`. Every item is achievable with **stdlib + Flask/Werkzeug only**
and runs on **Python 3.6** (no new dependencies).

> Full STIG compliance for a fielded DoD system also depends on the _hosting
> environment_ (DoD PKI certificates, a central audit/SIEM aggregator, CAC/PIV
> authentication, an approved OS baseline). Those are deployment concerns the
> application code cannot satisfy alone. This plan covers what the **code** can
> do to be as compliant as possible.

## Already compliant (keep it)

- **SQL injection (APSC-DV-002500)** — all queries use `?` bound parameters;
  dynamic SQL only concatenates constant clause fragments.
- **Password storage (APSC-DV-002560)** — PBKDF2-HMAC-SHA256 (Werkzeug), salted;
  only the hash is stored.
- **XSS (APSC-DV-002490/002500)** — Jinja2 autoescaping on; the only `| safe` is
  first-party CSS inlining.
- **Account lockout** — failed-attempt counting + timed lockout; login is
  rate-limited per IP.
- **Path traversal** — username regex `[A-Za-z0-9_\-]{1,32}`, `secure_filename`,
  UUID upload names.
- **CSRF on auth forms (APSC-DV-002500)** — per-session token + `SameSite=Lax`.
- **Transport** — TLS provisioned; session cookies `Secure`/`HttpOnly`.
- Dev server runs `debug=False` (no Werkzeug debugger / info leak).

## Work items

| #   | Item                          | Status                         | STIG refs                            |
| --- | ----------------------------- | ------------------------------ | ------------------------------------ |
| 1   | Security audit logging        | ✅ **Done** (`minimost.audit`) | APSC-DV-000340–000430, 000810–000900 |
| 2   | Session inactivity timeout    | ✅ **Done**                    | APSC-DV-000070 / 000080              |
| 3   | Security response headers     | ✅ **Done**                    | APSC-DV-002500                       |
| 4   | Custom generic error handlers | ✅ **Done**                    | APSC-DV-002880 / 002890              |
| 5   | Password policy hardening     | ☐ Planned                      | APSC-DV-001940 family                |
| 6   | DoD Notice & Consent banner   | ☐ Planned                      | logon banner                         |
| 7   | Concurrent-session limit      | ☐ Planned                      | APSC-DV-000010                       |
| 8   | Logoff confirmation page      | ✅ **Done**                    | APSC-DV-000100                       |
| 9   | Session ID rotation on auth   | ☐ Planned                      | APSC-DV-002250                       |

### 1. Security audit logging — ✅ Done

Implemented in `src/minimost/audit.py` (stdlib `logging` only). Appends one
machine-parseable line per security event to `audit.log` in the data root, each
record carrying _what_ (event), _when_ (ISO-8601 UTC), _where_ (source IP),
_who_ (user), and _outcome_. Events covered: login success/failure (incl.
non-existent and locked accounts), account lockout, logout, account
create/remove, password change/reset, and any 401/403 access denial (failed
CSRF, forbidden channel/DM/message access). Values are stripped of control
characters (log-injection defence); passwords, tokens, and message bodies are
never written.

The trail is bounded by rotation (relevant to audit-storage-capacity controls
such as APSC-DV-001340): the log rolls to a timestamped archive at
`audit_log_max_size_mb` or `audit_log_max_age_days`, retaining
`audit_log_backups` archives, coordinated across workers with an advisory lock.
Off-load records to a SIEM before they age out. See `docs/security.rst` →
_Audit logging_ and `docs/configuration.rst`.

### 2. Session inactivity timeout — ✅ Mechanism done; default needs tuning for compliance (APSC-DV-000070 / 000080)

The timeout mechanism is implemented and configurable via `session_idle_minutes`
in `settings.json`. `PERMANENT_SESSION_LIFETIME` is bound to that window and
sessions are marked permanent at login, so the signed cookie expires with it. A
`_enforce_idle_timeout` `before_request` hook (in `minimost.create_app`) clears
the session and redirects to `/login` once the window elapses since the last
user-initiated request, and audits a `session_timeout` event. Background pollers
(the SSE stream and its reconnect, the presence heartbeat, the sidebar badge
pollers, and in-call signal/state pollers — see `_PASSIVE_ENDPOINTS`) do **not**
refresh the timer, so an unattended-but-open tab is still logged out by its own
next poll. MiniMost has a single non-privileged role, so the 10-minute privileged
bound (APSC-DV-000080) collapses onto the same value.

> **Deployment note:** the shipped default (`session_idle_minutes`) is **2 weeks**
> for usability, which is intentionally **outside** the APSC-DV-000070 band. To
> meet the control, set `session_idle_minutes` to `15`. If `settings.json` is
> unreadable the code fails closed to the 15-minute baseline. Any value above 15
> minutes should be recorded as a documented risk acceptance.

### 3. Security response headers — ✅ Done (APSC-DV-002500)

A `_security_headers` `after_request` hook sets `X-Frame-Options: DENY` and a
CSP `frame-ancestors 'none'` (clickjacking), `X-Content-Type-Options: nosniff`,
`Referrer-Policy: no-referrer`, a conservative `Content-Security-Policy`, and
`Strict-Transport-Security` (only when MiniMost serves TLS). The CSP still
allows `'unsafe-inline'` for scripts/styles because the chat page ships inline
`<script>` and inlines CSS on the dev server; tightening to nonces is tracked
as a follow-up.

### 4. Custom generic error handlers — ✅ Done (APSC-DV-002880 / 002890)

`create_app` registers handlers for 400/403/404/405/413/429/500 that return a
fixed generic message — no stack trace, framework version, or request detail in
the body. Responses are content-negotiated: JSON (`{"error": ...}`) for API/fetch
callers, a small branded `error.html` page for browsers, with a plain-text
fallback if the template cannot render. The 500 handler relies on Flask logging
the traceback to the (admin-only) application log and additionally records a
generic `server_error` event in the audit trail; the exception text never
reaches the client.

### 5. Password policy hardening (APSC-DV-001940 family)

Current: ≥8 chars, ≥1 digit, ≥1 uppercase, ≥1 special. DoD requires:

- **≥15 characters** (currently 8) — APSC-DV-001955
- **≥1 lowercase** — not currently enforced — APSC-DV-001960
- **Password history / reuse prohibition** (≥5 generations) — APSC-DV-001980
- **Min 24h / max 60-day password age** — APSC-DV-001990 / 002000

Enforced in `auth._validate_password` plus small schema additions
(`password_history` table, `password_set_ts` column).

### 6. DoD Notice and Consent banner

DoD systems must display the Standard Mandatory DoD Notice and Consent Banner
before granting access, with explicit acknowledgement. Add it to `login.html`
with a click-through gate.

### 7. Concurrent-session limit (APSC-DV-000010)

No limit on simultaneous logins per account. Track an active-session marker
server-side (a small table in `auth.db` keyed by username + a session token)
and reject/evict additional sessions.

### 8. Logoff confirmation page — ✅ Done (APSC-DV-000100)

`/logout` clears the session and redirects to `/login?logged_out=1`; the login
page then displays an explicit confirmation banner ("You have been logged out.
Your session was securely terminated.") via a new `.auth-notice` style. The
banner shows only when the flag is present, and an `error` takes precedence over
it. The logout is still audited (`event=logout`).

### 9. Session ID rotation on auth (APSC-DV-002250)

Regenerate the session identifier on login and password change to prevent
session fixation (`session.clear()` then set `session["user"]` fresh).

## Environment / deployment notes (not code changes)

- **DoD PKI** — for compliance the served certificate must come from DoD PKI.
  The code already prefers an operator-supplied `cert.pem`/`key.pem` and only
  self-signs as a fallback; document the PKI path as the compliant deployment.
- **FIPS** — PBKDF2-SHA256 and TLS via the system OpenSSL are acceptable when
  running on a FIPS-validated OS module; avoid introducing any non-stdlib crypto.
- **Central audit aggregation** — forward `audit.log` to a SIEM via journald /
  rsyslog and restrict its filesystem permissions.

## References

- [ASD STIG on STIG Viewer](https://www.stigviewer.com/stigs/application_security_and_development)
- [ASD STIG V6R1 (cyber.trackr.live)](https://cyber.trackr.live/stig/Application_Security_and_Development/6/1)
