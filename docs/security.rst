Security
========

This page documents MiniMost's security model, the protections that are in
place, and the known limitations that operators should be aware of.

Authentication
--------------

**Password hashing**

Passwords are hashed using PBKDF2-HMAC-SHA256 via
:func:`werkzeug.security.generate_password_hash`. Each hash includes a
randomly generated salt. Plaintext passwords and bare SHA-256 hashes are
never stored.

**Password complexity**

Both the frontend (JavaScript, for immediate feedback) and the backend (Python,
as the authoritative check) enforce the following rules:

- At least ``password_min_length`` characters (default ``15``), and at most
  1024 (the upper bound is also guarded at login so an oversized password cannot
  force the server to spend CPU hashing it). The minimum can be raised in
  ``settings.json`` but never lowered below the built-in default.
- At least one uppercase ASCII letter.
- At least one lowercase ASCII letter.
- At least one digit.
- At least one special character from ``!@#$%^&*()_+-=[]{};\\':|,./<>?`~``.

These implement the ASD STIG APSC-DV-001940 family (length APSC-DV-001955,
lowercase APSC-DV-001960). See :doc:`configuration` for the tunable keys.

**Password reuse and age**

Three further controls limit how passwords may be reused and how long they live;
all are tunable in ``settings.json`` and a value of ``0`` disables the
individual control:

- **Reuse prohibition** (``password_history_count``, default ``5`` —
  APSC-DV-001980). Every password an account has used is recorded as a salted
  hash in the ``password_history`` table; a change or reset is rejected if the
  new password matches any of the most recent generations. Only hashes are kept,
  and the table is pruned to the configured number of generations per account.
- **Minimum age** (``password_min_age_hours`` — APSC-DV-001990). A
  user-initiated *change* is refused until the current password has been in
  place for the minimum age, which stops a user cycling through changes to flush
  the reuse history. The admin-mediated reset flow is exempt, since it is a
  recovery action rather than user churn.
- **Maximum age** (``password_max_age_days`` — APSC-DV-002000). At login a
  password older than the maximum is refused even when correct; the user is
  directed to the administrator reset flow (the same recovery path the
  forgot-password page describes). The ``users.password_set_ts`` column records
  when each password was set and backs both age checks; accounts that predate
  the feature are backfilled with the upgrade time so they are not treated as
  already expired.

Both age checks ship **disabled** (``0``) in the bundled ``settings.json`` for
usability — the same posture as ``session_idle_minutes`` — with built-in
fallbacks of ``24`` hours and ``60`` days. Set ``password_min_age_hours`` to
``24`` and ``password_max_age_days`` to ``60`` to enforce APSC-DV-001990 /
002000; leaving them disabled should be a documented risk acceptance. See
:doc:`configuration` for the tunable keys.

**Usernames**

Usernames are case-insensitive: ``Alice`` and ``alice`` refer to the same
account. The spelling chosen at registration is preserved for display, but
registration rejects names that differ only by case (preventing look-alike
impersonation) and login matches regardless of the case typed.

A small set of names is reserved and rejected at registration:
``minimost`` (the system message author), ``everyone`` (the channel-wide
``@``-mention keyword), and ``deleteduser`` (which would shadow the
"Deleted User" author used for soft-deleted accounts). The comparison is
case-insensitive.

**Brute-force protection**

The ``/login`` route is **rate limited per client IP** (see
`Denial-of-service mitigations`_ below), which bounds how fast credentials can
be guessed or sprayed from a single source without parking a worker thread on a
delay. (Earlier versions slept for 3 seconds on each failed attempt; that was
removed because a held sleep is itself a way to exhaust the worker pool — the
per-IP rate limit achieves the same throttling without tying up threads.)

In addition, **account lockout** temporarily disables an account after too many
consecutive failed logins. Once ``max_login_attempts`` (default ``5``)
consecutive failures are recorded, the account is locked for
``lockout_duration_minutes`` (default ``15``); during that window logins are
rejected without the password being checked. A successful login resets the
counter. Both values are configured in ``settings.json`` (see
:doc:`configuration`), and setting ``max_login_attempts`` to ``0`` disables the
feature. Lockout is tracked per account rather than per IP, so it complements
the per-IP rate limit: the rate limit caps total guessing volume from one
source, while lockout protects a specific targeted account.

**Password reset tokens**

Password reset links are generated only by administrators via the
``minimost reset-password`` CLI command (never through the web UI). Each token
is a 256-bit cryptographically random value produced by
:func:`python:secrets.token_urlsafe`. Tokens are:

- **Single-use** — marked ``used = 1`` in ``auth.db`` immediately after the
  password is changed; any replay attempt is rejected.
- **Time-limited** — expire after a configurable duration (default: 60 minutes).
- **Out-of-band** — the URL is printed to the administrator's terminal and never
  transmitted by MiniMost itself; the administrator shares it through a separate
  channel.

The user receives a system DM when a reset is requested, so they are aware if a
reset was initiated without their knowledge and can contact an administrator.

**Session security**

Flask signs session cookies with the ``SECRET_KEY`` loaded from
``secret.key``. A compromised secret key would allow an attacker to forge
session cookies. Protect ``secret.key`` with appropriate filesystem
permissions and never commit it to version control.

Authorization
-------------

**Login required**

Every route that serves user data is decorated with
:func:`minimost.auth.login_required`. Unauthenticated requests are
redirected to ``/login``.

**Channel access control**

:func:`minimost.chat.is_valid_channel` enforces two rules:

- **Public channels** — the channel name must be in the :data:`CHANNELS`
  list loaded from the ``channels`` key of ``settings.json``. Users cannot post
  to arbitrary channel names.
- **DM channels** — the authenticated user's username must appear in the
  ``dm:user1:user2`` channel string. Users cannot read or write to other
  users' DM conversations.

**Author-only operations**

Edit (:func:`minimost.chat.edit`) and delete
(:func:`minimost.chat.delete_message`) operations verify that the
authenticated user is the original sender of the message. Other users receive
``403 Forbidden``.

Injection Prevention
---------------------

**SQL injection**

All database queries use parameterized statements (``?`` placeholders).
There are no string-interpolated SQL queries in user-controlled data paths.
Where a query builds a dynamic ``IN (?, ?, …)`` list (e.g. the channel-access
filters in :func:`minimost.chat.channel_unreads`, ``search_messages`` and
``list_private_channels``), only the *number* of ``?`` markers is generated from
the data — every actual value is still passed as a bound parameter, never
interpolated into the SQL text.

**XSS (Cross-Site Scripting)**

The Jinja2 templating engine escapes HTML by default. In the JavaScript
frontend, user-supplied text is processed through an ``escapeHtml()``
function before being inserted into the DOM via ``innerHTML``. URLs are
auto-linked but sanitised to ``http``/``https`` schemes only.

**SSRF (Server-Side Request Forgery)**

The link preview endpoint applies three defences in order before making any
outgoing request:

1. **Scheme check** — only ``http`` and ``https`` URLs are accepted.
2. **Allowlist** (:func:`minimost.preview._is_allowed_host`) — the hostname
   must be an exact match or subdomain of an entry in
   :data:`minimost.preview._ALLOWED_PREVIEW_HOSTS`. Currently only
   ``bitbucket.org`` is permitted.
3. **Private-range block** (:func:`minimost.preview._is_safe_url`) — the
   hostname is matched against a regex that rejects loopback and RFC 1918
   private ranges (``localhost``, ``127.x.x.x``, ``10.x.x.x``,
   ``172.16–31.x.x``, ``192.168.x.x``, ``::1``).
4. **DNS resolution check** (:func:`minimost.preview._resolves_to_public_ip`)
   — the hostname is resolved and every returned IP address is verified to be
   public, preventing DNS rebinding attacks.

**Path traversal (file serving)**

Uploaded images are served with :func:`flask.send_from_directory` using
:data:`minimost.chat.UPLOAD_DIR` as a root. Flask's implementation validates
that the resolved path is within the root directory, preventing
``../../../etc/passwd``-style traversal.

Every stored filename begins with a fresh UUID4 (``uuid.uuid4().hex``). Images
are stored as ``<uuid>.<ext>``; all other files as
``<uuid>_<secure_filename(original)>`` — the original name is passed through
:func:`werkzeug.utils.secure_filename` before being appended, so a crafted name
can neither collide nor escape the uploads directory.

File Upload Security
--------------------

Files of **any** type are accepted. Images (``.jpg``, ``.jpeg``, ``.png``,
``.gif``, ``.webp``) are served inline; every other type is served as an
attachment (download), so the browser never renders it in the page's origin.
MiniMost does **not** validate file *content* (magic bytes) — a file named
``photo.jpg`` containing non-image bytes would be stored and served. This is
considered acceptable for a private LAN tool; add content validation if
deploying in a less-trusted environment.

A single upload is capped at ``max_upload_size_mb`` (default 25 MiB) — enforced
both per file in the route and globally by Flask's ``MAX_CONTENT_LENGTH``, which
rejects an oversized request before the handler runs. Avatar uploads are capped
separately by ``max_avatar_size_mb`` (default 5 MiB). The rate at which a single
account can upload is bounded by the per-user ``send`` and ``avatar`` rate limits
(see `Denial-of-service mitigations`_).

Disk use is also bounded in aggregate by ``max_upload_dir_size_mb``. When the
``uploads/`` directory exceeds that cap, files are evicted **fairly**: a file's
owner is the sender of the message that references it, and the uploader currently
consuming the most space has their oldest files removed first (orphaned files
with no owning message go first of all). This means a single account that floods
the directory has its *own* uploads purged before any other user's attachments —
a flood cannot be used to delete other people's files. The same fairness applies
to the message database cap ``max_message_db_size_mb`` (the heaviest sender is
trimmed first).

Denial-of-service mitigations
-----------------------------

Because anyone with an account (or, for some routes, any unauthenticated
visitor) can send requests, MiniMost includes in-process throttles to blunt the
most accessible denial-of-service (DoS) attacks. These use only the Python
standard library and Flask — no extra dependency — and are implemented in
:mod:`minimost.ratelimit`. They are enabled by default and can be turned off
with the ``rate_limit_enabled`` key in ``settings.json``.

**Request rate limiting.** Expensive or abuse-prone endpoints are capped using a
thread-safe sliding-window counter:

- ``/login``, ``/signup`` and the password-reset routes are limited **per client
  IP** — this throttles credential guessing, account-creation floods (the
  classic "create many accounts" attack), and repeated password-hashing (PBKDF2)
  work.
- ``/send``, avatar upload, and private-channel creation are limited **per
  authenticated user** — this throttles message/attachment floods and channel
  spam.

The defaults are deliberately generous, so ordinary interactive use never trips
them; they exist only to stop pathological volume. Each limit is an integer
count over a window in seconds and can be tuned via the ``rate_limits`` object in
``settings.json`` (see :doc:`configuration`). A throttled request receives
``429 Too Many Requests`` with a ``Retry-After`` header.

On the rare occasion a real user does hit a limit, the response is surfaced
rather than failing silently: the in-app actions (sending a message, uploading
an avatar, creating a channel) show a brief toast with the wait time and keep the
user's input intact so it can be retried, and the login/signup pages re-render
with the message as a normal inline form error instead of a raw status body.

**Concurrent SSE stream cap.** The live update stream (``GET /events``) holds one
worker thread open for the life of the connection, so a client that opens many
streams could exhaust the worker pool and lock everyone out. The number of
simultaneous streams **per user** is capped at
``max_event_streams_per_user`` (default 12 — far more than the handful of browser
tabs a real user keeps open); beyond that, new streams get ``429`` until an
existing one closes.

**Fair retention eviction.** The ``uploads/`` and message-database size caps
evict the heaviest-consuming account first rather than the globally oldest data,
so a flood cannot delete other users' history or files (see `File Upload
Security`_).

**Scope.** These counters live in each worker process, so with several Gunicorn
workers the effective ceiling is *limit × workers*. That is intentional: the goal
is to stop pathological abuse cheaply, not to enforce a globally exact quota. For
a hard, cross-worker ceiling — and to throttle traffic before it ever reaches the
application — put a reverse proxy in front (e.g. Nginx ``limit_req`` /
``limit_conn``). The in-process limits complement that layer rather than replace
it. Note that ``remote_addr`` is the proxy's address unless the proxy forwards
the real client IP and the deployment is configured to trust it.

Channel Access Control
----------------------

All messages live in one shared database (``users/messages.db``), so access is
enforced **at query time** rather than by filesystem separation. Every route
that reads or writes messages checks :func:`minimost.chat.is_valid_channel`
before touching the database:

- **Public channels** — the channel must be one of the configured names.
- **Private channels** — the caller must be a member (and late joiners only see
  history from their ``history_start_ts`` onward).
- **DMs** — the caller's username must appear in the ``dm:`` channel identifier.

This guard is applied consistently to the polling endpoint
(:func:`minimost.chat.messages`), to ``search_messages`` (which additionally
confines results to the set of channels the caller may read), and to
``channel_members``, so a crafted channel name cannot surface another user's
DMs or a private channel they don't belong to. All queries are parameterised, so
the channel identifier is never interpolated into SQL.

Audit logging
-------------

MiniMost writes a security audit trail (:mod:`minimost.audit`) to ``audit.log``
in the data root (see :func:`minimost.paths.data_dir`; on a packaged install
that is the systemd ``StateDirectory``, e.g. ``/var/lib/minimost``). Each record
is a single, machine-parseable line carrying the five fields an auditor needs —
*what* happened, *when* (ISO-8601 UTC), *where* it came from (source IP), *who*
(user identity), and the *outcome*::

    2026-06-29T18:04:11Z event=login outcome=failure user=alice src=10.0.0.5

The following security-relevant events are recorded:

- authentication: successful login, failed login (including attempts against a
  non-existent account and against a locked account), and logout;
- account lifecycle: account creation, account removal (soft/hard), and an
  account being locked after consecutive failed logins;
- credential changes: password change and password reset (success and failure);
- access-control denials: any ``401``/``403`` response, which covers failed CSRF
  validation and attempts to reach a channel, DM, or message the caller may not
  access.

Records are written with the standard-library :mod:`logging` module only (no new
dependency). Interpolated values are stripped of control characters before they
are written, so a newline smuggled through a username or path cannot forge or
split a record (log injection). Passwords, session tokens, and message bodies
are never written to the trail. The file is append-only and safe for multiple
Gunicorn workers to share; operators should forward it to a central
aggregator/SIEM (for example via journald or rsyslog) and restrict its
permissions, since it is the authoritative record of authentication and
access-control activity.

The log is rotated so it does not grow without bound. It is rolled to a
timestamped archive once it reaches ``audit_log_max_size_mb`` or is older than
``audit_log_max_age_days`` (either trigger can be disabled with ``0``), and
``audit_log_backups`` archives are retained — see :doc:`configuration`. Rotation
is coordinated across workers with an advisory lock so they never clobber each
other, and each worker reopens the fresh file automatically. Because pruning
deletes the oldest archives, a deployment with audit-retention requirements
should off-load records centrally before they age out.

Session inactivity timeout
--------------------------

Authenticated sessions are terminated after a period of inactivity, configured
by ``session_idle_minutes`` in ``settings.json``. The signed session cookie is
bound to the same lifetime via ``PERMANENT_SESSION_LIFETIME``, and a
``before_request`` hook clears the session and redirects to ``/login`` once the
idle window is exceeded, auditing a ``session_timeout`` event. If
``settings.json`` cannot be read the timeout falls back to
``minimost._SESSION_IDLE_SECONDS`` (the 15-minute STIG baseline).

Only genuine user interaction refreshes the timer. The frontend hits a number
of endpoints automatically on timers — the ``/events`` SSE stream and its
periodic reconnect, the presence heartbeat, the sidebar badge pollers, and the
in-call signal/state pollers — and these are excluded from refreshing activity
(``minimost._PASSIVE_ENDPOINTS``). As a result an unattended tab that is left
open is still logged out by its own next background poll once it has been idle
past the window. MiniMost has a single, non-privileged user role, so no separate
(shorter) administrator timeout applies.

.. note::

   The shipped default for ``session_idle_minutes`` is **2 weeks**, chosen for
   usability and intentionally outside the APSC-DV-000070 band. A deployment
   that must satisfy that control should set ``session_idle_minutes`` to ``15``.
   Setting it to ``0`` disables the inactivity logout entirely (sessions are
   never terminated for being idle), which likewise does not satisfy
   APSC-DV-000070.

Session identifier rotation
---------------------------

To defeat session fixation, the session identifier is regenerated whenever
authentication state changes. On login and signup the existing session is
cleared before the authenticated session is established, so a session an
attacker may have fixed in the victim's browser is discarded rather than
inherited, and a fresh identifier is minted; a password change rotates the
identifier while keeping the user logged in. Logout clears the session
entirely. (Flask's signed-cookie sessions are themselves resistant to classic
fixation — an attacker cannot forge a valid cookie without the secret key — so
this is defence in depth.)

Security response headers
-------------------------

Every response carries a set of defensive headers:

- ``X-Frame-Options: DENY`` and a Content-Security-Policy ``frame-ancestors
  'none'`` prevent the UI from being framed (clickjacking).
- ``X-Content-Type-Options: nosniff`` disables MIME sniffing.
- ``Referrer-Policy: no-referrer`` keeps URLs (which may carry a reset token)
  out of the ``Referer`` header.
- A conservative ``Content-Security-Policy`` constrains the origins for scripts,
  styles, images, media, and connections. It still permits ``'unsafe-inline'``
  for scripts and styles because the chat page ships inline ``<script>`` and the
  stylesheet macro inlines CSS on the dev server; moving to nonces is a planned
  hardening step.
- ``Strict-Transport-Security`` is sent only when MiniMost actually serves TLS
  (the same condition that gates the ``Secure`` session cookie), so a
  plain-HTTP reverse-proxy deployment is unaffected.

Error handling
--------------

MiniMost registers generic handlers for the common HTTP errors (400, 403, 404,
405, 413, 429, 500). Error responses contain only the status code and a fixed,
non-revealing message — never a stack trace, framework version, or request
detail — and are content-negotiated: a JSON ``{"error": ...}`` body for
API/fetch callers and a small branded ``error.html`` page for browsers (falling
back to plain text if the template cannot render). The development server and
Gunicorn both run with Flask debugging off, so the interactive debugger is never
exposed.

For a server error, Flask logs the full traceback to the application log (which
only administrators can read) and MiniMost additionally records a generic
``server_error`` entry in the audit trail; the exception text never reaches the
client.

Known Limitations
-----------------

**No end-to-end encryption**

Messages are stored in plaintext SQLite files. An administrator (or anyone
with filesystem access) can read all messages. MiniMost is intended as an
internal LAN tool, not a secure messenger. Do not use it for sensitive
communications.

**No audit log**

There is no built-in audit trail of who accessed what and when. SQLite's WAL
files are ephemeral and not preserved across checkpoints.

**CSRF protection scope**

CSRF tokens are enforced on every state-changing request to the **auth**
blueprint — ``/login``, ``/signup``, ``/reset-password/<token>`` and
``/change-password`` — via a session-stored token (rendered as a hidden
``<input>`` in each form, or sent by ``fetch``) validated in a
``before_request`` hook. The chat, presence, and calls API endpoints rely on
Flask's signed, ``SameSite=Lax`` session cookie for authentication; these
endpoints do not require CSRF tokens as they are not reachable via cross-origin
HTML forms.

**Open registration**

Any unauthenticated visitor can create an account. Signup is rate limited per
client IP (see `Denial-of-service mitigations`_), which bounds account-creation
floods, but there is no invite-code or approval gate: anyone who can reach the
page can register. If exposing MiniMost to the internet, consider adding
registration invite codes, an approval step, or stricter proxy-level limits on
the ``/signup`` route.

**TLS / HTTPS**

Voice and video calling requires a secure context — browsers refuse to grant
microphone, camera, and WebRTC access over plain HTTP.  MiniMost automatically
generates a self-signed TLS certificate on first run in pure Python (standard
library only — no ``openssl`` binary; see :doc:`deployment`).  This certificate
is suitable for LAN use; replace it with a CA-signed certificate for
public-facing deployments.

The TLS private key (``key.pem``) should be protected with the same
filesystem permissions as ``secret.key`` and ``auth.db``.

**WebRTC media and the STUN server**

Call and screen-share media is exchanged peer-to-peer over WebRTC and is
encrypted in transit by WebRTC's mandatory DTLS-SRTP — it never passes through
the server.  The bundled STUN server (:mod:`minimost.stun`) answers only
unauthenticated STUN Binding Requests with the requester's reflexive address
(standard, public-by-design behaviour); it stores no data, performs no
authentication, and is intentionally bound to all interfaces so LAN peers can
reach it.  Because MiniMost uses **no public STUN/TURN servers**, no call
metadata or IP addresses are sent to third parties.  As a LAN application it
expects to run on a trusted network; the STUN UDP port (``3478`` by default)
need only be reachable by trusted peers.

**Session cookie flags**

The ``HttpOnly`` flag is set by Flask by default. The ``Secure`` flag
(which restricts cookies to HTTPS) must be set manually when running behind
a TLS-terminating reverse proxy:

.. code-block:: python

    # Add to create_app() if running behind HTTPS:
    app.config["SESSION_COOKIE_SECURE"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

Security Scanning
-----------------

The MiniMost codebase is scanned automatically on every push via GitHub
Actions, and weekly on a schedule:

- `Bandit <https://bandit.readthedocs.io/>`_ — Python-specific SAST tool.
  Results are reviewed and suppressed with ``# nosec`` annotations where false
  positives are confirmed.
- `Semgrep <https://semgrep.dev/>`_ — Rule-based SAST, including
  Flask-specific rules (``p/python``, ``p/flask``).
- `CodeQL <https://codeql.github.com/>`_ — GitHub's semantic code analysis
  engine; catches data-flow and taint-tracking issues beyond pattern matching.
- `SonarCloud <https://sonarcloud.io/>`_ — Continuous quality and security
  gate covering code smells, hotspots, and coverage tracking.
- `pip-audit <https://github.com/pypa/pip-audit>`_ — Audits installed
  dependencies against the PyPI Advisory Database and the Open Source
  Vulnerability (OSV) database to detect known CVEs in third-party packages.

Reporting Vulnerabilities
--------------------------

If you discover a security issue in MiniMost, please open a GitHub issue
or contact the maintainer directly. For critical vulnerabilities, use GitHub's
private security advisory feature.
