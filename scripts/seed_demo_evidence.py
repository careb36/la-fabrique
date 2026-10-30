#!/usr/bin/env python3
"""
Seed the evidence layer with one run per verdict, for the demo.

Three runs land in `/evidence`: `verified`, `refuted` and `unverifiable`. The
point of the screen is that the three exist and are distinguishable, so the
seed produces all three rather than a happy path.

Idempotent by construction: each run carries a fixed ``external_ref`` and
ingestion de-duplicates on it, and a run that already has a verification is
left alone. Running this twice leaves the same data.

Usage:
    python scripts/seed_demo_evidence.py --company-id 1
    FABRIQUE_TOKEN=... python scripts/seed_demo_evidence.py --company-id 1

The company must already exist. With ``AUTH_REQUIRED=false`` (the compose
default for a local demo) no token is needed; otherwise pass ``--token`` or set
``FABRIQUE_TOKEN``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


HEALTH_SOURCE = "def health():\n    return {'status': 'ok'}\n"
METRICS_SOURCE = "def metrics():\n    return {'tasks_done': 0}\n"
REPORT_SOURCE = "def report(sprint_id):\n    return {'sprint_id': sprint_id}\n"


# Each entry is one scenario: a claim, an artifact, and the observations the
# platform gathers on its own. The verdict is a consequence of those, never an
# input — that is the property the demo screen is there to show.
SCENARIOS = [
    {
        "external_ref": "demo/verified-health-endpoint",
        "agent_role": "Developer",
        "subject": {"title": "Add a /health endpoint", "sprint": "demo"},
        "claims": {
            "files": ["src/api/health.py"],
            "summary": "Added src/api/health.py and 12 tests passed.",
        },
        "artifact": (
            "--- /dev/null\n+++ b/src/api/health.py\n"
            + "".join(f"+{line}" for line in HEALTH_SOURCE.splitlines(keepends=True))
        ),
        "evidence": {
            "expected": {"src/api/health.py": _sha256(HEALTH_SOURCE)},
            "workspace_writes": [
                {
                    "path": "src/api/health.py",
                    "status": "written",
                    "sha256": _sha256(HEALTH_SOURCE),
                }
            ],
            "ci": {
                "source": "github-actions",
                "conclusion": "success",
                "ref": "demo-run-verified",
            },
            "test_run": {"command": "pytest -q", "exit_code": 0},
        },
        "expect": "verified",
    },
    {
        # The agent says it wrote a file; the daemon looked and it was not there.
        "external_ref": "demo/refuted-missing-file",
        "agent_role": "Developer",
        "subject": {"title": "Emit SprintMetrics", "sprint": "demo"},
        "claims": {
            "files": ["src/api/metrics.py"],
            "summary": "Created src/api/metrics.py with the sprint metrics.",
        },
        "artifact": (
            "--- /dev/null\n+++ b/src/api/metrics.py\n"
            + "".join(f"+{line}" for line in METRICS_SOURCE.splitlines(keepends=True))
        ),
        "evidence": {
            "expected": {"src/api/metrics.py": _sha256(METRICS_SOURCE)},
            "workspace_writes": [{"path": "src/api/metrics.py", "status": "not_found"}],
        },
        "expect": "refuted",
    },
    {
        # The daemon confirms the file, but nothing independent reports on the
        # tests the agent claims. Not knowing is its own verdict.
        "external_ref": "demo/unverifiable-no-ci",
        "agent_role": "Developer",
        "subject": {"title": "Render the sprint report", "sprint": "demo"},
        "claims": {
            "files": ["src/api/report.py"],
            "summary": "Wrote src/api/report.py; all tests pass.",
        },
        "artifact": (
            "--- /dev/null\n+++ b/src/api/report.py\n"
            + "".join(f"+{line}" for line in REPORT_SOURCE.splitlines(keepends=True))
        ),
        "evidence": {
            "expected": {"src/api/report.py": _sha256(REPORT_SOURCE)},
            "workspace_writes": [
                {
                    "path": "src/api/report.py",
                    "status": "written",
                    "sha256": _sha256(REPORT_SOURCE),
                }
            ],
        },
        "expect": "unverifiable",
    },
]


class ApiError(RuntimeError):
    pass


def _request(api_url: str, method: str, path: str, token: str | None, body=None):
    url = api_url.rstrip("/") + path
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read().decode()
            return response.status, json.loads(payload) if payload else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()
        raise ApiError(f"{method} {path} -> {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise ApiError(
            f"{method} {path} failed: {exc.reason}. Is the backend running at {api_url}?"
        ) from exc


def _ingest(api_url: str, token: str | None, company_id: int, scenario: dict) -> int:
    status, run = _request(
        api_url,
        "POST",
        "/v1/agent_runs",
        token,
        {
            "company_id": company_id,
            "external_ref": scenario["external_ref"],
            "producer": "seed",
            "model": "nvidia/nemotron-4-340b-instruct",
            "agent_role": scenario["agent_role"],
            "subject": scenario["subject"],
            "claims": scenario["claims"],
            "artifact": scenario["artifact"],
        },
    )
    created = "created" if status == 201 else "already present"
    print(f"  run {run['id']} ({created})")
    return run["id"]


def _verify(
    api_url: str, token: str | None, company_id: int, run_id: int, scenario: dict
):
    # The endpoint answers `{"verifications": [...]}`, and that dict is truthy
    # even when the list is empty — unwrap before testing it.
    _, body = _request(
        api_url,
        "GET",
        f"/v1/agent_runs/{run_id}/verifications?company_id={company_id}",
        token,
    )
    existing = (body or {}).get("verifications") or []
    if existing:
        verdict = existing[0].get("verdict")
        print(f"  verification exists (verdict={verdict}); leaving it alone")
        return verdict

    _, verification = _request(
        api_url,
        "POST",
        f"/v1/agent_runs/{run_id}/verify",
        token,
        {"company_id": company_id, "evidence": scenario["evidence"]},
    )
    return verification.get("verdict") if isinstance(verification, dict) else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--api-url",
        default=os.getenv("FABRIQUE_API_URL", "http://localhost:8000"),
        help="backend base URL (default: %(default)s)",
    )
    parser.add_argument(
        "--company-id",
        type=int,
        default=int(os.getenv("COMPANY_ID", "0")) or None,
        help="company to seed; required (or set COMPANY_ID)",
    )
    parser.add_argument(
        "--token",
        default=os.getenv("FABRIQUE_TOKEN"),
        help="bearer token when AUTH_REQUIRED is on (or set FABRIQUE_TOKEN)",
    )
    args = parser.parse_args()

    if not args.company_id:
        parser.error("--company-id is required (or set COMPANY_ID)")

    print(f"Seeding evidence for company {args.company_id} at {args.api_url}")
    failures = []
    for scenario in SCENARIOS:
        print(f"- {scenario['expect']}: {scenario['external_ref']}")
        try:
            run_id = _ingest(args.api_url, args.token, args.company_id, scenario)
            verdict = _verify(
                args.api_url, args.token, args.company_id, run_id, scenario
            )
        except ApiError as exc:
            failures.append(f"{scenario['external_ref']}: {exc}")
            print(f"  ERROR {exc}")
            continue
        if verdict != scenario["expect"]:
            failures.append(
                f"{scenario['external_ref']}: expected {scenario['expect']}, got {verdict}"
            )
            print(f"  UNEXPECTED verdict={verdict} (expected {scenario['expect']})")
        else:
            print(f"  verdict={verdict}")

    if failures:
        print("\nSeed finished with problems:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print("\nAll three verdicts are in place. Open /evidence in the frontend.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
