"""
minimost.clean
==============

Maintenance utility for purging old uploads.

MiniMost stores file attachments in the ``uploads/`` directory.
:func:`delete_files_older_than` is called automatically by a background daemon
thread started in :func:`minimost.create_app` — no cron job or external
scheduler is required.  The thread runs 5 minutes after startup and repeats
every 24 hours.  Retention periods are read from ``settings.json`` on each run:

* ``"image_retention_days"`` — applies to image files (default: 30 days).
* ``"file_retention_days"`` — applies to all other file types (default: 30 days).

This module can also be invoked directly for ad-hoc cleanup:

.. code-block:: bash

    python3 src/minimost/clean.py

.. note::

   This script operates on filesystem modification times (``mtime``), not on
   the ``expires_ts`` column in the database.  Deleting a file makes its URL
   return 404 but does not remove the corresponding database row.  This is
   intentional — the soft-delete approach means historical metadata is
   preserved even when the binary data is gone.
"""

from pathlib import Path
import time

_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


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
        if not path.is_file():
            continue

        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue

        ext = path.suffix.lower()
        cutoff = image_cutoff if ext in _IMAGE_EXTENSIONS else file_cutoff

        if mtime < cutoff:
            if dry_run:
                print(f"[DRY RUN] Would delete: {path}")
            else:
                try:
                    path.unlink()
                    print(f"Deleted: {path}")
                except FileNotFoundError:
                    pass  # already removed by another process


if __name__ == "__main__":
    delete_files_older_than(directory="uploads", image_days=30, file_days=30)
