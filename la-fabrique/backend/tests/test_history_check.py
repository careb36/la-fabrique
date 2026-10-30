"""
The independent checker of task histories (``app/history_check.py``).

Each rule is shown on a legal history it accepts and an illegal one it
reports; the checker reads the database the same way, and it imports none
of the production readers it is meant to check.
"""

import ast
from pathlib import Path

import database
import history_check
from history_check import check_task
from models import AgentMessage, AgentRun, BacklogItem, Company, Sprint

DELIVERABLE = {
    "author": "Dev",
    "text": "Implemented it.\n```python path=src/a.py\nx = 1\n```",
}
APPROVAL = {"author": "QA", "text": "APPROVED: good"}
VERIFIED = [{"version": 1, "status": "verified"}]


def _task(status, *comments):
    return {"id": 1, "status": status, "comments": list(comments)}


def test_a_delivered_verified_and_approved_task_is_legal():
    assert check_task(_task("done", DELIVERABLE, APPROVAL), VERIFIED, []) == []


def test_done_needs_an_approval_or_a_person():
    assert check_task(_task("done", DELIVERABLE), VERIFIED, []) == [
        "done_without_approval"
    ]
    person = {"author": "user", "text": "Done by hand."}
    assert check_task(_task("done", DELIVERABLE, person), [], []) == []


def test_an_approval_needs_a_deliverable_before_it():
    gate = {"author": "Verifier", "text": "NEEDS WORK: x"}
    assert check_task(_task("done", gate, APPROVAL), VERIFIED, []) == [
        "approved_without_delivery: comment 1"
    ]


def test_an_approval_does_not_close_a_task_whose_delivery_was_not_verified():
    refuted = [
        {"version": 1, "status": "verified"},
        {"version": 2, "status": "refuted"},
    ]
    assert check_task(_task("done", DELIVERABLE, APPROVAL), refuted, []) == [
        "done_without_verified_delivery: latest run v2 is refuted"
    ]
    assert check_task(_task("done", DELIVERABLE, APPROVAL), [], []) == [
        "done_without_verified_delivery: no run recorded"
    ]
    # A person who closes it after the approval takes that decision.
    person = {"author": "user", "text": "Accepted."}
    assert check_task(_task("done", DELIVERABLE, APPROVAL, person), refuted, []) == []


def test_a_high_risk_hold_closes_only_through_a_person():
    hold = {
        "author": "System",
        "text": f"{history_check._RISK_HOLD} (authentication: a).",
    }
    accepted = {"author": "user", "text": "High-risk delivery accepted by a person."}
    assert (
        check_task(_task("done", DELIVERABLE, APPROVAL, hold, accepted), VERIFIED, [])
        == []
    )
    assert check_task(_task("done", DELIVERABLE, APPROVAL, hold), VERIFIED, []) == [
        "high_risk_done_without_person"
    ]
    assert check_task(_task("blocked", DELIVERABLE, APPROVAL, hold), VERIFIED, []) == []


def test_a_task_is_carried_over_once():
    note = {"author": "System", "text": "Carried over to sprint 2 as task 9."}
    assert check_task(_task("blocked", DELIVERABLE, note), [], []) == []
    assert check_task(_task("blocked", DELIVERABLE, note, note), [], []) == [
        "carried_twice: carried 2 times"
    ]


def test_a_decision_answers_an_escalation_of_its_own_task():
    escalation = {"id": 5, "kind": "escalation", "body": "blocked"}
    decision = {
        "id": 6,
        "kind": "decision",
        "body": "Triage decision: leave it for a person.\nAnswers escalation #5",
    }
    blocked = _task("blocked", DELIVERABLE)
    assert check_task(blocked, [], [escalation, decision]) == []
    stray = {**decision, "body": decision["body"].replace("#5", "#99")}
    assert check_task(blocked, [], [escalation, stray]) == [
        "decision_without_escalation: message 6 answers #99, which this task never had"
    ]
    unanswered = {**decision, "body": "Triage decision: leave it for a person."}
    assert check_task(blocked, [], [unanswered]) == [
        "decision_without_escalation: message 6 on a task never escalated"
    ]
    # QA's own decisions are not triage decisions.
    assert (
        check_task(blocked, [], [{"id": 7, "kind": "decision", "body": "APPROVED: ok"}])
        == []
    )


def test_the_database_is_read_the_same_way(sqlite_session, monkeypatch):
    monkeypatch.setattr(database, "engine", sqlite_session.get_bind())
    company = Company(company_name="History")
    sqlite_session.add(company)
    sqlite_session.commit()
    sqlite_session.refresh(company)
    sprint = Sprint(company_id=company.id, sprint_name="S", scope_size="S")
    sqlite_session.add(sprint)
    sqlite_session.commit()
    sqlite_session.refresh(sprint)
    good = BacklogItem(
        sprint_id=sprint.id,
        title="good one",
        status="done",
        comments=[DELIVERABLE, APPROVAL],
    )
    bad = BacklogItem(
        sprint_id=sprint.id,
        title="bad one",
        status="done",
        comments=[DELIVERABLE, APPROVAL],
    )
    sqlite_session.add_all([good, bad])
    sqlite_session.commit()
    for item, status in ((good, "verified"), (bad, "refuted")):
        sqlite_session.add(
            AgentRun(
                company_id=company.id,
                external_ref=f"task-{item.id}",
                producer=history_check._TASK_WORKER,
                artifact_digest="d",
                artifact_size=1,
                status=status,
            )
        )
    stray = AgentMessage(
        company_id=company.id,
        sprint_id=sprint.id,
        backlog_item_id=good.id,
        from_name="ScrumMaster",
        from_role="ScrumMaster",
        kind="decision",
        body="Triage decision: leave it for a person.\nAnswers escalation #424242",
    )
    sqlite_session.add(stray)
    sqlite_session.commit()
    sqlite_session.refresh(stray)

    found = [
        v
        for v in history_check.check_database()
        if "(good one)" in v or "(bad one)" in v
    ]

    assert found == [
        (
            f"task {good.id} (good one): decision_without_escalation: message "
            f"{stray.id} answers #424242, which this task never had"
        ),
        f"task {bad.id} (bad one): done_without_verified_delivery: latest run v1 is refuted",
    ]


def test_it_imports_none_of_the_readers_it_checks():
    source = Path(history_check.__file__).read_text()
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not {m for m in imported if m.startswith("services")}
