# From the python standard library
import sqlite3

# Local Imports
from . import auth
from . import presence

def init_auth_db():
    db = sqlite3.connect(auth.AUTH_DB)
    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL
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
