Administration
==============

This page covers tasks a server administrator may need to perform to keep
MiniMost running smoothly.

Image Cleanup
-------------

Image attachments are stored indefinitely in ``uploads/`` unless cleaned up.
The :mod:`minimost.clean` module provides the :func:`~minimost.clean.delete_files_older_than`
function for this purpose.

**Running manually:**

.. code-block:: bash

    python3 src/minimost/clean.py

This deletes files in ``uploads/`` older than 30 days (the hardcoded default
when the script is run directly).

**Dry run (preview without deleting):**

.. code-block:: python

    from minimost.clean import delete_files_older_than
    delete_files_older_than("uploads", days=30, dry_run=True)

**Scheduled cron job** (recommended — runs daily at 02:30):

.. code-block:: bash

    crontab -e

Add the following line::

    30 2 * * * /usr/bin/python3 /srv/minimost/src/minimost/clean.py

.. note::

   The cleanup script operates on filesystem ``mtime`` values, not on the
   database ``expires_ts`` column. Deleted files leave behind orphan database
   rows; this is intentional — messages referencing deleted images show
   a broken-image placeholder rather than being removed.

User Management
---------------

MiniMost has no admin UI. User management is done directly via SQLite.

**List all users:**

.. code-block:: bash

    sqlite3 auth.db "SELECT username FROM users;"

**Reset a forgotten password:**

Use the built-in CLI command to generate a one-time, time-limited reset URL:

.. code-block:: bash

    minimost reset-password alice

This stores a secure token in ``auth.db``, sends the user a system DM notifying
them that a reset was requested, and prints a URL to stdout. Share that URL with
the user through a side-channel (email, phone, etc.). When they open it they can
set a new password; the link is invalidated immediately after use.

By default the link expires in 60 minutes. Adjust with ``--expires``:

.. code-block:: bash

    minimost reset-password alice --expires 30

If the server is not on ``127.0.0.1:5000``, provide the public base URL so the
printed link is correct:

.. code-block:: bash

    minimost reset-password alice --base-url https://chat.example.com

Run ``minimost reset-password --help`` for the full list of options.

.. note::

   Reset tokens are single-use and stored in the ``password_reset_tokens`` table
   in ``auth.db``. Expired tokens are never automatically purged, but they are
   harmless — they are rejected at validation time. To clean them up manually:

   .. code-block:: bash

       sqlite3 auth.db "DELETE FROM password_reset_tokens WHERE used = 1 OR expires_ts < unixepoch();"

**Delete a user:**

1. Remove the user's record and settings from ``auth.db``::

    sqlite3 auth.db "DELETE FROM users WHERE username = 'alice';"
    sqlite3 auth.db "DELETE FROM user_settings WHERE username = 'alice';"

2. Delete the user's database file::

    rm users/alice.db

3. Remove the user's avatar image (if one exists)::

    # The filename is stored in user_settings.avatar_file; delete it from avatars/
    rm -f avatars/alice_*.jpg   # or check auth.db for the exact filename

4. Remove the user's presence records (optional)::

    sqlite3 presence.db "DELETE FROM presence WHERE user = 'alice';"
    sqlite3 presence.db "DELETE FROM typing WHERE user = 'alice';"
    sqlite3 presence.db "DELETE FROM read_receipts WHERE reader = 'alice';"
    sqlite3 presence.db "DELETE FROM message_reactions WHERE reactor = 'alice';"

.. warning::

   Deleting a user does **not** remove their messages from other users'
   databases. Their messages will still appear in other users' chat history,
   attributed to their username. There is no automatic cascade-delete across
   per-user databases.

**Add a channel:**

Edit ``channels.json`` and restart the server::

    # channels.json (before)
    ["general", "software"]

    # channels.json (after)
    ["general", "software", "design"]

**Remove a channel:**

Edit ``channels.json``, removing the unwanted channel name, and restart the
server. Existing messages for that channel remain in all user databases but
will no longer be accessible through the UI.

Database Maintenance
--------------------

**Check WAL file sizes:**

If a user's database has a large ``.wal`` file, it means the WAL has not
been checkpointed. Force a checkpoint:

.. code-block:: bash

    sqlite3 users/alice.db "PRAGMA wal_checkpoint(FULL);"

**Compact a database:**

After many soft-deletes, a database may grow larger than necessary. Run
``VACUUM`` to reclaim space:

.. code-block:: bash

    sqlite3 users/alice.db "VACUUM;"

Note: ``VACUUM`` rewrites the entire database file and can take a while on
large databases.

**Check for corruption:**

.. code-block:: bash

    sqlite3 auth.db "PRAGMA integrity_check;"
    sqlite3 presence.db "PRAGMA integrity_check;"
    for db in users/*.db; do
        echo "Checking $db..."
        sqlite3 "$db" "PRAGMA integrity_check;"
    done

Backup and Restore
------------------

**Backup:**

All state lives in these locations:

.. code-block:: bash

    # Full backup
    tar -czf minimost-backup-$(date +%Y%m%d).tar.gz \
        auth.db \
        presence.db \
        secret.key \
        channels.json \
        users/ \
        uploads/ \
        avatars/

**Restore:**

.. code-block:: bash

    tar -xzf minimost-backup-20240101.tar.gz -C /srv/minimost/

**Hot backup** (without stopping the server):

SQLite WAL mode allows safe online backups using the ``.backup`` command:

.. code-block:: bash

    sqlite3 auth.db ".backup /backup/auth.db"
    sqlite3 presence.db ".backup /backup/presence.db"
    for db in users/*.db; do
        name=$(basename "$db")
        sqlite3 "$db" ".backup /backup/users/$name"
    done

Monitoring
----------

**Check server status (systemd):**

.. code-block:: bash

    systemctl status minimost
    journalctl -u minimost -f

**Check disk usage:**

.. code-block:: bash

    du -sh users/ uploads/ auth.db presence.db

**Count messages per user:**

.. code-block:: bash

    for db in users/*.db; do
        user=$(basename "$db" .db)
        count=$(sqlite3 "$db" "SELECT COUNT(*) FROM messages WHERE deleted=0;")
        echo "$user: $count messages"
    done

Migrating to a New Server
--------------------------

1. Install MiniMost on the new server.
2. Stop the old server.
3. Copy all data files::

    rsync -avz \
        auth.db \
        presence.db \
        secret.key \
        channels.json \
        users/ \
        uploads/ \
        avatars/ \
        newserver:/srv/minimost/

4. Start the new server.
5. Verify that existing sessions work (they will, because ``secret.key`` was
   preserved).

If you do **not** copy ``secret.key``, a new key will be generated and all
existing browser sessions will be invalidated — users will have to log in
again.
