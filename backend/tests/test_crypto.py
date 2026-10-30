"""
Tests for credential encryption (``backend/app/crypto.py``).

Every test generates its own Fernet key with ``Fernet.generate_key()``. No key
is ever committed to this repository.
"""

import logging

import crypto
import pytest
from crypto import (
    FERNET_PREFIX,
    PLAINTEXT_PREFIX,
    CredentialDecryptionError,
    InvalidFernetKeyError,
    decrypt_value,
    encrypt_value,
    is_encryption_enabled,
)
from cryptography.fernet import Fernet


@pytest.fixture
def with_key(monkeypatch):
    """Configure a freshly generated Fernet key for the duration of a test."""
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(crypto, "_configured_key", lambda: key)
    return key


@pytest.fixture
def without_key(monkeypatch):
    """Simulate a deployment with no ``FERNET_SECRET_KEY`` configured."""
    monkeypatch.setattr(crypto, "_configured_key", lambda: None)
    # Reset the warn-once latch so a test can observe the warning.
    monkeypatch.setattr(crypto, "_missing_key_warned", False)


# ---------------------------------------------------------------------------
# Round trip
# ---------------------------------------------------------------------------


def test_round_trip_returns_the_original_value(with_key):
    secret = "ghp_a_github_token_value"
    stored = encrypt_value(secret)

    assert stored.startswith(FERNET_PREFIX)
    assert secret not in stored  # the plaintext must not survive in the column
    assert decrypt_value(stored) == secret


def test_round_trip_handles_unicode_and_empty_values(with_key):
    for secret in ("", "ключ-ñ-値", "x" * 5000):
        assert decrypt_value(encrypt_value(secret)) == secret


def test_encrypting_the_same_value_twice_gives_different_tokens(with_key):
    secret = "same-input-every-time"
    first, second = encrypt_value(secret), encrypt_value(secret)

    # Fernet embeds a timestamp and a random IV, so equal inputs must not
    # produce equal ciphertext; identical tokens would leak that two rows hold
    # the same credential.
    assert first != second
    assert decrypt_value(first) == decrypt_value(second) == secret


def test_is_encryption_enabled_reflects_configuration(with_key):
    assert is_encryption_enabled() is True


# ---------------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------------


def test_decryption_with_the_wrong_key_is_rejected(monkeypatch):
    right, wrong = Fernet.generate_key().decode(), Fernet.generate_key().decode()

    monkeypatch.setattr(crypto, "_configured_key", lambda: right)
    stored = encrypt_value("secret written under the first key")

    monkeypatch.setattr(crypto, "_configured_key", lambda: wrong)
    with pytest.raises(CredentialDecryptionError, match="different FERNET_SECRET_KEY"):
        decrypt_value(stored)


def test_a_tampered_token_is_rejected_rather_than_returning_garbage(with_key):
    stored = encrypt_value("secret")
    token = stored[len(FERNET_PREFIX) :]
    # Flip one character of the ciphertext body, past the version and timestamp.
    flipped = "B" if token[40] != "B" else "C"
    tampered = f"{FERNET_PREFIX}{token[:40]}{flipped}{token[41:]}"

    with pytest.raises(CredentialDecryptionError, match="tampered"):
        decrypt_value(tampered)


def test_an_encrypted_value_cannot_be_read_without_a_key(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(crypto, "_configured_key", lambda: key)
    stored = encrypt_value("secret")

    monkeypatch.setattr(crypto, "_configured_key", lambda: None)
    with pytest.raises(CredentialDecryptionError, match="not configured"):
        decrypt_value(stored)


def test_a_malformed_key_is_reported_clearly(monkeypatch):
    monkeypatch.setattr(crypto, "_configured_key", lambda: "not-a-valid-fernet-key")

    with pytest.raises(InvalidFernetKeyError, match="32 url-safe base64"):
        encrypt_value("secret")


# ---------------------------------------------------------------------------
# Fallback when no key is configured
# ---------------------------------------------------------------------------


def test_without_a_key_values_are_stored_prefixed_and_still_readable(without_key):
    stored = encrypt_value("secret")

    assert stored == f"{PLAINTEXT_PREFIX}secret"
    assert decrypt_value(stored) == "secret"
    assert is_encryption_enabled() is False


def test_the_missing_key_warning_is_logged_once(without_key, caplog):
    with caplog.at_level(logging.WARNING, logger="fabrique-backend"):
        encrypt_value("first")
        encrypt_value("second")
        encrypt_value("third")

    warnings = [r for r in caplog.records if "FERNET_SECRET_KEY" in r.getMessage()]
    assert len(warnings) == 1


def test_a_plaintext_prefixed_value_containing_the_prefix_round_trips(without_key):
    # Only the leading prefix is stripped; a value that happens to contain the
    # marker must come back intact.
    secret = f"{PLAINTEXT_PREFIX}embedded"
    assert decrypt_value(encrypt_value(secret)) == secret


# ---------------------------------------------------------------------------
# Rows written before this module existed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "legacy",
    [
        "vault_encrypted_placeholder",  # what every existing row actually holds
        "",
        "some-unprefixed-legacy-secret",
    ],
)
def test_legacy_unprefixed_rows_are_returned_unchanged(with_key, legacy):
    # Decryption must not crash on rows written before encryption existed,
    # whether or not a key is configured now.
    assert decrypt_value(legacy) == legacy


def test_legacy_rows_are_readable_without_a_key_too(without_key):
    assert decrypt_value("vault_encrypted_placeholder") == "vault_encrypted_placeholder"


# ---------------------------------------------------------------------------
# The write path
# ---------------------------------------------------------------------------


def test_init_company_stores_credentials_through_encrypt_value(
    sqlite_session, monkeypatch
):
    """The one production writer must not put a bare value in the column."""
    from models.company import ProjectCredential
    from services import company_service
    from sqlmodel import select

    key = Fernet.generate_key().decode()
    monkeypatch.setattr(crypto, "_configured_key", lambda: key)

    company_service.CompanyService(sqlite_session).init_company(
        company_name="Acme Corp",
        agents=[{"name": "Atlas", "role": "Developer"}],
        permissions={"github_token": "write"},
    )

    stored = sqlite_session.exec(select(ProjectCredential)).one()
    assert stored.encrypted_value.startswith(FERNET_PREFIX)
    assert decrypt_value(stored.encrypted_value) == "vault_encrypted_placeholder"
