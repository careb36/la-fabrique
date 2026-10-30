"""What each spoken instruction does (``POST /v1/voice/command``).

Every handler calls the same endpoint the web app uses, so a spoken order
cannot do more than the web allows.
"""

from uuid import uuid4

from fastapi import HTTPException
from models import BacklogItem, Company, OutboxEvent
from schemas import (
    AgentRunApprovalRequest,
    SprintPlanRequest,
    SprintStartRequest,
)
from services import voice_control
from sqlmodel import select

from routers.agent_runs import approve_run
from routers.sprint import (
    dispatch_sprint_tasks,
    pause_sprint,
    plan_sprint,
    resume_sprint,
    start_sprint,
)
from routers.voice_support import _company, _fail, _result, status_answer

# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


async def _action_status(req, action, language, session, caller):
    return status_answer(session, req.company_id, req.sprint_id, language)


async def _action_companies(req, action, language, session, caller):
    companies = list(session.exec(select(Company).order_by(Company.id)).all())
    if not companies:
        return _fail(
            action,
            language,
            "La fábrica no tiene empresas todavía.",
            "The factory has no companies yet.",
        )
    listing = "; ".join(f"{c.id}: {c.company_name}" for c in companies)
    return _result(
        action,
        voice_control.say(
            language,
            f"Hay {len(companies)} empresas: {listing}.",
            f"There are {len(companies)} companies: {listing}.",
        ),
        {"companies": [{"id": c.id, "name": c.company_name} for c in companies]},
        companies[0].id,
    )


async def _action_team(req, action, language, session, caller):
    company, failure = _company(session, req.company_id, action, language)
    if failure:
        return failure
    agents = voice_control.agent_roster(session, company.id)
    if not agents:
        return _fail(
            action,
            language,
            f"El equipo de {company.company_name} está vacío.",
            f"{company.company_name}'s team is empty.",
            company_id=company.id,
        )
    listing = "; ".join(
        f"{a.name or a.role or 'agente'} ({a.role or 'sin rol'})" for a in agents
    )
    return _result(
        action,
        voice_control.say(
            language,
            f"El equipo de {company.company_name} tiene {len(agents)} agentes: {listing}.",
            f"{company.company_name}'s team has {len(agents)} agents: {listing}.",
        ),
        {
            "agents": [
                {"id": a.id, "name": a.name, "role": a.role, "model": a.model}
                for a in agents
            ]
        },
        company.id,
    )


async def _action_assign(req, action, language, session, caller):
    """Turn a spoken sentence into a task for one agent and dispatch it.

    This is how the assistant "talks to" an agent: the instruction becomes a
    card assigned to that agent's role, and the same ``task.assign`` event the
    web board uses sends it to the worker. A paused sprint keeps the card
    without dispatching — resuming is still the human's decision.
    """
    company, failure = _company(session, req.company_id, action, language)
    if failure:
        return failure
    text = str(req.text or "").strip()
    if not text:
        return _fail(
            action,
            language,
            "Dime qué querés que haga el agente.",
            "Tell me what you want the agent to do.",
            company_id=company.id,
        )
    roster = voice_control.agent_roster(session, company.id)
    if not roster:
        return _fail(
            action,
            language,
            f"El equipo de {company.company_name} está vacío: sin agentes no hay "
            "a quién encargarle nada.",
            f"{company.company_name}'s team is empty: there is nobody to ask.",
            company_id=company.id,
        )
    agent = voice_control.find_agent(session, company.id, req.agent)
    if agent is None and req.agent:
        listing = "; ".join(a.name or a.role or "agente" for a in roster)
        return _fail(
            action,
            language,
            f"No sé a qué agente te referís con «{req.agent}». El equipo es: {listing}.",
            f"I do not know which agent «{req.agent}» is. The team is: {listing}.",
            company_id=company.id,
            data={
                "agents": [{"id": a.id, "name": a.name, "role": a.role} for a in roster]
            },
        )
    if agent is None and len(roster) == 1:
        agent = roster[0]
    if agent is None:
        listing = "; ".join(a.name or a.role or "agente" for a in roster)
        return _fail(
            action,
            language,
            f"¿A cuál agente se lo encargo? El equipo es: {listing}.",
            f"Which agent should take it? The team is: {listing}.",
            company_id=company.id,
            data={
                "agents": [{"id": a.id, "name": a.name, "role": a.role} for a in roster]
            },
        )

    sprint = voice_control.resolve_sprint(session, company.id, req.sprint_id)
    if sprint is None:
        return _fail(
            action,
            language,
            "No hay ningún sprint donde anotar el encargo. Pídeme primero un "
            "sprint nuevo.",
            "There is no sprint to record the request in. Ask me for a new sprint first.",
            company_id=company.id,
        )

    item = BacklogItem(
        sprint_id=sprint.id,
        title=voice_control.instruction_title(text),
        description=text,
        status="todo",
        priority="high",
        assignee=agent.role or agent.name,
    )
    session.add(item)
    session.commit()
    session.refresh(item)

    dispatched = sprint.status != "paused"
    if dispatched:
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
        session.commit()

    name = agent.name or agent.role or "el agente"
    if dispatched:
        speech = voice_control.say(
            language,
            f"Se lo encargué a {name}: «{item.title}». Tarea {item.id} del "
            f"sprint {sprint.id}, ya despachada.",
            f"I handed it to {name}: «{item.title}». Task {item.id} in sprint "
            f"{sprint.id}, already dispatched.",
        )
    else:
        speech = voice_control.say(
            language,
            f"Anoté el encargo para {name}: «{item.title}». Tarea {item.id} en "
            f"el sprint {sprint.id}, que está en pausa: nada corre hasta que "
            "digas «reanuda la fábrica».",
            f"I noted the request for {name}: «{item.title}». Task {item.id} in "
            f"sprint {sprint.id}, which is paused: nothing runs until you say "
            '"resume the factory".',
        )
    return _result(
        action,
        speech,
        {
            "task": {
                "id": item.id,
                "title": item.title,
                "assignee": item.assignee,
                "status": item.status,
            },
            "agent": {"id": agent.id, "name": agent.name, "role": agent.role},
            "sprint_id": sprint.id,
            "dispatched": dispatched,
        },
        company.id,
    )


async def _action_sprints(req, action, language, session, caller):
    company, failure = _company(session, req.company_id, action, language)
    if failure:
        return failure
    sprints = voice_control.sprint_list(session, company.id)
    return _result(
        action,
        voice_control.sprints_speech(sprints, language),
        {"sprints": sprints},
        company.id,
        ok=bool(sprints),
    )


async def _plan(session, company_id, text, scope, caller):
    plan = await plan_sprint(
        req=SprintPlanRequest(company_id=company_id, prompt=text, scope_size=scope),
        session=session,
        user=caller.user,
    )
    if isinstance(plan, dict):
        plan["sprint_name"] = voice_control.sprint_name_for_speech(
            plan.get("sprint_name"), text
        )
    return plan


async def _action_plan(req, action, language, session, caller):
    if not (req.text or "").strip():
        return _fail(
            action,
            language,
            "Dime el objetivo del sprint y te lo planeo.",
            "Tell me the sprint objective and I will plan it.",
        )
    company, failure = _company(session, req.company_id, action, language)
    if failure:
        return failure
    scope = voice_control.normalize_scope(req.scope_size, company.default_scope_size)
    try:
        plan = await _plan(session, company.id, req.text.strip(), scope, caller)
    except HTTPException as exc:
        return _fail(
            action,
            language,
            f"No he podido planearlo: {exc.detail}",
            f"I could not plan it: {exc.detail}",
            company_id=company.id,
        )
    return _result(
        action,
        voice_control.plan_speech(plan, language),
        {"plan": plan, "scope_size": scope},
        company.id,
    )


async def _action_create_sprint(req, action, language, session, caller):
    if not (req.text or "").strip():
        return _fail(
            action,
            language,
            "Dime para qué es el sprint y lo creo.",
            "Tell me what the sprint is for and I will create it.",
        )
    company, failure = _company(session, req.company_id, action, language)
    if failure:
        return failure
    scope = voice_control.normalize_scope(req.scope_size, company.default_scope_size)

    try:
        plan = await _plan(session, company.id, req.text.strip(), scope, caller)
        result = await start_sprint(
            req=SprintStartRequest(
                company_id=company.id,
                sprint_name=(req.sprint_name or plan["sprint_name"])[:70],
                start_date=voice_control.today_iso(),
                scope_size=scope,
                goal=plan.get("goal"),
                backlog_items=list(plan.get("tasks") or []),
            ),
            session=session,
            user=caller.user,
        )
    except HTTPException as exc:
        session.rollback()
        return _fail(
            action,
            language,
            f"No he creado el sprint: {exc.detail}",
            f"I did not create the sprint: {exc.detail}",
            company_id=company.id,
        )

    sprint_id = result["sprint_id"]
    await pause_sprint(sprint_id=sprint_id, session=session, user=caller.user)

    return _result(
        action,
        voice_control.created_speech(sprint_id, plan, language),
        {
            "sprint_id": sprint_id,
            "sprint_name": plan.get("sprint_name"),
            "tasks": len(plan.get("tasks") or []),
            "paused": True,
        },
        company.id,
    )


async def _action_dispatch(req, action, language, session, caller):
    company, failure = _company(session, req.company_id, action, language)
    if failure:
        return failure
    sprint = voice_control.resolve_sprint(session, company.id, req.sprint_id)
    if sprint is None:
        return _fail(
            action,
            language,
            "No hay ningún sprint que despachar.",
            "There is no sprint to dispatch.",
            company_id=company.id,
        )
    if sprint.status == "paused":
        return _fail(
            action,
            language,
            f"El sprint {sprint.id} está en pausa. Dime «reanuda la fábrica» y "
            "después lo despacho.",
            f'Sprint {sprint.id} is paused. Say "resume the factory" and I will dispatch it.',
            company_id=company.id,
        )
    result = await dispatch_sprint_tasks(
        sprint_id=sprint.id, session=session, user=caller.user
    )
    dispatched = int(result.get("dispatched", 0))
    return _result(
        action,
        voice_control.say(
            language,
            f"He despachado {dispatched} tareas del sprint {sprint.id} a los agentes."
            if dispatched
            else f"No había tareas pendientes que despachar en el sprint {sprint.id}.",
            f"I dispatched {dispatched} tasks from sprint {sprint.id} to the agents."
            if dispatched
            else f"There were no pending tasks to dispatch in sprint {sprint.id}.",
        ),
        {"sprint_id": sprint.id, "dispatched": dispatched},
        company.id,
    )


async def _action_pause(req, action, language, session, caller):
    company, failure = _company(session, req.company_id, action, language)
    if failure:
        return failure
    sprint = voice_control.resolve_sprint(session, company.id, req.sprint_id)
    if sprint is None:
        return _fail(
            action,
            language,
            "No hay ningún sprint que pausar.",
            "There is no sprint to pause.",
            company_id=company.id,
        )
    result = await pause_sprint(sprint_id=sprint.id, session=session, user=caller.user)
    already = result.get("status") == "already_paused"
    return _result(
        action,
        voice_control.say(
            language,
            f"El sprint {sprint.id} ya estaba en pausa."
            if already
            else f"Fábrica en pausa. Los agentes no empiezan nada nuevo en el sprint {sprint.id}.",
            f"Sprint {sprint.id} was already paused."
            if already
            else f"Factory paused. The agents start nothing new in sprint {sprint.id}.",
        ),
        {"sprint_id": sprint.id, "status": "paused"},
        company.id,
    )


async def _action_resume(req, action, language, session, caller):
    company, failure = _company(session, req.company_id, action, language)
    if failure:
        return failure
    sprint = voice_control.resolve_sprint(session, company.id, req.sprint_id)
    if sprint is None:
        return _fail(
            action,
            language,
            "No hay ningún sprint que reanudar.",
            "There is no sprint to resume.",
            company_id=company.id,
        )
    result = await resume_sprint(sprint_id=sprint.id, session=session, user=caller.user)
    return _result(
        action,
        voice_control.say(
            language,
            f"Fábrica en marcha otra vez. El sprint {sprint.id} sigue activo.",
            f"Factory running again. Sprint {sprint.id} is active.",
        ),
        {"sprint_id": sprint.id, "status": result.get("status")},
        company.id,
    )


def _action_decide(req, action, language, session, caller):
    company, failure = _company(session, req.company_id, action, language)
    if failure:
        return failure

    pending = voice_control.pending_runs(session, company.id)
    if req.run_id is not None:
        pending = [run for run in pending if run.id == req.run_id]
    if not pending:
        return _fail(
            action,
            language,
            "No hay ninguna entrega esperando tu decisión.",
            "No delivery is waiting for your decision.",
            company_id=company.id,
        )

    run = pending[0]
    approved = action == "aprobar"
    feedback = (req.feedback or "").strip()
    if not approved and not feedback:
        feedback = voice_control.say(
            language, "Rechazada por voz.", "Rejected by voice."
        )

    try:
        approval = approve_run(
            run_id=run.id,
            payload=AgentRunApprovalRequest(
                company_id=company.id,
                approver_name=(req.approver_name or "Asistente de voz").strip(),
                decision="approved" if approved else "rejected",
                feedback=feedback or None,
                rejection_category=None if approved else "other",
            ),
            session=session,
            user=caller.user,
        )
    except HTTPException as exc:
        return _fail(
            action,
            language,
            f"No he podido registrar la decisión: {exc.detail}",
            f"I could not record the decision: {exc.detail}",
            company_id=company.id,
        )

    role = run.agent_role or run.producer
    return _result(
        action,
        voice_control.say(
            language,
            f"He aprobado la entrega {run.id} de {role}."
            if approved
            else f"He rechazado la entrega {run.id} de {role}.",
            f"I approved delivery {run.id} from {role}."
            if approved
            else f"I rejected delivery {run.id} from {role}.",
        ),
        {
            "run_id": run.id,
            "approval_id": approval.id,
            "decision": approval.decision,
        },
        company.id,
    )


async def _action_approve(req, action, language, session, caller):
    return _action_decide(req, action, language, session, caller)


async def _action_reject(req, action, language, session, caller):
    return _action_decide(req, action, language, session, caller)


async def _action_help(req, action, language, session, caller):
    return _result(action, voice_control.help_speech(language))


_HANDLERS = {
    "estado": _action_status,
    "empresas": _action_companies,
    "equipo": _action_team,
    "asignar": _action_assign,
    "sprints": _action_sprints,
    "planear": _action_plan,
    "crear_sprint": _action_create_sprint,
    "despachar": _action_dispatch,
    "pausar": _action_pause,
    "reanudar": _action_resume,
    "aprobar": _action_approve,
    "rechazar": _action_reject,
    "ayuda": _action_help,
}
