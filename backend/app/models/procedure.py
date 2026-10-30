"""
The company's procedures: the rules each role follows, as versioned data.

A procedure is proposed (by the ScrumMaster at a retrospective, or written
by a person), then adopted or rejected. While active, it is part of every
prompt of its role. Whether an adopted procedure helped is decided by the
board's numbers in the sprints after its adoption, never by a model: it is
kept, or reverted when rework or blocking got worse.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON
from sqlmodel import Column, Field, SQLModel

PROCEDURE_STATUSES = ("proposed", "active", "rejected", "retired")
# The role name of procedures every role follows.
ALL_ROLES = "All"


class Procedure(SQLModel, table=True):
    __tablename__ = "procedures"

    id: int | None = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    role: str  # a role name, or ALL_ROLES
    title: str
    body: str
    status: str = "proposed"
    version: int = 1
    supersedes_id: int | None = Field(default=None, foreign_key="procedures.id")
    proposed_by: str  # a role ("ScrumMaster") or a person's email
    rationale: str | None = None
    source_sprint_id: int | None = Field(default=None, foreign_key="sprints.id")
    # Metrics of the completed sprints before adoption, and of those after.
    # none_as_null: "not measured yet" must be SQL NULL so queries can find it.
    baseline: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSON(none_as_null=True))
    )
    outcome: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSON(none_as_null=True))
    )
    # The latest completed sprint when adopted; later sprints measure it.
    adopted_after_sprint_id: int | None = None
    decided_by: str | None = None  # "autonomy" or a person's email
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    decided_at: datetime | None = None
    retired_at: datetime | None = None
