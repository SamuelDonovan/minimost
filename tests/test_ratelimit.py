"""Tests for the in-process DoS throttles (``minimost.ratelimit``)."""

from minimost import ratelimit
from minimost.ratelimit import ConcurrencyLimiter, RateLimiter

# ── RateLimiter (sliding window) ─────────────────────────────────────────────


def test_ratelimiter_allows_under_limit():
    rl = RateLimiter()
    for _ in range(3):
        allowed, retry = rl.hit("k", limit=3, window=60)
        assert allowed
        assert retry == 0


def test_ratelimiter_blocks_over_limit():
    rl = RateLimiter()
    for _ in range(3):
        assert rl.hit("k", 3, 60)[0]
    allowed, retry = rl.hit("k", 3, 60)
    assert not allowed
    assert retry >= 1  # a positive Retry-After hint


def test_ratelimiter_window_expiry(monkeypatch):
    rl = RateLimiter()
    clock = [1000.0]
    monkeypatch.setattr(ratelimit._time, "monotonic", lambda: clock[0])

    assert rl.hit("k", 1, 10)[0]
    assert not rl.hit("k", 1, 10)[0]  # second within window blocked

    clock[0] += 11  # window has fully passed
    assert rl.hit("k", 1, 10)[0]  # allowed again


def test_ratelimiter_keys_are_independent():
    rl = RateLimiter()
    assert rl.hit("a", 1, 60)[0]
    assert rl.hit("b", 1, 60)[0]  # different key has its own budget
    assert not rl.hit("a", 1, 60)[0]


def test_ratelimiter_reset_clears_state():
    rl = RateLimiter()
    assert rl.hit("k", 1, 60)[0]
    assert not rl.hit("k", 1, 60)[0]
    rl.reset()
    assert rl.hit("k", 1, 60)[0]


def test_ratelimiter_gc_drops_idle_keys(monkeypatch):
    rl = RateLimiter()
    clock = [0.0]
    monkeypatch.setattr(ratelimit._time, "monotonic", lambda: clock[0])

    rl.hit("stale", 100, 10)
    # Jump past the GC horizon, then trip the periodic sweep deterministically.
    clock[0] = ratelimit._GC_HORIZON_SECONDS + 100
    rl._ops = 4095  # next hit() makes _ops % 4096 == 0, firing the sweep
    rl.hit("fresh", 100, 10)

    assert "stale" not in rl._events
    assert "fresh" in rl._events


# ── ConcurrencyLimiter ───────────────────────────────────────────────────────


def test_concurrency_caps_simultaneous_holders():
    cl = ConcurrencyLimiter()
    assert cl.acquire("u", 2)
    assert cl.acquire("u", 2)
    assert not cl.acquire("u", 2)  # at the cap


def test_concurrency_release_frees_a_slot():
    cl = ConcurrencyLimiter()
    assert cl.acquire("u", 1)
    assert not cl.acquire("u", 1)
    cl.release("u")
    assert cl.acquire("u", 1)


def test_concurrency_release_never_goes_negative():
    cl = ConcurrencyLimiter()
    cl.release("u")  # releasing an unheld key is a no-op
    assert cl.acquire("u", 1)


def test_concurrency_reset_clears_state():
    cl = ConcurrencyLimiter()
    cl.acquire("u", 1)
    cl.reset()
    assert cl.acquire("u", 1)


# ── settings-driven limits ───────────────────────────────────────────────────


def test_limit_for_uses_default_without_override(monkeypatch):
    monkeypatch.setattr(ratelimit, "_load_settings", dict)
    assert ratelimit.limit_for("login") == ratelimit.DEFAULT_LIMITS["login"]


def test_limit_for_honours_settings_override(monkeypatch):
    monkeypatch.setattr(
        ratelimit, "_load_settings", lambda: {"rate_limits": {"login": [3, 30]}}
    )
    assert ratelimit.limit_for("login") == (3, 30.0)


def test_limit_for_ignores_malformed_override(monkeypatch):
    monkeypatch.setattr(
        ratelimit, "_load_settings", lambda: {"rate_limits": {"login": "nope"}}
    )
    assert ratelimit.limit_for("login") == ratelimit.DEFAULT_LIMITS["login"]


def test_max_event_streams_default(monkeypatch):
    monkeypatch.setattr(ratelimit, "_load_settings", dict)
    assert ratelimit.max_event_streams() == ratelimit.DEFAULT_MAX_EVENT_STREAMS


def test_max_event_streams_override(monkeypatch):
    monkeypatch.setattr(
        ratelimit, "_load_settings", lambda: {"max_event_streams_per_user": 3}
    )
    assert ratelimit.max_event_streams() == 3


def test_max_event_streams_rejects_bool(monkeypatch):
    # ``True`` is an int in Python; it must not be accepted as a count of 1.
    monkeypatch.setattr(
        ratelimit, "_load_settings", lambda: {"max_event_streams_per_user": True}
    )
    assert ratelimit.max_event_streams() == ratelimit.DEFAULT_MAX_EVENT_STREAMS


# ── decorator wired into real routes ─────────────────────────────────────────


def test_rate_limit_message_names_the_wait():
    msg = ratelimit.rate_limit_message(1)
    assert "1 second" in msg
    assert "seconds" not in msg.replace("1 second", "")  # singular for 1
    assert "5 seconds" in ratelimit.rate_limit_message(5)


def test_login_route_is_rate_limited(client, app, monkeypatch):
    app.config["RATELIMIT_ENABLED"] = True
    monkeypatch.setattr(ratelimit, "limit_for", lambda name: (2, 60))
    ratelimit.reset_all()

    for _ in range(2):
        resp = client.post("/login", data={"username": "x", "password": "y"})
        assert resp.status_code == 200  # invalid creds, but not throttled yet

    resp = client.post("/login", data={"username": "x", "password": "y"})
    assert resp.status_code == 429
    assert resp.headers.get("Retry-After")
    # The friendly message is rendered into the login page, not a raw body.
    body = resp.get_data(as_text=True)
    assert "too quickly" in body
    assert "<form" in body.lower()  # still the real login page


def test_signup_route_rate_limit_renders_friendly_page(client, app, monkeypatch):
    app.config["RATELIMIT_ENABLED"] = True
    monkeypatch.setattr(ratelimit, "limit_for", lambda name: (1, 60))
    ratelimit.reset_all()

    client.post("/signup", data={"username": "a", "password": "b"})
    resp = client.post("/signup", data={"username": "a", "password": "b"})
    assert resp.status_code == 429
    body = resp.get_data(as_text=True)
    assert "too quickly" in body
    assert "<form" in body.lower()


def test_change_password_rate_limit_returns_json(alice, app, monkeypatch):
    app.config["RATELIMIT_ENABLED"] = True
    monkeypatch.setattr(ratelimit, "limit_for", lambda name: (1, 60))
    ratelimit.reset_all()

    # First call is allowed (it fails on the wrong current password, but still
    # consumes the single-request budget); the second is throttled.
    alice.post("/change-password", data={"current_password": "nope"})
    resp = alice.post("/change-password", data={"current_password": "nope"})
    assert resp.status_code == 429
    assert resp.headers.get("Retry-After")
    assert "too quickly" in resp.get_json()["error"]


def test_rate_limit_skipped_when_disabled(client, app, monkeypatch):
    app.config["RATELIMIT_ENABLED"] = False
    monkeypatch.setattr(ratelimit, "limit_for", lambda name: (1, 60))
    ratelimit.reset_all()

    for _ in range(5):
        resp = client.post("/login", data={"username": "x", "password": "y"})
        assert resp.status_code == 200  # never throttled


def test_send_route_is_rate_limited_per_user(alice, app, monkeypatch):
    app.config["RATELIMIT_ENABLED"] = True
    monkeypatch.setattr(ratelimit, "limit_for", lambda name: (2, 60))
    ratelimit.reset_all()

    for _ in range(2):
        resp = alice.post("/send/general", data={"text": "hi"})
        assert resp.status_code == 200

    resp = alice.post("/send/general", data={"text": "hi"})
    assert resp.status_code == 429


def test_events_stream_cap_returns_429(alice, app, monkeypatch):
    app.config["RATELIMIT_ENABLED"] = True
    monkeypatch.setattr(ratelimit, "max_event_streams", lambda: 1)
    ratelimit.reset_all()

    # Simulate one already-open stream for alice, exhausting her single slot.
    assert ratelimit.acquire_stream("alice")
    try:
        resp = alice.get("/events?channel=general")
        assert resp.status_code == 429
        assert resp.headers.get("Retry-After")
    finally:
        ratelimit.release_stream("alice")
