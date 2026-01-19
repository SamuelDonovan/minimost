# From the python standard library
import time
import sqlite3

# Local import
import common

PRESENCE_TIMEOUT = 60 # seconds
PRESENCE_DB = "presence.db"

def touch_presence(user):
    now = int(time.time())
    db = sqlite3.connect(PRESENCE_DB)

    db.execute("""
        INSERT INTO presence (user, last_seen)
        VALUES (?, ?)
        ON CONFLICT(user)
        DO UPDATE SET last_seen = excluded.last_seen
    """, (user, now))

    db.commit()

def is_online(user):
    cutoff = int(time.time()) - PRESENCE_TIMEOUT
    db = sqlite3.connect(PRESENCE_DB)

    row = db.execute("""
        SELECT 1 FROM presence
        WHERE user = ?
          AND last_seen >= ?
    """, (user, cutoff)).fetchone()

    return row is not None

def get_online_users():
    cutoff = int(time.time()) - PRESENCE_TIMEOUT
    db = sqlite3.connect(PRESENCE_DB)

    rows = db.execute("""
        SELECT user FROM presence
        WHERE last_seen >= ?
    """, (cutoff,)).fetchall()

    return {row["user"] for row in rows}
