"""
minimost.clean
==============

Maintenance utilities for purging old uploads and messages.

There are two kinds of limit — **age-based** retention and **size-based** caps:

* :func:`delete_files_older_than` removes file attachments from ``uploads/``
  once they pass a per-type age threshold.
* :func:`delete_messages_older_than` hard-deletes message rows from the shared
  ``messages.db`` once they pass an age threshold.
* :func:`delete_files_over_size` deletes the oldest files in ``uploads/`` until
  the directory's total size is back under a cap.
* :func:`delete_messages_over_size` deletes the oldest messages from
  ``messages.db`` until the database is back under a cap.

All are called automatically by a background daemon thread started in
:func:`minimost.create_app` — no cron job or external scheduler is required.
The thread runs 5 minutes after startup and repeats every 24 hours.  Settings
are read from ``settings.json`` on each run:

* ``"image_retention_days"`` — image file attachments (default: 30 days).
* ``"file_retention_days"`` — all other file attachments (default: 30 days).
* ``"message_retention_days"`` — messages in the message database (default: 770
  days).
* ``"max_upload_dir_size_mb"`` — total size cap for the ``uploads/`` directory;
  oldest files are deleted when exceeded (``0`` or absent disables the cap).
* ``"max_message_db_size_mb"`` — size cap for the shared message database;
  oldest messages are deleted when exceeded (``0`` or absent disables the cap).

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


def delete_files_over_size(
    directory: str,
    max_size_mb: float,
    dry_run: bool = False,
) -> None:
    """Delete the oldest files in *directory* until it fits within a size cap.

    The combined size of every regular file directly in *directory* is compared
    against *max_size_mb*.  While the total exceeds the cap, files are deleted
    **oldest-first** (by modification time) until the directory is back under it.

    This bounds the disk footprint of ``uploads/`` independently of the
    age-based retention in :func:`delete_files_older_than`: a burst of large
    uploads is trimmed by size even before any of it ages out.  The two run
    together — age-based cleanup first, then this size cap on whatever remains.

    Subdirectories are ignored (only regular files are counted and deleted), so
    the function is safe to point at a directory that nests other content.  A cap
    of ``0`` (or any non-positive value) disables the check.

    :param directory: Path to the directory to bound.
    :type directory: str
    :param max_size_mb: Maximum combined size in mebibytes.  Non-positive
        disables the check.
    :type max_size_mb: float
    :param dry_run: If ``True``, only print what would be deleted without
        removing any files.  Defaults to ``False``.
    :type dry_run: bool
    :raises ValueError: If *directory* does not exist or is not a directory.
    """
    if not max_size_mb or max_size_mb <= 0:
        return
    dirpath = Path(directory)
    if not dirpath.is_dir():
        raise ValueError(f"{directory} is not a valid directory")
    max_bytes = int(max_size_mb * 1024 * 1024)

    # Snapshot (mtime, size, path) for every regular file. stat() can race with
    # another worker's cleanup removing the file, so tolerate it disappearing.
    entries = []
    total = 0
    for path in dirpath.iterdir():
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        entries.append((stat.st_mtime, stat.st_size, path))
        total += stat.st_size

    if total <= max_bytes:
        return

    # Oldest first, so the most recent uploads are the last to be removed.
    entries.sort(key=lambda entry: entry[0])

    for _mtime, size, path in entries:
        if total <= max_bytes:
            break
        if dry_run:
            print(f"[DRY RUN] Would delete (size cap): {path}")
            total -= size
            continue
        try:
            path.unlink()
            total -= size
            print(f"Deleted (size cap): {path}")
        except FileNotFoundError:
            total -= size  # already removed by another worker; count it as freed


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


def _live_size_bytes(conn) -> int:
    """Return the size in bytes of the *live* (non-free) pages of a database.

    ``page_count`` counts every page, including those on the freelist left
    behind by deletes/edits; those free pages are reclaimed when the database is
    compacted. ``(page_count - freelist_count) × page_size`` is therefore the
    size the ``.db`` file shrinks to after compaction, which is the meaningful
    quantity to cap: it ignores transient free-page bloat (so we don't delete
    messages merely because space has not been reclaimed yet) and is independent
    of the WAL file, avoiding the WAL-mode quirk where ``os.stat`` on the main
    file lags committed changes until a checkpoint.
    """
    page_count = conn.execute("PRAGMA page_count").fetchone()[0]
    freelist = conn.execute("PRAGMA freelist_count").fetchone()[0]
    page_size = conn.execute("PRAGMA page_size").fetchone()[0]
    return (page_count - freelist) * page_size


def delete_messages_over_size(
    db_path: str,
    max_size_mb: float,
    dry_run: bool = False,
    batch: int = 1000,
) -> None:
    """Delete the oldest messages until the message database fits a size cap.

    The shared ``messages.db`` is the only database that grows with prunable
    content, so it is the only one a size cap can be enforced on.  Size is
    measured as the live (post-compaction) data size — see
    :func:`_live_size_bytes` — so transient free-page bloat never triggers a
    deletion.  When that size exceeds *max_size_mb*, the oldest messages (lowest
    ``ts``) are deleted in batches of *batch* rows until the database is back
    under the cap, after which the freed pages are reclaimed in one ``VACUUM``
    and the WAL checkpointed so the on-disk file shrinks to match.  ``VACUUM``
    runs at most once per call, and only when something was actually pruned.

    A size cap of ``0`` (or any non-positive value) disables the check, leaving
    age-based retention as the only purge.  The database is opened only when it
    actually exceeds the cap.

    :param db_path: Path to the shared ``messages.db`` file.
    :type db_path: str
    :param max_size_mb: Maximum allowed size in mebibytes.  Non-positive
        disables the cap.
    :type max_size_mb: float
    :param dry_run: If ``True``, only report what would be deleted.
    :type dry_run: bool
    :param batch: Number of oldest messages to delete per cycle.
    :type batch: int
    """
    if not max_size_mb or max_size_mb <= 0:
        return
    path = Path(db_path)
    if not path.is_file():
        return
    max_bytes = int(max_size_mb * 1024 * 1024)

    conn = sqlite3.connect(str(path))
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        if not _has_table(conn, "messages"):
            return

        size = _live_size_bytes(conn)
        if size <= max_bytes:
            return

        if dry_run:
            print(
                f"[DRY RUN] {path.name} holds {size / 1048576:.1f} MiB of "
                f"messages, over the {max_size_mb} MiB cap; would delete the "
                f"oldest"
            )
            return

        deleted_total = 0
        while size > max_bytes:
            ids = [
                row[0]
                for row in conn.execute(
                    "SELECT id FROM messages ORDER BY ts ASC, id ASC LIMIT ?",
                    (batch,),
                ).fetchall()
            ]
            if not ids:
                break  # table is empty but the schema still exceeds the cap
            placeholders = ",".join("?" * len(ids))
            # nosec B608 — placeholders is a string of bound-parameter markers,
            # never message data; the ids are passed as parameters.
            conn.execute(
                f"DELETE FROM messages WHERE id IN ({placeholders})", ids
            )  # nosec B608
            # Reactions reference messages by id; drop any now-orphaned rows.
            # (The FTS index self-cleans via its delete trigger.)
            if _has_table(conn, "reactions"):
                conn.execute(
                    "DELETE FROM reactions WHERE message_id NOT IN "
                    "(SELECT id FROM messages)"
                )
            conn.commit()
            deleted_total += len(ids)

            new_size = _live_size_bytes(conn)
            if new_size >= size:
                # A batch freed no whole page (e.g. many tiny rows). Stop rather
                # than loop forever making no progress toward the cap.
                break
            size = new_size

        if deleted_total:
            # Reclaim the freed pages and collapse the WAL into the main file so
            # the on-disk size reflects the deletions immediately. VACUUM fully
            # compacts in one pass (a stepped ``PRAGMA incremental_vacuum`` only
            # releases a single page per call through Python's sqlite3); it runs
            # at most once per call and only after a prune, so the cost is rare.
            conn.execute("VACUUM")
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            print(
                f"Deleted {deleted_total} oldest messages from {path.name} "
                f"to stay under {max_size_mb} MiB"
            )
    finally:
        conn.close()


def _has_table(conn, name: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
        is not None
    )


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
            # Reactions reference messages by id; drop any now-orphaned rows so
            # they don't accumulate. (The FTS index self-cleans via its trigger.)
            if _has_table(conn, "reactions"):
                conn.execute(
                    "DELETE FROM reactions WHERE message_id NOT IN (SELECT id FROM messages)"
                )
            conn.commit()
            if conn.execute("PRAGMA auto_vacuum").fetchone()[0] == 0:
                conn.execute("PRAGMA auto_vacuum = FULL")
                conn.execute("VACUUM")
    finally:
        conn.close()


if __name__ == "__main__":
    delete_files_older_than(directory="uploads", image_days=30, file_days=30)
    delete_files_over_size(directory="uploads", max_size_mb=2048)
    delete_messages_older_than(users_dir="users", days=770)
    delete_messages_over_size(db_path="users/messages.db", max_size_mb=1024)
