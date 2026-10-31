"""
The review loop decides ``done`` from evidence and an explicit verdict.

- A delivery whose ``files_written`` check is refuted or unverifiable goes back
  for rework without asking the QA model.
- Only a reply starting ``APPROVED:`` closes a task; any other reply is a
  failed review that is retried, never an approval.
"""

import asyncio
from uuid import uuid4

import pytest
from models.agent_run import AgentRun, Verification
from models.company import Company
from models.sprint import BacklogItem, Sprint
from services import task_worker
from sqlmodel import Session

DELIVERABLE = "# Artifact: src/a.py\n\nprint('a')\n" + "word " * 120


class _FakeNATS:
    jetstream_enabled = False

    def __init__(self):
        self.published = []

    async def publish(self, subject, payload, msg_id=None):
        self.published.append((subject, payload))

    async def request(self, subject, payload, timeout=5.0):
        raise TimeoutError


@pytest.fixture()
def db(monkeypatch, sqlite_session):
    monkeypatch.setattr(task_worker, "engine", sqlite_session.get_bind())
    return sqlite_session


def _item_in_review(session: Session, files_written: str | None) -> int:
    company = Company(company_name=f"Gate {files_written}", autonomy_level=2)
    session.add(company)
    session.commit()
    session.refresh(company)
    sprint = Sprint(company_id=company.id, sprint_name="S", scope_size="S")
    session.add(sprint)
    session.commit()
    session.refresh(sprint)
    item = BacklogItem(
        sprint_id=sprint.id,
        title=f"Write a {uuid4().hex[:8]}",
        status="in_review",
        assignee="Developer",
        comments=[{"author": "Dev", "text": DELIVERABLE, "created_at": ""}],
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    if files_written is not None:
        run = AgentRun(
            company_id=company.id,
            external_ref=f"task-{item.id}",
            producer=task_worker.TASK_WORKER_PRODUCER,
            claims={"files": ["src/a.py"]},
            artifact_digest="d",
            artifact_size=1,
            status=files_written,
        )
        session.add(run)
        session.commit()
        session.refresh(run)
        session.add(
            Verification(
                company_id=company.id,
                agent_run_id=run.id,
                verdict=files_written,
                checks=[
                    {"name": "artifact_nonempty", "outcome": "pass", "observation": ""},
                    {
                        "name": "files_written",
                        "outcome": files_written,
                        "observation": "src/a.py content on disk differs from what was sent",
                    },
                ],
            )
        )
        session.commit()
    return item.id


def _run_cycle(monkeypatch, reply: str | None, session: Session, item_id: int):
    # The shared test database may hold other in_review items; only count the
    # QA calls about this test's item.
    title = session.get(BacklogItem, item_id).title
    calls = []

    def _review(agent, prompt, **kwargs):
        if title in prompt:
            calls.append(prompt)
        return reply

    monkeypatch.setattr(task_worker, "_call_llm_for_review", _review)
    asyncio.run(task_worker._review_cycle(_FakeNATS()))
    return calls


def _state(session: Session, item_id: int):
    session.expire_all()
    item = session.get(BacklogItem, item_id)
    return item.status, [(c["author"], c["text"]) for c in item.comments]


@pytest.mark.parametrize("outcome", ["refuted", "unverifiable"])
def test_unconfirmed_delivery_is_reworked_without_asking_qa(db, monkeypatch, outcome):
    item_id = _item_in_review(db, outcome)

    calls = _run_cycle(monkeypatch, "APPROVED: looks great", db, item_id)

    status, comments = _state(db, item_id)
    assert calls == []
    assert status == "todo"
    author, text = comments[-1]
    assert author == "Verifier"
    assert text.startswith("NEEDS WORK: delivery")
    assert "differs from what was sent" in text


def test_delivery_gate_blocks_after_the_rework_limit(db, monkeypatch):
    item_id = _item_in_review(db, "refuted")
    item = db.get(BacklogItem, item_id)
    history = []
    for attempt in range(task_worker.AUTOPILOT_MAX_REWORK_CYCLES):
        history.append(
            {
                "author": "Verifier",
                "text": "NEEDS WORK: delivery refuted — x",
                "created_at": "",
            }
        )
        history.append(
            {
                "author": "Dev",
                "text": f"{DELIVERABLE} retry {attempt}",
                "created_at": "",
            }
        )
    item.comments = item.comments + history
    db.commit()

    _run_cycle(monkeypatch, "APPROVED: fine", db, item_id)

    status, comments = _state(db, item_id)
    assert status == "blocked"
    assert "blocked for manual triage" in comments[-1][1]


def test_verified_delivery_goes_to_qa_and_explicit_approval_closes_it(db, monkeypatch):
    item_id = _item_in_review(db, "pass")

    calls = _run_cycle(monkeypatch, "APPROVED: complete and tested", db, item_id)

    status, comments = _state(db, item_id)
    assert len(calls) == 1
    assert status == "done"
    assert comments[-1] == ("QA", "APPROVED: complete and tested")


@pytest.mark.parametrize("reply", ["Looks fine to me.", "", None])
def test_reply_without_a_verdict_is_a_failed_review_not_an_approval(
    db, monkeypatch, reply
):
    item_id = _item_in_review(db, None)

    _run_cycle(monkeypatch, reply, db, item_id)

    status, comments = _state(db, item_id)
    assert status == "in_review"
    assert comments[-1][0] == "System"
    assert comments[-1][1].startswith("QA review failed")
    assert "without APPROVED:/NEEDS WORK:" in comments[-1][1]


def test_needs_work_still_schedules_rework(db, monkeypatch):
    item_id = _item_in_review(db, None)

    _run_cycle(monkeypatch, "NEEDS WORK: add input validation", db, item_id)

    status, comments = _state(db, item_id)
    assert status == "todo"
    assert ("QA", "NEEDS WORK: add input validation") in comments


def test_reworked_task_is_dispatched_again_not_bounced_back_to_review(db, monkeypatch):
    item_id = _item_in_review(db, None)
    item = db.get(BacklogItem, item_id)
    item.comments = item.comments + [
        {"author": "QA", "text": "NEEDS WORK: add input validation", "created_at": ""}
    ]
    item.status = "todo"
    db.commit()
    nats = _FakeNATS()

    asyncio.run(task_worker._dispatch_todo_items(nats))

    db.expire_all()
    assert db.get(BacklogItem, item_id).status != "in_review"
    assert not any(
        payload.get("semantic_type") == "task.recovered"
        and payload.get("task_id") == item_id
        for _subject, payload in nats.published
    )


def test_rework_prompt_carries_the_review_feedback(monkeypatch):
    captured = {}

    class _Client:
        def __init__(self, base_url):
            self.timeout = None

        def chat(self, messages, model, role):
            captured["prompt"] = messages[1]["content"]
            return {"choices": [{"message": {"content": "done"}}]}

    monkeypatch.setattr(task_worker, "LLMProxyClient", _Client)
    item = {
        "id": 1,
        "title": "Write a",
        "comments": [
            {"author": "Dev", "text": "first attempt"},
            {"author": "QA", "text": "NEEDS WORK: add input validation"},
            {
                "author": "System",
                "text": "Autopilot rework scheduled after QA feedback (1/2).",
            },
        ],
    }

    task_worker._execute_task(item, {"role": "Developer"}, "Sprint 1")

    assert "## Review feedback to address" in captured["prompt"]
    assert "QA: NEEDS WORK: add input validation" in captured["prompt"]
    assert "first attempt" not in captured["prompt"]


def test_another_companys_run_cannot_gate_this_task(db, monkeypatch):
    item_id = _item_in_review(db, None)
    intruder = Company(company_name="Intruder", autonomy_level=1)
    db.add(intruder)
    db.commit()
    db.refresh(intruder)
    # POST /v1/agent_runs accepts any producer and reference from any company.
    run = AgentRun(
        company_id=intruder.id,
        external_ref=f"task-{item_id}",
        producer=task_worker.TASK_WORKER_PRODUCER,
        claims={"files": ["src/a.py"]},
        artifact_digest="d",
        artifact_size=1,
        version=99,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    db.add(
        Verification(
            company_id=intruder.id,
            agent_run_id=run.id,
            verdict="refuted",
            checks=[
                {"name": "files_written", "outcome": "refuted", "observation": "x"}
            ],
        )
    )
    db.commit()

    calls = _run_cycle(monkeypatch, "APPROVED: complete", db, item_id)

    status, _comments = _state(db, item_id)
    assert len(calls) == 1
    assert status == "done"
