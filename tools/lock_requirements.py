"""Export a Poetry lock file as a pip requirements file.

Fallback only: when ``poetry install`` cannot reach PyPI (TLS interception,
flaky DNS) pip usually still can, because pip trusts the system certificate
store while Poetry only ships certifi. Exporting the lock keeps the exact
pinned versions, so the fallback does not silently upgrade anything.

Markers are written into the requirements file (``uvloop==0.22.1 ;
sys_platform != "win32"``) so pip evaluates them against the interpreter that
is actually installing. That matters: the exporter may run in a fresh venv
where ``packaging`` is not importable yet, and guessing here would try to
install uvloop on Windows. When ``packaging`` is available it is only used to
drop lines that certainly do not apply, keeping the file short.
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path

try:  # present in most venvs; never required
    from packaging.markers import Marker
    from packaging.specifiers import SpecifierSet
    from packaging.version import Version
except ImportError:  # pragma: no cover - fresh venvs only have pip
    # A venv created moments ago has pip and nothing else. Every helper below
    # must work with these set to None: markers are then left to pip.
    Marker = None  # type: ignore[assignment]
    SpecifierSet = None  # type: ignore[assignment]
    Version = None  # type: ignore[assignment]

Package = tuple[str, str, str | None]


def _marker_for(package: dict, group: str) -> str | None:
    markers = package.get("markers")
    if isinstance(markers, dict):
        return markers.get(group)
    if isinstance(markers, str):
        return markers
    return None


def _marker_applies(marker: str | None) -> bool:
    """True when the marker certainly applies (or cannot be evaluated)."""
    if not marker or Marker is None:
        return True
    try:
        return bool(Marker(marker).evaluate())
    except Exception:
        return True


def _python_matches(spec: str | None, python_version: str) -> bool:
    if not spec or Version is None:
        return True
    try:
        return Version(python_version) in SpecifierSet(spec)
    except Exception:
        return True


def select_packages(lock: dict, groups: list[str], python_version: str) -> list[Package]:
    chosen: dict[str, Package] = {}
    for package in lock.get("package", []):
        package_groups = package.get("groups") or ["main"]
        shared = [group for group in groups if group in package_groups]
        if not shared:
            continue
        if package.get("optional"):
            continue
        marker = _marker_for(package, shared[0])
        if not _marker_applies(marker):
            continue
        if not _python_matches(package.get("python-versions"), python_version):
            continue
        chosen.setdefault(package["name"], (package["name"], package["version"], marker))
    return list(chosen.values())


def render(lock: dict, groups: list[str], python_version: str) -> str:
    lines = []
    for name, version, marker in select_packages(lock, groups, python_version):
        line = f"{name}=={version}"
        if marker and marker.strip():
            line += f" ; {marker.strip()}"
        lines.append(line)
    return "".join(line + "\n" for line in lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lock", type=Path)
    parser.add_argument("--groups", default="main", help="grupos separados por comas")
    parser.add_argument(
        "--python",
        default=f"{sys.version_info.major}.{sys.version_info.minor}",
        help="versión de Python con la que evaluar los marcadores",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    lock = tomllib.loads(args.lock.read_text(encoding="utf-8"))
    groups = [group.strip() for group in args.groups.split(",") if group.strip()]
    text = render(lock, groups, args.python)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        print(f"{len(text.splitlines())} paquetes exportados a {args.output}")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
