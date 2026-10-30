"""
NATS messaging client for Fabrique Enterprise Backend.

Wraps the ``nats`` async library with a simplified interface for
publish / subscribe / request-reply patterns used throughout the platform.

NATS subjects in use:
- ``task.assign``          — new backlog item assigned to an agent.
- ``task.update``          — backlog item metadata changed.
- ``task.progress``        — status transition on a work package.
- ``workspace.generate``   — VS Code Daemon: write generated files.
- ``workspace.execute``    — VS Code Daemon: run shell commands.
- ``glassroom.<sprint_id>``— real-time event feed consumed by the SSE endpoint.
- ``audit.write``          — append an entry to the audit log.
- ``system.maintenance.*`` — internal ops events (e.g. error ticket creation).
- ``workspace.deliver``    — files queued for the daemon while it was offline.
- ``workspace.delivered``  — the daemon's per-file result for a queued delivery.

Durability
----------
Work that must survive a consumer being down — task assignments and queued
deliveries — goes through JetStream streams (see ``DURABLE_STREAMS``) when the
server has JetStream enabled: a publish returns only once the server has
stored the message, and a durable consumer receives it whenever it next runs.
Without JetStream the client falls back to core publish/subscribe, which
drops messages nobody is listening for.
"""

import asyncio
import contextlib
import json
import os
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import nats
from logging_config import setup_logger
from nats.errors import TimeoutError as NATSTimeoutError
from nats.js import api as js_api
from nats.js.errors import BadRequestError

logger = setup_logger("fabrique-nats")


@dataclass(frozen=True)
class DurableStream:
    name: str
    subjects: tuple[str, ...]
    # How long an unconsumed message is kept before the server discards it.
    max_age_seconds: float = 7 * 24 * 3600
    # Publishes repeating a ``Nats-Msg-Id`` inside this window are stored once.
    duplicate_window_seconds: float = 15 * 60


# Work-queue streams: a message is removed once its consumer acknowledges it.
# The workspace daemon declares the two workspace streams with the same
# settings, so whichever process starts first creates them.
DURABLE_STREAMS: tuple[DurableStream, ...] = (
    DurableStream("FABRIQUE_TASKS", ("task.assign",)),
    DurableStream("FABRIQUE_DELIVERIES", ("workspace.deliver",)),
    DurableStream("FABRIQUE_DELIVERY_RESULTS", ("workspace.delivered",)),
)
DURABLE_SUBJECTS = frozenset(
    subject for stream in DURABLE_STREAMS for subject in stream.subjects
)


def _namespace() -> str:
    """
    Prefix that separates this deployment's JetStream state from another's.

    Stream and consumer names are global to a NATS server, and these streams
    use work-queue retention: each message goes to exactly one consumer. Two
    deployments pointed at the same broker with the same names therefore do not
    merely duplicate work — they swallow each other's messages, and the loser
    sees a task that was published and never handled. That is what happened
    when the e2e run shared the compose stack's broker.

    Set ``NATS_NAMESPACE`` (for example ``e2e``) to keep the two apart. Empty —
    the default — keeps the historical names, so a single stack is unchanged.
    """
    raw = os.getenv("NATS_NAMESPACE", "").strip()
    if not raw:
        return ""
    # Stream names allow alphanumerics, ``-`` and ``_`` only.
    return re.sub(r"[^A-Za-z0-9_-]", "_", raw).strip("_")


def _scoped(name: str) -> str:
    """Return *name* prefixed with the deployment namespace, if one is set."""
    namespace = _namespace()
    return f"{namespace}_{name}" if namespace else name


def _scoped_subject(subject: str) -> str:
    """
    Namespace a durable subject, or leave it alone when no namespace is set.

    Streaming only the *names* would not isolate anything: two work-queue
    streams bound to the same subject each store every message, so both stacks
    would still process it. The subject has to differ too.
    """
    namespace = _namespace()
    return f"{namespace}.{subject}" if namespace else subject


def _stream_config(stream: DurableStream) -> js_api.StreamConfig:
    return js_api.StreamConfig(
        name=_scoped(stream.name),
        subjects=[_scoped_subject(subject) for subject in stream.subjects],
        retention=js_api.RetentionPolicy.WORK_QUEUE,
        storage=js_api.StorageType.FILE,
        max_age=stream.max_age_seconds,
        duplicate_window=stream.duplicate_window_seconds,
    )


class NATSClient:
    """
    Async NATS connection wrapper for publish/subscribe operations.

    Lifecycle:
    1. Instantiate with the target NATS server URL.
    2. Await ``connect()`` before calling any other method.
    3. Await ``close()`` during application shutdown to drain subscriptions.

    Attributes:
        nats_url: NATS server connection string (e.g. ``nats://localhost:4222``).
        nc: Underlying ``nats.NATS`` connection; ``None`` before ``connect()``.
        subscriptions: Map of subject pattern → asyncio Task for active listeners.
    """

    def __init__(self, nats_url: str | None = None):
        self.nats_url = nats_url or os.getenv("NATS_URL", "nats://localhost:4222")
        self.nc: nats.NATS | None = None
        # Tracks running listener tasks so they can be cancelled on shutdown.
        self.subscriptions: dict[str, asyncio.Task] = {}
        # Set by ``enable_jetstream`` once the durable streams exist.
        self.js = None

    async def connect(self):
        """
        Establish a connection to the NATS server.

        Raises:
            Exception: Propagated from the ``nats`` library if the server is
                       unreachable or authentication fails.
        """
        try:
            self.nc = await nats.connect(self.nats_url)
            logger.info(f"Connected to NATS at {self.nats_url}")
        except Exception as e:
            logger.error(f"Failed to connect to NATS: {e}")
            raise

    @property
    def jetstream_enabled(self) -> bool:
        return self.js is not None

    async def enable_jetstream(self) -> bool:
        """
        Create (or update) the durable streams and switch durable subjects to them.

        Returns ``False`` — and leaves the client on core NATS — when the server
        has no JetStream (``nats-server`` started without ``-js``).
        """
        if not self.nc:
            raise RuntimeError("NATS not connected")
        js = self.nc.jetstream()
        try:
            for stream in DURABLE_STREAMS:
                config = _stream_config(stream)
                try:
                    await js.add_stream(config)
                except BadRequestError:
                    # The stream exists with other settings (an older release).
                    await js.update_stream(config)
        except Exception as e:  # noqa: BLE001 - Any JetStream failure means core NATS only.
            logger.warning(
                "JetStream unavailable (%s: %s). Task assignments and queued "
                "deliveries use core NATS and are lost if no consumer is "
                "listening. Start nats-server with -js to make them durable.",
                type(e).__name__,
                e,
            )
            self.js = None
            return False
        self.js = js
        logger.info(
            "JetStream enabled: durable streams %s",
            ", ".join(stream.name for stream in DURABLE_STREAMS),
        )
        return True

    async def publish(
        self, subject: str, payload: dict[str, Any], *, msg_id: str | None = None
    ):
        """
        Publish a JSON-serialisable payload to a NATS subject.

        Durable subjects go to their JetStream stream when JetStream is enabled;
        the call returns once the server has stored the message and raises if
        it could not.  *msg_id* (``Nats-Msg-Id``) makes a repeated publish
        within the stream's duplicate window a no-op.

        Args:
            subject: NATS subject string (e.g. ``"task.assign"``).
            payload: Dictionary that will be JSON-encoded before sending.
            msg_id:  Optional de-duplication id for durable subjects.

        Raises:
            RuntimeError: If called before ``connect()``.
        """
        if not self.nc:
            raise RuntimeError("NATS not connected")

        data = json.dumps(payload).encode()
        if self.js is not None and subject in DURABLE_SUBJECTS:
            headers = {"Nats-Msg-Id": msg_id} if msg_id else None
            ack = await self.js.publish(_scoped_subject(subject), data, headers=headers)
            # Durable payloads can carry whole files; log the receipt only.
            logger.info(
                "Stored %s in %s (seq=%s%s)",
                subject,
                ack.stream,
                ack.seq,
                ", duplicate" if ack.duplicate else "",
            )
            return
        await self.nc.publish(subject, data)
        logger.info(f"Published to {subject}: {payload}")

    async def consume(
        self,
        subject: str,
        durable: str,
        callback: Callable[[Any, dict[str, Any]], Awaitable[None]],
        *,
        ack_wait_seconds: float = 600.0,
        max_deliver: int = 5,
    ):
        """
        Process every message on a durable *subject*, including ones published
        while this process was down.

        With JetStream this is a durable pull consumer named *durable* (prefixed
        with ``NATS_NAMESPACE`` when set): replicas
        sharing the name split the work, a message is acknowledged after
        *callback* returns, and one whose callback raises is redelivered (up to
        *max_deliver* times).  While *callback* runs the message is kept
        claimed, so slow work is not redelivered to another replica.  Without
        JetStream it is a core subscription in queue group *durable*.
        """
        if not self.nc:
            raise RuntimeError("NATS not connected")
        stream = next((s.name for s in DURABLE_STREAMS if subject in s.subjects), None)
        if self.js is None or stream is None:
            await self.subscribe(subject, callback, queue=_scoped(durable))
            return

        scoped_stream, scoped_durable = _scoped(stream), _scoped(durable)
        scoped_subject = _scoped_subject(subject)
        config = js_api.ConsumerConfig(
            durable_name=scoped_durable,
            deliver_policy=js_api.DeliverPolicy.ALL,
            ack_policy=js_api.AckPolicy.EXPLICIT,
            ack_wait=ack_wait_seconds,
            max_deliver=max_deliver,
            filter_subject=scoped_subject,
        )
        psub = await self.js.pull_subscribe(
            scoped_subject, durable=scoped_durable, stream=scoped_stream, config=config
        )
        task = asyncio.create_task(
            self._consume(psub, callback, ack_wait_seconds, max_deliver)
        )
        self.subscriptions[f"{scoped_subject}#{scoped_durable}"] = task
        logger.info(
            "Consuming %s from %s as %s", scoped_subject, scoped_stream, scoped_durable
        )

    async def _consume(self, psub, callback, ack_wait_seconds, max_deliver):
        while True:
            try:
                msgs = await psub.fetch(1, timeout=5)
            except (NATSTimeoutError, TimeoutError):
                continue
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 - Keep consuming across reconnects.
                logger.warning("Durable fetch failed (%s); retrying", e)
                await asyncio.sleep(2)
                continue
            for msg in msgs:
                await self._handle_durable(msg, callback, ack_wait_seconds, max_deliver)

    async def _handle_durable(self, msg, callback, ack_wait_seconds, max_deliver):
        try:
            data = json.loads(msg.data.decode())
        except (ValueError, UnicodeDecodeError):
            logger.error("Discarding malformed message on %s", msg.subject)
            await msg.term()
            return

        async def _keep_claimed():
            while True:
                await asyncio.sleep(max(ack_wait_seconds / 3, 1))
                with contextlib.suppress(Exception):
                    await msg.in_progress()

        keepalive = asyncio.create_task(_keep_claimed())
        try:
            await callback(msg, data)
        except asyncio.CancelledError:
            # Left unacknowledged: redelivered after ack_wait.
            raise
        except Exception as e:
            delivered = msg.metadata.num_delivered
            logger.exception(
                "Error processing %s (delivery %d/%d): %s",
                msg.subject,
                delivered,
                max_deliver,
                e,  # noqa: TRY401 - Keep the message as well as the traceback.
            )
            with contextlib.suppress(Exception):
                if delivered >= max_deliver:
                    await msg.term()
                else:
                    await msg.nak(delay=min(30 * delivered, 300))
            return
        finally:
            keepalive.cancel()
        await msg.ack()

    async def subscribe(
        self, subject: str, callback: Callable, queue: str | None = None
    ):
        """
        Subscribe to a subject pattern and dispatch messages to *callback*.

        Each subscription spawns a background ``asyncio.Task`` stored in
        ``self.subscriptions``.  Queue group support is provided via the
        optional *queue* parameter (load-balancing across multiple workers).

        Args:
            subject: NATS subject or wildcard (e.g. ``"glassroom.>"``).
            callback: Async callable invoked for each received message.
            queue:    Optional NATS queue group name for competing consumers.

        Raises:
            RuntimeError: If called before ``connect()``.
        """
        if not self.nc:
            raise RuntimeError("NATS not connected")

        sub = await self.nc.subscribe(subject, queue=queue)
        task = asyncio.create_task(self._listen(sub, callback))
        self.subscriptions[subject] = task
        logger.info(f"Subscribed to {subject}")

    async def _listen(self, sub, callback: Callable):
        """
        Internal coroutine that continuously reads messages from *sub* and
        forwards them to *callback*.

        Per-message exceptions are caught and logged so that a single bad
        message does not terminate the listener loop.  An outer try/except
        catches unexpected failures from the async generator itself (e.g. a
        NATS server disconnect) so the task exits with a clear log entry
        rather than a silent, unobservable cancellation.
        """
        try:
            async for msg in sub.messages:
                try:
                    data = json.loads(msg.data.decode())
                    await callback(msg, data)
                except asyncio.CancelledError:
                    raise  # Let cancellation propagate normally on shutdown.
                except Exception as e:
                    logger.exception(
                        "Error processing NATS message on subject=%s: %s",
                        getattr(msg, "subject", "?"),
                        e,  # noqa: TRY401 - Preserve the existing log message as well as its traceback.
                    )
        except asyncio.CancelledError:
            logger.info("NATS _listen task cancelled (normal shutdown).")
            raise
        except Exception as outer_err:
            logger.exception(
                "NATS _listen loop exited unexpectedly (subscription lost?): %s",
                outer_err,  # noqa: TRY401 - Preserve the existing log message as well as its traceback.
            )

    async def request(
        self, subject: str, payload: dict[str, Any], timeout: float = 5.0
    ) -> dict[str, Any]:
        """
        Send a request and block until a reply is received (request-reply pattern).

        Args:
            subject: Target NATS subject.
            payload: JSON-serialisable request body.
            timeout: Seconds to wait for a reply before raising ``TimeoutError``.

        Returns:
            Decoded JSON response dictionary.

        Raises:
            RuntimeError: If called before ``connect()``.
            nats.errors.TimeoutError: If no reply arrives within *timeout*.
        """
        if not self.nc:
            raise RuntimeError("NATS not connected")

        data = json.dumps(payload).encode()
        msg = await self.nc.request(subject, data, timeout=timeout)
        return json.loads(msg.data.decode())

    async def close(self):
        """
        Gracefully shut down all subscriptions and the NATS connection.

        Cancels every listener task before draining the connection, ensuring
        that in-flight messages are not silently dropped.
        """
        for task in self.subscriptions.values():
            task.cancel()
        if self.nc:
            await self.nc.close()
        logger.info("NATS connection closed")
