"""``/v1/voice/build`` — the factory builds a project and leaves it on disk.

This is the door behind "hacé una página con html, css y javascript con la
fábrica". Two endpoints:

* ``POST /v1/voice/build`` takes the sentence, asks the model for the files
  through the proxy, writes them under ``FABRICA_BUILDS_DIR`` and answers with a
  sentence plus the numbers (files, seconds, URL).
* ``GET /v1/voice/build/<slug>/<file>`` serves what was written, so the page the
  person asked for can be opened. It is deliberately **anonymous** — a browser
  cannot send ``X-Voice-Key`` when a link is clicked — but read-only, path-safe
  and sandboxed by a CSP header, so a generated page cannot reach back into the
  backend's origin.

The same rule as the rest of ``/v1/voice``: business failures come back as HTTP
200 with ``ok: false`` and a sentence the assistant can say.
"""

from __future__ import annotations

import mimetypes
import os
from pathlib import Path

from auth_policy import ROLE_RANK
from database import get_session
from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, JSONResponse
from llm_proxy_client import LLMProxyClient
from models import CompanyMember
from pydantic import BaseModel, Field
from services import codegen, voice_control
from sqlmodel import Session, select

from llm.model_factory import AgentRole, ModelFactory
from routers.voice_support import VoiceCaller, voice_access

router = APIRouter(prefix="/v1/voice", tags=["Voice"])

_LANGUAGE = "es"

# A generated page is untrusted content: it may run its own script, but not
# talk to this origin, read cookies or navigate the top window away.
_PREVIEW_HEADERS = {
    "Content-Security-Policy": "sandbox allow-scripts allow-popups",
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "no-store",
}


class VoiceBuildRequest(BaseModel):
    """One build request, in the words the person used."""

    texto: str = Field(max_length=4000, description="What to build, verbatim.")
    nombre: str | None = Field(
        default=None, max_length=120, description="Optional project name."
    )
    language: str | None = None


def _manages_a_company(session: Session, user) -> bool:
    roles = session.exec(
        select(CompanyMember.human_role).where(CompanyMember.user_id == user.id)
    ).all()
    return any(ROLE_RANK.get(role, 0) >= ROLE_RANK["Manager"] for role in roles)


def builds_root() -> Path:
    """Where generated projects live; ``FABRICA_BUILDS_DIR`` overrides it."""
    configured = (os.getenv("FABRICA_BUILDS_DIR") or "").strip()
    root = (
        Path(configured)
        if configured
        else (Path(__file__).resolve().parents[2] / "builds")
    )
    root.mkdir(parents=True, exist_ok=True)
    return root


def _candidate_models() -> list[str]:
    """The ids to try, in order, until one of them is served.

    A provider catalogue changes under the deployment's feet: the id in
    ``NEMOTRON_MODEL`` can be missing from the current endpoint while the
    strategic tier is there. A build is a one-shot action the person is waiting
    for, so a wrong id must cost a retry, not the whole feature.
    """
    # Stripped for the same reason the proxy trims its keys: a .env with CRLF
    # line endings turns "model-id" into "model-id\r".
    candidates = [
        (ModelFactory.model_for_role(AgentRole.DEVELOPER) or "").strip(),
        os.getenv("NEMOTRON_MODEL_STRATEGIC", "").strip(),
        ModelFactory.ROLE_MODEL_MAP[AgentRole.DEVELOPER].model_name.strip(),
    ]
    return [
        model
        for index, model in enumerate(candidates)
        if model and model not in candidates[:index]
    ]


def _codegen_switches(model: str) -> dict:
    """Asked of NVIDIA reasoning models only: write code, don't think first.

    The proxy forwards ``chat_template_kwargs`` untouched, and only NVIDIA's
    templates understand it; with reasoning on, a whole-file answer took longer
    than the client's budget and the failure looked like a dead proxy.
    """
    if (model or "").startswith("nvidia/"):
        return {"chat_template_kwargs": {"enable_thinking": False}}
    return {}


def _chat(messages: list[dict]) -> str:
    """Ask the factory's Developer model, through the same proxy as its agents.

    Going through the proxy (and not straight to Nebius) keeps one place for
    keys, token budgets and model tiers: the role decides whether Ultra thinks
    or Super answers, exactly as it does for a sprint task.
    """
    client = LLMProxyClient()
    failures: list[str] = []
    for model in _candidate_models():
        result = client.chat(
            messages,
            model=model,
            role=AgentRole.DEVELOPER.value,
            max_tokens=codegen.MAX_ANSWER_TOKENS,
            extra=_codegen_switches(model),
        )
        if isinstance(result, dict) and not result.get("error"):
            try:
                return str(result["choices"][0]["message"]["content"])
            except Exception:  # noqa: BLE001 - try the next id, then report
                failures.append(f"{model}: respuesta sin mensaje")
                continue
        failures.append(f"{model}: {str((result or {}).get('error'))[:120]}")

    # Spoken, so short and free of hostnames: the detail travels in data.error.
    failure = codegen.CodegenError(
        "No pude hablar con el proxy de modelos. Revisá que esté arriba y que "
        "la clave del proveedor sea válida."
    )
    failure.detail = "; ".join(failures)
    raise failure


@router.post("/build")
def voice_build(
    req: VoiceBuildRequest,
    session: Session = Depends(get_session),  # noqa: B008 - FastAPI dependency marker.
    caller: VoiceCaller = Depends(voice_access),  # noqa: B008 - FastAPI dependency marker.
) -> dict:
    """Build the project the person described and leave it ready to open."""
    language = voice_control.normalize_language(req.language or _LANGUAGE)
    # Each build spends model tokens: a signed-in caller must be a Manager of
    # some company, the same bar as starting a sprint. The shared key (or a
    # demo without authentication) needs no company: builds belong to none.
    if caller.user is not None and not _manages_a_company(session, caller.user):
        return _reply(
            False,
            voice_control.say(
                language,
                "No tienes permiso para construir: hace falta ser Manager de una empresa.",
                "You do not have permission to build: you need to be a Manager of a company.",
            ),
            language,
        )
    text = " ".join((req.texto or "").split())
    if not text:
        return _reply(
            False,
            voice_control.say(
                language,
                "No me dijiste qué construir. Pedímelo, por ejemplo: una página "
                "sencilla con html, css y javascript.",
                "You did not tell me what to build. Try: a simple page with html, "
                "css and javascript.",
            ),
            language,
        )

    try:
        result = codegen.build(builds_root(), text, _chat)
    except codegen.CodegenError as exc:
        return _reply(
            False, str(exc), language, {"error": getattr(exc, "detail", str(exc))}
        )

    files = result["files"]
    listing = ", ".join(files[:4]) + ("…" if len(files) > 4 else "")
    plural = "s" if len(files) != 1 else ""
    # Said out loud, so no slug and no path: the assistant opens the page, and a
    # URL read aloud is noise.
    speech = voice_control.say(
        language,
        f"Listo: armé el proyecto con {len(files)} archivo{plural} en "
        f"{result['seconds']} segundos ({listing}). Te lo abro en el navegador.",
        f"Done: I built the project with {len(files)} file{plural} in "
        f"{result['seconds']} seconds ({listing}). I am opening it in your browser.",
    )
    return _reply(True, speech, language, result)


@router.get("/build/{slug}/{file_path:path}", response_model=None)
def voice_build_file(slug: str, file_path: str = ""):
    """Serve one generated file (``index.html`` when the path is empty)."""
    target = codegen.serve_path(builds_root(), slug, file_path)
    if target is None:
        return JSONResponse(status_code=404, content={"detail": "not found"})

    media_type = mimetypes.guess_type(target.name)[0] or "text/plain"
    return FileResponse(target, media_type=media_type, headers=_PREVIEW_HEADERS)


def _reply(ok: bool, speech: str, language: str, data: dict | None = None) -> dict:
    return {
        "ok": ok,
        "action": "crear_proyecto",
        "speech": speech,
        "data": data or {},
    }
