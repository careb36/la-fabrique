#!/usr/bin/env python3
"""¿Cumple este repositorio lo que pide el hackathon? Se comprueba, no se opina.

Cada requisito de la convocatoria está aquí como una prueba que se puede
ejecutar. Sin clave comprueba lo que se puede comprobar en frío (licencia,
README, la demo funcionando, la configuración apuntando a Token Factory); con
``NEBIUS_API_KEY`` comprueba además que el proveedor contesta, que Nemotron está
en su catálogo y que un turno real se completa.

    python tools/hackathon_check.py            # en frío
    NEBIUS_API_KEY=nvapi-... python tools/hackathon_check.py   # completo

Sale 0 sólo si todo lo obligatorio pasa.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OK, BAD, SKIP = "\033[32m✔\033[0m", "\033[31m✘\033[0m", "\033[33m…\033[0m"


class Report:
    def __init__(self) -> None:
        self.failed = 0
        self.skipped = 0

    def check(self, ok: bool, what: str, detail: str = "") -> bool:
        mark = OK if ok else BAD
        if not ok:
            self.failed += 1
        print(f"  {mark} {what}" + (f" — {detail}" if detail and not ok else ""))
        return ok

    def warn(self, what: str, detail: str = "") -> None:
        print(f"  {SKIP} {what}" + (f" — {detail}" if detail else ""))

    def skip(self, what: str) -> None:
        self.skipped += 1
        print(f"  {SKIP} {what} (sin clave)")


def check_license(report: Report) -> None:
    path = ROOT / "LICENSE"
    text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    report.check(bool(text), "LICENSE en la raíz del repositorio")
    report.check("Apache License" in text and "Version 2.0" in text,
                 "licencia open source reconocible (Apache-2.0)")
    readme = (ROOT / "README.md").read_text(encoding="utf-8", errors="replace")
    report.check("Apache" in readme or "licencia" in readme.lower(),
                 "el README nombra la licencia")


def check_readme(report: Report) -> None:
    # The README that ships is English; README.es.md is the original Spanish
    # documentation kept alongside it.
    path = ROOT / "README.md"
    if not path.exists():
        path = ROOT / "README.es.md"
    text = path.read_text(encoding="utf-8", errors="replace")
    lowered = text.lower()
    required = {
        "Token Factory": ("token factory",),
        "Nemotron": ("nemotron",),
        "cómo ejecutar": ("installation", "getting started", "cómo ejecutar"),
        "categoría del hackathon": ("coding & agents",),
    }
    for label, needles in required.items():
        report.check(any(n in lowered for n in needles),
                     f"el README habla de {label}")
    report.check(len(text) > 3000, "el README tiene instrucciones de verdad")


def check_config(report: Report) -> None:
    from demo import nemotron

    report.check(nemotron.DEFAULT_NEMOTRON_URL.startswith(
        "https://api.tokenfactory.nebius.com"),
        "la dirección por defecto es Nebius Token Factory",
        nemotron.DEFAULT_NEMOTRON_URL)
    report.check("nvidia/" in nemotron.DEFAULT_NEMOTRON_MODEL,
                 "el modelo por defecto es un modelo abierto de NVIDIA",
                 nemotron.DEFAULT_NEMOTRON_MODEL)
    strategic, fast = nemotron.tier_models(
        [nemotron.DEFAULT_NEMOTRON_MODEL, nemotron.DEFAULT_FAST_MODEL])
    report.check(bool(strategic and fast),
                 "hay dos niveles: razonamiento y respuestas rápidas",
                 f"{strategic} / {fast}")
    report.check("developer" in nemotron.FACTORY_ROLES,
                 "los roles de la fábrica se reparten entre esos niveles")


def check_demo(report: Report) -> None:
    demo = ROOT / "demo" / "coding_agent.py"
    if not report.check(demo.exists(), "existe la demo del agente de código"):
        return
    done = subprocess.run([sys.executable, str(demo), "--offline", "--quiet"],
                          cwd=str(ROOT), capture_output=True, text=True,
                          timeout=300)
    report.check(done.returncode == 0,
                 "la demo escribe, ejecuta y prueba código sin red",
                 (done.stdout + done.stderr)[-300:])
    report.check("las pruebas pasan" in done.stdout,
                 "la demo termina con las pruebas en verde")


def check_secrets(report: Report) -> None:
    done = subprocess.run(["git", "ls-files", ".env", "la-fabrique/.env"],
                          cwd=str(ROOT), capture_output=True, text=True)
    tracked = done.stdout.strip()
    report.check(not tracked, "no hay claves versionadas en el repositorio",
                 tracked)


def check_live(report: Report, key: str) -> None:
    """Con clave: qué puerta la acepta, qué modelos sirve y que un turno responde.

    La convocatoria pide Token Factory. Las claves de Nebius y de NVIDIA se
    parecen demasiado como para distinguirlas a ojo, así que se prueba en orden
    y se dice en cuál cayó: una clave de otra puerta sirve para desarrollar,
    pero no para el envío, y eso tiene que verse aquí y no en el formulario.
    """
    from demo import nemotron
    from demo.nemotron import ChatClient

    doors = [(name, url) for name, url in nemotron.DOORS]
    doors.sort(key=lambda d: "tokenfactory" not in d[1])
    accepted = None
    for name, url in doors:
        try:
            ChatClient({"base_url": url, "model": "x",
                        "api_key": key}).models(timeout=10)
        except Exception:
            continue
        accepted = (name, url)
        break
    if not report.check(bool(accepted), "la clave es aceptada por el proveedor"):
        return
    name, url = accepted
    report.warn(f"la clave se aceptó en: {name}", url)
    if "tokenfactory" not in url:
        report.warn("esta clave NO es de Nebius Token Factory",
                    "sirve para desarrollo local; para el envío hace falta una "
                    "de Token Factory o de Nebius AI Cloud")
    llm = ChatClient({"base_url": url, "model": nemotron.DEFAULT_NEMOTRON_MODEL,
                      "api_key": key, "max_tokens": 64})
    offered = llm.models()
    nemotron_models = [m for m in offered if "nemotron" in m.lower()]
    report.check(bool(nemotron_models), "el catálogo sirve modelos Nemotron",
                 ", ".join(nemotron_models[:4]))
    if nemotron_models and llm.model not in offered:
        llm.model = nemotron.tier_models(offered)[0] or nemotron_models[0]
        report.warn("el modelo por defecto no está en este catálogo",
                    f"se probó con {llm.model}")
    text, _ = llm.complete([{"role": "user",
                             "content": "Answer with the single word: listo"}])
    report.check(bool(text.strip()), "un turno real devuelve texto",
                 repr(text[:60]))


def main() -> int:
    print("\nRequisitos del Hackathon Global de IA NVIDIA × Nebius\n"
          f"Repositorio: {ROOT}\n")
    report = Report()

    print("Licencia y README")
    check_license(report)
    check_readme(report)

    print("\nInfraestructura y modelos")
    check_config(report)

    print("\nDemo funcional")
    check_demo(report)

    print("\nRepositorio público")
    check_secrets(report)

    key = (os.getenv("NEBIUS_API_KEY") or "").strip()
    print("\nContra el proveedor (Token Factory)")
    if key:
        check_live(report, key)
    else:
        report.skip("clave aceptada, catálogo Nemotron y un turno real")

    print()
    if report.failed:
        print(f"{report.failed} requisito(s) sin cumplir\n")
        return 1
    print("Todo lo comprobable, cumplido"
          + (f" ({report.skipped} comprobación(es) esperando clave)\n"
             if report.skipped else "\n"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
