#!/usr/bin/env python3
"""Report how much wording this package shares with another source tree.

    python tools/similarity_check.py ../profesor3

Exit code 0 when the overlap is nil (or under ``--limit``), 1 otherwise. The
number is the evidence a reviewer asks for: not "I wrote it myself", but
"here are the 8-word sequences, and there are none in common".
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from b1.originality import compare  # noqa: E402 - after sys.path setup


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("other", type=Path, help="árbol con el que comparar")
    parser.add_argument("--mine", type=Path, default=Path(__file__).resolve().parents[1] / "b1")
    parser.add_argument("--show", type=int, default=5, help="cuántas coincidencias mostrar")
    args = parser.parse_args()

    report = compare(args.mine, args.other)
    print(report.summary())
    if report.identical:
        print("Original: no hay prosa ni bloques de código en común.")
        return 0
    for item in report.prose_shared[: args.show]:
        print(f"  prosa: {item}")
    for item in report.code_shared[: args.show]:
        print(f"  código: {item}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
