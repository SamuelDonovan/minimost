minimost.common
===============

.. automodule:: minimost.common
   :members:
   :undoc-members: False
   :show-inheritance:

Messages Table Schema
---------------------

The ``messages`` table created by :func:`minimost.common.init_user_db`
has the following columns:

.. list-table::
   :header-rows: 1
   :widths: 20 12 68

   * - Column
     - Type
     - Description
   * - ``id``
     - INTEGER PK
     - Auto-increment primary key (differs across per-user databases).
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
     - Always ``'text'``. Reserved for future media types.
   * - ``filename``
     - TEXT
     - UUID-based image filename. ``NULL`` for text-only messages.
   * - ``ts``
     - REAL NOT NULL
     - Unix timestamp (seconds, floating-point). Shared across all user
       copies of the same message.
   * - ``edited``
     - INTEGER (0/1)
     - Whether this message has been edited.
   * - ``edited_ts``
     - REAL
     - Timestamp of the most recent edit.
   * - ``read``
     - INTEGER (0/1)
     - Per-user read flag. Sender's copy is inserted as ``read=0``; seeds
       from :func:`minimost.auth._seed_channel_history` are ``read=1``.
   * - ``deleted``
     - INTEGER (0/1)
     - Soft-delete flag.
   * - ``deleted_ts``
     - REAL
     - Timestamp of deletion.
   * - ``reply_to_id``
     - INTEGER FK
     - Foreign key to ``messages.id`` for threaded replies.
   * - ``reactions``
     - TEXT
     - Legacy column (unused). Reactions are in ``presence.db``.
   * - ``reactions_ts``
     - REAL
     - Updated when a reaction is toggled; triggers polling pickup.
   * - ``mentions``
     - TEXT
     - Reserved for future ``@mention`` tracking.
   * - ``metadata``
     - TEXT
     - Reserved for future structured metadata.
   * - ``client_msg_id``
     - TEXT
     - Client-generated deduplication token.
   * - ``expires_ts``
     - REAL
     - Expiry timestamp for the associated upload file.
