"""
minimost.clean
==============

Maintenance utilities for purging old uploads and messages.

:func:`delete_files_older_than` removes old file attachments from ``uploads/``.
:func:`delete_messages_older_than` hard-deletes old rows from every per-user
message database in ``users/``.  Both are called automatically by a background
daemon thread started in :func:`minimost.create_app` — no cron job or external
scheduler is required.  The thread runs 5 minutes after startup and repeats
every 24 hours.  Retention periods are read from ``settings.json`` on each run:

* ``"image_retention_days"`` — image file attachments (default: 30 days).
* ``"file_retention_days"`` — all other file attachments (default: 30 days).
* ``"message_retention_days"`` — messages in user databases (default: 770 days).

This module can also be invoked directly for ad-hoc cleanup:

.. code-block:: bash

    python3 src/minimost/clean.py
"""

import sqlite3
from pathlib import Path
import time

_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


def _maybe_delete_file(
    path: Path, image_cutoff: float, file_cutoff: float, dry_run: bool
) -> None:
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return
    cutoff = image_cutoff if path.suffix.lower() in _IMAGE_EXTENSIONS else file_cutoff
    if mtime >= cutoff:
        return
    if dry_run:
        print(f"[DRY RUN] Would delete: {path}")
        return
    try:
        path.unlink()
        print(f"Deleted: {path}")
    except FileNotFoundError:
        pass  # already removed by another process


def delete_files_older_than(
    directory: str,
    image_days: int,
    file_days: int,
    dry_run: bool = False,
):
    """Delete files in *directory* based on type-specific retention periods.

    Image files (jpg, jpeg, png, gif, webp) are removed when older than
    *image_days*; all other files are removed when older than *file_days*.

    :param directory: Path to the directory to clean.
    :type directory: str
    :param image_days: Retention period in days for image files.
    :type image_days: int
    :param file_days: Retention period in days for non-image files.
    :type file_days: int
    :param dry_run: If ``True``, only print what would be deleted without
        removing any files.  Defaults to ``False``.
    :type dry_run: bool
    :raises ValueError: If *directory* does not exist or is not a directory.
    """
    now = time.time()
    image_cutoff = now - (image_days * 86400)
    file_cutoff = now - (file_days * 86400)
    dirpath = Path(directory)

    if not dirpath.is_dir():
        raise ValueError(f"{directory} is not a valid directory")

    for path in dirpath.iterdir():
        if path.is_file():
            _maybe_delete_file(path, image_cutoff, file_cutoff, dry_run)


def delete_messages_older_than(users_dir: str, days: int, dry_run: bool = False):
    """Hard-delete messages older than *days* from every user database.

    Iterates every ``*.db`` file in *users_dir* and removes rows from the
    ``messages`` table whose ``ts`` timestamp predates the cutoff.  Each
    database is processed independently so a single corrupted file does not
    abort the run.

    :param users_dir: Path to the directory containing per-user ``.db`` files.
    :type users_dir: str
    :param days: Messages older than this many days are deleted.
    :type days: int
    :param dry_run: If ``True``, print what would be deleted without making
        any changes.  Defaults to ``False``.
    :type dry_run: bool
    :raises ValueError: If *users_dir* does not exist or is not a directory.
    """
    cutoff = time.time() - (days * 86400)
    dirpath = Path(users_dir)

    if not dirpath.is_dir():
        raise ValueError(f"{users_dir} is not a valid directory")

    for db_file in sorted(dirpath.glob("*.db")):
        try:
            _clean_user_db(db_file, cutoff, dry_run)
        except Exception:  # nosec B110 — one bad DB must not stop the rest
            pass


def _clean_user_db(db_file: Path, cutoff: float, dry_run: bool) -> None:
    # try/finally guarantees the connection is closed even when a query raises
    # (e.g. a locked DB or a VACUUM error). The caller swallows the exception,
    # so without this the connection would leak and surface as a ResourceWarning.
    conn = sqlite3.connect(str(db_file))
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        if dry_run:
            row = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE ts < ?", (cutoff,)
            ).fetchone()
            count = row[0] if row else 0
            if count > 0:
                print(f"[DRY RUN] Would delete {count} messages from {db_file.name}")
        else:
            cur = conn.execute("DELETE FROM messages WHERE ts < ?", (cutoff,))
            if cur.rowcount > 0:
                print(f"Deleted {cur.rowcount} messages from {db_file.name}")
            conn.commit()
            if conn.execute("PRAGMA auto_vacuum").fetchone()[0] == 0:
                conn.execute("PRAGMA auto_vacuum = FULL")
                conn.execute("VACUUM")
    finally:
        conn.close()


if __name__ == "__main__":
    delete_files_older_than(directory="uploads", image_days=30, file_days=30)
    delete_messages_older_than(users_dir="users", days=770)
