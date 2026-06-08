import os
import sqlite3
import time
import pytest
from unittest.mock import patch
from minimost.clean import (
    delete_files_older_than,
    delete_files_over_size,
    delete_messages_older_than,
    delete_messages_over_size,
)


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


# ── delete_files_over_size ───────────────────────────────────────────────────


def _file_of_size(path, kb, mtime_offset=0):
    """Write a file of *kb* kibibytes with an mtime *mtime_offset* secs in past."""
    path.write_bytes(b"x" * (kb * 1024))
    ts = time.time() - mtime_offset
    os.utime(str(path), (ts, ts))


@pytest.fixture
def updir(tmp_path):
    # A directory of our own to size-cap. The autouse ``isolated_dbs`` fixture
    # drops auth.db/presence.db (and other dirs) straight into ``tmp_path``;
    # size-based cleanup counts and deletes *every* file, so the tests must work
    # in a clean subdirectory rather than ``tmp_path`` itself.
    d = tmp_path / "attachments"
    d.mkdir()
    return d


def test_over_size_files_deletes_oldest_first(updir):
    # 5 files of 10 KiB each (50 KiB total); cap at ~25 KiB should leave the
    # 2 or 3 newest and delete the oldest.
    for i in range(5):
        _file_of_size(updir / f"f{i}.bin", kb=10, mtime_offset=(5 - i) * 100)
    delete_files_over_size(str(updir), max_size_mb=25 / 1024)
    survivors = sorted(p.name for p in updir.iterdir())
    # The newest files (highest index = smallest offset) survive; oldest gone.
    assert "f0.bin" not in survivors  # oldest
    assert "f4.bin" in survivors  # newest
    total = sum(p.stat().st_size for p in updir.iterdir())
    assert total <= int((25 / 1024) * 1024 * 1024)


def test_over_size_files_under_cap_is_noop(updir, capsys):
    _file_of_size(updir / "small.bin", kb=10)
    delete_files_over_size(str(updir), max_size_mb=50)
    assert (updir / "small.bin").exists()
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("cap", [0, -1, None])
def test_over_size_files_disabled_cap_is_noop(updir, cap):
    _file_of_size(updir / "big.bin", kb=100)
    delete_files_over_size(str(updir), max_size_mb=cap)
    assert (updir / "big.bin").exists()


def test_over_size_files_dry_run(updir, capsys):
    for i in range(3):
        _file_of_size(updir / f"f{i}.bin", kb=20, mtime_offset=(3 - i) * 100)
    delete_files_over_size(str(updir), max_size_mb=25 / 1024, dry_run=True)
    # Nothing deleted, but the action is reported.
    assert len(list(updir.iterdir())) == 3
    assert "[DRY RUN]" in capsys.readouterr().out


def test_over_size_files_invalid_directory():
    with pytest.raises(ValueError, match="not a valid directory"):
        delete_files_over_size("/nonexistent/path", max_size_mb=1)


def test_over_size_files_skips_subdirectories(updir):
    subdir = updir / "sub"
    subdir.mkdir()
    _file_of_size(subdir / "nested.bin", kb=100)  # not counted, not deleted
    _file_of_size(updir / "top.bin", kb=10, mtime_offset=100)
    delete_files_over_size(str(updir), max_size_mb=50)
    assert subdir.exists()
    assert (subdir / "nested.bin").exists()


def test_over_size_files_tolerates_vanished_during_scan(updir):
    from unittest.mock import MagicMock

    real = updir / "real.bin"
    _file_of_size(real, kb=100)
    gone = MagicMock()
    gone.is_file.return_value = True
    gone.stat.side_effect = OSError("vanished")

    with patch("pathlib.Path.iterdir", return_value=[gone, real]):
        # Cap below the one real file so it must be deleted; the vanished entry
        # is silently skipped during the size scan.
        delete_files_over_size(str(updir), max_size_mb=10 / 1024)
    assert not real.exists()


def test_over_size_files_tolerates_unlink_race(updir):
    # A file counted during the scan is removed by another worker before we
    # unlink it: FileNotFoundError is swallowed and its bytes still count as
    # freed, so the loop terminates instead of raising.
    _file_of_size(updir / "a.bin", kb=100, mtime_offset=200)
    _file_of_size(updir / "b.bin", kb=100, mtime_offset=100)
    with patch("pathlib.Path.unlink", side_effect=FileNotFoundError):
        delete_files_over_size(str(updir), max_size_mb=50 / 1024)
    # No exception, and the (un-unlinkable) files are still on disk.
    assert (updir / "a.bin").exists()


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


# ── delete_messages_over_size ────────────────────────────────────────────────


def _make_messages_db(path):
    conn = sqlite3.connect(str(path))
    # auto_vacuum must be set before the first table is created to take effect
    # without a full VACUUM.
    conn.execute("PRAGMA auto_vacuum = INCREMENTAL")
    conn.execute("PRAGMA journal_mode=WAL")
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
    conn.execute("""
        CREATE TABLE reactions (
            message_id INTEGER NOT NULL,
            emoji TEXT NOT NULL,
            reactor TEXT NOT NULL,
            PRIMARY KEY (message_id, emoji, reactor)
        )
    """)
    conn.commit()
    conn.close()


def _fill_messages(path, count, size=4000):
    """Insert *count* fat messages with strictly increasing timestamps."""
    conn = sqlite3.connect(str(path))
    payload = "x" * size
    base = time.time() - count
    conn.executemany(
        "INSERT INTO messages (channel, sender, content, ts) "
        "VALUES ('general', 'alice', ?, ?)",
        [(payload, base + i) for i in range(count)],
    )
    conn.commit()
    conn.close()


def _surviving_ids(path):
    conn = sqlite3.connect(str(path))
    ids = [r[0] for r in conn.execute("SELECT id FROM messages ORDER BY id")]
    conn.close()
    return ids


def test_over_size_deletes_oldest_first(tmp_path):
    db = tmp_path / "messages.db"
    _make_messages_db(db)
    _fill_messages(db, 100)
    before = _surviving_ids(db)

    delete_messages_over_size(str(db), max_size_mb=0.1, batch=10)

    after = _surviving_ids(db)
    # Some messages were pruned, and the survivors are the most recent ones —
    # the deleted ids are a contiguous prefix of the original (lowest) ids.
    assert 0 < len(after) < len(before)
    assert after == before[len(before) - len(after) :]


def test_over_size_brings_db_under_cap(tmp_path):
    db = tmp_path / "messages.db"
    _make_messages_db(db)
    _fill_messages(db, 100)

    delete_messages_over_size(str(db), max_size_mb=0.1, batch=10)

    conn = sqlite3.connect(str(db))
    page_count = conn.execute("PRAGMA page_count").fetchone()[0]
    page_size = conn.execute("PRAGMA page_size").fetchone()[0]
    conn.close()
    assert page_count * page_size <= int(0.1 * 1024 * 1024)


def test_over_size_drops_orphaned_reactions(tmp_path):
    db = tmp_path / "messages.db"
    _make_messages_db(db)
    _fill_messages(db, 100)
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO reactions (message_id, emoji, reactor) VALUES (1, '👍', 'bob')"
    )
    conn.commit()
    conn.close()

    delete_messages_over_size(str(db), max_size_mb=0.1, batch=10)

    conn = sqlite3.connect(str(db))
    # message id 1 is the oldest, so it (and its reaction) should be gone
    assert conn.execute("SELECT COUNT(*) FROM messages WHERE id = 1").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM reactions").fetchone()[0] == 0
    conn.close()


def test_over_size_under_cap_is_noop(tmp_path, capsys):
    db = tmp_path / "messages.db"
    _make_messages_db(db)
    _fill_messages(db, 5)
    delete_messages_over_size(str(db), max_size_mb=50)
    assert _count_msgs(db) == 5
    assert capsys.readouterr().out == ""


def test_over_size_dry_run_deletes_nothing(tmp_path, capsys):
    db = tmp_path / "messages.db"
    _make_messages_db(db)
    _fill_messages(db, 100)
    delete_messages_over_size(str(db), max_size_mb=0.1, dry_run=True)
    assert _count_msgs(db) == 100
    assert "[DRY RUN]" in capsys.readouterr().out


@pytest.mark.parametrize("cap", [0, -1, None])
def test_over_size_disabled_cap_is_noop(tmp_path, cap):
    db = tmp_path / "messages.db"
    _make_messages_db(db)
    _fill_messages(db, 20)
    delete_messages_over_size(str(db), max_size_mb=cap, batch=5)
    assert _count_msgs(db) == 20


def test_over_size_missing_file_is_noop(tmp_path):
    # No exception should be raised when the database file does not exist.
    delete_messages_over_size(str(tmp_path / "nope.db"), max_size_mb=1)


def test_over_size_no_messages_table_is_noop(tmp_path):
    db = tmp_path / "messages.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE other (id INTEGER)")
    conn.commit()
    conn.close()
    delete_messages_over_size(str(db), max_size_mb=0.0001)  # no messages table


def test_over_size_stops_when_batch_frees_no_page(tmp_path):
    # Many tiny rows packed onto a couple of pages: deleting a single row frees
    # no whole page, so the live size does not drop. The function must break out
    # rather than spin forever deleting the entire table to no effect.
    db = tmp_path / "messages.db"
    _make_messages_db(db)
    _fill_messages(db, 200, size=1)
    delete_messages_over_size(str(db), max_size_mb=0.0001, batch=1)
    # The no-progress guard stopped it after the first (page-free-less) batch.
    assert _count_msgs(db) >= 199


def test_over_size_empties_table_when_cap_below_schema(tmp_path):
    # A cap smaller than even an empty database deletes every message, then the
    # loop exits because there are no more rows to delete (the schema's own
    # pages keep it nominally "over" the impossible cap).
    db = tmp_path / "messages.db"
    _make_messages_db(db)
    _fill_messages(db, 30, size=4000)
    delete_messages_over_size(str(db), max_size_mb=0.00001, batch=1000)
    assert _count_msgs(db) == 0
