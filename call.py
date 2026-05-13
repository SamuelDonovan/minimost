import sqlite3
import time

from flask import Blueprint, request, jsonify, session

from auth import login_required
from presence import PRESENCE_DB

call_bp = Blueprint("call", __name__)

@call_bp.route("/call/signal", methods=["POST"])
@login_required
def send_signal():
    body     = request.get_json()
    to_user  = body["to_user"]
    sig_type = body["type"]
    data     = body.get("data", "")

    db = sqlite3.connect(PRESENCE_DB)
    db.execute(
        "INSERT INTO call_signals (from_user, to_user, type, data, ts) VALUES (?, ?, ?, ?, ?)",
        (session["user"], to_user, sig_type, data, time.time())
    )
    db.commit()
    db.close()
    return jsonify({"ok": True})

@call_bp.route("/call/signals")
@login_required
def get_signals():
    me = session["user"]
    db = sqlite3.connect(PRESENCE_DB)

    # Prune old consumed signals
    db.execute("DELETE FROM call_signals WHERE consumed = 1 AND ts < ?", (time.time() - 300,))

    rows = db.execute(
        "SELECT id, from_user, type, data FROM call_signals "
        "WHERE to_user = ? AND consumed = 0 ORDER BY ts",
        (me,)
    ).fetchall()

    if rows:
        ids = [r[0] for r in rows]
        db.execute(
            f"UPDATE call_signals SET consumed = 1 WHERE id IN ({','.join('?' * len(ids))})",
            ids
        )

    db.commit()
    db.close()

    return jsonify([
        {"from_user": r[1], "type": r[2], "data": r[3]}
        for r in rows
    ])
