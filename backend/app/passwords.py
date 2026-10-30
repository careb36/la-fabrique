"""Password hashing, on ``bcrypt`` directly.

This used to go through ``passlib``. It no longer can: passlib 1.7.4 (last
release, 2020) probes the bcrypt backend at import time with a 255-byte vector
to detect the ``$2a$`` wraparound bug. bcrypt 5.0 stopped truncating silently
above 72 bytes and raises instead, so the probe now fails, the backend is never
registered, and every hash and verify breaks — whatever the password length.

Talking to bcrypt directly removes the middle layer and, with it, the pin that
kept us on bcrypt 4.

The 72-byte limit is bcrypt's own, not ours. It is enforced where a password is
*chosen* (the request schema rejects longer ones) and tolerated where a
password is *checked*, because a stored hash made before the limit existed was
computed from the truncated bytes; refusing them at login would lock out
accounts that did nothing wrong.
"""

import logging

import bcrypt

logger = logging.getLogger(__name__)

# bcrypt hashes at most this many bytes and ignores the rest.
BCRYPT_MAX_BYTES = 72

# The cost passlib used by default. Matching it means existing hashes are not
# rewritten on every login; raising it later upgrades them one login at a time.
BCRYPT_ROUNDS = 12

_KNOWN_PREFIXES = ("$2a$", "$2b$", "$2y$")


class PasswordTooLong(ValueError):
    """A password exceeded bcrypt's 72-byte limit."""


def _encode(plain: str) -> bytes:
    return plain.encode("utf-8")


def hash_password(plain: str) -> str:
    """Hash a password the user has just chosen.

    Raises:
        PasswordTooLong: the UTF-8 form exceeds 72 bytes. The request schema
            rejects this first, so reaching here means a caller bypassed it.
    """
    raw = _encode(plain)
    if len(raw) > BCRYPT_MAX_BYTES:
        raise PasswordTooLong(
            f"password is {len(raw)} bytes; bcrypt hashes at most {BCRYPT_MAX_BYTES}"
        )
    return bcrypt.hashpw(raw, bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode("ascii")


def verify_password(plain: str, stored: str) -> bool:
    """Check a password against a stored hash.

    Accepts the ``$2a$``, ``$2b$`` and ``$2y$`` prefixes, so hashes written by
    passlib (and by other systems) keep working. A malformed stored hash is a
    failed check, not an exception: a corrupted row must not turn a login into
    a server error.
    """
    raw = _encode(plain)[:BCRYPT_MAX_BYTES]
    try:
        return bcrypt.checkpw(raw, stored.encode("ascii"))
    except ValueError:
        logger.warning("stored password hash is not a usable bcrypt hash")
        return False


def needs_rehash(stored: str) -> bool:
    """Whether a stored hash should be rewritten on the next successful login.

    True when the cost is below the current one, or when the hash is not in a
    shape we recognise. This is what ``deprecated="auto"`` used to do.
    """
    if not stored.startswith(_KNOWN_PREFIXES):
        return True
    parts = stored.split("$")
    if len(parts) < 4:
        return True
    try:
        return int(parts[2]) < BCRYPT_ROUNDS
    except ValueError:
        return True


def rehash_password(plain: str) -> str:
    """Hash a password that has just verified against an older hash.

    Truncates like the old hash did, so the password the user knows keeps
    working: the stored bytes were already computed from the truncated form.
    """
    return bcrypt.hashpw(
        _encode(plain)[:BCRYPT_MAX_BYTES], bcrypt.gensalt(rounds=BCRYPT_ROUNDS)
    ).decode("ascii")
