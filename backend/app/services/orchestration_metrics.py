"""
Orchestration metrics — emitters for the KPIs read by
``GET /v1/analytics/orchestration_health``.

The analytics endpoint (``routers/enterprise.py``) derives three weekly KPIs
from data that the task pipeline must write in a specific shape:

1. **QA NEEDS WORK rate** — ``audit_log`` rows where
   ``details->>'role' = 'QA'`` and ``details->>'result_type' = 'NEEDS_WORK'``.
2. **Avg Developer tokens** — ``audit_log.cost_tokens`` for rows where
   ``details->>'role' = 'Developer'`` and the proxy reported the usage
   (``details->>'tokens' = 'reported'``; older rows without the key count
   when their total is above zero). Turns without a reported count are
   counted apart, never averaged in as zero.
3. **Architect consult frequency** — ``backlog_items.comments`` entries authored
   by ``Architect`` whose text starts with ``ARCHITECT_CONSULTED:``.

Every query is additionally scoped by ``details->>'company_id'``.

Historically nothing in the worker wrote any of that, so KPIs 2 and 3 were
structurally always zero and KPI 1 only worked through its comment-scan
fallback.  This module centralises the *emitting* side so the query side and
the write side share one contract (role names, marker prefix, detail keys).

All helpers here are side-effect free except :func:`record_agent_turn`, which
is deliberately fail-soft: an audit write must never break task execution.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable
from typing import Any

logger = logging.getLogger("fabrique-task-worker")

# ---------------------------------------------------------------------------
# Shared contract with routers/enterprise.py
# ---------------------------------------------------------------------------

KPI_ROLE_DEVELOPER = "Developer"
KPI_ROLE_QA = "QA"
KPI_ROLE_ARCHITECT = "Architect"

ARCHITECT_CONSULT_MARKER = "ARCHITECT_CONSULTED:"
ARCHITECT_COMMENT_AUTHOR = KPI_ROLE_ARCHITECT

RESULT_APPROVED = "APPROVED"
RESULT_NEEDS_WORK = "NEEDS_WORK"

ACTION_EXECUTE_TASK = "execute_task"
ACTION_QA_REVIEW = "qa_review"
ACTION_ARCHITECT_CONSULT = "architect_consult"
ACTION_AGENT_RUN_VERIFIED = "agent_run_verified"

VERDICT_VERIFIED = "verified"
VERDICT_REFUTED = "refuted"
VERDICT_UNVERIFIABLE = "unverifiable"

# Agent roles are free text in the ``agents`` table ("Dev", "Developer",
# "QA", "Tester", ...).  The KPI queries filter on canonical names, so every
# emitter normalises through this table before writing.
_ROLE_ALIASES: dict[str, str] = {
    "dev": KPI_ROLE_DEVELOPER,
    "developer": KPI_ROLE_DEVELOPER,
    "engineer": KPI_ROLE_DEVELOPER,
    "software engineer": KPI_ROLE_DEVELOPER,
    "qa": KPI_ROLE_QA,
    "tester": KPI_ROLE_QA,
    "quality": KPI_ROLE_QA,
    "quality assurance": KPI_ROLE_QA,
    "architect": KPI_ROLE_ARCHITECT,
    "po": "PO",
    "product owner": "PO",
    "sm": "ScrumMaster",
    "scrummaster": "ScrumMaster",
    "scrum master": "ScrumMaster",
}

# Keywords that mark a Developer task as design-sensitive enough to warrant a
# short Architect consultation before implementation starts.
ARCHITECT_CONSULT_KEYWORDS = (
    "architecture",
    "architectural",
    "design",
    "schema",
    "migration",
    "refactor",
    "integration",
    "api contract",
    "scalab",
    "security",
    "performance",
    "infrastructure",
)

ARCHITECT_CONSULT_PRIORITIES = {"high", "critical"}


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def canonical_kpi_role(role: str | None) -> str:
    """Map a free-text agent role onto the canonical name the KPI queries use.

    Unknown roles are returned stripped but otherwise untouched so they still
    land in the audit trail; only known aliases are rewritten.
    """
    raw = (role or "").strip()
    if not raw:
        return KPI_ROLE_DEVELOPER
    return _ROLE_ALIASES.get(raw.lower(), raw)


def extract_usage_tokens(llm_result: dict[str, Any] | None) -> int:
    """Return the total token count reported by the LLM proxy for one call.

    The proxy returns an OpenAI-style ``usage`` block only when the provider
    reported the count; when only the prompt/completion split is present the
    two are summed.  A missing or malformed block yields ``0`` rather than
    raising; ``usage_status`` says whether that 0 is known.
    """
    if not isinstance(llm_result, dict):
        return 0
    usage = llm_result.get("usage")
    if not isinstance(usage, dict):
        return 0

    def _as_int(value: Any) -> int:
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return 0

    total = _as_int(usage.get("total_tokens"))
    if total:
        return total
    return _as_int(usage.get("prompt_tokens")) + _as_int(usage.get("completion_tokens"))


TOKENS_REPORTED = "reported"
TOKENS_UNAVAILABLE = "unavailable"
TOKENS_ESTIMATED = "estimated"


def usage_status(llm_result: dict[str, Any] | None) -> str:
    """How the call's token usage is known: ``reported``, ``estimated`` or ``unavailable``.

    The proxy marks a count it only estimated (``usage_status: estimated``,
    the estimate apart in ``usage_estimate``): that is not the provider's
    figure, so it is never taken for one.

    ``extract_usage_tokens`` returns 0 for a call whose usage is missing or
    malformed; this tells that 0 apart from a call that really used none, so
    the KPIs leave unknown counts out of an average instead of counting them
    as zero.
    """
    if isinstance(llm_result, dict) and llm_result.get("usage_status") == (
        TOKENS_ESTIMATED
    ):
        return TOKENS_ESTIMATED
    if not isinstance(llm_result, dict) or not isinstance(
        llm_result.get("usage"), dict
    ):
        return TOKENS_UNAVAILABLE
    usage = llm_result["usage"]
    for key in ("total_tokens", "prompt_tokens", "completion_tokens"):
        try:
            int(usage.get(key))
        except (TypeError, ValueError):
            continue
        return TOKENS_REPORTED
    return TOKENS_UNAVAILABLE


def classify_review_result(review_text: str | None) -> str | None:
    """Classify a QA review by its leading verdict prefix.

    Returns ``"APPROVED"``, ``"NEEDS_WORK"`` or ``None`` when the reviewer did
    not follow the expected ``APPROVED:`` / ``NEEDS WORK:`` convention.
    """
    normalized = (review_text or "").strip().upper()
    if normalized.startswith(("NEEDS WORK:", "NEEDS_WORK:")):
        return RESULT_NEEDS_WORK
    if normalized.startswith("APPROVED:"):
        return RESULT_APPROVED
    return None


def build_agent_turn_details(
    *,
    role: str | None,
    company_id: int | None,
    sprint_id: int | None = None,
    backlog_item_id: int | None = None,
    model: str | None = None,
    agent_name: str | None = None,
    result_type: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the ``audit_log.details`` payload in the shape the KPI queries read.

    ``role`` and ``company_id`` are the two keys every analytics query filters
    on; ``result_type`` feeds the QA rate.  The remaining keys are lineage
    context for dashboards and debugging.
    """
    details: dict[str, Any] = {
        "role": canonical_kpi_role(role),
        "agent_role": (role or "").strip() or None,
        # Stored as text on purpose: the SQL side casts ``details->>'company_id'``.
        "company_id": str(company_id) if company_id is not None else "",
        "sprint_id": sprint_id,
        "backlog_item_id": backlog_item_id,
        "model": model or None,
        "agent_name": agent_name or None,
    }
    if result_type:
        details["result_type"] = result_type
    if extra:
        for key, value in extra.items():
            details.setdefault(key, value)
    return details


def format_architect_consult_comment(advice: str, max_chars: int = 3500) -> str:
    """Render Architect advice as the marker-prefixed comment the KPI counts."""
    body = re.sub(r"\s+\Z", "", (advice or "").strip())
    if len(body) > max_chars:
        body = body[: max_chars - 1].rstrip() + "…"
    return f"{ARCHITECT_CONSULT_MARKER} {body}".rstrip()


def is_architect_consult_comment(comment: Any) -> bool:
    """True when *comment* is an ``ARCHITECT_CONSULTED:`` note written by the Architect."""
    if not isinstance(comment, dict):
        return False
    author = str(comment.get("author", "")).strip().lower()
    text = str(comment.get("text", "")).strip().upper()
    return author == ARCHITECT_COMMENT_AUTHOR.lower() and text.startswith(
        ARCHITECT_CONSULT_MARKER
    )


def _coerce_comments(comments: Any) -> list:
    if isinstance(comments, str):
        try:
            comments = json.loads(comments)
        except (json.JSONDecodeError, TypeError):
            return []
    return comments if isinstance(comments, list) else []


def count_architect_consults(comments: Any) -> int:
    return sum(1 for c in _coerce_comments(comments) if is_architect_consult_comment(c))


def count_qa_rework_requests(comments: Any) -> int:
    """Number of ``NEEDS WORK:`` verdicts already recorded on the item."""
    return sum(
        1
        for c in _coerce_comments(comments)
        if isinstance(c, dict)
        and str(c.get("author", "")).strip().lower() != "system"
        and classify_review_result(str(c.get("text", ""))) == RESULT_NEEDS_WORK
    )


def should_consult_architect(
    item: dict[str, Any],
    agent: dict[str, Any],
    comments: Any = None,
    *,
    enabled: bool = True,
) -> bool:
    """Decide whether a Developer task deserves an Architect consultation.

    The Architect is consulted at most once per implementation attempt, and
    only for Developer-owned work that is either high priority, touches a
    design-sensitive topic, or is being reworked after QA pushed it back.
    """
    if not enabled:
        return False
    if canonical_kpi_role(agent.get("role")) != KPI_ROLE_DEVELOPER:
        return False

    comments = _coerce_comments(
        comments if comments is not None else item.get("comments")
    )
    consults = count_architect_consults(comments)
    reworks = count_qa_rework_requests(comments)
    # One consult per attempt: the first attempt plus one per rework cycle.
    if consults > reworks:
        return False

    if reworks > 0:
        return True

    priority = str(item.get("priority") or "").strip().lower()
    if priority in ARCHITECT_CONSULT_PRIORITIES:
        return True

    task_text = f"{item.get('title', '')}\n{item.get('description', '')}".lower()
    return any(keyword in task_text for keyword in ARCHITECT_CONSULT_KEYWORDS)


def build_architect_consult_prompt(
    item: dict[str, Any],
    developer: dict[str, Any],
    sprint_name: str,
    prior_feedback: Iterable[str] = (),
    record: str = "",
) -> str:
    """Prompt asking the Architect for a compact technical brief on a task.

    *record* is how tasks went after its earlier briefs
    (``services.architect.track_record_context``), or ''.
    """
    feedback_lines = [
        f"- {line.strip()[:600]}" for line in prior_feedback if line and line.strip()
    ]
    prompt = (
        f"## Consultation request from {developer.get('name') or developer.get('role') or 'Developer'}\n\n"
        f"Sprint: {sprint_name}\n"
        f"Task: {item.get('title', '')}\n"
        f"Priority: {item.get('priority', 'medium')}\n\n"
        f"{item.get('description', '') or ''}\n\n"
        "Provide a concise technical brief (max ~12 lines) covering: the recommended approach, "
        "key constraints or existing components to reuse, risks to avoid, and what 'done' must "
        "include. Do not write the implementation yourself."
    )
    if feedback_lines:
        prompt += "\n\n## QA feedback from the previous attempt\n" + "\n".join(
            feedback_lines
        )
    return prompt + record


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def record_agent_turn(
    *,
    company_id: int | None,
    sprint_id: int | None,
    backlog_item_id: int | None,
    agent: dict[str, Any],
    action: str,
    llm_result: dict[str, Any] | None,
    result_type: str | None = None,
    result_preview: str | None = None,
    session=None,
):
    """Persist one LLM turn to ``audit_log`` in the shape the KPI queries read.

    ``llm_result`` is the raw proxy response; only its ``usage`` block is
    consumed.  Pass ``session`` to reuse an open SQLModel session (tests,
    batch writers); otherwise a short-lived session is opened on the shared
    engine.  Failures are logged and swallowed so metrics never block work.
    Returns the persisted ``AuditLog`` row, or ``None`` when nothing was written.
    """
    try:
        from models import (
            AuditLog,  # local import: keeps this module importable without DB config
        )
    except Exception as exc:  # noqa: BLE001 - Optional KPI recording must tolerate unavailable models.  # pragma: no cover - defensive
        logger.warning("Audit model unavailable, skipping KPI audit write: %s", exc)
        return None

    role = agent.get("role")
    details = build_agent_turn_details(
        role=role,
        company_id=company_id,
        sprint_id=sprint_id,
        backlog_item_id=backlog_item_id,
        model=agent.get("model"),
        agent_name=agent.get("name"),
        result_type=result_type,
    )
    # Unknown is not zero: the KPI average reads this to leave such turns out.
    details["tokens"] = usage_status(llm_result)
    result_payload: dict[str, Any] = {"result_type": result_type} if result_type else {}
    if result_preview:
        result_payload["preview"] = result_preview[:500]

    row = AuditLog(
        company_id=company_id,
        interaction_id=f"task-{backlog_item_id}"
        if backlog_item_id is not None
        else None,
        agent_id=(agent.get("name") or canonical_kpi_role(role) or None),
        action=action,
        details=details,
        result=result_payload or None,
        cost_tokens=extract_usage_tokens(llm_result),
    )

    try:
        # Signed and chained like every other audit row (audit_chain.py);
        # these rows used to be stored with no signature at all.
        from audit_chain import seal_audit_row

        if session is not None:
            seal_audit_row(session, row)
            session.commit()
            session.refresh(row)
            return row

        from database import engine
        from sqlmodel import Session

        with Session(engine) as own_session:
            seal_audit_row(own_session, row)
            own_session.commit()
            own_session.refresh(row)
            return row
    except Exception as exc:  # noqa: BLE001 - KPI recording must not abort the primary operation.
        if session is not None:
            # A failed write must not leave the caller's session unusable.
            try:
                session.rollback()
            except Exception as rollback_exc:  # noqa: BLE001
                logger.debug("KPI audit rollback failed: %s", rollback_exc)
        logger.warning(
            "KPI audit write failed (action=%s item=%s company=%s): %s",
            action,
            backlog_item_id,
            company_id,
            exc,
        )
        return None
