import os
import time
import pytest
from unittest.mock import patch
from minimost.clean import delete_files_older_than


def _old_file(path, days=31):
    path.write_text("data")
    old_ts = time.time() - (days * 86400)
    os.utime(str(path), (old_ts, old_ts))


def test_deletes_old_file(tmp_path, capsys):
    f = tmp_path / "old.txt"
    _old_file(f)
    delete_files_older_than(str(tmp_path), days=30)
    assert not f.exists()
    assert "Deleted" in capsys.readouterr().out


def test_keeps_new_file(tmp_path, capsys):
    f = tmp_path / "new.txt"
    f.write_text("data")
    delete_files_older_than(str(tmp_path), days=30)
    assert f.exists()
    assert capsys.readouterr().out == ""


def test_dry_run_does_not_delete(tmp_path, capsys):
    f = tmp_path / "old.txt"
    _old_file(f)
    delete_files_older_than(str(tmp_path), days=30, dry_run=True)
    assert f.exists()
    assert "[DRY RUN]" in capsys.readouterr().out


def test_invalid_directory_raises():
    with pytest.raises(ValueError, match="not a valid directory"):
        delete_files_older_than("/nonexistent/path", days=30)


def test_skips_subdirectory(tmp_path):
    subdir = tmp_path / "subdir"
    subdir.mkdir()
    delete_files_older_than(str(tmp_path), days=0)
    assert subdir.exists()


def test_skips_unreadable_file(tmp_path):
    from unittest.mock import MagicMock

    # Use a fake path object so only the file's stat raises, not the
    # directory's (which would break the is_dir() check in Python 3.11).
    fake = MagicMock()
    fake.is_file.return_value = True
    fake.stat.side_effect = OSError("no access")

    with patch("pathlib.Path.iterdir", return_value=[fake]):
        delete_files_older_than(str(tmp_path), days=0)

    fake.unlink.assert_not_called()


def test_multiple_files_mixed_ages(tmp_path):
    old = tmp_path / "old.log"
    new = tmp_path / "new.log"
    _old_file(old)
    new.write_text("recent")
    delete_files_older_than(str(tmp_path), days=30)
    assert not old.exists()
    assert new.exists()
