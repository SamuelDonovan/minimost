Administration
==============

This page covers tasks a server administrator may need to perform to keep
MiniMost running smoothly.

Automatic Cleanup
-----------------

MiniMost runs a background cleanup thread that starts 5 minutes after startup
and repeats every 24 hours. No cron job or external scheduler is required. Each
run applies two kinds of limit — **age** and **size** — to two stores:

1. **File cleanup** — removes attachments from ``uploads/`` once they pass an
   age threshold, then deletes the oldest files if the directory exceeds a total
   size cap.
2. **Message cleanup** — permanently deletes rows from ``users/messages.db``
   (along with their reactions and search-index entries) once they pass an age
   threshold, then deletes the oldest messages if the database exceeds a total
   size cap.

All retention periods and size caps are read from ``settings.json`` on each run,
so changes take effect at the next scheduled run without restarting the server.
See :doc:`configuration` for the full list of keys and defaults.

File Cleanup
~~~~~~~~~~~~

Separate retention periods apply to different file types (both default: 30 days):

- ``"image_retention_days"`` — images (jpg, jpeg, png, gif, webp)
- ``"file_retention_days"`` — all other file types (pdf, zip, docx, etc.)

**Running file cleanup manually:**

.. code-block:: bash

    python3 src/minimost/clean.py

**Dry run (preview without deleting):**

.. code-block:: python

    from minimost.clean import delete_files_older_than
    delete_files_older_than("uploads", image_days=30, file_days=30, dry_run=True)

**Custom retention:**

.. code-block:: python

    from minimost.clean import delete_files_older_than
    # Keep images for 90 days, delete other files after 7 days
    delete_files_older_than("uploads", image_days=90, file_days=7)

.. note::

   File cleanup operates on filesystem ``mtime`` values. Deleted files leave
   behind orphan database rows — messages referencing deleted files show a
   "File deleted" indicator rather than being removed from chat history.

**Size cap (delete oldest files until the directory fits):**

Independently of age, ``"max_upload_dir_size_mb"`` (default: 2048) bounds the
total size of ``uploads/``. When exceeded, the oldest files are deleted until
the directory is back under the cap:

.. code-block:: python

    from minimost.clean import delete_files_over_size
    # Keep uploads/ under 2 GiB; preview first with dry_run=True
    delete_files_over_size("uploads", max_size_mb=2048, dry_run=True)
    delete_files_over_size("uploads", max_size_mb=2048)

Message Cleanup
~~~~~~~~~~~~~~~

Old messages are permanently deleted from ``users/messages.db`` to prevent the
database from growing without bound. The retention period is set by
``"message_retention_days"`` in ``settings.json`` (default: 770 days).

**Running message cleanup manually:**

.. code-block:: python

    from minimost.clean import delete_messages_older_than
    delete_messages_older_than("users", days=770)

**Dry run (preview without deleting):**

.. code-block:: python

    from minimost.clean import delete_messages_older_than
    delete_messages_older_than("users", days=770, dry_run=True)

.. warning::

   Message cleanup is a **permanent hard delete** — rows are removed from the
   database entirely and cannot be recovered. Ensure your ``message_retention_days``
   value is set to a period that comfortably covers how far back your users
   ever need to scroll before lowering it.

**Size cap (delete oldest messages until the database fits):**

Independently of age, ``"max_message_db_size_mb"`` (default: 1024) bounds the
size of ``users/messages.db``. When exceeded, the oldest messages are deleted
(and the file compacted) until it is back under the cap:

.. code-block:: python

    from minimost.clean import delete_messages_over_size
    # Keep messages.db under 1 GiB; preview first with dry_run=True
    delete_messages_over_size("users/messages.db", max_size_mb=1024, dry_run=True)
    delete_messages_over_size("users/messages.db", max_size_mb=1024)

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

Account Deletion
~~~~~~~~~~~~~~~~

Users can delete their own account from **Settings → Danger Zone**. Two modes
are available, both requiring the user to enter their current password before
anything is changed.

**Soft delete**

Removes the user's login credentials, settings, and avatar. Every message they
sent is re-attributed to ``Deleted User`` in the shared message store. Chat
history remains intact and visible to other users. The account cannot be
recovered, but a new account with the same username can be registered later.

**Hard delete**

Removes the user's login credentials, settings, and avatar, and additionally
deletes every message they ever sent (and its reactions) from the shared message
store. Private channels the user created are left intact (other members'
messages are unaffected); only the deleted user's own messages are removed.

.. note::

   After either deletion the user's session is immediately invalidated and
   they are redirected to the login page. Private channel memberships and
   presence records are cleaned up automatically in both cases.

**Manual deletion (admin override)**

If an account must be removed by an administrator without the user's
co-operation, replicate the hard delete steps directly against the databases.
The self-service flow above is the recommended path whenever possible.

.. code-block:: bash

    # 1. Remove credentials and settings
    sqlite3 auth.db "DELETE FROM users WHERE username = 'alice';"
    sqlite3 auth.db "DELETE FROM user_settings WHERE username = 'alice';"
    sqlite3 auth.db "DELETE FROM password_reset_tokens WHERE username = 'alice';"

    # 2. Remove the user's messages, reactions and read state from the shared store
    sqlite3 users/messages.db "DELETE FROM messages WHERE sender = 'alice';"
    sqlite3 users/messages.db "DELETE FROM reactions WHERE reactor = 'alice';"
    sqlite3 users/messages.db "DELETE FROM read_state WHERE user = 'alice';"
    sqlite3 users/messages.db "DELETE FROM dm_hidden WHERE user = 'alice';"

    # 3. Delete the user's avatar
    # avatar filename is stored in user_settings.avatar_file — check before deleting
    rm -f avatars/<avatar_filename>

    # 4. Remove presence records
    sqlite3 presence.db "DELETE FROM presence WHERE user = 'alice';"
    sqlite3 presence.db "DELETE FROM typing WHERE user = 'alice';"
    sqlite3 presence.db "DELETE FROM private_channel_members WHERE username = 'alice';"
    sqlite3 presence.db "DELETE FROM call_participants WHERE username = 'alice';"

**Add a channel:**

Edit the ``"channels"`` list in ``settings.json`` and restart the server::

    # settings.json (before)
    {"channels": ["general", "software"], "image_retention_days": 30, "file_retention_days": 30, "message_retention_days": 770}

    # settings.json (after)
    {"channels": ["general", "software", "design"], "image_retention_days": 30, "file_retention_days": 30, "message_retention_days": 770}

**Remove a channel:**

Edit the ``"channels"`` list in ``settings.json``, removing the unwanted channel
name, and restart the server. Existing messages for that channel remain in all
user databases but will no longer be accessible through the UI.

Database Maintenance
--------------------

**Check WAL file sizes:**

If the message database has a large ``.wal`` file, it means the WAL has not
been checkpointed. Force a checkpoint:

.. code-block:: bash

    sqlite3 users/messages.db "PRAGMA wal_checkpoint(FULL);"

**Compact a database:**

After many soft-deletes, a database may grow larger than necessary. Run
``VACUUM`` to reclaim space:

.. code-block:: bash

    sqlite3 users/messages.db "VACUUM;"

Note: ``VACUUM`` rewrites the entire database file and can take a while on
large databases.

**Check for corruption:**

.. code-block:: bash

    sqlite3 auth.db "PRAGMA integrity_check;"
    sqlite3 presence.db "PRAGMA integrity_check;"
    sqlite3 users/messages.db "PRAGMA integrity_check;"

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
        cert.pem \
        key.pem \
        settings.json \
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
    sqlite3 users/messages.db ".backup /backup/users/messages.db"

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

    sqlite3 users/messages.db \
        "SELECT sender, COUNT(*) FROM messages WHERE deleted=0 GROUP BY sender ORDER BY 2 DESC;"

Migrating to a New Server
--------------------------

1. Install MiniMost on the new server.
2. Stop the old server.
3. Copy all data files::

    rsync -avz \
        auth.db \
        presence.db \
        secret.key \
        cert.pem \
        key.pem \
        settings.json \
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
