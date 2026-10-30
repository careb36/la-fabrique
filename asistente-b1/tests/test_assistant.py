"""The turn loop: tool calls, languages, failures and the startup guide."""

from __future__ import annotations

import asyncio
import webbrowser

import pytest

from b1 import fabrica
from b1.assistant import Assistant, build_assistant, detect_language
from b1.config import Settings
from b1.llm import ModelError, Reply, ToolCall
from b1.speech import ConsoleSpeaker, Silence
from b1.tools import ToolRegistry, object_schema


class ScriptedModel:
    """Hands back prepared replies in order and records what it was asked."""

    def __init__(self, *replies: Reply) -> None:
        self.replies = list(replies)
        self.calls: list[dict] = []

    def complete(self, messages, tools):
        self.calls.append({"messages": [dict(m) for m in messages], "tools": tools})
        if not self.replies:
            return Reply(text="sin guion")
        return self.replies.pop(0)


class RecordingSpeaker(Silence):
    def __init__(self) -> None:
        self.said: list[str] = []

    def say(self, text: str) -> None:
        self.said.append(text)


def settings(**overrides) -> Settings:
    base = Settings(language="es", briefing=False, open_build_in_browser=False)
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def make(repies_model, *, registry=None, speaker=None, events=None, **kwargs):
    registry = registry or ToolRegistry()
    assistant = Assistant(
        kwargs.pop("cfg", settings()),
        repies_model,
        registry,
        speaker=speaker or Silence(),
        on_event=events.append if events is not None else None,
        **kwargs,
    )
    return assistant


def test_plain_answer_needs_no_tools():
    model = ScriptedModel(Reply(text="  Son   las diez. "))
    assistant = make(model)
    answer = asyncio.run(assistant.handle("¿qué hora es?"))
    assert answer == "Son las diez."
    assert model.calls[0]["tools"] == []


def test_tool_call_then_answer():
    calls: list[dict] = []
    registry = ToolRegistry()

    def status() -> dict:
        calls.append({"hit": True})
        return {"ok": True, "speech": "Hay un sprint en curso."}

    registry.register("factory_status", "estado", object_schema({}), status)

    model = ScriptedModel(
        Reply(tool_calls=[ToolCall("c1", "factory_status", "{}")]),
        Reply(text="Hay un sprint en curso."),
    )
    assistant = make(model, registry=registry)
    answer = asyncio.run(assistant.handle("¿cómo va la fábrica?"))

    assert answer == "Hay un sprint en curso."
    assert calls == [{"hit": True}]
    second_call = model.calls[1]["messages"]
    assert second_call[-1]["role"] == "tool"
    assert second_call[-1]["tool_call_id"] == "c1"
    assert second_call[-2]["tool_calls"][0]["function"]["name"] == "factory_status"


def test_tool_error_is_fed_back_to_the_model():
    registry = ToolRegistry()

    def boom() -> str:
        raise RuntimeError("disco lleno")

    registry.register("boom", "falla", object_schema({}), boom)
    model = ScriptedModel(
        Reply(tool_calls=[ToolCall("c1", "boom", "{}")]),
        Reply(text="No pude: el disco está lleno."),
    )
    assistant = make(model, registry=registry)
    asyncio.run(assistant.handle("guardá esto"))
    tool_message = model.calls[1]["messages"][-1]
    assert "disco lleno" in tool_message["content"]


def test_loop_is_bounded():
    registry = ToolRegistry()
    registry.register("spin", "gira", object_schema({}), lambda: "sigo")
    forever = Reply(tool_calls=[ToolCall("c1", "spin", "{}")])
    model = ScriptedModel(*([forever] * 10))
    assistant = make(model, registry=registry)
    answer = asyncio.run(assistant.handle("dale"))
    assert "vueltas" in answer
    assert len(model.calls) <= 5


def test_missing_model_explains_itself():
    assistant = make(None)
    answer = asyncio.run(assistant.handle("hola"))
    assert "clave del modelo" in answer


def test_model_failure_is_spoken_not_raised():
    class Failing:
        def complete(self, messages, tools):
            raise ModelError("HTTP 401")

    events: list[dict] = []
    assistant = make(Failing(), events=events)
    answer = asyncio.run(assistant.handle("hola"))
    assert "401" in answer
    assert any(event["type"] == "error" for event in events)


def test_events_describe_the_whole_turn():
    events: list[dict] = []
    speaker = RecordingSpeaker()
    assistant = make(ScriptedModel(Reply(text="Listo.")), events=events, speaker=speaker)

    asyncio.run(assistant.handle("hacelo"))

    states = [e["value"] for e in events if e["type"] == "state"]
    assert states == ["thinking", "speaking", "idle"]
    assert speaker.said == ["Listo."]


def test_startup_shows_the_guide_and_says_the_summary():
    events: list[dict] = []
    speaker = RecordingSpeaker()
    assistant = make(
        ScriptedModel(), cfg=settings(briefing=True), events=events, speaker=speaker
    )
    result = asyncio.run(assistant.startup())

    guide_events = [e for e in events if e["type"] == "guide"]
    assert guide_events and guide_events[0]["title"] == fabrica.guide_title("es")
    assert result["text"] == fabrica.guide_text("es")
    assert speaker.said == [fabrica.spoken_summary("es")]


def test_startup_can_stay_silent():
    speaker = RecordingSpeaker()
    assistant = make(ScriptedModel(), speaker=speaker)
    asyncio.run(assistant.startup())
    assert speaker.said == []


def test_language_follows_the_person():
    speaker = RecordingSpeaker()
    assistant = make(
        ScriptedModel(Reply(text="Sure."), Reply(text="Dale.")), speaker=speaker
    )
    asyncio.run(assistant.handle("what is the status please"))
    assert assistant.language == "en"
    asyncio.run(assistant.handle("¿y ahora qué hago? dale"))
    assert assistant.language == "es"


def test_history_is_kept_and_reset():
    assistant = make(ScriptedModel(Reply(text="uno"), Reply(text="dos")))
    asyncio.run(assistant.handle("primera"))
    asyncio.run(assistant.handle("segunda"))
    messages = assistant._messages()
    contents = [m["content"] for m in messages]
    assert "primera" in contents and "segunda" in contents
    assistant.reset()
    assert len(assistant._messages()) == 1


def test_build_url_is_opened_once(monkeypatch):
    opened: list[str] = []
    monkeypatch.setattr(webbrowser, "open", lambda url, new=0: opened.append(url))

    registry = ToolRegistry()

    preview = "http://x/v1/voice/build/pagina/index.html"

    def factory_build(texto: str) -> dict:
        return {"ok": True, "speech": "Listo.", "data": {"url": preview}}

    registry.register(
        "factory_build", "construye", object_schema({"texto": {"type": "string"}}, ["texto"]),
        factory_build,
    )
    model = ScriptedModel(
        Reply(tool_calls=[ToolCall("c1", "factory_build", '{"texto": "una página"}')]),
        Reply(text="Listo: te la abrí."),
    )
    events: list[dict] = []
    assistant = make(
        model,
        registry=registry,
        events=events,
        cfg=settings(open_build_in_browser=True),
        factory=fabrica.FactoryClient("http://x"),
    )
    asyncio.run(assistant.handle("armá una página"))
    assert opened == [preview]
    assert any(event["type"] == "opened" for event in events)


@pytest.mark.parametrize(
    "url",
    ["file:///etc/passwd", "http://evil.example/v1/voice/build/x", "\\\\host\\share\\x.exe"],
)
def test_only_the_factory_previews_are_opened(monkeypatch, url):
    opened: list[str] = []
    monkeypatch.setattr(webbrowser, "open", lambda u, new=0: opened.append(u))
    registry = ToolRegistry()
    registry.register(
        "factory_status", "estado", object_schema({}),
        lambda: {"ok": True, "speech": "x", "data": {"url": url}},
    )
    model = ScriptedModel(
        Reply(tool_calls=[ToolCall("c1", "factory_status", "{}")]), Reply(text="ok")
    )
    assistant = make(
        model,
        registry=registry,
        cfg=settings(open_build_in_browser=True),
        factory=fabrica.FactoryClient("http://x"),
    )
    asyncio.run(assistant.handle("estado"))
    assert opened == []


def test_build_url_is_not_opened_when_disabled(monkeypatch):
    opened: list[str] = []
    monkeypatch.setattr(webbrowser, "open", lambda url, new=0: opened.append(url))
    registry = ToolRegistry()
    registry.register(
        "factory_build",
        "construye",
        object_schema({"texto": {"type": "string"}}, ["texto"]),
        lambda texto: {"ok": True, "data": {"url": "http://x/y"}},
    )
    model = ScriptedModel(
        Reply(tool_calls=[ToolCall("c1", "factory_build", '{"texto": "algo"}')]),
        Reply(text="Hecho."),
    )
    assistant = make(model, registry=registry)
    asyncio.run(assistant.handle("construí algo"))
    assert opened == []


@pytest.mark.parametrize(
    ("phrase", "expected"),
    [
        ("¿cómo va la fábrica?", "es"),
        ("build me a calculator please", "en"),
        ("decime el estado del sprint", "es"),
        ("what is the status with the team", "en"),
    ],
)
def test_detect_language(phrase, expected):
    assert detect_language(phrase, "es") == expected


def test_factory_language_follows_the_turn():
    client = fabrica.FactoryClient("http://127.0.0.1:9", "", language="es")
    assistant = make(
        ScriptedModel(Reply(text="ok")),
        factory=client,
    )
    asyncio.run(assistant.handle("what is the status please"))
    assert client.language == "en"


def test_assistant_without_factory_has_no_factory_tools():
    assistant = build_assistant(settings(factory_url=""))
    assert assistant.registry.names() == []


def test_assistant_with_factory_registers_its_tools():
    assistant = build_assistant(settings(factory_url="http://127.0.0.1:9", voice_key="k"))
    assert set(assistant.registry.names()) == {
        "factory_status",
        "factory_command",
        "factory_build",
    }


def test_console_speaker_prints(capsys):
    ConsoleSpeaker().say("hola")
    assert "hola" in capsys.readouterr().out
