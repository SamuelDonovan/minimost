minimost.presence
=================

.. automodule:: minimost.presence
   :members:
   :undoc-members: False
   :show-inheritance:

Route Summary
-------------

.. list-table::
   :header-rows: 1
   :widths: 15 30 55

   * - Method
     - Path
     - Handler
   * - POST
     - ``/typing/<channel>``
     - :func:`minimost.presence.typing_start`
   * - GET
     - ``/typing/<channel>``
     - :func:`minimost.presence.typing_get`
   * - POST
     - ``/presence``
     - :func:`minimost.presence.presence`

presence.db Schema
------------------

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Table
     - Description
   * - ``presence``
     - ``user`` (PK), ``last_seen`` (INTEGER epoch), ``state`` (TEXT).
       One row per user.
   * - ``typing``
     - ``user`` + ``channel`` (PK), ``ts`` (INTEGER epoch).
       Rows older than 5 s are considered stale.
   * - ``read_receipts``
     - ``channel`` + ``msg_ts`` + ``reader`` (PK).
       Permanent record of who has read which message.
   * - ``message_reactions``
     - ``channel`` + ``msg_ts`` + ``emoji`` + ``reactor`` (PK).
       One row per user-emoji-message combination.
