"""
Who may use the voice façade, and on which company.

The voice routes take two credentials: the desktop's shared key, or a signed-in
user. The key reaches one company (``VOICE_COMPANY_ID``, else the oldest); a
user reaches the companies they belong to, as a Viewer to read and a Manager to
change anything. The desktop operator's account cannot be claimed by
registering its email first.
"""

import secrets

import auth_tokens
import pytest
from config import settings
from models import Company, CompanyMember, User
from models.agent_run import AgentRunApproval
from sqlalchemy import inspect
from sqlmodel import SQLModel, delete, select


@pytest.fixture(autouse=True)
def _clean_database(sqlite_session):
    _wipe(sqlite_session)
    yield
    _wipe(sqlite_session)


def _wipe(session):
    session.rollback()
    existing = set(inspect(session.get_bind()).get_table_names())
    for table in reversed(SQLModel.metadata.sorted_tables):
        if table.name in existing:
            session.exec(delete(table))
    session.commit()


@pytest.fixture
def signing_key(monkeypatch):
    key = secrets.token_urlsafe(48)
    monkeypatch.setattr(auth_tokens, "_configured_key", lambda: key)
    return key


@pytest.fixture
def voice_key(monkeypatch):
    key = secrets.token_urlsafe(24)
    monkeypatch.setattr(settings, "VOICE_API_KEY", key)
    monkeypatch.setattr(settings, "VOICE_COMPANY_ID", None)
    return key


def _company(session, name):
    company = Company(company_name=name)
    session.add(company)
    session.commit()
    session.refresh(company)
    return company


def _user(session, company=None, role=None):
    user = User(
        email=f"u-{secrets.token_hex(6)}@example.com",
        full_name="Someone",
        password_hash="unused",
    )
    session.add(user)
    session.commit()
    if company is not None:
        session.add(
            CompanyMember(company_id=company.id, user_id=user.id, human_role=role)
        )
        session.commit()
    token = auth_tokens.create_access_token(user_id=user.id, email=user.email)
    return {"Authorization": f"Bearer {token}"}


def _command(client, headers, **payload):
    response = client.post("/v1/voice/command", json=payload, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


# --- a signed-in user -------------------------------------------------------


def test_a_user_cannot_read_a_company_they_do_not_belong_to(
    sqlite_session, test_client, signing_key, voice_key
):
    _company(sqlite_session, "Theirs")
    other = _company(sqlite_session, "Other")
    stranger = _user(sqlite_session)

    for action in ("estado", "equipo", "sprints"):
        body = _command(test_client, stranger, action=action, company_id=other.id)
        assert body["ok"] is False, action
        assert "permiso" in body["speech"]

    status = test_client.get(
        "/v1/voice/status", params={"company_id": other.id}, headers=stranger
    ).json()
    assert status["ok"] is False


def test_a_user_lists_only_their_own_companies(
    sqlite_session, test_client, signing_key, voice_key
):
    mine = _company(sqlite_session, "Mine")
    _company(sqlite_session, "Someone else's")
    viewer = _user(sqlite_session, mine, "Viewer")

    body = _command(test_client, viewer, action="empresas")

    assert [c["id"] for c in body["data"]["companies"]] == [mine.id]
    assert "Someone else" not in body["speech"]


def test_a_viewer_reads_but_cannot_assign_or_decide(
    sqlite_session, test_client, signing_key, voice_key
):
    company = _company(sqlite_session, "Acme")
    viewer = _user(sqlite_session, company, "Viewer")

    assert _command(test_client, viewer, action="estado")["ok"] is True
    for action in ("asignar", "despachar", "pausar", "aprobar", "crear_sprint"):
        body = _command(test_client, viewer, action=action, text="do it", agent="QA")
        assert body["ok"] is False, action
        assert "permiso" in body["speech"], action


def test_a_user_cannot_build_without_being_a_manager(
    sqlite_session, test_client, signing_key, voice_key
):
    company = _company(sqlite_session, "Acme")
    viewer = _user(sqlite_session, company, "Viewer")

    body = test_client.post(
        "/v1/voice/build", json={"texto": "una página"}, headers=viewer
    ).json()

    assert body["ok"] is False
    assert "permiso" in body["speech"]


def test_a_build_request_has_a_size_limit(test_client, voice_key):
    response = test_client.post(
        "/v1/voice/build",
        json={"texto": "x" * 4001},
        headers={"X-Voice-Key": voice_key},
    )
    assert response.status_code == 422


# --- the shared key -----------------------------------------------------------


def test_the_key_reaches_only_its_own_company(sqlite_session, test_client, voice_key):
    first = _company(sqlite_session, "First")
    second = _company(sqlite_session, "Second")
    key = {"X-Voice-Key": voice_key}

    assert _command(test_client, key, action="estado")["company_id"] == first.id
    denied = _command(test_client, key, action="estado", company_id=second.id)
    assert denied["ok"] is False
    listing = _command(test_client, key, action="empresas")
    assert [c["id"] for c in listing["data"]["companies"]] == [first.id]


def test_the_key_follows_voice_company_id(
    sqlite_session, test_client, voice_key, monkeypatch
):
    _company(sqlite_session, "First")
    second = _company(sqlite_session, "Second")
    monkeypatch.setattr(settings, "VOICE_COMPANY_ID", second.id)

    body = _command(test_client, {"X-Voice-Key": voice_key}, action="estado")

    assert body["company_id"] == second.id


def test_a_non_ascii_key_is_refused_not_a_server_error(test_client, voice_key):
    # Starlette decodes header bytes as latin-1, so this arrives as "ÿ".
    response = test_client.post(
        "/v1/voice/command",
        json={"action": "estado"},
        headers={"X-Voice-Key": "ÿ".encode("latin-1")},
    )
    assert response.status_code == 401


def test_an_approval_by_key_is_recorded_as_the_key_not_a_chosen_name(
    sqlite_session, test_client, voice_key, monkeypatch, tmp_path
):
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path))
    company = _company(sqlite_session, "Acme")
    run = test_client.post(
        "/v1/agent_runs",
        json={
            "company_id": company.id,
            "external_ref": "voice-run:1",
            "producer": "copilot",
            "artifact": "diff contents",
        },
    ).json()

    body = _command(
        test_client,
        {"X-Voice-Key": voice_key},
        action="aprobar",
        run_id=run["id"],
        approver_name="The CEO",
    )

    assert body["ok"] is True
    approval = sqlite_session.exec(
        select(AgentRunApproval).where(AgentRunApproval.agent_run_id == run["id"])
    ).one()
    assert approval.approver_name == "voice-key"


# --- the desktop operator ---------------------------------------------------


def test_the_desktop_email_cannot_be_registered(test_client):
    for email in (
        "escritorio@fabrica.local",
        "Escritorio@Fabrica.Local",
        "x@fabrica.local",
    ):
        response = test_client.post(
            "/v1/auth/register",
            json={"email": email, "password": "a-long-password-1", "full_name": "X"},
        )
        assert response.status_code == 400, email


def test_a_desktop_account_registered_earlier_loses_its_password(
    sqlite_session, test_client, signing_key, voice_key
):
    # An install from before the domain was reserved may hold such an account.
    from passwords import hash_password

    company = _company(sqlite_session, "Acme")
    planted = User(
        email="escritorio@fabrica.local",
        full_name="Planted",
        password_hash=hash_password("attacker-knows-this"),
    )
    sqlite_session.add(planted)
    sqlite_session.commit()

    exchanged = test_client.post("/v1/auth/desktop", headers={"X-Voice-Key": voice_key})
    assert exchanged.status_code == 200, exchanged.text

    login = test_client.post(
        "/v1/auth/login",
        json={"email": "escritorio@fabrica.local", "password": "attacker-knows-this"},
    )
    assert login.status_code == 401
    member = sqlite_session.exec(
        select(CompanyMember).where(CompanyMember.user_id == planted.id)
    ).one()
    assert member.company_id == company.id
