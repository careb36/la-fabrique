"""
Fabrique Enterprise API — FastAPI application entry point.

Responsibilities:
- Creates the FastAPI app and configures CORS
- Mounts all API routers (auth, enterprise, sprint, agents, support)
- Registers global exception handlers
- Registers lifecycle handlers (startup/shutdown)
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from config import Settings
from exception_handlers import register_exception_handlers
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from lifecycle import shutdown, startup
from metrics import setup_metrics
from routers import (
    agent_runs_router,
    agents_router,
    auth_router,
    enterprise_router,
    github_router,
    inbox_router,
    messages_router,
    procedures_router,
    sprint_router,
    support_router,
    workspace_router,
)
from security import add_security_headers, get_cors_origins, setup_security
from services.healthcheck import aggregate
from ui_static import mount_ui

settings = Settings()


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Runs the startup/shutdown handlers for the app's lifetime.

    Starlette 1.0 removed `add_event_handler`, so this is the only way left to
    hook the lifecycle.
    """
    await startup(application)
    try:
        yield
    finally:
        await shutdown(application)


app = FastAPI(
    lifespan=lifespan,
    title="Fabrique Enterprise API",
    description="Autonomous AI Engineering Factory API with Multi-Tenancy, Governance, and Auto-Healing support.",
    version="2026.4.1",
    openapi_tags=[
        {"name": "Core", "description": "Factory initialization and sprint management"},
        {"name": "Enterprise", "description": "Multi-tenancy, Quotas, and Governance"},
        {"name": "Support", "description": "System health, logs, and bug reporting"},
        {"name": "Agents", "description": "LangGraph orchestration and Glassroom SSE"},
        {"name": "Auth", "description": "User registration and company membership"},
        {
            "name": "Workspace",
            "description": "The developer's machine via the workspace daemon",
        },
    ],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # The support logs download names its file in this header.
    expose_headers=["Content-Disposition"],
)

# Setup security (rate limiting + security headers)
setup_security(app)

# Setup Prometheus metrics
setup_metrics(app)

app.include_router(auth_router)
app.include_router(enterprise_router)
app.include_router(sprint_router)
app.include_router(agents_router)
app.include_router(agent_runs_router)
app.include_router(support_router)
app.include_router(github_router)
app.include_router(inbox_router)
app.include_router(messages_router)
app.include_router(procedures_router)
app.include_router(workspace_router)

# Register exception handlers
register_exception_handlers(app)


def _nats_state(request: Request) -> str:
    return getattr(request.app.state, "nats_state", "connecting")


@app.get("/health")
async def health_check(request: Request):
    return {
        "status": "healthy",
        "timestamp": datetime.now(UTC).replace(tzinfo=None).isoformat(),
        "nats": _nats_state(request),
        "jetstream": bool(getattr(request.app.state, "jetstream", False)),
    }


@app.get("/health/deep")
async def deep_health_check(request: Request):
    nats_client = getattr(request.app.state, "nats_client", None)
    return await aggregate(nats_client, nats_state=_nats_state(request))


# Last, so every API route above wins over the SPA fallback.
mount_ui(app)

# Even later: the shell the SPA fallback returns is exactly what an iframe
# loads, so the headers have to wrap that middleware too.
add_security_headers(app)
