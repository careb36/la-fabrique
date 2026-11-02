"""The speech service's API, with stand-in engines: no model on disk."""

from __future__ import annotations

import io
import sys
import wave
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import Settings, create_app  # noqa: E402
from audio import decode_wav  # noqa: E402
from engines import Transcript, pick_language  # noqa: E402


class FakeTranscriber:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def transcribe(self, samples, *, languages, preferred, prompt):
        self.calls.append({"n": len(samples), "languages": languages, "preferred": preferred, "prompt": prompt})
        return Transcript(text="aprobá", language=preferred or languages[0], seconds=0.1)

    def describe(self):
        return {"engine": "fake"}


class FakeSynthesizer:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def speak(self, text, *, language, voice):
        self.calls.append({"text": text, "language": language, "voice": voice})
        return np.linspace(-0.5, 0.5, 2400, dtype=np.float32), 24_000

    def describe(self):
        return {"engine": "fake-voice"}


def wav_bytes(seconds: float = 0.5, rate: int = 16_000, channels: int = 1) -> bytes:
    pcm = (np.sin(np.linspace(0, 440 * 2 * np.pi * seconds, int(rate * seconds))) * 8000).astype("<i2")
    if channels == 2:
        pcm = np.repeat(pcm, 2)
    out = io.BytesIO()
    with wave.open(out, "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(pcm.tobytes())
    return out.getvalue()


@pytest.fixture
def service(monkeypatch):
    monkeypatch.delenv("SPEECH_API_KEY", raising=False)
    stt, tts = FakeTranscriber(), FakeSynthesizer()
    client = TestClient(create_app(stt, tts, Settings()))
    return client, stt, tts


def test_health_describes_both_engines(service):
    client, _, _ = service
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["transcriber"] == {"engine": "fake"}
    assert body["synthesizer"] == {"engine": "fake-voice"}
    assert body["languages"] == ["es", "en"]


def test_transcribe_resamples_and_passes_the_languages_prior_and_prompt(service):
    client, stt, _ = service
    response = client.post(
        "/v1/transcribe?languages=es,en&preferred=es&prompt=Aprob%C3%A1.%20Devolvela.",
        content=wav_bytes(seconds=0.5, rate=48_000, channels=2),
        headers={"Content-Type": "audio/wav"},
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"text": "aprobá", "language": "es", "seconds": 0.1}
    call = stt.calls[0]
    assert call["languages"] == ["es", "en"]
    assert call["preferred"] == "es"
    assert call["prompt"] == "Aprobá. Devolvela."
    # Half a second at 48 kHz stereo arrives as half a second at 16 kHz mono.
    assert abs(call["n"] - 8000) <= 2


def test_transcribe_refuses_what_is_not_a_wav_or_names_no_language(service):
    client, _, _ = service
    assert client.post("/v1/transcribe", content=b"not audio").status_code == 422
    assert client.post("/v1/transcribe", content=b"").status_code == 422
    assert client.post("/v1/transcribe?languages=fr", content=wav_bytes()).status_code == 422
    assert client.post("/v1/transcribe?preferred=fr", content=wav_bytes()).status_code == 422


def test_speak_answers_a_wav_in_the_voice_asked(service):
    client, _, tts = service
    response = client.post("/v1/speak", json={"text": "Aprobada.", "language": "es", "voice": "ef_dora"})
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.headers["x-sample-rate"] == "24000"
    samples, rate = decode_wav(response.content)
    assert rate == 24_000 and len(samples) == 2400
    assert tts.calls == [{"text": "Aprobada.", "language": "es", "voice": "ef_dora"}]


def test_speak_validates_its_input(service):
    client, _, _ = service
    assert client.post("/v1/speak", json={"text": "", "language": "es"}).status_code == 422
    assert client.post("/v1/speak", json={"text": "hola", "language": "fr"}).status_code == 422
    assert client.post("/v1/speak", json={"text": "hola", "language": "es", "voice": "../x"}).status_code == 422


def test_api_key_guards_the_two_routes_but_not_health(monkeypatch):
    monkeypatch.setenv("SPEECH_API_KEY", "secret")
    client = TestClient(create_app(FakeTranscriber(), FakeSynthesizer(), Settings()))
    assert client.get("/health").status_code == 200
    assert client.post("/v1/speak", json={"text": "hola", "language": "es"}).status_code == 401
    assert client.post("/v1/transcribe", content=wav_bytes()).status_code == 401
    assert client.post("/v1/speak", json={"text": "hola", "language": "es"}, headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.post("/v1/speak", json={"text": "hola", "language": "es"}, headers={"X-API-Key": "secret"}).status_code == 200


def test_cors_allows_only_the_origins_configured(monkeypatch):
    monkeypatch.delenv("SPEECH_API_KEY", raising=False)
    monkeypatch.setenv("SPEECH_CORS_ORIGINS", "https://careb36.github.io, http://localhost:5173")
    client = TestClient(create_app(FakeTranscriber(), FakeSynthesizer(), Settings()))
    ok = client.options("/v1/speak", headers={"Origin": "https://careb36.github.io", "Access-Control-Request-Method": "POST"})
    assert ok.headers.get("access-control-allow-origin") == "https://careb36.github.io"
    no = client.options("/v1/speak", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in no.headers


def test_pick_language_prefers_the_pages_language_on_a_close_call():
    assert pick_language({"es": 0.55, "en": 0.40}, ["es", "en"], preferred="en") == "en"
    assert pick_language({"es": 0.55, "en": 0.40}, ["es", "en"], preferred=None) == "es"
    assert pick_language({"es": 0.90, "en": 0.05, "ja": 0.95}, ["es", "en"], preferred="en") == "es"
    assert pick_language({"es": 0.90, "en": 0.05}, ["en"], preferred=None) == "en"
