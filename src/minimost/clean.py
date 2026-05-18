"""
minimost.clean
==============

Maintenance utility for purging old image uploads.

MiniMost stores image attachments in the ``uploads/`` directory with no
automatic expiry.  This module provides :func:`delete_files_older_than`,
which is intended to be run as a scheduled cron job to prevent unbounded
disk growth.

**Recommended crontab entry** (runs daily at 02:30)::

    30 2 * * * /usr/bin/python3 /path/to/minimost/src/minimost/clean.py

When executed directly (``python -m minimost.clean`` or as the cron command
above) the script deletes files in the ``uploads/`` directory that are older
than 30 days.

.. note::

   This script operates on filesystem modification times (``mtime``), not on
   the ``expires_ts`` column in the database.  Deleting a file makes its URL
   return 404 but does not remove the corresponding database row.  This is
   intentional — the soft-delete approach means historical metadata is
   preserved even when the binary data is gone.
"""

from pathlib import Path
import time


def delete_files_older_than(directory: str, days: int, dry_run: bool = False):
    """Delete files in *directory* whose modification time is older than *days*.

    Iterates over every file (not directory) directly inside *directory* and
    removes those whose ``mtime`` predates the computed cutoff timestamp.
    Subdirectories are skipped.

    Files that cannot be stat'd (e.g. due to a permission error) are silently
    skipped so a single unreadable file does not abort the cleanup run.

    **Dry-run mode:**

    When *dry_run* is ``True`` the function prints a ``[DRY RUN]`` line for
    each file it *would* delete but does not actually remove anything.  This
    is useful for previewing what a scheduled run will clean up::

        delete_files_older_than("uploads", days=30, dry_run=True)

    **Normal mode:**

    Each deleted file is logged to stdout so the cron daemon (or systemd
    journal) captures an audit trail.

    :param directory: Path to the directory to clean.  Relative paths are
        resolved from the current working directory.
    :type directory: str
    :param days: Files older than this many days will be deleted.  For
        example, ``days=30`` removes files not modified in the last 30 days.
    :type days: int
    :param dry_run: If ``True``, only print what would be deleted without
        removing any files.  Defaults to ``False``.
    :type dry_run: bool
    :returns: None
    :raises ValueError: If *directory* does not exist or is not a directory.

    Example::

        # Remove uploads older than 14 days
        delete_files_older_than("uploads", days=14)

        # Preview what would be removed without deleting
        delete_files_older_than("uploads", days=14, dry_run=True)
    """
    cutoff = time.time() - (days * 86400)
    directory = Path(directory)

    if not directory.is_dir():
        raise ValueError(f"{directory} is not a valid directory")

    for path in directory.iterdir():
        if not path.is_file():
            continue

        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue  # skip unreadable files

        if mtime < cutoff:
            if dry_run:
                print(f"[DRY RUN] Would delete: {path}")
            else:
                path.unlink()
                print(f"Deleted: {path}")


if __name__ == "__main__":
    delete_files_older_than(directory="uploads", days=30)
