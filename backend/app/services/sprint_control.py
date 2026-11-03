"""Who decides when a sprint's agents work: start, pause, stop, and no credit.

A sprint runs only while its status is ``active`` (or ``needs_split``):

- ``planned``: created but not started. The New company wizard can leave
  Sprint 0 like this, and ``POST /v1/sprints/{id}/start`` dispatches it.
- ``paused``: a Manager paused it, or the worker did because a model provider
  answered that the account has no credit (``pause_reason`` says which). No
  task is dispatched, reviewed or retried until it is resumed.
- ``cancelled``: a Manager stopped it. Nothing runs again and no follow-up
  sprint opens from it.

The worker asks ``is_halted`` before it dispatches, reviews or retries; an
answer already being written when a sprint is paused is still delivered (it
was paid for) and waits in review until the sprint resumes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from models import BacklogItem, OutboxEvent, Sprint
from sqlmodel import Session, select

from services.glassroom import publish_glassroom

PLANNED = "planned"
ACTIVE = "active"
PAUSED = "paused"
CANCELLED = "cancelled"
HALTED_STATUSES = (PLANNED, PAUSED, CANCELLED)
# A company with a sprint in one of these does not get a follow-up sprint
# opened on its own: a paused or planned sprint is still the company's.
OPEN_STATUSES = (ACTIVE, "needs_split", PLANNED, PAUSED)

# The autonomy level at which every approved task waits for a person.
HUMAN_LED_LEVEL = 1
HUMAN_LED_REASON = "autonomy level 1: every approved task waits for a person"

# Words a provider uses when the account has run out of money or quota, as
# opposed to a transient rate limit.
_CREDIT_WORDS = (
    "insufficient balance",
    "insufficient_balance",
    "insufficient_quota",
    "insufficient credit",
    "credit balance",
    "out of credit",
    "exceeded your current quota",
    "quota exceeded",
    "billing",
    "payment required",
    "resource_exhausted",
)


def is_halted(status: str | None) -> bool:
    return status in HALTED_STATUSES


def credit_failure(result: dict[str, Any]) -> str | None:
    """The provider whose account has no credit, when *result* says so.

    A 402 is always a credit answer; a 429 counts only when its message names
    a quota or balance, since a plain 429 is a rate limit that passes.
    """
    if not result.get("error"):
        return None
    detail = result.get("detail") if isinstance(result.get("detail"), dict) else {}
    status = detail.get("status") or result.get("status_code")
    message = " ".join(
        str(part)
        for part in (detail.get("message"), detail.get("error"), result.get("error"))
        if part
    ).lower()
    provider = str(detail.get("provider") or "llm-proxy")
    if status == 402 or "payment required" in message:
        return provider
    if any(word in message for word in _CREDIT_WORDS):
        return provider
    return None


def credit_reason(provider: str) -> str:
    return (
        f"No credit at {provider}: the provider refused the call for lack of "
        "balance or quota. Top up the account, then resume the sprint."
    )


def pause(session: Session, sprint: Sprint, reason: str | None = None) -> bool:
    """Pause *sprint*; ``False`` when it was not running."""
    if sprint.status not in (ACTIVE, "needs_split"):
        return False
    sprint.status = PAUSED
    sprint.pause_reason = reason
    session.add(sprint)
    return True


def pause_for_credit(session: Session, sprint_id: int, provider: str) -> bool:
    sprint = session.get(Sprint, sprint_id)
    if sprint is None:
        return False
    return pause(session, sprint, credit_reason(provider))


def pause_task_for_credit(
    engine: Any, item_id: int, sprint_id: int, provider: str
) -> None:
    """The worker's answer to a task whose call found no credit.

    The sprint pauses (once, with the reason) and the task goes back to
    ``todo`` with a note, so resuming the sprint runs it again; it is not
    blocked, which would leave it for a person or close the sprint.
    """
    with Session(engine) as session:
        pause_for_credit(session, sprint_id, provider)
        item = session.get(BacklogItem, item_id)
        if item is not None:
            item.status = "todo"
            item.comments = [
                *(item.comments or []),
                {
                    "author": "System",
                    "text": f"Paused: {credit_reason(provider)}",
                    "created_at": datetime.now(UTC).isoformat(),
                },
            ]
            item.updated_at = datetime.now(UTC)
            session.add(item)
        session.commit()


async def publish_credit_pause(nats_client: Any, sprint_id: int, provider: str) -> None:
    await publish_glassroom(
        nats_client,
        sprint_id,
        {
            "type": "error",
            "semantic_type": "sprint.paused_no_credit",
            "source": "task_worker",
            "task_status": PAUSED,
            "message": f"⏸ {credit_reason(provider)}",
        },
    )


def dispatch_todo(session: Session, sprint: Sprint) -> int:
    """Queue every ``todo`` item of *sprint* on ``task.assign``; the count."""
    items = session.exec(
        select(BacklogItem).where(
            BacklogItem.sprint_id == sprint.id, BacklogItem.status == "todo"
        )
    ).all()
    for item in items:
        session.add(
            OutboxEvent(
                aggregate_type="backlog_item",
                aggregate_id=str(item.id),
                event_type="nats_publish",
                payload={
                    "subject": "task.assign",
                    "message": {
                        "backlog_item_id": item.id,
                        "interaction_id": str(uuid4()),
                        "agent": item.assignee or "PO",
                        "sprint_id": sprint.id,
                    },
                },
            )
        )
    return len(items)


def stop(session: Session, sprint: Sprint) -> int:
    """Cancel *sprint*: unfinished tasks are blocked with a note; the count."""
    sprint.status = CANCELLED
    sprint.pause_reason = None
    session.add(sprint)
    items = session.exec(
        select(BacklogItem).where(
            BacklogItem.sprint_id == sprint.id,
            BacklogItem.status.in_(("todo", "in_progress", "in_review")),  # type: ignore[attr-defined]
        )
    ).all()
    now = datetime.now(UTC)
    for item in items:
        item.status = "blocked"
        item.comments = [
            *(item.comments or []),
            {
                "author": "System",
                "text": "Stopped: a Manager stopped the sprint; nothing more runs on it.",
                "created_at": now.isoformat(),
            },
        ]
        item.updated_at = now
        session.add(item)
    return len(items)


def needs_person_acceptance(autonomy_level: int | None) -> bool:
    """At the human-led level, an approved task waits for a person to accept it."""
    return (autonomy_level or 2) <= HUMAN_LED_LEVEL
