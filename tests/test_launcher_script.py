"""Static guards for the PowerShell launcher.

The script cannot run in CI (no Windows), but two of its bugs were invisible in
code review and only showed up on a real machine, so the traps are pinned here.
"""

from pathlib import Path
import sys

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


def test_captures_output_with_dotnet_not_start_process(script):
    """Start-Process -PassThru loses ExitCode ($null) in PowerShell 5.1.

    With a null code every "if ($code -ne 0)" fires: a successful export or a
    finished install looked like a failure and the real message was lost.
    """
    assert "Start-Process -FilePath" not in script
    assert "ReadToEndAsync()" in script
    assert "$process.ExitCode" in script


def test_readiness_is_decided_by_the_probe_payload(script):
    """The JSON report is the truth; the exit code is not reliable."""
    assert "Ready    =" in script
    assert script.count("$report.Ready") >= 2


def test_has_diagnostic_mode(script):
    assert "[switch]$Diagnostico" in script
    assert "-Diagnostico" in (ROOT / "README.md").read_text(encoding="utf-8")


def test_never_writes_a_readonly_automatic_variable(script):
    """$home, $input, $args... are read-only; assigning one aborts the run."""
    for name in ("$home ", "$input ", "$error "):
        assert name not in script


def test_full_factory_mode_is_wired_through(script):
    """-Completa must reach run_fusion; the flag is the only way to Docker."""
    assert "[switch]$Completa" in script
    assert "[string]$Agentes" in script
    assert "'--completa'" in script
    assert "@('--agentes', $Agentes)" in script


def test_full_factory_mode_is_documented(script):
    assert ".PARAMETER Completa" in script
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "-Completa" in readme


def test_frontend_is_built_where_it_lives(script):
    """The SPA is la-fabrique/frontend, not la-fabrique/backend/frontend.

    Pointing npm at <backend>/frontend made Push-Location fail and npm look for
    package.json in the repo root; the run aborted before the backend was up.
    """
    assert "Join-Path (Split-Path -Parent $BackendDir) 'frontend'" in script
    assert "Join-Path $BackendDir 'frontend'" not in script
    assert (ROOT / "la-fabrique" / "frontend" / "package.json").is_file()


def test_frontend_build_failure_does_not_abort_the_launch(script):
    """The API and the voice do not need the SPA: a broken npm step only warns."""
    body = script[script.index("function Install-Frontend"):]
    body = body[:body.index("function Test-BackendReady")]
    assert 'throw "npm no pudo' not in body
    assert body.count("Write-Aviso") >= 2
    assert "return" in body


def test_web_ui_build_is_opt_in(script):
    """The product serves the assistant's own panel (:8770/fabrica), not React.

    Building the SPA on every launch cost minutes of npm on the first start and
    killed the run when it failed; it is now behind -InterfazWeb.
    """
    assert "[switch]$InterfazWeb" in script
    assert "if ($InterfazWeb) { Install-Frontend }" in script
    assert "\n        Install-Frontend\n" not in script.replace("\r\n", "\n")
    assert "-InterfazWeb" in (ROOT / "README.md").read_text(encoding="utf-8")


def test_backend_serves_the_same_frontend_the_launcher_builds():
    sys.path.insert(0, str(ROOT / "la-fabrique" / "backend" / "app"))
    try:
        import ui_static
    finally:
        sys.path.pop(0)
    assert ui_static.dist_dir() == ROOT / "la-fabrique" / "frontend" / "dist"


def test_the_default_assistant_is_the_one_in_this_repository(script):
    """A fresh clone has asistente-b1/ and not profesor3/: the default must
    build its environment and install its requirements from asistente-b1."""
    assert "$script:AssistantName = if ($Asistente)" in script
    assert "else { 'b1' }" in script
    assert "if ($script:AssistantName -eq 'b1') { 'asistente-b1' } else { 'profesor3' }" in script
    assert "$AssistantDir = Join-Path $Root $AssistantFolder" in script
    assert "Join-Path $Root 'profesor3'" not in script
    assert "@('--asistente', $script:AssistantName)" in script


def test_a_missing_reference_assistant_says_how_to_start_instead(script):
    assert "No está la carpeta profesor3" in script
    assert "-Asistente b1" in script
    assert "-Asistente acepta 'b1' o 'profesor3'" in script


def test_b1_does_not_require_the_reference_assistants_gemini_module(script):
    b1_modules = script.split("$script:AssistantModules = if ($script:AssistantName -eq 'b1') {", 1)[1]
    b1_modules = b1_modules.split("} else {", 1)[0]
    assert "google.genai" not in b1_modules
    assert "faster_whisper" in b1_modules
