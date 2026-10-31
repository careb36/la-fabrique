"""Login, registration and the desktop key exchange are rate-limited.

They are the routes that take a guess (a password, a voice key) from anyone
who can reach the port, so each client address gets a few tries a minute.
"""

import pytest
from config import settings
from security import RATE_LIMIT_EXEMPT, check_default_rate_limit, limiter


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
        ("/v1/auth/desktop", None),
        ("/v1/auth/desktop/handoff", None),
        ("/v1/auth/desktop/redeem", {"code": "guess"}),
    ],
)
def test_guessing_is_cut_off_after_the_limit(test_client, limits_on, path, body):
    allowed = int(settings.AUTH_RATE_LIMIT.split("/")[0])
    statuses = [
        test_client.post(path, json=body, headers={"X-Voice-Key": "guess"}).status_code
        for _ in range(allowed + 1)
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


def test_exempt_routes_skip_the_default_limit(monkeypatch):
    from types import SimpleNamespace

    checked = []
    monkeypatch.setattr(
        limiter,
        "_check_request_limit",
        lambda *args, **kwargs: checked.append(args),
    )
    for path in RATE_LIMIT_EXEMPT:
        request = SimpleNamespace(
            url=SimpleNamespace(path=path),
            scope={"endpoint": test_exempt_routes_skip_the_default_limit},
        )
        check_default_rate_limit(request)

    assert checked == []
