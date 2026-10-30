"""
The Architect's record: how tasks went after its briefs.

The Developer asks the Architect before implementing a design-sensitive or
reworked task, and the brief travels into the Developer's prompt. The brief
is a claim; whether it helps is counted from the boards of the company's
completed sprints, briefed tasks against the rest, and the Architect is told
those numbers when it is asked again, the way the ScrumMaster is told how
second attempts went.
"""

from models import BacklogItem, Sprint
from sqlmodel import Session, select

from services.board import count_architect_advice, no_architect_advice


def track_record(session: Session, company_id: int) -> dict[str, dict[str, int]]:
    """Briefed tasks against the rest, over the company's completed sprints.

    The same tally the sprint list shows per sprint (``architect_advice``):
    how many tasks, how many got done and how many rework requests they drew,
    a briefed task's counted from its first brief on. Only closed sprints
    count, so every task has its outcome.
    """
    tally = no_architect_advice()
    for status, comments in session.exec(
        select(BacklogItem.status, BacklogItem.comments)
        .join(Sprint, Sprint.id == BacklogItem.sprint_id)
        .where(Sprint.company_id == company_id, Sprint.status == "completed")
    ).all():
        count_architect_advice(tally, status, comments)
    return tally


def _group(group: dict[str, int]) -> str:
    per_task = group["rework"] / group["total"] if group["total"] else 0.0
    return (
        f"{group['done']} of {group['total']} got done, "
        f"{per_task:.2f} rework requests per task"
    )


def track_record_context(tally: dict[str, dict[str, int]]) -> str:
    """The prompt section with how earlier briefs went, or '' before any."""
    if not tally["advised"]["total"]:
        return ""
    return (
        "\n\n## How tasks went after your earlier briefs\n"
        f"Tasks you briefed: {_group(tally['advised'])} (counted from your brief on). "
        f"Tasks without a brief: {_group(tally['unadvised'])}. "
        "You are asked about design-sensitive and reworked tasks, so the groups "
        "are not alike; these are counted from the boards, not reported by anyone."
    )
