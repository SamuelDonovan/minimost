import sqlite3
import pytest
from werkzeug.security import check_password_hash

from minimost.auth import hash_password, _validate_signup, _seed_channel_history
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


@pytest.mark.parametrize(
    "name", ["minimost", "MiniMost", "everyone", "deleteduser", "DeletedUser"]
)
def test_validate_signup_reserved_usernames(name):
    err = _validate_signup(name, "Password1!", "Password1!")
    assert err is not None
    assert "protected" in err


# ── _seed_channel_history ─────────────────────────────────────────────────────


def test_seed_is_noop(isolated_dbs):
    """Seeding is obsolete under the shared database — it must not copy or error.

    New users see public history natively because every message lives in one
    shared table, so the retained stub does nothing.
    """
    from time import time

    common_mod.init_messages_db()
    db = sqlite3.connect(str(common_mod.shared_db_path()))
    db.execute(
        "INSERT INTO messages (channel, sender, content, ts) VALUES (?, ?, ?, ?)",
        ("general", "existing", "hello", time()),
    )
    db.commit()
    db.close()

    _seed_channel_history("newuser")  # must not raise or duplicate rows

    db = sqlite3.connect(str(common_mod.shared_db_path()))
    count = db.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    db.close()
    assert count == 1
