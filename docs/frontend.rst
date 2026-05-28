Frontend Architecture
=====================

MiniMost's chat interface is a **single-page application (SPA)** implemented
in vanilla JavaScript — no framework, no build step, no bundler.

This page documents the client-side architecture for developers who need to
understand or modify the frontend behaviour.

Page Structure
--------------

The rendered HTML has three main regions:

.. code-block:: text

    ┌──────────────────────────────────────────────────────────────┐
    │  Sidebar (220–260px)        │  Main Content (flex: 1)        │
    │  ─────────────────────────  │  ───────────────────────────── │
    │  Public Channels            │  Topbar                        │
    │  ● general          [3]     │                                │
    │  ● software                 │  Chat Area (scrollable)        │
    │  ● off-topic                │  ── Date divider ──            │
    │                             │  alice  12:34                  │
    │  Private Channels           │  Hello, world!                 │
    │  ● minimost-enjoyers [5]    │                                │
    │  ● software                 │  bob  12:35                    │
    │                             │  👋 Hello!                     │
    │  Direct Messages            │                                │
    │  ● bob              [1]     │                                │
    │  ● charlie                  │  Typing indicator              │
    │                             │  ───────────────────────────── │
    │                             │  [  Type a message...      ]   │
    │                             │  [ 📎 ] [ ▶ Send ]             │
    └──────────────────────────────────────────────────────────────┘
   

Client-side State
-----------------

Key JavaScript variables maintained in the module scope:

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Variable
     - Purpose
   * - ``channel``
     - The currently active channel or DM identifier string.
   * - ``lastTs``
     - Timestamp of the last message received; used as the ``after``
       parameter for incremental polling.
   * - ``unread``
     - ``Set`` of message IDs considered unread in the current view.
   * - ``seen``
     - ``Set`` of message IDs already rendered (deduplication guard).
   * - ``CURRENT_USER``
     - Injected from the Jinja2 template: ``{{ session.user }}``.
   * - ``notifMuted``
     - Boolean loaded from ``localStorage['notifMuted']``; persists across
       page reloads.
   * - ``currentPresence``
     - The state most recently sent to ``/presence``.
   * - ``lastActivity``
     - Timestamp of the last observed keyboard/mouse event (for idle detection).
   * - ``idleSent``
     - Boolean flag — prevents sending repeated ``"idle"`` presence updates.
   * - ``ggTimer``
     - Timer handle used to detect the ``gg`` (jump-to-top) double-keypress
       sequence; cleared after the timeout window expires.
   * - ``userColorOverrides``
     - Object mapping username → hex colour string, populated from
       ``GET /user_colors`` on sidebar load.
   * - ``usersWithAvatars``
     - ``Set`` of usernames that have a custom avatar, populated from
       ``GET /user_avatars`` on sidebar load.
   * - ``presenceMapCache``
     - Most recent result of ``GET /online_users``; used to initialise
       presence dots on newly created avatar elements.

Polling Loops
-------------

The client starts several ``setInterval`` loops after the page loads. Each
loop calls a different API endpoint and updates the DOM based on the response.

.. list-table::
   :header-rows: 1
   :widths: 30 15 55

   * - Function
     - Interval
     - Description
   * - ``fetchMessages()``
     - 500 ms
     - Core polling loop. Calls ``/messages/<channel>?after=<lastTs>``
       and merges new/updated/deleted messages into the chat area.
   * - ``refreshPresence()``
     - 1 s
     - Calls ``/online_users`` and updates presence dots in the sidebar.
   * - ``fetchTyping()``
     - 1 s
     - Calls ``/typing/<channel>`` and shows/hides the typing indicator.
   * - ``refreshDMs()``
     - 1 s
     - Calls ``/dms`` and refreshes the DM list with current unread counts.
   * - ``refreshChannels()``
     - 1 s
     - Calls ``/channel_unreads`` and updates channel unread badges.
   * - ``fetchReadReceipts()``
     - 3 s
     - Calls ``/read_receipts/<channel>`` and updates ``✓`` indicators.
   * - ``refreshTotalUnreadCount()``
     - 5 s
     - Calls ``/unread_count`` and updates the browser tab title.
   * - ``pollIncomingCalls()``
     - 1 s
     - Calls ``/calls/incoming`` and surfaces incoming call notifications
       for both ringing calls and active-call invitations.
   * - ``_pollCallState()``
     - 3 s
     - During an active call: diffs the participant list, detects call end,
       and tracks ``screenshare_user`` changes. Started by ``startCall()``
       and ``acceptCall()``; stopped by ``_cleanupCall()``.
   * - Per-participant audio poll
     - 100 ms
     - One interval per remote participant; polls
       ``/calls/<id>/media?sender=<user>:audio`` and schedules PCM chunks
       on the shared ``AudioContext``.
   * - Screen media poll (``_pollScreenMedia``)
     - 500 ms
     - Polls ``/calls/<id>/media?sender=<screenshare_user>:screen`` and
       feeds chunks into the screen ``MediaSource`` pipeline. Active only
       while ``currentScreenSender`` is set to a remote user.
   * - Presence heartbeat
     - 30 s
     - Re-sends the current presence state to keep ``last_seen`` fresh.
   * - Idle check
     - 5 s
     - Compares ``Date.now() - lastActivity`` to 5 minutes; sends
       ``"idle"`` if exceeded.

Message Rendering
-----------------

``fetchMessages()`` is the heart of the client. On each call it:

1. Calls ``GET /messages/<channel>?after=<lastTs>``.
2. For each returned message:

   - **New message** (``!seen.has(id)``): creates a DOM element and
     appends it to the chat area. Inserts date-divider banners when the
     date changes between messages.
   - **Updated message** (``seen.has(id)``, ``edited`` or ``reactions``
     changed): finds the existing DOM element and patches the content.
   - **Deleted message**: replaces the message content with a
     ``[message deleted]`` tombstone and hides action buttons.

3. Updates ``lastTs`` to the highest ``ts`` value seen.
4. Scrolls to the bottom if the user was already at the bottom before the
   update.
5. Triggers desktop and sound notifications for new messages when the tab
   is hidden.

Message DOM Structure
~~~~~~~~~~~~~~~~~~~~~

Each message is rendered as:

.. code-block:: html

    <div class="msg" data-id="42" data-ts="1716000000.123" data-sender="alice">
      <div class="msg-header">
        <span class="user">alice</span>
        <span class="time">12:34</span>
        <div class="msg-actions">
          <!-- Reply, Edit, Delete buttons (conditionally shown) -->
        </div>
      </div>
      <div class="text">Hello, world!</div>
      <!-- OR for images: -->
      <img class="chat-image" src="/files/uuid.jpg" loading="lazy">
      <!-- Optional: -->
      <div class="reply-quote">...</div>
      <div class="reactions">...</div>
      <div class="link-preview">...</div>
      <div class="read-receipt">✓ Read by alice, bob</div>
    </div>

Text Formatting
---------------

``formatText(text)`` converts a subset of Markdown to HTML:

.. list-table::
   :header-rows: 1
   :widths: 30 20 50

   * - Input
     - Output
     - Notes
   * - ``**text**``
     - ``<strong>text</strong>``
     - Bold
   * - ``*text*``
     - ``<em>text</em>``
     - Italic
   * - ``__text__``
     - ``<u>text</u>``
     - Underline (non-standard Markdown extension)
   * - ``~~text~~``
     - ``<s>text</s>``
     - Strikethrough
   * - ``https://...``
     - ``<a href="...">...</a>``
     - Auto-linked URLs (``http`` and ``https`` only)

All text is HTML-escaped before formatting is applied to prevent XSS.

Keyboard Shortcuts
------------------

See :doc:`keyboard_shortcuts` for the complete reference.

Global keyboard events are handled by ``userInput(e)``. Notable
implementation details:

- ``Ctrl+B/I/U/S`` — format shortcuts wrap the selected text or toggle
  prefix/suffix markers at the cursor position.
- Navigation shortcuts (``j/k/d/u/G/g``) scroll the ``.messages`` container
  by a fixed number of pixels.
- ``Ctrl+J/Ctrl+K`` — cycle through the channel list by finding the current
  channel's index in the sidebar and activating the next/previous sibling.

Reactions
---------

The emoji reaction system uses 477 reactions defined in the ``REACTIONS``
array inside ``chat.html``. Each entry carries a ``name``, ``label``, and
``emoji`` (Unicode character). The ``REACTION_EMOJI`` lookup map (built
from the array) provides O(1) name-to-character access. The workflow:

1. User clicks the ``😊`` button on a message (or hovers to reveal it).
2. ``openReactionPicker(msgId)`` renders a modal grid of all available emoji.
3. User clicks an emoji in the picker; ``pickerReact(name)`` is called.
4. ``toggleReaction(msgId, name)`` POSTs to ``/react/<msgId>``.
5. The server response contains the updated reactions map.
6. ``buildReactionsHtml(msgId, reactions)`` re-renders the reaction chips
   below the message.

Each reaction chip shows the emoji character and a count. Hovering reveals a
tooltip with the list of reactor usernames.

Search
------

The search modal uses two matching strategies:

1. **Server-side search** — ``GET /search_messages?q=<query>`` performs a
   SQLite ``LIKE %query%`` match and returns up to 50 results. This handles
   exact substring matches across the full message history.

2. **Client-side fuzzy search** — ``fuzzySearch(query, text)`` scores
   candidate strings based on how well a fuzzy (out-of-order character)
   match works. Used to rank results and highlight matches in the UI.

Results are displayed with the matched text highlighted using
``highlightFuzzyMatch(text, indices)``, which wraps matched character
positions in ``<mark>`` tags.

The search input is debounced (250 ms) to avoid sending a request on every
keypress.

Presence System
---------------

The client tracks three signals to determine presence state:

1. **Visibility** — ``document.addEventListener("visibilitychange", ...)``
   sends ``"hidden"`` when the tab moves to the background and ``"active"``
   when it returns.

2. **Activity** — mousemove and keydown events reset ``lastActivity``. The
   idle-check interval (5 s) compares ``Date.now() - lastActivity`` to
   5 minutes (300,000 ms); if exceeded, ``"idle"`` is sent and ``idleSent``
   is set to prevent repeated idle notifications.

3. **Heartbeat** — every 30 seconds, the current ``currentPresence`` is
   re-sent to keep ``last_seen`` from expiring in ``presence.db``.

Notifications
-------------

Two notification channels are supported:

- **Desktop notifications** — ``sendDesktopNotification(count)`` requests
  permission on first use (browsers require a user gesture for this) and
  sends a ``Notification`` when ``document.hidden`` is true and there are
  unread messages.

- **Sound notifications** — a short beep is played using the Web Audio API
  when a new message arrives and the user has not muted notifications.
  The mute state is persisted in ``localStorage['notifMuted']``.

The browser tab title is updated by ``updateTitleBadge(count)`` to show
unread count: ``(3) MiniMost``. ``startFaviconFlash()`` alternates the
favicon between the normal icon and a red dot every second while there
are unread messages and the tab is in the background.

File Upload
-----------

Three input methods are supported for image attachments:

1. **File picker** — clicking the ``📎`` button opens a file input.
2. **Drag and drop** — files dragged onto the message input area are
   captured by ``dragover`` and ``drop`` event listeners.
3. **Clipboard paste** — ``paste`` events on the input box check
   ``event.clipboardData.items`` for image data.

Files are accumulated in the ``pendingFiles`` array. ``addFiles(files)``
renders thumbnail previews above the input. On send, files are submitted
as a ``multipart/form-data`` body using ``FormData``.

Link Previews
-------------

After rendering a message containing a URL, ``attachPreview(msgEl)`` is
called asynchronously:

1. Extracts the first URL from the message text.
2. Calls ``GET /link_preview?url=<url>``.
3. If ``type === "og"``, ``_previewOgEl(data)`` renders an OpenGraph card.
4. If ``type === "code"``, ``_previewCodeEl(data)`` renders a code block
   with ``_syntaxHighlight(text, ext)`` applied.

``_syntaxHighlight`` uses regex-based rules for these languages:
``python``, ``js``, ``c``, ``sh``, ``make``, ``cmake``, ``vhdl``,
``verilog``, ``java``, ``go``, ``rust``.

Avatar System
-------------

Every user has a circular avatar shown in three places: the DM sidebar entry,
the private channel hover tooltip, and the channel member list modal.

``makeAvatarWrap(username, size, channelKey)`` creates the DOM structure:

.. code-block:: text

    div.avatar-wrap  (position: relative; width/height set inline)
    ├── div.avatar   (border-radius: 50%; overflow: hidden)
    │   ├── img.avatar-img     (if the user has a custom avatar)
    │   └── div.avatar-initials (fallback — first two letters of username)
    └── span.avatar-presence   (presence dot, position: absolute, bottom-right)

The presence dot carries a ``data-username`` attribute. ``refreshPresence()``
queries ``document.querySelectorAll(".avatar-presence[data-username]")`` once
and updates every dot from the cached presence map in a single pass.

When a user uploads a custom avatar the image is resized **client-side** using
the Canvas API before the upload request is sent:

1. The selected file is drawn into a ``<canvas>`` element.
2. The canvas is centre-cropped to a square and scaled to 128 × 128 px.
3. ``canvas.toBlob("image/jpeg", 0.88)`` produces the compressed image.
4. The blob is sent to ``POST /avatar`` as ``multipart/form-data``.

This means no server-side image library is required — the server stores
whatever JPEG the client sends.

Settings Modal
--------------

The settings cog button (top-right, next to Logout) opens a modal with two
sections:

**Name colour** — a row of colour swatches plus a hex preview chip. Clicking a
swatch immediately updates ``userColorOverrides[CURRENT_USER]`` in memory and
re-renders the current user's name in the sidebar so the change is visible
before saving. The chosen colour is written to ``POST /settings`` on save.

**Avatar** — shows a 64 × 64 preview of the current avatar (initials or
uploaded image). The user can pick a new image file; ``_resizeImage()`` runs
the Canvas resize pipeline and stores the resulting blob in
``_pendingAvatarBlob``. A "Remove" button sets the ``_removeAvatar`` flag.
On save, the pending upload/delete is executed before the colour setting is
saved.

DM Sidebar Close Button
-----------------------

Each DM entry in the sidebar has a ``×`` close button that appears on hover.
Clicking it calls ``closeDm(channelName)``, which posts to ``POST /dms/close``
and removes the entry from the DOM. The conversation is not deleted — it
reappears as soon as a new message arrives in that thread.

Private Channel Leave
---------------------

The private channel controls bar (shown when a private channel is active)
includes a **Leave** button. Clicking it calls ``leaveChannel()``, which posts
to ``POST /private_channels/<id>/leave``. On success the channel is removed
from the sidebar and the client switches to the first available channel. A
system message is written to the channel informing remaining members that the
user has left.

DM Modal
--------

The "New DM" modal provides username autocomplete:

1. User starts typing in the input box.
2. ``fuzzySearch`` filters the ``allUsers`` list (loaded from ``/users``).
3. Suggestions are shown in a dropdown; arrow keys navigate, Enter/Tab
   selects.
4. Multiple users can be entered (comma-separated) for group DMs.
5. On submit, :func:`minimost.chat.normalize_dm` is computed client-side and
   the user is switched to that channel.

Calling
-------

Voice calls (audio only) are initiated from a phone icon displayed in the
topbar when the active channel is a DM or private channel.  Calls support
any number of participants; any member of an active call can invite additional
registered users.

**Caller flow:**

1. The microphone is acquired via ``getUserMedia`` *before* the call is
   created on the server.  This ensures the call is never created and then
   immediately abandoned due to a permission denial or browser timeout.
2. ``startCall()`` posts ``{ channel }`` to ``POST /calls/initiate`` and
   receives a ``call_id``.
3. A call panel appears; ``callingAudio`` (``calling.mp3``) loops while
   waiting for the first participant to answer.
4. A 30-second ``setTimeout`` (``ringTimeoutId``) is armed; if nobody
   answers in time, ``_handleRingTimeout()`` posts ``POST /calls/<id>/end``
   and shows "No answer" before cleaning up.
5. ``_startCallStatePolling()`` polls ``GET /calls/<id>/state`` every 3
   seconds.  When ``state === "active"`` the ring timeout is cleared and
   ``call_accepted.mp3`` plays.

**Callee / invite flow:**

1. ``pollIncomingCalls()`` runs every second, polling
   ``GET /calls/incoming``.  This endpoint returns both fresh ringing calls
   *and* active-call invitations (a pending participant row on an active call).
2. When a call is returned, ``openIncomingCallUI(callData)`` shows an overlay
   with the caller's name and Accept / Decline buttons; ``receiving_call.mp3``
   loops.  The client-side ring timeout is always the full ``RING_TIMEOUT_MS``
   (30 seconds) regardless of how long the call has been ringing on the server,
   so invited users always get the full window.
3. Accepting posts to ``POST /calls/<id>/accept``; declining posts to
   ``POST /calls/<id>/reject``.

**Group call — state polling and participant diffing:**

``_pollCallState()`` is the engine that keeps the call panel in sync with
server state.  On every tick it:

1. Checks the overall call state.  ``"ended"`` or ``"rejected"`` triggers
   ``_cleanupCall()`` and plays ``hang_up.mp3``.
2. Diffs the accepted participant list against ``remoteParticipants`` (a
   ``Map<username, state>``).  New accepted participants get a tile added via
   ``_addRemoteParticipant()``; departed participants are removed via
   ``_removeRemoteParticipant()``, which also plays ``left_call.mp3`` while
   the call is still active.
3. Reads ``screenshare_user`` from the response and triggers screen-receive
   transitions (see below).

**Per-participant audio and voice activity detection:**

Each remote participant has independent polling state:

- A 100 ms ``setInterval`` polls ``GET /calls/<id>/media?sender=<user>:audio``
  and schedules decoded PCM chunks on a shared ``AudioContext`` using the Web
  Audio API for gapless, drift-free playback.
- An ``AnalyserNode`` connected to the participant's audio output drives a
  100 ms VAD interval that toggles the ``speaking`` CSS class on their tile's
  ring element.

**Participant tile grid:**

``_createParticipantTile(username)`` builds a DOM tile containing a speaking
ring (``div.call-speaking-ring`` inside ``div.call-participant-avatar``),
an avatar (``makeAvatarWrap``), and a name label.  The ring uses
``inset: -6px`` on the avatar container so it is always perfectly centred
regardless of tile size.  ``_updateCallGrid()`` sets the CSS grid
``grid-template-columns`` based on the number of remote participants:

- 1 participant: ``1fr`` (centred, full width).
- 2 or more participants: ``1fr 1fr`` (equal columns).

**Inviting participants during a call:**

The "Add person" button in the call controls bar opens a panel with a fuzzy-
search input (backed by ``fuzzySearch`` / ``highlightFuzzyMatch``) that lists
all registered users not already in the call.  Clicking a name posts to
``POST /calls/<id>/invite``, which adds a ``call_participants`` row with
``state = 'pending'``.  The invited user sees the standard incoming-call
notification; the call is already active so they join immediately on accept.

**Leave vs. end:**

Clicking the hang-up button calls ``endCall()``, which posts to
``POST /calls/<id>/end``.  The server marks the participant as ``'left'`` and
only transitions the overall call to ``'ended'`` if no other accepted
participants remain.  Participants still in the call detect the departure on
their next ``_pollCallState`` tick (the departed user's entry changes to
``state: "left"``), remove their tile, and play ``left_call.mp3``.

**Screen sharing flow:**

Screen sharing is available during an active call.  Only one participant may
share at a time; the server tracks the current sharer in the ``screenshare_user``
column of the ``calls`` table.

1. ``toggleScreenShare()`` is invoked directly by the button's ``onclick``
   handler.  ``navigator.mediaDevices.getDisplayMedia()`` is called
   immediately — without any intermediate async calls — so the browser's
   user-gesture activation token is preserved.
2. The resulting stream is passed to ``_startScreenCapture()``, which sets up
   a ``MediaRecorder`` for the screen track.  Chunks are uploaded via
   ``POST /calls/<id>/media`` with ``X-Track: screen``.
3. When the first screen init segment arrives, the server sets
   ``screenshare_user = <sender>``; any existing sharer is atomically
   replaced (takeover).
4. On the receiver side, ``_pollCallState()`` reads ``screenshare_user``.
   When it differs from ``currentScreenSender`` the old ``MediaSource`` /
   ``SourceBuffer`` pipeline is torn down and a new one is started for the
   new sender.  If the local user was sharing, ``_stopScreenCapture()`` is
   called automatically.
5. When ``screenshare_user`` becomes ``null`` (sharer left or stopped),
   ``_stopScreenReceiving()`` removes the ``screen-share-active`` CSS class
   and the participant grid returns to the full-panel layout.
6. If a participant who is screensharing leaves the call,
   ``_removeRemoteParticipant()`` immediately calls ``_stopScreenReceiving()``
   without waiting for the next state poll.

**Sound effects:**

All call audio respects the notification mute toggle.

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - File
     - When played
   * - ``receiving_call.mp3``
     - Loops on the callee side while the incoming-call overlay is visible.
   * - ``calling.mp3``
     - Loops on the caller side while waiting for the first answer.
   * - ``call_accepted.mp3``
     - Played once on the caller side when ``state`` transitions to
       ``"active"``.
   * - ``hang_up.mp3``
     - Played when the local user hangs up, when the call ends for all
       participants (detected via ``_pollCallState``), or when a ring times
       out with no answer.
   * - ``left_call.mp3``
     - Played when a remote participant leaves while the call is still active.

**Key variables:**

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Variable
     - Purpose
   * - ``activeCallId``
     - UUID of the call currently in progress; ``null`` when idle.
   * - ``remoteParticipants``
     - ``Map<username, state>`` holding per-participant polling state
       (audio intervals, VAD analyser, tile DOM element, etc.).
   * - ``sharedAudioCtx``
     - A single ``AudioContext`` shared across all remote participants for
       gapless PCM playback.
   * - ``currentScreenSender``
     - Username of the participant whose ``:screen`` track is currently
       being received; ``null`` when no screen share is active.
   * - ``ringTimeoutId``
     - Handle for the caller-side 30-second ring timeout.
   * - ``incomingRingTimeout``
     - Handle for the callee-side ring timeout (always ``RING_TIMEOUT_MS``).
   * - ``RING_TIMEOUT_MS``
     - Ring timeout in milliseconds (30 000); matches the backend
       ``_RINGING_TIMEOUT`` of 30 s.
   * - ``incomingCallData``
     - The call object currently shown in the incoming-call overlay.
   * - ``localStream``
     - The ``MediaStream`` from ``getUserMedia``; stopped on hang-up.
   * - ``screenStream``
     - The ``MediaStream`` from ``getDisplayMedia``; ``null`` when not sharing.
   * - ``screenRecorder``
     - The ``MediaRecorder`` instance for the screen track.
   * - ``screenEnabled``
     - ``true`` while the local user is screensharing.
   * - ``screenPollId``
     - Handle for the screen-relay download poll interval.

Mobile Support
--------------

The sidebar is hidden by default on narrow screens and revealed by a
hamburger menu button. The ``touch-action: manipulation`` CSS property
disables double-tap zoom on buttons for a more app-like feel. Pinch-to-zoom
adjusts the message font size, and this preference is saved in
``localStorage['fontSize']``.
