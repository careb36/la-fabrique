"""
services/scrum_master.py: the ScrumMaster answers an escalation.

- The answer is asked for in a fixed format; only that format is a decision.
- The decision is recorded as a message to the assignee (another attempt,
  with a brief) or to nobody in particular (a person decides), and read back
  from the conversation.
- A failed call or an unusable answer records nothing: the company keeps its
  deterministic default.
- The decision reaches the loop: a task left for a person is not carried over
  on the company's own; a brief travels with the new attempt into the prompt.
"""

import secrets

import pytest
from models import Agent, AgentMessage, BacklogItem, Company, Sprint
from services import carry_over, scrum_master
from services.board import CARRIED_FROM_PREFIX
from sqlmodel import select

TRIAGE = (
    "Pre-review quality gate failed after 2 rework(s) — blocked for manual triage: "
    "Too short (41 words, minimum 180)."
)
RETRY_ANSWER = (
    "DECISION: retry\n"
    "BRIEF: Write the full strategy document (at least 180 words) with sections for "
    "unit, integration and end-to-end tests, as a path= block.\n"
    "WHY: the attempts were cut short, not wrong.\n"
    "END"
)


@pytest.fixture()
def company(sqlite_session):
    company = Company(company_name=f"SM {secrets.token_hex(3)}", autonomy_level=3)
    sqlite_session.add(company)
    sqlite_session.commit()
    sqlite_session.refresh(company)
    sprint = Sprint(company_id=company.id, sprint_name="Sprint 0", status="active")
    sqlite_session.add(sprint)
    sqlite_session.commit()
    sqlite_session.refresh(sprint)
    return company, sprint


def _blocked(session, sprint, comments=None, **fields):
    item = BacklogItem(
        sprint_id=sprint.id,
        title=fields.pop("title", "Create testing strategy document"),
        description="Define the testing pyramid.",
        priority="high",
        assignee="QA",
        status=fields.pop("status", "blocked"),
        comments=comments
        or [
            {"author": "QA Quinn", "text": "NEEDS WORK: cover integration tests too"},
            {"author": "Quality gate", "text": "NEEDS WORK: Too short (12 words)."},
            {"author": "Quality gate", "text": TRIAGE},
        ],
        **fields,
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


# ---------------------------------------------------------------------------
# The question and the answer
# ---------------------------------------------------------------------------


def test_the_prompt_carries_the_task_the_block_and_the_rework_asked(
    sqlite_session, company
):
    _company, sprint = company
    item = _blocked(sqlite_session, sprint)

    prompt = scrum_master.triage_prompt(item, TRIAGE, "\n\n## Company Procedures\nx")

    assert prompt.startswith("You are the ScrumMaster. A task was blocked")
    assert "## Task: Create testing strategy document" in prompt
    assert "Assigned to: QA" in prompt
    assert f"## What blocked it\n{TRIAGE}" in prompt
    assert "- QA Quinn: NEEDS WORK: cover integration tests too" in prompt
    assert "- Quality gate: NEEDS WORK: Too short (12 words)." in prompt
    assert "## Company Procedures" in prompt
    assert "DECISION: <retry or person>" in prompt


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        (
            RETRY_ANSWER,
            {
                "decision": "retry",
                "brief": "Write the full strategy document (at least 180 words) with sections for unit, integration and end-to-end tests, as a path= block.",
                "why": "the attempts were cut short, not wrong.",
            },
        ),
        (
            "Sure.\nDECISION: person\nBRIEF: n/a\nWHY: it needs the team's test budget.\nEND\nThanks",
            {
                "decision": "person",
                "brief": "",
                "why": "it needs the team's test budget.",
            },
        ),
        ("decision: Retry\nEND", {"decision": "retry", "brief": "", "why": ""}),
        ("I think it should be retried with a longer document.", None),
        ("DECISION: maybe\nEND", None),
        ("DECISION: retry\nBRIEF: no END marker", None),
    ],
    ids=["retry", "person", "bare", "prose", "unknown", "unterminated"],
)
def test_only_the_fixed_format_is_a_decision(answer, expected):
    assert scrum_master.parse_answer(answer) == expected


def test_a_long_brief_is_cut():
    answer = f"DECISION: retry\nBRIEF: {'x' * 700}\nWHY: y\nEND"

    assert len(scrum_master.parse_answer(answer)["brief"]) == scrum_master.BRIEF_LIMIT


def test_the_decision_is_asked_of_the_companys_scrum_master(
    sqlite_session, company, monkeypatch
):
    company, _sprint = company
    sqlite_session.add(
        Agent(
            company_id=company.id,
            name="Sam",
            role="ScrumMaster",
            model="deepseek-v4-pro",
            system_prompt="Be brief.",
        )
    )
    sqlite_session.commit()
    calls = []

    class _Client:
        def __init__(self, base_url=None):
            self.timeout = None

        def chat(self, messages, model, role, bu_id=None):
            calls.append((messages, model, role, self.timeout))
            return {"choices": [{"message": {"content": "  DECISION: person\nEND "}}]}

    monkeypatch.setattr(scrum_master, "LLMProxyClient", _Client)

    answer = scrum_master.ask(sqlite_session, company.id, "the question")

    assert answer == "DECISION: person\nEND"
    (messages, model, role, timeout) = calls[0]
    assert (model, role, timeout) == ("deepseek-v4-pro", "ScrumMaster", 90)
    assert messages == [
        {"role": "system", "content": "Be brief."},
        {"role": "user", "content": "the question"},
    ]


@pytest.mark.parametrize(
    "result",
    [{"error": "proxy down", "status_code": 503}, {"choices": [{"message": {}}]}],
    ids=["error", "empty"],
)
def test_a_failed_call_raises(sqlite_session, company, monkeypatch, result):
    company, _sprint = company

    class _Client:
        def __init__(self, base_url=None):
            self.timeout = None

        def chat(self, messages, model, role, bu_id=None):
            return result

    monkeypatch.setattr(scrum_master, "LLMProxyClient", _Client)

    with pytest.raises(scrum_master.ScrumMasterError):
        scrum_master.ask(sqlite_session, company.id, "q")


# ---------------------------------------------------------------------------
# The decision, recorded and read back
# ---------------------------------------------------------------------------


def test_the_triage_is_a_message_the_conversation_keeps(
    sqlite_session, company, monkeypatch
):
    company, sprint = company
    item = _blocked(sqlite_session, sprint)
    asked = []

    def _ask(model, system_prompt, prompt):
        asked.append((model, prompt))
        return RETRY_ANSWER

    monkeypatch.setattr(scrum_master, "ask_triage", _ask)

    message = scrum_master.triage(sqlite_session, company.id, sprint.id, item, TRIAGE)
    sqlite_session.commit()

    assert asked[0][0] and "## What blocked it" in asked[0][1]
    recorded = sqlite_session.exec(
        select(AgentMessage).where(AgentMessage.backlog_item_id == item.id)
    ).one()
    assert recorded.id == message.id
    assert (
        recorded.from_role,
        recorded.to_role,
        recorded.kind,
        recorded.sprint_id,
    ) == (
        "ScrumMaster",
        "QA",
        "decision",
        sprint.id,
    )
    assert recorded.body == (
        "Triage decision: another attempt in the next sprint.\n"
        "Why: the attempts were cut short, not wrong.\n"
        "Brief for the next attempt: Write the full strategy document (at least 180 "
        "words) with sections for unit, integration and end-to-end tests, as a path= block."
    )
    assert scrum_master.decision_for(sqlite_session, item.id) == {
        "decision": "retry",
        "why": "the attempts were cut short, not wrong.",
        "brief": "Write the full strategy document (at least 180 words) with sections for unit, integration and end-to-end tests, as a path= block.",
    }


def test_a_person_decision_is_addressed_to_nobody_and_read_back(
    sqlite_session, company, monkeypatch
):
    company, sprint = company
    item = _blocked(sqlite_session, sprint)
    monkeypatch.setattr(
        scrum_master,
        "ask_triage",
        lambda *a: "DECISION: person\nWHY: it needs a budget decision.\nEND",
    )

    message = scrum_master.triage(sqlite_session, company.id, sprint.id, item, TRIAGE)
    sqlite_session.commit()

    assert message.to_role is None
    assert message.body == (
        "Triage decision: leave it for a person.\nWhy: it needs a budget decision."
    )
    assert scrum_master.decision_for(sqlite_session, item.id) == {
        "decision": "person",
        "why": "it needs a budget decision.",
        "brief": "",
    }


@pytest.mark.parametrize(
    "ask",
    [
        lambda *a: (_ for _ in ()).throw(scrum_master.ScrumMasterError("proxy 503")),
        lambda *a: "I would retry it.",
    ],
    ids=["failed-call", "unusable-answer"],
)
def test_without_a_usable_answer_nothing_is_recorded(
    sqlite_session, company, monkeypatch, ask
):
    company, sprint = company
    item = _blocked(sqlite_session, sprint)
    monkeypatch.setattr(scrum_master, "ask_triage", ask)

    assert (
        scrum_master.triage(sqlite_session, company.id, sprint.id, item, TRIAGE) is None
    )
    sqlite_session.commit()

    assert (
        sqlite_session.exec(
            select(AgentMessage).where(AgentMessage.backlog_item_id == item.id)
        ).all()
        == []
    )
    assert scrum_master.decision_for(sqlite_session, item.id) is None


def test_other_scrum_master_messages_are_not_a_triage(sqlite_session, company):
    company, sprint = company
    item = _blocked(sqlite_session, sprint)
    sqlite_session.add(
        AgentMessage(
            company_id=company.id,
            sprint_id=sprint.id,
            backlog_item_id=item.id,
            from_name="ScrumMaster",
            from_role="ScrumMaster",
            to_role="QA",
            kind="decision",
            body='"Create testing strategy document" gets another attempt in sprint "Sprint 1".',
        )
    )
    sqlite_session.commit()

    assert scrum_master.decision_for(sqlite_session, item.id) is None


# ---------------------------------------------------------------------------
# The decision reaches the loop
# ---------------------------------------------------------------------------


def _decide(monkeypatch, session, company, sprint, item, answer):
    monkeypatch.setattr(scrum_master, "ask_triage", lambda *a: answer)
    scrum_master.triage(session, company.id, sprint.id, item, TRIAGE)
    session.commit()


def test_the_brief_travels_with_the_next_attempt(sqlite_session, company, monkeypatch):
    company, sprint = company
    item = _blocked(sqlite_session, sprint)
    _decide(monkeypatch, sqlite_session, company, sprint, item, RETRY_ANSWER)
    next_sprint = Sprint(company_id=company.id, sprint_name="Sprint 1", status="active")
    sqlite_session.add(next_sprint)
    sqlite_session.commit()

    (clone,) = carry_over.carry_over_on_the_companys_own(
        sqlite_session, company.id, sprint.id, next_sprint, room=4
    )
    sqlite_session.commit()

    note = clone.comments[0]["text"]
    assert note.startswith(
        f'Carried over from task {item.id} ("Sprint 0"), which was blocked: {TRIAGE}'
    )
    assert "\nBrief for the next attempt: Write the full strategy document" in note
    prompt_section = carry_over.previous_attempt_context(clone)
    assert "## Previous attempt" in prompt_section
    assert (
        "Brief for the next attempt: Write the full strategy document" in prompt_section
    )
    told = sqlite_session.exec(
        select(AgentMessage).where(AgentMessage.backlog_item_id == clone.id)
    ).one()
    assert "Brief for the next attempt:" in told.body


def test_a_task_left_for_a_person_is_not_carried_on_the_companys_own(
    sqlite_session, company, monkeypatch
):
    company, sprint = company
    kept = _blocked(sqlite_session, sprint, title="Needs a budget")
    _decide(
        monkeypatch,
        sqlite_session,
        company,
        sprint,
        kept,
        "DECISION: person\nWHY: budget.\nEND",
    )
    retried = _blocked(sqlite_session, sprint, title="Just too short")
    _decide(monkeypatch, sqlite_session, company, sprint, retried, RETRY_ANSWER)
    undecided = _blocked(sqlite_session, sprint, title="No answer")
    next_sprint = Sprint(company_id=company.id, sprint_name="Sprint 1", status="active")
    sqlite_session.add(next_sprint)
    sqlite_session.commit()

    clones = carry_over.carry_over_on_the_companys_own(
        sqlite_session, company.id, sprint.id, next_sprint, room=4
    )
    sqlite_session.commit()

    assert [c.title for c in clones] == ["Just too short", "No answer"]
    assert carry_over.left_for_a_person(sqlite_session, kept)
    assert not carry_over.left_for_a_person(sqlite_session, undecided)
    # A person may still carry it over by hand: the triage is advice.
    (by_hand,) = carry_over.carry_over(
        sqlite_session, company.id, [kept.id], next_sprint, "ana", "Manager"
    )
    assert by_hand.title == "Needs a budget"


# ---------------------------------------------------------------------------
# What the review of this module asked for
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        (
            "**DECISION:** `retry`\n**BRIEF:** Write the full document\n(at least 180 words) as a path= block.\n**WHY:** cut short.\n**END**",
            {
                "decision": "retry",
                "brief": "Write the full document (at least 180 words) as a path= block.",
                "why": "cut short.",
            },
        ),
        (
            'DECISION: "person"\nWHY: needs a budget decision\nthe team cannot make.\nEND',
            {
                "decision": "person",
                "brief": "",
                "why": "needs a budget decision the team cannot make.",
            },
        ),
    ],
    ids=["markdown-and-wrapped-brief", "quoted-and-wrapped-why"],
)
def test_markdown_and_wrapped_fields_are_still_a_decision(answer, expected):
    assert scrum_master.parse_answer(answer) == expected


def test_the_prompt_shows_only_the_rework_since_the_last_send_back(
    sqlite_session, company
):
    _company, sprint = company
    item = _blocked(
        sqlite_session,
        sprint,
        comments=[
            {"author": "QA Quinn", "text": "NEEDS WORK: the old attempt's problem"},
            {"author": "Quality gate", "text": TRIAGE},
            {"author": "user", "text": "Sent back to work by a person."},
            {"author": "Quality gate", "text": "NEEDS WORK: Too short (30 words)."},
        ],
    )

    prompt = scrum_master.triage_prompt(item, TRIAGE)

    assert "- Quality gate: NEEDS WORK: Too short (30 words)." in prompt
    assert "the old attempt's problem" not in prompt


def test_a_decision_answers_one_escalation_only(sqlite_session, company, monkeypatch):
    """Sent back by a person and blocked again, the task is escalated again; the
    earlier triage no longer counts, so an unanswered new block keeps the default."""
    company, sprint = company
    item = _blocked(sqlite_session, sprint, title="Needs a budget")

    def _escalate():
        sqlite_session.add(
            AgentMessage(
                company_id=company.id,
                sprint_id=sprint.id,
                backlog_item_id=item.id,
                from_name="Quality gate",
                from_role="Quality gate",
                to_role="ScrumMaster",
                kind="escalation",
                body=TRIAGE,
            )
        )
        sqlite_session.commit()

    _escalate()
    _decide(monkeypatch, sqlite_session, company, sprint, item, "DECISION: person\nEND")
    assert scrum_master.decision_for(sqlite_session, item.id)["decision"] == "person"
    assert carry_over.left_for_a_person(sqlite_session, item)

    _escalate()  # blocked again after a send-back; this time no usable answer

    assert scrum_master.decision_for(sqlite_session, item.id) is None
    assert not carry_over.left_for_a_person(sqlite_session, item)

    _decide(monkeypatch, sqlite_session, company, sprint, item, RETRY_ANSWER)
    assert scrum_master.decision_for(sqlite_session, item.id)["decision"] == "retry"
    assert scrum_master.decisions_for(sqlite_session, [item.id, 999_999]) == {
        item.id: scrum_master.decision_for(sqlite_session, item.id)
    }
    assert scrum_master.decisions_for(sqlite_session, []) == {}


# ---------------------------------------------------------------------------
# What the review of the merged triage asked for
# ---------------------------------------------------------------------------


def test_a_wrapped_line_starting_with_end_does_not_end_the_answer():
    answer = (
        "DECISION: retry\n"
        "BRIEF: Deliver all files and\n"
        "end-to-end tests for the parser.\n"
        "WHY: the tests were missing\n"
        "END"
    )

    assert scrum_master.parse_answer(answer) == {
        "decision": "retry",
        "brief": "Deliver all files and end-to-end tests for the parser.",
        "why": "the tests were missing",
    }


@pytest.mark.parametrize(
    "answer",
    [
        "DECISION: retry\nBRIEF: Finish the document.\nWHY: cut short\nEND.",
        "DECISION: retry\r\nBRIEF: Finish the document.\r\nWHY: cut short\r\nEND\r\n",
    ],
    ids=["end-with-a-period", "windows-line-endings"],
)
def test_end_with_a_period_or_windows_line_endings_still_closes_the_answer(answer):
    assert scrum_master.parse_answer(answer) == {
        "decision": "retry",
        "brief": "Finish the document.",
        "why": "cut short",
    }


def test_a_send_back_during_the_triage_makes_the_answer_stale(
    sqlite_session, company, monkeypatch
):
    """On the Verifier and QA paths the task is blocked before the ScrumMaster
    answers. A person who sends it back in that window acted on the old block,
    so the answer, recorded after the send-back, does not govern the next one."""
    from datetime import UTC, datetime, timedelta

    company, sprint = company
    item = _blocked(sqlite_session, sprint, title="Sent back mid-triage")
    escalated_at = datetime.now(UTC) - timedelta(seconds=30)
    sqlite_session.add(
        AgentMessage(
            company_id=company.id,
            sprint_id=sprint.id,
            backlog_item_id=item.id,
            from_name="Verifier",
            from_role="Verifier",
            to_role="ScrumMaster",
            kind="escalation",
            body=TRIAGE,
            created_at=escalated_at,
        )
    )
    sent_back_at = escalated_at + timedelta(seconds=10)
    item.comments = [
        *item.comments,
        {
            "author": "user",
            "text": "Sent back to work by a person.",
            "created_at": str(sent_back_at.replace(tzinfo=None)),
        },
        {"author": "System", "text": "Agent error: proxy 503"},
    ]
    sqlite_session.add(item)
    sqlite_session.commit()

    # The answer lands now, after the send-back.
    _decide(monkeypatch, sqlite_session, company, sprint, item, "DECISION: person\nEND")

    assert scrum_master.decision_for(sqlite_session, item.id) is None
    assert not carry_over.left_for_a_person(sqlite_session, item)


def test_a_send_back_after_the_decision_makes_it_stale(
    sqlite_session, company, monkeypatch
):
    """A person sent the task back after the ScrumMaster answered, and the next
    attempt failed without an escalation (an agent error): the old decision is
    about another block and no longer counts."""
    from datetime import UTC, datetime, timedelta

    company, sprint = company
    item = _blocked(sqlite_session, sprint, title="Sent back since")
    _decide(monkeypatch, sqlite_session, company, sprint, item, "DECISION: person\nEND")
    assert scrum_master.decision_for(sqlite_session, item.id)["decision"] == "person"

    later = datetime.now(UTC) + timedelta(seconds=5)
    item.comments = [
        *item.comments,
        {
            "author": "user",
            "text": "Sent back to work by a person.",
            "created_at": str(later.replace(tzinfo=None)),
        },
        {"author": "System", "text": "Agent error: proxy 503"},
    ]
    sqlite_session.add(item)
    sqlite_session.commit()

    assert scrum_master.decision_for(sqlite_session, item.id) is None
    assert scrum_master.triages_for(sqlite_session, [item]) == {}
    assert not carry_over.left_for_a_person(sqlite_session, item)


def test_the_triage_asks_once_with_a_short_timeout(monkeypatch):
    seen = []

    class _Client:
        def __init__(self, base_url=None):
            self.timeout = None
            self.max_retries = 2

        def chat(self, messages, model, role, bu_id=None):
            seen.append((self.timeout, self.max_retries))
            return {"choices": [{"message": {"content": "DECISION: person\nEND"}}]}

    monkeypatch.setattr(scrum_master, "LLMProxyClient", _Client)

    scrum_master.ask_triage("m", None, "q")
    scrum_master.ask_model("m", None, "q")

    assert seen == [
        (scrum_master.TRIAGE_TIMEOUT_SECONDS, 0),
        (scrum_master.TIMEOUT_SECONDS, 2),
    ]


def test_the_triage_prompt_carries_how_second_attempts_went(sqlite_session, company):
    company_row, sprint = company
    closed = Sprint(
        company_id=company_row.id, sprint_name="Sprint 1", status="completed"
    )
    sqlite_session.add(closed)
    sqlite_session.commit()
    sqlite_session.refresh(closed)
    note = f'{CARRIED_FROM_PREFIX} task 1 ("Sprint 0"), which was blocked: too short'
    briefed = f"{note}\n{scrum_master.BRIEF_PREFIX}Write it in full."
    for status, text in (("done", briefed), ("blocked", briefed), ("blocked", note)):
        _blocked(
            sqlite_session,
            closed,
            comments=[{"author": "System", "text": text}],
            status=status,
        )
    # Still open, so its outcome is unknown and it does not count.
    _blocked(sqlite_session, sprint, comments=[{"author": "System", "text": briefed}])
    item = _blocked(sqlite_session, sprint)

    assert scrum_master.track_record(sqlite_session, company_row.id) == {
        "total": 3,
        "done": 1,
        "briefed": 2,
        "briefed_done": 1,
    }
    prompt, _model, _system = scrum_master.prepare_triage(
        sqlite_session, company_row.id, item, TRIAGE
    )
    assert "## How second attempts went in this company" in prompt
    assert "1 of 3 tasks carried into another sprint got done." in prompt
    assert "With a brief from you: 1 of 2; without one: 0 of 1." in prompt
    assert prompt.index("How second attempts went") < prompt.index("DECISION:")


def test_without_second_attempts_the_prompt_has_no_track_record(
    sqlite_session, company
):
    company_row, sprint = company
    item = _blocked(sqlite_session, sprint)

    prompt, _model, _system = scrum_master.prepare_triage(
        sqlite_session, company_row.id, item, TRIAGE
    )

    assert "How second attempts went" not in prompt


def test_a_decision_is_judged_by_the_escalation_it_names(
    sqlite_session, company, monkeypatch
):
    """The worker records which escalation a decision answers. One that names an
    older escalation is dropped however late it was recorded; one that names the
    latest counts, until a person sends the task back after that escalation."""
    from datetime import UTC, datetime, timedelta

    company_row, sprint = company
    item = _blocked(sqlite_session, sprint, title="Answered late")
    now = datetime.now(UTC)

    def escalate(at):
        message = AgentMessage(
            company_id=company_row.id,
            sprint_id=sprint.id,
            backlog_item_id=item.id,
            from_name="Verifier",
            from_role="Verifier",
            to_role="ScrumMaster",
            kind="escalation",
            body=TRIAGE,
            created_at=at,
        )
        sqlite_session.add(message)
        sqlite_session.commit()
        sqlite_session.refresh(message)
        return message

    first = escalate(now - timedelta(seconds=60))
    second = escalate(now - timedelta(seconds=20))
    # The answer to the first escalation lands after the second was posted.
    person = {"decision": "person", "why": "needs a budget", "brief": ""}
    scrum_master.record_decision(
        sqlite_session,
        company_row.id,
        sprint.id,
        item.id,
        "QA",
        person,
        answers=first.id,
    )
    sqlite_session.commit()
    assert scrum_master.decision_for(sqlite_session, item.id) is None
    assert not carry_over.left_for_a_person(sqlite_session, item)

    retry = {"decision": "retry", "why": "cut short", "brief": "Write it in full."}
    recorded = scrum_master.record_decision(
        sqlite_session,
        company_row.id,
        sprint.id,
        item.id,
        "QA",
        retry,
        answers=second.id,
    )
    sqlite_session.commit()
    assert scrum_master.answered_escalation(recorded.body) == second.id
    assert scrum_master.parse_decision_body(recorded.body) == retry
    assert scrum_master.decision_for(sqlite_session, item.id) == retry

    # A send-back after the escalation it answers makes it stale, even though the
    # decision itself was recorded later still.
    item.comments = [
        *item.comments,
        {
            "author": "user",
            "text": "Sent back to work by a person.",
            "created_at": str((now - timedelta(seconds=10)).replace(tzinfo=None)),
        },
    ]
    sqlite_session.add(item)
    sqlite_session.commit()
    assert scrum_master.decision_for(sqlite_session, item.id) is None


def test_the_worker_names_the_escalation_in_the_decision(
    sqlite_session, company, monkeypatch
):
    from services import task_worker

    company_row, sprint = company
    item = _blocked(sqlite_session, sprint, title="Named by the worker")
    escalation = AgentMessage(
        company_id=company_row.id,
        sprint_id=sprint.id,
        backlog_item_id=item.id,
        from_name="Quality gate",
        from_role="Quality gate",
        to_role="ScrumMaster",
        kind="escalation",
        body=TRIAGE,
    )
    sqlite_session.add(escalation)
    sqlite_session.commit()
    sqlite_session.refresh(escalation)
    monkeypatch.setattr(task_worker, "engine", sqlite_session.get_bind())
    monkeypatch.setattr(scrum_master, "ask_triage", lambda *a, **k: RETRY_ANSWER)

    task_worker._triage_blocked_task(
        company_row.id, sprint.id, item.id, TRIAGE, escalation.id
    )

    sqlite_session.expire_all()
    decision = sqlite_session.exec(
        select(AgentMessage).where(
            AgentMessage.backlog_item_id == item.id, AgentMessage.kind == "decision"
        )
    ).one()
    assert scrum_master.answered_escalation(decision.body) == escalation.id
    assert scrum_master.decision_for(sqlite_session, item.id)["decision"] == "retry"
