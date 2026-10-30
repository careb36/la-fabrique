"""
A failed graph kickoff must not block the sprint (issue #103).

The kickoff is only a conversation; backlog tasks run independently in the
task worker.  When an agent node fails, the sprint stays ``active``, a
Glassroom event says the kickoff failed and tasks continue, and the sprint can
still be completed once every task is done.

Run with:
    cd backend && PYTHONPATH=.:app python3 -m pytest tests/test_kickoff_failure.py -q
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import config
import pytest
from models.company import Company
from models.sprint import BacklogItem, Sprint
from services import agent_run_service, agent_worker
from services.task_worker import _complete_sprint_and_plan_follow_up

import agents.graph as graph_module


class _FakeNATSClient:
    def __init__(self):
        self.publish = AsyncMock()
        self.callback = None

    async def subscribe(self, subject, callback):
        self.callback = callback


def _insert_sprint_with_items(session) -> tuple[int, list[int]]:
    company = Company(company_name="Kickoff Failure Corp", autonomy_level=2)
    session.add(company)
    session.commit()
    session.refresh(company)
    sprint = Sprint(
        company_id=company.id,
        sprint_name="Kickoff Sprint",
        scope_size="S",
        status="active",
    )
    session.add(sprint)
    session.commit()
    session.refresh(sprint)
    items = [
        BacklogItem(sprint_id=sprint.id, title=f"Task {n}", status="in_progress")
        for n in range(2)
    ]
    session.add_all(items)
    session.commit()
    return sprint.id, [item.id for item in items]


def _stub_failing_llm(monkeypatch):
    """Every agent turn fails, as when the LLM proxy is down."""
    monkeypatch.setattr(
        graph_module.LLMProxyClient,
        "chat_async",
        AsyncMock(return_value={"error": "LLM proxy unavailable"}),
    )
    monkeypatch.setattr(
        graph_module,
        "create_work_package",
        AsyncMock(return_value={"work_package_id": "wp-1"}),
    )
    monkeypatch.setattr(
        graph_module,
        "get_engram_processor",
        lambda: SimpleNamespace(
            query_relevant_engrams=lambda *args, **kwargs: None,
            burn_engram=lambda **kwargs: {"engram_id": "engram-1"},
        ),
    )
    monkeypatch.setattr(
        agent_run_service,
        "ingest_agent_run",
        MagicMock(return_value=(MagicMock(id=1), True)),
    )


@pytest.mark.asyncio
async def test_kickoff_failure_keeps_sprint_active_and_reports(
    monkeypatch, sqlite_session
):
    monkeypatch.setattr(config.settings, "AGENT_GRAPH_ENABLED", True)
    _stub_failing_llm(monkeypatch)
    sprint_id, item_ids = _insert_sprint_with_items(sqlite_session)
    sqlite_engine = sqlite_session.get_bind()
    nats = _FakeNATSClient()

    with patch("services.agent_worker.engine", sqlite_engine):
        await agent_worker.process_agent_tasks(nats)
        await nats.callback(
            SimpleNamespace(subject="workspace.generate"),
            {
                "story": "Sprint kickoff: Kickoff Sprint\n- Task 0: do it",
                "interaction_id": "kickoff-fail-1",
                "sprint_id": sprint_id,
                "company_id": 1,
            },
        )

    sqlite_session.expire_all()
    assert sqlite_session.get(Sprint, sprint_id).status == "active"

    events = [call.args[1] for call in nats.publish.await_args_list]
    messages = [event.get("message", "") for event in events]
    assert "Kickoff failed: LLM proxy unavailable; tasks continue" in messages
    assert not [event for event in events if event.get("type") == "needs_split"]

    # Tasks finish independently of the kickoff; completion is not blocked.
    for item_id in item_ids:
        item = sqlite_session.get(BacklogItem, item_id)
        item.status = "done"
        sqlite_session.add(item)
    sqlite_session.commit()

    with patch("services.task_worker.engine", sqlite_engine):
        result = _complete_sprint_and_plan_follow_up(sprint_id)

    assert result["completed"] is True
    sqlite_session.expire_all()
    assert sqlite_session.get(Sprint, sprint_id).status == "completed"


@pytest.mark.asyncio
async def test_workflow_error_result_does_not_mark_needs_split(
    monkeypatch, sqlite_session
):
    """A workflow-level error, even one flagged needs_split, is a kickoff failure."""
    monkeypatch.setattr(config.settings, "AGENT_GRAPH_ENABLED", True)
    monkeypatch.setattr(
        agent_worker,
        "run_fabrique_workflow",
        AsyncMock(
            return_value={
                "error": "GraphRecursionError: limit",
                "needs_split": True,
            }
        ),
    )
    sprint_id, _ = _insert_sprint_with_items(sqlite_session)
    nats = _FakeNATSClient()

    with patch("services.agent_worker.engine", sqlite_session.get_bind()):
        await agent_worker.process_agent_tasks(nats)
        await nats.callback(
            SimpleNamespace(subject="workspace.generate"),
            {
                "story": "Kickoff",
                "interaction_id": "kickoff-fail-2",
                "sprint_id": sprint_id,
            },
        )

    sqlite_session.expire_all()
    assert sqlite_session.get(Sprint, sprint_id).status == "active"
    event = nats.publish.await_args.args[1]
    assert event["message"] == (
        "Kickoff failed: GraphRecursionError: limit; tasks continue"
    )


@pytest.mark.asyncio
async def test_explicit_split_decision_still_marks_needs_split(
    monkeypatch, sqlite_session
):
    monkeypatch.setattr(config.settings, "AGENT_GRAPH_ENABLED", True)
    monkeypatch.setattr(
        agent_worker,
        "run_fabrique_workflow",
        AsyncMock(return_value={"needs_split": True, "engram_id": "e-1"}),
    )
    sprint_id, _ = _insert_sprint_with_items(sqlite_session)
    nats = _FakeNATSClient()

    with patch("services.agent_worker.engine", sqlite_session.get_bind()):
        await agent_worker.process_agent_tasks(nats)
        await nats.callback(
            SimpleNamespace(subject="workspace.generate"),
            {"story": "Kickoff", "interaction_id": "split-1", "sprint_id": sprint_id},
        )

    sqlite_session.expire_all()
    assert sqlite_session.get(Sprint, sprint_id).status == "needs_split"
