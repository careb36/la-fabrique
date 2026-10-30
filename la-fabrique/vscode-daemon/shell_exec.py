"""Running a workspace command on the host shell, and describing how it ended.

Split out of ``daemon.py`` so the NATS handlers stay readable and the daemon
keeps to the repository's file-size ratchet. The module holds no policy: it
arranges the environment, picks the shell and reports the exit — including the
case where there is no exit, because the command ran past its wall clock.

That last distinction is the point of ``timed_out``. The backend verifies what a
producer says it did, and "the suite hung" is a result, not a missing one.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger("fabrique-daemon.shell")

IS_WINDOWS = os.name == "nt"

# Wall clock before a workspace command is killed. Kept under the backend's
# DELIVERY_TEST_TIMEOUT_SECONDS (130s) so this side, not the NATS client,
# reports the timeout and the caller learns the command hung.
COMMAND_TIMEOUT_SECONDS = 120


def build_command_env() -> dict[str, str]:
    """Provide a stable host-like environment for assistant CLI execution."""
    env = os.environ.copy()
    home = env.get("HOME") or str(Path.home())
    env["HOME"] = home
    if IS_WINDOWS:
        return env

    nvm_root = Path(home) / ".nvm" / "versions" / "node"
    nvm_bins = sorted(nvm_root.glob("*/bin"), reverse=True) if nvm_root.exists() else []

    path_entries = [
        *(str(path) for path in nvm_bins),
        os.path.join(home, ".local", "bin"),
        "/opt/homebrew/bin",
        "/usr/local/bin",
        env.get("PATH", ""),
    ]
    env["PATH"] = os.pathsep.join(entry for entry in path_entries if entry)
    return env


def build_shell_command(command: str) -> list[str]:
    """Run commands through the user's shell when available instead of bare /bin/sh."""
    configured_shell = os.getenv("FABRIQUE_EXEC_SHELL")
    if IS_WINDOWS:
        shell_path = configured_shell or os.environ.get("COMSPEC", "cmd.exe")
        if Path(shell_path).stem.lower() in {"powershell", "pwsh"}:
            return [shell_path, "-NoProfile", "-NonInteractive", "-Command", command]
        return [shell_path, "/d", "/s", "/c", command]
    shell_path = configured_shell or (
        "/bin/zsh" if Path("/bin/zsh").exists() else "/bin/sh"
    )
    if shell_path.endswith("zsh"):
        return [shell_path, "-dfc", command]
    if shell_path.endswith("bash"):
        return [shell_path, "--noprofile", "--norc", "-c", command]
    return [shell_path, "-c", command]


def execute_shell_command(command: str, cwd: str = ".") -> dict[str, Any]:
    """Execute a shell command and return a structured result.

    Args:
        command: Shell command string (passed to the host shell).
        cwd:     Working directory for the command.

    Returns:
        Dict with keys ``success`` (bool), ``stdout``, ``stderr``,
        ``exit_code`` — or ``{"success": False, "error": ...}`` on exception.
        A command killed by the timeout keeps ``timed_out: True`` and the output
        captured before the kill, so the caller can tell "hung" from "ran and
        failed".
    """
    logger.info(f"Executing: {command} in {cwd}")
    try:
        result = subprocess.run(
            build_shell_command(command),
            cwd=cwd,
            check=False,
            env=build_command_env(),
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.returncode,
        }
    except subprocess.TimeoutExpired as e:
        return {
            "success": False,
            "stdout": e.output or "",
            "stderr": e.stderr or "",
            "timed_out": True,
            "timeout_seconds": COMMAND_TIMEOUT_SECONDS,
            "error": f"command timed out after {COMMAND_TIMEOUT_SECONDS}s",
        }
    except Exception as e:  # noqa: BLE001 - a command that cannot start must not kill the daemon
        return {"success": False, "error": str(e)}
