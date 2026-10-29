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
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
FACTORY = ROOT / "la-fabrique"
BACKEND = FACTORY / "backend"
ASSISTANT = ROOT / "profesor3"
DEFAULT_URL = "http://127.0.0.1:8000"
DEFAULT_COMPANY = "Mi fábrica"

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
    if not env.get("JWT_SECRET_KEY"):
        # Local single-user desktop: login is not available without a JWT key,
        # so the factory runs in the documented demo mode. The voice key still
        # guards /v1/voice/*.
        env.setdefault("AUTH_REQUIRED", "false")
        if announce:
            print(
                "⚠  AUTH_REQUIRED=false (no JWT_SECRET_KEY). This is a local "
                "single-user install; set both in la-fabrique/.env for a shared one.",
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
) -> tuple[int, dict | None]:
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if key:
        headers["X-Voice-Key"] = key
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


def _ensure_company(url: str, key: str, name: str) -> int | None:
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


def _pick_python(explicit: str | None, venv_dir: Path, module: str) -> str:
    """The interpreter that can import ``module``: flag, local venv, then ours."""
    if explicit:
        return explicit
    for candidate in (
        venv_dir / "bin" / "python",
        venv_dir / "Scripts" / "python.exe",
        venv_dir / "bin" / "python3",
    ):
        if candidate.is_file() and _can_import(str(candidate), module):
            return str(candidate)
    if _can_import(sys.executable, module):
        return sys.executable
    return sys.executable


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


def _start_assistant(extra: list[str], python: str) -> subprocess.Popen:
    entry = ASSISTANT / "main.py"
    print("→  Arrancando el asistente …", flush=True)
    return subprocess.Popen(
        [python, str(entry), *extra],
        cwd=str(ASSISTANT),
        env=dict(os.environ),
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.getenv("FUSION_URL", DEFAULT_URL))
    parser.add_argument("--port", type=int, default=int(os.getenv("FUSION_PORT", "8000")))
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
    parser.add_argument("assistant_args", nargs="*", help="extra arguments for the assistant")
    args = parser.parse_args(argv)

    url = args.url.rstrip("/")
    use_sqlite = _is_local(url)
    env = _child_env(args.voice_key, use_sqlite, announce=not args.assistant_only)
    key = args.voice_key or env.get("VOICE_API_KEY") or secrets.token_urlsafe(32)
    env["VOICE_API_KEY"] = key

    backend: subprocess.Popen | None = None
    assistant: subprocess.Popen | None = None

    def _shutdown(_signum=None, _frame=None):
        _stop(assistant, "el asistente")
        _stop(backend, "el backend")
        raise SystemExit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
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
                port = urlsplit(url).port or args.port
                backend_python = _pick_python(
                    args.backend_python, ROOT / ".venv-backend", "fastapi"
                )
                if not _can_import(backend_python, "fastapi"):
                    print(
                        f"✗  {backend_python} no tiene las dependencias del "
                        "backend. Instálalas como explica la-fabrique/README.md "
                        "(cd la-fabrique/backend && poetry install) sobre ese "
                        "intérprete, o pasa --backend-python RUTA.",
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

        if not args.no_bootstrap:
            company_id = _ensure_company(url, key, args.company) if key_ok else None
        else:
            company_id = None

        if not args.no_config and key_ok:
            _configure_assistant(url, key, company_id)

        if not args.backend_only:
            assistant_python = _pick_python(
                args.assistant_python, ASSISTANT / ".venv", "PyQt6"
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
            assistant = _start_assistant(args.assistant_args, assistant_python)
            while True:
                if backend is not None and backend.poll() is not None:
                    print("✗  El backend se ha detenido.", file=sys.stderr)
                    return backend.returncode or 1
                if assistant.poll() is not None:
                    return assistant.returncode or 0
                time.sleep(0.5)

        print("Listo. Ctrl+C para parar.", flush=True)
        while backend is not None and backend.poll() is None:
            time.sleep(0.5)
        return 0
    finally:
        _stop(assistant, "el asistente")
        _stop(backend, "el backend")


if __name__ == "__main__":
    raise SystemExit(main())
