"""
Requests to the workspace daemon about the user's own machine.

The backend runs in a container; the projects live on the developer's macOS,
Linux or Windows machine, where the workspace daemon runs.  Every question
about that machine's files — list a folder, inspect a project — is a NATS
request to the daemon.  Paths are the host's own absolute paths and are passed
through as opaque strings: the backend never resolves them locally.
"""

import contextlib
import os
import tempfile
from collections.abc import Iterator
from pathlib import PurePosixPath
from typing import Any

STATUS_TIMEOUT_SECONDS = 3.0
BROWSE_TIMEOUT_SECONDS = 10.0
INSPECT_TIMEOUT_SECONDS = 30.0


DAEMON_UNAVAILABLE_DETAIL = (
    "The workspace daemon is not connected. Start it on the computer that has "
    "your projects: ./scripts/start-daemon.sh (macOS/Linux) or "
    ".\\scripts\\start-daemon.ps1 (Windows)."
)


class DaemonUnavailable(Exception):
    """No workspace daemon answered (not running, or NATS is down).

    ``absent`` is True only when NATS said that nobody listens on the subject
    ("no responders"): a daemon that is not running. A timeout or an
    unreachable NATS leaves it False: whether a daemon runs is then unknown.
    """

    def __init__(self, message: str, absent: bool = False):
        super().__init__(message)
        self.absent = absent


def _no_responders(exc: BaseException) -> bool:
    return (
        type(exc).__name__ == "NoRespondersError" or "no responders" in str(exc).lower()
    )


class DaemonError(Exception):
    """The daemon answered with an error; ``status`` follows HTTP."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


async def daemon_request(
    nats_client: Any, subject: str, payload: dict[str, Any], timeout: float
) -> dict[str, Any]:
    if nats_client is None:
        raise DaemonUnavailable("NATS is not connected")
    try:
        reply = await nats_client.request(subject, payload, timeout=timeout)
    except Exception as e:
        raise DaemonUnavailable(
            f"{type(e).__name__}: {e}", absent=_no_responders(e)
        ) from e
    if not isinstance(reply, dict):
        raise DaemonError(502, "The workspace daemon sent an unreadable reply")
    error = reply.get("error")
    if isinstance(error, dict):
        raise DaemonError(
            int(error.get("status") or 502),
            str(error.get("message") or "workspace daemon error"),
        )
    return reply


async def daemon_presence(nats_client: Any) -> dict[str, Any]:
    """Whether a daemon is ``connected``, ``absent`` or ``unknown``, and why.

    Unknown is not absent: when NATS cannot be reached, no reply arrives in
    time or the daemon answers with an error, the backend cannot tell whether
    a daemon runs, and says so rather than reporting it stopped.
    """
    try:
        status = await daemon_request(
            nats_client, "workspace.status", {}, STATUS_TIMEOUT_SECONDS
        )
    except DaemonUnavailable as exc:
        if exc.absent:
            return {
                "state": "absent",
                "reason": "no daemon is listening",
                "status": None,
            }
        if nats_client is None:
            return {
                "state": "unknown",
                "reason": "the backend is not connected to NATS",
                "status": None,
            }
        if (
            isinstance(exc.__cause__, TimeoutError)
            or "timeout" in type(exc.__cause__).__name__.lower()
        ):
            reason = f"no answer within {STATUS_TIMEOUT_SECONDS:g} s"
        else:
            reason = str(exc)
        return {"state": "unknown", "reason": reason, "status": None}
    except DaemonError as exc:
        return {
            "state": "unknown",
            "reason": f"the daemon answered with an error: {exc.message}",
            "status": None,
        }
    return {"state": "connected", "reason": None, "status": status}


async def inspect_project(
    nats_client: Any, path: str, snapshot: bool = False
) -> dict[str, Any]:
    return await daemon_request(
        nats_client,
        "workspace.inspect",
        {"path": path, "snapshot": snapshot},
        INSPECT_TIMEOUT_SECONDS,
    )


def _safe_relative(path: str) -> PurePosixPath | None:
    relative = PurePosixPath(path)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        return None
    return relative


@contextlib.contextmanager
def materialized_snapshot(snapshot: dict[str, Any]) -> Iterator[str]:
    """
    A temporary folder that mirrors the daemon's snapshot of a project.

    Every listed file exists (empty unless the daemon sent its text), so the
    filesystem-based stack and test detection run unchanged on a project that
    is on another machine.
    """
    files = snapshot.get("files") or []
    contents = snapshot.get("contents") or {}
    with tempfile.TemporaryDirectory(prefix="fabrique-snapshot-") as root:
        for path in files:
            relative = _safe_relative(path) if isinstance(path, str) else None
            if relative is None:
                continue
            target = os.path.join(root, *relative.parts)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            text = contents.get(path)
            with open(target, "w", encoding="utf-8") as fh:
                if isinstance(text, str):
                    fh.write(text)
        yield root


def without_snapshot(project: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in project.items() if key != "snapshot"}
