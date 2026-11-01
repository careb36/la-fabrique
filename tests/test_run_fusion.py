"""Tests for the fusion launcher: env handling and backend detection."""

import argparse
import json
import stat
import sys
import threading
import time
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import run_fusion

REAL_FACTORY = run_fusion.FACTORY
REAL_AGENTS_DIR = run_fusion.AGENTS_DIR


@pytest.fixture(autouse=True)
def _launcher_writes_stay_in_tmp(tmp_path, monkeypatch):
    """main() creates the agents' folder and writes la-fabrique/.env (with a
    fresh JWT secret) before it looks for Docker; in a test both go to a
    temporary folder, never into the working tree."""
    monkeypatch.setattr(run_fusion, "FACTORY", tmp_path / "la-fabrique")
    monkeypatch.setattr(run_fusion, "AGENTS_DIR", tmp_path / "agentes")
    (tmp_path / "la-fabrique").mkdir()


class _FactoryHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - http.server API
        if self.path == "/v1/capabilities":
            body = json.dumps({"auth_required": False}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, *_args):
        pass


class _HealthOnlyHandler(BaseHTTPRequestHandler):
    """A service that is up on the port but is not the factory."""

    def do_GET(self):  # noqa: N802 - http.server API
        if self.path == "/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, *_args):
        pass


def _serve(handler) -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def test_env_file_ignores_comments_and_quotes(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        '# comentario\nVOICE_API_KEY="secreto"\n\nAUTH_REQUIRED=false\nsin_igual\n',
        encoding="utf-8",
    )

    values = run_fusion._parse_env_file(env_file)

    assert values == {"VOICE_API_KEY": "secreto", "AUTH_REQUIRED": "false"}


def test_missing_env_file_is_empty(tmp_path):
    assert run_fusion._parse_env_file(tmp_path / "nope.env") == {}


def test_local_sqlite_mode_disables_optional_services(monkeypatch):
    for name in ("DATABASE_URL", "POSTGRES_PASSWORD", "JWT_SECRET_KEY", "AUTH_REQUIRED"):
        monkeypatch.delenv(name, raising=False)

    env = run_fusion._child_env(voice_key="k", use_sqlite=True, announce=False)

    assert env["DATABASE_URL"].startswith("sqlite:///")
    assert env["DATABASE_URL"].endswith("factory.db")
    assert env["NEO4J_DISABLED"] == "true"
    assert env["NATS_DISABLED"] == "true"
    assert env["VOICE_API_KEY"] == "k"


def test_the_browser_gets_a_session_even_on_a_single_user_install(monkeypatch):
    """The UI is a web app: without auth the only way in would be to leave the
    API open, and the launcher never does that."""
    for name in ("AUTH_REQUIRED", "ACCESS_TOKEN_EXPIRE_MINUTES"):
        monkeypatch.delenv(name, raising=False)

    env = run_fusion._child_env(voice_key="k", use_sqlite=True, announce=False)

    assert env["AUTH_REQUIRED"] == "true"
    assert int(env["ACCESS_TOKEN_EXPIRE_MINUTES"]) >= 60


def test_the_dashboard_is_allowed_to_embed_the_factory(monkeypatch):
    """The assistant embeds the React UI in an iframe; a DENY header blanked it."""
    monkeypatch.delenv("FRAME_ANCESTORS", raising=False)

    env = run_fusion._child_env(voice_key="k", use_sqlite=True, announce=False)

    origins = env["FRAME_ANCESTORS"].split()
    assert origins == ["http://127.0.0.1:8770", "http://localhost:8770"]
    # Not every loopback port: any local page could frame the signed-in UI.
    assert not any("*" in o for o in origins)


def test_auth_cannot_be_switched_off_from_the_environment(monkeypatch):
    monkeypatch.setenv("AUTH_REQUIRED", "false")

    env = run_fusion._child_env(voice_key="k", use_sqlite=True, announce=False)

    assert env["AUTH_REQUIRED"] == "true"


def test_a_chosen_frame_ancestors_list_is_respected(monkeypatch):
    monkeypatch.setenv("FRAME_ANCESTORS", "https://mi-panel.local:9000")

    env = run_fusion._child_env(voice_key="k", use_sqlite=True, announce=False)

    assert env["FRAME_ANCESTORS"] == "https://mi-panel.local:9000"


def test_children_get_utf8_console(monkeypatch):
    """cp1252 would mangle the accents the assistant and backend print."""
    monkeypatch.delenv("PYTHONIOENCODING", raising=False)
    monkeypatch.delenv("PYTHONUTF8", raising=False)

    env = run_fusion._child_env(voice_key="k", use_sqlite=True, announce=False)

    assert env["PYTHONIOENCODING"] == "utf-8:replace"
    assert env["PYTHONUTF8"] == "1"


def test_postgres_mode_leaves_nats_alone(monkeypatch):
    monkeypatch.setenv("POSTGRES_PASSWORD", "pw")
    monkeypatch.delenv("NATS_DISABLED", raising=False)

    env = run_fusion._child_env(voice_key="k", use_sqlite=False, announce=False)

    assert "NATS_DISABLED" not in env


def test_postgres_config_is_left_alone(monkeypatch):
    monkeypatch.setenv("POSTGRES_PASSWORD", "pw")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("JWT_SECRET_KEY", "jwt")
    monkeypatch.delenv("NEO4J_DISABLED", raising=False)
    monkeypatch.delenv("AUTH_REQUIRED", raising=False)

    env = run_fusion._child_env(voice_key="k", use_sqlite=True, announce=False)

    assert env.get("DATABASE_URL", "").startswith("sqlite") is False
    assert env.get("NEO4J_DISABLED") is None
    assert env.get("AUTH_REQUIRED") != "false"


def test_is_local_only_loopback():
    assert run_fusion._is_local("http://127.0.0.1:8000")
    assert run_fusion._is_local("http://localhost:8000")
    assert not run_fusion._is_local("http://192.168.1.10:8000")
    assert not run_fusion._is_local("https://fabrica.example.com")


def test_wait_until_up_accepts_the_factory_api():
    server, url = _serve(_FactoryHandler)
    try:
        assert run_fusion._wait_until_up(url, timeout=3) is True
    finally:
        server.shutdown()


def test_wait_until_up_ignores_a_foreign_service():
    server, url = _serve(_HealthOnlyHandler)
    try:
        assert run_fusion._wait_until_up(url, timeout=1) is False
    finally:
        server.shutdown()


def test_pick_python_honours_an_explicit_interpreter(tmp_path):
    fake = tmp_path / "python"
    fake.write_text("")
    assert (
        run_fusion._pick_python(str(fake), [tmp_path], "no_such_module") == str(fake)
    )


def test_pick_python_falls_back_when_nothing_matches(tmp_path):
    assert run_fusion._pick_python(None, [tmp_path], "no_such_module_xyz") == (
        run_fusion.sys.executable
    )


def test_venv_pythons_knows_the_windows_layout(tmp_path, monkeypatch):
    exe = tmp_path / "Scripts" / "python.exe"
    exe.parent.mkdir()
    exe.write_text("")

    monkeypatch.setattr(run_fusion.os, "name", "nt")
    found = list(run_fusion._venv_pythons([tmp_path]))
    assert found == [str(exe)]


def test_venv_pythons_ignores_linux_paths_on_windows(tmp_path, monkeypatch):
    exe = tmp_path / "bin" / "python"
    exe.parent.mkdir()
    exe.write_text("")

    monkeypatch.setattr(run_fusion.os, "name", "nt")
    assert list(run_fusion._venv_pythons([tmp_path])) == []


def test_venv_layout_matches_the_platform(monkeypatch):
    monkeypatch.setattr(run_fusion.os, "name", "nt")
    assert run_fusion._venv_layout() == (("Scripts", "python.exe"),)

    monkeypatch.setattr(run_fusion.os, "name", "posix")
    assert run_fusion._venv_layout() == (("bin", "python"), ("bin", "python3"))


def test_pick_python_ignores_a_missing_explicit_interpreter(tmp_path):
    missing = tmp_path / "no-existe" / "python.exe"
    assert run_fusion._pick_python(str(missing), [tmp_path], "no_such_module_xyz") == (
        run_fusion.sys.executable
    )


def test_pick_python_prefers_a_venv_that_has_the_module(tmp_path, monkeypatch):
    venv = tmp_path / "venv"
    (venv / "Scripts").mkdir(parents=True)
    (venv / "Scripts" / "python.exe").write_text("")
    (venv / "bin").mkdir()
    posix = venv / "bin" / "python"
    posix.write_text("")
    monkeypatch.setattr(
        run_fusion, "_can_import", lambda python, module: python == str(posix)
    )

    assert run_fusion._pick_python(None, [venv], "sys") == str(posix)


def test_port_in_use_sees_a_real_listener():
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]

        assert run_fusion._port_in_use("127.0.0.1", port) is True
        free = run_fusion._choose_port("127.0.0.1", port + 1)
        assert free is not None and free > port


def test_choose_port_returns_none_when_everything_is_taken(monkeypatch):
    monkeypatch.setattr(run_fusion, "_port_in_use", lambda host, port: True)

    assert run_fusion._choose_port("127.0.0.1", 8000, tries=3) is None


class _PanelHandler(BaseHTTPRequestHandler):
    """The factory itself: its own UI on the same port as the API."""

    def do_GET(self):  # noqa: N802 - http.server API
        if self.path == "/":
            body = b"<title>La Fabrique</title>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, *_args):
        pass


def test_the_ui_opens_once_the_factory_answers(monkeypatch):
    server, url = _serve(_PanelHandler)
    opened: list[str] = []
    asked: list[tuple[str, str]] = []

    def handoff(u, k):
        asked.append((u, k))
        return "code-123"

    monkeypatch.setattr(run_fusion, "_desktop_handoff", handoff)
    monkeypatch.setattr(run_fusion.webbrowser, "open", opened.append)
    monkeypatch.setattr(run_fusion, "_panel_answers", lambda *a, **k: False)
    try:
        run_fusion._open_panel(url, "voice-key", timeout=5.0, panel_timeout=0.0)
    finally:
        server.shutdown()
        server.server_close()

    # A single-use code, asked for when the browser opens; never the session.
    assert opened == [f"{url}/#codigo=code-123"]
    assert asked == [(url, "voice-key")]


def test_without_a_session_the_ui_still_opens(monkeypatch):
    server, url = _serve(_PanelHandler)
    opened: list[str] = []
    monkeypatch.setattr(run_fusion.webbrowser, "open", opened.append)
    monkeypatch.setattr(run_fusion, "_panel_answers", lambda *a, **k: False)
    try:
        run_fusion._open_panel(url, timeout=5.0, panel_timeout=0.0)
    finally:
        server.shutdown()
        server.server_close()

    assert opened == [f"{url}/"]


def test_a_factory_that_never_answers_is_reported(monkeypatch, capsys):
    opened: list[str] = []
    monkeypatch.setattr(run_fusion.webbrowser, "open", opened.append)
    monkeypatch.setattr(run_fusion, "_panel_answers", lambda *a, **k: False)

    run_fusion._open_panel("http://127.0.0.1:9", timeout=1.5, panel_timeout=0.0)

    assert opened == []
    assert "abre la fábrica" in capsys.readouterr().out


def test_the_launch_opens_the_new_panel_not_the_old_board(monkeypatch, capsys):
    """The user's complaint: a launch showed the factory's old skin.

    The panel carries the new identity and embeds the factory, so it must be
    the window that opens — not the factory's own UI.
    """
    server, url = _serve(_PanelHandler)
    opened: list[str] = []
    monkeypatch.setattr(run_fusion.webbrowser, "open", opened.append)
    monkeypatch.setattr(run_fusion, "_panel_answers", lambda *a, **k: True)
    try:
        run_fusion._open_panel(url, "voice-key", timeout=5.0, panel_timeout=2.0)
    finally:
        server.shutdown()
        server.server_close()

    assert opened == [f"{run_fusion.ASSISTANT_PANEL_URL}/"]
    assert "Fábrica" in capsys.readouterr().out


def test_a_stranger_on_the_panel_port_is_not_the_panel():
    """`/health` names the app; anything else listening there is not ours."""
    class _Stranger(_PanelHandler):
        def do_GET(self):
            body = b'{"ok": true, "app": "otra-cosa"}'
            self.send_response(200 if self.path == "/health" else 404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

    server, url = _serve(_Stranger)
    try:
        assert run_fusion._panel_answers(url) is False
    finally:
        server.shutdown()
        server.server_close()


def test_the_panel_is_recognised_by_its_health_marker():
    class _Real(_PanelHandler):
        def do_GET(self):
            body = json.dumps({"ok": True, "app": "tutor-virtual-a1"}).encode()
            self.send_response(200 if self.path == "/health" else 404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

    server, url = _serve(_Real)
    try:
        assert run_fusion._panel_answers(url) is True
    finally:
        server.shutdown()
        server.server_close()


def test_the_board_can_be_switched_off_from_the_command_line(capsys):
    with pytest.raises(SystemExit):
        run_fusion.main(["--help"])
    assert "--no-browser" in capsys.readouterr().out


def test_the_assistant_child_receives_the_factory_address(
    tmp_path, monkeypatch, capfd
):
    (tmp_path / "main.py").write_text(
        "import os\nprint('URL=' + os.environ.get('FABRICA_URL', ''))\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(run_fusion, "ASSISTANT", tmp_path)

    child = run_fusion._start_assistant(
        [], sys.executable, {"FABRICA_URL": "http://127.0.0.1:8123", "PATH": ""}
    )
    child.wait(timeout=60)

    assert child.returncode == 0
    assert "URL=http://127.0.0.1:8123" in capfd.readouterr().out



# ---------------------------------------------------------------------------
# Modo fábrica completa
# ---------------------------------------------------------------------------


def _fake_docker(tmp_path, *, compose_exit=0, log=None) -> Path:
    """A real executable that records its argv, like the docker CLI would."""
    log = log or tmp_path / "docker.log"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    docker = bin_dir / "docker"
    docker.write_text(
        "#!/bin/sh\n"
        f'echo "$@" >> "{log}"\n'
        'if [ "$1" = "info" ]; then echo "29.0.0"; exit 0; fi\n'
        f"exit {compose_exit}\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    return docker


def test_full_mode_points_the_backend_at_the_containers(tmp_path):
    env = run_fusion._full_env(
        {"POSTGRES_USER": "factory", "POSTGRES_PASSWORD": "pw", "POSTGRES_DB": "factory"},
        tmp_path / "agentes",
    )

    assert env["NATS_URL"] == "nats://127.0.0.1:4222"
    assert env["LLM_PROXY_URL"] == "http://127.0.0.1:5100"
    assert env["POSTGRES_PASSWORD"] == "pw"
    assert env["AGENT_WORKSPACE_ROOT"] == str(tmp_path / "agentes")
    # The graph is optional; NATS is not, so it must not be disabled.
    assert "NATS_DISABLED" not in env


def test_the_agents_folder_explains_itself(tmp_path):
    folder = run_fusion._ensure_agents_dir(tmp_path / "agentes")

    assert folder.is_dir()
    assert "Agentes" in (folder / "LEEME.md").read_text(encoding="utf-8")
    ignore = (folder / ".gitignore").read_text(encoding="utf-8")
    assert "*" in ignore and "!LEEME.md" in ignore


def test_the_agents_folder_is_reusable(tmp_path):
    first = run_fusion._ensure_agents_dir(tmp_path / "agentes")
    (first / "LEEME.md").write_text("mío", encoding="utf-8")

    again = run_fusion._ensure_agents_dir(tmp_path / "agentes")

    assert again == first
    assert (first / "LEEME.md").read_text(encoding="utf-8") == "mío"


def test_compose_only_starts_what_the_backend_needs(tmp_path, monkeypatch):
    log = tmp_path / "docker.log"
    _fake_docker(tmp_path, log=log)
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))

    docker = run_fusion._docker_cli()
    assert docker is not None
    result = run_fusion._compose(docker, "up", "-d", *run_fusion.FULL_SERVICES)

    assert result.returncode == 0
    # The first line is the `docker info` probe that proves a daemon answers.
    recorded = log.read_text(encoding="utf-8").strip().splitlines()[-1].split()
    assert recorded == ["compose", "up", "-d", "postgres", "nats", "llm-proxy"]
    # The backend runs natively: its container and the React frontend are out.
    assert "backend" not in recorded and "frontend" not in recorded


def test_a_failed_compose_is_reported(tmp_path, monkeypatch, capsys):
    _fake_docker(tmp_path, compose_exit=1)
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))

    started = run_fusion._start_full_stack(run_fusion._docker_cli(), wait=1.0)

    assert started is False
    assert "docker compose no pudo" in capsys.readouterr().err


def test_services_that_never_open_their_port_are_reported(tmp_path, monkeypatch, capsys):
    _fake_docker(tmp_path)
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    # The answer must not depend on which ports this machine happens to have
    # open: the fake Docker never starts anything.
    monkeypatch.setattr(run_fusion, "_wait_tcp", lambda *_a, **_kw: False)

    started = run_fusion._start_full_stack(run_fusion._docker_cli(), wait=0.5)

    assert started is False
    assert "no abrió el puerto" in capsys.readouterr().err


def test_a_published_port_with_a_dead_proxy_inside_is_reported(
    tmp_path, monkeypatch, capsys
):
    """Docker keeps 5100 published after the app crashes; that is not a proxy."""
    _fake_docker(tmp_path)
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    monkeypatch.setattr(run_fusion, "_wait_tcp", lambda *_a, **_kw: True)
    monkeypatch.setattr(run_fusion, "_wait_proxy_catalogue", lambda *_a, **_kw: False)

    started = run_fusion._start_full_stack(run_fusion._docker_cli(), wait=0.5)

    assert started is False
    assert "el proxy no responde" in capsys.readouterr().err


def test_without_docker_the_full_mode_explains_itself(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PATH", str(tmp_path / "vacio"))

    code = run_fusion.main(["--completa", "--no-browser"])

    assert code == 1
    err = capsys.readouterr().err
    assert "necesita Docker" in err
    assert "sin -Completa" in err


def test_running_the_launcher_in_a_test_leaves_the_tree_alone(tmp_path, monkeypatch):
    env_before = (REAL_FACTORY / ".env").exists()
    agents_before = REAL_AGENTS_DIR.exists()
    monkeypatch.setenv("PATH", str(tmp_path / "vacio"))

    assert run_fusion.main(["--completa", "--no-browser"]) == 1

    assert (tmp_path / "agentes").is_dir()
    assert "JWT_SECRET_KEY=" in (tmp_path / "la-fabrique" / ".env").read_text(encoding="utf-8")
    assert (REAL_FACTORY / ".env").exists() == env_before
    assert REAL_AGENTS_DIR.exists() == agents_before


def test_secrets_are_generated_once_and_comments_survive(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("# ajustes\nAUTH_REQUIRED=false\n", encoding="utf-8")
    monkeypatch.setattr(run_fusion, "FACTORY", tmp_path)
    monkeypatch.setattr(run_fusion, "ASSISTANT", tmp_path / "asistente")

    first = run_fusion._ensure_full_secrets()
    second = run_fusion._ensure_full_secrets()

    assert first["POSTGRES_PASSWORD"]
    assert first["JWT_SECRET_KEY"]
    assert second["POSTGRES_PASSWORD"] == first["POSTGRES_PASSWORD"]
    written = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "# ajustes" in written
    assert "AUTH_REQUIRED=false" in written
    assert written.count("POSTGRES_PASSWORD") == 1


def test_the_proxy_reuses_the_assistant_key(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("", encoding="utf-8")
    config = tmp_path / "asistente" / "config"
    config.mkdir(parents=True)
    (config / "api_keys.json").write_text(
        json.dumps({"gemini_api_key": "clave-del-asistente"}), encoding="utf-8"
    )
    monkeypatch.setattr(run_fusion, "FACTORY", tmp_path)
    monkeypatch.setattr(run_fusion, "ASSISTANT", tmp_path / "asistente")

    values = run_fusion._ensure_full_secrets()

    assert values["GEMINI_API_KEY"] == "clave-del-asistente"


def test_a_single_gemini_key_overrides_every_agent_model(tmp_path):
    env = run_fusion._full_env(
        {"GEMINI_API_KEY": "clave", "POSTGRES_PASSWORD": "pw"}, tmp_path / "agentes"
    )

    # Qwen/DeepSeek ids in the role map would be rejected as "unknown model".
    assert env["AGENT_MODEL"] == "gemini-flash-latest"


def test_a_nemotron_key_becomes_the_agents_model(tmp_path):
    env = run_fusion._full_env(
        {"NEBIUS_API_KEY": "nvapi-x", "POSTGRES_PASSWORD": "pw"}, tmp_path / "agentes"
    )

    # El id retirado (410) que traía la fábrica ya no se usa.
    assert env["AGENT_MODEL"] == "nvidia/nemotron-3-ultra-550b-a55b"


def test_extra_provider_keys_leave_the_role_map_alone(tmp_path):
    env = run_fusion._full_env(
        {"GEMINI_API_KEY": "clave", "QWEN_API_KEY": "otra", "POSTGRES_PASSWORD": "pw"},
        tmp_path / "agentes",
    )

    assert "AGENT_MODEL" not in env


def test_an_explicit_agent_model_is_respected(tmp_path):
    env = run_fusion._full_env(
        {"GEMINI_API_KEY": "clave", "AGENT_MODEL": "gemini-3.1-pro-preview"},
        tmp_path / "agentes",
    )

    assert env["AGENT_MODEL"] == "gemini-3.1-pro-preview"


def test_new_assistant_config_keeps_existing_settings(tmp_path, monkeypatch):
    """Wiring Asistente B1 must not wipe the rest of its config file."""
    monkeypatch.setenv("B1_HOME", str(tmp_path))
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"language": "en", "stt_model": "medium"}), encoding="utf-8")

    run_fusion._configure_new_assistant(
        "http://127.0.0.1:8123", "clave-voz", 9, proxy_url="http://127.0.0.1:5100/v1"
    )

    data = json.loads(config.read_text(encoding="utf-8"))
    assert data["factory_url"] == "http://127.0.0.1:8123"
    assert data["voice_key"] == "clave-voz"
    assert data["factory_company_id"] == 9
    assert data["model_base_url"] == "http://127.0.0.1:5100/v1"
    assert data["model"] == run_fusion.NEW_ASSISTANT_MODEL
    assert data["language"] == "en"
    assert data["stt_model"] == "medium"


def test_new_assistant_config_survives_a_corrupt_file(tmp_path, monkeypatch):
    monkeypatch.setenv("B1_HOME", str(tmp_path))
    (tmp_path / "config.json").write_text("{ roto", encoding="utf-8")

    run_fusion._configure_new_assistant("http://127.0.0.1:8123", "k", None)

    data = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert data["voice_key"] == "k"
    assert "model_base_url" not in data


def test_new_assistant_starts_as_a_module(monkeypatch):
    calls = []

    class _Proc:
        returncode = 0

        def poll(self):
            return 0

    monkeypatch.setattr(
        run_fusion.subprocess, "Popen", lambda cmd, **kw: calls.append((cmd, kw)) or _Proc()
    )
    run_fusion._start_new_assistant(["--orb"], "/usr/bin/python3", {"A": "1"})

    cmd, kwargs = calls[0]
    assert cmd == ["/usr/bin/python3", "-m", "b1", "--orb"]
    assert Path(kwargs["cwd"]) == run_fusion.NEW_ASSISTANT
    assert kwargs["env"] == {"A": "1"}


class _ModelsHandler(BaseHTTPRequestHandler):
    """A proxy that answers its catalogue, like ``llm-proxy`` does."""

    models: list = ["nvidia/nemotron-3-ultra-550b-a55b"]

    def do_GET(self):  # noqa: N802 - http.server API
        if self.path == "/v1/models":
            body = json.dumps({"models": self.models}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, *_args):
        pass


def test_a_proxy_is_only_trusted_once_it_lists_models(monkeypatch):
    """A published port is not a proxy: Docker keeps it open after a crash."""
    server, url = _serve(_ModelsHandler)
    try:
        assert run_fusion._proxy_answers(url) is True

        monkeypatch.setattr(_ModelsHandler, "models", [])
        assert run_fusion._proxy_answers(url) is False
    finally:
        server.shutdown()


def test_an_empty_port_is_not_a_proxy():
    assert run_fusion._proxy_answers("http://127.0.0.1:9", timeout=0.5) is False


def test_the_catalogue_wait_gives_up_instead_of_hanging(monkeypatch):
    monkeypatch.setattr(run_fusion, "_proxy_answers", lambda **_kw: False)
    started = time.monotonic()
    assert run_fusion._wait_proxy_catalogue(5.0) is False
    assert time.monotonic() - started < 15


def test_the_first_provider_key_present_is_reported():
    assert run_fusion._provider_key({"NVIDIA_API_KEY": "nvapi-x"}) == "NVIDIA_API_KEY"
    assert run_fusion._provider_key(
        {"NVIDIA_API_KEY": "  ", "NEBIUS_API_KEY": "k"}
    ) == "NEBIUS_API_KEY"
    assert run_fusion._provider_key({}) == ""


def test_the_proxy_uses_an_interpreter_that_can_import_flask(tmp_path, monkeypatch):
    """``.venv-backend`` has no Flask: the proxy needs its own interpreter."""
    venv = tmp_path / "llm-proxy-venv"
    python = venv.joinpath(*run_fusion._venv_layout()[0])
    python.parent.mkdir(parents=True)
    python.write_text("", encoding="utf-8")
    monkeypatch.setattr(run_fusion, "PROXY_VENV", venv)
    monkeypatch.setattr(
        run_fusion, "_can_import", lambda py, mod: Path(py) == python
    )

    picked = run_fusion._proxy_python(argparse.Namespace(backend_python=None))

    assert Path(picked) == python


def test_without_any_capable_interpreter_the_proxy_venv_is_built(monkeypatch):
    built: list[str] = []
    monkeypatch.setattr(run_fusion, "_can_import", lambda *_a: False)
    monkeypatch.setattr(run_fusion, "_poetry_python", lambda *_a: None)
    monkeypatch.setattr(
        run_fusion, "_build_proxy_venv", lambda: built.append("si") or "python-x"
    )

    assert run_fusion._proxy_python(argparse.Namespace(backend_python=None)) == "python-x"
    assert built == ["si"]


def test_a_handoff_needs_the_key():
    assert run_fusion._desktop_handoff("http://127.0.0.1:9", "") == ""


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_the_env_file_is_private_from_its_first_byte(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("# ajustes\n", encoding="utf-8")
    env_file.chmod(0o644)
    monkeypatch.setattr(run_fusion, "FACTORY", tmp_path)

    run_fusion._write_env_file({"JWT_SECRET_KEY": "s"})

    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600
    assert "JWT_SECRET_KEY=s" in env_file.read_text(encoding="utf-8")
