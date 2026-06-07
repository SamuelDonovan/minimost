<img src="src/minimost/static/minimost-logo.svg" alt="MiniMost" width="360">

---

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python: 3.6+](https://img.shields.io/badge/python-3.6%20%7C%203.7%20%7C%203.8%20%7C%203.9%20%7C%203.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue.svg)](https://www.python.org/)
[![Built with Flask](https://img.shields.io/badge/built%20with-Flask-000000.svg?logo=flask)](https://flask.palletsprojects.com/)
[![Database: SQLite](https://img.shields.io/badge/database-SQLite%20only-003b57.svg?logo=sqlite&logoColor=white)](https://www.sqlite.org/)
[![PWA](https://img.shields.io/badge/PWA-installable-5a0fc8.svg)](https://developer.mozilla.org/en-US/docs/Web/Progressive_web_apps)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Code style: prettier](https://img.shields.io/badge/code%20style-prettier-ff69b4.svg)](https://github.com/prettier/prettier)
[![Build](https://github.com/SamuelDonovan/minimost/actions/workflows/build.yml/badge.svg)](https://github.com/SamuelDonovan/minimost/actions/workflows/build.yml)
[![Bandit](https://github.com/SamuelDonovan/minimost/actions/workflows/bandit.yml/badge.svg)](https://github.com/SamuelDonovan/minimost/actions/workflows/bandit.yml)
[![Semgrep](https://github.com/SamuelDonovan/minimost/actions/workflows/semgrep.yml/badge.svg)](https://github.com/SamuelDonovan/minimost/actions/workflows/semgrep.yml)
[![pip-audit](https://github.com/SamuelDonovan/minimost/actions/workflows/pip-audit.yml/badge.svg)](https://github.com/SamuelDonovan/minimost/actions/workflows/pip-audit.yml)
[![CodeQL](https://github.com/SamuelDonovan/minimost/actions/workflows/codeql.yml/badge.svg)](https://github.com/SamuelDonovan/minimost/actions/workflows/codeql.yml)
[![Documentation Status](https://readthedocs.org/projects/minimost/badge/?version=latest)](https://minimost.readthedocs.io/en/latest/)
[![Quality Gate](https://sonarcloud.io/api/project_badges/measure?project=SamuelDonovan_minimost&metric=alert_status)](https://sonarcloud.io/summary/overall?id=SamuelDonovan_minimost)
[![Maintainability](https://sonarcloud.io/api/project_badges/measure?project=SamuelDonovan_minimost&metric=sqale_rating)](https://sonarcloud.io/summary/overall?id=SamuelDonovan_minimost)
[![Reliability](https://sonarcloud.io/api/project_badges/measure?project=SamuelDonovan_minimost&metric=reliability_rating)](https://sonarcloud.io/summary/overall?id=SamuelDonovan_minimost)
[![Security Rating](https://sonarcloud.io/api/project_badges/measure?project=SamuelDonovan_minimost&metric=security_rating)](https://sonarcloud.io/summary/overall?id=SamuelDonovan_minimost)

**MiniMost** is a lightweight, self-hosted chat platform built for private networks. It runs entirely on Python and SQLite — no external database, no root access, no infrastructure required. Just Flask and a browser.

---

## Screenshots

![Login page](docs/_static/screenshot-login.png)
_The login page — clean, minimal, and version-tagged._

![Chat interface](docs/_static/screenshot-chat.png)
_The main chat interface — channel list, direct messages, inline image attachments, and real-time typing indicators._

![Message search](docs/_static/screenshot-message-search.png)
_Full-text message search with highlighted results._

---

## Features

- **Channels & Direct Messages** — public channels (configurable), private channels, and one-on-one or group DMs
- **Private channels** — invite-only rooms; members can be added or removed, the channel can be renamed, and any member can leave
- **Message history** — persistent, searchable, and visible to new users from day one
- **Replies & threading** — quote any message to reply in context
- **Editing & deletion** — edit or delete your own messages; changes propagate in real time
- **Emoji reactions** — react to any message; reactions sync across all users instantly
- **Read receipts** — see who has read your messages
- **@mentions** — type `@` to open a fuzzy-search dropdown of the channel's members; a mentioned user sees the message highlighted and gets a sound and desktop notification (honoring their toggles) even while the page is open. Mention `@everyone` to ping the whole channel
- **Voice calling** — one-click calls in any DM or private channel; audio streams **peer-to-peer over WebRTC** (`RTCPeerConnection`) for low-latency, real-time voice; unanswered calls time out and cancel automatically
- **Group calling** — any participant in an active call can invite additional registered users via the in-call "Add person" button; up to any number of callers can share the same call (a WebRTC full mesh); participants can leave individually without ending the call for others; the last person to leave ends the call
- **Dynamic call layout** — participants appear as avatar tiles that reflow automatically: one caller fills the panel, two callers split 50/50, three or more tile in a grid; each tile has an independent speaking-ring animation driven by per-participant voice activity detection, plus a live level meter on your own mic button
- **Screen sharing** — share your screen peer-to-peer over WebRTC, either during a call or standalone in any DM/private channel; the shared screen takes the majority of the panel while participant avatars move to a right-hand sidebar; only one participant may share at a time during a call — starting a new share automatically stops any existing one; stopping the browser capture ends the share
- **LAN-first WebRTC** — call and screen-share media never touch the server; signaling (offer/answer/ICE) is relayed through the existing Flask backend and a small **bundled STUN server**, so there are no external/public STUN/TURN servers to configure and it works on fully air-gapped LANs
- **Presence indicators** — active, idle, away, and offline states updated automatically; overlaid on user avatars
- **User avatars** — default initials avatar for every account; upload a custom image via Settings; displayed in the DM sidebar, private channel tooltips, and the member list
- **User settings** — choose a display name colour from a palette of presets; upload or remove a profile avatar
- **Close DM conversations** — hide a DM thread from the sidebar with one click; it reappears automatically if a new message arrives
- **File attachments** — paste, drag-and-drop, or use the paperclip button to attach any file type; images are displayed inline, other files appear as a download link; uploaded files auto-delete after a configurable retention period
- **Automatic message retention** — a background thread permanently removes messages older than a configurable threshold (default: 770 days) so database files never grow without bound; runs every 24 hours with no cron job required
- **Desktop & sound notifications** — configurable per session, mutable with one click; `@mentions` alert you even when the tab is focused
- **Mobile responsive** — full drawer sidebar, touch-friendly layout, pinch-to-zoom font sizing
- **Dark theme** — easy on the eyes
- **Password security** — salted hashes (PBKDF2), enforced complexity requirements
- **Account self-deletion** — users can delete their own account from Settings; soft delete removes login credentials and re-attributes messages to "Deleted User" while preserving chat history; hard delete removes the account and every message the user ever sent across all channels and conversations; both require password confirmation
- **Admin password reset** — generate a one-time, time-limited reset URL from the CLI; the user receives an in-app notification when a reset is requested

---

## Requirements

- Python 3.6+
- Flask (`pip install flask`)

That's it!

---

## Installation

### From source

```bash
git clone https://github.com/SamuelDonovan/minimost.git
cd minimost
pip install -e .
```

### From wheel (latest build)

Download the latest `.whl` from the [releases page](https://github.com/SamuelDonovan/minimost/releases/tag/dev), then:

```bash
pip install minimost-*.whl
```

### Dependencies only (no internet access)

Download the Flask wheel and its dependencies, then:

```bash
pip install --user *.whl
```

---

## Running

```bash
minimost
```

Or without installing:

```bash
python3 -m minimost
```

On first run MiniMost automatically generates a self-signed TLS certificate (`cert.pem` / `key.pem`) using the system `openssl` binary and serves over **HTTPS**. The server starts at [https://127.0.0.1:5000](https://127.0.0.1:5000) by default. Use `--host` and `--port` to change the bind address:

```bash
# Listen on all interfaces (accessible from other machines on the network)
minimost --host 0.0.0.0

# Listen on a specific IP and port
minimost --host 192.168.1.10 --port 8080
```

To reach the server from another machine, navigate to `https://<server-ip>:<port>` in a browser. The generated certificate is self-signed, so your browser will show a security warning — add a permanent exception to dismiss it.

> **Note:** HTTPS is required for voice and video calling (browsers only allow camera/microphone and WebRTC access in secure contexts). If `openssl` is not installed, MiniMost will still start over plain HTTP but the calling feature will not work.

> **Note:** Calls and screen shares connect peers directly over WebRTC. For this to work, peers must be on the **same LAN/subnet** and able to reach each other (and the bundled STUN server on UDP `3478`, configurable via `stun_port` in `settings.json`) over UDP. No public STUN/TURN server is used, so calls work on air-gapped networks, but they will not traverse the public internet or connect peers on different subnets.

### Ports & firewall

| Port                                  | Protocol | Open on          | Required for                                            | Notes                                                                                              |
| ------------------------------------- | -------- | ---------------- | ------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| `6767` (Gunicorn) / `5000` (dev)      | TCP      | Server (inbound) | Everything — web UI, chat, file uploads, call signaling | The only port needed for text chat. Set via `--port` or `gunicorn.conf.py`.                        |
| `3478`                                | UDP      | Server (inbound) | Voice/video calls & screen sharing                      | Bundled STUN server. Set via `stun_port` in `settings.json`.                                       |
| Ephemeral UDP (Linux `32768`–`60999`) | UDP      | Between clients  | WebRTC media (audio/video/screen)                       | Peer-to-peer, browser-chosen; only matters if clients run host firewalls or sit on segmented LANs. |

No outbound internet access is required (no external database, no public STUN/TURN) — MiniMost runs fully air-gapped. There is **no TURN relay**, so peers must be on the same LAN/subnet, and SQLite is file-based so there is no database port. See the [deployment docs](docs/deployment.rst) for an administrator setup checklist plus `firewalld` / `ufw` examples.

### Production deployment

The built-in Flask server is suitable for development and small private networks. For a more robust deployment, run MiniMost behind a WSGI server such as Gunicorn:

```bash
pip install gunicorn

# From an installed package (wheel or `pip install -e .`) — uses the config
# module shipped inside the package, so no source checkout is required:
gunicorn "minimost:create_app()" -c python:minimost.gunicorn_conf

# From a source checkout — equivalent thin shim that re-exports the same config:
gunicorn "minimost:create_app()" --config gunicorn.conf.py
```

Both forms handle automatic TLS certificate generation before Gunicorn starts. The bundled `gunicorn.conf.py` is a thin shim around the packaged `minimost.gunicorn_conf` module, so the two are interchangeable.

### Configuration

Edit `settings.json` (bundled with the package at `src/minimost/settings.json`) to configure MiniMost. All keys are optional and fall back to sensible defaults if omitted:

```json
{
  "channels": ["general", "software", "firmware", "systems", "off-topic"],
  "image_retention_days": 30,
  "file_retention_days": 30,
  "message_retention_days": 770,
  "max_upload_size_mb": 25,
  "max_avatar_size_mb": 5,
  "stun_port": 3478,
  "max_login_attempts": 5,
  "lockout_duration_minutes": 15
}
```

| Key                        | Default       | Description                                                                                                    |
| -------------------------- | ------------- | -------------------------------------------------------------------------------------------------------------- |
| `channels`                 | `["general"]` | Public channel names shown in the sidebar. Restart required.                                                   |
| `image_retention_days`     | `30`          | Days before image attachments are auto-deleted. No restart needed.                                             |
| `file_retention_days`      | `30`          | Days before non-image attachments are auto-deleted. No restart needed.                                         |
| `message_retention_days`   | `770`         | Days before messages are permanently deleted from the database. No restart needed.                             |
| `max_upload_size_mb`       | `25`          | Maximum size in MB for a single file attachment. Restart required.                                             |
| `max_avatar_size_mb`       | `5`           | Maximum size in MB for a profile avatar upload. Restart required.                                              |
| `stun_port`                | `3478`        | UDP port for the bundled STUN server used by WebRTC calls/screen share. Must be `1`–`65535`. Restart required. |
| `max_login_attempts`       | `5`           | Consecutive failed logins before an account is locked. Set to `0` to disable lockout. No restart needed.       |
| `lockout_duration_minutes` | `15`          | How long an account stays locked after too many failed logins. No restart needed.                              |

---

## Keyboard Shortcuts

### Messaging

| Key             | Action                                                             |
| --------------- | ------------------------------------------------------------------ |
| `Enter`         | Send message                                                       |
| `Shift + Enter` | New line                                                           |
| `@`             | Open the mention dropdown (`↑`/`↓` navigate, `Enter`/`Tab` accept) |
| `Esc`           | Unfocus input / close menus                                        |

### Navigation

| Key                     | Action                  |
| ----------------------- | ----------------------- |
| `i`                     | Focus message input     |
| `o`                     | Start a new DM          |
| `/` or `f`              | Search messages         |
| `j` / `k`               | Scroll down / up        |
| `d` / `u`               | Scroll down / up (2×)   |
| `G`                     | Jump to bottom          |
| `g`                     | Jump to top             |
| `Ctrl + J` / `Ctrl + K` | Next / previous channel |
| `?`                     | Open help menu          |

### Visual Mode

Press `v` in normal mode (input unfocused) to enter visual mode, which highlights a single message for direct keyboard actions. The topbar shows `-- visual --` while active.

| Key       | Action                                          |
| --------- | ----------------------------------------------- |
| `v`       | Enter visual mode (selects most recent message) |
| `j` / `↓` | Move selection to next (newer) message          |
| `k` / `↑` | Move selection to previous (older) message      |
| `d`       | Delete highlighted message                      |
| `c`       | Edit highlighted message                        |
| `o`       | Reply to highlighted message                    |
| `y`       | Copy highlighted message text to clipboard      |
| `e`       | React to highlighted message with emoji         |
| `Esc`     | Exit visual mode                                |

### Text Formatting

| Key        | Action            |
| ---------- | ----------------- |
| `Ctrl + B` | **Bold**          |
| `Ctrl + I` | _Italic_          |
| `Ctrl + U` | Underline         |
| `Ctrl + S` | ~~Strikethrough~~ |

All formatting uses Markdown syntax (underline uses `__text__`). Shortcuts work on selected text or toggle the format on/off while typing.

### Media & Display

- **Attach files** — paste from clipboard, drag onto the message box, or use the paperclip button; any file type is accepted
- **Images** are displayed inline; all other file types appear as a download link showing the original filename
- **File size limit** — configurable per-upload maximum (default 25 MB); the browser warns before attempting an oversized upload
- **Font size** — pinch (mobile) or `Ctrl + Scroll` (desktop); preference is saved across sessions

---

## Security

- Passwords are salted and hashed with PBKDF2 via Werkzeug — no plaintext or bare SHA-256 storage
- Password complexity is enforced on both frontend and backend (8+ characters, uppercase, number, special character)
- All database queries use parameterized statements — no SQL injection surface
- Each user has an isolated SQLite database; channel history is shared only through controlled writes
- SAST scanning via [Bandit](https://bandit.readthedocs.io/), [Semgrep](https://semgrep.dev/), [CodeQL](https://codeql.github.com/), and [SonarCloud](https://sonarcloud.io/) in CI
- Dependency vulnerabilities audited on every push with [pip-audit](https://github.com/pypa/pip-audit)
- Flask debug mode is disabled in production

---

## FAQ

**Are messages encrypted?**

Messages are not end-to-end encrypted. Each user's data lives in a SQLite file on the server filesystem. These files are not world-readable, but an administrator with filesystem access can read/audit them. Treat this as an internal LAN tool, not a secure messenger.

**What if a user forgets their password?**

An administrator can generate a one-time reset link from the command line:

```bash
minimost reset-password <username>
```

This prints a URL valid for 60 minutes (configurable with `--expires`) and sends the user an in-app notification via a system DM. Share the URL with the user through another channel (email, phone, etc.). When they open it, they can set a new password. The link expires after use or when the timer runs out — whichever comes first. Run `minimost reset-password --help` for all options.

**Does it have feature X from Slack/Discord/Mattermost?**

Probably not. Those products have hundreds of engineers and years of development. MiniMost is intentionally minimal — the goal is something that runs anywhere with zero infrastructure overhead.
