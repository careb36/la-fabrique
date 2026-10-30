"""Static guards for the PowerShell launcher.

The script cannot run in CI (no Windows), but two of its bugs were invisible in
code review and only showed up on a real machine, so the traps are pinned here.
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "arrancar.ps1"
WRAPPER = ROOT / "arrancar.cmd"


@pytest.fixture(scope="module")
def script() -> str:
    return LAUNCHER.read_bytes().decode("utf-8-sig")


def test_files_exist():
    assert LAUNCHER.is_file()
    assert WRAPPER.is_file()


def test_script_is_utf8_with_bom_and_crlf():
    """PowerShell 5.1 needs the BOM; cmd.exe needs CRLF."""
    raw = LAUNCHER.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    assert text.count("\r\n") == text.count("\n")


def test_wrapper_is_ascii_and_crlf():
    raw = WRAPPER.read_bytes()
    raw.decode("ascii")
    assert raw.count(b"\r\n") == raw.count(b"\n")


def test_venv_layout_covers_both_platforms(script):
    """Windows uses Scripts\\python.exe, POSIX bin/python."""
    assert "Add(@('Scripts', 'python.exe'))" in script
    assert "'bin', 'python'" in script


def test_no_array_unrolling_through_if(script):
    """`$x = if (...) { @(, @(a, b)) }` yields two strings, not one array.

    That silently made every Windows venv look broken: the launcher looked for
    <venv>\\Scripts and <venv>\\python.exe instead of <venv>\\Scripts\\python.exe.
    """
    assert "@(, @" not in script


def test_waits_for_output_before_reading_it(script):
    """Reading the redirect file after WaitForExit(ms) alone returns empty."""
    assert script.count("WaitForExit()") >= 1


def test_has_diagnostic_mode(script):
    assert "[switch]$Diagnostico" in script
    assert "-Diagnostico" in (ROOT / "README.md").read_text(encoding="utf-8")


def test_never_writes_a_readonly_automatic_variable(script):
    """$home, $input, $args... are read-only; assigning one aborts the run."""
    for name in ("$home ", "$input ", "$error "):
        assert name not in script
