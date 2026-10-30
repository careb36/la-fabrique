from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest
from audit_signing import verify_audit_row
from config import settings
from models.agent_run import AgentRunApproval
from models.audit import AuditLog
from models.company import Company
from models.sprint import BacklogItem, OutboxEvent, Sprint
from services.company_service import CompanyService
from sqlmodel import SQLModel, select


@pytest.fixture()
def run(sqlite_session, test_client, monkeypatch, tmp_path):
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path))
    company = Company(company_name="Approval Test")
    sqlite_session.add(company)
    sqlite_session.commit()
    sqlite_session.refresh(company)
    response = test_client.post(
        "/v1/agent_runs",
        json={
            "company_id": company.id,
            "external_ref": f"approval-test:{company.id}",
            "producer": "copilot",
            "artifact": "diff contents",
        },
    )
    assert response.status_code == 201
    return response.json()


def _approve(test_client, run, **overrides):
    payload = {
        "company_id": run["company_id"],
        "approver_name": "Ada Reviewer",
        "decision": "approved",
    }
    payload.update(overrides)
    return test_client.post(f"/v1/agent_runs/{run['id']}/approve", json=payload)


def _approvals(session, run):
    return session.exec(
        select(AgentRunApproval).where(AgentRunApproval.agent_run_id == run["id"])
    ).all()


def _audit_rows(session, run):
    return session.exec(
        select(AuditLog).where(
            AuditLog.interaction_id == f"agent-run:{run['external_ref']}"
        )
    ).all()


def test_approve_records_named_human_and_server_timestamp(
    sqlite_session, test_client, run
):
    pending = test_client.get(
        "/v1/agent_runs", params={"company_id": run["company_id"]}
    ).json()["agent_runs"]
    assert pending[0]["latest_approval"] is None
    before = datetime.now(UTC).replace(tzinfo=None)
    response = _approve(test_client, run, approver_name=" Ada Reviewer ")
    after = datetime.now(UTC).replace(tzinfo=None)

    assert response.status_code == 201
    body = response.json()
    assert body["decision"] == "approved"
    assert body["approver_name"] == "Ada Reviewer"
    assert body["agent_run_id"] == run["id"]
    assert body["company_id"] == run["company_id"]
    assert before <= datetime.fromisoformat(body["decided_at"]) <= after
    stored = sqlite_session.get(AgentRunApproval, body["id"])
    assert stored.approver_name == "Ada Reviewer"
    assert stored.decided_at is not None


@pytest.mark.parametrize("category", ["scope", "quality", "security", "other"])
def test_reject_stores_feedback_and_category(
    sqlite_session, test_client, run, category
):
    response = _approve(
        test_client,
        run,
        decision="rejected",
        feedback="Please add isolation tests.",
        rejection_category=category,
    )
    assert response.status_code == 201
    stored = sqlite_session.get(AgentRunApproval, response.json()["id"])
    assert stored.decision == "rejected"
    assert stored.feedback == "Please add isolation tests."
    assert stored.rejection_category == category


@pytest.mark.parametrize("feedback", [None, "", " \t\n"])
def test_reject_requires_nonempty_feedback(sqlite_session, test_client, run, feedback):
    before = len(_audit_rows(sqlite_session, run))
    response = _approve(test_client, run, decision="rejected", feedback=feedback)
    assert response.status_code == 422
    assert _approvals(sqlite_session, run) == []
    assert len(_audit_rows(sqlite_session, run)) == before


def test_invalid_decision_is_rejected(sqlite_session, test_client, run):
    assert _approve(test_client, run, decision="maybe").status_code == 422
    assert _approvals(sqlite_session, run) == []


@pytest.mark.parametrize("name", ["", " \t\n"])
def test_approver_name_must_not_be_empty(sqlite_session, test_client, run, name):
    assert _approve(test_client, run, approver_name=name).status_code == 422
    assert _approvals(sqlite_session, run) == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"rejection_category": "quality"},
        {"decision": "rejected", "feedback": "Rework", "rejection_category": "unknown"},
    ],
)
def test_rejection_category_is_valid_and_only_for_rejection(
    sqlite_session, test_client, run, overrides
):
    assert _approve(test_client, run, **overrides).status_code == 422
    assert _approvals(sqlite_session, run) == []


@pytest.mark.parametrize("first_decision", ["approved", "rejected"])
def test_decisions_are_append_only_and_oldest_first(
    sqlite_session, test_client, run, first_decision
):
    first = _approve(
        test_client,
        run,
        decision=first_decision,
        feedback="Initial review" if first_decision == "rejected" else None,
    ).json()
    second = _approve(
        test_client,
        run,
        decision="rejected" if first_decision == "approved" else "approved",
        feedback="Please rework" if first_decision == "approved" else None,
    ).json()
    response = test_client.get(
        f"/v1/agent_runs/{run['id']}/approvals",
        params={"company_id": run["company_id"]},
    )
    assert response.status_code == 200
    assert response.json()["approvals"] == [first, second]
    assert len(_approvals(sqlite_session, run)) == 2
    sqlite_session.expire_all()
    assert sqlite_session.get(AgentRunApproval, first["id"]).decision == first_decision


def test_list_exposes_latest_feedback_without_artifact(
    sqlite_session, test_client, run
):
    first = _approve(test_client, run).json()
    latest = _approve(
        test_client, run, decision="rejected", feedback="Add missing tests."
    ).json()
    # Exercise the ID tie-breaker when decisions share the same timestamp.
    first_row = sqlite_session.get(AgentRunApproval, first["id"])
    latest_row = sqlite_session.get(AgentRunApproval, latest["id"])
    latest_row.decided_at = first_row.decided_at
    sqlite_session.commit()
    unreviewed = test_client.post(
        "/v1/agent_runs",
        json={
            "company_id": run["company_id"],
            "external_ref": "unreviewed",
            "producer": "external",
            "artifact": "another diff",
        },
    ).json()

    response = test_client.get(
        "/v1/agent_runs", params={"company_id": run["company_id"]}
    )
    items = {item["id"]: item for item in response.json()["agent_runs"]}
    assert items[run["id"]]["latest_approval"] == {
        "decision": "rejected",
        "feedback": "Add missing tests.",
        "approver_name": "Ada Reviewer",
        "decided_at": first["decided_at"],
    }
    assert items[unreviewed["id"]]["latest_approval"] is None
    assert all("artifact_text" not in item for item in items.values())


@pytest.mark.parametrize("decision", ["approved", "rejected"])
def test_each_decision_has_one_linked_signed_audit(
    sqlite_session, test_client, monkeypatch, run, decision
):
    monkeypatch.setattr(settings, "AUDIT_SIGNING_KEY", "approval-test-signing-key")
    before = {row.id for row in _audit_rows(sqlite_session, run)}
    feedback = "Please revise" if decision == "rejected" else None
    category = "quality" if decision == "rejected" else None
    response = _approve(
        test_client,
        run,
        decision=decision,
        feedback=feedback,
        rejection_category=category,
    )
    assert response.status_code == 201
    new_rows = [row for row in _audit_rows(sqlite_session, run) if row.id not in before]
    assert len(new_rows) == 1
    audit = new_rows[0]
    assert response.json()["audit_log_id"] == audit.id
    assert audit.action == f"agent_run_{decision}"
    assert audit.agent_id == "human:Ada Reviewer"
    assert audit.details == {
        "company_id": str(run["company_id"]),
        "agent_run_id": run["id"],
        "version": run["version"],
        "rejection_category": category,
    }
    assert audit.result == {"decision": decision, "feedback": feedback}
    assert audit.cost_tokens == 0
    assert verify_audit_row(audit) == {"status": "valid", "mode": "hmac-sha256"}


def test_rejection_does_not_redispatch(sqlite_session, test_client, run):
    before = list(sqlite_session.exec(select(OutboxEvent.id)).all())
    response = _approve(test_client, run, decision="rejected", feedback="Rework")
    assert response.status_code == 201
    assert list(sqlite_session.exec(select(OutboxEvent.id)).all()) == before


def test_other_tenant_and_missing_run_are_hidden(sqlite_session, test_client, run):
    other = Company(company_name="Other Approval Tenant")
    sqlite_session.add(other)
    sqlite_session.commit()
    before = len(_audit_rows(sqlite_session, run))
    assert _approve(test_client, run, company_id=other.id).status_code == 404
    assert _approvals(sqlite_session, run) == []
    assert len(_audit_rows(sqlite_session, run)) == before
    assert (
        test_client.get(
            f"/v1/agent_runs/{run['id']}/approvals", params={"company_id": other.id}
        ).status_code
        == 404
    )
    missing = {**run, "id": 2147483647}
    assert _approve(test_client, missing).status_code == 404
    assert (
        test_client.get(
            f"/v1/agent_runs/{missing['id']}/approvals",
            params={"company_id": run["company_id"]},
        ).status_code
        == 404
    )


def test_legacy_approval_endpoint_is_gone(test_client):
    for payload in [
        None,
        {"task_id": 1, "approver_name": "Ada", "decision": "approved"},
    ]:
        response = test_client.post("/v1/approve_task", json=payload)
        assert response.status_code == 410
        assert response.json() == {
            "detail": "POST /v1/approve_task was removed; use POST /v1/agent_runs/{id}/approve (issue #42)"
        }


def test_project_health_sums_only_sprints_own_items(sqlite_session):
    company = Company(company_name="Health Test")
    sqlite_session.add(company)
    sqlite_session.flush()
    sprints = [
        Sprint(company_id=company.id, sprint_name=name)
        for name in ["First", "Second", "Empty"]
    ]
    sqlite_session.add_all(sprints)
    sqlite_session.flush()
    items = [
        BacklogItem(sprint_id=sprints[0].id, title="First task"),
        BacklogItem(sprint_id=sprints[0].id, title="Another first task"),
        BacklogItem(sprint_id=sprints[1].id, title="Second task"),
    ]
    sqlite_session.add_all(items)
    sqlite_session.flush()
    for item, tokens in zip(items, [10, 20, 100]):
        sqlite_session.add(
            AuditLog(
                company_id=company.id,
                interaction_id=f"task-{item.id}",
                action="agent_turn",
                cost_tokens=tokens,
            )
        )
    sqlite_session.add(
        AuditLog(
            company_id=company.id,
            interaction_id=f"task-{items[0].id}",
            action="agent_turn",
            cost_tokens=5,
        )
    )
    sqlite_session.commit()

    service = CompanyService(sqlite_session)
    assert service.get_project_health(sprints[0].id)["tokens_consumed"] == 35
    assert service.get_project_health(sprints[1].id)["tokens_consumed"] == 100
    assert service.get_project_health(sprints[2].id)["tokens_consumed"] == 0


def test_task_queue_model_is_removed():
    with pytest.raises(ImportError):
        from models import TaskQueue  # noqa: F401
    assert "task_queue" not in SQLModel.metadata.tables
    init_sql = Path(__file__).resolve().parents[2] / "db" / "init-db" / "init.sql"
    assert "task_queue" not in init_sql.read_text()


def test_janitor_drops_retired_queue_before_cleanup(monkeypatch, sqlite_session):
    from janitor import main as janitor

    connection = MagicMock()
    cursor = connection.cursor.return_value
    monkeypatch.setattr(janitor, "get_db_connection", lambda: connection)
    janitor.run_janitor_tasks()
    janitor.run_janitor_tasks()
    expected = [
        call("DROP TABLE IF EXISTS task_queue"),
        call(
            "DELETE FROM outbox_events WHERE status = 'completed' AND processed_at < NOW() - INTERVAL '7 days'"
        ),
        call("REINDEX INDEX CONCURRENTLY vector_memory_idx"),
    ]
    assert connection.autocommit is True
    assert cursor.execute.call_args_list == expected * 2
    assert cursor.close.call_count == 2
    assert connection.close.call_count == 2
    # The migration also succeeds for an existing table and on subsequent runs.
    from sqlalchemy import text

    sqlite_session.execute(text("CREATE TABLE task_queue (id INTEGER PRIMARY KEY)"))
    sqlite_session.execute(text("DROP TABLE IF EXISTS task_queue"))
    sqlite_session.execute(text("DROP TABLE IF EXISTS task_queue"))
