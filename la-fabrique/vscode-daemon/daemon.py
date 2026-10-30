"""
Fabrique workspace daemon.

Runs natively on the developer's machine (macOS, Linux or Windows) — the one
where the project was cloned — and is the only Fabrique component that touches
that machine's files.  The backend reaches it over NATS:

- workspace.generate:     write files (request/reply, per-file sha256 of the bytes on disk)
- workspace.execute:      run a shell command in the project and return its output
- workspace.capabilities: the console assistant CLIs found on PATH
- workspace.status:       which machine this is (hostname, platform, home)
- workspace.browse:       list the sub-folders of a folder, for the folder picker
- workspace.inspect:      validate a project folder: git remote/branch, optional file snapshot
- workspace.deliver:      (JetStream) files queued while this daemon was offline;
                          the result goes to workspace.delivered

Start it with scripts/start-daemon.sh (macOS/Linux) or scripts/start-daemon.ps1
(Windows); it reconnects to NATS on its own.
"""

import asyncio
import configparser
import hashlib
import json
import logging
import os
import platform
import shutil
import stat
import string
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

import nats
from nats.errors import TimeoutError as NATSTimeoutError

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("fabrique-daemon")

DAEMON_VERSION = "2026.10"
NATS_URL = os.getenv("NATS_URL", "nats://localhost:4222")
WORKSPACE_ROOT_DEFAULT = os.getenv("WORKSPACE_ROOT", os.path.expanduser("~/factory-workspaces"))
IS_WINDOWS = os.name == "nt"
PROTECTED_ROOT_DOCS = set()
# Console assistant commands reported by workspace.capabilities when the
# request does not name its own list.
ASSISTANT_COMMANDS_DEFAULT = os.getenv("CONSOLE_ASSISTANT_COMMANDS", "copilot,claude")
# Off-PATH install locations the backend's command wrapper falls back to.
ASSISTANT_FALLBACK_PATHS = {
    "copilot": "~/Library/Application Support/Code/User/globalStorage/github.copilot-chat/copilotCli/copilot",
}
# Every daemon instance answers in this queue group, so a request is handled once.
QUEUE_GROUP = "workspace-daemon"

# JetStream streams for deliveries queued while no daemon was connected.  The
# backend declares the same streams (backend/app/nats_client.py).
DELIVER_SUBJECT = "workspace.deliver"
DELIVERED_SUBJECT = "workspace.delivered"
DELIVERY_STREAMS = {
    "FABRIQUE_DELIVERIES": DELIVER_SUBJECT,
    "FABRIQUE_DELIVERY_RESULTS": DELIVERED_SUBJECT,
}
DELIVERY_CONSUMER = "workspace-daemon"
STREAM_MAX_AGE_SECONDS = 7 * 24 * 3600
STREAM_DUPLICATE_WINDOW_SECONDS = 15 * 60

def compute_prompt_hash(prompt: str) -> str:
    """Return a SHA-256 hex digest of the prompt for audit / tamper-detection."""
    return hashlib.sha256(prompt.encode()).hexdigest()


def create_commit_message(
    interaction_id: str,
    agent_id: str,
    prompt_hash: str,
    decision_signature: Optional[str] = None,
) -> str:
    """
    Build a structured git commit message that embeds governance metadata.

    The ``interaction_id`` and ``prompt_hash`` fields allow full traceability
    from a git commit back to the originating API call and decision record.
    """
    sig = decision_signature or "placeholder_signature"
    return f"""feat: AI generated code

interaction_id: {interaction_id}
agent_id: {agent_id}
prompt_hash: {prompt_hash}
decision_signature: {sig}"""

def confirm_workspace_path() -> str:
    """Ensure the default workspace root directory exists and return its path."""
    Path(WORKSPACE_ROOT_DEFAULT).mkdir(parents=True, exist_ok=True)
    return WORKSPACE_ROOT_DEFAULT


def _resolve_target_path(workspace_path: str, relative_path: str) -> Optional[Path]:
    """Resolve a payload path safely under the workspace root."""
    root = Path(workspace_path).resolve()
    candidate = (root / (relative_path or "")).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def _is_protected_existing_doc(workspace_root: Path, target_path: Path) -> bool:
    """Protect curated root docs from blind overwrite by agent output."""
    if not target_path.exists() or target_path.is_dir():
        return False

    try:
        relative = target_path.relative_to(workspace_root)
    except ValueError:
        return False

    return len(relative.parts) == 1 and relative.name in PROTECTED_ROOT_DOCS


def write_files(workspace_path: str, files: list) -> Dict[str, Any]:
    """
    Write a list of files to the workspace directory, creating parent dirs as needed.

    Args:
        workspace_path: Absolute path to the workspace root.
        files:          List of dicts with ``path`` (relative) and ``content`` keys.

    Returns:
        One dict per file: ``path`` (as requested), ``status`` (``written``,
        ``skipped_protected`` or ``rejected``) and, for written files,
        ``absolute_path``, ``bytes`` and ``sha256`` of the bytes read back from
        disk after writing — an observation, not an echo of the request.
    """
    results = []
    workspace_root = Path(workspace_path).expanduser()
    if not workspace_root.is_absolute() or not workspace_root.is_dir():
        # The project is not on this machine (wrong host, or the folder was
        # moved): never create it, and say so for every file.
        logger.warning("Workspace %s is not a folder on this machine", workspace_path)
        return [
            {"path": file_info.get("path", ""), "status": "workspace_missing"}
            for file_info in files
        ]
    workspace_root = workspace_root.resolve()
    for file_info in files:
        requested = file_info.get("path", "")
        target_path = _resolve_target_path(workspace_path, requested)
        content = file_info.get("content", "")
        overwrite_existing = bool(file_info.get("overwrite_existing") or file_info.get("safe_replace"))

        if not target_path or target_path == workspace_root:
            results.append({"path": requested, "status": "rejected"})
            logger.warning("Rejected unsafe file path: %s", requested)
            continue

        if _is_protected_existing_doc(workspace_root, target_path) and not overwrite_existing:
            results.append({"path": requested, "status": "skipped_protected", "absolute_path": str(target_path)})
            logger.warning("Skipped protected document overwrite: %s", target_path)
            continue

        os.makedirs(target_path.parent, exist_ok=True)
        with open(target_path, "w", encoding="utf-8", newline="") as f:
            f.write(content)
        on_disk = target_path.read_bytes()
        results.append({
            "path": requested,
            "status": "written",
            "absolute_path": str(target_path),
            "bytes": len(on_disk),
            "sha256": hashlib.sha256(on_disk).hexdigest(),
        })
        logger.info(f"File written: {target_path}")
    return results


def deliver_files(workspace_path: str, files: list) -> Dict[str, Any]:
    """``write_files`` wrapped in the reply shape the backend reads."""
    try:
        write_results = write_files(workspace_path, files)
        return {
            "ok": all(r["status"] == "written" for r in write_results),
            "workspace_root": workspace_path,
            "files": write_results,
        }
    except OSError as e:
        logger.error("Writing files under %s failed: %s", workspace_path, e)
        return {"ok": False, "workspace_root": workspace_path, "files": [], "error": str(e)}


def _delivery_summary(response: Dict[str, Any]) -> str:
    written = [r["path"] for r in response["files"] if r["status"] == "written"]
    others = [f"{r['path']} ({r['status']})" for r in response["files"] if r["status"] != "written"]
    summary = f"📝 Wrote {len(written)} file(s): {', '.join(written) or '—'}"
    if others:
        summary += f"; not written: {', '.join(others)}"
    if response.get("error"):
        summary += f"; error: {response['error']}"
    return summary


async def _publish_glassroom_status(nc, sprint_id, content: str) -> None:
    await nc.publish(f"glassroom.{sprint_id}", json.dumps({
        "agent": "System",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "content": content,
        "type": "status",
    }).encode())


def _build_command_env() -> Dict[str, str]:
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


def _build_shell_command(command: str) -> list[str]:
    """Run commands through the user's shell when available instead of bare /bin/sh."""
    configured_shell = os.getenv("FABRIQUE_EXEC_SHELL")
    if IS_WINDOWS:
        shell_path = configured_shell or os.environ.get("COMSPEC", "cmd.exe")
        if Path(shell_path).stem.lower() in {"powershell", "pwsh"}:
            return [shell_path, "-NoProfile", "-NonInteractive", "-Command", command]
        return [shell_path, "/d", "/s", "/c", command]
    shell_path = configured_shell or ("/bin/zsh" if Path("/bin/zsh").exists() else "/bin/sh")
    if shell_path.endswith("zsh"):
        return [shell_path, "-dfc", command]
    if shell_path.endswith("bash"):
        return [shell_path, "--noprofile", "--norc", "-c", command]
    return [shell_path, "-c", command]


def _is_assistant_command(command: str) -> bool:
    normalized = (command or "").lower()
    return "copilot" in normalized or "claude" in normalized


def _summarize_command_result(command: str, result: Dict[str, Any]) -> str:
    command_preview = " ".join((command or "").strip().split())[:180]
    exit_code = result.get("exit_code", -1)
    output = (result.get("stdout") or result.get("stderr") or result.get("error") or "").strip()
    output_preview = output[:240]

    if result.get("success"):
        return f"Workspace command finished successfully (exit {exit_code}): {command_preview}"

    if output_preview:
        return f"Workspace command failed (exit {exit_code}): {output_preview}"

    return f"Workspace command failed (exit {exit_code}): {command_preview}"

def execute_shell_command(command: str, cwd: str) -> Dict[str, Any]:
    """
    Execute a shell command synchronously and capture all output.

    Inspired by OpenHands' real-execution model: runs the command with a
    120-second timeout, captures both stdout and stderr, and returns the
    exit code so the caller can decide whether execution succeeded.

    Args:
        command: Shell command string (passed to ``shell=True``).
        cwd:     Working directory for the command.

    Returns:
        Dict with keys ``success`` (bool), ``stdout``, ``stderr``,
        ``exit_code`` — or ``{"success": False, "error": ...}`` on exception.
    """
    logger.info(f"Executing: {command} in {cwd}")
    try:
        result = subprocess.run(
            _build_shell_command(command),
            cwd=cwd,
            env=_build_command_env(),
            capture_output=True,
            text=True,
            timeout=120
        )
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.returncode
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

async def handle_msg(nc, msg):
    """
    Unified NATS message handler for ``workspace.generate`` and ``workspace.execute``.

    ``workspace.generate`` flow:
    1. Write all files provided in the payload to the workspace directory.
    2. Reply with the per-file result and post a Glassroom summary.

    ``workspace.execute`` flow:
    1. Run the requested shell command inside the workspace directory.
    2. Publish the command output to the Glassroom NATS subject so the frontend
       SSE stream receives it in real-time.
    3. Optionally reply with the full result dict.

    File writes and commands run in a worker thread, so a long test run does
    not stop this daemon from answering other requests.
    """
    subject = msg.subject
    data = json.loads(msg.data.decode())
    reply_to = msg.reply

    workspace_path = data.get("workspace_root") or confirm_workspace_path()

    if subject == "workspace.generate":
        files = data.get("files", [])
        if not files:
            # Sprint kickoff stories also travel on this subject; they are for
            # the backend's agent graph, not for this daemon.
            return
        response = await asyncio.to_thread(deliver_files, workspace_path, files)
        if reply_to:
            await nc.publish(reply_to, json.dumps(response).encode())

        sprint_id = data.get("sprint_id")
        if sprint_id is not None:
            await _publish_glassroom_status(nc, sprint_id, _delivery_summary(response))

    elif subject == "workspace.execute":
        cmd = data.get("command")
        result = await asyncio.to_thread(execute_shell_command, cmd, workspace_path)

        sprint_id = data.get("sprint_id", "1")
        if not _is_assistant_command(cmd):
            await _publish_glassroom_status(nc, sprint_id, _summarize_command_result(cmd, result))

        if reply_to:
            await nc.publish(reply_to, json.dumps(result).encode())

def _configured_assistant_commands(data: Dict[str, Any]) -> list[str]:
    """Assistant commands to look for: the request's list, else the env default."""
    requested = data.get("commands")
    if isinstance(requested, list) and requested:
        names = [str(name).strip() for name in requested]
    else:
        names = [name.strip() for name in ASSISTANT_COMMANDS_DEFAULT.split(",")]
    # Only bare command names: a path or shell syntax is not an assistant name.
    return [name for name in names if name and os.path.basename(name) == name]


def _has_fallback_binary(name: str) -> bool:
    """Match the host fallback paths the backend's command wrapper also tries."""
    fallback = ASSISTANT_FALLBACK_PATHS.get(name)
    if not fallback:
        return False
    path = os.path.expanduser(fallback)
    return os.path.isfile(path) and os.access(path, os.X_OK)


def detect_assistants(commands: list[str]) -> list[str]:
    """Return the assistant commands found on the PATH used for command execution."""
    search_path = _build_command_env().get("PATH")
    return [
        name
        for name in commands
        if shutil.which(name, path=search_path) or _has_fallback_binary(name)
    ]


async def handle_capabilities(nc, msg):
    """
    Reply to ``workspace.capabilities`` with the console assistants this host has.

    Reply body: ``{"assistants": [<command names found via shutil.which>]}``.
    The backend asks once when its workers start and skips console assistants
    entirely when the list is empty.
    """
    try:
        data = json.loads(msg.data.decode() or "{}")
    except (ValueError, UnicodeDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    response = {"assistants": detect_assistants(_configured_assistant_commands(data))}
    logger.info(f"Capabilities: {response}")
    if msg.reply:
        await nc.publish(msg.reply, json.dumps(response).encode())


# ---------------------------------------------------------------------------
# This machine: identity, folder browsing, project inspection
# ---------------------------------------------------------------------------


def host_info() -> Dict[str, Any]:
    """Which machine answered: the backend shows it next to host paths."""
    return {
        "hostname": platform.node() or "unknown",
        "platform": sys.platform,
        "home": str(Path.home()),
        "sep": os.sep,
    }


class WorkspaceError(Exception):
    """A folder request that cannot be served; ``status`` follows HTTP."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


# Folders never offered in the picker (dependencies, build output, VCS data).
BROWSE_SKIP_DIRS = {
    "node_modules", "__pycache__", "venv", "env", "dist", "build", "coverage",
    "target", "vendor", "$RECYCLE.BIN", "System Volume Information",
}
BROWSE_MAX_ENTRIES = 500
# Common places people clone repositories, offered as shortcuts when present.
CLONE_FOLDERS = (
    "code", "Code", "projects", "Projects", "src", "dev", "Developer", "repos",
    "git", "GitHub", "workspace", "workspaces", "Documents/GitHub",
    "Documents/GitLab", "source/repos", "IdeaProjects", "PycharmProjects",
    "WebstormProjects",
)


def _host_path(path: str) -> Path:
    """An absolute path on this machine, with ``~`` expanded."""
    candidate = Path(os.path.expanduser(path.strip()))
    if not candidate.is_absolute():
        raise WorkspaceError(400, f"Not an absolute path on this machine: {path}")
    return candidate


def _is_hidden(entry: os.DirEntry) -> bool:
    if entry.name.startswith("."):
        return True
    if IS_WINDOWS:
        try:
            attributes = entry.stat().st_file_attributes
        except OSError:
            return True
        return bool(attributes & (stat.FILE_ATTRIBUTE_HIDDEN | stat.FILE_ATTRIBUTE_SYSTEM))
    return False


def filesystem_roots() -> List[Dict[str, str]]:
    if IS_WINDOWS:
        drives = [f"{letter}:\\" for letter in string.ascii_uppercase]
        return [{"name": d, "path": d} for d in drives if os.path.isdir(d)]
    return [{"name": "/", "path": "/"}]


def clone_shortcuts() -> List[Dict[str, str]]:
    home = Path.home()
    shortcuts = [{"name": "Home", "path": str(home)}]
    seen = {str(home).lower() if IS_WINDOWS else str(home)}
    for relative in CLONE_FOLDERS:
        folder = home / relative
        key = str(folder).lower() if IS_WINDOWS else str(folder)
        if key not in seen and folder.is_dir():
            seen.add(key)
            shortcuts.append({"name": relative, "path": str(folder)})
    return shortcuts


def browse(path: Optional[str] = None) -> Dict[str, Any]:
    """The sub-folders of *path* (default: the home folder) on this machine."""
    target = _host_path(path).resolve() if path else Path.home()
    if not target.is_dir():
        raise WorkspaceError(404, f"Folder not found on {host_info()['hostname']}: {target}")
    entries = []
    truncated = False
    try:
        with os.scandir(target) as it:
            for entry in it:
                if entry.name in BROWSE_SKIP_DIRS or _is_hidden(entry):
                    continue
                try:
                    if not entry.is_dir():
                        continue
                except OSError:
                    continue
                if len(entries) >= BROWSE_MAX_ENTRIES:
                    truncated = True
                    break
                entries.append({
                    "name": entry.name,
                    "path": entry.path,
                    "is_git": os.path.exists(os.path.join(entry.path, ".git")),
                })
    except PermissionError:
        raise WorkspaceError(403, f"Permission denied: {target}")
    entries.sort(key=lambda e: e["name"].lower())
    parent = target.parent
    return {
        "host": host_info(),
        "path": str(target),
        "parent": str(parent) if parent != target else None,
        "entries": entries,
        "shortcuts": clone_shortcuts(),
        "roots": filesystem_roots(),
        "truncated": truncated,
    }


def _git_dir(root: Path) -> Optional[Path]:
    """The repository's git directory: ``.git`` itself, or where a ``.git`` file points."""
    dot_git = root / ".git"
    if dot_git.is_dir():
        return dot_git
    if dot_git.is_file():
        try:
            line = dot_git.read_text(encoding="utf-8", errors="ignore").strip()
        except OSError:
            return None
        if line.startswith("gitdir:"):
            git_dir = Path(line[len("gitdir:"):].strip())
            return git_dir if git_dir.is_absolute() else (root / git_dir).resolve()
    return None


def _strip_credentials(url: str) -> str:
    """Drop a password or token embedded in a remote URL (``https://TOKEN@host/...``)."""
    if "://" not in url:
        return url
    parts = urlsplit(url)
    if "@" not in parts.netloc:
        return url
    userinfo, host_port = parts.netloc.rsplit("@", 1)
    if ":" in userinfo or parts.scheme in {"http", "https"}:
        return parts._replace(netloc=host_port).geturl()
    # ssh://git@host/... names the login user, not a secret.
    return url


def remote_web_url(remote_url: Optional[str]) -> tuple:
    """``(provider, web_url)`` for a git remote: github, gitlab, bitbucket or other."""
    if not remote_url:
        return None, None
    url = remote_url.strip()
    if "://" in url:
        parts = urlsplit(url)
        host, path = parts.hostname or "", parts.path
    elif ":" in url:
        # scp-like syntax: git@github.com:owner/repo.git
        host, path = url.split(":", 1)
        host = host.split("@")[-1]
    else:
        return "other", None
    path = path.strip("/")
    if path.endswith(".git"):
        path = path[: -len(".git")]
    host = host.lower()
    if host == "github.com" or host.endswith(".github.com"):
        provider = "github"
    elif "gitlab" in host:
        provider = "gitlab"
    elif "bitbucket" in host:
        provider = "bitbucket"
    else:
        provider = "other"
    return provider, (f"https://{host}/{path}" if host and path else None)


def git_info(root: Path) -> Dict[str, Any]:
    """Branch and origin of the repository at *root*, read from its git files."""
    info: Dict[str, Any] = {
        "is_repo": False, "branch": None, "remote_url": None, "provider": None, "web_url": None,
    }
    git_dir = _git_dir(root)
    if git_dir is None:
        return info
    info["is_repo"] = True
    try:
        head = (git_dir / "HEAD").read_text(encoding="utf-8", errors="ignore").strip()
        if head.startswith("ref: refs/heads/"):
            info["branch"] = head[len("ref: refs/heads/"):]
    except OSError:
        pass
    # Linked worktrees keep the shared config in the main repository.
    common_dir = git_dir
    commondir_file = git_dir / "commondir"
    if commondir_file.is_file():
        try:
            common = Path(commondir_file.read_text(encoding="utf-8").strip())
            common_dir = common if common.is_absolute() else (git_dir / common).resolve()
        except OSError:
            pass
    config = configparser.ConfigParser(strict=False, interpolation=None)
    try:
        config.read(common_dir / "config", encoding="utf-8")
    except (configparser.Error, OSError):
        return info
    remotes = [section for section in config.sections() if section.startswith('remote "')]
    preferred = 'remote "origin"' if 'remote "origin"' in remotes else (remotes[0] if remotes else None)
    if preferred and config.has_option(preferred, "url"):
        remote = _strip_credentials(config.get(preferred, "url"))
        info["remote_url"] = remote
        info["provider"], info["web_url"] = remote_web_url(remote)
    return info


# What the backend's stack detection reads.  Paths are listed for every file;
# contents only for these build/config files.  ``.env`` is never sent.
SNAPSHOT_SKIP_DIRS = {
    ".git", ".svn", "node_modules", "__pycache__", ".venv", "venv", "env", "dist",
    "build", ".next", ".nuxt", "target", ".gradle", ".idea", ".vscode", "coverage",
    ".pytest_cache", ".mypy_cache", "vendor",
}
SNAPSHOT_KEY_FILES = {
    "package.json", "pyproject.toml", "requirements.txt", "setup.cfg", "pytest.ini",
    "pom.xml", "build.gradle", "build.gradle.kts", "Gemfile", "go.mod",
    "docker-compose.yml", "docker-compose.yaml", ".env.example", "application.yml",
    "application.properties", "database.yml", "Chart.yaml",
    "README.md", "README.rst", "README.txt", "README",
}
SNAPSHOT_MAX_FILES = 5000
SNAPSHOT_MAX_DEPTH_FOR_CONTENT = 3
SNAPSHOT_MAX_FILE_BYTES = 64 * 1024
SNAPSHOT_MAX_TOTAL_BYTES = 400 * 1024


def _wants_content(relative: str, name: str, depth: int) -> bool:
    if name in SNAPSHOT_KEY_FILES:
        return depth <= SNAPSHOT_MAX_DEPTH_FOR_CONTENT
    lowered = relative.lower()
    return name.endswith((".yaml", ".yml")) and ("k8s" in lowered or "kubernetes" in lowered)


def project_snapshot(root: Path) -> Dict[str, Any]:
    """Relative paths of the project's files plus the text of its config files."""
    files: List[str] = []
    contents: Dict[str, str] = {}
    total = 0
    truncated = False
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SNAPSHOT_SKIP_DIRS)
        rel_dir = Path(dirpath).relative_to(root)
        depth = len(rel_dir.parts)
        for name in sorted(filenames):
            relative = (rel_dir / name).as_posix()
            files.append(relative)
            if _wants_content(relative, name, depth) and total < SNAPSHOT_MAX_TOTAL_BYTES:
                try:
                    with open(os.path.join(dirpath, name), "rb") as fh:
                        raw = fh.read(SNAPSHOT_MAX_FILE_BYTES)
                except OSError:
                    raw = b""
                text = raw.decode("utf-8", errors="ignore")
                if name.startswith("README"):
                    text = text[:2000]
                contents[relative] = text
                total += len(text)
            if len(files) >= SNAPSHOT_MAX_FILES:
                truncated = True
                break
        if truncated:
            break
    return {"files": files, "contents": contents, "truncated": truncated}


def inspect_project(path: str, with_snapshot: bool = False) -> Dict[str, Any]:
    """Whether *path* is a folder on this machine, and what repository it holds."""
    candidate = _host_path(path)
    try:
        resolved = candidate.resolve()
    except OSError:
        resolved = candidate
    is_dir = resolved.is_dir()
    result: Dict[str, Any] = {
        "host": host_info(),
        "path": str(resolved),
        "name": resolved.name or str(resolved),
        "exists": resolved.exists(),
        "is_dir": is_dir,
        "git": git_info(resolved) if is_dir else None,
    }
    if with_snapshot and is_dir:
        result["snapshot"] = project_snapshot(resolved)
    return result


async def _reply(nc, msg, body: Dict[str, Any]) -> None:
    if msg.reply:
        await nc.publish(msg.reply, json.dumps(body).encode())


def _request_body(msg) -> Dict[str, Any]:
    try:
        data = json.loads(msg.data.decode() or "{}")
    except (ValueError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


async def handle_browse(nc, msg):
    """``workspace.browse`` → the folder listing, or ``{"error": {status, message}}``."""
    data = _request_body(msg)
    try:
        body = await asyncio.to_thread(browse, data.get("path") or None)
    except WorkspaceError as e:
        body = {"error": {"status": e.status, "message": e.message}}
    await _reply(nc, msg, body)


async def handle_inspect(nc, msg):
    """``workspace.inspect`` → folder, git and (when asked) file snapshot."""
    data = _request_body(msg)
    path = data.get("path")
    if not isinstance(path, str) or not path.strip():
        body = {"error": {"status": 400, "message": "A folder path is required."}}
    else:
        try:
            body = await asyncio.to_thread(inspect_project, path, bool(data.get("snapshot")))
        except WorkspaceError as e:
            body = {"error": {"status": e.status, "message": e.message}}
    await _reply(nc, msg, body)


async def handle_status(nc, msg, jetstream: bool = False):
    await _reply(nc, msg, {"host": host_info(), "version": DAEMON_VERSION, "jetstream": jetstream})


# ---------------------------------------------------------------------------
# Deliveries queued while this daemon was offline (JetStream)
# ---------------------------------------------------------------------------


async def ensure_delivery_streams(js) -> None:
    from nats.js import api
    from nats.js.errors import NotFoundError

    for name, subject in DELIVERY_STREAMS.items():
        try:
            await js.stream_info(name)
        except NotFoundError:
            await js.add_stream(api.StreamConfig(
                name=name,
                subjects=[subject],
                retention=api.RetentionPolicy.WORK_QUEUE,
                storage=api.StorageType.FILE,
                max_age=STREAM_MAX_AGE_SECONDS,
                duplicate_window=STREAM_DUPLICATE_WINDOW_SECONDS,
            ))


async def process_queued_delivery(nc, js, msg) -> None:
    """Write one queued delivery and report the result on ``workspace.delivered``."""
    try:
        job = json.loads(msg.data.decode())
    except (ValueError, UnicodeDecodeError):
        logger.error("Discarding malformed queued delivery")
        await msg.term()
        return
    workspace_path = job.get("workspace_root") or ""
    response = await asyncio.to_thread(deliver_files, workspace_path, job.get("files") or [])
    result = {
        **response,
        "job_id": job.get("job_id"),
        "company_id": job.get("company_id"),
        "sprint_id": job.get("sprint_id"),
        "item_id": job.get("item_id"),
        "host": host_info(),
    }
    try:
        await js.publish(
            DELIVERED_SUBJECT,
            json.dumps(result).encode(),
            headers={"Nats-Msg-Id": f"delivered-{job.get('job_id')}"},
        )
    except Exception as e:  # noqa: BLE001 - Retry the job; writing again is idempotent.
        logger.warning("Could not report queued delivery %s (%s); will retry", job.get("job_id"), e)
        await msg.nak(delay=10)
        return
    await msg.ack()
    logger.info("Queued delivery %s: %s", job.get("job_id"), _delivery_summary(response))
    if job.get("sprint_id") is not None:
        await _publish_glassroom_status(nc, job["sprint_id"], f"{_delivery_summary(response)} (queued delivery)")


async def consume_queued_deliveries(nc, js) -> None:
    from nats.js import api

    psub = await js.pull_subscribe(
        DELIVER_SUBJECT,
        durable=DELIVERY_CONSUMER,
        stream="FABRIQUE_DELIVERIES",
        config=api.ConsumerConfig(
            durable_name=DELIVERY_CONSUMER,
            deliver_policy=api.DeliverPolicy.ALL,
            ack_policy=api.AckPolicy.EXPLICIT,
            ack_wait=120,
            max_deliver=10,
            filter_subject=DELIVER_SUBJECT,
        ),
    )
    while True:
        try:
            msgs = await psub.fetch(1, timeout=5)
        except (NATSTimeoutError, asyncio.TimeoutError):
            continue
        except Exception as e:  # noqa: BLE001 - Keep consuming across reconnects.
            logger.warning("Fetching queued deliveries failed (%s); retrying", e)
            await asyncio.sleep(2)
            continue
        for msg in msgs:
            await process_queued_delivery(nc, js, msg)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def connect_with_retry():
    """Connect to NATS, waiting for it if the backend stack is not up yet."""
    delay = 1.0
    while True:
        try:
            return await nats.connect(
                NATS_URL,
                name=f"fabrique-daemon@{platform.node()}",
                max_reconnect_attempts=-1,
                reconnect_time_wait=2,
            )
        except Exception as e:  # noqa: BLE001 - Keep waiting for the broker.
            logger.warning("NATS at %s unavailable (%s); retrying in %.0fs", NATS_URL, e, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)


async def main():
    logger.info(f"Connecting to NATS at {NATS_URL}...")
    nc = await connect_with_retry()
    host = host_info()

    jetstream = False
    consumer = None
    try:
        js = nc.jetstream()
        await ensure_delivery_streams(js)
        consumer = asyncio.create_task(consume_queued_deliveries(nc, js))
        jetstream = True
    except Exception as e:  # noqa: BLE001 - Without JetStream only live requests are served.
        logger.warning("JetStream unavailable (%s); queued deliveries are not processed", e)

    async def _callback(msg):
        await handle_msg(nc, msg)

    async def _capabilities_callback(msg):
        await handle_capabilities(nc, msg)

    async def _status_callback(msg):
        await handle_status(nc, msg, jetstream)

    async def _browse_callback(msg):
        await handle_browse(nc, msg)

    async def _inspect_callback(msg):
        await handle_inspect(nc, msg)

    for subject, callback in (
        ("workspace.generate", _callback),
        ("workspace.execute", _callback),
        ("workspace.capabilities", _capabilities_callback),
        ("workspace.status", _status_callback),
        ("workspace.browse", _browse_callback),
        ("workspace.inspect", _inspect_callback),
    ):
        await nc.subscribe(subject, queue=QUEUE_GROUP, cb=callback)

    logger.info(
        "Daemon ready on %s (%s), home %s; JetStream %s.",
        host["hostname"], host["platform"], host["home"], "on" if jetstream else "off",
    )
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        if consumer:
            consumer.cancel()
        await nc.drain()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
