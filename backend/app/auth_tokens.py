"""Creation and validation of signed human-user access tokens."""

from datetime import UTC, datetime, timedelta

import jwt


class AuthTokenError(Exception):
    """Base class for authentication-token failures."""


class AuthNotConfiguredError(AuthTokenError):
    """Raised when the JWT signing key is not configured."""


class InvalidTokenError(AuthTokenError):
    """Raised when a token is malformed, invalid, or expired."""


def _configured_key() -> str | None:
    """Return the configured JWT key, or ``None`` when unset or blank."""
    from config import settings

    key = getattr(settings, "JWT_SECRET_KEY", None)
    if key is None:
        return None
    key = key.strip()
    return key or None


def is_auth_configured() -> bool:
    """True when a JWT signing key is configured."""
    return _configured_key() is not None


def create_access_token(
    *,
    user_id: int,
    email: str,
    expires_delta: timedelta | None = None,
) -> str:
    """Create a signed access token for a human user."""
    from config import settings

    key = _configured_key()
    if key is None:
        raise AuthNotConfiguredError("JWT_SECRET_KEY is not configured")

    now = datetime.now(UTC)
    expires_at = now + (
        expires_delta
        if expires_delta is not None
        else timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    claims = {
        "sub": str(user_id),
        "email": email,
        "iat": now,
        "exp": expires_at,
        "typ": "access",
    }
    return jwt.encode(claims, key, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Verify an access token's signature, expiration, and token type."""
    from config import settings

    key = _configured_key()
    if key is None:
        raise AuthNotConfiguredError("JWT_SECRET_KEY is not configured")

    try:
        claims = jwt.decode(
            token,
            key,
            algorithms=[settings.JWT_ALGORITHM],
            options={"require": ["sub", "exp", "typ"]},
        )
    except (jwt.PyJWTError, TypeError, ValueError) as exc:
        raise InvalidTokenError("Invalid or expired token") from exc

    if claims.get("typ") != "access":
        raise InvalidTokenError("Invalid token type")
    return claims


STREAM_TICKET_MINUTES = 5


def create_stream_ticket(
    *, user_id: int, sprint_id: int, expires_delta: timedelta | None = None
) -> str:
    """A short-lived token that opens one sprint's Glassroom stream for *user_id*.

    A browser EventSource cannot send an Authorization header, so the stream
    takes this in its query string instead of the access token: it is good
    for one sprint and a few minutes, and membership is checked again when it
    is used.
    """
    from config import settings

    key = _configured_key()
    if key is None:
        raise AuthNotConfiguredError("JWT_SECRET_KEY is not configured")
    now = datetime.now(UTC)
    claims = {
        "sub": str(user_id),
        "sprint": sprint_id,
        "iat": now,
        "exp": now + (expires_delta or timedelta(minutes=STREAM_TICKET_MINUTES)),
        "typ": "glassroom",
    }
    return jwt.encode(claims, key, algorithm=settings.JWT_ALGORITHM)


def decode_stream_ticket(ticket: str, sprint_id: int) -> int:
    """The user a valid ticket for *sprint_id* was issued to; raises otherwise."""
    from config import settings

    key = _configured_key()
    if key is None:
        raise AuthNotConfiguredError("JWT_SECRET_KEY is not configured")
    try:
        claims = jwt.decode(
            ticket,
            key,
            algorithms=[settings.JWT_ALGORITHM],
            options={"require": ["sub", "exp", "typ", "sprint"]},
        )
        user_id = int(claims["sub"])
    except (jwt.PyJWTError, TypeError, ValueError) as exc:
        raise InvalidTokenError("Invalid or expired stream ticket") from exc
    if claims.get("typ") != "glassroom" or claims.get("sprint") != sprint_id:
        raise InvalidTokenError("The ticket is not for this sprint's stream")
    return user_id
