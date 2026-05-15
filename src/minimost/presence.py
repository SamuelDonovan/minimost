# From the python standard library
import time
import sqlite3

# From Flask
from flask import session, request, Blueprint

presence_bp = Blueprint("presence", __name__)

PRESENCE_DB = "presence.db"


def _init_tables():
    db = sqlite3.connect(PRESENCE_DB)
    db.execute("""
        CREATE TABLE IF NOT EXISTS typing (
            user    TEXT NOT NULL,
            channel TEXT NOT NULL,
            ts      INTEGER NOT NULL,
            PRIMARY KEY (user, channel)
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS read_receipts (
            channel TEXT NOT NULL,
            msg_ts  REAL NOT NULL,
            reader  TEXT NOT NULL,
            PRIMARY KEY (channel, msg_ts, reader)
        )
    """)
    db.commit()
    db.close()


_init_tables()


@presence_bp.route("/typing/<channel>", methods=["POST"])
def typing_start(channel):
    user = session.get("user")
    if not user:
        return "", 204
    now = int(time.time())
    db = sqlite3.connect(PRESENCE_DB)
    db.execute(
        "INSERT OR REPLACE INTO typing (user, channel, ts) VALUES (?, ?, ?)",
        (user, channel, now),
    )
    db.commit()
    db.close()
    return "", 204


@presence_bp.route("/typing/<channel>", methods=["GET"])
def typing_get(channel):
    user = session.get("user")
    if not user:
        return []
    cutoff = int(time.time()) - 5
    db = sqlite3.connect(PRESENCE_DB)
    rows = db.execute(
        "SELECT user FROM typing WHERE channel = ? AND ts >= ? AND user != ?",
        (channel, cutoff, user),
    ).fetchall()
    db.close()
    return [r[0] for r in rows]


@presence_bp.route("/presence", methods=["POST"])
def presence():
    user = session.get("user")
    if not user:
        return "", 204

    data = request.get_json(silent=True) or {}
    state = data.get("state")
    return update_presence(user, state)


def update_presence(user, state):
    if not state:
        return "", 204

    now = int(time.time())
    db = sqlite3.connect(PRESENCE_DB)

    db.execute(
        "INSERT OR REPLACE INTO presence (user, last_seen, state) VALUES (?, ?, ?)",
        (user, now, state),
    )

    db.commit()
    db.close()
    return "", 204
