from pathlib import Path
import time

# Set up to run every day at 2:30 AM:
#
# crontab -e
# 30 2 * * * /usr/bin/python3 /Data01/minimost/cleanup.py


def delete_files_older_than(directory: str, days: int, dry_run: bool = False):
    """
    Delete files in `directory` older than `days`.

    :param directory: Path to directory
    :param days: Age threshold in days
    :param dry_run: If True, only print files that would be deleted
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
    delete_files_older_than(directory = "uploads", days=30)

