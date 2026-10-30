"""
Carrying a blocked task into the next sprint.

A task the agents gave up on waits for a person. One way a person (or, at
autonomy level 3, the company itself) answers is to give it another attempt
in the next sprint: a fresh task with the same brief plus what blocked the
previous one, so the agent does not repeat it blind. The original stays on
its board, marked as carried over, and leaves the person's inbox.

A task is carried over at most once on the company's own initiative; one
that blocks again stays for a person. The ScrumMaster's triage of the block
(``services.scrum_master``) is honoured: a task it left for a person is not
carried on the company's own, and its brief for the next attempt travels
with the new task into the agent's prompt.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from models import AgentMessage, BacklogItem, OutboxEvent, Sprint
from sqlmodel import Session, select

from services import scrum_master
from services.board import (
    CARRIED_FROM_PREFIX,
    CARRIED_TO_PREFIX,
    SCRUM_MASTER_ROLE,
    awaits_risk_acceptance,
    block_reason,
    blocked_item_next_step,
    comment_list,
)

REASON_LIMIT = 500


class CarryOverError(ValueError):
    """The task cannot be carried over; ``status`` says why (404 or 409)."""

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def waits_for_a_person(item: BacklogItem) -> bool:
    """Blocked, and nothing the worker does on its own will move it."""
    return item.status == "blocked" and blocked_item_next_step(
        item.comments, item.assignee
    ) in (None, "frozen")


def carried_over(item: BacklogItem) -> bool:
    """Already given to another sprint: it no longer waits for a person."""
    return any(
        str(c.get("text", "")).startswith(CARRIED_TO_PREFIX)
        for c in comment_list(item.comments)
    )


def is_carry_over(item: BacklogItem) -> bool:
    """This task is itself a second attempt at an earlier one."""
    return any(
        str(c.get("text", "")).startswith(CARRIED_FROM_PREFIX)
        for c in comment_list(item.comments)
    )


def left_for_a_person(session: Session, item: BacklogItem) -> bool:
    """The ScrumMaster's triage said a person must decide, not another attempt."""
    return _left_for_a_person(scrum_master.triages_for(session, [item]).get(item.id))


def _left_for_a_person(triage: dict[str, Any] | None) -> bool:
    return bool(triage) and triage["decision"] == scrum_master.DECISION_PERSON


def carry_over(
    session: Session,
    company_id: int,
    item_ids: list[int],
    new_sprint: Sprint,
    by: str,
    by_role: str,
) -> list[BacklogItem]:
    """Clone each blocked task of *company_id* into *new_sprint*, queued for an agent.

    Raises ``CarryOverError`` (404 unknown or another company's task, 409 not
    waiting for a person or already carried over) before writing anything.
    The caller commits.
    """
    originals: list[tuple[BacklogItem, Sprint]] = []
    for item_id in dict.fromkeys(item_ids):
        row = session.exec(
            select(BacklogItem, Sprint)
            .join(Sprint, Sprint.id == BacklogItem.sprint_id)
            .where(BacklogItem.id == item_id, Sprint.company_id == company_id)
        ).first()
        if row is None:
            raise CarryOverError(404, f"Task {item_id} not found in this company")
        item, sprint = row
        if not waits_for_a_person(item):
            raise CarryOverError(
                409, f"Task {item_id} is not blocked waiting for a person"
            )
        if carried_over(item):
            raise CarryOverError(409, f"Task {item_id} was already carried over")
        originals.append((item, sprint))

    now = datetime.now(UTC)
    created: list[BacklogItem] = []
    triages = scrum_master.triages_for(session, [item for item, _ in originals])
    for item, sprint in originals:
        reason = block_reason(item.comments)[:REASON_LIMIT]
        brief = (triages.get(item.id) or {}).get("brief") or ""
        clone = BacklogItem(
            sprint_id=new_sprint.id,
            title=item.title,
            description=item.description or "",
            priority=item.priority,
            assignee=item.assignee,
            status="todo",
            comments=[
                {
                    "author": "System",
                    "text": (
                        f'{CARRIED_FROM_PREFIX} task {item.id} ("{sprint.sprint_name}"), '
                        f"which was blocked: {reason or 'no reason recorded'}"
                        + (f"\n{scrum_master.BRIEF_PREFIX}{brief}" if brief else "")
                    ),
                    "created_at": now.isoformat(),
                }
            ],
        )
        session.add(clone)
        session.flush()
        created.append(clone)

        item.comments = [
            *comment_list(item.comments),
            {
                "author": "System",
                "text": f'{CARRIED_TO_PREFIX} {new_sprint.id} ("{new_sprint.sprint_name}") as task {clone.id} by {by}.',
                "created_at": now.isoformat(),
            },
        ]
        item.updated_at = now
        session.add(item)

        session.add(
            OutboxEvent(
                aggregate_type="backlog_item",
                aggregate_id=str(clone.id),
                event_type="nats_publish",
                payload={
                    "subject": "task.assign",
                    "message": {
                        "backlog_item_id": clone.id,
                        "interaction_id": str(uuid4()),
                        "agent": clone.assignee or "PO",
                        "sprint_id": new_sprint.id,
                    },
                },
            )
        )
        session.add(
            AgentMessage(
                company_id=company_id,
                sprint_id=new_sprint.id,
                backlog_item_id=clone.id,
                from_name=by,
                from_role=by_role,
                to_role=clone.assignee,
                kind="decision",
                body=(
                    f'"{item.title}" gets another attempt in sprint "{new_sprint.sprint_name}". '
                    f"Last time it was blocked: {reason or 'no reason recorded'}"
                    + (f"\n{scrum_master.BRIEF_PREFIX}{brief}" if brief else "")
                ),
            )
        )
    return created


def previous_attempt_context(item: dict[str, Any] | BacklogItem) -> str:
    """The prompt section telling an agent what blocked the earlier attempt, or ''."""
    comments = item.get("comments") if isinstance(item, dict) else item.comments
    for comment in comment_list(comments):
        text = str(comment.get("text", ""))
        if text.startswith(CARRIED_FROM_PREFIX):
            return (
                "\n\n## Previous attempt\n"
                "This task was tried in an earlier sprint and blocked. Do not repeat "
                f"what blocked it.\n{text}"
            )
    return ""


def carry_over_on_the_companys_own(
    session: Session,
    company_id: int,
    closed_sprint_id: int,
    new_sprint: Sprint,
    room: int,
) -> list[BacklogItem]:
    """At sprint close with autonomy 3: give each blocked task one more attempt.

    Tasks that were already a second attempt, and tasks the ScrumMaster's
    triage left for a person, stay for a person. At most *room* tasks, oldest
    first, so the next sprint keeps within its scope.
    """
    if room <= 0:
        return []
    candidates = session.exec(
        select(BacklogItem)
        .where(
            BacklogItem.sprint_id == closed_sprint_id, BacklogItem.status == "blocked"
        )
        .order_by(BacklogItem.id)
    ).all()
    triages = scrum_master.triages_for(session, list(candidates))
    ids = [
        item.id
        for item in candidates
        if waits_for_a_person(item)
        and not carried_over(item)
        and not is_carry_over(item)
        and not _left_for_a_person(triages.get(item.id))
        # Approved, waiting for a person to accept it: not another attempt.
        and not awaits_risk_acceptance(item.comments)
    ][:room]
    if not ids:
        return []
    return carry_over(
        session, company_id, ids, new_sprint, SCRUM_MASTER_ROLE, SCRUM_MASTER_ROLE
    )
