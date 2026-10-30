"""The conversation between roles: recorded at each hand-over, listed per company."""

import asyncio
import secrets

import auth_tokens
import pytest
from config import settings
from models import AgentMessage, BacklogItem, Company, CompanyMember, Sprint, User
from services import task_worker
from sqlmodel import select
from test_review_gate import _FakeNATS, _item_in_review, _run_cycle


@pytest.fixture()
def db(monkeypatch, sqlite_session):
    monkeypatch.setattr(task_worker, "engine", sqlite_session.get_bind())
    return sqlite_session


def _messages(session, item_id):
    session.expire_all()
    return session.exec(
        select(AgentMessage)
        .where(AgentMessage.backlog_item_id == item_id)
        .order_by(AgentMessage.id)
    ).all()


def _summary(messages):
    return [(m.from_role, m.to_role, m.kind) for m in messages]


def test_qa_approval_is_a_decision_to_the_developer(db, monkeypatch):
    item_id = _item_in_review(db, "verified")
    _run_cycle(monkeypatch, "APPROVED: clean and complete", db, item_id)

    messages = _messages(db, item_id)
    assert _summary(messages) == [("QA", "Developer", "decision")]
    assert messages[0].body == "APPROVED: clean and complete"
    sprint = db.get(Sprint, db.get(BacklogItem, item_id).sprint_id)
    assert messages[0].company_id == sprint.company_id
    assert messages[0].sprint_id == sprint.id


def test_qa_rework_is_a_request_and_the_last_one_escalates(db, monkeypatch):
    item_id = _item_in_review(db, "verified")
    _run_cycle(monkeypatch, "NEEDS WORK: validate the email", db, item_id)
    assert _summary(_messages(db, item_id)) == [("QA", "Developer", "request")]

    item = db.get(BacklogItem, item_id)
    item.comments = (
        item.comments
        + [
            {"author": "QA", "text": "NEEDS WORK: earlier", "created_at": ""}
            for _ in range(task_worker.AUTOPILOT_MAX_REWORK_CYCLES)
        ]
        + [{"author": "Dev", "text": "another deliverable " * 30, "created_at": ""}]
    )
    item.status = "in_review"
    db.add(item)
    db.commit()
    _run_cycle(monkeypatch, "NEEDS WORK: still no validation", db, item_id)

    messages = _messages(db, item_id)
    assert _summary(messages)[-2:] == [
        ("QA", "Developer", "request"),
        ("QA", "ScrumMaster", "escalation"),
    ]
    assert "is blocked" in messages[-1].body
    assert "still no validation" in messages[-1].body


def test_the_verifier_requests_rework_from_the_assignee(db, monkeypatch):
    item_id = _item_in_review(db, "refuted")
    _run_cycle(monkeypatch, "APPROVED: never asked", db, item_id)

    messages = _messages(db, item_id)
    assert _summary(messages) == [("Verifier", "Developer", "request")]
    assert messages[0].body.startswith("NEEDS WORK: delivery")


def test_handoff_lists_the_declared_files():
    body = task_worker._handoff_body(
        "Login form",
        "```python path=src/login.py\nx\n```\n```python path=tests/test_login.py\ny\n```",
    )
    assert (
        body
        == 'Delivered "Login form" for review: 2 file(s) declared — src/login.py, tests/test_login.py.'
    )
    assert (
        task_worker._handoff_body("Notes", "just text")
        == 'Delivered "Notes" for review (no files declared).'
    )


def test_a_failed_write_never_stops_the_task(monkeypatch):
    class _Broken:
        def __enter__(self):
            raise RuntimeError("database down")

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(task_worker, "Session", lambda engine: _Broken())
    task_worker._post_message(
        company_id=1,
        sprint_id=None,
        item_id=None,
        from_name="QA",
        from_role="QA",
        to_role=None,
        kind="decision",
        body="x",
    )


# ── GET /v1/messages ─────────────────────────────────────────────────────────


@pytest.fixture()
def member(sqlite_session, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    key = secrets.token_urlsafe(48)
    monkeypatch.setattr(auth_tokens, "_configured_key", lambda: key)
    user = User(
        email=f"m-{secrets.token_hex(6)}@example.com", full_name="M", password_hash="x"
    )
    company = Company(company_name=f"Talk {secrets.token_hex(3)}")
    other = Company(company_name=f"Other {secrets.token_hex(3)}")
    sqlite_session.add_all([user, company, other])
    sqlite_session.commit()
    sqlite_session.add(
        CompanyMember(company_id=company.id, user_id=user.id, human_role="Viewer")
    )
    sprint = Sprint(company_id=company.id, sprint_name="S")
    sqlite_session.add(sprint)
    sqlite_session.commit()
    item = BacklogItem(sprint_id=sprint.id, title="Login form")
    sqlite_session.add(item)
    sqlite_session.commit()
    for message in (
        task_worker._message(
            company.id,
            sprint.id,
            item.id,
            "Dev",
            "Developer",
            "QA",
            "handoff",
            "Delivered",
        ),
        task_worker._message(
            company.id,
            sprint.id,
            item.id,
            "QA",
            "QA",
            "Developer",
            "request",
            "NEEDS WORK: x",
        ),
        task_worker._message(
            company.id,
            sprint.id,
            None,
            "ScrumMaster",
            "ScrumMaster",
            None,
            "retrospective",
            "Sprint done",
        ),
        task_worker._message(
            other.id, None, None, "QA", "QA", None, "decision", "elsewhere"
        ),
    ):
        sqlite_session.add(message)
    sqlite_session.commit()
    headers = {
        "Authorization": "Bearer "
        + auth_tokens.create_access_token(user_id=user.id, email=user.email)
    }
    return {
        "headers": headers,
        "company": company.id,
        "other": other.id,
        "sprint": sprint.id,
        "item": item.id,
    }


def test_lists_the_companys_conversation_oldest_first(test_client, member):
    response = test_client.get(
        "/v1/messages",
        params={"company_id": member["company"]},
        headers=member["headers"],
    )
    assert response.status_code == 200
    messages = response.json()["messages"]
    assert [m["kind"] for m in messages] == ["handoff", "request", "retrospective"]
    assert messages[0]["task_title"] == "Login form"
    assert messages[0]["from_role"] == "Developer" and messages[0]["to_role"] == "QA"
    assert messages[2]["task_title"] is None and messages[2]["to_role"] is None


def test_filters_by_task_and_kind(test_client, member):
    by_task = test_client.get(
        "/v1/messages",
        params={"company_id": member["company"], "backlog_item_id": member["item"]},
        headers=member["headers"],
    ).json()["messages"]
    assert [m["kind"] for m in by_task] == ["handoff", "request"]
    by_kind = test_client.get(
        "/v1/messages",
        params={"company_id": member["company"], "kind": "retrospective"},
        headers=member["headers"],
    ).json()["messages"]
    assert [m["body"] for m in by_kind] == ["Sprint done"]
    limited = test_client.get(
        "/v1/messages",
        params={"company_id": member["company"], "limit": 1},
        headers=member["headers"],
    ).json()["messages"]
    assert [m["kind"] for m in limited] == ["retrospective"]


def test_rejects_unknown_kinds_and_other_companies(test_client, member):
    bad = test_client.get(
        "/v1/messages",
        params={"company_id": member["company"], "kind": "gossip"},
        headers=member["headers"],
    )
    assert bad.status_code == 400
    other = test_client.get(
        "/v1/messages",
        params={"company_id": member["other"]},
        headers=member["headers"],
    )
    assert other.status_code == 403
    assert (
        test_client.get(
            "/v1/messages", params={"company_id": member["company"]}
        ).status_code
        == 401
    )


def test_a_finished_sprint_posts_its_retrospective_to_the_team(db, monkeypatch):
    from memory import engram_processor

    def _no_graph():
        raise RuntimeError("no Neo4j in tests")

    monkeypatch.setattr(engram_processor, "get_engram_processor", _no_graph)
    monkeypatch.setattr(
        task_worker, "AUTO_SELF_IMPROVEMENT_ENABLED", False, raising=False
    )
    company = Company(company_name=f"Retro {secrets.token_hex(3)}", autonomy_level=2)
    db.add(company)
    db.commit()
    sprint = Sprint(company_id=company.id, sprint_name="S", status="active")
    db.add(sprint)
    db.commit()
    db.add(BacklogItem(sprint_id=sprint.id, title="Done one", status="done"))
    db.commit()

    asyncio.run(task_worker._finalize_sprint_if_ready(_FakeNATS(), sprint.id))

    db.expire_all()
    messages = db.exec(
        select(AgentMessage).where(AgentMessage.sprint_id == sprint.id)
    ).all()
    assert [(m.from_role, m.to_role, m.kind) for m in messages] == [
        ("ScrumMaster", None, "retrospective")
    ]
    assert f"Sprint {sprint.id} retrospective" in messages[0].body
    assert "Completed 1/1 tasks" in messages[0].body
