"""
Publishing to the Glassroom: the per-sprint real-time stream the UI follows.

Every worker that reports progress on a sprint publishes on
``glassroom.<sprint_id>``; the SSE endpoint in ``routers/agents.py`` relays it.
Publishing is best-effort: a failure is logged and never interrupts the work
being reported on.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from logging_config import setup_logger
from nats_client import NATSClient

logger = setup_logger("fabrique-glassroom")


async def publish_glassroom(
    nats_client: NATSClient,
    sprint_id: int,
    event: dict[str, Any],
) -> None:
    """Publish a real-time event to the Glassroom SSE stream for a sprint."""
    try:
        event.setdefault("event_id", str(uuid4()))
        event.setdefault("source", "backend")
        event.setdefault("semantic_version", 1)
        event["timestamp"] = datetime.now(UTC).isoformat()
        await nats_client.publish(f"glassroom.{sprint_id}", event)
    except Exception as e:  # noqa: BLE001 - Glassroom notifications are best-effort.
        logger.warning("Failed to publish glassroom event: %s", e)
