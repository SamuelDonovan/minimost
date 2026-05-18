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
_WAL = "PRAGMA journal_mode=WAL"
_SIGNUP_TEMPLATE = "signup.html"

auth_bp = Blueprint("auth", __name__)


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


@auth_bp.route("/login", methods=["GET", "POST"])
@auth_bp.route("/login.html", methods=["GET", "POST"])
def login():
    """Display the login form and authenticate users.

    **GET** — renders ``login.html``.

    **POST** — reads ``username`` and ``password`` from the form, looks up
    the stored hash in ``auth.db``, and verifies it with
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

    Routes: ``GET /login``, ``POST /login``,
    ``GET /login.html``, ``POST /login.html``

    :returns: A rendered ``login.html`` template (GET or failed POST), or a
        redirect to ``/`` on success.
    :rtype: flask.Response
    """
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]

        db = sqlite3.connect(AUTH_DB)
        db.execute(_WAL)
        row = db.execute(
            "SELECT password_hash FROM users WHERE username = ?", (username,)
        ).fetchone()
        db.close()

        if not row or not check_password_hash(row[0], password):
            # Delay to prevent users from brute forcing others passwords
            time.sleep(3)
            return render_template("login.html", error="Invalid credentials")

        session["user"] = username
        common.init_user_db(username)
        return redirect("/")

    return render_template("login.html")


@auth_bp.route("/logout", methods=["GET"])
@login_required
def logout():
    """Log the current user out and redirect to the login page.

    Sets the user's presence state to ``"offline"`` in ``presence.db`` via
    :func:`minimost.presence.update_presence`, then clears the Flask session
    and redirects to ``/login``.

    Route: ``GET /logout``

    :returns: A redirect response to ``/login``.
    :rtype: flask.Response
    """
    user = session["user"]
    presence.update_presence(user, "offline")
    session.clear()
    return redirect("/login")


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
    if not _USERNAME_RE.fullmatch(username):
        return "Username may only contain letters, numbers, hyphens, and underscores (1–32 characters)"
    if len(password) < 8:
        return "Password must be at least 8 characters"
    if not re.search(r"\d", password):
        return "Password must contain at least one number"
    if not re.search(r"[A-Z]", password):
        return "Password must contain at least one uppercase letter"
    if not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>/?`~]", password):
        return "Password must contain at least one special character"
    if password != confirm:
        return "Passwords do not match"
    return None


@auth_bp.route("/signup", methods=["GET", "POST"])
def signup():
    """Display the registration form and create new user accounts.

    **GET** — renders ``signup.html``.

    **POST** — validates the submitted ``username``, ``password``, and
    ``confirm_password`` fields, creates the account, and logs the user in.

    **Validation rules (enforced server-side):**

    * ``username`` must fully match ``[A-Za-z0-9_\\-]{1,32}``.
    * ``password`` must be at least 8 characters long.
    * ``password`` must contain at least one digit (``\\d``).
    * ``password`` must contain at least one uppercase ASCII letter.
    * ``password`` must contain at least one special character from the
      set ``!@#$%^&*()_+-=[]{};\\':|,./<>?`~``.
    * ``password`` and ``confirm_password`` must match.

    The same rules are enforced client-side in ``signup.html`` for
    immediate feedback, but server-side validation is authoritative.

    On success:

    1. Inserts ``(username, hashed_password)`` into ``auth.db``.
    2. Calls :func:`minimost.common.init_user_db` to create the user's DB.
    3. Calls :func:`_seed_channel_history` to populate public channel history.
    4. Sets ``session["user"]`` and redirects to ``/``.

    On failure:

    * Returns ``signup.html`` with a descriptive ``error`` variable.
    * If the username is already taken (``IntegrityError``), the error
      message says so.

    Routes: ``GET /signup``, ``POST /signup``

    :returns: A rendered ``signup.html`` template on GET or validation
        failure, or a redirect to ``/`` on successful registration.
    :rtype: flask.Response
    """
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]
        confirm = request.form["confirm_password"]

        error = _validate_signup(username, password, confirm)
        if error:
            return render_template(_SIGNUP_TEMPLATE, error=error)

        db = sqlite3.connect(AUTH_DB)
        db.execute(_WAL)
        try:
            db.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (username, hash_password(password)),
            )
            db.commit()
        except sqlite3.IntegrityError:
            db.close()
            return render_template(_SIGNUP_TEMPLATE, error="User already exists")

        db.close()

        common.init_user_db(username)
        _seed_channel_history(username)

        session["user"] = username
        return redirect("/")

    return render_template(_SIGNUP_TEMPLATE)
