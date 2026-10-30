from datetime import datetime
from typing import Any

from sqlalchemy import JSON, UniqueConstraint
from sqlmodel import Column, Field, SQLModel

# Runs the company produces itself. The review loop already decides them: the
# Verifier and QA judge a task worker delivery (a blocked one reaches a person
# as a blocked task), and a kickoff transcript is context, not a deliverable.
# Only runs ingested from other producers wait for a person's approval.
TASK_WORKER_PRODUCER = "le-fabrique-task-worker"
GRAPH_PRODUCER = "le-fabrique-graph"
IN_HOUSE_PRODUCERS = (TASK_WORKER_PRODUCER, GRAPH_PRODUCER)


class AgentRun(SQLModel, table=True):
    __tablename__ = "agent_runs"
    __table_args__ = (UniqueConstraint("company_id", "external_ref", "version"),)

    id: int | None = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id")
    external_ref: str
    version: int = 1
    producer: str
    model: str | None = None
    agent_role: str | None = None
    subject: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    claims: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    artifact_text: str | None = None
    artifact_digest: str
    artifact_size: int
    status: str = "ingested"
    started_at: datetime | None = None
    finished_at: datetime | None = None
    ingested_at: datetime = Field(default_factory=datetime.utcnow)
    audit_log_id: int | None = Field(default=None, foreign_key="audit_log.id")
    # The Reviewer agent's suggestion: a claim kept apart from the approval a
    # person records (``AgentRunApproval``). ``reviewed_at`` with no decision
    # means its answer was unusable and the run is left to people.
    suggested_decision: str | None = None
    suggested_category: str | None = None
    suggested_reason: str | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None


class Verification(SQLModel, table=True):
    __tablename__ = "verifications"

    id: int | None = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id")
    agent_run_id: int = Field(foreign_key="agent_runs.id")
    verdict: str
    checks: list | None = Field(default=None, sa_column=Column(JSON))
    evidence: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    observed_at: datetime = Field(default_factory=datetime.utcnow)
    audit_log_id: int | None = Field(default=None, foreign_key="audit_log.id")


class AgentRunApproval(SQLModel, table=True):
    __tablename__ = "agent_run_approvals"

    id: int | None = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id")
    agent_run_id: int = Field(foreign_key="agent_runs.id")
    approver_name: str
    decision: str
    feedback: str | None = None
    rejection_category: str | None = None
    decided_at: datetime = Field(default_factory=datetime.utcnow)
    audit_log_id: int | None = Field(default=None, foreign_key="audit_log.id")
