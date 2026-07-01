import sqlite3
import pytest
from werkzeug.security import generate_password_hash


@pytest.fixture(autouse=True)
def isolated_dbs(tmp_path, monkeypatch):
    """Redirect all DB paths to a temp directory and initialise clean schemas."""
    import minimost.audit as audit_mod
    import minimost.auth as auth_mod
    import minimost.presence as presence_mod
    import minimost.common as common_mod
    import minimost.preview as preview_mod
    import minimost.chat as chat_mod
    import minimost.ratelimit as ratelimit_mod

    auth_db = str(tmp_path / "auth.db")
    presence_db = str(tmp_path / "presence.db")
    users_dir = tmp_path / "users"
    uploads_dir = tmp_path / "uploads"
    avatars_dir = tmp_path / "avatars"
    users_dir.mkdir()
    uploads_dir.mkdir()
    avatars_dir.mkdir()

    monkeypatch.setattr(auth_mod, "AUTH_DB", auth_db)
    monkeypatch.setattr(presence_mod, "PRESENCE_DB", presence_db)
    monkeypatch.setattr(common_mod, "DB_DIR", users_dir)
    # Confine file I/O — including the startup cleanup daemon — to the temp dir
    # so tests never read, write, or delete real uploads/avatars.
    monkeypatch.setattr(chat_mod, "UPLOAD_DIR", uploads_dir)
    monkeypatch.setattr(chat_mod, "AVATAR_DIR", avatars_dir)
    # Skip the (relatively slow) TLS keygen in create_app for every test; the
    # certificate logic is covered directly in test_pki.py instead.
    monkeypatch.setenv("MINIMOST_SKIP_TLS", "1")
    # Skip the background cleanup daemon: it's a leaked thread that fires ~5s
    # after the app is created and reaches the live common.shared_db_path(), so
    # left running it opens a concurrent WAL connection on an unrelated test's
    # messages.db and intermittently locks it. The cleanup logic is covered
    # directly in test_clean.py instead.
    monkeypatch.setenv("MINIMOST_SKIP_CLEANUP", "1")
    # Confine the security audit trail to the temp dir so tests never append to a
    # real audit.log; pointing AUDIT_LOG at a fresh path also makes the logger
    # reattach its file handler there on the next event (see audit._get_logger).
    monkeypatch.setattr(audit_mod, "AUDIT_LOG", str(tmp_path / "audit.log"))

    preview_mod._CACHE.clear()
    # Clear in-process rate-limit / stream-cap state so one test's requests never
    # count against another's.
    ratelimit_mod.reset_all()

    from minimost.database import init_auth_db

    init_auth_db()
    from minimost.presence import _init_tables

    _init_tables()

    yield


def _add_user(auth_db, username, password="Password1!"):
    db = sqlite3.connect(auth_db)
    db.execute(
        "INSERT INTO users (username, password_hash) VALUES (?, ?)",
        (username, generate_password_hash(password)),
    )
    db.commit()
    db.close()


@pytest.fixture
def app(isolated_dbs):
    from minimost import create_app

    application = create_app()
    application.config["TESTING"] = True
    application.config["CSRF_ENABLED"] = False
    # Functional tests fire many requests in tight loops; leave DoS throttling
    # off here so it never interferes. The limiter is exercised directly in
    # test_ratelimit.py, which re-enables the flag.
    application.config["RATELIMIT_ENABLED"] = False
    return application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def alice(app, isolated_dbs):
    """Register alice and return an authenticated test client."""
    import minimost.auth as auth_mod
    import minimost.common as common_mod

    _add_user(auth_mod.AUTH_DB, "alice")
    common_mod.init_user_db("alice")

    c = app.test_client()
    with c.session_transaction() as sess:
        sess["user"] = "alice"
    return c


@pytest.fixture
def alice_and_bob(app, isolated_dbs):
    """Register alice and bob; return alice's authenticated client."""
    import minimost.auth as auth_mod
    import minimost.common as common_mod

    _add_user(auth_mod.AUTH_DB, "alice")
    _add_user(auth_mod.AUTH_DB, "bob")
    common_mod.init_user_db("alice")
    common_mod.init_user_db("bob")

    c = app.test_client()
    with c.session_transaction() as sess:
        sess["user"] = "alice"
    return c
