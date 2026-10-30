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
