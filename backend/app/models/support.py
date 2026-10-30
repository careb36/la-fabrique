"""
SQLModel ORM model for the ``bug_reports`` table.

Stores structured support tickets submitted by users via the Bug Reporter
tab or the ``POST /v1/support/report_bug`` API endpoint.  Ticket numbers
follow the ``FAB-XXXXX`` format (zero-padded 5-digit integer).
"""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON
from sqlmodel import Column, Field, SQLModel


class BugReport(SQLModel, table=True):
    """
    A single support ticket capturing a defect, feature request, or incident.

    Lifecycle (``status`` transitions):
        open → in_progress → waiting → resolved → closed
    """

    __tablename__ = "bug_reports"

    id: int | None = Field(default=None, primary_key=True)
    ticket_num: str = Field(unique=True)  # Human-readable ID, e.g. "FAB-00042"
    title: str
    description: str
    steps: str | None = None  # Step-by-step reproduction instructions
    expected: str | None = None  # What the user expected to happen
    actual: str | None = None  # What actually happened (the bug)
    # "low" | "medium" | "high" | "critical"; None when the reporter chose none.
    severity: str | None = None
    # "bug" | "feature" | "question" | "incident"; None when the reporter chose none.
    category: str | None = None
    status: str = "open"  # "open" | "in_progress" | "waiting" | "resolved" | "closed"
    reporter_email: str | None = None
    assigned_to: str | None = None
    resolution: str | None = None  # Free-text explanation of how the issue was resolved
    # The Support agent's triage. Its suggestions sit beside what the reporter
    # chose and never overwrite it; a support admin decides.
    agent_reply: str | None = None  # first reply to the reporter
    suggested_severity: str | None = None
    suggested_category: str | None = None
    triaged_by: str | None = None
    triaged_at: datetime | None = None
    # A support admin's decision, beside the reporter's choice and the agent's
    # suggestion; none of the three overwrites another. Comparing the
    # suggestion with the decision is how the agent's triage is measured.
    decided_severity: str | None = None
    decided_category: str | None = None
    decided_by: str | None = None
    decided_at: datetime | None = None
    browser_info: Any | None = Field(
        default=None, sa_column=Column(JSON)
    )  # User-agent, viewport, etc.
    created_at: datetime | None = Field(default_factory=datetime.utcnow)
    updated_at: datetime | None = Field(default_factory=datetime.utcnow)
    resolved_at: datetime | None = (
        None  # Set when status transitions to "resolved" or "closed"
    )
