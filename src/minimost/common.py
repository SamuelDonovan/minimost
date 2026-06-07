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

from werkzeug.utils import secure_filename

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
    # Defence in depth: usernames are validated at signup, but sanitise the
    # value here too so an untrusted name can never escape DB_DIR via path
    # traversal.  secure_filename is a no-op for valid usernames
    # ([A-Za-z0-9_-]) and strips any separators or ".." from a crafted one.
    return DB_DIR / f"{secure_filename(username)}.db"


# Length of the substrings indexed by the FTS5 trigram tokenizer. Search queries
# shorter than this can't use the index, so chat.search_messages falls back to a
# plain LIKE scan for them (rare, and cheap on the small result a 1–2 char query
# would over-match anyway).
SEARCH_MIN_TOKEN = 3


def _ensure_search_index(cur) -> None:
    """Create the trigram full-text index over ``messages.content``.

    Message search is a case-insensitive substring match. A plain
    ``content LIKE '%q%'`` cannot use an index (leading wildcard) and so scans
    the whole ``messages`` table on every keystroke — cost grows linearly with
    history. An FTS5 virtual table with the **trigram** tokenizer indexes every
    3-character substring, so the identical substring query is answered from the
    index in well under a millisecond no matter how large the history grows.

    The table is *external-content* (``content='messages'``): it stores only the
    trigram postings, not a second copy of the message text, and is kept in sync
    with ``messages`` by the three triggers created here. ``tokenize='trigram'``
    needs SQLite ≥ 3.34 (2020), which ships with every supported CPython.

    Idempotent — safe to call from every :func:`init_user_db`. The first time it
    runs on a database that already holds messages, it indexes the existing rows
    with a one-off ``'rebuild'``.
    """
    # Exact-name lookup (the FTS5 shadow tables are messages_fts_data, _idx, …).
    already_indexed = cur.execute(
        "SELECT 1 FROM sqlite_master WHERE name = 'messages_fts'"
    ).fetchone()

    # columnsize=0 drops the per-row token-count store that only powers bm25
    # relevance ranking; results are ordered by rowid and re-ranked client-side,
    # so it is unused weight. Trims the index with no behaviour change.
    cur.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts "
        "USING fts5(content, content='messages', content_rowid='id', "
        "tokenize='trigram', columnsize=0)"
    )

    # Mirror every content change into the index. The UPDATE trigger fires on the
    # content column alone — it is always in the SET clause of an edit, while a
    # soft-delete touches `deleted`, not `content` (deleted rows are excluded at
    # query time instead). The external-content 'delete' command needs the old
    # text to know which trigrams to remove, hence old.content in the args.
    cur.executescript("""
        CREATE TRIGGER IF NOT EXISTS messages_fts_ai
        AFTER INSERT ON messages BEGIN
            INSERT INTO messages_fts(rowid, content)
            VALUES (new.id, new.content);
        END;
        CREATE TRIGGER IF NOT EXISTS messages_fts_ad
        AFTER DELETE ON messages BEGIN
            INSERT INTO messages_fts(messages_fts, rowid, content)
            VALUES ('delete', old.id, old.content);
        END;
        CREATE TRIGGER IF NOT EXISTS messages_fts_au
        AFTER UPDATE OF content ON messages BEGIN
            INSERT INTO messages_fts(messages_fts, rowid, content)
            VALUES ('delete', old.id, old.content);
            INSERT INTO messages_fts(rowid, content)
            VALUES (new.id, new.content);
        END;
        """)

    if not already_indexed:
        # Brand-new index on a possibly-populated table: index existing rows once.
        cur.execute("INSERT INTO messages_fts(messages_fts) VALUES ('rebuild')")


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
    db.execute("PRAGMA auto_vacuum = FULL")
    db.execute("PRAGMA journal_mode=WAL")
    cur = db.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS dm_hidden (
        channel  TEXT PRIMARY KEY,
        hidden_ts REAL NOT NULL
    )
    """)

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

    _ensure_search_index(cur)

    db.commit()
    db.close()
