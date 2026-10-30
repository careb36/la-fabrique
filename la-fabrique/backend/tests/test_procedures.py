"""Procedures: proposed by the ScrumMaster, kept or reverted by the board's numbers."""

import asyncio
import secrets

import auth_tokens
import pytest
from config import settings
from models import (
    AgentMessage,
    BacklogItem,
    Company,
    CompanyMember,
    Procedure,
    Sprint,
    User,
)
from services import procedures, scrum_master, task_worker
from sqlmodel import select
from test_review_gate import _FakeNATS


@pytest.fixture()
def db(monkeypatch, sqlite_session):
    monkeypatch.setattr(task_worker, "engine", sqlite_session.get_bind())
    return sqlite_session


def _company(session, autonomy=2):
    company = Company(
        company_name=f"Proc {secrets.token_hex(3)}", autonomy_level=autonomy
    )
    session.add(company)
    session.commit()
    return company


def _sprint(session, company, tasks=2, reworks=0, blocked=0, status="completed"):
    """A sprint whose board shows *reworks* NEEDS WORK requests and *blocked* tasks."""
    sprint = Sprint(company_id=company.id, sprint_name="S", status=status)
    session.add(sprint)
    session.commit()
    for index in range(tasks):
        comments = [
            {"author": "QA", "text": "NEEDS WORK: again", "created_at": ""}
            for _ in range(reworks if index == 0 else 0)
        ]
        session.add(
            BacklogItem(
                sprint_id=sprint.id,
                title=f"T{index}",
                status="blocked" if index < blocked else "done",
                comments=comments,
            )
        )
    session.commit()
    return sprint


PROPOSAL_TEXT = """Here is my proposal.

PROCEDURE role=Developer title=Validate inputs
Validate every user input at the boundary and add a test for invalid input.
WHY: two tasks came back for missing validation
END

PROCEDURE role=Janitor title=Sweep
Sweep the floor.
WHY: not a role here
END

PROCEDURE role=All title=Small tasks
Split work bigger than a day.
WHY: one task was blocked
END

PROCEDURE role=QA title=Third one
Never reached.
WHY: only two are read
END
"""


# ── Parsing ──────────────────────────────────────────────────────────────────


def test_parses_proposals_for_known_roles_up_to_the_limit():
    parsed = procedures.parse_proposals(PROPOSAL_TEXT, ["Developer", "QA"])
    assert [(p["role"], p["title"]) for p in parsed] == [
        ("Developer", "Validate inputs"),
        ("All", "Small tasks"),
    ]
    assert parsed[0]["body"] == (
        "Validate every user input at the boundary and add a test for invalid input."
    )
    assert parsed[0]["why"] == "two tasks came back for missing validation"
    assert procedures.parse_proposals("NONE", ["Developer"]) == []
    assert (
        procedures.parse_proposals(
            "PROCEDURE role=Developer title=X\nno end", ["Developer"]
        )
        == []
    )


# ── Proposing, adopting, measuring ───────────────────────────────────────────


def test_a_new_version_supersedes_the_active_one_and_duplicates_are_skipped(db):
    company = _company(db)
    first = procedures.propose(
        db,
        company.id,
        [{"role": "QA", "title": "Run tests", "body": "Run them."}],
        "a@b.c",
    )[0]
    procedures.adopt(db, first, "a@b.c")
    db.commit()
    assert (
        procedures.propose(
            db,
            company.id,
            [{"role": "QA", "title": "Run tests", "body": "Run them."}],
            "a@b.c",
        )
        == []
    )

    second = procedures.propose(
        db,
        company.id,
        [{"role": "QA", "title": "Run tests", "body": "Run all of them."}],
        "ScrumMaster",
    )[0]
    assert (second.version, second.supersedes_id, second.status) == (
        2,
        first.id,
        "proposed",
    )
    procedures.adopt(db, second, "autonomy")
    db.commit()
    db.refresh(first)
    assert first.status == "retired"
    assert first.outcome == {"result": "superseded", "by": second.id}


def test_adoption_records_the_numbers_of_the_last_two_completed_sprints(db):
    company = _company(db)
    _sprint(db, company, tasks=2, reworks=4)  # older, outside the baseline
    _sprint(db, company, tasks=2, reworks=1)
    last = _sprint(db, company, tasks=2, reworks=1, blocked=1)
    _sprint(db, company, status="active")
    procedure = procedures.propose(
        db, company.id, [{"role": "Developer", "title": "T", "body": "B"}], "x"
    )[0]

    procedures.adopt(db, procedure, "x")

    assert procedure.baseline == {
        "sprints": 2,
        "tasks": 4,
        "rework_per_task": 0.5,
        "blocked_rate": 0.25,
    }
    assert procedure.adopted_after_sprint_id == last.id
    assert procedure.status == "active"


def _adopted(db, company, supersedes=None):
    procedure = procedures.propose(
        db,
        company.id,
        [{"role": "Developer", "title": "Rule", "body": f"B{secrets.token_hex(2)}"}],
        "x",
    )[0]
    procedures.adopt(db, procedure, "x")
    db.commit()
    return procedure


def test_kept_when_the_numbers_hold_and_only_after_two_sprints(db):
    company = _company(db)
    _sprint(db, company, tasks=2, reworks=1)
    procedure = _adopted(db, company)

    _sprint(db, company, tasks=2, reworks=1)
    assert procedures.evaluate(db, company.id) == []  # one sprint is not enough

    _sprint(db, company, tasks=2, reworks=0)
    assert procedures.evaluate(db, company.id) == [procedure]
    assert procedure.status == "active"
    assert procedure.outcome["result"] == "kept"
    assert procedure.outcome["rework_per_task"] == 0.25
    assert "is kept" in procedures.describe_outcome(procedure)
    db.commit()
    assert procedures.evaluate(db, company.id) == []  # measured once


def test_reverted_when_rework_grows_and_the_previous_version_returns(db):
    company = _company(db)
    _sprint(db, company, tasks=2, reworks=0)
    first = _adopted(db, company)
    first.outcome = {"result": "kept"}
    db.add(first)
    db.commit()
    second = procedures.propose(
        db,
        company.id,
        [{"role": "Developer", "title": "Rule", "body": "A stricter rule"}],
        "ScrumMaster",
    )[0]
    procedures.adopt(db, second, "autonomy")
    db.commit()

    _sprint(db, company, tasks=2, reworks=2)
    _sprint(db, company, tasks=2, reworks=2, blocked=1)
    procedures.evaluate(db, company.id)
    db.commit()
    db.refresh(first)

    assert second.status == "retired"
    assert second.outcome["result"] == "reverted"
    assert first.status == "active"
    assert first.outcome["result"] == "restored"
    assert "reverted" in procedures.describe_outcome(second)


def test_unmeasured_without_a_baseline(db):
    company = _company(db)
    procedure = _adopted(db, company)  # no completed sprint before it
    _sprint(db, company)
    _sprint(db, company)
    procedures.evaluate(db, company.id)
    assert procedure.status == "active"
    assert procedure.outcome["result"] == "unmeasured"


# ── The task worker ──────────────────────────────────────────────────────────


def _scrum_master_answers(monkeypatch, answer):
    calls = []

    class _Client:
        def __init__(self, base_url=None):
            self.timeout = None

        def chat(self, messages, model, role, bu_id=None):
            calls.append({"prompt": messages[-1]["content"], "role": role})
            return {"choices": [{"message": {"content": answer}}]}

    # The ScrumMaster speaks through scrum_master.ask; the other roles through
    # the task worker's client. Both answer the same here.
    monkeypatch.setattr(scrum_master, "LLMProxyClient", _Client)
    monkeypatch.setattr(task_worker, "LLMProxyClient", _Client)
    return calls


@pytest.mark.parametrize("autonomy, status", [(3, "active"), (2, "proposed")])
def test_the_scrum_master_proposes_after_a_sprint_with_rework(
    db, monkeypatch, autonomy, status
):
    calls = _scrum_master_answers(monkeypatch, PROPOSAL_TEXT)
    company = _company(db, autonomy=autonomy)
    db.add_all(
        [
            task_worker.Agent(company_id=company.id, name="Dev", role="Developer"),
            task_worker.Agent(company_id=company.id, name="Quinn", role="QA"),
        ]
    )
    db.commit()
    sprint = _sprint(db, company, tasks=2, reworks=2)
    metrics = task_worker._build_sprint_retrospective(sprint.id)

    task_worker._propose_procedures(company.id, sprint.id, metrics)

    assert calls[0]["role"] == "ScrumMaster"
    assert "QA rework cycles: 2" in calls[0]["prompt"]
    assert "role=<one of: All, Developer, QA>" in calls[0]["prompt"]
    db.expire_all()
    stored = db.exec(select(Procedure).where(Procedure.company_id == company.id)).all()
    assert sorted((p.title, p.status) for p in stored) == [
        ("Small tasks", status),
        ("Validate inputs", status),
    ]
    messages = db.exec(
        select(AgentMessage).where(AgentMessage.company_id == company.id)
    ).all()
    assert {(m.kind, m.to_role) for m in messages} == {
        ("proposal", "Developer"),
        ("proposal", None),
    }
    expected = (
        "Adopted (autonomy level 3)"
        if autonomy == 3
        else "Proposed, waiting for a Manager"
    )
    assert all(m.body.startswith(expected) for m in messages)


def test_the_scrum_master_sees_what_earlier_procedures_did_and_cannot_repeat_a_failed_one(
    db, monkeypatch
):
    calls = _scrum_master_answers(monkeypatch, PROPOSAL_TEXT)
    company = _company(db, autonomy=3)
    db.add(task_worker.Agent(company_id=company.id, name="Dev", role="Developer"))
    db.commit()
    # The same "Validate inputs" text was adopted once and the board reverted it;
    # "Small tasks" was proposed once and a person rejected it.
    reverted, rejected = procedures.propose(
        db,
        company.id,
        procedures.parse_proposals(PROPOSAL_TEXT, ["Developer"]),
        "ScrumMaster",
    )
    reverted.status = "retired"
    reverted.baseline = {"rework_per_task": 0.5, "blocked_rate": 0.0}
    reverted.outcome = {
        "result": "reverted",
        "rework_per_task": 1.5,
        "blocked_rate": 0.5,
    }
    procedures.reject(db, rejected, "manager@example.com")
    kept = _adopted(db, company)
    kept.outcome = {"result": "kept", "rework_per_task": 0.0, "blocked_rate": 0.0}
    db.add_all([reverted, kept])
    db.commit()
    sprint = _sprint(db, company, tasks=2, reworks=2)

    task_worker._propose_procedures(
        company.id, sprint.id, task_worker._build_sprint_retrospective(sprint.id)
    )

    prompt = calls[0]["prompt"]
    assert "## What earlier procedures did" in prompt
    assert (
        '- "Validate inputs" (Developer, v1): reverted, '
        "rework per task 0.5 → 1.5, blocked 0.0 → 0.5"
    ) in prompt
    assert '- "Small tasks" (All, v1): rejected by a person' in prompt
    assert '- "Rule" (Developer, v1): kept, rework per task' in prompt
    assert prompt.index('"Rule"') < prompt.index('"Validate inputs"')  # newest first
    assert "nor one that was reverted or rejected" in prompt
    db.expire_all()
    # The same two texts again: neither is recorded, so autonomy adopts nothing.
    assert db.exec(
        select(Procedure).where(
            Procedure.company_id == company.id, Procedure.status == "active"
        )
    ).all() == [kept]
    assert (
        db.exec(
            select(AgentMessage).where(
                AgentMessage.company_id == company.id, AgentMessage.kind == "proposal"
            )
        ).all()
        == []
    )


def test_a_person_can_bring_back_a_rejected_procedure(db):
    company = _company(db)
    rule = {"role": "Developer", "title": "Rule", "body": "Write the test first."}
    [first] = procedures.propose(db, company.id, [rule], "ScrumMaster")
    procedures.reject(db, first, "manager@example.com")
    db.commit()

    assert (
        procedures.propose(db, company.id, [rule], "ScrumMaster", skip_failed=True)
        == []
    )
    [again] = procedures.propose(db, company.id, [rule], "manager@example.com")
    assert again.id != first.id


def test_no_history_before_any_procedure_has_a_result(db):
    company = _company(db)
    _adopted(db, company)  # active, not measured yet
    procedures.propose(
        db,
        company.id,
        [{"role": "QA", "title": "Waiting", "body": "Pending."}],
        "ScrumMaster",
    )
    assert procedures.history_prompt(db, company.id) == ""


def test_no_proposal_after_a_clean_sprint(db, monkeypatch):
    calls = _scrum_master_answers(monkeypatch, PROPOSAL_TEXT)
    company = _company(db, autonomy=3)
    sprint = _sprint(db, company, tasks=2)
    task_worker._propose_procedures(
        company.id, sprint.id, task_worker._build_sprint_retrospective(sprint.id)
    )
    assert calls == []


def test_sprint_close_measures_procedures_and_tells_the_team(db, monkeypatch):
    _scrum_master_answers(monkeypatch, "NONE")
    from memory import engram_processor

    monkeypatch.setattr(
        engram_processor,
        "get_engram_processor",
        lambda: (_ for _ in ()).throw(RuntimeError()),
    )
    company = _company(db)
    _sprint(db, company, tasks=2, reworks=1)
    procedure = _adopted(db, company)
    _sprint(db, company, tasks=2, reworks=1)
    closing = _sprint(db, company, tasks=1, status="active")

    asyncio.run(task_worker._finalize_sprint_if_ready(_FakeNATS(), closing.id))

    db.expire_all()
    assert db.get(Procedure, procedure.id).outcome["result"] == "kept"
    messages = db.exec(
        select(AgentMessage)
        .where(AgentMessage.sprint_id == closing.id)
        .order_by(AgentMessage.id)
    ).all()
    assert [m.kind for m in messages] == ["retrospective", "proposal"]
    assert "is kept" in messages[1].body


def test_active_procedures_reach_the_role_prompt(db, monkeypatch):
    company = _company(db)
    for role, title in (
        ("Developer", "Dev rule"),
        ("All", "Team rule"),
        ("QA", "QA rule"),
    ):
        procedures.adopt(
            db,
            procedures.propose(
                db,
                company.id,
                [{"role": role, "title": title, "body": f"{title} body"}],
                "x",
            )[0],
            "x",
        )
    db.commit()

    context = task_worker._load_procedures_context(company.id, "Developer")
    assert "Dev rule" in context and "Team rule" in context and "QA rule" not in context

    prompts = _scrum_master_answers(monkeypatch, "Done.")
    task_worker._execute_task(
        {"id": 1, "title": "Do it"},
        {"role": "Developer"},
        "S",
        procedures_context=context,
    )
    assert "## Company Procedures" in prompts[0]["prompt"]
    assert "Dev rule body" in prompts[0]["prompt"]


# ── API ──────────────────────────────────────────────────────────────────────


@pytest.fixture()
def people(sqlite_session, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    key = secrets.token_urlsafe(48)
    monkeypatch.setattr(auth_tokens, "_configured_key", lambda: key)
    company = _company(sqlite_session)
    headers = {}
    for role in ("Manager", "Viewer"):
        user = User(
            email=f"{role.lower()}-{secrets.token_hex(4)}@example.com",
            full_name=role,
            password_hash="x",
        )
        sqlite_session.add(user)
        sqlite_session.commit()
        sqlite_session.add(
            CompanyMember(company_id=company.id, user_id=user.id, human_role=role)
        )
        sqlite_session.commit()
        headers[role] = {
            "Authorization": "Bearer "
            + auth_tokens.create_access_token(user_id=user.id, email=user.email)
        }
    return company, headers


def test_api_manager_writes_adopts_rejects_and_retires(
    test_client, sqlite_session, people
):
    company, headers = people
    body = {
        "company_id": company.id,
        "role": "QA",
        "title": "Run the tests",
        "body": "Always run them.",
    }

    assert (
        test_client.post(
            "/v1/procedures", json=body, headers=headers["Viewer"]
        ).status_code
        == 403
    )
    created = test_client.post("/v1/procedures", json=body, headers=headers["Manager"])
    assert created.status_code == 201
    assert created.json()["status"] == "active"
    assert created.json()["decided_by"].startswith("manager-")
    assert (
        test_client.post(
            "/v1/procedures", json=body, headers=headers["Manager"]
        ).status_code
        == 409
    )

    proposals = procedures.propose(
        sqlite_session,
        company.id,
        [
            {"role": "Developer", "title": "A", "body": "a"},
            {"role": "Developer", "title": "B", "body": "b"},
        ],
        "ScrumMaster",
    )
    sqlite_session.commit()
    adopt = test_client.post(
        f"/v1/procedures/{proposals[0].id}/adopt", headers=headers["Manager"]
    )
    assert adopt.json()["status"] == "active"
    reject = test_client.post(
        f"/v1/procedures/{proposals[1].id}/reject", headers=headers["Manager"]
    )
    assert reject.json()["status"] == "rejected"
    assert (
        test_client.post(
            f"/v1/procedures/{proposals[1].id}/adopt", headers=headers["Manager"]
        ).status_code
        == 409
    )
    retire = test_client.post(
        f"/v1/procedures/{created.json()['id']}/retire", headers=headers["Manager"]
    )
    assert retire.json()["status"] == "retired"
    assert (
        test_client.post(
            "/v1/procedures/999999/adopt", headers=headers["Manager"]
        ).status_code
        == 404
    )

    listed = test_client.get(
        "/v1/procedures", params={"company_id": company.id}, headers=headers["Viewer"]
    ).json()
    assert [p["title"] for p in listed["procedures"]] == ["B", "A", "Run the tests"]
    active = test_client.get(
        "/v1/procedures",
        params={"company_id": company.id, "status": "active"},
        headers=headers["Viewer"],
    ).json()
    assert [p["title"] for p in active["procedures"]] == ["A"]
    bad = test_client.get(
        "/v1/procedures",
        params={"company_id": company.id, "status": "x"},
        headers=headers["Viewer"],
    )
    assert bad.status_code == 400
