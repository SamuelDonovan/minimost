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

- At least 8 characters, and at most 1024 (the upper bound is also guarded at
  login so an oversized password cannot force the server to spend CPU hashing
  it).
- At least one uppercase ASCII letter.
- At least one digit.
- At least one special character from ``!@#$%^&*()_+-=[]{};\\':|,./<>?`~``.

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

Failed login attempts sleep for 3 seconds before the server responds. This
limits brute-force attacks to approximately 20 attempts per minute per
connection, and — because it applies to every failed attempt — also slows
password spraying across many accounts from a single source. For stronger
protection, use a reverse proxy with rate limiting (e.g. Nginx's
``limit_req_zone``).

In addition, **account lockout** temporarily disables an account after too many
consecutive failed logins. Once ``max_login_attempts`` (default ``5``)
consecutive failures are recorded, the account is locked for
``lockout_duration_minutes`` (default ``15``); during that window logins are
rejected without the password being checked. A successful login resets the
counter. Both values are configured in ``settings.json`` (see
:doc:`configuration`), and setting ``max_login_attempts`` to ``0`` disables the
feature. Lockout is tracked per account rather than per IP, so it complements —
but does not replace — proxy-level rate limiting.

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
separately by ``max_avatar_size_mb`` (default 5 MiB).

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

**No rate limiting on signup**

Any unauthenticated visitor can create an account. If exposing MiniMost to
the internet, consider adding registration invite codes or IP-based rate
limiting on the ``/signup`` route.

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
