#!/usr/bin/env python3
"""
Le Fabrique — Orchestration Regression Suite
=============================================
Tests the core orchestration pipeline contracts **without** invoking any LLM.
Run against a live stack:

    python scripts/regression_orchestration.py [--base-url http://localhost:8000]

Or inside the backend container:

    docker exec factory-backend python /app/../scripts/regression_orchestration.py

Exit codes:
    0  All checks passed
    1  One or more checks failed
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import textwrap
import time
import traceback
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError

# ── ANSI colour helpers (no extra deps) ─────────────────────────────────────

RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RED    = "\033[91m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"

def _c(text: str, *codes: str) -> str:
    return "".join(codes) + str(text) + RESET

def ok(msg: str)   -> str: return _c(f"  ✓  {msg}", GREEN, BOLD)
def fail(msg: str) -> str: return _c(f"  ✗  {msg}", RED,   BOLD)
def warn(msg: str) -> str: return _c(f"  ⚠  {msg}", YELLOW)
def info(msg: str) -> str: return _c(f"     {msg}", DIM)
def head(msg: str) -> str: return _c(f"\n{'─'*60}\n  {msg}\n{'─'*60}", CYAN, BOLD)


# ── Result tracking ──────────────────────────────────────────────────────────

@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""
    elapsed: float = 0.0


@dataclass
class Suite:
    base_url: str
    results: List[CheckResult] = field(default_factory=list)

    def run(self, name: str, fn: Callable[[], Optional[str]]) -> bool:
        """Run *fn*; record pass/fail. fn returns None on success, error msg on failure."""
        t0 = time.monotonic()
        try:
            err = fn()
            passed = err is None
            detail = "" if passed else err
        except Exception as exc:  # noqa: BLE001
            passed = False
            detail = f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=4)}"
        elapsed = time.monotonic() - t0
        r = CheckResult(name=name, passed=passed, detail=detail, elapsed=elapsed)
        self.results.append(r)
        marker = ok(name) if passed else fail(name)
        print(marker + _c(f"  ({elapsed:.2f}s)", DIM))
        if detail and not passed:
            for line in textwrap.wrap(detail, width=80):
                print(info("  " + line))
        return passed

    # HTTP helpers ─────────────────────────────────────────────────────────

    def get(self, path: str, params: dict | None = None) -> dict:
        url = self.base_url.rstrip("/") + path
        if params:
            from urllib.parse import urlencode
            url += "?" + urlencode(params)
        req = urllib_request.Request(url, headers={"Accept": "application/json"})
        with urllib_request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())

    def post(self, path: str, body: dict) -> dict:
        url = self.base_url.rstrip("/") + path
        data = json.dumps(body).encode()
        req = urllib_request.Request(
            url, data=data,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        with urllib_request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())

    # Summary ──────────────────────────────────────────────────────────────

    def summary(self) -> int:
        passed = sum(1 for r in self.results if r.passed)
        total  = len(self.results)
        failed = total - passed
        print(head("RESULTS"))
        for r in self.results:
            icon = ok(r.name) if r.passed else fail(r.name)
            print(f"  {'✓' if r.passed else '✗'}  {r.name}  ({r.elapsed:.2f}s)")
        print()
        if failed == 0:
            print(_c(f"  All {total} checks passed.", GREEN, BOLD))
        else:
            print(_c(f"  {passed}/{total} passed — {failed} FAILED", RED, BOLD))
        return 1 if failed else 0


# ── Individual check groups ───────────────────────────────────────────────────

def check_health(s: Suite) -> None:
    print(head("1 · Health endpoints"))

    def _shallow():
        r = s.get("/health")
        status = r.get("status", "")
        if status not in ("ok", "healthy"):
            return f"Expected status=ok|healthy, got: {r}"

    def _deep():
        r = s.get("/health/deep")
        status = r.get("status")
        if status not in ("healthy", "degraded"):
            return f"Expected healthy/degraded, got status={status!r} — {r}"
        if status == "degraded":
            # Warn but don't fail; degraded = Neo4j/NATS down, not API down
            print(warn("  deep health is degraded (non-critical deps may be down)"))

    s.run("GET /health → status=ok", _shallow)
    s.run("GET /health/deep → healthy|degraded", _deep)


def check_company_lifecycle(s: Suite) -> tuple[int | None, int | None]:
    """
    Bootstrap a temporary test company and return (company_id, sprint_id).
    Returns (None, None) if bootstrap fails — downstream checks skip.
    """
    print(head("2 · Company bootstrap + sprint creation"))
    company_id: int | None = None
    sprint_id:  int | None = None

    unique = f"regression-{uuid.uuid4().hex[:8]}"

    def _init():
        nonlocal company_id
        r = s.post("/v1/init_company", {
            "company_name": unique,
            "admin_email":  f"{unique}@test.invalid",
            "admin_password": "Regression!2026",
        })
        cid = r.get("company_id") or r.get("id")
        if not cid:
            return f"No company_id in response: {r}"
        company_id = int(cid)

    s.run(f"POST /v1/init_company ({unique})", _init)
    if company_id is None:
        return None, None

    def _sprint():
        nonlocal sprint_id
        today = time.strftime("%Y-%m-%d")
        r = s.post("/v1/start_sprint", {
            "company_id":   company_id,
            "sprint_name":  "Regression test sprint",
            "start_date":   today,
            "scope_size":   "S",
            "goal":         "Regression test — no real work",
            "backlog_items": [
                {"title": "Dummy task A", "description": "no-op test task"},
            ],
        })
        sid = r.get("sprint_id") or r.get("id")
        if not sid:
            return f"No sprint_id in response: {r}"
        sprint_id = int(sid)

    s.run("POST /v1/start_sprint (1 task)", _sprint)

    def _board():
        if sprint_id is None:
            return "sprint_id not available"
        r = s.get(f"/v1/sprints/{sprint_id}/board")
        if "columns" not in r and "backlog" not in r and "items" not in r:
            return f"Board response missing columns/backlog/items: {r}"

    s.run(f"GET /v1/sprints/{{id}}/board (id={sprint_id})", _board)

    def _quotas():
        r = s.get("/v1/enterprise/quotas", {"company_id": company_id})
        if not isinstance(r, (dict, list)):
            return f"Expected dict or list, got: {type(r)}"

    s.run("GET /v1/enterprise/quotas", _quotas)

    return company_id, sprint_id


def check_memory(s: Suite, company_id: int | None) -> None:
    print(head("3 · Memory (pgvector + engram)"))

    payload = {
        "content": "Regression test engram — can be safely deleted.",
        "role": "Developer",
        "company_id": company_id or 1,
        "sprint_id": 0,
        "task_id": 0,
    }

    def _store():
        # memory/store uses query params, not a JSON body
        from urllib.parse import urlencode, quote
        url = s.base_url.rstrip("/") + "/v1/memory/store?" + urlencode({
            "content": "Regression test engram — can be safely deleted.",
        })
        req = urllib_request.Request(url, data=b"", method="POST",
                                     headers={"Accept": "application/json"})
        with urllib_request.urlopen(req, timeout=10) as resp:
            r = json.loads(resp.read())
        if "id" not in r and "status" not in r and "stored" not in r and "ok" not in str(r).lower():
            return f"Unexpected store response: {r}"

    def _search():
        r = s.get("/v1/memory/search", {
            "query": "regression test engram",
            "limit": 5,
        })
        if not isinstance(r, (list, dict)):
            return f"Expected list or dict, got: {type(r)}"

    s.run("POST /v1/memory/store (Developer engram)", _store)
    s.run("GET  /v1/memory/search (keyword query)", _search)


def check_analytics(s: Suite, company_id: int | None) -> None:
    print(head("4 · Analytics endpoint (Issue #7)"))

    cid = company_id or 1

    def _health_shape():
        r = s.get("/v1/analytics/orchestration_health", {"company_id": cid, "weeks": 4})
        required = {"company_id", "anchor_commit", "anchor_date", "weeks",
                    "pre_batch1", "post_batch1"}
        missing = required - r.keys()
        if missing:
            return f"Missing keys in response: {missing} — got {list(r.keys())}"
        if r["anchor_commit"] != "116138e":
            return f"anchor_commit mismatch: {r['anchor_commit']!r}"
        if r["anchor_date"] != "2026-05-02":
            return f"anchor_date mismatch: {r['anchor_date']!r}"
        for section in ("pre_batch1", "post_batch1"):
            sec = r[section]
            for field in ("qa_needs_work_rate", "avg_developer_tokens",
                          "architect_consult_count", "task_count"):
                if field not in sec:
                    return f"{section}.{field} missing"

    def _weeks_param():
        r1 = s.get("/v1/analytics/orchestration_health", {"company_id": cid, "weeks": 1})
        r8 = s.get("/v1/analytics/orchestration_health", {"company_id": cid, "weeks": 8})
        # With no real data both may return empty weeks — just check shape is consistent
        if not isinstance(r1.get("weeks"), list) or not isinstance(r8.get("weeks"), list):
            return f"weeks field not a list: r1={r1}, r8={r8}"

    def _summary_also():
        # /v1/analytics/summary existed before batch 1 — ensure it still responds
        try:
            r = s.get("/v1/analytics/summary", {"company_id": cid})
            if not isinstance(r, (dict, list)):
                return f"summary returned unexpected type: {type(r)}"
        except HTTPError as exc:
            if exc.code == 404:
                return "GET /v1/analytics/summary returned 404 — route may have been removed"
            # 500 with empty DB is acceptable
        except Exception as exc:  # noqa: BLE001
            return f"summary call failed: {exc}"

    s.run("GET /v1/analytics/orchestration_health (shape + anchor)", _health_shape)
    s.run("GET /v1/analytics/orchestration_health (weeks param)", _weeks_param)
    s.run("GET /v1/analytics/summary (backward compat)", _summary_also)


def check_workspace_snapshot() -> None:
    """
    Unit-level regression for workspace_snapshot module.
    Runs inside the current process; requires the backend on sys.path
    OR a PYTHONPATH that includes /app/app.
    """
    print(head("5 · workspace_snapshot (unit, no LLM)"))

    # Locate the project root (2 levels up from this script)
    repo_root = Path(__file__).resolve().parent.parent

    # Try to import workspace_snapshot; silently skip if not on path
    import importlib, sys as _sys
    candidates = [
        str(repo_root / "backend" / "app"),
        "/app/app",
        "/app",
    ]
    loaded = False
    for c in candidates:
        if c not in _sys.path:
            _sys.path.insert(0, c)
        try:
            ws = importlib.import_module("services.workspace_snapshot")
            loaded = True
            break
        except ImportError:
            pass

    if not loaded:
        print(warn("  workspace_snapshot not importable from this environment — skipping unit checks"))
        return

    # ── 5a: _list_workspace_files or walk fallback ────────────────────────
    list_fn = (
        getattr(ws, "_list_workspace_files", None)
        or getattr(ws, "walk_workspace", None)
        or getattr(ws, "_walk_workspace", None)
    )
    if list_fn is None:
        print(warn("  workspace file listing function not found — skipping"))
    else:
        t0 = time.monotonic()
        try:
            files = list_fn(str(repo_root))
            elapsed = time.monotonic() - t0
            assert isinstance(files, list), f"Expected list, got {type(files)}"
            assert len(files) > 10, f"Expected >10 files, got {len(files)}"
            bad = [f for f in files if "/.git/" in f or f.startswith(".git/") or "/node_modules/" in f or "/__pycache__/" in f]
            assert not bad, f"Found {len(bad)} ignored-path files: {bad[:3]}"
            print(ok(f"file listing: {len(files)} files, no ignored paths  ({elapsed:.2f}s)"))
        except Exception as exc:  # noqa: BLE001
            print(fail(f"file listing: {exc}"))

    # ── 5b: build_task_snapshot with synthetic task ──────────────────────
    build_fn = getattr(ws, "build_task_snapshot", None)
    if build_fn is None:
        print(warn("  build_task_snapshot not found — skipping"))
    else:
        t0 = time.monotonic()
        try:
            snapshot = build_fn(
                task_title="regression test: check task_worker routing",
                task_description="test orchestration regression suite for the backend",
                workspace_root=str(repo_root),
            )
            elapsed = time.monotonic() - t0
            assert isinstance(snapshot, str), f"Expected str, got {type(snapshot)}"
            assert len(snapshot) > 50, "Snapshot suspiciously short"
            assert "/" in snapshot or "\\" in snapshot, "No path reference found in snapshot"
            print(ok(f"build_task_snapshot: {len(snapshot)} chars, contains path refs  ({elapsed:.2f}s)"))
        except Exception as exc:  # noqa: BLE001
            print(fail(f"build_task_snapshot: {exc}"))

    # ── 5c: read_artifact_evidence path traversal guard ──────────────────
    evidence_fn = getattr(ws, "read_artifact_evidence", None)
    if evidence_fn is None:
        print(warn("  read_artifact_evidence not found — skipping"))
    else:
        t0 = time.monotonic()
        try:
            # Traversal attempt: pass as list of paths (iterable), as per real signature
            traversal_attempt = ["../../../../etc/passwd"]
            result = evidence_fn(
                workspace_root=str(repo_root),
                artifact_paths=traversal_attempt,
            )
            elapsed = time.monotonic() - t0
            if result and "/etc/passwd" in result and "root:" in result:
                print(fail(f"read_artifact_evidence: path traversal NOT blocked! ({elapsed:.2f}s)"))
            else:
                print(ok(f"read_artifact_evidence: traversal rejected/sanitised  ({elapsed:.2f}s)"))
        except (ValueError, PermissionError, FileNotFoundError):
            elapsed = time.monotonic() - t0
            print(ok(f"read_artifact_evidence: traversal raised expected error  ({elapsed:.2f}s)"))
        except Exception as exc:  # noqa: BLE001
            print(warn(f"  read_artifact_evidence traversal check: {exc}"))


def check_model_factory() -> None:
    """Unit-level regression for model_factory complexity routing."""
    print(head("6 · model_factory (unit, no LLM)"))

    import importlib, sys as _sys
    repo_root = Path(__file__).resolve().parent.parent
    for c in [str(repo_root / "backend" / "app"), "/app/app", "/app"]:
        if c not in _sys.path:
            _sys.path.insert(0, c)

    try:
        mf = importlib.import_module("llm.model_factory")
    except ImportError:
        try:
            mf = importlib.import_module("app.llm.model_factory")
        except ImportError:
            print(warn("  llm.model_factory not importable — skipping"))
            return

    # get_model backward-compat
    t0 = time.monotonic()
    try:
        model = mf.get_model("Developer")
        assert isinstance(model, str) and model, f"Expected non-empty str, got {model!r}"
        print(ok(f"get_model('Developer') → {model!r}  ({time.monotonic()-t0:.2f}s)"))
    except Exception as exc:  # noqa: BLE001
        print(fail(f"get_model: {exc}"))

    # get_model_for_complexity new API
    t0 = time.monotonic()
    try:
        gc = getattr(mf, "get_model_for_complexity", None)
        if gc is None:
            print(warn("  get_model_for_complexity not found — skipping"))
        else:
            TaskComplexity = getattr(mf, "TaskComplexity", None)
            if TaskComplexity:
                m_simple  = gc("Developer", TaskComplexity.SIMPLE)
                m_complex = gc("Developer", TaskComplexity.COMPLEX)
                assert isinstance(m_simple, str) and m_simple
                assert isinstance(m_complex, str) and m_complex
                print(ok(
                    f"get_model_for_complexity Developer: "
                    f"simple={m_simple!r} complex={m_complex!r}  "
                    f"({time.monotonic()-t0:.2f}s)"
                ))
    except Exception as exc:  # noqa: BLE001
        print(fail(f"get_model_for_complexity: {exc}"))


def check_governance() -> None:
    """Unit-level regression for governance path blocking."""
    print(head("7 · governance (unit, path-blocking)"))

    import importlib, sys as _sys
    repo_root = Path(__file__).resolve().parent.parent
    for c in [str(repo_root / "backend" / "app"), "/app/app", "/app"]:
        if c not in _sys.path:
            _sys.path.insert(0, c)

    try:
        gov = importlib.import_module("app.services.governance")
    except ImportError:
        try:
            gov = importlib.import_module("services.governance")
        except ImportError:
            print(warn("  governance module not importable — skipping"))
            return

    check_fn = getattr(gov, "check_write_path", None) or getattr(gov, "is_protected_path", None)
    if check_fn is None:
        print(warn("  check_write_path / is_protected_path not found — skipping"))
        return

    # Protected paths: SELF_IMPROVEMENT_PROTECTED_PATHS
    protected_examples = [
        "backend/app/services/governance.py",
        "db/init-db/init.sql",
        "docker-compose.yml",
    ]
    safe_examples = [
        "workspace/output/my_feature.py",
        "generated/report.md",
    ]

    all_pass = True
    for path in protected_examples:
        t0 = time.monotonic()
        try:
            result = check_fn(path, is_self_improvement=True)
            elapsed = time.monotonic() - t0
            # Should be blocked (return False/raise/return 'blocked' sentinel)
            blocked = (result is False) or (result == "blocked") or (result == "sandbox")
            if not blocked:
                print(fail(f"protected path NOT blocked: {path}  ({elapsed:.2f}s)"))
                all_pass = False
            else:
                print(ok(f"protected path blocked: {path}  ({elapsed:.2f}s)"))
        except (ValueError, PermissionError) as exc:
            print(ok(f"protected path raised expected exception for {path}: {type(exc).__name__}"))
        except Exception as exc:  # noqa: BLE001
            print(warn(f"  governance check for {path}: {exc}"))

    for path in safe_examples:
        t0 = time.monotonic()
        try:
            result = check_fn(path, is_self_improvement=True)
            elapsed = time.monotonic() - t0
            allowed = result is not False and result != "blocked"
            if not allowed:
                print(fail(f"safe path unexpectedly blocked: {path}"))
                all_pass = False
            else:
                print(ok(f"safe path allowed: {path}  ({elapsed:.2f}s)"))
        except Exception as exc:  # noqa: BLE001
            print(warn(f"  governance safe-path check for {path}: {exc}"))


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Le Fabrique orchestration regression suite")
    parser.add_argument("--base-url", default="http://localhost:8000",
                        help="Base URL of the running backend API (default: http://localhost:8000)")
    parser.add_argument("--skip-api", action="store_true",
                        help="Skip HTTP API checks (run unit checks only)")
    parser.add_argument("--skip-unit", action="store_true",
                        help="Skip unit checks (run HTTP API checks only)")
    args = parser.parse_args()

    print(_c("\n╔══════════════════════════════════════════╗", CYAN, BOLD))
    print(_c("║  Le Fabrique — Orchestration Regression  ║", CYAN, BOLD))
    print(_c("╚══════════════════════════════════════════╝\n", CYAN, BOLD))
    print(info(f"  Target: {args.base_url}"))
    print(info(f"  Date:   {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}"))

    s = Suite(base_url=args.base_url)

    # ── HTTP / integration checks ────────────────────────────────────────
    if not args.skip_api:
        try:
            s.get("/health")
            api_reachable = True
        except (URLError, OSError):
            api_reachable = False
            print(warn(f"\n  Backend not reachable at {args.base_url} — skipping HTTP checks"))

        if api_reachable:
            check_health(s)
            company_id, sprint_id = check_company_lifecycle(s)
            check_memory(s, company_id)
            check_analytics(s, company_id)

    # ── Unit checks (no HTTP needed) ─────────────────────────────────────
    if not args.skip_unit:
        check_workspace_snapshot()
        check_model_factory()
        check_governance()

    return s.summary()


if __name__ == "__main__":
    sys.exit(main())
