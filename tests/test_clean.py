import os
import sqlite3
import time
import pytest
from unittest.mock import patch
from minimost.clean import delete_files_older_than, delete_messages_older_than


def _old_file(path, days=31):
    path.write_text("data")
    old_ts = time.time() - (days * 86400)
    os.utime(str(path), (old_ts, old_ts))


def test_deletes_old_file(tmp_path, capsys):
    f = tmp_path / "old.txt"
    _old_file(f)
    delete_files_older_than(str(tmp_path), image_days=30, file_days=30)
    assert not f.exists()
    assert "Deleted" in capsys.readouterr().out


def test_keeps_new_file(tmp_path, capsys):
    f = tmp_path / "new.txt"
    f.write_text("data")
    delete_files_older_than(str(tmp_path), image_days=30, file_days=30)
    assert f.exists()
    assert capsys.readouterr().out == ""


def test_dry_run_does_not_delete(tmp_path, capsys):
    f = tmp_path / "old.txt"
    _old_file(f)
    delete_files_older_than(str(tmp_path), image_days=30, file_days=30, dry_run=True)
    assert f.exists()
    assert "[DRY RUN]" in capsys.readouterr().out


def test_invalid_directory_raises():
    with pytest.raises(ValueError, match="not a valid directory"):
        delete_files_older_than("/nonexistent/path", image_days=30, file_days=30)


def test_skips_subdirectory(tmp_path):
    subdir = tmp_path / "subdir"
    subdir.mkdir()
    delete_files_older_than(str(tmp_path), image_days=0, file_days=0)
    assert subdir.exists()


def test_skips_unreadable_file(tmp_path):
    from unittest.mock import MagicMock

    # Use a fake path object so only the file's stat raises, not the
    # directory's (which would break the is_dir() check in Python 3.11).
    fake = MagicMock()
    fake.is_file.return_value = True
    fake.stat.side_effect = OSError("no access")

    with patch("pathlib.Path.iterdir", return_value=[fake]):
        delete_files_older_than(str(tmp_path), image_days=0, file_days=0)

    fake.unlink.assert_not_called()


def test_multiple_files_mixed_ages(tmp_path):
    old = tmp_path / "old.log"
    new = tmp_path / "new.log"
    _old_file(old)
    new.write_text("recent")
    delete_files_older_than(str(tmp_path), image_days=30, file_days=30)
    assert not old.exists()
    assert new.exists()


def test_image_and_file_retention_differ(tmp_path):
    # Old image (32 days) should survive a 60-day image retention
    # but an old non-image (32 days) should be deleted under a 10-day file retention
    old_img = tmp_path / "photo.jpg"
    old_doc = tmp_path / "report.pdf"
    _old_file(old_img, days=32)
    _old_file(old_doc, days=32)
    delete_files_older_than(str(tmp_path), image_days=60, file_days=10)
    assert old_img.exists()
    assert not old_doc.exists()


# ── delete_messages_older_than ────────────────────────────────────────────────


def _make_user_db(path):
    conn = sqlite3.connect(str(path))
    conn.execute("""
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel TEXT NOT NULL,
            sender TEXT NOT NULL,
            content TEXT,
            ts REAL NOT NULL,
            deleted INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()


def _insert_msg(path, ts, content="hello"):
    conn = sqlite3.connect(str(path))
    conn.execute(
        "INSERT INTO messages (channel, sender, content, ts) VALUES ('general', 'alice', ?, ?)",
        (content, ts),
    )
    conn.commit()
    conn.close()


def _count_msgs(path):
    conn = sqlite3.connect(str(path))
    count = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    conn.close()
    return count


def test_delete_messages_removes_old(tmp_path):
    db = tmp_path / "alice.db"
    _make_user_db(db)
    old_ts = time.time() - (32 * 86400)
    _insert_msg(db, old_ts)
    delete_messages_older_than(str(tmp_path), days=30)
    assert _count_msgs(db) == 0


def test_delete_messages_keeps_new(tmp_path):
    db = tmp_path / "alice.db"
    _make_user_db(db)
    _insert_msg(db, time.time())
    delete_messages_older_than(str(tmp_path), days=30)
    assert _count_msgs(db) == 1


def test_delete_messages_dry_run(tmp_path, capsys):
    db = tmp_path / "alice.db"
    _make_user_db(db)
    old_ts = time.time() - (32 * 86400)
    _insert_msg(db, old_ts)
    delete_messages_older_than(str(tmp_path), days=30, dry_run=True)
    assert _count_msgs(db) == 1
    assert "[DRY RUN]" in capsys.readouterr().out


def test_delete_messages_invalid_directory():
    with pytest.raises(ValueError, match="not a valid directory"):
        delete_messages_older_than("/nonexistent/path", days=30)


def test_delete_messages_multiple_dbs(tmp_path):
    for name in ("alice.db", "bob.db"):
        db = tmp_path / name
        _make_user_db(db)
        old_ts = time.time() - (32 * 86400)
        _insert_msg(db, old_ts)
        _insert_msg(db, time.time())
    delete_messages_older_than(str(tmp_path), days=30)
    for name in ("alice.db", "bob.db"):
        assert _count_msgs(tmp_path / name) == 1


def test_delete_messages_skips_non_db_files(tmp_path):
    (tmp_path / "README.txt").write_text("not a db")
    db = tmp_path / "alice.db"
    _make_user_db(db)
    old_ts = time.time() - (32 * 86400)
    _insert_msg(db, old_ts)
    delete_messages_older_than(str(tmp_path), days=30)
    assert _count_msgs(db) == 0


def test_delete_messages_tolerates_corrupted_db(tmp_path, capsys):
    (tmp_path / "corrupt.db").write_bytes(b"not a sqlite database")
    db = tmp_path / "alice.db"
    _make_user_db(db)
    old_ts = time.time() - (32 * 86400)
    _insert_msg(db, old_ts)
    delete_messages_older_than(str(tmp_path), days=30)
    assert _count_msgs(db) == 0
