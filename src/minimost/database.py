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
import time

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
       * - ``failed_attempts``
         - INTEGER
         - Count of consecutive failed login attempts since the last success.
           Reset to ``0`` on a successful login or when the account is locked.
       * - ``lockout_until``
         - REAL
         - Unix timestamp until which logins are rejected, or ``NULL`` when the
           account is not locked.  Set once ``failed_attempts`` reaches the
           configured threshold.  See :func:`minimost.auth.login_post`.
       * - ``password_set_ts``
         - REAL
         - Unix timestamp of the last time the password was set (signup, change,
           or reset).  Backs the minimum/maximum password-age controls
           (ASD STIG APSC-DV-001990 / 002000).  See
           :func:`minimost.auth._password_policy`.

    A companion ``password_history`` table records the hash of every password
    each account has used, so a change/reset can reject reuse of a recent
    password (ASD STIG APSC-DV-001980).

    This function is idempotent — safe to call multiple times.

    :returns: None
    """
    db = sqlite3.connect(auth.AUTH_DB)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            failed_attempts INTEGER NOT NULL DEFAULT 0,
            lockout_until REAL,
            password_set_ts REAL
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS password_history (
            username      TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            set_ts        REAL NOT NULL
        )
    """)
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_password_history_user"
        " ON password_history (username, set_ts)"
    )
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
    try:
        db.execute("ALTER TABLE user_settings ADD COLUMN bio TEXT")
    except sqlite3.OperationalError:
        pass
    # Account-lockout columns — added by migration for databases created before
    # the lockout feature existed.  Harmless OperationalError once present.
    try:
        db.execute(
            "ALTER TABLE users ADD COLUMN failed_attempts INTEGER NOT NULL DEFAULT 0"
        )
    except sqlite3.OperationalError:
        pass
    try:
        db.execute("ALTER TABLE users ADD COLUMN lockout_until REAL")
    except sqlite3.OperationalError:
        pass
    # Password-age column — added by migration for databases created before the
    # password-policy feature existed. Existing accounts are backfilled with the
    # current time below so they start a fresh maximum-age window rather than
    # being treated as already expired on first login after the upgrade.
    backfill_ts = None
    try:
        db.execute("ALTER TABLE users ADD COLUMN password_set_ts REAL")
        backfill_ts = time.time()
    except sqlite3.OperationalError:
        pass
    if backfill_ts is not None:
        db.execute(
            "UPDATE users SET password_set_ts = ? WHERE password_set_ts IS NULL",
            (backfill_ts,),
        )
        # Seed the reuse-history with each account's current password so the
        # prohibition (APSC-DV-001980) has a baseline to compare against.
        db.execute(
            "INSERT INTO password_history (username, password_hash, set_ts)"
            " SELECT username, password_hash, ? FROM users"
            " WHERE username NOT IN (SELECT username FROM password_history)",
            (backfill_ts,),
        )
    db.commit()
    db.close()


init_auth_db()
