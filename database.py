# From the python standard library
import sqlite3

# Local Imports
import auth
import presence

def init_auth_db():
    db = sqlite3.connect(auth.AUTH_DB)
    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            email TEXT
        )
    """)
    # Migrate: add email column for existing installations
    try:
        db.execute("ALTER TABLE users ADD COLUMN email TEXT")
    except sqlite3.OperationalError:
        pass  # column already exists
    db.execute("""
        CREATE TABLE IF NOT EXISTS reset_tokens (
            token TEXT PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            expires_at REAL NOT NULL
        )
    """)
    db.commit()
    db.close()

def init_presence_db():
    db = sqlite3.connect(presence.PRESENCE_DB)
    cur = db.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS presence (
        user TEXT PRIMARY KEY,
        last_seen INTEGER NOT NULL,
        state TEXT NOT NULL
    )
    """)
    db.commit()
    db.close()

init_auth_db()
init_presence_db()
