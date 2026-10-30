"""
Tests for how the task worker turns an agent's answer into files in the
company's project, and how that delivery is confirmed and recorded (#101).

The daemon is exercised for real (``vscode-daemon/daemon.py`` imported by
path) against ``tmp_path``; NATS and the LLM are replaced by in-process fakes.
"""

import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
from models.agent_run import AgentRun, Verification
from models.company import Company, ProjectDiscovery
from models.sprint import BacklogItem, Sprint
from services import task_worker
from services.verification import check_files_written
from sqlmodel import Session, select

_DAEMON_PATH = Path(__file__).resolve().parents[2] / "vscode-daemon" / "daemon.py"


def _load_daemon():
    spec = importlib.util.spec_from_file_location("fabrique_daemon", _DAEMON_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


TWO_FILE_ANSWER = """I added the login handler and its test.

```python path=src/auth/login.py
def login(user, password):
    return user == "admin" and password == "secret"
```

```python path=tests/test_login.py
from src.auth.login import login


def test_login_rejects_wrong_password():
    assert not login("admin", "nope")
```

Both files are complete.
"""


# ---------------------------------------------------------------------------
# parse_file_manifest
# ---------------------------------------------------------------------------


def test_manifest_gives_each_file_its_own_content():
    files = task_worker.parse_file_manifest(TWO_FILE_ANSWER)

    assert [f["path"] for f in files] == ["src/auth/login.py", "tests/test_login.py"]
    assert files[0]["content"].startswith("def login(user, password):")
    assert "test_login_rejects_wrong_password" not in files[0]["content"]
    assert files[1]["content"].startswith("from src.auth.login import login")
    assert "def login(user" not in files[1]["content"]


def test_manifest_accepts_blocks_without_language_and_quoted_paths():
    answer = (
        "```path=docs/notes.md\n# Notes\n```\n\n"
        '```json path="config/app settings.json"\n{"a": 1}\n```\n'
    )

    files = task_worker.parse_file_manifest(answer)

    assert files == [
        {"path": "docs/notes.md", "content": "# Notes\n"},
        {"path": "config/app settings.json", "content": '{"a": 1}\n'},
    ]


def test_manifest_drops_unsafe_paths_and_disallowed_extensions():
    answer = (
        "```python path=../escape.py\nx = 1\n```\n"
        "```python path=/etc/passwd.py\nx = 2\n```\n"
        "```text path=tools/run.exe\nbinary\n```\n"
        "```python path=ok/module.py\nx = 3\n```\n"
    )

    files = task_worker.parse_file_manifest(answer)

    assert [f["path"] for f in files] == ["ok/module.py"]


def test_manifest_ignores_plain_code_blocks_and_last_duplicate_wins():
    answer = (
        "```python\nprint('example only')\n```\n"
        "```python path=app.py\nv = 1\n```\n"
        "```python path=app.py\nv = 2\n```\n"
    )

    files = task_worker.parse_file_manifest(answer)

    assert files == [{"path": "app.py", "content": "v = 2\n"}]


def test_manifest_empty_when_no_files_declared():
    assert task_worker.parse_file_manifest("Just prose.\n```python\nx = 1\n```") == []
    assert task_worker.parse_file_manifest("") == []


def test_prompt_asks_for_the_file_manifest(monkeypatch):
    captured = {}

    class _Client:
        def __init__(self, base_url):
            self.timeout = None

        def chat(self, messages, model, role):
            captured["prompt"] = messages[1]["content"]
            return {"choices": [{"message": {"content": "done"}}]}

    monkeypatch.setattr(task_worker, "LLMProxyClient", _Client)

    task_worker._execute_task(
        {"id": 1, "title": "Implement login"}, {"role": "Developer"}, "Sprint 1"
    )

    assert "path=src/example/module.py" in captured["prompt"]


# ---------------------------------------------------------------------------
# Workspace root
# ---------------------------------------------------------------------------


@pytest.fixture()
def db(monkeypatch, sqlite_session):
    bind = sqlite_session.get_bind()
    ProjectDiscovery.__table__.create(bind, checkfirst=True)
    monkeypatch.setattr(task_worker, "engine", bind)
    return sqlite_session


def _company(session: Session, name: str = "Delivery Corp") -> Company:
    company = Company(company_name=name, autonomy_level=2)
    session.add(company)
    session.commit()
    session.refresh(company)
    return company


def test_discovered_project_wins_over_the_env_workspace(db, monkeypatch, tmp_path):
    company = _company(db)
    db.add(ProjectDiscovery(company_id=company.id, project_path=str(tmp_path)))
    db.commit()
    monkeypatch.setenv("AGENT_WORKSPACE_ROOT", "/workspace")

    assert task_worker._resolve_workspace_root(company.id) == str(tmp_path)


def test_env_workspace_is_the_fallback(db, monkeypatch):
    company = _company(db, "No discovery Corp")
    monkeypatch.setenv("AGENT_WORKSPACE_ROOT", "/workspace")

    assert task_worker._resolve_workspace_root(company.id) == "/workspace"


# ---------------------------------------------------------------------------
# check_files_written
# ---------------------------------------------------------------------------


def _run(files):
    return AgentRun(
        company_id=1,
        external_ref="task-1",
        producer=task_worker.TASK_WORKER_PRODUCER,
        claims={"files": files},
        artifact_digest="x",
        artifact_size=1,
    )


def _evidence(writes, expected=None):
    return {
        "workspace_root": "/p",
        "expected": expected or {},
        "workspace_writes": writes,
    }


def test_files_written_verified_when_every_hash_matches():
    check = check_files_written(
        _run(["a.py"]),
        _evidence(
            [{"path": "a.py", "status": "written", "sha256": _sha("x")}],
            {"a.py": _sha("x")},
        ),
    )
    assert check["outcome"] == "pass"


@pytest.mark.parametrize(
    "writes",
    [
        [],
        [{"path": "a.py", "status": "rejected"}],
        [{"path": "a.py", "status": "skipped_protected"}],
        [{"path": "a.py", "status": "written", "sha256": _sha("tampered")}],
    ],
)
def test_files_written_refuted_when_missing_rejected_or_different(writes):
    check = check_files_written(_run(["a.py"]), _evidence(writes, {"a.py": _sha("x")}))
    assert check["outcome"] == "refuted"


def test_files_written_unverifiable_without_a_daemon_report():
    check = check_files_written(
        _run(["a.py"]),
        {"workspace_root": "/p", "workspace_writes": None, "reason": "timeout"},
    )
    assert check["outcome"] == "unverifiable"
    assert "timeout" in check["observation"]


# ---------------------------------------------------------------------------
# Daemon
# ---------------------------------------------------------------------------


def test_daemon_reports_hash_of_the_bytes_on_disk(tmp_path):
    daemon = _load_daemon()

    results = daemon.write_files(
        str(tmp_path),
        [
            {"path": "pkg/mod.py", "content": "print('ñ')\n"},
            {"path": "../outside.py", "content": "x"},
        ],
    )

    written, rejected = results
    on_disk = (tmp_path / "pkg" / "mod.py").read_bytes()
    assert written["path"] == "pkg/mod.py"
    assert written["status"] == "written"
    assert written["sha256"] == hashlib.sha256(on_disk).hexdigest()
    assert written["bytes"] == len(on_disk)
    assert rejected == {"path": "../outside.py", "status": "rejected"}
    assert not (tmp_path.parent / "outside.py").exists()


def test_daemon_skips_protected_root_docs(tmp_path, monkeypatch):
    daemon = _load_daemon()
    monkeypatch.setattr(daemon, "PROTECTED_ROOT_DOCS", {"README.md"})
    (tmp_path / "README.md").write_text("curated")

    (result,) = daemon.write_files(
        str(tmp_path), [{"path": "README.md", "content": "agent"}]
    )

    assert result["status"] == "skipped_protected"
    assert (tmp_path / "README.md").read_text() == "curated"


def test_daemon_replies_with_per_file_results(tmp_path):
    daemon = _load_daemon()
    published = []

    class _NC:
        async def publish(self, subject, data):
            published.append((subject, json.loads(data.decode())))

    class _Msg:
        subject = "workspace.generate"
        reply = "_INBOX.1"
        data = json.dumps(
            {
                "workspace_root": str(tmp_path),
                "files": [{"path": "a.py", "content": "a = 1\n"}],
                "sprint_id": 7,
            }
        ).encode()

    asyncio.run(daemon.handle_msg(_NC(), _Msg()))

    reply = dict(published)["_INBOX.1"]
    assert reply["ok"] is True
    assert reply["workspace_root"] == str(tmp_path)
    assert reply["files"][0]["sha256"] == _sha("a = 1\n")
    assert "Wrote 1 file(s): a.py" in dict(published)["glassroom.7"]["content"]


# ---------------------------------------------------------------------------
# End to end: answer → files on disk → AgentRun + Verification → board
# ---------------------------------------------------------------------------


class _DaemonOverNATS:
    """Fake NATS client: ``request`` runs the real daemon; publishes are kept."""

    jetstream_enabled = False

    def __init__(self, daemon, fail: bool = False):
        self.daemon = daemon
        self.fail = fail
        self.published = []
        self.requests = []

    async def request(self, subject, payload, timeout=5.0):
        self.requests.append((subject, payload, timeout))
        if self.fail:
            raise TimeoutError("nats: timeout")
        files = self.daemon.write_files(payload["workspace_root"], payload["files"])
        return {"ok": True, "workspace_root": payload["workspace_root"], "files": files}

    async def publish(self, subject, payload, msg_id=None):
        self.published.append((subject, payload))


def _task_fixture(db, project_path: str):
    company = _company(db, f"E2E Corp {project_path[-6:]}")
    db.add(ProjectDiscovery(company_id=company.id, project_path=project_path))
    sprint = Sprint(
        company_id=company.id, sprint_name="Auth", scope_size="M", status="active"
    )
    db.add(sprint)
    db.commit()
    db.refresh(sprint)
    item = BacklogItem(
        sprint_id=sprint.id,
        title="Implement login",
        description="Login handler with a test",
        status="in_progress",
        priority="high",
        assignee="Developer",
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return (
        {"id": item.id, "title": item.title, "description": item.description},
        {
            "role": "Developer",
            "name": "Dev Ana",
            "model": "deepseek-v4-pro",
            "served_model": "deepseek-chat",
        },
        {"id": sprint.id, "company_id": company.id, "name": sprint.sprint_name},
    )


def _latest(db, item_id: int):
    db.expire_all()
    company_id = db.get(Sprint, db.get(BacklogItem, item_id).sprint_id).company_id
    run = db.exec(
        select(AgentRun)
        .where(
            AgentRun.company_id == company_id,
            AgentRun.external_ref == f"task-{item_id}",
        )
        .order_by(AgentRun.version.desc())
    ).first()
    verification = db.exec(
        select(Verification).where(Verification.agent_run_id == run.id)
    ).first()
    comments = db.get(BacklogItem, item_id).comments
    if isinstance(comments, str):
        comments = json.loads(comments)
    return run, verification, comments


def test_end_to_end_files_land_and_delivery_is_verified(db, tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path / "audit"))
    project = tmp_path / "project"
    project.mkdir()
    item, agent, sprint = _task_fixture(db, str(project))
    nats = _DaemonOverNATS(_load_daemon())

    review = asyncio.run(
        task_worker._deliver_artifacts(nats, item, agent, sprint, TWO_FILE_ANSWER)
    )

    login = project / "src" / "auth" / "login.py"
    assert login.read_text().startswith("def login(user, password):")
    assert (
        "from src.auth.login import login"
        in (project / "tests" / "test_login.py").read_text()
    )
    assert nats.requests[0][0] == "workspace.generate"

    run, verification, comments = _latest(db, item["id"])
    assert run.producer == "le-fabrique-task-worker"
    assert run.claims["files"] == ["src/auth/login.py", "tests/test_login.py"]
    assert run.model == "deepseek-chat"
    assert verification.verdict == "verified"
    assert {c["name"]: c["outcome"] for c in verification.checks}[
        "files_written"
    ] == "pass"
    assert comments[-1]["text"].startswith(f"Delivered to {project}")
    assert f"evidence run #{run.id} (verified)" in comments[-1]["text"]
    assert "# Artifact: src/auth/login.py" in review
    event = next(p for s, p in nats.published if s == f"glassroom.{sprint['id']}")
    assert event["agent_run_id"] == run.id
    assert event["verdict"] == "verified"


def test_end_to_end_daemon_down_is_unverifiable_not_lost(db, tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path / "audit"))
    project = tmp_path / "project-down"
    project.mkdir()
    item, agent, sprint = _task_fixture(db, str(project))
    nats = _DaemonOverNATS(_load_daemon(), fail=True)

    review = asyncio.run(
        task_worker._deliver_artifacts(nats, item, agent, sprint, TWO_FILE_ANSWER)
    )

    assert not (project / "src").exists()
    _, verification, comments = _latest(db, item["id"])
    assert verification.verdict == "unverifiable"
    assert comments[-1]["text"].startswith("Delivery unconfirmed:")
    assert "did not reply" in comments[-1]["text"]
    assert review  # QA still gets the deliverable


def test_answer_without_files_is_still_recorded(db, tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path / "audit"))
    item, agent, sprint = _task_fixture(db, str(tmp_path))
    nats = _DaemonOverNATS(_load_daemon())

    asyncio.run(
        task_worker._deliver_artifacts(
            nats, item, agent, sprint, "A written analysis with no files."
        )
    )

    assert nats.requests == []
    run, verification, _comments = _latest(db, item["id"])
    assert run.claims["files"] == []
    assert verification is not None


def test_unreported_served_model_is_left_empty_not_defaulted(db, tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path / "audit"))
    item, agent, sprint = _task_fixture(db, str(tmp_path))
    agent = {**agent, "served_model": None}

    asyncio.run(
        task_worker._deliver_artifacts(
            _DaemonOverNATS(_load_daemon()), item, agent, sprint, "Analysis only."
        )
    )

    run, _verification, _comments = _latest(db, item["id"])
    assert run.model is None


def test_new_company_records_its_project_so_agents_write_there(
    db, monkeypatch, tmp_path
):
    from services.company_service import CompanyService

    monkeypatch.setenv("AGENT_WORKSPACE_ROOT", "/workspace")
    result = CompanyService(db).init_company(
        company_name="Project Corp",
        agents=[{"name": "Dev Ana", "role": "Developer"}],
        project_path=f"  {tmp_path}  ",
        detected_stack={"language": "Python"},
    )
    db.commit()

    company_id = result["company_id"]
    assert task_worker._resolve_workspace_root(company_id) == str(tmp_path)
    discovery = db.exec(
        select(ProjectDiscovery).where(ProjectDiscovery.company_id == company_id)
    ).one()
    assert json.loads(discovery.detected_stack) == {"language": "Python"}


def test_company_without_a_project_uses_the_fallback_root(db, monkeypatch):
    from services.company_service import CompanyService

    monkeypatch.setenv("AGENT_WORKSPACE_ROOT", "/workspace")
    result = CompanyService(db).init_company(company_name="No project Corp", agents=[])
    db.commit()

    assert task_worker._resolve_workspace_root(result["company_id"]) == "/workspace"
