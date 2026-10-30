"""The desktop session: the launcher's key becomes the operator's web session.

The packaged product has one operator and no password prompt, so the browser
signs in with the same key the voice already uses. These tests pin the two
properties that make that safe: a wrong or missing key gets nothing, and the
account it signs in as owns the company the launcher bootstraps.
"""

import secrets

import auth_tokens
import pytest
from models.company import User
from sqlmodel import select


@pytest.fixture
def signing_key(monkeypatch):
    key = secrets.token_urlsafe(48)
    monkeypatch.setattr(auth_tokens, "_configured_key", lambda: key)
    return key


@pytest.fixture
def voice_key(monkeypatch):
    from config import settings

    key = secrets.token_urlsafe(24)
    monkeypatch.setattr(settings, "VOICE_API_KEY", key)
    return key


def test_the_voice_key_opens_a_session_for_the_desktop_operator(
    test_client, signing_key, voice_key
):
    response = test_client.post("/v1/auth/desktop", headers={"X-Voice-Key": voice_key})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["email"] == "escritorio@fabrica.local"
    claims = auth_tokens.decode_access_token(body["access_token"])
    assert claims["email"] == "escritorio@fabrica.local"


def test_the_session_identifies_as_the_operator(test_client, signing_key, voice_key):
    token = test_client.post(
        "/v1/auth/desktop", headers={"X-Voice-Key": voice_key}
    ).json()["access_token"]

    me = test_client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert me.status_code == 200
    assert me.json()["email"] == "escritorio@fabrica.local"


def test_a_wrong_key_gets_no_session(test_client, signing_key, voice_key):
    response = test_client.post(
        "/v1/auth/desktop", headers={"X-Voice-Key": "not-the-key"}
    )

    assert response.status_code == 401
    assert "X-Voice-Key" in response.json()["detail"]


def test_without_a_configured_key_the_endpoint_refuses(test_client, signing_key, monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "VOICE_API_KEY", None)

    response = test_client.post("/v1/auth/desktop", headers={"X-Voice-Key": ""})

    assert response.status_code == 401


def test_repeat_sessions_reuse_one_account(
    test_client, sqlite_session, signing_key, voice_key
):
    test_client.post("/v1/auth/desktop", headers={"X-Voice-Key": voice_key})
    test_client.post("/v1/auth/desktop", headers={"X-Voice-Key": voice_key})

    users = sqlite_session.exec(
        select(User).where(User.email == "escritorio@fabrica.local")
    ).all()

    assert len(users) == 1


def test_the_operator_owns_the_company_the_launcher_created(
    test_client, signing_key, voice_key
):
    token = test_client.post(
        "/v1/auth/desktop", headers={"X-Voice-Key": voice_key}
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    created = test_client.post(
        "/v1/init_company",
        json={
            "company_name": "Escritorio",
            "agents": [{"name": "Atlas", "role": "PO", "seniority": "Senior",
                        "specialty": "product"}],
        },
        headers=headers,
    )
    assert created.status_code == 200, created.text

    me = test_client.get("/v1/auth/me", headers=headers).json()
    company_id = created.json()["company_id"]

    assert {"company_id": company_id, "human_role": "Owner"} in me["memberships"]
