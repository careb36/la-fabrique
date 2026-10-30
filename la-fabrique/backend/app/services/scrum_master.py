"""
The ScrumMaster answers escalations: the triage of a blocked task.

When a gate or a reviewer gives up on a task it is blocked and escalated to
the ScrumMaster. Here the ScrumMaster answers, as in a company: read what
blocked it and decide whether the task deserves another attempt in the next
sprint, with a brief saying what that attempt must do differently, or whether
it is better left for a person. The answer is asked for in a fixed format a
parser checks; anything else is no decision.

The decision is a message (``AgentMessage``, kind ``decision``), so it is a
claim: it changes what the company does next, never what the evidence says
about the task. ``carry_over`` reads it: a task the ScrumMaster left for a
person is not carried over on the company's own initiative, and the brief
of one it sent back travels with the new attempt into the agent's prompt.
Without a decision (the call failed, the answer was unusable) the company
keeps the deterministic default: one more attempt, then a person.
"""

import os
import re
from datetime import UTC, datetime
from typing import Any

from llm_proxy_client import LLMProxyClient
from logging_config import setup_logger
from models import Agent, AgentMessage, BacklogItem, Sprint
from sqlmodel import Session, select

from llm.model_factory import default_model_for_role
from services import procedures
from services.board import (
    BRIEF_PREFIX,
    SCRUM_MASTER_ROLE,
    count_second_attempt,
    is_rework_request,
    last_send_back_at,
    no_second_attempts,
    since_send_back,
)

logger = setup_logger("fabrique-scrum-master")

DECISION_RETRY = "retry"
DECISION_PERSON = "person"
TRIAGE_PREFIX = "Triage decision: "
RETRY_LINE = TRIAGE_PREFIX + "another attempt in the next sprint."
PERSON_LINE = TRIAGE_PREFIX + "leave it for a person."
WHY_PREFIX = "Why: "
# Written by the worker, never by the model: which escalation a decision answers.
ANSWERS_PREFIX = "Answers escalation #"
BRIEF_LIMIT = 600
WHY_LIMIT = 300
FEEDBACK_SHOWN = 3
FEEDBACK_CHARS = 400
TIMEOUT_SECONDS = 90
# The triage is advice the worker waits for: one short attempt, no retries, so
# a slow or failing proxy cannot hold the review loop for long.
TRIAGE_TIMEOUT_SECONDS = 45

_ANSWER = re.compile(
    r"DECISION:[\s*`\"']*(?P<decision>retry|person)\b"
    r"(?P<rest>.*?)(?:^|\n)[ \t*`]*END[ \t*`.]*(?:\n|$)",
    re.IGNORECASE | re.DOTALL,
)
_FIELD_START = re.compile(
    r"^[\s*`]*(?P<key>BRIEF|WHY)[\s*`]*:\s*(?P<value>.*)$", re.IGNORECASE
)
_DECORATION = "*`\"' \t"


class ScrumMasterError(RuntimeError):
    """The ScrumMaster's call produced no usable answer."""


# ---------------------------------------------------------------------------
# The question and its answer
# ---------------------------------------------------------------------------


def answer_format() -> str:
    """The format the ScrumMaster is asked to answer in; ``parse_answer`` reads it."""
    return (
        "Answer exactly in this form and nothing else:\n\n"
        "DECISION: <retry or person>\n"
        "BRIEF: <only for retry: what the next attempt must do differently, concrete "
        f"and short (at most {BRIEF_LIMIT} characters); one line>\n"
        "WHY: <one line>\n"
        "END\n\n"
        "Choose retry when the brief can realistically fix what blocked the task "
        "(a format or scope problem, a missing part, a misread requirement). Choose "
        "person when the task needs a decision, access or information an agent does "
        "not have, or when the attempts show the task itself is wrong."
    )


def track_record(session: Session, company_id: int) -> dict[str, int]:
    """How the company's second attempts went, over its completed sprints.

    The same tally the sprint list shows: tasks carried into another sprint,
    how many got done, and the same for those that came with a brief. Only
    closed sprints count, so every attempt has its outcome.
    """
    tally = no_second_attempts()
    for status, comments in session.exec(
        select(BacklogItem.status, BacklogItem.comments)
        .join(Sprint, Sprint.id == BacklogItem.sprint_id)
        .where(Sprint.company_id == company_id, Sprint.status == "completed")
    ).all():
        count_second_attempt(tally, status, comments)
    return tally


def track_record_context(tally: dict[str, int]) -> str:
    """The prompt section with the outcomes of earlier second attempts, or ''."""
    if not tally["total"]:
        return ""
    unbriefed = tally["total"] - tally["briefed"]
    return (
        "\n\n## How second attempts went in this company\n"
        f"{tally['done']} of {tally['total']} tasks carried into another sprint got done. "
        f"With a brief from you: {tally['briefed_done']} of {tally['briefed']}; "
        f"without one: {tally['done'] - tally['briefed_done']} of {unbriefed}. "
        "These are counted from the boards, not reported by anyone."
    )


def triage_prompt(
    item: BacklogItem,
    reason: str,
    procedures_context: str = "",
    record_context: str = "",
) -> str:
    """What the ScrumMaster is told about a blocked task."""
    feedback = [
        f"{c.get('author') or 'Reviewer'}: {str(c.get('text', '')).strip()[:FEEDBACK_CHARS]}"
        for c in since_send_back(item.comments)
        if is_rework_request(c)
    ][-FEEDBACK_SHOWN:]
    return (
        "You are the ScrumMaster. A task was blocked after the agents' attempts and "
        "escalated to you. Decide whether it gets another attempt in the next sprint "
        "or stays for a person.\n\n"
        f"## Task: {item.title}\n"
        f"Assigned to: {item.assignee or 'Developer'}\n"
        f"Priority: {item.priority or 'medium'}\n"
        f"Description: {item.description or '(none)'}\n\n"
        f"## What blocked it\n{reason.strip() or '(no reason recorded)'}\n\n"
        "## Rework the reviewers asked for\n"
        + ("\n".join(f"- {line}" for line in feedback) if feedback else "(none)")
        + f"{procedures_context}{record_context}\n\n"
        + answer_format()
    )


def parse_answer(text: str) -> dict[str, str] | None:
    """The decision in the expected form, or ``None`` when the answer is unusable.

    Markdown around the labels and values (bold, backticks, quotes) is ignored,
    a field the model wraps over several lines is joined into one, and the
    closing END may carry a period or Windows line endings.
    """
    match = _ANSWER.search((text or "").replace("\r\n", "\n").replace("\r", "\n"))
    if not match:
        return None
    decision = match["decision"].lower()
    fields: dict[str, list[str]] = {}
    current: str | None = None
    for line in match["rest"].split("\n"):
        start = _FIELD_START.match(line)
        if start:
            current = start["key"].upper()
            fields[current] = [start["value"]]
        elif current and line.strip():
            fields[current].append(line)
    cleaned = {
        key: " ".join(part.strip(_DECORATION) for part in parts).strip()
        for key, parts in fields.items()
    }
    brief = cleaned.get("BRIEF", "")[:BRIEF_LIMIT] if decision == DECISION_RETRY else ""
    return {
        "decision": decision,
        "brief": brief,
        "why": cleaned.get("WHY", "")[:WHY_LIMIT],
    }


def profile(session: Session, company_id: int) -> tuple[str, str | None]:
    """The company's ScrumMaster agent: its model (or the role's default) and system prompt."""
    scrum_master = session.exec(
        select(Agent).where(
            Agent.company_id == company_id, Agent.role == SCRUM_MASTER_ROLE
        )
    ).first()
    configured = (scrum_master.model if scrum_master else "") or ""
    model = configured.strip() or default_model_for_role(SCRUM_MASTER_ROLE)
    return model, (scrum_master.system_prompt if scrum_master else None) or None


def ask_model(
    model: str,
    system_prompt: str | None,
    prompt: str,
    *,
    timeout: float = TIMEOUT_SECONDS,
    retries: int | None = None,
) -> str:
    """One question to the ScrumMaster through the proxy; no database involved.

    *retries* ``None`` keeps the client's default (``LLM_PROXY_MAX_RETRIES``).
    """
    messages = [{"role": "user", "content": prompt}]
    if system_prompt:
        messages.insert(0, {"role": "system", "content": system_prompt})
    client = LLMProxyClient(
        base_url=os.getenv("LLM_PROXY_URL", "http://llm-proxy:5100")
    )
    client.timeout = timeout
    if retries is not None:
        client.max_retries = retries
    result = client.chat(messages=messages, model=model, role=SCRUM_MASTER_ROLE)
    if not isinstance(result, dict) or result.get("error"):
        raise ScrumMasterError(f"LLM call failed: {result!r}"[:500])
    choices = result.get("choices") or [{}]
    content = ((choices[0] or {}).get("message") or {}).get("content") or ""
    if not str(content).strip():
        raise ScrumMasterError("LLM call failed: empty response")
    return str(content).strip()


def ask(
    session: Session,
    company_id: int,
    prompt: str,
    *,
    timeout: float = TIMEOUT_SECONDS,
    retries: int | None = None,
) -> str:
    """Ask the company's ScrumMaster agent (its model, or the role's default)."""
    model, system_prompt = profile(session, company_id)
    return ask_model(model, system_prompt, prompt, timeout=timeout, retries=retries)


# ---------------------------------------------------------------------------
# The decision, recorded and read back
# ---------------------------------------------------------------------------


def decision_body(decision: dict[str, str], answers: int | None = None) -> str:
    """The recorded form of a decision; *answers* is the escalation's message id."""
    retry = decision["decision"] == DECISION_RETRY
    lines = [RETRY_LINE if retry else PERSON_LINE]
    if decision.get("why"):
        lines.append(WHY_PREFIX + decision["why"])
    if retry and decision.get("brief"):
        lines.append(BRIEF_PREFIX + decision["brief"])
    if answers is not None:
        lines.append(f"{ANSWERS_PREFIX}{answers}")
    return "\n".join(lines)


def parse_decision_body(body: str) -> dict[str, str] | None:
    """Read a recorded triage back; ``None`` for any other message."""
    lines = (body or "").split("\n")
    if lines[0] == RETRY_LINE:
        decision = DECISION_RETRY
    elif lines[0] == PERSON_LINE:
        decision = DECISION_PERSON
    else:
        return None
    why = brief = ""
    for line in lines[1:]:
        if line.startswith(WHY_PREFIX):
            why = line[len(WHY_PREFIX) :]
        elif line.startswith(BRIEF_PREFIX):
            brief = line[len(BRIEF_PREFIX) :]
    return {"decision": decision, "why": why, "brief": brief}


def answered_escalation(body: str) -> int | None:
    """The id of the escalation a recorded decision says it answers, if any."""
    for line in (body or "").split("\n"):
        if line.startswith(ANSWERS_PREFIX) and line[len(ANSWERS_PREFIX) :].isdigit():
            return int(line[len(ANSWERS_PREFIX) :])
    return None


def prepare_triage(
    session: Session, company_id: int, item: BacklogItem, reason: str
) -> tuple[str, str, str | None]:
    """What the triage needs from the database: the prompt and who answers it."""
    context = procedures.procedures_prompt(
        procedures.active_procedures(session, company_id, item.assignee)
    )
    record = track_record_context(track_record(session, company_id))
    model, system_prompt = profile(session, company_id)
    return triage_prompt(item, reason, context, record), model, system_prompt


def ask_triage(model: str, system_prompt: str | None, prompt: str) -> str:
    """The triage question itself: one short attempt (see ``TRIAGE_TIMEOUT_SECONDS``)."""
    return ask_model(
        model, system_prompt, prompt, timeout=TRIAGE_TIMEOUT_SECONDS, retries=0
    )


def decide(answer: str, item_id: int | None = None) -> dict[str, str] | None:
    """The decision in an answer, or ``None`` (logged) when it is unusable."""
    decision = parse_answer(answer)
    if decision is None:
        logger.info(
            "ScrumMaster triage of item=%s was unusable: %r", item_id, answer[:200]
        )
    return decision


def record_decision(
    session: Session,
    company_id: int,
    sprint_id: int | None,
    item_id: int,
    assignee: str | None,
    decision: dict[str, str],
    answers: int | None = None,
) -> AgentMessage:
    """Record a triage as the ScrumMaster's ``decision`` message. The caller commits.

    *answers* is the id of the escalation message it replies to; with it, the
    decision is read back against that escalation and not against whichever
    was the latest when the answer finally arrived.
    """
    message = AgentMessage(
        company_id=company_id,
        sprint_id=sprint_id,
        backlog_item_id=item_id,
        from_name=SCRUM_MASTER_ROLE,
        from_role=SCRUM_MASTER_ROLE,
        to_role=assignee if decision["decision"] == DECISION_RETRY else None,
        kind="decision",
        body=decision_body(decision, answers),
    )
    session.add(message)
    return message


def triage(
    session: Session, company_id: int, sprint_id: int, item: BacklogItem, reason: str
) -> AgentMessage | None:
    """Ask the ScrumMaster about a blocked task and record its decision, in one session.

    Returns the recorded message, or ``None`` when the call failed or the
    answer was unusable: the company then keeps its deterministic default.
    The caller commits. The task worker uses the steps above instead, so no
    database connection is held while the model answers.
    """
    try:
        prompt, model, system_prompt = prepare_triage(session, company_id, item, reason)
        answer = ask_triage(model, system_prompt, prompt)
    except Exception as exc:  # noqa: BLE001 - The triage is advice; the task stays blocked for a person either way.
        logger.warning("ScrumMaster triage failed for item=%s: %s", item.id, exc)
        return None
    decision = decide(answer, item.id)
    if decision is None:
        return None
    return record_decision(
        session, company_id, sprint_id, item.id, item.assignee, decision
    )


def _naive_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value


def decisions_for(
    session: Session,
    item_ids: list[int],
    sent_back_at: dict[int, datetime] | None = None,
) -> dict[int, dict[str, Any]]:
    """The ScrumMaster's current triage of each of *item_ids*, by item id.

    A triage answers one block. It is stale, and left out, once the task was
    escalated again (a later ``escalation`` message) or sent back to work by a
    person after it (*sent_back_at*, from the task's comments): the next block
    may have another cause and gets its own answer, or the deterministic
    default when none comes.
    """
    ids = list(dict.fromkeys(i for i in item_ids if i is not None))
    if not ids:
        return {}
    sent_back = {k: _naive_utc(v) for k, v in (sent_back_at or {}).items()}
    rows = session.exec(
        select(
            AgentMessage.backlog_item_id,
            AgentMessage.id,
            AgentMessage.kind,
            AgentMessage.from_role,
            AgentMessage.body,
            AgentMessage.created_at,
        )
        .where(
            AgentMessage.backlog_item_id.in_(ids),
            AgentMessage.kind.in_(("decision", "escalation")),
        )
        .order_by(AgentMessage.id)
    ).all()
    decisions: dict[int, dict[str, Any]] = {}
    latest_escalation: dict[int, int] = {}
    escalated_at: dict[int, datetime | None] = {}  # by escalation message id
    for item_id, message_id, kind, from_role, body, created_at in rows:
        if kind == "escalation":
            decisions.pop(item_id, None)
            latest_escalation[item_id] = message_id
            escalated_at[message_id] = _naive_utc(created_at)
            continue
        if from_role != SCRUM_MASTER_ROLE:
            continue
        decision = parse_decision_body(body)
        if decision is None:
            continue
        # The escalation this decision answers: the one it names, or else the
        # latest before it. One that names an older escalation is about a
        # block a later escalation replaced, however late it was recorded.
        latest = latest_escalation.get(item_id)
        answers = answered_escalation(body)
        if answers is not None and answers != latest:
            continue
        cutoff = sent_back.get(item_id)
        if cutoff is not None:
            # Stale when the person sent the task back after that escalation,
            # even if the answer itself came later: the worker posts the
            # escalation, then waits up to TRIAGE_TIMEOUT_SECONDS for the
            # answer, and on the Verifier and QA paths the task is already
            # blocked, so a person can act in that window.
            answered_at = escalated_at.get(latest) if latest is not None else None
            if (_naive_utc(created_at) or cutoff) <= cutoff or (
                answered_at is not None and answered_at <= cutoff
            ):
                continue
        decisions[item_id] = decision
    return decisions


def triages_for(
    session: Session, items: list[BacklogItem]
) -> dict[int, dict[str, Any]]:
    """``decisions_for`` the given tasks, minding when a person last sent each back."""
    sent_back = {
        item.id: moment
        for item in items
        if (moment := last_send_back_at(item.comments)) is not None
    }
    return decisions_for(session, [item.id for item in items], sent_back)


def decision_for(session: Session, item_id: int) -> dict[str, Any] | None:
    """The ScrumMaster's current triage of *item_id*, or ``None``."""
    item = session.get(BacklogItem, item_id)
    if item is None:
        return decisions_for(session, [item_id]).get(item_id)
    return triages_for(session, [item]).get(item_id)
