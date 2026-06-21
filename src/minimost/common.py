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
from typing import Optional
import sqlite3

from werkzeug.utils import secure_filename

from .paths import data_dir

DB_DIR = data_dir() / "users"


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


def shared_db_path() -> Path:
    """Return the absolute path of the single shared message database.

    MiniMost stores every message exactly once in a single shared database
    (``users/messages.db``) rather than copying it into a per-user file. The
    path is resolved from the live :data:`DB_DIR` on each call so the test
    suite's monkeypatched directory is honoured.

    :returns: Absolute path to ``messages.db``.
    :rtype: pathlib.Path
    """
    return DB_DIR / "messages.db"


def init_user_db(_username: Optional[str] = None):
    """Backwards-compatible alias for :func:`init_messages_db`.

    Historically each account had its own database, initialised here. The data
    model is now a single shared database, so *_username* is ignored and this
    simply ensures the shared schema exists. Kept as a named entry point because
    the signup and account-recovery flows still call it per account.

    :param _username: Ignored. Retained for call-site compatibility.
    :returns: None
    """
    init_messages_db()


def init_messages_db():
    """Create the shared message database and ensure its schema is current.

    Idempotent — every table uses ``CREATE TABLE IF NOT EXISTS``, so repeated
    calls are safe and cheap. Creates:

    * ``messages`` — one canonical row per message (referenced everywhere by its
      auto-increment ``id``; there are no per-user copies, so edits/deletes/
      reactions act on a single row).
    * ``messages_fts`` — the trigram substring search index (see
      :func:`_ensure_search_index`).
    * ``reactions`` — one row per (message, emoji, reactor), keyed by the real
      ``message_id`` rather than a timestamp.
    * ``read_state`` — a per-(user, channel) **read watermark** (``last_read_ts``).
      Unread counts and read receipts are both derived from it, so read state
      costs O(users × channels) rows instead of O(messages × users).
    * ``dm_hidden`` — per-(user, channel) hidden-DM markers.

    WAL keeps readers (the 500 ms pollers) from blocking the single writer;
    ``auto_vacuum = INCREMENTAL`` reclaims space from retention/edits without the
    long global lock that FULL would take on a shared file.

    :returns: None
    """
    DB_DIR.mkdir(exist_ok=True)
    db = sqlite3.connect(str(shared_db_path()))
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA auto_vacuum = INCREMENTAL")
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

        deleted INTEGER DEFAULT 0,
        deleted_ts REAL,

        reply_to_id INTEGER,

        reactions_ts REAL,
        mentions TEXT,
        metadata TEXT,

        client_msg_id TEXT,
        expires_ts REAL,

        FOREIGN KEY (reply_to_id) REFERENCES messages(id)
    )
    """)
    # The hot path (channel poll + unread counts) filters by channel and ts.
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_messages_channel_ts ON messages(channel, ts)"
    )

    cur.execute("""
    CREATE TABLE IF NOT EXISTS reactions (
        message_id INTEGER NOT NULL,
        emoji      TEXT NOT NULL,
        reactor    TEXT NOT NULL,
        PRIMARY KEY (message_id, emoji, reactor)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS read_state (
        user         TEXT NOT NULL,
        channel      TEXT NOT NULL,
        last_read_ts REAL NOT NULL DEFAULT 0,
        PRIMARY KEY (user, channel)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS dm_hidden (
        user      TEXT NOT NULL,
        channel   TEXT NOT NULL,
        hidden_ts REAL NOT NULL,
        PRIMARY KEY (user, channel)
    )
    """)

    _ensure_search_index(cur)

    db.commit()
    db.close()
