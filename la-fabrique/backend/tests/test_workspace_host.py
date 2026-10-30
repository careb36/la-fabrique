"""
Projects on the developer's own machine (macOS, Linux or Windows).

The workspace daemon runs there and is the only component that reads that
machine's folders; the backend relays the folder picker, the project check
and the stack scan to it.  The daemon is the real ``vscode-daemon/daemon.py``
running against ``tmp_path``; NATS is an in-process fake that calls it.
"""

import asyncio
import importlib.util
import json
from pathlib import Path

import pytest
from models.company import Company, ProjectDiscovery
from services import task_worker, workspace_daemon
from sqlmodel import select

_DAEMON_PATH = Path(__file__).resolve().parents[2] / "vscode-daemon" / "daemon.py"


@pytest.fixture(scope="module")
def daemon():
    spec = importlib.util.spec_from_file_location("fabrique_daemon_host", _DAEMON_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git_repo(root: Path, remote: str | None, branch: str = "main") -> Path:
    git = root / ".git"
    git.mkdir(parents=True)
    (git / "HEAD").write_text(f"ref: refs/heads/{branch}\n")
    config = "[core]\n\trepositoryformatversion = 0\n"
    if remote:
        config += f'[remote "origin"]\n\turl = {remote}\n'
    (git / "config").write_text(config)
    return root


# ---------------------------------------------------------------------------
# Daemon: folder browsing
# ---------------------------------------------------------------------------


def test_browse_lists_subfolders_with_their_own_paths(daemon, tmp_path):
    _git_repo(tmp_path / "app", "git@github.com:ana/app.git")
    (tmp_path / "notes").mkdir()
    (tmp_path / "node_modules").mkdir()
    (tmp_path / ".cache").mkdir()
    (tmp_path / "file.txt").write_text("x")

    listing = daemon.browse(str(tmp_path))

    assert listing["path"] == str(tmp_path.resolve())
    assert listing["parent"] == str(tmp_path.resolve().parent)
    assert listing["entries"] == [
        {"name": "app", "path": str(tmp_path.resolve() / "app"), "is_git": True},
        {"name": "notes", "path": str(tmp_path.resolve() / "notes"), "is_git": False},
    ]
    assert listing["host"]["home"] == str(Path.home())
    assert listing["roots"]
    assert listing["shortcuts"][0] == {"name": "Home", "path": str(Path.home())}


def test_browse_without_a_path_starts_at_home(daemon):
    assert daemon.browse(None)["path"] == str(Path.home())


def test_browse_missing_or_relative_folder_is_an_error(daemon, tmp_path):
    with pytest.raises(daemon.WorkspaceError) as missing:
        daemon.browse(str(tmp_path / "nope"))
    with pytest.raises(daemon.WorkspaceError) as relative:
        daemon.browse("projects/app")
    assert missing.value.status == 404
    assert relative.value.status == 400


def test_windows_drives_are_offered_as_roots(daemon, monkeypatch):
    monkeypatch.setattr(daemon, "IS_WINDOWS", True)
    monkeypatch.setattr(
        daemon.os.path, "isdir", lambda p: p in {"C:\\", "D:\\"}, raising=True
    )

    assert daemon.filesystem_roots() == [
        {"name": "C:\\", "path": "C:\\"},
        {"name": "D:\\", "path": "D:\\"},
    ]


# ---------------------------------------------------------------------------
# Daemon: project inspection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("remote", "provider", "web_url"),
    [
        (
            "git@github.com:careb36/la-fabrique.git",
            "github",
            "https://github.com/careb36/la-fabrique",
        ),
        (
            "https://gitlab.com/group/sub/app.git",
            "gitlab",
            "https://gitlab.com/group/sub/app",
        ),
        (
            "ssh://git@gitlab.example.com:2222/team/app.git",
            "gitlab",
            "https://gitlab.example.com/team/app",
        ),
        (
            "https://bitbucket.org/team/app.git",
            "bitbucket",
            "https://bitbucket.org/team/app",
        ),
        (
            "git@git.example.com:team/app.git",
            "other",
            "https://git.example.com/team/app",
        ),
    ],
)
def test_inspect_reads_the_clone_origin(daemon, tmp_path, remote, provider, web_url):
    _git_repo(tmp_path / "app", remote, branch="feature/x")

    project = daemon.inspect_project(str(tmp_path / "app"))

    assert project["exists"] and project["is_dir"]
    assert project["name"] == "app"
    assert project["git"] == {
        "is_repo": True,
        "branch": "feature/x",
        "remote_url": remote,
        "provider": provider,
        "web_url": web_url,
    }


def test_inspect_never_returns_a_token_from_the_remote(daemon, tmp_path):
    _git_repo(tmp_path / "app", "https://ghp_SECRET@github.com/ana/app.git")

    git = daemon.inspect_project(str(tmp_path / "app"))["git"]

    assert "SECRET" not in json.dumps(git)
    assert git["remote_url"] == "https://github.com/ana/app.git"
    assert git["web_url"] == "https://github.com/ana/app"


def test_inspect_follows_a_worktree_git_file(daemon, tmp_path):
    main = _git_repo(tmp_path / "main", "git@gitlab.com:team/app.git")
    worktree_git = main / ".git" / "worktrees" / "wt"
    worktree_git.mkdir(parents=True)
    (worktree_git / "HEAD").write_text("ref: refs/heads/wt-branch\n")
    (worktree_git / "commondir").write_text("../..\n")
    (tmp_path / "wt").mkdir()
    (tmp_path / "wt" / ".git").write_text(f"gitdir: {worktree_git}\n")

    git = daemon.inspect_project(str(tmp_path / "wt"))["git"]

    assert git["branch"] == "wt-branch"
    assert git["provider"] == "gitlab"


def test_inspect_plain_and_missing_folders(daemon, tmp_path):
    (tmp_path / "plain").mkdir()

    plain = daemon.inspect_project(str(tmp_path / "plain"))
    missing = daemon.inspect_project(str(tmp_path / "gone"))

    assert plain["git"]["is_repo"] is False
    assert missing["exists"] is False
    assert missing["git"] is None


def test_snapshot_lists_files_and_sends_config_text_but_never_env(daemon, tmp_path):
    root = tmp_path / "app"
    (root / "src").mkdir(parents=True)
    (root / "node_modules" / "x").mkdir(parents=True)
    (root / "package.json").write_text('{"dependencies": {"react": "18"}}')
    (root / "src" / "main.tsx").write_text("export {}")
    (root / ".env").write_text("DATABASE_PASSWORD=hunter2")
    (root / "node_modules" / "x" / "index.js").write_text("x")

    snapshot = daemon.inspect_project(str(root), with_snapshot=True)["snapshot"]

    assert set(snapshot["files"]) == {"package.json", "src/main.tsx", ".env"}
    assert snapshot["contents"] == {"package.json": '{"dependencies": {"react": "18"}}'}
    assert "hunter2" not in json.dumps(snapshot)


# ---------------------------------------------------------------------------
# Daemon: writing and running on the user's machine
# ---------------------------------------------------------------------------


def test_files_are_never_written_to_a_folder_that_is_not_on_this_machine(
    daemon, tmp_path
):
    elsewhere = tmp_path / "not-here"

    results = daemon.write_files(str(elsewhere), [{"path": "a.py", "content": "x"}])
    relative = daemon.write_files(
        "C:\\Users\\ana\\app", [{"path": "a.py", "content": "x"}]
    )

    assert results == [{"path": "a.py", "status": "workspace_missing"}]
    assert relative == [{"path": "a.py", "status": "workspace_missing"}]
    assert not elsewhere.exists()
    assert not Path("C:\\Users\\ana\\app").exists()


def test_commands_run_through_cmd_on_windows(daemon, monkeypatch):
    monkeypatch.setattr(daemon, "IS_WINDOWS", True)
    monkeypatch.delenv("FABRIQUE_EXEC_SHELL", raising=False)
    monkeypatch.setenv("COMSPEC", "C:\\Windows\\system32\\cmd.exe")

    assert daemon._build_shell_command("npm test") == [
        "C:\\Windows\\system32\\cmd.exe",
        "/d",
        "/s",
        "/c",
        "npm test",
    ]
    monkeypatch.setenv("FABRIQUE_EXEC_SHELL", "pwsh")
    assert daemon._build_shell_command("npm test")[:2] == ["pwsh", "-NoProfile"]


# ---------------------------------------------------------------------------
# Backend relay
# ---------------------------------------------------------------------------


class _DaemonNATS:
    """Fake NATS whose requests are answered by the real daemon functions."""

    def __init__(self, daemon):
        self.daemon = daemon
        self.subjects = []

    async def request(self, subject, payload, timeout=5.0):
        self.subjects.append(subject)
        try:
            if subject == "workspace.status":
                return {"host": self.daemon.host_info(), "jetstream": True}
            if subject == "workspace.browse":
                return self.daemon.browse(payload.get("path"))
            if subject == "workspace.inspect":
                return self.daemon.inspect_project(
                    payload["path"], bool(payload.get("snapshot"))
                )
        except self.daemon.WorkspaceError as e:
            return {"error": {"status": e.status, "message": e.message}}
        raise AssertionError(subject)

    async def close(self):
        pass


class NoRespondersError(Exception):
    """Named like nats-py's: NATS says nobody listens on the subject."""


class _NoDaemonNATS:
    async def request(self, subject, payload, timeout=5.0):
        raise NoRespondersError("nats: no responders available for request")

    async def close(self):
        pass


class _SilentNATS:
    """A subscriber exists but nothing answers in time."""

    async def request(self, subject, payload, timeout=5.0):
        raise TimeoutError("nats: timeout")

    async def close(self):
        pass


class _ErrorReplyNATS:
    async def request(self, subject, payload, timeout=5.0):
        return {"error": {"status": 500, "message": "disk full"}}

    async def close(self):
        pass


def _with_nats(test_client, nats):
    test_client.app.state.nats_client = nats
    return test_client


def test_status_reports_the_daemon_machine(test_client, daemon):
    connected = _with_nats(test_client, _DaemonNATS(daemon)).get("/v1/workspace/status")
    absent = _with_nats(test_client, _NoDaemonNATS()).get("/v1/workspace/status")

    assert connected.status_code == 200
    assert connected.json()["connected"] is True
    assert connected.json()["host"]["home"] == str(Path.home())
    assert connected.json()["state"] == "connected"
    assert absent.json() == {
        "connected": False,
        "state": "absent",
        "reason": "no daemon is listening",
        "host": None,
        "jetstream": False,
    }


def test_status_says_unknown_when_it_cannot_tell(test_client):
    """Unknown is not absent: no NATS, no answer in time or an error reply."""
    silent = _with_nats(test_client, _SilentNATS()).get("/v1/workspace/status").json()
    erroring = (
        _with_nats(test_client, _ErrorReplyNATS()).get("/v1/workspace/status").json()
    )
    no_nats = _with_nats(test_client, None).get("/v1/workspace/status").json()
    _with_nats(
        test_client, _SilentNATS()
    )  # the app's shutdown closes whatever is there

    assert (silent["state"], silent["connected"]) == ("unknown", False)
    assert silent["reason"].startswith("no answer within")
    assert erroring["state"] == "unknown"
    assert erroring["reason"] == "the daemon answered with an error: disk full"
    assert no_nats["state"] == "unknown"
    assert no_nats["reason"] == "the backend is not connected to NATS"


def test_browse_relays_the_daemon_listing_and_its_errors(test_client, daemon, tmp_path):
    (tmp_path / "repo").mkdir()
    client = _with_nats(test_client, _DaemonNATS(daemon))

    listing = client.get("/v1/workspace/browse", params={"path": str(tmp_path)})
    missing = client.get("/v1/workspace/browse", params={"path": str(tmp_path / "x")})
    offline = _with_nats(test_client, _NoDaemonNATS()).get("/v1/workspace/browse")

    assert listing.status_code == 200
    assert [e["name"] for e in listing.json()["entries"]] == ["repo"]
    assert missing.status_code == 404
    assert "Folder not found" in missing.json()["detail"]
    assert offline.status_code == 503
    assert "start-daemon" in offline.json()["detail"]


def test_inspect_endpoint_never_returns_the_file_snapshot(
    test_client, daemon, tmp_path
):
    _git_repo(tmp_path / "app", "git@github.com:ana/app.git")
    client = _with_nats(test_client, _DaemonNATS(daemon))

    response = client.get(
        "/v1/workspace/inspect", params={"path": str(tmp_path / "app")}
    )

    assert response.status_code == 200
    assert response.json()["git"]["provider"] == "github"
    assert "snapshot" not in response.json()


def test_discovery_scans_the_daemon_snapshot_and_records_the_host_path(
    test_client, sqlite_session, daemon, tmp_path, monkeypatch
):
    ProjectDiscovery.__table__.create(sqlite_session.get_bind(), checkfirst=True)
    monkeypatch.setattr(
        "services.discovery_service._ai_suggest_team", lambda *a, **k: None
    )
    project = _git_repo(tmp_path / "shop", "git@gitlab.com:team/shop.git")
    (project / "web").mkdir()
    (project / "web" / "package.json").write_text(
        '{"dependencies": {"react": "18", "vite": "5"}}'
    )
    for name in ("a", "b", "c"):
        (project / "web" / f"{name}.tsx").write_text("export {}")
    company = Company(company_name="Shop Corp")
    sqlite_session.add(company)
    sqlite_session.commit()
    nats = _DaemonNATS(daemon)

    response = _with_nats(test_client, nats).post(
        "/v1/discover_team",
        json={"company_id": company.id, "project_path": str(project)},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert "workspace.inspect" in nats.subjects
    assert body["project_path"] == str(project.resolve())
    assert body["project"]["git"]["provider"] == "gitlab"
    assert "snapshot" not in body["project"]
    assert body["detected_stack"]["name"] == "shop"
    assert body["detected_stack"]["language"] == "TypeScript"
    assert {"React", "Vite"} <= set(body["detected_stack"]["frameworks"])
    stored = sqlite_session.exec(
        select(ProjectDiscovery).where(ProjectDiscovery.company_id == company.id)
    ).first()
    assert stored.project_path == str(project.resolve())


def test_discovery_of_a_folder_missing_on_the_daemon_machine(
    test_client, daemon, tmp_path
):
    response = _with_nats(test_client, _DaemonNATS(daemon)).post(
        "/v1/discover_team",
        json={"company_id": None, "project_path": str(tmp_path / "gone")},
    )

    assert response.status_code == 422
    assert "Folder not found on" in response.json()["detail"]


def test_discovery_without_daemon_explains_how_to_start_it(test_client):
    response = _with_nats(test_client, _NoDaemonNATS()).post(
        "/v1/discover_team",
        json={"company_id": None, "project_path": "C:\\Users\\ana\\source\\repos\\app"},
    )

    assert response.status_code == 503
    assert "start-daemon.ps1" in response.json()["detail"]


def test_snapshot_mirror_ignores_paths_that_escape_it(tmp_path):
    snapshot = {
        "files": ["ok.txt", "../escape.txt", "/etc/passwd", "a/../../b.txt"],
        "contents": {"ok.txt": "hi"},
    }

    with workspace_daemon.materialized_snapshot(snapshot) as mirror:
        written = sorted(
            str(p.relative_to(mirror)) for p in Path(mirror).rglob("*") if p.is_file()
        )
        assert written == ["ok.txt"]
        assert (Path(mirror) / "ok.txt").read_text() == "hi"


def test_delivery_tests_are_detected_on_the_daemon_machine(
    daemon, tmp_path, monkeypatch
):
    from config import settings

    monkeypatch.setattr(settings, "DELIVERY_TEST_COMMAND", "")
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    nats = _DaemonNATS(daemon)

    command = asyncio.run(task_worker._detect_project_test_command(nats, str(tmp_path)))

    assert command == "python -m pytest -q"
    assert nats.subjects == ["workspace.inspect"]
