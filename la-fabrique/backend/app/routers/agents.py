"""
Agents router — LangGraph orchestration, memory, and Glassroom SSE endpoints.

Endpoints:
- ``POST /v1/generate``        — trigger a LangGraph workflow run via NATS.
- ``POST /v1/audit``           — write an agent decision to the audit log.
- ``GET  /v1/memory/search``   — vector-similarity search over pgvector + Neo4j.
- ``POST /v1/memory/store``    — persist content and its embedding.
- ``GET  /v1/glassroom/stream``— SSE stream of real-time agent events for a sprint.

The ``sse_connections`` dict is a module-level singleton shared with the NATS
listener in ``main.py``.  When a NATS message arrives on ``glassroom.<sprint_id>``,
the listener pushes the payload into the corresponding ``asyncio.Queue`` which
this router's SSE generator reads and forwards to the connected browser.
"""

import asyncio
import json
from collections import defaultdict
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from uuid import uuid4

from audit_chain import verify_chain
from audit_signing import verify_audit_row
from auth_policy import (
    current_user_if_required,
    require_authenticated,
    require_company_role,
    viewer_company_ids,
)
from auth_tokens import AuthTokenError, decode_stream_ticket
from config import settings
from database import engine, get_session
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from logging_config import logger
from models import AuditLog, BacklogItem, BusinessUnit, Sprint, User
from models.agent_run import AgentRun
from schemas import AuditRequest, GenerateRequest
from services.agent_service import AgentService
from sqlmodel import Session, or_, select

router = APIRouter(prefix="/v1", tags=["Agents"])

# Shared SSE connection map — keys are sprint IDs, values are active subscriber queues.
# Also consumed by the NATS listener in main.py to forward Glassroom events.
sse_connections: dict[str, list[asyncio.Queue[str]]] = {}
recent_sse_events: dict[str, list[dict]] = defaultdict(list)
MAX_RECENT_SSE_EVENTS = 50

HistoryLoader = Callable[[], Awaitable[list[dict]]]


def register_sse_connection(sprint_id: str, queue: asyncio.Queue[str]) -> None:
    subscribers = sse_connections.setdefault(sprint_id, [])
    subscribers.append(queue)


def unregister_sse_connection(sprint_id: str, queue: asyncio.Queue[str]) -> None:
    subscribers = sse_connections.get(sprint_id)
    if not subscribers:
        return
    sse_connections[sprint_id] = [
        subscriber for subscriber in subscribers if subscriber is not queue
    ]
    if not sse_connections[sprint_id]:
        sse_connections.pop(sprint_id, None)


async def publish_sse_event(sprint_id: str, payload: str) -> None:
    try:
        parsed = json.loads(payload)
    except (json.JSONDecodeError, TypeError):
        parsed = None

    if isinstance(parsed, dict):
        recent_sse_events[sprint_id].append(parsed)
        if len(recent_sse_events[sprint_id]) > MAX_RECENT_SSE_EVENTS:
            recent_sse_events[sprint_id] = recent_sse_events[sprint_id][
                -MAX_RECENT_SSE_EVENTS:
            ]

    for subscriber in list(sse_connections.get(sprint_id, [])):
        await subscriber.put(payload)


def _merge_sse_history(
    db_history: list[dict], recent_history: list[dict]
) -> list[dict]:
    merged: list[dict] = []
    seen: set[tuple[str, str, str, str, str, str]] = set()
    combined = [*db_history, *recent_history]

    latest_queue_index: dict[str, int] = {}
    has_follow_up_for_task: set[str] = set()

    for index, event in enumerate(combined):
        if not isinstance(event, dict):
            continue
        task_key = str(event.get("task_id") or event.get("task") or "")
        semantic_type = str(event.get("semantic_type") or "")
        if not task_key:
            continue
        if semantic_type == "task.queued":
            latest_queue_index[task_key] = index
            continue
        if semantic_type in {
            "task.claimed",
            "task.progress",
            "task.review_started",
            "task.review_handoff",
            "task.agent_complete",
            "task.approved",
            "task.blocked",
            "task.recovered",
            "task.history_comment",
            "task.status_snapshot",
            "task.retry_queued",
            "task.rework_scheduled",
        }:
            has_follow_up_for_task.add(task_key)

    for index, event in enumerate(combined):
        if not isinstance(event, dict):
            continue
        task_key = str(event.get("task_id") or event.get("task") or "")
        semantic_type = str(event.get("semantic_type") or "")

        if semantic_type == "task.queued" and task_key:
            if latest_queue_index.get(task_key) != index:
                continue
            if task_key in has_follow_up_for_task:
                continue

        key = (
            str(event.get("type", "")),
            str(event.get("agent", "")),
            str(event.get("role", "")),
            str(event.get("task", "")),
            str(event.get("message", "")),
            str(event.get("timestamp", "")),
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append(event)

    return merged


def load_sprint_history(sprint_id: str) -> list[dict]:
    """
    A sprint's past agent comments as Glassroom messages, replayed to every
    new connection before the live events.

    Each event's ``event_id`` names the task and the comment's position
    (``history-<task id>-<index>``; ``history-<task id>-status-<status>``
    for a task without comments), the same on every replay: a client that
    reconnects can tell the history it already shows from a new event, and
    a status that changed while it was away is new. Comments are only ever
    appended, so a comment keeps its position.
    """
    events: list[dict] = []
    try:
        with Session(engine) as session:
            items = session.exec(
                select(BacklogItem)
                .where(BacklogItem.sprint_id == int(sprint_id))
                .order_by(BacklogItem.id)
            ).all()
            for item in items:
                comments = item.comments or []
                if isinstance(comments, str):
                    try:
                        comments = json.loads(comments)
                    except (json.JSONDecodeError, TypeError):
                        comments = []
                for index, c in enumerate(comments):
                    text = c.get("text") or ""
                    if text.startswith(
                        "External assistant context used for this task:"
                    ):
                        events.append(
                            {
                                "type": "status",
                                "semantic_type": "assistant.history_context",
                                "source": "history",
                                "semantic_version": 1,
                                "event_id": f"history-{item.id}-{index}",
                                "agent": "System",
                                "role": "System",
                                "task_id": item.id,
                                "task": item.title,
                                "message": "External assistant context was used for this task.",
                                "preview": text[:300],
                                "timestamp": c.get("created_at", ""),
                                "status": item.status,
                            }
                        )
                        continue
                    events.append(
                        {
                            "type": "agent_complete",
                            "semantic_type": "task.history_comment",
                            "source": "history",
                            "semantic_version": 1,
                            "event_id": f"history-{item.id}-{index}",
                            "agent": c.get("author", item.assignee or "Agent"),
                            "role": item.assignee or "Agent",
                            "task_id": item.id,
                            "task_status": item.status,
                            "task": item.title,
                            "message": f"✅ {c.get('author', 'Agent')} delivered: {item.title}",
                            "preview": text[:300],
                            "timestamp": c.get("created_at", ""),
                            "status": item.status,
                        }
                    )
                # Show current status for items without comments too
                if not comments and item.status not in ("todo",):
                    events.append(
                        {
                            "type": "status",
                            "semantic_type": "task.status_snapshot",
                            "source": "history",
                            "semantic_version": 1,
                            "event_id": f"history-{item.id}-status-{item.status}",
                            "agent": item.assignee or "System",
                            "role": item.assignee or "System",
                            "task_id": item.id,
                            "task_status": item.status,
                            "task": item.title,
                            "message": f"📋 {item.title} → {item.status}",
                            "timestamp": (
                                item.updated_at or item.created_at or ""
                            ).isoformat()
                            if hasattr(item.updated_at or item.created_at, "isoformat")
                            else "",
                            "status": item.status,
                        }
                    )
    except Exception:  # noqa: BLE001, S110 - SSE history is best-effort; live events remain available.
        pass
    return events


async def generate_glassroom_sse(
    queue: asyncio.Queue[str],
    sprint_id: str,
    nats_available: bool,
    history_loader: HistoryLoader,
) -> AsyncIterator[str]:
    try:
        yield f"data: {json.dumps({'type': 'connected', 'semantic_type': 'stream.connected', 'source': 'sse', 'semantic_version': 1, 'event_id': str(uuid4()), 'sprint_id': sprint_id})}\n\n"

        if not nats_available:
            yield f"data: {json.dumps({'type': 'error', 'semantic_type': 'stream.unavailable', 'source': 'sse', 'semantic_version': 1, 'event_id': str(uuid4()), 'agent': 'System', 'role': 'System', 'message': '⚠️ NATS message broker is not connected. Agents cannot run. Start NATS and restart the backend.', 'timestamp': datetime.now(UTC).replace(tzinfo=None).isoformat()})}\n\n"

        history = _merge_sse_history(
            await history_loader(), recent_sse_events.get(sprint_id, [])
        )
        for evt in history:
            yield f"data: {json.dumps(evt)}\n\n"

        while True:
            try:
                data = await asyncio.wait_for(queue.get(), timeout=15)
                try:
                    parsed = json.loads(data)
                except (json.JSONDecodeError, TypeError):
                    parsed = {"type": "message", "message": str(data)}
                yield f"data: {json.dumps(parsed)}\n\n"
            except TimeoutError:
                yield f"data: {json.dumps({'ping': True})}\n\n"
    finally:
        unregister_sse_connection(sprint_id, queue)


@router.post("/generate")
async def generate(
    req: GenerateRequest,
    request: Request,
    session: Session = Depends(get_session),  # noqa: B008 - FastAPI dependency marker.
    user: User | None = Depends(current_user_if_required),  # noqa: B008 - FastAPI dependency marker.
):
    """
    Trigger a LangGraph agent workflow run.
    """
    require_company_role(session, user, req.company_id, "Manager")
    # The business unit is billed for the run's tokens: it must be this company's.
    if req.business_unit_id is not None:
        unit = session.get(BusinessUnit, req.business_unit_id)
        if unit is None or unit.company_id != req.company_id:
            raise HTTPException(
                status_code=403,
                detail="The business unit does not belong to this company",
            )
    if not settings.AGENT_GRAPH_ENABLED:
        raise HTTPException(
            status_code=409,
            detail=(
                "AGENT_GRAPH_ENABLED is false; the internal agent graph is disabled. "
                "Ingest externally-produced work via POST /v1/agent_runs."
            ),
        )
    service = AgentService(nats_client=request.app.state.nats_client)
    interaction_id = await service.generate_package(
        company_id=req.company_id,
        business_unit_id=req.business_unit_id,
        story=req.story,
        constraints=req.constraints,
        interaction_id=req.interaction_id,
        session=session,
    )
    return {"interaction_id": interaction_id, "package_url": None}


def _write_company(session, user, company_id, context, interaction_id=None):
    """Resolve ownership from membership and stored interactions, never metadata."""
    owners = set()
    if interaction_id:
        owners.update(
            session.exec(
                select(AuditLog.company_id).where(
                    AuditLog.interaction_id == interaction_id,
                    AuditLog.company_id.is_not(None),
                )
            ).all()
        )
        if interaction_id.startswith("agent-run:"):
            owners.update(
                session.exec(
                    select(AgentRun.company_id).where(
                        AgentRun.external_ref == interaction_id[len("agent-run:") :]
                    )
                ).all()
            )
    if company_id is None:
        if len(owners) == 1:
            company_id = next(iter(owners))
        elif user is not None:
            companies = viewer_company_ids(session, user)
            if len(companies) == 1:
                company_id = companies[0]
    require_company_role(session, user, company_id, "Manager")
    if owners and company_id not in owners:
        raise HTTPException(
            status_code=403, detail="Interaction belongs to another company"
        )
    supplied = (context or {}).get("company_id")
    if supplied is not None and str(supplied) != str(company_id):
        raise HTTPException(
            status_code=403, detail="Company metadata does not match ownership"
        )
    run_id = (context or {}).get("agent_run_id")
    if run_id is not None:
        run = session.get(AgentRun, run_id)
        if run is None or run.company_id != company_id:
            raise HTTPException(
                status_code=403, detail="Agent run belongs to another company"
            )
    return company_id


@router.post("/audit")
async def audit(
    req: AuditRequest,
    company_id: int | None = None,
    session: Session = Depends(get_session),  # noqa: B008 - FastAPI dependency marker.
    user: User | None = Depends(current_user_if_required),  # noqa: B008 - FastAPI dependency marker.
):
    """
    Write an agent decision entry to the audit log.

    Writes to both the filesystem JSONL file and the ``audit_log`` database
    table via ``AgentService.audit_interaction()``.
    """
    company_id = _write_company(
        session, user, company_id, req.details, req.interaction_id
    )
    if req.decision_signature is not None:
        logger.warning(
            "decision_signature supplied by caller is ignored; signatures are computed server-side"
        )

    service = AgentService()
    service.audit_interaction(
        session=session,
        company_id=company_id,
        interaction_id=req.interaction_id,
        agent_id=req.agent_id,
        action=req.action,
        details=req.details,
        result=req.result,
        decision_signature=None,
        cost_tokens=req.cost_tokens,
    )
    return {"status": "ok"}


@router.get("/audit/verify")
async def verify_audit(
    interaction_id: str = Query(...),
    company_id: int | None = None,
    session: Session = Depends(get_session),  # noqa: B008 - FastAPI dependency marker.
    user: User | None = Depends(current_user_if_required),  # noqa: B008 - FastAPI dependency marker.
):
    """Verify every audit row associated with an interaction."""
    require_authenticated(user)
    statement = select(AuditLog).where(AuditLog.interaction_id == interaction_id)
    if user is not None:
        statement = statement.where(
            or_(
                AuditLog.company_id.in_(viewer_company_ids(session, user)),
                AuditLog.company_id.is_(None) if company_id is None else False,
            )
        )
    if company_id is not None:
        statement = statement.where(AuditLog.company_id == company_id)
    rows = session.exec(statement.order_by(AuditLog.id)).all()
    if not rows:
        raise HTTPException(
            status_code=404, detail="No audit rows found for interaction_id."
        )

    summary = {"valid": 0, "invalid": 0, "unsigned": 0, "legacy": 0}
    verified_rows = []
    for row in rows:
        verification = verify_audit_row(row)
        summary[verification["status"]] += 1
        verified_rows.append(
            {
                "id": row.id,
                "action": row.action,
                "status": verification["status"],
                "mode": verification["mode"],
                "company_id": row.company_id,
                "legacy": row.company_id is None,
            }
        )

    return {
        "interaction_id": interaction_id,
        "rows": verified_rows,
        "summary": summary,
    }


@router.get("/audit/chain")
async def verify_audit_chain(
    company_id: int = Query(...),
    session: Session = Depends(get_session),  # noqa: B008 - FastAPI dependency marker.
    user: User | None = Depends(current_user_if_required),  # noqa: B008 - FastAPI dependency marker.
):
    """Walk a company's audit hash chain and report where it breaks.

    A row deleted, inserted, reordered, altered or moved from another company
    shows as a break at its sequence number; the head (last number and hash)
    can be recorded elsewhere to notice newest rows being dropped.
    """
    require_authenticated(user)
    require_company_role(session, user, company_id, "Viewer")
    return verify_chain(session, company_id)


@router.get("/memory/search")
async def search_memory(
    request: Request,
    query: str = Query(...),
    limit: int = Query(10, ge=1, le=100),
    company_id: int | None = None,
    session: Session = Depends(get_session),  # noqa: B008 - FastAPI dependency marker.
    user: User | None = Depends(current_user_if_required),  # noqa: B008 - FastAPI dependency marker.
):
    """
    Search the vector memory store for content similar to *query*.

    Uses pgvector cosine similarity on pre-computed embeddings.
    Returns up to *limit* results sorted by descending similarity.
    """
    require_authenticated(user)
    company_ids = viewer_company_ids(session, user) if user is not None else None
    if company_id is not None:
        require_company_role(session, user, company_id, "Viewer")
        company_ids = [company_id]
    client = request.app.state.memory_client
    if not client:
        raise HTTPException(
            status_code=503, detail="Memory service unavailable (Neo4j not connected)."
        )
    results = client.search_similar(
        query, limit, company_ids=company_ids, include_legacy=company_id is None
    )
    return {"results": results}


@router.post("/memory/store")
async def store_memory(
    request: Request,
    content: str,
    metadata: dict | None = None,
    company_id: int | None = None,
    session: Session = Depends(get_session),  # noqa: B008 - FastAPI dependency marker.
    user: User | None = Depends(current_user_if_required),  # noqa: B008 - FastAPI dependency marker.
):
    """
    Compute and store an embedding for *content* in pgvector and Neo4j.

    Embeddings are generated by the LLM Proxy (``text-embedding-004``).
    *metadata* is an arbitrary JSON dict stored alongside the embedding for
    later retrieval context.
    """
    company_id = _write_company(
        session, user, company_id, metadata, (metadata or {}).get("interaction_id")
    )
    client = request.app.state.memory_client
    if not client:
        raise HTTPException(
            status_code=503, detail="Memory service unavailable (Neo4j not connected)."
        )
    client.store(content, metadata, company_id=company_id)
    return {"status": "stored"}


def _check_stream_ticket(sprint_id: str, ticket: str | None) -> None:
    """401 unless *ticket* opens this sprint's stream for a member of its company."""
    unauthorized = HTTPException(
        status_code=401,
        detail="A valid stream ticket for this sprint is required",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        sprint_number = int(sprint_id)
        user_id = decode_stream_ticket(ticket or "", sprint_number)
    except (ValueError, AuthTokenError):
        raise unauthorized from None
    with Session(engine) as session:
        sprint = session.get(Sprint, sprint_number)
        user = session.get(User, user_id)
        if sprint is None or user is None:
            raise unauthorized
        # Checked again here: the ticket proves who asked, not that they still belong.
        require_company_role(session, user, sprint.company_id, "Viewer")


@router.get("/glassroom/stream")
async def glassroom_stream(
    sprint_id: str = Query(...),
    ticket: str | None = Query(None),
    request: Request = None,
):
    """
    Server-Sent Events (SSE) stream for real-time Glassroom monitoring.

    On connect, replays past agent activity from backlog item comments so the
    user sees the full conversation history.  Then switches to live streaming
    via NATS.  A keepalive ping is sent every 15 seconds.

    If NATS is unavailable, a red system error event is emitted immediately so
    the user sees a clear explanation instead of silent inactivity.

    A browser EventSource cannot send an Authorization header: with
    authentication required, the stream takes a short-lived ``ticket`` for
    this sprint from ``POST /v1/sprints/{id}/stream_ticket`` instead.
    """
    if settings.AUTH_REQUIRED:
        _check_stream_ticket(sprint_id, ticket)
    queue: asyncio.Queue[str] = asyncio.Queue()
    register_sse_connection(sprint_id, queue)

    # Detect whether NATS (and therefore agents) is available.
    nats_available = bool(request and getattr(request.app.state, "nats_client", None))

    return StreamingResponse(
        generate_glassroom_sse(
            queue=queue,
            sprint_id=sprint_id,
            nats_available=nats_available,
            history_loader=lambda: asyncio.to_thread(load_sprint_history, sprint_id),
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
