Configuration
=============

MiniMost is designed to work out-of-the-box with zero configuration. All
settings have sensible defaults and only need to be changed to customize the
application for your environment.

settings.json
-------------

**Location:** ``src/minimost/settings.json`` — the file is bundled inside the
package so it ships in the wheel.

The main configuration file for MiniMost. It is a JSON object. All keys are
optional — missing keys fall back to built-in defaults.

Example (showing all available keys with their defaults)::

    {
        "channels": ["general", "software", "firmware", "systems", "off-topic"],
        "image_retention_days": 30,
        "file_retention_days": 30,
        "message_retention_days": 770,
        "max_message_db_size_mb": 1024,
        "max_upload_dir_size_mb": 2048,
        "max_upload_size_mb": 25,
        "max_avatar_size_mb": 5,
        "stun_port": 3478,
        "max_login_attempts": 5,
        "lockout_duration_minutes": 15
    }

MiniMost limits how much disk it uses in two complementary ways. **Age-based**
retention (``*_retention_days``) deletes content once it gets old enough.
**Size-based** caps (``max_*_size_mb`` on the message database and the uploads
directory) delete the oldest content once a store grows past a limit. Both run
in the same background cleanup pass; whichever condition is hit first removes the
content. The two are independent, so you can cap by age, by size, or both.

``channels``
    List of public channel names visible to all users. Channels are displayed
    in the sidebar in the order listed. Changes take effect on the **next server
    restart**. If this key is absent or the file cannot be read, MiniMost falls
    back to a single ``"general"`` channel. Channel names should be short,
    lowercase, and contain no spaces.

``image_retention_days``
    How many days to keep image attachments in ``uploads/`` before the
    background cleanup thread removes them. Defaults to ``30``. Changes take
    effect at the next scheduled cleanup run — no restart required. See
    :doc:`administration` for details.

``file_retention_days``
    How many days to keep non-image file attachments in ``uploads/`` before
    the background cleanup thread removes them. Defaults to ``30``. Kept
    separate from ``image_retention_days`` so administrators can apply
    different retention policies to images versus documents, archives, etc.
    Changes take effect at the next scheduled cleanup run — no restart required.

``message_retention_days``
    How many days to keep messages in the shared ``users/messages.db`` before
    they are permanently deleted. Unlike the soft-delete used when a user
    deletes a message, this removes the database rows entirely (along with their
    reactions and search-index entries) so the database does not grow without
    bound over time. Defaults to ``770`` (approximately two years). Changes take
    effect at the next scheduled cleanup run — no restart required.

    .. note::

       Messages deleted by this process are gone permanently — they cannot
       be recovered. Set this value to a period that comfortably covers how
       far back your users ever need to scroll.

``max_message_db_size_mb``
    Total **size cap**, in megabytes, for the shared message database
    ``users/messages.db``. When the database exceeds this size, the cleanup
    thread permanently deletes the **oldest** messages (lowest timestamp first),
    along with their reactions and search-index entries, until it fits — then
    compacts the file so the space is returned to disk. This complements
    ``message_retention_days``: age-based retention bounds *how old* messages
    get, while this bounds *how large* the database grows, regardless of age.
    Defaults to ``1024``. Set to ``0`` (or any non-positive value) to disable
    the size cap. Changes take effect at the next scheduled cleanup run — no
    restart required.

    .. note::

       Size is measured against the database's *live* data (free pages left by
       earlier deletes are excluded), so messages are never deleted merely
       because space has not yet been reclaimed. As with age-based retention,
       deletions are permanent.

``max_upload_dir_size_mb``
    Total **size cap**, in megabytes, for the ``uploads/`` attachment directory.
    When the combined size of all stored attachments exceeds this value, the
    cleanup thread deletes the **oldest** files (by modification time) until the
    directory fits. This complements ``image_retention_days`` /
    ``file_retention_days``: age-based retention bounds *how old* attachments
    get, while this bounds the *total* footprint — useful when a burst of large
    uploads would otherwise fill the disk before aging out. Defaults to ``2048``.
    Set to ``0`` (or any non-positive value) to disable the size cap. Changes
    take effect at the next scheduled cleanup run — no restart required.

    .. note::

       This is distinct from ``max_upload_size_mb``, which limits a *single*
       upload. This key limits the *combined* size of everything in ``uploads/``.

``max_upload_size_mb``
    Maximum size in megabytes allowed for a single file attachment uploaded
    via the message input. Applies to all file types. Defaults to ``25``.
    The server enforces this limit per file and returns ``413`` if it is
    exceeded; the browser also warns the user before attempting the upload.
    Changes require a **server restart** to take effect.

``max_avatar_size_mb``
    Maximum size in megabytes allowed for a profile avatar upload. The browser
    resizes the chosen image to 128×128 pixels before sending, so the upload
    is always small in practice — this limit guards against oversized source
    files being loaded into browser memory. Defaults to ``5``. Changes require
    a **server restart** to take effect.

``stun_port``
    UDP port the bundled STUN server listens on, used by WebRTC calls and
    screen sharing so LAN peers can gather a server-reflexive ICE candidate.
    Must be an integer in the range ``1``–``65535``. Defaults to ``3478`` (the
    IANA-assigned STUN port). Avoid the OS ephemeral range
    (typically ``32768``–``60999`` on Linux) to prevent bind collisions.
    Changes require a **server restart** to take effect.

``max_login_attempts``
    Number of **consecutive failed login attempts** allowed against an existing
    account before it is temporarily locked. Defaults to ``5``. Set to ``0`` (or
    any non-positive value) to **disable** account lockout entirely. The counter
    resets to zero on the next successful login. Read fresh on every login
    attempt, so changes take effect without a restart.

``lockout_duration_minutes``
    How long, in minutes, an account remains locked once
    ``max_login_attempts`` is reached. During the lockout window every login is
    rejected **without checking the password**, and the user is shown how many
    minutes remain. Defaults to ``15``. Read fresh on every login attempt, so
    changes take effect without a restart.

    .. note::

       Lockout is tracked **per account** (in the ``users.failed_attempts`` and
       ``users.lockout_until`` columns of ``auth.db``), not per IP address. A
       lockout message confirms that the account exists, which is a deliberate
       trade-off for clear user feedback; the rest of the login flow keeps
       invalid-username and invalid-password failures indistinguishable.

.. warning::

   Removing a channel from ``settings.json`` does not delete its message
   history. The messages remain in the message database but the channel will
   no longer appear in the sidebar. If you re-add the channel name later,
   the history reappears.

secret.key
----------

**Location:** ``<project_root>/secret.key``

A 64-character hexadecimal string used as Flask's ``SECRET_KEY`` for signing
session cookies. MiniMost generates this file automatically on first startup
using :func:`secrets.token_hex`.

.. important::

   Keep this file secret and do not commit it to version control. If the
   secret key changes, all existing browser sessions are invalidated and
   users must log in again.

   Back it up alongside your databases when migrating to a new server.

auth.db
-------

**Location:** ``<project_root>/auth.db``

The shared SQLite database that stores user credentials. Created automatically
on first startup. Contains a single table:

.. code-block:: sql

    CREATE TABLE users (
        username TEXT PRIMARY KEY,
        password_hash TEXT NOT NULL
    );

- ``password_hash`` stores a Werkzeug PBKDF2 hash, never plaintext.
- To reset a forgotten password, update this column directly with a new hash.

**Generating a replacement hash:**

.. code-block:: python

    from werkzeug.security import generate_password_hash
    print(generate_password_hash("NewPassword123!"))

Then update the database::

    sqlite3 auth.db
    UPDATE users SET password_hash = '<output_from_above>' WHERE username = 'alice';
    .quit

presence.db
-----------

**Location:** ``<project_root>/presence.db``

The shared SQLite database for real-time state: presence status, typing
indicators, private-channel membership, and call state. Created automatically on
first startup. (Read receipts and reactions are **not** here — they live in the
shared message database; see ``users/`` below.)

This database can be safely deleted if it becomes corrupted — it will be
recreated on next startup. The only data lost is:

- Presence states (users will appear offline until they next reload).
- Typing indicators (transient — no user-visible impact).
- Private-channel membership (private channels would need to be recreated).
- Active call state (any in-progress calls are dropped).

users/ directory
----------------

**Location:** ``<project_root>/users/``

Contains the single shared message store, ``messages.db``: the ``messages``
table (full history), the trigram full-text search index, the ``reactions``
table, and the per-``(user, channel)`` read-state watermarks.

This file is the primary data store of MiniMost. Back it up regularly. Its size
is bounded by ``"message_retention_days"`` (age) and ``"max_message_db_size_mb"``
(total size) — see the ``settings.json`` keys above and :doc:`administration`.

uploads/ directory
------------------

**Location:** ``<project_root>/uploads/``

Stores all message file attachments. Two naming schemes are used:

- **Images** (``jpg``, ``jpeg``, ``png``, ``gif``, ``webp``) are stored as
  ``<uuid32hex><ext>`` (e.g. ``a3f1b2c4d5e6f7a8b9c0d1e2f3a4b5c6.jpg``).
- **All other files** are stored as ``<uuid32hex>_<original_filename>`` (e.g.
  ``a3f1b2c4d5e6f7a8b9c0d1e2f3a4b5c6_report.pdf``), preserving the original
  name while still preventing collisions and path-traversal attacks.

Files are automatically purged by a background thread that runs every 24 hours,
using both age-based retention and a directory-wide size cap from
``settings.json``:

- ``"image_retention_days"`` controls how long image files are kept (default: 30).
- ``"file_retention_days"`` controls how long non-image files are kept (default: 30).
- ``"max_upload_dir_size_mb"`` caps the total size of the directory; once
  exceeded, the oldest files are deleted until it fits (default: 2048, ``0``
  disables).

See :doc:`administration` for details on manual cleanup.

avatars/ directory
------------------

**Location:** ``<project_root>/avatars/``

Stores user profile avatar images. Each file is named ``<uuid32hex>.jpg`` and
is linked to a user via the ``avatar_file`` column in the ``user_settings``
table in ``auth.db``.

Avatars are uploaded at a maximum resolution of 128×128 pixels (the browser
crops and resizes the source image before sending). The maximum permitted source
file size is controlled by ``"max_avatar_size_mb"`` in ``settings.json``
(default: 5 MB).

When a user uploads a new avatar, the previous file is automatically deleted.
Avatar files are **not** subject to the automatic retention cleanup — they
persist until the user replaces or removes them, or the user account is deleted.

gunicorn.conf.py
----------------

**Location:** ``<project_root>/gunicorn.conf.py`` (a thin shim) and
``minimost.gunicorn_conf`` (the packaged module shipped inside the wheel).

Configuration file for the Gunicorn WSGI server, used when running in
production. The top-level ``gunicorn.conf.py`` simply adds ``src/`` to the
import path and re-exports the packaged ``minimost.gunicorn_conf`` module, so
the two are interchangeable:

- **Installed package** (wheel or ``pip install -e .``)::

      gunicorn "minimost:create_app()" -c python:minimost.gunicorn_conf

- **Source checkout**::

      gunicorn "minimost:create_app()" --config gunicorn.conf.py

The defaults are:

.. list-table::
   :header-rows: 1
   :widths: 30 20 50

   * - Setting
     - Default
     - Description
   * - ``bind``
     - ``"0.0.0.0:6767"``
     - Address and port to listen on. Change to a Unix socket when using
       Nginx as a reverse proxy.
   * - ``workers``
     - ``cpu_count * 2 + 1``
     - Number of worker processes. Each worker handles one request at a
       time (sync worker class).
   * - ``worker_class``
     - ``"sync"``
     - Synchronous workers. Suitable for MiniMost's SQLite-based workload.
   * - ``timeout``
     - ``30``
     - Seconds before a worker is killed if it does not respond. Increase
       if link preview fetches are timing out.
   * - ``preload_app``
     - ``True``
     - Load the application once in the master process before forking.
       Saves memory and startup time.
   * - ``max_requests``
     - ``1000``
     - Restart workers after this many requests to prevent memory leaks.
   * - ``max_requests_jitter``
     - ``50``
     - Random jitter added to ``max_requests`` to stagger worker restarts.
   * - ``loglevel``
     - ``"info"``
     - Log verbosity.
   * - ``accesslog``
     - ``"-"`` (stdout)
     - Access log destination. Captured by systemd if running as a service.
   * - ``pythonpath``
     - ``"src"``
     - Added to ``PYTHONPATH`` so Gunicorn can find the ``minimost``
       package in ``src/minimost/``.

**Example: Unix socket bind (for use with Nginx)**

.. code-block:: python

    # gunicorn.conf.py
    bind = "unix:/run/gunicorn/minimost.sock"

**Example: File-based logging**

.. code-block:: python

    # gunicorn.conf.py
    accesslog = "/var/log/minimost/access.log"
    errorlog = "/var/log/minimost/error.log"

Environment Variables
---------------------

MiniMost itself does not read any environment variables. Flask respects the
following standard variables if set:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Variable
     - Effect
   * - ``FLASK_ENV``
     - Set to ``"development"`` to enable the Werkzeug reloader. Not
       recommended for production.
   * - ``PYTHONPATH``
     - Used by Gunicorn's ``pythonpath`` setting to locate the package.
