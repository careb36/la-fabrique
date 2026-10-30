"""
Agent Worker — NATS consumer for LangGraph workflow execution.

Listens for ``workspace.generate`` events and invokes the corresponding
LangGraph agent graph asynchronously so agent turns can publish GlassRoom
events in real time while the workflow is still running.
"""

import json
import logging
from datetime import UTC, datetime

from config import settings
from database import engine
from models import Sprint
from nats_client import NATSClient
from sqlmodel import Session

from agents.graph import run_fabrique_workflow

logger = logging.getLogger("fabrique-worker")


def _mark_sprint_needs_split(sprint_id: int) -> None:
    """Update sprint status to needs_split in DB.

    Called only for an explicit split decision (a workflow result with
    ``needs_split`` and no error); a failed kickoff keeps the sprint active.
    """
    try:
        with Session(engine) as session:
            sprint = session.get(Sprint, sprint_id)
            if sprint and sprint.status == "active":
                sprint.status = "needs_split"
                session.add(sprint)
                session.commit()
    except Exception as exc:  # noqa: BLE001 - Failure bookkeeping must not mask the original worker error.
        logger.warning("Could not mark sprint %s as needs_split: %s", sprint_id, exc)


async def _publish_glassroom_error(
    nats_client: NATSClient,
    sprint_id: int | str | None,
    interaction_id: str,
    error_msg: str,
) -> None:
    """Emit a red error event to the Glassroom SSE stream for the given sprint."""
    if not sprint_id:
        return
    try:
        await nats_client.publish(
            f"glassroom.{sprint_id}",
            {
                "type": "error",
                "agent": "System",
                "role": "System",
                "task": f"LangGraph workflow ({interaction_id})",
                "message": f"❌ LangGraph workflow failed: {error_msg}",
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )
    except Exception as pub_err:  # noqa: BLE001 - Glassroom notifications are best-effort.
        logger.warning("Failed to publish Glassroom error event: %s", pub_err)


async def _publish_glassroom_info(
    nats_client: NATSClient,
    sprint_id: int | str | None,
    interaction_id: str,
    message: str,
    event_type: str = "info",
    semantic_type: str | None = None,
) -> None:
    """Emit an informational event to the Glassroom SSE stream for the given sprint."""
    if not sprint_id:
        return
    event = {
        "type": event_type,
        "agent": "System",
        "role": "System",
        "task": f"LangGraph workflow ({interaction_id})",
        "message": message,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    if semantic_type:
        event["semantic_type"] = semantic_type
    try:
        await nats_client.publish(f"glassroom.{sprint_id}", event)
    except Exception as pub_err:  # noqa: BLE001 - Glassroom notifications are best-effort.
        logger.warning("Failed to publish Glassroom info event: %s", pub_err)


async def process_agent_tasks(nats_client: NATSClient) -> None:
    """
    Background loop that subscribes to ``workspace.generate`` and runs workflows.

    Each incoming message is processed in a dedicated thread via
    ``asyncio.to_thread()`` so the event loop is never blocked by the
    synchronous LangGraph execution.  On any failure, a structured error event
    is published to the Glassroom SSE stream so the user sees a clear red message
    rather than silent inactivity.
    """

    async def task_callback(msg, data=None):
        if data is None:
            data = {}
        interaction_id = "unknown"
        sprint_id = None
        try:
            if not data:
                raw = msg.data.decode()
                logger.debug("workspace.generate raw payload: %.200s", raw)
                data = json.loads(raw)

            subject = msg.subject
            if subject != "workspace.generate":
                return

            story = data.get("story")
            files = data.get("files")
            interaction_id = data.get("interaction_id", "unknown")
            bu_id = data.get("business_unit_id")
            sprint_id = data.get(
                "sprint_id"
            )  # included when triggered from task_worker
            po_feedback = data.get(
                "po_feedback"
            )  # present when re-dispatched after PO rejection

            if files and not story:
                # The task worker's file deliveries share this subject; they
                # are for the workspace daemon, not the agent graph.
                logger.debug(
                    "Ignoring workspace.generate file materialization payload: interaction_id=%s files=%s",
                    interaction_id,
                    len(files),
                )
                return

            if not settings.AGENT_GRAPH_ENABLED:
                message = "AGENT_GRAPH_ENABLED is false; the internal agent graph is disabled."
                logger.info(
                    "AGENT_GRAPH_ENABLED is false; ignoring workspace.generate interaction_id=%s",
                    interaction_id,
                )
                await _publish_glassroom_info(
                    nats_client, sprint_id, interaction_id, message
                )
                return

            logger.info(
                "workspace.generate received: interaction_id=%s bu_id=%s sprint_id=%s story=%.80s",
                interaction_id,
                bu_id,
                sprint_id,
                story,
            )

            if not story:
                logger.warning(
                    "workspace.generate message missing 'story' field — skipping: %s",
                    data,
                )
                return

            result = await run_fabrique_workflow(
                story=story,
                bu_id=bu_id,
                sprint_id=sprint_id,
                company_id=data.get("company_id"),
                nats_client=nats_client,
                interaction_id=interaction_id,
                po_feedback=po_feedback,
            )

            # The kickoff is only a conversation; backlog tasks run on their own
            # in the task worker.  A failed kickoff (an agent node error, or a
            # workflow-level error) must not block the sprint, so it stays
            # ``active`` and only an explicit split decision sets needs_split.
            kickoff_error = result.get("error") or result.get("last_error")
            if kickoff_error:
                logger.error(
                    "Sprint kickoff failed for interaction_id=%s sprint_id=%s: %s; "
                    "sprint stays active and tasks continue",
                    interaction_id,
                    sprint_id,
                    kickoff_error,
                )
                await _publish_glassroom_info(
                    nats_client,
                    sprint_id,
                    interaction_id,
                    f"Kickoff failed: {kickoff_error}; tasks continue",
                    event_type="status",
                    semantic_type="kickoff.failed",
                )
            elif result.get("needs_split") and sprint_id:
                _mark_sprint_needs_split(sprint_id)
                logger.warning(
                    "Sprint sprint_id=%s marked needs_split after workflow interaction_id=%s",
                    sprint_id,
                    interaction_id,
                )
            else:
                logger.info(
                    "LangGraph workflow completed: interaction_id=%s engram_id=%s needs_split=%s",
                    interaction_id,
                    result.get("engram_id"),
                    result.get("needs_split"),
                )

        except Exception as e:
            logger.exception(
                "Fatal error in workspace.generate handler (interaction_id=%s): %s",
                interaction_id,
                e,  # noqa: TRY401 - Preserve the existing log message as well as its traceback.
            )
            await _publish_glassroom_error(
                nats_client,
                sprint_id,
                interaction_id,
                f"{type(e).__name__}: {e}",
            )

    logger.info("Agent Worker subscribing to workspace.generate")
    await nats_client.subscribe("workspace.generate", task_callback)
    logger.info("Agent Worker subscribed to workspace.generate — ready.")
