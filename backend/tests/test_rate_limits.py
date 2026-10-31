"""Login is rate-limited tightly, and every other API route by default.

Login takes a guess (a password) from anyone who can reach the port, so each
client address gets a few tries a minute.
"""

import pytest
from config import settings
from security import limiter


@pytest.fixture
def limits_on(monkeypatch):
    monkeypatch.setattr(limiter, "enabled", True)
    limiter.reset()
    yield
    limiter.reset()


@pytest.mark.parametrize(
    "path, body",
    [
        ("/v1/auth/login", {"email": "x@example.com", "password": "wrong-password-1"}),
    ],
)
def test_guessing_is_cut_off_after_the_limit(test_client, limits_on, path, body):
    allowed = int(settings.AUTH_RATE_LIMIT.split("/")[0])
    statuses = [
        test_client.post(path, json=body).status_code for _ in range(allowed + 1)
    ]
    assert 429 not in statuses[:allowed]
    assert statuses[-1] == 429


def _limit_of(spec: str) -> int:
    return int(spec.split("/")[0])


def test_every_other_route_gets_the_default_limit(test_client, limits_on):
    # Before the middleware was installed, RATE_LIMIT_DEFAULT was configured
    # and applied to nothing.
    allowed = _limit_of(settings.RATE_LIMIT_DEFAULT)
    statuses = [
        test_client.get("/v1/capabilities").status_code for _ in range(allowed + 1)
    ]
    assert 429 not in statuses[:allowed]
    assert statuses[-1] == 429


def test_probes_are_never_limited(test_client, limits_on):
    allowed = _limit_of(settings.RATE_LIMIT_DEFAULT)
    statuses = {test_client.get("/health").status_code for _ in range(allowed + 5)}
    assert statuses == {200}


def test_only_the_api_counts_and_the_stream_never_does():
    from security import is_rate_limited

    assert is_rate_limited("/v1/capabilities")
    assert is_rate_limited("/v1/auth/login")
    assert not is_rate_limited("/v1/glassroom/stream")
    for path in (
        "/health",
        "/health/deep",
        "/metrics",
        "/docs",
        "/",
        "/assets/index.js",
    ):
        assert not is_rate_limited(path)


def _allowed_origin() -> str:
    from security import get_cors_origins

    origin = get_cors_origins()[0]
    return "http://localhost:5173" if origin == "*" else origin


def test_a_limited_answer_still_carries_the_cors_headers(test_client, limits_on):
    # The limiter used to sit outside CORS: a browser saw a network error
    # instead of a 429 it could read.
    origin = _allowed_origin()
    allowed = _limit_of(settings.RATE_LIMIT_DEFAULT)
    for _ in range(allowed):
        test_client.get("/v1/capabilities", headers={"Origin": origin})
    limited = test_client.get("/v1/capabilities", headers={"Origin": origin})
    assert limited.status_code == 429
    assert limited.headers.get("access-control-allow-origin") in {origin, "*"}


def test_preflights_never_count(test_client, limits_on):
    origin = _allowed_origin()
    allowed = _limit_of(settings.RATE_LIMIT_DEFAULT)
    preflight = {"Origin": origin, "Access-Control-Request-Method": "GET"}
    statuses = {
        test_client.options("/v1/capabilities", headers=preflight).status_code
        for _ in range(allowed + 5)
    }
    assert 429 not in statuses
    assert test_client.get("/v1/capabilities").status_code == 200


def test_a_remote_store_is_asked_off_the_event_loop(
    test_client, limits_on, monkeypatch
):
    import asyncio

    import security

    seen = []
    real_hit = security.limiter._limiter.hit

    def on_the_loop() -> bool:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return False
        return True

    def hit(*args):
        seen.append(on_the_loop())
        return real_hit(*args)

    monkeypatch.setattr(security, "_LOCAL_STORAGE", False)
    monkeypatch.setattr(security.limiter._limiter, "hit", hit)
    assert test_client.get("/v1/capabilities").status_code == 200
    assert seen and not any(seen), "the store was called on the event loop's thread"
