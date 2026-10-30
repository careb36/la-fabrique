"""
The backend keeps retrying NATS and starts its workers once connected (issue #103).

No broker is needed: ``NATSClient`` and the four workers are replaced with
fakes, and the backoff base is shrunk so the retries take milliseconds.

Run with:
    cd backend && PYTHONPATH=.:app python3 -m pytest tests/test_nats_connect_retry.py -q
"""

import asyncio
import time
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import lifecycle
import pytest


class _FlakyNATSClient:
    """Fails ``connect`` a set number of times, then succeeds."""

    def __init__(self, failures: int):
        self.failures = failures
        self.connect_calls = 0
        self.nc = None
        self.subscriptions = {}
        self.closed = False

    async def connect(self):
        self.connect_calls += 1
        if self.connect_calls <= self.failures:
            raise ConnectionRefusedError("nats not up yet")
        self.nc = object()

    async def enable_jetstream(self):
        return False

    async def request(self, subject, payload, timeout=5.0):
        return {"assistants": []}

    async def close(self):
        self.closed = True


async def _wait_until(predicate, timeout: float = 1.0) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.005)
    return predicate()


def _patch_startup(stack: ExitStack, client, base_delay: float) -> dict:
    workers = {
        name: stack.enter_context(patch(f"lifecycle.{name}", new=AsyncMock()))
        for name in (
            "_listen_to_nats",
            "process_outbox",
            "process_agent_tasks",
            "process_backlog_tasks",
        )
    }
    stack.enter_context(patch("lifecycle.create_db_and_tables", return_value=None))
    stack.enter_context(
        patch("lifecycle.get_neo4j_driver", side_effect=Exception("neo4j stubbed"))
    )
    stack.enter_context(patch("lifecycle.NATSClient", return_value=client))
    stack.enter_context(
        patch.object(
            lifecycle, "NATS_CONNECT_BACKOFF_BASE_SECONDS", base_delay, create=True
        )
    )
    return workers


@pytest.mark.asyncio
async def test_workers_start_once_after_connect_retries():
    client = _FlakyNATSClient(failures=2)
    app = SimpleNamespace(state=SimpleNamespace())

    with ExitStack() as stack:
        workers = _patch_startup(stack, client, base_delay=0.001)
        await lifecycle.startup(app)

        started = await _wait_until(
            lambda: all(worker.await_count for worker in workers.values())
        )
        # Give a duplicate start, if any, the chance to happen.
        await asyncio.sleep(0.05)

        assert started, "workers never started after NATS became reachable"
        assert client.connect_calls == 3
        for name, worker in workers.items():
            assert worker.await_count == 1, f"{name} started {worker.await_count}x"
        assert app.state.nats_client is client
        assert app.state.nats_state == "connected"

        await lifecycle.shutdown(app)

    assert client.closed


@pytest.mark.asyncio
async def test_shutdown_during_backoff_cancels_cleanly():
    client = _FlakyNATSClient(failures=10**6)
    app = SimpleNamespace(state=SimpleNamespace())

    with ExitStack() as stack:
        workers = _patch_startup(stack, client, base_delay=30.0)
        await lifecycle.startup(app)

        assert await _wait_until(lambda: client.connect_calls >= 1)
        assert getattr(app.state, "nats_state", None) == "connecting"
        assert app.state.nats_client is None

        # The connector is asleep in a 30 s backoff; shutdown must not wait it out.
        await asyncio.wait_for(lifecycle.shutdown(app), timeout=1.0)

        assert app.state.nats_connect_task.cancelled()
        assert client.connect_calls == 1
        for worker in workers.values():
            worker.assert_not_awaited()
    assert not lifecycle._background_tasks


@pytest.mark.asyncio
async def test_backoff_doubles_and_caps(monkeypatch):
    client = _FlakyNATSClient(failures=7)
    app = SimpleNamespace(state=SimpleNamespace(nats_workers_started=True))
    delays: list[float] = []

    async def fake_sleep(delay):
        delays.append(delay)

    monkeypatch.setattr(lifecycle.asyncio, "sleep", fake_sleep)
    await lifecycle._connect_nats_and_start_workers(app, client)

    assert delays == [1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0]
    assert app.state.nats_state == "connected"


def test_health_reports_nats_state(test_client):
    from app.main import app

    # The conftest fake NATS client connects at once; wait for the connector.
    deadline = time.monotonic() + 2.0
    while getattr(app.state, "nats_state", None) != "connected":
        assert time.monotonic() < deadline, "connector never reported connected"
        time.sleep(0.01)

    body = test_client.get("/health").json()
    assert body["status"] == "healthy"
    assert "timestamp" in body
    assert body["nats"] == "connected"
