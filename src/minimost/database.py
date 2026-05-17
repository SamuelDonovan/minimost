# From the python standard library
import sqlite3

# Local Imports
from . import auth


def init_auth_db():
    db = sqlite3.connect(auth.AUTH_DB)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL
        )
    """)
    db.commit()
    db.close()


init_auth_db()
