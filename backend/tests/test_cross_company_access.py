"""
A company's resources are changed only from inside it.

- ``POST /v1/discover_team`` with a ``company_id`` records the folder that
  company's agents write to: only its Managers may set it.
- ``POST /v1/generate`` bills a business unit for the run's tokens: only one
  of the company's own.
- A sprint's token total counts only its own company's audit rows, even when
  another company logged under the same ``task-<id>``.
"""

import secrets

import auth_tokens
import pytest
from config import settings
from models import (
    AuditLog,
    BacklogItem,
    BusinessUnit,
    Company,
    CompanyMember,
    ProjectDiscovery,
    Sprint,
    User,
)
from services.company_service import CompanyService
from sqlmodel import select


@pytest.fixture(autouse=True)
def enforcement(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path))
    key = secrets.token_urlsafe(48)
    monkeypatch.setattr(auth_tokens, "_configured_key", lambda: key)


def _user(session, label):
    user = User(
        email=f"{label}-{secrets.token_hex(6)}@example.com",
        full_name=label,
        password_hash="unused",
    )
    session.add(user)
    session.commit()
    token = auth_tokens.create_access_token(user_id=user.id, email=user.email)
    return user, {"Authorization": f"Bearer {token}"}


def _company(session, name, member=None, role="Owner"):
    company = Company(company_name=f"{name} {secrets.token_hex(3)}")
    session.add(company)
    session.commit()
    if member is not None:
        session.add(
            CompanyMember(company_id=company.id, user_id=member.id, human_role=role)
        )
        session.commit()
    return company


@pytest.fixture
def discovery(sqlite_session, tmp_path, monkeypatch):
    ProjectDiscovery.__table__.create(sqlite_session.get_bind(), checkfirst=True)
    monkeypatch.setattr(
        "services.discovery_service._ai_suggest_team", lambda *a, **k: None
    )
    folder = tmp_path / "chosen"
    folder.mkdir()
    (folder / "package.json").write_text("{}")
    return folder


def _paths(session, company_id):
    session.expire_all()
    return [
        row.project_path
        for row in session.exec(
            select(ProjectDiscovery).where(ProjectDiscovery.company_id == company_id)
        ).all()
    ]


@pytest.mark.parametrize(
    "role, detail",
    [(None, "Not a member of this company"), ("Viewer", "Requires Manager role")],
    ids=["outsider", "viewer"],
)
def test_only_a_manager_sets_where_the_companys_agents_write(
    test_client, sqlite_session, discovery, role, detail
):
    owner, _ = _user(sqlite_session, "owner")
    company = _company(sqlite_session, "Victim", owner)
    sqlite_session.add(
        ProjectDiscovery(
            company_id=company.id, project_path="/home/victim/app", status="completed"
        )
    )
    sqlite_session.commit()
    caller, headers = _user(sqlite_session, "caller")
    if role is not None:
        sqlite_session.add(
            CompanyMember(company_id=company.id, user_id=caller.id, human_role=role)
        )
        sqlite_session.commit()

    response = test_client.post(
        "/v1/discover_team",
        json={"company_id": company.id, "project_path": str(discovery)},
        headers=headers,
    )

    assert response.status_code == 403
    assert response.json() == {"detail": detail}
    assert _paths(sqlite_session, company.id) == ["/home/victim/app"]


def test_a_manager_sets_it(test_client, sqlite_session, discovery):
    manager, headers = _user(sqlite_session, "manager")
    company = _company(sqlite_session, "Mine", manager, role="Manager")

    response = test_client.post(
        "/v1/discover_team",
        json={"company_id": company.id, "project_path": str(discovery)},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert _paths(sqlite_session, company.id) == [str(discovery.resolve())]


@pytest.fixture
def published(monkeypatch):
    monkeypatch.setattr(settings, "AGENT_GRAPH_ENABLED", True)
    sent = []

    async def publish(subject, payload, msg_id=None):
        sent.append(payload)

    from app.main import app

    monkeypatch.setattr(app.state.nats_client, "publish", publish)
    return sent


def test_a_run_is_billed_only_to_the_companys_own_business_unit(
    test_client, sqlite_session, published
):
    owner, headers = _user(sqlite_session, "owner")
    mine = _company(sqlite_session, "Mine", owner)
    theirs = _company(sqlite_session, "Theirs")
    my_unit = BusinessUnit(company_id=mine.id, unit_name="Mine")
    their_unit = BusinessUnit(company_id=theirs.id, unit_name="Theirs")
    sqlite_session.add_all([my_unit, their_unit])
    sqlite_session.commit()

    def generate(unit_id):
        return test_client.post(
            "/v1/generate",
            json={"company_id": mine.id, "business_unit_id": unit_id, "story": "s"},
            headers=headers,
        )

    refused = generate(their_unit.id)
    assert refused.status_code == 403
    assert refused.json() == {
        "detail": "The business unit does not belong to this company"
    }
    assert generate(10**9).status_code == 403
    assert published == []

    assert generate(my_unit.id).status_code == 200
    assert published[-1]["business_unit_id"] == my_unit.id


def test_a_sprints_tokens_are_its_own_companys(sqlite_session):
    mine = _company(sqlite_session, "Tokens")
    theirs = _company(sqlite_session, "Other tokens")
    sprint = Sprint(company_id=mine.id, sprint_name="S")
    sqlite_session.add(sprint)
    sqlite_session.commit()
    item = BacklogItem(sprint_id=sprint.id, title="Task")
    sqlite_session.add(item)
    sqlite_session.commit()
    for company_id, tokens in ((mine.id, 30), (theirs.id, 1_000_000)):
        sqlite_session.add(
            AuditLog(
                company_id=company_id,
                interaction_id=f"task-{item.id}",
                action="agent_turn",
                cost_tokens=tokens,
            )
        )
    sqlite_session.commit()

    health = CompanyService(sqlite_session).get_project_health(sprint.id)

    assert health["tokens_consumed"] == 30
