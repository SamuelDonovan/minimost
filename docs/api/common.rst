minimost.common
===============

.. automodule:: minimost.common
   :members:
   :undoc-members: False
   :show-inheritance:

Messages Table Schema
---------------------

The ``messages`` table created by :func:`minimost.common.init_messages_db`
has the following columns. There is one canonical row per message in the single
shared ``users/messages.db`` — no per-user copies.

.. list-table::
   :header-rows: 1
   :widths: 20 12 68

   * - Column
     - Type
     - Description
   * - ``id``
     - INTEGER PK
     - Auto-increment primary key; the canonical identifier used by edit,
       delete, reaction, and reply references.
   * - ``channel``
     - TEXT NOT NULL
     - Public channel name or DM identifier (``"dm:user1:user2"``).
   * - ``sender``
     - TEXT NOT NULL
     - Username of the message author.
   * - ``content``
     - TEXT
     - Message text body. ``NULL`` for image-only messages.
   * - ``content_type``
     - TEXT
     - ``'text'`` for normal messages; ``'system'`` for system notices
       (welcome, channel rename, member add/leave) rendered under the
       "MiniMost" identity.
   * - ``filename``
     - TEXT
     - Stored attachment filename (UUID-based). ``NULL`` for text-only messages.
   * - ``ts``
     - REAL NOT NULL
     - Unix timestamp (seconds, floating-point).
   * - ``edited``
     - INTEGER (0/1)
     - Whether this message has been edited.
   * - ``edited_ts``
     - REAL
     - Timestamp of the most recent edit.
   * - ``deleted``
     - INTEGER (0/1)
     - Soft-delete flag.
   * - ``deleted_ts``
     - REAL
     - Timestamp of deletion.
   * - ``reply_to_id``
     - INTEGER FK
     - Foreign key to ``messages.id`` for threaded replies.
   * - ``reactions_ts``
     - REAL
     - Bumped when a reaction is toggled (the reactions themselves live in the
       ``reactions`` table); the change drives re-delivery to viewers.
   * - ``mentions``
     - TEXT
     - JSON array of the channel members ``@``-mentioned in the message
       (or the ``"@everyone"`` sentinel); ``NULL`` when none. Set at send/edit
       time by :func:`minimost.chat.extract_mentions`.
   * - ``metadata``
     - TEXT
     - Reserved for future structured metadata.
   * - ``client_msg_id``
     - TEXT
     - Client-generated deduplication token.
   * - ``expires_ts``
     - REAL
     - Expiry timestamp for the associated upload file.
