"""
SQLModel ORM models for sprint management and the transactional outbox.

Tables:
- ``Sprint``       — a time-boxed iteration for a company.
- ``BacklogItem``  — a single task on the sprint board (Kanban card).
- ``OutboxEvent``  — transactional outbox rows published to NATS by the background worker.
"""

import json
from datetime import datetime
from typing import Any

from sqlalchemy import JSON
from sqlalchemy.ext.mutable import MutableList
from sqlmodel import Column, Field, SQLModel


class CommentList(MutableList):
    """
    A JSON list whose in-place changes are persisted.

    Workers append to ``item.comments`` and assign the same list back; a plain
    ``JSON`` column does not see that change, so every comment after the first
    was silently dropped.  Legacy rows that stored the list as a JSON string
    are read as a list.
    """

    @classmethod
    def coerce(cls, key: str, value: Any) -> Any:
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                value = []
            if not isinstance(value, list):
                value = []
        return super().coerce(key, value)


class Sprint(SQLModel, table=True):
    """A scope-bounded work iteration owned by a company."""

    __tablename__ = "sprints"

    id: int | None = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id")
    business_unit_id: int | None = Field(default=None, foreign_key="business_units.id")
    sprint_name: str
    start_date: str | None = None  # ISO-8601 date string
    scope_size: str = "M"  # "S" (≤4 items) | "M" (≤8) | "L" (≤12)
    duration_days: int | None = None  # deprecated — kept for backwards compat
    status: str = "active"  # "active" | "completed" | "cancelled" | "needs_split"
    goal: str | None = None  # Sprint goal statement for the team


class BacklogItem(SQLModel, table=True):
    """
    A single task / user story on the sprint board.

    ``status`` drives the Kanban column placement.
    ``comments`` stores a JSON list of ``{author, text, created_at}`` objects
    appended by agents and human reviewers over the item's lifecycle.
    """

    __tablename__ = "backlog_items"

    id: int | None = Field(default=None, primary_key=True)
    sprint_id: int = Field(foreign_key="sprints.id")
    title: str
    description: str = ""
    status: str = "todo"  # "todo" | "in_progress" | "in_review" | "done" | "blocked"
    priority: str = "medium"  # "low" | "medium" | "high" | "critical"
    assignee: str | None = None  # Agent role or human name
    comments: Any | None = Field(
        default=None, sa_column=Column(CommentList.as_mutable(JSON))
    )
    created_at: datetime | None = Field(default_factory=datetime.utcnow)
    updated_at: datetime | None = Field(default_factory=datetime.utcnow)


class OutboxEvent(SQLModel, table=True):
    """
    Transactional outbox entry for reliable NATS message delivery.

    The ``process_outbox`` background worker polls this table for pending
    rows, publishes them to NATS, and marks them completed.  Rows that
    exceed 5 retries are marked ``"failed"`` and require manual inspection.

    Using ``FOR UPDATE SKIP LOCKED`` in the worker query prevents duplicate
    processing when multiple worker replicas run concurrently (e.g. in K8s).
    """

    __tablename__ = "outbox_events"

    id: int | None = Field(default=None, primary_key=True)
    aggregate_type: str  # Domain entity type (e.g. "backlog_item", "sprint")
    aggregate_id: str  # PK of the domain entity that triggered this event
    event_type: str  # Action that produced the event (e.g. "nats_publish")
    payload: Any | None = Field(
        default=None, sa_column=Column(JSON)
    )  # {"subject": "...", "message": {...}}
    status: str = "pending"  # "pending" | "completed" | "failed"
    retry_count: int = 0  # Incremented on each failed delivery attempt
    created_at: datetime | None = Field(default_factory=datetime.utcnow)
    processed_at: datetime | None = (
        None  # Set when status transitions to completed/failed
    )
