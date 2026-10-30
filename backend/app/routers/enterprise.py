"""
Enterprise router — multi-tenancy governance, quota management, and analytics.

Endpoints:
- ``POST /v1/init_company``        — bootstrap a new company with agents and credentials.
- ``POST /v1/approve_task``        — retired approval endpoint (410 Gone).
- ``GET  /v1/enterprise/quotas``   — token usage per business unit.
- ``GET  /v1/analytics/summary``   — AI Scrum Master sprint health report.
- ``POST /v1/discover_team``       — auto-detect project stack and suggest an AI team.
- ``GET  /v1/enterprise/lineage``  — time-travel debugging: architectural decisions for a file.
- ``GET  /v1/capabilities``        — public report of which optional backend features are enabled.
"""

import asyncio
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from auth_policy import (
    current_user_if_required,
    require_authenticated,
    require_company_role,
    viewer_company_ids,
)
from config import settings
from database import get_neo4j_driver, get_session
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from logging_config import logger
from models import Agent, AuditLog, BusinessUnit, Sprint, User
from schemas import (
    AgentCreateRequest,
    AgentPromptRequest,
    AgentUpdateRequest,
    CompanyInitRequest,
    DiscoveryRequest,
    OrchestrationHealthResponse,
    OrchestrationHealthSummaries,
    OrchestrationHealthSummary,
    OrchestrationHealthWeek,
)
from services.company_service import CompanyService
from services.discovery_service import DiscoveryService
from services.workspace_daemon import (
    DAEMON_UNAVAILABLE_DETAIL,
    DaemonError,
    DaemonUnavailable,
    inspect_project,
    materialized_snapshot,
    without_snapshot,
)
from sqlalchemy import text
from sqlmodel import Session, select

router = APIRouter(prefix="/v1", tags=["Enterprise"])

_ANCHOR_COMMIT = "116138e"
_ANCHOR_DATE = date(2026, 5, 2)


@router.post("/init_company", tags=["Core"])
async def init_company(
    req: CompanyInitRequest,
    session: Session = Depends(get_session),  # noqa: B008 - FastAPI dependency marker.
    user: User | None = Depends(current_user_if_required),  # noqa: B008 - FastAPI dependency marker.
):
    """
    Bootstrap a new company tenant with its AI agents and project credentials.
    Delegates to CompanyService for transactional logic and team planning.
    """
    require_authenticated(user)
    service = CompanyService(session)
    try:
        result = service.init_company(
            company_name=req.company_name,
            agents=req.agents,
            default_scope_size=req.default_scope_size,
            autonomy_level=req.autonomy_level,
            permissions=req.permissions,
            project_path=req.project_path,
            detected_stack=req.detected_stack,
            owner_user_id=user.id if user is not None else None,
        )
        return result
    except Exception as exc:  # noqa: BLE001 - Translate service failures to a sanitized API error.
        logger.error(f"Company initialization failed: {exc}")
        raise HTTPException(
            status_code=500, detail="Internal server error during initialization"
        )


@router.post("/approve_task", tags=["Enterprise"])
async def approve_task():
    raise HTTPException(
        status_code=410,
        detail="POST /v1/approve_task was removed; use POST /v1/agent_runs/{id}/approve (issue #42)",
    )


@router.get("/enterprise/quotas", tags=["Enterprise"])
async def get_quotas(
    company_id: int,
    session: Session = Depends(get_session),  # noqa: B008 - FastAPI dependency marker.
    user: User | None = Depends(current_user_if_required),  # noqa: B008 - FastAPI dependency marker.
):
    """
    Return token usage and limits for all business units of a company.
    """
    require_company_role(session, user, company_id, "Viewer")
    service = CompanyService(session)
    return service.get_quotas(company_id)


@router.post("/enterprise/quotas/{bu_id}/reset", tags=["Enterprise"])
async def reset_quota(
    bu_id: int,
    session: Session = Depends(get_session),  # noqa: B008 - FastAPI dependency marker.
    user: User | None = Depends(current_user_if_required),  # noqa: B008 - FastAPI dependency marker.
):
    """
    Reset the token usage counter for a business unit to zero.
    Intended for use at the start of a new billing cycle.
    """
    if user is not None:
        unit = session.get(BusinessUnit, bu_id)
        if not unit:
            raise HTTPException(
                status_code=404, detail=f"Business Unit {bu_id} not found"
            )
        require_company_role(session, user, unit.company_id, "Manager")
    service = CompanyService(session)
    try:
        return service.reset_quota(bu_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/analytics/summary", tags=["Enterprise"])
async def get_project_health(
    sprint_id: int,
    session: Session = Depends(get_session),  # noqa: B008 - FastAPI dependency marker.
    user: User | None = Depends(current_user_if_required),  # noqa: B008 - FastAPI dependency marker.
):
    """
    AI Scrum Master: generate a sprint health report from audit and backlog data.
    """
    if user is not None:
        sprint = session.get(Sprint, sprint_id)
        if not sprint:
            raise HTTPException(status_code=404, detail="Sprint not found")
        require_company_role(session, user, sprint.company_id, "Viewer")
    service = CompanyService(session)
    return service.get_project_health(sprint_id)


@router.get(
    "/analytics/orchestration_health",
    response_model=OrchestrationHealthResponse,
    tags=["Enterprise"],
)
async def get_orchestration_health(
    company_id: int = Query(
        ..., description="Company whose orchestration history will be analysed"
    ),
    weeks: int = Query(8, ge=1, le=52, description="Trailing weeks to include"),
    session: Session = Depends(get_session),  # noqa: B008 - FastAPI dependency marker.
    user: User | None = Depends(current_user_if_required),  # noqa: B008 - FastAPI dependency marker.
):
    """
    Return weekly KPI trends that measure the Batch-1 orchestration rollout.
    """
    require_company_role(session, user, company_id, "Viewer")
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(weeks=weeks)
    params = {"company_id": company_id, "cutoff": cutoff}

    qa_sql = text("""
        SELECT
            to_char(date_trunc('week', a.created_at), 'IYYY-"W"IW') AS week,
            COALESCE(
                COUNT(*) FILTER (WHERE a.details->>'result_type' = 'NEEDS_WORK') * 1.0
                / NULLIF(COUNT(*), 0),
                0
            ) AS qa_needs_work_rate,
            COUNT(*) AS task_count
        FROM audit_log a
        WHERE a.details->>'role' = 'QA'
          AND a.action = 'qa_review'
          AND NULLIF(a.details->>'company_id', '')::int = :company_id
          AND a.created_at >= :cutoff
        GROUP BY 1
        ORDER BY 1
    """)

    qa_fallback_sql = text("""
        WITH review_comments AS (
            SELECT
                to_char(date_trunc('week', bi.updated_at), 'IYYY-"W"IW') AS week,
                UPPER(COALESCE(c->>'text', '')) AS review_text
            FROM backlog_items bi
            JOIN sprints s ON s.id = bi.sprint_id
            CROSS JOIN LATERAL jsonb_array_elements(
                CASE
                    WHEN bi.comments IS NULL THEN '[]'::jsonb
                    WHEN jsonb_typeof(bi.comments::jsonb) = 'array' THEN bi.comments::jsonb
                    ELSE '[]'::jsonb
                END
            ) AS c
            WHERE s.company_id = :company_id
              AND bi.updated_at >= :cutoff
              AND (
                  UPPER(COALESCE(c->>'text', '')) LIKE 'APPROVED:%'
                  OR UPPER(COALESCE(c->>'text', '')) LIKE 'NEEDS WORK:%'
              )
        )
        SELECT
            week,
            COALESCE(
                COUNT(*) FILTER (WHERE review_text LIKE 'NEEDS WORK:%') * 1.0
                / NULLIF(COUNT(*), 0),
                0
            ) AS qa_needs_work_rate,
            COUNT(*) AS task_count
        FROM review_comments
        GROUP BY 1
        ORDER BY 1
    """)

    reported = "COALESCE(a.details->>'tokens', CASE WHEN a.cost_tokens > 0 THEN 'reported' ELSE 'unavailable' END) = 'reported'"
    tokens_sql = text(
        """
        SELECT
            to_char(date_trunc('week', a.created_at), 'IYYY-"W"IW') AS week,
            -- Turns whose usage the proxy did not report are counted apart, not averaged as zero.
            COALESCE(AVG(a.cost_tokens) FILTER (WHERE {reported}), 0) AS avg_developer_tokens,
            COUNT(*) FILTER (WHERE {reported}) AS developer_turn_count,
            COUNT(*) FILTER (WHERE NOT ({reported})) AS developer_turns_without_tokens
        FROM audit_log a
        WHERE a.details->>'role' = 'Developer'
          AND NULLIF(a.details->>'company_id', '')::int = :company_id
          AND a.created_at >= :cutoff
        GROUP BY 1
        ORDER BY 1
    """.replace("{reported}", reported)
    )

    consult_sql = text("""
        SELECT
            to_char(date_trunc('week', bi.updated_at), 'IYYY-"W"IW') AS week,
            COUNT(*) AS architect_consult_count
        FROM backlog_items bi
        JOIN sprints s ON s.id = bi.sprint_id
        CROSS JOIN LATERAL jsonb_array_elements(
            CASE
                WHEN bi.comments IS NULL THEN '[]'::jsonb
                WHEN jsonb_typeof(bi.comments::jsonb) = 'array' THEN bi.comments::jsonb
                ELSE '[]'::jsonb
            END
        ) AS c
        WHERE s.company_id = :company_id
          AND bi.updated_at >= :cutoff
          AND c->>'author' = 'Architect'
          AND UPPER(COALESCE(c->>'text', '')) LIKE 'ARCHITECT_CONSULTED:%'
        GROUP BY 1
        ORDER BY 1
    """)

    try:
        qa_rows = session.execute(qa_sql, params).mappings().all()
        if not qa_rows:
            qa_rows = session.execute(qa_fallback_sql, params).mappings().all()
        token_rows = session.execute(tokens_sql, params).mappings().all()
        consult_rows = session.execute(consult_sql, params).mappings().all()
    except Exception as exc:  # noqa: BLE001 - Translate analytics failures to a sanitized API error.
        logger.error("Orchestration health query failed: %s", exc)
        raise HTTPException(status_code=500, detail="Analytics query failed.")

    qa_by_week = {row["week"]: row for row in qa_rows}
    tokens_by_week = {row["week"]: row for row in token_rows}
    consult_by_week = {row["week"]: row for row in consult_rows}
    developer_turn_counts = {
        row["week"]: int(row.get("developer_turn_count", 0)) for row in token_rows
    }
    all_weeks = sorted(set(qa_by_week) | set(tokens_by_week) | set(consult_by_week))
    anchor_week = _ANCHOR_DATE.strftime("%G-W%V")

    week_rows: list[OrchestrationHealthWeek] = []
    for week_label in all_weeks:
        qa_row = qa_by_week.get(week_label, {})
        token_row = tokens_by_week.get(week_label, {})
        consult_row = consult_by_week.get(week_label, {})
        week_rows.append(
            OrchestrationHealthWeek(
                week=week_label,
                qa_needs_work_rate=float(qa_row.get("qa_needs_work_rate", 0.0)),
                avg_developer_tokens=float(token_row.get("avg_developer_tokens", 0.0)),
                architect_consult_count=int(
                    consult_row.get("architect_consult_count", 0)
                ),
                task_count=int(qa_row.get("task_count", 0)),
                developer_turns_without_tokens=int(
                    token_row.get("developer_turns_without_tokens", 0) or 0
                ),
                post_batch1=week_label >= anchor_week,
            )
        )

    def _weighted_qa_rate(items: list[OrchestrationHealthWeek]) -> float:
        total_reviews = sum(item.task_count for item in items)
        if not total_reviews:
            return 0.0
        weighted_sum = sum(item.qa_needs_work_rate * item.task_count for item in items)
        return weighted_sum / total_reviews

    def _weighted_token_average(items: list[OrchestrationHealthWeek]) -> float:
        total_turns = sum(developer_turn_counts.get(item.week, 0) for item in items)
        if not total_turns:
            return 0.0
        weighted_sum = sum(
            item.avg_developer_tokens * developer_turn_counts.get(item.week, 0)
            for item in items
        )
        return weighted_sum / total_turns

    pre_batch1 = [row for row in week_rows if not row.post_batch1]
    post_batch1 = [row for row in week_rows if row.post_batch1]

    return OrchestrationHealthResponse(
        anchor_commit=_ANCHOR_COMMIT,
        anchor_date=_ANCHOR_DATE.isoformat(),
        weeks=week_rows,
        summary=OrchestrationHealthSummaries(
            pre_batch1=OrchestrationHealthSummary(
                qa_needs_work_rate=_weighted_qa_rate(pre_batch1),
                avg_developer_tokens=_weighted_token_average(pre_batch1),
            ),
            post_batch1=OrchestrationHealthSummary(
                qa_needs_work_rate=_weighted_qa_rate(post_batch1),
                avg_developer_tokens=_weighted_token_average(post_batch1),
            ),
        ),
    )


@router.get("/enterprise/quota_usage_history", tags=["Enterprise"])
async def quota_usage_history(
    company_id: int,
    days: int = Query(7, ge=1, le=90),
    session: Session = Depends(get_session),  # noqa: B008 - FastAPI dependency marker.
    user: User | None = Depends(current_user_if_required),  # noqa: B008 - FastAPI dependency marker.
):
    """Return daily token usage for a company over the last *days* days (Viewer)."""
    require_company_role(session, user, company_id, "Viewer")
    from datetime import timedelta

    from sqlmodel import func

    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days)
    rows = session.exec(
        select(
            func.date(AuditLog.created_at).label("day"),
            func.coalesce(func.sum(AuditLog.cost_tokens), 0),
        )
        .where(AuditLog.company_id == company_id)
        .where(AuditLog.created_at >= cutoff)
        .group_by(func.date(AuditLog.created_at))
        .order_by(func.date(AuditLog.created_at))
    ).all()
    usage = {str(r[0]): int(r[1] or 0) for r in rows}

    result = []
    for i in range(days):
        d = (
            datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days - 1 - i)
        ).date()
        result.append({"date": d.isoformat(), "tokens": usage.get(str(d), 0)})
    return {"days": result, "total": sum(u["tokens"] for u in result)}


@router.get("/capabilities", tags=["Enterprise"])
async def get_capabilities(request: Request) -> dict[str, bool | str | None]:
    """
    Report which optional backend features are available.

    Public like ``/health``: it exposes configuration flags, never company
    data, so the frontend can hide navigation for disabled features.
    """
    return {
        "agent_graph": bool(settings.AGENT_GRAPH_ENABLED),
        "memory": getattr(request.app.state, "memory_client", None) is not None,
        "github": bool(settings.GITHUB_TOKEN),
        "auth_required": bool(settings.AUTH_REQUIRED),
        "support_agent": bool(settings.SUPPORT_AGENT_ENABLED),
        # Where GitHub can reach this backend; null when not configured.
        "public_api_url": (settings.PUBLIC_API_URL or "").rstrip("/") or None,
    }


@router.get("/models", tags=["Enterprise"])
async def list_models(request: Request):
    """
    Return the live LLM model catalogue from the proxy.

    Proxies the ``/v1/models`` response from the internal LLM proxy so that
    the frontend can build a dynamic model selector without hardcoding model
    names or tiers.  The proxy refreshes its catalogue from the Gemini API
    every hour and classifies models by capability tier.

    Response shape::

        {
          "models": [
            {"id": "gemini-2.5-pro", "provider": "gemini", "tier": "strategic", "description": "..."},
            ...
          ],
          "orchestrator": "gemini-2.5-flash",
          "refreshed_at": 1712345678.0
        }
    """
    llm_client = getattr(request.app.state, "llm_client", None)
    if llm_client is None:
        raise HTTPException(status_code=503, detail="LLM proxy not available")
    try:
        data = await asyncio.to_thread(llm_client.get_available_models)
        if not data:
            raise HTTPException(
                status_code=502, detail="LLM proxy returned empty catalogue"
            )
        return data
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - Translate upstream catalogue failures to an API error.
        logger.error("Failed to fetch model catalogue: %s", exc)
        raise HTTPException(status_code=502, detail="Could not reach LLM proxy")


@router.post("/discover_team", tags=["Enterprise"])
async def discover_team(
    req: DiscoveryRequest,
    request: Request,
    session: Session = Depends(get_session),  # noqa: B008 - FastAPI dependency marker.
    user: User | None = Depends(current_user_if_required),  # noqa: B008 - FastAPI dependency marker.
):
    """
    Scan a project path to detect its technology stack and suggest an AI team.

    Phase 1 (deterministic): filesystem walk + config-file parsing.
    Phase 2 (AI): LLM proxy reasons about the stack and suggests a team with
    per-role justifications. Falls back to rule-based team if LLM unavailable.

    If ``company_id`` is provided, the result is persisted in the
    ``project_discovery`` table, and it becomes the folder that company's
    agents write to, so that needs a Manager of the company.
    """
    require_authenticated(user)
    if req.company_id is not None:
        require_company_role(session, user, req.company_id, "Manager")
    llm_proxy_url = None
    llm_client = getattr(request.app.state, "llm_client", None)
    if llm_client:
        llm_proxy_url = llm_client.base_url
    service = DiscoveryService(session, llm_proxy_url=llm_proxy_url)

    # The project is on the user's machine: the workspace daemon there checks
    # the folder and sends a snapshot of its files, which is scanned here.
    project = None
    daemon_missing = False
    try:
        project = await inspect_project(
            getattr(request.app.state, "nats_client", None),
            req.project_path,
            snapshot=True,
        )
    except DaemonUnavailable:
        daemon_missing = True
    except DaemonError as exc:
        raise HTTPException(
            status_code=422 if exc.status in {400, 404} else exc.status,
            detail=exc.message,
        )

    if project is not None and not project.get("is_dir"):
        host = (project.get("host") or {}).get("hostname") or "the workspace machine"
        raise HTTPException(
            status_code=422,
            detail=f"Folder not found on {host}: {project.get('path')}",
        )

    def _scan_snapshot():
        with materialized_snapshot(project.get("snapshot") or {}) as mirror:
            return service.discover_project_team(
                company_id=req.company_id,
                project_path=mirror,
                stored_path=project["path"],
                project_name=project.get("name"),
            )

    try:
        # Run the synchronous scan + LLM call in a thread pool so the async
        # event loop stays free while the work runs.
        if project is not None:
            discovery, detected_stack, suggested_team = await asyncio.to_thread(
                _scan_snapshot
            )
            project_path = project["path"]
        else:
            # No daemon: a folder this server can see (e.g. a Linux host
            # mounted at the same path) is scanned directly.
            discovery, detected_stack, suggested_team = await asyncio.to_thread(
                service.discover_project_team,
                company_id=req.company_id,
                project_path=req.project_path,
            )
            project_path = str(Path(req.project_path).expanduser().resolve())
    except ValueError as exc:
        if daemon_missing:
            raise HTTPException(status_code=503, detail=DAEMON_UNAVAILABLE_DETAIL)
        raise HTTPException(status_code=422, detail=str(exc))
    return {
        "discovery_id": discovery.id if discovery else None,
        "detected_stack": detected_stack,
        "suggested_team": suggested_team,
        "project_path": project_path,
        "project": without_snapshot(project) if project is not None else None,
    }


@router.get("/enterprise/lineage", tags=["Enterprise"])
async def get_code_lineage(
    file_path: str,
    company_id: int | None = None,
    session: Session = Depends(get_session),  # noqa: B008 - FastAPI dependency marker.
    user: User | None = Depends(current_user_if_required),  # noqa: B008 - FastAPI dependency marker.
):
    """
    Time-Travel Debugging: retrieve all architectural decisions that modified a file.

    Queries the Neo4j Temporal Knowledge Graph for ``Episodic`` nodes connected
    to a ``Semantic`` node whose ``id`` ends with *file_path* via a
    ``MODIFIED_BY`` relationship.  Returns up to 10 most recent decisions.
    """
    require_authenticated(user)
    if company_id is not None:
        require_company_role(session, user, company_id, "Viewer")
    company_ids = viewer_company_ids(session, user) if user is not None else []
    driver = get_neo4j_driver()
    try:
        company_filter = (
            "AND e.company_id = $company_id"
            if company_id is not None
            else "AND (e.company_id IN $company_ids OR e.company_id IS NULL)"
            if user is not None
            else ""
        )
        cypher = f"""
        MATCH (e:Episodic)-[r:MODIFIED_BY]->(s)
        WHERE s.id ENDS WITH $file_path
        {company_filter}
        RETURN e.id AS engram_id, e.agent_role AS role, e.summary AS decision, e.created_at AS timestamp,
               e.company_id AS company_id, e.company_id IS NULL AS legacy
        ORDER BY e.created_at DESC LIMIT 10
        """
        with driver.session() as neo_session:
            result = neo_session.run(
                cypher,
                file_path=file_path,
                company_id=company_id,
                company_ids=company_ids,
            )
            lineage = [dict(record) for record in result]
        if not lineage:
            return {
                "file": file_path,
                "status": "No historical engrams found.",
                "lineage": [],
            }
        return {"file": file_path, "status": "success", "lineage": lineage}
    except Exception as e:  # noqa: BLE001 - Translate graph failures to a sanitized API error.
        logger.error(f"Lineage query failed: {e}")
        raise HTTPException(status_code=500, detail="Neo4j Time Travel query failed.")


# ---------------------------------------------------------------------------
# Agent management (rescued from develop)
# ---------------------------------------------------------------------------

_ROLE_RESPONSIBILITIES: dict[str, str] = {
    "PO": "Define and prioritize the product backlog.",
    "Architect": "Design the overall system architecture.",
    "ScrumMaster": "Facilitate sprint ceremonies and remove impediments.",
    "Dev": "Implement features according to acceptance criteria.",
    "BackendDev": "Design and implement server-side logic, APIs, and databases.",
    "FrontendDev": "Build responsive, accessible user interfaces.",
    "FullstackDev": "Deliver features end-to-end across frontend and backend.",
    "QA": "Design and execute test strategies.",
    "DevOps": "Own CI/CD pipelines and infrastructure.",
}


def _build_template_prompt(
    role: str, seniority: str, specialty: str, persona: str
) -> str:
    responsibilities = _ROLE_RESPONSIBILITIES.get(
        role, f"Deliver high-quality work for the {role} discipline."
    )
    return (
        f"You are a {seniority} {role}. {responsibilities} "
        f"Communication style: {persona or 'professional, precise, collaborative'}."
    ).strip()


def _agent_company(session: Session, agent_id: int) -> int:
    """The company an agent belongs to; 404 when there is no such agent."""
    agent = session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    return agent.company_id


@router.get("/agents", tags=["Enterprise"])
async def list_agents(
    company_id: int,
    session: Session = Depends(get_session),  # noqa: B008
    user: User | None = Depends(current_user_if_required),  # noqa: B008
):
    """List all agents for a company (Viewer)."""
    require_company_role(session, user, company_id, "Viewer")
    service = CompanyService(session)
    try:
        return {"agents": service.list_agents(company_id)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/agents", tags=["Enterprise"])
async def create_agent(
    req: AgentCreateRequest,
    session: Session = Depends(get_session),  # noqa: B008
    user: User | None = Depends(current_user_if_required),  # noqa: B008
):
    """Create a new agent configuration (Manager)."""
    require_company_role(session, user, req.company_id, "Manager")
    service = CompanyService(session)
    try:
        return service.create_agent(
            req.company_id, req.model_dump(exclude={"company_id"})
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/agents/generate_prompt", tags=["Enterprise"])
async def generate_agent_prompt(req: AgentPromptRequest):
    """Auto-generate a system prompt for an agent."""
    return {
        "system_prompt": _build_template_prompt(
            req.role, req.seniority, req.specialty, req.persona
        ),
        "source": "template",
    }


@router.patch("/agents/{agent_id}", tags=["Enterprise"])
async def update_agent(
    agent_id: int,
    req: AgentUpdateRequest,
    session: Session = Depends(get_session),  # noqa: B008
    user: User | None = Depends(current_user_if_required),  # noqa: B008
):
    """Update an existing agent configuration (Manager of its company).

    An agent's prompt, model and budget decide what it does for the company,
    so only its Managers change them.
    """
    require_company_role(session, user, _agent_company(session, agent_id), "Manager")
    service = CompanyService(session)
    try:
        return service.update_agent(agent_id, req.model_dump(exclude_unset=True))
    except ValueError as exc:
        status = 404 if "not found" in str(exc).lower() else 422
        raise HTTPException(status_code=status, detail=str(exc))


@router.delete("/agents/{agent_id}", tags=["Enterprise"])
async def delete_agent(
    agent_id: int,
    session: Session = Depends(get_session),  # noqa: B008
    user: User | None = Depends(current_user_if_required),  # noqa: B008
):
    """Delete an existing agent configuration (Manager of its company)."""
    require_company_role(session, user, _agent_company(session, agent_id), "Manager")
    service = CompanyService(session)
    try:
        return service.delete_agent(agent_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
