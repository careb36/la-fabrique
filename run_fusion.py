#!/usr/bin/env python3
"""Fusion — one entry point for the voice assistant and the factory.

``la-fabrique`` is the AI software factory (FastAPI). ``profesor3`` is MARK LVI,
the desktop voice assistant. This launcher runs both as one program:

1. loads ``la-fabrique/.env`` (already-set environment variables win);
2. starts the backend on 127.0.0.1:8000 if nothing is answering there;
3. with no Postgres configured, points it at a local SQLite file so the
   factory works with zero infrastructure;
4. bootstraps a default company the first time;
5. writes the backend URL + ``VOICE_API_KEY`` into the assistant's plugin
   settings, so "la fábrica" works by voice with no manual step;
6. starts the assistant, and stops both on Ctrl+C.

Examples::

    python run_fusion.py                     # backend + assistant
    python run_fusion.py --backend-only      # just the factory API
    python run_fusion.py --assistant-only    # assistant against a running API
    python run_fusion.py --url http://mi-servidor:8000 --no-config
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import webbrowser
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
FACTORY = ROOT / "la-fabrique"
BACKEND = FACTORY / "backend"
ASSISTANT = ROOT / "profesor3"
DEFAULT_PORT = 8000
DEFAULT_COMPANY = "Mi fábrica"
# An assistant that dies this fast never showed a window: usually a missing
# GUI, audio device or Gemini key, so the traceback above is the real answer.
ASSISTANT_CRASH_SECONDS = 20.0
# The assistant's panel is the window a launch should show: it wears the new
# identity and embeds the factory's own UI in its «Fábrica» tab, signed in
# through /fabrica. The factory's UI is the fallback when the Qt side never
# comes up; the panel port is fixed by the dashboard (8770, or 8771 with the
# optional HTTPS).
ASSISTANT_PANEL_URL = "http://127.0.0.1:8770"
PANEL_APP_MARKER = "tutor-virtual-a1"   # what the dashboard's /health calls itself
PANEL_WAIT_SECONDS = 20.0              # then settle for the factory UI

DEFAULT_AGENTS = [
    {"name": "Atlas", "role": "PO", "seniority": "Senior", "specialty": "product"},
    {"name": "Nova", "role": "Architect", "seniority": "Senior", "specialty": "architecture"},
    {"name": "Delta", "role": "Developer", "seniority": "Senior", "specialty": "backend"},
    {"name": "Iris", "role": "QA", "seniority": "Senior", "specialty": "testing"},
]


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip("'\"")
        if key.strip():
            values[key.strip()] = value
    return values


def _child_env(
    voice_key: str, use_sqlite: bool, announce: bool = True
) -> dict[str, str]:
    env = dict(os.environ)
    for key, value in _parse_env_file(FACTORY / ".env").items():
        env.setdefault(key, value)
    # The children inherit our console; without this their accents would go
    # through the ANSI code page and either crash or print mojibake.
    env.setdefault("PYTHONIOENCODING", "utf-8:replace")
    env.setdefault("PYTHONUTF8", "1")

    if voice_key:
        env["VOICE_API_KEY"] = voice_key
    else:
        env.setdefault("VOICE_API_KEY", "")
    if use_sqlite and not env.get("DATABASE_URL") and not env.get("POSTGRES_PASSWORD"):
        db_dir = FACTORY / ".fusion"
        db_dir.mkdir(parents=True, exist_ok=True)
        env["DATABASE_URL"] = f"sqlite:///{(db_dir / 'factory.db').as_posix()}"
        # The graph backend is optional and absent in a desktop install;
        # failing fast keeps startup at ~2 s instead of a bolt timeout.
        env.setdefault("NEO4J_DISABLED", "true")
        # Same for the broker: without it the connector retries forever and
        # prints a traceback every few seconds on the user's console.
        env.setdefault("NATS_DISABLED", "true")
    # The UI is a web app, so the browser needs a session even on a desktop
    # instalment. _ensure_app_secrets() always writes a signing key; the session
    # itself is minted from the voice key by /v1/auth/desktop, so nobody types a
    # password and the factory is never left open anonymously.
    env.setdefault("AUTH_REQUIRED", "true")
    env.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "1440")
    # The assistant's dashboard embeds the factory's own UI in an iframe, which
    # is a different origin: `X-Frame-Options: DENY` (the API default) left that
    # panel blank. Loopback with any port, because the panel moves to the next
    # free port when 8770 is taken.
    env.setdefault("FRAME_ANCESTORS", " ".join(
        f"{scheme}://{host}:*"
        for host in ("127.0.0.1", "localhost")
        for scheme in ("http", "https")))
    if announce and use_sqlite:
        print(
            "⚠  Modo local sin NATS: la voz mueve el tablero (crear, despachar, "
            "pausar, aprobar), pero los agentes no ejecutan tareas hasta que "
            "haya NATS y un modelo. Para eso: cd la-fabrique && docker compose up -d",
            flush=True,
        )
    return env


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _request(
    url: str,
    payload: dict | None = None,
    key: str = "",
    timeout: float = 10,
    bearer: str = "",
) -> tuple[int, dict | None]:
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if key:
        headers["X-Voice-Key"] = key
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    request = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", "replace")
            return response.status, json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(body) if body else None
        except ValueError:
            return exc.code, None
    except (urllib.error.URLError, OSError, ValueError):
        return 0, None


def _wait_until_up(url: str, timeout: float) -> bool:
    """Wait for *this* factory, not for any service that answers on the port."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        status, body = _request(f"{url}/v1/capabilities", timeout=2)
        if status == 200 and isinstance(body, dict) and "auth_required" in body:
            return True
        time.sleep(0.5)
    return False


def _is_local(url: str) -> bool:
    return (urlsplit(url).hostname or "") in {"127.0.0.1", "localhost", "::1"}


def _desktop_session(url: str, key: str) -> tuple[str, int]:
    """Trade the voice key for a web session, so the UI opens signed in.

    Returns ``(token, expires_in)``; an empty token means the browser will ask
    for a password, which the packaged product never sets.
    """
    status, body = _request(f"{url}/v1/auth/desktop", payload={}, key=key)
    if status == 200 and body and body.get("access_token"):
        return str(body["access_token"]), int(body.get("expires_in") or 3600)
    print(
        f"⚠  No pude abrir sesión para la interfaz (HTTP {status}). "
        "Se abrirá la pantalla de acceso.",
        flush=True,
    )
    return "", 0


def _ensure_company(url: str, key: str, name: str, token: str = "") -> int | None:
    status, body = _request(f"{url}/v1/voice/status", key=key)
    if status == 200 and body and body.get("ok"):
        return (body.get("data") or {}).get("company", {}).get("id")
    if status != 200:
        print(f"⚠  No pude leer el estado de la fábrica (HTTP {status}).", flush=True)

    status, body = _request(
        f"{url}/v1/init_company",
        {"company_name": name, "agents": DEFAULT_AGENTS},
        key="",
        timeout=30,
        bearer=token,
    )
    if status in (200, 201) and body:
        company_id = body.get("company_id") or (body.get("company") or {}).get("id")
        print(f"✓  Empresa creada: {name} (id {company_id})", flush=True)
        return company_id
    print(
        f"⚠  No pude crear la empresa automáticamente (HTTP {status}). "
        "Créala en la interfaz web y vuelve a arrancar.",
        flush=True,
    )
    return None


# ---------------------------------------------------------------------------
# Assistant configuration
# ---------------------------------------------------------------------------


def _configure_assistant(url: str, key: str, company_id: int | None) -> None:
    config = ASSISTANT / "config" / "api_keys.json"
    config.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {}
    if config.is_file():
        try:
            data = json.loads(config.read_text(encoding="utf-8"))
        except ValueError:
            data = {}
    plugin = data.setdefault("plugin_config", {}).setdefault("fabrica", {})
    plugin["base_url"] = url
    plugin["api_key"] = key
    if company_id is not None:
        plugin["company_id"] = str(company_id)
    plugin.setdefault("idioma", "auto")
    config.write_text(json.dumps(data, indent=4), encoding="utf-8")
    try:
        config.chmod(0o600)
    except OSError:
        pass
    print("✓  Plugin FÁBRICA configurado en el asistente.", flush=True)


# ---------------------------------------------------------------------------
# Processes
# ---------------------------------------------------------------------------


def _configure_console() -> None:
    """Windows consoles are cp1252 by default and choke on «», ✓ and ⚠."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


def _can_import(python: str, module: str) -> bool:
    try:
        result = subprocess.run(
            [python, "-c", f"import {module}"],
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _venv_layout() -> tuple[tuple[str, ...], ...]:
    """Interpreter paths inside a venv, for the platform we are running on.

    A Windows venv has ``Scripts\\python.exe``; a POSIX one has ``bin/python``.
    Mixing them made the launcher try to run a non-executable path in cmd.exe.
    """
    if os.name == "nt":
        return (("Scripts", "python.exe"),)
    return (("bin", "python"), ("bin", "python3"))


def _venv_pythons(venv_dirs: list[Path]):
    for venv_dir in venv_dirs:
        for parts in _venv_layout():
            candidate = venv_dir.joinpath(*parts)
            if candidate.is_file():
                yield str(candidate)


def _poetry_python(project: Path) -> str | None:
    """Interpreter of the venv Poetry already built for the project, if any.

    ``poetry install`` puts its venv in the Poetry cache by default, so the
    launcher cannot find it by looking at the project directory.
    """
    poetry = shutil.which("poetry")
    if not poetry:
        return None
    try:
        result = subprocess.run(
            [poetry, "env", "info", "--path"],
            cwd=str(project),
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    env_dir = Path(result.stdout.strip())
    candidate = env_dir / ("Scripts" if os.name == "nt" else "bin") / (
        "python.exe" if os.name == "nt" else "python"
    )
    return str(candidate) if candidate.is_file() else None


def _pick_python(
    explicit: str | None,
    venv_dirs: list[Path],
    module: str,
    poetry_project: Path | None = None,
) -> str:
    """The interpreter that can import ``module``: flag, local venvs, Poetry, ours."""
    if explicit:
        if Path(explicit).exists() or shutil.which(explicit):
            return explicit
        print(
            f"⚠  El intérprete indicado no existe: {explicit}. Busco otro.",
            file=sys.stderr,
        )
    for candidate in _venv_pythons(venv_dirs):
        if _can_import(candidate, module):
            return candidate
    if poetry_project is not None:
        poetry_python = _poetry_python(poetry_project)
        if poetry_python and _can_import(poetry_python, module):
            return poetry_python
    return sys.executable


def _port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        return probe.connect_ex((host, port)) == 0


def _choose_port(host: str, start: int, tries: int = 20) -> int | None:
    for port in range(start, start + tries):
        if not _port_in_use(host, port):
            return port
    return None


def _start_backend(
    url: str, env: dict[str, str], port: int, python: str
) -> subprocess.Popen:
    print(f"→  Arrancando backend en {url} …", flush=True)
    # The backend imports both ``app.*`` and its own top-level modules
    # (``config``, ``routers`` …); the Dockerfile sets the same two entries.
    env = dict(env)
    paths = [str(BACKEND), str(BACKEND / "app")]
    if env.get("PYTHONPATH"):
        paths.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(paths)
    return subprocess.Popen(
        [
            python,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "info",
        ],
        cwd=str(BACKEND),
        env=env,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )


def _start_assistant(
    extra: list[str], python: str, env: dict[str, str] | None = None
) -> subprocess.Popen:
    entry = ASSISTANT / "main.py"
    print("→  Arrancando el asistente …", flush=True)
    return subprocess.Popen(
        [python, str(entry), *extra],
        cwd=str(ASSISTANT),
        env=dict(env or os.environ),
    )


def _stop(process: subprocess.Popen | None, name: str) -> None:
    if process is None or process.poll() is not None:
        return
    print(f"→  Cerrando {name} …", flush=True)
    try:
        process.terminate()
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Modo fábrica completa
# ---------------------------------------------------------------------------

AGENTS_DIR = ROOT / "agentes"
# Only the services the backend needs. It runs natively here, so its own
# container is not started; jaeger stays out until telemetry is configured.
FULL_SERVICES = ("postgres", "nats", "llm-proxy")
FULL_PORTS = (("postgres", 5432), ("nats", 4222), ("llm-proxy", 5100))
AGENTS_README = """# Agentes

Aquí escriben los agentes de la fábrica cuando el sprint se despacha por voz:
un fichero por entrega, en el proyecto que nombre la tarea. La carpeta se crea
sola y `arrancar.ps1 -Completa` la pasa como `AGENT_WORKSPACE_ROOT` al backend,
así que es el único sitio del disco que el demonio tiene permitido escribir.

Se puede mover con `-Agentes C:\\ruta\\a\\mi\\carpeta`, y el contenido está en
`.gitignore`: lo generado no se versiona, el producto sí.
"""


def _ensure_agents_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    ignore = path / ".gitignore"
    if not ignore.exists():
        ignore.write_text("*\n!.gitignore\n!LEEME.md\n", encoding="utf-8")
    readme = path / "LEEME.md"
    if not readme.exists():
        readme.write_text(AGENTS_README, encoding="utf-8")
    return path


def _docker_cli() -> str | None:
    """The docker binary, but only if a daemon answers behind it."""
    docker = shutil.which("docker")
    if not docker:
        return None
    try:
        probe = subprocess.run(
            [docker, "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return docker if probe.returncode == 0 else None


def _compose(docker: str, *args: str, timeout: float = 1800):
    return subprocess.run(
        [docker, "compose", *args],
        cwd=str(FACTORY),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _write_env_file(values: dict[str, str]) -> None:
    """Merge *values* into ``la-fabrique/.env`` without dropping the comments."""
    path = FACTORY / ".env"
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    written: set[str] = set()
    merged: list[str] = []
    for raw in lines:
        name, sep, _ = raw.partition("=")
        name = name.strip()
        if sep and name in values:
            merged.append(f"{name}={values[name]}")
            written.add(name)
        else:
            merged.append(raw)
    merged.extend(f"{name}={value}" for name, value in values.items() if name not in written)
    path.write_text("\n".join(merged).rstrip("\n") + "\n", encoding="utf-8")


def _assistant_gemini_key() -> str:
    """The key the assistant already uses, so the proxy does not ask for another."""
    config = ASSISTANT / "config" / "api_keys.json"
    try:
        data = json.loads(config.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str(data.get("gemini_api_key") or "").strip()


def _ensure_app_secrets() -> dict[str, str]:
    """The signing key the web UI's session needs, in both modes.

    It is generated once and kept, so a restart does not log the browser out,
    and it is the same secret Docker gets in full mode.
    """
    values = _parse_env_file(FACTORY / ".env")
    if values.get("JWT_SECRET_KEY"):
        return values
    _write_env_file({"JWT_SECRET_KEY": secrets.token_urlsafe(32)})
    print("✓  Clave de sesión de la interfaz creada en la-fabrique/.env.", flush=True)
    return _parse_env_file(FACTORY / ".env")


def _ensure_full_secrets() -> dict[str, str]:
    """Fill what ``docker compose`` requires, once, in ``la-fabrique/.env``."""
    values = _parse_env_file(FACTORY / ".env")
    add: dict[str, str] = {}
    if not values.get("POSTGRES_USER"):
        add["POSTGRES_USER"] = "factory"
    if not values.get("POSTGRES_DB"):
        add["POSTGRES_DB"] = "factory"
    if not values.get("POSTGRES_PASSWORD"):
        add["POSTGRES_PASSWORD"] = secrets.token_urlsafe(24)
    if not values.get("GEMINI_API_KEY"):
        key = _assistant_gemini_key()
        if key:
            add["GEMINI_API_KEY"] = key
    if not values.get("JWT_SECRET_KEY"):
        add["JWT_SECRET_KEY"] = secrets.token_urlsafe(32)
    if add:
        _write_env_file(add)
        print(
            "✓  Secretos de la infraestructura en la-fabrique/.env "
            f"({', '.join(sorted(add))}).",
            flush=True,
        )
    return {**values, **add}


def _wait_tcp(port: int, timeout: float, host: str = "127.0.0.1") -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _port_in_use(host, port):
            return True
        time.sleep(1.0)
    return False


def _start_full_stack(docker: str, wait: float) -> bool:
    print(
        "→  Modo fábrica completa: levantando Postgres, NATS y el proxy de modelos …",
        flush=True,
    )
    result = _compose(docker, "up", "-d", *FULL_SERVICES)
    if result.returncode != 0:
        output = (result.stderr or result.stdout or "").strip().splitlines()
        print("✗  docker compose no pudo levantar la infraestructura:", file=sys.stderr)
        for line in output[-12:]:
            print(f"   {line}", file=sys.stderr)
        return False
    for name, port in FULL_PORTS:
        if not _wait_tcp(port, wait):
            print(
                f"✗  {name} no abrió el puerto {port} en {wait:.0f}s. "
                "Revisa `docker compose logs` en la-fabrique.",
                file=sys.stderr,
            )
            return False
        print(f"✓  {name} escuchando en 127.0.0.1:{port}", flush=True)
    return True


def _agent_model(secrets: dict[str, str]) -> str:
    """One model id for every role when the install only has the Gemini key.

    The factory's role map mixes Qwen and DeepSeek ids; a desktop install that
    only carries the assistant's Gemini key would have most roles rejected by
    the proxy as "unknown model", so those tasks end blocked. Empty means
    "leave the role map alone", which is right as soon as a second key exists.
    """
    explicit = (secrets.get("AGENT_MODEL") or "").strip()
    if explicit:
        return explicit
    if secrets.get("NEBIUS_API_KEY"):
        # Nemotron: one id for every role, like the Gemini case. Kept in step
        # with profesor3/core/fabrica_env.DEFAULT_NEMOTRON_MODEL — the old
        # llama-3.3-nemotron-super-49b-v1 was retired (410 Gone) and every
        # task came back blocked.
        return "nvidia/nemotron-3-ultra-550b-a55b"
    if secrets.get("QWEN_API_KEY") or secrets.get("DEEPSEEK_API_KEY"):
        return ""
    return "gemini-flash-latest" if secrets.get("GEMINI_API_KEY") else ""


def _full_env(secrets: dict[str, str], agents_dir: Path) -> dict[str, str]:
    """Backend environment for the complete factory, over the local one."""
    env = {
        "POSTGRES_HOST": "127.0.0.1",
        "POSTGRES_PORT": "5432",
        "POSTGRES_USER": secrets.get("POSTGRES_USER", "factory"),
        "POSTGRES_PASSWORD": secrets.get("POSTGRES_PASSWORD", ""),
        "POSTGRES_DB": secrets.get("POSTGRES_DB", "factory"),
        "NATS_URL": "nats://127.0.0.1:4222",
        "LLM_PROXY_URL": "http://127.0.0.1:5100",
        "NEO4J_DISABLED": "true",
        "AGENT_WORKSPACE_ROOT": str(agents_dir),
    }
    model = _agent_model(secrets)
    if model:
        env["AGENT_MODEL"] = model
    return env


def _start_daemon(python: str, env: dict[str, str], agents_dir: Path) -> subprocess.Popen:
    """The workspace daemon, native, writing only inside the agents' folder."""
    print(f"→  Arrancando el demonio de trabajo sobre {agents_dir} …", flush=True)
    daemon_env = dict(env)
    daemon_env["WORKSPACE_ROOT"] = str(agents_dir)
    daemon_env.setdefault("PYTHONUNBUFFERED", "1")
    return subprocess.Popen(
        [python, str(FACTORY / "vscode-daemon" / "daemon.py")],
        cwd=str(FACTORY / "vscode-daemon"),
        env=daemon_env,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )


def _panel_url(url: str, token: str, expires_in: int) -> str:
    """The UI's address, with the session handed over in the fragment.

    The fragment is never sent to the server and `main.tsx` scrubs it from the
    address bar as soon as it is adopted, so the token does not sit in history.
    """
    base = f"{url.rstrip('/')}/"
    if not token:
        return base
    return f"{base}#sesion={token}&caduca={expires_in}"


def _panel_answers(url: str = ASSISTANT_PANEL_URL,
                   timeout: float = 2.0) -> bool:
    """Is the assistant's dashboard listening there?

    `/health` names the app, so a stranger that happens to hold 8770 is never
    mistaken for the panel.
    """
    try:
        with urllib.request.urlopen(f"{url}/health", timeout=timeout) as response:
            if response.status != 200:
                return False
            data = json.loads(response.read().decode("utf-8", "replace"))
        return str((data or {}).get("app") or "") == PANEL_APP_MARKER
    except Exception:
        return False


def _open_panel(url: str, token: str = "", expires_in: int = 0,
                timeout: float = 45.0,
                panel_timeout: float = PANEL_WAIT_SECONDS) -> None:
    """Open the assistant's panel, or the factory when it never comes up.

    The panel is the product's face: it carries the new identity and embeds
    the factory in its «Fábrica» tab, so it goes first. It starts with the
    assistant, hence the polling. The factory's own UI is the fallback for a
    launch where the Qt side refused to start — a board you can use beats an
    address that answers nothing.
    """
    panel_deadline = time.monotonic() + max(0.0, min(panel_timeout, timeout))
    while time.monotonic() < panel_deadline:
        if _panel_answers():
            webbrowser.open(f"{ASSISTANT_PANEL_URL}/")
            print("ℹ  Panel del asistente abierto — la fábrica está en «Fábrica».",
                  flush=True)
            return
        time.sleep(1.0)

    target = _panel_url(url, token, expires_in)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{url.rstrip('/')}/", timeout=2) as response:
                if response.status == 200:
                    webbrowser.open(target)
                    return
        except Exception:
            pass
        time.sleep(1.0)
    print(
        "⚠  No pude abrir el navegador. Dímelo por voz: «abre la fábrica».",
        flush=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.getenv("FUSION_URL"))
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("FUSION_PORT", str(DEFAULT_PORT))),
        help="puerto del backend cuando no se pasa --url",
    )
    parser.add_argument("--company", default=os.getenv("FUSION_COMPANY", DEFAULT_COMPANY))
    parser.add_argument("--voice-key", default=os.getenv("VOICE_API_KEY", ""))
    parser.add_argument("--backend-only", action="store_true")
    parser.add_argument("--assistant-only", action="store_true")
    parser.add_argument(
        "--backend-python",
        default=os.getenv("FUSION_BACKEND_PYTHON"),
        help="interpreter with the backend's dependencies (default: auto-detect)",
    )
    parser.add_argument(
        "--assistant-python",
        default=os.getenv("FUSION_ASSISTANT_PYTHON"),
        help="interpreter with the assistant's dependencies (default: auto-detect)",
    )
    parser.add_argument("--no-config", action="store_true", help="do not touch the assistant's settings")
    parser.add_argument("--no-bootstrap", action="store_true", help="do not create a company")
    parser.add_argument("--wait", type=float, default=90.0, help="seconds to wait for the backend")
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="do not open the factory board in the browser",
    )
    parser.add_argument(
        "--completa",
        action="store_true",
        help=(
            "fábrica completa: levanta Postgres, NATS y el proxy de modelos con "
            "Docker y arranca el demonio, para que los agentes ejecuten y escriban"
        ),
    )
    parser.add_argument(
        "--agentes",
        default=os.getenv("FUSION_AGENTS_DIR"),
        help=f"carpeta donde escriben los agentes (por defecto: {AGENTS_DIR})",
    )
    parser.add_argument(
        "--espera-infra",
        type=float,
        default=240.0,
        help="segundos de espera para cada servicio de Docker",
    )
    parser.add_argument("assistant_args", nargs="*", help="extra arguments for the assistant")
    args = parser.parse_args(argv)
    _configure_console()

    explicit_url = args.url is not None
    url = (args.url or f"http://127.0.0.1:{args.port}").rstrip("/")
    agents_dir = _ensure_agents_dir(
        Path(args.agentes).expanduser() if args.agentes else AGENTS_DIR
    )
    full = args.completa and not args.assistant_only
    # Sin SQLite cuando la fábrica es completa: Postgres y NATS vienen de Docker.
    use_sqlite = _is_local(url) and not full
    app_secrets = _ensure_app_secrets()
    env = _child_env(args.voice_key, use_sqlite, announce=not args.assistant_only)
    if app_secrets.get("JWT_SECRET_KEY"):
        env["JWT_SECRET_KEY"] = app_secrets["JWT_SECRET_KEY"]
    key = args.voice_key or env.get("VOICE_API_KEY") or secrets.token_urlsafe(32)
    env["VOICE_API_KEY"] = key

    backend: subprocess.Popen | None = None
    assistant: subprocess.Popen | None = None
    daemon: subprocess.Popen | None = None
    backend_python: str | None = None

    def _shutdown(_signum=None, _frame=None):
        _stop(assistant, "el asistente")
        _stop(daemon, "el demonio")
        _stop(backend, "el backend")
        raise SystemExit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        if full:
            docker = _docker_cli()
            if docker is None:
                print(
                    "✗  El modo fábrica completa necesita Docker, y aquí no hay "
                    "ningún demonio que responda.\n"
                    "   Windows: instala Docker Desktop y ábrelo "
                    "(https://docs.docker.com/desktop/setup/install/windows-install/).\n"
                    "   Sin Docker, arranca sin -Completa: el tablero y la voz "
                    "funcionan, pero los agentes no ejecutan.",
                    file=sys.stderr,
                )
                return 1
            if not _start_full_stack(docker, args.espera_infra):
                return 1
            env.update(_full_env(_ensure_full_secrets(), agents_dir))
            # El modo local deja DATABASE_URL en SQLite; aquí manda Postgres.
            env.pop("DATABASE_URL", None)
            env.pop("NATS_DISABLED", None)
            print(
                f"✓  Infraestructura lista. Los agentes escribirán en {agents_dir}",
                flush=True,
            )

        key_ok = True
        if not args.assistant_only:
            already_up = _wait_until_up(url, timeout=1.0)
            if already_up:
                print(f"✓  Ya hay una fábrica respondiendo en {url}.", flush=True)
                status, _ = _request(f"{url}/v1/voice/ping", key=key, timeout=5)
                if status == 401 and not args.voice_key:
                    key_ok = False
                    print(
                        "⚠  Esa fábrica ya tenía otra VOICE_API_KEY. Pásame la "
                        "correcta con --voice-key o pon la misma en "
                        "la-fabrique/.env. No toco la configuración del asistente.",
                        flush=True,
                    )
            elif not _is_local(url):
                print(
                    f"✗  No hay fábrica en {url} y no puedo arrancar una "
                    "remota. Arráncala allí o usa una URL local.",
                    file=sys.stderr,
                )
                return 1
            else:
                parsed = urlsplit(url)
                host = parsed.hostname or "127.0.0.1"
                port = parsed.port or args.port
                # 8000 is the most contested port on a dev machine. If someone
                # else holds it (and is not the factory, we just checked), move
                # instead of failing to bind.
                if _port_in_use(host, port):
                    if explicit_url:
                        print(
                            f"✗  El puerto {port} está ocupado por otro programa. "
                            f"Prueba --url http://{host}:{port + 1} o, desde "
                            f"PowerShell, .\\arrancar.ps1 -Puerto {port + 1}.",
                            file=sys.stderr,
                        )
                        return 1
                    free = _choose_port(host, port + 1)
                    if free is None:
                        print(
                            f"✗  No encuentro un puerto libre a partir de {port}.",
                            file=sys.stderr,
                        )
                        return 1
                    print(
                        f"⚠  El puerto {port} está ocupado; uso {free}.",
                        flush=True,
                    )
                    port = free
                    url = f"http://{host}:{port}"

                backend_python = _pick_python(
                    args.backend_python,
                    [ROOT / ".venv-backend", BACKEND / ".venv", BACKEND / "venv"],
                    "fastapi",
                    poetry_project=BACKEND,
                )
                if not _can_import(backend_python, "fastapi"):
                    print(
                        f"✗  {backend_python} no tiene las dependencias del "
                        "backend. Lo más rápido en Windows es ejecutar:\n"
                        "     .\\arrancar.ps1 -Instalar\n"
                        "   En macOS/Linux: cd la-fabrique/backend && poetry install\n"
                        "   …o pasa --backend-python RUTA.",
                        file=sys.stderr,
                    )
                    return 1
                backend = _start_backend(url, env, port, backend_python)
                if not _wait_until_up(url, timeout=args.wait):
                    print(
                        "✗  El backend no arrancó. Revisa la salida de arriba "
                        "(dependencias del backend o el puerto ocupado).",
                        file=sys.stderr,
                    )
                    return 1
                print("✓  Fábrica en marcha.", flush=True)

        if full:
            daemon_python = backend_python or _pick_python(
                args.backend_python,
                [ROOT / ".venv-backend", BACKEND / ".venv", BACKEND / "venv"],
                "nats",
                poetry_project=BACKEND,
            )
            if not _can_import(daemon_python, "nats"):
                _stop(backend, "el backend")
                print(
                    f"✗  {daemon_python} no tiene nats-py, que el demonio necesita "
                    "para hablar con NATS. Ejecuta .\\arrancar.ps1 -Instalar.",
                    file=sys.stderr,
                )
                return 1
            daemon = _start_daemon(daemon_python, env, agents_dir)

        if args.assistant_only and not _wait_until_up(url, timeout=5.0):
            print(
                f"✗  No hay ninguna fábrica en {url}: no configuro el asistente "
                "para hablar con un servicio que no es la fábrica. Arranca el "
                "backend primero (python run_fusion.py --backend-only).",
                file=sys.stderr,
            )
            return 1

        session_token, session_ttl = ("", 0)
        if key_ok:
            session_token, session_ttl = _desktop_session(url, key)

        if not args.no_bootstrap:
            company_id = (
                _ensure_company(url, key, args.company, session_token)
                if key_ok else None
            )
        else:
            company_id = None

        env["FABRICA_URL"] = url
        env["FABRICA_API_KEY"] = key
        env["FABRICA_COMPANY_ID"] = str(company_id) if company_id else ""

        if not args.no_config and key_ok:
            _configure_assistant(url, key, company_id)

        if not args.backend_only:
            assistant_python = _pick_python(
                args.assistant_python,
                [ASSISTANT / ".venv", ASSISTANT / "venv"],
                "PyQt6",
            )
            if not _can_import(assistant_python, "PyQt6"):
                print(
                    f"✗  {assistant_python} no tiene las dependencias del "
                    "asistente. Instálalas con:\n"
                    f"     {assistant_python} -m pip install -r "
                    f"{ASSISTANT / 'requirements.txt'}\n"
                    "   (en Windows, usa pythonw para que no abra consola) y "
                    "vuelve a ejecutar, o pasa --assistant-python RUTA.",
                    file=sys.stderr,
                )
                return 1
            assistant = _start_assistant(args.assistant_args, assistant_python, env)
            if not args.no_browser:
                threading.Thread(
                    target=_open_panel,
                    args=(url, session_token, session_ttl),
                    daemon=True,
                ).start()
            started_at = time.monotonic()
            while True:
                if backend is not None and backend.poll() is not None:
                    print("✗  El backend se ha detenido.", file=sys.stderr)
                    return backend.returncode or 1
                if assistant.poll() is not None:
                    code = assistant.returncode or 0
                    if code != 0 and time.monotonic() - started_at < ASSISTANT_CRASH_SECONDS:
                        # A Qt/PortAudio import error kills the window in the
                        # first seconds; the traceback above is the real cause.
                        print(
                            "✗  El asistente se cerró nada más arrancar (mira el "
                            "error de arriba). Sin entorno gráfico, micrófono o "
                            "altavoces no puede abrir la ventana; la fábrica sí "
                            "funciona sola:\n"
                            "     .\\arrancar.ps1 -SoloBackend\n"
                            "   o, en macOS/Linux: python run_fusion.py --backend-only",
                            file=sys.stderr,
                        )
                    return code
                time.sleep(0.5)

        print("Listo. Ctrl+C para parar.", flush=True)
        while backend is not None and backend.poll() is None:
            time.sleep(0.5)
        return 0
    finally:
        _stop(assistant, "el asistente")
        _stop(daemon, "el demonio")
        _stop(backend, "el backend")


if __name__ == "__main__":
    raise SystemExit(main())
