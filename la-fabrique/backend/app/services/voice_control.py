"""Read models and spoken sentences for the voice façade.

The desktop assistant (JARVIS / MARK LVI) drives the factory through
``/v1/voice/*``. A spoken instruction only needs three things from this side:
what the company's board looks like, which deliveries wait for a person, and a
sentence short enough to be read out loud. All of it lives here so the router
stays a thin adapter over the same router functions the web UI calls.

Nothing here writes: the mutating actions are the existing endpoints
(``start_sprint``, ``pause_sprint``, ``approve_run`` …), called by the router so
a voice instruction cannot drift from the web product's validation.
"""

from datetime import UTC, datetime

from models import Agent, BacklogItem, Company, Sprint
from models.agent_run import IN_HOUSE_PRODUCERS, AgentRun, AgentRunApproval
from sqlmodel import Session, select

COUNT_KEYS = ("todo", "in_progress", "in_review", "done", "blocked")

# Spoken verb -> canonical action. The assistant is told one vocabulary; the
# aliases are here because a model paraphrases the word it was given.
VOICE_ACTIONS = {
    "estado": "estado",
    "status": "estado",
    "estado_fabrica": "estado",
    "empresas": "empresas",
    "empresa": "empresas",
    "equipo": "equipo",
    "agentes": "equipo",
    "planear": "planear",
    "plan": "planear",
    "crear_sprint": "crear_sprint",
    "nuevo_sprint": "crear_sprint",
    "despachar": "despachar",
    "dispatch": "despachar",
    "pausar": "pausar",
    "pause": "pausar",
    "reanudar": "reanudar",
    "resume": "reanudar",
    "aprobar": "aprobar",
    "approve": "aprobar",
    "rechazar": "rechazar",
    "reject": "rechazar",
    "sprints": "sprints",
    "sprint_list": "sprints",
    "listar_sprints": "sprints",
    "asignar": "asignar",
    "pedir": "asignar",
    "hablar_con_agente": "asignar",
    "encargar": "asignar",
    "ayuda": "ayuda",
    "help": "ayuda",
}


def normalize_language(value: str | None) -> str:
    """``es``/``en`` only; anything else falls back to Spanish (the default)."""
    text = str(value or "").strip().lower()
    return "en" if text.startswith("en") else "es"


def say(language: str, es: str, en: str) -> str:
    return en if normalize_language(language) == "en" else es


def normalize_scope(value: str | None, default: str = "M") -> str:
    text = str(value or "").strip().upper()[:1]
    return text if text in {"S", "M", "L"} else default


def resolve_company(session: Session, company_id: int | None) -> Company | None:
    """The company a spoken instruction is about.

    An explicit id must exist; otherwise the configured default is used and,
    absent one, the oldest company — the only sensible answer on the
    single-tenant install this assistant is built for.
    """
    if company_id is not None:
        return session.get(Company, company_id)
    return session.exec(select(Company).order_by(Company.id)).first()


def resolve_sprint(
    session: Session, company_id: int, sprint_id: int | None
) -> Sprint | None:
    """The named sprint, else the newest one still running, else the newest."""
    if sprint_id is not None:
        sprint = session.get(Sprint, sprint_id)
        return sprint if sprint and sprint.company_id == company_id else None

    running = session.exec(
        select(Sprint)
        .where(
            Sprint.company_id == company_id,
            Sprint.status.in_(("active", "paused")),
        )
        .order_by(Sprint.id.desc())
    ).first()
    if running is not None:
        return running
    return session.exec(
        select(Sprint).where(Sprint.company_id == company_id).order_by(Sprint.id.desc())
    ).first()


def board_counts(session: Session, sprint_id: int) -> dict[str, int]:
    counts = dict.fromkeys(COUNT_KEYS, 0)
    items = session.exec(
        select(BacklogItem).where(BacklogItem.sprint_id == sprint_id)
    ).all()
    for item in items:
        key = item.status if item.status in counts else "todo"
        counts[key] += 1
    return counts


def blocked_titles(session: Session, sprint_id: int, limit: int = 3) -> list[str]:
    items = session.exec(
        select(BacklogItem)
        .where(BacklogItem.sprint_id == sprint_id, BacklogItem.status == "blocked")
        .order_by(BacklogItem.id)
    ).all()
    return [item.title for item in items[:limit]]


def pending_runs(session: Session, company_id: int) -> list[AgentRun]:
    """Runs from other producers that still wait for a person's decision.

    The factory's own producers are decided by the review loop, so only runs
    ingested from elsewhere appear here — the same rule the inbox uses.
    """
    runs = session.exec(
        select(AgentRun)
        .where(AgentRun.company_id == company_id)
        .order_by(AgentRun.id.desc())
    ).all()
    decided = set(
        session.exec(
            select(AgentRunApproval.agent_run_id).where(
                AgentRunApproval.company_id == company_id
            )
        ).all()
    )
    return [
        run
        for run in runs
        if run.id not in decided and run.producer not in IN_HOUSE_PRODUCERS
    ]


def agent_roster(session: Session, company_id: int) -> list[Agent]:
    return list(
        session.exec(
            select(Agent).where(Agent.company_id == company_id).order_by(Agent.id)
        ).all()
    )


def find_agent(session: Session, company_id: int, hint: str | None) -> Agent | None:
    """The agent behind a spoken name: id, exact name, then a contained match.

    A model repeats what it heard ("R2", "la QA"), so the fallback is a
    substring match on name and role — the last one wins only when it is
    unambiguous.
    """
    text = str(hint or "").strip().lower()
    if not text:
        return None
    roster = agent_roster(session, company_id)
    if text.isdigit():
        for agent in roster:
            if agent.id == int(text):
                return agent
    for agent in roster:
        if (agent.name or "").strip().lower() == text:
            return agent
    matches = [
        agent
        for agent in roster
        if text in (agent.name or "").lower() or text in (agent.role or "").lower()
    ]
    return matches[0] if len(matches) == 1 else None


def instruction_title(text: str, limit: int = 80) -> str:
    """The backlog title for a spoken instruction: its first sentence, trimmed."""
    clean = " ".join(str(text or "").split())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1].rstrip() + "…"


def sprint_list(session: Session, company_id: int, limit: int = 5) -> list[dict]:
    """The newest sprints, newest first: what "¿qué sprints tengo?" answers."""
    sprints = session.exec(
        select(Sprint)
        .where(Sprint.company_id == company_id)
        .order_by(Sprint.id.desc())
        .limit(limit)
    ).all()
    return [{"id": s.id, "name": s.sprint_name, "status": s.status} for s in sprints]


def sprints_speech(sprints: list[dict], language: str | None) -> str:
    if not sprints:
        return say(
            language,
            "Todavía no hay sprints. Dime un objetivo y te preparo el primero.",
            "There are no sprints yet. Give me an objective and I will plan the first one.",
        )
    states_es = {
        "active": "en marcha",
        "paused": "en pausa",
        "needs_split": "pendiente de dividir",
        "completed": "terminado",
        "cancelled": "cancelado",
    }
    states_en = {
        "active": "running",
        "paused": "paused",
        "needs_split": "waiting to be split",
        "completed": "completed",
        "cancelled": "cancelled",
    }
    states = states_en if normalize_language(language) == "en" else states_es
    listing = "; ".join(
        f"{s['id']} «{s['name']}» ({states.get(s['status'], s['status'])})"
        for s in sprints
    )
    count = len(sprints)
    plural = "s" if count != 1 else ""
    return say(
        language,
        f"Tienes {count} sprint{plural}, del más nuevo al más viejo: {listing}.",
        f"You have {count} sprint{plural}, newest first: {listing}.",
    )


def status_snapshot(session: Session, company: Company, sprint_id: int | None = None):
    sprint = resolve_sprint(session, company.id, sprint_id)
    counts = (
        board_counts(session, sprint.id) if sprint else dict.fromkeys(COUNT_KEYS, 0)
    )
    return {
        "company": {"id": company.id, "name": company.company_name},
        "sprint": (
            {
                "id": sprint.id,
                "name": sprint.sprint_name,
                "status": sprint.status,
                "goal": sprint.goal,
                "scope_size": sprint.scope_size,
            }
            if sprint
            else None
        ),
        "counts": counts,
        "blocked": blocked_titles(session, sprint.id) if sprint else [],
        "pending_approvals": len(pending_runs(session, company.id)),
        "total": sum(counts.values()),
    }


def status_speech(snapshot: dict, language: str | None) -> str:
    company = snapshot["company"]["name"]
    sprint = snapshot["sprint"]
    counts = snapshot["counts"]

    if sprint is None:
        return say(
            language,
            f"La fábrica de {company} no tiene ningún sprint todavía. "
            "Dime el objetivo y te preparo el primero.",
            f"The {company} factory has no sprint yet. Tell me the objective and I will plan the first one.",
        )

    state_es = {
        "active": "en marcha",
        "paused": "en pausa",
        "needs_split": "pendiente de dividir",
        "completed": "terminado",
        "cancelled": "cancelado",
    }.get(sprint["status"], sprint["status"])
    state_en = {
        "active": "running",
        "paused": "paused",
        "needs_split": "waiting to be split",
        "completed": "completed",
        "cancelled": "cancelled",
    }.get(sprint["status"], sprint["status"])

    numbers_es = (
        f"{counts['todo']} pendientes, {counts['in_progress']} en curso, "
        f"{counts['in_review']} en revisión, {counts['done']} terminadas "
        f"y {counts['blocked']} bloqueadas"
    )
    numbers_en = (
        f"{counts['todo']} to do, {counts['in_progress']} in progress, "
        f"{counts['in_review']} in review, {counts['done']} done "
        f"and {counts['blocked']} blocked"
    )

    speech = say(
        language,
        f"Sprint {sprint['id']} «{sprint['name']}» está {state_es}: {numbers_es}.",
        f'Sprint {sprint["id"]} "{sprint["name"]}" is {state_en}: {numbers_en}.',
    )

    blocked = snapshot["blocked"]
    if blocked:
        listed = "; ".join(blocked)
        speech += say(
            language,
            f" Lo bloqueado es: {listed}.",
            f" Blocked: {listed}.",
        )

    pending = snapshot["pending_approvals"]
    if pending:
        speech += say(
            language,
            f" Hay {pending} entrega{'s' if pending != 1 else ''} esperando tu aprobación.",
            f" {pending} deliver{'ies' if pending != 1 else 'y'} waiting for your approval.",
        )

    return speech


def sprint_name_for_speech(name: str | None, objective: str = "") -> str:
    """Drop the planner's ``Sprint - `` prefix.

    The spoken sentence already carries the id (``Sprint 2 «…»``), so keeping
    the planner's default prefix reads as ``Sprint 2 «Sprint - Add login»``.
    """
    text = str(name or "").strip()
    for prefix in ("Sprint - ", "Sprint: ", "Sprint — "):
        if text[: len(prefix)].lower() == prefix.lower():
            text = text[len(prefix) :].strip()
            break
    if not text:
        text = str(objective or "").strip() or "Execution"
    return text[:70]


def plan_speech(plan: dict, language: str | None) -> str:
    tasks = plan.get("tasks") or []
    titles = "; ".join(str(task.get("title", "")) for task in tasks[:4])
    more = len(tasks) - 4
    suffix_es = f" y {more} más" if more > 0 else ""
    suffix_en = f" and {more} more" if more > 0 else ""

    return say(
        language,
        f"He preparado el sprint «{plan.get('sprint_name', '')}» con {len(tasks)} "
        f"tareas: {titles}{suffix_es}. "
        f"Objetivo: {plan.get('goal', '')}. ¿Lo creo?",
        f'I have planned the sprint "{plan.get("sprint_name", "")}" with {len(tasks)} '
        f"tasks: {titles}{suffix_en}. "
        f"Goal: {plan.get('goal', '')}. Shall I create it?",
    )


def created_speech(sprint_id: int, plan: dict, language: str | None) -> str:
    return say(
        language,
        f"He creado el sprint {sprint_id} «{plan.get('sprint_name', '')}» con "
        f"{len(plan.get('tasks') or [])} tareas, pero lo he dejado EN PAUSA para "
        "que nada empiece sin tu permiso. Di «reanuda la fábrica» cuando quieras "
        "que los agentes se pongan a trabajar.",
        f'I created sprint {sprint_id} "{plan.get("sprint_name", "")}" with '
        f"{len(plan.get('tasks') or [])} tasks, but left it PAUSED so nothing "
        'starts without your permission. Say "resume the factory" when you want '
        "the agents to begin.",
    )


def help_speech(language: str | None) -> str:
    return say(
        language,
        "Puedo decirte cómo va la fábrica, planear un sprint desde un objetivo, "
        "crearlo, despachar las tareas, pausar y reanudar, aprobar o rechazar "
        "entregas, listar los sprints y el equipo. Por ejemplo: «¿cómo va la "
        "fábrica?», "
        "«crea un sprint para el login con Google», «pausa la fábrica».",
        "I can report on the factory, plan a sprint from an objective, create it, "
        "dispatch the tasks, pause and resume, approve or reject deliveries, and "
        'list the sprints and the team. For example: "how is the factory doing?", '
        '"create a sprint for Google login", "pause the factory".',
    )


def today_iso() -> str:
    return datetime.now(UTC).date().isoformat()
