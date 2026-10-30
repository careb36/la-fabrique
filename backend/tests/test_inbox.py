"""
``GET /v1/inbox``: everything the company needs a person for.

Tasks blocked until someone acts (not the ones the worker still retries or
re-reviews), procedure proposals waiting for a Manager, and runs nobody has
decided on. Viewer-scoped to the company.
"""

import secrets

import auth_tokens
import pytest
from config import settings
from models import (
    AgentRun,
    AgentRunApproval,
    BacklogItem,
    Company,
    CompanyMember,
    Procedure,
    Sprint,
    User,
)

TRIAGE = (
    "Pre-review quality gate failed after 2 rework(s) — blocked for manual triage: x"
)


@pytest.fixture()
def member(sqlite_session, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    key = secrets.token_urlsafe(48)
    monkeypatch.setattr(auth_tokens, "_configured_key", lambda: key)
    user = User(
        email=f"i-{secrets.token_hex(6)}@example.com", full_name="I", password_hash="x"
    )
    company = Company(company_name=f"Inbox {secrets.token_hex(3)}")
    other = Company(company_name=f"Other {secrets.token_hex(3)}")
    sqlite_session.add_all([user, company, other])
    sqlite_session.commit()
    sqlite_session.add(
        CompanyMember(company_id=company.id, user_id=user.id, human_role="Viewer")
    )
    sqlite_session.commit()
    token = auth_tokens.create_access_token(user_id=user.id, email=user.email)
    return {
        "company": company.id,
        "other": other.id,
        "headers": {"Authorization": f"Bearer {token}"},
    }


def _sprint(session, company_id, status="completed"):
    sprint = Sprint(company_id=company_id, sprint_name="Sprint 0", status=status)
    session.add(sprint)
    session.commit()
    session.refresh(sprint)
    return sprint


def _blocked(session, sprint, title, comments):
    item = BacklogItem(
        sprint_id=sprint.id,
        title=title,
        status="blocked",
        assignee="QA",
        comments=comments,
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


def test_lists_the_tasks_only_a_person_can_move(test_client, sqlite_session, member):
    sprint = _sprint(sqlite_session, member["company"])
    triage = _blocked(
        sqlite_session,
        sprint,
        "Create testing strategy",
        [{"author": "Quality gate", "text": TRIAGE}],
    )
    frozen = _blocked(
        sqlite_session,
        sprint,
        "Frozen one",
        [{"author": "Ana", "text": "freeze after sleep-induced churn"}],
    )
    _blocked(  # the worker retries this one on its own
        sqlite_session,
        sprint,
        "Transient",
        [{"author": "System", "text": "Agent error: boom"}],
    )
    elsewhere = _sprint(sqlite_session, member["other"])
    _blocked(
        sqlite_session,
        elsewhere,
        "Not ours",
        [{"author": "Quality gate", "text": TRIAGE}],
    )

    response = test_client.get(
        "/v1/inbox", params={"company_id": member["company"]}, headers=member["headers"]
    )

    assert response.status_code == 200
    body = response.json()
    tasks = {task["title"]: task for task in body["blocked_tasks"]}
    assert set(tasks) == {"Create testing strategy", "Frozen one"}
    assert tasks["Create testing strategy"] == {
        "id": triage.id,
        "title": "Create testing strategy",
        "assignee": "QA",
        "sprint_id": sprint.id,
        "sprint_name": "Sprint 0",
        "sprint_status": "completed",
        "reason": TRIAGE,
        "triage": None,
        "frozen": False,
        "risk_hold": False,
        "updated_at": triage.updated_at.isoformat(),
    }
    assert tasks["Frozen one"]["frozen"] is True
    assert tasks["Frozen one"]["id"] == frozen.id
    assert body["proposals"] == []
    assert body["pending_runs"] == 0
    assert body["total"] == 2


def test_a_blocked_task_carries_the_scrum_masters_triage(
    test_client, sqlite_session, member
):
    from models import AgentMessage

    sprint = _sprint(sqlite_session, member["company"])
    item = _blocked(
        sqlite_session,
        sprint,
        "Needs a budget",
        [{"author": "Quality gate", "text": TRIAGE}],
    )
    sqlite_session.add(
        AgentMessage(
            company_id=member["company"],
            sprint_id=sprint.id,
            backlog_item_id=item.id,
            from_name="ScrumMaster",
            from_role="ScrumMaster",
            to_role=None,
            kind="decision",
            body="Triage decision: leave it for a person.\nWhy: it needs a budget decision.",
        )
    )
    sqlite_session.commit()

    response = test_client.get(
        "/v1/inbox", params={"company_id": member["company"]}, headers=member["headers"]
    )

    assert response.status_code == 200
    (task,) = response.json()["blocked_tasks"]
    assert task["triage"] == {
        "decision": "person",
        "why": "it needs a budget decision.",
        "brief": "",
    }


def test_lists_proposals_and_counts_undecided_runs(test_client, sqlite_session, member):
    company = member["company"]
    sqlite_session.add_all(
        [
            Procedure(
                company_id=company,
                role="Developer",
                title="Cover edge cases",
                body="Add tests.",
                proposed_by="ScrumMaster",
            ),
            Procedure(
                company_id=company,
                role="QA",
                title="Already active",
                body="x",
                proposed_by="ScrumMaster",
                status="active",
            ),
            Procedure(
                company_id=member["other"],
                role="QA",
                title="Theirs",
                body="x",
                proposed_by="ScrumMaster",
            ),
        ]
    )
    undecided = AgentRun(
        company_id=company,
        external_ref="pr-1",
        producer="github",
        artifact_digest="d",
        artifact_size=1,
    )
    decided = AgentRun(
        company_id=company,
        external_ref="pr-2",
        producer="github",
        artifact_digest="d",
        artifact_size=1,
    )
    theirs = AgentRun(
        company_id=member["other"],
        external_ref="pr-3",
        producer="github",
        artifact_digest="d",
        artifact_size=1,
    )
    # The company's own runs: the review loop decided them already.
    own = [
        AgentRun(
            company_id=company,
            external_ref=ref,
            producer=producer,
            artifact_digest="d",
            artifact_size=1,
        )
        for ref, producer in (
            ("task-1", "le-fabrique-task-worker"),
            ("graph:abc", "le-fabrique-graph"),
        )
    ]
    sqlite_session.add_all([undecided, decided, theirs, *own])
    sqlite_session.commit()
    sqlite_session.add(
        AgentRunApproval(
            company_id=company,
            agent_run_id=decided.id,
            approver_name="ana",
            decision="approved",
        )
    )
    sqlite_session.commit()

    body = test_client.get(
        "/v1/inbox", params={"company_id": company}, headers=member["headers"]
    ).json()

    assert [(p["role"], p["title"], p["proposed_by"]) for p in body["proposals"]] == [
        ("Developer", "Cover edge cases", "ScrumMaster")
    ]
    assert body["pending_runs"] == 1
    assert body["total"] == 2


def test_inbox_is_scoped_to_the_members_company(test_client, member):
    assert (
        test_client.get(
            "/v1/inbox",
            params={"company_id": member["other"]},
            headers=member["headers"],
        ).status_code
        == 403
    )
    assert (
        test_client.get(
            "/v1/inbox", params={"company_id": member["company"]}
        ).status_code
        == 401
    )


def test_the_total_counts_every_blocked_task_beyond_the_limit(
    test_client, sqlite_session, member
):
    sprint = _sprint(sqlite_session, member["company"])
    for title in ("One", "Two", "Three"):
        _blocked(
            sqlite_session, sprint, title, [{"author": "Quality gate", "text": TRIAGE}]
        )

    body = test_client.get(
        "/v1/inbox",
        params={"company_id": member["company"], "limit": 2},
        headers=member["headers"],
    ).json()

    assert len(body["blocked_tasks"]) == 2
    assert body["blocked_total"] == 3
    assert body["total"] == 3
