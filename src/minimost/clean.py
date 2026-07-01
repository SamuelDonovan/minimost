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
from typing import Optional
import time

_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

# SQLite journal mode used for every connection opened here.
_WAL_PRAGMA = "PRAGMA journal_mode=WAL"


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


def _snapshot_files(dirpath: Path):
    """Snapshot ``(mtime, size, path)`` for every regular file in *dirpath*.

    ``stat()`` can race with another worker's cleanup removing the file, so a
    file that disappears mid-scan is simply skipped.

    :param dirpath: Directory to scan (non-recursively).
    :type dirpath: pathlib.Path
    :returns: A tuple ``(entries, total_bytes)`` where *entries* is a list of
        ``(mtime, size, path)`` tuples and *total_bytes* is their summed size.
    :rtype: tuple[list, int]
    """
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
    return entries, total


def _file_owners(owner_db: str) -> dict:
    """Map each stored upload filename to its uploader, read from *owner_db*.

    A file's owner is the ``sender`` of the message whose ``filename`` column
    references it. Returns an empty dict when the database, its ``messages``
    table, or its ``filename`` column is unavailable, so the caller transparently
    falls back to plain oldest-first eviction.

    :param owner_db: Path to the shared ``messages.db``.
    :returns: ``{stored_filename: uploader}``.
    :rtype: dict
    """
    path = Path(owner_db)
    if not path.is_file():
        return {}
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(_WAL_PRAGMA)
        if not _has_table(conn, "messages"):
            return {}
        rows = conn.execute(
            "SELECT filename, sender FROM messages "
            "WHERE filename IS NOT NULL AND filename != ''"
        ).fetchall()
    except sqlite3.Error:
        return {}
    finally:
        conn.close()
    return dict(rows)


def _fair_file_order(entries, owners: dict):
    """Order ``(mtime, size, path)`` entries for fair size-cap deletion.

    Yields ``(size, path)`` pairs in the order they should be removed: files with
    no known owner first (orphans, or every file when *owners* is empty),
    oldest-first; then the remaining files by repeatedly trimming the owner that
    currently holds the most bytes, oldest of theirs first. The greedy pick keeps
    the largest consumer shrinking until another owner overtakes it, so deletions
    stay proportional to consumption instead of falling entirely on whoever
    happens to have the oldest files.

    :param entries: ``(mtime, size, path)`` tuples from :func:`_snapshot_files`.
    :param owners: ``{filename: uploader}`` map (empty for oldest-first).
    :returns: A list of ``(size, path)`` tuples in deletion order.
    :rtype: list
    """
    by_owner = {}
    orphans = []
    for mtime, size, path in entries:
        owner = owners.get(path.name)
        if owner is None:
            orphans.append((mtime, size, path))
        else:
            by_owner.setdefault(owner, []).append((mtime, size, path))

    order = [(size, path) for _mtime, size, path in sorted(orphans, key=lambda e: e[0])]

    for files in by_owner.values():
        files.sort(key=lambda e: e[0])  # oldest-first within each owner
    owner_bytes = {o: sum(e[1] for e in files) for o, files in by_owner.items()}

    while by_owner:
        owner = max(owner_bytes, key=owner_bytes.get)
        _mtime, size, path = by_owner[owner].pop(0)
        order.append((size, path))
        owner_bytes[owner] -= size
        if not by_owner[owner]:
            del by_owner[owner]
            del owner_bytes[owner]

    return order


def delete_files_over_size(
    directory: str,
    max_size_mb: float,
    dry_run: bool = False,
    owner_db: Optional[str] = None,
) -> None:
    """Delete files in *directory* until its total size fits within a cap.

    The combined size of every regular file directly in *directory* is compared
    against *max_size_mb*.  While the total exceeds the cap, files are deleted
    until the directory is back under it.

    This bounds the disk footprint of ``uploads/`` independently of the
    age-based retention in :func:`delete_files_older_than`: a burst of large
    uploads is trimmed by size even before any of it ages out.  The two run
    together — age-based cleanup first, then this size cap on whatever remains.

    Eviction order depends on *owner_db*:

    * **With** *owner_db* — the upload→uploader mapping is read from the shared
      message database (a file's owner is the sender of the message that
      references it).  Files with no owner (orphans whose message was deleted)
      are removed first, oldest-first; the rest are removed by repeatedly
      trimming the **uploader currently holding the most bytes**, oldest of
      theirs first.  This makes the cap *fair*: a single account that floods the
      directory has its own uploads purged before anyone else's.
    * **Without** *owner_db* — files are simply removed oldest-first (by
      modification time), the historic behaviour.

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
    :param owner_db: Optional path to the shared ``messages.db``; when given,
        eviction is made fair across uploaders (see above).
    :type owner_db: str or None
    :raises ValueError: If *directory* does not exist or is not a directory.
    """
    if not max_size_mb or max_size_mb <= 0:
        return
    dirpath = Path(directory)
    if not dirpath.is_dir():
        raise ValueError(f"{directory} is not a valid directory")
    max_bytes = int(max_size_mb * 1024 * 1024)

    entries, total = _snapshot_files(dirpath)
    if total <= max_bytes:
        return

    owners = _file_owners(owner_db) if owner_db else {}

    for size, path in _fair_file_order(entries, owners):
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


def _heaviest_sender(conn):
    """Return the sender consuming the most message bytes, or ``None`` if empty.

    "Bytes" is the summed length of each sender's ``content`` text — the
    dominant driver of database size — with message count as a tiebreaker (so
    senders of empty-content attachment rows are still ranked). This is what
    makes size-cap eviction fair: the account that has written the most is
    trimmed first, so a flooder's own messages go before anyone else's.
    """
    row = conn.execute(
        "SELECT sender FROM messages GROUP BY sender ORDER BY "
        "SUM(LENGTH(COALESCE(content, ''))) DESC, COUNT(*) DESC LIMIT 1"
    ).fetchone()
    return row[0] if row else None


def _evict_until_under_cap(conn, size: int, max_bytes: int, batch: int) -> int:
    """Delete oldest messages in fair batches until the live size fits the cap.

    Fair eviction: each batch trims the sender currently consuming the most space
    (see :func:`_heaviest_sender`), oldest of theirs first. A flood from one
    account makes that account the heaviest, so its own messages are purged
    before any other user's history — a single spammer cannot evict everyone
    else's data the way a pure global-oldest pass would. With one dominant sender
    this naturally reduces to oldest-first.

    :param conn: Open connection to the message database.
    :param size: The current live size in bytes (already known to exceed the cap).
    :param max_bytes: Target size cap in bytes.
    :param batch: Number of oldest messages to delete per cycle.
    :returns: The total number of messages deleted.
    :rtype: int
    """
    deleted_total = 0
    while size > max_bytes:
        sender = _heaviest_sender(conn)
        if sender is None:
            break  # table is empty but the schema still exceeds the cap
        ids = [
            row[0]
            for row in conn.execute(
                "SELECT id FROM messages WHERE sender = ? "
                "ORDER BY ts ASC, id ASC LIMIT ?",
                (sender, batch),
            ).fetchall()
        ]
        if not ids:
            break  # table is empty but the schema still exceeds the cap
        placeholders = ",".join("?" * len(ids))
        # nosec B608 — placeholders is a string of bound-parameter markers,
        # never message data; the ids are passed as parameters.
        conn.execute(
            f"DELETE FROM messages WHERE id IN ({placeholders})", ids  # nosec B608
        )
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
    return deleted_total


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
    deletion.  When that size exceeds *max_size_mb*, messages are deleted in
    batches of *batch* rows until the database is back under the cap, after which
    the freed pages are reclaimed in one ``VACUUM`` and the WAL checkpointed so
    the on-disk file shrinks to match.  ``VACUUM`` runs at most once per call,
    and only when something was actually pruned.

    Eviction is **fair**: each batch targets the oldest messages of the sender
    currently consuming the most space (see :func:`_heaviest_sender`), so a
    single account that floods the channel has its own messages purged before
    any other user's history.  When one sender dominates this is equivalent to
    deleting the globally oldest messages first.

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
        conn.execute(_WAL_PRAGMA)
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

        deleted_total = _evict_until_under_cap(conn, size, max_bytes, batch)

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
        conn.execute(_WAL_PRAGMA)
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
