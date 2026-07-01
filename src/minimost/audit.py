"""
minimost.audit
==============

Security audit logging for MiniMost.

The Application Security and Development (ASD) STIG requires an application to
generate audit records for security-relevant events, and that each record
identify *what* happened, *when* (timestamp), *where* it came from (source
address), *who* triggered it (user identity), and the *outcome*
(success/failure).  This module is the single source of truth for producing
those records.

Design
------
* **Standard library only.**  Records are emitted through :mod:`logging`, so
  there is no new dependency and nothing newer than Python 3.6 is required.
* **Durable local trail.**  Records are appended to ``audit.log`` in the
  MiniMost data root (see :func:`minimost.paths.data_dir`).  On a packaged
  install that is the systemd ``StateDirectory`` (e.g. ``/var/lib/minimost``),
  so the file persists across restarts and can be shipped to a central
  aggregator/SIEM by the host's log forwarder (journald, rsyslog, …).
* **One line per event, machine-parseable.**  Each record is a single
  ``key=value`` line prefixed with an ISO-8601 UTC timestamp, e.g.::

      2026-06-29T18:04:11Z event=login outcome=failure user=alice src=10.0.0.5

* **Append-only, multi-worker safe.**  The file handler is created lazily on
  first use *after* Gunicorn forks its workers, so every worker opens its own
  ``O_APPEND`` descriptor; on POSIX, single-line appends are atomic, so the
  workers never corrupt each other's records.
* **Bounded by rotation.**  The handler rotates the log by size and/or age (see
  ``audit_log_max_size_mb`` / ``audit_log_max_age_days`` / ``audit_log_backups``
  in ``settings.json``), keeping a configurable number of timestamped archives.
  Rotation is coordinated across workers so they never clobber each other (see
  :class:`_RotatingAuditHandler`). Pruning deletes the oldest archives, so a
  deployment with audit-retention requirements should off-load records to a
  central aggregator/SIEM before they age out.
* **Log-injection resistant.**  All interpolated values are stripped of control
  characters (notably CR/LF) before they reach the log, so an attacker cannot
  forge or split records by smuggling newlines through a username or path.

Module-level attributes
------------------------
AUDIT_LOG : str
    Absolute path to ``audit.log``.  Resolved once at import time from
    :func:`minimost.paths.data_dir`.  Exposed as a module attribute (mirroring
    ``auth.AUTH_DB`` / ``presence.PRESENCE_DB``) so the test suite can redirect
    it to a temp directory; changing it re-points the logger on the next event.
"""

import glob
import logging
import logging.handlers
import os
import re
import time
from pathlib import Path

from .paths import data_dir

AUDIT_LOG = str(data_dir() / "audit.log")

_LOGGER_NAME = "minimost.audit"

# settings.json ships inside the package (next to this module); the rotation
# thresholds are read from it so the audit trail does not grow without bound.
_SETTINGS_FILE = Path(__file__).resolve().parent / "settings.json"

# Shipped rotation defaults, used when settings.json is absent/unreadable. A
# size or age of 0 disables that trigger; a backup count of 0 keeps every
# archive (so total size is unbounded — bound it with a positive count).
_DEFAULT_AUDIT_MAX_SIZE_MB = 10
_DEFAULT_AUDIT_MAX_AGE_DAYS = 30
_DEFAULT_AUDIT_BACKUPS = 12

# Matches any ASCII control character (CR, LF, NUL, tabs, …).  Replaced with a
# space before interpolation so a value can never inject a newline and forge a
# second log record (CWE-117: improper output neutralization for logs).
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")

# Tracks which path the active file handler points at, so a change to
# ``AUDIT_LOG`` (e.g. a test monkeypatching it) transparently reconfigures the
# logger on the next event instead of writing to the stale path.
_configured_path = None


class _UTCFormatter(logging.Formatter):
    """Format timestamps as ISO-8601 UTC with a trailing ``Z``.

    The default :class:`logging.Formatter` emits local time with millisecond
    precision; the STIG audit-content requirement is cleaner to satisfy with an
    unambiguous UTC instant, so the converter is pinned to :func:`time.gmtime`.
    """

    converter = time.gmtime

    def formatTime(self, record, datefmt=None):  # noqa: D401, N802 (logging API)
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", self.converter(record.created))


def _setting_num(value, default):
    """Return *value* if it is a non-negative, non-bool number, else *default*."""
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
        return value
    return default


def _rotation_config():
    """Return ``(max_bytes, max_age_seconds, backup_count)`` from settings.json.

    Keys (all optional):

    * ``audit_log_max_size_mb`` — rotate once the live log reaches this size.
    * ``audit_log_max_age_days`` — rotate this long after the previous rotation.
    * ``audit_log_backups`` — number of rotated archives to keep; older ones are
      deleted. ``0`` keeps every archive.

    A ``0`` (or absent) size/age disables that trigger; with both disabled the
    file is never rotated. A read/parse error falls back to the shipped defaults.
    """
    max_mb = _DEFAULT_AUDIT_MAX_SIZE_MB
    max_days = _DEFAULT_AUDIT_MAX_AGE_DAYS
    backups = _DEFAULT_AUDIT_BACKUPS
    try:
        import json

        data = json.loads(_SETTINGS_FILE.read_text())
        max_mb = _setting_num(data.get("audit_log_max_size_mb"), max_mb)
        max_days = _setting_num(data.get("audit_log_max_age_days"), max_days)
        backups = _setting_num(data.get("audit_log_backups"), backups)
    except (OSError, ValueError):
        pass
    return int(max_mb * 1024 * 1024), int(max_days * 24 * 3600), int(backups)


class _RotatingAuditHandler(logging.handlers.WatchedFileHandler):
    """Append-only audit handler that rotates by size and/or age.

    Rotation is safe across several Gunicorn workers, each of which holds its
    own handler. :class:`~logging.handlers.WatchedFileHandler` reopens the log
    whenever its inode changes, so when one worker rotates the file (by renaming
    it) the others transparently switch to the freshly created one — no records
    are lost, and, unlike :class:`~logging.handlers.RotatingFileHandler`, the
    workers never clobber each other's rotation. The rename is guarded by an
    atomically-created ``<log>.lock`` file (``O_CREAT | O_EXCL``, which works on
    both POSIX and Windows) and re-checked under the lock, so exactly one worker
    rotates and a file already rotated by a peer is left alone. A lock left
    behind by a crashed rotation is treated as stale after a minute so it can
    never deadlock.

    Age is measured from a companion ``<log>.rotated_at`` marker file (touched at
    each rotation), independent of write activity, so a quiet day does not reset
    the clock.
    """

    def __init__(
        self,
        filename,
        max_bytes,
        max_age_seconds,
        backup_count,
        encoding=None,
        delay=False,
    ):
        super().__init__(filename, encoding=encoding, delay=delay)
        self.max_bytes = max_bytes
        self.max_age_seconds = max_age_seconds
        self.backup_count = backup_count

    @property
    def _marker(self):
        return self.baseFilename + ".rotated_at"

    def _touch_marker(self):
        try:
            with open(self._marker, "a"):
                os.utime(self._marker, None)
        except OSError:  # nosec B110 - best effort; clock just restarts later
            pass

    def _needs_rotation(self):
        try:
            if self.max_bytes and os.path.getsize(self.baseFilename) >= self.max_bytes:
                return True
        except OSError:
            return False
        if self.max_age_seconds:
            try:
                started = os.path.getmtime(self._marker)
            except OSError:
                self._touch_marker()  # no marker yet: start the clock now
                return False
            if time.time() - started >= self.max_age_seconds:
                return True
        return False

    def _archive_name(self):
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        target = "{0}.{1}".format(self.baseFilename, stamp)
        n = 0
        while os.path.exists(target):  # avoid clobbering a same-second archive
            n += 1
            target = "{0}.{1}.{2}".format(self.baseFilename, stamp, n)
        return target

    def _prune(self):
        if not self.backup_count:
            return
        archives = [
            p
            for p in glob.glob(self.baseFilename + ".*")
            if not p.endswith((".rotated_at", ".lock"))
        ]
        archives.sort(key=os.path.getmtime)
        for old in archives[: max(0, len(archives) - self.backup_count)]:
            try:
                os.remove(old)
            except OSError:  # nosec B110 - a peer may have pruned it already
                pass

    def _close_stream(self):
        """Release this handler's open file descriptor on the log.

        Windows refuses to rename a file that is open in the process, so the log
        must be closed before it can be rotated (POSIX allows renaming an open
        file, so this is harmless there). The stream is left as ``None`` so the
        next :meth:`emit` reopens a fresh file via the base handler.
        """
        if self.stream is not None:
            try:
                self.stream.flush()
            finally:
                self.stream.close()
                self.stream = None

    def _rotate(self):
        target = self._archive_name()
        # Drop our own handle first so the rename succeeds on Windows.
        self._close_stream()
        try:
            os.rename(self.baseFilename, target)
        except OSError:
            return  # already moved by a peer, or gone
        self._touch_marker()
        self._prune()
        # The next emit recreates baseFilename (the stream is now None), so there
        # is nothing else to do here.

    # A rotation that crashes mid-way would leave its lock file behind; treat a
    # lock older than this as abandoned so it can never deadlock future rotations.
    _LOCK_STALE_SECONDS = 60

    def _rotate_locked(self):
        # Cross-platform mutual exclusion (works on Windows and POSIX, unlike
        # ``fcntl``): O_EXCL makes the lock-file creation atomic, so only one
        # worker wins. The trigger is re-checked under the lock so a file a peer
        # already rotated is left alone.
        lockpath = self.baseFilename + ".lock"
        try:
            fd = os.open(lockpath, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            self._clear_stale_lock(lockpath)
            return  # a peer is rotating; the trigger will fire again next emit
        except OSError:
            return
        try:
            if self._needs_rotation():  # re-check now that we hold the lock
                self._rotate()
        finally:
            os.close(fd)
            try:
                os.remove(lockpath)
            except OSError:  # nosec B110 - a peer may have cleared it already
                pass

    def _clear_stale_lock(self, lockpath):
        """Remove the lock file if it was abandoned by a crashed rotation."""
        try:
            if time.time() - os.path.getmtime(lockpath) > self._LOCK_STALE_SECONDS:
                os.remove(lockpath)
        except OSError:  # nosec B110 - best effort; gone or just-recreated is fine
            pass

    def emit(self, record):
        super().emit(record)  # write, reopening first if the file was rotated
        try:
            if (self.max_bytes or self.max_age_seconds) and self._needs_rotation():
                self._rotate_locked()
        except Exception:  # nosec B110 # pragma: no cover - rotation is best effort
            pass


def _make_handler(path):
    """Return a rotating audit handler for *path*, or ``None`` if unopenable.

    Audit logging must never take the request down: if the log file cannot be
    created (read-only data dir, permissions, …) the failure is swallowed and
    the caller proceeds without a durable record rather than raising. The handler
    rotates by size and/or age per :func:`_rotation_config` so the trail does not
    grow without bound.
    """
    try:
        max_bytes, max_age, backups = _rotation_config()
        handler = _RotatingAuditHandler(
            path,
            max_bytes,
            max_age,
            backups,
            encoding="utf-8",
            delay=True,
        )
    except OSError:
        return None
    handler.setFormatter(_UTCFormatter("%(asctime)s %(message)s"))
    return handler


def _get_logger():
    """Return the configured audit logger, (re)attaching the file handler.

    Idempotent: the handler is built only when missing or when ``AUDIT_LOG`` has
    changed since it was last built.  ``propagate`` is disabled so audit records
    do not bleed into Gunicorn's root/error logger.
    """
    global _configured_path
    logger = logging.getLogger(_LOGGER_NAME)
    if _configured_path != AUDIT_LOG:
        for existing in logger.handlers:
            existing.close()
        logger.handlers.clear()
        handler = _make_handler(AUDIT_LOG)
        if handler is not None:
            logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
        _configured_path = AUDIT_LOG
    return logger


def _sanitize(value, limit=256):
    """Neutralise a value for safe single-line logging.

    Control characters are replaced with spaces (defeating log injection) and
    the result is length-capped so an oversized field cannot bloat the trail.
    """
    text = _CONTROL_RE.sub(" ", str(value))
    if len(text) > limit:
        text = text[:limit] + "..."
    return text


def _client_ip():
    """Return the request's source IP, or ``None`` outside a request context.

    When the app sits behind a reverse proxy the real client is the leftmost
    ``X-Forwarded-For`` entry; otherwise it is the peer address.  ``XFF`` is
    attacker-controllable when the app is exposed directly, so deployments that
    must trust it should terminate at a proxy that overwrites the header.
    """
    try:
        from flask import has_request_context, request

        if not has_request_context():
            return None
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.remote_addr
    except Exception:  # pragma: no cover - defensive; never break a request
        return None


def log_event(event, outcome, user=None, source=None, detail=None):
    """Append one security audit record.

    :param event: Short event type, e.g. ``"login"`` or ``"account_create"``.
    :param outcome: ``"success"`` or ``"failure"``.
    :param user: The user identity the event concerns (``None`` → ``-``).
    :param source: Source address; resolved from the request when omitted.
    :param detail: Optional free-text context (sanitised and quoted).
    """
    if source is None:
        source = _client_ip()
    fields = [
        "event={0}".format(_sanitize(event, 64)),
        "outcome={0}".format(_sanitize(outcome, 16)),
        "user={0}".format(_sanitize(user, 64) if user else "-"),
        "src={0}".format(_sanitize(source, 64) if source else "-"),
    ]
    if detail:
        fields.append('detail="{0}"'.format(_sanitize(detail)))
    # Auditing must never break the request that triggered it.
    try:
        _get_logger().info(" ".join(fields))
    except Exception:  # nosec B110 # pragma: no cover
        pass


# --- Convenience wrappers for the security events MiniMost audits -----------
# Keeping the event vocabulary here (rather than spelling out strings at every
# call site) keeps the audit trail consistent and greppable.


def login_success(user):
    """Record a successful authentication."""
    log_event("login", "success", user=user)


def login_failure(user, detail=None):
    """Record a failed authentication attempt."""
    log_event("login", "failure", user=user, detail=detail)


def logout(user):
    """Record a user-initiated logout."""
    log_event("logout", "success", user=user)


def account_lockout(user):
    """Record an account being locked after repeated failed logins."""
    log_event(
        "account_lockout",
        "success",
        user=user,
        detail="account locked after consecutive failed logins",
    )


def account_created(user):
    """Record creation of a new account."""
    log_event("account_create", "success", user=user)


def account_deleted(user, delete_type):
    """Record removal (soft/hard) of an account."""
    log_event(
        "account_remove", "success", user=user, detail="type={0}".format(delete_type)
    )


def password_changed(user, outcome="success"):
    """Record a password change by the logged-in user."""
    log_event("password_change", outcome, user=user)


def password_reset(user, outcome="success"):
    """Record a password reset via a reset token."""
    log_event("password_reset", outcome, user=user)


def password_expired(user):
    """Record a login refused because the password exceeded its maximum age."""
    log_event(
        "password_expired",
        "failure",
        user=user,
        detail="login refused; password past maximum age",
    )


def access_denied(user, resource):
    """Record an access-control denial (forbidden resource / failed CSRF)."""
    log_event("access_denied", "failure", user=user, detail=resource)
