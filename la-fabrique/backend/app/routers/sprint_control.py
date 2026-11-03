"""
Sprint control router — who decides when a sprint's agents work.

Endpoints (Manager):
- ``POST /v1/sprints/{id}/dispatch`` — queue the sprint's ``todo`` tasks again.
- ``POST /v1/sprints/{id}/start``    — start a ``planned`` sprint.
- ``POST /v1/sprints/{id}/pause``    — pause: nothing is dispatched, reviewed or retried.
- ``POST /v1/sprints/{id}/resume``   — resume a paused sprint (also one the worker
  paused for lack of credit) and dispatch its waiting tasks.
- ``POST /v1/sprints/{id}/stop``     — stop for good; no follow-up sprint opens.
- ``GET/PUT /v1/companies/{id}/autonomy`` — read (Viewer) or change the autonomy level.

The states and what they allow are in ``services/sprint_control.py``.
"""

from auth_policy import current_user_if_required, require_company_role
from database import get_session
from fastapi import APIRouter, Depends, HTTPException
from logging_config import logger
from models import Company, Sprint, User
from pydantic import BaseModel, Field
from services import sprint_control
from sqlmodel import Session

router = APIRouter(prefix="/v1", tags=["Core"])


@router.post("/sprints/{sprint_id}/dispatch")
async def dispatch_sprint_tasks(
    sprint_id: int,
    session: Session = Depends(get_session),  # noqa: B008 - FastAPI dependency marker.
    user: User | None = Depends(current_user_if_required),  # noqa: B008 - FastAPI dependency marker.
):
    """
    Dispatch all ``todo`` backlog items in a sprint to their assigned agents.

    Creates an ``OutboxEvent`` for each eligible item.  The background worker
    publishes these to NATS as ``task.assign`` messages and the task worker
    picks them up.  Items already dispatched (non-todo status) are skipped.
    """
    sprint = session.get(Sprint, sprint_id)
    if not sprint:
        raise HTTPException(status_code=404, detail="Sprint not found")

    require_company_role(session, user, sprint.company_id, "Manager")
    if sprint_control.is_halted(sprint.status):
        raise HTTPException(status_code=409, detail=f"Sprint is {sprint.status}")
    dispatched = sprint_control.dispatch_todo(session, sprint)
    session.commit()
    if not dispatched:
        return {"dispatched": 0, "message": "No todo items to dispatch"}
    logger.info("Dispatched %d tasks for sprint %d", dispatched, sprint_id)
    return {"dispatched": dispatched, "sprint_id": sprint_id}


def _managed_sprint(session: Session, sprint_id: int, user: User | None) -> Sprint:
    sprint = session.get(Sprint, sprint_id)
    if not sprint:
        raise HTTPException(status_code=404, detail="Sprint not found")
    require_company_role(session, user, sprint.company_id, "Manager")
    return sprint


@router.post("/sprints/{sprint_id}/start")
async def start_planned_sprint(
    sprint_id: int,
    session: Session = Depends(get_session),  # noqa: B008 - FastAPI dependency marker.
    user: User | None = Depends(current_user_if_required),  # noqa: B008 - FastAPI dependency marker.
):
    """Start a ``planned`` sprint: it becomes active and its tasks are dispatched."""
    sprint = _managed_sprint(session, sprint_id, user)
    if sprint.status != sprint_control.PLANNED:
        raise HTTPException(
            status_code=409,
            detail=f"Only a planned sprint can start; this one is {sprint.status}",
        )
    sprint.status = sprint_control.ACTIVE
    session.add(sprint)
    dispatched = sprint_control.dispatch_todo(session, sprint)
    session.commit()
    return {"status": sprint.status, "dispatched": dispatched}


@router.post("/sprints/{sprint_id}/stop")
async def stop_sprint(
    sprint_id: int,
    session: Session = Depends(get_session),  # noqa: B008 - FastAPI dependency marker.
    user: User | None = Depends(current_user_if_required),  # noqa: B008 - FastAPI dependency marker.
):
    """Stop a sprint for good: unfinished tasks are blocked and no follow-up opens."""
    sprint = _managed_sprint(session, sprint_id, user)
    if sprint.status in ("completed", sprint_control.CANCELLED):
        raise HTTPException(
            status_code=409, detail=f"Sprint is already {sprint.status}"
        )
    stopped = sprint_control.stop(session, sprint)
    session.commit()
    return {"status": sprint.status, "stopped_tasks": stopped}


@router.post("/sprints/{sprint_id}/pause")
async def pause_sprint(
    sprint_id: int,
    session: Session = Depends(get_session),  # noqa: B008 - FastAPI dependency marker.
    user: User | None = Depends(current_user_if_required),  # noqa: B008 - FastAPI dependency marker.
):
    """Pause a running sprint: nothing is dispatched, reviewed or retried."""
    sprint = _managed_sprint(session, sprint_id, user)
    if sprint.status == sprint_control.PAUSED:
        return {"status": "already_paused"}
    if not sprint_control.pause(session, sprint):
        raise HTTPException(status_code=409, detail=f"Sprint is {sprint.status}")
    session.commit()
    return {"status": "paused"}


@router.post("/sprints/{sprint_id}/resume")
async def resume_sprint(
    sprint_id: int,
    session: Session = Depends(get_session),  # noqa: B008 - FastAPI dependency marker.
    user: User | None = Depends(current_user_if_required),  # noqa: B008 - FastAPI dependency marker.
):
    """Resume a paused sprint; its waiting tasks are dispatched again."""
    sprint = _managed_sprint(session, sprint_id, user)
    if sprint.status != sprint_control.PAUSED:
        return {"status": sprint.status}
    sprint.status = sprint_control.ACTIVE
    sprint.pause_reason = None
    session.add(sprint)
    dispatched = sprint_control.dispatch_todo(session, sprint)
    session.commit()
    return {"status": "active", "dispatched": dispatched}


class AutonomyRequest(BaseModel):
    autonomy_level: int = Field(ge=1, le=3)


@router.get("/companies/{company_id}/autonomy")
async def get_autonomy(
    company_id: int,
    session: Session = Depends(get_session),  # noqa: B008 - FastAPI dependency marker.
    user: User | None = Depends(current_user_if_required),  # noqa: B008 - FastAPI dependency marker.
):
    """The company's autonomy level (Viewer)."""
    require_company_role(session, user, company_id, "Viewer")
    company = session.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")
    return {"company_id": company_id, "autonomy_level": company.autonomy_level}


@router.put("/companies/{company_id}/autonomy")
async def set_autonomy(
    company_id: int,
    req: AutonomyRequest,
    session: Session = Depends(get_session),  # noqa: B008 - FastAPI dependency marker.
    user: User | None = Depends(current_user_if_required),  # noqa: B008 - FastAPI dependency marker.
):
    """Change the company's autonomy level (Manager).

    1: every approved task waits for a person and Sprint 0 never starts on
    its own; 2: only high-risk deliveries wait; 3: also follow-up sprints and
    procedure adoption run on the company's own.
    """
    require_company_role(session, user, company_id, "Manager")
    company = session.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")
    company.autonomy_level = req.autonomy_level
    session.add(company)
    session.commit()
    return {"company_id": company_id, "autonomy_level": company.autonomy_level}
