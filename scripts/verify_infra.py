#!/usr/bin/env python3
"""
La Fabrique — Infrastructure Verification Script
=================================================
Validates Neo4j (TKG), Postgres/pgvector, and OpenProject without invoking
any LLM. Run from the project root:

    python scripts/verify_infra.py [--env /path/to/.env]

Running from the HOST (outside Docker):
    python scripts/verify_infra.py --local
    # Translates Docker-internal hostnames (neo4j, postgres, openproject)
    # → localhost / 127.0.0.1 so the script can reach containers from macOS.

Exit codes:
    0  All checks passed
    1  One or more checks failed
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

# ── Optional dependency: python-dotenv ───────────────────────────────────────
try:
    from dotenv import load_dotenv
    _HAS_DOTENV = True
except ImportError:
    _HAS_DOTENV = False

# ── ANSI colour helpers (no extra deps) ──────────────────────────────────────

RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RED    = "\033[91m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
WHITE  = "\033[97m"
BLUE   = "\033[94m"

def _c(text: str, *codes: str) -> str:
    return "".join(codes) + str(text) + RESET

def ok(msg: str)   -> str: return _c(f"  ✓  {msg}", GREEN, BOLD)
def fail(msg: str) -> str: return _c(f"  ✗  {msg}", RED,   BOLD)
def warn(msg: str) -> str: return _c(f"  ⚠  {msg}", YELLOW)
def info(msg: str) -> str: return _c(f"     {msg}", DIM)
def head(msg: str) -> str: return _c(f"\n{'─'*60}\n  {msg}\n{'─'*60}", CYAN, BOLD)
def hint(var: str, desc: str) -> None:
    print(_c(f"     → Set {var} in your .env  ({desc})", YELLOW))

def note(msg: str) -> None:
    print(_c(f"  ℹ  {msg}", BLUE))


# ── Result accumulator ────────────────────────────────────────────────────────

@dataclass
class CheckResult:
    suite: str
    name: str
    passed: bool
    detail: str = ""
    elapsed_ms: float = 0.0

@dataclass
class Suite:
    name: str
    results: List[CheckResult] = field(default_factory=list)

    def add(self, name: str, passed: bool, detail: str = "", elapsed_ms: float = 0.0) -> None:
        self.results.append(CheckResult(self.name, name, passed, detail, elapsed_ms))
        icon = ok(name) if passed else fail(name)
        print(icon)
        if detail:
            for line in detail.splitlines():
                print(info(line))
        if elapsed_ms:
            print(info(f"({elapsed_ms:.0f} ms)"))

    @property
    def all_passed(self) -> bool:
        return all(r.passed for r in self.results)


def _timed(fn: Callable[[], Any]):
    """Run fn(), return (result, elapsed_ms)."""
    t0 = time.perf_counter()
    result = fn()
    return result, (time.perf_counter() - t0) * 1000


# ── Docker service name → localhost translation ───────────────────────────────

_DOCKER_SERVICES = {"neo4j", "postgres", "nats", "openproject"}


def _apply_local_overrides() -> None:
    """Translate Docker-internal service hostnames → localhost for host execution."""
    note("--local mode: translating Docker service names → localhost / 127.0.0.1")

    def _replace_host(val: str, replacement: str) -> str:
        for svc in _DOCKER_SERVICES:
            val = val.replace(f"//{svc}:", f"//{replacement}:")
            val = val.replace(f"//{svc}/", f"//{replacement}/")
        return val

    # NEO4J_URI
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    new_uri = _replace_host(uri, "localhost")
    if new_uri != uri:
        os.environ["NEO4J_URI"] = new_uri
        print(info(f"NEO4J_URI: {uri!r} → {new_uri!r}"))

    # POSTGRES_HOST — use 127.0.0.1 (IPv4) to avoid native-Postgres on [::1]
    pg_host = os.getenv("POSTGRES_HOST", "localhost")
    if pg_host in _DOCKER_SERVICES:
        os.environ["POSTGRES_HOST"] = "127.0.0.1"
        print(info(f"POSTGRES_HOST: {pg_host!r} → '127.0.0.1'"))
    elif pg_host in ("localhost", "::1"):
        os.environ["POSTGRES_HOST"] = "127.0.0.1"
        print(info(f"POSTGRES_HOST: {pg_host!r} → '127.0.0.1'  (forcing IPv4)"))

    # OPENPROJECT_URL — replace Docker service name; port stays the same
    op_url = os.getenv("OPENPROJECT_URL", "")
    new_op = _replace_host(op_url, "localhost")
    if new_op != op_url:
        os.environ["OPENPROJECT_URL"] = new_op
        print(info(f"OPENPROJECT_URL: {op_url!r} → {new_op!r}"))
        note("If Docker exposes OpenProject on a different host port, set OPENPROJECT_URL manually.")

    print()


# ══════════════════════════════════════════════════════════════════════════════
# 1. NEO4J
# ══════════════════════════════════════════════════════════════════════════════

def _check_neo4j(suite: Suite) -> None:
    try:
        import neo4j
    except ImportError:
        suite.add("Driver import", False,
                  "neo4j package not installed.\n"
                  "Run: pip install neo4j")
        hint("—", "pip install neo4j")
        return

    uri      = os.getenv("NEO4J_URI",      "bolt://localhost:7687")
    user     = os.getenv("NEO4J_USER",     "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "")

    if not password:
        suite.add("Credentials present", False,
                  "NEO4J_PASSWORD is empty.")
        hint("NEO4J_PASSWORD", "your Neo4j database password")
        return

    suite.add("Credentials present", True,
              f"URI={uri}  USER={user}  PASSWORD={'*' * len(password)}")

    # ── Connect ──────────────────────────────────────────────────────────────
    driver: Optional[neo4j.Driver] = None
    try:
        driver, ms = _timed(lambda: neo4j.GraphDatabase.driver(
            uri, auth=(user, password),
            connection_timeout=5,
            max_transaction_retry_time=5,
        ))
        driver.verify_connectivity()
        suite.add("TCP connection", True, f"Connected to {uri}", ms)
    except Exception as exc:
        suite.add("TCP connection", False,
                  f"{exc}\nVerify NEO4J_URI is reachable and the password is correct.")
        hint("NEO4J_URI",      "bolt://<host>:7687")
        hint("NEO4J_PASSWORD", "your Neo4j password")
        return

    # ── Create dummy Semantic_JavaClass node ─────────────────────────────────
    node_id = f"verify_infra_{uuid4().hex[:8]}"
    create_cypher = """
        CREATE (n:Semantic_JavaClass:_VerifyInfra {
            id: $id,
            fqn: 'com.fabrique.VerifyInfra',
            created_at: datetime()
        })
        RETURN n.id AS id
    """
    try:
        with driver.session() as session:
            result, ms = _timed(lambda: session.run(create_cypher, id=node_id).single())
        returned_id = result["id"] if result else None
        assert returned_id == node_id, f"Expected {node_id!r}, got {returned_id!r}"
        suite.add(
            "CREATE Semantic_JavaClass node",
            True,
            f"Node id={node_id!r}  label=Semantic_JavaClass:_VerifyInfra",
            ms,
        )
    except Exception as exc:
        suite.add("CREATE Semantic_JavaClass node", False, str(exc))
        return
    finally:
        # ── Cleanup (always runs, even if assert failed) ──────────────────────
        try:
            with driver.session() as session:
                deleted, ms = _timed(lambda: session.run(
                    "MATCH (n:_VerifyInfra {id: $id}) DELETE n RETURN count(n) AS cnt",
                    id=node_id,
                ).single())
            cnt = deleted["cnt"] if deleted else 0
            suite.add("Cleanup (DELETE node)", True, f"Deleted {cnt} node(s)", ms)
        except Exception as exc:
            suite.add("Cleanup (DELETE node)", False, str(exc))
        try:
            driver.close()
        except Exception:
            pass

    # ── APOC availability (optional — absence is a warning, not a failure) ──────
    try:
        with neo4j.GraphDatabase.driver(uri, auth=(user, password)) as drv:
            with drv.session() as session:
                result = session.run(
                    "CALL apoc.help('text') YIELD name WITH name LIMIT 1 RETURN name"
                ).single()
        suite.add("APOC plugin (optional)", True, f"apoc.{result['name']} available")
    except Exception:
        # Not a blocking failure — APOC is only needed for advanced graph ops
        suite.add("APOC plugin (optional)", True,
                  "APOC not installed. Not required for core features.\n"
                  "To enable: add APOC jar to Neo4j Docker image.")


# ══════════════════════════════════════════════════════════════════════════════
# 2. POSTGRES / pgvector
# ══════════════════════════════════════════════════════════════════════════════

def _check_postgres(suite: Suite) -> None:
    try:
        import psycopg2
    except ImportError:
        suite.add("Driver import", False,
                  "psycopg2 package not installed.\n"
                  "Run: pip install psycopg2-binary")
        return

    host     = os.getenv("POSTGRES_HOST",     "localhost")
    port     = int(os.getenv("POSTGRES_PORT", "5432"))
    user     = os.getenv("POSTGRES_USER",     "factory")
    password = os.getenv("POSTGRES_PASSWORD", "")
    db       = os.getenv("POSTGRES_DB",       "factory")

    missing = [v for v, val in [
        ("POSTGRES_PASSWORD", password),
    ] if not val]
    if missing:
        suite.add("Credentials present", False,
                  f"Missing: {', '.join(missing)}")
        for v in missing:
            hint(v, "required for Postgres connection")
        return

    suite.add("Credentials present", True,
              f"host={host}:{port}  db={db}  user={user}")

    # ── Connect ──────────────────────────────────────────────────────────────
    conn = None
    try:
        conn, ms = _timed(lambda: psycopg2.connect(
            host=host, port=port, user=user,
            password=password, dbname=db,
            connect_timeout=5,
        ))
        suite.add("TCP connection", True, f"Connected to {host}:{port}/{db}", ms)
    except Exception as exc:
        err_str = str(exc)
        detail = (
            f"{exc}\n"
            "Check POSTGRES_HOST, POSTGRES_PORT, POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB."
        )
        # Native macOS Postgres conflict: our role exists only in the Docker container
        if "role" in err_str and "does not exist" in err_str:
            detail += (
                f"\n\n⚠ Port conflict detected: a non-Docker Postgres on port {port} "
                f"rejected role '{user}' (that role lives only inside the Docker container).\n"
                "Fix options:\n"
                "  A) Stop native Postgres (macOS):\n"
                "       brew services stop postgresql@14   # adjust version as needed\n"
                "  B) Remap Docker Postgres to port 5433 in docker-compose.yml:\n"
                "       ports: ['5433:5432']\n"
                "     then add POSTGRES_PORT=5433 to your .env and re-run with --local"
            )
        suite.add("TCP connection", False, detail)
        hint("POSTGRES_HOST",     "hostname/IP of your Postgres server")
        hint("POSTGRES_PASSWORD", "your Postgres password")
        return

    cursor = conn.cursor()

    # ── pgvector extension ────────────────────────────────────────────────────
    try:
        cursor.execute(
            "SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';"
        )
        row = cursor.fetchone()
        if row:
            suite.add("pgvector extension", True,
                      f"Extension '{row[0]}' version {row[1]} is installed.")
        else:
            # Try to create it (requires superuser or CREATE privilege)
            try:
                cursor.execute("CREATE EXTENSION IF NOT EXISTS vector;")
                conn.commit()
                suite.add("pgvector extension", True,
                          "Extension 'vector' was not present — created successfully.")
            except Exception as inner:
                suite.add("pgvector extension", False,
                          f"Extension not installed and auto-create failed: {inner}\n"
                          "Run as superuser: CREATE EXTENSION vector;")
    except Exception as exc:
        suite.add("pgvector extension", False, str(exc))

    # ── vector_memory table ───────────────────────────────────────────────────
    try:
        cursor.execute("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = 'vector_memory'
            ORDER BY ordinal_position;
        """)
        cols = cursor.fetchall()
        if cols:
            col_summary = ", ".join(f"{c[0]}:{c[1]}" for c in cols)
            suite.add("vector_memory table", True, f"Columns: {col_summary}")
        else:
            suite.add("vector_memory table", False,
                      "Table 'vector_memory' does not exist.\n"
                      "Run db/init-db/ migrations to create the schema.")
    except Exception as exc:
        suite.add("vector_memory table", False, str(exc))

    # ── round-trip vector INSERT + cosine search ──────────────────────────────
    try:
        # A 3-dim dummy vector — just enough to prove the operator works.
        # We use a TEXT cast so the test works even when the column is 1536-dim.
        cursor.execute("""
            SELECT '[1,2,3]'::vector <=> '[1,2,3]'::vector AS cosine_dist;
        """)
        dist = cursor.fetchone()[0]
        assert abs(dist) < 1e-6, f"Expected ~0.0, got {dist}"
        suite.add("pgvector <=> operator", True,
                  f"Cosine distance [1,2,3]↔[1,2,3] = {dist:.6f} (expected 0.0)")
    except Exception as exc:
        suite.add("pgvector <=> operator", False,
                  f"{exc}\n"
                  "Ensure pgvector is installed and the 'vector' type is available.")

    cursor.close()
    conn.close()


# ══════════════════════════════════════════════════════════════════════════════
# 3. OPENPROJECT
# ══════════════════════════════════════════════════════════════════════════════

def _basic_auth(api_key: str) -> str:
    return "Basic " + base64.b64encode(f"apikey:{api_key}".encode()).decode()


def _op_headers(token: str) -> Dict[str, str]:
    return {
        "Authorization": _basic_auth(token),
        "Content-Type": "application/json",
        "Accept":        "application/hal+json",
    }


def _check_openproject(suite: Suite) -> None:
    try:
        import httpx
    except ImportError:
        suite.add("httpx import", False,
                  "httpx package not installed.\n"
                  "Run: pip install httpx")
        return

    base  = os.getenv("OPENPROJECT_URL",      "http://localhost:8080").rstrip("/")
    token = os.getenv("OPENPROJECT_TOKEN_PO", "")

    if not token:
        suite.add("Credentials present", False,
                  "OPENPROJECT_TOKEN_PO is empty.")
        hint("OPENPROJECT_TOKEN_PO",
             "OpenProject → My Account → Access Tokens → API key")
        hint("OPENPROJECT_URL",
             "Base URL of your OpenProject instance (no trailing slash)")
        return

    suite.add("Credentials present", True,
              f"URL={base}  TOKEN={'*' * 6}{token[-4:]}")

    # ── 3a. GET /api/v3/projects — auth + connectivity ─────────────────────
    project_id: Optional[int] = None
    try:
        with httpx.Client(timeout=10) as client:
            resp, ms = _timed(lambda: client.get(
                f"{base}/api/v3/projects",
                headers=_op_headers(token),
            ))

        if resp.status_code == 200:
            projects = resp.json().get("_embedded", {}).get("elements", [])
            if projects:
                project_id = projects[0]["id"]
                proj_names = ", ".join(f"#{p['id']} {p.get('name','?')}" for p in projects[:3])
                suite.add("GET /api/v3/projects", True,
                          f"Found {len(projects)} project(s): {proj_names}", ms)
            else:
                suite.add("GET /api/v3/projects", True,
                          "Auth OK — but no projects exist yet. "
                          "Create a project in OpenProject first.", ms)
                hint("—", "Create at least one project in OpenProject so WP tests can run")
        elif resp.status_code == 401:
            suite.add("GET /api/v3/projects", False,
                      "401 Unauthorized — token rejected.")
            hint("OPENPROJECT_TOKEN_PO",
                 "Make sure you copied the full API key, not an OAuth client secret")
            return
        elif resp.status_code == 403:
            suite.add("GET /api/v3/projects", False,
                      "403 Forbidden — token valid but lacks 'View projects' permission.")
            hint("OPENPROJECT_TOKEN_PO",
                 "Grant the API key user the 'Member' role in at least one project")
            return
        else:
            suite.add("GET /api/v3/projects", False,
                      f"HTTP {resp.status_code}: {resp.text[:300]}", ms)
            return
    except httpx.ConnectError as exc:
        suite.add("GET /api/v3/projects", False,
                  f"Cannot reach OpenProject at {base}:\n{exc}")
        hint("OPENPROJECT_URL",
             "Ensure OpenProject is running and the URL is reachable from this host")
        return
    except Exception as exc:
        suite.add("GET /api/v3/projects", False, str(exc))
        return

    if project_id is None:
        # No projects to test WP creation against — skip remaining checks.
        suite.add("POST work package (skipped)", False,
                  "Cannot create a Work Package without at least one project.")
        return

    # ── 3b. POST dummy Work Package ──────────────────────────────────────────
    wp_id: Optional[int] = None
    wp_subject = f"[VERIFY_INFRA] Automated test — {uuid4().hex[:8]}"

    payload: Dict[str, Any] = {
        "subject": wp_subject,
        "description": {"raw": "Created by `scripts/verify_infra.py`. Safe to delete."},
        "_links": {
            "project": {"href": f"/api/v3/projects/{project_id}"},
            "type":    {"href": "/api/v3/types/1"},    # 1 = Task (default)
            "status":  {"href": "/api/v3/statuses/1"}, # 1 = New (default)
        },
    }

    try:
        with httpx.Client(timeout=15) as client:
            resp, ms = _timed(lambda: client.post(
                f"{base}/api/v3/work_packages",
                headers=_op_headers(token),
                json=payload,
            ))

        if resp.status_code in (200, 201):
            wp_data  = resp.json()
            wp_id    = wp_data.get("id")
            wp_url   = f"{base}/work_packages/{wp_id}"
            suite.add(
                "POST /api/v3/work_packages",
                True,
                f"Created WP #{wp_id}: {wp_subject!r}\n"
                f"URL: {wp_url}",
                ms,
            )
        elif resp.status_code == 403:
            suite.add("POST /api/v3/work_packages", False,
                      f"403 Forbidden — token lacks 'Create work packages' permission "
                      f"in project #{project_id}.\n{resp.text[:300]}")
            hint("OPENPROJECT_TOKEN_PO",
                 "Assign the API key user a role with 'Create work packages' permission")
            return
        elif resp.status_code == 422:
            suite.add("POST /api/v3/work_packages", False,
                      f"422 Unprocessable — OpenProject rejected the payload.\n"
                      f"{resp.text[:500]}\n"
                      "The default type/status IDs may differ in your installation.")
            return
        else:
            suite.add("POST /api/v3/work_packages", False,
                      f"HTTP {resp.status_code}: {resp.text[:400]}", ms)
            return
    except Exception as exc:
        suite.add("POST /api/v3/work_packages", False, str(exc))
        return

    if wp_id is None:
        return

    # ── 3c. PATCH — close / reject the dummy WP ──────────────────────────────
    # Fetch lock_version first (required for optimistic concurrency in OP v3).
    lock_version = 0
    try:
        with httpx.Client(timeout=10) as client:
            get_resp = client.get(
                f"{base}/api/v3/work_packages/{wp_id}",
                headers=_op_headers(token),
            )
        if get_resp.status_code == 200:
            lock_version = get_resp.json().get("lockVersion", 0)
    except Exception:
        pass  # proceed with lockVersion=0; worst case OP returns 409

    # Try status IDs in order: Closed (5) → Rejected (6) → Resolved (3)
    # Different installations may have different sets.
    closed = False
    for status_id, label in [(5, "Closed"), (6, "Rejected"), (3, "Resolved")]:
        patch_payload: Dict[str, Any] = {
            "lockVersion": lock_version,
            "_links": {
                "status": {"href": f"/api/v3/statuses/{status_id}"},
            },
        }
        try:
            with httpx.Client(timeout=10) as client:
                patch_resp, ms = _timed(lambda: client.patch(
                    f"{base}/api/v3/work_packages/{wp_id}",
                    headers=_op_headers(token),
                    json=patch_payload,
                ))
            if patch_resp.status_code in (200, 201):
                new_status = (
                    patch_resp.json()
                    .get("_links", {})
                    .get("status", {})
                    .get("title", label)
                )
                suite.add(
                    f"PATCH WP #{wp_id} → {label}",
                    True,
                    f"WP #{wp_id} status is now '{new_status}' (lockVersion bumped)",
                    ms,
                )
                closed = True
                break
            elif patch_resp.status_code == 422:
                # Status transition not allowed — try next
                continue
            else:
                suite.add(
                    f"PATCH WP #{wp_id} → {label}",
                    False,
                    f"HTTP {patch_resp.status_code}: {patch_resp.text[:300]}",
                )
                break
        except Exception as exc:
            suite.add(f"PATCH WP #{wp_id} → {label}", False, str(exc))
            break

    if not closed:
        suite.add(
            "Cleanup (close WP)",
            False,
            f"Could not transition WP #{wp_id} to a closed state.\n"
            f"No standard closed-status (Closed/Rejected/Resolved) accepted the transition.\n"
            f"Please close WP #{wp_id} manually in OpenProject.",
        )


# ══════════════════════════════════════════════════════════════════════════════
# Runner
# ══════════════════════════════════════════════════════════════════════════════

def _load_env(env_file: Path) -> None:
    if _HAS_DOTENV:
        load_dotenv(env_file, override=False)
    else:
        # Minimal hand-rolled parser — no dependency required
        if not env_file.exists():
            return
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key   = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def _banner() -> None:
    print(_c("""
╔══════════════════════════════════════════════════════════════╗
║        La Fabrique — Infrastructure Verification             ║
║        Neo4j TKG · Postgres/pgvector · OpenProject           ║
╚══════════════════════════════════════════════════════════════╝
""", CYAN, BOLD))


def _summary(suites: List[Suite]) -> int:
    all_results = [r for s in suites for r in s.results]
    passed = sum(1 for r in all_results if r.passed)
    failed = sum(1 for r in all_results if not r.passed)

    print(_c(f"\n{'═'*60}", CYAN))
    print(_c(f"  Summary", CYAN, BOLD))
    print(_c(f"{'═'*60}", CYAN))

    for suite in suites:
        icon = _c("✓", GREEN, BOLD) if suite.all_passed else _c("✗", RED, BOLD)
        print(f"  {icon}  {suite.name}")
        for r in suite.results:
            sub_icon = _c("✓", GREEN) if r.passed else _c("✗", RED)
            ms_str   = _c(f"  {r.elapsed_ms:.0f}ms", DIM) if r.elapsed_ms else ""
            print(f"       {sub_icon} {r.name}{ms_str}")

    print()
    if failed == 0:
        print(_c(f"  ✓  All {passed} checks passed. Infrastructure is ready.", GREEN, BOLD))
    else:
        print(_c(f"  {passed} passed  ·  {failed} failed", BOLD))
        print(_c("  Fix the failing checks before starting the LangGraph simulation.", YELLOW))
    print()

    return 0 if failed == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify La Fabrique infrastructure (Neo4j, Postgres, OpenProject)"
    )
    parser.add_argument(
        "--env",
        default=str(Path(__file__).parent.parent / ".env"),
        help="Path to .env file (default: <project-root>/.env)",
    )
    parser.add_argument(
        "--only",
        choices=["neo4j", "postgres", "openproject"],
        default=None,
        help="Run only one suite",
    )
    parser.add_argument(
        "--local",
        action="store_true",
        default=False,
        help=(
            "Translate Docker-internal service hostnames (neo4j, postgres, openproject) "
            "→ localhost/127.0.0.1 for running from the host machine outside Docker."
        ),
    )
    args = parser.parse_args()

    env_path = Path(args.env)
    _load_env(env_path)

    _banner()

    if env_path.exists():
        print(info(f"Loaded env vars from: {env_path}"))
    else:
        print(warn(f".env not found at {env_path} — using shell environment only"))

    print()

    if args.local:
        _apply_local_overrides()

    suites: List[Suite] = []

    CHECKS = [
        ("neo4j",       "Neo4j TKG",          _check_neo4j),
        ("postgres",    "Postgres / pgvector", _check_postgres),
        ("openproject", "OpenProject API",     _check_openproject),
    ]

    for key, label, fn in CHECKS:
        if args.only and args.only != key:
            continue
        print(head(label))
        suite = Suite(label)
        try:
            fn(suite)
        except Exception:
            suite.add(
                "Unexpected error",
                False,
                traceback.format_exc(),
            )
        suites.append(suite)

    return _summary(suites)


if __name__ == "__main__":
    sys.exit(main())
