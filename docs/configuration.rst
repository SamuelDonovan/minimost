Configuration
=============

MiniMost is designed to work out-of-the-box with zero configuration. All
settings have sensible defaults and only need to be changed to customize the
application for your environment.

channels.json
-------------

**Location:** ``<project_root>/channels.json``

Defines the list of public channels visible to all users. Edit this file to
add, remove, or rename channels.

Example::

    ["general", "software", "firmware", "systems", "off-topic"]

- Channels are displayed in the sidebar in the order listed.
- Changes take effect on the **next server restart** — the list is loaded
  at startup.
- If ``channels.json`` is absent or contains invalid JSON, MiniMost falls
  back to a single ``"general"`` channel.
- Channel names should be short, lowercase, and contain no spaces.

.. warning::

   Removing a channel from ``channels.json`` does not delete its message
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

Images are not automatically cleaned up. Run ``clean.py`` periodically
to remove old attachments — see :doc:`administration`.

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
