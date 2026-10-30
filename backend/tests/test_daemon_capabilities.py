"""
``workspace.capabilities`` handler in vscode-daemon/daemon.py (issue #103).

The daemon is not a package, so it is imported by file path.  ``shutil.which``
is patched so the result does not depend on the CLIs installed on this host.

Run with:
    cd backend && PYTHONPATH=.:app python3 -m pytest tests/test_daemon_capabilities.py -q
"""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

DAEMON_PATH = Path(__file__).resolve().parents[2] / "vscode-daemon" / "daemon.py"


@pytest.fixture(scope="module")
def daemon():
    spec = importlib.util.spec_from_file_location("fabrique_vscode_daemon", DAEMON_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _which_finding(*found):
    def fake_which(name, path=None):
        return f"/usr/local/bin/{name}" if name in found else None

    return fake_which


async def _ask(daemon, payload: dict | None):
    nc = SimpleNamespace(publish=AsyncMock())
    data = json.dumps(payload).encode() if payload is not None else b""
    msg = SimpleNamespace(subject="workspace.capabilities", data=data, reply="_INBOX.1")
    await daemon.handle_capabilities(nc, msg)
    nc.publish.assert_awaited_once()
    subject, body = nc.publish.await_args.args
    assert subject == "_INBOX.1"
    return json.loads(body.decode())


@pytest.mark.asyncio
async def test_capabilities_lists_assistants_found_on_path(daemon, monkeypatch):
    monkeypatch.setattr(daemon.shutil, "which", _which_finding("claude"))

    reply = await _ask(daemon, {"commands": ["copilot", "claude"]})

    assert reply == {"assistants": ["claude"]}


@pytest.mark.asyncio
async def test_capabilities_empty_when_no_cli_installed(daemon, monkeypatch):
    monkeypatch.setattr(daemon.shutil, "which", _which_finding())
    monkeypatch.setattr(daemon, "ASSISTANT_FALLBACK_PATHS", {})

    reply = await _ask(daemon, {})

    assert reply == {"assistants": []}


@pytest.mark.asyncio
async def test_capabilities_default_commands_and_empty_body(daemon, monkeypatch):
    monkeypatch.setattr(daemon.shutil, "which", _which_finding("copilot", "claude"))
    monkeypatch.setattr(daemon, "ASSISTANT_COMMANDS_DEFAULT", "copilot,claude")

    reply = await _ask(daemon, None)

    assert reply == {"assistants": ["copilot", "claude"]}


@pytest.mark.asyncio
async def test_capabilities_ignores_paths_and_shell_syntax(daemon, monkeypatch):
    monkeypatch.setattr(daemon.shutil, "which", lambda name, path=None: "/bin/x")

    reply = await _ask(daemon, {"commands": ["/bin/sh", "../claude", "claude"]})

    assert reply == {"assistants": ["claude"]}


# --- workspace.execute: a command the timeout killed --------------------------


def _fake_run(daemon, monkeypatch, **kwargs):
    seen = {}

    def fake(*args, **inner):
        seen.update(inner)
        seen["argv"] = args[0] if args else None
        outcome = kwargs.get("raises")
        if outcome is not None:
            raise outcome
        return SimpleNamespace(
            returncode=kwargs.get("returncode", 0), stdout="", stderr=""
        )

    monkeypatch.setattr(daemon.subprocess, "run", fake)
    return seen


def test_execute_reports_a_timeout_as_timed_out_with_its_output(daemon, monkeypatch):
    """The backend must be able to tell 'hung' from 'ran and failed'."""
    import subprocess

    seen = _fake_run(
        daemon,
        monkeypatch,
        raises=subprocess.TimeoutExpired(
            cmd="sleep 999", timeout=120, output="partial"
        ),
    )

    result = daemon.execute_shell_command("sleep 999", "/tmp")

    assert result["success"] is False
    assert result["timed_out"] is True
    assert result["timeout_seconds"] == seen["timeout"]
    assert result["stdout"] == "partial"
    assert "timed out" in result["error"]


def test_execute_reports_a_normal_failure_without_the_timed_out_flag(
    daemon, monkeypatch
):
    _fake_run(daemon, monkeypatch, returncode=2)

    result = daemon.execute_shell_command("false", "/tmp")

    assert result["exit_code"] == 2
    assert "timed_out" not in result


def test_execute_uses_the_module_timeout_constant(daemon, monkeypatch):
    """The daemon timeout must stay under the backend's 130s NATS wait."""
    seen = _fake_run(daemon, monkeypatch, returncode=0)

    daemon.execute_shell_command("true", "/tmp")

    assert seen["timeout"] == daemon.COMMAND_TIMEOUT_SECONDS
    assert daemon.COMMAND_TIMEOUT_SECONDS < 130


def test_execute_keeps_other_errors_untyped(daemon, monkeypatch):
    _fake_run(daemon, monkeypatch, raises=OSError("no such directory"))

    result = daemon.execute_shell_command("true", "/nonexistent")

    assert result["success"] is False
    assert "timed_out" not in result
    assert "no such directory" in result["error"]
