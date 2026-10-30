"""Dependency probes for the deep healthcheck endpoint.

Each probe runs with a short timeout and returns a small dict so that
``/health/deep`` can aggregate component states without ever blocking the
request. The endpoint reports ``healthy`` only when every required component
is up; otherwise the overall status becomes ``degraded`` (or ``down`` if any
required component is missing).

Why deep healthchecks matter here
---------------------------------
La Fabrique runs several backing services that can fail independently
(NATS, Postgres, Neo4j, the LLM proxy). Without per-component visibility,
operators see "API is up" while agents silently stop progressing because
the broker disconnected or the proxy is stuck. The deep probe surfaces
the actual blast radius so GlassRoom and the runbook can react.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx
from database import engine, get_neo4j_driver
from logging_config import logger
from sqlmodel import Session, text

_PROBE_TIMEOUT_SECONDS = 3.0


def _ok(detail: str | None = None, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"status": "up"}
    if detail:
        payload["detail"] = detail
    payload.update(extra)
    return payload


def _down(reason: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"status": "down", "reason": reason[:500]}
    payload.update(extra)
    return payload


async def probe_nats(nats_client: Any) -> dict[str, Any]:
    if not nats_client:
        return _down("not_initialized")
    nc = getattr(nats_client, "nc", None)
    if not nc:
        return _down("not_connected")
    try:
        is_connected = bool(nc.is_connected)
    except Exception as exc:  # noqa: BLE001  # defensive: SDK shape can change
        return _down(f"introspection_error: {exc}")
    if not is_connected:
        return _down("disconnected")
    return _ok(
        servers=getattr(nc, "connected_url", None) and str(nc.connected_url) or "?",
        subscriptions=len(getattr(nats_client, "subscriptions", {}) or {}),
    )


def _sync_probe_postgres() -> dict[str, Any]:
    try:
        with Session(engine) as session:
            session.exec(text("SELECT 1")).first()
        return _ok()
    except Exception as exc:  # noqa: BLE001
        return _down(f"{type(exc).__name__}: {exc}")


async def probe_postgres() -> dict[str, Any]:
    return await asyncio.to_thread(_sync_probe_postgres)


def _sync_probe_neo4j() -> dict[str, Any]:
    driver = None
    try:
        driver = get_neo4j_driver()
        with driver.session() as session:
            record = session.run("RETURN 1 AS ok").single()
            ok = record and record.get("ok") == 1
            return _ok() if ok else _down("unexpected_response")
    except Exception as exc:  # noqa: BLE001
        return _down(f"{type(exc).__name__}: {exc}")
    finally:
        if driver is not None:
            try:
                driver.close()
            except Exception:  # noqa: BLE001, S110
                pass


async def probe_neo4j() -> dict[str, Any]:
    return await asyncio.to_thread(_sync_probe_neo4j)


async def probe_llm_proxy() -> dict[str, Any]:
    base_url = os.getenv("LLM_PROXY_URL", "http://localhost:5100").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_SECONDS) as client:
            response = await client.get(f"{base_url}/health")
        if response.status_code != 200:
            return _down(f"http_{response.status_code}")
        try:
            body = response.json()
        except Exception:  # noqa: BLE001
            body = {}
        models = body.get("models")
        return _ok(
            detail=body.get("status"),
            models_count=len(models) if isinstance(models, list) else None,
        )
    except Exception as exc:  # noqa: BLE001
        return _down(f"{type(exc).__name__}: {exc}")


async def aggregate(nats_client: Any, nats_state: str | None = None) -> dict[str, Any]:
    """Run all probes concurrently and return a structured health document.

    ``nats_state`` is the backend's NATS connection lifecycle state
    (``"connecting"`` while the startup connector is still retrying,
    ``"connected"`` once workers have started); it is reported as the
    top-level ``nats`` field when given.
    """
    nats_result, postgres_result, neo4j_result, llm_result = await asyncio.gather(
        probe_nats(nats_client),
        probe_postgres(),
        probe_neo4j(),
        probe_llm_proxy(),
    )

    components = {
        "nats": nats_result,
        "postgres": postgres_result,
        "neo4j": neo4j_result,
        "llm_proxy": llm_result,
    }

    # Postgres and the LLM proxy are required for any agent work. Without NATS
    # we can still serve API reads but cannot run sprints. Without Neo4j we lose
    # episodic memory but kickoff still works. Surface the nuance instead of a
    # single boolean so operators can read the reason at a glance.
    required = {"postgres", "llm_proxy"}
    severity = "healthy"
    for name, comp in components.items():
        if comp.get("status") != "up":
            if name in required:
                severity = "down"
                break
            severity = "degraded"

    logger.info(
        "deep healthcheck: severity=%s components=%s",
        severity,
        {k: v.get("status") for k, v in components.items()},
    )
    document: dict[str, Any] = {"status": severity, "components": components}
    if nats_state is not None:
        document["nats"] = nats_state
    return document
