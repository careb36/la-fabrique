#!/usr/bin/env python3
"""Genera el modelo de amenazas (OWASP pytm) de La Fabrique.

El modelo describe la arquitectura real del repositorio: frontend React,
backend FastAPI, PostgreSQL/pgvector, Neo4j, NATS JetStream, el proxy de LLM,
los proveedores externos, el daemon de workspace y el Janitor.

pytm es una herramienta de modelado, no una dependencia de ejecución del
servicio. Se recomienda un virtualenv aparte::

    python3 -m venv .venv-pytm
    .venv-pytm/bin/pip install pytm==1.4.0
    .venv-pytm/bin/python scripts/threat_model.py

Salidas: ``docs/threat_model.json`` y ``docs/threat_model.md``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    from pytm import TM, Actor, Boundary, Dataflow, Datastore, Process, Server
except ImportError as exc:  # pragma: no cover - depende del entorno de modelado
    print(
        "✘ falta pytm. Creá un virtualenv de modelado e instalá pytm==1.4.0:\n"
        "    python3 -m venv .venv-pytm\n"
        "    .venv-pytm/bin/pip install pytm==1.4.0",
        file=sys.stderr,
    )
    raise SystemExit(2) from exc


def build() -> TM:
    """Construye el modelo de amenazas de La Fabrique."""
    tm = TM("La Fabrique")
    tm.description = (
        "Plataforma multiagente que orquesta sprints de IA: frontend React, API "
        "FastAPI, PostgreSQL con pgvector, Neo4j, NATS JetStream, proxy de LLM, "
        "proveedores externos, daemon de workspace y Janitor."
    )

    # Límites de confianza
    navegador_b = Boundary("Navegador de la persona")
    host_b = Boundary("Host / red compose (operada por el mismo equipo)")
    externo_b = Boundary("Proveedores externos")

    # Actores
    persona = Actor("Product Owner / Engineer")
    persona.inBoundary = navegador_b

    github = Actor("GitHub")
    github.inBoundary = externo_b

    proveedor_llm = Actor("Gemini / DeepSeek")
    proveedor_llm.inBoundary = externo_b

    vault = Actor("Vault / Secrets Manager (opcional)")
    vault.inBoundary = externo_b

    # Procesos
    frontend = Process("Frontend React (Dashboard, GlassRoom, Kanban)")
    frontend.inBoundary = navegador_b
    frontend.allowsClientSideScripting = True
    frontend.controls.sanitizesInput = False
    frontend.controls.encodesOutput = True

    api = Server("Backend FastAPI")
    api.inBoundary = host_b
    api.isWebApplication = True
    api.controls.sanitizesInput = True
    api.controls.checksInputBounds = True
    api.controls.encodesOutput = True
    api.controls.authenticatesSource = True
    api.controls.implementsAuthenticationScheme = True
    api.controls.handlesCrashes = True
    api.usesEnvironmentVariables = True

    worker = Process("Task worker / LangGraph")
    worker.inBoundary = host_b
    worker.controls.sanitizesInput = False
    worker.controls.checksInputBounds = False

    llm_proxy = Process("LLM Proxy")
    llm_proxy.inBoundary = host_b
    llm_proxy.controls.sanitizesInput = True
    llm_proxy.controls.checksInputBounds = True

    daemon = Process("Workspace daemon (VS Code CLI)")
    daemon.inBoundary = host_b
    daemon.controls.sanitizesInput = False
    daemon.controls.checksInputBounds = False
    daemon.controls.isHardened = False

    janitor = Process("Janitor (mantenimiento diario)")
    janitor.inBoundary = host_b

    # Almacenes
    postgres = Datastore("PostgreSQL + pgvector")
    postgres.inBoundary = host_b
    postgres.type = "SQL"
    postgres.storesSensitiveData = True
    postgres.storesPII = True
    postgres.controls.encryptsDataAtRest = False

    neo4j = Datastore("Neo4j (Engram)")
    neo4j.inBoundary = host_b
    neo4j.type = "SQL"
    neo4j.storesSensitiveData = True
    neo4j.controls.encryptsDataAtRest = False

    nats = Process("NATS JetStream")
    nats.inBoundary = host_b
    nats.controls.encryptsDataAtRest = False

    audit = Datastore("Audit log JSONL")
    audit.inBoundary = host_b
    audit.type = "FILE_SYSTEM"
    audit.storesSensitiveData = True
    audit.controls.encryptsDataAtRest = False

    workspace = Datastore("Workspace de código")
    workspace.inBoundary = host_b
    workspace.type = "FILE_SYSTEM"
    workspace.storesSensitiveData = True
    workspace.controls.encryptsDataAtRest = False

    secrets = Datastore("Variables de entorno / .env")
    secrets.inBoundary = host_b
    secrets.type = "FILE_SYSTEM"
    secrets.storesSensitiveData = True
    secrets.isCredentials = True
    secrets.controls.encryptsDataAtRest = False

    # Flujos
    Dataflow(persona, frontend, "uso de la consola")
    Dataflow(frontend, api, "REST + SSE", protocol="HTTPS")
    Dataflow(api, postgres, "SQLModel (sprints, auditoría, embeddings)")
    Dataflow(api, neo4j, "Bolt (memoria episódica)")
    Dataflow(api, nats, "publicación de eventos")
    Dataflow(nats, worker, "asignaciones de tareas")
    Dataflow(worker, llm_proxy, "prompt + contexto")
    Dataflow(llm_proxy, proveedor_llm, "inferencia (API key)", protocol="HTTPS")
    Dataflow(worker, daemon, "workspace.generate")
    Dataflow(daemon, workspace, "escritura de archivos y comandos")
    Dataflow(api, github, "GitHub App (issues, PRs, checks)", protocol="HTTPS")
    Dataflow(api, audit, "registro append-only")
    Dataflow(api, secrets, "lectura de configuración y claves")
    Dataflow(llm_proxy, secrets, "lectura de API keys")
    Dataflow(api, vault, "secretos (opcional)", protocol="HTTPS")
    Dataflow(janitor, postgres, "mantenimiento y reindexación")
    Dataflow(janitor, neo4j, "mantenimiento de Engram")

    tm.process()
    return tm


def main() -> int:
    """Genera el JSON y el resumen Markdown del modelo."""
    tm = build()
    threats = tm._threats
    por_sev: dict[str, list] = {}
    for threat in threats:
        por_sev.setdefault(getattr(threat, "severity", "?"), []).append(threat)

    out_dir = Path(__file__).resolve().parent.parent / "docs"
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / "threat_model.json"

    def _serializable(threat):
        data = threat.model_dump()
        data["target"] = [
            getattr(target, "__name__", str(target))
            for target in (data.get("target") or ())
        ]
        return data

    json_path.write_text(
        json.dumps([_serializable(t) for t in threats], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines = [
        "# Modelo de amenazas (OWASP pytm / STRIDE)",
        "",
        f"Total de amenazas identificadas: **{len(threats)}**.",
        "",
        ("El modelo describe la arquitectura del repositorio; no reemplaza la "
         "revisión humana ni las pruebas de seguridad. Los riesgos residuales se "
         "documentan en `SECURITY.md`."),
        "",
    ]
    for severity in ("Critical", "Very High", "High", "Medium", "Low", "Very Low"):
        selected = por_sev.get(severity, [])
        if not selected:
            continue
        lines.append(f"## {severity} ({len(selected)})")
        lines.append("")
        for threat in selected:
            lines.append(f"- **{threat.id}** — {threat.description}")
            if getattr(threat, "mitigations", None):
                lines.append(f"  - *Mitigación:* {threat.mitigations}")
        lines.append("")

    (out_dir / "threat_model.md").write_text("\n".join(lines), encoding="utf-8")

    print(f"✔ {len(threats)} amenazas → {json_path} y {out_dir / 'threat_model.md'}")
    for severity in ("Critical", "Very High", "High", "Medium", "Low", "Very Low"):
        if por_sev.get(severity):
            print(f"  {severity}: {len(por_sev[severity])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
