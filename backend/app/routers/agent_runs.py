from datetime import datetime

from auth_policy import current_user_if_required, require_company_role
from database import get_session
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from logging_config import logger
from models import User
from models.agent_run import (
    IN_HOUSE_PRODUCERS,
    AgentRun,
    AgentRunApproval,
    Verification,
)
from schemas import AgentRunApprovalRequest, AgentRunCreate, AgentRunVerificationRequest
from services.agent_run_service import ArtifactTooLargeError, ingest_agent_run
from services.agent_service import AgentService
from services.reviewer_agent import track_record as reviewer_track_record
from services.verification import verify_agent_run
from sqlalchemy import String, cast
from sqlmodel import Session, select

router = APIRouter(prefix="/v1/agent_runs", tags=["Agent Runs"])


def _subject_sprint_id_equals(sprint_id: int):
    """
    SQL condition: ``subject.sprint_id`` is the JSON number ``sprint_id``.

    Filtering in SQL keeps ``limit`` exact (a Python filter after the query
    would have to over-fetch an unbounded number of rows). Casting the JSON
    element to a string is portable: SQLAlchemy renders
    ``CAST(subject -> 'sprint_id' AS VARCHAR)`` on Postgres and
    ``CAST(JSON_QUOTE(JSON_EXTRACT(subject, '$."sprint_id"')) AS VARCHAR)`` on
    SQLite, and both yield the element's JSON text — ``7`` for the number,
    ``"7"`` for a string. Matching the JSON text means a malformed caller-
    supplied ``subject`` can never make the query fail, as an integer cast
    would on Postgres, and keeps the comparison type-strict on both engines.
    """
    return cast(AgentRun.subject["sprint_id"], String) == str(sprint_id)


@router.post("")
def create_agent_run(
    payload: AgentRunCreate,
    session: Session = Depends(get_session),  # noqa: B008 - FastAPI dependency marker.
    user: User | None = Depends(current_user_if_required),  # noqa: B008 - FastAPI dependency marker.
):
    require_company_role(session, user, payload.company_id, "Manager")
    if "artifact_digest" in (payload.model_extra or {}):
        logger.warning(
            "artifact_digest supplied by caller is ignored; digests are computed server-side (company_id=%s external_ref=%s)",
            payload.company_id,
            payload.external_ref,
        )
    try:
        run, created = ingest_agent_run(session, payload)
    except ArtifactTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc

    response = jsonable_encoder(run)
    response["created"] = created
    return JSONResponse(status_code=201 if created else 200, content=response)


@router.get("")
def list_agent_runs(
    company_id: int = Query(...),
    producer: str | None = None,
    status: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    external_ref: str | None = None,
    sprint_id: int | None = None,
    exclude_in_house: bool = False,
    limit: int = Query(50, ge=1, le=500),
    session: Session = Depends(get_session),  # noqa: B008 - FastAPI dependency marker.
    user: User | None = Depends(current_user_if_required),  # noqa: B008 - FastAPI dependency marker.
):
    require_company_role(session, user, company_id, "Viewer")
    statement = select(AgentRun).where(AgentRun.company_id == company_id)
    if producer is not None:
        statement = statement.where(AgentRun.producer == producer)
    if status is not None:
        statement = statement.where(AgentRun.status == status)
    if external_ref is not None:
        statement = statement.where(AgentRun.external_ref == external_ref)
    if sprint_id is not None:
        statement = statement.where(_subject_sprint_id_equals(sprint_id))
    if exclude_in_house:
        # The company's own runs, which the review loop decides (see the inbox).
        statement = statement.where(AgentRun.producer.not_in(IN_HOUSE_PRODUCERS))
    if since is not None:
        statement = statement.where(AgentRun.ingested_at >= since)
    if until is not None:
        statement = statement.where(AgentRun.ingested_at <= until)

    runs = session.exec(
        statement.order_by(AgentRun.ingested_at.desc(), AgentRun.id.desc()).limit(limit)
    ).all()
    latest_approvals = {}
    if runs:
        approvals = session.exec(
            select(AgentRunApproval)
            .where(
                AgentRunApproval.company_id == company_id,
                AgentRunApproval.agent_run_id.in_([run.id for run in runs]),
            )
            .order_by(AgentRunApproval.decided_at.desc(), AgentRunApproval.id.desc())
        ).all()
        for approval in approvals:
            latest_approvals.setdefault(approval.agent_run_id, approval)

    items = []
    for run in runs:
        item = run.model_dump(exclude={"artifact_text"})
        approval = latest_approvals.get(run.id)
        item["latest_approval"] = (
            approval.model_dump(
                include={"decision", "feedback", "approver_name", "decided_at"}
            )
            if approval
            else None
        )
        items.append(item)
    return {"agent_runs": items}


@router.get("/reviewer_record")
def reviewer_record(
    company_id: int = Query(...),
    session: Session = Depends(get_session),  # noqa: B008 - FastAPI dependency marker.
    user: User | None = Depends(current_user_if_required),  # noqa: B008 - FastAPI dependency marker.
):
    """How the Reviewer agent's suggestions compared with the decisions people recorded."""
    require_company_role(session, user, company_id, "Viewer")
    return reviewer_track_record(session, company_id)


@router.get("/{run_id}")
def get_agent_run(
    run_id: int,
    company_id: int = Query(...),
    session: Session = Depends(get_session),  # noqa: B008 - FastAPI dependency marker.
    user: User | None = Depends(current_user_if_required),  # noqa: B008 - FastAPI dependency marker.
):
    require_company_role(session, user, company_id, "Viewer")
    run = session.exec(
        select(AgentRun).where(
            AgentRun.id == run_id,
            AgentRun.company_id == company_id,
        )
    ).first()
    if run is None:
        raise HTTPException(status_code=404, detail="Agent run not found")
    return run


@router.post("/{run_id}/verify", status_code=201)
def verify_run(
    run_id: int,
    payload: AgentRunVerificationRequest,
    session: Session = Depends(get_session),  # noqa: B008 - FastAPI dependency marker.
    user: User | None = Depends(current_user_if_required),  # noqa: B008 - FastAPI dependency marker.
):
    require_company_role(session, user, payload.company_id, "Manager")
    run = session.exec(
        select(AgentRun).where(
            AgentRun.id == run_id,
            AgentRun.company_id == payload.company_id,
        )
    ).first()
    if run is None:
        raise HTTPException(status_code=404, detail="Agent run not found")
    return verify_agent_run(session, run, payload.evidence)


@router.get("/{run_id}/verifications")
def list_run_verifications(
    run_id: int,
    company_id: int = Query(...),
    session: Session = Depends(get_session),  # noqa: B008 - FastAPI dependency marker.
    user: User | None = Depends(current_user_if_required),  # noqa: B008 - FastAPI dependency marker.
):
    require_company_role(session, user, company_id, "Viewer")
    run = session.exec(
        select(AgentRun).where(
            AgentRun.id == run_id,
            AgentRun.company_id == company_id,
        )
    ).first()
    if run is None:
        raise HTTPException(status_code=404, detail="Agent run not found")

    verifications = session.exec(
        select(Verification)
        .where(
            Verification.agent_run_id == run_id,
            Verification.company_id == company_id,
        )
        .order_by(Verification.observed_at, Verification.id)
    ).all()
    return {"verifications": verifications}


@router.post("/{run_id}/approve", status_code=201)
def approve_run(
    run_id: int,
    payload: AgentRunApprovalRequest,
    session: Session = Depends(get_session),  # noqa: B008 - FastAPI dependency marker.
    user: User | None = Depends(current_user_if_required),  # noqa: B008 - FastAPI dependency marker.
):
    require_company_role(session, user, payload.company_id, "Manager")
    run = session.exec(
        select(AgentRun).where(
            AgentRun.id == run_id,
            AgentRun.company_id == payload.company_id,
        )
    ).first()
    if run is None:
        raise HTTPException(status_code=404, detail="Agent run not found")

    approval = AgentRunApproval(agent_run_id=run.id, **payload.model_dump())
    session.add(approval)
    audit_log = AgentService().audit_interaction(
        session=session,
        company_id=run.company_id,
        interaction_id=f"agent-run:{run.external_ref}",
        agent_id=f"human:{approval.approver_name}",
        action=f"agent_run_{approval.decision}",
        details={
            "company_id": str(run.company_id),
            "agent_run_id": run.id,
            "version": run.version,
            "rejection_category": approval.rejection_category,
        },
        result={"decision": approval.decision, "feedback": approval.feedback},
        decision_signature=None,
        cost_tokens=0,
    )
    approval.audit_log_id = audit_log.id
    session.add(approval)
    session.commit()
    session.refresh(approval)
    return approval


@router.get("/{run_id}/approvals")
def list_run_approvals(
    run_id: int,
    company_id: int = Query(...),
    session: Session = Depends(get_session),  # noqa: B008 - FastAPI dependency marker.
    user: User | None = Depends(current_user_if_required),  # noqa: B008 - FastAPI dependency marker.
):
    require_company_role(session, user, company_id, "Viewer")
    run = session.exec(
        select(AgentRun).where(
            AgentRun.id == run_id,
            AgentRun.company_id == company_id,
        )
    ).first()
    if run is None:
        raise HTTPException(status_code=404, detail="Agent run not found")

    approvals = session.exec(
        select(AgentRunApproval)
        .where(
            AgentRunApproval.agent_run_id == run_id,
            AgentRunApproval.company_id == company_id,
        )
        .order_by(AgentRunApproval.decided_at, AgentRunApproval.id)
    ).all()
    return {"approvals": approvals}
