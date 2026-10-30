import hashlib
import logging

import pytest
from models.agent_run import AgentRun
from models.audit import AuditLog
from models.company import Company
from sqlalchemy.exc import IntegrityError
from sqlmodel import select


def _make_company(session, name="Agent Run Test"):
    company = Company(company_name=name)
    session.add(company)
    session.commit()
    session.refresh(company)
    return company.id


def _payload(company_id, **overrides):
    payload = {
        "company_id": company_id,
        "external_ref": "github:careb36/le-fabrique#35",
        "producer": "copilot",
        "artifact": "diff contents",
        "claims": {"summary": "opened a PR"},
    }
    payload.update(overrides)
    return payload


def _ingest(test_client, monkeypatch, tmp_path, payload):
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path))
    return test_client.post("/v1/agent_runs", json=payload)


def test_new_run_is_ingested_with_server_digest(
    sqlite_session, test_client, monkeypatch, tmp_path
):
    company_id = _make_company(sqlite_session)
    artifact = "diff contents"

    response = _ingest(test_client, monkeypatch, tmp_path, _payload(company_id))

    assert response.status_code == 201
    body = response.json()
    assert body["created"] is True
    assert body["version"] == 1
    assert body["status"] == "ingested"
    assert (
        body["artifact_digest"] == hashlib.sha256(artifact.encode("utf-8")).hexdigest()
    )


def test_identical_reingest_is_noop(sqlite_session, test_client, monkeypatch, tmp_path):
    company_id = _make_company(sqlite_session)
    payload = _payload(company_id)
    first = _ingest(test_client, monkeypatch, tmp_path, payload)
    second = _ingest(test_client, monkeypatch, tmp_path, payload)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["created"] is False
    assert second.json()["id"] == first.json()["id"]
    assert (
        len(
            sqlite_session.exec(
                select(AgentRun).where(
                    AgentRun.company_id == company_id,
                    AgentRun.external_ref == payload["external_ref"],
                )
            ).all()
        )
        == 1
    )


def test_changed_artifact_creates_immutable_new_version(
    sqlite_session, test_client, monkeypatch, tmp_path
):
    company_id = _make_company(sqlite_session)
    first_response = _ingest(test_client, monkeypatch, tmp_path, _payload(company_id))
    first_id = first_response.json()["id"]
    before = sqlite_session.get(AgentRun, first_id)
    original_columns = {
        column.name: getattr(before, column.name)
        for column in AgentRun.__table__.columns
    }

    second_response = _ingest(
        test_client,
        monkeypatch,
        tmp_path,
        _payload(company_id, artifact="changed diff"),
    )

    assert second_response.status_code == 201
    assert second_response.json()["version"] == 2
    after = sqlite_session.get(AgentRun, first_id)
    assert {
        column.name: getattr(after, column.name)
        for column in AgentRun.__table__.columns
    } == original_columns


def test_changed_claims_create_new_version(
    sqlite_session, test_client, monkeypatch, tmp_path
):
    company_id = _make_company(sqlite_session)
    _ingest(test_client, monkeypatch, tmp_path, _payload(company_id))

    response = _ingest(
        test_client,
        monkeypatch,
        tmp_path,
        _payload(company_id, claims={"summary": "opened a different PR"}),
    )

    assert response.status_code == 201
    assert response.json()["version"] == 2


def test_caller_digest_is_ignored_and_logged(
    sqlite_session, test_client, monkeypatch, tmp_path, caplog
):
    company_id = _make_company(sqlite_session)
    caplog.set_level(logging.WARNING)

    response = _ingest(
        test_client,
        monkeypatch,
        tmp_path,
        _payload(company_id, artifact_digest="deadbeef"),
    )

    assert response.status_code == 201
    assert (
        response.json()["artifact_digest"]
        == hashlib.sha256(b"diff contents").hexdigest()
    )
    assert "artifact_digest supplied by caller is ignored" in caplog.text


def test_model_is_nullable_and_preserved_when_known(
    sqlite_session, test_client, monkeypatch, tmp_path
):
    company_id = _make_company(sqlite_session)
    omitted = _ingest(
        test_client,
        monkeypatch,
        tmp_path,
        _payload(company_id, external_ref="github:unknown-model"),
    )
    known = _ingest(
        test_client,
        monkeypatch,
        tmp_path,
        _payload(company_id, external_ref="github:known-model", model="gpt-x"),
    )

    assert omitted.json()["model"] is None
    assert known.json()["model"] == "gpt-x"


def test_nested_claims_round_trip_unchanged(
    sqlite_session, test_client, monkeypatch, tmp_path
):
    company_id = _make_company(sqlite_session)
    claims = {"z": {"emoji": "🧪", "nested": [1, {"é": "雪"}]}, "a": "first"}

    response = _ingest(
        test_client, monkeypatch, tmp_path, _payload(company_id, claims=claims)
    )
    stored = sqlite_session.get(AgentRun, response.json()["id"])

    assert response.status_code == 201
    assert stored.claims == claims
    assert response.json()["claims"] == claims


def test_runs_are_isolated_between_companies(
    sqlite_session, test_client, monkeypatch, tmp_path
):
    company_a = _make_company(sqlite_session, name="Company A")
    company_b = _make_company(sqlite_session, name="Company B")
    external_ref = "github:x/y#1"
    run_a = _ingest(
        test_client,
        monkeypatch,
        tmp_path,
        _payload(company_a, external_ref=external_ref),
    ).json()
    run_b = _ingest(
        test_client,
        monkeypatch,
        tmp_path,
        _payload(company_b, external_ref=external_ref),
    ).json()

    assert run_a["version"] == run_b["version"] == 1
    assert run_a["id"] != run_b["id"]
    listed = test_client.get("/v1/agent_runs", params={"company_id": company_a}).json()
    assert [run["id"] for run in listed["agent_runs"]] == [run_a["id"]]
    hidden = test_client.get(
        f"/v1/agent_runs/{run_b['id']}", params={"company_id": company_a}
    )
    assert hidden.status_code == 404


def test_list_omits_artifact_but_detail_includes_it(
    sqlite_session, test_client, monkeypatch, tmp_path
):
    company_id = _make_company(sqlite_session)
    artifact = "large diff content"
    ingested = _ingest(
        test_client, monkeypatch, tmp_path, _payload(company_id, artifact=artifact)
    ).json()

    listed = test_client.get(
        "/v1/agent_runs", params={"company_id": company_id}
    ).json()["agent_runs"][0]
    detail = test_client.get(
        f"/v1/agent_runs/{ingested['id']}", params={"company_id": company_id}
    ).json()

    assert "artifact_text" not in listed
    assert "artifact_text" in detail
    assert detail["artifact_text"] == artifact


def test_oversized_artifact_returns_413_without_writing(
    sqlite_session, test_client, monkeypatch, tmp_path
):
    company_id = _make_company(sqlite_session)
    response = _ingest(
        test_client,
        monkeypatch,
        tmp_path,
        _payload(company_id, artifact="x" * (2 * 1024 * 1024 + 1)),
    )

    assert response.status_code == 413
    assert (
        sqlite_session.exec(
            select(AgentRun).where(AgentRun.company_id == company_id)
        ).all()
        == []
    )
    company_audits = sqlite_session.exec(select(AuditLog)).all()
    assert not any(
        audit.details and audit.details.get("company_id") == str(company_id)
        for audit in company_audits
    )


def test_each_insert_has_linked_audit_and_noop_does_not_add_one(
    sqlite_session, test_client, monkeypatch, tmp_path
):
    company_id = _make_company(sqlite_session)
    payload = _payload(company_id)
    first = _ingest(test_client, monkeypatch, tmp_path, payload)
    audit_rows = [
        audit
        for audit in sqlite_session.exec(
            select(AuditLog).where(
                AuditLog.interaction_id == f"agent-run:{payload['external_ref']}"
            )
        ).all()
        if audit.details.get("company_id") == str(company_id)
    ]
    assert len(audit_rows) == 1
    assert audit_rows[0].action == "agent_run_ingested"
    assert audit_rows[0].details["company_id"] == str(company_id)
    assert (
        sqlite_session.get(AgentRun, first.json()["id"]).audit_log_id
        == audit_rows[0].id
    )

    noop = _ingest(test_client, monkeypatch, tmp_path, payload)

    assert noop.status_code == 200
    audit_rows_after_noop = [
        audit
        for audit in sqlite_session.exec(
            select(AuditLog).where(
                AuditLog.interaction_id == f"agent-run:{payload['external_ref']}"
            )
        ).all()
        if audit.details.get("company_id") == str(company_id)
    ]
    assert len(audit_rows_after_noop) == 1


def test_list_filters_and_requires_company_id(
    sqlite_session, test_client, monkeypatch, tmp_path
):
    company_id = _make_company(sqlite_session)
    _ingest(
        test_client,
        monkeypatch,
        tmp_path,
        _payload(
            company_id,
            external_ref="github:first",
            producer="copilot",
        ),
    )
    _ingest(
        test_client,
        monkeypatch,
        tmp_path,
        _payload(company_id, external_ref="github:second", producer="claude-code"),
    )
    claude_run = sqlite_session.exec(
        select(AgentRun).where(
            AgentRun.company_id == company_id, AgentRun.producer == "claude-code"
        )
    ).first()
    claude_run.status = "verified"
    sqlite_session.add(claude_run)
    sqlite_session.commit()

    filtered = test_client.get(
        "/v1/agent_runs",
        params={
            "company_id": company_id,
            "producer": "claude-code",
            "status": "verified",
            "limit": 1,
            "since": "2000-01-01T00:00:00",
            "until": "2100-01-01T00:00:00",
        },
    )
    missing_company = test_client.get("/v1/agent_runs")

    assert filtered.status_code == 200
    assert len(filtered.json()["agent_runs"]) == 1
    assert filtered.json()["agent_runs"][0]["producer"] == "claude-code"
    assert missing_company.status_code == 422


def test_list_can_leave_out_the_companys_own_runs(
    sqlite_session, test_client, monkeypatch, tmp_path
):
    """The Review page asks only for the runs a person decides: the task
    worker's deliveries and the kickoff transcripts are decided by the loop."""
    company_id = _make_company(sqlite_session, "In-house runs")
    for ref, producer in (
        ("github:pr-1", "copilot"),
        ("task-1", "le-fabrique-task-worker"),
        ("graph:abc", "le-fabrique-graph"),
    ):
        _ingest(
            test_client,
            monkeypatch,
            tmp_path,
            _payload(company_id, external_ref=ref, producer=producer),
        )

    every = test_client.get("/v1/agent_runs", params={"company_id": company_id})
    external = test_client.get(
        "/v1/agent_runs", params={"company_id": company_id, "exclude_in_house": "true"}
    )

    assert sorted(r["producer"] for r in every.json()["agent_runs"]) == [
        "copilot",
        "le-fabrique-graph",
        "le-fabrique-task-worker",
    ]
    assert [r["external_ref"] for r in external.json()["agent_runs"]] == ["github:pr-1"]


def test_company_external_ref_version_is_unique(sqlite_session):
    company_id = _make_company(sqlite_session)
    first = AgentRun(
        company_id=company_id,
        external_ref="github:duplicate",
        producer="copilot",
        artifact_digest="a",
        artifact_size=0,
    )
    duplicate = AgentRun(
        company_id=company_id,
        external_ref="github:duplicate",
        producer="copilot",
        artifact_digest="b",
        artifact_size=0,
    )
    sqlite_session.add(first)
    sqlite_session.commit()
    sqlite_session.add(duplicate)

    with pytest.raises(IntegrityError):
        sqlite_session.commit()
    sqlite_session.rollback()


def _listed(test_client, **params):
    response = test_client.get("/v1/agent_runs", params=params)
    assert response.status_code == 200
    return response.json()["agent_runs"]


def test_list_filters_by_external_ref_newest_version_first(
    sqlite_session, test_client, monkeypatch, tmp_path
):
    company_id = _make_company(sqlite_session, name="Ref A")
    other_company = _make_company(sqlite_session, name="Ref B")
    first = _ingest(
        test_client,
        monkeypatch,
        tmp_path,
        _payload(company_id, external_ref="task-2", artifact="first attempt"),
    ).json()
    _ingest(
        test_client,
        monkeypatch,
        tmp_path,
        _payload(company_id, external_ref="task-3", artifact="other task"),
    )
    rework = _ingest(
        test_client,
        monkeypatch,
        tmp_path,
        _payload(company_id, external_ref="task-2", artifact="after rework"),
    ).json()
    _ingest(
        test_client,
        monkeypatch,
        tmp_path,
        _payload(other_company, external_ref="task-2", artifact="other company"),
    )

    runs = _listed(test_client, company_id=company_id, external_ref="task-2")
    latest = _listed(test_client, company_id=company_id, external_ref="task-2", limit=1)

    assert [(run["id"], run["version"]) for run in runs] == [
        (rework["id"], 2),
        (first["id"], 1),
    ]
    assert [run["id"] for run in latest] == [rework["id"]]


def test_list_filters_by_subject_sprint_id_before_limiting(
    sqlite_session, test_client, monkeypatch, tmp_path
):
    company_id = _make_company(sqlite_session, name="Sprint A")
    other_company = _make_company(sqlite_session, name="Sprint B")
    in_sprint = _ingest(
        test_client,
        monkeypatch,
        tmp_path,
        _payload(
            company_id,
            external_ref="task-2",
            subject={"sprint_id": 7, "backlog_item_id": 2, "title": "Encrypt"},
        ),
    ).json()
    # Newer runs that must not match: another sprint, a prefix-alike id, a
    # string id, no sprint at all, and the same sprint id in another company.
    for ref, subject in [
        ("task-5", {"sprint_id": 8, "backlog_item_id": 5}),
        ("task-6", {"sprint_id": 70, "backlog_item_id": 6}),
        ("task-7", {"sprint_id": "7", "backlog_item_id": 7}),
        ("github:no-subject", None),
        ("github:empty-subject", {}),
    ]:
        _ingest(
            test_client,
            monkeypatch,
            tmp_path,
            _payload(company_id, external_ref=ref, subject=subject),
        )
    _ingest(
        test_client,
        monkeypatch,
        tmp_path,
        _payload(other_company, external_ref="task-9", subject={"sprint_id": 7}),
    )

    runs = _listed(test_client, company_id=company_id, sprint_id=7)
    limited = _listed(test_client, company_id=company_id, sprint_id=7, limit=1)
    other = _listed(test_client, company_id=other_company, sprint_id=7)

    assert [run["id"] for run in runs] == [in_sprint["id"]]
    assert runs[0]["subject"]["backlog_item_id"] == 2
    # The filter applies before LIMIT: five newer non-matching runs exist.
    assert [run["id"] for run in limited] == [in_sprint["id"]]
    assert [run["external_ref"] for run in other] == ["task-9"]
    assert _listed(test_client, company_id=company_id, sprint_id=999) == []


def test_sprint_filter_compiles_without_integer_cast_on_postgres():
    from routers.agent_runs import _subject_sprint_id_equals
    from sqlalchemy.dialects import postgresql

    sql = str(
        select(AgentRun.id)
        .where(_subject_sprint_id_equals(7))
        .compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )

    assert "agent_runs.subject -> 'sprint_id'" in sql
    assert "AS VARCHAR" in sql
    assert "INTEGER" not in sql
