"""
Procedures: proposing, adopting, measuring, and putting them in prompts.

The company learns by changing its procedures, and the board decides whether
a change helped (deterministic checks decide, a model may only propose).
After adoption, the next ``MEASURE_AFTER_SPRINTS`` completed
sprints are compared with the ones before it. A procedure under which rework
per task or the share of blocked tasks got clearly worse is reverted, and the
version it replaced comes back; otherwise it is kept.

Every function takes the caller's session and leaves committing to it.
"""

import re
from datetime import UTC, datetime
from typing import Any

from models import BacklogItem, Procedure, Sprint
from models.procedure import ALL_ROLES
from sqlmodel import Session, select

from services.board import awaits_risk_acceptance, rework_request_count

BASELINE_SPRINTS = 2
MEASURE_AFTER_SPRINTS = 2
# How much worse counts as worse, so one unlucky task does not revert a rule.
REWORK_TOLERANCE = 0.25  # extra rework requests per task
BLOCKED_TOLERANCE = 0.10  # extra share of blocked tasks
MAX_PROPOSALS = 2
TITLE_LIMIT = 120
BODY_LIMIT = 2000
PROMPT_LIMIT = 3000
HISTORY_SHOWN = 8
# What a procedure's record can say once it is decided or measured.
FAILED_RESULTS = ("reverted",)

_PROPOSAL = re.compile(
    r"^PROCEDURE\s+role=(?P<role>\S+)\s+title=(?P<title>.+?)\s*$"
    r"(?P<body>.*?)"
    r"^WHY:\s*(?P<why>.+?)\s*$\s*^END\s*$",
    re.MULTILINE | re.DOTALL,
)


# ── Numbers from the board ───────────────────────────────────────────────────


def board_metrics(session: Session, sprint_ids: list[int]) -> dict[str, Any]:
    """Rework requests per task and the share of blocked tasks in *sprint_ids*."""
    items = (
        session.exec(
            select(BacklogItem).where(BacklogItem.sprint_id.in_(sprint_ids))
        ).all()
        if sprint_ids
        else []
    )
    tasks = len(items)
    rework = sum(rework_request_count(item.comments) for item in items)
    # An approved high-risk delivery waiting for a person is not a failure
    # of the procedures in force (services/risk.py).
    blocked = sum(
        1
        for item in items
        if item.status == "blocked" and not awaits_risk_acceptance(item.comments)
    )
    return {
        "sprints": len(sprint_ids),
        "tasks": tasks,
        "rework_per_task": round(rework / tasks, 3) if tasks else 0.0,
        "blocked_rate": round(blocked / tasks, 3) if tasks else 0.0,
    }


def completed_sprint_ids(
    session: Session, company_id: int, after_id: int | None = None
) -> list[int]:
    """The company's completed sprints, oldest first; only later than *after_id* if given."""
    query = select(Sprint.id).where(
        Sprint.company_id == company_id, Sprint.status == "completed"
    )
    if after_id is not None:
        query = query.where(Sprint.id > after_id)
    return list(session.exec(query.order_by(Sprint.id)).all())


# ── Prompts ──────────────────────────────────────────────────────────────────


def active_procedures(
    session: Session, company_id: int, role: str | None
) -> list[Procedure]:
    roles = [ALL_ROLES] + ([role] if role else [])
    return list(
        session.exec(
            select(Procedure)
            .where(
                Procedure.company_id == company_id,
                Procedure.status == "active",
                Procedure.role.in_(roles),
            )
            .order_by(Procedure.id)
        ).all()
    )


def procedures_prompt(procedures: list[Procedure]) -> str:
    if not procedures:
        return ""
    sections = [
        f"### {p.title} (v{p.version}{'' if p.role != ALL_ROLES else ', every role'})\n{p.body}"
        for p in procedures
    ]
    return (
        "\n\n## Company Procedures\n"
        "Rules this company adopted for your role. Follow them.\n\n"
        + "\n\n".join(sections)
    )[:PROMPT_LIMIT]


# ── Proposals ────────────────────────────────────────────────────────────────


def proposal_format(roles: list[str]) -> str:
    """The answer format the ScrumMaster is asked for; ``parse_proposals`` reads it."""
    return (
        "Answer NONE if no procedure would have prevented these problems. Otherwise "
        f"propose at most {MAX_PROPOSALS} procedures, each exactly in this form:\n\n"
        "PROCEDURE role=<one of: "
        + ", ".join([ALL_ROLES, *roles])
        + "> title=<short title>\n"
        "<the rule, as instructions to that role>\n"
        "WHY: <which problem of this sprint it prevents>\n"
        "END"
    )


def parse_proposals(text: str, roles: list[str]) -> list[dict[str, str]]:
    """Proposals in the expected form for a known role; anything else is ignored."""
    allowed = {ALL_ROLES, *roles}
    proposals = []
    for match in _PROPOSAL.finditer(text or ""):
        role = match["role"].strip()
        title = match["title"].strip()[:TITLE_LIMIT]
        body = match["body"].strip()[:BODY_LIMIT]
        if role in allowed and title and body:
            proposals.append(
                {
                    "role": role,
                    "title": title,
                    "body": body,
                    "why": match["why"].strip(),
                }
            )
        if len(proposals) == MAX_PROPOSALS:
            break
    return proposals


def propose(
    session: Session,
    company_id: int,
    proposals: list[dict[str, str]],
    proposed_by: str,
    source_sprint_id: int | None = None,
    skip_failed: bool = False,
) -> list[Procedure]:
    """Record proposals.

    One with the same text as a procedure already active or pending is
    skipped. With *skip_failed* (the ScrumMaster's proposals), so is one the
    board reverted or a person rejected: the same rule again would only
    repeat what was already decided. A person writing a procedure can still
    bring one back.
    """
    created = []
    for proposal in proposals:
        earlier = session.exec(
            select(Procedure).where(
                Procedure.company_id == company_id,
                Procedure.role == proposal["role"],
                Procedure.title == proposal["title"],
            )
        ).all()
        if any(
            p.body == proposal["body"]
            and (p.status in ("active", "proposed") or (skip_failed and _failed(p)))
            for p in earlier
        ):
            continue
        same_title = [p for p in earlier if p.status in ("active", "proposed")]
        current = next((p for p in same_title if p.status == "active"), None)
        procedure = Procedure(
            company_id=company_id,
            role=proposal["role"],
            title=proposal["title"],
            body=proposal["body"],
            rationale=proposal.get("why"),
            proposed_by=proposed_by,
            source_sprint_id=source_sprint_id,
            version=(current.version + 1) if current else 1,
            supersedes_id=current.id if current else None,
        )
        session.add(procedure)
        session.flush()
        created.append(procedure)
    return created


def _failed(procedure: Procedure) -> bool:
    """Reverted by the board's numbers, or rejected by a person."""
    return (
        procedure.status == "rejected"
        or (procedure.outcome or {}).get("result") in FAILED_RESULTS
    )


def history_prompt(session: Session, company_id: int) -> str:
    """The prompt section with what earlier procedures did, newest first, or ''.

    Kept, reverted and unmeasured come with the board's numbers; a rejection
    is a person's decision. Proposals still waiting and procedures no one
    measured yet are left out: they have no result to learn from.
    """
    decided = [
        p
        for p in session.exec(
            select(Procedure)
            .where(Procedure.company_id == company_id)
            .order_by(Procedure.id.desc())
        ).all()
        if p.status == "rejected"
        or (p.outcome or {}).get("result") in ("kept", "reverted", "unmeasured")
    ][:HISTORY_SHOWN]
    if not decided:
        return ""
    lines = [
        f'- "{p.title}" ({p.role}, v{p.version}): '
        + (
            "rejected by a person"
            if p.status == "rejected"
            else f"{p.outcome['result']}, {_numbers(p)}"
        )
        for p in decided
    ]
    return (
        "\n\n## What earlier procedures did\n"
        "Counted from the boards of the sprints before and after adoption.\n"
        + "\n".join(lines)
    )


def _numbers(procedure: Procedure) -> str:
    outcome = procedure.outcome or {}
    baseline = procedure.baseline or {}
    return (
        f"rework per task {baseline.get('rework_per_task', 0)} → {outcome.get('rework_per_task', 0)}, "
        f"blocked {baseline.get('blocked_rate', 0)} → {outcome.get('blocked_rate', 0)}"
    )


# ── Decisions ────────────────────────────────────────────────────────────────


def adopt(session: Session, procedure: Procedure, decided_by: str) -> None:
    """Make *procedure* active, record the numbers to beat, retire what it replaces."""
    now = datetime.now(UTC)
    completed = completed_sprint_ids(session, procedure.company_id)
    procedure.status = "active"
    procedure.decided_by = decided_by
    procedure.decided_at = now
    procedure.baseline = board_metrics(session, completed[-BASELINE_SPRINTS:])
    procedure.adopted_after_sprint_id = completed[-1] if completed else 0
    replaced = session.exec(
        select(Procedure).where(
            Procedure.company_id == procedure.company_id,
            Procedure.role == procedure.role,
            Procedure.title == procedure.title,
            Procedure.status == "active",
            Procedure.id != procedure.id,
        )
    ).all()
    for old in replaced:
        old.status = "retired"
        old.retired_at = now
        old.outcome = {
            **(old.outcome or {}),
            "result": "superseded",
            "by": procedure.id,
        }
        session.add(old)
    session.add(procedure)


def reject(session: Session, procedure: Procedure, decided_by: str) -> None:
    procedure.status = "rejected"
    procedure.decided_by = decided_by
    procedure.decided_at = datetime.now(UTC)
    session.add(procedure)


def retire(session: Session, procedure: Procedure, decided_by: str) -> None:
    procedure.status = "retired"
    procedure.retired_at = datetime.now(UTC)
    procedure.outcome = {
        **(procedure.outcome or {}),
        "result": "retired",
        "by": decided_by,
    }
    session.add(procedure)


# ── Measuring ────────────────────────────────────────────────────────────────


def evaluate(session: Session, company_id: int) -> list[Procedure]:
    """Keep or revert every active procedure with enough sprints after its adoption.

    Returns the procedures that got an outcome in this call.
    """
    decided = []
    pending = session.exec(
        select(Procedure).where(
            Procedure.company_id == company_id,
            Procedure.status == "active",
            Procedure.baseline.is_not(None),
            Procedure.outcome.is_(None),
        )
    ).all()
    for procedure in pending:
        after = completed_sprint_ids(
            session, company_id, procedure.adopted_after_sprint_id or 0
        )
        if len(after) < MEASURE_AFTER_SPRINTS:
            continue
        measured = board_metrics(session, after[:MEASURE_AFTER_SPRINTS])
        baseline = procedure.baseline or {}
        if not baseline.get("tasks") or not measured["tasks"]:
            # Nothing to compare with: neither proven nor disproven.
            procedure.outcome = {**measured, "result": "unmeasured"}
        elif (
            measured["rework_per_task"] > baseline["rework_per_task"] + REWORK_TOLERANCE
            or measured["blocked_rate"] > baseline["blocked_rate"] + BLOCKED_TOLERANCE
        ):
            procedure.outcome = {**measured, "result": "reverted"}
            procedure.status = "retired"
            procedure.retired_at = datetime.now(UTC)
            if procedure.supersedes_id:
                previous = session.get(Procedure, procedure.supersedes_id)
                if previous is not None and previous.status == "retired":
                    previous.status = "active"
                    previous.retired_at = None
                    previous.outcome = {
                        **(previous.outcome or {}),
                        "result": "restored",
                    }
                    session.add(previous)
        else:
            procedure.outcome = {**measured, "result": "kept"}
        session.add(procedure)
        decided.append(procedure)
    return decided


def describe_outcome(procedure: Procedure) -> str:
    """One line for the team: what the numbers said about *procedure*."""
    numbers = _numbers(procedure)
    result = (procedure.outcome or {}).get("result")
    if result == "reverted":
        return f'Procedure "{procedure.title}" ({procedure.role}) is reverted: things got worse ({numbers}).'
    if result == "unmeasured":
        return f'Procedure "{procedure.title}" ({procedure.role}) stays, unmeasured: no sprints to compare with.'
    return f'Procedure "{procedure.title}" ({procedure.role}) is kept ({numbers}).'
