"""
minimost.database
=================

Authentication database schema initialisation.

This module bootstraps the shared ``auth.db`` SQLite database, which stores
all user credentials.  It is imported — and therefore executed — by
:func:`minimost.create_app` as a side effect of the import chain.

**Why a separate module?**

Keeping schema initialisation in its own module avoids circular imports: both
:mod:`minimost.auth` (which defines ``AUTH_DB``) and higher-level modules need
to reference the same initialisation step, and a dedicated module is the
cleanest boundary.

**Side effect at import time:**

:func:`init_auth_db` is called unconditionally at module level when this
module is first imported.  This guarantees that ``auth.db`` exists and has the
correct schema before any authentication route is reached.
"""

# From the python standard library
import sqlite3

# Local Imports
from . import auth


def init_auth_db():
    """Create ``auth.db`` and ensure the ``users`` table exists.

    Opens (or creates) the shared authentication database at the path
    defined by :data:`minimost.auth.AUTH_DB` and creates the ``users`` table
    if it is not present.  WAL journal mode is enabled for concurrent access.

    **Schema — ``users`` table:**

    .. list-table::
       :header-rows: 1
       :widths: 25 15 60

       * - Column
         - Type
         - Description
       * - ``username``
         - TEXT PK
         - Unique account identifier.  Validated against
           ``[A-Za-z0-9_\\-]{1,32}`` on registration.
       * - ``password_hash``
         - TEXT NOT NULL
         - PBKDF2 hash produced by
           :func:`werkzeug.security.generate_password_hash`.  Never stored
           in plaintext.

    This function is idempotent — safe to call multiple times.

    :returns: None
    """
    db = sqlite3.connect(auth.AUTH_DB)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS user_settings (
            username    TEXT PRIMARY KEY,
            name_color  TEXT,
            avatar_file TEXT
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            token      TEXT PRIMARY KEY,
            username   TEXT NOT NULL,
            expires_ts REAL NOT NULL,
            used       INTEGER NOT NULL DEFAULT 0
        )
    """)
    try:
        db.execute("ALTER TABLE user_settings ADD COLUMN avatar_file TEXT")
    except sqlite3.OperationalError:
        pass
    db.commit()
    db.close()


init_auth_db()
