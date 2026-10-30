"""
Tests for the KPI emitters behind ``GET /v1/analytics/orchestration_health``.

The analytics queries in ``routers/enterprise.py`` read ``audit_log.details``
keys (``role``, ``company_id``, ``result_type``) and the ``ARCHITECT_CONSULTED:``
comment marker.  These tests pin the write side to that contract so the KPIs
cannot silently drift back to always-zero.
"""

import inspect

import pytest
from models import AuditLog
from sqlmodel import Session, SQLModel, create_engine, select

from app.services import orchestration_metrics as om
from app.services.orchestration_metrics import (
    ARCHITECT_CONSULT_MARKER,
    build_agent_turn_details,
    canonical_kpi_role,
    classify_review_result,
    count_architect_consults,
    extract_usage_tokens,
    format_architect_consult_comment,
    is_architect_consult_comment,
    record_agent_turn,
    should_consult_architect,
    usage_status,
)


@pytest.fixture
def audit_session():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine, tables=[AuditLog.__table__])
    with Session(engine) as session:
        yield session


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Dev", "Developer"),
        ("developer", "Developer"),
        ("Developer", "Developer"),
        ("", "Developer"),
        (None, "Developer"),
        ("QA", "QA"),
        ("tester", "QA"),
        ("Architect", "Architect"),
        ("PO", "PO"),
        ("SecOps", "SecOps"),  # unknown roles pass through untouched
    ],
)
def test_canonical_kpi_role(raw, expected):
    assert canonical_kpi_role(raw) == expected


def test_extract_usage_tokens_prefers_total_then_sums_split():
    assert extract_usage_tokens({"usage": {"total_tokens": 4120}}) == 4120
    assert (
        extract_usage_tokens({"usage": {"prompt_tokens": 100, "completion_tokens": 50}})
        == 150
    )
    assert extract_usage_tokens({"usage": {"total_tokens": "oops"}}) == 0
    assert extract_usage_tokens({}) == 0
    assert extract_usage_tokens(None) == 0


def test_usage_status_tells_an_unknown_count_from_a_zero():
    assert usage_status({"usage": {"total_tokens": 0}}) == "reported"
    assert usage_status({"usage": {"prompt_tokens": 10}}) == "reported"
    assert usage_status({"usage": {"total_tokens": "oops"}}) == "unavailable"
    assert usage_status({"usage": {}}) == "unavailable"
    assert usage_status({}) == "unavailable"
    assert usage_status(None) == "unavailable"


def test_an_estimate_from_the_proxy_is_never_taken_for_a_reported_count():
    estimated = {"usage_status": "estimated", "usage_estimate": 40}
    assert usage_status(estimated) == "estimated"
    assert extract_usage_tokens(estimated) == 0


def test_record_agent_turn_marks_whether_tokens_were_reported(audit_session):
    reported = record_agent_turn(
        agent={"role": "Developer", "name": "dev"},
        llm_result={"usage": {"total_tokens": 12}},
        company_id=1,
        sprint_id=1,
        backlog_item_id=1,
        action="task.execute",
        session=audit_session,
    )
    unknown = record_agent_turn(
        agent={"role": "Developer", "name": "dev"},
        llm_result={"text": "no usage block"},
        company_id=1,
        sprint_id=1,
        backlog_item_id=2,
        action="task.execute",
        session=audit_session,
    )
    assert (reported.details["tokens"], reported.cost_tokens) == ("reported", 12)
    # The stored count is still 0, but the row says it is unknown, not zero.
    assert (unknown.details["tokens"], unknown.cost_tokens) == ("unavailable", 0)


def test_classify_review_result():
    assert classify_review_result("APPROVED: looks good") == "APPROVED"
    assert classify_review_result("  needs work: missing tests") == "NEEDS_WORK"
    assert classify_review_result("NEEDS_WORK: legacy spelling") == "NEEDS_WORK"
    assert classify_review_result("I think this is fine") is None
    assert classify_review_result(None) is None


def test_build_agent_turn_details_matches_query_contract():
    details = build_agent_turn_details(
        role="Dev",
        company_id=7,
        sprint_id=3,
        backlog_item_id=42,
        model="deepseek-coder",
        agent_name="Atlas",
        result_type=None,
    )
    # Keys the SQL in routers/enterprise.py filters on.
    assert details["role"] == "Developer"
    assert details["company_id"] == "7"
    assert "result_type" not in details
    # Lineage context.
    assert details["agent_role"] == "Dev"
    assert details["sprint_id"] == 3
    assert details["backlog_item_id"] == 42
    assert details["model"] == "deepseek-coder"
    assert details["agent_name"] == "Atlas"

    qa = build_agent_turn_details(role="QA", company_id=7, result_type="NEEDS_WORK")
    assert qa["role"] == "QA"
    assert qa["result_type"] == "NEEDS_WORK"


def test_architect_consult_comment_roundtrip():
    text = format_architect_consult_comment(
        "  Use the existing repository pattern.\n\n"
    )
    assert text.startswith(ARCHITECT_CONSULT_MARKER + " ")
    assert text.endswith("repository pattern.")
    comment = {"author": "Architect", "text": text}
    assert is_architect_consult_comment(comment)
    assert not is_architect_consult_comment({"author": "Developer", "text": text})
    assert not is_architect_consult_comment(
        {"author": "Architect", "text": "APPROVED: fine"}
    )
    assert (
        count_architect_consults([comment, {"author": "System", "text": "x"}, comment])
        == 2
    )


def test_format_architect_consult_comment_truncates():
    text = format_architect_consult_comment("x" * 5000, max_chars=100)
    assert len(text) <= len(ARCHITECT_CONSULT_MARKER) + 1 + 100
    assert text.endswith("…")


# ---------------------------------------------------------------------------
# Consultation policy
# ---------------------------------------------------------------------------

_DEV = {"role": "Dev", "name": "Atlas"}


def test_should_consult_architect_for_high_priority_dev_task():
    item = {"title": "Ship login page", "description": "", "priority": "high"}
    assert should_consult_architect(item, _DEV, [])


def test_should_consult_architect_for_design_keywords():
    item = {
        "title": "Add pagination",
        "description": "Requires a schema migration",
        "priority": "medium",
    }
    assert should_consult_architect(item, _DEV, [])


def test_should_not_consult_architect_for_routine_dev_task():
    item = {"title": "Fix typo in footer", "description": "", "priority": "low"}
    assert not should_consult_architect(item, _DEV, [])


def test_should_not_consult_architect_for_non_developer_roles():
    item = {
        "title": "Design system architecture",
        "description": "",
        "priority": "critical",
    }
    assert not should_consult_architect(item, {"role": "Architect"}, [])
    assert not should_consult_architect(item, {"role": "QA"}, [])
    assert not should_consult_architect(item, {"role": "PO"}, [])


def test_should_consult_architect_respects_feature_flag():
    item = {"title": "Ship login page", "description": "", "priority": "critical"}
    assert not should_consult_architect(item, _DEV, [], enabled=False)


def test_should_consult_architect_once_per_attempt_and_again_after_rework():
    item = {"title": "Ship login page", "description": "", "priority": "high"}
    consulted = {"author": "Architect", "text": f"{ARCHITECT_CONSULT_MARKER} do X"}
    deliverable = {"author": "Atlas", "text": "Here is the implementation ..."}
    needs_work = {"author": "QA", "text": "NEEDS WORK: missing validation"}

    # Already consulted on this attempt → do not consult twice.
    assert not should_consult_architect(item, _DEV, [consulted, deliverable])
    # QA sent it back → a new attempt earns a fresh consultation, even for a low-priority task.
    assert should_consult_architect(item, _DEV, [consulted, deliverable, needs_work])
    low = {"title": "Fix typo", "description": "", "priority": "low"}
    assert should_consult_architect(low, _DEV, [deliverable, needs_work])
    # Consulted again for the rework → stop until the next rework.
    assert not should_consult_architect(
        item, _DEV, [consulted, deliverable, needs_work, consulted]
    )


def test_should_consult_architect_accepts_json_string_comments():
    item = {"title": "Ship login page", "description": "", "priority": "high"}
    comments = '[{"author": "Architect", "text": "ARCHITECT_CONSULTED: done"}]'
    assert not should_consult_architect(item, _DEV, comments)
    assert should_consult_architect(item, _DEV, "not json")


# ---------------------------------------------------------------------------
# Persistence — the row shape the KPI queries consume
# ---------------------------------------------------------------------------


def test_record_agent_turn_writes_developer_row_with_tokens(audit_session):
    row = record_agent_turn(
        company_id=7,
        sprint_id=3,
        backlog_item_id=42,
        agent={"role": "Dev", "name": "Atlas", "model": "deepseek-coder"},
        action="execute_task",
        llm_result={"usage": {"total_tokens": 4120}, "choices": []},
        result_preview="deliverable text",
        session=audit_session,
    )
    assert row is not None and row.id is not None

    stored = audit_session.exec(select(AuditLog)).one()
    assert stored.action == "execute_task"
    assert stored.agent_id == "Atlas"
    assert stored.interaction_id == "task-42"
    assert stored.cost_tokens == 4120
    assert stored.details["role"] == "Developer"
    assert stored.details["company_id"] == "7"
    assert stored.result["preview"] == "deliverable text"


def test_record_agent_turn_writes_qa_row_with_result_type(audit_session):
    record_agent_turn(
        company_id=7,
        sprint_id=3,
        backlog_item_id=42,
        agent={"role": "QA", "name": "QA", "model": "deepseek-coder"},
        action="qa_review",
        llm_result={"usage": {"prompt_tokens": 300, "completion_tokens": 40}},
        result_type=classify_review_result("NEEDS WORK: add tests"),
        session=audit_session,
    )
    stored = audit_session.exec(select(AuditLog)).one()
    assert stored.details["role"] == "QA"
    assert stored.details["result_type"] == "NEEDS_WORK"
    assert stored.result["result_type"] == "NEEDS_WORK"
    assert stored.cost_tokens == 340


def test_record_agent_turn_never_raises(audit_session, monkeypatch):
    class BrokenSession:
        def add(self, _row):
            raise RuntimeError("db down")

        def commit(self):  # pragma: no cover
            pass

    assert (
        record_agent_turn(
            company_id=1,
            sprint_id=1,
            backlog_item_id=1,
            agent={"role": "Dev"},
            action="execute_task",
            llm_result={},
            session=BrokenSession(),
        )
        is None
    )


# ---------------------------------------------------------------------------
# Contract with the analytics router
# ---------------------------------------------------------------------------


def test_router_queries_use_the_same_contract_as_the_emitters():
    from app.routers import enterprise

    source = inspect.getsource(enterprise.get_orchestration_health)
    assert f"LIKE '{ARCHITECT_CONSULT_MARKER}%'" in source
    assert f"c->>'author' = '{om.ARCHITECT_COMMENT_AUTHOR}'" in source
    assert f"a.details->>'role' = '{om.KPI_ROLE_DEVELOPER}'" in source
    assert f"a.details->>'role' = '{om.KPI_ROLE_QA}'" in source
    assert f"a.details->>'result_type' = '{om.RESULT_NEEDS_WORK}'" in source
    # QA-assigned *executions* also carry role=QA; only review turns may feed the QA rate.
    assert f"a.action = '{om.ACTION_QA_REVIEW}'" in source
    assert "a.details->>'company_id'" in source
