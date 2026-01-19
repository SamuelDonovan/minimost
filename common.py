# From the python standard library
from pathlib import Path
import sqlite3

DB_DIR = Path("users")

def user_db_path(username: str) -> Path:
    return DB_DIR / f"{username}.db"

def init_user_db(username: str):
    DB_DIR.mkdir(exist_ok=True)
    path = user_db_path(username)
    db = sqlite3.connect(path)
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

        reply_to_id INTEGER,

        reactions TEXT,
        mentions TEXT,
        metadata TEXT,

        client_msg_id TEXT,
        expires_ts REAL,

        FOREIGN KEY (reply_to_id) REFERENCES messages(id)
    )
    """)

    db.commit()
    db.close()
