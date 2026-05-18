import sqlite3
from werkzeug.security import check_password_hash

from minimost.auth import hash_password, _validate_signup, _seed_channel_history
import minimost.auth as auth_mod
import minimost.common as common_mod


def test_hash_password_returns_string():
    h = hash_password("Password1!")
    assert isinstance(h, str)
    assert check_password_hash(h, "Password1!")


def test_hash_password_different_each_call():
    assert hash_password("Password1!") != hash_password("Password1!")


# ── _validate_signup ──────────────────────────────────────────────────────────

def test_validate_signup_ok():
    assert _validate_signup("alice", "Password1!", "Password1!") is None


def test_validate_signup_missing_username():
    assert _validate_signup("", "Password1!", "Password1!") == "Missing fields"


def test_validate_signup_missing_password():
    assert _validate_signup("alice", "", "") == "Missing fields"


def test_validate_signup_invalid_username_chars():
    err = _validate_signup("ali ce!", "Password1!", "Password1!")
    assert err is not None
    assert "Username" in err


def test_validate_signup_username_too_long():
    long_name = "a" * 33
    err = _validate_signup(long_name, "Password1!", "Password1!")
    assert err is not None


def test_validate_signup_password_too_short():
    err = _validate_signup("alice", "Pa1!", "Pa1!")
    assert err and "8 characters" in err


def test_validate_signup_no_digit():
    err = _validate_signup("alice", "Password!", "Password!")
    assert err and "number" in err


def test_validate_signup_no_uppercase():
    err = _validate_signup("alice", "password1!", "password1!")
    assert err and "uppercase" in err


def test_validate_signup_no_special():
    err = _validate_signup("alice", "Password1", "Password1")
    assert err and "special" in err


def test_validate_signup_passwords_mismatch():
    err = _validate_signup("alice", "Password1!", "Password1!!")
    assert err and "match" in err


def test_validate_signup_valid_hyphens_underscores():
    assert _validate_signup("alice_bob-123", "Password1!", "Password1!") is None


# ── _seed_channel_history ─────────────────────────────────────────────────────

def test_seed_no_existing_users(isolated_dbs):
    common_mod.init_user_db("newuser")
    _seed_channel_history("newuser")
    db = sqlite3.connect(str(common_mod.user_db_path("newuser")))
    count = db.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    db.close()
    assert count == 0


def test_seed_existing_user_no_db_file(isolated_dbs):
    db = sqlite3.connect(auth_mod.AUTH_DB)
    from werkzeug.security import generate_password_hash
    db.execute("INSERT INTO users VALUES (?, ?)", ("ghost", generate_password_hash("x")))
    db.commit()
    db.close()
    common_mod.init_user_db("newuser")
    _seed_channel_history("newuser")
    db = sqlite3.connect(str(common_mod.user_db_path("newuser")))
    count = db.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    db.close()
    assert count == 0


def test_seed_copies_public_channel_messages(isolated_dbs):
    from werkzeug.security import generate_password_hash
    from time import time

    adb = sqlite3.connect(auth_mod.AUTH_DB)
    adb.execute("INSERT INTO users VALUES (?, ?)", ("existing", generate_password_hash("x")))
    adb.commit()
    adb.close()

    common_mod.init_user_db("existing")
    src = sqlite3.connect(str(common_mod.user_db_path("existing")))
    src.execute(
        "INSERT INTO messages (channel, sender, content, ts, read) VALUES (?, ?, ?, ?, ?)",
        ("general", "existing", "hello", time(), 1),
    )
    src.commit()
    src.close()

    common_mod.init_user_db("newuser")
    _seed_channel_history("newuser")

    dst = sqlite3.connect(str(common_mod.user_db_path("newuser")))
    rows = dst.execute("SELECT channel, read FROM messages").fetchall()
    dst.close()
    assert len(rows) == 1
    assert rows[0][0] == "general"
    assert rows[0][1] == 1


def test_seed_does_not_copy_dm_messages(isolated_dbs):
    from werkzeug.security import generate_password_hash
    from time import time

    adb = sqlite3.connect(auth_mod.AUTH_DB)
    adb.execute("INSERT INTO users VALUES (?, ?)", ("existing", generate_password_hash("x")))
    adb.commit()
    adb.close()

    common_mod.init_user_db("existing")
    src = sqlite3.connect(str(common_mod.user_db_path("existing")))
    src.execute(
        "INSERT INTO messages (channel, sender, content, ts, read) VALUES (?, ?, ?, ?, ?)",
        ("dm:existing:other", "existing", "private", time(), 1),
    )
    src.commit()
    src.close()

    common_mod.init_user_db("newuser")
    _seed_channel_history("newuser")

    dst = sqlite3.connect(str(common_mod.user_db_path("newuser")))
    count = dst.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    dst.close()
    assert count == 0


def test_seed_empty_public_history(isolated_dbs):
    from werkzeug.security import generate_password_hash

    adb = sqlite3.connect(auth_mod.AUTH_DB)
    adb.execute("INSERT INTO users VALUES (?, ?)", ("existing", generate_password_hash("x")))
    adb.commit()
    adb.close()

    common_mod.init_user_db("existing")
    common_mod.init_user_db("newuser")
    _seed_channel_history("newuser")

    dst = sqlite3.connect(str(common_mod.user_db_path("newuser")))
    count = dst.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    dst.close()
    assert count == 0
