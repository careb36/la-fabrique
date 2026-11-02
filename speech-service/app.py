"""The speech service: the server tier of the voice layer.

Two routes any client of the voice layer can call when a backend is at
hand (La Fabrique in live mode, OSINT Orchestrator, the desktop assistant):

- ``POST /v1/transcribe``: 16-bit PCM WAV in the body, a transcript out,
  with the language detected among those the client speaks (`languages`),
  the page's language winning a close call (`preferred`), and the client's
  vocabulary as Whisper's previous text (`prompt`).
- ``POST /v1/speak``: JSON {text, language, voice?} in, WAV out (Kokoro).

With ``SPEECH_API_KEY`` set, both take it in ``X-API-Key``; ``/health``
never needs it. ``SPEECH_CORS_ORIGINS`` lists the pages allowed to call
from a browser. The engines are loaded on first use: the recognizer's
model downloads then, so the first transcript can take minutes; a client
that wants them warm calls ``/health?warm=1`` once.
"""

from __future__ import annotations

import os
import secrets

from fastapi import FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from audio import SAMPLE_RATE, AudioError, decode_wav, encode_wav, resample
from engines import KokoroEngine, Synthesizer, Transcriber, WhisperEngine
from intent import ActionDescription, IntentResolver, LlmIntentResolver

MAX_AUDIO_BYTES = 10 * 1024 * 1024  # about five minutes at 16 kHz, far more than a phrase
MAX_TEXT_CHARS = 2000
LANGUAGES = ("es", "en")


class Settings:
    def __init__(self) -> None:
        self.api_key = os.getenv("SPEECH_API_KEY", "").strip()
        self.cors_origins = [o.strip() for o in os.getenv("SPEECH_CORS_ORIGINS", "").split(",") if o.strip()]
        self.stt_model = os.getenv("SPEECH_STT_MODEL", "large-v3-turbo")
        self.device = os.getenv("SPEECH_DEVICE", "cpu")
        self.compute_type = os.getenv("SPEECH_COMPUTE_TYPE", "int8" if self.device == "cpu" else "float16")
        # The understanding tier: any OpenAI-compatible chat endpoint.
        self.llm_url = os.getenv("SPEECH_LLM_URL", "").strip()
        self.llm_key = os.getenv("SPEECH_LLM_KEY", "").strip()
        self.llm_model = os.getenv("SPEECH_LLM_MODEL", "").strip()


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_TEXT_CHARS)
    language: str = Field(default="es", pattern="^(es|en)$")
    voice: str | None = Field(default=None, max_length=40, pattern="^[a-z_]+$")


class TranscribeResponse(BaseModel):
    text: str
    language: str
    seconds: float


class ItemDescription(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=200)


class ActionIn(BaseModel):
    id: str = Field(min_length=1, max_length=80, pattern="^[a-z][a-z0-9_-]*$")
    label: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=400)
    items: list[ItemDescription] = Field(default_factory=list, max_length=60)


class IntentRequest(BaseModel):
    transcript: str = Field(min_length=1, max_length=1000)
    language: str = Field(default="es", pattern="^(es|en)$")
    actions: list[ActionIn] = Field(min_length=1, max_length=60)
    context: str = Field(default="", max_length=1000)


class IntentResponse(BaseModel):
    intent: str | None
    item: str | None
    reply: str | None


def create_app(
    transcriber: Transcriber | None = None,
    synthesizer: Synthesizer | None = None,
    settings: Settings | None = None,
    resolver: IntentResolver | None = None,
) -> FastAPI:
    settings = settings or Settings()
    stt: Transcriber = transcriber or WhisperEngine(settings.stt_model, settings.device, settings.compute_type)
    tts: Synthesizer = synthesizer or KokoroEngine()
    llm: IntentResolver = resolver or LlmIntentResolver(settings.llm_url, settings.llm_model, settings.llm_key)
    app = FastAPI(title="La Fabrique speech service", version="0.1.0", docs_url=None, redoc_url=None)
    if settings.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["POST", "GET"], allow_headers=["Content-Type", "X-API-Key"])

    def authorize(key: str | None) -> None:
        if not settings.api_key:
            return
        if not key or not secrets.compare_digest(key, settings.api_key):
            raise HTTPException(status_code=401, detail="a valid X-API-Key is required")

    @app.get("/health")
    def health(warm: bool = Query(default=False)) -> dict:
        if warm:
            # Loading the models here, on purpose, so the first real request is quick.
            stt.transcribe(resample(_silence(), SAMPLE_RATE), languages=["en"], preferred=None, prompt="")
        return {"status": "ok", "transcriber": stt.describe(), "synthesizer": tts.describe(), "intent": llm.describe(), "languages": list(LANGUAGES)}

    @app.post("/v1/transcribe", response_model=TranscribeResponse)
    async def transcribe(
        request: Request,
        languages: str = Query(default="es,en", description="comma-separated, among es and en"),
        preferred: str | None = Query(default=None, pattern="^(es|en)$"),
        prompt: str = Query(default="", max_length=MAX_TEXT_CHARS),
        x_api_key: str | None = Header(default=None),
    ) -> TranscribeResponse:
        authorize(x_api_key)
        wanted = [code for code in (c.strip() for c in languages.split(",")) if code in LANGUAGES]
        if not wanted:
            raise HTTPException(status_code=422, detail="languages must name es, en or both")
        body = await request.body()
        if not body:
            raise HTTPException(status_code=422, detail="the body must be a 16-bit PCM WAV")
        if len(body) > MAX_AUDIO_BYTES:
            raise HTTPException(status_code=413, detail="audio too long")
        try:
            samples, rate = decode_wav(body)
        except AudioError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        result = stt.transcribe(resample(samples, rate), languages=wanted, preferred=preferred, prompt=prompt)
        return TranscribeResponse(text=result.text, language=result.language, seconds=round(result.seconds, 3))

    @app.post("/v1/speak")
    def speak(body: SpeakRequest, x_api_key: str | None = Header(default=None)) -> Response:
        authorize(x_api_key)
        samples, rate = tts.speak(body.text, language=body.language, voice=body.voice)
        return Response(content=encode_wav(samples, rate), media_type="audio/wav", headers={"X-Sample-Rate": str(rate)})

    @app.post("/v1/intent", response_model=IntentResponse)
    def intent(body: IntentRequest, x_api_key: str | None = Header(default=None)) -> IntentResponse:
        authorize(x_api_key)
        actions = [ActionDescription(a.id, a.label, a.description, [i.model_dump() for i in a.items]) for a in body.actions]
        try:
            result = llm.resolve(body.transcript, body.language, actions, body.context)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from None
        return IntentResponse(intent=result.intent, item=result.item, reply=result.reply)

    return app


def _silence():
    import numpy as np  # noqa: PLC0415

    return np.zeros(SAMPLE_RATE // 2, dtype=np.float32)


app = create_app() if os.getenv("SPEECH_SERVICE_AUTOCREATE", "1") == "1" and __name__ != "__main__" else None

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(create_app(), host=os.getenv("SPEECH_BIND", "0.0.0.0"), port=int(os.getenv("SPEECH_PORT", "5200")))
