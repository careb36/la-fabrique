"""The understanding tier: the model asked for a fixed answer, read strictly."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import Settings, create_app  # noqa: E402
from intent import ActionDescription, Intent, LlmIntentResolver, catalogue_text, parse_answer  # noqa: E402
from test_app import FakeSynthesizer, FakeTranscriber  # noqa: E402

ACTIONS = [
    ActionDescription("approve", "aprobar", "aprueba la entrega que espera"),
    ActionDescription("pause", "pausar"),
    ActionDescription("launch", "lanzar una tarea", items=[{"id": "reset", "label": "Password reset endpoint"}, {"id": "csv", "label": "CSV export"}]),
]


def test_parse_accepts_only_what_the_catalogue_has():
    assert parse_answer('{"intent": "approve", "item": null, "reply": "Dale."}', ACTIONS) == Intent("approve", None, "Dale.")
    assert parse_answer('{"intent": "launch", "item": "csv", "reply": null}', ACTIONS) == Intent("launch", "csv", None)
    # An item the action does not have, an action outside the list, garbage.
    assert parse_answer('{"intent": "launch", "item": "deploy"}', ACTIONS) == Intent("launch", None, None)
    assert parse_answer('{"intent": "approve", "item": "csv"}', ACTIONS) == Intent("approve", None, None)
    assert parse_answer('{"intent": "format_disk", "reply": "Sure!"}', ACTIONS) == Intent(None, None, "Sure!")
    assert parse_answer("I think they want to approve.", ACTIONS) == Intent(None)
    assert parse_answer("", ACTIONS) == Intent(None)
    assert parse_answer('Claro: {"intent": "yes", "item": null, "reply": null} eso.', ACTIONS) == Intent("yes")


def test_catalogue_text_lists_actions_and_items():
    text = catalogue_text(ACTIONS, "es")
    assert "- approve: aprobar — aprueba la entrega que espera" in text
    assert "- launch: lanzar una tarea · elementos: reset (Password reset endpoint), csv (CSV export)" in text


def test_resolver_asks_in_the_language_spoken_and_reads_the_answer():
    seen = {}

    def post(url, headers, payload):
        seen["url"], seen["headers"], seen["payload"] = url, headers, payload
        return {"choices": [{"message": {"content": '{"intent": "pause", "item": null, "reply": "En pausa."}'}}]}

    resolver = LlmIntentResolver("https://llm.example/v1/", "nemotron", "key", post=post)
    result = resolver.resolve("¿podrías frenar esto un segundito?", "es", ACTIONS, context="sala XR")
    assert result == Intent("pause", None, "En pausa.")
    assert seen["url"] == "https://llm.example/v1/chat/completions"
    assert seen["headers"]["Authorization"] == "Bearer key"
    assert seen["payload"]["model"] == "nemotron"
    assert seen["payload"]["temperature"] == 0
    system, user = seen["payload"]["messages"]
    assert system["role"] == "system" and "intérprete de voz" in system["content"]
    assert "Contexto: sala XR" in user["content"]
    assert "La persona dijo: «¿podrías frenar esto un segundito?»" in user["content"]


def test_resolver_without_a_model_or_unreachable_fails_loudly():
    with pytest.raises(RuntimeError):
        LlmIntentResolver("", "", "").resolve("hola", "es", ACTIONS)

    def down(url, headers, payload):
        raise OSError("connection refused")

    with pytest.raises(RuntimeError):
        LlmIntentResolver("https://x", "m", post=down).resolve("hola", "es", ACTIONS)


def test_resolver_treats_a_malformed_completion_as_no_answer():
    resolver = LlmIntentResolver("https://x", "m", post=lambda *a: {"choices": []})
    assert resolver.resolve("hola", "en", ACTIONS) == Intent(None)


class FakeResolver:
    def __init__(self) -> None:
        self.calls = []

    def resolve(self, transcript, lang, actions, context):
        self.calls.append((transcript, lang, [a.id for a in actions], context))
        return Intent("launch", "csv", "Lanzo la exportación.")

    def describe(self):
        return {"engine": "fake-intent"}


def test_intent_route_passes_the_catalogue_and_answers(monkeypatch):
    monkeypatch.delenv("SPEECH_API_KEY", raising=False)
    resolver = FakeResolver()
    client = TestClient(create_app(FakeTranscriber(), FakeSynthesizer(), Settings(), resolver))
    response = client.post(
        "/v1/intent",
        json={
            "transcript": "dale con la planilla",
            "language": "es",
            "context": "La Fabrique XR",
            "actions": [
                {"id": "approve", "label": "aprobar"},
                {"id": "launch", "label": "lanzar una tarea", "items": [{"id": "csv", "label": "CSV export"}]},
            ],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"intent": "launch", "item": "csv", "reply": "Lanzo la exportación."}
    assert resolver.calls == [("dale con la planilla", "es", ["approve", "launch"], "La Fabrique XR")]
    assert client.get("/health").json()["intent"] == {"engine": "fake-intent"}


def test_intent_route_validates_and_reports_a_missing_model(monkeypatch):
    monkeypatch.delenv("SPEECH_API_KEY", raising=False)
    for var in ("SPEECH_LLM_URL", "SPEECH_LLM_MODEL", "SPEECH_LLM_KEY"):
        monkeypatch.delenv(var, raising=False)
    client = TestClient(create_app(FakeTranscriber(), FakeSynthesizer(), Settings()))
    assert client.post("/v1/intent", json={"transcript": "x", "actions": []}).status_code == 422
    assert client.post("/v1/intent", json={"transcript": "x", "actions": [{"id": "Bad Id", "label": "x"}]}).status_code == 422
    unconfigured = client.post("/v1/intent", json={"transcript": "hola", "actions": [{"id": "pause", "label": "pausar"}]})
    assert unconfigured.status_code == 503
