"""
minimost.auth
=============

Authentication routes, password utilities, and access-control decorator.

This module handles everything related to user identity:

* **Registration** (``/signup``) — validates and stores new user credentials,
  creates the user's SQLite database, and seeds it with public channel history
  so a new user is not greeted by an empty chat.

* **Login** (``/login``) — verifies credentials and establishes a Flask session.

* **Logout** (``/logout``) — marks the user as offline and clears the session.

* **:func:`login_required`** — a decorator applied to every route that requires
  an authenticated session.

Module-level attributes
-----------------------
AUTH_DB : str
    Absolute path to the shared ``auth.db`` SQLite file that holds all user
    credentials.

auth_bp : flask.Blueprint
    The Flask Blueprint for all authentication routes.  Registered in
    :func:`minimost.create_app`.

_USERNAME_RE : re.Pattern
    Compiled regular expression that a username must fully match:
    ``[A-Za-z0-9_\\-]{1,32}``.
"""

# From the python standard library
import json
import re
from functools import wraps
import sqlite3
import time
from pathlib import Path

# From Flask
from flask import session, redirect, request, render_template, Blueprint
from werkzeug.security import generate_password_hash, check_password_hash

# Local Imports
from . import common
from . import presence

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent.parent
AUTH_DB = str(_PROJECT_ROOT / "auth.db")

_USERNAME_RE = re.compile(r"[A-Za-z0-9_\-]{1,32}")

# Usernames that nobody may register because the app gives them special
# meaning: "minimost" is the system author, "everyone" is the channel-wide
# @-mention keyword, and "deleteduser" shadows the "Deleted User" author used
# for soft-deleted accounts.  Compared case-insensitively.
_RESERVED_USERNAMES = {"minimost", "everyone", "deleteduser"}

_WAL = "PRAGMA journal_mode=WAL"
_RESET_PW_TEMPLATE = "reset_password.html"
_SIGNUP_TEMPLATE = "signup.html"
_LOGIN_TEMPLATE = "login.html"

# settings.json is bundled inside the package (src/minimost/); _HERE is the
# package directory.
_SETTINGS_FILE = _HERE / "settings.json"
_DEFAULT_MAX_LOGIN_ATTEMPTS = 5
_DEFAULT_LOCKOUT_MINUTES = 15

# Upper bound on password length.  Enforced at signup/reset and guarded at login
# so an attacker cannot force the server to hash a huge string (PBKDF2 cost
# scales with input length).
_MAX_PASSWORD_LEN = 1024

auth_bp = Blueprint("auth", __name__)


def _lockout_settings() -> tuple:
    """Return ``(max_attempts, lockout_seconds)`` for account lockout.

    Reads ``max_login_attempts`` and ``lockout_duration_minutes`` from
    ``settings.json`` on each call, so changes take effect without a restart.
    A ``max_login_attempts`` of ``0`` (or any non-positive value) **disables**
    lockout entirely.  Missing, malformed, or invalid values fall back to the
    built-in defaults (``5`` attempts, ``15`` minutes).

    :returns: ``(max_attempts, lockout_seconds)`` — the number of consecutive
        failed attempts allowed before locking, and the lockout duration in
        seconds.
    :rtype: tuple[int, int]
    """
    max_attempts = _DEFAULT_MAX_LOGIN_ATTEMPTS
    minutes = _DEFAULT_LOCKOUT_MINUTES
    try:
        data = json.loads(_SETTINGS_FILE.read_text())
        value = data.get("max_login_attempts")
        if isinstance(value, int) and not isinstance(value, bool):
            max_attempts = value
        duration = data.get("lockout_duration_minutes")
        if (
            isinstance(duration, (int, float))
            and not isinstance(duration, bool)
            and duration > 0
        ):
            minutes = duration
    except (OSError, json.JSONDecodeError):
        pass
    return max_attempts, int(minutes * 60)


def _lockout_message(minutes) -> str:
    """Return the user-facing error shown while an account is locked out.

    :param minutes: Whole minutes remaining in the lockout (rounded up; a
        minimum of ``1`` is always shown).
    :returns: A human-readable lockout message.
    :rtype: str
    """
    minutes = max(1, int(minutes))
    unit = "minute" if minutes == 1 else "minutes"
    return (
        "Account locked due to too many failed login attempts. "
        f"Try again in {minutes} {unit}."
    )


def hash_password(password: str) -> str:
    """Hash a plaintext password using PBKDF2.

    Delegates to :func:`werkzeug.security.generate_password_hash`, which
    applies a random salt and uses PBKDF2-HMAC-SHA256 by default.  The
    returned string is suitable for storage in ``auth.db`` and can be
    verified with :func:`werkzeug.security.check_password_hash`.

    :param password: The plaintext password to hash.
    :type password: str
    :returns: A Werkzeug-format hash string that encodes the algorithm,
        iterations, salt, and digest.
    :rtype: str

    Example::

        hashed = hash_password("S3cr3t!")
        assert check_password_hash(hashed, "S3cr3t!")
    """
    return generate_password_hash(password)


def _seed_channel_history(new_user: str) -> None:
    """Copy all public channel message history into a newly created user's DB.

    When a new account is created, this function seeds the new user's
    ``messages`` table with every public-channel message from an existing
    user's database.  This ensures new users can see the full conversation
    history from the moment they join, rather than starting with a blank
    slate.

    **Algorithm:**

    1. Pick any existing user from ``auth.db`` (other than *new_user*).
    2. Open that user's ``.db`` file as the source.
    3. Select all rows from ``messages`` where ``channel NOT LIKE 'dm:%'``
       (i.e. public channels only — DMs are never copied).
    4. Insert those rows verbatim into the new user's database with
       ``read = 1`` so they generate no unread-message notifications.

    **Edge cases:**

    * If no other users exist (first registration), the function returns
      immediately — there is no history to copy.
    * If the existing user's ``.db`` file is missing on disk, the function
      also returns without error.

    :param new_user: The username of the account being registered.
    :type new_user: str
    :returns: None
    """
    adb = sqlite3.connect(AUTH_DB)
    adb.execute(_WAL)
    row = adb.execute(
        "SELECT username FROM users WHERE username != ? LIMIT 1", (new_user,)
    ).fetchone()
    adb.close()

    if not row:
        return

    src_path = common.user_db_path(row[0])
    if not src_path.exists():
        return

    src = sqlite3.connect(str(src_path))
    src.execute(_WAL)
    rows = src.execute("""
        SELECT id, channel, sender, content, content_type, filename, ts,
               edited, edited_ts, deleted, deleted_ts, reply_to_id,
               reactions, reactions_ts, mentions, metadata, client_msg_id, expires_ts
        FROM messages
        WHERE channel NOT LIKE 'dm:%'
        """).fetchall()
    src.close()

    if not rows:
        return

    dst = sqlite3.connect(str(common.user_db_path(new_user)))
    dst.execute(_WAL)
    dst.executemany(
        """
        INSERT INTO messages
            (id, channel, sender, content, content_type, filename, ts,
             edited, edited_ts, deleted, deleted_ts, reply_to_id,
             reactions, reactions_ts, mentions, metadata, client_msg_id, expires_ts,
             read)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        """,
        rows,
    )
    dst.commit()
    dst.close()


def login_required(fn):
    """Decorator that enforces an authenticated Flask session.

    Wraps a Flask view function so that unauthenticated requests are
    redirected to ``/login`` instead of executing the view.  The session
    key ``"user"`` is set by the :func:`login` route upon successful
    authentication.

    This decorator preserves the wrapped function's name and docstring via
    :func:`functools.wraps`, which is required for Flask's endpoint
    registration to work correctly when multiple routes use the decorator.

    :param fn: The Flask view function to protect.
    :type fn: callable
    :returns: A wrapped view function that checks for ``session["user"]``
        before calling *fn*.
    :rtype: callable

    Example::

        @chat_bp.route("/messages/<channel>")
        @login_required
        def messages(channel):
            ...
    """

    @wraps(fn)
    def wrapper(*args, **kwargs):
        if "user" not in session:
            return redirect("/login")
        return fn(*args, **kwargs)

    return wrapper


@auth_bp.route("/login", methods=["GET"])
def login():
    """Render the login page.

    Routes: ``GET /login``

    :returns: A rendered ``login.html`` template.
    :rtype: flask.Response
    """
    return render_template(_LOGIN_TEMPLATE)


@auth_bp.route("/login", methods=["POST"])
def login_post():
    """Authenticate a user from the login form.

    Reads ``username`` and ``password`` from the form, looks up the stored
    hash in ``auth.db``, and verifies it with
    :func:`werkzeug.security.check_password_hash`.

    On success:

    * Sets ``session["user"]`` to the authenticated username.
    * Calls :func:`minimost.common.init_user_db` to ensure the user's
      database exists (relevant after a manual ``users/`` directory wipe).
    * Redirects to ``/`` (the main chat interface).

    On failure:

    * Waits **3 seconds** before responding to slow down brute-force
      attempts.
    * Re-renders ``login.html`` with a generic ``"Invalid credentials"``
      error (username and password failures are intentionally
      indistinguishable).

    **Account lockout:** consecutive failed attempts against an existing
    account are counted in ``users.failed_attempts``.  Once they reach
    ``max_login_attempts`` (from ``settings.json``) the account is locked for
    ``lockout_duration_minutes`` by setting ``users.lockout_until``; further
    logins are rejected — without checking the password — until that time
    passes.  A successful login clears the counter.  Setting
    ``max_login_attempts`` to ``0`` disables the feature.  See
    :func:`_lockout_settings`.

    Routes: ``POST /login``

    :returns: A rendered ``login.html`` template on failure, or a redirect
        to ``/`` on success.
    :rtype: flask.Response
    """
    username = request.form["username"].strip()
    password = request.form["password"]

    # No valid password can exceed this (enforced at signup/reset); reject an
    # oversized one cheaply rather than spending CPU hashing it.
    if len(password) > _MAX_PASSWORD_LEN:
        time.sleep(3)
        return render_template(
            _LOGIN_TEMPLATE, error="Invalid credentials", username=username
        )

    max_attempts, lockout_seconds = _lockout_settings()
    lockout_enabled = max_attempts > 0
    now = time.time()

    db = sqlite3.connect(AUTH_DB)
    db.execute(_WAL)
    # Username matching is case-insensitive; ``canonical`` is the stored spelling
    # used for the session and every follow-up query so per-user DB paths and
    # cross-references stay consistent regardless of the case the user typed.
    row = db.execute(
        "SELECT username, password_hash, failed_attempts, lockout_until"
        " FROM users WHERE username = ? COLLATE NOCASE",
        (username,),
    ).fetchone()
    canonical = row[0] if row else username

    # Account currently locked — reject without checking the password.
    if row and lockout_enabled and row[3] and now < row[3]:
        db.close()
        time.sleep(3)
        remaining = int((row[3] - now) // 60) + 1
        return render_template(
            _LOGIN_TEMPLATE, error=_lockout_message(remaining), username=username
        )

    if not row or not check_password_hash(row[1], password):
        # Record the failed attempt against an existing account and lock it once
        # the threshold is reached.
        if row and lockout_enabled:
            attempts = row[2] + 1
            if attempts >= max_attempts:
                db.execute(
                    "UPDATE users SET failed_attempts = 0, lockout_until = ?"
                    " WHERE username = ?",
                    (now + lockout_seconds, canonical),
                )
                db.commit()
                db.close()
                time.sleep(3)
                return render_template(
                    _LOGIN_TEMPLATE,
                    error=_lockout_message(lockout_seconds // 60),
                    username=username,
                )
            db.execute(
                "UPDATE users SET failed_attempts = ? WHERE username = ?",
                (attempts, canonical),
            )
            db.commit()
        db.close()
        # Delay to prevent users from brute forcing others passwords
        time.sleep(3)
        return render_template(
            _LOGIN_TEMPLATE, error="Invalid credentials", username=username
        )

    # Success — clear any recorded failed-attempt / lockout state.
    if row[2] or row[3]:
        db.execute(
            "UPDATE users SET failed_attempts = 0, lockout_until = NULL"
            " WHERE username = ?",
            (canonical,),
        )
        db.commit()
    db.close()

    session["user"] = canonical
    common.init_user_db(canonical)
    presence.update_presence(canonical, "active")
    return redirect("/")


@auth_bp.route("/logout", methods=["GET"])
@login_required
def logout():
    """Log the current user out and redirect to the login page.

    Sets the user's presence state to ``"offline"`` in ``presence.db`` via
    :func:`minimost.presence.update_presence` and clears any manual presence
    override, then clears the Flask session and redirects to ``/login``.

    Route: ``GET /logout``

    :returns: A redirect response to ``/login``.
    :rtype: flask.Response
    """
    user = session["user"]
    presence.update_presence(user, "offline")
    presence.set_override(user, None)
    session.clear()
    return redirect("/login")


def _validate_password(password: str):
    """Return an error string if *password* fails the strength rules, else ``None``.

    Shared by signup and password reset so the rules stay in one place.

    :param password: The submitted password.
    :returns: A human-readable error message, or ``None`` if all rules pass.
    :rtype: str or None
    """
    if len(password) < 8:
        return "Password must be at least 8 characters"
    if len(password) > _MAX_PASSWORD_LEN:
        return f"Password must be at most {_MAX_PASSWORD_LEN} characters"
    if not re.search(r"\d", password):
        return "Password must contain at least one number"
    if not re.search(r"[A-Z]", password):
        return "Password must contain at least one uppercase letter"
    if not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>/?`~]", password):
        return "Password must contain at least one special character"
    return None


def _validate_signup(username: str, password: str, confirm: str):
    """Validate signup form fields and return an error string, or ``None`` on success.

    :param username: The submitted username.
    :param password: The submitted password.
    :param confirm: The password confirmation field.
    :returns: A human-readable error message, or ``None`` if all rules pass.
    :rtype: str or None
    """
    if not username or not password:
        return "Missing fields"
    if username.lower() in _RESERVED_USERNAMES:
        return f'"{username}" is a protected username'
    if not _USERNAME_RE.fullmatch(username):
        return "Username may only contain letters, numbers, hyphens, and underscores (1–32 characters)"
    password_error = _validate_password(password)
    if password_error:
        return password_error
    if password != confirm:
        return "Passwords do not match"
    return None


@auth_bp.route("/forgot-password", methods=["GET"])
def forgot_password():
    """Render the forgot-password information page.

    Route: ``GET /forgot-password``

    :returns: A rendered ``forgot_password.html`` template.
    :rtype: flask.Response
    """
    return render_template("forgot_password.html")


@auth_bp.route("/signup", methods=["GET"])
def signup():
    """Render the registration page.

    Route: ``GET /signup``

    :returns: A rendered ``signup.html`` template.
    :rtype: flask.Response
    """
    return render_template(_SIGNUP_TEMPLATE)


@auth_bp.route("/signup", methods=["POST"])
def signup_post():
    """Create a new user account from the registration form.

    Validates the submitted ``username``, ``password``, and
    ``confirm_password`` fields, creates the account, and logs the user in.

    **Validation rules (enforced server-side):**

    * ``username`` must fully match ``[A-Za-z0-9_\\-]{1,32}``.
    * ``password`` must be at least 8 characters long.
    * ``password`` must contain at least one digit (``\\d``).
    * ``password`` must contain at least one uppercase ASCII letter.
    * ``password`` must contain at least one special character from the
      set ``!@#$%^&*()_+-=[]{};\\':|,./<>?`~``.
    * ``password`` and ``confirm_password`` must match.

    On success:

    1. Inserts ``(username, hashed_password)`` into ``auth.db``.
    2. Calls :func:`minimost.common.init_user_db` to create the user's DB.
    3. Calls :func:`_seed_channel_history` to populate public channel history.
    4. Calls :func:`minimost.chat.post_welcome_message` to greet the new user
       in the first public channel under the MiniMost identity.
    5. Sets ``session["user"]`` and redirects to ``/``.

    On failure:

    * Returns ``signup.html`` with a descriptive ``error`` variable.
    * If the username is already taken (``IntegrityError``), the error
      message says so.

    Route: ``POST /signup``

    :returns: A rendered ``signup.html`` template on validation failure, or
        a redirect to ``/`` on successful registration.
    :rtype: flask.Response
    """
    username = request.form["username"].strip()
    password = request.form["password"]
    confirm = request.form["confirm_password"]

    error = _validate_signup(username, password, confirm)
    if error:
        return render_template(_SIGNUP_TEMPLATE, error=error, username=username)

    db = sqlite3.connect(AUTH_DB)
    db.execute(_WAL)
    # Reject names that collide case-insensitively with an existing account
    # (e.g. "Admin" vs "admin") to prevent look-alike impersonation.
    existing = db.execute(
        "SELECT 1 FROM users WHERE username = ? COLLATE NOCASE", (username,)
    ).fetchone()
    if existing:
        db.close()
        return render_template(
            _SIGNUP_TEMPLATE, error="User already exists", username=username
        )
    try:
        db.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username, hash_password(password)),
        )
        db.commit()
    except sqlite3.IntegrityError:
        db.close()
        return render_template(
            _SIGNUP_TEMPLATE, error="User already exists", username=username
        )

    db.close()

    # Remove any leftover DB from a previously soft-deleted account so that
    # init_user_db and _seed_channel_history start from a clean slate.
    stale_db = common.user_db_path(username)
    if stale_db.exists():
        stale_db.unlink()

    common.init_user_db(username)
    _seed_channel_history(username)

    # Greet the newcomer in the first public channel under the MiniMost
    # identity.  Imported lazily because chat imports auth at module load.
    from . import chat

    chat.post_welcome_message(username)

    session["user"] = username
    presence.update_presence(username, "active")
    return redirect("/")


def _validate_password_reset(password: str, confirm: str):
    """Return an error string if the new password fails validation, else None."""
    password_error = _validate_password(password)
    if password_error:
        return password_error
    if password != confirm:
        return "Passwords do not match"
    return None


@auth_bp.route("/reset-password/<token>", methods=["GET"])
def reset_password_form(token):
    """Render the password reset form if the token is valid and unexpired.

    Route: ``GET /reset-password/<token>``

    :returns: Rendered ``reset_password.html`` with the form or an error.
    :rtype: flask.Response
    """
    db = sqlite3.connect(AUTH_DB)
    db.execute(_WAL)
    row = db.execute(
        "SELECT username, expires_ts, used FROM password_reset_tokens WHERE token = ?",
        (token,),
    ).fetchone()
    db.close()

    if not row or row[2] or time.time() > row[1]:
        return render_template(
            _RESET_PW_TEMPLATE, token=None, error="invalid", username=None
        )
    return render_template(_RESET_PW_TEMPLATE, token=token, error=None, username=row[0])


@auth_bp.route("/reset-password/<token>", methods=["POST"])
def reset_password_post(token):
    """Process a password reset form submission.

    Validates the token is still active, applies password rules, updates the
    stored hash in ``auth.db``, and marks the token as used.

    Route: ``POST /reset-password/<token>``

    :returns: Rendered ``reset_password.html`` (success or error).
    :rtype: flask.Response
    """
    db = sqlite3.connect(AUTH_DB)
    db.execute(_WAL)
    row = db.execute(
        "SELECT username, expires_ts, used FROM password_reset_tokens WHERE token = ?",
        (token,),
    ).fetchone()

    if not row or row[2] or time.time() > row[1]:
        db.close()
        return render_template(
            _RESET_PW_TEMPLATE, token=None, error="invalid", username=None
        )

    username = row[0]
    password = request.form.get("password", "")
    confirm = request.form.get("confirm_password", "")

    error = _validate_password_reset(password, confirm)
    if error:
        db.close()
        return render_template(
            _RESET_PW_TEMPLATE, token=token, error=error, username=username
        )

    db.execute(
        "UPDATE users SET password_hash = ? WHERE username = ?",
        (hash_password(password), username),
    )
    db.execute("UPDATE password_reset_tokens SET used = 1 WHERE token = ?", (token,))
    db.commit()
    db.close()
    return render_template(
        _RESET_PW_TEMPLATE, token=None, error=None, success=True, username=username
    )
