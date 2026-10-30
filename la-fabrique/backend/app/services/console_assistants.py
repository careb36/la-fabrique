"""
Console assistants: advice from the terminal CLIs on the daemon's machine.

Before an agent runs a task, the task worker may ask the assistant CLIs the
workspace daemon can run (GitHub Copilot CLI, Claude CLI) for advice on the
task, through ``workspace.execute``. What comes back is context for the
agent's prompt and a note on the board; it is never evidence about the
delivery.

This module decides which assistants to ask (``select_assistants``), renders
their commands with the prompt safely quoted, asks them (``collect_advice``)
and remembers, per company, when one is out of quota or missing on the host
so the next tasks skip it until the cooldown ends (``AssistantRuntimeState``).
Every decision is published to the Glassroom as ``assistant.telemetry``.
"""

import asyncio
import os
import re
import shlex
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from config import settings
from database import engine
from logging_config import setup_logger
from models import AssistantRuntimeState
from nats_client import NATSClient
from sqlmodel import Session, select

from services import console_capabilities
from services.board import CONSOLE_ADVICE_PREFIX
from services.glassroom import publish_glassroom

logger = setup_logger("fabrique-console-assistants")

CONSOLE_ASSISTANTS_ENABLED = settings.CONSOLE_ASSISTANTS_ENABLED
CONSOLE_ASSISTANT_TIMEOUT = float(settings.CONSOLE_ASSISTANT_TIMEOUT_SECONDS)
COPILOT_CLI_COMMAND_TEMPLATE = settings.COPILOT_CLI_COMMAND_TEMPLATE
CLAUDE_CLI_COMMAND_TEMPLATE = settings.CLAUDE_CLI_COMMAND_TEMPLATE or ""
CLAUDE_CLI_ALLOWED_TOOLS = settings.CLAUDE_CLI_ALLOWED_TOOLS
CLAUDE_CLI_APPEND_SYSTEM_PROMPT = settings.CLAUDE_CLI_APPEND_SYSTEM_PROMPT
CONSOLE_ASSISTANT_STRATEGY = settings.CONSOLE_ASSISTANT_STRATEGY
CLAUDE_CLI_HIGH_VALUE_ROLES = {
    role.strip()
    for role in settings.CLAUDE_CLI_HIGH_VALUE_ROLES.split(",")
    if role.strip()
}
CLAUDE_CLI_DEFAULT_COOLDOWN_MINUTES = max(
    1, int(settings.CLAUDE_CLI_DEFAULT_COOLDOWN_MINUTES)
)
ASSISTANT_UNAVAILABLE_COOLDOWN_MINUTES = int(
    os.getenv("ASSISTANT_UNAVAILABLE_COOLDOWN_MINUTES", "30")
)
CONSOLE_ASSISTANT_EXCERPT_CHARS = int(
    os.getenv("CONSOLE_ASSISTANT_EXCERPT_CHARS", "240")
)
CONSOLE_ASSISTANT_ALLOWED_ROLES = {
    role.strip()
    for role in settings.CONSOLE_ASSISTANT_ALLOWED_ROLES.split(",")
    if role.strip()
}
CLAUDE_LABEL = "Claude CLI"
COPILOT_LABEL = "GitHub Copilot CLI"
CLAUDE_QUOTA_PATTERNS = (
    "usage limit",
    "rate limit",
    "quota",
    "too many requests",
)
ASSISTANT_UNAVAILABLE_PATTERNS = (
    "not found",
    "cannot find github copilot cli",
    "no such file or directory",
    "command not found",
)
CLAUDE_RESET_TIME_PATTERNS = (
    re.compile(
        r"(?:available|retry|resets?)\s+(?:at|after)\s+(?P<time>\d{1,2}:\d{2}\s?(?:am|pm)?)",
        re.IGNORECASE,
    ),
    re.compile(r"(?P<time>\d{1,2}:\d{2}\s?(?:am|pm))", re.IGNORECASE),
)

NO_ADVICE: dict[str, Any] = {"combined": "", "sources": []}


def normalize_utc(value: datetime | None) -> datetime | None:
    """Normalize datetimes loaded from the DB to timezone-aware UTC values."""
    if not value:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


# ---------------------------------------------------------------------------
# Which assistants, and what for
# ---------------------------------------------------------------------------


def build_prompt(item: dict[str, Any], agent: dict[str, Any], sprint_name: str) -> str:
    """Build a concise prompt for external console assistants."""
    return (
        f"Repository task for {agent.get('role', 'Developer')} in sprint '{sprint_name}'.\n"
        f"Task: {item.get('title', '')}\n"
        f"Description: {item.get('description', '')}\n"
        f"Priority: {item.get('priority', 'medium')}\n\n"
        "Provide concise actionable advice for implementing this task in the current repository. "
        "Prefer incremental changes, mention relevant existing code or GitHub/MCP-backed ideas when useful, and avoid suggesting destructive rewrites."
    )


def assistant_purpose(item: dict[str, Any], agent: dict[str, Any], label: str) -> str:
    """Describe why an external assistant is being consulted for the current task."""
    role = (agent.get("role") or "Developer").strip()
    priority = (item.get("priority") or "medium").strip().lower()
    task_text = f"{item.get('title', '')}\n{item.get('description', '')}".lower()

    if label == CLAUDE_LABEL:
        if role in {"Architect", "PO", "ScrumMaster"}:
            return "planning and architecture advice"
        if role == "QA" or any(
            token in task_text for token in ("validate", "review", "security", "risk")
        ):
            return "review and risk analysis advice"
        return "high-value implementation guidance"

    if priority in {"high", "critical"}:
        return "high-priority implementation guidance"
    return "incremental implementation guidance"


def claude_is_high_value(item: dict[str, Any], agent: dict[str, Any]) -> bool:
    """Use Claude selectively for strategic, review-heavy, or high-priority work."""
    role = (agent.get("role") or "Developer").strip()
    priority = (item.get("priority") or "medium").strip().lower()
    task_text = f"{item.get('title', '')}\n{item.get('description', '')}".lower()
    strategic_keywords = (
        "architecture",
        "plan",
        "planning",
        "review",
        "security",
        "risk",
        "refactor",
        "scrumban",
        "autonomy",
        "self-improvement",
        "design",
    )
    return (
        role in CLAUDE_CLI_HIGH_VALUE_ROLES
        or priority in {"high", "critical"}
        or any(keyword in task_text for keyword in strategic_keywords)
    )


def select_assistants(
    item: dict[str, Any], agent: dict[str, Any]
) -> list[tuple[str, str, str]]:
    """Choose assistants efficiently so Copilot is the default and Claude stays budget-aware.

    Each entry is ``(label, command template, purpose)``.
    """
    assistants: list[tuple[str, str, str]] = []
    if CONSOLE_ASSISTANT_STRATEGY == "copilot_first" and COPILOT_CLI_COMMAND_TEMPLATE:
        assistants.append(
            (
                COPILOT_LABEL,
                COPILOT_CLI_COMMAND_TEMPLATE,
                assistant_purpose(item, agent, COPILOT_LABEL),
            )
        )

    if CLAUDE_CLI_COMMAND_TEMPLATE and claude_is_high_value(item, agent):
        assistants.append(
            (
                CLAUDE_LABEL,
                CLAUDE_CLI_COMMAND_TEMPLATE,
                assistant_purpose(item, agent, CLAUDE_LABEL),
            )
        )

    if not assistants and COPILOT_CLI_COMMAND_TEMPLATE:
        assistants.append(
            (
                COPILOT_LABEL,
                COPILOT_CLI_COMMAND_TEMPLATE,
                assistant_purpose(item, agent, COPILOT_LABEL),
            )
        )

    return assistants


# ---------------------------------------------------------------------------
# Cooldowns: remembered per company so a restart does not retry a dead CLI
# ---------------------------------------------------------------------------


def assistant_key_for_label(label: str) -> str:
    if label == CLAUDE_LABEL:
        return "claude"
    if label == COPILOT_LABEL:
        return "copilot"
    return re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_") or "assistant"


def _get_runtime_state(
    company_id: int, assistant_key: str
) -> AssistantRuntimeState | None:
    """Load the persisted runtime state for a company/assistant pair."""
    with Session(engine) as session:
        return session.exec(
            select(AssistantRuntimeState).where(
                AssistantRuntimeState.company_id == company_id,
                AssistantRuntimeState.assistant_key == assistant_key,
            )
        ).first()


def set_runtime_state(
    company_id: int,
    assistant_key: str,
    *,
    cooldown_until: datetime | None,
    last_error: str | None = None,
) -> datetime | None:
    """Persist runtime state updates so assistant cooldown survives backend restarts."""
    normalized_cooldown = normalize_utc(cooldown_until)
    with Session(engine) as session:
        state = session.exec(
            select(AssistantRuntimeState).where(
                AssistantRuntimeState.company_id == company_id,
                AssistantRuntimeState.assistant_key == assistant_key,
            )
        ).first()
        if not state:
            state = AssistantRuntimeState(
                company_id=company_id, assistant_key=assistant_key
            )
        state.cooldown_until = normalized_cooldown
        state.last_error = (last_error or "")[:1000] or None
        state.updated_at = datetime.now(UTC)
        session.add(state)
        session.commit()
    return normalized_cooldown


def cooldown_until(company_id: int, assistant_key: str) -> datetime | None:
    """The persisted cooldown deadline for an assistant, cleared once it has passed."""
    now = datetime.now(UTC)
    state = _get_runtime_state(company_id, assistant_key)
    deadline = normalize_utc(state.cooldown_until) if state else None
    if deadline and deadline <= now:
        set_runtime_state(
            company_id, assistant_key, cooldown_until=None, last_error=None
        )
        return None
    return deadline


def parse_claude_reset_time(text: str) -> datetime | None:
    """Best-effort parse for reset times embedded in Claude CLI quota messages."""
    now = datetime.now().astimezone()
    for pattern in CLAUDE_RESET_TIME_PATTERNS:
        match = pattern.search(text or "")
        if not match:
            continue
        raw_time = (match.group("time") or "").strip().upper().replace(" ", "")
        formats = ["%I:%M%p", "%H:%M"]
        for fmt in formats:
            try:
                parsed = datetime.strptime(raw_time, fmt).replace(tzinfo=now.tzinfo)
            except ValueError:
                continue
            candidate = now.replace(
                hour=parsed.hour, minute=parsed.minute, second=0, microsecond=0
            )
            if candidate <= now:
                candidate += timedelta(days=1)
            return candidate.astimezone(UTC)
    return None


def activate_claude_cooldown(company_id: int, output: str) -> datetime | None:
    """Detect Claude quota exhaustion and persist a cooldown window for the company."""
    lowered = (output or "").lower()
    if not any(token in lowered for token in CLAUDE_QUOTA_PATTERNS):
        return None
    deadline = parse_claude_reset_time(output) or (
        datetime.now(UTC) + timedelta(minutes=CLAUDE_CLI_DEFAULT_COOLDOWN_MINUTES)
    )
    return set_runtime_state(
        company_id, "claude", cooldown_until=deadline, last_error=output
    )


def activate_unavailable_cooldown(
    company_id: int, label: str, output: str
) -> datetime | None:
    """Persist a short cooldown when an assistant binary is missing or unusable."""
    lowered = (output or "").lower()
    if not any(token in lowered for token in ASSISTANT_UNAVAILABLE_PATTERNS):
        return None
    return set_runtime_state(
        company_id,
        assistant_key_for_label(label),
        cooldown_until=datetime.now(UTC)
        + timedelta(minutes=max(1, ASSISTANT_UNAVAILABLE_COOLDOWN_MINUTES)),
        last_error=output,
    )


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def render_command(template: str, prompt: str, workspace_root: str) -> str | None:
    """Render a shell command template with a safely quoted prompt."""
    normalized = (template or "").strip()
    if not normalized:
        return None
    quoted_values = {
        "prompt": shlex.quote(prompt),
        "workspace_root": shlex.quote(workspace_root),
        "allowed_tools": shlex.quote(CLAUDE_CLI_ALLOWED_TOOLS),
        "system_prompt": shlex.quote(CLAUDE_CLI_APPEND_SYSTEM_PROMPT),
    }
    if any(
        token in normalized
        for token in (
            "{prompt}",
            "{workspace_root}",
            "{allowed_tools}",
            "{system_prompt}",
        )
    ):
        return normalized.format(**quoted_values)
    return f"{normalized} {quoted_values['prompt']}"


def replace_command_binary(command: str, original: str, replacement: str) -> str:
    """Swap the first command token while preserving the rest of the shell command."""
    if command == original:
        return replacement
    prefix = f"{original} "
    if command.startswith(prefix):
        return f"{replacement}{command[len(original) :]}"
    return command


def wrap_command_with_fallback(label: str, command: str) -> str:
    """Add host-specific binary fallback paths for known assistants."""
    if label == COPILOT_LABEL:
        fallback = '"$HOME/Library/Application Support/Code/User/globalStorage/github.copilot-chat/copilotCli/copilot"'
        fallback_command = replace_command_binary(command, "copilot", fallback)
        return (
            f"if [ -x {fallback} ]; then {fallback_command}; "
            f"elif command -v copilot >/dev/null 2>&1; then {command}; "
            f"else {command}; fi"
        )

    if label == CLAUDE_LABEL:
        fallback = '"$HOME/.local/bin/claude"'
        fallback_command = replace_command_binary(command, "claude", fallback)
        return (
            f"if command -v claude >/dev/null 2>&1; then {command}; "
            f"elif [ -x {fallback} ]; then {fallback_command}; "
            f"else {command}; fi"
        )

    return command


# ---------------------------------------------------------------------------
# Asking them
# ---------------------------------------------------------------------------


async def publish_event(
    nats_client: NATSClient,
    sprint_id: int,
    item: dict[str, Any],
    label: str,
    purpose: str,
    message: str,
    *,
    decision: str,
    detail: str | None = None,
) -> None:
    """Publish a Glassroom status event explaining an assistant usage decision."""
    await publish_glassroom(
        nats_client,
        sprint_id,
        {
            "type": "status",
            "semantic_type": "assistant.telemetry",
            "source": "task_worker",
            "agent": "System",
            "role": "System",
            "task_id": item.get("id"),
            "task": item.get("title", "Task"),
            "message": message,
            "assistant_label": label,
            "assistant_purpose": purpose,
            "assistant_decision": decision,
            "assistant_detail": detail or "",
        },
    )


async def collect_advice(
    nats_client: NATSClient,
    item: dict[str, Any],
    agent: dict[str, Any],
    sprint: dict[str, Any],
    resolve_workspace_root: Callable[[int], str | None],
) -> dict[str, Any]:
    """Ask the configured assistants, through the daemon, for advice on *item*.

    Returns ``{"combined": <notes for the prompt>, "sources": [...]}``; empty when
    assistants are disabled, the role is not allowed, the daemon reported none,
    or the company has no project folder. *resolve_workspace_root* maps a
    company id to its project folder and is only called when an assistant will
    run.
    """
    if not CONSOLE_ASSISTANTS_ENABLED:
        return dict(NO_ADVICE)

    role = agent.get("role", "Developer")
    if role not in CONSOLE_ASSISTANT_ALLOWED_ROLES:
        return dict(NO_ADVICE)

    # Only consult assistants the daemon reported it can run; the capability
    # probe runs once when workers start (see lifecycle).
    available = set(console_capabilities.available_console_assistants())
    if not available:
        console_capabilities.log_skip_once()
        return dict(NO_ADVICE)
    assistants = [
        assistant
        for assistant in select_assistants(item, agent)
        if console_capabilities.command_binary(assistant[1]) in available
    ]
    if not assistants:
        return dict(NO_ADVICE)

    workspace_root = await asyncio.to_thread(
        resolve_workspace_root, sprint["company_id"]
    )
    if not workspace_root:
        return dict(NO_ADVICE)

    prompt = build_prompt(item, agent, sprint["name"])
    notes: list[str] = []
    sources: list[dict[str, str]] = []

    for label, template, purpose in assistants:
        assistant_key = assistant_key_for_label(label)
        deadline = await asyncio.to_thread(
            cooldown_until, sprint["company_id"], assistant_key
        )
        if deadline:
            cooldown_local = deadline.astimezone().strftime("%H:%M")
            if label == CLAUDE_LABEL:
                await publish_event(
                    nats_client,
                    sprint["id"],
                    item,
                    label,
                    purpose,
                    f"Claude CLI skipped for now due to quota cooldown until {cooldown_local}. Copilot remains the default assistant.",
                    decision="skipped_quota_cooldown",
                    detail=f"cooldown_until={deadline.isoformat()}",
                )
            else:
                await publish_event(
                    nats_client,
                    sprint["id"],
                    item,
                    label,
                    purpose,
                    f"{label} skipped temporarily after repeated local availability failures. Cooldown until {cooldown_local}.",
                    decision="skipped_unavailable_cooldown",
                    detail=f"cooldown_until={deadline.isoformat()}",
                )
            continue

        await publish_event(
            nats_client,
            sprint["id"],
            item,
            label,
            purpose,
            f"Consulting {label} for {purpose} on: {item.get('title', 'task')}",
            decision="requested",
        )

        command = render_command(template, prompt, workspace_root)
        if not command:
            continue
        command = wrap_command_with_fallback(label, command)

        try:
            result = await nats_client.request(
                "workspace.execute",
                {
                    "workspace_root": workspace_root,
                    "command": command,
                    "sprint_id": sprint["id"],
                },
                timeout=CONSOLE_ASSISTANT_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001 - Assistant failures fall back without aborting task execution.
            logger.warning(
                "Console assistant request failed for %s on item=%s: %s",
                label,
                item.get("id"),
                exc,
            )
            await publish_event(
                nats_client,
                sprint["id"],
                item,
                label,
                purpose,
                f"{label} request failed while gathering {purpose}.",
                decision="failed",
                detail=str(exc),
            )
            continue

        output = str(result.get("stdout") or result.get("stderr") or "").strip()
        if not result.get("success"):
            logger.info(
                "Console assistant %s unavailable for item=%s exit=%s",
                label,
                item.get("id"),
                result.get("exit_code"),
            )
            if label == CLAUDE_LABEL:
                deadline = await asyncio.to_thread(
                    activate_claude_cooldown, sprint["company_id"], output
                )
                if deadline:
                    cooldown_local = deadline.astimezone().strftime("%H:%M")
                    await publish_event(
                        nats_client,
                        sprint["id"],
                        item,
                        label,
                        purpose,
                        f"Claude CLI hit quota limits and entered cooldown until {cooldown_local}. Future tasks will prefer Copilot until then.",
                        decision="quota_cooldown",
                        detail=output[:CONSOLE_ASSISTANT_EXCERPT_CHARS],
                    )
                    continue
            unavailable_until = await asyncio.to_thread(
                activate_unavailable_cooldown, sprint["company_id"], label, output
            )
            if unavailable_until:
                cooldown_local = unavailable_until.astimezone().strftime("%H:%M")
                await publish_event(
                    nats_client,
                    sprint["id"],
                    item,
                    label,
                    purpose,
                    f"{label} is unavailable in the local runtime and entered cooldown until {cooldown_local}.",
                    decision="unavailable_cooldown",
                    detail=output[:CONSOLE_ASSISTANT_EXCERPT_CHARS],
                )
                continue
            await publish_event(
                nats_client,
                sprint["id"],
                item,
                label,
                purpose,
                f"{label} was unavailable for {purpose}.",
                decision="unavailable",
                detail=output[:CONSOLE_ASSISTANT_EXCERPT_CHARS],
            )
            continue

        if output:
            notes.append(f"[{label}]\n{output[:2500]}")
            sources.append(
                {
                    "label": label,
                    "purpose": purpose,
                    "excerpt": output[:CONSOLE_ASSISTANT_EXCERPT_CHARS],
                }
            )
            await publish_event(
                nats_client,
                sprint["id"],
                item,
                label,
                purpose,
                f"{label} contributed {purpose} for: {item.get('title', 'task')}",
                decision="used",
                detail=output[:CONSOLE_ASSISTANT_EXCERPT_CHARS],
            )

    return {"combined": "\n\n".join(notes), "sources": sources}


def usage_comment(sources: list[dict[str, str]]) -> str:
    """Summarize which external assistants were used and their immediate value."""
    if not sources:
        return ""

    lines = [CONSOLE_ADVICE_PREFIX]
    for source in sources:
        label = source.get("label", "Assistant")
        purpose = source.get("purpose", "advice")
        excerpt = (source.get("excerpt") or "").strip().replace("\n", " ")
        lines.append(f"- {label} ({purpose}): {excerpt}")
    return "\n".join(lines)[:1800]
