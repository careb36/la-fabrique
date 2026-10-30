"""
A blocked task gets another attempt in the next sprint.

- ``POST /v1/start_sprint`` with ``carry_over_ids`` clones each task the agents
  gave up on into the new sprint, with what blocked it, queues it for an
  agent and marks the original, which leaves the inbox. Only blocked tasks
  waiting for a person, of this company, not carried before.
- At autonomy level 3 the follow-up sprint carries the closed sprint's
  blocked tasks on its own, once each.
- The agent's prompt for the new task says what blocked the previous one.
"""

import secrets
from unittest.mock import patch

import pytest
from models import AgentMessage, BacklogItem, Company, OutboxEvent, Sprint
from models.agent_run import AgentRun, Verification
from services import carry_over, task_worker
from sqlmodel import select

TRIAGE = "Pre-review quality gate failed after 2 rework(s) — blocked for manual triage: too short"


@pytest.fixture()
def company(sqlite_session, monkeypatch):
    monkeypatch.setattr(task_worker, "engine", sqlite_session.get_bind())
    company = Company(company_name=f"Carry {secrets.token_hex(3)}", autonomy_level=2)
    sqlite_session.add(company)
    sqlite_session.commit()
    sqlite_session.refresh(company)
    return company


def _sprint(session, company_id, name="Sprint 0", status="completed"):
    sprint = Sprint(
        company_id=company_id, sprint_name=name, status=status, scope_size="S"
    )
    session.add(sprint)
    session.commit()
    session.refresh(sprint)
    return sprint


def _blocked(session, sprint, title="Create testing strategy", comments=None):
    item = BacklogItem(
        sprint_id=sprint.id,
        title=title,
        description="Define the testing pyramid.",
        priority="high",
        assignee="QA",
        status="blocked",
        comments=comments or [{"author": "Quality gate", "text": TRIAGE}],
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


def _payload(company_id, **extra):
    return {
        "company_id": company_id,
        "sprint_name": "Sprint 1",
        "start_date": "2026-10-20",
        "scope_size": "S",
        "backlog_items": [{"title": "New work", "description": "Something new."}],
        **extra,
    }


def test_start_sprint_carries_a_blocked_task_with_its_reason(
    test_client, sqlite_session, company
):
    old_sprint = _sprint(sqlite_session, company.id)
    old = _blocked(sqlite_session, old_sprint)

    response = test_client.post(
        "/v1/start_sprint", json=_payload(company.id, carry_over_ids=[old.id, old.id])
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["backlog_item_ids"]) == 2
    sqlite_session.expire_all()
    clone = sqlite_session.get(BacklogItem, body["backlog_item_ids"][1])
    assert (
        clone.sprint_id,
        clone.status,
        clone.title,
        clone.assignee,
        clone.priority,
    ) == (
        body["sprint_id"],
        "todo",
        "Create testing strategy",
        "QA",
        "high",
    )
    assert clone.comments[0]["author"] == "System"
    assert clone.comments[0]["text"].startswith(
        f'Carried over from task {old.id} ("Sprint 0"), which was blocked: {TRIAGE}'
    )
    # The original stays blocked on its board but is marked, so it leaves the inbox.
    original = sqlite_session.get(BacklogItem, old.id)
    assert original.status == "blocked"
    assert original.comments[-1]["text"].startswith(
        f'Carried over to sprint {body["sprint_id"]} ("Sprint 1") as task {clone.id}'
    )
    assert carry_over.carried_over(original)
    # Queued for an agent like any new task, and said to the team.
    # A sprint's event can share the number in the shared test database.
    events = sqlite_session.exec(
        select(OutboxEvent).where(
            OutboxEvent.aggregate_type == "backlog_item",
            OutboxEvent.aggregate_id == str(clone.id),
        )
    ).all()
    assert [e.payload["message"]["backlog_item_id"] for e in events] == [clone.id]
    message = sqlite_session.exec(
        select(AgentMessage).where(AgentMessage.backlog_item_id == clone.id)
    ).one()
    assert (message.kind, message.to_role) == ("decision", "QA")
    assert "gets another attempt" in message.body and TRIAGE in message.body


def test_the_previous_attempt_reaches_the_agents_prompt(
    sqlite_session, company, monkeypatch
):
    old_sprint = _sprint(sqlite_session, company.id)
    old = _blocked(sqlite_session, old_sprint)
    new_sprint = _sprint(sqlite_session, company.id, "Sprint 1", "active")
    (clone,) = carry_over.carry_over(
        sqlite_session, company.id, [old.id], new_sprint, "ana@example.com", "Manager"
    )
    sqlite_session.commit()
    prompts = []

    class _Client:
        def __init__(self, base_url=None):
            self.timeout = None

        def chat(self, messages, model, role, bu_id=None):
            prompts.append(messages[-1]["content"])
            return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(task_worker, "LLMProxyClient", _Client)
    task_worker._execute_task(
        {"id": clone.id, "title": clone.title, "comments": clone.comments},
        {"role": "QA"},
        "Sprint 1",
    )

    assert "## Previous attempt" in prompts[0]
    assert f"Carried over from task {old.id}" in prompts[0]
    assert TRIAGE in prompts[0]
    # It is context, not a rework request: nothing was "sent back" on this task.
    assert "## Review feedback to address" not in prompts[0]


@pytest.mark.parametrize(
    ("make_item", "status", "detail"),
    [
        (lambda s, c: 999_999, 404, "not found"),
        (
            lambda s, c: (
                _blocked(
                    s,
                    _sprint(s, c.id),
                    comments=[{"author": "System", "text": "Agent error: x"}],
                ).id
            ),
            409,
            "not blocked waiting for a person",
        ),
        (
            lambda s, c: (
                _blocked(
                    s,
                    _sprint(s, c.id),
                    comments=[
                        {"author": "Quality gate", "text": TRIAGE},
                        {
                            "author": "System",
                            "text": "Carried over to sprint 3 as task 9 by ana.",
                        },
                    ],
                ).id
            ),
            409,
            "already carried over",
        ),
    ],
    ids=["unknown", "still-retried", "already-carried"],
)
def test_only_tasks_waiting_for_a_person_can_be_carried(
    test_client, sqlite_session, company, make_item, status, detail
):
    item_id = make_item(sqlite_session, company)

    response = test_client.post(
        "/v1/start_sprint", json=_payload(company.id, carry_over_ids=[item_id])
    )

    assert response.status_code == status
    assert detail in response.json()["detail"]
    assert (
        sqlite_session.exec(
            select(Sprint).where(
                Sprint.company_id == company.id, Sprint.sprint_name == "Sprint 1"
            )
        ).first()
        is None
    ), "nothing is written when a carry-over is refused"


def test_another_companys_task_is_not_found(test_client, sqlite_session, company):
    other = Company(company_name=f"Other {secrets.token_hex(3)}")
    sqlite_session.add(other)
    sqlite_session.commit()
    theirs = _blocked(sqlite_session, _sprint(sqlite_session, other.id))

    response = test_client.post(
        "/v1/start_sprint", json=_payload(company.id, carry_over_ids=[theirs.id])
    )

    assert response.status_code == 404


def test_carried_tasks_count_towards_the_scope(test_client, sqlite_session, company):
    old_sprint = _sprint(sqlite_session, company.id)
    ids = [_blocked(sqlite_session, old_sprint, title=f"T{i}").id for i in range(4)]

    response = test_client.post(
        "/v1/start_sprint", json=_payload(company.id, carry_over_ids=ids)
    )

    assert response.status_code == 422
    assert "allows up to 4 items, got 5" in response.json()["detail"]


def test_a_carried_task_leaves_the_inbox(
    test_client, sqlite_session, company, monkeypatch
):
    from config import settings

    monkeypatch.setattr(settings, "AUTH_REQUIRED", False)
    old_sprint = _sprint(sqlite_session, company.id)
    carried = _blocked(sqlite_session, old_sprint, title="Carried")
    waiting = _blocked(sqlite_session, old_sprint, title="Still waiting")
    new_sprint = _sprint(sqlite_session, company.id, "Sprint 1", "active")
    carry_over.carry_over(
        sqlite_session, company.id, [carried.id], new_sprint, "ana", "Manager"
    )
    sqlite_session.commit()

    body = test_client.get("/v1/inbox", params={"company_id": company.id}).json()

    assert [task["id"] for task in body["blocked_tasks"]] == [waiting.id]


def test_the_company_carries_its_blocked_tasks_into_the_follow_up_once(
    sqlite_session, company, monkeypatch
):
    company.autonomy_level = 3
    sqlite_session.add(company)
    closing = _sprint(sqlite_session, company.id, "Sprint 2", "active")
    sqlite_session.add(BacklogItem(sprint_id=closing.id, title="Done", status="done"))
    first_time = _blocked(sqlite_session, closing, title="First time")
    second_time = _blocked(
        sqlite_session,
        closing,
        title="Second time",
        comments=[
            {
                "author": "System",
                "text": 'Carried over from task 1 ("Sprint 1"), which was blocked: x',
            },
            {"author": "Quality gate", "text": TRIAGE},
        ],
    )
    sqlite_session.commit()
    plan = {
        "sprint_name": "Sprint 3",
        "goal": "Improve",
        "tasks": [{"title": "Planned", "description": "d"}],
    }

    with (
        patch("services.task_worker.AUTO_SELF_IMPROVEMENT_ENABLED", True),
        patch("services.task_worker.plan_self_improvement_sprint", return_value=plan),
        patch(
            "services.task_worker.build_self_improvement_objective",
            return_value="Improve",
        ),
    ):
        result = task_worker._complete_sprint_and_plan_follow_up(closing.id)

    assert result["completed"] is True and result["auto_opened"] is True
    assert len(result["carried_over"]) == 1
    sqlite_session.expire_all()
    clone = sqlite_session.get(BacklogItem, result["carried_over"][0])
    assert (clone.title, clone.sprint_id, clone.status) == (
        "First time",
        result["next_sprint_id"],
        "todo",
    )
    assert carry_over.carried_over(sqlite_session.get(BacklogItem, first_time.id))
    assert not carry_over.carried_over(sqlite_session.get(BacklogItem, second_time.id))
    message = sqlite_session.exec(
        select(AgentMessage).where(AgentMessage.backlog_item_id == clone.id)
    ).one()
    assert (message.from_role, message.kind) == ("ScrumMaster", "decision")


def test_qa_reviews_the_second_attempt_with_the_previous_attempts_context(
    sqlite_session, company, monkeypatch
):
    """The reviewer sees what blocked the first attempt and the ScrumMaster's
    brief, the same context the agent had, so it judges the attempt against them."""
    import asyncio

    from test_review_gate import _FakeNATS

    sprint = _sprint(sqlite_session, company.id, "Sprint 1", "active")
    note = (
        f'Carried over from task 7 ("Sprint 0"), which was blocked: {TRIAGE}\n'
        "Brief for the next attempt: Write at least 180 words with one section per test level."
    )
    clone = BacklogItem(
        sprint_id=sprint.id,
        title=f"Create testing strategy {secrets.token_hex(2)}",
        status="in_review",
        assignee="QA",
        comments=[
            {"author": "System", "text": note},
            {"author": "QA Quinn", "text": "# Artifact: STRATEGY.md\n" + "word " * 200},
        ],
    )
    sqlite_session.add(clone)
    sqlite_session.commit()
    sqlite_session.refresh(clone)
    run = AgentRun(
        company_id=company.id,
        external_ref=f"task-{clone.id}",
        producer=task_worker.TASK_WORKER_PRODUCER,
        claims={"files": ["STRATEGY.md"]},
        artifact_digest="d",
        artifact_size=1,
        status="verified",
    )
    sqlite_session.add(run)
    sqlite_session.commit()
    sqlite_session.refresh(run)
    sqlite_session.add(
        Verification(
            company_id=company.id,
            agent_run_id=run.id,
            verdict="verified",
            checks=[
                {"name": "files_written", "outcome": "verified", "observation": ""}
            ],
        )
    )
    sqlite_session.commit()
    prompts = []

    def _review(agent, prompt, **kwargs):
        if clone.title in prompt:
            prompts.append(prompt)
        return "APPROVED: covers every level."

    monkeypatch.setattr(task_worker, "_call_llm_for_review", _review)

    asyncio.run(task_worker._review_cycle(_FakeNATS()))

    assert len(prompts) == 1
    assert "## Previous attempt" in prompts[0]
    assert TRIAGE in prompts[0]
    assert "Brief for the next attempt: Write at least 180 words" in prompts[0]
    sqlite_session.expire_all()
    assert sqlite_session.get(BacklogItem, clone.id).status == "done"
