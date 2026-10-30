"""
``NATS_NAMESPACE`` separates the JetStream state of two deployments sharing a
broker (issue: the e2e run stole the compose stack's task assignments).

The streams use work-queue retention, so a message goes to exactly one
consumer. Two stacks with the same stream and consumer names therefore consume
each other's messages, and the publisher sees a task that was never handled.
Namespacing only the stream names is not enough: two streams bound to one
subject each store every message, so the subject must differ too. These tests
pin both; no broker is needed.

Run with:
    cd backend && PYTHONPATH=.:app python3 -m pytest tests/test_nats_namespace.py -q
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nats_client import NATSClient, _namespace, _scoped, _scoped_subject


@pytest.fixture(autouse=True)
def _clear_namespace(monkeypatch):
    monkeypatch.delenv("NATS_NAMESPACE", raising=False)


class _FakeJetStream:
    """Records the stream configs, publishes and pull subscriptions requested."""

    def __init__(self):
        self.added = []
        self.subscribed = None
        self.published = []

    async def add_stream(self, config):
        self.added.append(config)
        return MagicMock()

    async def pull_subscribe(self, subject, durable, stream, config):
        self.subscribed = {
            "subject": subject,
            "durable": durable,
            "stream": stream,
            "config": config,
        }
        return MagicMock()

    async def publish(self, subject, data, headers=None):
        self.published.append({"subject": subject, "headers": headers})
        return MagicMock(stream="x", seq=1, duplicate=False)


def _client():
    return NATSClient(nats_url="nats://127.0.0.1:4222")


def test_no_namespace_keeps_the_historical_names():
    assert _namespace() == ""
    assert _scoped("FABRIQUE_TASKS") == "FABRIQUE_TASKS"
    assert _scoped_subject("task.assign") == "task.assign"


def test_namespace_prefixes_stream_and_consumer_names(monkeypatch):
    monkeypatch.setenv("NATS_NAMESPACE", "e2e")

    assert _scoped("FABRIQUE_TASKS") == "e2e_FABRIQUE_TASKS"
    assert _scoped("task-worker") == "e2e_task-worker"


def test_namespace_prefixes_the_subject_with_a_dot(monkeypatch):
    # A subject has to stay a legal subject: stream names use `_`, subjects `.`.
    monkeypatch.setenv("NATS_NAMESPACE", "e2e")

    assert _scoped_subject("task.assign") == "e2e.task.assign"


def test_namespace_is_sanitised_to_legal_stream_characters(monkeypatch):
    # NATS rejects dots, spaces and slashes in stream names.
    monkeypatch.setenv("NATS_NAMESPACE", " team.a/b ")

    assert _namespace() == "team_a_b"
    assert _scoped_subject("task.assign") == "team_a_b.task.assign"


def test_whitespace_only_namespace_is_ignored(monkeypatch):
    monkeypatch.setenv("NATS_NAMESPACE", "   ")

    assert _scoped("task-worker") == "task-worker"
    assert _scoped_subject("task.assign") == "task.assign"


@pytest.mark.asyncio
async def test_streams_are_declared_with_the_namespaced_names_and_subjects(monkeypatch):
    monkeypatch.setenv("NATS_NAMESPACE", "e2e")
    client = _client()
    client.nc = MagicMock()
    fake_js = _FakeJetStream()
    client.nc.jetstream.return_value = fake_js

    assert await client.enable_jetstream() is True
    names = sorted(config.name for config in fake_js.added)
    assert names == [
        "e2e_FABRIQUE_DELIVERIES",
        "e2e_FABRIQUE_DELIVERY_RESULTS",
        "e2e_FABRIQUE_TASKS",
    ]
    # Without namespaced subjects both stacks would still capture each
    # other's messages, so the isolation would be cosmetic.
    subjects = sorted(
        subject for config in fake_js.added for subject in config.subjects
    )
    assert subjects == [
        "e2e.task.assign",
        "e2e.workspace.deliver",
        "e2e.workspace.delivered",
    ]


@pytest.mark.asyncio
async def test_consume_uses_the_namespaced_durable_stream_and_subject(monkeypatch):
    monkeypatch.setenv("NATS_NAMESPACE", "e2e")
    client = _client()
    fake_js = _FakeJetStream()
    client.nc = MagicMock()
    client.js = fake_js

    def _discard_task(coro, **_kwargs):
        coro.close()
        return MagicMock()

    # Keep the fetch loop and the task registry out of the assertion.
    with patch("nats_client.asyncio.create_task", side_effect=_discard_task):
        await client.consume("task.assign", "task-worker", AsyncMock())

    assert fake_js.subscribed["durable"] == "e2e_task-worker"
    assert fake_js.subscribed["stream"] == "e2e_FABRIQUE_TASKS"
    assert fake_js.subscribed["config"].durable_name == "e2e_task-worker"
    assert fake_js.subscribed["subject"] == "e2e.task.assign"
    assert fake_js.subscribed["config"].filter_subject == "e2e.task.assign"


@pytest.mark.asyncio
async def test_publish_namespaces_durable_subjects_only(monkeypatch):
    monkeypatch.setenv("NATS_NAMESPACE", "e2e")
    client = _client()
    fake_js = _FakeJetStream()
    client.nc = MagicMock()
    client.nc.publish = AsyncMock()
    client.js = fake_js

    await client.publish("task.assign", {"task_id": 1})
    # Glassroom is core pub/sub for the SSE relay, not a durable stream: it
    # stays on the plain subject so the frontend keeps receiving it.
    await client.publish("glassroom.7", {"content": "hi"})

    assert fake_js.published[0]["subject"] == "e2e.task.assign"
    assert client.nc.publish.await_args.args[0] == "glassroom.7"
