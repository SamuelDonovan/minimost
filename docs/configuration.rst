Configuration
=============

MiniMost is designed to work out-of-the-box with zero configuration. All
settings have sensible defaults and only need to be changed to customize the
application for your environment.

settings.json
-------------

**Location:** ``<project_root>/settings.json``

The main configuration file for MiniMost. It is a JSON object. All keys are
optional — missing keys fall back to built-in defaults.

Example (showing all available keys with their defaults)::

    {
        "channels": ["general", "software", "firmware", "systems", "off-topic"],
        "image_retention_days": 30,
        "file_retention_days": 30,
        "message_retention_days": 770,
        "max_upload_size_mb": 25,
        "max_avatar_size_mb": 5
    }

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
    How many days to keep messages in the per-user SQLite databases before
    they are permanently deleted. Unlike the soft-delete used when a user
    deletes a message, this removes the database rows entirely so the
    ``users/*.db`` files do not grow without bound over time. Defaults to
    ``770`` (approximately two years). Changes take effect at the next
    scheduled cleanup run — no restart required.

    .. note::

       Messages deleted by this process are gone permanently — they cannot
       be recovered. Set this value to a period that comfortably covers how
       far back your users ever need to scroll.

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

.. warning::

   Removing a channel from ``settings.json`` does not delete its message
   history. The messages remain in each user's database but the channel will
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
indicators, read receipts, and message reactions. Created automatically on
first startup.

This database can be safely deleted if it becomes corrupted — it will be
recreated on next startup. The only data lost is:

- Presence states (users will appear offline until they next reload).
- Typing indicators (transient — no user-visible impact).
- Read receipts (``✓`` checkmarks will disappear for existing messages).
- Reactions (emoji reactions will disappear from all messages).

users/ directory
----------------

**Location:** ``<project_root>/users/``

Contains one SQLite ``.db`` file per registered user, named
``<username>.db``. Each file holds the user's complete message history.

These files are the primary data store of MiniMost. Back them up regularly.

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
using type-specific retention periods from ``settings.json``:

- ``"image_retention_days"`` controls how long image files are kept (default: 30).
- ``"file_retention_days"`` controls how long non-image files are kept (default: 30).

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

**Location:** ``<project_root>/gunicorn.conf.py``

Configuration file for the Gunicorn WSGI server, used when running in
production. The defaults are:

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
