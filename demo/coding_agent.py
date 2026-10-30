#!/usr/bin/env python3
"""Un agente de código que escribe, ejecuta y prueba — con Nemotron, en serio.

Este es el bucle que pide la categoría «Coding & Agents Engineering»: el modelo
propone archivos, el agente los escribe en un directorio de trabajo, ejecuta la
suite de pruebas de verdad y, si algo falla, le devuelve la salida al modelo y
vuelve a intentarlo. Nada se da por bueno porque el texto lo diga: la única
respuesta que cuenta es la del intérprete.

Corre contra Nebius Token Factory (los Nemotron abiertos de NVIDIA viven ahí) o
contra NVIDIA NIM, que sirve los mismos modelos:

    export NEBIUS_API_KEY=nvapi-...
    python demo/coding_agent.py --task "slugify con pruebas unittest"

Sin clave, ``--offline`` usa dos respuestas grabadas y hace el mismo recorrido
(una ronda que falla, otra que arregla), para que la demostración se pueda
grabar y probar sin red.

Uso:
    python demo/coding_agent.py --task "..." [--model ID] [--url URL]
                                [--rounds 3] [--offline] [--keep] [--quiet]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from demo import nemotron

PROTOCOL = """\
You are a coding agent working alone in an empty directory.

Answer with ONE JSON object and nothing else — no prose, no code fences:

{"files": [{"path": "relative/name.py", "content": "the whole file"}],
 "summary": "one sentence"}

Rules:
- Python 3 standard library only. No third-party packages, no network.
- Write the implementation AND its tests. Tests use `unittest`.
- `path` is relative; no absolute paths, no parent directories (`..`).
- The tests must be runnable with `python -m unittest discover -q`.
"""


# ── el directorio de trabajo ────────────────────────────────────────────────
def _safe_path(root: Path, name: str) -> Path:
    """Un archivo dentro de *root* y sólo dentro.

    El modelo escribe nombres de archivo; si alguna vez devuelve `../../algo` o
    una ruta absoluta, esto lo deja fuera en vez de dejar que el agente escriba
    donde no debe. El directorio temporal ya es una caja, pero no hace falta
    confiar en que el modelo respete la caja.
    """
    rel = str(name or "").replace("\\", "/")
    if rel.startswith("/") or (len(rel) > 1 and rel[1] == ":"):
        raise ValueError(f"absolute path refused: {name!r}")
    target = (root / rel).resolve()
    if root.resolve() not in target.parents and target != root.resolve():
        raise ValueError(f"path escapes the workspace: {name!r}")
    return target


def write_files(root: Path, files: list[dict]) -> list[str]:
    written = []
    for item in files or []:
        if not isinstance(item, dict):
            continue
        path = _safe_path(root, str(item.get("path") or ""))
        content = str(item.get("content") or "")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content if content.endswith("\n") else content + "\n",
                        encoding="utf-8")
        written.append(str(path.relative_to(root.resolve())).replace("\\", "/"))
    return written


def _clean_env() -> dict[str, str]:
    """Only what a test run needs; nothing that could carry a secret."""
    keep = ("PATH", "SYSTEMROOT", "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL")
    env = {name: os.environ[name] for name in keep if name in os.environ}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def run_tests(root: Path, timeout: float = 120.0) -> tuple[bool, str]:
    """Ejecuta la suite. La salida real es la que decide, no el modelo.

    ``unittest`` y no ``pytest``: el directorio tiene que poder probarse en una
    máquina recién clonada, sin instalar nada.
    """
    try:
        # The tests are code the model wrote: they run without this
        # process's environment (no API keys, no tokens) and with Python in
        # isolated mode. It is still this user on this machine; run the live
        # demo in a container or a throwaway VM, ``--offline`` anywhere.
        done = subprocess.run([sys.executable, "-I", "-m", "unittest", "discover",
                               "-q", "-t", str(root)],
                              cwd=str(root), capture_output=True, text=True,
                              timeout=timeout, env=_clean_env())
    except subprocess.TimeoutExpired:
        return False, f"the test run timed out after {timeout:.0f}s"
    output = ((done.stdout or "") + (done.stderr or "")).strip()
    return done.returncode == 0, output


# ── leer lo que contestó el modelo ──────────────────────────────────────────
def parse_reply(text: str) -> dict:
    """El JSON del protocolo, aunque venga envuelto en ```json o con prosa.

    Los modelos abiertos contestan el JSON casi siempre y a veces con un saludo
    delante. Se busca el objeto más grande que se pueda decodificar en vez de
    exigir que la respuesta entera sea JSON.
    """
    raw = str(text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", raw, re.S)
    if fence:
        raw = fence.group(1).strip()
    try:
        return json.loads(raw)
    except Exception:
        pass
    decoder = json.JSONDecoder()
    best: dict = {}
    for start in (i for i, ch in enumerate(raw) if ch == "{"):
        try:
            candidate, _ = decoder.raw_decode(raw[start:])
        except Exception:
            continue
        if isinstance(candidate, dict) and len(json.dumps(candidate)) > len(json.dumps(best)):
            best = candidate
    if not best:
        raise ValueError("the model did not answer JSON: " + raw[:200])
    return best


# ── respuestas grabadas (sin red) ───────────────────────────────────────────
_OFFLINE_ROUNDS = [
    {
        "files": [
            {"path": "slugify.py", "content":
             'def slugify(text):\n'
             '    """A short, URL-safe version of *text*."""\n'
             '    return text.lower().replace(" ", "-")\n'},
            {"path": "test_slugify.py", "content":
             'import unittest\n\n'
             'from slugify import slugify\n\n\n'
             'class SlugifyTest(unittest.TestCase):\n'
             '    def test_spaces_become_dashes(self):\n'
             '        self.assertEqual(slugify("Hola Mundo"), "hola-mundo")\n\n'
             '    def test_accents_are_folded(self):\n'
             '        self.assertEqual(slugify("Canción de cuna"),\n'
             '                         "cancion-de-cuna")\n\n'
             '    def test_punctuation_goes_away(self):\n'
             '        self.assertEqual(slugify("¿Qué tal?"), "que-tal")\n\n\n'
             'if __name__ == "__main__":\n'
             '    unittest.main()\n'},
        ],
        "summary": "first pass: lower-case and dashes",
    },
    {
        "files": [
            {"path": "slugify.py", "content":
             'import re\n'
             'import unicodedata\n\n\n'
             'def slugify(text):\n'
             '    """A short, URL-safe version of *text*."""\n'
             '    plain = unicodedata.normalize("NFKD", str(text))\n'
             '    plain = "".join(c for c in plain\n'
             '                    if not unicodedata.combining(c))\n'
             '    plain = re.sub(r"[^a-zA-Z0-9]+", "-", plain).strip("-")\n'
             '    return plain.lower()\n'},
        ],
        "summary": "second pass: fold accents and drop punctuation",
    },
]


# ── elegir la puerta ────────────────────────────────────────────────────────
def open_llm(key: str, url: str, model: str, probe: bool = True, log=print):
    """El proveedor que acepta esta clave, con un modelo que ese proveedor sirve.

    Las claves de Nebius y de NVIDIA empiezan igual (``nvapi-``) y cada puerta
    sólo acepta la suya, así que se prueban las direcciones conocidas hasta que
    una contesta. Después se comprueba que el modelo pedido esté en su catálogo:
    un id retirado no se descubre en la primera ronda, se descubre cuando la
    fábrica ya lleva media hora trabajando.
    """
    doors = [url] if not probe else [url] + [
        u for _, u in nemotron.DOORS if u.rstrip("/") != url.rstrip("/")]
    last: Exception | None = None
    for door in doors:
        llm = nemotron.ChatClient({"base_url": door, "model": model,
                                   "api_key": key, "temperature": 0.2,
                                   "max_tokens": 8192})
        try:
            offered = llm.models()
        except Exception as exc:
            last = exc
            continue
        if offered and model not in offered:
            strategic, _ = nemotron.tier_models(offered, model)
            if strategic and strategic != model:
                log(f"El modelo {model} no está en {door}: uso {strategic}")
                llm.model = strategic
        return llm
    raise RuntimeError(f"ninguna dirección aceptó la clave: {last}")


# ── el agente ───────────────────────────────────────────────────────────────
class CodingAgent:
    def __init__(self, llm=None, offline: bool = False, log=print):
        self._llm = llm
        self._offline = offline or llm is None
        self._log = log
        self._offline_round = 0

    def _ask(self, messages: list[dict]) -> dict:
        if self._offline:
            reply = _OFFLINE_ROUNDS[min(self._offline_round,
                                        len(_OFFLINE_ROUNDS) - 1)]
            self._offline_round += 1
            return reply
        text, _ = self._llm.complete(messages, temperature=0.2)
        return parse_reply(text)

    def _messages(self, task: str, history: list[str]) -> list[dict]:
        messages = [
            {"role": "system", "content": PROTOCOL},
            {"role": "user", "content": f"TASK\n{task}"},
        ]
        for failure in history:
            messages += [
                {"role": "assistant", "content": "(the previous files)"},
                {"role": "user", "content":
                 "The tests ran and did not pass. Fix the code. Output the "
                 "full JSON again, with every file that changes.\n\n"
                 + failure[-4000:]},
            ]
        return messages

    def run(self, task: str, workdir: Path, rounds: int = 3) -> dict:
        failures: list[str] = []
        report = {"ok": False, "rounds": 0, "workspace": str(workdir),
                  "output": ""}
        for number in range(1, max(1, rounds) + 1):
            started = time.monotonic()
            plan = self._ask(self._messages(task, failures))
            written = write_files(workdir, plan.get("files") or [])
            self._log(f"[ronda {number}] {plan.get('summary') or 'sin resumen'}")
            self._log(f"[ronda {number}] escribió: {', '.join(written) or '(nada)'}")
            ok, output = run_tests(workdir)
            took = time.monotonic() - started
            report["rounds"] = number
            report["output"] = output
            if ok:
                self._log(f"[ronda {number}] pruebas: OK ({took:.1f}s)")
                report["ok"] = True
                return report
            last = [line for line in output.splitlines() if line.strip()][-3:]
            self._log(f"[ronda {number}] pruebas: FALLAN — " + " | ".join(last))
            failures.append(output)
        return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--task", default=(
        "Escribe una función slugify(text) que convierta un título en una URL "
        "corta: minúsculas, sin acentos, sin signos y con guiones. Incluye "
        "pruebas unittest para espacios, acentos y puntuación."))
    parser.add_argument("--model", default="")
    parser.add_argument("--url", default="")
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--offline", action="store_true",
                        help="sin red: dos respuestas grabadas, mismo recorrido")
    parser.add_argument("--keep", action="store_true",
                        help="deja el directorio de trabajo y dice dónde")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    log = (lambda *a, **k: None) if args.quiet else print
    env = nemotron.read_env()
    key = (os.getenv("NEBIUS_API_KEY") or env.get(nemotron.KEY_NAME) or "").strip()
    url = (args.url or os.getenv("NEBIUS_PROXY_URL")
           or env.get("NEBIUS_PROXY_URL") or nemotron.DEFAULT_NEMOTRON_URL)
    model = (args.model or os.getenv("AGENT_MODEL") or env.get("AGENT_MODEL")
             or nemotron.DEFAULT_NEMOTRON_MODEL)

    llm = None
    if not args.offline:
        if not key:
            print("No hay clave: exportá NEBIUS_API_KEY=nvapi-... "
                  "(o usá --offline)", file=sys.stderr)
            return 2
        llm = open_llm(key, url, model, probe=not args.url, log=log)
        print(f"Proveedor: {llm.base}\nModelo: {llm.model}")

    workdir = Path(tempfile.mkdtemp(prefix="fabrica-demo-"))
    if args.keep:
        print(f"Directorio de trabajo: {workdir}")
    started = time.monotonic()
    try:
        report = CodingAgent(llm=llm, offline=args.offline, log=log).run(
            args.task, workdir, rounds=args.rounds)
    finally:
        if not args.keep:
            import shutil
            shutil.rmtree(workdir, ignore_errors=True)

    took = time.monotonic() - started
    if report["ok"]:
        print(f"\n✅ las pruebas pasan ({report['rounds']} ronda(s), {took:.1f}s)")
        return 0
    print(f"\n❌ no pasaron en {report['rounds']} ronda(s)\n"
          f"{report['output'][-1500:]}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
