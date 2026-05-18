import sqlite3
import minimost.common as common_mod


def test_user_db_path_format(tmp_path, monkeypatch):
    monkeypatch.setattr(common_mod, "DB_DIR", tmp_path)
    path = common_mod.user_db_path("testuser")
    assert path == tmp_path / "testuser.db"


def test_init_user_db_creates_file(tmp_path, monkeypatch):
    monkeypatch.setattr(common_mod, "DB_DIR", tmp_path)
    common_mod.init_user_db("sam")
    assert (tmp_path / "sam.db").exists()


def test_init_user_db_creates_messages_table(tmp_path, monkeypatch):
    monkeypatch.setattr(common_mod, "DB_DIR", tmp_path)
    common_mod.init_user_db("sam")
    db = sqlite3.connect(str(tmp_path / "sam.db"))
    tables = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='messages'"
    ).fetchone()
    db.close()
    assert tables is not None


def test_init_user_db_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(common_mod, "DB_DIR", tmp_path)
    common_mod.init_user_db("sam")
    common_mod.init_user_db("sam")
    assert (tmp_path / "sam.db").exists()


def test_init_user_db_creates_users_dir_if_missing(tmp_path, monkeypatch):
    users_dir = tmp_path / "newusers"
    monkeypatch.setattr(common_mod, "DB_DIR", users_dir)
    assert not users_dir.exists()
    common_mod.init_user_db("sam")
    assert users_dir.exists()
    assert (users_dir / "sam.db").exists()
