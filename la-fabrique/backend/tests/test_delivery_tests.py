"""
Opt-in test run after delivery: the daemon runs the project's tests and the
exit status becomes evidence (a ``tests_run`` check, and the ``ci`` evidence
that judges an agent's "tests pass" claim).
"""

import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import pytest
from config import settings
from models.agent_run import AgentRun, Verification
from models.company import Company, ProjectDiscovery
from models.sprint import BacklogItem, Sprint
from services import task_worker
from services.verification import check_tests_run
from sqlmodel import select

_DAEMON_PATH = Path(__file__).resolve().parents[2] / "vscode-daemon" / "daemon.py"


def _load_daemon():
    spec = importlib.util.spec_from_file_location("fabrique_daemon_tests", _DAEMON_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Command detection
# ---------------------------------------------------------------------------


@pytest.fixture()
def no_override(monkeypatch):
    monkeypatch.setattr(settings, "DELIVERY_TEST_COMMAND", "")


def test_configured_command_wins(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "DELIVERY_TEST_COMMAND", " make test ")
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    assert task_worker._detect_test_command(str(tmp_path)) == "make test"


def test_npm_test_script_is_detected(no_override, tmp_path):
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"test": "vitest run"}})
    )
    assert task_worker._detect_test_command(str(tmp_path)) == "npm test --silent"


def test_npm_placeholder_script_is_not_a_test_suite(no_override, tmp_path):
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"test": 'echo "Error: no test specified" && exit 1'}})
    )
    assert task_worker._detect_test_command(str(tmp_path)) is None


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("pytest.ini", "[pytest]\n"),
        ("pyproject.toml", "[tool.pytest.ini_options]\naddopts = '-q'\n"),
        ("setup.cfg", "[tool:pytest]\n"),
    ],
)
def test_pytest_configuration_is_detected(no_override, tmp_path, name, content):
    (tmp_path / name).write_text(content)
    assert task_worker._detect_test_command(str(tmp_path)) == "python -m pytest -q"


def test_tests_folder_is_detected_and_unrelated_toml_is_not(no_override, tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    assert task_worker._detect_test_command(str(tmp_path)) is None
    (tmp_path / "tests" / "unit").mkdir(parents=True)
    (tmp_path / "tests" / "unit" / "test_x.py").write_text("def test_x(): pass\n")
    assert task_worker._detect_test_command(str(tmp_path)) == "python -m pytest -q"


# ---------------------------------------------------------------------------
# check_tests_run
# ---------------------------------------------------------------------------


def test_tests_run_outcomes():
    passed = check_tests_run({"test_run": {"command": "pytest", "exit_code": 0}})
    failed = check_tests_run(
        {"test_run": {"command": "pytest", "exit_code": 1, "output_tail": "1 failed"}}
    )
    silent = check_tests_run({"test_run": {"command": "pytest", "reason": "timeout"}})
    none = check_tests_run(
        {"test_run": {"command": None, "reason": "no test command found"}}
    )

    assert passed["outcome"] == "pass"
    assert failed["outcome"] == "refuted"
    assert "exited 1: 1 failed" in failed["observation"]
    assert silent["outcome"] == "unverifiable"
    assert none["outcome"] == "unverifiable"
    assert "no test command found" in none["observation"]


# ---------------------------------------------------------------------------
# End to end: files written, tests executed by the real daemon
# ---------------------------------------------------------------------------


def _answer(expected: str) -> str:
    return f"""Added greet with a test. All tests pass.

```python path=src/greet.py
def greet(name):
    return f"Hello, {{name}}!"
```

```python path=tests/test_greet.py
from src.greet import greet


def test_greet():
    assert greet("Ana") == "{expected}"
```
"""


class _DaemonOverNATS:
    jetstream_enabled = False

    def __init__(self, daemon):
        self.daemon = daemon
        self.subjects = []

    async def request(self, subject, payload, timeout=5.0):
        self.subjects.append(subject)
        if subject == "workspace.generate":
            files = self.daemon.write_files(payload["workspace_root"], payload["files"])
            return {"ok": True, "files": files}
        if subject == "workspace.execute":
            return self.daemon.execute_shell_command(
                payload["command"], payload["workspace_root"]
            )
        if subject == "workspace.inspect":
            return self.daemon.inspect_project(payload["path"], payload["snapshot"])
        raise AssertionError(subject)

    async def publish(self, subject, payload, msg_id=None):
        pass


@pytest.fixture()
def project(monkeypatch, sqlite_session, tmp_path):
    bind = sqlite_session.get_bind()
    ProjectDiscovery.__table__.create(bind, checkfirst=True)
    monkeypatch.setattr(task_worker, "engine", bind)
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path / "audit"))
    monkeypatch.setattr(settings, "DELIVERY_TESTS_ENABLED", True)
    monkeypatch.setattr(
        settings,
        "DELIVERY_TEST_COMMAND",
        f"{sys.executable} -m pytest -q -p no:cacheprovider",
    )
    root = tmp_path / "project"
    root.mkdir()
    (root / "pytest.ini").write_text("[pytest]\npythonpath = .\n")

    company = Company(company_name=f"Tests Corp {tmp_path.name}", autonomy_level=2)
    sqlite_session.add(company)
    sqlite_session.commit()
    sqlite_session.refresh(company)
    sqlite_session.add(ProjectDiscovery(company_id=company.id, project_path=str(root)))
    sprint = Sprint(company_id=company.id, sprint_name="T", scope_size="S")
    sqlite_session.add(sprint)
    sqlite_session.commit()
    sqlite_session.refresh(sprint)
    item = BacklogItem(sprint_id=sprint.id, title="Greet", status="in_progress")
    sqlite_session.add(item)
    sqlite_session.commit()
    sqlite_session.refresh(item)
    return (
        sqlite_session,
        {"id": item.id, "title": item.title},
        {"role": "Developer", "served_model": "m"},
        {"id": sprint.id, "company_id": company.id},
    )


def _verification(session, company_id, item_id):
    session.expire_all()
    run = session.exec(
        select(AgentRun).where(
            AgentRun.company_id == company_id,
            AgentRun.external_ref == f"task-{item_id}",
        )
    ).first()
    verification = session.exec(
        select(Verification).where(Verification.agent_run_id == run.id)
    ).first()
    return verification, {c["name"]: c for c in verification.checks}


def test_passing_suite_verifies_the_agents_test_claim(project):
    session, item, agent, sprint = project
    nats = _DaemonOverNATS(_load_daemon())

    asyncio.run(
        task_worker._deliver_artifacts(
            nats, item, agent, sprint, _answer("Hello, Ana!")
        )
    )

    verification, checks = _verification(session, sprint["company_id"], item["id"])
    assert nats.subjects == ["workspace.generate", "workspace.execute"]
    assert checks["tests_run"]["outcome"] == "pass"
    assert checks["claimed_tests_evidenced"]["outcome"] == "pass"
    assert verification.verdict == "verified"
    assert task_worker._delivery_gate(sprint["company_id"], item["id"]) is None


def test_failing_suite_refutes_and_sends_the_task_back(project):
    session, item, agent, sprint = project
    nats = _DaemonOverNATS(_load_daemon())

    asyncio.run(
        task_worker._deliver_artifacts(nats, item, agent, sprint, _answer("Hi, Ana!"))
    )

    verification, checks = _verification(session, sprint["company_id"], item["id"])
    assert checks["tests_run"]["outcome"] == "refuted"
    assert "exited 1" in checks["tests_run"]["observation"]
    assert checks["claimed_tests_evidenced"]["outcome"] == "refuted"
    assert verification.verdict == "refuted"
    problem, observation = task_worker._delivery_gate(sprint["company_id"], item["id"])
    assert problem == "tests failed"
    assert "exited 1" in observation


def test_disabled_by_default(project, monkeypatch):
    session, item, agent, sprint = project
    monkeypatch.setattr(settings, "DELIVERY_TESTS_ENABLED", False)
    nats = _DaemonOverNATS(_load_daemon())

    asyncio.run(
        task_worker._deliver_artifacts(nats, item, agent, sprint, _answer("Hi, Ana!"))
    )

    _verification_row, checks = _verification(session, sprint["company_id"], item["id"])
    assert nats.subjects == ["workspace.generate"]
    assert "tests_run" not in checks
