"""
minimost.common
===============

Shared path helpers and per-user database initialisation.

This module provides two things:

* **Path resolution** — a single :data:`DB_DIR` constant and
  :func:`user_db_path` so every other module refers to the same on-disk
  location without duplicating the path logic.

* **Schema bootstrap** — :func:`init_user_db` creates (or opens) a user's
  SQLite database and ensures the ``messages`` table exists with the full
  column set.

Module-level attributes
-----------------------
DB_DIR : pathlib.Path
    Absolute path to the ``users/`` directory that stores all per-user
    SQLite database files.  The directory is created lazily by
    :func:`init_user_db` the first time it is called.
"""

from pathlib import Path
import sqlite3

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent.parent

DB_DIR = _PROJECT_ROOT / "users"


def user_db_path(username: str) -> Path:
    """Return the absolute filesystem path for a user's SQLite database.

    The path follows the pattern ``<project_root>/users/<username>.db``.
    This function does **not** create the file or its parent directory — use
    :func:`init_user_db` for that.

    :param username: The account username.  Must be a valid filename component
        (alphanumeric, hyphens, and underscores).
    :type username: str
    :returns: Absolute path to the user's ``.db`` file.
    :rtype: pathlib.Path

    Example::

        path = user_db_path("alice")
        # e.g. PosixPath('/srv/minimost/users/alice.db')
    """
    return DB_DIR / f"{username}.db"


def init_user_db(username: str):
    """Create the per-user SQLite database and ensure the schema is current.

    This function is idempotent: calling it multiple times on the same
    *username* is safe because the ``CREATE TABLE IF NOT EXISTS`` guard
    prevents duplicate table creation.

    **What it does:**

    1. Creates the ``users/`` directory if it does not already exist.
    2. Opens (or creates) ``users/<username>.db`` with SQLite.
    3. Enables **WAL** (Write-Ahead Logging) journal mode for better
       concurrency under simultaneous reads from multiple Gunicorn workers.
    4. Creates the ``messages`` table if it is absent.

    **Messages table schema:**

    .. list-table::
       :header-rows: 1
       :widths: 20 10 70

       * - Column
         - Type
         - Description
       * - ``id``
         - INTEGER PK
         - Auto-increment primary key.
       * - ``channel``
         - TEXT
         - Public channel name (e.g. ``"general"``) or DM identifier
           (e.g. ``"dm:alice:bob"``).
       * - ``sender``
         - TEXT
         - Username of the message author.
       * - ``content``
         - TEXT
         - Message body text.  ``NULL`` for image-only messages.
       * - ``content_type``
         - TEXT
         - Always ``'text'`` for the current version; reserved for future
           media types.
       * - ``filename``
         - TEXT
         - Uploaded image filename stored in ``uploads/``.  ``NULL`` for
           text-only messages.
       * - ``ts``
         - REAL
         - Unix timestamp (seconds, floating-point) at which the message
           was sent.  Used as the primary ordering key and as the
           cross-user identity token for edits, deletes, and reactions.
       * - ``edited``
         - INTEGER
         - Boolean flag (0/1) — ``1`` when the message body has been
           modified after initial send.
       * - ``edited_ts``
         - REAL
         - Unix timestamp of the most recent edit.
       * - ``read``
         - INTEGER
         - Per-user read flag (0/1).  The sender's copy is always inserted
           as ``read=1``; recipients start at ``0``.
       * - ``deleted``
         - INTEGER
         - Soft-delete flag (0/1).  Deleted messages are retained in the
           database so that tombstones can be propagated to clients that
           have already cached the message.
       * - ``deleted_ts``
         - REAL
         - Unix timestamp when the message was deleted.
       * - ``reply_to_id``
         - INTEGER FK
         - Foreign key to ``messages.id`` — the parent message that this
           message is replying to, or ``NULL``.
       * - ``reactions``
         - TEXT
         - Legacy JSON column; reactions are now stored in the shared
           ``presence.db::message_reactions`` table.  Kept for schema
           compatibility.
       * - ``reactions_ts``
         - REAL
         - Unix timestamp updated whenever a reaction is toggled.  The
           polling query uses this to detect reaction changes without
           re-fetching the whole message list.
       * - ``mentions``
         - TEXT
         - Reserved for future ``@mention`` tracking.
       * - ``metadata``
         - TEXT
         - Reserved for future structured metadata.
       * - ``client_msg_id``
         - TEXT
         - Client-generated deduplication token (not currently enforced
           server-side).
       * - ``expires_ts``
         - REAL
         - Unix timestamp after which the associated upload file may be
           deleted by :mod:`minimost.clean`.

    :param username: Account username whose database should be initialised.
    :type username: str
    :returns: None
    """
    DB_DIR.mkdir(exist_ok=True)
    path = user_db_path(username)
    db = sqlite3.connect(str(path))
    db.execute("PRAGMA journal_mode=WAL")
    cur = db.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,

        channel TEXT NOT NULL,
        sender TEXT NOT NULL,

        content TEXT,
        content_type TEXT DEFAULT 'text',
        filename TEXT,

        ts REAL NOT NULL,
        edited INTEGER DEFAULT 0,
        edited_ts REAL,

        read INTEGER DEFAULT 0,
        deleted INTEGER DEFAULT 0,
        deleted_ts REAL,

        reply_to_id INTEGER,

        reactions TEXT,
        reactions_ts REAL,
        mentions TEXT,
        metadata TEXT,

        client_msg_id TEXT,
        expires_ts REAL,

        FOREIGN KEY (reply_to_id) REFERENCES messages(id)
    )
    """)

    db.commit()
    db.close()
