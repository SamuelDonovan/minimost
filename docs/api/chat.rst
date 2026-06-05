minimost.chat
=============

.. automodule:: minimost.chat
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
     - ``/``
     - :func:`minimost.chat.index`
   * - GET
     - ``/channels``
     - :func:`minimost.chat.channels`
   * - GET
     - ``/channel_unreads``
     - :func:`minimost.chat.channel_unreads`
   * - GET
     - ``/messages/<channel>``
     - :func:`minimost.chat.messages`
   * - POST
     - ``/send/<channel>``
     - :func:`minimost.chat.send`
   * - GET
     - ``/message/<msg_id>``
     - :func:`minimost.chat.get_message`
   * - POST
     - ``/edit/<msg_id>``
     - :func:`minimost.chat.edit`
   * - POST
     - ``/delete/<msg_id>``
     - :func:`minimost.chat.delete_message`
   * - POST
     - ``/react/<msg_id>``
     - :func:`minimost.chat.react`
   * - POST
     - ``/mark_read/<channel>``
     - :func:`minimost.chat.mark_read`
   * - GET
     - ``/read_receipts/<channel>``
     - :func:`minimost.chat.read_receipts`
   * - GET
     - ``/dms``
     - :func:`minimost.chat.dms`
   * - GET
     - ``/unread_count``
     - :func:`minimost.chat.unread_count`
   * - GET
     - ``/online_users``
     - :func:`minimost.chat.online_users`
   * - GET
     - ``/users``
     - :func:`minimost.chat.users`
   * - GET
     - ``/channel_members/<channel>``
     - :func:`minimost.chat.channel_members`
   * - GET
     - ``/search_messages``
     - :func:`minimost.chat.search_messages`
   * - GET
     - ``/files/<filename>``
     - :func:`minimost.chat.files`
   * - GET
     - ``/link_preview``
     - :func:`minimost.chat.link_preview`
