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
         ├── auth.db              (shared, WAL mode)
         ├── presence.db          (shared, WAL mode)
         ├── avatars/             (user profile images)
         └── users/
             └── messages.db      (shared message store, WAL mode)

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

Shared SQLite Model
-------------------

Every message lives exactly once in a single shared SQLite file
(``users/messages.db``), addressed by its auto-increment ``id``. Built by
:func:`minimost.common.init_messages_db`; :func:`minimost.chat.get_db` opens it.

.. note::

   Earlier versions copied each message into a per-user ``users/<username>.db``
   (fan-out on write) and cross-referenced copies by ``ts``. That model is gone.
   ``init_user_db``, ``user_db_path`` and ``_seed_channel_history`` survive only
   as no-op compatibility shims.

**Tables in messages.db:**

- **messages** — one canonical row per message.
- **messages_fts** — trigram FTS5 substring search index over ``content``, kept
  in sync with ``messages`` by triggers (see *Search*).
- **reactions** — one row per ``(message_id, emoji, reactor)``.
- **read_state** — one read **watermark** (``last_read_ts``) per
  ``(user, channel)`` (see *Read state*).
- **dm_hidden** — one row per ``(user, channel)`` for hidden DM threads.

**Why a single database?**

- **One canonical row** — edits, deletes and reactions act on a single row by
  ``id``, eliminating the timestamp-matching code the per-user model needed.
- **No write amplification** — a public-channel message is one ``INSERT``, not
  one per recipient, and is stored (and indexed) once rather than ``N`` times.
- **Cross-channel queries stay cheap** — global search and the total-unread
  badge are single indexed queries rather than a fan-out across many files.

**The trade-off:** all writes serialise on one file's write lock. In WAL mode
the lock is held for microseconds per insert and readers never block, so for
MiniMost's self-hosted scale this is a non-issue; very high write concurrency
is the case where per-channel sharding would become worthwhile.

Message Propagation
-------------------

When ``POST /send/<channel>`` is called:

1. :func:`minimost.chat.is_valid_channel` authorises the sender for the channel.
2. The message row(s) are inserted into the shared ``messages`` table — one for
   the text content, one per attached image. Consecutive short messages from the
   same sender within 300 s are merged into the previous row instead.
3. The sender's ``read_state`` watermark for the channel is advanced to this
   message, so their own message never counts as unread.

:func:`minimost.chat.extract_mentions` scans the text for ``@username`` tokens
that resolve to real channel members and stores the result (JSON, or the
``"@everyone"`` sentinel for a channel-wide mention) in the ``mentions`` column.
Editing a message re-extracts mentions from the new text. The polling response
returns ``mentions`` so each client can highlight and notify the mentioned
viewer.

Because all messages share one table, the read path enforces access control
explicitly: :func:`minimost.chat.messages`, ``search_messages`` and
``channel_members`` check :func:`minimost.chat.is_valid_channel` (public
channels, private channels the user belongs to, DMs they participate in), and
private-channel late-joiners are bounded by ``history_start_ts``.

Read State (Watermark)
----------------------

Read state is a **per-channel watermark**, not a per-message flag. ``read_state``
holds one ``last_read_ts`` per ``(user, channel)``:

- **Unread counts** = messages in the channel after ``last_read_ts`` (sent by
  someone else, not deleted).
- **Read receipts** are *derived*: a user has read message *M* iff their
  ``last_read_ts >= M.ts``. ``GET /read_receipts/<channel>`` returns the
  watermarks (``{user: last_read_ts}``) and the client computes each ``✓`` from
  the message timestamps it already holds.

This costs ``O(users × channels)`` rows instead of the ``O(messages × users)``
of a per-message receipts table. ``POST /mark_read/<channel>`` advances the
watermark to the channel's newest message; ``POST /send`` advances the sender's.

Search
------

``GET /search_messages`` performs a case-insensitive **substring** search over
message content. It is backed by an FTS5 virtual table (``messages_fts``) using
the **trigram** tokenizer, which indexes every 3-character substring, so the
match is served from the index in well under a millisecond regardless of history
size (a plain ``LIKE '%q%'`` would scan the whole table). The index is
*external-content* (it stores only trigram postings, not a second copy of the
text) and is kept in sync with ``messages`` by insert/update/delete triggers.

- Queries shorter than 3 characters can't use the trigram index and fall back to
  a ``LIKE`` scan.
- Ordering by the FTS rowid descending returns newest-first results and lets
  FTS5 stop after 50 rows instead of sorting the full match set (``id`` is
  monotonic with ``ts``).
- Results are confined to channels the caller may read (see *Message
  Propagation*), so the shared table never leaks other users' DMs or private
  channels.

Shared State: auth.db and presence.db
--------------------------------------

``auth.db`` holds:

- **users** — credentials (``username``, ``password_hash``).
- **user_settings** — display preferences (``name_color``, ``avatar_file``), so
  every client can read another user's colour and avatar.

``presence.db`` holds:

- **Presence** (active/idle/hidden/offline) — shown to all users in sidebar.
- **Typing indicators** — shown to channel members in real time.
- **Private channels** — ``private_channels`` and ``private_channel_members``
  (the latter carries each member's ``history_start_ts``).
- **Call state** — ``calls`` and ``call_participants`` track the full
  lifecycle of every voice/video call; ``call_signals`` relays WebRTC
  offer/answer/ICE-candidate messages between peers during connection setup.
  (The legacy ``call_media``/``share_media`` tables are retained but unused now
  that media flows peer-to-peer over WebRTC.)
- The legacy ``read_receipts`` and ``message_reactions`` tables remain defined
  but are **unused** — read state and reactions now live in ``messages.db``.

**Reactions workflow:**

1. Client posts to ``/react/<msg_id>``.
2. Server atomically toggles the row in the shared ``reactions`` table
   (``INSERT`` or ``DELETE``), keyed by the message ``id`` — one statement, no
   read-modify-write race and no per-user fan-out.
3. Server bumps ``reactions_ts`` on the message row — the signal the polling
   query picks up.
4. Next poll cycle: ``/messages/<channel>?after=<ts>`` returns the message
   because ``reactions_ts > after``, with its reactions joined in from the
   ``reactions`` table.
5. Client receives the updated ``reactions`` JSON and re-renders.

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
     - Fetches per-user read watermarks and derives the ``✓`` checkmarks.
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
4. :func:`minimost.common.init_messages_db` ensures the shared message schema
   exists (idempotent). There is no per-account database to create or seed — the
   new user can already see the full public history, since every message lives in
   the one shared table.
5. A welcome message is posted; the session is established; user is redirected
   to ``/``.

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
messages. The ``dm_hidden`` table (in ``messages.db``) records one row per
``(user, channel)`` with a ``hidden_ts`` (Unix timestamp of when the
conversation was hidden), so hiding is per-viewer.

The ``GET /dms`` query joins ``dm_hidden`` for the requesting user and uses a
``HAVING`` clause to filter out hidden conversations unless a message has
arrived after ``hidden_ts``::

    HAVING dh.hidden_ts IS NULL OR MAX(m.ts) > dh.hidden_ts

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
