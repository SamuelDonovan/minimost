Configuration
=============

MiniMost is designed to work out-of-the-box with zero configuration. All
settings have sensible defaults and only need to be changed to customize the
application for your environment.

settings.json
-------------

**Location:** ``<project_root>/settings.json``

The main configuration file for MiniMost. It is a JSON object that controls
channel definitions and upload retention. All keys are optional — missing keys
fall back to built-in defaults.

Example::

    {
        "channels": ["general", "software", "firmware", "systems", "off-topic"],
        "image_retention_days": 30
    }

``channels``
    List of public channel names visible to all users. Channels are displayed
    in the sidebar in the order listed. Changes take effect on the **next server
    restart**. If this key is absent or the file cannot be read, MiniMost falls
    back to a single ``"general"`` channel. Channel names should be short,
    lowercase, and contain no spaces.

``image_retention_days``
    How many days to keep image uploads before the background cleanup thread
    removes them. Defaults to ``30``. Changes take effect at the next scheduled
    cleanup run — no restart required. See :doc:`administration` for details.

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

Stores image attachments as UUID-named files (e.g.
``a3f1b2c4d5e6f7a8b9c0d1e2f3a4b5c6.jpg``). The original filename is not
preserved on disk; only the extension is kept.

Image attachments are automatically purged by a background thread that runs
every 24 hours. The retention period is set by ``"image_retention_days"`` in
``settings.json`` (default: 30 days). See :doc:`administration` for details.

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
