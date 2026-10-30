"""Who is speaking to ``/v1/voice/*`` and how its answers are shaped.

Shared by the voice router and its action handlers (``routers/voice_actions.py``).
"""

import secrets
from dataclasses import dataclass

from auth_policy import current_user_if_required
from config import settings
from database import get_session
from fastapi import Depends, HTTPException, Request
from models import Company, User
from services import voice_control
from sqlmodel import Session

# The date a voice-created sprint starts on; the factory itself only stores it.
_LANGUAGE = "es"


@dataclass
class VoiceCaller:
    """Who is speaking: the shared key (owner-equivalent) or a real user."""

    user: User | None
    via_key: bool


async def voice_access(
    request: Request,
    session: Session = Depends(get_session),  # noqa: B008 - FastAPI dependency marker.
) -> VoiceCaller:
    configured = (settings.VOICE_API_KEY or "").strip()
    provided = (request.headers.get("X-Voice-Key") or "").strip()

    if configured:
        if provided and secrets.compare_digest(provided, configured):
            return VoiceCaller(user=None, via_key=True)
        try:
            user = await current_user_if_required(request, session)
        except HTTPException:
            user = None
        if user is not None:
            return VoiceCaller(user=user, via_key=False)
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing X-Voice-Key",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not settings.AUTH_REQUIRED:
        return VoiceCaller(user=None, via_key=False)

    raise HTTPException(
        status_code=503,
        detail="Voice control is not configured (set VOICE_API_KEY)",
    )


def _result(
    action: str,
    speech: str,
    data: dict | None = None,
    company_id: int | None = None,
    ok: bool = True,
) -> dict:
    return {
        "ok": ok,
        "action": action,
        "speech": speech,
        "data": data or {},
        "company_id": company_id,
    }


def _fail(action: str, language: str, speech_es: str, speech_en: str, **extra) -> dict:
    return _result(
        action,
        voice_control.say(language, speech_es, speech_en),
        extra.pop("data", {}),
        extra.pop("company_id", None),
        ok=False,
    )


def _company(
    session: Session, requested: int | None, action: str, language: str
) -> tuple[Company | None, dict | None]:
    company_id = requested if requested is not None else settings.VOICE_COMPANY_ID
    company = voice_control.resolve_company(session, company_id)
    if company is not None:
        return company, None
    if company_id is not None:
        return None, _fail(
            action,
            language,
            "No encuentro esa empresa en la fábrica.",
            "I cannot find that company in the factory.",
        )
    return None, _fail(
        action,
        language,
        "La fábrica todavía no tiene ninguna empresa. Créala primero en la "
        "aplicación web y vuelve a pedírmelo.",
        "The factory has no company yet. Create one in the web app first, then ask me again.",
    )


def status_answer(
    session: Session,
    company_id: int | None,
    sprint_id: int | None,
    language: str | None,
) -> dict:
    """What the factory is doing, as one sentence plus its numbers."""
    language = voice_control.normalize_language(language or _LANGUAGE)
    company, failure = _company(session, company_id, "estado", language)
    if failure:
        return failure

    snapshot = voice_control.status_snapshot(session, company, sprint_id)
    return _result(
        "estado",
        voice_control.status_speech(snapshot, language),
        snapshot,
        company.id,
    )
