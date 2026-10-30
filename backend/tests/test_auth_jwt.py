"""Tests for human-user JWT login and identity resolution."""

import secrets
from datetime import UTC, datetime, timedelta

import auth_tokens
import jwt
import pytest
from models.company import Company, User


@pytest.fixture
def signing_key(monkeypatch):
    key = secrets.token_urlsafe(48)
    monkeypatch.setattr(auth_tokens, "_configured_key", lambda: key)
    return key


def _register_user(client, email=None):
    if email is None:
        email = f"jules-{secrets.token_hex(8)}@example.com"
    response = client.post(
        "/v1/auth/register",
        json={
            "email": email,
            "full_name": "Jules Example",
            "password": "correct-password",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_correct_login_issues_an_access_token(test_client, signing_key):
    registered = _register_user(test_client)

    response = test_client.post(
        "/v1/auth/login",
        json={"email": registered["email"], "password": "correct-password"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 3600
    claims = auth_tokens.decode_access_token(body["access_token"])
    assert claims["sub"] == str(registered["user_id"])
    assert claims["typ"] == "access"


def test_wrong_password_returns_the_generic_authentication_error(
    test_client, signing_key
):
    registered = _register_user(test_client)

    response = test_client.post(
        "/v1/auth/login",
        json={"email": registered["email"], "password": "wrong-password"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid email or password"}


def test_unknown_email_matches_the_wrong_password_response(test_client, signing_key):
    registered = _register_user(test_client)
    wrong_password = test_client.post(
        "/v1/auth/login",
        json={"email": registered["email"], "password": "wrong-password"},
    )

    unknown_email = test_client.post(
        "/v1/auth/login",
        json={"email": "unknown@example.com", "password": "correct-password"},
    )

    assert unknown_email.status_code == 401
    assert unknown_email.json() == wrong_password.json()


def test_login_without_a_signing_key_returns_503_before_database_access(
    test_client, sqlite_session, monkeypatch
):
    monkeypatch.setattr(auth_tokens, "_configured_key", lambda: None)
    monkeypatch.setattr(
        sqlite_session,
        "exec",
        lambda *args, **kwargs: pytest.fail("login queried the database without a key"),
    )

    response = test_client.post(
        "/v1/auth/login",
        json={"email": "nobody@example.com", "password": "password"},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "Authentication is not configured"}


def test_me_returns_user_and_company_membership_without_password_hash(
    test_client, sqlite_session, signing_key
):
    registered = _register_user(test_client)
    company = Company(company_name="Acme Corp")
    sqlite_session.add(company)
    sqlite_session.commit()
    sqlite_session.refresh(company)

    invited = test_client.post(
        "/v1/company/invite",
        json={
            "company_id": company.id,
            "email": registered["email"],
            "human_role": "Manager",
        },
    )
    assert invited.status_code == 200
    token = auth_tokens.create_access_token(
        user_id=registered["user_id"],
        email=registered["email"],
    )

    response = test_client.get(
        "/v1/auth/me",
        headers={"Authorization": "Bearer " + token},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == registered["email"]
    assert body["memberships"] == [{"company_id": company.id, "human_role": "Manager"}]
    assert "password_hash" not in body


def test_me_without_authorization_header_returns_bearer_challenge(test_client):
    response = test_client.get("/v1/auth/me")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_me_rejects_an_expired_token(test_client, signing_key):
    token = auth_tokens.create_access_token(
        user_id=1,
        email="jules@example.com",
        expires_delta=timedelta(seconds=-1),
    )

    response = test_client.get(
        "/v1/auth/me",
        headers={"Authorization": "Bearer " + token},
    )

    assert response.status_code == 401


def test_me_rejects_a_token_signed_with_a_different_key(test_client, signing_key):
    token = jwt.encode(
        {
            "sub": "1",
            "email": "jules@example.com",
            "exp": datetime.now(UTC) + timedelta(minutes=5),
            "typ": "access",
        },
        secrets.token_urlsafe(48),
        algorithm="HS256",
    )

    response = test_client.get(
        "/v1/auth/me",
        headers={"Authorization": "Bearer " + token},
    )

    assert response.status_code == 401


def test_me_rejects_a_tampered_token(test_client, signing_key):
    token = auth_tokens.create_access_token(user_id=1, email="jules@example.com")
    header, payload, signature = token.split(".")
    flipped = "A" if payload[0] != "A" else "B"
    tampered_token = f"{header}.{flipped}{payload[1:]}.{signature}"

    response = test_client.get(
        "/v1/auth/me",
        headers={"Authorization": "Bearer " + tampered_token},
    )

    assert response.status_code == 401


def test_me_rejects_a_refresh_token(test_client, signing_key):
    token = jwt.encode(
        {
            "sub": "1",
            "email": "jules@example.com",
            "exp": datetime.now(UTC) + timedelta(minutes=5),
            "typ": "refresh",
        },
        signing_key,
        algorithm="HS256",
    )

    response = test_client.get(
        "/v1/auth/me",
        headers={"Authorization": "Bearer " + token},
    )

    assert response.status_code == 401


def test_me_rejects_a_token_for_a_deleted_user(
    test_client, sqlite_session, signing_key
):
    registered = _register_user(test_client)
    user = sqlite_session.get(User, registered["user_id"])
    sqlite_session.delete(user)
    sqlite_session.commit()
    token = auth_tokens.create_access_token(
        user_id=registered["user_id"],
        email=registered["email"],
    )

    response = test_client.get(
        "/v1/auth/me",
        headers={"Authorization": "Bearer " + token},
    )

    assert response.status_code == 401


def test_decode_access_token_wraps_malformed_jwt_errors(signing_key):
    with pytest.raises(auth_tokens.InvalidTokenError):
        auth_tokens.decode_access_token("not.a.jwt")
