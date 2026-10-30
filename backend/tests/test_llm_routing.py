"""
How the task worker picks a model and reports LLM failures (#102).

An agent with no model uses its role's default from ``llm.model_factory``
(the same map the LangGraph producer uses) at every call site; a failed or
empty LLM call reaches the board as ``LLM call failed: <provider> <status>
<message>``; and the model the proxy says answered is what the AgentRun
records.  The proxy client is replaced by an in-process fake.
"""

import asyncio
import json
from uuid import uuid4

import pytest
from models.agent_message import AgentMessage
from models.agent_run import AgentRun
from models.company import Agent, Company
from models.sprint import BacklogItem, Sprint
from services import console_assistants, task_worker
from sqlmodel import Session, select

from llm.model_factory import AgentRole, ModelFactory


def _role_default(role: AgentRole) -> str:
    return ModelFactory.ROLE_MODEL_MAP[role].model_name


class _FakeLLM:
    """What the fake proxy answers, and the model of every call it received."""

    def __init__(self):
        self.calls: list[dict] = []
        self.response: dict = {
            "choices": [{"message": {"content": "A thorough answer."}}],
            "served_model": None,
        }


@pytest.fixture()
def llm(monkeypatch):
    state = _FakeLLM()

    class _Client:
        def __init__(self, base_url=None):
            self.timeout = None

        def chat(self, messages, model, role, bu_id=None):
            state.calls.append({"model": model, "role": role})
            return state.response

    monkeypatch.setattr(task_worker, "LLMProxyClient", _Client)
    return state


@pytest.fixture()
def db(monkeypatch, sqlite_session):
    monkeypatch.setattr(task_worker, "engine", sqlite_session.get_bind())
    return sqlite_session


def _board(db: Session, role: str = "Developer", agent_model: str | None = None):
    company = Company(company_name=f"Routing {uuid4().hex[:8]}", autonomy_level=2)
    db.add(company)
    db.commit()
    db.refresh(company)
    if agent_model is not None:
        db.add(
            Agent(company_id=company.id, name=f"{role} A", role=role, model=agent_model)
        )
    sprint = Sprint(
        company_id=company.id, sprint_name="Routing", scope_size="M", status="active"
    )
    db.add(sprint)
    db.commit()
    db.refresh(sprint)
    item = BacklogItem(
        sprint_id=sprint.id,
        title="Implement login",
        description="Login handler",
        status="todo",
        priority="low",
        assignee=role,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return company, sprint, item


# ---------------------------------------------------------------------------
# Role defaults come from model_factory
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("role", list(AgentRole), ids=lambda r: r.value)
@pytest.mark.parametrize("configured", ["", None], ids=["empty", "missing"])
def test_task_with_no_agent_model_uses_the_role_default(llm, role, configured):
    agent = {"role": role.value}
    if configured is not None:
        agent["model"] = configured

    task_worker._execute_task({"id": 1, "title": "Do it"}, agent, "Sprint 1")

    assert llm.calls[0]["model"] == _role_default(role)


def test_stored_role_names_map_to_their_agent_role(llm):
    task_worker._execute_task(
        {"id": 1, "title": "Do it"}, {"role": "BackendDev", "model": ""}, "Sprint 1"
    )

    assert llm.calls[0]["model"] == _role_default(AgentRole.DEVELOPER)


def test_configured_model_is_kept(llm):
    task_worker._execute_task(
        {"id": 1, "title": "Do it"}, {"role": "QA", "model": "qwen3.6-flash"}, "S"
    )

    assert llm.calls[0]["model"] == "qwen3.6-flash"


def test_qa_review_with_no_model_uses_the_qa_default(llm):
    task_worker._call_llm_for_review({"role": "QA", "model": ""}, "Review this")

    assert llm.calls[0]["model"] == _role_default(AgentRole.QA)


def test_architect_consult_with_no_model_uses_the_architect_default(
    llm, db, monkeypatch
):
    recorded = []
    monkeypatch.setattr(
        task_worker, "record_agent_turn", lambda **kw: recorded.append(kw)
    )
    llm.response = {
        "choices": [{"message": {"content": "Use a service layer."}}],
        "served_model": "qwen3.6-flash",
    }
    company, sprint, item = _board(db, role="Architect", agent_model="")

    advice = task_worker._consult_architect(
        {"id": item.id, "title": item.title},
        {"role": "Developer"},
        {"id": sprint.id, "company_id": company.id, "name": "Routing"},
    )

    assert advice == "Use a service layer."
    assert llm.calls[0]["model"] == _role_default(AgentRole.ARCHITECT)
    assert recorded[0]["agent"]["model"] == "qwen3.6-flash"


@pytest.mark.parametrize("agent_model", ["", None], ids=["empty-row", "no-row"])
def test_task_context_resolves_an_empty_model(db, agent_model):
    _company, _sprint, item = _board(db, role="QA", agent_model=agent_model)

    ctx = task_worker._load_task_context(item.id)

    assert ctx["agent"]["model"] == _role_default(AgentRole.QA)


# ---------------------------------------------------------------------------
# LLM failures are errors, with provider, status and message
# ---------------------------------------------------------------------------

_UPSTREAM_500 = {
    "error": "HTTP 502: {...}",
    "ok": False,
    "status_code": 502,
    "detail": {
        "error": "upstream_error",
        "provider": "deepseek",
        "model": "deepseek-v4-pro",
        "status": 500,
        "message": "internal failure",
    },
}


def test_upstream_error_names_provider_status_and_message(llm):
    llm.response = _UPSTREAM_500

    with pytest.raises(
        RuntimeError, match=r"^LLM call failed: deepseek 500 internal failure$"
    ):
        task_worker._execute_task({"id": 1, "title": "x"}, {"role": "Developer"}, "S")


def test_unknown_model_error_says_what_is_available(llm):
    llm.response = {
        "error": "HTTP 400: {...}",
        "ok": False,
        "status_code": 400,
        "detail": {
            "error": "unknown_model",
            "model": "kimi-k2.6",
            "message": "unknown model 'kimi-k2.6'; available: deepseek-v4-pro",
            "available": ["deepseek-v4-pro"],
        },
    }

    with pytest.raises(
        RuntimeError,
        match=r"^LLM call failed: llm-proxy 400 unknown model 'kimi-k2.6'; available: deepseek-v4-pro$",
    ):
        task_worker._execute_task(
            {"id": 1, "title": "x"}, {"role": "Developer", "model": "kimi-k2.6"}, "S"
        )


def test_empty_content_without_error_is_a_failure(llm):
    llm.response = {
        "choices": [{"message": {"content": "  "}}],
        "served_model": "qwen3.7-plus",
        "provider": "qwen",
    }

    with pytest.raises(
        RuntimeError,
        match=r"^LLM call failed: qwen 200 empty response from qwen3.7-plus$",
    ):
        task_worker._execute_task({"id": 1, "title": "x"}, {"role": "PO"}, "S")


class _StopAfterSubscribe(Exception):
    pass


class _Nats:
    jetstream_enabled = False

    def __init__(self):
        self.handler = None
        self.published = []

    async def consume(self, subject, durable, callback, **kwargs):
        self.handler = callback
        raise _StopAfterSubscribe

    async def publish(self, subject, payload, msg_id=None):
        self.published.append((subject, payload))

    async def request(self, subject, payload, timeout=5.0):
        raise TimeoutError("no daemon in this test")


def _task_assign_handler(monkeypatch):
    monkeypatch.setattr(task_worker, "ARCHITECT_CONSULT_ENABLED", False)
    monkeypatch.setattr(task_worker, "_fetch_memory_context", lambda *args: "")
    monkeypatch.setattr(task_worker, "_load_recent_lessons", lambda *args: "")
    monkeypatch.setattr(
        task_worker, "_load_sprint_completed_tasks", lambda sprint_id, item_id: ""
    )

    async def _no_assistants(nats, item, agent, sprint, resolve_workspace_root):
        return {"combined": "", "sources": []}

    monkeypatch.setattr(console_assistants, "collect_advice", _no_assistants)
    nats = _Nats()
    with pytest.raises(_StopAfterSubscribe):
        asyncio.run(task_worker.process_backlog_tasks(nats))
    return nats


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (_UPSTREAM_500, "LLM call failed: deepseek 500 internal failure"),
        (
            {
                "choices": [{"message": {"content": ""}}],
                "served_model": "deepseek-v4-pro",
                "provider": "deepseek",
            },
            "LLM call failed: deepseek 200 empty response from deepseek-v4-pro",
        ),
    ],
    ids=["upstream-500", "empty-content"],
)
def test_llm_failure_is_recorded_on_the_board(llm, db, monkeypatch, response, expected):
    llm.response = response
    _company, sprint, item = _board(db, role="Developer", agent_model="")
    nats = _task_assign_handler(monkeypatch)

    asyncio.run(
        nats.handler(None, {"backlog_item_id": item.id, "sprint_id": sprint.id})
    )

    db.expire_all()
    stored = db.get(BacklogItem, item.id)
    comments = stored.comments
    if isinstance(comments, str):
        comments = json.loads(comments)
    assert comments[-1]["text"] == expected
    assert stored.status == "blocked"


# ---------------------------------------------------------------------------
# AgentRun.model is the model that answered
# ---------------------------------------------------------------------------


def test_served_model_is_recorded_on_the_agent_run(llm, db, tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path / "audit"))
    monkeypatch.setattr(task_worker, "_resolve_workspace_root", lambda cid: None)
    llm.response = {
        "choices": [{"message": {"content": "A written analysis with no files."}}],
        "served_model": "qwen3.6-flash",
        "provider": "qwen",
    }
    company, sprint, item = _board(db, role="Developer", agent_model="deepseek-v4-pro")
    ctx_agent = {"role": "Developer", "name": "Dev", "model": "deepseek-v4-pro"}
    item_dict = {"id": item.id, "title": item.title, "description": item.description}
    sprint_dict = {"id": sprint.id, "company_id": company.id, "name": "Routing"}

    deliverable = task_worker._execute_task(item_dict, ctx_agent, "Routing")
    asyncio.run(
        task_worker._deliver_artifacts(
            _Nats(), item_dict, ctx_agent, sprint_dict, deliverable
        )
    )

    db.expire_all()
    run = db.exec(
        select(AgentRun).where(AgentRun.external_ref == f"task-{item.id}")
    ).first()
    assert run.model == "qwen3.6-flash"


# ---------------------------------------------------------------------------
# The conversation: the developer asks the Architect, then hands over to QA
# ---------------------------------------------------------------------------


def test_task_execution_records_the_conversation(llm, db, monkeypatch):
    llm.response = {
        "choices": [{"message": {"content": "A thorough written analysis. " * 40}}],
    }
    company, sprint, item = _board(db, role="Developer", agent_model="")
    db.add(Agent(company_id=company.id, name="Ada", role="Architect", model=""))
    db.commit()
    nats = _task_assign_handler(monkeypatch)
    monkeypatch.setattr(task_worker, "ARCHITECT_CONSULT_ENABLED", True)
    monkeypatch.setattr(task_worker, "should_consult_architect", lambda *a, **k: True)

    asyncio.run(
        nats.handler(None, {"backlog_item_id": item.id, "sprint_id": sprint.id})
    )

    db.expire_all()
    messages = db.exec(
        select(AgentMessage)
        .where(AgentMessage.backlog_item_id == item.id)
        .order_by(AgentMessage.id)
    ).all()
    assert [(m.from_role, m.to_role, m.kind) for m in messages] == [
        ("Developer", "Architect", "question"),
        ("Architect", "Developer", "answer"),
        ("Developer", "QA", "handoff"),
    ]
    assert 'Before I implement "Implement login"' in messages[0].body
    assert (
        messages[2].body
        == 'Delivered "Implement login" for review (no files declared).'
    )
    assert {m.sprint_id for m in messages} == {sprint.id}
