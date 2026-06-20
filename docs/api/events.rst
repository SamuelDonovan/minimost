minimost.events
===============

.. automodule:: minimost.events
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
   * - GET
     - ``/events?channel=<ch>&after=<ts>``
     - :func:`minimost.events.events`

The single ``text/event-stream`` response carries these named events, each the
push-mode equivalent of a former polling endpoint: ``messages``, ``typing``,
``read_receipts``, ``online_users``, ``dms``, ``channel_unreads``,
``private_channels``, ``mentions``, ``unread_count``, ``incoming_calls`` and
``screenshares``. See :doc:`/architecture` for the delivery model and the
``gthread`` worker requirement.
