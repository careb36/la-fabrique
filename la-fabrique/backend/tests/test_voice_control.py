"""
Tests for the voice façade (``/v1/voice/*``) the desktop assistant speaks to.

Everything runs against the in-memory SQLite session from ``conftest.py``: no
Postgres, NATS or LLM proxy. The planner falls back to its deterministic list
because the default team carries no model, so these are stable assertions about
the spoken contract rather than about a model's wording.
"""

import pytest
from config import settings
from models.agent_run import AgentRunApproval
from models.company import Company
from models.sprint import BacklogItem, OutboxEvent, Sprint
from sqlalchemy import inspect
from sqlmodel import SQLModel, delete, select


@pytest.fixture(autouse=True)
def _clean_database(sqlite_session):
    """The in-memory engine is shared by the module: start and end each test empty."""
    _wipe(sqlite_session)
    yield
    _wipe(sqlite_session)


def _wipe(session):
    session.rollback()
    existing = set(inspect(session.get_bind()).get_table_names())
    for table in reversed(SQLModel.metadata.sorted_tables):
        if table.name in existing:
            session.exec(delete(table))
    session.commit()


def _company(session, name="Acme Factory"):
    company = Company(company_name=name)
    session.add(company)
    session.commit()
    session.refresh(company)
    return company


def _sprint(session, test_client, company_id, items=2):
    response = test_client.post(
        "/v1/start_sprint",
        json={
            "company_id": company_id,
            "sprint_name": "Sprint Voz",
            "start_date": "2026-01-01",
            "scope_size": "S",
            "goal": "Ship the voice door",
            "backlog_items": [
                {"title": f"Task {i}", "description": "Do it", "priority": "high"}
                for i in range(items)
            ],
        },
    )
    assert response.status_code == 200, response.text
    sprint = session.get(Sprint, response.json()["sprint_id"])
    return sprint


def _command(client, **payload):
    response = client.post("/v1/voice/command", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


def test_status_without_company_is_spoken_not_a_404(test_client):
    body = _command(test_client, action="estado")

    assert body["ok"] is False
    assert "empresa" in body["speech"].lower()


def test_status_counts_the_board_and_names_the_blocked_task(
    sqlite_session, test_client
):
    company = _company(sqlite_session)
    sprint = _sprint(sqlite_session, test_client, company.id)

    item = sqlite_session.exec(
        select(BacklogItem).where(BacklogItem.sprint_id == sprint.id)
    ).first()
    item.status = "blocked"
    sqlite_session.add(item)
    sqlite_session.commit()

    body = _command(test_client, action="estado")

    assert body["ok"] is True
    assert body["data"]["counts"]["blocked"] == 1
    assert body["data"]["counts"]["todo"] == 1
    assert body["data"]["blocked"] == ["Task 0"]
    assert "bloqueadas" in body["speech"]
    assert "Task 0" in body["speech"]


def test_status_speaks_english_when_asked(sqlite_session, test_client):
    _company(sqlite_session)

    body = _command(test_client, action="estado", language="en")

    assert body["ok"] is True
    assert "no sprint yet" in body["speech"].lower()


# ---------------------------------------------------------------------------
# Sprint list
# ---------------------------------------------------------------------------


def test_sprints_without_company_says_so(test_client):
    body = _command(test_client, action="sprints")

    assert body["ok"] is False
    assert "empresa" in body["speech"].lower()


def test_sprints_lists_the_newest_first(sqlite_session, test_client):
    company = _company(sqlite_session)
    first = _sprint(sqlite_session, test_client, company.id)
    second = _sprint(sqlite_session, test_client, company.id)

    body = _command(test_client, action="listar_sprints")

    assert body["ok"] is True
    assert [s["id"] for s in body["data"]["sprints"]] == [second.id, first.id]
    assert body["speech"].index(f"{second.id} «") < body["speech"].index(
        f"{first.id} «"
    )


def test_sprints_speaks_english_when_asked(sqlite_session, test_client):
    company = _company(sqlite_session)
    _sprint(sqlite_session, test_client, company.id)

    body = _command(test_client, action="sprints", language="en")

    assert body["ok"] is True
    assert "you have 1 sprint," in body["speech"].lower()
    assert "en marcha" not in body["speech"]


# ---------------------------------------------------------------------------
# Planning and creation
# ---------------------------------------------------------------------------


def test_plan_previews_without_writing(sqlite_session, test_client):
    company = _company(sqlite_session)

    body = _command(test_client, action="planear", text="Add Google login")

    assert body["ok"] is True
    assert body["data"]["plan"]["tasks"]
    assert "¿Lo creo?" in body["speech"]
    assert sqlite_session.exec(select(Sprint)).all() == []


def test_plan_without_objective_asks_for_one(test_client):
    body = _command(test_client, action="planear", text="   ")

    assert body["ok"] is False
    assert "objetivo" in body["speech"].lower()


def test_create_sprint_leaves_it_paused(sqlite_session, test_client):
    company = _company(sqlite_session)

    body = _command(test_client, action="crear_sprint", text="Add Google login")

    assert body["ok"] is True
    assert body["data"]["paused"] is True
    sprint = sqlite_session.get(Sprint, body["data"]["sprint_id"])
    assert sprint.status == "paused"
    assert sprint.company_id == company.id
    items = sqlite_session.exec(
        select(BacklogItem).where(BacklogItem.sprint_id == sprint.id)
    ).all()
    assert len(items) == body["data"]["tasks"]
    # The transactional outbox was written, as on the web path.
    assert sqlite_session.exec(select(OutboxEvent)).all()
    assert "PAUSA" in body["speech"]


def test_sprint_name_is_not_read_twice(sqlite_session, test_client):
    """The sentence says the id, so the planner's ``Sprint - `` prefix is noise."""
    _company(sqlite_session)

    body = _command(test_client, action="crear_sprint", text="Add Google login")

    sprint = sqlite_session.get(Sprint, body["data"]["sprint_id"])
    assert sprint.sprint_name == "Add Google login"
    assert "Sprint -" not in body["speech"]


def test_resume_then_pause_round_trip(sqlite_session, test_client):
    _company(sqlite_session)
    created = _command(test_client, action="crear_sprint", text="Voice flow")
    sprint_id = created["data"]["sprint_id"]

    resumed = _command(test_client, action="reanudar")
    assert resumed["ok"] is True
    assert sqlite_session.get(Sprint, sprint_id).status == "active"

    paused = _command(test_client, action="pausar")
    assert paused["ok"] is True
    assert sqlite_session.get(Sprint, sprint_id).status == "paused"


def test_dispatch_sends_the_todo_tasks(sqlite_session, test_client):
    company = _company(sqlite_session)
    _sprint(sqlite_session, test_client, company.id, items=3)

    body = _command(test_client, action="despachar")

    assert body["ok"] is True
    assert body["data"]["dispatched"] == 3
    assert "3" in body["speech"]


def test_dispatch_refuses_a_paused_sprint(sqlite_session, test_client):
    _company(sqlite_session)
    _command(test_client, action="crear_sprint", text="Paused flow")

    body = _command(test_client, action="despachar")

    assert body["ok"] is False
    assert "pausa" in body["speech"].lower()


# ---------------------------------------------------------------------------
# Talking to one agent
# ---------------------------------------------------------------------------


def _agent(session, company_id, name="R2", role="Dev", model="nvidia/llama-3.3-nemotron-super-49b-v1"):
    from models.company import Agent

    agent = Agent(company_id=company_id, name=name, role=role, model=model)
    session.add(agent)
    session.commit()
    session.refresh(agent)
    return agent


def test_assign_records_the_task_for_the_named_agent(sqlite_session, test_client):
    company = _company(sqlite_session)
    _agent(sqlite_session, company.id)
    sprint = _sprint(sqlite_session, test_client, company.id, items=1)

    body = _command(
        test_client, action="asignar", agent="R2",
        text="Arreglá el login que falla en Safari",
    )

    assert body["ok"] is True
    assert body["data"]["task"]["assignee"] == "Dev"
    assert body["data"]["dispatched"] is True
    assert "R2" in body["speech"]

    item = sqlite_session.get(BacklogItem, body["data"]["task"]["id"])
    assert item.sprint_id == sprint.id
    assert item.description == "Arreglá el login que falla en Safari"
    assert item.title.startswith("Arreglá el login")

    events = sqlite_session.exec(
        select(OutboxEvent).where(OutboxEvent.aggregate_id == str(item.id))
    ).all()
    assert len(events) == 1
    assert events[0].payload["subject"] == "task.assign"


def test_assign_without_agent_name_asks_which_one(sqlite_session, test_client):
    company = _company(sqlite_session)
    _agent(sqlite_session, company.id, name="R2", role="Dev")
    _agent(sqlite_session, company.id, name="Nova", role="QA")
    _sprint(sqlite_session, test_client, company.id, items=1)

    body = _command(test_client, action="asignar", text="Revisá el sprint")

    assert body["ok"] is False
    assert "R2" in body["speech"] and "Nova" in body["speech"]
    assert len(body["data"]["agents"]) == 2


def test_assign_unknown_agent_lists_the_team(sqlite_session, test_client):
    company = _company(sqlite_session)
    _agent(sqlite_session, company.id, name="R2", role="Dev")
    _sprint(sqlite_session, test_client, company.id, items=1)

    body = _command(test_client, action="asignar", agent="Ultron", text="Hacé algo")

    assert body["ok"] is False
    assert "Ultron" in body["speech"]


def test_assign_to_a_paused_sprint_does_not_dispatch(sqlite_session, test_client):
    company = _company(sqlite_session)
    _agent(sqlite_session, company.id)
    created = _command(test_client, action="crear_sprint", text="Paused flow")
    sprint_id = created["data"]["sprint_id"]

    body = _command(test_client, action="asignar", agent="R2", text="Cuando puedas")

    assert body["ok"] is True
    assert body["data"]["dispatched"] is False
    assert "pausa" in body["speech"].lower()
    assert sqlite_session.exec(
        select(OutboxEvent).where(
            OutboxEvent.aggregate_id == str(body["data"]["task"]["id"])
        )
    ).all() == []
    assert sqlite_session.get(Sprint, sprint_id).status == "paused"


def test_assign_without_a_sprint_asks_for_one(sqlite_session, test_client):
    company = _company(sqlite_session)
    _agent(sqlite_session, company.id)

    body = _command(test_client, action="asignar", agent="R2", text="Hacé algo")

    assert body["ok"] is False
    assert "sprint" in body["speech"].lower()


def test_assign_with_an_empty_team_says_so(sqlite_session, test_client):
    company = _company(sqlite_session)
    _sprint(sqlite_session, test_client, company.id, items=1)

    body = _command(test_client, action="asignar", text="Hacé algo")

    assert body["ok"] is False
    assert "vac" in body["speech"].lower()


# ---------------------------------------------------------------------------
# Governance
# ---------------------------------------------------------------------------


def _outside_run(test_client, company_id, ref="voice-run:1"):
    response = test_client.post(
        "/v1/agent_runs",
        json={
            "company_id": company_id,
            "external_ref": ref,
            "producer": "copilot",
            "artifact": "diff contents",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_approve_records_the_latest_waiting_run(
    sqlite_session, test_client, monkeypatch, tmp_path
):
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path))
    company = _company(sqlite_session)
    run = _outside_run(test_client, company.id)

    body = _command(test_client, action="aprobar", run_id=run["id"])

    assert body["ok"] is True
    approvals = sqlite_session.exec(
        select(AgentRunApproval).where(AgentRunApproval.agent_run_id == run["id"])
    ).all()
    assert len(approvals) == 1
    assert approvals[0].decision == "approved"
    assert "aprobado" in body["speech"]

    again = _command(test_client, action="aprobar")
    assert again["ok"] is False
    assert "entrega" in again["speech"].lower()


def test_reject_requires_nothing_but_records_feedback(
    sqlite_session, test_client, monkeypatch, tmp_path
):
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path))
    company = _company(sqlite_session)
    run = _outside_run(test_client, company.id)

    body = _command(test_client, action="rechazar", feedback="No cumple criterios")

    assert body["ok"] is True
    approval = sqlite_session.exec(
        select(AgentRunApproval).where(AgentRunApproval.agent_run_id == run["id"])
    ).first()
    assert approval.decision == "rejected"
    assert approval.feedback == "No cumple criterios"


# ---------------------------------------------------------------------------
# Vocabulary and access
# ---------------------------------------------------------------------------


def test_unknown_action_explains_the_vocabulary(test_client):
    body = _command(test_client, action="hacer_cafe")

    assert body["ok"] is False
    assert "no lo sé hacer" in body["speech"].lower()


def test_help_lists_the_actions(test_client):
    body = _command(test_client, action="ayuda")

    assert body["ok"] is True
    assert "crea un sprint" in body["speech"]


def test_voice_key_is_required_when_configured(test_client, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    monkeypatch.setattr(settings, "VOICE_API_KEY", "s3cret")

    assert test_client.get("/v1/voice/status").status_code == 401

    response = test_client.get(
        "/v1/voice/status", headers={"X-Voice-Key": "s3cret"}
    )
    assert response.status_code == 200
    assert response.json()["action"] == "estado"


def test_voice_routes_refuse_to_open_anonymously(test_client, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    monkeypatch.setattr(settings, "VOICE_API_KEY", None)

    response = test_client.get("/v1/voice/status")

    assert response.status_code == 503
    assert "VOICE_API_KEY" in response.json()["detail"]


def test_ping_confirms_the_key(test_client, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    monkeypatch.setattr(settings, "VOICE_API_KEY", "s3cret")

    response = test_client.get("/v1/voice/ping", headers={"X-Voice-Key": "s3cret"})

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["via_key"] is True
