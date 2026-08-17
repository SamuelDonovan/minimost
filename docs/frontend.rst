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

Event Stream (chat-events.js)
-----------------------------

Live updates arrive over a single ``EventSource`` connection opened by
``connectEvents()`` (``chat-events.js``) instead of a fleet of ``setInterval``
loops. Each named SSE event carries the same JSON a former poller fetched and is
handed to the same render function, now split out of its old fetcher so both the
one-shot REST load and the push path share it:

.. list-table::
   :header-rows: 1
   :widths: 28 28 44

   * - SSE event
     - Render function
     - Replaces poller
   * - ``messages``
     - ``applyMessages(data, ch)``
     - ``fetchMessages`` (500 ms)
   * - ``typing`` / ``read_receipts``
     - ``applyTyping`` / ``applyReadReceipts``
     - ``fetchTyping`` / ``fetchReadReceipts``
   * - ``online_users`` / ``dms``
     - ``applyOnlineUsers`` / ``applyDMs``
     - ``refreshPresence`` / ``refreshDMs``
   * - ``channel_unreads`` / ``private_channels``
     - ``applyChannelUnreads`` / ``applyPrivateChannels``
     - ``refreshChannels`` / ``refreshPrivateChannels``
   * - ``mentions`` / ``unread_count``
     - ``applyMentions`` / ``applyUnreadCount``
     - ``fetchMentions`` / ``refreshTotalUnreadCount``
   * - ``incoming_calls`` / ``screenshares``
     - ``applyIncomingCalls`` / ``applyScreenShares``
     - ``pollIncomingCalls`` / ``refreshScreenShares``

The fetchers (``fetchMessages``, ``refreshDMs``, …) still exist for one-shot
loads — initial sidebar build and the instant backlog paint on a channel switch
— but are no longer driven on an interval. ``switchChannel`` reconnects the
stream (``fetchMessages().then(connectEvents)``) so the message cursor and
channel scope follow the user.

Loops that remain on ``setInterval`` (all unrelated to the SSE stream):

.. list-table::
   :header-rows: 1
   :widths: 30 15 55

   * - Function
     - Interval
     - Description
   * - ``_pollCallState()``
     - 3 s
     - During an active call only: diffs the participant list
       (opening/closing ``RTCPeerConnection`` s), tracks who is still ringing,
       detects call end, and reconciles the ``screensharers`` list against the
       video tracks actually being received. Started by ``startCall()`` /
       ``acceptCall()``; stopped by ``_cleanupCall()``.
   * - WebRTC signalling poll (``_pollCallSignals``)
     - 600 ms
     - During an active call only: drains ``/calls/<id>/signals`` and
       dispatches each offer/answer/ICE candidate to the matching peer
       connection (perfect negotiation). Standalone screen shares poll
       ``/screenshare/<id>/signals`` the same way. Call and screen **media**
       travels peer-to-peer and is never polled.
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
   is hidden, and for ``@mentions`` of the current user even when the tab is
   focused (see :ref:`mentions`).

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
   * - ``@username``
     - ``<span class="mention">@username</span>``
     - Mention pill, rendered only for known users and ``@everyone`` (see
       :ref:`mentions`). Applied after link auto-linking so URLs containing
       ``@`` are left untouched.

All text is HTML-escaped before formatting is applied to prevent XSS.

Keyboard Shortcuts
------------------

See :doc:`keyboard_shortcuts` for the complete reference.

Global keyboard events are handled by ``userInput(e)``. Notable
implementation details:

- ``Ctrl+B/I/U/S`` — format shortcuts wrap the selected text or toggle
  prefix/suffix markers at the cursor position.
- Navigation shortcuts (``j/k/d/u``) scroll the ``.messages`` container by a
  fixed number of pixels; ``G`` jumps to the bottom.
- ``gg`` is a real chord: the first ``g`` arms a 500 ms timer and the second
  jumps to the top. Any other key in between abandons it, so a stray ``g``
  while reading scrollback no longer throws you to the oldest message.
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

Pinned Messages
---------------

Pinning lives in ``chat-pins.js``. A pin belongs to the **channel**, not to the
user who set it, so the server is the only source of truth here and the module
never mutates its list locally. Every path — pinning, unpinning, or someone else
doing either — ends with the whole list arriving from the server and
``applyPins()`` repainting from it:

1. The pin button in a message's hover actions (or ``p`` in visual mode) calls
   ``togglePin(msgId)``, which POSTs to ``/pin/<msgId>``.
2. The response is the channel's full post-toggle list. Every other viewer gets
   the same payload as the ``pins`` SSE event, so nobody has to poll.
3. ``applyPins(data, forChannel)`` stores it as ``pinnedMessages`` plus a
   ``pinsById`` Map, and drops any payload whose channel is no longer the open
   one — the guard that keeps an in-flight response from a channel the user has
   left off the screen.

Three surfaces render from that one payload:

- **The topbar button** (``#pins-btn``) carries a count and is hidden entirely
  at zero, since a control that can only report emptiness is noise.
- **The dropdown panel** (``#pins-panel``) lists each pin, newest-pinned first;
  clicking a row calls the shared ``revealMessage()`` — the same jump search
  results and mentions use — and each row carries an ``×`` to unpin without
  hunting for the message first.
- **The transcript itself**, via ``paintPinMarkers()``, which toggles the
  ``pinned`` class and inserts a ``Pinned by <user>`` caption into
  ``.msg-content-col``. The caption goes there rather than in the message header
  because a grouped message's header is positioned out to the top-right corner,
  and it is a caption rather than a left border because that slot is already
  taken by ``mentioned`` and ``visual-selected`` — a message can be any
  combination of the three.

``_buildMsgHtml()`` has no view of the pin list, so it emits every message with a
blank pin button; the render passes (``applyMessages`` on append,
``prependMessages`` on a history page) hand their new nodes to
``paintPinMarkers()`` afterwards. They pass only the nodes they touched — a full
repaint on every incoming message would walk the whole loaded window to compute a
result that cannot have changed for rows nothing rewrote.

``refreshPins()`` does the first paint on each channel switch and clears the
outgoing channel's pins immediately, so a stale count never lingers while the
request is in flight. The server caps a channel at ``MAX_PINS_PER_CHANNEL`` (50)
and truncates each preview to ``PIN_PREVIEW_CHARS`` (300), which bounds a payload
that is re-pushed to every open stream on the channel whenever it changes.

.. _mentions:

Mentions
--------

The ``@``-mention system lives in ``chat-mentions.js`` and has three parts.

**Autocomplete dropdown.** Typing ``@`` in the composer opens a fuzzy-search
dropdown of the current channel's members:

1. ``activeMentionToken()`` inspects the text before the caret and returns the
   ``@token`` being typed (start offset and partial query), or ``null``.
2. ``ensureMentionMembers()`` lazily fetches ``GET /channel_members/<channel>``
   and caches the result per channel. The reserved keyword ``everyone`` is
   always offered alongside the real members.
3. ``refreshMentions()`` ranks candidates with the shared ``fuzzySearch`` and
   renders them (avatar + name, or an ``@`` badge and hint for ``everyone``).
   A capture-phase ``keydown`` handler runs before the send-on-Enter handler so
   ``↑``/``↓`` navigate, ``Enter``/``Tab`` accept, and ``Esc`` closes.
4. ``acceptMention()`` replaces the ``@token`` with ``@username`` (or
   ``@everyone``) plus a trailing space.

**Pill rendering.** ``applyMentionPills(html)`` (called from ``formatText``)
wraps ``@username`` tokens for known users in ``<span class="mention">`` pills,
using a brighter ``mention-me`` variant for the current user and ``@everyone``.
Known users come from a ``GET /users`` fetch at load plus every channel-members
fetch. Tokens preceded by a word character, ``@`` or ``/`` are skipped, so
emails and URLs never become pills.

**Highlighting and notifications.** Mentions are extracted and validated
server-side and returned in each message's ``mentions`` field (a JSON array, or
the ``"@everyone"`` sentinel). ``isMentioned(m)`` is true when the current user
appears there — or for ``@everyone`` on any copy except the sender's own.
``fetchMessages()`` then:

- toggles the ``mentioned`` CSS class (a highlighted, left-barred message), and
- plays the new-message sound (honoring ``notifMuted``) and fires
  ``notifyMention()`` — a native ``Notification`` honoring ``nativeNotifEnabled``
  and browser permission — **even when the tab is focused**.

A ``mentionNotifyArmed`` flag, reset on page load and channel switch and armed
after the first poll response, suppresses these alerts for the historical
mentions in a channel's initial backlog.

Search
------

The search modal uses two matching strategies:

1. **Server-side search** — ``GET /search_messages?q=<query>`` performs a
   case-insensitive substring match and returns up to 50 results (restricted to
   channels the caller can read). The match is served by a trigram FTS5 index
   over the full message history, so it stays fast as history grows; queries
   shorter than three characters fall back to a ``LIKE`` scan.

2. **Client-side fuzzy search** — ``fuzzySearch(query, text)`` scores the
   returned candidates based on how well a fuzzy (out-of-order character) match
   works. Used to rank results and highlight matches in the UI.

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

- **Sound notifications** — ``notification.mp3`` is played through an
  ``Audio`` element when a new message arrives and the user has not muted
  notifications. The mute state is persisted in
  ``localStorage['notifMuted']``. See :ref:`sound-design` for the full set.

The browser tab title is updated by ``updateTitleBadge(count)`` to show
unread count: ``(3) MiniMost``. ``startFaviconFlash()`` alternates the
favicon between the normal icon and a red dot every second while there
are unread messages and the tab is in the background.

.. _sound-design:

Sound Design
------------

MiniMost ships six sounds, all in ``src/minimost/static/``:

.. list-table::
   :header-rows: 1
   :widths: 22 12 66

   * - File
     - Length
     - Played when
   * - ``notification.mp3``
     - 1.10 s
     - A new message arrives (``chat-sidebar.js``). A two-note marimba ding
       rising a perfect fifth, E6 → B6.
   * - ``receiving_call.mp3``
     - 4.20 s
     - Someone is calling you — **loops** until answered or timed out. A warm
       bell arpeggio (A major) played twice per loop.
   * - ``calling.mp3``
     - 4.00 s
     - Your outgoing call is ringing — **loops**. A soft double ringback pulse
       on A4, then a long gap.
   * - ``call_accepted.mp3``
     - 1.20 s
     - Someone answered. A rising perfect fifth, D5 → A5.
   * - ``hang_up.mp3``
     - 1.20 s
     - The call ended. The answer tone inverted: A5 → D5, falling.
   * - ``left_call.mp3``
     - 0.75 s
     - Another participant left a call still in progress. A quiet descending
       blip.

Provenance and licensing
~~~~~~~~~~~~~~~~~~~~~~~~

**The sounds are not sampled from anywhere.** They are synthesised from
scratch by ``tools/gen_sounds.py``, which is committed alongside them. They
are original work created for this project, carry no third-party licence, and
require no attribution — MiniMost can be redistributed and used commercially
without tracking terms for a handful of UI blips. Nothing was downloaded from
a sound library, so there is no external source to credit.

To change a sound, edit its recipe in ``tools/gen_sounds.py`` and re-run it;
do not hand-edit the MP3s, or the script and the shipped audio will disagree::

    pip install numpy      # not a runtime dependency — only needed to regenerate
    python3 tools/gen_sounds.py

``ffmpeg`` must be on ``PATH`` for the WAV → MP3 encode. The script overwrites
the six files in place and prints each one's length and size.

How they are built
~~~~~~~~~~~~~~~~~~

Each note is additive synthesis: a few sine partials, each with its own
amplitude and its own decay rate. Partials that fade faster than the
fundamental are what make the ear hear a struck object instead of a beep, and
their frequency ratios are what separate "wooden" from "metallic" — the
``MARIMBA`` timbre puts overtones near 4x and 10x the fundamental, the ``BELL``
timbre uses a nearly-harmonic stack with an inharmonic 2.76x partial. A short
synthetic reverb sits behind each sound.

Two details matter for correctness rather than taste:

- **Loop seams.** Every MP3 carries roughly 26 ms of encoder padding that
  ``<audio loop>`` does not splice out. The two looping ring sounds therefore
  start and end in silence, with the phrase faded to zero well before the
  seam, so the gap falls in silence and cannot be heard.

- **Clicks.** Notes are faded in over a few milliseconds and every file is
  faded out at its tail. Switching a waveform on or cutting it off mid-decay
  is a step change, and a step change is heard as a click.

Loudness is set **only** in the generator — each recipe normalises to the peak
it should actually play at, and the client never adjusts ``volume``. Splitting
level between the audio files and the JavaScript is how a set of sounds drifts
out of balance. The relative levels are deliberate: the incoming ring is the
loudest (it has to carry across a room), a new message is noticeable, and the
in-call cues are quiet enough not to startle someone mid-sentence.

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

Overlays (chat-modals.js)
-------------------------

Every overlay in the app — Account, Settings, Members, New DM, create/rename
private channel, and Help — is shown and hidden through one pair of functions
in ``chat-modals.js``:

.. code-block:: javascript

   openModal(el, { display, label, focus });
   closeModal(el);

``openModal`` sets ``role="dialog"`` and ``aria-modal="true"``, applies the
overlay's display value, records the element that had focus, and moves focus
inside. Where a dialog opens onto a field the caller passes it as ``focus``;
otherwise focus lands on the dialog's ``.modal-close-x`` button rather than
whatever comes first in the markup — in Account that would be **Sign out**.

``closeModal`` hides the element and hands focus back to whatever opened it,
but only if focus is still inside the dialog: if the user clicked elsewhere
first, pulling focus back would be the surprise. When the opener is gone, or
nothing held focus to begin with, focus falls to the message list.

Open dialogs are tracked on a stack, and one document-level ``keydown``
listener keeps ``Tab`` cycling inside the top-most one. Containment stands
down while an autocomplete list is open inside the dialog, since those fields
use ``Tab`` to accept the highlighted suggestion.

Help Dialog
~~~~~~~~~~~

The help overlay is a scrolling reference of thirteen sections, so it carries
a filter box and a jump list. ``filterHelp(query)`` hides every ``<li>`` that
does not match and then any section left empty; a section whose *heading*
matches keeps all its entries, so filtering for "calls" yields the whole Calls
section rather than one stray line. The jump list is built once from the
section headings themselves (``_buildHelpToc``), so adding a ``.help-sect`` to
the template is all it takes for a new pill to appear.

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
registered users.  Media travels **peer-to-peer over WebRTC**
(``RTCPeerConnection``); the server only relays signalling and runs a bundled
STUN server for LAN ICE (see :doc:`architecture`).

**ICE configuration:**

``RTC_CONFIG`` points ICE at the app's own STUN server using the page's
hostname (``stun:<location.hostname>:<STUN_PORT>``, injected into the template
as ``STUN_PORT``).  No public STUN/TURN servers are used, so calls work on an
air-gapped LAN.  ``_logPeerState()`` logs the ICE connection state to the
console and, on failure, hints at the likely cause (e.g. unreachable STUN UDP
port or peers on different subnets).

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
6. ``_startCallSignaling()`` begins a 600 ms poll of
   ``GET /calls/<id>/signals``.  As participants are seen as ``accepted`` (via
   the state poll) or a signal arrives from them, a ``RTCPeerConnection`` is
   created, the local microphone track is added, and offers/answers/ICE
   candidates are exchanged through ``POST /calls/<id>/signal``.

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

**Peer connections, remote audio, and voice activity detection:**

Each remote participant has one ``RTCPeerConnection`` (stored on its
``remoteParticipants`` entry) negotiated with the perfect-negotiation pattern
(``polite = CURRENT_USER < username`` to break offer glare):

- The remote audio track arrives via the connection's ``ontrack`` event and is
  attached to a hidden ``<audio>`` element for playback.
- An ``AnalyserNode`` tapped off that remote stream drives a 100 ms VAD
  interval that toggles the ``speaking`` CSS class on the participant's tile
  ring.

**Local microphone meter:**

``_startMicLevelMeter()`` taps the local ``getUserMedia`` track through its own
``AudioContext`` + ``AnalyserNode`` and updates the ``#call-mic-level`` fill on
the mute button every 50 ms, giving the user immediate "my mic works" feedback
(independent of the WebRTC connection).  It resumes a suspended ``AudioContext``
(and retries on the next gesture) and logs the chosen input device's
``label``/``muted``/``readyState`` to aid debugging silent-microphone issues.

**Tiles, spotlight and grid:**

``_renderCall()`` is the single render pass for the call surface.  It derives
the tiles that should exist right now — one per participant (including
yourself), one per invitee still ringing, and one per active screen share —
creates the missing ones with ``_createTile()``, refreshes the rest with
``_updateTile()``, and drops the ones whose subject has gone.

Each tile is then placed either on the **spotlight** (``#call-stage``) or in
the **grid** (``#call-participants-grid``), which becomes a filmstrip beside
the spotlight when ``#call-panel`` carries ``has-stage``.  Tiles are cached in
``callTiles`` and moved with ``appendChild`` rather than rebuilt, so a
``<video>`` never loses its stream to a re-render.

``_stageKey()`` picks the spotlight: an explicit pin wins, then the newest
screen share, then nothing.  ``cycleCallLayout()`` steps ``callLayout``
through ``auto`` → ``grid`` → ``stage``, and ``togglePinTile()`` pins the tile
the user clicked, so a share starting later cannot yank the view away.

The grid itself is ``repeat(auto-fit, minmax(230px, 1fr))``, so it reflows
from one large tile to a dense grid as people join without any JS.

``toggleCallMinimized()`` docks the whole panel into a corner card
(``.minimized``) — same DOM, different box — so the channel stays usable
during a call.

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

**In-call screen sharing flow:**

Screen sharing is available during an active call.  Only one participant may
share at a time; the server tracks the current sharer in the ``screenshare_user``
column of the ``calls`` table.

1. ``toggleScreenShare()`` is invoked directly by the button's ``onclick``
   handler.  ``navigator.mediaDevices.getDisplayMedia()`` is called
   immediately — without any intermediate async calls — so the browser's
   user-gesture activation token is preserved.
2. The display video track is added to every existing ``RTCPeerConnection``
   via ``addTrack()``, which triggers renegotiation (perfect negotiation).
   ``POST /calls/<id>/screenshare`` records the sharer in
   ``call_participants.sharing``.  Sharing is per participant, so any number
   of people can share at the same time.
3. On the receiver side the new video track arrives via ``ontrack`` and
   becomes that peer's screen tile, which takes the spotlight unless the user
   has pinned something else.  ``_pollCallState()`` reconciles the server's
   ``screensharers`` list against the tracks actually being received, as a
   backup for a share that stops without its track events arriving.
4. Stopping (button, native "stop sharing", or leaving) removes the track
   (renegotiating) and clears the ``sharing`` flag; the receiver drops the
   tile on the track's ``ended``/``mute`` event.

**Standalone screen sharing (outside a call):**

The topbar share button (``toggleStandaloneScreenShare()``) starts a share in
any DM/private channel via ``POST /screenshare/start``.  This is
**viewer-initiated**: other members see a banner (``refreshScreenShares()``
polls ``GET /screenshare/active``) and click *View* to open
``openShareViewer()``, which creates a recvonly ``RTCPeerConnection``, sends an
offer to the sharer, and renders the answered track.  The sharer polls
``GET /screenshare/<id>/signals`` and, for each viewer offer, attaches its
screen track (via ``replaceTrack`` on the offered transceiver) and answers —
fanning out one sharer to many viewers.  ICE candidates are buffered until the
remote description is set so none are dropped to a signalling race.

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
     - ``Map<username, state>`` holding per-participant WebRTC state: the
       ``RTCPeerConnection``, perfect-negotiation flags, buffered ICE
       candidates, remote ``<audio>`` element, VAD analyser, and tile element.
   * - ``RTC_CONFIG``
     - ICE configuration — a single ``stun:<hostname>:<STUN_PORT>`` server
       (the bundled STUN server); no public STUN/TURN.
   * - ``lastCallSignalId``
     - Cursor (``?after=``) for the WebRTC signalling poll so each
       offer/answer/ICE message is processed once.
   * - ``sharedAudioCtx`` / ``micMeterCtx``
     - ``AudioContext`` s for remote-participant VAD analysers and the local
       microphone level meter, respectively.
   * - ``callTiles`` / ``pinnedTileKey`` / ``callLayout``
     - The rendered tiles keyed ``user:<name>`` / ``screen:<name>``, the tile
       the user pinned to the spotlight, and the layout mode
       (``auto`` / ``grid`` / ``stage``).
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
     - The ``MediaStream`` from ``getDisplayMedia`` for an in-call share;
       ``null`` when not sharing.
   * - ``screenEnabled``
     - ``true`` while the local user is screensharing in a call.
   * - ``standaloneShareId`` / ``standaloneViewerPeers``
     - The active standalone share id and the map of viewer username →
       ``RTCPeerConnection`` the sharer answers.
   * - ``shareViewers`` / ``viewerFocusShareId``
     - One entry per standalone share being watched (peer connection, tile and
       signalling cursor), and which of them is on the viewer's stage.  Empty
       when not viewing.

Mobile Support
--------------

The sidebar is hidden by default on narrow screens and revealed by a
hamburger menu button. The ``touch-action: manipulation`` CSS property
disables double-tap zoom on buttons for a more app-like feel. Pinch-to-zoom
adjusts the message font size, and this preference is saved in
``localStorage['fontSize']``.
