"""
Durable messaging: task assignments and deliveries survive a consumer that is down.

- ``NATSClient`` stores durable subjects in JetStream (with a de-duplication
  id), consumes them with an explicit-ack durable consumer, and falls back to
  core NATS when the server has no JetStream.
- A delivery the daemon did not answer is queued on ``workspace.deliver``; the
  task waits (no QA, no rework) until the daemon reports what it wrote, and
  that report is verified against the hashes the backend recorded.

The daemon is the real ``vscode-daemon/daemon.py``; NATS is faked in-process.
"""

import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import nats_client as nats_client_module
import pytest
from models.agent_run import AgentRun, Verification
from models.company import Company, ProjectDiscovery
from models.sprint import BacklogItem, Sprint
from nats.js.errors import BadRequestError
from nats_client import NATSClient
from services import task_worker
from sqlmodel import select

_DAEMON_PATH = Path(__file__).resolve().parents[2] / "vscode-daemon" / "daemon.py"

ANSWER = """Added the greeting.

```python path=src/greet.py
def greet(name):
    return f"Hello, {name}!"
```
"""


def _load_daemon():
    spec = importlib.util.spec_from_file_location("fabrique_daemon_js", _DAEMON_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# NATSClient
# ---------------------------------------------------------------------------


class _FakeJS:
    def __init__(self, add_error=None):
        self.published = []
        self.added = []
        self.updated = []
        self.add_error = add_error

    async def publish(self, subject, data, headers=None):
        self.published.append((subject, json.loads(data), headers))
        return SimpleNamespace(stream="S", seq=len(self.published), duplicate=False)

    async def add_stream(self, config):
        if self.add_error:
            raise self.add_error
        self.added.append(config.name)

    async def update_stream(self, config):
        self.updated.append(config.name)


class _FakeNC:
    def __init__(self, js):
        self.js = js
        self.core = []
        self.subscribed = []

    def jetstream(self):
        return self.js

    async def publish(self, subject, data):
        self.core.append((subject, json.loads(data)))

    async def subscribe(self, subject, queue=None):
        self.subscribed.append((subject, queue))

        class _Sub:
            messages = _empty()

        return _Sub()


async def _empty():
    return
    yield


def _client(js) -> NATSClient:
    client = NATSClient("nats://test")
    client.nc = _FakeNC(js)
    return client


def test_durable_subjects_are_stored_in_jetstream_with_their_id():
    js = _FakeJS()
    client = _client(js)

    async def scenario():
        assert await client.enable_jetstream()
        await client.publish("task.assign", {"backlog_item_id": 1}, msg_id="a-1")
        await client.publish("glassroom.7", {"x": 1})

    asyncio.run(scenario())

    assert js.added == [s.name for s in nats_client_module.DURABLE_STREAMS]
    assert js.published == [
        ("task.assign", {"backlog_item_id": 1}, {"Nats-Msg-Id": "a-1"})
    ]
    # Live events stay on core NATS.
    assert client.nc.core == [("glassroom.7", {"x": 1})]


def test_existing_streams_with_other_settings_are_updated():
    js = _FakeJS(add_error=BadRequestError())
    client = _client(js)

    assert asyncio.run(client.enable_jetstream())
    assert js.updated == [s.name for s in nats_client_module.DURABLE_STREAMS]


def test_without_jetstream_everything_uses_core_nats():
    js = _FakeJS(add_error=RuntimeError("nats: no responders available"))
    client = _client(js)

    async def scenario():
        assert not await client.enable_jetstream()
        await client.publish("task.assign", {"backlog_item_id": 1}, msg_id="a-1")
        await client.consume("task.assign", "task-worker", lambda msg, data: None)

    asyncio.run(scenario())

    assert not client.jetstream_enabled
    assert js.published == []
    assert client.nc.core == [("task.assign", {"backlog_item_id": 1})]
    assert client.nc.subscribed == [("task.assign", "task-worker")]
    for task in client.subscriptions.values():
        task.cancel()


class _FakeMsg:
    subject = "task.assign"

    def __init__(self, data: bytes, delivered: int = 1):
        self.data = data
        self.metadata = SimpleNamespace(num_delivered=delivered)
        self.calls = []

    async def ack(self):
        self.calls.append("ack")

    async def nak(self, delay=None):
        self.calls.append("nak")

    async def term(self):
        self.calls.append("term")

    async def in_progress(self):
        self.calls.append("in_progress")


def _handle(msg, callback, max_deliver=3):
    client = NATSClient("nats://test")
    asyncio.run(client._handle_durable(msg, callback, 600.0, max_deliver))
    return msg.calls


def test_message_is_acknowledged_after_the_handler_returns():
    seen = []

    async def callback(msg, data):
        seen.append(data)

    assert _handle(_FakeMsg(b'{"backlog_item_id": 4}'), callback) == ["ack"]
    assert seen == [{"backlog_item_id": 4}]


def test_handler_failure_is_redelivered_then_dropped_at_the_limit():
    async def callback(msg, data):
        raise RuntimeError("boom")

    assert _handle(_FakeMsg(b"{}", delivered=1), callback) == ["nak"]
    assert _handle(_FakeMsg(b"{}", delivered=3), callback) == ["term"]


def test_malformed_message_is_dropped_without_calling_the_handler():
    called = []

    async def callback(msg, data):
        called.append(data)

    assert _handle(_FakeMsg(b"not json"), callback) == ["term"]
    assert called == []


# ---------------------------------------------------------------------------
# Queued deliveries
# ---------------------------------------------------------------------------


class _OfflineDaemonNATS:
    """JetStream is on, but no daemon answers requests."""

    jetstream_enabled = True

    def __init__(self):
        self.published = []
        self.requests = []

    async def request(self, subject, payload, timeout=5.0):
        self.requests.append(subject)
        raise TimeoutError("nats: no responders available for request")

    async def publish(self, subject, payload, msg_id=None):
        self.published.append((subject, payload, msg_id))


@pytest.fixture()
def db(monkeypatch, sqlite_session, tmp_path):
    ProjectDiscovery.__table__.create(sqlite_session.get_bind(), checkfirst=True)
    monkeypatch.setattr(task_worker, "engine", sqlite_session.get_bind())
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path / "audit"))
    return sqlite_session


def _task(db, project: Path):
    company = Company(company_name=f"Queue {project.name}", autonomy_level=2)
    db.add(company)
    db.commit()
    db.refresh(company)
    db.add(ProjectDiscovery(company_id=company.id, project_path=str(project)))
    sprint = Sprint(company_id=company.id, sprint_name="Q", scope_size="S")
    db.add(sprint)
    db.commit()
    db.refresh(sprint)
    item = BacklogItem(
        sprint_id=sprint.id,
        title=f"Greet {uuid4().hex[:8]}",
        status="in_progress",
        assignee="Dev",
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return (
        {"id": item.id, "title": item.title},
        {"role": "Dev", "served_model": "m"},
        {"id": sprint.id, "company_id": company.id},
    )


def _latest_verification(db, company_id, item_id):
    db.expire_all()
    run = db.exec(
        select(AgentRun)
        .where(
            AgentRun.company_id == company_id,
            AgentRun.external_ref == f"task-{item_id}",
        )
        .order_by(AgentRun.version.desc())
    ).first()
    return db.exec(
        select(Verification)
        .where(Verification.agent_run_id == run.id)
        .order_by(Verification.id.desc())
    ).first()


def _comments(db, item_id):
    db.expire_all()
    return [c["text"] for c in db.get(BacklogItem, item_id).comments]


class _FakeDaemonJS:
    def __init__(self):
        self.published = []

    async def publish(self, subject, data, headers=None):
        self.published.append((subject, json.loads(data), headers))


class _FakeDaemonNC:
    def __init__(self):
        self.published = []

    async def publish(self, subject, data):
        self.published.append((subject, json.loads(data)))


def _daemon_writes(daemon, job: dict) -> tuple[dict, list]:
    """Run the daemon's queued-delivery handler on *job*; return its report."""
    js, nc = _FakeDaemonJS(), _FakeDaemonNC()
    msg = _FakeMsg(json.dumps(job).encode())
    asyncio.run(daemon.process_queued_delivery(nc, js, msg))
    [(subject, result, headers)] = js.published
    assert subject == "workspace.delivered"
    assert headers == {"Nats-Msg-Id": f"delivered-{job['job_id']}"}
    return result, msg.calls


def test_delivery_to_an_offline_daemon_is_queued_and_the_task_waits(
    db, tmp_path, monkeypatch
):
    project = tmp_path / "project"
    project.mkdir()
    item, agent, sprint = _task(db, project)
    nats = _OfflineDaemonNATS()

    asyncio.run(task_worker._deliver_artifacts(nats, item, agent, sprint, ANSWER))

    [(_subject, job, msg_id)] = [
        p for p in nats.published if p[0] == "workspace.deliver"
    ]
    assert job["workspace_root"] == str(project)
    assert job["files"][0]["path"] == "src/greet.py"
    assert job["item_id"] == item["id"]
    assert msg_id == f"deliver-{job['job_id']}"
    verification = _latest_verification(db, sprint["company_id"], item["id"])
    assert verification.verdict == "unverifiable"
    assert verification.evidence["delivery_queued"] == {"job_id": job["job_id"]}
    assert _comments(db, item["id"])[-1].startswith("Delivery queued:")

    # The review loop neither asks QA nor schedules a rework while it waits.
    item_row = db.get(BacklogItem, item["id"])
    item_row.status = "in_review"
    item_row.comments = [*item_row.comments, {"author": "Dev", "text": ANSWER}]
    db.commit()
    # The shared test database may hold other in_review items; only count the
    # QA calls about this one.
    asked = []

    def _review(agent, prompt, **kwargs):
        if item["title"] in prompt:
            asked.append(prompt)
        return "APPROVED: ok"

    monkeypatch.setattr(task_worker, "_call_llm_for_review", _review)
    assert task_worker._delivery_gate(sprint["company_id"], item["id"])[0] == (
        task_worker.DELIVERY_QUEUED
    )
    asyncio.run(task_worker._review_cycle(nats))
    db.expire_all()
    assert db.get(BacklogItem, item["id"]).status == "in_review"
    assert asked == []


def test_daemon_report_for_a_queued_delivery_verifies_the_run(db, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    item, agent, sprint = _task(db, project)
    nats = _OfflineDaemonNATS()
    asyncio.run(task_worker._deliver_artifacts(nats, item, agent, sprint, ANSWER))
    job = next(p[1] for p in nats.published if p[0] == "workspace.deliver")

    # The daemon connects later and writes the queued files.
    result, acks = _daemon_writes(_load_daemon(), job)
    assert acks == ["ack"]
    assert (project / "src" / "greet.py").read_text().startswith("def greet(name):")

    asyncio.run(task_worker._on_delivery_result(nats, result))

    verification = _latest_verification(db, sprint["company_id"], item["id"])
    checks = {c["name"]: c for c in verification.checks}
    assert verification.verdict == "verified"
    assert checks["files_written"]["outcome"] == "pass"
    assert "delivery_queued" not in verification.evidence
    assert verification.evidence["delivered_after_queue"] is True
    assert task_worker._delivery_gate(sprint["company_id"], item["id"]) is None
    assert _comments(db, item["id"])[-1].startswith(
        f"Queued delivery: Delivered to {project}"
    )


def test_report_cannot_supply_its_own_expected_hashes(db, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    item, agent, sprint = _task(db, project)
    nats = _OfflineDaemonNATS()
    asyncio.run(task_worker._deliver_artifacts(nats, item, agent, sprint, ANSWER))
    job = next(p[1] for p in nats.published if p[0] == "workspace.deliver")
    forged = {
        **job,
        "files": [{"path": "src/greet.py", "status": "written", "sha256": "f" * 64}],
        "expected": {"src/greet.py": "f" * 64},
    }

    asyncio.run(task_worker._on_delivery_result(nats, forged))

    verification = _latest_verification(db, sprint["company_id"], item["id"])
    assert verification.verdict == "refuted"
    assert "differs from what was sent" in str(verification.checks)


def test_report_for_a_superseded_job_is_ignored(db, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    item, agent, sprint = _task(db, project)
    nats = _OfflineDaemonNATS()
    asyncio.run(task_worker._deliver_artifacts(nats, item, agent, sprint, ANSWER))
    job = next(p[1] for p in nats.published if p[0] == "workspace.deliver")
    before = _latest_verification(db, sprint["company_id"], item["id"]).id

    stale = {**job, "job_id": "another-job", "files": []}
    asyncio.run(task_worker._on_delivery_result(nats, stale))

    assert _latest_verification(db, sprint["company_id"], item["id"]).id == before


class _DaemonConnectsDuringPublishNATS(_OfflineDaemonNATS):
    """The daemon connects just as the job is stored and reports at once."""

    def __init__(self, daemon):
        super().__init__()
        self.daemon = daemon

    async def publish(self, subject, payload, msg_id=None):
        await super().publish(subject, payload, msg_id)
        if subject == "workspace.deliver":
            result = {
                **self.daemon.deliver_files(
                    payload["workspace_root"], payload["files"]
                ),
                "job_id": payload["job_id"],
                "company_id": payload["company_id"],
                "sprint_id": payload["sprint_id"],
                "item_id": payload["item_id"],
            }
            await task_worker._on_delivery_result(self, result)


def test_report_arriving_while_the_job_is_published_is_not_lost(db, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    item, agent, sprint = _task(db, project)
    nats = _DaemonConnectsDuringPublishNATS(_load_daemon())

    asyncio.run(task_worker._deliver_artifacts(nats, item, agent, sprint, ANSWER))

    verification = _latest_verification(db, sprint["company_id"], item["id"])
    assert verification.verdict == "verified"
    assert task_worker._delivery_gate(sprint["company_id"], item["id"]) is None


class _QueueDownNATS(_OfflineDaemonNATS):
    async def publish(self, subject, payload, msg_id=None):
        if subject == "workspace.deliver":
            raise ConnectionError("nats: connection closed")
        await super().publish(subject, payload, msg_id)


def test_delivery_that_cannot_be_queued_does_not_leave_the_task_waiting(db, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    item, agent, sprint = _task(db, project)

    asyncio.run(
        task_worker._deliver_artifacts(_QueueDownNATS(), item, agent, sprint, ANSWER)
    )

    verification = _latest_verification(db, sprint["company_id"], item["id"])
    assert "delivery_queued" not in verification.evidence
    assert "queueing the delivery failed" in verification.evidence["reason"]
    gate = task_worker._delivery_gate(sprint["company_id"], item["id"])
    assert gate[0] == "delivery unconfirmed"
    assert _comments(db, item["id"])[-1].startswith("Delivery unconfirmed:")


def test_without_jetstream_an_offline_daemon_still_means_unconfirmed(db, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    item, agent, sprint = _task(db, project)
    nats = _OfflineDaemonNATS()
    nats.jetstream_enabled = False

    asyncio.run(task_worker._deliver_artifacts(nats, item, agent, sprint, ANSWER))

    assert not [p for p in nats.published if p[0] == "workspace.deliver"]
    verification = _latest_verification(db, sprint["company_id"], item["id"])
    assert "delivery_queued" not in verification.evidence
    gate = task_worker._delivery_gate(sprint["company_id"], item["id"])
    assert gate[0] == "delivery unconfirmed"


def test_daemon_retries_a_queued_delivery_it_could_not_report(tmp_path):
    daemon = _load_daemon()
    project = tmp_path / "p"
    project.mkdir()

    class _DownJS:
        async def publish(self, subject, data, headers=None):
            raise ConnectionError("nats down")

    msg = _FakeMsg(
        json.dumps(
            {
                "job_id": "j1",
                "workspace_root": str(project),
                "files": [{"path": "a.txt", "content": "a"}],
            }
        ).encode()
    )
    asyncio.run(daemon.process_queued_delivery(_FakeDaemonNC(), _DownJS(), msg))

    assert msg.calls == ["nak"]


def test_repeated_dispatch_of_the_same_todo_item_has_one_id(db, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    item, _agent, _sprint = _task(db, project)
    row = db.get(BacklogItem, item["id"])
    row.status = "todo"
    db.commit()
    nats = _OfflineDaemonNATS()

    asyncio.run(task_worker._dispatch_todo_items(nats))
    task_worker._clear_queue_marker(item["id"])
    asyncio.run(task_worker._dispatch_todo_items(nats))

    ids = [
        msg_id
        for subject, payload, msg_id in nats.published
        if subject == "task.assign" and payload["backlog_item_id"] == item["id"]
    ]
    assert len(ids) == 2
    assert ids[0] == ids[1]
    assert ids[0].startswith(f"assign-{item['id']}-")
