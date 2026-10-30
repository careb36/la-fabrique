"""
Symmetric encryption for credentials held in ``ProjectCredential.encrypted_value``.

Uses Fernet (AES-128-CBC with an HMAC-SHA256 authentication tag) from the
``cryptography`` package. Fernet is authenticated, so a value that has been
tampered with fails loudly on decryption instead of returning garbage.

Stored values carry an explicit prefix describing their shape:

``fernet:<token>``
    Ciphertext produced by :func:`encrypt_value` while ``FERNET_SECRET_KEY``
    was configured.

``plaintext:<value>``
    Written by :func:`encrypt_value` when no key is configured. This keeps a
    developer without a key unblocked while making the situation obvious to
    anyone reading the table.

Anything else
    A legacy row written before this module existed. :func:`decrypt_value`
    returns it unchanged rather than failing, so existing databases keep
    working with no migration.

Tagging the ciphertext rather than sniffing the Fernet token's byte layout
keeps the three cases unambiguous, and makes a row's state obvious to a human
reading the column.

Generate a key with::

    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""

from __future__ import annotations

import logging
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger("fabrique-backend")

FERNET_PREFIX = "fernet:"
PLAINTEXT_PREFIX = "plaintext:"

# Set once the "no key configured" warning has been emitted, so a backend
# running without a key logs it a single time rather than on every write.
_missing_key_warned = False


class CredentialCryptoError(Exception):
    """Base class for every failure raised by this module."""


class InvalidFernetKeyError(CredentialCryptoError):
    """``FERNET_SECRET_KEY`` is set but is not a valid Fernet key."""


class CredentialDecryptionError(CredentialCryptoError):
    """A stored ciphertext could not be decrypted.

    Raised when the token was tampered with, was encrypted under a different
    key, or when no key is configured to decrypt it with.
    """


def _configured_key() -> str | None:
    """Return the configured Fernet key, or ``None`` when unset or blank."""
    from config import settings  # imported lazily so this module loads without env

    key = getattr(settings, "FERNET_SECRET_KEY", None)
    if key is None:
        return None
    key = key.strip()
    return key or None


@lru_cache(maxsize=8)
def _fernet_for(key: str) -> Fernet:
    """Build (and cache) a Fernet instance for *key*.

    Raises:
        InvalidFernetKeyError: if *key* is not a valid 32-byte urlsafe-base64 key.
    """
    try:
        return Fernet(key.encode("utf-8"))
    except (ValueError, TypeError) as exc:
        raise InvalidFernetKeyError(
            "FERNET_SECRET_KEY is not a valid Fernet key. It must be 32 "
            "url-safe base64-encoded bytes. Generate one with: python -c "
            '"from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"'
        ) from exc


def is_encryption_enabled() -> bool:
    """True when a Fernet key is configured, so writes will be encrypted."""
    return _configured_key() is not None


def encrypt_value(plaintext: str) -> str:
    """Encrypt *plaintext* for storage in ``ProjectCredential.encrypted_value``.

    With a key configured, returns ``fernet:<token>``. Without one, returns
    ``plaintext:<value>`` and logs a warning the first time, so local
    development is not blocked but the gap is visible.

    Raises:
        InvalidFernetKeyError: if a key is configured but malformed.
    """
    global _missing_key_warned

    key = _configured_key()
    if key is None:
        if not _missing_key_warned:
            _missing_key_warned = True
            logger.warning(
                "FERNET_SECRET_KEY is not configured — credential values are "
                "being stored unencrypted with a '%s' prefix. Set the key to "
                "encrypt them at rest.",
                PLAINTEXT_PREFIX.rstrip(":"),
            )
        return f"{PLAINTEXT_PREFIX}{plaintext}"

    token = _fernet_for(key).encrypt(plaintext.encode("utf-8")).decode("utf-8")
    return f"{FERNET_PREFIX}{token}"


def decrypt_value(stored: str) -> str:
    """Return the plaintext behind a value read from ``encrypted_value``.

    Handles all three stored shapes: a ``fernet:`` token, a ``plaintext:``
    fallback, and a legacy unprefixed value from before this module existed.

    Raises:
        CredentialDecryptionError: if a ``fernet:`` token cannot be decrypted,
            because it was tampered with, was written under a different key,
            or because no key is configured.
        InvalidFernetKeyError: if the configured key is malformed.
    """
    if stored.startswith(PLAINTEXT_PREFIX):
        return stored[len(PLAINTEXT_PREFIX) :]

    if not stored.startswith(FERNET_PREFIX):
        # Legacy row written before encryption existed. Pass it through rather
        # than failing, so existing databases keep working without a migration.
        return stored

    token = stored[len(FERNET_PREFIX) :]
    key = _configured_key()
    if key is None:
        raise CredentialDecryptionError(
            "Cannot decrypt a stored credential: the value is encrypted but "
            "FERNET_SECRET_KEY is not configured."
        )

    try:
        return _fernet_for(key).decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise CredentialDecryptionError(
            "Stored credential failed authentication. It was either tampered "
            "with or encrypted under a different FERNET_SECRET_KEY."
        ) from exc
