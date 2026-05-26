HTTP API Reference
==================

All API endpoints require an authenticated session unless noted otherwise.
Authentication is performed by the ``/login`` route, which sets a signed
session cookie. Subsequent requests include this cookie automatically.

All JSON responses use ``Content-Type: application/json``.

Authentication
--------------

.. http:get:: /login

   Render the login page.

   :resheader Content-Type: text/html

.. http:post:: /login

   Authenticate a user and establish a session.

   :form username: Account username.
   :form password: Account password.
   :status 302: Redirect to ``/`` on success.
   :status 200: Re-render login page with error message on failure.
   :resheader Set-Cookie: ``session=<signed_value>`` on success.

   .. note::

      Failed login attempts are deliberately delayed by 3 seconds to slow
      brute-force attacks.

.. http:get:: /logout

   Log out the current user, set presence to offline, and clear the session.

   **Requires authentication.**

   :status 302: Redirect to ``/login``.

.. http:get:: /signup

   Render the registration page.

   :resheader Content-Type: text/html

.. http:post:: /signup

   Register a new account.

   :form username: 1–32 characters; letters, numbers, hyphens, underscores.
   :form password: Minimum 8 characters; must include uppercase, digit, and
       special character.
   :form confirm_password: Must match ``password``.
   :status 302: Redirect to ``/`` on success.
   :status 200: Re-render signup page with error on validation failure.

Chat Interface
--------------

.. http:get:: /

   Serve the main chat SPA.

   **Requires authentication.**

   :resheader Content-Type: text/html

Channels
--------

.. http:get:: /channels

   Return the list of public channel names.

   **Requires authentication.**

   :>json array channels: Ordered list of channel name strings.

   **Example response:**

   .. code-block:: json

      ["general", "software", "firmware", "off-topic"]

.. http:get:: /channel_unreads

   Return unread message counts for every public channel.

   **Requires authentication.**

   :>json object: Mapping of channel name to unread count.

   **Example response:**

   .. code-block:: json

      {"general": 3, "software": 0, "off-topic": 1}

Messages
--------

.. http:get:: /messages/(channel)

   Fetch messages for a channel since a given timestamp.

   **Requires authentication.**

   :param channel: Public channel name or DM identifier (e.g. ``dm:alice:bob``).
   :query float after: Only return messages modified after this Unix timestamp.
       Defaults to ``0`` (return all messages). Pass ``NaN`` to also trigger
       a full load.
   :>json array: Array of message objects.

   **Message object fields:**

   .. list-table::
      :header-rows: 1
      :widths: 20 15 65

      * - Field
        - Type
        - Description
      * - ``id``
        - integer
        - Database primary key (in the current user's database).
      * - ``channel``
        - string
        - Channel or DM identifier.
      * - ``sender``
        - string
        - Username of the author.
      * - ``content``
        - string or null
        - Message text body. ``null`` for image-only messages.
      * - ``filename``
        - string or null
        - UUID-named image filename, served from ``/files/<filename>``.
      * - ``ts``
        - float
        - Unix timestamp (seconds).
      * - ``edited``
        - integer (0/1)
        - Whether the message has been edited.
      * - ``edited_ts``
        - float or null
        - Timestamp of the most recent edit.
      * - ``deleted``
        - integer (0/1)
        - Soft-delete flag.
      * - ``deleted_ts``
        - float or null
        - Timestamp of deletion.
      * - ``reply_to_id``
        - integer or null
        - ID of the parent message (in the same user's database).
      * - ``reactions``
        - string (JSON) or null
        - JSON-encoded object mapping emoji names to lists of reactor
          usernames, e.g. ``"{\"thumbs_up\": [\"alice\", \"bob\"]}"``
      * - ``reactions_ts``
        - float or null
        - Timestamp of the most recent reaction change.

.. http:post:: /send/(channel)

   Send a message and/or image attachment(s) to a channel.

   **Requires authentication.**

   :param channel: Target channel or DM identifier.
   :form text: Message text body (optional if files are provided).
   :form reply_to_id: Integer ID of the parent message (optional).
   :form files: One or more image files (multipart). Accepted extensions:
       ``.jpg``, ``.jpeg``, ``.png``, ``.gif``, ``.webp``.
   :status 200: Returns the string ``"ok"``.
   :status 400: Empty message (no text and no valid files).
   :status 403: User is not permitted to post to the channel.

.. http:get:: /message/(msg_id)

   Fetch a single message by ID.

   **Requires authentication.**

   :param int msg_id: Message primary key in the current user's database.
   :>json integer id: Message ID.
   :>json string sender: Author's username.
   :>json string content: Message text.
   :>json string filename: Image filename or null.
   :>json integer deleted: Soft-delete flag.
   :status 404: Message not found.

.. http:post:: /edit/(msg_id)

   Edit the text content of a message.

   **Requires authentication.** Only the original sender can edit.

   :param int msg_id: Message ID in the current user's database.
   :form text: Replacement message text.
   :status 200: Returns ``"ok"``.
   :status 403: Not the sender, or message not found.

.. http:post:: /delete/(msg_id)

   Soft-delete a message.

   **Requires authentication.** Only the original sender can delete.

   :param int msg_id: Message ID in the current user's database.
   :status 200: Returns ``"ok"``.
   :status 403: Not the sender, or message not found.

.. http:get:: /search_messages

   Search message history by keyword.

   **Requires authentication.**

   :query string q: Search term (substring match).
   :>json array: Up to 50 matching message objects (fields: ``id``,
       ``channel``, ``sender``, ``content``, ``ts``), newest first.

Reactions
---------

.. http:post:: /react/(msg_id)

   Toggle an emoji reaction on a message.

   **Requires authentication.**

   :param int msg_id: Message ID in the current user's database.
   :form reaction: Emoji name (e.g. ``thumbsup``, ``heart``). Must be a
       valid reaction name from the ``VALID_REACTIONS`` set.
   :>json object: Current reactions map after the toggle, e.g.
       ``{"thumbs_up": ["alice", "bob"]}``
   :status 400: Invalid reaction name.
   :status 404: Message not found.

Users and Presence
------------------

.. http:get:: /users

   Return all registered users except the current user.

   **Requires authentication.**

   :>json array: List of username strings.

.. http:get:: /user_colors

   Return the display name colour for every user that has set one.

   **Requires authentication.**

   :>json object: Mapping of username to CSS hex colour string.

   **Example response:**

   .. code-block:: json

      {"alice": "#e06c75", "bob": "#61afef"}

.. http:get:: /user_avatars

   Return the set of usernames that have a custom avatar.

   **Requires authentication.**

   :>json array: List of username strings that have uploaded an avatar.

.. http:get:: /online_users

   Return presence states for recently active users.

   **Requires authentication.**

   :>json object: Mapping of username to presence state string
       (``"active"``, ``"idle"``, ``"hidden"``, ``"offline"``).

   **Example response:**

   .. code-block:: json

      {"alice": "active", "bob": "idle", "charlie": "offline"}

.. http:post:: /presence

   Update the current user's presence state.

   **Requires authentication.**

   :<json string state: One of ``"active"``, ``"idle"``, ``"hidden"``,
       ``"offline"``.
   :status 204: State updated.

.. http:get:: /typing/(channel)

   Return users currently typing in a channel.

   **Requires authentication.**

   :param channel: Channel or DM identifier.
   :>json array: List of username strings. Excludes the current user.

.. http:post:: /typing/(channel)

   Report that the current user is typing.

   Session is checked silently (not ``@login_required``).

   :param channel: Channel or DM identifier.
   :status 204: Recorded.

Direct Messages
---------------

.. http:get:: /dms

   Return a summary of all visible DM conversations.

   **Requires authentication.**

   Hidden conversations (closed by the user) are excluded unless a new
   message has arrived after the conversation was hidden.

   :>json array: List of conversation objects, sorted by most recent
       activity. Each object has:

       - ``channel`` (string): DM channel identifier.
       - ``users`` (array): Other participant usernames.
       - ``unread`` (integer): Unread message count.

.. http:post:: /dms/close

   Hide a DM conversation from the sidebar.

   **Requires authentication.**

   The conversation is not deleted. It reappears automatically when a new
   message is received after the hidden timestamp.

   :<json string channel: DM channel identifier to hide.
   :status 204: Conversation hidden.
   :status 400: Missing or invalid channel.

.. http:get:: /unread_count

   Return the total number of unread DMs.

   **Requires authentication.**

   :>json integer count: Total unread DM message count.

Read Receipts
-------------

.. http:post:: /mark_read/(channel)

   Mark all messages in a channel as read.

   **Requires authentication.**

   :param channel: Channel or DM identifier.
   :status 204: Messages marked as read.

.. http:get:: /read_receipts/(channel)

   Return read receipts for all messages in a channel.

   **Requires authentication.**

   :param channel: Channel or DM identifier.
   :>json object: Mapping of message timestamp strings to lists of reader
       usernames.

   **Example response:**

   .. code-block:: json

      {
          "1716000000.123": ["alice", "bob"],
          "1716000001.456": ["alice"]
      }

User Settings
-------------

.. http:get:: /settings

   Return the current user's settings.

   **Requires authentication.**

   :>json string name_color: CSS hex colour string, or ``null`` if not set.
   :>json string avatar_file: Avatar filename, or ``null`` if not set.

.. http:post:: /settings

   Update the current user's settings.

   **Requires authentication.**

   :form name_color: CSS hex colour in ``#rrggbb`` format (optional). Pass an
       empty string to clear the colour.
   :status 204: Settings saved.
   :status 400: Invalid colour format.

Avatars
-------

.. http:get:: /avatar/(username)

   Serve a user's profile avatar image.

   **Requires authentication.**

   :param username: Account username.
   :resheader Content-Type: ``image/jpeg``
   :status 404: User has no avatar.

.. http:post:: /avatar

   Upload or replace the current user's avatar.

   **Requires authentication.**

   The image should be pre-resized to 128 × 128 px by the client before
   upload (the frontend uses the Canvas API for this). The server stores the
   file as-is.

   :form avatar: Image file (``multipart/form-data``). Accepted extensions:
       ``.jpg``, ``.jpeg``, ``.png``, ``.gif``, ``.webp``.
   :status 204: Avatar saved.
   :status 400: No file provided or invalid file type.

.. http:delete:: /avatar

   Delete the current user's avatar. The default initials avatar is shown
   to other users after removal.

   **Requires authentication.**

   :status 204: Avatar removed.

Private Channels
----------------

.. http:post:: /private_channels/(channel_id)/leave

   Leave a private channel.

   **Requires authentication.**

   A system message is posted to the channel notifying remaining members.
   If the leaving user is the last member, the channel is not automatically
   deleted — it becomes an empty room.

   :param channel_id: Private channel identifier (``private:<name>`` form).
   :status 204: User removed from channel.
   :status 403: User is not a member of the channel.
   :status 404: Channel not found.

Files
-----

.. http:get:: /files/(filename)

   Serve an uploaded image file.

   **Requires authentication.**

   :param filename: UUID-based image filename (as stored in the database).
   :resheader Content-Type: Inferred from the file extension.
   :status 404: File not found.

Link Previews
-------------

.. http:get:: /link_preview

   Fetch a link preview card for a URL.

   **Requires authentication.**

   :query string url: Fully-qualified URL to preview.
   :>json object: Preview data. Shape depends on the type:

   **Code preview (Bitbucket):**

   .. code-block:: json

      {
          "type": "code",
          "filename": "chat.py",
          "filepath": "src/minimost/chat.py",
          "language": "py",
          "first_line_num": 1,
          "highlight_start": 50,
          "highlight_end": 60,
          "code": "...",
          "total_lines": 616,
          "url": "https://bitbucket.org/..."
      }

   **OpenGraph preview:**

   .. code-block:: json

      {
          "type": "og",
          "title": "Page Title",
          "description": "Page description...",
          "image": "https://example.com/image.png",
          "domain": "example.com",
          "url": "https://example.com/page"
      }

   **No preview available:**

   .. code-block:: json

      {}
