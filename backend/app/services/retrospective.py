"""A closed sprint's health, for its retrospective and the next sprint's plan.

``build`` counts a sprint's tasks (done, blocked, waiting for a person) and the
rework and QA failures on their boards; ``summary`` writes those numbers as the
text the ScrumMaster's retrospective message, the memory engram and the
procedure proposals carry. Best-effort: a failure returns no metrics.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from models import BacklogItem, Sprint
from sqlmodel import Session, select

from services.board import (
    awaits_risk_acceptance,
    block_reason,
    extract_latest_reviewable_comment,
)

logger = logging.getLogger("fabrique-task-worker")


def build(engine: Any, sprint_id: int) -> dict[str, Any]:
    """Compute sprint health metrics for retrospective engram and next-sprint planning."""
    try:
        with Session(engine) as session:
            items = session.exec(
                select(BacklogItem).where(BacklogItem.sprint_id == sprint_id)
            ).all()
            if not items:
                return {}

            sprint = session.get(Sprint, sprint_id)
            total = len(items)
            done = sum(1 for i in items if i.status == "done")
            # An approved high-risk delivery waiting for a person is not a
            # failure: counted apart from the blocked tasks.
            awaiting_person = sum(
                1
                for i in items
                if i.status == "blocked" and awaits_risk_acceptance(i.comments)
            )
            blocked = sum(1 for i in items if i.status == "blocked") - awaiting_person
            rework_count = 0
            qa_fail_count = 0
            blocked_reasons: list[str] = []

            for item in items:
                comments = item.comments or []
                if isinstance(comments, str):
                    try:
                        comments = json.loads(comments)
                    except Exception:  # noqa: BLE001 - Malformed legacy comments fall back to an empty list.
                        comments = []
                for comment in comments:
                    text = str(comment.get("text", ""))
                    if "NEEDS WORK:" in text.upper():
                        rework_count += 1
                    if (
                        "qa quality gate failed" in text.lower()
                        or "qa review failed" in text.lower()
                    ):
                        qa_fail_count += 1
                if item.status == "blocked" and not awaits_risk_acceptance(comments):
                    reason = block_reason(comments) or (
                        extract_latest_reviewable_comment(
                            comments, assignee_role=item.assignee
                        )
                    )
                    if reason:
                        blocked_reasons.append(f"{item.title[:60]}: {reason[:120]}")

            return {
                "company_id": sprint.company_id if sprint else None,
                "sprint_id": sprint_id,
                "total_tasks": total,
                "done_tasks": done,
                "blocked_tasks": blocked,
                "awaiting_person_tasks": awaiting_person,
                "completion_rate": round(done / total * 100) if total else 0,
                "rework_cycles": rework_count,
                "qa_failures": qa_fail_count,
                "blocked_reasons": blocked_reasons[:5],
            }
    except Exception as exc:  # noqa: BLE001 - Retrospective context is best-effort.
        logger.warning(
            "Sprint retrospective build failed for sprint=%s: %s", sprint_id, exc
        )
        return {}


def summary(metrics: dict[str, Any]) -> str:
    lines = [
        f"Sprint {metrics.get('sprint_id')} retrospective:",
        f"- Completed {metrics.get('done_tasks', 0)}/{metrics.get('total_tasks', 0)} tasks ({metrics.get('completion_rate', 0)}%)",
        f"- Blocked: {metrics.get('blocked_tasks', 0)} tasks",
        f"- QA rework cycles: {metrics.get('rework_cycles', 0)}",
        f"- QA failures: {metrics.get('qa_failures', 0)}",
    ]
    for reason in metrics.get("blocked_reasons") or []:
        lines.append(f"  • {reason}")
    return "\n".join(lines)
