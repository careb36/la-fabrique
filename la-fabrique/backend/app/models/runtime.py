"""Runtime persistence models for lightweight assistant state."""

from datetime import datetime

from sqlmodel import Field, SQLModel


class AssistantRuntimeState(SQLModel, table=True):
    """Persistent per-company runtime state for external console assistants."""

    __tablename__ = "assistant_runtime_state"

    id: int | None = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    assistant_key: str = Field(index=True)
    cooldown_until: datetime | None = None
    last_error: str | None = None
    updated_at: datetime | None = Field(default_factory=datetime.utcnow)
