"""
Procedures router — the rules each role follows.

Endpoints:
- ``GET  /v1/procedures``                 — the company's procedures (Viewer).
- ``POST /v1/procedures``                 — write and adopt a procedure (Manager).
- ``POST /v1/procedures/{id}/adopt``      — adopt a proposal (Manager).
- ``POST /v1/procedures/{id}/reject``     — reject a proposal (Manager).
- ``POST /v1/procedures/{id}/retire``     — retire an active procedure (Manager).

Adopting records the board's numbers before the procedure; the task worker
keeps or reverts it from the numbers after (``services.procedures``).
"""

from auth_policy import current_user_if_required, require_company_role
from database import get_session
from fastapi import APIRouter, Depends, HTTPException
from models import Procedure, User
from models.procedure import PROCEDURE_STATUSES
from pydantic import BaseModel, Field
from services import procedures
from sqlmodel import Session, select

router = APIRouter(prefix="/v1", tags=["Agents"])


class ProcedureCreateRequest(BaseModel):
    company_id: int
    role: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=procedures.TITLE_LIMIT)
    body: str = Field(min_length=1, max_length=procedures.BODY_LIMIT)


def _serialize(procedure: Procedure) -> dict:
    return {
        "id": procedure.id,
        "role": procedure.role,
        "title": procedure.title,
        "body": procedure.body,
        "status": procedure.status,
        "version": procedure.version,
        "supersedes_id": procedure.supersedes_id,
        "proposed_by": procedure.proposed_by,
        "rationale": procedure.rationale,
        "source_sprint_id": procedure.source_sprint_id,
        "baseline": procedure.baseline,
        "outcome": procedure.outcome,
        "decided_by": procedure.decided_by,
        "created_at": procedure.created_at.isoformat()
        if procedure.created_at
        else None,
        "decided_at": procedure.decided_at.isoformat()
        if procedure.decided_at
        else None,
        "retired_at": procedure.retired_at.isoformat()
        if procedure.retired_at
        else None,
    }


def _actor(user: User | None) -> str:
    return user.email if user is not None else "local demo"


@router.get("/procedures")
async def list_procedures(
    company_id: int,
    status: str | None = None,
    session: Session = Depends(get_session),  # noqa: B008 - FastAPI dependency marker.
    user: User | None = Depends(current_user_if_required),  # noqa: B008 - FastAPI dependency marker.
):
    """The company's procedures, newest first."""
    require_company_role(session, user, company_id, "Viewer")
    if status is not None and status not in PROCEDURE_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown status. Use one of: {', '.join(PROCEDURE_STATUSES)}",
        )
    query = select(Procedure).where(Procedure.company_id == company_id)
    if status is not None:
        query = query.where(Procedure.status == status)
    rows = session.exec(query.order_by(Procedure.id.desc())).all()
    return {"procedures": [_serialize(p) for p in rows]}


@router.post("/procedures", status_code=201)
async def create_procedure(
    req: ProcedureCreateRequest,
    session: Session = Depends(get_session),  # noqa: B008 - FastAPI dependency marker.
    user: User | None = Depends(current_user_if_required),  # noqa: B008 - FastAPI dependency marker.
):
    """A person writes a procedure; it is adopted at once and measured like any other."""
    require_company_role(session, user, req.company_id, "Manager")
    created = procedures.propose(
        session,
        req.company_id,
        [
            {
                "role": req.role.strip(),
                "title": req.title.strip(),
                "body": req.body.strip(),
            }
        ],
        _actor(user),
    )
    if not created:
        raise HTTPException(
            status_code=409, detail="That procedure is already active or proposed."
        )
    procedures.adopt(session, created[0], _actor(user))
    session.commit()
    session.refresh(created[0])
    return _serialize(created[0])


def _decide(
    session: Session, user: User | None, procedure_id: int, expected: str
) -> Procedure:
    procedure = session.get(Procedure, procedure_id)
    if procedure is None:
        raise HTTPException(status_code=404, detail="Procedure not found")
    require_company_role(session, user, procedure.company_id, "Manager")
    if procedure.status != expected:
        raise HTTPException(
            status_code=409,
            detail=f"The procedure is {procedure.status}, not {expected}.",
        )
    return procedure


@router.post("/procedures/{procedure_id}/adopt")
async def adopt_procedure(
    procedure_id: int,
    session: Session = Depends(get_session),  # noqa: B008 - FastAPI dependency marker.
    user: User | None = Depends(current_user_if_required),  # noqa: B008 - FastAPI dependency marker.
):
    procedure = _decide(session, user, procedure_id, "proposed")
    procedures.adopt(session, procedure, _actor(user))
    session.commit()
    session.refresh(procedure)
    return _serialize(procedure)


@router.post("/procedures/{procedure_id}/reject")
async def reject_procedure(
    procedure_id: int,
    session: Session = Depends(get_session),  # noqa: B008 - FastAPI dependency marker.
    user: User | None = Depends(current_user_if_required),  # noqa: B008 - FastAPI dependency marker.
):
    procedure = _decide(session, user, procedure_id, "proposed")
    procedures.reject(session, procedure, _actor(user))
    session.commit()
    session.refresh(procedure)
    return _serialize(procedure)


@router.post("/procedures/{procedure_id}/retire")
async def retire_procedure(
    procedure_id: int,
    session: Session = Depends(get_session),  # noqa: B008 - FastAPI dependency marker.
    user: User | None = Depends(current_user_if_required),  # noqa: B008 - FastAPI dependency marker.
):
    procedure = _decide(session, user, procedure_id, "active")
    procedures.retire(session, procedure, _actor(user))
    session.commit()
    session.refresh(procedure)
    return _serialize(procedure)
