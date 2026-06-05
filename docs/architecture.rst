Architecture
============

This page explains the internal design decisions that make MiniMost work. It
is intended for developers who want to understand, extend, or maintain the
codebase.

High-Level Overview
-------------------

MiniMost is a classic **server-rendered + polling** web application. There is
no WebSocket, no event stream, and no message broker. The client polls a set
of JSON endpoints at fixed intervals to pick up new data.

.. code-block:: text

    Browser (Vanilla JS SPA)
         │
         │  HTTP polling (500ms – 5s intervals)
         │  JSON REST API
         ▼
    Flask Application (Gunicorn workers)
         │
         ├── auth.db          (shared, WAL mode)
         ├── presence.db      (shared, WAL mode)
         ├── avatars/         (user profile images)
         └── users/
             ├── alice.db     (per-user, WAL mode)
             ├── bob.db       (per-user, WAL mode)
             └── ...

Application Factory
-------------------

The application follows Flask's `application factory pattern
<https://flask.palletsprojects.com/en/stable/patterns/appfactories/>`_.
:func:`minimost.create_app` is the single point of entry for all execution
paths: the CLI, Gunicorn, and test suites.

The factory is responsible for:

1. Generating or loading the ``secret.key`` (session signing key).
2. Setting the 16 MiB upload limit.
3. Injecting the version string into the Jinja2 context.
4. Registering the four Blueprints:

   - :mod:`minimost.auth` — authentication routes.
   - :mod:`minimost.chat` — messaging routes.
   - :mod:`minimost.presence` — presence, typing, and reaction routes.
   - :mod:`minimost.calls` — voice/video calling lifecycle and WebRTC
     signalling routes.

5. Resetting all presence records to ``"offline"`` and all in-progress call
   records to ``"ended"`` (and clearing stale signalling rows) so stale state
   from a previous server run does not persist.

6. Starting the bundled STUN server (:mod:`minimost.stun`) in a daemon thread
   so LAN WebRTC peers can gather a real-IP server-reflexive ICE candidate.

Blueprint structure means each module is self-contained and the URL routing
is defined close to the handler code.

Distributed SQLite Model
-------------------------

The most unusual design decision in MiniMost is its database layout.

Most chat applications use a single shared database where every user's
messages are stored together. MiniMost instead gives every user their own
SQLite file (``users/<username>.db``).

**Why?**

- **Per-user read state** — each user needs to track which messages they have
  read. In a shared table this requires a ``(user_id, message_id)`` join
  table that grows with ``O(users × messages)``. With per-user databases, the
  ``read`` column is a single bit on the message row itself.
- **Isolation** — a corrupted or locked user database affects only that one
  user, not the entire application.
- **SQLite WAL mode** — SQLite's WAL journal allows one writer and many
  readers to operate simultaneously without blocking each other. Per-user
  databases mean write contention is spread across many files rather than
  concentrated on one.

**The trade-off:**

When a user sends a message, MiniMost must write a copy of that message into
**every recipient's database** individually. For a public channel with *N*
users, that is *N* separate ``INSERT`` statements. For small teams this is
fast; for large teams it could become a bottleneck.

Message Propagation
-------------------

When ``POST /send/<channel>`` is called:

1. :func:`minimost.chat.channel_users` returns the list of recipients.
   - Public channels: all registered users.
   - DM channels: the participants listed in the channel name.
2. The sender is added to the list if not already present.
3. For each recipient, ``get_db(recipient)`` opens their database.
4. The message row(s) are inserted — one for the text content, one per
   attached image.
5. Each database is committed and closed.

The ``ts`` (Unix timestamp) is assigned once before the loop and shared
across all recipients. This shared timestamp is used as the cross-user
identity token for edits, deletes, and reactions — since row ``id`` values
differ between per-user databases.

Before the loop, :func:`minimost.chat.extract_mentions` scans the text for
``@username`` tokens that resolve to real channel members and stores the result
(JSON, or the ``"@everyone"`` sentinel for a channel-wide mention) in each
recipient's ``mentions`` column. Editing a message re-extracts mentions from
the new text. The polling response returns ``mentions`` so each client can
highlight and notify the mentioned viewer.

Shared State: auth.db and presence.db
--------------------------------------

Some state cannot live in per-user databases because it needs to be visible
to all users simultaneously.

``auth.db`` holds two tables:

- **users** — credentials (``username``, ``password_hash``).
- **user_settings** — per-user display preferences (``name_color``,
  ``avatar_file``). Stored here rather than in per-user databases so that
  every client can read another user's colour and avatar without needing
  access to that user's private database.

``presence.db`` holds:

- **Presence** (active/idle/hidden/offline) — shown to all users in sidebar.
- **Typing indicators** — shown to channel members in real time.
- **Read receipts** — visible to the message sender.
- **Reactions** — visible to all users on the message.
- **Call state** — ``calls`` and ``call_participants`` track the full
  lifecycle of every voice/video call; ``call_signals`` relays WebRTC
  offer/answer/ICE-candidate messages between peers during connection setup.
  (The legacy ``call_media``/``share_media`` tables are retained but unused now
  that media flows peer-to-peer over WebRTC.)

All of this lives in ``presence.db``. The key table is ``message_reactions``,
which stores individual ``(channel, msg_ts, emoji, reactor)`` tuples. This
avoids the read-modify-write race condition that would occur if reactions were
stored as a JSON string in per-user databases.

**Reactions workflow:**

1. Client posts to ``/react/<msg_id>``.
2. Server opens ``presence.db`` and atomically toggles the reaction row
   (``INSERT`` or ``DELETE``).
3. Server reads back all current reactions for that message.
4. Server bumps ``reactions_ts`` in every recipient's database — this is the
   signal that the polling query will pick up.
5. Next poll cycle: ``/messages/<channel>?after=<ts>`` returns the message
   because ``reactions_ts > after``.
6. Client receives the updated ``reactions`` JSON and re-renders.

Polling Architecture
--------------------

The client runs several ``setInterval`` loops:

.. list-table::
   :header-rows: 1
   :widths: 30 15 55

   * - Loop
     - Interval
     - What it does
   * - ``fetchMessages``
     - 500 ms
     - Fetches new/updated/deleted messages since ``lastTs``.
   * - ``refreshPresence``
     - 1 s
     - Updates presence indicators in the sidebar.
   * - ``fetchTyping``
     - 1 s
     - Shows/hides the typing indicator.
   * - ``refreshDMs``
     - 1 s
     - Refreshes the DM list and unread badges.
   * - ``refreshChannels``
     - 1 s
     - Refreshes channel unread badges.
   * - ``pollIncomingCalls``
     - 1 s
     - Polls ``GET /calls/incoming``; surfaces the incoming-call overlay
       and closes it when the caller hangs up or times out.
   * - ``fetchReadReceipts``
     - 3 s
     - Updates ``✓`` read checkmarks.
   * - ``_pollCallState``
     - 3 s
     - Polls ``GET /calls/<id>/state`` during an active call; diffs the
       participant list to open/close peer connections and tears down the
       call UI when the remote side hangs up.
   * - WebRTC signalling poll
     - 600 ms
     - During an active call, polls ``GET /calls/<id>/signals`` and dispatches
       offers/answers/ICE candidates to the matching ``RTCPeerConnection``.
       Standalone screen shares use ``GET /screenshare/<id>/signals`` the same
       way.  (Call/screen-share **media** itself flows peer-to-peer over
       WebRTC and is never polled.)
   * - ``refreshTotalUnreadCount``
     - 5 s
     - Updates the browser tab title badge.
   * - Presence heartbeat
     - 30 s
     - Re-sends the current presence state to keep ``last_seen`` fresh.
   * - Idle detection
     - 5 s
     - Checks for 5 minutes of inactivity; sends ``"idle"`` if detected.

The message polling endpoint uses a ``?after=<timestamp>`` parameter so
responses only contain changes since the last poll. This keeps payloads small
even for channels with long histories.

Authentication Flow
-------------------

1. User submits credentials to ``POST /login``.
2. Server looks up ``password_hash`` in ``auth.db``.
3. :func:`werkzeug.security.check_password_hash` verifies the PBKDF2 hash.
4. On success, ``session["user"]`` is set (signed cookie via Flask's
   ``secret.key``).
5. Every subsequent route decorated with ``@login_required`` checks for this
   session key.

New User Registration Flow
--------------------------

1. User submits the signup form.
2. Server validates username format and password complexity rules. The
   reserved names ``minimost``, ``everyone``, and ``deleteduser`` are rejected
   (case-insensitively) because the app gives them special meaning.
3. ``(username, hash)`` is inserted into ``auth.db``.
4. :func:`minimost.common.init_user_db` creates ``users/<username>.db``.
5. :func:`minimost.auth._seed_channel_history` copies all public channel
   messages from an existing user's database (with ``read=1``) so the new
   user sees the full history without any unread notifications.
6. Session is established; user is redirected to ``/``.

DM Channel Naming
-----------------

DM channel identifiers are constructed by sorting participant usernames and
joining them with colons::

    dm:alice:bob          # two-person DM
    dm:alice:bob:charlie  # group DM with three participants

:func:`minimost.chat.normalize_dm` is the canonical function for this. Sorting
ensures that the same conversation always has the same identifier regardless of
who initiates it. Channel access is enforced by checking that the authenticated
user's username appears in the channel string.

DM Visibility (dm_hidden)
--------------------------

Users can close (hide) a DM thread from the sidebar without deleting any
messages. The per-user database includes a ``dm_hidden`` table with columns
``channel`` (primary key) and ``hidden_ts`` (Unix timestamp of when the
conversation was hidden).

The ``GET /dms`` query uses a ``HAVING`` clause to filter out hidden
conversations unless a message has arrived after ``hidden_ts``::

    HAVING MAX(ts) > COALESCE(hidden_ts, 0)

This means the DM reappears automatically the next time a new message is
received — no manual "reopen" action is required.

Avatar Storage
--------------

User profile avatars are stored in the ``avatars/`` directory at the project
root. The filename is stored in ``auth.db`` → ``user_settings.avatar_file``.
Images are resized client-side (Canvas API, centre-crop to a 128 × 128 JPEG)
before upload, so no server-side image library is required.

Link Preview Pipeline
---------------------

When the client detects a URL in a message, it calls ``GET /link_preview?url=``.
The server-side pipeline in :mod:`minimost.preview`:

1. Check the in-process FIFO cache (200-entry limit).
2. Validate: reject non-HTTP/HTTPS schemes and private IP addresses (SSRF
   protection).
3. Try **Bitbucket Cloud** preview (``bitbucket.org`` host).
4. Try **Bitbucket Server** preview (matches ``/projects/…/repos/…/browse/``
   path pattern).
5. Fall back to **OpenGraph** preview (fetch HTML, parse ``<meta>`` tags).
6. Cache and return the result.

The client renders the result as a card below the message:
- Code previews use client-side syntax highlighting with regex-based rules.
- OpenGraph previews show the title, description, and thumbnail image.

Calling Architecture
--------------------

Voice, video, and screen-share **media flows peer-to-peer over WebRTC**
(``RTCPeerConnection``).  Flask's only role is the call lifecycle state machine
(the ``calls`` and ``call_participants`` tables) and relaying the WebRTC
signalling messages (offer/answer/ICE) through the ``call_signals`` table.

**Why WebRTC?**

MiniMost is a LAN application, so the firewall-traversal benefit of an HTTP
media relay is unnecessary, while its costs — polling latency, irregular
``MediaRecorder`` bursts, TCP head-of-line blocking, and per-chunk SQLite I/O —
caused freezing during calls and screen shares.  WebRTC gives a smooth,
low-latency, congestion-controlled real-time stream directly between peers.

**ICE without external servers:**

Because the app is LAN-only there is no NAT between peers, so no TURN relay is
needed.  ICE is configured with **no public STUN/TURN servers**.  Instead,
:mod:`minimost.stun` is a tiny, dependency-free STUN server started with the
app (UDP ``3478`` by default).  Pointing the browser at it lets each peer
gather a **server-reflexive** candidate carrying its real LAN IP — unlike host
candidates, srflx candidates are not obfuscated as ``*.local`` mDNS names, so
peers connect without avahi/Bonjour and the whole thing works air-gapped.

**Topology:**

Calls form a **full mesh** — one ``RTCPeerConnection`` per pair of accepted
participants, negotiated with the "perfect negotiation" pattern to avoid offer
glare.  In-call screen share adds the display video track to each existing peer
connection (renegotiating).  Standalone screen share is **viewer-initiated**:
each viewer creates the offer and the sharer answers with its screen track,
giving a one-sharer-to-many-viewers fan-out.

**Call lifecycle:**

.. code-block:: text

    Caller                            Server                         Callee
      │                                 │                               │
      │  POST /calls/initiate           │                               │
      │ ─────────────────────────► │  INSERT calls (ringing)       │
      │                                 │  INSERT call_participants     │
      │  ◄──────────────────────── │  { call_id }                  │
      │                                 │                               │
      │  GET /calls/<id>/state (3 s)    │  GET /calls/incoming (1 s)    │
      │ ─────────────────────────► │ ◄─────────────────────── │
      │                                 │  ───────────────────────► │
      │                                 │  incoming call overlay shown  │
      │  [user answers]                 │  POST /calls/<id>/accept      │
      │                                 │ ◄──────────────────────── │
      │  ◄── state: active ────────── │  UPDATE calls (active)        │
      │                                 │                               │
      │   ── signalling (offer/answer/ICE) via /calls/<id>/signal[s] ── │
      │  POST /signal  ───────────► │  INSERT call_signals          │
      │  GET  /signals (600 ms) ◄── │  ───────────────────────► GET │
      │                                 │                               │
      │  ◄════════ WebRTC media (audio / screen) flows P2P ══════════► │
      │            (never touches the server)                          │
      │                                 │                               │
      │  POST /calls/<id>/end           │                               │
      │ ─────────────────────────► │  UPDATE calls (ended)         │
      │                                 │  DELETE call_signals          │

**Screen sharing layout:**

When screen sharing is active, the browser adds the ``screen-share-active``
CSS class to the call panel.  The shared screen occupies the main area of the
call overlay and the camera feed shrinks to a picture-in-picture corner.
Removing the class restores the camera to full size.  Stopping the
browser's native screen-capture (via its built-in stop button) fires the
``"ended"`` event on the video track, which calls ``toggleScreenShare()``
automatically to keep the UI in sync.  The current in-call sharer is recorded
via ``POST /calls/<id>/screenshare`` in the ``screenshare_user`` column so the
single-sharer policy and viewer UI stay in sync.

**Ring timeout:**

If the callee does not answer, the call is automatically cancelled through
two complementary mechanisms:

- **Backend** (``_RINGING_TIMEOUT = 30 s``) — ``GET /calls/incoming``
  filters out calls older than 30 seconds so they never surface on the
  callee side.  ``GET /calls/<id>/state`` also auto-transitions a stale
  ringing call to ``'rejected'`` at the same threshold.
- **Frontend** (``RING_TIMEOUT_MS = 30 000 ms``) — a client-side
  ``setTimeout`` fires after 30 s; the caller posts
  ``POST /calls/<id>/end`` and the callee's incoming-call overlay is closed.
- **Callee poll** — ``pollIncomingCalls`` continues running even while the
  incoming-call overlay is visible; when the call disappears from the
  ringing list (due to the backend timeout, the caller hanging up, or any
  other state change) ``closeIncomingCallUI()`` is called immediately.

**Database tables** (all in ``presence.db``):

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Table
     - Contents
   * - ``calls``
     - One row per call: ``call_id`` (UUID), ``channel``, ``initiator``,
       ``state`` (ringing/active/ended/rejected), and timestamps.
   * - ``call_participants``
     - One row per (call, user): ``role`` (initiator/participant),
       ``state`` (pending/accepted/rejected/left), and timestamps.
   * - ``call_signals``
     - WebRTC signalling relay: offer/answer/ICE-candidate messages between
       peers, keyed by ``call_id`` (and reused for standalone screen shares,
       keyed by ``share_id``).  Purged when the call/share ends and at startup.
   * - ``call_media`` / ``share_media``
     - Legacy HTTP media-relay buffers, retained for one release as a fallback
       but **no longer used** now that media flows peer-to-peer over WebRTC.

**HTTPS requirement:**

Browsers only grant microphone, camera, and WebRTC access in a `secure context
<https://developer.mozilla.org/en-US/docs/Web/Security/Secure_Contexts>`_
(HTTPS or localhost).  MiniMost auto-generates a self-signed TLS certificate
on first run (see :doc:`deployment`) to satisfy this requirement.  Note the
bundled STUN server uses plain UDP (STUN is not a TLS protocol); only the page
and signalling traffic need HTTPS.

Frontend Architecture
---------------------

See :doc:`frontend` for a detailed description of the client-side JavaScript.

Security Architecture
---------------------

See :doc:`security` for a full description of the security model.

Module Dependency Graph
-----------------------

.. code-block:: text

    minimost.__init__
    ├── minimost.auth        (auth_bp)
    │   ├── minimost.common
    │   └── minimost.presence
    ├── minimost.chat        (chat_bp)
    │   ├── minimost.common
    │   ├── minimost.presence
    │   ├── minimost.auth
    │   └── minimost.preview
    ├── minimost.presence    (presence_bp)
    ├── minimost.calls       (calls_bp)
    │   ├── minimost.auth
    │   ├── minimost.presence  (for PRESENCE_DB path)
    │   └── minimost.chat      (for get_private_channel_members)
    ├── minimost.common
    └── minimost.database
        └── minimost.auth    (for AUTH_DB path)

:mod:`minimost.clean` is a standalone script with no imports from the rest
of the package.
