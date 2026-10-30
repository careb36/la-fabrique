"""Structured event envelope helpers for GlassRoom and outbox publishing.

Every operational event in La Fabrique must carry the same correlation fields
so that GlassRoom, logs, and audit can be joined end-to-end:

- ``event_id``       — unique per emission, used for idempotency.
- ``interaction_id`` — workflow-level correlation across agent turns.
- ``sprint_id``      — sprint scope when the event applies to one.
- ``task_id``        — backlog item when the event applies to a single card.
- ``role`` / ``agent`` — who emitted the event.
- ``model``          — actual LLM model used (when applicable).
- ``timestamp``      — UTC ISO-8601.

This module exposes a single helper, :func:`build_event`, which is intentionally
non-strict: it injects an ``event_id`` and timestamp, fills missing fields with
``None``, and records which correlation fields were missing on the event itself
under ``correlation_missing``. Callers stay simple, but downstream consumers
(GlassRoom, log search, support) can clearly see when an event lacks context
instead of silently losing the trail.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

logger = logging.getLogger("fabrique-events")

# Required correlation fields. ``role`` and ``interaction_id`` are mandatory in
# practice; ``sprint_id`` / ``task_id`` are situational and only flagged when
# the caller is one of the sprint/task code paths.
_BASE_REQUIRED = ("role", "interaction_id")


def build_event(
    *,
    event_type: str,
    role: str,
    interaction_id: str | None = None,
    sprint_id: Any | None = None,
    task_id: Any | None = None,
    semantic_type: str | None = None,
    semantic_version: int = 1,
    source: str = "backend",
    agent: str | None = None,
    model: str | None = None,
    message: str | None = None,
    extra: dict[str, Any] | None = None,
    require_sprint: bool = False,
    require_task: bool = False,
) -> dict[str, Any]:
    """Build a normalized event payload with required correlation fields.

    Missing-but-required fields are reported on the event itself as
    ``correlation_missing`` and logged at WARNING. We never drop the event —
    silent dropping is far worse for ops than a noisy event.
    """
    payload: dict[str, Any] = {
        "event_id": str(uuid4()),
        "type": event_type,
        "semantic_type": semantic_type or event_type,
        "semantic_version": semantic_version,
        "source": source,
        "role": role,
        "agent": agent or role,
        "interaction_id": interaction_id or "unknown",
        "sprint_id": sprint_id,
        "task_id": task_id,
        "model": model,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    if message is not None:
        payload["message"] = message
    if extra:
        for key, value in extra.items():
            # Caller-provided keys win unless they collide with reserved fields
            # set above. ``setdefault`` preserves the envelope contract.
            payload.setdefault(key, value)

    required = list(_BASE_REQUIRED)
    if require_sprint:
        required.append("sprint_id")
    if require_task:
        required.append("task_id")

    missing = [
        field for field in required if payload.get(field) in (None, "", "unknown")
    ]
    if missing:
        payload["correlation_missing"] = missing
        logger.warning(
            "event missing correlation fields: type=%s missing=%s role=%s sprint=%s task=%s",
            event_type,
            missing,
            role,
            sprint_id,
            task_id,
        )
    return payload


def ensure_envelope(
    event: dict[str, Any], *, source: str = "backend"
) -> dict[str, Any]:
    """Backfill missing envelope fields on a pre-built event dict.

    Used at the publish boundary so existing callers that built dicts manually
    still produce events with ``event_id``, ``timestamp``, and a stable shape.
    Mutates and returns the same dict for convenience.
    """
    event.setdefault("event_id", str(uuid4()))
    event.setdefault("source", source)
    event.setdefault("semantic_version", 1)
    event.setdefault("timestamp", datetime.now(UTC).isoformat())

    role = event.get("role") or event.get("agent")
    if role:
        event.setdefault("role", role)
        event.setdefault("agent", role)

    interaction_id = event.get("interaction_id")
    if not interaction_id:
        event["interaction_id"] = "unknown"
        # Flag, but never drop.
        missing = list(event.get("correlation_missing") or [])
        if "interaction_id" not in missing:
            missing.append("interaction_id")
            event["correlation_missing"] = missing
        logger.debug(
            "event missing interaction_id at publish boundary: type=%s sprint=%s task=%s",
            event.get("type"),
            event.get("sprint_id"),
            event.get("task_id"),
        )
    return event
