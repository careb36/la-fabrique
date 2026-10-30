"""Login, registration and the desktop key exchange are rate-limited.

They are the routes that take a guess (a password, a voice key) from anyone
who can reach the port, so each client address gets a few tries a minute.
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
