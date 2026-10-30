"""
Reading a task's board: what its comments say about where it stands.

The task worker, the inbox and the carry-over all need the same answers
from a task's comment thread: which comment is the deliverable to review,
which rework requests are still pending, whether a blocked task is waiting
for a person or will move again on its own. They live here, with no engine
and no I/O, so every caller reads the board the same way.

Four kinds of comment are never a deliverable and never a verdict on the
task they sit on: the gates' texts (``Quality gate``, ``Verifier``), a
person's notes (author ``user``; the send-back one, ``SEND_BACK_MARKER``,
also restarts the rework budgets), the carry-over lineage notes
(``CARRIED_*_PREFIX``), which quote an earlier task's verdict and must not be
read as this task's, and the advice a task got: the worker's console-advice
note (``CONSOLE_ADVICE_PREFIX``), which quotes an assistant's words, and the
Architect's brief (``ARCHITECT_CONSULTED:``). Whether that advice helps is
counted from the boards (``count_console_advice``, ``count_architect_advice``).
Only the system, the gates and a person write the phrases that keep a task
blocked; the same words in a deliverable or a brief are not a verdict.
"""

import json
from collections.abc import Callable
from datetime import datetime
from typing import Any

from models import BacklogItem

from services.orchestration_metrics import is_architect_consult_comment

# Who signs the text checks a deliverable passes before anyone reviews it, and
# who signs the delivery evidence check; neither ever writes a deliverable.
QUALITY_GATE_AUTHOR = "Quality gate"
DELIVERY_GATE_AUTHOR = "Verifier"
GATE_AUTHORS_LOWER = {QUALITY_GATE_AUTHOR.lower(), DELIVERY_GATE_AUTHOR.lower()}
# Who writes the phrases that keep a task blocked ("manual triage", "agent
# error:"): the system, the gates and a person, never a deliverable's author.
BLOCK_VERDICT_AUTHORS = {"system", "user"} | GATE_AUTHORS_LOWER
SCRUM_MASTER_ROLE = "ScrumMaster"
# A person's note when they send a blocked task back to work (author "user",
# written as-is by the frontend, never translated). Rework budgets restart
# after it.
SEND_BACK_MARKER = "Sent back to work"
# The carry-over notes on the original task and on its new attempt.
CARRIED_TO_PREFIX = "Carried over to sprint"
CARRIED_FROM_PREFIX = "Carried over from"
# The line the ScrumMaster's brief travels on, in its decision and in the
# carry-over note of the next attempt.
BRIEF_PREFIX = "Brief for the next attempt: "
# The note the worker writes when console assistants (Copilot CLI, Claude CLI)
# advised on a task. Their advice is context, never evidence; whether it helps
# is counted from the boards.
CONSOLE_ADVICE_PREFIX = "External assistant context used for this task:"
# The worker's note when QA approved a delivery whose risk tier is high
# (services/risk.py): the task waits for a person to accept it, at every
# autonomy level. A person accepts it by marking it done, or sends it back.
RISK_HOLD_PREFIX = (
    "High-risk delivery approved by QA, waiting for a person to accept it"
)


def comment_list(comments: Any) -> list[dict[str, Any]]:
    """A backlog item's comments as a list, whatever the column holds."""
    if isinstance(comments, str):
        try:
            comments = json.loads(comments)
        except Exception:  # noqa: BLE001 - Malformed legacy comments fall back to an empty list.
            comments = []
    if not isinstance(comments, list):
        return []
    return [c for c in comments if isinstance(c, dict)]


def _text(comment: dict[str, Any]) -> str:
    return str(comment.get("text", "")).strip()


def _author(comment: dict[str, Any]) -> str:
    return str(comment.get("author", "")).strip().lower()


def is_lineage_comment(comment: dict[str, Any]) -> bool:
    """A carry-over note: it quotes another task's verdict, not this one's."""
    text = _text(comment)
    return text.startswith((CARRIED_TO_PREFIX, CARRIED_FROM_PREFIX))


def is_console_advice_note(comment: dict[str, Any]) -> bool:
    """The worker's note quoting console assistants' advice.

    It carries an excerpt of what an assistant wrote ("add retry logic", "needs
    manual triage"), so it is never read as a verdict; and only the worker's
    own note (author ``System``) counts, not a deliverable or a person's note
    that happens to start the same way.
    """
    return _author(comment) == "system" and _text(comment).startswith(
        CONSOLE_ADVICE_PREFIX
    )


def is_send_back(comment: dict[str, Any]) -> bool:
    """A person's note sending the task back to work."""
    return _author(comment) == "user" and _text(comment).startswith(SEND_BACK_MARKER)


def is_rework_request(comment: dict[str, Any]) -> bool:
    return _text(comment).upper().startswith("NEEDS WORK:")


def verdict_comments(comments: Any) -> list[dict[str, Any]]:
    """The comments that may say something about *this* task's state."""
    return [
        c
        for c in comment_list(comments)
        if not is_lineage_comment(c)
        and not is_console_advice_note(c)
        and not is_architect_consult_comment(c)
    ]


def since_send_back(comments: Any) -> list[dict[str, Any]]:
    """The comments after the last time a person sent the task back, or all of them."""
    comments = comment_list(comments)
    for index in range(len(comments) - 1, -1, -1):
        if is_send_back(comments[index]):
            return comments[index + 1 :]
    return comments


def last_send_back_at(comments: Any) -> datetime | None:
    """When a person last sent the task back to work, or ``None`` (or unknown)."""
    for comment in reversed(comment_list(comments)):
        if is_send_back(comment):
            try:
                return datetime.fromisoformat(str(comment.get("created_at") or ""))
            except ValueError:
                return None
    return None


def rework_request_count(comments: Any) -> int:
    """Every ``NEEDS WORK:`` request on the task, whoever made it.

    The number the sprint list shows and the procedures are judged by: a
    gate's, a reviewer's or the Verifier's request each count once.
    """
    return sum(1 for c in verdict_comments(comments) if is_rework_request(c))


def rework_requests_by(comments: Any, author: str) -> int:
    """How many ``NEEDS WORK:`` requests *author* made since the last send-back.

    A person sending a task back to work gives every gate and reviewer a fresh
    rework budget; otherwise the task would be blocked again on its first
    rejected attempt.
    """
    return sum(
        1
        for c in since_send_back(comments)
        if str(c.get("author", "")) == author and is_rework_request(c)
    )


def has_manual_freeze_marker(comments: Any) -> bool:
    """Detect operator comments that intentionally freeze a task out of automation."""
    return any(
        "sleep-induced churn" in _text(comment).lower()
        or _text(comment).lower().startswith("freeze after")
        for comment in verdict_comments(comments)
    )


def extract_latest_reviewable_comment(
    comments: Any, assignee_role: str | None = None
) -> str:
    """Return the latest non-system, non-QA deliverable comment for review."""
    assignee_normalized = (assignee_role or "").strip().lower()

    for comment in reversed(comment_list(comments)):
        author = _author(comment)
        text = _text(comment)
        if not text:
            continue
        if (
            text.lower().startswith("freeze after")
            or "sleep-induced churn" in text.lower()
        ):
            continue
        if author == "system":
            continue
        if is_rework_request(comment):
            # A rework request after the latest deliverable makes it stale:
            # the task must run again before anything is reviewed.
            return ""
        if author in GATE_AUTHORS_LOWER or author == "user":
            # The gates write verdicts and a person on the board writes notes
            # (``PATCH /v1/backlog`` records them as "user"); neither is a
            # deliverable, so neither goes to review.
            continue
        if author == "qa" and assignee_normalized != "qa":
            continue
        if text.upper().startswith("APPROVED:"):
            continue
        if is_architect_consult_comment(comment):
            continue
        return text

    return ""


def pending_rework_feedback(comments: Any) -> list[str]:
    """The ``NEEDS WORK:`` requests made since the task's latest deliverable."""
    feedback: list[str] = []
    for comment in reversed(comment_list(comments)):
        text = _text(comment)
        if is_rework_request(comment):
            feedback.append(f"{comment.get('author') or 'Reviewer'}: {text}")
            continue
        author = _author(comment)
        if (
            text
            and author != "system"
            and author not in GATE_AUTHORS_LOWER
            and author != "user"
            and not text.upper().startswith("APPROVED:")
            and not is_architect_consult_comment(comment)
        ):
            break  # reached the deliverable those requests were about
    return list(reversed(feedback))


def is_explicit_block_reason(text: str) -> bool:
    """Return True when a comment clearly indicates the task must remain blocked."""
    normalized = (text or "").strip().lower()
    return any(
        token in normalized
        for token in (
            "manual triage",
            "pre-review quality gate failed",
            "qa quality gate failed",
            "qa review failed",
            "agent error:",
            "missing deliverable",
            "freeze after",
            "sleep-induced churn",
            RISK_HOLD_PREFIX.lower(),
        )
    )


def can_resume_blocked_item_from_deliverable(
    comments: Any, assignee_role: str | None = None
) -> bool:
    """Detect blocked items that already have a deliverable and no explicit block reason."""
    comments = verdict_comments(comments)
    if not comments:
        return False
    if has_manual_freeze_marker(comments):
        return False
    if any(
        is_explicit_block_reason(_text(c))
        for c in comments
        if _author(c) in BLOCK_VERDICT_AUTHORS
    ):
        return False
    return bool(
        extract_latest_reviewable_comment(comments, assignee_role=assignee_role)
    )


def blocked_item_next_step(comments: Any, assignee_role: str | None) -> str | None:
    """What the worker still does on its own with a blocked item.

    ``"frozen"``: an operator froze it, so only a person moves it. ``"review"``:
    a deliverable exists and nothing says it must stay blocked, so it goes back
    to review. ``"retry"``: a transient failure not retried yet. ``None``: it
    stays blocked until a person acts, which is the only case a sprint may
    close around (see ``item_is_settled``).
    """
    comments = verdict_comments(comments)
    if has_manual_freeze_marker(comments):
        return "frozen"
    if can_resume_blocked_item_from_deliverable(comments, assignee_role=assignee_role):
        return "review"

    # A verdict that needs a person: a gate or the system said "manual triage",
    # or a reviewer asked for rework the task already spent. Never retried.
    needs_a_person = any(
        (
            _author(c) in ({"system"} | GATE_AUTHORS_LOWER)
            and "manual triage" in _text(c).lower()
        )
        or (_author(c) == "system" and "qa quality gate failed" in _text(c).lower())
        or is_risk_hold_note(c)
        or is_rework_request(c)
        for c in comments
    )
    if needs_a_person:
        return None

    # Only retry blocked items that failed for transient/system reasons.
    retryable_system_block = any(
        _author(c) == "system"
        and (
            "qa review failed" in _text(c).lower()
            or "agent error:" in _text(c).lower()
            or "no deliverable found" in _text(c).lower()
            or "unfinished in-progress task returned to todo for redispatch"
            in _text(c).lower()
        )
        for c in comments
    )
    if not retryable_system_block:
        return None

    # Only retry once — check if there's already a retry comment
    retry_count = sum(
        1 for c in comments if _author(c) == "system" and "retry" in _text(c).lower()
    )
    return None if retry_count >= 1 else "retry"


def is_risk_hold_note(comment: dict[str, Any]) -> bool:
    """The worker's note holding an approved high-risk delivery for a person."""
    return _author(comment) == "system" and _text(comment).startswith(RISK_HOLD_PREFIX)


def awaits_risk_acceptance(comments: Any) -> bool:
    """The task's latest verdict is a high-risk hold: approved, waiting for a person.

    Not a failure: the sprint's blocked share and the procedures' numbers
    leave it out, and it is never carried into another sprint on the
    company's own.
    """
    for comment in reversed(verdict_comments(comments)):
        text = _text(comment)
        author = _author(comment)
        if text and (
            author == "system"
            or author in GATE_AUTHORS_LOWER
            or is_rework_request(comment)
            or is_send_back(comment)
        ):
            return is_risk_hold_note(comment)
    return False


def block_reason(comments: Any) -> str:
    """The latest verdict on a blocked item: what a gate, the system or a reviewer said."""
    for comment in reversed(verdict_comments(comments)):
        text = _text(comment)
        author = _author(comment)
        if text and (
            author == "system"
            or author in GATE_AUTHORS_LOWER
            or is_rework_request(comment)
        ):
            return text
    return ""


def item_is_settled(item: BacklogItem) -> bool:
    """Done, or blocked until a person acts: nothing the worker does moves it."""
    if item.status == "done":
        return True
    if item.status != "blocked":
        return False
    return blocked_item_next_step(item.comments, item.assignee) is None


def second_attempt_briefed(comments: Any) -> bool | None:
    """None for a first attempt; for a second, whether the ScrumMaster briefed it."""
    for comment in comment_list(comments):
        text = _text(comment)
        if text.startswith(CARRIED_FROM_PREFIX):
            return f"\n{BRIEF_PREFIX}" in text
    return None


def no_second_attempts() -> dict[str, int]:
    """An empty tally of second attempts: how many, how many done, and briefed."""
    return {"total": 0, "done": 0, "briefed": 0, "briefed_done": 0}


def count_second_attempt(tally: dict[str, int], status: str, comments: Any) -> None:
    """Add one task to *tally* when it is a second attempt."""
    briefed = second_attempt_briefed(comments)
    if briefed is None:
        return
    done = int(status == "done")
    tally["total"] += 1
    tally["done"] += done
    if briefed:
        tally["briefed"] += 1
        tally["briefed_done"] += done


def has_console_advice(comments: Any) -> bool:
    """Whether the worker wrote a console assistant's advice onto the task."""
    return any(is_console_advice_note(comment) for comment in comment_list(comments))


def no_console_advice() -> dict[str, dict[str, int]]:
    """An empty tally: tasks that got advice and tasks that did not."""
    return {
        "advised": {"total": 0, "done": 0, "rework": 0},
        "unadvised": {"total": 0, "done": 0, "rework": 0},
    }


# The Architect's briefs are tallied the same way.
no_architect_advice = no_console_advice


def _count_advice(
    tally: dict[str, dict[str, int]],
    status: str,
    comments: Any,
    is_advice: Callable[[dict[str, Any]], bool],
) -> None:
    """Add one task to *tally*, under the group its board puts it in.

    An advised task's rework counts from its first advice on: requests an
    earlier, unadvised attempt drew are not the advice's doing.
    """
    comments = comment_list(comments)
    first_advice = next(
        (i for i, comment in enumerate(comments) if is_advice(comment)), None
    )
    group = tally["unadvised" if first_advice is None else "advised"]
    group["total"] += 1
    group["done"] += int(status == "done")
    group["rework"] += rework_request_count(comments[first_advice or 0 :])


def count_console_advice(
    tally: dict[str, dict[str, int]], status: str, comments: Any
) -> None:
    """Tally a task by whether a console assistant advised on it.

    An assistant may have been cooling down, or silent, on the first attempt;
    the rework that attempt drew is not the advice's doing.
    """
    _count_advice(tally, status, comments, is_console_advice_note)


def count_architect_advice(
    tally: dict[str, dict[str, int]], status: str, comments: Any
) -> None:
    """Tally a task by whether the Architect briefed it.

    The Architect is often consulted only after a review sent the task back;
    the rework before the brief is not the brief's doing.
    """
    _count_advice(tally, status, comments, is_architect_consult_comment)
