"""Voice façade — the desktop assistant's control surface for the factory.

``/v1/voice/*`` is not a second API: it is the spoken door to the same endpoints
the React app uses. The assistant sends one instruction with a small fixed
vocabulary (``estado``, ``crear_sprint``, ``pausar`` …) and gets back a
``speech`` sentence it reads verbatim, plus the structured ``data`` behind it.

Two deliberate choices:

* **A created sprint starts paused.** ``start_sprint`` already dispatches work,
  so voice creation parks the sprint right after it is written. Nothing runs
  until the person says "reanuda". That is the confirmation, and it cannot be
  forged by the model the way a ``confirm=true`` parameter can.
* **Authentication is a shared secret, never anonymous.** The assistant holds
  ``VOICE_API_KEY`` and sends it as ``X-Voice-Key``. With no key configured and
  ``AUTH_REQUIRED`` on, the routes answer 503 instead of opening the factory to
  anyone who can reach the port.

Business failures come back as HTTP 200 with ``ok: false`` and a spoken
sentence: a voice assistant should say "todavía no hay sprints" rather than
surface a 404 to the person listening.
"""

from database import get_session
from fastapi import APIRouter, Depends, Query
from schemas import (
    VoiceCommandRequest,
)
from services import voice_control
from sqlmodel import Session

from routers.voice_actions import _HANDLERS
from routers.voice_support import (
    _LANGUAGE,
    VoiceCaller,
    _fail,
    status_answer,
    voice_access,
)

router = APIRouter(prefix="/v1/voice", tags=["Voice"])


@router.get("/ping")
def voice_ping(
    caller: VoiceCaller = Depends(voice_access),  # noqa: B008 - FastAPI dependency marker.
):
    """Credential check for the assistant's settings screen."""
    return {
        "ok": True,
        "speech": "Conexión con la fábrica correcta.",
        "via_key": caller.via_key,
    }


@router.get("/status")
def voice_status(
    company_id: int | None = Query(default=None),
    sprint_id: int | None = Query(default=None),
    language: str | None = Query(default=None),
    session: Session = Depends(get_session),  # noqa: B008 - FastAPI dependency marker.
    caller: VoiceCaller = Depends(voice_access),  # noqa: B008 - FastAPI dependency marker.
):
    """What the factory is doing, as one sentence plus its numbers."""
    return status_answer(session, company_id, sprint_id, language, caller)


@router.post("/command")
async def voice_command(
    req: VoiceCommandRequest,
    session: Session = Depends(get_session),  # noqa: B008 - FastAPI dependency marker.
    caller: VoiceCaller = Depends(voice_access),  # noqa: B008 - FastAPI dependency marker.
):
    """Run one spoken instruction and return the sentence to say back."""
    language = voice_control.normalize_language(req.language or _LANGUAGE)
    action = voice_control.VOICE_ACTIONS.get((req.action or "").strip().lower())
    if action is None:
        return _fail(
            (req.action or "").strip().lower() or "desconocida",
            language,
            "Eso no lo sé hacer con la fábrica. Pídeme el estado, crear un "
            "sprint, despachar, pausar, reanudar o aprobar una entrega.",
            "I cannot do that with the factory. Ask me for the status, to create "
            "a sprint, dispatch, pause, resume or approve a delivery.",
        )

    handler = _HANDLERS[action]
    return await handler(req, action, language, session, caller)
