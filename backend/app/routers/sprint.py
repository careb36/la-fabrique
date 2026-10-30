"""
Sprint router — Kanban board management and backlog item lifecycle.

Endpoints:
- ``POST /v1/start_sprint``          — create a sprint with initial backlog items.
- ``GET  /v1/sprints``               — list a company's sprints with progress counts.
- ``GET  /v1/sprints/{id}/board``    — retrieve sprint metadata and Kanban columns.
- ``PATCH /v1/backlog/{item_id}``    — update status, priority, assignee, or add a comment.

New backlog items are dispatched to agents via the transactional outbox:
an ``OutboxEvent`` row is inserted atomically in the same DB transaction and
delivered to NATS by the ``process_outbox`` background worker.
"""

from datetime import UTC, datetime
from uuid import uuid4

from auth_policy import current_user_if_required, require_company_role
from auth_tokens import STREAM_TICKET_MINUTES, create_stream_ticket
from database import get_session
from fastapi import APIRouter, Depends, HTTPException
from logging_config import logger
from models import (
    Agent,
    BacklogItem,
    BusinessUnit,
    Company,
    OutboxEvent,
    ProjectDiscovery,
    Sprint,
    User,
)
from schemas import (
    SCOPE_HARD_MAX,
    SCOPE_LIMITS,
    BacklogItemUpdate,
    SelfImprovementSprintRequest,
    SprintPlanRequest,
    SprintStartRequest,
)
from services.board import (
    count_architect_advice,
    count_console_advice,
    count_second_attempt,
    no_architect_advice,
    no_console_advice,
    no_second_attempts,
    rework_request_count,
)
from services.carry_over import CarryOverError, carry_over
from services.sprint_planner import (
    build_self_improvement_objective,
    plan_execution_sprint,
)
from services.sprint_planner import (
    plan_self_improvement_sprint as build_self_improvement_plan,
)
from sqlalchemy import case, func
from sqlmodel import Session, select, text

router = APIRouter(prefix="/v1", tags=["Core"])

# Allowed values for validation; rejected values return HTTP 422.
VALID_STATUSES = {"todo", "in_progress", "in_review", "done", "blocked"}
VALID_PRIORITIES = {"low", "medium", "high", "critical"}


def _load_planning_context(session: Session, company_id: int):
    company = session.get(Company, company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    agents = session.exec(select(Agent).where(Agent.company_id == company_id)).all()
    agent_dicts = [
        {
            "role": agent.role,
            "name": agent.name,
            "model": agent.model,
            "seniority": agent.seniority,
            "specialty": agent.specialty,
        }
        for agent in agents
    ]

    discovery = session.exec(
        select(ProjectDiscovery)
        .where(ProjectDiscovery.company_id == company_id)
        .order_by(text("created_at DESC"))
    ).first()

    return company, agent_dicts, discovery


def _serialize_plan_response(
    plan: dict, scope_size: str, fallback_name: str, fallback_goal: str
):
    return {
        "sprint_name": plan.get("sprint_name", fallback_name),
        "goal": plan.get("goal", fallback_goal),
        "scope_size": scope_size,
        "tasks": plan.get("tasks", []),
    }


@router.post("/plan_sprint")
async def plan_sprint(
    req: SprintPlanRequest,
    session: Session = Depends(get_session),  # noqa: B008 - FastAPI dependency marker.
    user: User | None = Depends(current_user_if_required),  # noqa: B008 - FastAPI dependency marker.
):
    """Turn a strategic prompt into a scoped sprint backlog before sprint creation."""
    require_company_role(session, user, req.company_id, "Manager")
    scope_size = req.scope_size.upper()
    if scope_size not in SCOPE_LIMITS:
        raise HTTPException(
            status_code=422, detail="Invalid scope_size. Valid values: S, M, L"
        )
    if not req.prompt.strip():
        raise HTTPException(status_code=422, detail="Prompt is required")

    company, agent_dicts, discovery = _load_planning_context(session, req.company_id)

    plan = plan_execution_sprint(
        company_name=company.company_name,
        objective=req.prompt,
        scope_size=scope_size,
        agents=agent_dicts,
        detected_stack=discovery.detected_stack if discovery else None,
        project_path=discovery.project_path if discovery else None,
    )

    return _serialize_plan_response(
        plan,
        scope_size,
        f"Sprint - {company.company_name}",
        req.prompt.strip(),
    )


@router.post("/plan_self_improvement_sprint")
async def plan_self_improvement_sprint(
    req: SelfImprovementSprintRequest,
    session: Session = Depends(get_session),  # noqa: B008 - FastAPI dependency marker.
    user: User | None = Depends(current_user_if_required),  # noqa: B008 - FastAPI dependency marker.
):
    """Create a bounded autonomous-improvement plan from the repository's own context."""
    require_company_role(session, user, req.company_id, "Manager")
    scope_size = req.scope_size.upper()
    if scope_size not in SCOPE_LIMITS:
        raise HTTPException(
            status_code=422, detail="Invalid scope_size. Valid values: S, M, L"
        )

    company, agent_dicts, discovery = _load_planning_context(session, req.company_id)
    objective = build_self_improvement_objective(
        company_name=company.company_name,
        detected_stack=discovery.detected_stack if discovery else None,
    )

    plan = build_self_improvement_plan(
        company_name=company.company_name,
        objective=objective,
        scope_size=scope_size,
        agents=agent_dicts,
        detected_stack=discovery.detected_stack if discovery else None,
        project_path=discovery.project_path if discovery else None,
    )

    return _serialize_plan_response(
        plan,
        scope_size,
        f"Sprint - Improve {company.company_name}",
        objective,
    )


@router.post("/start_sprint")
async def start_sprint(
    req: SprintStartRequest,
    session: Session = Depends(get_session),  # noqa: B008 - FastAPI dependency marker.
    user: User | None = Depends(current_user_if_required),  # noqa: B008 - FastAPI dependency marker.
):
    """
    Create a sprint and its initial backlog items in a single transaction.

    For each backlog item an ``OutboxEvent`` is inserted so the background
    worker can publish a ``task.assign`` NATS message once the DB transaction
    commits.  This guarantees at-least-once delivery without a distributed
    transaction between Postgres and NATS.
    """
    require_company_role(session, user, req.company_id, "Manager")
    scope_size = req.scope_size.upper()
    if scope_size not in SCOPE_LIMITS:
        raise HTTPException(
            status_code=422, detail="Invalid scope_size. Valid values: S, M, L"
        )

    item_limit = SCOPE_LIMITS[scope_size]
    carry_over_ids = list(dict.fromkeys(req.carry_over_ids))
    item_count = len(req.backlog_items) + len(carry_over_ids)
    if item_count > SCOPE_HARD_MAX:
        raise HTTPException(
            status_code=422,
            detail=f"Too many backlog items ({item_count}). Hard limit is {SCOPE_HARD_MAX}. Split into multiple sprints.",
        )
    if item_count > item_limit:
        raise HTTPException(
            status_code=422,
            detail=f"Scope '{scope_size}' allows up to {item_limit} items, got {item_count}. Use scope 'L' or split this sprint.",
        )

    sprint = Sprint(
        company_id=req.company_id,
        sprint_name=req.sprint_name,
        start_date=req.start_date,
        scope_size=scope_size,
        goal=req.goal,
    )

    # Resolve the company's default business unit for quota tracking.
    default_bu = session.exec(
        select(BusinessUnit).where(BusinessUnit.company_id == req.company_id)
    ).first()
    default_bu_id: int | None = default_bu.id if default_bu else None
    sprint.business_unit_id = default_bu_id
    session.add(sprint)
    session.flush()  # Obtain sprint.id before processing backlog items

    item_ids = []
    for item in req.backlog_items:
        backlog_item = BacklogItem(
            sprint_id=sprint.id,
            title=item.get("title", ""),
            description=item.get("description", ""),
            priority=item.get("priority", "medium"),
            assignee=item.get("assignee", "PO"),
        )
        session.add(backlog_item)
        session.flush()
        item_ids.append(backlog_item.id)

        # Outbox entry — delivered to NATS by the process_outbox background worker.
        nats_payload = {
            "subject": "task.assign",
            "message": {
                "backlog_item_id": backlog_item.id,
                "interaction_id": str(uuid4()),
                "agent": item.get("assignee", "PO"),
                "sprint_id": sprint.id,
            },
        }
        session.add(
            OutboxEvent(
                aggregate_type="backlog_item",
                aggregate_id=str(backlog_item.id),
                event_type="nats_publish",
                payload=nats_payload,
            )
        )

    if carry_over_ids:
        try:
            carried = carry_over(
                session,
                req.company_id,
                carry_over_ids,
                sprint,
                user.email if user is not None else "a person",
                "Manager",
            )
        except CarryOverError as exc:
            session.rollback()
            raise HTTPException(status_code=exc.status, detail=exc.detail) from exc
        item_ids.extend(item.id for item in carried)
        story_items = [
            *req.backlog_items,
            *(
                {"title": item.title, "description": item.description or ""}
                for item in carried
            ),
        ]
    else:
        story_items = list(req.backlog_items)

    kickoff_story = "\n".join(
        [
            f"Sprint kickoff: {req.sprint_name}",
            f"Sprint ID: {sprint.id}",
            "Backlog:",
            *[
                f"- {item.get('title', '').strip()}: {item.get('description', '').strip()}"
                for item in story_items
            ],
            "Goal: PO, Scrum Master and Developer must coordinate, surface blockers, and agree the first execution plan.",
        ]
    )
    session.add(
        OutboxEvent(
            aggregate_type="sprint",
            aggregate_id=str(sprint.id),
            event_type="nats_publish",
            payload={
                "subject": "workspace.generate",
                "message": {
                    "interaction_id": str(uuid4()),
                    "company_id": req.company_id,
                    "business_unit_id": default_bu_id,
                    "sprint_id": sprint.id,
                    "story": kickoff_story,
                    "constraints": "Start the sprint conversation, coordinate roles, and keep the GlassRoom updated.",
                },
            },
        )
    )

    session.commit()
    return {
        "sprint_id": sprint.id,
        "backlog_item_ids": item_ids,
        "sprint_url": f"/v1/sprints/{sprint.id}/board",
    }


@router.get("/sprints")
async def list_sprints(
    company_id: int,
    session: Session = Depends(get_session),  # noqa: B008 - FastAPI dependency marker.
    user: User | None = Depends(current_user_if_required),  # noqa: B008 - FastAPI dependency marker.
):
    """
    Return the company's sprints, newest first, with backlog progress.

    ``total`` and ``done`` are counted from the sprint's backlog items so the
    list never needs one board request per sprint. ``second_attempts`` counts
    the tasks carried over from an earlier sprint: how many there are, how
    many got done, and the same two numbers for those that came with the
    ScrumMaster's brief, so a person sees whether another attempt, and the
    brief, pay off. ``console_advice`` splits the tasks into those a console
    assistant advised on and those none did, with how many got done and how
    many rework requests each group drew, so whether that advice helps is a
    number too. ``architect_advice`` does the same for the Architect's
    briefs.
    """
    require_company_role(session, user, company_id, "Viewer")
    sprints = session.exec(
        select(Sprint).where(Sprint.company_id == company_id).order_by(Sprint.id.desc())
    ).all()
    sprint_ids = [s.id for s in sprints]
    counts: dict[int, tuple[int, int, int]] = {}
    rework: dict[int, int] = {}
    attempts: dict[int, dict[str, int]] = {}
    advice: dict[int, dict[str, dict[str, int]]] = {}
    briefs: dict[int, dict[str, dict[str, int]]] = {}
    if sprint_ids:
        rows = session.exec(
            select(
                BacklogItem.sprint_id,
                func.count(BacklogItem.id),
                func.sum(case((BacklogItem.status == "done", 1), else_=0)),
                func.sum(case((BacklogItem.status == "blocked", 1), else_=0)),
            )
            .where(BacklogItem.sprint_id.in_(sprint_ids))
            .group_by(BacklogItem.sprint_id)
        ).all()
        counts = {
            sid: (int(total), int(done or 0), int(blocked or 0))
            for sid, total, done, blocked in rows
        }
        # Rework requests live in the comments, so they are counted in Python;
        # together with the blocked share they are the numbers the procedures
        # are judged by, shown per sprint so a person sees the trend.
        for sid, status, comments in session.exec(
            select(
                BacklogItem.sprint_id, BacklogItem.status, BacklogItem.comments
            ).where(BacklogItem.sprint_id.in_(sprint_ids))
        ).all():
            rework[sid] = rework.get(sid, 0) + rework_request_count(comments)
            count_second_attempt(
                attempts.setdefault(sid, no_second_attempts()), status, comments
            )
            count_console_advice(
                advice.setdefault(sid, no_console_advice()), status, comments
            )
            count_architect_advice(
                briefs.setdefault(sid, no_architect_advice()), status, comments
            )
    return [
        {
            "id": s.id,
            "sprint_name": s.sprint_name,
            "status": s.status,
            "goal": s.goal,
            "start_date": s.start_date,
            "scope_size": s.scope_size,
            "total": counts.get(s.id, (0, 0, 0))[0],
            "done": counts.get(s.id, (0, 0, 0))[1],
            "blocked": counts.get(s.id, (0, 0, 0))[2],
            "rework": rework.get(s.id, 0),
            "second_attempts": attempts.get(s.id, no_second_attempts()),
            "console_advice": advice.get(s.id, no_console_advice()),
            "architect_advice": briefs.get(s.id, no_architect_advice()),
        }
        for s in sprints
    ]


@router.post("/sprints/{sprint_id}/stream_ticket")
async def glassroom_stream_ticket(
    sprint_id: int,
    session: Session = Depends(get_session),  # noqa: B008 - FastAPI dependency marker.
    user: User | None = Depends(current_user_if_required),  # noqa: B008 - FastAPI dependency marker.
):
    """A short-lived ticket to open this sprint's Glassroom stream (Viewer).

    The browser's EventSource cannot send an Authorization header, so the
    stream takes this ticket in its query string. Without a login (a local
    demo) the stream needs none and ``ticket`` is null.
    """
    sprint = session.get(Sprint, sprint_id)
    if not sprint:
        raise HTTPException(status_code=404, detail="Sprint not found")
    require_company_role(session, user, sprint.company_id, "Viewer")
    if user is None:
        return {"ticket": None, "expires_in": 0}
    return {
        "ticket": create_stream_ticket(user_id=user.id, sprint_id=sprint.id),
        "expires_in": STREAM_TICKET_MINUTES * 60,
    }


@router.get("/sprints/{sprint_id}/board")
async def get_sprint_board(
    sprint_id: int,
    session: Session = Depends(get_session),  # noqa: B008 - FastAPI dependency marker.
    user: User | None = Depends(current_user_if_required),  # noqa: B008 - FastAPI dependency marker.
):
    """
    Return sprint metadata and all backlog items grouped by Kanban column.

    Items whose ``status`` value is not in ``VALID_STATUSES`` are placed in
    the ``"todo"`` column to avoid breaking the frontend rendering.
    """
    sprint = session.get(Sprint, sprint_id)
    if not sprint:
        raise HTTPException(status_code=404, detail="Sprint not found")

    require_company_role(session, user, sprint.company_id, "Viewer")
    sprint_data = {
        "id": sprint.id,
        "company_id": sprint.company_id,
        "sprint_name": sprint.sprint_name,
        "start_date": sprint.start_date,
        "scope_size": sprint.scope_size,
        "item_limit": SCOPE_LIMITS.get(sprint.scope_size, 8),
        "status": sprint.status,
        "goal": sprint.goal,
    }

    items_db = session.exec(
        select(BacklogItem).where(BacklogItem.sprint_id == sprint_id)
    ).all()

    items = [
        {
            "id": i.id,
            "title": i.title,
            "description": i.description,
            "status": i.status,
            "priority": i.priority,
            "assignee": i.assignee,
            "comments": i.comments or [],
            "created_at": str(i.created_at),
            "updated_at": str(i.updated_at),
        }
        for i in items_db
    ]

    # Pre-populate all columns so the frontend always receives a complete dict.
    columns = {s: [] for s in ["todo", "in_progress", "in_review", "done", "blocked"]}
    for item in items:
        col = item["status"] if item["status"] in columns else "todo"
        columns[col].append(item)

    return {"sprint": sprint_data, "columns": columns, "total": len(items)}


@router.patch("/backlog/{item_id}")
async def update_backlog_item(
    item_id: int,
    req: BacklogItemUpdate,
    session: Session = Depends(get_session),  # noqa: B008 - FastAPI dependency marker.
    user: User | None = Depends(current_user_if_required),  # noqa: B008 - FastAPI dependency marker.
):
    """
    Partially update a backlog item.

    Supports updating ``status``, ``priority``, ``assignee``, or appending a
    new comment.  All fields are optional; only provided fields are changed.
    A comment is recorded as a person's note (author ``user``): it is never
    taken for a deliverable to review, and one starting with
    ``services.board.SEND_BACK_MARKER`` restarts the task's rework budgets.
    Invalid ``status`` or ``priority`` values return HTTP 422.
    """
    if req.status and req.status not in VALID_STATUSES:
        raise HTTPException(
            status_code=422, detail=f"Invalid status. Valid: {VALID_STATUSES}"
        )
    if req.priority and req.priority not in VALID_PRIORITIES:
        raise HTTPException(
            status_code=422, detail=f"Invalid priority. Valid: {VALID_PRIORITIES}"
        )

    item = session.get(BacklogItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Backlog item not found")

    if user is not None:
        sprint = session.get(Sprint, item.sprint_id)
        if not sprint:
            raise HTTPException(status_code=404, detail="Sprint not found")
        require_company_role(session, user, sprint.company_id, "Manager")

    if req.status:
        item.status = req.status
    if req.priority:
        item.priority = req.priority
    if req.assignee is not None:
        item.assignee = req.assignee
    if req.comment:
        # Append the new comment to the existing JSON list.
        comments = list(item.comments or [])
        comments.append(
            {
                "author": "user",
                "text": req.comment,
                "created_at": str(datetime.now(UTC).replace(tzinfo=None)),
            }
        )
        item.comments = comments
    item.updated_at = datetime.now(UTC).replace(tzinfo=None)

    session.add(item)
    session.commit()
    session.refresh(item)
    return {
        "id": item.id,
        "sprint_id": item.sprint_id,
        "status": item.status,
        "priority": item.priority,
        "assignee": item.assignee,
        "comments": item.comments,
    }


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
    if sprint.status == "paused":
        raise HTTPException(status_code=409, detail="Sprint is paused")
    items = session.exec(
        select(BacklogItem).where(
            BacklogItem.sprint_id == sprint_id,
            BacklogItem.status == "todo",
        )
    ).all()

    if not items:
        return {"dispatched": 0, "message": "No todo items to dispatch"}

    dispatched = 0
    for item in items:
        nats_payload = {
            "subject": "task.assign",
            "message": {
                "backlog_item_id": item.id,
                "interaction_id": str(uuid4()),
                "agent": item.assignee or "PO",
                "sprint_id": sprint.id,
            },
        }
        session.add(
            OutboxEvent(
                aggregate_type="backlog_item",
                aggregate_id=str(item.id),
                event_type="nats_publish",
                payload=nats_payload,
            )
        )
        dispatched += 1

    session.commit()
    logger.info("Dispatched %d tasks for sprint %d", dispatched, sprint_id)
    return {"dispatched": dispatched, "sprint_id": sprint_id}


@router.post("/sprints/{sprint_id}/pause")
async def pause_sprint(
    sprint_id: int,
    session: Session = Depends(get_session),  # noqa: B008 - FastAPI dependency marker.
    user: User | None = Depends(current_user_if_required),  # noqa: B008 - FastAPI dependency marker.
):
    sprint = session.get(Sprint, sprint_id)
    if not sprint:
        raise HTTPException(status_code=404, detail="Sprint not found")
    require_company_role(session, user, sprint.company_id, "Manager")
    if sprint.status == "paused":
        return {"status": "already_paused"}
    sprint.status = "paused"
    session.add(sprint)
    session.commit()
    return {"status": "paused"}


@router.post("/sprints/{sprint_id}/resume")
async def resume_sprint(
    sprint_id: int,
    session: Session = Depends(get_session),  # noqa: B008 - FastAPI dependency marker.
    user: User | None = Depends(current_user_if_required),  # noqa: B008 - FastAPI dependency marker.
):
    sprint = session.get(Sprint, sprint_id)
    if not sprint:
        raise HTTPException(status_code=404, detail="Sprint not found")
    require_company_role(session, user, sprint.company_id, "Manager")
    if sprint.status != "paused":
        return {"status": sprint.status}
    sprint.status = "active"
    session.add(sprint)
    session.commit()
    return {"status": "active"}
