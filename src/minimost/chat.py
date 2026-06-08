"""
minimost.chat
=============

Core messaging routes: sending, receiving, editing, deleting, reacting, and
serving uploaded files.

This is the largest module in MiniMost and contains all business logic for
the chat interface, including:

* **Channel management helpers** — resolving participants, validating access
  for public channels, DMs, and private channels.
* **Message CRUD** — sending, fetching (with polling support), editing, and
  soft-deleting messages across every recipient's database simultaneously.
* **Reactions** — toggle emoji reactions stored atomically in the shared
  ``presence.db``.
* **Read receipts** — mark messages as read and query who has read them.
* **File serving** — authenticated delivery of image attachments.
* **Search** — full-text ``LIKE`` search across a user's message history.
* **Link previews** — delegate to :mod:`minimost.preview`.
* **Private channels** — create invite-only channels, manage membership, and
  rename channels.  Private channel state (membership, channel metadata) is
  stored in the shared ``presence.db`` so every member sees the same view.
  Private channels are identified throughout the app as ``"private:<id>"``
  where ``<id>`` is the auto-increment primary key from the
  ``private_channels`` table.

Module-level attributes
-----------------------
chat_bp : flask.Blueprint
    The Flask Blueprint that groups all chat-related routes.  Registered in
    :func:`minimost.create_app`.

ALLOWED_EXTENSIONS : set
    File extensions accepted for image uploads:
    ``{".jpg", ".jpeg", ".png", ".gif", ".webp"}``.

UPLOAD_DIR : pathlib.Path
    Absolute path to the ``uploads/`` directory where image attachments are
    stored.  Created at import time if it does not exist.

CHANNELS : list of str
    Public channel names loaded from ``channels.json`` at startup.  Defaults
    to ``["general"]`` if the file is absent or malformed.

VALID_REACTIONS : set of str
    Set of valid reaction emoji names, derived from the SVG filenames in
    ``static/reactions/``.  Only names in this set are accepted by the
    ``/react/<msg_id>`` endpoint.
"""

# From the python standard library
from time import time
import sqlite3
import os
import re
import uuid
import json
from pathlib import Path
from typing import List, Optional

# From Flask
from flask import (
    abort,
    request,
    jsonify,
    render_template,
    send_from_directory,
    session,
    Blueprint,
)
from werkzeug.utils import secure_filename as _secure_filename
from werkzeug.security import check_password_hash

# Local Imports
from . import common
from . import presence
from . import auth
from . import preview as preview_mod

chat_bp = Blueprint("chat", __name__)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


def _max_upload_size_bytes() -> int:
    """Return the configured max upload size in bytes (default 25 MiB)."""
    try:
        data = json.loads(_SETTINGS_FILE.read_text())
        value = data.get("max_upload_size_mb")
        if isinstance(value, (int, float)) and value > 0:
            return int(value * 1024 * 1024)
    except (OSError, json.JSONDecodeError):
        pass
    return 25 * 1024 * 1024


def _check_upload_sizes(files, max_bytes: int):
    """Return an error tuple if any file exceeds *max_bytes*, else ``None``."""
    for f in files:
        if not hasattr(f, "filename") or not f.filename:
            continue
        f.stream.seek(0, 2)
        size = f.stream.tell()
        f.stream.seek(0)
        if size > max_bytes:
            mb = max_bytes // (1024 * 1024)
            return f"file too large (max {mb} MB)", 413
    return None


def _max_avatar_size_bytes() -> int:
    """Return the configured max avatar size in bytes (default 5 MiB)."""
    try:
        data = json.loads(_SETTINGS_FILE.read_text())
        value = data.get("max_avatar_size_mb")
        if isinstance(value, (int, float)) and value > 0:
            return int(value * 1024 * 1024)
    except (OSError, json.JSONDecodeError):
        pass
    return 5 * 1024 * 1024


_WAL = "PRAGMA journal_mode=WAL"
_SQL_AVATAR = "SELECT avatar_file FROM user_settings WHERE username = ?"
_SQL_ENSURE_SETTINGS = "INSERT OR IGNORE INTO user_settings (username) VALUES (?)"
_MSG_LOOKUP_SQL = "SELECT channel, sender, ts FROM messages WHERE id = ?"
_INSERT_MSG_SQL = (
    "INSERT INTO messages (channel, sender, content, content_type, ts)"
    " VALUES (?, ?, ?, ?, ?)"
)

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent.parent

UPLOAD_DIR = _PROJECT_ROOT / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

AVATAR_DIR = _PROJECT_ROOT / "avatars"
AVATAR_DIR.mkdir(exist_ok=True)

# settings.json is bundled inside the package (src/minimost/) so it ships in
# the wheel; _HERE is the package directory.
_SETTINGS_FILE = _HERE / "settings.json"


def _load_channels() -> List[str]:
    """Load the list of public channels from ``settings.json``.

    Reads and parses ``settings.json`` from the project root and returns the
    value of the ``"channels"`` key.  Falls back to a single ``"general"``
    channel if the file is absent, malformed, or missing the key.

    :returns: Ordered list of public channel name strings.
    :rtype: list of str
    """
    try:
        data = json.loads(_SETTINGS_FILE.read_text())
        channels = data.get("channels")
        if isinstance(channels, list) and channels:
            return channels
    except (OSError, json.JSONDecodeError):
        pass
    return ["general"]


CHANNELS = _load_channels()
MAX_CHANNEL_NAME_LEN = 80

# Matches an ``@username`` mention.  The negative lookbehind for word
# characters, ``@`` and ``/`` prevents matching inside email addresses
# (``foo@bar``) and URLs (``.../@handle``).  Username charset mirrors the
# ``[A-Za-z0-9_-]`` rule enforced at signup (see auth._USERNAME_RE).
_MENTION_RE = re.compile(r"(?<![\w@/])@([A-Za-z0-9_-]+)")

# Reserved keyword: ``@everyone`` mentions the whole channel.  Stored as a
# sentinel in the ``mentions`` column instead of expanding to the (possibly
# large, possibly stale) member list.  Usernames can never collide with it
# because ``@`` is not a legal username character.
MENTION_EVERYONE = "@everyone"


def extract_mentions(text: str, channel: str) -> List[str]:
    """Return the channel members that are ``@``-mentioned in *text*.

    Parses every ``@name`` token out of *text* and keeps only those that
    resolve (case-insensitively) to an actual member of *channel*.  The
    returned usernames use their canonical (stored) casing, in channel
    membership order.  Returns ``[]`` when *text* is empty or contains no
    valid mentions.

    The reserved keyword ``@everyone`` mentions the whole channel; when it is
    present the single-element list ``[MENTION_EVERYONE]`` is returned
    regardless of any other tokens, since it already covers every member.

    :param text: The raw message body.
    :type text: str
    :param channel: The channel the message is being posted to.
    :type channel: str
    :returns: Canonical usernames of mentioned channel members, or
        ``[MENTION_EVERYONE]`` for a channel-wide mention.
    :rtype: list of str
    """
    if not text:
        return []
    found = {name.lower() for name in _MENTION_RE.findall(text)}
    if not found:
        return []
    if "everyone" in found:
        return [MENTION_EVERYONE]
    return [u for u in channel_users(channel) if u.lower() in found]


def _mentions_json(text: str, channel: str):
    """Return a JSON-encoded mention list for *text*, or ``None`` if empty."""
    mentions = extract_mentions(text, channel)
    return json.dumps(mentions) if mentions else None


def _opt_float(value):
    """Parse *value* as a float, returning ``None`` for empty/invalid input.

    Used to coerce optional numeric query-string parameters (e.g. the search
    date bounds) without raising on absent or malformed values.

    :param value: The raw query-string value, or ``None``.
    :returns: The parsed float, or ``None`` if *value* is missing or invalid.
    :rtype: float or None
    """
    if not value:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _get_private_db():
    """Return an open WAL connection to the shared ``presence.db``.

    Configures the connection with WAL journal mode and ``sqlite3.Row``
    row factory so columns are accessible by name.  The caller is
    responsible for closing the returned connection.

    :returns: An open SQLite connection to ``presence.db``.
    :rtype: sqlite3.Connection
    """
    pdb = sqlite3.connect(presence.PRESENCE_DB)
    pdb.execute(_WAL)
    pdb.row_factory = sqlite3.Row
    return pdb


def get_private_channel_members(channel_id: int) -> List[str]:
    """Return the list of usernames that are members of a private channel.

    Queries the ``private_channel_members`` table in ``presence.db`` for
    all rows matching *channel_id* and returns the corresponding usernames.
    Returns an empty list if the channel does not exist or has no members.

    :param channel_id: The integer primary key of the private channel.
    :type channel_id: int
    :returns: Usernames of all current members, in insertion order.
    :rtype: list of str
    """
    pdb = _get_private_db()
    rows = pdb.execute(
        "SELECT username FROM private_channel_members WHERE channel_id = ?",
        (channel_id,),
    ).fetchall()
    pdb.close()
    return [r[0] for r in rows]


def get_db(username: Optional[str] = None):
    """Open and return a connection to the shared message database.

    The connection is configured with:

    * **WAL journal mode** — readers (the 500 ms pollers) never block the single
      writer, so many users can read concurrently while one message is written.
    * **``row_factory = sqlite3.Row``** — rows can be accessed by column name
      (e.g. ``row["sender"]``) in addition to integer index.

    The caller is responsible for closing the returned connection.

    :param username: Ignored. Retained so existing call sites that passed a
        username (from the former per-user-database model) keep working.
    :returns: An open SQLite database connection to the shared database.
    :rtype: sqlite3.Connection

    Example::

        db = get_db()
        rows = db.execute("SELECT * FROM messages WHERE channel = ?", ("general",)).fetchall()
        db.close()
    """
    db = sqlite3.connect(str(common.shared_db_path()))
    db.execute(_WAL)
    db.row_factory = sqlite3.Row
    return db


def _advance_read(db, user: str, channel: str, ts: float) -> None:
    """Move *user*'s read watermark for *channel* forward to at least *ts*.

    The watermark only ever advances — a stale concurrent write can't rewind it
    — so unread counts and read receipts stay monotonic.
    """
    db.execute(
        "INSERT INTO read_state (user, channel, last_read_ts) VALUES (?, ?, ?) "
        "ON CONFLICT(user, channel) DO UPDATE SET "
        "last_read_ts = MAX(last_read_ts, excluded.last_read_ts)",
        (user, channel, ts),
    )


def _history_start(channel: str, user: str):
    """Return the timestamp before which *user* may not see *channel*'s history.

    Private-channel members added after creation get a ``history_start_ts`` so
    they don't see the backlog. Returns ``None`` when there is no cutoff (public
    channels, DMs, founding members).
    """
    if not channel.startswith("private:"):
        return None
    try:
        channel_id = int(channel.split(":")[1])
    except (ValueError, IndexError):
        return None
    pdb = _get_private_db()
    row = pdb.execute(
        "SELECT history_start_ts FROM private_channel_members "
        "WHERE channel_id = ? AND username = ?",
        (channel_id, user),
    ).fetchone()
    pdb.close()
    return row["history_start_ts"] if row else None


def _search_access(user):
    """Build the channel-access filter for a shared-database search.

    Returns ``(clause, params, history_starts)`` where *clause* restricts a
    ``messages m`` query to channels *user* may read — public channels, the
    private channels they belong to, and their own DMs — and *history_starts*
    maps a private channel to the timestamp before which the user must not see
    its backlog (so late joiners can't search history from before they joined).
    """
    allowed = list(CHANNELS)
    history_starts = {}
    pdb = _get_private_db()
    rows = pdb.execute(
        "SELECT channel_id, history_start_ts FROM private_channel_members "
        "WHERE username = ?",
        (user,),
    ).fetchall()
    pdb.close()
    for r in rows:
        ch = f"private:{r['channel_id']}"
        allowed.append(ch)
        if r["history_start_ts"] is not None:
            history_starts[ch] = r["history_start_ts"]

    placeholders = ",".join("?" * len(allowed)) if allowed else "NULL"
    clause = (
        f"(m.channel IN ({placeholders})"
        " OR m.channel LIKE 'dm:' || ? || ':%'"
        " OR m.channel LIKE 'dm:%:' || ?"
        " OR m.channel LIKE 'dm:%:' || ? || ':%')"
    )
    return clause, [*allowed, user, user, user], history_starts


def all_users() -> List[str]:
    """Return a list of every registered username.

    Queries the shared ``auth.db`` database and returns every username in
    the ``users`` table.  The order is undefined (SQLite row insertion order).

    This is used to determine the recipient list when sending a message to a
    public channel — every registered user receives a copy of every public
    channel message.

    :returns: List of usernames for all registered accounts.
    :rtype: list of str
    """
    db = sqlite3.connect(auth.AUTH_DB)
    db.execute(_WAL)
    rows = db.execute("SELECT username FROM users").fetchall()
    db.close()
    return [r[0] for r in rows]


def normalize_dm(users: List[str]) -> str:
    """Return the canonical DM channel identifier for a set of participants.

    DM channels are identified by the string ``"dm:"`` followed by the
    sorted, colon-separated participant usernames.  Sorting ensures that
    ``normalize_dm(["bob", "alice"])`` and ``normalize_dm(["alice", "bob"])``
    both return the same string, preventing duplicate conversations from
    being created with different orderings.

    :param users: List of usernames that are participants in the DM.
        Duplicates are removed before sorting.
    :type users: list of str
    :returns: Canonical DM channel string, e.g. ``"dm:alice:bob"``.
    :rtype: str

    Example::

        normalize_dm(["charlie", "alice"])
        # returns "dm:alice:charlie"
    """
    users = sorted(set(users))
    return "dm:" + ":".join(users)


def channel_users(channel: str) -> List[str]:
    """Return the list of users who should receive messages on a channel.

    * For **DM channels** (``"dm:user1:user2:..."``): the participants are
      parsed directly from the channel string.
    * For **private channels** (``"private:<id>"``): the member list is
      fetched from the ``private_channel_members`` table in ``presence.db``
      via :func:`get_private_channel_members`.  Returns ``[]`` if the
      channel ID is invalid.
    * For **public channels**: every registered user is a recipient, so
      :func:`all_users` is called.

    This list is used by the send, edit, delete, and react routes to
    determine which per-user databases must be updated.

    :param channel: The channel name, DM identifier, or private channel
        identifier (``"private:<id>"``).
    :type channel: str
    :returns: List of usernames that are members of *channel*.
    :rtype: list of str

    Example::

        channel_users("dm:alice:bob")     # ["alice", "bob"]
        channel_users("private:3")        # members of private channel 3
        channel_users("general")          # all registered users
    """
    if channel.startswith("dm:"):
        return channel.split(":")[1:]
    if channel.startswith("private:"):
        try:
            return get_private_channel_members(int(channel.split(":")[1]))
        except (ValueError, IndexError):
            return []
    return all_users()


def is_valid_channel(channel: str, user: str) -> bool:
    """Return ``True`` only if *user* is permitted to access *channel*.

    Three access rules apply:

    * **DM channels** — the channel string must have at least two
      participants (``len(parts) >= 3``) and *user* must be one of them.
    * **Private channels** — *user* must appear in the
      ``private_channel_members`` table for the given channel ID (looked up
      via :func:`get_private_channel_members`).  Returns ``False`` if the
      ID is malformed or the channel does not exist.
    * **Public channels** — *channel* must appear in the :data:`CHANNELS`
      list loaded from ``channels.json``.

    This function is called by the :func:`send` route before writing any
    data, and is the primary authorization check for channel access.

    :param channel: The channel name, DM identifier, or private channel
        identifier (``"private:<id>"``).
    :type channel: str
    :param user: The username attempting to access the channel.
    :type user: str
    :returns: ``True`` if access is permitted, ``False`` otherwise.
    :rtype: bool

    Example::

        is_valid_channel("dm:alice:bob", "alice")    # True
        is_valid_channel("dm:alice:bob", "charlie")  # False
        is_valid_channel("private:3", "alice")       # True if alice is a member
        is_valid_channel("general", "alice")         # True (if "general" in CHANNELS)
        is_valid_channel("secret", "alice")          # False (not in CHANNELS)
    """
    if channel.startswith("dm:"):
        parts = channel.split(":")
        return len(parts) >= 3 and user in parts[1:]
    if channel.startswith("private:"):
        try:
            return user in get_private_channel_members(int(channel.split(":")[1]))
        except (ValueError, IndexError):
            return False
    return channel in CHANNELS


@chat_bp.route("/channels", methods=["GET"])
@auth.login_required
def channels():
    """Return the list of public channel names.

    Route: ``GET /channels``

    Requires authentication.  Returns the :data:`CHANNELS` list that was
    loaded from ``channels.json`` at application startup.  The client uses
    this list to build the channel sidebar.

    :returns: JSON array of channel name strings,
        e.g. ``["general", "software", "off-topic"]``.
    :rtype: flask.Response (application/json)
    """
    return jsonify(CHANNELS)


@chat_bp.route("/channel_unreads", methods=["GET"])
@auth.login_required
def channel_unreads():
    """Return unread message counts for every public channel.

    Route: ``GET /channel_unreads``

    Requires authentication.  Queries the current user's database and counts
    messages that are unread (``read = 0``), not sent by the user
    (``sender != user``), and not deleted (``deleted = 0``), grouped by
    public channel.

    All channels in :data:`CHANNELS` are included in the response — those
    with no unread messages are returned with a count of ``0``.

    :returns: JSON object mapping each public channel name to its unread
        count, e.g. ``{"general": 3, "software": 0, "off-topic": 1}``.
    :rtype: flask.Response (application/json)
    """
    user = session["user"]
    db = get_db()
    placeholders = ",".join("?" * len(CHANNELS))
    sql = (
        "SELECT m.channel AS channel, COUNT(*) AS count "  # nosec B608
        "FROM messages m "
        "LEFT JOIN read_state r ON r.user = ? AND r.channel = m.channel "
        f"WHERE m.channel IN ({placeholders}) AND m.sender != ? AND m.deleted = 0 "
        "AND m.ts > COALESCE(r.last_read_ts, 0) "
        "GROUP BY m.channel"
    )
    rows = db.execute(sql, (user, *CHANNELS, user)).fetchall()
    db.close()
    result = dict.fromkeys(CHANNELS, 0)
    for row in rows:
        result[row["channel"]] = row["count"]
    return jsonify(result)


@chat_bp.route("/unread_count", methods=["GET"])
@auth.login_required
def unread_count():
    """Return the total number of unread direct messages for the current user.

    Route: ``GET /unread_count``

    Requires authentication.  Counts all unread (``read = 0``) messages in DM
    channels (``channel LIKE 'dm:%'``) where the current user is a participant
    and the message was sent by someone else.

    The three ``LIKE`` patterns handle the three positions a username can
    occupy in a DM channel string:

    * ``dm:<user>:<others>`` — user is the first participant.
    * ``dm:<others>:<user>`` — user is the last participant.
    * ``dm:<others>:<user>:<more>`` — user is a middle participant (group DM).

    This count is displayed as a badge on the "DMs" section of the sidebar and
    drives the browser tab title badge.

    :returns: JSON object ``{"count": N}`` where *N* is the total unread DM
        message count.
    :rtype: flask.Response (application/json)
    """
    user = session["user"]
    db = get_db()

    row = db.execute(
        """
        SELECT COUNT(*) AS unread
        FROM messages m
        LEFT JOIN read_state r ON r.user = ? AND r.channel = m.channel
        WHERE m.channel LIKE 'dm:%'
          AND m.sender != ?
          AND m.deleted = 0
          AND m.ts > COALESCE(r.last_read_ts, 0)
          AND (
                m.channel LIKE 'dm:' || ? || ':%'
             OR m.channel LIKE 'dm:%:' || ?
             OR m.channel LIKE 'dm:%:' || ? || ':%'
          )
    """,
        (user, user, user, user, user),
    ).fetchone()

    count = row["unread"]
    db.close()
    return {"count": count}


@chat_bp.route("/dms", methods=["GET"])
@auth.login_required
def dms():
    """Return a summary of all DM conversations involving the current user.

    Route: ``GET /dms``

    Requires authentication.  Queries the current user's database for all DM
    channels, returning them sorted by most-recent message timestamp
    (``last_ts DESC``) so the sidebar list reflects activity order.

    For each conversation, the response includes:

    * ``channel`` — the canonical DM channel identifier (e.g.
      ``"dm:alice:bob"``).
    * ``users`` — list of the *other* participants (the current user is
      excluded so the client can display their names).
    * ``unread`` — count of unread messages from other users in this
      conversation.

    :returns: JSON array of conversation objects, each with keys ``channel``,
        ``users`` (list of str), and ``unread`` (int), ordered by most
        recent activity descending.
    :rtype: flask.Response (application/json)
    """
    user = session["user"]
    db = get_db()

    rows = db.execute(
        """
        SELECT
            m.channel,
            MAX(m.ts) AS last_ts,
            COALESCE(SUM(
                CASE
                    WHEN m.sender != ? AND m.deleted = 0
                         AND m.ts > COALESCE(rs.last_read_ts, 0)
                    THEN 1 ELSE 0
                END
            ), 0) AS unread
        FROM messages m
        LEFT JOIN dm_hidden dh ON dh.user = ? AND dh.channel = m.channel
        LEFT JOIN read_state rs ON rs.user = ? AND rs.channel = m.channel
        WHERE m.channel LIKE 'dm:%'
          AND (
                m.channel LIKE 'dm:' || ? || ':%'
             OR m.channel LIKE 'dm:%:' || ?
             OR m.channel LIKE 'dm:%:' || ? || ':%'
          )
        GROUP BY m.channel
        HAVING dh.hidden_ts IS NULL OR MAX(m.ts) > dh.hidden_ts
        ORDER BY last_ts DESC
    """,
        (user, user, user, user, user, user),
    ).fetchall()

    db.close()

    result = []
    for r in rows:
        users = r["channel"].split(":")[1:]
        others = [u for u in users if u != user]
        result.append(
            {
                "channel": r["channel"],
                "users": others,
                "unread": int(r["unread"]),
            }
        )

    return jsonify(result)


@chat_bp.route("/dms/close", methods=["POST"])
@auth.login_required
def close_dm():
    """Hide a DM conversation from the current user's sidebar.

    Route: ``POST /dms/close``

    JSON body: ``{"channel": str}``.  Records a ``hidden_ts`` timestamp for the
    channel; the ``/dms`` endpoint will exclude this conversation until a new
    message arrives after that timestamp.

    :returns: ``"ok"`` on success.
    :rtype: flask.Response
    """
    user = session["user"]
    data = request.get_json(silent=True) or {}
    dm_channel = (data.get("channel") or "").strip()
    if not dm_channel.startswith("dm:"):
        return "invalid channel", 400
    if user not in dm_channel.split(":")[1:]:
        return "forbidden", 403

    db = get_db()
    db.execute(
        "INSERT OR REPLACE INTO dm_hidden (user, channel, hidden_ts) VALUES (?, ?, ?)",
        (user, dm_channel, time()),
    )
    db.commit()
    db.close()
    return "ok"


_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


@chat_bp.route("/user_colors", methods=["GET"])
@auth.login_required
def user_colors():
    """Return custom name colors for all users who have set one.

    Route: ``GET /user_colors``

    :returns: JSON object mapping username to hex color string.
    :rtype: flask.Response (application/json)
    """
    db = sqlite3.connect(auth.AUTH_DB)
    db.execute(_WAL)
    rows = db.execute(
        "SELECT username, name_color FROM user_settings WHERE name_color IS NOT NULL"
    ).fetchall()
    db.close()
    return jsonify({r[0]: r[1] for r in rows})


@chat_bp.route("/settings", methods=["GET"])
@auth.login_required
def get_settings():
    """Return the current user's settings.

    Route: ``GET /settings``

    :returns: JSON object with user settings keys.
    :rtype: flask.Response (application/json)
    """
    user = session["user"]
    db = sqlite3.connect(auth.AUTH_DB)
    db.execute(_WAL)
    db.row_factory = sqlite3.Row
    row = db.execute(
        "SELECT name_color, bio FROM user_settings WHERE username = ?", (user,)
    ).fetchone()
    db.close()
    return jsonify(
        {
            "name_color": row["name_color"] if row else None,
            "bio": row["bio"] if row else None,
        }
    )


@chat_bp.route("/settings", methods=["POST"])
@auth.login_required
def save_settings():
    """Save the current user's settings.

    Route: ``POST /settings``

    JSON body: ``{"name_color": str | null}``.  Pass ``null`` to reset to the
    default hash-derived color.

    :returns: ``"ok"`` on success.
    :rtype: flask.Response
    """
    user = session["user"]
    data = request.get_json(silent=True) or {}

    name_color = data.get("name_color")
    if name_color is not None:
        name_color = name_color.strip()
        if not _COLOR_RE.match(name_color):
            return "invalid color", 400

    bio = data.get("bio")
    if bio is not None:
        bio = bio.strip()[:160]

    db = sqlite3.connect(auth.AUTH_DB)
    db.execute(_WAL)
    # Upsert without ON CONFLICT (SQLite >= 3.24) so this works on the older
    # SQLite that ships with some Python 3.6 systems.  INSERT OR IGNORE creates
    # the row if absent; the UPDATE then sets only these columns, preserving any
    # others (e.g. avatar_file).
    db.execute(_SQL_ENSURE_SETTINGS, (user,))
    db.execute(
        "UPDATE user_settings SET name_color = ?, bio = ? WHERE username = ?",
        (name_color, bio, user),
    )
    db.commit()
    db.close()
    return "ok"


@chat_bp.route("/profile/<username>", methods=["GET"])
@auth.login_required
def get_profile(username):
    db = sqlite3.connect(auth.AUTH_DB)
    db.execute(_WAL)
    db.row_factory = sqlite3.Row
    row = db.execute(
        "SELECT name_color, bio FROM user_settings WHERE username = ?", (username,)
    ).fetchone()
    db.close()
    return jsonify(
        {
            "username": username,
            "name_color": row["name_color"] if row else None,
            "bio": row["bio"] if row else None,
        }
    )


@chat_bp.route("/user_avatars", methods=["GET"])
@auth.login_required
def user_avatars():
    """Return usernames of all users who have a custom avatar.

    Route: ``GET /user_avatars``

    :returns: JSON array of usernames.
    :rtype: flask.Response (application/json)
    """
    db = sqlite3.connect(auth.AUTH_DB)
    db.execute(_WAL)
    rows = db.execute(
        "SELECT username FROM user_settings WHERE avatar_file IS NOT NULL"
    ).fetchall()
    db.close()
    return jsonify([r[0] for r in rows])


@chat_bp.route("/avatar/<username>", methods=["GET"])
@auth.login_required
def get_avatar(username):
    """Serve a user's avatar image.

    Route: ``GET /avatar/<username>``

    Returns 404 if the user has no custom avatar.

    :returns: Image file response or 404.
    :rtype: flask.Response
    """
    db = sqlite3.connect(auth.AUTH_DB)
    db.execute(_WAL)
    row = db.execute(_SQL_AVATAR, (username,)).fetchone()
    db.close()
    if not row or not row[0]:
        return "", 404
    return send_from_directory(AVATAR_DIR, row[0])


@chat_bp.route("/avatar", methods=["POST"])
@auth.login_required
def upload_avatar():
    """Upload and store the current user's avatar.

    Route: ``POST /avatar``

    Expects a multipart file named ``avatar`` (pre-resized client-side).
    Deletes the previous avatar file if one existed.

    :returns: ``"ok"`` on success.
    :rtype: flask.Response
    """
    user = session["user"]
    f = request.files.get("avatar")
    if not f or not f.filename:
        return "no file", 400

    f.stream.seek(0, 2)
    size = f.stream.tell()
    f.stream.seek(0)
    max_bytes = _max_avatar_size_bytes()
    if size > max_bytes:
        mb = max_bytes // (1024 * 1024)
        return f"file too large (max {mb} MB)", 413

    filename = f"{uuid.uuid4().hex}.jpg"
    f.save(AVATAR_DIR / filename)

    db = sqlite3.connect(auth.AUTH_DB)
    db.execute(_WAL)
    row = db.execute(_SQL_AVATAR, (user,)).fetchone()
    if row and row[0]:
        try:
            (AVATAR_DIR / row[0]).unlink()
        except FileNotFoundError:
            pass
    db.execute(_SQL_ENSURE_SETTINGS, (user,))
    db.execute(
        "UPDATE user_settings SET avatar_file = ? WHERE username = ?",
        (filename, user),
    )
    db.commit()
    db.close()
    return "ok"


@chat_bp.route("/avatar", methods=["DELETE"])
@auth.login_required
def delete_avatar():
    """Remove the current user's custom avatar.

    Route: ``DELETE /avatar``

    :returns: ``"ok"`` on success.
    :rtype: flask.Response
    """
    user = session["user"]
    db = sqlite3.connect(auth.AUTH_DB)
    db.execute(_WAL)
    row = db.execute(_SQL_AVATAR, (user,)).fetchone()
    if row and row[0]:
        try:
            (AVATAR_DIR / row[0]).unlink()
        except FileNotFoundError:
            pass
    db.execute(_SQL_ENSURE_SETTINGS, (user,))
    db.execute(
        "UPDATE user_settings SET avatar_file = NULL WHERE username = ?",
        (user,),
    )
    db.commit()
    db.close()
    return "ok"


def _apply_delete_to_messages(user, delete_type):
    """Anonymise (soft) or remove (hard) a departing user's messages.

    Acts on the single shared ``messages`` table. The FTS index follows
    automatically via its triggers (rename re-indexes; delete removes).
    """
    db = get_db()
    if delete_type == "soft":
        db.execute(
            "UPDATE messages SET sender = 'Deleted User' WHERE sender = ?", (user,)
        )
    else:
        db.execute("DELETE FROM messages WHERE sender = ?", (user,))
        db.execute("DELETE FROM reactions WHERE reactor = ?", (user,))
    db.execute("DELETE FROM read_state WHERE user = ?", (user,))
    db.execute("DELETE FROM dm_hidden WHERE user = ?", (user,))
    db.commit()
    db.close()


@chat_bp.route("/delete_account", methods=["POST"])
@auth.login_required
def delete_account():
    """Soft or hard delete the current user's account.

    Route: ``POST /delete_account``

    JSON body: ``{"type": "soft"|"hard", "password": "<current password>"}``

    **Soft delete** — removes the user's credentials and settings from
    ``auth.db``, renames their messages to ``"Deleted User"`` in every
    recipient's database, and deletes their avatar file.  Message history
    remains visible.

    **Hard delete** — performs the soft delete steps and additionally removes
    every message they sent from all recipient databases, deletes their own
    database file, and purges their records from ``presence.db``.

    In both cases the session is cleared and the client should redirect to
    the login page.

    :returns: JSON ``{"status": "ok"}`` on success, or an error response.
    :rtype: flask.Response (application/json)
    """
    user = session["user"]
    data = request.get_json(silent=True) or {}
    delete_type = data.get("type")
    password = data.get("password", "")

    if delete_type not in ("soft", "hard"):
        return jsonify({"error": "Invalid delete type."}), 400

    # Verify password before doing anything destructive
    adb = sqlite3.connect(auth.AUTH_DB)
    adb.execute(_WAL)
    row = adb.execute(
        "SELECT password_hash FROM users WHERE username = ?", (user,)
    ).fetchone()
    adb.close()

    if not row or not check_password_hash(row[0], password):
        return jsonify({"error": "Incorrect password."}), 403

    adb = sqlite3.connect(auth.AUTH_DB)
    adb.execute(_WAL)
    avatar_row = adb.execute(
        "SELECT avatar_file FROM user_settings WHERE username = ?", (user,)
    ).fetchone()
    adb.close()

    # Anonymise or remove the user's messages in the shared database, and drop
    # their read/hidden state.
    _apply_delete_to_messages(user, delete_type)

    # Clean presence.db for both delete types — removes the user from private
    # channel membership so they are no longer treated as a member.
    pdb = sqlite3.connect(presence.PRESENCE_DB)
    pdb.execute(_WAL)
    pdb.execute("DELETE FROM presence WHERE user = ?", (user,))
    pdb.execute("DELETE FROM typing WHERE user = ?", (user,))
    pdb.execute("DELETE FROM private_channel_members WHERE username = ?", (user,))
    pdb.execute("DELETE FROM call_participants WHERE username = ?", (user,))
    pdb.commit()
    pdb.close()

    # Delete avatar file
    if avatar_row and avatar_row[0]:
        try:
            (AVATAR_DIR / avatar_row[0]).unlink()
        except FileNotFoundError:
            pass

    # Remove from auth.db
    adb = sqlite3.connect(auth.AUTH_DB)
    adb.execute(_WAL)
    adb.execute("DELETE FROM users WHERE username = ?", (user,))
    adb.execute("DELETE FROM user_settings WHERE username = ?", (user,))
    adb.execute("DELETE FROM password_reset_tokens WHERE username = ?", (user,))
    adb.commit()
    adb.close()

    session.clear()
    return jsonify({"status": "ok"})


@chat_bp.route("/online_users", methods=["GET"])
@auth.login_required
def online_users():
    """Return presence states for all recently active users.

    Route: ``GET /online_users``

    Requires authentication.  Queries ``presence.db`` for any user whose
    ``last_seen`` timestamp is within the last 3600 seconds (one hour).
    Users who have not reported any presence update in that window are
    considered offline and excluded from the response.

    Possible state values returned: ``"active"``, ``"idle"``, ``"hidden"``,
    ``"offline"``.  States are lowercased before being returned.

    The client polls this endpoint once per second to refresh the colored
    presence indicator (dot) displayed next to each username in the sidebar.

    :returns: JSON object mapping username strings to their current presence
        state, e.g. ``{"alice": "active", "bob": "idle"}``.
    :rtype: flask.Response (application/json)
    """
    presence_timeout = 3600
    cutoff = int(time()) - presence_timeout
    db = sqlite3.connect(presence.PRESENCE_DB)
    db.execute(_WAL)
    db.row_factory = sqlite3.Row

    rows = db.execute(
        "SELECT user, state, override FROM presence WHERE last_seen >= ?",
        (cutoff,),
    ).fetchall()

    db.close()

    # A manual override (set in the account modal) wins over the live,
    # activity-derived state; otherwise fall back to the real state.
    return jsonify(
        {row["user"]: (row["override"] or row["state"]).lower() for row in rows}
    )


@chat_bp.route("/messages/<channel>", methods=["GET"])
@auth.login_required
def messages(channel):
    """Fetch messages for a channel since a given timestamp.

    Route: ``GET /messages/<channel>?after=<timestamp>``

    Requires authentication.  This is the core polling endpoint: the
    JavaScript client calls it every 500 ms, passing the timestamp of the
    last message it received as the ``after`` query parameter.  The server
    returns only rows that have changed since that point, keeping each
    response small.

    **What is returned:**

    A message row is included in the response if **any** of the following
    conditions are true since *after*:

    * It is a new, non-deleted message (``ts > after``).
    * It has been edited since *after* (``edited_ts > after``).
    * Its reactions have been updated since *after* (``reactions_ts > after``).
    * It was deleted after *after* (``deleted = 1 AND deleted_ts > after``).
      Deleted tombstones are returned so the client can remove the message
      from view.

    **Reactions enrichment:**

    After querying the user's database, the function fetches the current
    reactions for all returned messages from ``presence.db::message_reactions``
    and merges them into the response as a JSON string under the ``reactions``
    key.  This overwrites the stale ``reactions`` column from the user DB.

    **``after`` parameter handling:**

    * The string ``"NaN"`` (case-insensitive) is treated as ``0.0`` to guard
      against clients passing ``NaN`` on first load.
    * Non-numeric values are silently converted to ``0.0``.

    :param channel: The channel name or DM identifier.
    :type channel: str

    Query parameters:
        **after** (float, optional): Unix timestamp.  Only messages modified
        after this point are returned.  Defaults to ``0`` (return all
        messages).

    :returns: JSON array of message objects.  Each object has keys:
        ``id``, ``channel``, ``sender``, ``content``, ``filename``, ``ts``,
        ``edited``, ``edited_ts``, ``deleted``, ``deleted_ts``,
        ``reply_to_id``, ``reactions`` (JSON string or null),
        ``reactions_ts``.
    :rtype: flask.Response (application/json)
    """
    user = session["user"]

    # All messages now live in one shared database, so the channel-access check
    # that per-user databases gave us implicitly must be made explicit here.
    if not is_valid_channel(channel, user):
        return "forbidden", 403

    after_raw = request.args.get("after", "0")
    if after_raw.lower() == "nan":
        after = 0.0
    else:
        try:
            after = float(
                after_raw
            )  # nosemgrep: python.flask.security.injection.nan-injection.nan-injection
        except (ValueError, TypeError):
            after = 0.0

    # Members added to a private channel after creation don't see the backlog.
    hist_start = _history_start(channel, user)
    after = max(after, hist_start) if hist_start is not None else after

    db = get_db()
    rows = db.execute(
        """
        SELECT
            id,
            channel,
            sender,
            content,
            filename,
            ts,
            edited,
            edited_ts,
            deleted,
            deleted_ts,
            reply_to_id,
            reactions_ts,
            mentions
        FROM messages
        WHERE channel = ?
          AND (
                (deleted = 0 AND (ts > ? OR (edited_ts IS NOT NULL AND edited_ts > ?) OR reactions_ts > ?))
                OR (deleted = 1 AND deleted_ts > ?)
              )
        ORDER BY ts
    """,
        (channel, after, after, after, after),
    ).fetchall()

    result = [dict(r) for r in rows]

    if result:
        ids = [r["id"] for r in result]
        placeholders = ",".join("?" * len(ids))
        rx_rows = db.execute(
            f"SELECT message_id, emoji, reactor FROM reactions WHERE message_id IN ({placeholders})",  # nosec B608
            ids,
        ).fetchall()

        rx_map: dict = {}
        for message_id, emoji, reactor in rx_rows:
            rx_map.setdefault(message_id, {}).setdefault(emoji, []).append(reactor)

        for msg in result:
            reactions_dict = rx_map.get(msg["id"])
            msg["reactions"] = json.dumps(reactions_dict) if reactions_dict else None

    db.close()
    return jsonify(result)


def _insert_message(
    db, channel, sender, text, ts, reply_to_id, filenames, mentions=None
):
    """Insert a message (and/or its file attachments) as canonical rows.

    One row per text body and one per uploaded file, all in the single shared
    database. Does not commit or close — the caller owns the transaction.
    """
    if text:
        db.execute(
            "INSERT INTO messages (channel, sender, content, filename, ts, reply_to_id, mentions)"
            " VALUES (?, ?, ?, NULL, ?, ?, ?)",
            (channel, sender, text, ts, reply_to_id, mentions),
        )
    for filename in filenames:
        db.execute(
            "INSERT INTO messages (channel, sender, content, filename, ts, reply_to_id)"
            " VALUES (?, ?, '', ?, ?, ?)",
            (channel, sender, filename, ts, reply_to_id),
        )


def _try_append_message(db, channel, sender, text, ts, filenames, reply_to_id):
    """Append text to the sender's previous message if within the 300 s window.

    Returns True if appended; returns False if a new message is needed. Operates
    on the single canonical row, so the merge is one UPDATE. Does not commit.
    """
    if not text or filenames or reply_to_id is not None:
        return False
    prev = db.execute(
        """
        SELECT id, ts, content FROM messages
        WHERE channel = ? AND sender = ? AND deleted = 0
          AND filename IS NULL AND reply_to_id IS NULL
        ORDER BY ts DESC LIMIT 1
        """,
        (channel, sender),
    ).fetchone()
    if not prev or (ts - prev["ts"]) >= 300:
        return False
    combined = prev["content"] + "\n" + text
    mentions = _mentions_json(combined, channel)
    db.execute(
        "UPDATE messages SET content = ?, edited_ts = ?, mentions = ? WHERE id = ?",
        (combined, ts, mentions, prev["id"]),
    )
    return True


def post_welcome_message(new_user: str) -> None:
    """Post a system welcome message greeting a new user.

    Called from the signup flow when a new account is created.  Inserts a
    ``content_type = "system"`` message — rendered under the "MiniMost"
    identity, like other system notices — into the first public channel for
    every recipient (including the newcomer), so the whole community sees
    the new arrival being greeted.

    No-op if no public channels are configured.

    :param new_user: The username of the newly registered account.
    :type new_user: str
    :returns: None
    """
    if not CHANNELS:
        return
    channel = CHANNELS[0]
    content = f"Welcome to MiniMost, {new_user}! \U0001f44b Say hello \U0001f44b"
    db = get_db()
    db.execute(_INSERT_MSG_SQL, (channel, "system", content, "system", time()))
    db.commit()
    db.close()


@chat_bp.route("/send/<channel>", methods=["POST"])
@auth.login_required
def send(channel):
    """Send a message (and/or image attachments) to a channel.

    Route: ``POST /send/<channel>``

    Requires authentication.  Validates the channel, processes any uploaded
    images, then inserts the message into the shared message database.

    **Form fields:**

    * ``text`` (str, optional) — The message body.  Trailing whitespace is
      stripped.
    * ``reply_to_id`` (int, optional) — The ``id`` of the message being
      replied to.  Stored as a foreign key in the ``reply_to_id`` column.
    * ``files`` (multipart file list, optional) — One or more image files.
      Only files with extensions in :data:`ALLOWED_EXTENSIONS` are saved;
      others are silently skipped.

    At least one of *text* or *files* must be non-empty; a request with
    neither returns ``400 empty``.

    **Message storage:**

    Each message is one canonical row in the shared ``messages`` table:

    * A text body becomes one row; each uploaded image becomes an additional
      row (``content = ''`` with ``filename`` set to the UUID-based filename).
    * Consecutive short messages from the same sender within 300 s are merged
      into the previous row (see :func:`_try_append_message`).
    * The sender's read watermark for the channel is advanced to this message,
      so their own message never counts as unread.

    **File naming:**

    Uploaded images are saved as ``<uuid4hex><original_ext>`` in
    :data:`UPLOAD_DIR` to prevent collisions and avoid directory traversal
    via crafted filenames.

    :param channel: Target channel name or DM identifier.
    :type channel: str
    :returns: The string ``"ok"`` on success.
    :rtype: flask.Response

    :raises: ``403 forbidden`` — if the user is not permitted to post to the
        channel.
    :raises: ``400 empty`` — if neither text nor valid files were provided.
    """
    sender = session["user"]

    if not is_valid_channel(channel, sender):
        return "forbidden", 403

    text = (request.form.get("text") or "").rstrip()
    reply_to_id_raw = request.form.get("reply_to_id")
    try:
        reply_to_id = int(reply_to_id_raw) if reply_to_id_raw else None
    except (ValueError, TypeError):
        reply_to_id = None

    files = request.files.getlist("files")
    size_err = _check_upload_sizes(files, _max_upload_size_bytes())
    if size_err:
        return size_err

    filenames = _save_uploaded_files(files)

    if not text and not filenames:
        return "empty", 400

    ts = time()
    db = get_db()
    try:
        if not _try_append_message(
            db, channel, sender, text, ts, filenames, reply_to_id
        ):
            mentions = _mentions_json(text, channel)
            _insert_message(
                db, channel, sender, text, ts, reply_to_id, filenames, mentions
            )
        # The sender has implicitly read up to their own message.
        _advance_read(db, sender, channel, ts)
        db.commit()
    finally:
        db.close()

    return "ok"


@chat_bp.route("/message/<int:msg_id>", methods=["GET"])
@auth.login_required
def get_message(msg_id):
    """Fetch a single message by its database ID.

    Route: ``GET /message/<msg_id>``

    Requires authentication.  Used by the client to load the quoted parent
    message when rendering a reply thread, since the ``reply_to_id`` column
    stores only the ID rather than the full message content.

    The lookup is performed against the **current user's database**, which
    means the message must exist in that user's records.

    :param msg_id: The integer primary key of the message to retrieve.
    :type msg_id: int
    :returns: JSON object with keys ``id``, ``sender``, ``content``,
        ``filename``, and ``deleted``.
    :rtype: flask.Response (application/json)

    :raises: ``404 not found`` — if no message with *msg_id* exists in the
        current user's database.
    """
    db = get_db()
    row = db.execute(
        "SELECT id, sender, content, filename, deleted FROM messages WHERE id = ?",
        (msg_id,),
    ).fetchone()
    db.close()
    if not row:
        return "not found", 404
    return jsonify(dict(row))


@chat_bp.route("/files/<path:filename>", methods=["GET"])
@auth.login_required
def files(filename):
    """Serve an uploaded file.

    Route: ``GET /files/<filename>``

    Images are served inline; all other file types are served as attachments
    so the browser downloads rather than attempts to render them.
    """
    ext = Path(filename).suffix.lower()
    as_attachment = ext not in IMAGE_EXTENSIONS
    if as_attachment:
        # Strip the 32-char UUID prefix + underscore separator to recover the original name
        download_name = (
            filename[33:] if len(filename) > 33 and filename[32] == "_" else filename
        )
        return send_from_directory(
            UPLOAD_DIR, filename, as_attachment=True, download_name=download_name
        )
    return send_from_directory(UPLOAD_DIR, filename)


@chat_bp.route("/file_preview/<path:filename>", methods=["GET"])
@auth.login_required
def file_preview(filename):
    """Return a code preview for an uploaded text file.

    Route: ``GET /file_preview/<filename>``

    Reads the file from :data:`UPLOAD_DIR`, checks its extension against the
    known text-file extension set, and returns the same code-preview dict shape
    used by the Bitbucket preview routes.  Returns ``{}`` for unrecognised
    extensions or unreadable files.
    """
    safe_name = _secure_filename(filename)
    if not safe_name:
        abort(404)
    path = UPLOAD_DIR / safe_name

    # Strip the 32-char UUID prefix to recover the original filename — needed
    # both for the header and for matching special names (Makefile, Jenkinsfile)
    # whose stored form is prefixed and so never matches on its own.
    display_name = (
        filename[33:] if len(filename) > 33 and filename[32] == "_" else filename
    )

    if not preview_mod.is_text_filename(display_name):
        return jsonify({})

    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return jsonify({})

    result = preview_mod._build_code_result(
        raw, display_name, None, None, f"/files/{filename}"
    )
    return jsonify(result)


@chat_bp.route("/search_messages", methods=["GET"])
@auth.login_required
def search_messages():
    """Search the current user's message history by keyword.

    Route: ``GET /search_messages?q=<query>``

    Requires authentication.  Performs a case-insensitive substring search
    across the ``content`` column of the current user's ``messages`` table,
    excluding deleted messages.  The keyword match is served by the trigram
    FTS5 index (:func:`~minimost.common._ensure_search_index`) so it stays
    sub-millisecond regardless of history size; queries shorter than
    :data:`~minimost.common.SEARCH_MIN_TOKEN` characters, which the trigram
    index cannot serve, fall back to a plain ``LIKE`` scan.

    Results are returned in descending timestamp order (newest first) and
    limited to 50 rows to keep responses fast.  The search scope is the
    **current user's database only**, which means only messages that user has
    access to (including all public channels and their DMs) are searched.

    Query parameters (all optional, combined with ``AND``):
        **q** (str): Keyword matched as a case-insensitive ``LIKE`` substring
        of the message content.

        **from** (str): Restrict to messages from this sender (matched
        case-insensitively).

        **channel** (str): Restrict to a single channel identifier.

        **start** / **end** (float): Inclusive lower / exclusive upper bound
        on the message timestamp, as epoch seconds.  The client computes
        these from the picked dates using the viewer's local timezone.

    At least one filter must be supplied; a request with no filters returns
    ``[]`` without hitting the database, so an empty search box never dumps
    the whole history.

    :returns: JSON array of matching message objects, each with keys
        ``id``, ``channel``, ``sender``, ``content``, and ``ts``.
    :rtype: flask.Response (application/json)
    """
    user = session["user"]

    query = request.args.get("q", "").strip()
    sender = request.args.get("from", "").strip()
    channel = request.args.get("channel", "").strip()
    start_ts = _opt_float(request.args.get("start"))
    end_ts = _opt_float(request.args.get("end"))

    # An empty search box must never dump the whole history.
    if not (query or sender or channel or start_ts is not None or end_ts is not None):
        return jsonify([])

    # Filters on the base table. The `m.` alias matches both query shapes below.
    clauses = ["m.deleted = 0"]
    params = []
    if sender:
        clauses.append("m.sender = ? COLLATE NOCASE")
        params.append(sender)

    # Channel access control. With one shared database the search must be
    # confined to channels the user may read — a single explicit channel they
    # can access, or otherwise the full set of channels visible to them.
    history_starts = {}
    if channel:
        if not is_valid_channel(channel, user):
            return jsonify([])
        clauses.append("m.channel = ?")
        params.append(channel)
        hs = _history_start(channel, user)
        if hs is not None:
            history_starts[channel] = hs
    else:
        access_clause, access_params, history_starts = _search_access(user)
        clauses.append(access_clause)
        params.extend(access_params)

    if start_ts is not None:
        clauses.append("m.ts >= ?")
        params.append(start_ts)
    if end_ts is not None:
        clauses.append("m.ts < ?")
        params.append(end_ts)

    if query and len(query) >= common.SEARCH_MIN_TOKEN:
        # Trigram-indexed substring match: the MATCH is served from messages_fts
        # in sub-millisecond time however large the history is. Wrapping the query
        # in a quoted FTS5 phrase (doubling any embedded quote) makes it a literal
        # substring with no special-character handling, matching LIKE semantics.
        # `id` is AUTOINCREMENT and so monotonic with `ts`, so ordering by the FTS
        # rowid descending is newest-first and lets FTS5 stop after 50 rows
        # instead of sorting the full match set.
        match = '"' + query.replace('"', '""') + '"'
        sql = (
            "SELECT m.id, m.channel, m.sender, m.content, m.ts "  # nosec B608
            "FROM messages_fts f JOIN messages m ON m.id = f.rowid "
            "WHERE f.content MATCH ? AND " + " AND ".join(clauses) + " "
            "ORDER BY f.rowid DESC LIMIT 50"
        )
        params = [match, *params]
    else:
        # No keyword, or one too short for the trigram index (< 3 chars): a plain
        # scan. Only constant clause strings are concatenated; every user value is
        # bound via a ? placeholder, so this is not an injection vector.
        if query:
            clauses.append("m.content LIKE ?")
            params.append(f"%{query}%")
        sql = (
            "SELECT m.id, m.channel, m.sender, m.content, m.ts FROM messages m "  # nosec B608
            "WHERE " + " AND ".join(clauses) + " ORDER BY m.ts DESC LIMIT 50"
        )

    db = get_db()
    cur = db.execute(sql, params)
    results = [dict(r) for r in cur.fetchall()]
    db.close()

    # Hide private-channel backlog from members who joined later.
    if history_starts:
        results = [
            r
            for r in results
            if r["channel"] not in history_starts
            or r["ts"] >= history_starts[r["channel"]]
        ]

    return jsonify(results)


@chat_bp.route("/edit/<int:msg_id>", methods=["POST"])
@auth.login_required
def edit(msg_id):
    """Edit the text content of the current user's message.

    Route: ``POST /edit/<msg_id>``

    Requires authentication.  Only the original sender may edit a message;
    any other user's attempt returns ``403 forbidden``.

    Only text messages can be edited — rows with a non-null ``filename``
    (image attachments) are excluded from the ``UPDATE`` by the
    ``AND filename IS NULL`` clause.

    **Propagation:**

    The edit is applied to every recipient's copy of the message, matched by
    the combination of ``(channel, sender, ts)`` rather than by ``id``
    because row IDs differ between per-user databases.  The ``edited`` flag
    is set to ``1`` and ``edited_ts`` records when the edit occurred so the
    polling query (:func:`messages`) picks it up for other users.

    Form fields:
        **text** (str): The new message content.  Stripped of leading/trailing
        whitespace.

    :param msg_id: The integer ``id`` of the message to edit (in the
        current user's database).
    :type msg_id: int
    :returns: The string ``"ok"`` on success.
    :rtype: flask.Response

    :raises: ``403 forbidden`` — if the message does not belong to the
        current user or does not exist.
    """
    editor = session["user"]
    new_text = request.form.get("text", "").strip()

    db = get_db()
    row = db.execute(_MSG_LOOKUP_SQL, (msg_id,)).fetchone()

    if not row or row["sender"] != editor:
        db.close()
        return "forbidden", 403

    mentions = _mentions_json(new_text, row["channel"])
    db.execute(
        """
        UPDATE messages
        SET content = ?, edited = 1, edited_ts = ?, mentions = ?
        WHERE id = ? AND filename IS NULL
        """,
        (new_text, time(), mentions, msg_id),
    )
    db.commit()
    db.close()

    return "ok"


@chat_bp.route("/delete/<int:msg_id>", methods=["POST"])
@auth.login_required
def delete_message(msg_id):
    """Soft-delete the current user's message.

    Route: ``POST /delete/<msg_id>``

    Requires authentication.  Only the original sender may delete a message;
    other users receive ``403 forbidden``.

    **Soft delete, not hard delete:**

    The message row is *not* removed from the database.  Instead, ``deleted``
    is set to ``1`` and ``deleted_ts`` records when the deletion occurred.
    This allows the polling query (:func:`messages`) to return a tombstone
    to any client that has already cached the message, so they can remove it
    from their view.  The actual row is preserved for audit/admin purposes.

    **Propagation:**

    Like edits, the soft-delete is applied to every recipient's copy of the
    message, matched by ``(channel, sender, ts)``.

    :param msg_id: The integer ``id`` of the message to delete (in the
        current user's database).
    :type msg_id: int
    :returns: The string ``"ok"`` on success.
    :rtype: flask.Response

    :raises: ``403 forbidden`` — if the message was not sent by the current
        user or does not exist.
    """
    deleter = session["user"]

    db = get_db()
    row = db.execute(_MSG_LOOKUP_SQL, (msg_id,)).fetchone()

    if not row or row["sender"] != deleter:
        db.close()
        return "forbidden", 403

    db.execute(
        "UPDATE messages SET deleted = 1, deleted_ts = ? WHERE id = ?",
        (time(), msg_id),
    )
    db.commit()
    db.close()

    return "ok"


VALID_REACTIONS = {
    # Original set
    "airplane",
    "alien",
    "angry",
    "anguished",
    "apple",
    "archery",
    "astonished",
    "atom",
    "avocado",
    "axolotl",
    "balloon",
    "banana",
    "bandage",
    "basketball",
    "bat",
    "bear",
    "bee",
    "beer",
    "bell",
    "bento",
    "bicycle",
    "bomb",
    "book",
    "boxing",
    "brain",
    "bread",
    "broken_heart",
    "bug",
    "bulb",
    "burger",
    "butterfly",
    "cactus",
    "cake",
    "call_me",
    "camera",
    "candle",
    "canoe",
    "car",
    "cat",
    "champagne",
    "chart",
    "check",
    "chess",
    "chocolate",
    "clapper_board",
    "clap",
    "cloud",
    "clown",
    "cocktail",
    "coffee",
    "cold_face",
    "comet",
    "compass",
    "confounded",
    "cowboy",
    "crab",
    "cross_fingers",
    "crown",
    "crying",
    "crystal_ball",
    "curry",
    "dart",
    "desert",
    "devil",
    "die",
    "dinosaur",
    "dizzy",
    "dna",
    "dog",
    "donut",
    "dragon",
    "drum",
    "duck",
    "dumpling",
    "earth",
    "eyes",
    "fire",
    "fireworks",
    "fist",
    "flag",
    "flamingo",
    "flower",
    "flushed",
    "football",
    "four_leaf",
    "fox",
    "fries",
    "frog",
    "gaming",
    "gear",
    "gem",
    "ghost",
    "gift",
    "golf",
    "grapes",
    "grimace",
    "grinning",
    "guitar",
    "gun",
    "hammer",
    "handshake",
    "headphones",
    "hear_no_evil",
    "heart",
    "heart_black",
    "heart_blue",
    "heart_box",
    "heart_brown",
    "heart_eyes",
    "heart_green",
    "heart_grow",
    "heart_orange",
    "heart_pink",
    "heart_purple",
    "heart_white",
    "heart_yellow",
    "hedgehog",
    "helicopter",
    "hot_dog",
    "hot_face",
    "hourglass",
    "hugging",
    "ice_cream",
    "innocent",
    "island",
    "jellyfish",
    "joystick",
    "juice",
    "key",
    "laptop",
    "laugh",
    "lightning",
    "lion",
    "lock",
    "love_you",
    "magnet",
    "magnify",
    "mammoth",
    "map",
    "mask",
    "medal",
    "melting",
    "microphone",
    "microscope",
    "milk",
    "milky_way",
    "mind_blown",
    "money_mouth",
    "money",
    "monkey",
    "monocle",
    "moon",
    "mountain",
    "muscle",
    "mushroom",
    "music",
    "nauseated",
    "nerd",
    "neutral",
    "newspaper",
    "no",
    "octopus",
    "ok",
    "open_hands",
    "owl",
    "package",
    "palette",
    "palm_tree",
    "pancakes",
    "panda",
    "parrot",
    "partying",
    "party",
    "peace",
    "pencil",
    "penguin",
    "pensive",
    "persevere",
    "phone",
    "piano",
    "pig",
    "pill",
    "pinch",
    "pin",
    "pizza",
    "pleading",
    "point_down",
    "point_left",
    "point_right",
    "point_up",
    "poop",
    "popcorn",
    "pray",
    "rage",
    "rainbow",
    "raised_eyebrow",
    "raised_hands",
    "ramen",
    "recycle",
    "relieved",
    "revolving_hearts",
    "robot",
    "rocket",
    "rofl",
    "sad",
    "salute",
    "saturn",
    "scissors",
    "scream",
    "seal",
    "see_no_evil",
    "shark",
    "shield",
    "ship",
    "shrimp",
    "shushing",
    "ski",
    "skull",
    "sleeping",
    "slightly_smile",
    "sloth",
    "smile",
    "smirk",
    "snake",
    "sneezing",
    "snowflake",
    "soccer",
    "spaghetti",
    "sparkle",
    "sparkling_heart",
    "speak_no_evil",
    "star_struck",
    "star",
    "stethoscope",
    "strawberry",
    "sunflower",
    "sunglasses",
    "sun",
    "surf",
    "sushi",
    "sweat_smile",
    "swim",
    "taco",
    "tada",
    "target",
    "tea",
    "telescope",
    "tennis",
    "test_flask",
    "test_tube",
    "thinking",
    "thread",
    "thumbsdown",
    "thumbsup",
    "tongue",
    "toolbox",
    "tornado",
    "train",
    "trash",
    "triumph",
    "trophy",
    "trumpet",
    "turtle",
    "two_hearts",
    "ufo",
    "unicorn",
    "upside_down",
    "vampire",
    "violin",
    "volcano",
    "vulcan",
    "waffle",
    "warning",
    "watermelon",
    "wave",
    "whale",
    "wink",
    "wolf",
    "woozy",
    "worried",
    "wow",
    "wrench",
    "writing",
    "yarn",
    "yawn",
    "yoga",
    "zap",
    "zipper",
    "zombie",
    # More faces
    "expressionless",
    "no_mouth",
    "rolling_eyes",
    "hushed",
    "sleepy",
    "drooling",
    "lying",
    "exhaling",
    "holding_back_tears",
    "peeking",
    "hand_over_mouth",
    "dotted_face",
    "shaking_face",
    "diagonal_mouth",
    "heart_on_fire",
    "mending_heart",
    # More gestures
    "middle_finger",
    "backhand_up",
    "raised_back",
    "heart_hands",
    "left_fist",
    "right_fist",
    "splayed_hand",
    "palm_up",
    "palm_down",
    "point_at_you",
    # More animals
    "horse",
    "cow",
    "sheep",
    "goat",
    "rabbit",
    "hamster",
    "mouse",
    "chipmunk",
    "otter",
    "raccoon",
    "skunk",
    "gorilla",
    "elephant",
    "hippo",
    "giraffe",
    "camel",
    "zebra",
    "kangaroo",
    "koala",
    "deer",
    "llama",
    "peacock",
    "swan",
    "eagle",
    "dove",
    "rooster",
    "fish",
    "tropical_fish",
    "dolphin",
    "lobster",
    "squid",
    "snail",
    "worm",
    "oyster",
    "rhino",
    "crocodile",
    "microbe",
    # More food & drink
    "bagel",
    "croissant",
    "pretzel",
    "cheese",
    "egg",
    "bacon",
    "sandwich",
    "wrap",
    "salad",
    "soup",
    "salt",
    "honey",
    "lollipop",
    "candy",
    "bubble_tea",
    "ice",
    "mate",
    "fortune_cookie",
    "tamale",
    "flatbread",
    "beans",
    "blueberries",
    "mango",
    "kiwi",
    "pear",
    "peach",
    "cherry",
    "lemon",
    "tangerine",
    "pineapple",
    "melon",
    "tomato",
    "garlic",
    "onion",
    "carrot",
    "broccoli",
    "corn",
    "hot_pepper",
    # More sports & activities
    "baseball",
    "softball",
    "badminton",
    "rugby",
    "ping_pong",
    "flying_disc",
    "sled",
    "parachute",
    "martial_arts",
    "climbing",
    "weightlifting",
    "skateboard",
    "lacrosse",
    "ice_skate",
    "fishing",
    "diving",
    "cards",
    # More music
    "saxophone",
    "banjo",
    "accordion",
    "notes",
    "long_drum",
    # More vehicles
    "motorcycle",
    "race_car",
    "speedboat",
    "sailboat",
    "bus",
    "truck",
    "fire_truck",
    "ambulance",
    "tractor",
    "motor_scooter",
    # More nature & plants
    "seedling",
    "evergreen",
    "deciduous",
    "chestnut",
    "cherry_blossom",
    "rose",
    "tulip",
    "lotus",
    "bouquet",
    "wilted_flower",
    "herb",
    "maple_leaf",
    "leaves",
    "water_wave",
    "droplet",
    "fog",
    "cyclone",
    "umbrella",
    "snowman",
    "rainbow_flag",
    # More symbols & objects
    "hundred",
    "speech_bubble",
    "thought_bubble",
    "zzz",
    "anger",
    "red_circle",
    "blue_circle",
    "green_circle",
    "infinity",
    "syringe",
    "fire_extinguisher",
    "safety_pin",
    "broom",
    "soap",
    "nazar",
    "teddy_bear",
    "magic_wand",
    "kite",
    "yo_yo",
    "boomerang",
    "axe",
    "ladder",
    "mirror",
    "chair",
    "battery",
    "floppy",
    "cd",
    "globe",
    "satellite",
    # Celebrations & holidays
    "jack_o_lantern",
    "christmas_tree",
    "sparkler",
    "firecracker",
    "ribbon",
    "ticket",
}


def _save_uploaded_files(files) -> List[str]:
    """Save uploaded files of any type, returning their stored filenames.

    Images are stored as ``<uuid32hex><ext>``.
    All other files are stored as ``<uuid32hex>_<sanitized_original_name>``
    so the original name can be recovered by slicing off the first 33 chars.
    """
    filenames = []
    for f in files:
        if not hasattr(f, "filename") or not f.filename:
            continue
        ext = os.path.splitext(f.filename)[1].lower()
        uid = uuid.uuid4().hex
        if ext in IMAGE_EXTENSIONS:
            filename = f"{uid}{ext}"
        else:
            safe = _secure_filename(f.filename) or f"file{ext}"
            filename = f"{uid}_{safe}"
        f.save(UPLOAD_DIR / filename)
        filenames.append(filename)
    return filenames


@chat_bp.route("/react/<int:msg_id>", methods=["POST"])
@auth.login_required
def react(msg_id):
    """Toggle an emoji reaction on a message.

    Route: ``POST /react/<msg_id>``

    Requires authentication.  The reaction is **toggled**: if the current
    user has already reacted with this emoji, the reaction is removed;
    otherwise it is added.

    **Why the shared ``presence.db`` is used:**

    Reactions must be visible to all users instantly and without race
    conditions.  If reactions were stored in per-user databases, a
    read-modify-write cycle would be needed on each user's file — which
    creates TOCTOU races under concurrent requests.  Instead, the
    ``message_reactions`` table in ``presence.db`` is used with a single
    atomic ``INSERT OR DELETE`` operation.

    **Propagation to user databases:**

    After updating ``presence.db``, the function bumps the ``reactions_ts``
    column in every recipient's copy of the message.  This causes the
    polling query (:func:`messages`) to return the message row again for
    all users, and the client re-fetches the current reactions from the
    response.

    Form fields:
        **reaction** (str): The emoji name (SVG filename without extension)
        to toggle.  Must be a member of :data:`VALID_REACTIONS`.

    :param msg_id: The integer ``id`` of the message to react to (in the
        current user's database).
    :type msg_id: int
    :returns: JSON object mapping emoji names to lists of reactors, e.g.
        ``{"thumbs_up": ["alice", "bob"], "heart": ["charlie"]}``.
    :rtype: flask.Response (application/json)

    :raises: ``400 invalid reaction`` — if *reaction* is not in
        :data:`VALID_REACTIONS`.
    :raises: ``404 not found`` — if *msg_id* does not exist in the current
        user's database.
    """
    user = session["user"]
    reaction = request.form.get("reaction", "").strip()

    if reaction not in VALID_REACTIONS:
        return "invalid reaction", 400

    db = get_db()
    row = db.execute(_MSG_LOOKUP_SQL, (msg_id,)).fetchone()

    if not row:
        db.close()
        return "not found", 404

    # Toggle the reaction on the canonical message row. Reactions key on the real
    # message id, so this is a single atomic insert/delete — no per-user fan-out
    # and no read-modify-write race.
    existing = db.execute(
        "SELECT 1 FROM reactions WHERE message_id=? AND emoji=? AND reactor=?",
        (msg_id, reaction, user),
    ).fetchone()

    if existing:
        db.execute(
            "DELETE FROM reactions WHERE message_id=? AND emoji=? AND reactor=?",
            (msg_id, reaction, user),
        )
    else:
        db.execute(
            "INSERT INTO reactions (message_id, emoji, reactor) VALUES (?, ?, ?)",
            (msg_id, reaction, user),
        )

    # Bump reactions_ts so the polling query re-sends this row to every viewer.
    db.execute("UPDATE messages SET reactions_ts=? WHERE id=?", (time(), msg_id))

    rx_rows = db.execute(
        "SELECT emoji, reactor FROM reactions WHERE message_id=?", (msg_id,)
    ).fetchall()
    db.commit()
    db.close()

    reactions = {}
    for emoji, reactor in rx_rows:
        reactions.setdefault(emoji, []).append(reactor)

    return jsonify(reactions)


@chat_bp.route("/mark_read/<channel>", methods=["POST"])
@auth.login_required
def mark_read(channel):
    """Mark all messages in a channel as read for the current user.

    Route: ``POST /mark_read/<channel>``

    Requires authentication.  Called by the client whenever the user switches
    to a channel or scrolls to the bottom of the message list.

    **Two-step operation:**

    1. Collects the timestamps of every currently-unread message in the
       channel (sent by other users) so they can be recorded as read
       receipts.
    2. Sets ``read = 1`` for all messages in the channel that were not sent
       by the current user.

    **Read receipts:**

    After marking messages as read in the user's database, a row is inserted
    into ``presence.db::read_receipts`` for each previously-unread message
    timestamp.  ``INSERT OR IGNORE`` is used to avoid duplicate entries when
    the same message is read multiple times (e.g. the user switches to the
    channel, back, then returns).

    The client polls :func:`read_receipts` to display ``✓`` checkmarks and
    tooltips showing who has read each message.

    :param channel: The channel name or DM identifier.
    :type channel: str
    :returns: Empty body with HTTP 204 No Content.
    :rtype: flask.Response
    """
    user = session["user"]
    db = get_db()

    # Advance the read watermark to the newest message in the channel. Unread
    # counts and read receipts are both derived from this single per-(user,
    # channel) row, so there is no per-message write.
    row = db.execute(
        "SELECT MAX(ts) AS max_ts FROM messages WHERE channel = ?", (channel,)
    ).fetchone()
    if row and row["max_ts"] is not None:
        _advance_read(db, user, channel, row["max_ts"])
        db.commit()
    db.close()

    return "", 204


@chat_bp.route("/read_receipts/<channel>", methods=["GET"])
@auth.login_required
def read_receipts(channel):
    """Return each member's read watermark for a channel.

    Route: ``GET /read_receipts/<channel>``

    Requires authentication.  Returns the ``read_state`` watermarks for the
    channel: one ``last_read_ts`` per user. A user has read a given message iff
    their watermark is ``>=`` that message's ``ts``, so the client derives the
    per-message ``✓`` receipts itself from the message timestamps it already
    holds.

    This keeps the 3-second poll's payload and work proportional to the number
    of members (O(users)) rather than the channel's full history
    (O(messages × users)), which is what returning a per-message map would cost.

    :param channel: The channel name or DM identifier.
    :type channel: str
    :returns: JSON object mapping each reader's username to their read watermark
        (epoch seconds), e.g. ``{"alice": 1716000001.4, "bob": 1716000000.1}``.
    :rtype: flask.Response (application/json)
    """
    db = get_db()
    states = db.execute(
        "SELECT user, last_read_ts FROM read_state WHERE channel = ?", (channel,)
    ).fetchall()
    db.close()
    return jsonify({s["user"]: s["last_read_ts"] for s in states})


@chat_bp.route("/users", methods=["GET"])
@auth.login_required
def users():
    """Return a list of all registered users except the current user.

    Route: ``GET /users``

    Requires authentication.  Used by the client to populate the "New DM"
    autocomplete modal — the list shows all other accounts the user can
    start a conversation with.

    :returns: JSON array of username strings, excluding the currently
        logged-in user.
    :rtype: flask.Response (application/json)
    """
    me = session["user"]
    return jsonify([u for u in all_users() if u != me])


@chat_bp.route("/channel_members/<channel>", methods=["GET"])
@auth.login_required
def channel_members(channel):
    """Return the mentionable members of a channel (excluding the caller).

    Route: ``GET /channel_members/<channel>``

    Requires authentication and that the caller is permitted to access the
    channel.  Used by the client to populate the ``@``-mention autocomplete
    dropdown: for public channels this is every other registered user, for
    private channels the other members, and for DMs the other participants.

    :param channel: The channel name, DM identifier, or ``"private:<id>"``.
    :type channel: str
    :returns: JSON array of usernames the caller may mention, excluding
        themselves.
    :rtype: flask.Response (application/json)

    :raises: ``403 forbidden`` — if the caller may not access the channel.
    """
    user = session["user"]
    if not is_valid_channel(channel, user):
        return "forbidden", 403
    return jsonify([m for m in channel_users(channel) if m != user])


@chat_bp.route("/link_preview", methods=["GET"])
@auth.login_required
def link_preview():
    """Fetch a link preview card for a URL.

    Route: ``GET /link_preview?url=<url>``

    Requires authentication.  Delegates to
    :func:`minimost.preview.fetch_preview`, which supports Bitbucket Cloud,
    Bitbucket Server, and generic OpenGraph previews.

    An empty JSON object ``{}`` is returned if:

    * The ``url`` query parameter is missing or blank.
    * The URL is a private/internal IP address (SSRF protection).
    * The URL scheme is not ``http`` or ``https``.
    * The request fails or times out.
    * No usable preview data can be extracted.

    Query parameters:
        **url** (str): The fully-qualified URL to preview.

    :returns: A JSON object describing the preview.  Shape depends on the
        preview type:

        * **Code preview** (Bitbucket): ``{"type": "code", "filename": ...,
          "filepath": ..., "language": ..., "first_line_num": ...,
          "highlight_start": ..., "highlight_end": ..., "code": ...,
          "total_lines": ..., "url": ...}``
        * **OpenGraph preview**: ``{"type": "og", "title": ...,
          "description": ..., "image": ..., "domain": ..., "url": ...}``
        * **No preview**: ``{}``
    :rtype: flask.Response (application/json)
    """
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({})
    return jsonify(preview_mod.fetch_preview(url))


@chat_bp.route("/private_channels/create", methods=["POST"])
@auth.login_required
def create_private_channel():
    """Create a new private channel.

    Route: ``POST /private_channels/create``

    JSON body: ``{"name": str, "members": [str]}``.  The creator is always
    included as a member regardless of the list provided.

    :returns: JSON ``{"id": int, "channel": str, "name": str}`` on success.
    :rtype: flask.Response (application/json)
    """
    user = session["user"]
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    members = [m.strip() for m in (data.get("members") or []) if str(m).strip()]

    if not name:
        return "name required", 400

    if len(name) > MAX_CHANNEL_NAME_LEN:
        return f"channel name must be {MAX_CHANNEL_NAME_LEN} characters or fewer", 400

    if user not in members:
        members.append(user)

    now = time()
    pdb = _get_private_db()
    cur = pdb.execute(
        "INSERT INTO private_channels (name, created_by, created_ts) VALUES (?, ?, ?)",
        (name, user, now),
    )
    channel_id = cur.lastrowid
    pdb.executemany(
        "INSERT INTO private_channel_members (channel_id, username, joined_ts, history_start_ts) VALUES (?, ?, ?, NULL)",
        [(channel_id, m, now) for m in members],
    )
    pdb.commit()
    pdb.close()

    return jsonify({"id": channel_id, "channel": f"private:{channel_id}", "name": name})


@chat_bp.route("/private_channels", methods=["GET"])
@auth.login_required
def list_private_channels():
    """List private channels the current user is a member of.

    Route: ``GET /private_channels``

    :returns: JSON array of ``{"id", "channel", "name", "unread"}`` objects.
    :rtype: flask.Response (application/json)
    """
    user = session["user"]

    pdb = _get_private_db()
    rows = pdb.execute(
        """
        SELECT pc.id, pc.name
        FROM private_channels pc
        JOIN private_channel_members pcm ON pc.id = pcm.channel_id
        WHERE pcm.username = ?
        ORDER BY pc.id
        """,
        (user,),
    ).fetchall()
    pdb.close()

    result = []
    db = get_db()
    for row in rows:
        ch = f"private:{row['id']}"
        count = db.execute(
            "SELECT COUNT(*) AS c FROM messages m "
            "LEFT JOIN read_state r ON r.user = ? AND r.channel = m.channel "
            "WHERE m.channel = ? AND m.sender != ? AND m.deleted = 0 "
            "AND m.ts > COALESCE(r.last_read_ts, 0)",
            (user, ch, user),
        ).fetchone()["c"]
        result.append(
            {
                "id": row["id"],
                "channel": ch,
                "name": row["name"],
                "unread": count,
                "members": get_private_channel_members(row["id"]),
            }
        )
    db.close()

    return jsonify(result)


@chat_bp.route("/private_channels/<int:channel_id>/rename", methods=["POST"])
@auth.login_required
def rename_private_channel(channel_id):
    """Rename a private channel. Any member may rename.

    Route: ``POST /private_channels/<channel_id>/rename``

    JSON body: ``{"name": str}``.

    :returns: ``"ok"`` on success.
    :rtype: flask.Response
    """
    user = session["user"]
    if user not in get_private_channel_members(channel_id):
        return "forbidden", 403

    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return "name required", 400

    if len(name) > MAX_CHANNEL_NAME_LEN:
        return f"channel name must be {MAX_CHANNEL_NAME_LEN} characters or fewer", 400

    pdb = _get_private_db()
    pdb.execute("UPDATE private_channels SET name = ? WHERE id = ?", (name, channel_id))
    pdb.commit()
    pdb.close()

    ch = f"private:{channel_id}"
    sys_content = f'{user} has renamed the channel to "{name}"'
    db = get_db()
    db.execute(_INSERT_MSG_SQL, (ch, "system", sys_content, "system", time()))
    db.commit()
    db.close()

    return "ok"


@chat_bp.route("/private_channels/<int:channel_id>/add_member", methods=["POST"])
@auth.login_required
def add_private_channel_member(channel_id):
    """Add a user to a private channel. Any existing member may add.

    Route: ``POST /private_channels/<channel_id>/add_member``

    JSON body: ``{"username": str}``.  The new member starts fresh — no
    prior message history is shared.  A system message is inserted into
    every member's database announcing the addition.

    :returns: ``"ok"`` on success.
    :rtype: flask.Response
    """
    user = session["user"]
    members = get_private_channel_members(channel_id)
    if user not in members:
        return "forbidden", 403

    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()

    if not username:
        return "username required", 400
    if username not in all_users():
        return "user not found", 404
    if username in members:
        return "already a member", 409

    now = time()
    ch = f"private:{channel_id}"

    pdb = _get_private_db()
    pdb.execute(
        "INSERT OR IGNORE INTO private_channel_members (channel_id, username, joined_ts, history_start_ts) VALUES (?, ?, ?, ?)",
        (channel_id, username, now, now),
    )
    pdb.commit()
    pdb.close()

    sys_content = f"{user} added {username} to this channel"
    db = get_db()
    db.execute(_INSERT_MSG_SQL, (ch, "system", sys_content, "system", now))
    db.commit()
    db.close()

    return "ok"


@chat_bp.route("/private_channels/<int:channel_id>/leave", methods=["POST"])
@auth.login_required
def leave_private_channel(channel_id):
    """Remove the current user from a private channel.

    Route: ``POST /private_channels/<channel_id>/leave``

    A system message announcing the departure is inserted into every
    remaining member's database.

    :returns: ``"ok"`` on success.
    :rtype: flask.Response
    """
    user = session["user"]
    members = get_private_channel_members(channel_id)
    if user not in members:
        return "forbidden", 403

    pdb = _get_private_db()
    pdb.execute(
        "DELETE FROM private_channel_members WHERE channel_id = ? AND username = ?",
        (channel_id, user),
    )
    pdb.commit()
    pdb.close()

    remaining = [m for m in members if m != user]
    if remaining:
        ch = f"private:{channel_id}"
        sys_content = f"{user} has left the channel"
        db = get_db()
        db.execute(_INSERT_MSG_SQL, (ch, "system", sys_content, "system", time()))
        db.commit()
        db.close()

    return "ok"


@chat_bp.route("/private_channels/<int:channel_id>/members", methods=["GET"])
@auth.login_required
def private_channel_members_route(channel_id):
    """List members of a private channel.

    Route: ``GET /private_channels/<channel_id>/members``

    :returns: JSON array of ``{"username": str}`` objects.
    :rtype: flask.Response (application/json)
    """
    user = session["user"]
    members = get_private_channel_members(channel_id)
    if user not in members:
        return "forbidden", 403
    return jsonify([{"username": m} for m in members])


@chat_bp.route("/", methods=["GET"])
@auth.login_required
def index():
    """Serve the main chat single-page application.

    Route: ``GET /``

    Requires authentication (redirects to ``/login`` otherwise).  Renders
    the ``chat.html`` Jinja2 template, which contains the full client-side
    chat interface.  All subsequent data is loaded by the JavaScript
    polling loop via the JSON API endpoints in this module.

    :returns: A rendered HTML response.
    :rtype: flask.Response (text/html)
    """
    return render_template("chat.html")
