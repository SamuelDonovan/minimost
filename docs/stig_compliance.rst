STIG Compliance
===============

This page documents how MiniMost conforms to the **Application Security and
Development (ASD) STIG, V6R1** (DISA / cyber.mil) — the Security Technical
Implementation Guide that applies to custom-developed applications. It describes
which controls the application code satisfies, how each is implemented, and which
controls depend on the deployment environment rather than the code.

Scope
-----

This assessment covers the shippable application code under ``src/minimost/``.
Every control below is met with the **Python standard library plus Flask /
Werkzeug only** — no additional dependencies — and runs on **Python 3.6**.

Full STIG compliance for a fielded DoD system also depends on the *hosting
environment* — DoD PKI certificates, a central audit/SIEM aggregator, CAC/PIV
authentication, and an approved OS baseline. Those are deployment concerns that
application code cannot satisfy on its own; they are called out under
`Environment and deployment controls`_ below. This page covers what the **code**
does to be as compliant as possible.

.. note::

   Two control families ship with **usability-oriented defaults that are
   intentionally outside the STIG band** — the session inactivity timeout and
   the two password-age checks. Each has a built-in fail-closed fallback and a
   one-line setting to bring it into compliance; see the relevant rows below and
   :doc:`configuration`. Any value left outside the band should be recorded as a
   documented risk acceptance.

Control matrix
--------------

.. list-table::
   :header-rows: 1
   :widths: 22 12 40 26

   * - Control area
     - Status
     - How MiniMost satisfies it
     - STIG references
   * - SQL injection
     - Compliant
     - All queries use ``?`` bound parameters; dynamic SQL only generates the
       *number* of placeholders, never interpolates values.
     - APSC-DV-002500
   * - Password storage
     - Compliant
     - PBKDF2-HMAC-SHA256 (Werkzeug), per-password salt; only the hash is stored.
     - APSC-DV-002560
   * - Cross-site scripting (XSS)
     - Compliant
     - Jinja2 autoescaping on; frontend ``escapeHtml()`` before ``innerHTML``;
       URLs restricted to ``http``/``https``.
     - APSC-DV-002490 / 002500
   * - Account lockout & brute force
     - Compliant
     - Consecutive-failure lockout plus per-IP rate limiting on ``/login``.
     - APSC-DV-000110 family
   * - Path traversal
     - Compliant
     - Username regex ``[A-Za-z0-9_\-]{1,32}``, ``secure_filename``, UUID4 upload
       names, ``send_from_directory`` root confinement.
     - APSC-DV-002560 / 002570
   * - CSRF on auth forms
     - Compliant
     - Per-session token validated in a ``before_request`` hook, plus
       ``SameSite=Lax`` cookies.
     - APSC-DV-002500
   * - Security audit logging
     - Compliant
     - ``minimost.audit`` writes one machine-parseable record per security event
       with what/when/where/who/outcome; rotated and bounded.
     - APSC-DV-000340–000430, 000810–000900, 001340
   * - Session inactivity timeout
     - Compliant (tune default)
     - ``before_request`` idle hook clears the session and audits a
       ``session_timeout``; passive pollers do not refresh the timer.
     - APSC-DV-000070 / 000080
   * - Security response headers
     - Compliant
     - ``after_request`` hook sets frame, sniff, referrer, CSP, and HSTS headers.
     - APSC-DV-002500
   * - Generic error handlers
     - Compliant
     - Fixed non-revealing messages for 400/403/404/405/413/429/500; no stack
       trace or version leak; debugger disabled.
     - APSC-DV-002880 / 002890
   * - Password policy hardening
     - Compliant (tune default)
     - Length ≥ 15, character classes, reuse history, and min/max age enforced in
       the auth flows.
     - APSC-DV-001940 family
   * - Logoff confirmation
     - Compliant
     - ``/logout`` terminates the session and shows an explicit confirmation
       banner on the login page.
     - APSC-DV-000100
   * - Session ID rotation on auth
     - Compliant
     - Session cleared and identifier regenerated on login/signup; rotated on
       password change.
     - APSC-DV-002250

Baseline protections
--------------------

These controls are structural to the application and require no configuration.

**SQL injection (APSC-DV-002500).** Every database query uses parameterised
statements. Where a query builds a dynamic ``IN (?, ?, …)`` list, only the number
of markers is derived from the data — each value is still bound, never
interpolated. See :doc:`security` → *Injection Prevention*.

**Password storage (APSC-DV-002560).** Passwords are hashed with
PBKDF2-HMAC-SHA256 via :func:`werkzeug.security.generate_password_hash`, each
with a random salt; plaintext and bare hashes are never stored.

**Cross-site scripting (APSC-DV-002490 / 002500).** Jinja2 autoescaping is on;
the only ``| safe`` use is first-party CSS inlining. In the frontend,
user-supplied text passes through ``escapeHtml()`` before DOM insertion, and
auto-linked URLs are restricted to ``http``/``https`` schemes.

**Account lockout and brute-force protection.** After ``max_login_attempts``
(default 5) consecutive failures an account is locked for
``lockout_duration_minutes`` (default 15); ``/login`` is additionally rate
limited per client IP. Lockout is per-account and the rate limit is per-IP, so
they complement one another. See :doc:`security` → *Brute-force protection*.

**Path traversal.** Usernames are constrained to ``[A-Za-z0-9_\-]{1,32}``, upload
names begin with a fresh UUID4 with the original passed through
:func:`werkzeug.utils.secure_filename`, and files are served via
:func:`flask.send_from_directory`, which confines the resolved path to the
uploads root.

**CSRF on auth forms (APSC-DV-002500).** State-changing requests to the auth
blueprint carry a per-session token validated in a ``before_request`` hook;
session cookies are ``SameSite=Lax``.

**Transport.** TLS is provisioned (operator-supplied certificate preferred,
self-signed fallback); session cookies are ``HttpOnly`` and ``Secure`` when
MiniMost serves TLS.

**No information leak from the dev server.** Both the development server and
Gunicorn run with Flask debugging off, so the interactive Werkzeug debugger is
never exposed.

Audit logging (APSC-DV-000340–000430, 000810–000900)
-----------------------------------------------------

:mod:`minimost.audit` (standard-library :mod:`logging` only) appends one
machine-parseable line per security event to ``audit.log`` in the data root. Each
record carries the five fields an auditor needs — *what* (event), *when*
(ISO-8601 UTC), *where* (source IP), *who* (user), and *outcome*::

    2026-06-29T18:04:11Z event=login outcome=failure user=alice src=10.0.0.5

Recorded events include login success/failure (including non-existent and locked
accounts), account lockout, logout, account create/remove, password
change/reset, and any 401/403 access denial (failed CSRF, forbidden
channel/DM/message access). Interpolated values are stripped of control
characters (log-injection defence); passwords, tokens, and message bodies are
never written.

The trail is bounded by rotation (relevant to audit-storage-capacity controls
such as APSC-DV-001340): the log rolls to a timestamped archive at
``audit_log_max_size_mb`` or ``audit_log_max_age_days``, retaining
``audit_log_backups`` archives, coordinated across workers with an advisory lock.
Because pruning deletes the oldest archives, off-load records to a SIEM before
they age out. See :doc:`security` → *Audit logging* and :doc:`configuration`.

Session inactivity timeout (APSC-DV-000070 / 000080)
----------------------------------------------------

The timeout is configured by ``session_idle_minutes``.
``PERMANENT_SESSION_LIFETIME`` is bound to that window and sessions are marked
permanent at login, so the signed cookie expires with it. A
``_enforce_idle_timeout`` ``before_request`` hook clears the session, redirects
to ``/login``, and audits a ``session_timeout`` event once the window elapses
since the last user-initiated request. Background pollers — the SSE stream and
its reconnect, the presence heartbeat, the sidebar badge pollers, and in-call
signal/state pollers (``_PASSIVE_ENDPOINTS``) — do **not** refresh the timer, so
an unattended-but-open tab is still logged out by its own next poll. MiniMost has
a single non-privileged role, so the 10-minute privileged bound (APSC-DV-000080)
collapses onto the same value.

.. warning::

   The shipped default for ``session_idle_minutes`` is **2 weeks** for usability,
   intentionally **outside** the APSC-DV-000070 band. To meet the control set it
   to ``15``. If ``settings.json`` is unreadable the code fails closed to the
   15-minute baseline (``minimost._SESSION_IDLE_SECONDS``). Any value above 15
   minutes should be recorded as a documented risk acceptance.

Security response headers (APSC-DV-002500)
------------------------------------------

A ``_security_headers`` ``after_request`` hook sets ``X-Frame-Options: DENY`` and
a CSP ``frame-ancestors 'none'`` (clickjacking), ``X-Content-Type-Options:
nosniff``, ``Referrer-Policy: no-referrer``, a conservative
``Content-Security-Policy``, the ``Cross-Origin-Opener-Policy`` /
``Cross-Origin-Embedder-Policy`` / ``Cross-Origin-Resource-Policy`` isolation
trio, a ``Permissions-Policy`` that denies unused browser features (and scopes
camera/microphone/screen-capture to same-origin for the calling feature), and
``Strict-Transport-Security`` (only when MiniMost serves TLS). The CSP still
allows ``'unsafe-inline'`` for scripts and styles because the chat page ships
inline ``<script>`` and inlines CSS on the dev server; tightening to nonces is
tracked as a follow-up.

Generic error handlers (APSC-DV-002880 / 002890)
------------------------------------------------

``create_app`` registers handlers for 400/403/404/405/413/429/500 that return a
fixed generic message — no stack trace, framework version, or request detail in
the body. Responses are content-negotiated: JSON (``{"error": …}``) for
API/fetch callers, a small branded ``error.html`` page for browsers, with a
plain-text fallback if the template cannot render. The 500 handler relies on
Flask logging the traceback to the admin-only application log and additionally
records a generic ``server_error`` event in the audit trail; the exception text
never reaches the client.

Password policy hardening (APSC-DV-001940 family)
-------------------------------------------------

Complexity is enforced in ``auth._validate_password`` (with a frontend mirror in
``auth-password-rules.js`` / ``_password_fields.html``); reuse and age are
enforced across the signup, change, reset, and login flows, backed by a
``password_set_ts`` column on ``users`` and a ``password_history`` table (schema
in ``database.py``, with a migration that backfills existing accounts so they are
neither expired nor historyless after upgrade). All knobs are read fresh per
request; ``0`` disables the reuse/age checks, while the length minimum can only
be raised, never lowered below 15.

- **≥ 15 characters** — ``password_min_length`` (default 15) — APSC-DV-001955
- **≥ 1 lowercase** (plus the existing digit / uppercase / special) —
  APSC-DV-001960
- **Reuse prohibition** of the last ``password_history_count`` (default 5)
  generations, on change *and* reset — APSC-DV-001980
- **Minimum age** ``password_min_age_hours`` on user-initiated change; the admin
  reset flow is exempt — APSC-DV-001990
- **Maximum age** ``password_max_age_days``: an aged password is refused at login
  and the user is routed to the admin reset flow — APSC-DV-002000

.. warning::

   Like ``session_idle_minutes``, the two password-age controls ship **disabled**
   (``0``) for usability, while length, lowercase, and reuse ship enforced. The
   code falls back to ``24`` hours / ``60`` days when the keys are absent. To meet
   APSC-DV-001990 / 002000 set ``password_min_age_hours`` to ``24`` and
   ``password_max_age_days`` to ``60``; leaving either at ``0`` should be recorded
   as a documented risk acceptance.

See :doc:`security` → *Password reuse and age* and :doc:`configuration`.

Logoff confirmation (APSC-DV-000100)
------------------------------------

``/logout`` clears the session and redirects to ``/login?logged_out=1``; the
login page then displays an explicit confirmation banner ("You have been logged
out. Your session was securely terminated.") via the ``.auth-notice`` style. The
banner shows only when the flag is present, and an ``error`` takes precedence over
it. The logout is audited (``event=logout``).

Session ID rotation on authentication (APSC-DV-002250)
------------------------------------------------------

On login and signup, ``_start_authenticated_session`` calls ``session.clear()``
before establishing the authenticated session, so any session an attacker fixed
in the victim's browser is discarded rather than inherited, and a fresh session
identifier (``_sid``) is minted. On a password change, ``_rotate_session_id``
regenerates ``_sid`` without clearing the session, so the user stays logged in
and the CSRF token is preserved. Logout clears the session. Flask's signed-cookie
sessions are themselves resistant to classic fixation — an attacker cannot mint a
valid cookie without the secret key — so this is defence in depth.

Environment and deployment controls
------------------------------------

The following controls cannot be satisfied by application code alone; they are
properties of the deployment.

- **DoD PKI (transport).** For compliance the served certificate must come from
  DoD PKI. The code already prefers an operator-supplied ``cert.pem`` /
  ``key.pem`` and only self-signs as a fallback; document the PKI path as the
  compliant deployment.
- **FIPS.** PBKDF2-SHA256 and TLS via the system OpenSSL are acceptable when
  running on a FIPS-validated OS module; avoid introducing any non-stdlib crypto.
- **Central audit aggregation.** Forward ``audit.log`` to a SIEM via journald /
  rsyslog and restrict its filesystem permissions, since it is the authoritative
  record of authentication and access-control activity.

References
----------

- `ASD STIG on STIG Viewer
  <https://www.stigviewer.com/stigs/application_security_and_development>`_
- `ASD STIG V6R1 (cyber.trackr.live)
  <https://cyber.trackr.live/stig/Application_Security_and_Development/6/1>`_
