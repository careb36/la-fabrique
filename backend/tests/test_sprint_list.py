"""``GET /v1/sprints`` — a company's sprints with progress, scoped by membership."""

import secrets

import auth_tokens
import pytest
from config import settings
from models import BacklogItem, Company, CompanyMember, Sprint, User
from services import console_assistants, scrum_master
from services.board import CARRIED_FROM_PREFIX
from services.orchestration_metrics import (
    ARCHITECT_COMMENT_AUTHOR,
    format_architect_consult_comment,
)
from sqlmodel import select


@pytest.fixture
def signing_key(monkeypatch):
    key = secrets.token_urlsafe(48)
    monkeypatch.setattr(auth_tokens, "_configured_key", lambda: key)
    return key


def _company(session, name):
    company = Company(company_name=name)
    session.add(company)
    session.commit()
    return company


def _sprint(session, company_id, name, statuses=(), **fields):
    sprint = Sprint(company_id=company_id, sprint_name=name, **fields)
    session.add(sprint)
    session.flush()
    for index, status in enumerate(statuses):
        session.add(
            BacklogItem(sprint_id=sprint.id, title=f"{name} {index}", status=status)
        )
    session.commit()
    return sprint


def _user_headers(session, company_id=None, role="Viewer"):
    user = User(
        email=f"list-{secrets.token_hex(8)}@example.com",
        full_name="Sprint list reader",
        password_hash="unused",
    )
    session.add(user)
    session.commit()
    if company_id is not None:
        session.add(
            CompanyMember(company_id=company_id, user_id=user.id, human_role=role)
        )
        session.commit()
    token = auth_tokens.create_access_token(user_id=user.id, email=user.email)
    return {"Authorization": f"Bearer {token}"}


def test_member_lists_own_sprints_newest_first_with_progress(
    test_client, sqlite_session, signing_key, monkeypatch
):
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    mine = _company(sqlite_session, "Sprint list owner")
    other = _company(sqlite_session, "Sprint list other tenant")
    older = _sprint(
        sqlite_session,
        mine.id,
        "Foundation",
        statuses=("done", "todo", "blocked"),
        start_date="2026-10-01",
        goal="Lay the base",
        scope_size="S",
        status="completed",
    )
    reworked = sqlite_session.exec(
        select(BacklogItem).where(BacklogItem.sprint_id == older.id)
    ).first()
    reworked.comments = [
        {"author": "QA", "text": "NEEDS WORK: add a test"},
        {"author": "Dev", "text": "Delivered again"},
        {"author": "Verifier", "text": "Delivery verified: 2 files written"},
        {"author": "Quality gate", "text": "NEEDS WORK: too short"},
    ]
    sqlite_session.add(reworked)
    sqlite_session.commit()
    newer = _sprint(sqlite_session, mine.id, "Hardening", start_date="2026-10-15")
    _sprint(sqlite_session, other.id, "Someone else's", statuses=("done",))
    headers = _user_headers(sqlite_session, mine.id, role="Viewer")

    response = test_client.get(
        "/v1/sprints", params={"company_id": mine.id}, headers=headers
    )

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": newer.id,
            "sprint_name": "Hardening",
            "status": "active",
            "goal": None,
            "start_date": "2026-10-15",
            "scope_size": "M",
            "total": 0,
            "done": 0,
            "blocked": 0,
            "rework": 0,
            "second_attempts": {"total": 0, "done": 0, "briefed": 0, "briefed_done": 0},
            "console_advice": {
                "advised": {"total": 0, "done": 0, "rework": 0},
                "unadvised": {"total": 0, "done": 0, "rework": 0},
            },
            "architect_advice": {
                "advised": {"total": 0, "done": 0, "rework": 0},
                "unadvised": {"total": 0, "done": 0, "rework": 0},
            },
        },
        {
            "id": older.id,
            "sprint_name": "Foundation",
            "status": "completed",
            "goal": "Lay the base",
            "start_date": "2026-10-01",
            "scope_size": "S",
            "total": 3,
            "done": 1,
            "blocked": 1,
            "rework": 2,
            "second_attempts": {"total": 0, "done": 0, "briefed": 0, "briefed_done": 0},
            "console_advice": {
                "advised": {"total": 0, "done": 0, "rework": 0},
                "unadvised": {"total": 3, "done": 1, "rework": 2},
            },
            "architect_advice": {
                "advised": {"total": 0, "done": 0, "rework": 0},
                "unadvised": {"total": 3, "done": 1, "rework": 2},
            },
        },
    ]


def test_counts_second_attempts_and_those_briefed_by_the_scrum_master(
    test_client, sqlite_session
):
    company = _company(sqlite_session, "Sprint list second attempts")
    sprint = _sprint(
        sqlite_session,
        company.id,
        "Retry",
        statuses=("done", "blocked", "done", "todo"),
        status="completed",
    )
    items = sqlite_session.exec(
        select(BacklogItem)
        .where(BacklogItem.sprint_id == sprint.id)
        .order_by(BacklogItem.id)
    ).all()
    carried = (
        f'{CARRIED_FROM_PREFIX} task 1 ("Foundation"), which was blocked: no tests'
    )
    briefed = f"{carried}\n{scrum_master.BRIEF_PREFIX}Write the test first."
    # Done with a brief, blocked again with one, done without; the last is new work.
    for item, text in zip(items, (briefed, briefed, carried), strict=False):
        item.comments = [{"author": "System", "text": text}]
        sqlite_session.add(item)
    sqlite_session.commit()

    response = test_client.get("/v1/sprints", params={"company_id": company.id})

    assert response.status_code == 200
    [row] = response.json()
    assert row["total"] == 4
    assert row["second_attempts"] == {
        "total": 3,
        "done": 2,
        "briefed": 2,
        "briefed_done": 1,
    }


def test_counts_tasks_with_and_without_console_advice(test_client, sqlite_session):
    company = _company(sqlite_session, "Sprint list console advice")
    sprint = _sprint(
        sqlite_session,
        company.id,
        "Advised",
        statuses=("done", "blocked", "done"),
        status="completed",
    )
    items = sqlite_session.exec(
        select(BacklogItem)
        .where(BacklogItem.sprint_id == sprint.id)
        .order_by(BacklogItem.id)
    ).all()
    # The note the worker writes after asking the assistants, as it writes it.
    advice = console_assistants.usage_comment(
        [{"label": "Claude CLI", "purpose": "review", "excerpt": "Add a test."}]
    )
    rework = {"author": "QA", "text": "NEEDS WORK: cover the empty case"}
    items[0].comments = [{"author": "System", "text": advice}, rework]
    items[1].comments = [{"author": "System", "text": advice}]
    items[2].comments = [rework]
    sqlite_session.add_all(items)
    sqlite_session.commit()

    response = test_client.get("/v1/sprints", params={"company_id": company.id})

    assert response.status_code == 200
    [row] = response.json()
    assert row["console_advice"] == {
        "advised": {"total": 2, "done": 1, "rework": 1},
        "unadvised": {"total": 1, "done": 1, "rework": 1},
    }


def test_counts_tasks_with_and_without_the_architects_brief(
    test_client, sqlite_session
):
    company = _company(sqlite_session, "Sprint list architect briefs")
    sprint = _sprint(
        sqlite_session,
        company.id,
        "Briefed",
        statuses=("done", "blocked", "done"),
        status="completed",
    )
    items = sqlite_session.exec(
        select(BacklogItem)
        .where(BacklogItem.sprint_id == sprint.id)
        .order_by(BacklogItem.id)
    ).all()
    brief = {
        "author": ARCHITECT_COMMENT_AUTHOR,
        "text": format_architect_consult_comment("Reuse the parser; test empty input."),
    }
    rework = {"author": "QA", "text": "NEEDS WORK: cover the empty case"}
    # Briefed after its first rework: only the request after the brief counts.
    items[0].comments = [rework, brief, rework]
    items[1].comments = [brief]
    items[2].comments = [rework]
    sqlite_session.add_all(items)
    sqlite_session.commit()

    response = test_client.get("/v1/sprints", params={"company_id": company.id})

    assert response.status_code == 200
    [row] = response.json()
    assert row["architect_advice"] == {
        "advised": {"total": 2, "done": 1, "rework": 1},
        "unadvised": {"total": 1, "done": 1, "rework": 1},
    }


def test_nonmember_gets_403_when_auth_required(
    test_client, sqlite_session, signing_key, monkeypatch
):
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    target = _company(sqlite_session, "Sprint list private tenant")
    _sprint(sqlite_session, target.id, "Private")
    member_elsewhere = _company(sqlite_session, "Sprint list elsewhere")
    headers = _user_headers(sqlite_session, member_elsewhere.id, role="Owner")

    response = test_client.get(
        "/v1/sprints", params={"company_id": target.id}, headers=headers
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Not a member of this company"}


def test_requires_token_when_auth_required(test_client, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    response = test_client.get("/v1/sprints", params={"company_id": 1})
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_company_id_is_required(test_client):
    response = test_client.get("/v1/sprints")
    assert response.status_code == 422
