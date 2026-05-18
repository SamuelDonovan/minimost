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

- At least 8 characters.
- At least one uppercase ASCII letter.
- At least one digit.
- At least one special character from ``!@#$%^&*()_+-=[]{};\\':|,./<>?`~``.

**Brute-force protection**

Failed login attempts sleep for 3 seconds before the server responds. This
limits brute-force attacks to approximately 20 attempts per minute per
connection. For stronger protection, use a reverse proxy with rate limiting
(e.g. Nginx's ``limit_req_zone``).

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
  list defined in ``channels.json``. Users cannot post to arbitrary channel
  names.
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
The two places where table/column names are interpolated (the ``channel IN
(?, ?, ?)`` placeholder list in :func:`minimost.chat.channel_unreads`) use
only values from the server-controlled ``CHANNELS`` list, not user input.

**XSS (Cross-Site Scripting)**

The Jinja2 templating engine escapes HTML by default. In the JavaScript
frontend, user-supplied text is processed through an ``escapeHtml()``
function before being inserted into the DOM via ``innerHTML``. URLs are
auto-linked but sanitised to ``http``/``https`` schemes only.

**SSRF (Server-Side Request Forgery)**

The link preview endpoint validates URLs through :func:`minimost.preview._is_safe_url`
before making any outgoing request. The following are blocked:

- ``localhost``
- ``127.x.x.x`` (loopback)
- ``10.x.x.x``, ``172.16–31.x.x``, ``192.168.x.x`` (RFC 1918 private ranges)
- ``::1`` (IPv6 loopback)
- Non-HTTP/HTTPS schemes

**Path traversal (file serving)**

Uploaded images are served with :func:`flask.send_from_directory` using
:data:`minimost.chat.UPLOAD_DIR` as a root. Flask's implementation validates
that the resolved path is within the root directory, preventing
``../../../etc/passwd``-style traversal.

Uploaded image names are generated using UUID4 (``uuid.uuid4().hex``), so
the original filename submitted by the client is never used on the filesystem.

File Upload Security
--------------------

Only files with extensions in ``{".jpg", ".jpeg", ".png", ".gif", ".webp"}``
are accepted. Files with other extensions are silently skipped. However,
note that MiniMost does **not** validate the actual file content (magic bytes)
— a file named ``malicious.jpg`` with non-image content would be stored and
served. This is considered acceptable for a private LAN tool; add content
validation if deploying in a less-trusted environment.

The upload limit is 16 MiB, enforced by Flask's ``MAX_CONTENT_LENGTH``
configuration. Requests exceeding this limit are rejected before the route
handler runs.

Data Isolation
--------------

Each user's message history is stored in a separate SQLite database file
(``users/<username>.db``). This means:

- A bug that corrupts one user's database does not affect others.
- Database-level access control is possible at the filesystem level (e.g.
  each file is owned by the corresponding OS user account).
- A SQL query error in one user's route handler cannot read another user's
  messages — the wrong database is simply not open.

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

**No CSRF protection**

MiniMost does not use CSRF tokens. Its API is consumed by its own JavaScript
client using session cookies. On a private network behind a firewall this is
generally acceptable; on the public internet, consider adding Flask-WTF or
another CSRF protection layer.

**No rate limiting on signup**

Any unauthenticated visitor can create an account. If exposing MiniMost to
the internet, consider adding registration invite codes or IP-based rate
limiting on the ``/signup`` route.

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

The MiniMost codebase is scanned by:

- `Bandit <https://bandit.readthedocs.io/>`_ — Python SAST tool. Results are
  reviewed and suppressed with ``# nosec`` annotations where false positives
  are confirmed.
- `CodeQL <https://codeql.github.com/>`_ — GitHub's semantic code analysis.
  Run on every push via GitHub Actions.
- `Semgrep <https://semgrep.dev/>`_ — Additional rule-based scanning,
  including Flask-specific rules (e.g. NaN injection in query parameters).

Reporting Vulnerabilities
--------------------------

If you discover a security issue in MiniMost, please open a GitHub issue
or contact the maintainer directly. For critical vulnerabilities, use GitHub's
private security advisory feature.
