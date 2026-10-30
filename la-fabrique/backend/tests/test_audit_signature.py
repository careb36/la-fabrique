"""Tests for server-side audit decision signatures."""

import json
import logging
from datetime import UTC, datetime
from types import SimpleNamespace

import audit_signing
import pytest
from audit_signing import (
    SIGNED_PREFIX,
    UNSIGNED_PREFIX,
    canonical_payload,
    sign_audit_payload,
    verify_audit_row,
)
from models.audit import AuditLog
from services.agent_service import AgentService
from sqlmodel import Session


@pytest.fixture
def with_key(monkeypatch):
    key = "test-audit-signing-key"
    monkeypatch.setattr(audit_signing, "_configured_key", lambda: key)
    return key


@pytest.fixture
def without_key(monkeypatch):
    monkeypatch.setattr(audit_signing, "_configured_key", lambda: None)
    monkeypatch.setattr(audit_signing, "_missing_key_warned", False)


@pytest.fixture
def audit_log_path(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path))
    return tmp_path


def _write_audit(
    session,
    interaction_id="test-interaction",
    agent_id="agent-1",
    details=None,
    result=None,
    cost_tokens=7,
    decision_signature=None,
):
    return AgentService().audit_interaction(
        session=session,
        interaction_id=interaction_id,
        agent_id=agent_id,
        action="execute",
        details=details if details is not None else {"input": "value"},
        result=result if result is not None else {"output": "complete"},
        decision_signature=decision_signature,
        cost_tokens=cost_tokens,
    )


def test_signed_audit_row_verifies(with_key, sqlite_session, audit_log_path):
    row = _write_audit(sqlite_session)

    assert row.decision_signature.startswith(SIGNED_PREFIX)
    assert verify_audit_row(row) == {"status": "valid", "mode": "hmac-sha256"}


def test_canonical_payload_bytes_are_pinned():
    payload = canonical_payload(
        interaction_id="i-1",
        agent_id="agent-1",
        action="run",
        details={"b": 2, "a": "ñ"},
        result=None,
        cost_tokens=3,
        # Naive on purpose: the row is signed after a refresh, with the value a
        # `timestamp` column hands back, and verified the same way.
        created_at=datetime(2026, 1, 2, 3, 4, 5),
    )

    assert payload == (
        b'{"action":"run","agent_id":"agent-1","cost_tokens":3,'
        b'"created_at":"2026-01-02T03:04:05","details":{"a":"\xc3\xb1","b":2},'
        b'"interaction_id":"i-1","result":null}'
    )


def test_tampering_with_details_invalidates_signature(
    with_key, sqlite_session, audit_log_path
):
    row = _write_audit(sqlite_session)
    row.details = {"input": "tampered"}

    assert verify_audit_row(row)["status"] == "invalid"


def test_tampering_with_result_invalidates_signature(
    with_key, sqlite_session, audit_log_path
):
    row = _write_audit(sqlite_session)
    row.result = {"output": "tampered"}

    assert verify_audit_row(row)["status"] == "invalid"


def test_tampering_with_cost_tokens_invalidates_signature(
    with_key, sqlite_session, audit_log_path
):
    row = _write_audit(sqlite_session)
    row.cost_tokens += 1

    assert verify_audit_row(row)["status"] == "invalid"


def test_signature_does_not_verify_under_a_different_key(
    monkeypatch, sqlite_session, audit_log_path
):
    right_key = "right-audit-key"
    monkeypatch.setattr(audit_signing, "_configured_key", lambda: right_key)
    row = _write_audit(sqlite_session)

    monkeypatch.setattr(audit_signing, "_configured_key", lambda: "wrong-audit-key")
    assert verify_audit_row(row)["status"] == "invalid"


def test_missing_key_writes_unsigned_rows_and_warns_once(
    without_key, sqlite_session, audit_log_path, caplog
):
    with caplog.at_level(logging.WARNING, logger="fabrique-backend"):
        first = _write_audit(sqlite_session, interaction_id="unsigned-one")
        second = _write_audit(sqlite_session, interaction_id="unsigned-two")

    assert first.decision_signature.startswith(UNSIGNED_PREFIX)
    assert verify_audit_row(first) == {"status": "unsigned", "mode": "unsigned"}
    assert verify_audit_row(second)["status"] == "unsigned"
    warnings = [
        record
        for record in caplog.records
        if "AUDIT_SIGNING_KEY" in record.getMessage()
    ]
    assert len(warnings) == 1


def test_tampered_unsigned_signature_is_invalid(without_key):
    created_at = datetime(2026, 1, 2, 3, 4, 5)  # naive, as read back from the column
    row = SimpleNamespace(
        interaction_id="unsigned-row",
        agent_id="agent-1",
        action="execute",
        details={"input": "original"},
        result={"output": "complete"},
        cost_tokens=4,
        created_at=created_at,
        decision_signature=sign_audit_payload(
            canonical_payload(
                interaction_id="unsigned-row",
                agent_id="agent-1",
                action="execute",
                details={"input": "original"},
                result={"output": "complete"},
                cost_tokens=4,
                created_at=created_at,
            )
        ),
    )
    assert verify_audit_row(row)["status"] == "unsigned"

    row.details = {"input": "tampered"}
    assert verify_audit_row(row) == {"status": "invalid", "mode": "unsigned"}


def test_missing_or_unprefixed_signature_is_legacy(with_key):
    row = SimpleNamespace(decision_signature=None)
    assert verify_audit_row(row) == {"status": "legacy", "mode": "legacy"}

    row.decision_signature = "a" * 64
    assert verify_audit_row(row) == {"status": "legacy", "mode": "legacy"}


def test_caller_supplied_signature_is_ignored_and_warned(
    with_key, sqlite_session, audit_log_path, caplog
):
    with caplog.at_level(logging.WARNING, logger="fabrique-backend"):
        row = _write_audit(sqlite_session, decision_signature="forged")

    assert row.decision_signature != "forged"
    assert row.decision_signature.startswith(SIGNED_PREFIX)
    assert any(
        "decision_signature supplied by caller is ignored" in record.getMessage()
        for record in caplog.records
    )


def test_jsonl_and_database_share_signature_and_timestamp(
    with_key, sqlite_session, audit_log_path
):
    row = _write_audit(sqlite_session, interaction_id="same-record")
    entry = json.loads((audit_log_path / "audit.jsonl").read_text().splitlines()[-1])

    assert entry["decision_signature"] == row.decision_signature
    assert entry["timestamp"] == row.created_at.isoformat()


def test_integer_agent_id_verifies_after_loading_in_a_new_session(
    with_key, sqlite_session, audit_log_path
):
    written = _write_audit(
        sqlite_session,
        interaction_id="integer-agent-id",
        agent_id=7,
    )

    with Session(sqlite_session.get_bind()) as read_session:
        row = read_session.get(AuditLog, written.id)

    assert row.agent_id == "7"
    assert verify_audit_row(row)["status"] == "valid"


def test_verify_endpoint_reports_valid_and_legacy_rows(
    with_key, sqlite_session, audit_log_path, test_client
):
    interaction_id = "endpoint-interaction"
    valid_row = _write_audit(sqlite_session, interaction_id=interaction_id)
    sqlite_session.add(
        AuditLog(
            interaction_id=interaction_id,
            agent_id="agent-2",
            action="legacy",
            details={},
            result={},
            cost_tokens=0,
            created_at=datetime.now(UTC).replace(tzinfo=None),
            decision_signature=None,
        )
    )
    sqlite_session.commit()

    response = test_client.get(f"/v1/audit/verify?interaction_id={interaction_id}")
    assert response.status_code == 200
    assert response.json()["summary"] == {
        "valid": 1,
        "invalid": 0,
        "unsigned": 0,
        "legacy": 1,
    }
    assert [row["id"] for row in response.json()["rows"]] == [
        valid_row.id,
        valid_row.id + 1,
    ]

    missing = test_client.get("/v1/audit/verify?interaction_id=unknown-interaction")
    assert missing.status_code == 404
