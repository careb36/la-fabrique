"""Idempotency claims for NATS message handlers.

Why this exists
---------------
NATS gives at-least-once delivery, and our outbox can re-publish on retries
or after a backend restart. Without a claim, two consumers (or one consumer
on a retry) can run the same LangGraph kickoff twice or assign the same
backlog item twice. Both are observable to users and waste model tokens.

Design
------
A single ``processed_events`` table acts as a small persistence layer keyed by
``event_key``. ``claim_event`` does an ``INSERT ... ON CONFLICT DO NOTHING``
and reports whether *this* call won the race. The first claim returns ``True``
and the work proceeds; subsequent claims for the same key return ``False`` and
the consumer skips. Failures fall through (return ``True``) so a transient
database hiccup never blocks the entire pipeline — duplicate execution is the
worse outcome only when it can corrupt state, which is what protected paths +
heartbeats are for separately.

The schema is created additively in ``database._ensure_runtime_schema``.
Old rows are pruned by the existing janitor service.
"""

from __future__ import annotations

import asyncio

from database import engine
from logging_config import logger


def claim_event(event_key: str | None, subject: str) -> bool:
    """Claim *event_key* for *subject*. Return ``True`` if this is the first claim.

    If *event_key* is empty/None we cannot dedupe — log a warning and let the
    caller through. Callers should always pass an event_id (or a deterministic
    composite key) when they care about exactly-once semantics.
    """
    if not event_key:
        logger.debug(
            "idempotency: missing event_key for subject=%s — skipping dedupe", subject
        )
        return True

    try:
        with engine.begin() as conn:
            result = conn.exec_driver_sql(
                "INSERT INTO processed_events (event_key, subject, processed_at) "
                "VALUES (%s, %s, NOW()) ON CONFLICT (event_key) DO NOTHING",
                (event_key, subject),
            )
            claimed = (result.rowcount or 0) > 0
        if not claimed:
            logger.info(
                "idempotency: dropping duplicate %s event_key=%s", subject, event_key
            )
        return claimed
    except Exception as exc:  # noqa: BLE001
        # Never block real work on a dedupe storage failure. Surface the issue
        # in logs so ops can act, but allow the consumer to proceed.
        logger.warning(
            "idempotency: claim failed for subject=%s event_key=%s err=%s — allowing through",
            subject,
            event_key,
            exc,
        )
        return True


def prune_expired(retention_days: int) -> int:
    """Delete ``processed_events`` rows older than *retention_days*.

    Returns the number of rows removed. Errors are logged but not raised so
    the periodic loop never crashes the backend.
    """
    if retention_days <= 0:
        return 0
    try:
        with engine.begin() as conn:
            result = conn.exec_driver_sql(
                "DELETE FROM processed_events "
                "WHERE processed_at < NOW() - (%s || ' days')::interval",
                (str(int(retention_days)),),
            )
            removed = int(result.rowcount or 0)
        if removed:
            logger.info(
                "idempotency: pruned %d processed_events rows older than %d day(s)",
                removed,
                retention_days,
            )
        return removed
    except Exception as exc:  # noqa: BLE001
        logger.warning("idempotency: prune failed: %s", exc)
        return 0


async def run_retention_loop(
    retention_days: int,
    interval_seconds: int,
    *,
    sleep: asyncio.AbstractEventLoop | None = None,
) -> None:
    """Background loop that prunes expired ``processed_events`` rows.

    Started from the FastAPI startup handler so retention is enforced from the
    moment the backend boots. The loop is resilient: any failure inside
    :func:`prune_expired` is swallowed there, and the outer ``while True``
    only exits on cancellation.
    """
    if interval_seconds <= 0:
        return
    while True:
        try:
            await asyncio.to_thread(prune_expired, retention_days)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("idempotency: retention loop iteration failed: %s", exc)
        await asyncio.sleep(interval_seconds)
