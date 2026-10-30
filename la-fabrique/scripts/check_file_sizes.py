#!/usr/bin/env python3
"""
A ratchet on file size: a source file over the limit may not grow.

Source files (backend app code, the daemon, scripts, the frontend's src,
tests excluded) must stay at or under LIMIT lines. The files already over it
are listed in scripts/file_size_baseline.json with the size they had; each
may shrink but never grow, and a new file may not cross the limit. When a
listed file shrinks, ``--update`` lowers its entry (it never raises one) and
drops the entries of files back under the limit or gone.

Exit status 0 when every file keeps to the rule, 1 otherwise. Run from
anywhere: paths are resolved from the repository root.
"""

import json
import subprocess
import sys
from pathlib import Path

LIMIT = 600
ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "scripts" / "file_size_baseline.json"
PATTERNS = (
    "backend/app/*.py",
    "backend/agents/*.py",
    "vscode-daemon/*.py",
    "llm-proxy/*.py",
    "scripts/*.py",
    "frontend/src/*.ts",
    "frontend/src/*.tsx",
)


def _is_test(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return "/tests/" in f"/{path}" or ".test." in name or name.startswith("test_")


def source_files() -> list[str]:
    # git pathspecs: a single * matches across directories.
    listed = subprocess.run(
        ["git", "ls-files", "--", *PATTERNS],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return sorted(path for path in listed if not _is_test(path))


def line_count(path: str) -> int:
    with open(ROOT / path, encoding="utf-8", errors="replace") as handle:
        return sum(1 for _ in handle)


def main(argv: list[str]) -> int:
    update = "--update" in argv
    baseline: dict[str, int] = (
        json.loads(BASELINE.read_text()) if BASELINE.exists() else {}
    )
    sizes = {path: line_count(path) for path in source_files()}

    problems = []
    for path, lines in sizes.items():
        if lines <= LIMIT:
            continue
        allowed = baseline.get(path)
        if allowed is None:
            problems.append(
                f"{path}: {lines} lines, over the {LIMIT}-line limit; split it"
            )
        elif lines > allowed:
            problems.append(
                f"{path}: grew from {allowed} to {lines} lines; it is over the "
                f"{LIMIT}-line limit, so it may only shrink"
            )

    tightened = {
        path: min(allowed, sizes[path])
        for path, allowed in baseline.items()
        if sizes.get(path, 0) > LIMIT
    }
    if update:
        if problems:
            print("Not updating while files break the rule:", file=sys.stderr)
        else:
            BASELINE.write_text(json.dumps(tightened, indent=2, sort_keys=True) + "\n")
            print(f"Baseline written: {len(tightened)} file(s) over {LIMIT} lines.")
    elif tightened != baseline:
        print(
            "The baseline can be tightened (files shrank or went under the "
            "limit): run scripts/check_file_sizes.py --update and commit it."
        )

    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
