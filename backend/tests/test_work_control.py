"""Who decides when a sprint's agents work: start, pause, stop, no credit, autonomy."""

from __future__ import annotations

import asyncio
import secrets
import sys
from pathlib import Path
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import auth_tokens
from config import settings
from models.company import Company, CompanyMember, User
from models.sprint import BacklogItem, OutboxEvent, Sprint
from services import company_service, sprint_control
from services import task_worker as tw
from services.board import RISK_HOLD_PREFIX, awaits_risk_acceptance
from sqlmodel import Session, select
from test_risk_tier import _approve, _item_in_review


@pytest.fixture()
def db(monkeypatch, sqlite_session):
    monkeypatch.setattr(tw, "engine", sqlite_session.get_bind())
    return sqlite_session


def _sprint(session: Session, status: str = "active", autonomy: int = 2) -> Sprint:
    company = Company(company_name=f"Ctl {uuid4().hex[:6]}", autonomy_level=autonomy)
    session.add(company)
    session.commit()
    sprint = Sprint(
        company_id=company.id, sprint_name="S", scope_size="S", status=status
    )
    session.add(sprint)
    session.commit()
    for title in ("a", "b"):
        session.add(
            BacklogItem(
                sprint_id=sprint.id, title=title, status="todo", assignee="Developer"
            )
        )
    session.commit()
    session.refresh(sprint)
    return sprint


def _events(session: Session, sprint: Sprint) -> list[OutboxEvent]:
    ids = {
        str(i.id)
        for i in session.exec(
            select(BacklogItem).where(BacklogItem.sprint_id == sprint.id)
        )
    }
    return [e for e in session.exec(select(OutboxEvent)) if e.aggregate_id in ids]


# ── Sprint 0 starts only when asked ──────────────────────────────────────────


@pytest.fixture()
def quiet_init(monkeypatch):
    monkeypatch.setattr(
        company_service,
        "plan_foundation_sprint",
        lambda **kw: {"goal": "g", "tasks": [{"title": "t1"}, {"title": "t2"}]},
    )
    monkeypatch.setattr(company_service.CompanyService, "_seed_neo4j", lambda *a: None)


@pytest.mark.parametrize(
    ("start_now", "autonomy", "status", "dispatched"),
    [(True, 2, "active", 2), (False, 2, "planned", 0), (True, 1, "planned", 0)],
)
def test_sprint_0_starts_only_when_asked_and_never_at_the_human_led_level(
    sqlite_session, quiet_init, start_now, autonomy, status, dispatched
):
    result = company_service.CompanyService(sqlite_session).init_company(
        company_name=f"Init {uuid4().hex[:6]}",
        agents=[],
        autonomy_level=autonomy,
        start_now=start_now,
    )
    sprint = sqlite_session.get(Sprint, result["sprint_id"])
    assert (sprint.status, result["sprint_status"]) == (status, status)
    assert len(_events(sqlite_session, sprint)) == dispatched


# ── The routes ───────────────────────────────────────────────────────────────


@pytest.fixture()
def auth_on(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    key = secrets.token_urlsafe(48)
    monkeypatch.setattr(auth_tokens, "_configured_key", lambda: key)


def _member(session: Session, company_id: int | None, role: str) -> dict[str, str]:
    user = User(
        email=f"{role.lower()}-{secrets.token_hex(5)}@example.com",
        full_name=role,
        password_hash="x",
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


def test_a_planned_sprint_starts_once_and_dispatches_its_tasks(
    sqlite_session, test_client, auth_on
):
    sprint = _sprint(sqlite_session, status="planned")
    manager = _member(sqlite_session, sprint.company_id, "Manager")
    viewer = _member(sqlite_session, sprint.company_id, "Viewer")
    assert (
        test_client.post(f"/v1/sprints/{sprint.id}/start", headers=viewer).status_code
        == 403
    )
    assert (
        test_client.post(
            f"/v1/sprints/{sprint.id}/dispatch", headers=manager
        ).status_code
        == 409
    )
    resp = test_client.post(f"/v1/sprints/{sprint.id}/start", headers=manager)
    assert resp.status_code == 200 and resp.json() == {
        "status": "active",
        "dispatched": 2,
    }
    assert len(_events(sqlite_session, sprint)) == 2
    assert (
        test_client.post(f"/v1/sprints/{sprint.id}/start", headers=manager).status_code
        == 409
    )


def test_pause_resume_and_stop(sqlite_session, test_client, auth_on):
    sprint = _sprint(sqlite_session)
    manager = _member(sqlite_session, sprint.company_id, "Manager")
    assert test_client.post(
        f"/v1/sprints/{sprint.id}/pause", headers=manager
    ).json() == {"status": "paused"}
    assert (
        test_client.post(
            f"/v1/sprints/{sprint.id}/dispatch", headers=manager
        ).status_code
        == 409
    )
    resumed = test_client.post(
        f"/v1/sprints/{sprint.id}/resume", headers=manager
    ).json()
    assert resumed == {"status": "active", "dispatched": 2}
    stopped = test_client.post(f"/v1/sprints/{sprint.id}/stop", headers=manager)
    assert stopped.status_code == 200 and stopped.json() == {
        "status": "cancelled",
        "stopped_tasks": 2,
    }
    sqlite_session.expire_all()
    items = sqlite_session.exec(
        select(BacklogItem).where(BacklogItem.sprint_id == sprint.id)
    ).all()
    assert {i.status for i in items} == {"blocked"}
    assert all(i.comments[-1]["text"].startswith("Stopped:") for i in items)
    assert (
        test_client.post(f"/v1/sprints/{sprint.id}/stop", headers=manager).status_code
        == 409
    )
    assert (
        test_client.post(f"/v1/sprints/{sprint.id}/pause", headers=manager).status_code
        == 409
    )
    assert test_client.post(
        f"/v1/sprints/{sprint.id}/resume", headers=manager
    ).json() == {"status": "cancelled"}


def test_autonomy_is_read_by_a_viewer_and_changed_by_a_manager(
    sqlite_session, test_client, auth_on
):
    sprint = _sprint(sqlite_session)
    manager = _member(sqlite_session, sprint.company_id, "Manager")
    viewer = _member(sqlite_session, sprint.company_id, "Viewer")
    outsider = _member(sqlite_session, None, "Owner")
    url = f"/v1/companies/{sprint.company_id}/autonomy"
    assert test_client.get(url, headers=viewer).json()["autonomy_level"] == 2
    assert test_client.get(url, headers=outsider).status_code == 403
    assert (
        test_client.put(url, json={"autonomy_level": 1}, headers=viewer).status_code
        == 403
    )
    assert (
        test_client.put(url, json={"autonomy_level": 4}, headers=manager).status_code
        == 422
    )
    assert (
        test_client.put(url, json={"autonomy_level": 1}, headers=manager).json()[
            "autonomy_level"
        ]
        == 1
    )
    assert test_client.get(url, headers=viewer).json()["autonomy_level"] == 1


# ── The worker ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("status", ["planned", "paused", "cancelled"])
def test_a_halted_sprint_s_task_is_not_loaded_reviewed_or_dispatched(
    db, monkeypatch, status
):
    sprint = _sprint(db, status=status)
    item = db.exec(
        select(BacklogItem).where(BacklogItem.sprint_id == sprint.id)
    ).first()
    assert tw._load_task_context(item.id) is None

    published = []

    class _Nats:
        jetstream_enabled = False

        async def publish(self, subject, payload, msg_id=None):
            if subject == "task.assign":
                published.append(payload.get("backlog_item_id"))

    asyncio.run(tw._dispatch_todo_items(_Nats()))
    # The shared test database holds other sprints' todo items; none of ours.
    ours = {
        i.id
        for i in db.exec(select(BacklogItem).where(BacklogItem.sprint_id == sprint.id))
    }
    assert not ours & set(published)

    item.status = "in_review"
    item.comments = [
        {
            "author": "Dev",
            "text": "# Artifact: a.py\n" + "word " * 120,
            "created_at": "",
        }
    ]
    db.add(item)
    db.commit()
    reviewed = []
    monkeypatch.setattr(
        tw, "_call_llm_for_review", lambda *a, **k: reviewed.append(1) or "APPROVED: ok"
    )
    asyncio.run(tw._review_cycle(_Nats()))
    assert reviewed == []


@pytest.mark.parametrize(
    ("result", "provider"),
    [
        (
            {
                "error": "HTTP 402",
                "detail": {
                    "provider": "deepseek",
                    "status": 402,
                    "message": "Insufficient Balance",
                },
            },
            "deepseek",
        ),
        (
            {
                "error": "HTTP 429",
                "detail": {
                    "provider": "gemini",
                    "status": 429,
                    "message": "You exceeded your current quota",
                },
            },
            "gemini",
        ),
        (
            {
                "error": "HTTP 429",
                "status_code": 429,
                "detail": {"error": "Quota exceeded", "message": "budget"},
            },
            "llm-proxy",
        ),
        (
            {
                "error": "HTTP 429",
                "detail": {
                    "provider": "qwen",
                    "status": 429,
                    "message": "Rate limit, slow down",
                },
            },
            None,
        ),
        (
            {
                "error": "HTTP 502",
                "detail": {
                    "provider": "nebius",
                    "status": 502,
                    "message": "Bad gateway",
                },
            },
            None,
        ),
        ({"choices": [{"message": {"content": "ok"}}]}, None),
    ],
)
def test_a_credit_answer_is_told_from_a_passing_error(result, provider):
    assert sprint_control.credit_failure(result) == provider


def test_no_credit_pauses_the_sprint_and_the_task_waits_as_todo(db):
    sprint = _sprint(db)
    item = db.exec(
        select(BacklogItem).where(BacklogItem.sprint_id == sprint.id)
    ).first()
    item.status = "in_progress"
    db.add(item)
    db.commit()
    sprint_control.pause_task_for_credit(db.get_bind(), item.id, sprint.id, "deepseek")
    db.expire_all()
    sprint = db.get(Sprint, sprint.id)
    item = db.get(BacklogItem, item.id)
    assert sprint.status == "paused" and "No credit at deepseek" in sprint.pause_reason
    assert item.status == "todo" and item.comments[-1]["text"].startswith(
        "Paused: No credit at deepseek"
    )
    # A second task failing the same way leaves the pause and its reason as they are.
    assert sprint_control.pause_for_credit(db, sprint.id, "gemini") is False


def test_the_execute_call_names_the_provider_without_credit(monkeypatch):
    class _Client:
        def __init__(self, base_url=None):
            pass

        def chat(self, messages, model, role, bu_id=None, tools=None):
            return {
                "error": "HTTP 402",
                "detail": {
                    "provider": "deepseek",
                    "status": 402,
                    "message": "Insufficient Balance",
                },
            }

    monkeypatch.setattr(tw, "LLMProxyClient", _Client)
    with pytest.raises(tw.LLMCallError) as raised:
        tw._execute_task(
            {"id": 1, "title": "T"},
            {"role": "Developer", "model": "deepseek-flash"},
            "S",
        )
    assert raised.value.credit_provider == "deepseek"


def test_a_paused_or_planned_sprint_keeps_the_company_from_a_follow_up():
    assert {"planned", "paused", "active"} <= set(sprint_control.OPEN_STATUSES)
    assert "cancelled" not in sprint_control.OPEN_STATUSES


# ── Autonomy level 1 ─────────────────────────────────────────────────────────


def test_at_the_human_led_level_every_approved_task_waits_for_a_person(db, monkeypatch):
    item = _approve(monkeypatch, db, _item_in_review(db, "low", autonomy=1))
    assert item.status == "blocked"
    assert item.comments[-1]["text"].startswith(RISK_HOLD_PREFIX)
    assert sprint_control.HUMAN_LED_REASON in item.comments[-1]["text"]
    assert awaits_risk_acceptance(item.comments)


def test_at_level_2_a_low_risk_approval_is_done(db, monkeypatch):
    item = _approve(monkeypatch, db, _item_in_review(db, "low", autonomy=2))
    assert item.status == "done"
