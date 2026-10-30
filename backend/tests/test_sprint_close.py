"""
A sprint closes when nothing in it can still move on its own, and the text
checks before review ask for rework instead of holding a task for good.

- A task blocked until a person acts is settled: the sprint closes around it,
  the retrospective records it and the procedures' ``blocked_rate`` measures
  it. A task the worker will still retry, re-review or that an operator froze
  keeps the sprint open.
- The pre-review quality gate (length, sections, fences) is a deterministic
  opinion about form: it sends the deliverable back with the reason, up to the
  rework limit, then blocks the task and escalates to the ScrumMaster.
"""

import asyncio
import json
import secrets

import pytest
from models.agent_message import AgentMessage
from models.company import Agent, Company
from models.sprint import BacklogItem, Sprint
from services import board, scrum_master, task_worker
from sqlmodel import select
from test_llm_routing import _task_assign_handler
from test_llm_routing import llm as llm_fixture
from test_review_gate import _FakeNATS

llm = llm_fixture  # the fake proxy client from test_llm_routing, as a fixture here

TRIAGE = (
    "Pre-review quality gate failed after 2 rework(s) — blocked for manual triage: x"
)


@pytest.fixture()
def db(monkeypatch, sqlite_session):
    monkeypatch.setattr(task_worker, "engine", sqlite_session.get_bind())
    monkeypatch.setattr(
        task_worker, "AUTO_SELF_IMPROVEMENT_ENABLED", False, raising=False
    )
    from memory import engram_processor

    def _no_graph():
        raise RuntimeError("no Neo4j in tests")

    monkeypatch.setattr(engram_processor, "get_engram_processor", _no_graph)
    return sqlite_session


def _sprint(db, autonomy_level: int = 2):
    company = Company(
        company_name=f"Close {secrets.token_hex(3)}", autonomy_level=autonomy_level
    )
    db.add(company)
    db.commit()
    sprint = Sprint(company_id=company.id, sprint_name="S", status="active")
    db.add(sprint)
    db.commit()
    db.refresh(sprint)
    return sprint


def _item(db, sprint, status: str, comments: list | None = None, **fields):
    item = BacklogItem(
        sprint_id=sprint.id,
        title=fields.pop("title", f"Task {secrets.token_hex(2)}"),
        status=status,
        assignee="Developer",
        comments=comments or [],
        **fields,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def _comments(db, item_id):
    db.expire_all()
    comments = db.get(BacklogItem, item_id).comments
    if isinstance(comments, str):
        comments = json.loads(comments)
    return [(c["author"], c["text"]) for c in comments]


# ---------------------------------------------------------------------------
# What settles a sprint
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("comments", "settled"),
    [
        ([{"author": "Quality gate", "text": TRIAGE}], True),
        ([{"author": "Verifier", "text": "NEEDS WORK: delivery refuted"}], True),
        ([{"author": "System", "text": "Pre-review quality gate failed: short"}], True),
        # A transient failure is retried once before it settles.
        ([{"author": "System", "text": "Agent error: boom"}], False),
        (
            [
                {"author": "System", "text": "Agent error: boom"},
                {
                    "author": "System",
                    "text": "Automatic retry — re-queuing blocked task.",
                },
            ],
            True,
        ),
        # A deliverable with no reason to stay blocked goes back to review.
        ([{"author": "Dev", "text": "# Artifact: a.py\n" + "word " * 100}], False),
        # An operator's freeze is a person's decision; only a person lifts it.
        ([{"author": "Ana", "text": "freeze after sleep-induced churn"}], False),
    ],
    ids=[
        "gate-triage",
        "verifier-rework-limit",
        "legacy-gate-block",
        "retry-pending",
        "retry-spent",
        "deliverable-to-review",
        "frozen",
    ],
)
def test_a_blocked_task_settles_only_when_a_person_must_act(db, comments, settled):
    sprint = _sprint(db)
    _item(db, sprint, "done")
    _item(db, sprint, "blocked", comments=comments)

    result = task_worker._complete_sprint_and_plan_follow_up(sprint.id)

    db.expire_all()
    assert result["completed"] is settled
    assert db.get(Sprint, sprint.id).status == ("completed" if settled else "active")


def test_a_sprint_with_every_task_blocked_still_closes(db):
    sprint = _sprint(db)
    _item(db, sprint, "blocked", comments=[{"author": "Quality gate", "text": TRIAGE}])

    assert task_worker._complete_sprint_and_plan_follow_up(sprint.id)["completed"]


@pytest.mark.parametrize("status", ["todo", "in_progress", "in_review"])
def test_an_open_task_keeps_the_sprint_active(db, status):
    sprint = _sprint(db)
    _item(db, sprint, "blocked", comments=[{"author": "Quality gate", "text": TRIAGE}])
    _item(db, sprint, status)

    result = task_worker._complete_sprint_and_plan_follow_up(sprint.id)

    assert result == {
        "completed": False,
        "auto_opened": False,
        "reason": "not_all_done",
    }


def test_the_review_cycle_closes_a_sprint_whose_last_task_got_blocked(db, monkeypatch):
    sprint = _sprint(db)
    _item(db, sprint, "done")
    blocked = _item(
        db,
        sprint,
        "blocked",
        title="Write the strategy",
        comments=[{"author": "Quality gate", "text": TRIAGE}],
    )
    monkeypatch.setattr(
        task_worker, "_call_llm_for_review", lambda *a, **k: "APPROVED: n/a"
    )

    asyncio.run(task_worker._review_cycle(_FakeNATS()))

    db.expire_all()
    assert db.get(Sprint, sprint.id).status == "completed"
    assert db.get(BacklogItem, blocked.id).status == "blocked"
    retro = db.exec(
        select(AgentMessage).where(
            AgentMessage.sprint_id == sprint.id, AgentMessage.kind == "retrospective"
        )
    ).one()
    assert "Completed 1/2 tasks" in retro.body
    assert "Blocked: 1 tasks" in retro.body
    assert "Write the strategy" in retro.body


def test_a_retry_in_the_same_cycle_keeps_the_sprint_open(db, monkeypatch):
    sprint = _sprint(db)
    _item(db, sprint, "done")
    failed = _item(
        db,
        sprint,
        "blocked",
        comments=[{"author": "System", "text": "Agent error: boom"}],
    )
    monkeypatch.setattr(
        task_worker, "_call_llm_for_review", lambda *a, **k: "APPROVED: n/a"
    )

    asyncio.run(task_worker._review_cycle(_FakeNATS()))

    db.expire_all()
    assert db.get(BacklogItem, failed.id).status == "todo"
    assert db.get(Sprint, sprint.id).status == "active"


# ---------------------------------------------------------------------------
# The pre-review quality gate asks for rework
# ---------------------------------------------------------------------------


def _short_answer(llm):
    llm.response = {
        "choices": [
            {"message": {"content": "Done.\n\n```md path=STRATEGY.md\nok\n```"}}
        ],
        "served_model": None,
    }


def _doc_task(db, autonomy_level: int = 2):
    sprint = _sprint(db, autonomy_level)
    db.add(
        Agent(company_id=sprint.company_id, name="QA Quinn", role="Developer", model="")
    )
    db.commit()
    item = _item(
        db,
        sprint,
        "todo",
        title="Create testing strategy document",
        description="Define the testing pyramid.",
    )
    return sprint, item


def _assign(nats, sprint, item):
    asyncio.run(
        nats.handler(None, {"backlog_item_id": item.id, "sprint_id": sprint.id})
    )


def test_a_rejected_deliverable_goes_back_with_the_reason(llm, db, monkeypatch):
    _short_answer(llm)
    sprint, item = _doc_task(db)
    nats = _task_assign_handler(monkeypatch)

    _assign(nats, sprint, item)

    db.expire_all()
    assert db.get(BacklogItem, item.id).status == "todo"
    author, text = _comments(db, item.id)[-1]
    assert author == "Quality gate"
    assert text.startswith("NEEDS WORK: Too short (")
    assert "minimum 180" in text
    assert board.pending_rework_feedback(db.get(BacklogItem, item.id).comments) == [
        f"Quality gate: {text}"
    ]
    message = db.exec(
        select(AgentMessage).where(AgentMessage.backlog_item_id == item.id)
    ).one()
    assert (message.from_role, message.to_role, message.kind) == (
        "Quality gate",
        "Developer",
        "request",
    )
    assert any(subject == "task.assign" for subject, _ in nats.published) is False, (
        "the review cycle dispatches it; the gate only changes the board"
    )


def test_the_gate_blocks_after_the_rework_limit_and_the_sprint_closes(
    llm, db, monkeypatch
):
    _short_answer(llm)
    monkeypatch.setattr(task_worker, "AUTOPILOT_MAX_REWORK_CYCLES", 1)
    sprint, item = _doc_task(db)
    nats = _task_assign_handler(monkeypatch)

    _assign(nats, sprint, item)
    db.expire_all()
    assert db.get(BacklogItem, item.id).status == "todo"
    _assign(nats, sprint, item)

    db.expire_all()
    assert db.get(BacklogItem, item.id).status == "blocked"
    author, text = _comments(db, item.id)[-1]
    assert author == "Quality gate"
    assert text.startswith("Pre-review quality gate failed after 1 rework(s)")
    assert "blocked for manual triage" in text
    kinds = db.exec(
        select(AgentMessage.kind, AgentMessage.to_role)
        .where(AgentMessage.backlog_item_id == item.id)
        .order_by(AgentMessage.id)
    ).all()
    assert list(kinds) == [("request", "Developer"), ("escalation", "ScrumMaster")]

    monkeypatch.setattr(
        task_worker, "_call_llm_for_review", lambda *a, **k: "APPROVED: n/a"
    )
    asyncio.run(task_worker._review_cycle(_FakeNATS()))

    db.expire_all()
    assert db.get(Sprint, sprint.id).status == "completed"
    assert db.get(BacklogItem, item.id).status == "blocked"
    retro = db.exec(
        select(AgentMessage).where(
            AgentMessage.sprint_id == sprint.id, AgentMessage.kind == "retrospective"
        )
    ).one()
    assert "Completed 0/1 tasks" in retro.body
    assert "blocked for manual triage" in retro.body


def test_the_scrum_master_answers_the_gates_escalation(llm, db, monkeypatch):
    """Blocked by the gate, the task is escalated and the ScrumMaster's triage is
    recorded with what blocked it; the task stays blocked for a person."""
    _short_answer(llm)
    monkeypatch.setattr(task_worker, "AUTOPILOT_MAX_REWORK_CYCLES", 0)
    asked = []

    def _ask(model, system_prompt, prompt):
        # Asked before the task counts as blocked, so a sprint closing in the
        # meantime already sees the decision.
        statuses.append(
            db.exec(select(BacklogItem.status).where(BacklogItem.id == item.id)).one()
        )
        asked.append(prompt)
        return "DECISION: retry\nBRIEF: Write at least 180 words.\nWHY: cut short.\nEND"

    statuses = []
    monkeypatch.setattr(scrum_master, "ask_triage", _ask)
    sprint, item = _doc_task(db)
    nats = _task_assign_handler(monkeypatch)

    _assign(nats, sprint, item)

    db.expire_all()
    assert db.get(BacklogItem, item.id).status == "blocked"
    assert len(asked) == 1
    assert statuses != ["blocked"]
    assert (
        "## What blocked it\nPre-review quality gate failed after 0 rework(s)"
        in asked[0]
    )
    kinds = db.exec(
        select(AgentMessage.kind, AgentMessage.from_role, AgentMessage.to_role)
        .where(AgentMessage.backlog_item_id == item.id)
        .order_by(AgentMessage.id)
    ).all()
    assert list(kinds) == [
        ("escalation", "Quality gate", "ScrumMaster"),
        ("decision", "ScrumMaster", "Developer"),
    ]
    assert (
        scrum_master.decision_for(db, item.id)["brief"] == "Write at least 180 words."
    )


def test_a_person_can_send_a_gate_blocked_task_back_to_work(db):
    """Moved to todo by a Manager, the task runs again: the gate's verdicts are never
    mistaken for a deliverable to review."""
    sprint = _sprint(db)
    item = _item(
        db,
        sprint,
        "todo",
        comments=[
            {"author": "Quality gate", "text": "NEEDS WORK: Too short (9 words)."},
            {"author": "Quality gate", "text": TRIAGE},
            {"author": "user", "text": "Please try once more."},
        ],
    )
    nats = _FakeNATS()

    asyncio.run(task_worker._dispatch_todo_items(nats))

    db.expire_all()
    assert db.get(BacklogItem, item.id).status == "todo"
    assert [s for s, _ in nats.published if s == "task.assign"] == ["task.assign"]
    assert board.block_reason(db.get(BacklogItem, item.id).comments) == TRIAGE


def test_a_send_back_gives_the_gate_a_fresh_rework_budget(llm, db, monkeypatch):
    """After a person sends a gate-blocked task back, its first short deliverable
    is sent back for rework again, not blocked on the spot."""
    _short_answer(llm)
    monkeypatch.setattr(task_worker, "AUTOPILOT_MAX_REWORK_CYCLES", 1)
    sprint, item = _doc_task(db)
    item.comments = [
        {
            "author": "Quality gate",
            "text": "NEEDS WORK: Too short (9 words, minimum 180).",
        },
        {"author": "Quality gate", "text": TRIAGE},
        {"author": "user", "text": "Sent back to work by a person."},
    ]
    db.add(item)
    db.commit()
    nats = _task_assign_handler(monkeypatch)

    _assign(nats, sprint, item)

    db.expire_all()
    assert db.get(BacklogItem, item.id).status == "todo"
    author, text = _comments(db, item.id)[-1]
    assert author == "Quality gate"
    assert text.startswith("NEEDS WORK: Too short (")
