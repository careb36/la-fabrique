"""
Workspace router — the developer's machine, as seen by the workspace daemon.

The folder picker and the project check in "New company" use these endpoints.
They relay to the daemon running on the user's computer (macOS, Linux or
Windows), so the paths are that computer's own: the backend's container does
not need to see the user's disk.
"""

from auth_policy import current_user_if_required, require_authenticated
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from models import User
from services.workspace_daemon import (
    BROWSE_TIMEOUT_SECONDS,
    DAEMON_UNAVAILABLE_DETAIL,
    DaemonError,
    DaemonUnavailable,
    daemon_presence,
    daemon_request,
    inspect_project,
    without_snapshot,
)

router = APIRouter(prefix="/v1/workspace", tags=["Workspace"])


def _nats(request: Request):
    return getattr(request.app.state, "nats_client", None)


def _raise_for(exc: Exception):
    if isinstance(exc, DaemonUnavailable):
        raise HTTPException(status_code=503, detail=DAEMON_UNAVAILABLE_DETAIL)
    if isinstance(exc, DaemonError):
        raise HTTPException(status_code=exc.status, detail=exc.message)
    raise exc


@router.get("/status")
async def workspace_status(
    request: Request,
    user: User | None = Depends(current_user_if_required),  # noqa: B008 - FastAPI dependency marker.
):
    """Whether a workspace daemon is connected, absent or unknown, and on which machine.

    ``state`` is ``connected``, ``absent`` (nothing listens) or ``unknown``
    (NATS unreachable, no answer in time, or an error reply), with ``reason``;
    ``connected`` stays for older clients.
    """
    require_authenticated(user)
    presence = await daemon_presence(_nats(request))
    status = presence["status"]
    return {
        "connected": presence["state"] == "connected",
        "state": presence["state"],
        "reason": presence["reason"],
        "host": (status or {}).get("host"),
        "jetstream": bool(getattr(request.app.state, "jetstream", False)),
    }


@router.get("/browse")
async def browse_folders(
    request: Request,
    path: str | None = Query(default=None),
    user: User | None = Depends(current_user_if_required),  # noqa: B008 - FastAPI dependency marker.
):
    """Sub-folders of *path* (default: the home folder) on the daemon's machine."""
    require_authenticated(user)
    try:
        return await daemon_request(
            _nats(request),
            "workspace.browse",
            {"path": path} if path else {},
            BROWSE_TIMEOUT_SECONDS,
        )
    except (DaemonUnavailable, DaemonError) as exc:
        _raise_for(exc)


@router.get("/inspect")
async def inspect_folder(
    request: Request,
    path: str = Query(..., min_length=1),
    user: User | None = Depends(current_user_if_required),  # noqa: B008 - FastAPI dependency marker.
):
    """Canonical path, existence and git remote/branch of a project folder."""
    require_authenticated(user)
    try:
        project = await inspect_project(_nats(request), path)
    except (DaemonUnavailable, DaemonError) as exc:
        _raise_for(exc)
    return without_snapshot(project)
