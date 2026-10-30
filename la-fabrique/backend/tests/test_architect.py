"""
The Architect's record: how tasks went after its briefs, counted from the
boards of the company's completed sprints, and told to it when it is asked
again.
"""

from uuid import uuid4

import pytest
from models.company import Agent, Company
from models.sprint import BacklogItem, Sprint
from services import architect, task_worker
from services.orchestration_metrics import (
    ARCHITECT_COMMENT_AUTHOR,
    format_architect_consult_comment,
)

BRIEF = {
    "author": ARCHITECT_COMMENT_AUTHOR,
    "text": format_architect_consult_comment("Reuse the parser; test empty input."),
}
REWORK = {"author": "QA", "text": "NEEDS WORK: cover the empty case"}


def _company(session, *, with_architect=True):
    company = Company(company_name=f"Architect {uuid4().hex[:8]}")
    session.add(company)
    session.commit()
    if with_architect:
        session.add(Agent(company_id=company.id, name="Ari", role="Architect"))
        session.commit()
    return company


def _sprint(session, company, status, tasks):
    sprint = Sprint(company_id=company.id, sprint_name="S", status=status)
    session.add(sprint)
    session.commit()
    for task_status, comments in tasks:
        session.add(
            BacklogItem(
                sprint_id=sprint.id,
                title="Task",
                status=task_status,
                comments=comments,
            )
        )
    session.commit()
    return sprint


def test_the_record_counts_completed_sprints_and_rework_from_the_brief_on(
    sqlite_session,
):
    company = _company(sqlite_session)
    _sprint(
        sqlite_session,
        company,
        "completed",
        [
            # Briefed after its first rework: one request is the brief's.
            ("done", [REWORK, BRIEF, REWORK]),
            ("blocked", [BRIEF, REWORK, REWORK]),
            ("done", []),
            ("blocked", [REWORK]),
        ],
    )
    # Still running: its outcomes are not known yet.
    _sprint(sqlite_session, company, "active", [("todo", [BRIEF])])
    # Another company's board is not this Architect's record.
    _sprint(sqlite_session, _company(sqlite_session), "completed", [("done", [BRIEF])])

    tally = architect.track_record(sqlite_session, company.id)

    assert tally == {
        "advised": {"total": 2, "done": 1, "rework": 3},
        "unadvised": {"total": 2, "done": 1, "rework": 1},
    }
    context = architect.track_record_context(tally)
    assert "## How tasks went after your earlier briefs" in context
    assert (
        "Tasks you briefed: 1 of 2 got done, 1.50 rework requests per task" in context
    )
    assert "Tasks without a brief: 1 of 2 got done, 0.50 rework requests per task" in (
        context
    )
    assert "counted from the boards, not reported by anyone" in context
    assert (
        architect.track_record_context(architect.track_record(sqlite_session, 0)) == ""
    )


@pytest.fixture()
def prompts(monkeypatch, sqlite_session):
    monkeypatch.setattr(task_worker, "engine", sqlite_session.get_bind())
    monkeypatch.setattr(task_worker, "record_agent_turn", lambda **kw: None)
    sent = []

    class _Client:
        def __init__(self, base_url=None):
            self.timeout = None

        def chat(self, messages, model, role, bu_id=None):
            sent.append(messages[-1]["content"])
            return {"choices": [{"message": {"content": "Use a service layer."}}]}

    monkeypatch.setattr(task_worker, "LLMProxyClient", _Client)
    return sent


def test_the_architect_is_told_how_its_earlier_briefs_went(prompts, sqlite_session):
    company = _company(sqlite_session)
    _sprint(sqlite_session, company, "completed", [("done", [BRIEF]), ("done", [])])
    sprint = _sprint(sqlite_session, company, "active", [])

    advice = task_worker._consult_architect(
        {"id": 1, "title": "Add parser", "description": "A function."},
        {"role": "Developer"},
        {"id": sprint.id, "company_id": company.id, "name": "S"},
    )

    assert advice == "Use a service layer."
    assert "Task: Add parser" in prompts[0]
    assert "Tasks you briefed: 1 of 1 got done, 0.00 rework" in prompts[0]


def test_no_record_before_any_brief(prompts, sqlite_session):
    company = _company(sqlite_session)
    sprint = _sprint(sqlite_session, company, "active", [])

    task_worker._consult_architect(
        {"id": 1, "title": "Add parser"},
        {"role": "Developer"},
        {"id": sprint.id, "company_id": company.id, "name": "S"},
    )

    assert "earlier briefs" not in prompts[0]


def test_a_failed_record_leaves_it_out_and_the_brief_still_comes(
    prompts, sqlite_session, monkeypatch
):
    company = _company(sqlite_session)
    sprint = _sprint(sqlite_session, company, "active", [])

    def _broken(session, company_id):
        raise RuntimeError("statement timeout")

    monkeypatch.setattr(task_worker, "architect_track_record", _broken)

    advice = task_worker._consult_architect(
        {"id": 1, "title": "Add parser"},
        {"role": "Developer"},
        {"id": sprint.id, "company_id": company.id, "name": "S"},
    )

    assert advice == "Use a service layer."
    assert "earlier briefs" not in prompts[0]
