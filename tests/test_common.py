import sqlite3
import minimost.common as common_mod


def test_shared_db_path_format(tmp_path, monkeypatch):
    monkeypatch.setattr(common_mod, "DB_DIR", tmp_path)
    path = common_mod.shared_db_path()
    assert path == tmp_path / "messages.db"


def test_init_creates_file(tmp_path, monkeypatch):
    monkeypatch.setattr(common_mod, "DB_DIR", tmp_path)
    common_mod.init_messages_db()
    assert (tmp_path / "messages.db").exists()


def test_init_creates_messages_table(tmp_path, monkeypatch):
    monkeypatch.setattr(common_mod, "DB_DIR", tmp_path)
    common_mod.init_messages_db()
    db = sqlite3.connect(str(tmp_path / "messages.db"))
    tables = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='messages'"
    ).fetchone()
    db.close()
    assert tables is not None


def test_init_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(common_mod, "DB_DIR", tmp_path)
    common_mod.init_messages_db()
    common_mod.init_messages_db()
    assert (tmp_path / "messages.db").exists()


def test_init_creates_users_dir_if_missing(tmp_path, monkeypatch):
    users_dir = tmp_path / "newusers"
    monkeypatch.setattr(common_mod, "DB_DIR", users_dir)
    assert not users_dir.exists()
    common_mod.init_messages_db()
    assert users_dir.exists()
    assert (users_dir / "messages.db").exists()
