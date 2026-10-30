"""
Messages router — the conversation between the company's agents.

Endpoints:
- ``GET /v1/messages`` — the company's messages, optionally for one sprint, one
  task or one kind, oldest first.

Messages are what roles said to each other (claims). What happened to a task
is in the board and its AgentRun evidence.
"""

from auth_policy import current_user_if_required, require_company_role
from database import get_session
from fastapi import APIRouter, Depends, HTTPException, Query
from models import AgentMessage, BacklogItem, User
from models.agent_message import MESSAGE_KINDS
from sqlmodel import Session, select

router = APIRouter(prefix="/v1", tags=["Agents"])


@router.get("/messages")
async def list_messages(
    company_id: int,
    sprint_id: int | None = None,
    backlog_item_id: int | None = None,
    kind: str | None = None,
    limit: int = Query(200, ge=1, le=500),
    session: Session = Depends(get_session),  # noqa: B008 - FastAPI dependency marker.
    user: User | None = Depends(current_user_if_required),  # noqa: B008 - FastAPI dependency marker.
):
    """The latest *limit* messages of the company matching the filters, oldest first."""
    require_company_role(session, user, company_id, "Viewer")
    if kind is not None and kind not in MESSAGE_KINDS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown kind. Use one of: {', '.join(MESSAGE_KINDS)}",
        )
    query = (
        select(AgentMessage, BacklogItem.title)
        .join(BacklogItem, BacklogItem.id == AgentMessage.backlog_item_id, isouter=True)
        .where(AgentMessage.company_id == company_id)
    )
    if sprint_id is not None:
        query = query.where(AgentMessage.sprint_id == sprint_id)
    if backlog_item_id is not None:
        query = query.where(AgentMessage.backlog_item_id == backlog_item_id)
    if kind is not None:
        query = query.where(AgentMessage.kind == kind)
    rows = session.exec(
        query.order_by(AgentMessage.created_at.desc(), AgentMessage.id.desc()).limit(
            limit
        )
    ).all()
    return {
        "messages": [
            {
                "id": message.id,
                "sprint_id": message.sprint_id,
                "backlog_item_id": message.backlog_item_id,
                "task_title": title,
                "from_name": message.from_name,
                "from_role": message.from_role,
                "to_role": message.to_role,
                "kind": message.kind,
                "body": message.body,
                "created_at": message.created_at.isoformat()
                if message.created_at
                else None,
            }
            for message, title in reversed(rows)
        ]
    }
