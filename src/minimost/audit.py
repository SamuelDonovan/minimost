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

import logging
import re
import time

from .paths import data_dir

AUDIT_LOG = str(data_dir() / "audit.log")

_LOGGER_NAME = "minimost.audit"

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


def _make_handler(path):
    """Return a file handler for *path*, or ``None`` if it cannot be opened.

    Audit logging must never take the request down: if the log file cannot be
    created (read-only data dir, permissions, …) the failure is swallowed and
    the caller proceeds without a durable record rather than raising.
    """
    try:
        handler = logging.FileHandler(path, encoding="utf-8", delay=True)
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
        for existing in list(logger.handlers):
            logger.removeHandler(existing)
            existing.close()
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


def access_denied(user, resource):
    """Record an access-control denial (forbidden resource / failed CSRF)."""
    log_event("access_denied", "failure", user=user, detail=resource)
