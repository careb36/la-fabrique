from datetime import datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


class GitHubRepoBinding(SQLModel, table=True):
    __tablename__ = "github_repo_bindings"
    __table_args__ = (UniqueConstraint("owner", "repo"),)

    id: int | None = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id")
    owner: str
    repo: str
    webhook_secret_encrypted: str
    inclusion_rule: str = "all"
    created_at: datetime = Field(default_factory=datetime.utcnow)
