"""
An independent checker of task histories.

It reads what the database holds about each task (its status, its comment
thread, the task worker's runs of it and the company's messages about it)
and reports histories the loop must never produce:

- ``done_without_approval``: done with neither an explicit ``APPROVED:`` from
  a reviewer nor a note from a person;
- ``approved_without_delivery``: an ``APPROVED:`` with no deliverable before it;
- ``done_without_verified_delivery``: closed by an approval while the task
  worker's latest run of it was refuted, unverifiable or never recorded;
- ``high_risk_done_without_person``: a high-risk hold closed with no note
  from a person after it;
- ``carried_twice``: one task carried into another sprint more than once;
- ``decision_without_escalation``: a ScrumMaster decision that names an
  escalation the task never had.

It deliberately imports none of the production readers (``services/board.py``,
``services/carry_over.py``, ``services/scrum_master.py``) and restates the
markers it looks for, so a bug shared with them cannot hide here. It runs in
the tests (``tests/test_history_check.py``) and at the end of
``scripts/e2e/run.sh`` against the run's database::

    PYTHONPATH=.:app python app/history_check.py

which prints every violation and exits 1 when there is one.
"""

from __future__ import annotations

import sys
from typing import Any

# Restated on purpose; see the module docstring.
_GATE_AUTHORS = {"quality gate", "verifier"}
_PERSON = "user"
_CARRIED_TO = "Carried over to sprint"
_RISK_HOLD = "High-risk delivery approved by QA, waiting for a person to accept it"
_ANSWERS = "Answers escalation #"
_DECISION_FIRST_LINES = ("Triage decision:",)
_TASK_WORKER = "le-fabrique-task-worker"


def _author(comment: dict[str, Any]) -> str:
    return str(comment.get("author") or "").strip().lower()


def _text(comment: dict[str, Any]) -> str:
    return str(comment.get("text") or "").strip()


def _is_approval(comment: dict[str, Any]) -> bool:
    return _author(comment) not in _GATE_AUTHORS | {"system", _PERSON} and _text(
        comment
    ).upper().startswith("APPROVED:")


def _is_deliverable(comment: dict[str, Any]) -> bool:
    text = _text(comment)
    return (
        bool(text)
        and _author(comment) not in _GATE_AUTHORS | {"system", _PERSON}
        and not text.upper().startswith(("APPROVED:", "NEEDS WORK:"))
        and not text.startswith("ARCHITECT_CONSULTED:")
    )


def _answered(body: str) -> int | None:
    for line in (body or "").split("\n"):
        line = line.strip()
        if line.startswith(_ANSWERS) and line[len(_ANSWERS) :].isdigit():
            return int(line[len(_ANSWERS) :])
    return None


def check_task(
    task: dict[str, Any],
    runs: list[dict[str, Any]],
    messages: list[dict[str, Any]],
) -> list[str]:
    """The violations in one task's history, as ``"<rule>: <detail>"`` lines.

    *task* has ``id``, ``status`` and ``comments``; *runs* are the task
    worker's runs of it with ``version`` and ``status``; *messages* are the
    company's messages about it with ``id``, ``kind`` and ``body``.
    """
    comments = [c for c in task.get("comments") or [] if isinstance(c, dict)]
    status = task.get("status")
    violations: list[str] = []

    approvals = [i for i, c in enumerate(comments) if _is_approval(c)]
    person_notes = [i for i, c in enumerate(comments) if _author(c) == _PERSON]

    for index in approvals:
        if not any(_is_deliverable(c) for c in comments[:index]):
            violations.append(f"approved_without_delivery: comment {index}")

    if status == "done":
        if not approvals and not person_notes:
            violations.append("done_without_approval")
        closed_by_person = bool(person_notes) and (
            not approvals or person_notes[-1] > approvals[-1]
        )
        if approvals and not closed_by_person:
            latest = max(runs, key=lambda r: r.get("version") or 0) if runs else None
            if latest is None:
                violations.append("done_without_verified_delivery: no run recorded")
            elif latest.get("status") != "verified":
                violations.append(
                    "done_without_verified_delivery: latest run "
                    f"v{latest.get('version')} is {latest.get('status')}"
                )
        holds = [
            i
            for i, c in enumerate(comments)
            if _author(c) == "system" and _text(c).startswith(_RISK_HOLD)
        ]
        if holds and not any(i > holds[-1] for i in person_notes):
            violations.append("high_risk_done_without_person")

    carried = sum(1 for c in comments if _text(c).startswith(_CARRIED_TO))
    if carried > 1:
        violations.append(f"carried_twice: carried {carried} times")

    escalations = {m.get("id") for m in messages if m.get("kind") == "escalation"}
    for message in messages:
        if message.get("kind") != "decision":
            continue
        body = str(message.get("body") or "")
        if not body.startswith(_DECISION_FIRST_LINES):
            continue
        answers = _answered(body)
        if answers is not None and answers not in escalations:
            violations.append(
                f"decision_without_escalation: message {message.get('id')} "
                f"answers #{answers}, which this task never had"
            )
        elif answers is None and not escalations:
            violations.append(
                f"decision_without_escalation: message {message.get('id')} "
                "on a task never escalated"
            )
    return violations


def check_database() -> list[str]:
    """Every task in the database, checked; violations prefixed with the task id."""
    from database import engine
    from models import AgentMessage, AgentRun, BacklogItem
    from sqlmodel import Session, select

    found: list[str] = []
    with Session(engine) as session:
        runs_by_ref: dict[str, list[dict[str, Any]]] = {}
        for run in session.exec(
            select(AgentRun).where(AgentRun.producer == _TASK_WORKER)
        ).all():
            runs_by_ref.setdefault(run.external_ref, []).append(
                {"version": run.version, "status": run.status}
            )
        messages_by_task: dict[int, list[dict[str, Any]]] = {}
        for message in session.exec(select(AgentMessage)).all():
            if message.backlog_item_id is not None:
                messages_by_task.setdefault(message.backlog_item_id, []).append(
                    {"id": message.id, "kind": message.kind, "body": message.body}
                )
        for item in session.exec(select(BacklogItem)).all():
            task = {"id": item.id, "status": item.status, "comments": item.comments}
            for violation in check_task(
                task,
                runs_by_ref.get(f"task-{item.id}", []),
                messages_by_task.get(item.id, []),
            ):
                found.append(f"task {item.id} ({item.title}): {violation}")
    return found


if __name__ == "__main__":
    problems = check_database()
    for problem in problems:
        print(problem)
    print(f"{len(problems)} illegal history(ies)")
    sys.exit(1 if problems else 0)
