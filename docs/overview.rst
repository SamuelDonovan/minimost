Overview
========

What is MiniMost?
-----------------

MiniMost is a lightweight, self-hosted team chat platform designed for private
networks. It provides a Slack-like chat experience with zero external
dependencies — no PostgreSQL, no Redis, no message broker, no Docker required.
The entire application is a Python package that you can install with ``pip``
and run with a single command.

The design philosophy is intentional minimalism: MiniMost aims to be the
simplest possible thing that actually works for a small team. It will never
compete feature-for-feature with Slack or Mattermost. What it offers is
something those tools cannot: a single self-contained binary equivalent that
runs on any machine with Python 3.6+, stores its data in plain SQLite files
that you can inspect with any SQLite browser, and requires no configuration
to get started.

Features
--------

Messaging
~~~~~~~~~

- **Public channels** — configurable via ``channels.json``; visible to all
  users.
- **Direct messages** — private one-on-one or group conversations.
- **Message history** — persistent and searchable; new users see the full
  public channel history from their first login.
- **Replies & threading** — quote any message to reply in context; the parent
  message is shown inline above the reply.
- **Edit & delete** — users can edit or soft-delete their own messages;
  changes propagate to all recipients in real time.
- **Full-text search** — search across all message content with fuzzy matching
  and highlighted results.

Real-time Interaction
~~~~~~~~~~~~~~~~~~~~~

- **Emoji reactions** — react to any message with one of 150+ emoji; reactions
  are toggled atomically and sync instantly across all users.
- **Typing indicators** — see when other users are composing a message.
- **Read receipts** — checkmark indicators showing who has read each message.
- **Presence indicators** — active, idle, hidden, and offline states updated
  automatically based on tab visibility and user activity.

Media
~~~~~

- **Image attachments** — paste from clipboard, drag-and-drop, or use the
  paperclip button; supports JPEG, PNG, GIF, and WebP.
- **Link previews** — automatically generated preview cards for URLs, with
  special support for Bitbucket Cloud and Bitbucket Server code file URLs
  (showing the file content with line-number highlighting).
- **Syntax highlighting** — code previews and inline code blocks are
  highlighted for Python, JavaScript, C, shell scripts, and more.

Interface
~~~~~~~~~

- **Single-page application** — the entire chat interface is a zero-framework
  vanilla JavaScript SPA that loads once and polls for updates.
- **Dark theme** — easy on the eyes by default.
- **Keyboard shortcuts** — Vim-inspired navigation, formatting shortcuts,
  and quick-access commands; see :doc:`keyboard_shortcuts`.
- **Mobile responsive** — full drawer sidebar, touch-friendly layout, and
  pinch-to-zoom font sizing.
- **Desktop notifications** — browser push notifications when a new message
  arrives and the tab is in the background; mutable per session.
- **Sound notifications** — configurable audio alert on new messages.

Security
~~~~~~~~

- Password hashing with PBKDF2 (Werkzeug).
- Enforced password complexity on both frontend and backend.
- 3-second delay on failed login attempts (brute-force protection).
- Per-user isolated SQLite databases.
- Parameterized SQL queries throughout.
- SSRF protection on link preview fetching.
- SAST scanning with Bandit and CodeQL.

Technical Stack
---------------

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Component
     - Technology
   * - Web framework
     - `Flask <https://flask.palletsprojects.com/>`_
   * - Database
     - SQLite (standard library ``sqlite3``)
   * - Password hashing
     - Werkzeug (installed as a Flask dependency)
   * - Frontend
     - Vanilla JavaScript (ES6+), no framework
   * - Styling
     - Plain CSS, dark theme
   * - Templating
     - Jinja2 (Flask default)
   * - Production server
     - Gunicorn (optional, recommended for multi-user deployments)
   * - Python requirement
     - Python 3.6 or later

Project Structure
-----------------

::

    minimost/
    ├── pyproject.toml              # Package metadata and dependencies
    ├── gunicorn.conf.py            # Production WSGI server configuration
    ├── channels.json               # Public channel definitions
    ├── secret.key                  # Auto-generated Flask session secret
    ├── auth.db                     # Shared authentication database
    ├── presence.db                 # Shared real-time state database
    ├── uploads/                    # Image attachment storage
    ├── users/                      # Per-user SQLite message databases
    │   └── {username}.db
    └── src/minimost/
        ├── __init__.py             # Flask app factory
        ├── __main__.py             # CLI entry point
        ├── auth.py                 # Authentication routes & utilities
        ├── chat.py                 # Messaging routes & channel logic
        ├── presence.py             # Presence, typing, reactions
        ├── common.py               # Database path helpers
        ├── database.py             # Schema bootstrap (auth.db)
        ├── preview.py              # Link preview generation
        ├── clean.py                # Image retention cleanup utility
        ├── templates/
        │   ├── login.html
        │   ├── signup.html
        │   └── chat.html           # Main SPA template (~2800 lines)
        └── static/
            ├── auth.css
            ├── styles.css
            └── reactions/          # 150+ reaction SVG files

Limitations and Non-goals
--------------------------

MiniMost is intentionally minimal. The following are explicit non-goals:

- **End-to-end encryption** — messages are stored in plaintext in SQLite
  files. An administrator with filesystem access can read all messages. Treat
  this as an internal LAN tool, not a secure messenger.
- **Self-service password reset** — there is no email-based reset flow. An
  administrator must update the password hash directly in ``auth.db``.
- **Role-based access control** — all registered users have the same
  permissions; there are no admin accounts, channel moderation roles, or
  invite-only channels.
- **Message retention policies** — the database grows indefinitely (images
  are cleaned up by ``clean.py``, but message rows are never deleted).
- **Federation or multi-server** — MiniMost is a single-server application
  with no inter-server protocol.
- **Webhooks or integrations** — there is no bot API or incoming webhook
  support in the current version.

FAQ
---

**Can it run on Windows?**

Yes. Replace ``python3`` with ``py`` and ``pip`` with ``py -m pip``.
Everything else works the same.

**How many users can it support?**

MiniMost is designed for small teams — typically 2–50 users on a local
network. SQLite performs well for this workload, especially with WAL mode
enabled. For larger deployments, Gunicorn with multiple workers is
recommended.

**What happens to messages if the server restarts?**

Nothing — all messages are durably written to SQLite before the route
handler returns. The only state lost on restart is the in-process link
preview cache (``preview.py``).

**Can I back up the data?**

Yes. The entire state of the application lives in:

- ``auth.db`` — credentials
- ``presence.db`` — reactions and read receipts (transient state)
- ``users/*.db`` — all message history
- ``uploads/`` — image attachments

A simple filesystem backup of the project directory is sufficient.
