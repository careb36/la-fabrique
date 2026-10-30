"""
The conversation between the company's agents.

Each row is one message from a role to another (or to the whole team):
asking, answering, handing work over, requesting rework, deciding,
escalating, or reporting a retrospective. It is the company's record of who
said what to whom.

A message is a claim. What actually happened to a task is in the board, the
AgentRun evidence and its verifications; a message never stands in for them.
"""

from datetime import UTC, datetime

from sqlmodel import Field, SQLModel

# What a message does in the conversation.
MESSAGE_KINDS = (
    "question",  # asks another role for input before acting
    "answer",  # replies to a question
    "handoff",  # hands work to the next role
    "request",  # asks for rework
    "decision",  # accepts the work
    "escalation",  # raises a blocked task to the ScrumMaster
    "retrospective",  # what a finished sprint showed
    "proposal",  # proposes, adopts or reverts a procedure
)


class AgentMessage(SQLModel, table=True):
    __tablename__ = "agent_messages"

    id: int | None = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    sprint_id: int | None = Field(default=None, foreign_key="sprints.id", index=True)
    backlog_item_id: int | None = Field(
        default=None, foreign_key="backlog_items.id", index=True
    )
    from_name: str
    from_role: str
    to_role: str | None = None  # None: the whole team
    kind: str
    body: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
