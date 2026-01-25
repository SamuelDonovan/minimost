# From the python standard library
import time
import sqlite3

# From Flask 
from flask import session, request, Blueprint

presence_bp = Blueprint("presence", __name__)

PRESENCE_DB = "presence.db"

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

    db.execute("""
        INSERT INTO presence (user, last_seen, state)
        VALUES (?, ?, ?)
        ON CONFLICT(user)
        DO UPDATE SET
            last_seen = excluded.last_seen,
            state = excluded.state
    """, (user, now, state))

    db.commit()
    return "", 204
