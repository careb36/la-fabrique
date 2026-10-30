"""
Console assistant capabilities reported by the VS Code daemon.

The task worker can ask the daemon to run terminal assistants (``copilot``,
``claude``) through ``workspace.execute``.  When the daemon host has neither
CLI installed, every such request burns the full per-call timeout.  The backend
therefore asks the daemon once, on ``workspace.capabilities``, which assistant
binaries it can find, and caches the answer for the life of the process.

A failed or timed-out probe is cached as ``None``; callers treat that the same
as an empty list and skip the console-assistant step.
"""

import shlex
from typing import Any

from config import settings
from logging_config import setup_logger

logger = setup_logger("fabrique-console-capabilities")

CAPABILITIES_SUBJECT = "workspace.capabilities"
CAPABILITIES_TIMEOUT_SECONDS = 2.0

# ``None`` until probed, then the list the daemon reported, or ``None`` again
# with ``_probe_failed`` set when the request could not be answered.
_available: list[str] | None = None
_probed = False
_probe_failed = False
_skip_logged = False


def command_binary(template: str | None) -> str | None:
    """Return the executable name a command template starts with."""
    try:
        tokens = shlex.split(template or "")
    except ValueError:
        tokens = (template or "").split()
    return tokens[0] if tokens else None


def configured_assistant_commands() -> list[str]:
    """Executable names of the configured Copilot and Claude command templates."""
    commands: list[str] = []
    for template in (
        settings.COPILOT_CLI_COMMAND_TEMPLATE,
        settings.CLAUDE_CLI_COMMAND_TEMPLATE,
    ):
        binary = command_binary(template)
        if binary and binary not in commands:
            commands.append(binary)
    return commands


async def probe_console_assistants(
    nats_client: Any,
    commands: list[str] | None = None,
    timeout: float = CAPABILITIES_TIMEOUT_SECONDS,
) -> list[str] | None:
    """Ask the daemon which assistant *commands* it can run, and cache the answer."""
    global _available, _probed, _probe_failed, _skip_logged
    _skip_logged = False
    if commands is None:
        commands = configured_assistant_commands()
    try:
        reply = await nats_client.request(
            CAPABILITIES_SUBJECT, {"commands": commands}, timeout=timeout
        )
        assistants = reply.get("assistants") if isinstance(reply, dict) else None
        if not isinstance(assistants, list):
            raise TypeError(f"unexpected capabilities reply: {reply!r}")
        _available = [str(name) for name in assistants]
        _probe_failed = False
        logger.info("Daemon console assistants available: %s", _available)
    except Exception as exc:  # noqa: BLE001 - A missing daemon must not stop workers from starting.
        _available = None
        _probe_failed = True
        logger.warning(
            "Console assistant capability probe failed (%s: %s); "
            "console assistants are disabled until the backend restarts.",
            type(exc).__name__,
            exc,
        )
    _probed = True
    return _available


def available_console_assistants() -> list[str]:
    """Return the cached assistant names; empty when unprobed or the probe failed."""
    return list(_available or [])


def log_skip_once() -> None:
    """Log, once per probe, that the console-assistant step is being skipped."""
    global _skip_logged
    if _skip_logged:
        return
    _skip_logged = True
    if not _probed:
        reason = "the daemon has not been asked for its capabilities"
    elif _probe_failed:
        reason = "the daemon capability request failed"
    else:
        reason = "the daemon reported no assistant CLI on its PATH"
    logger.info("Skipping console assistants for all tasks: %s.", reason)


def reset() -> None:
    """Forget the cached probe result (used by tests)."""
    global _available, _probed, _probe_failed, _skip_logged
    _available = None
    _probed = False
    _probe_failed = False
    _skip_logged = False
