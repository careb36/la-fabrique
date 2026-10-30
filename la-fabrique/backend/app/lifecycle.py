"""
Application lifecycle handlers for startup and shutdown events.
"""

import asyncio
import os

from audit_signing import is_signing_enabled
from auth_tokens import is_auth_configured
from config import settings
from crypto import is_encryption_enabled
from database import create_db_and_tables, ensure_memory_graph_schema, get_neo4j_driver
from llm_proxy_client import LLMProxyClient
from logging_config import logger
from memory_client import MemoryClient
from nats_client import NATSClient
from services import console_capabilities
from services.agent_worker import process_agent_tasks
from services.outbox_service import process_outbox
from services.task_worker import process_backlog_tasks

# Retained task references for graceful cancellation on shutdown.
_background_tasks: set[asyncio.Task] = set()

# NATS connection state exposed by the health endpoints.
NATS_STATE_CONNECTING = "connecting"
NATS_STATE_CONNECTED = "connected"
NATS_STATE_DISABLED = "disabled"


def _nats_disabled() -> bool:
    return os.getenv("NATS_DISABLED", "").strip().lower() in {"1", "true", "yes", "on"}


# Reconnect backoff for the initial NATS connection: 1s, 2s, 4s, ... capped.
NATS_CONNECT_BACKOFF_BASE_SECONDS = 1.0
NATS_CONNECT_BACKOFF_MAX_SECONDS = 30.0


def _on_task_done(task: asyncio.Task) -> None:
    """Log unexpected exits from background worker tasks."""
    _background_tasks.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error(
            "Background worker task '%s' exited with an exception: %s",
            task.get_name(),
            exc,
            exc_info=exc,
        )


async def _connect_nats_and_start_workers(app, client: NATSClient) -> None:
    """
    Connect to NATS, retrying forever, then start the background workers once.

    The delay between attempts starts at ``NATS_CONNECT_BACKOFF_BASE_SECONDS``
    and doubles up to ``NATS_CONNECT_BACKOFF_MAX_SECONDS``.  Cancelling the
    task (as ``shutdown`` does) interrupts a pending attempt or sleep.
    """
    delay = NATS_CONNECT_BACKOFF_BASE_SECONDS
    attempt = 0
    while True:
        attempt += 1
        try:
            await client.connect()
            break
        except Exception as exc:  # noqa: BLE001 - Keep retrying; the API stays up in degraded mode.
            logger.warning(
                "NATS unavailable (attempt %d: %s). Agent workflow and SSE "
                "streaming are paused; retrying in %.1fs.",
                attempt,
                exc,
                delay,
            )
            await asyncio.sleep(delay)
            delay = min(delay * 2, NATS_CONNECT_BACKOFF_MAX_SECONDS)

    # Streams must exist before the outbox publishes and the workers consume.
    app.state.jetstream = await client.enable_jetstream()
    app.state.nats_client = client
    app.state.nats_state = NATS_STATE_CONNECTED
    await _start_workers(app, client)


async def _start_workers(app, client: NATSClient) -> None:
    """Start the NATS-dependent background workers, at most once per app."""
    if getattr(app.state, "nats_workers_started", False):
        return
    app.state.nats_workers_started = True

    # Ask the daemon once which console assistants it can run, so the task
    # worker does not wait out a timeout per task for a CLI that is absent.
    if settings.CONSOLE_ASSISTANTS_ENABLED:
        await console_capabilities.probe_console_assistants(client)

    worker_coros = {
        "nats_glassroom_listener": _listen_to_nats(app),
        "outbox_processor": process_outbox(client),
        "agent_worker": process_agent_tasks(client),
        "task_worker": process_backlog_tasks(client),
    }
    for name, coro in worker_coros.items():
        task = asyncio.create_task(coro, name=name)
        _background_tasks.add(task)
        task.add_done_callback(_on_task_done)

    logger.info(
        "NATS connected — background workers started: %s",
        list(worker_coros.keys()),
    )


async def startup(app):
    """
    Application startup handler.

    Always succeeds — NATS and Neo4j connection failures are caught and logged
    as warnings, so DB-only endpoints (discovery, init_company, sprint board,
    etc.) remain available even when those services are not yet running.

    Infrastructure clients are stored on ``app.state`` (not module globals) so
    that request handlers only see them after startup completes.  Callers must
    guard against ``None`` before using NATS/Neo4j features.

    NATS is connected by a background task that retries with exponential
    backoff, so a broker that starts after the backend still brings agents up.
    Once connected, that task starts these workers exactly once:
    - ``_listen_to_nats()`` — subscribes to ``glassroom.>`` for SSE fanout.
    - ``process_outbox()`` — transactional outbox → NATS publisher.
    - ``process_agent_tasks()`` — NATS consumer → LangGraph runner.
    - ``process_backlog_tasks()`` — NATS consumer → backlog task execution.
    """
    logger.info("Initializing Enterprise Backend Components...")
    create_db_and_tables()

    # NATS is required for agent workflow and SSE streaming, but the DB-only
    # endpoints (discovery, init_company, sprints, etc.) must remain available
    # even when the NATS broker is not yet running.  ``app.state.nats_client``
    # stays ``None`` until the connection succeeds.
    app.state.nats_client = None
    app.state.nats_workers_started = False
    app.state.jetstream = False
    if _nats_disabled():
        # Desktop/single-node installs have no broker: skip the reconnect loop
        # so the console is not flooded with tracebacks every few seconds.
        app.state.nats_state = NATS_STATE_DISABLED
        app.state.nats_connect_task = None
        logger.warning(
            "NATS disabled (NATS_DISABLED=true): agents, outbox publishing and "
            "SSE fanout are off; board endpoints work from the database only."
        )
    else:
        app.state.nats_state = NATS_STATE_CONNECTING
        client = NATSClient(os.getenv("NATS_URL", "nats://localhost:4222"))
        connect_task = asyncio.create_task(
            _connect_nats_and_start_workers(app, client), name="nats_connector"
        )
        app.state.nats_connect_task = connect_task
        _background_tasks.add(connect_task)
        connect_task.add_done_callback(_on_task_done)

    # The Support agent needs only the database and the LLM proxy.
    if settings.SUPPORT_AGENT_ENABLED:
        from database import engine
        from services.support_agent import run_support_agent

        support_task = asyncio.create_task(
            run_support_agent(engine), name="support_agent"
        )
        _background_tasks.add(support_task)
        support_task.add_done_callback(_on_task_done)

    # So does the Reviewer agent, which suggests on other producers' runs.
    if settings.REVIEWER_AGENT_ENABLED:
        from database import engine
        from services.reviewer_agent import run_reviewer_agent

        reviewer_task = asyncio.create_task(
            run_reviewer_agent(engine), name="reviewer_agent"
        )
        _background_tasks.add(reviewer_task)
        reviewer_task.add_done_callback(_on_task_done)

    # Neo4j is used for memory search and lineage; degrade gracefully if absent.
    app.state.memory_client = None
    try:
        driver = get_neo4j_driver()
        ensure_memory_graph_schema(driver)
        app.state.memory_client = MemoryClient(neo4j_driver=driver)
        logger.info("Neo4j connected — memory features enabled.")
    except Exception as exc:  # noqa: BLE001 - Start in degraded mode if the optional memory backend fails.
        logger.warning(
            f"Neo4j unavailable at startup ({exc}). "
            "Memory search and lineage endpoints will return errors until Neo4j is reachable."
        )

    app.state.llm_client = LLMProxyClient(
        os.getenv("LLM_PROXY_URL", "http://localhost:5100")
    )

    # Credential encryption degrades gracefully like the services above: without
    # a key the backend still runs, but stored credentials are not encrypted.
    if not is_encryption_enabled():
        logger.warning(
            "FERNET_SECRET_KEY is not configured. Project credentials will be "
            "stored unencrypted with a 'plaintext:' prefix. Generate a key with: "
            'python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"'
        )
    if not is_signing_enabled():
        logger.warning(
            "AUDIT_SIGNING_KEY is not configured. Audit rows will be stored with "
            "an 'unsigned:' prefix. Generate a key with: "
            'python -c "import secrets; print(secrets.token_hex(32))"'
        )

    if not is_auth_configured():
        logger.warning(
            "JWT_SECRET_KEY is not configured. POST /v1/auth/login will return 503 until it is set."
        )


async def shutdown(app):
    """
    Graceful shutdown: cancel background tasks, then drain the NATS connection.

    Cancelling stored task references ensures the outbox poller and NATS
    listener exit cleanly instead of being killed mid-operation.
    """
    logger.info("Initiating graceful shutdown...")

    for task in list(_background_tasks):
        task.cancel()
    if _background_tasks:
        await asyncio.gather(*_background_tasks, return_exceptions=True)

    if app.state.nats_client:
        await app.state.nats_client.close()
    logger.info("Shutdown complete.")


async def _listen_to_nats(app):
    """
    Internal NATS subscriber that bridges Glassroom events to SSE queues.

    Subscribes to the wildcard subject ``glassroom.>`` so that any event
    published to ``glassroom.<sprint_id>`` is picked up here.  If a browser
    client has an active SSE connection for that sprint, the raw JSON payload
    is placed on its ``asyncio.Queue`` and flushed to the response stream.
    """
    from routers.agents import publish_sse_event, sse_connections

    async def callback(msg, data=None):
        subject = msg.subject
        if subject.startswith("glassroom."):
            sprint_id = subject.split(".")[1]
            if sprint_id in sse_connections:
                await publish_sse_event(sprint_id, msg.data.decode())

    try:
        await app.state.nats_client.subscribe("glassroom.>", callback)
    except Exception as e:  # noqa: BLE001 - A streaming subscription failure must not abort startup.
        logger.error(f"Failed to subscribe to Glassroom events: {e}")
