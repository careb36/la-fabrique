"""
Public re-export surface for all FastAPI routers.

Import these objects in ``main.py`` via ``from routers import ...`` instead of
importing each router module individually.  This keeps ``main.py`` clean and
makes it easy to rename or split router modules in the future.
"""

from routers.agent_runs import router as agent_runs_router
from routers.agents import router as agents_router
from routers.auth import router as auth_router
from routers.enterprise import router as enterprise_router
from routers.github import router as github_router
from routers.inbox import router as inbox_router
from routers.messages import router as messages_router
from routers.procedures import router as procedures_router
from routers.sprint import router as sprint_router
from routers.support import router as support_router
from routers.workspace import router as workspace_router

__all__ = [
    "agent_runs_router",
    "agents_router",
    "auth_router",
    "enterprise_router",
    "github_router",
    "inbox_router",
    "messages_router",
    "procedures_router",
    "sprint_router",
    "support_router",
    "workspace_router",
]
