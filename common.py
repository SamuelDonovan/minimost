# From the python standard library
from functools import wraps
import secrets
from pathlib import Path
import sqlite3

# From Flask 
from flask import session, redirect, Flask

AUTH_DB = "auth.db"

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if "user" not in session:
            return redirect("/login")
        return fn(*args, **kwargs)
    return wrapper

def user_db_path(username: str) -> Path:
    return DB_DIR / f"{username}.db"

def init_user_db(username: str):
    path = user_db_path(username)
    db = sqlite3.connect(path)
    cur = db.cursor()

    cur.execute("""
    CREATE TABLE messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        channel TEXT NOT NULL,
        sender TEXT NOT NULL,
        content TEXT,
        filename TEXT,
        ts REAL,
        edited INTEGER DEFAULT 0
    )
    """)

    db.commit()
    db.close()


DB_DIR = Path("users")
DB_DIR.mkdir(exist_ok=True)

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)

