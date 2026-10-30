"""
The risk tier of a delivery and what it changes (``services/risk.py``).

- Paths decide the tier: authentication, secrets, payments and the CI
  pipeline are high; shell scripts, migrations, dependency manifests and
  container files are medium; anything else is low. More files never lower
  it, and a producer may raise it with a reason, never lower it.
- The Verifier records it as a ``risk_tier`` check that never changes the
  verdict.
- An approved high-risk task waits for a person at every autonomy level, is
  listed in the inbox as ``risk_hold``, settles the sprint, is not counted as
  a failure and is not carried into another sprint on the company's own.
"""

import asyncio
from uuid import uuid4

import pytest
from models.agent_run import AgentRun, Verification
from models.company import Company
from models.sprint import BacklogItem, Sprint
from services import procedures, risk, task_worker
from services.board import (
    RISK_HOLD_PREFIX,
    SEND_BACK_MARKER,
    awaits_risk_acceptance,
    blocked_item_next_step,
    item_is_settled,
)
from services.carry_over import carry_over_on_the_companys_own
from services.verification import check_risk_tier
from sqlmodel import Session, select

DELIVERABLE = "# Artifact: src/a.py\n\nprint('a')\n" + "word " * 120


# ── The classification ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("path", "tier", "area"),
    [
        ("backend/app/auth_deps.py", "high", "authentication"),
        ("frontend/src/pages/LoginPage.tsx", "high", "authentication"),
        ("src/AuthProvider.tsx", "high", "authentication"),
        ("config/.env", "high", "secrets"),
        (".env.production", "high", "secrets"),
        ("deploy/server.pem", "high", "secrets"),
        ("app/services/credentials.py", "high", "secrets"),
        ("app/billing/invoice.py", "high", "payments"),
        (".github/workflows/ci.yml", "high", "CI pipeline"),
        ("scripts/deploy.sh", "medium", "shell script"),
        ("alembic/versions/0001_init.py", "medium", "database migration"),
        ("db/schema.sql", "medium", "database migration"),
        ("package.json", "medium", "dependencies"),
        ("requirements-dev.txt", "medium", "dependencies"),
        ("Dockerfile.backend", "medium", "containers and infrastructure"),
        ("infra/main.tf", "medium", "containers and infrastructure"),
    ],
)
def test_a_path_marks_its_area(path, tier, area):
    assert risk.classify([path]) == {"tier": tier, "reasons": [f"{area}: {path}"]}


@pytest.mark.parametrize(
    "path",
    ["src/author.py", "docs/authors.md", ".env.example", "src/session_store.py"],
)
def test_words_that_only_look_alike_are_low(path):
    assert risk.classify([path])["tier"] == "low"


def test_the_highest_path_decides_and_more_files_never_lower_it():
    result = risk.classify(
        ["src/a.py", "scripts/run.sh", "backend/app/auth.py", "README.md"] * 3
    )
    assert result["tier"] == "high"
    assert result["reasons"] == [
        "shell script: scripts/run.sh",
        "authentication: backend/app/auth.py",
    ]


def test_a_producer_may_raise_the_tier_with_a_reason_but_never_lower_it():
    raised = risk.classify(["src/a.py"], {"tier": "high", "reason": "touches PII"})
    assert raised == {
        "tier": "high",
        "reasons": ["raised by the producer: touches PII"],
    }
    assert risk.classify(["src/a.py"], {"tier": "high"})["tier"] == "low"
    lowered = risk.classify(["app/auth.py"], {"tier": "low", "reason": "trivial"})
    assert lowered["tier"] == "high"


def test_the_verifier_check_reads_the_daemons_report_and_never_decides_the_verdict():
    run = AgentRun(
        company_id=1,
        external_ref="x",
        producer="p",
        claims={"files": ["src/a.py"]},
        artifact_digest="d",
        artifact_size=1,
    )
    evidence = {
        "workspace_writes": [
            {"path": "src/a.py", "status": "written"},
            {"path": "app/auth.py", "status": "written"},
            {"path": "app/billing.py", "status": "rejected"},
        ]
    }
    check = check_risk_tier(run, evidence)
    assert check["outcome"] == "pass"
    assert check["tier"] == "high"
    assert check["reasons"] == ["authentication: app/auth.py"]
    assert check["observation"] == "high — authentication: app/auth.py"


# ── What a high tier changes in the review loop ─────────────────────────────


class _FakeNATS:
    jetstream_enabled = False

    async def publish(self, subject, payload, msg_id=None):
        pass

    async def request(self, subject, payload, timeout=5.0):
        raise TimeoutError


@pytest.fixture()
def db(monkeypatch, sqlite_session):
    monkeypatch.setattr(task_worker, "engine", sqlite_session.get_bind())
    return sqlite_session


def _item_in_review(session: Session, tier: str, autonomy: int = 3) -> BacklogItem:
    company = Company(company_name=f"Risk {uuid4().hex[:6]}", autonomy_level=autonomy)
    session.add(company)
    session.commit()
    session.refresh(company)
    sprint = Sprint(company_id=company.id, sprint_name="S", scope_size="S")
    session.add(sprint)
    session.commit()
    session.refresh(sprint)
    item = BacklogItem(
        sprint_id=sprint.id,
        title=f"Change {uuid4().hex[:8]}",
        status="in_review",
        assignee="Developer",
        comments=[{"author": "Dev", "text": DELIVERABLE, "created_at": ""}],
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    run = AgentRun(
        company_id=company.id,
        external_ref=f"task-{item.id}",
        producer=task_worker.TASK_WORKER_PRODUCER,
        claims={"files": ["app/auth.py"]},
        artifact_digest="d",
        artifact_size=1,
        status="verified",
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    reasons = ["authentication: app/auth.py"] if tier == "high" else []
    session.add(
        Verification(
            company_id=company.id,
            agent_run_id=run.id,
            verdict="verified",
            checks=[
                {"name": "files_written", "outcome": "pass", "observation": ""},
                {
                    "name": "risk_tier",
                    "outcome": "pass",
                    "observation": tier,
                    "tier": tier,
                    "reasons": reasons,
                },
            ],
        )
    )
    session.commit()
    return item


def _approve(monkeypatch, session: Session, item: BacklogItem) -> BacklogItem:
    title = item.title

    def _review(agent, prompt, **kwargs):
        return "APPROVED: complete" if title in prompt else None

    monkeypatch.setattr(task_worker, "_call_llm_for_review", _review)
    asyncio.run(task_worker._review_cycle(_FakeNATS()))
    session.expire_all()
    return session.get(BacklogItem, item.id)


def test_an_approved_high_risk_task_waits_for_a_person_even_at_autonomy_3(
    db, monkeypatch
):
    item = _approve(monkeypatch, db, _item_in_review(db, "high", autonomy=3))

    assert item.status == "blocked"
    author, text = item.comments[-1]["author"], item.comments[-1]["text"]
    assert author == "System"
    assert text.startswith(RISK_HOLD_PREFIX)
    assert "authentication: app/auth.py" in text
    assert awaits_risk_acceptance(item.comments)
    # Nothing the worker does moves it, so the sprint can close around it.
    assert blocked_item_next_step(item.comments, item.assignee) is None
    assert item_is_settled(item)


def test_without_a_recorded_check_the_declared_paths_decide(db, monkeypatch):
    item = _item_in_review(db, "high")
    runs = db.exec(select(AgentRun).where(AgentRun.external_ref == f"task-{item.id}"))
    run_ids = [run.id for run in runs]
    for verification in db.exec(
        select(Verification).where(Verification.agent_run_id.in_(run_ids))
    ):
        db.delete(verification)
    item.comments = [
        {
            "author": "Dev",
            "text": DELIVERABLE + "\n```python path=app/auth_guard.py\nx = 1\n```\n",
            "created_at": "",
        }
    ]
    db.add(item)
    db.commit()

    item = _approve(monkeypatch, db, item)

    assert item.status == "blocked"
    assert "authentication: app/auth_guard.py" in item.comments[-1]["text"]


def test_an_approved_low_risk_task_is_done(db, monkeypatch):
    item = _approve(monkeypatch, db, _item_in_review(db, "low"))
    assert item.status == "done"
    assert not awaits_risk_acceptance(item.comments)


def test_a_hold_is_not_a_failure_and_is_not_carried_over_on_the_companys_own(
    db, monkeypatch
):
    item = _approve(monkeypatch, db, _item_in_review(db, "high"))
    sprint = db.get(Sprint, item.sprint_id)

    assert procedures.board_metrics(db, [sprint.id])["blocked_rate"] == 0.0

    follow_up = Sprint(company_id=sprint.company_id, sprint_name="S2", scope_size="S")
    db.add(follow_up)
    db.commit()
    db.refresh(follow_up)
    assert (
        carry_over_on_the_companys_own(db, sprint.company_id, sprint.id, follow_up, 5)
        == []
    )


def test_after_a_send_back_the_task_no_longer_awaits_acceptance():
    comments = [
        {"author": "System", "text": f"{RISK_HOLD_PREFIX} (x).", "created_at": ""},
        {
            "author": "user",
            "text": f"{SEND_BACK_MARKER} by a person.",
            "created_at": "",
        },
    ]
    assert not awaits_risk_acceptance(comments)


def test_the_inbox_marks_the_hold(db, monkeypatch, test_client):
    item = _approve(monkeypatch, db, _item_in_review(db, "high"))
    sprint = db.get(Sprint, item.sprint_id)

    body = test_client.get("/v1/inbox", params={"company_id": sprint.company_id}).json()

    [listed] = [t for t in body["blocked_tasks"] if t["id"] == item.id]
    assert listed["risk_hold"] is True
    assert listed["reason"].startswith(RISK_HOLD_PREFIX)
