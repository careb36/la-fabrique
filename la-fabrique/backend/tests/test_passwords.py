"""Password hashing on bcrypt directly, and the limits that come with it.

The hashes below were written by passlib 1.7.4 against bcrypt 4.3 before this
module existed. They are literals on purpose: passlib is no longer a
dependency, so a hash it produced is the only way to keep proving that accounts
created before the migration can still log in.
"""

import secrets

import auth_tokens
import bcrypt
import pytest
from models.company import User
from passwords import (
    BCRYPT_MAX_BYTES,
    BCRYPT_ROUNDS,
    PasswordTooLong,
    hash_password,
    needs_rehash,
    rehash_password,
    verify_password,
)
from sqlmodel import select

# passlib CryptContext(schemes=["bcrypt"], deprecated="auto"), cost 12.
PASSLIB_HASH = "$2b$12$J0AYnteKcsJtRY4lSo/1DeFLf1WfDCmdnPjp4bfb/HiGXecgYKDge"
PASSLIB_PASSWORD = "correct horse battery staple"

# Same digest under the two older prefixes. Other systems still emit these.
HASH_2A = "$2a$12$AiuaupvWVhpxDDZj1UB0.OODVtmDLMIYioAwAU8TA0fdv7dKNH8L2"
HASH_2Y = "$2y$12$AiuaupvWVhpxDDZj1UB0.OODVtmDLMIYioAwAU8TA0fdv7dKNH8L2"
LEGACY_PASSWORD = "legacy-2a"


# ---------------------------------------------------------------------------
# The primitives
# ---------------------------------------------------------------------------


def test_a_password_verifies_against_its_own_hash():
    stored = hash_password("hunter2-but-longer")

    assert verify_password("hunter2-but-longer", stored)
    assert not verify_password("hunter2-but-longeR", stored)
    assert stored.startswith("$2b$")


def test_the_hash_is_salted_so_the_same_password_hashes_differently():
    assert hash_password("same password") != hash_password("same password")


@pytest.mark.parametrize(
    ("stored", "password"),
    [
        (PASSLIB_HASH, PASSLIB_PASSWORD),
        (HASH_2A, LEGACY_PASSWORD),
        (HASH_2Y, LEGACY_PASSWORD),
    ],
    ids=["passlib-2b", "2a", "2y"],
)
def test_hashes_written_before_the_migration_still_verify(stored, password):
    assert verify_password(password, stored)


def test_a_malformed_stored_hash_fails_the_check_instead_of_raising():
    # A corrupted row must read as a wrong password, not as a server error.
    assert verify_password("anything", "not-a-bcrypt-hash") is False
    assert verify_password("anything", "") is False


def test_hashing_refuses_a_password_beyond_bcrypts_limit():
    assert len(hash_password("x" * BCRYPT_MAX_BYTES))

    with pytest.raises(PasswordTooLong):
        hash_password("x" * (BCRYPT_MAX_BYTES + 1))


def test_the_limit_counts_bytes_not_characters():
    # "ñ" is two bytes in UTF-8, so 37 of them already exceed 72 bytes.
    assert verify_password("ñ" * 36, hash_password("ñ" * 36))

    with pytest.raises(PasswordTooLong):
        hash_password("ñ" * 37)


def test_a_legacy_password_longer_than_the_limit_still_verifies():
    # Before the limit was enforced, bcrypt quietly ignored everything past
    # byte 72. A stored hash therefore matches the truncated form, and login
    # must accept the password the user actually types.
    legacy = bcrypt.hashpw(b"y" * BCRYPT_MAX_BYTES, bcrypt.gensalt()).decode("ascii")

    assert verify_password("y" * BCRYPT_MAX_BYTES + "ignored tail", legacy)


# ---------------------------------------------------------------------------
# Re-hashing on login
# ---------------------------------------------------------------------------


def test_a_hash_at_the_current_cost_needs_no_rewrite():
    # passlib also used cost 12, so a migrated database is not rewritten.
    assert needs_rehash(hash_password("anything")) is False
    assert needs_rehash(PASSLIB_HASH) is False


def test_a_cheaper_hash_is_marked_for_rewrite():
    cheap = bcrypt.hashpw(b"anything", bcrypt.gensalt(rounds=4)).decode("ascii")

    assert needs_rehash(cheap) is True


def test_an_unrecognised_hash_is_marked_for_rewrite():
    assert needs_rehash("$argon2id$v=19$m=65536,t=3,p=4$c2FsdA$aGFzaA") is True
    assert needs_rehash("garbage") is True


def test_rehashing_keeps_the_same_password_working():
    rewritten = rehash_password(LEGACY_PASSWORD)

    assert rewritten != HASH_2A
    assert verify_password(LEGACY_PASSWORD, rewritten)


# ---------------------------------------------------------------------------
# Through the API
# ---------------------------------------------------------------------------


@pytest.fixture
def signing_key(monkeypatch):
    # Login answers 503 until JWT_SECRET_KEY is set; the fixture substitutes a
    # throwaway key instead of asking the suite to configure one.
    key = secrets.token_urlsafe(48)
    monkeypatch.setattr(auth_tokens, "_configured_key", lambda: key)
    return key


def _register(client, email, password):
    return client.post(
        "/v1/auth/register",
        json={"email": email, "full_name": "Ada Example", "password": password},
    )


def _add_user(session, email, password_hash):
    user = User(email=email, full_name="Ada Example", password_hash=password_hash)
    session.add(user)
    session.commit()
    return user


def test_registering_with_a_password_beyond_the_limit_is_refused(test_client):
    response = _register(
        test_client, "too-long@example.com", "x" * (BCRYPT_MAX_BYTES + 1)
    )

    assert response.status_code == 422
    assert str(BCRYPT_MAX_BYTES) in response.text


def test_registering_with_exactly_the_limit_is_accepted(test_client):
    response = _register(test_client, "edge@example.com", "x" * BCRYPT_MAX_BYTES)

    assert response.status_code == 200, response.text


def test_a_passlib_account_can_log_in_after_the_migration(
    test_client, sqlite_session, signing_key
):
    # The whole point of the migration: an account created while the app used
    # passlib authenticates unchanged.
    _add_user(sqlite_session, "old@example.com", PASSLIB_HASH)

    response = test_client.post(
        "/v1/auth/login",
        json={"email": "old@example.com", "password": PASSLIB_PASSWORD},
    )

    assert response.status_code == 200, response.text


def test_logging_in_with_a_cheap_hash_rewrites_it_at_the_current_cost(
    test_client, sqlite_session, signing_key
):
    cheap = bcrypt.hashpw(b"cheap-password", bcrypt.gensalt(rounds=4)).decode("ascii")
    _add_user(sqlite_session, "rewrite@example.com", cheap)

    response = test_client.post(
        "/v1/auth/login",
        json={"email": "rewrite@example.com", "password": "cheap-password"},
    )

    assert response.status_code == 200, response.text
    stored = sqlite_session.exec(
        select(User).where(User.email == "rewrite@example.com")
    ).one()
    assert stored.password_hash != cheap
    assert needs_rehash(stored.password_hash) is False
    assert verify_password("cheap-password", stored.password_hash)


def test_a_failed_login_does_not_rewrite_the_stored_hash(
    test_client, sqlite_session, signing_key
):
    cheap = bcrypt.hashpw(b"cheap-password", bcrypt.gensalt(rounds=4)).decode("ascii")
    _add_user(sqlite_session, "wrong@example.com", cheap)

    response = test_client.post(
        "/v1/auth/login",
        json={"email": "wrong@example.com", "password": "wrong-password"},
    )

    assert response.status_code == 401
    stored = sqlite_session.exec(
        select(User).where(User.email == "wrong@example.com")
    ).one()
    assert stored.password_hash == cheap


def test_a_legacy_account_with_a_long_password_can_still_log_in(
    test_client, sqlite_session, signing_key
):
    # Refusing this at login would lock out an account that did nothing wrong;
    # only registration enforces the limit.
    long_password = "z" * 100
    legacy = bcrypt.hashpw(
        long_password.encode()[:BCRYPT_MAX_BYTES], bcrypt.gensalt()
    ).decode("ascii")
    _add_user(sqlite_session, "legacy-long@example.com", legacy)

    response = test_client.post(
        "/v1/auth/login",
        json={"email": "legacy-long@example.com", "password": long_password},
    )

    assert response.status_code == 200, response.text


def test_the_new_hash_uses_the_configured_cost(test_client, sqlite_session):
    _register(test_client, "cost@example.com", "a-password")
    stored = sqlite_session.exec(
        select(User).where(User.email == "cost@example.com")
    ).one()

    assert stored.password_hash.split("$")[2] == f"{BCRYPT_ROUNDS:02d}"
