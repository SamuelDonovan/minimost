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
   * - GET / POST
     - ``/presence/override``
     - :func:`minimost.presence.presence_override_get` /
       :func:`minimost.presence.presence_override`

presence.db Schema
------------------

.. list-table::
   :header-rows: 1
   :widths: 28 72

   * - Table
     - Description
   * - ``presence``
     - ``user`` (PK), ``last_seen`` (INTEGER epoch), ``state`` (TEXT), and
       ``override`` (TEXT, the manual "appear online/away/offline" choice or
       ``NULL`` for automatic). One row per user.
   * - ``typing``
     - ``user`` + ``channel`` (PK), ``ts`` (INTEGER epoch).
       Rows older than 5 s are considered stale.
   * - ``private_channels``
     - ``id`` (PK), ``name``, ``created_by``, ``created_ts``. One row per
       private channel; ``id`` forms the ``private:<id>`` identifier.
   * - ``private_channel_members``
     - ``channel_id`` + ``username`` (PK), ``joined_ts``, ``history_start_ts``
       (the timestamp a late joiner sees history from, or ``NULL``).
   * - ``calls`` / ``call_participants`` / ``call_signals``
     - Call lifecycle, per-participant state, and the WebRTC signalling relay
       (offer/answer/ICE), respectively. See :doc:`/architecture`.
   * - ``screenshares``
     - Standalone screen-share lifecycle (``share_id``, ``channel``, ``sharer``,
       ``state``, timestamps).
   * - ``event_signal``
     - Single-row monotonic counter bumped on every state-changing write; the
       ``GET /events`` SSE stream watches it to decide when to push.
   * - ``read_receipts`` / ``message_reactions``
     - **Legacy, unused.** Still created for backward compatibility, but read
       state and reactions now live in ``users/messages.db`` (``read_state`` and
       ``reactions`` respectively).
