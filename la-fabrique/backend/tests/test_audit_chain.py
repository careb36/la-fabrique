"""The per-company hash chain over audit rows (audit_chain.py)."""

import secrets

import audit_signing
import pytest
from audit_chain import chain_hash, verify_chain
from audit_signing import SIGNED_PREFIX, UNSIGNED_PREFIX
from models.audit import AuditLog
from services.agent_service import AgentService
from services.orchestration_metrics import record_agent_turn
from sqlmodel import select


@pytest.fixture(autouse=True)
def audit_log_path(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path))


@pytest.fixture
def with_key(monkeypatch):
    monkeypatch.setattr(audit_signing, "_configured_key", lambda: "chain-test-key")


@pytest.fixture
def without_key(monkeypatch):
    monkeypatch.setattr(audit_signing, "_configured_key", lambda: None)


def _company() -> int:
    # The tests share one SQLite engine: a fresh id keeps each chain apart.
    return 10_000 + secrets.randbelow(10_000_000)


def _write(session, company_id, action="execute", tokens=1):
    return AgentService().audit_interaction(
        session=session,
        interaction_id=f"chain-{secrets.token_hex(4)}",
        agent_id="developer",
        action=action,
        details={"n": tokens},
        result={"ok": True},
        decision_signature=None,
        cost_tokens=tokens,
        company_id=company_id,
    )


def _rows(session, company_id):
    return session.exec(
        select(AuditLog)
        .where(AuditLog.company_id == company_id)
        .order_by(AuditLog.chain_seq)
    ).all()


def test_rows_of_a_company_form_an_intact_keyed_chain(with_key, sqlite_session):
    company = _company()
    rows = [_write(sqlite_session, company, tokens=n) for n in range(1, 4)]

    assert [row.chain_seq for row in rows] == [1, 2, 3]
    assert rows[0].prev_hash is None
    assert [row.prev_hash for row in rows[1:]] == [
        rows[0].chain_hash,
        rows[1].chain_hash,
    ]
    assert all(row.chain_hash.startswith(SIGNED_PREFIX) for row in rows)
    report = verify_chain(sqlite_session, company)
    assert report == {
        "company_id": company,
        "status": "intact",
        "mode": "hmac-sha256",
        "rows": 3,
        "head": {"seq": 3, "chain_hash": rows[2].chain_hash},
        "breaks": [],
    }


def test_each_company_has_its_own_chain(with_key, sqlite_session):
    first, second = _company(), _company()
    _write(sqlite_session, first)
    _write(sqlite_session, second)
    row = _write(sqlite_session, first)

    assert row.chain_seq == 2
    assert verify_chain(sqlite_session, second)["rows"] == 1


def test_a_deleted_row_breaks_the_chain_where_it_was(with_key, sqlite_session):
    company = _company()
    rows = [_write(sqlite_session, company, tokens=n) for n in range(1, 4)]
    sqlite_session.delete(rows[1])
    sqlite_session.commit()

    report = verify_chain(sqlite_session, company)
    assert report["status"] == "broken"
    assert {"seq": 3, "reason": "gap"} in report["breaks"]
    assert {"seq": 3, "reason": "prev_mismatch"} in report["breaks"]


def test_an_altered_row_breaks_the_chain(with_key, sqlite_session):
    company = _company()
    rows = [_write(sqlite_session, company, tokens=n) for n in range(1, 3)]
    rows[0].cost_tokens = 999
    sqlite_session.add(rows[0])
    sqlite_session.commit()

    assert verify_chain(sqlite_session, company)["breaks"] == [
        {"seq": 1, "reason": "hash_mismatch"}
    ]


def test_a_row_moved_to_another_company_breaks_both_chains(with_key, sqlite_session):
    source, target = _company(), _company()
    moved = _write(sqlite_session, source)
    _write(sqlite_session, source)
    _write(sqlite_session, target)
    moved.company_id = target
    moved.chain_seq = 2
    moved.prev_hash = _rows(sqlite_session, target)[0].chain_hash
    sqlite_session.add(moved)
    sqlite_session.commit()

    # The company id is inside the hash: renumbering the row does not make it belong.
    assert {"seq": 2, "reason": "hash_mismatch"} in verify_chain(
        sqlite_session, target
    )["breaks"]
    assert verify_chain(sqlite_session, source)["status"] == "broken"


def test_a_rewritten_chain_without_the_key_does_not_verify(with_key, sqlite_session):
    company = _company()
    first = _write(sqlite_session, company)
    row = _write(sqlite_session, company)
    # Someone with database access but no key alters the last row and
    # recomputes its hash. Labelled as keyed, it does not match.
    row.cost_tokens = 0
    forged = chain_hash(company, 2, first.chain_hash, row, key=None)
    row.chain_hash = forged.replace(UNSIGNED_PREFIX, SIGNED_PREFIX)
    sqlite_session.add(row)
    sqlite_session.commit()
    assert verify_chain(sqlite_session, company)["breaks"] == [
        {"seq": 2, "reason": "hash_mismatch"}
    ]

    # Labelled honestly as unkeyed, it matches its own hash, but follows a
    # keyed row while a key is configured: a downgrade.
    row.chain_hash = forged
    sqlite_session.add(row)
    sqlite_session.commit()
    report = verify_chain(sqlite_session, company)
    assert (report["status"], report["breaks"]) == (
        "broken",
        [{"seq": 2, "reason": "downgrade"}],
    )


def test_unkeyed_rows_from_before_the_key_are_not_a_downgrade(
    monkeypatch, sqlite_session
):
    company = _company()
    monkeypatch.setattr(audit_signing, "_configured_key", lambda: None)
    _write(sqlite_session, company)
    monkeypatch.setattr(audit_signing, "_configured_key", lambda: "chain-test-key")
    _write(sqlite_session, company)

    report = verify_chain(sqlite_session, company)
    assert (report["status"], report["mode"]) == ("intact", "mixed")


def test_without_a_key_the_chain_is_unkeyed_and_says_so(without_key, sqlite_session):
    company = _company()
    _write(sqlite_session, company)
    _write(sqlite_session, company)

    report = verify_chain(sqlite_session, company)
    assert (report["status"], report["mode"]) == ("intact", "unsigned")


def test_a_keyed_chain_cannot_be_checked_once_the_key_is_gone(
    monkeypatch, sqlite_session
):
    company = _company()
    monkeypatch.setattr(audit_signing, "_configured_key", lambda: "chain-test-key")
    _write(sqlite_session, company)
    monkeypatch.setattr(audit_signing, "_configured_key", lambda: None)

    assert verify_chain(sqlite_session, company)["breaks"] == [
        {"seq": 1, "reason": "key_missing"}
    ]


def test_rows_without_a_company_are_not_chained(with_key, sqlite_session):
    row = _write(sqlite_session, None)
    assert (row.chain_seq, row.prev_hash, row.chain_hash) == (None, None, None)
    assert row.decision_signature.startswith(SIGNED_PREFIX)


def test_an_empty_chain_is_reported_as_empty(sqlite_session):
    assert verify_chain(sqlite_session, _company())["status"] == "empty"


def test_kpi_turn_rows_are_signed_and_chained(with_key, sqlite_session):
    company = _company()
    _write(sqlite_session, company)
    row = record_agent_turn(
        agent={"role": "Developer", "name": "dev", "model": "m"},
        llm_result={"usage": {"total_tokens": 5}},
        company_id=company,
        sprint_id=1,
        backlog_item_id=1,
        action="task.execute",
        session=sqlite_session,
    )

    assert row.decision_signature.startswith(SIGNED_PREFIX)
    assert row.chain_seq == 2
    assert verify_chain(sqlite_session, company)["status"] == "intact"
