"""The pip fallback must install exactly what poetry.lock pins."""

import platform
import tomllib
from pathlib import Path

import pytest

from tools import lock_requirements

LOCK_PATH = Path(__file__).resolve().parents[1] / "la-fabrique" / "backend" / "poetry.lock"
LOCK = tomllib.loads(LOCK_PATH.read_text(encoding="utf-8"))


def _requirements(text: str) -> dict[str, tuple[str, str]]:
    """Map name -> (version, marker) for a requirements file."""
    found = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        requirement, _, marker = line.partition(";")
        name, _, version = requirement.strip().partition("==")
        found[name.strip()] = (version.strip(), marker.strip())
    return found


def _pins(text: str) -> dict[str, str]:
    return {name: version for name, (version, _) in _requirements(text).items()}


def _markers(text: str) -> dict[str, str]:
    return {name: marker for name, (_, marker) in _requirements(text).items() if marker}


def test_lock_has_packages():
    assert len(LOCK["package"]) > 50


def test_main_group_excludes_dev_tools():
    pins = _pins(lock_requirements.render(LOCK, ["main"], "3.12"))

    assert "fastapi" in pins
    assert "httpx" in pins  # the package Poetry failed to install
    assert "pytest" not in pins
    assert "black" not in pins


def test_dev_group_is_optional():
    pins = _pins(lock_requirements.render(LOCK, ["main", "dev"], "3.12"))

    assert "pytest" in pins


def test_platform_markers_are_evaluated_and_kept():
    requirements = _requirements(lock_requirements.render(LOCK, ["main"], "3.12"))

    if platform.system() == "Windows":
        assert requirements["colorama"][0]
        assert 'platform_system == "Windows"' in requirements["colorama"][1]
        assert "uvloop" not in requirements
    else:
        assert 'sys_platform != "win32"' in requirements["uvloop"][1]
        assert "colorama" not in requirements


def test_markers_survive_when_packaging_is_missing(monkeypatch):
    """Without packaging nothing is filtered, so pip must be the one deciding.

    This is the Windows-critical case: a fresh venv has no ``packaging``, and
    dropping the marker would try to build uvloop there.
    """
    monkeypatch.setattr(lock_requirements, "Marker", None)

    requirements = _requirements(lock_requirements.render(LOCK, ["main"], "3.12"))

    assert 'sys_platform != "win32"' in requirements["uvloop"][1]
    assert 'platform_system == "Windows"' in requirements["colorama"][1]


def test_python_version_filter_is_applied(monkeypatch):
    monkeypatch.setattr(lock_requirements, "Marker", None)
    lock = {
        "package": [
            {
                "name": "solo-nuevo",
                "version": "2.0.0",
                "groups": ["main"],
                "python-versions": ">=3.13",
            },
            {"name": "cualquiera", "version": "1.0.0", "groups": ["main"], "python-versions": "*"},
        ]
    }

    pins = _pins(lock_requirements.render(lock, ["main"], "3.12"))

    assert "solo-nuevo" not in pins
    assert "cualquiera" in pins


def test_optional_extras_are_skipped():
    lock = {
        "package": [
            {"name": "base", "version": "1.0.0", "groups": ["main"], "optional": False},
            {"name": "extra", "version": "1.0.0", "groups": ["main"], "optional": True},
        ]
    }

    assert _pins(lock_requirements.render(lock, ["main"], "3.12")) == {"base": "1.0.0"}


def test_group_marker_dict_is_read_per_group(monkeypatch):
    monkeypatch.setattr(lock_requirements, "Marker", None)
    lock = {
        "package": [
            {
                "name": "solo-dev",
                "version": "1.0.0",
                "groups": ["main", "dev"],
                "markers": {
                    "main": 'platform_system == "Plan9"',
                    "dev": 'platform_system != "Plan9"',
                },
            }
        ]
    }

    markers = _markers(lock_requirements.render(lock, ["main"], "3.12"))
    assert markers == {"solo-dev": 'platform_system == "Plan9"'}

    assert _markers(lock_requirements.render(lock, ["dev"], "3.12")) == {
        "solo-dev": 'platform_system != "Plan9"'
    }


def test_output_is_a_valid_requirements_file():
    text = lock_requirements.render(LOCK, ["main", "dev"], "3.12")

    lines = [line for line in text.splitlines() if line.strip()]
    assert lines
    for line in lines:
        requirement, _, marker = line.partition(";")
        name, sep, version = requirement.strip().partition("==")
        assert sep == "=="
        assert name and version and " " not in requirement.strip()
        if marker:
            assert '"' in marker or "'" in marker


def test_writes_output_file(tmp_path):
    target = tmp_path / "req.txt"

    assert lock_requirements.main([str(LOCK_PATH), "--output", str(target)]) == 0

    lines = target.read_text(encoding="utf-8").strip().splitlines()
    assert lines and all("==" in line for line in lines)


def test_works_in_a_fresh_venv_without_packaging(monkeypatch):
    """A just-created venv has pip and nothing else: the exporter must not crash."""
    import importlib
    import sys

    for name in ("packaging", "packaging.markers", "packaging.specifiers", "packaging.version"):
        monkeypatch.setitem(sys.modules, name, None)

    fresh = importlib.reload(lock_requirements)
    try:
        assert fresh.Marker is None
        text = fresh.render(LOCK, ["main"], "3.12")
        assert 'sys_platform != "win32"' in text
        assert "fastapi==" in text
    finally:
        monkeypatch.undo()
        importlib.reload(lock_requirements)
