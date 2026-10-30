import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import config
import database
import pytest
from models.agent_run import AgentRun
from models.company import Company
from services import agent_run_service, agent_worker
from sqlmodel import Session, select

import agents.graph as graph_module


def test_graph_is_disabled_by_default_and_documented(monkeypatch):
    monkeypatch.delenv("AGENT_GRAPH_ENABLED", raising=False)

    assert config.Settings().AGENT_GRAPH_ENABLED is False
    env_example = Path(__file__).parents[2] / ".env.example"
    assert "AGENT_GRAPH_ENABLED=false" in env_example.read_text()


class _FakeNATSClient:
    def __init__(self):
        self.publish = AsyncMock()
        self.callback = None

    async def subscribe(self, subject, callback):
        self.callback = callback


@pytest.mark.asyncio
async def test_worker_ignores_generate_when_graph_is_disabled(monkeypatch, caplog):
    monkeypatch.setattr(config.settings, "AGENT_GRAPH_ENABLED", False)
    workflow = AsyncMock()
    monkeypatch.setattr(agent_worker, "run_fabrique_workflow", workflow)
    nats = _FakeNATSClient()

    await agent_worker.process_agent_tasks(nats)
    with caplog.at_level(logging.INFO):
        await nats.callback(
            SimpleNamespace(subject="workspace.generate"),
            {
                "story": "Build a feature",
                "interaction_id": "disabled-1",
                "sprint_id": 23,
                "company_id": 4,
            },
        )

    workflow.assert_not_awaited()
    assert "AGENT_GRAPH_ENABLED is false" in caplog.text
    event = nats.publish.await_args.args[1]
    assert event["type"] == "info"


@pytest.mark.asyncio
async def test_worker_runs_graph_when_enabled(monkeypatch):
    monkeypatch.setattr(config.settings, "AGENT_GRAPH_ENABLED", True)
    workflow = AsyncMock(return_value={})
    monkeypatch.setattr(agent_worker, "run_fabrique_workflow", workflow)
    nats = _FakeNATSClient()

    await agent_worker.process_agent_tasks(nats)
    data = {
        "story": "Build a feature",
        "interaction_id": "enabled-1",
        "business_unit_id": 8,
        "sprint_id": 23,
        "company_id": 4,
        "po_feedback": "Revise the design",
    }
    await nats.callback(SimpleNamespace(subject="workspace.generate"), data)

    workflow.assert_awaited_once_with(
        story="Build a feature",
        bu_id=8,
        sprint_id=23,
        company_id=4,
        nats_client=nats,
        interaction_id="enabled-1",
        po_feedback="Revise the design",
    )


def test_generate_rejects_when_graph_is_disabled(monkeypatch, test_client):
    from services.agent_service import AgentService

    monkeypatch.setattr(config.settings, "AGENT_GRAPH_ENABLED", False)
    generate_package = AsyncMock()
    monkeypatch.setattr(AgentService, "generate_package", generate_package)

    response = test_client.post(
        "/v1/generate",
        json={"company_id": 4, "story": "Build a feature"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "AGENT_GRAPH_ENABLED is false; the internal agent graph is disabled. "
        "Ingest externally-produced work via POST /v1/agent_runs."
    )
    generate_package.assert_not_awaited()


def test_generate_keeps_existing_behavior_when_graph_is_enabled(
    monkeypatch, test_client
):
    from services.agent_service import AgentService

    monkeypatch.setattr(config.settings, "AGENT_GRAPH_ENABLED", True)
    generate_package = AsyncMock(return_value="enabled-route-1")
    monkeypatch.setattr(AgentService, "generate_package", generate_package)

    response = test_client.post(
        "/v1/generate",
        json={"company_id": 4, "story": "Build a feature"},
    )

    assert response.status_code == 200
    assert response.json()["interaction_id"] == "enabled-route-1"
    generate_package.assert_awaited_once()


def _stub_graph_dependencies(monkeypatch):
    monkeypatch.setattr(
        graph_module.LLMProxyClient,
        "chat_async",
        AsyncMock(return_value={"choices": [{"message": {"content": "Graph result"}}]}),
    )
    monkeypatch.setattr(
        graph_module,
        "create_work_package",
        AsyncMock(return_value={"work_package_id": "work-package-1"}),
    )
    monkeypatch.setattr(
        graph_module,
        "get_engram_processor",
        lambda: SimpleNamespace(
            query_relevant_engrams=lambda *args, **kwargs: None,
            burn_engram=lambda **kwargs: {"engram_id": "engram-1"},
        ),
    )


@pytest.mark.asyncio
async def test_graph_ingests_successful_output(monkeypatch):
    _stub_graph_dependencies(monkeypatch)
    ingest = MagicMock(return_value=(MagicMock(id=7), True))
    monkeypatch.setattr(agent_run_service, "ingest_agent_run", ingest)
    story = "Build the graph ingestion feature"
    interaction_id = "ingest-graph-1"

    result = await graph_module.run_fabrique_workflow(
        story=story,
        company_id=1,
        interaction_id=interaction_id,
    )

    ingest.assert_called_once()
    payload = ingest.call_args.args[1]
    assert payload.producer == "le-fabrique-graph"
    assert payload.external_ref == f"graph:{interaction_id}"
    assert payload.claims["engram_id"] == result["engram_id"]
    assert payload.artifact
    assert story in payload.artifact


@pytest.mark.asyncio
async def test_graph_ingestion_failure_is_fail_soft(monkeypatch, caplog):
    _stub_graph_dependencies(monkeypatch)
    ingest = MagicMock(side_effect=RuntimeError("db down"))
    monkeypatch.setattr(agent_run_service, "ingest_agent_run", ingest)

    with caplog.at_level(logging.WARNING):
        result = await graph_module.run_fabrique_workflow(
            story="Return the normal graph result",
            company_id=1,
            interaction_id="ingest-failure-1",
        )

    assert result.get("error") is None
    assert "db down" in caplog.text


@pytest.mark.asyncio
async def test_graph_skips_ingestion_without_company_id(monkeypatch, caplog):
    _stub_graph_dependencies(monkeypatch)
    ingest = MagicMock()
    monkeypatch.setattr(agent_run_service, "ingest_agent_run", ingest)

    with caplog.at_level(logging.INFO):
        result = await graph_module.run_fabrique_workflow(
            story="Return without a tenant",
            company_id=None,
            interaction_id="ingest-no-company-1",
        )

    ingest.assert_not_called()
    assert "without company_id" in caplog.text
    assert result.get("error") is None


@pytest.mark.asyncio
async def test_graph_persists_agent_run_with_digest(
    monkeypatch, sqlite_session, tmp_path
):
    _stub_graph_dependencies(monkeypatch)
    company = Company(company_name="Graph ingestion test")
    sqlite_session.add(company)
    sqlite_session.commit()
    monkeypatch.setattr(database, "engine", sqlite_session.get_bind())
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path))
    interaction_id = "ingest-e2e-1"

    await graph_module.run_fabrique_workflow(
        story="Persist this graph output",
        company_id=company.id,
        interaction_id=interaction_id,
    )

    with Session(database.engine) as session:
        run = session.exec(
            select(AgentRun).where(
                AgentRun.company_id == company.id,
                AgentRun.external_ref == f"graph:{interaction_id}",
            )
        ).first()
    assert run is not None
    assert run.producer == "le-fabrique-graph"
    assert run.artifact_digest
