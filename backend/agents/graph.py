"""Multi-agent LangGraph orchestration for sprint kickoff conversations."""

import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional
from typing_extensions import Annotated, TypedDict
from uuid import uuid4

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.errors import GraphRecursionError

from agents.tools.openproject_tools import create_work_package
from llm_proxy_client import LLMProxyClient
from llm.model_factory import AgentRole, ModelFactory
from memory.engram_processor import get_engram_processor
from telemetry import configure_telemetry, get_tracer
from opentelemetry.trace import StatusCode

configure_telemetry("agent-worker")
tracer = get_tracer(__name__)
logger = logging.getLogger("fabrique-agents")

PublishEvent = Callable[[dict[str, Any]], Awaitable[None]]


class AgentState(TypedDict):
    interaction_id: str
    company_id: Optional[int]
    business_unit_id: Optional[int]
    sprint_id: Optional[int]
    story: str
    backlog_items: list[str]
    messages: Annotated[list[AnyMessage], add_messages]
    next_agent: str
    openproject_ticket_id: Optional[str]
    engram_id: Optional[Any]
    last_error: Optional[str]
    needs_split: Optional[bool]
    created_at: str
    publish_event: Optional[PublishEvent]
    po_feedback: Optional[str]


def _resolve_model_name(role: str) -> str:
    try:
        return ModelFactory.ROLE_MODEL_MAP[AgentRole(role)].model_name
    except Exception:
        return ModelFactory.ROLE_MODEL_MAP[AgentRole.DEVELOPER].model_name


def _message_text(message: AnyMessage) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    return str(content)


def _message_name(message: AnyMessage) -> str:
    explicit_name = getattr(message, "name", None)
    if explicit_name:
        return str(explicit_name)
    message_type = getattr(message, "type", "message")
    if message_type == "human":
        return "User"
    if message_type == "system":
        return "System"
    return "Agent"


def _transcript(messages: list[AnyMessage]) -> str:
    lines: list[str] = []
    for message in messages:
        lines.append(f"{_message_name(message)}: {_message_text(message)}")
    return "\n".join(lines[-12:])


def _extract_backlog(story: str) -> list[str]:
    items: list[str] = []
    for raw_line in story.splitlines():
        line = raw_line.strip()
        if line.startswith(("- ", "* ")):
            items.append(line[2:].strip())
    return items


async def _publish(state: AgentState, event: dict[str, Any]) -> None:
    publish_event = state.get("publish_event")
    sprint_id = state.get("sprint_id")
    if not publish_event or sprint_id is None:
        return
    payload = dict(event)
    payload.setdefault("event_id", str(uuid4()))
    payload.setdefault("source", "langgraph")
    payload.setdefault("semantic_version", 1)
    payload.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    await publish_event(payload)


async def _invoke_agent(
    state: AgentState,
    role: str,
    task: str,
    prompt: str,
) -> str:
    await _publish(
        state,
        {
            "type": "agent_start",
            "semantic_type": "kickoff.agent_started",
            "agent": role,
            "role": role,
            "task_status": "kickoff",
            "phase": "kickoff",
            "task": task,
            "message": f"{role} is thinking about: {task}",
        },
    )

    client = LLMProxyClient()
    result = await client.chat_async(
        messages=[
            {
                "role": "system",
                "content": f"You are {role} in a sprint orchestration. Keep answers concrete, operational, and aware of prior messages.",
            },
            {"role": "user", "content": prompt},
        ],
        model=_resolve_model_name(role),
        role=role,
        bu_id=state.get("business_unit_id"),
    )

    if result.get("error"):
        raise RuntimeError(str(result["error"]))

    if result.get("quota_warning"):
        await _publish(
            state,
            {
                "type": "quota.warning",
                "semantic_type": "quota.warning",
                "agent": "System",
                "role": "System",
                "task_status": "kickoff",
                "phase": "kickoff",
                "task": task,
                "message": f"⚠️ Token quota usage is above 80% (used={result.get('quota_used')}, limit={result.get('quota_limit')}). Consider resetting the quota or splitting the sprint.",
                "quota_used": result.get("quota_used"),
                "quota_limit": result.get("quota_limit"),
            },
        )

    content = (
        result.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
        .strip()
    )

    await _publish(
        state,
        {
            "type": "message",
            "semantic_type": "kickoff.agent_message",
            "agent": role,
            "role": role,
            "task_status": "kickoff",
            "phase": "kickoff",
            "task": task,
            "message": content,
        },
    )
    await _publish(
        state,
        {
            "type": "agent_complete",
            "semantic_type": "kickoff.agent_completed",
            "agent": role,
            "role": role,
            "task_status": "kickoff",
            "phase": "kickoff",
            "task": task,
            "message": f"{role} finished: {task}",
        },
    )
    return content


async def kickoff_node(state: AgentState) -> dict[str, Any]:
    await _publish(
        state,
        {
            "type": "status",
            "semantic_type": "kickoff.started",
            "agent": "System",
            "role": "System",
            "task_status": "kickoff",
            "phase": "kickoff",
            "task": "Sprint kickoff",
            "message": "Sprint orchestration started. PO, Architect, Scrum Master, and Developer are joining the conversation.",
        },
    )
    messages: list[AnyMessage] = [SystemMessage(content="Sprint kickoff started.")]

    # Retrieve relevant memory from past sprints and inject into planning context.
    try:
        processor = get_engram_processor()
        memory_context = processor.query_relevant_engrams(state["story"], limit=4, company_id=state.get("company_id"))
        if memory_context:
            messages.append(SystemMessage(content=f"Relevant memory from past sprints:\n{memory_context}"))
            await _publish(
                state,
                {
                    "type": "status",
                    "semantic_type": "kickoff.memory_retrieved",
                    "agent": "System",
                    "role": "System",
                    "task_status": "kickoff",
                    "phase": "memory_retrieved",
                    "task": "Sprint kickoff",
                    "message": "Memory retrieved from past sprints — context injected into agent planning.",
                },
            )
    except Exception as exc:
        logger.warning("Memory retrieval at kickoff failed (non-fatal): %s", exc)

    return {
        "messages": messages,
        "backlog_items": state.get("backlog_items") or _extract_backlog(state["story"]),
        "next_agent": "PO",
        "last_error": None,
    }


async def po_node(state: AgentState) -> dict[str, Any]:
    with tracer.start_as_current_span("graph.po") as span:
        span.set_attribute("agent.role", "PO")
        span.set_attribute("sprint.id", str(state.get("sprint_id") or ""))
        span.set_attribute("company.id", str(state.get("company_id") or ""))
        try:
            backlog_items = state.get("backlog_items") or _extract_backlog(state["story"])
            first_ticket = backlog_items[0] if backlog_items else state["story"].splitlines()[0]
            tool_result = await create_work_package(
                {
                    "project_id": 1,
                    "subject": first_ticket[:120],
                    "description": state["story"],
                    "interaction_id": state["interaction_id"],
                    "sprint_id": state.get("sprint_id"),
                },
                publish_event=lambda event: _publish(state, event),
            )
            prompt = (
                f"Sprint brief:\n{state['story']}\n\n"
                f"Conversation so far:\n{_transcript(state['messages'])}\n\n"
                f"Backlog anchor ticket: {tool_result.get('work_package_id')}\n"
                "As PO, prioritize the sprint, call out the riskiest item, and give one clear instruction to the Scrum Master."
            )
            content = await _invoke_agent(state, "PO", "Prioritize sprint backlog", prompt)
            return {
                "messages": [AIMessage(content=content, name="PO")],
                "next_agent": "ScrumMaster",
                "openproject_ticket_id": str(tool_result.get("work_package_id")),
                "backlog_items": backlog_items,
                "last_error": None,
            }
        except Exception as exc:
            await _publish(
                state,
                {
                    "type": "error",
                    "semantic_type": "kickoff.agent_failed",
                    "agent": "PO",
                    "role": "PO",
                    "task_status": "kickoff",
                    "phase": "kickoff",
                    "task": "Prioritize sprint backlog",
                    "message": f"PO failed: {exc}",
                },
            )
            span.set_status(StatusCode.ERROR, str(exc))
            return {"last_error": str(exc), "next_agent": "burn"}


async def architect_node(state: AgentState) -> dict[str, Any]:
    with tracer.start_as_current_span("graph.architect") as span:
        span.set_attribute("agent.role", "Architect")
        span.set_attribute("sprint.id", str(state.get("sprint_id") or ""))
        span.set_attribute("company.id", str(state.get("company_id") or ""))
        try:
            backlog_items = state.get("backlog_items") or []
            items_text = "\n".join(f"- {i}" for i in backlog_items) if backlog_items else "(see sprint brief)"
            prompt = (
                f"Sprint brief:\n{state['story']}\n\n"
                f"Conversation so far:\n{_transcript(state['messages'])}\n\n"
                f"Backlog items:\n{items_text}\n\n"
                "As Architect, define the technical approach for this sprint: "
                "key design decisions, data model or interface changes, integration points, "
                "and architectural constraints or risks the team must respect. "
                "Be concrete — one clear paragraph per concern. No verbose preamble."
            )
            content = await _invoke_agent(state, "Architect", "Define technical approach", prompt)
            return {
                "messages": [AIMessage(content=content, name="Architect")],
                "next_agent": "ScrumMaster",
                "last_error": None,
            }
        except Exception as exc:
            await _publish(
                state,
                {
                    "type": "error",
                    "semantic_type": "kickoff.agent_failed",
                    "agent": "Architect",
                    "role": "Architect",
                    "task_status": "kickoff",
                    "phase": "kickoff",
                    "task": "Define technical approach",
                    "message": f"Architect failed: {exc}",
                },
            )
            span.set_status(StatusCode.ERROR, str(exc))
            return {"last_error": str(exc), "next_agent": "burn"}


async def scrum_master_node(state: AgentState) -> dict[str, Any]:
    with tracer.start_as_current_span("graph.scrum_master") as span:
        span.set_attribute("agent.role", "ScrumMaster")
        span.set_attribute("sprint.id", str(state.get("sprint_id") or ""))
        span.set_attribute("company.id", str(state.get("company_id") or ""))
        try:
            prompt = (
                f"Sprint brief:\n{state['story']}\n\n"
                f"Conversation so far:\n{_transcript(state['messages'])}\n\n"
                f"OpenProject ticket: {state.get('openproject_ticket_id') or 'pending'}\n"
                "As Scrum Master, coordinate sequencing, identify one blocker, and assign the first execution move to the Developer."
            )
            content = await _invoke_agent(state, "ScrumMaster", "Coordinate sprint execution", prompt)
            return {
                "messages": [AIMessage(content=content, name="ScrumMaster")],
                "next_agent": "Developer",
                "last_error": None,
            }
        except Exception as exc:
            await _publish(
                state,
                {
                    "type": "error",
                    "agent": "ScrumMaster",
                    "role": "ScrumMaster",
                    "task": "Coordinate sprint execution",
                    "message": f"Scrum Master failed: {exc}",
                },
            )
            span.set_status(StatusCode.ERROR, str(exc))
            return {"last_error": str(exc), "next_agent": "burn"}


async def developer_node(state: AgentState) -> dict[str, Any]:
    with tracer.start_as_current_span("graph.developer") as span:
        span.set_attribute("agent.role", "Developer")
        span.set_attribute("sprint.id", str(state.get("sprint_id") or ""))
        span.set_attribute("company.id", str(state.get("company_id") or ""))
        try:
            prompt = (
                f"Sprint brief:\n{state['story']}\n\n"
                f"Conversation so far:\n{_transcript(state['messages'])}\n\n"
                "As Developer, pick up the first actionable item, state exactly what you will implement first, and mention any dependency or unblock request."
            )
            content = await _invoke_agent(state, "Developer", "Pick up first sprint task", prompt)
            return {
                "messages": [AIMessage(content=content, name="Developer")],
                "next_agent": "PO_WRAP",
                "last_error": None,
            }
        except Exception as exc:
            await _publish(
                state,
                {
                    "type": "error",
                    "agent": "Developer",
                    "role": "Developer",
                    "task": "Pick up first sprint task",
                    "message": f"Developer failed: {exc}",
                },
            )
            span.set_status(StatusCode.ERROR, str(exc))
            return {"last_error": str(exc), "next_agent": "burn"}


async def po_wrap_node(state: AgentState) -> dict[str, Any]:
    with tracer.start_as_current_span("graph.po_wrap") as span:
        span.set_attribute("agent.role", "PO")
        span.set_attribute("sprint.id", str(state.get("sprint_id") or ""))
        span.set_attribute("company.id", str(state.get("company_id") or ""))
        try:
            prompt = (
                f"Conversation so far:\n{_transcript(state['messages'])}\n\n"
                "As PO, close the kickoff by summarizing priority, owner, and next immediate action in 3 compact bullets."
            )
            content = await _invoke_agent(state, "PO", "Close sprint kickoff", prompt)
            return {
                "messages": [AIMessage(content=content, name="PO")],
                "next_agent": "burn",
                "last_error": None,
            }
        except Exception as exc:
            await _publish(
                state,
                {
                    "type": "error",
                    "agent": "PO",
                    "role": "PO",
                    "task": "Close sprint kickoff",
                    "message": f"PO wrap-up failed: {exc}",
                },
            )
            span.set_status(StatusCode.ERROR, str(exc))
            return {"last_error": str(exc), "next_agent": "burn"}


async def burn_node(state: AgentState) -> dict[str, Any]:
    summary = _transcript(state["messages"])
    last_error = state.get("last_error")
    sprint_id = state.get("sprint_id")

    try:
        processor = get_engram_processor()
        result = processor.burn_engram(
            company_id=state.get("company_id"),
            agent_id=f"orchestrator_{state['interaction_id']}",
            role="PO",
            decision_summary=summary[:4000],
            metadata={
                "interaction_id": state["interaction_id"],
                "sprint_id": sprint_id,
                "needs_split": False,
                "kickoff_failed": bool(last_error),
            },
        )
        engram_id = result.get("engram_id")
    except Exception as exc:
        logger.warning("Could not burn engram for interaction_id=%s: %s", state["interaction_id"], exc)
        engram_id = None

    if last_error:
        # A node error is a failed kickoff, not a decision to split the sprint.
        # The agent worker reports it to the Glassroom and keeps the sprint
        # active, because backlog tasks run independently of the kickoff.
        logger.warning(
            "Sprint kickoff failed sprint_id=%s interaction_id=%s error=%s",
            sprint_id,
            state["interaction_id"],
            last_error,
        )
    else:
        await _publish(
            state,
            {
                "type": "status",
                "semantic_type": "kickoff.completed",
                "agent": "System",
                "role": "System",
                "task": "Sprint kickoff",
                "task_status": "kickoff_complete",
                "phase": "kickoff",
                "message": "Sprint kickoff conversation finished. Background sprint execution continues on the board and task workers.",
            },
        )

    return {"engram_id": engram_id, "needs_split": False}


def _route_from(state: AgentState, fallback: str, success: str) -> str:
    if state.get("last_error"):
        return fallback
    return success


def _route_entry(state: AgentState) -> str:
    """Route to rejection_node if PO feedback is present, otherwise start with kickoff."""
    if state.get("po_feedback"):
        return "rejection"
    return "kickoff"


async def rejection_node(state: AgentState) -> dict[str, Any]:
    """
    Process PO rejection feedback and route to the appropriate agent for revision.

    Reads ``state["po_feedback"]``, announces the rejection in the GlassRoom,
    then delegates to the Developer (code changes) or Architect (design concerns)
    based on a lightweight keyword heuristic on the feedback text.
    """
    with tracer.start_as_current_span("graph.rejection") as span:
        feedback = state.get("po_feedback", "")
        span.set_attribute("sprint.id", str(state.get("sprint_id") or ""))
        span.set_attribute("company.id", str(state.get("company_id") or ""))
        span.set_attribute("po_feedback.length", len(feedback))

        await _publish(
            state,
            {
                "type": "status",
                "semantic_type": "hitl.rejection_received",
                "agent": "System",
                "role": "System",
                "task_status": "rejected",
                "phase": "rejection",
                "task": "Process PO rejection feedback",
                "message": f"🔄 PO rejected task. Re-routing with feedback: {feedback[:200]}",
            },
        )

        # Route to Architect for design/scope concerns, Developer otherwise.
        design_keywords = {"architect", "design", "scope", "interface", "schema", "model", "api"}
        route_to = "architect" if any(kw in feedback.lower() for kw in design_keywords) else "developer"

        try:
            prompt = (
                f"Sprint brief:\n{state['story']}\n\n"
                f"Conversation so far:\n{_transcript(state['messages'])}\n\n"
                f"⚠️ PO REJECTION FEEDBACK: {feedback}\n\n"
                f"As {'Architect' if route_to == 'architect' else 'Developer'}, "
                "address the PO's specific concerns point-by-point and propose a revised approach."
            )
            role = "Architect" if route_to == "architect" else "Developer"
            content = await _invoke_agent(state, role, "Address PO rejection feedback", prompt)
            return {
                "messages": [AIMessage(content=content, name=role)],
                "next_agent": "po_wrap",
                "last_error": None,
                "po_feedback": None,  # Clear feedback after processing
            }
        except Exception as exc:
            span.set_status(StatusCode.ERROR, str(exc))
            return {"last_error": str(exc), "next_agent": "burn"}


def create_agent_graph():
    workflow = StateGraph(AgentState)
    workflow.add_node("kickoff", kickoff_node)
    workflow.add_node("po", po_node)
    workflow.add_node("architect", architect_node)
    workflow.add_node("scrum_master", scrum_master_node)
    workflow.add_node("developer", developer_node)
    workflow.add_node("po_wrap", po_wrap_node)
    workflow.add_node("burn", burn_node)
    workflow.add_node("rejection", rejection_node)

    workflow.set_conditional_entry_point(_route_entry, {"kickoff": "kickoff", "rejection": "rejection"})
    workflow.add_edge("kickoff", "po")
    workflow.add_conditional_edges("po", lambda state: _route_from(state, "burn", "architect"))
    workflow.add_conditional_edges("architect", lambda state: _route_from(state, "burn", "scrum_master"))
    workflow.add_conditional_edges("scrum_master", lambda state: _route_from(state, "burn", "developer"))
    workflow.add_conditional_edges("developer", lambda state: _route_from(state, "burn", "po_wrap"))
    workflow.add_conditional_edges("rejection", lambda state: _route_from(state, "burn", "po_wrap"))
    workflow.add_edge("po_wrap", "burn")
    workflow.add_edge("burn", END)
    return workflow.compile()


async def run_fabrique_workflow(
    story: str,
    role: str = "Developer",
    bu_id: Optional[int] = None,
    sprint_id: Optional[int] = None,
    company_id: Optional[int] = None,
    nats_client: Any = None,
    interaction_id: Optional[str] = None,
    po_feedback: Optional[str] = None,
) -> dict[str, Any]:
    interaction_id = interaction_id or str(uuid4())

    async def publish_event(event: dict[str, Any]) -> None:
        if not nats_client or sprint_id is None:
            return
        await nats_client.publish(f"glassroom.{sprint_id}", event)

    initial_state: AgentState = {
        "interaction_id": interaction_id,
        "company_id": company_id,
        "business_unit_id": bu_id,
        "sprint_id": sprint_id,
        "story": story,
        "backlog_items": _extract_backlog(story),
        "messages": [HumanMessage(content=story, name="User")],
        "next_agent": role,
        "openproject_ticket_id": None,
        "engram_id": None,
        "last_error": None,
        "needs_split": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "publish_event": publish_event,
        "po_feedback": po_feedback,
    }

    logger.info(
        "Starting multi-agent workflow interaction_id=%s sprint_id=%s role=%s story=%.80s",
        interaction_id,
        sprint_id,
        role,
        story,
    )

    try:
        graph = create_agent_graph()
        result = await graph.ainvoke(
            initial_state,
            config={
                "configurable": {"thread_id": interaction_id},
                # 6 fixed nodes × 2 safety margin = 12. Keep limit at execution time
                # for compatibility with older LangGraph versions.
                "recursion_limit": 16,
            },
        )
        logger.info(
            "Workflow completed interaction_id=%s sprint_id=%s engram_id=%s needs_split=%s",
            interaction_id,
            sprint_id,
            result.get("engram_id"),
            result.get("needs_split"),
        )
        if company_id is None:
            logger.info(
                "Skipping AgentRun ingestion without company_id interaction_id=%s",
                interaction_id,
            )
        else:
            try:
                from sqlmodel import Session

                import database
                from models.agent_run import GRAPH_PRODUCER
                from schemas import AgentRunCreate
                from services import agent_run_service

                summary_message = next(
                    (
                        message
                        for message in reversed(result.get("messages", []))
                        if _message_name(message) == "PO"
                    ),
                    result.get("messages", [])[-1]
                    if result.get("messages")
                    else None,
                )
                payload = AgentRunCreate(
                    company_id=company_id,
                    external_ref=f"graph:{interaction_id}",
                    producer=GRAPH_PRODUCER,
                    model=_resolve_model_name("Developer"),
                    agent_role="Developer",
                    subject={
                        "sprint_id": sprint_id,
                        "business_unit_id": bu_id,
                        "backlog_items": result.get("backlog_items"),
                    },
                    claims={
                        "summary": _message_text(summary_message)
                        if summary_message
                        else "",
                        "engram_id": result.get("engram_id"),
                        "needs_split": result.get("needs_split"),
                    },
                    artifact=_transcript(result.get("messages", [])),
                    started_at=datetime.fromisoformat(initial_state["created_at"]),
                    finished_at=datetime.now(timezone.utc),
                )
                with Session(database.engine) as session:
                    agent_run_service.ingest_agent_run(session, payload)
            except Exception as exc:
                logger.warning(
                    "AgentRun ingestion failed for graph interaction_id=%s: %s",
                    interaction_id,
                    exc,
                    exc_info=True,
                )
        return result
    except GraphRecursionError as exc:
        # A runaway kickoff conversation is a failed kickoff, not a split
        # decision; the agent worker reports it and keeps the sprint active.
        logger.error(
            "Workflow RECURSION LIMIT hit interaction_id=%s sprint_id=%s — kickoff failed",
            interaction_id,
            sprint_id,
        )
        return {
            **initial_state,
            "error": f"GraphRecursionError: {exc}",
            "engram_id": None,
            "needs_split": False,
        }
    except Exception as exc:
        logger.error(
            "Workflow FATAL ERROR interaction_id=%s: %s",
            interaction_id,
            exc,
            exc_info=True,
        )
        if nats_client and sprint_id is not None:
            await nats_client.publish(
                f"glassroom.{sprint_id}",
                {
                    "type": "error",
                    "agent": "System",
                    "role": "System",
                    "task": "Sprint kickoff",
                    "message": f"LangGraph workflow failed: {type(exc).__name__}: {exc}",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )
        return {
            **initial_state,
            "error": f"{type(exc).__name__}: {exc}",
            "engram_id": None,
            "needs_split": False,
        }
