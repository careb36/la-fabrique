"""Tests for the fusion launcher: env handling and backend detection."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import run_fusion


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
    assert env["AUTH_REQUIRED"] == "false"
    assert env["VOICE_API_KEY"] == "k"


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
