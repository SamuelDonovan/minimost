<img src="src/minimost/static/minimost-logo.svg" alt="MiniMost" width="360">

---

[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![security: bandit](https://img.shields.io/badge/security-bandit-yellow.svg)](https://github.com/PyCQA/bandit)
[![security: semgrep](https://img.shields.io/badge/security-semgrep-green.svg)](https://semgrep.dev/)
[![CodeQL](https://github.com/SamuelDonovan/minimost/actions/workflows/codeql.yml/badge.svg)](https://github.com/SamuelDonovan/minimost/actions/workflows/codeql.yml)

**MiniMost** is a lightweight, self-hosted chat platform built for private networks. It runs entirely on Python and SQLite — no external database, no root access, no infrastructure required. Just Flask and a browser.

---

## Features

- **Channels & Direct Messages** — public channels (configurable) and private one-on-one DMs
- **Message history** — persistent, searchable, and visible to new users from day one
- **Replies & threading** — quote any message to reply in context
- **Editing & deletion** — edit or delete your own messages; changes propagate in real time
- **Emoji reactions** — react to any message; reactions sync across all users instantly
- **Read receipts** — see who has read your messages
- **Presence indicators** — active, idle, away, and offline states updated automatically
- **Image attachments** — paste, drag-and-drop, or use the paperclip button; images auto-delete after 30 days
- **Desktop & sound notifications** — configurable per session, mutable with one click
- **Mobile responsive** — full drawer sidebar, touch-friendly layout, pinch-to-zoom font sizing
- **Dark theme** — easy on the eyes
- **Password security** — salted hashes (PBKDF2), enforced complexity requirements

---

## Requirements

- Python 3.6+
- Flask (`pip install flask`)

That's it. SQLite is part of the Python standard library.

---

## Installation

### From source

```bash
git clone https://github.com/SamuelDonovan/minimost.git
cd minimost
pip install -e .
```

### Dependencies only (no internet access)

Download the Flask wheel and its dependencies, then:

```bash
pip install --user *.whl
```

> On Windows, use `py` instead of `python3` / `pip`.

---

## Running

```bash
minimost
```

Or without installing:

```bash
python3 -m minimost
```

The server starts at [http://127.0.0.1:5000](http://127.0.0.1:5000) by default. Use `--host` and `--port` to change the bind address:

```bash
# Listen on all interfaces (accessible from other machines on the network)
minimost --host 0.0.0.0

# Listen on a specific IP and port
minimost --host 192.168.1.10 --port 8080
```

To reach the server from another machine, navigate to `http://<server-ip>:<port>` in a browser.

### Production deployment

The built-in Flask server is suitable for development and small private networks. For a more robust deployment, run MiniMost behind a WSGI server such as Gunicorn:

```bash
pip install gunicorn
gunicorn "minimost:create_app()" --workers 4 --bind 0.0.0.0:5000
```

### Configuring channels

Edit `channels.json` in the project root to define your public channels:

```json
["general", "software", "firmware", "off-topic"]
```

---

## Keyboard Shortcuts

### Messaging

| Key | Action |
|-----|--------|
| `Enter` | Send message |
| `Shift + Enter` | New line |
| `Esc` | Unfocus input / close menus |

### Navigation

| Key | Action |
|-----|--------|
| `i` | Focus message input |
| `o` | Start a new DM |
| `/` or `f` | Search messages |
| `j` / `k` | Scroll down / up |
| `d` / `u` | Scroll down / up (2×) |
| `G` | Jump to bottom |
| `gg` | Jump to top |
| `Ctrl + J` / `Ctrl + K` | Next / previous channel |
| `?` | Open help menu |

### Text Formatting

| Key | Action |
|-----|--------|
| `Ctrl + B` | **Bold** |
| `Ctrl + I` | *Italic* |
| `Ctrl + U` | Underline |
| `Ctrl + S` | ~~Strikethrough~~ |

All formatting uses Markdown syntax (underline uses `__text__`). Shortcuts work on selected text or toggle the format on/off while typing.

### Media & Display

- **Attach images** — paste from clipboard, drag onto the message box, or use the paperclip button
- **Font size** — pinch (mobile) or `Ctrl + Scroll` (desktop); preference is saved across sessions

---

## Security

- Passwords are salted and hashed with PBKDF2 via Werkzeug — no plaintext or bare SHA-256 storage
- Password complexity is enforced on both frontend and backend (8+ characters, uppercase, number, special character)
- All database queries use parameterized statements — no SQL injection surface
- Each user has an isolated SQLite database; channel history is shared only through controlled writes
- SAST scanning via [Bandit](https://bandit.readthedocs.io/) and [CodeQL](https://codeql.github.com/) in CI
- Flask debug mode is disabled in production

---

## FAQ

**Are messages encrypted?**

Messages are not end-to-end encrypted. Each user's data lives in a SQLite file on the server filesystem. These files are not world-readable, but an administrator with filesystem access can read/audit them. Treat this as an internal LAN tool, not a secure messenger.

**What if a user forgets their password?**

There is no self-service password reset. An administrator would need to update the password hash directly in `auth.db`.

**Does it have feature X from Slack/Discord/Mattermost?**

Probably not. Those products have hundreds of engineers and years of development. MiniMost is intentionally minimal — the goal is something that runs anywhere with zero infrastructure overhead. If you want a feature, open a PR.

**Can I run this on Windows?**

Yes. Replace `python3` with `py` and `pip` with `py -m pip`. Everything else is the same.

