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
      brute-force attacks.  Repeated failures additionally trigger **account
      lockout**: after ``max_login_attempts`` consecutive failures an account is
      locked for ``lockout_duration_minutes`` (both configurable in
      ``settings.json``).

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
       The reserved names ``minimost``, ``everyone``, and ``deleteduser`` are
       rejected (case-insensitively).
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

Event Stream
------------

.. http:get:: /events

   Open the live update stream. A single long-lived `Server-Sent Events
   <https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events>`_
   connection per tab replaces the former interval pollers: the server holds the
   request open and pushes a named event whenever the relevant shared state
   changes. See :doc:`architecture` for the write-gating and recycle design.

   **Requires authentication.**

   :query channel: The tab's currently-open channel; scopes the ``messages``,
       ``typing``, ``read_receipts`` and ``screenshares`` events. The client
       reconnects with a new value when the user switches channels.
   :query float after: Last-seen message timestamp; the stream sends only newer
       rows. On reconnect the browser's ``Last-Event-ID`` resumes the cursor.
   :resheader Content-Type: ``text/event-stream``

   **Named events emitted** — each carries the same JSON its matching REST
   endpoint returns: ``messages``, ``typing``, ``read_receipts``,
   ``online_users``, ``dms``, ``channel_unreads``, ``private_channels``,
   ``mentions``, ``unread_count``, ``incoming_calls``, and ``screenshares``.

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
        - Database primary key (shared message store).
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
        - ID of the parent message (shared message store).
      * - ``reactions``
        - string (JSON) or null
        - JSON-encoded object mapping emoji names to lists of reactor
          usernames, e.g. ``"{\"thumbs_up\": [\"alice\", \"bob\"]}"``
      * - ``reactions_ts``
        - float or null
        - Timestamp of the most recent reaction change.
      * - ``mentions``
        - string (JSON) or null
        - JSON-encoded array of the channel members ``@``-mentioned in the
          message, e.g. ``"[\"alice\"]"``. The sentinel ``"@everyone"`` marks
          a channel-wide mention. ``null`` when the message mentions no one.
          The client highlights the message and notifies the viewer when their
          username (or ``@everyone``) appears here.

.. http:post:: /send/(channel)

   Send a message and/or image attachment(s) to a channel.

   **Requires authentication.**

   Any ``@username`` tokens in *text* that resolve to real channel members are
   extracted (case-insensitively) and stored in the message's ``mentions``
   column; ``@everyone`` is stored as the sentinel ``"@everyone"``. Tokens
   inside emails (``foo@bar``) and URLs are ignored.

   :param channel: Target channel or DM identifier.
   :form text: Message text body (optional if files are provided).
   :form reply_to_id: Integer ID of the parent message (optional).
   :form files: One or more files of any type (multipart). Images (``.jpg``,
       ``.jpeg``, ``.png``, ``.gif``, ``.webp``) are shown inline; all other
       types are served as downloads with the original filename preserved.
   :status 200: Returns the string ``"ok"``.
   :status 400: Empty message (no text and no files).
   :status 403: User is not permitted to post to the channel.
   :status 413: A file exceeds ``max_upload_size_mb`` or the message text
       exceeds the maximum length.

.. http:get:: /message/(msg_id)

   Fetch a single message by ID.

   **Requires authentication.**

   :param int msg_id: Message primary key.
   :>json integer id: Message ID.
   :>json string sender: Author's username.
   :>json string content: Message text.
   :>json string filename: Image filename or null.
   :>json integer deleted: Soft-delete flag.
   :status 404: Message not found.

.. http:post:: /edit/(msg_id)

   Edit the text content of a message.

   **Requires authentication.** Only the original sender can edit.

   :param int msg_id: Message ID.
   :form text: Replacement message text. Mentions are re-extracted from the new
       text and the ``mentions`` column is updated accordingly.
   :status 200: Returns ``"ok"``.
   :status 403: Not the sender, or message not found.

.. http:post:: /delete/(msg_id)

   Soft-delete a message.

   **Requires authentication.** Only the original sender can delete.

   :param int msg_id: Message ID.
   :status 200: Returns ``"ok"``.
   :status 403: Not the sender, or message not found.

.. http:get:: /search_messages

   Search message history. The keyword is a case-insensitive **substring**
   match served by the trigram full-text index, so it stays fast regardless of
   history size. Results are confined to channels the caller may read (public
   channels, private channels they belong to, and their own DMs). At least one
   filter must be supplied; with none, an empty array is returned.

   **Requires authentication.**

   :query string q: Search term (substring match).
   :query string from: Restrict to a sender (case-insensitive).
   :query string channel: Restrict to a single channel the caller can access.
   :query float start: Only messages at or after this Unix timestamp.
   :query float end: Only messages before this Unix timestamp.
   :>json array: Up to 50 matching message objects (fields: ``id``,
       ``channel``, ``sender``, ``content``, ``ts``), newest first.

Reactions
---------

.. http:post:: /react/(msg_id)

   Toggle an emoji reaction on a message.

   **Requires authentication.**

   :param int msg_id: Message ID.
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

.. http:get:: /channel_members/(channel)

   Return the members of a channel that the current user may ``@``-mention,
   excluding the current user. For public channels this is every other
   registered user; for private channels the other members; for DMs the other
   participants. Used to populate the ``@``-mention autocomplete dropdown.

   **Requires authentication.**

   :param channel: Channel name, DM identifier, or ``private:<id>``.
   :>json array: List of mentionable username strings.
   :status 403: User is not permitted to access the channel.

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
   :status 200: Returns ``"ok"``; conversation hidden.
   :status 400: Missing or invalid channel.
   :status 403: Caller is not a participant in the DM.

.. http:get:: /unread_count

   Return the total number of unread DMs.

   **Requires authentication.**

   :>json integer count: Total unread DM message count.

Read Receipts
-------------

.. http:post:: /mark_read/(channel)

   Mark a channel as read by advancing the caller's read watermark to its
   newest message.

   **Requires authentication.**

   :param channel: Channel or DM identifier.
   :status 204: Watermark advanced.

.. http:get:: /read_receipts/(channel)

   Return each member's read watermark for a channel. A user has read a message
   iff their watermark is ``>=`` that message's ``ts``; the client derives the
   per-message ``✓`` indicators from the message timestamps it already holds.
   This keeps the payload proportional to the number of members, not the
   channel's history length.

   **Requires authentication.**

   :param channel: Channel or DM identifier.
   :>json object: Mapping of each reader's username to their read watermark
       (epoch seconds).

   **Example response:**

   .. code-block:: json

      {
          "alice": 1716000001.456,
          "bob": 1716000000.123
      }

User Settings
-------------

.. http:get:: /settings

   Return the current user's settings.

   **Requires authentication.**

   :>json string name_color: CSS hex colour string, or ``null`` if not set.
   :>json string bio: Profile bio text, or ``null`` if not set.

.. http:post:: /settings

   Update the current user's settings.

   **Requires authentication.** Accepts a JSON body.

   :<json string name_color: CSS hex colour in ``#rrggbb`` format (optional).
       Pass ``null`` to reset to the default hash-derived colour.
   :<json string bio: Profile bio text (optional); trimmed to 160 characters.
   :status 200: Returns ``"ok"``.
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

   :form avatar: Image file (``multipart/form-data``). Stored as-is as a
       ``.jpg`` (the client pre-resizes to 128 × 128 px).
   :status 200: Returns ``"ok"``; avatar saved.
   :status 400: No file provided.
   :status 413: File exceeds ``max_avatar_size_mb``.

.. http:delete:: /avatar

   Delete the current user's avatar. The default initials avatar is shown
   to other users after removal.

   **Requires authentication.**

   :status 200: Returns ``"ok"``; avatar removed.

Private Channels
----------------

.. http:post:: /private_channels/(channel_id)/leave

   Leave a private channel.

   **Requires authentication.**

   A system message is posted to the channel notifying remaining members.
   If the leaving user is the last member, the channel is not automatically
   deleted — it becomes an empty room.

   :param int channel_id: Numeric private-channel id (the ``<id>`` in the
       ``private:<id>`` channel identifier).
   :status 200: Returns ``"ok"``; user removed from channel.
   :status 403: User is not a member of the channel.

Files
-----

.. http:get:: /files/(filename)

   Serve an uploaded file. Images are served inline; all other file types are
   served as attachments (download) with the original filename restored.

   **Requires authentication.**

   :param filename: UUID-based stored filename (as stored in the database).
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
