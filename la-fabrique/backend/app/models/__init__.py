"""
Public re-export surface for all SQLModel ORM models.

Importing from this package gives access to every table model without
needing to know which sub-module it lives in.  SQLModel registers each
model with the shared ``MetaData`` object automatically when the module is
imported, so this ``__init__`` must be imported before
``database.create_db_and_tables()`` is called.
"""

from .agent_message import AgentMessage
from .agent_run import AgentRun, AgentRunApproval, Verification
from .audit import AuditLog
from .company import (
    Agent,
    BusinessUnit,
    Company,
    CompanyMember,
    ProjectCredential,
    ProjectDiscovery,
    User,
)
from .github import GitHubRepoBinding
from .procedure import Procedure
from .runtime import AssistantRuntimeState
from .sprint import BacklogItem, OutboxEvent, Sprint
from .support import BugReport

__all__ = [
    "Agent",
    "AgentMessage",
    "AgentRun",
    "AgentRunApproval",
    "AssistantRuntimeState",
    "AuditLog",
    "BacklogItem",
    "BugReport",
    "BusinessUnit",
    "Company",
    "CompanyMember",
    "GitHubRepoBinding",
    "OutboxEvent",
    "Procedure",
    "ProjectCredential",
    "ProjectDiscovery",
    "Sprint",
    "User",
    "Verification",
]
