"""
Transactional Outbox processor for reliable NATS message delivery.

Background worker that continuously polls the ``outbox_events`` table for
pending rows and publishes them to NATS, ensuring at-least-once delivery.
For durable subjects (``task.assign``) a row is marked completed only after
JetStream has stored the message, so it reaches the task worker even if the
worker is down at that moment.

Why the outbox pattern?
-----------------------
A naive approach (publish to NATS inside the HTTP handler) risks data loss if
the process crashes after the database transaction commits but before the NATS
message is sent.  The outbox pattern solves this by writing the event to the
database **in the same transaction** as the domain change, then delivering it
asynchronously from here.

Concurrency safety:
-------------------
``SELECT ... FOR UPDATE SKIP LOCKED`` acquires row-level locks so that multiple
worker replicas running in Kubernetes never process the same event simultaneously.
On SQLite (the tests, or a DATABASE_URL install) the clause is skipped: the engine has no row
locks, and a single process owns the loop.

Retry policy:
-------------
- Up to 5 delivery attempts per event.
- After 5 failures the row is marked ``"failed"`` and excluded from future polls.
- A ``retry_count`` column tracks the number of failed attempts.
"""

import asyncio
import json
from datetime import UTC, datetime

from database import IS_SQLITE, engine
from logging_config import logger
from sqlmodel import Session, text


def _utc_now() -> datetime:
    """Naive UTC, what the ``processed_at`` column stores."""
    return datetime.now(UTC).replace(tzinfo=None)


async def process_outbox(nats_client) -> None:
    """
    Background coroutine that drains the ``outbox_events`` table into NATS.

    Intended to run for the entire application lifetime as an ``asyncio.Task``
    (started in ``main.startup``).

    Args:
        nats_client: Active ``NATSClient`` instance used for publishing.
                     The loop sleeps and retries until the client is available.
    """
    while True:
        # Wait until the NATS client is ready (e.g. after application startup).
        if not nats_client:
            await asyncio.sleep(2)
            continue

        try:
            with Session(engine) as session:
                # Fetch up to 10 pending events; SKIP LOCKED prevents worker
                # conflicts. SQLite has no row locks and rejects the clause
                # outright, so a SQLite engine polls without it — it runs a
                # single outbox loop, and SQLite serialises the writers anyway.
                rows = session.exec(
                    text(
                        """
                        SELECT id, event_type, payload, retry_count
                        FROM outbox_events
                        WHERE status = 'pending'
                        ORDER BY created_at ASC
                        """
                        + ("" if IS_SQLITE else "FOR UPDATE SKIP LOCKED")
                        + """
                        LIMIT 10
                        """
                    )
                ).all()

                if rows:
                    logger.debug("Outbox: processing %d pending event(s)", len(rows))

                for event_id, event_type, payload_str, retries in rows:
                    try:
                        payload = (
                            json.loads(payload_str)
                            if isinstance(payload_str, str)
                            else payload_str
                        )

                        if event_type == "nats_publish":
                            subject = payload["subject"]
                            message = payload["message"]
                            logger.info(
                                "Outbox dispatching event_id=%s subject=%s sprint_id=%s item_id=%s",
                                event_id,
                                subject,
                                message.get("sprint_id"),
                                message.get("backlog_item_id"),
                            )
                            # Publish the inner message to the specified NATS subject.
                            # Durable subjects return only once JetStream has
                            # stored the message; the id makes a retry after a
                            # lost acknowledgement a no-op.
                            await nats_client.publish(
                                subject, message, msg_id=f"outbox-{event_id}"
                            )

                        # Mark the event as successfully delivered.
                        # A bound timestamp instead of NOW(): the function is
                        # Postgres-only and the tests run on SQLite.
                        session.exec(
                            text(
                                "UPDATE outbox_events SET status = 'completed', "
                                "processed_at = :now WHERE id = :id"
                            ).bindparams(id=event_id, now=_utc_now())
                        )
                        logger.debug("Outbox event_id=%s marked completed", event_id)
                    except Exception as row_e:  # noqa: BLE001 - Retain failed rows for retry without stopping delivery.
                        logger.error(
                            "Failed to process outbox event_id=%s (retry=%d): %s",
                            event_id,
                            retries,
                            row_e,
                            exc_info=True,
                        )
                        # Increment retry counter; mark as failed after 5 attempts.
                        session.exec(
                            text(
                                """
                                UPDATE outbox_events
                                SET retry_count = retry_count + 1,
                                    status = CASE WHEN retry_count >= 5 THEN 'failed' ELSE 'pending' END,
                                    processed_at = :now
                                WHERE id = :id
                                """
                            ).bindparams(id=event_id, now=_utc_now())
                        )

                session.commit()

        except Exception as e:  # noqa: BLE001 - Keep the outbox polling loop alive across failures.
            logger.error(f"Outbox processor error: {e}")

        # Poll every 2 seconds — keeps end-to-end NATS latency low.
        await asyncio.sleep(2)
