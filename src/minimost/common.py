from pathlib import Path
import sqlite3

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent.parent

DB_DIR = _PROJECT_ROOT / "users"


def user_db_path(username: str) -> Path:
    return DB_DIR / f"{username}.db"


def init_user_db(username: str):
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
