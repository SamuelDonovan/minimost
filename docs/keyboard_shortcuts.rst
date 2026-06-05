Keyboard Shortcuts
==================

MiniMost provides Vim-inspired keyboard navigation so you can control the
interface without reaching for the mouse. Shortcuts are active whenever the
message input box is **not** focused, unless noted otherwise.

Messaging
---------

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Key
     - Action
   * - ``Enter``
     - Send the composed message.
   * - ``Shift + Enter``
     - Insert a newline (multi-line message).
   * - ``Esc``
     - Unfocus the message input box; close any open modal or cancel
       an in-progress reply or edit. Also closes the ``@``-mention dropdown.
   * - ``@``
     - Open the mention autocomplete dropdown for the channel's members. While
       it is open, ``↑``/``↓`` navigate, ``Enter`` or ``Tab`` accept the
       highlighted name, and ``Esc`` closes it. Type ``@everyone`` to mention
       the whole channel.
   * - ``i``
     - Focus the message input box (works from anywhere).

Navigation
----------

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Key
     - Action
   * - ``j``
     - Scroll the chat area down 200 px.
   * - ``k``
     - Scroll the chat area up 200 px.
   * - ``d``
     - Scroll the chat area down 400 px (double-speed).
   * - ``u``
     - Scroll the chat area up 400 px (double-speed).
   * - ``G``
     - Jump to the bottom of the chat (most recent messages).
   * - ``gg``
     - Jump to the top of the chat (oldest messages). Press ``g`` twice
       within 500 ms.
   * - ``Ctrl + J``
     - Switch to the next channel in the sidebar (wraps around).
   * - ``Ctrl + K``
     - Switch to the previous channel in the sidebar (wraps around).

Search and DMs
--------------

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Key
     - Action
   * - ``/`` or ``f``
     - Open the search modal and focus the search input.
   * - ``o``
     - Open the "New DM" modal.

Text Formatting
---------------

These shortcuts work inside the message input box. They wrap the currently
selected text in the appropriate markers, or toggle the marker at the cursor
position if no text is selected.

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Key
     - Action
   * - ``Ctrl + B``
     - **Bold** — wraps selection in ``**...**``
   * - ``Ctrl + I``
     - *Italic* — wraps selection in ``*...*``
   * - ``Ctrl + U``
     - Underline — wraps selection in ``__...__``
   * - ``Ctrl + S``
     - ~~Strikethrough~~ — wraps selection in ``~~...~~``

All formatting uses the same Markdown-style syntax rendered by
``formatText()`` in the client.

Help
----

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Key
     - Action
   * - ``?``
     - Open the help overlay (shows a quick-reference shortcut list).

Visual Mode
-----------

Press ``v`` in normal mode (message input not focused) to enter **visual
mode**. The topbar displays ``-- visual --`` while active. In visual mode,
one message is highlighted and the following keys act on it directly.

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Key
     - Action
   * - ``v``
     - Enter visual mode; the most recent message is selected.
   * - ``j`` / ``↓``
     - Move the selection to the next (newer) message.
   * - ``k`` / ``↑``
     - Move the selection to the previous (older) message.
   * - ``d``
     - Delete the highlighted message.
   * - ``c``
     - Edit the highlighted message inline.
   * - ``o``
     - Reply to the highlighted message.
   * - ``y``
     - Copy the highlighted message text to the clipboard.
   * - ``e``
     - Open the emoji reaction picker for the highlighted message.
   * - ``Esc``
     - Exit visual mode without taking any action.

Tips
----

- Keyboard shortcuts are disabled when a modal is open or when the message
  input has focus (except ``Esc``, ``Enter``, and ``Shift+Enter``).
- ``Ctrl+J`` and ``Ctrl+K`` cycle through both public channels and DM
  conversations in sidebar order.
- The ``gg`` chord has a 500 ms window — type both ``g`` presses quickly.
- Font size can be adjusted with ``Ctrl + mouse scroll`` (desktop) or pinch
  gesture (mobile). The preference is saved in browser ``localStorage``.
