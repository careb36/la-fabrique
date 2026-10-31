"""Streamed answers: sentences cut as they arrive, SSE read, spoken before the end."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from b1.assistant import Assistant
from b1.config import Settings
from b1.llm import ModelError, OpenAICompatModel, Reply, ToolCall
from b1.sentences import SentenceBuffer
from b1.speech import Silence
from b1.tools import ToolRegistry, object_schema


# -- the sentence buffer -------------------------------------------------------
def feed_all(pieces, **kwargs):
    buffer = SentenceBuffer(**kwargs)
    out = []
    for piece in pieces:
        out.extend(buffer.feed(piece))
    return out, buffer.flush()


def test_sentences_come_out_as_soon_as_they_end():
    buffer = SentenceBuffer()
    assert buffer.feed("La fábrica tiene tres tar") == []
    assert buffer.feed("eas abiertas. Una espera") == ["La fábrica tiene tres tareas abiertas."]
    assert buffer.flush() == ["Una espera"]


def test_a_short_sentence_waits_for_the_next_one():
    sentences, rest = feed_all(["Sí. ", "Ya la armo y te aviso cuando esté. ", "Listo"])
    assert sentences == ["Sí. Ya la armo y te aviso cuando esté."]
    assert rest == ["Listo"]


def test_numbers_hosts_and_abbreviations_do_not_end_a_sentence():
    text = "La versión 3.5 corre en b1.local con el Dr. Pérez desde hoy mismo. Fin"
    sentences, rest = feed_all(list(text))
    assert sentences == ["La versión 3.5 corre en b1.local con el Dr. Pérez desde hoy mismo."]
    assert rest == ["Fin"]


def test_questions_exclamations_quotes_and_line_breaks_end_one():
    sentences, rest = feed_all(
        ['¿Querés que la construya ahora? ', '¡Perfecto, arranco ya mismo!" ', "- primero\n", "- segundo"]
    )
    assert sentences == [
        "¿Querés que la construya ahora?",
        '¡Perfecto, arranco ya mismo!"',
        "- primero",
    ]
    assert rest == ["- segundo"]


def test_flush_on_an_empty_buffer_says_nothing():
    buffer = SentenceBuffer()
    buffer.feed("   ")
    assert buffer.flush() == []


# -- the SSE client ------------------------------------------------------------
def sse(*chunks, done=True) -> bytes:
    lines = [f"data: {json.dumps(chunk)}\n\n" for chunk in chunks]
    if done:
        lines.append("data: [DONE]\n\n")
    return ": keep-alive\n\n".join(lines).encode("utf-8")


def delta(**fields) -> dict:
    return {"choices": [{"index": 0, "delta": fields}]}


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        return

    def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler API
        length = int(self.headers.get("Content-Length") or 0)
        self.server.seen.append(json.loads(self.rfile.read(length)))
        status, kind, body = self.server.answer
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture()
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    httpd.seen = []
    httpd.answer = (200, "text/event-stream", b"")
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd
    httpd.shutdown()


def model_for(httpd) -> OpenAICompatModel:
    return OpenAICompatModel(f"http://127.0.0.1:{httpd.server_port}/v1", "", "test-model", timeout=5)


def test_text_arrives_piece_by_piece_and_the_reasoning_stays_apart(server):
    server.answer = (
        200,
        "text/event-stream; charset=utf-8",
        sse(
            delta(role="assistant", reasoning_content="PENSANDO "),
            delta(reasoning_content="en silencio"),
            delta(content="Hola, "),
            delta(content="todo en orden."),
            {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
        ),
    )
    pieces: list[str] = []
    reply = model_for(server).stream([{"role": "user", "content": "hola"}], [], pieces.append)

    assert pieces == ["Hola, ", "todo en orden."]
    assert reply.text == "Hola, todo en orden."
    assert reply.reasoning == "PENSANDO en silencio"
    assert reply.tool_calls == []
    assert server.seen[0]["stream"] is True


def test_tool_call_fragments_are_put_back_together(server):
    server.answer = (
        200,
        "text/event-stream",
        sse(
            delta(tool_calls=[{"index": 0, "id": "call_a", "type": "function",
                               "function": {"name": "factory_build", "arguments": ""}}]),
            delta(tool_calls=[{"index": 0, "function": {"arguments": '{"texto": '}}]),
            delta(tool_calls=[{"index": 0, "function": {"name": "factory_build",
                                                         "arguments": '"una landing"}'}}]),
            delta(tool_calls=[{"index": 1, "id": "call_b",
                               "function": {"name": "factory_status", "arguments": {}}}]),
        ),
    )
    reply = model_for(server).stream([], [{"type": "function"}], lambda _p: None)

    assert reply.tool_calls == [
        ToolCall(id="call_a", name="factory_build", arguments='{"texto": "una landing"}'),
        ToolCall(id="call_b", name="factory_status", arguments="{}"),
    ]
    assert json.loads(reply.tool_calls[0].arguments) == {"texto": "una landing"}


def test_a_server_that_ignores_stream_still_answers(server):
    body = {"choices": [{"message": {"role": "assistant", "content": "Respuesta entera."}}]}
    server.answer = (200, "application/json", json.dumps(body).encode())
    pieces: list[str] = []
    reply = model_for(server).stream([], [], pieces.append)
    assert reply.text == "Respuesta entera."
    assert pieces == ["Respuesta entera."]


def test_stream_errors_become_model_errors(server):
    server.answer = (401, "application/json", b'{"error": "bad key"}')
    with pytest.raises(ModelError, match="401"):
        model_for(server).stream([], [], lambda _p: None)

    server.answer = (200, "text/event-stream", sse({"error": {"message": "overloaded"}}))
    with pytest.raises(ModelError, match="overloaded"):
        model_for(server).stream([], [], lambda _p: None)

    server.answer = (200, "text/event-stream", b"data: [DONE]\n\n")
    with pytest.raises(ModelError):
        model_for(server).stream([], [], lambda _p: None)


def test_an_unreachable_server_is_a_model_error():
    model = OpenAICompatModel("http://127.0.0.1:9/v1", "", "m", timeout=2)
    with pytest.raises(ModelError):
        model.stream([], [], lambda _p: None)


def test_the_plain_request_still_asks_without_streaming(server):
    body = {"choices": [{"message": {"content": "ok"}}]}
    server.answer = (200, "application/json", json.dumps(body).encode())
    assert model_for(server).complete([], []).text == "ok"
    assert server.seen[0]["stream"] is False


# -- the assistant speaks while the model writes ------------------------------
class StreamingModel:
    """Writes each scripted turn in pieces, slowly, like a real endpoint."""

    def __init__(self, *turns, pause=0.05):
        self.turns = list(turns)
        self.pause = pause
        self.finished_at: list[float] = []

    def complete(self, messages, tools):  # pragma: no cover - never used when streaming
        raise AssertionError("the streaming path should not call complete()")

    def stream(self, messages, tools, on_text):
        pieces, reply = self.turns.pop(0)
        for piece in pieces:
            on_text(piece)
            time.sleep(self.pause)
        self.finished_at.append(time.monotonic())
        return reply


class TimedSpeaker(Silence):
    def __init__(self):
        self.said: list[tuple[float, str]] = []

    def say(self, text: str) -> None:
        self.said.append((time.monotonic(), text))


def make(model, *, registry=None, events=None, **cfg):
    settings = Settings(language="es", briefing=False, open_build_in_browser=False)
    for key, value in cfg.items():
        setattr(settings, key, value)
    speaker = TimedSpeaker()
    assistant = Assistant(
        settings,
        model,
        registry or ToolRegistry(),
        speaker=speaker,
        on_event=events.append if events is not None else None,
    )
    return assistant, speaker


def test_the_first_sentence_is_spoken_before_the_model_finishes():
    text = "La fábrica tiene tres tareas abiertas. Una espera tu aprobación desde ayer. Nada más."
    pieces = [text[i : i + 6] for i in range(0, len(text), 6)]
    model = StreamingModel((pieces, Reply(text=text)), pause=0.02)
    events: list[dict] = []
    assistant, speaker = make(model, events=events)

    answer = asyncio.run(assistant.handle("¿cómo está la fábrica?"))

    assert answer == text
    spoken = [s for _, s in speaker.said]
    assert spoken == [
        "La fábrica tiene tres tareas abiertas.",
        "Una espera tu aprobación desde ayer.",
        "Nada más.",
    ]
    assert speaker.said[0][0] < model.finished_at[0], "nothing was said until the end"
    parts = [e["text"] for e in events if e["type"] == "reply_part"]
    assert parts == spoken
    final = [e for e in events if e["type"] == "reply"]
    assert final == [{"type": "reply", "text": text, "streamed": True}]
    states = [e["value"] for e in events if e["type"] == "state"]
    assert states == ["thinking", "speaking", "idle"]


def test_words_before_a_tool_call_are_spoken_and_the_answer_is_not_repeated():
    registry = ToolRegistry()
    registry.register(
        "factory_status", "estado", object_schema({}), lambda **_: json.dumps({"ok": True})
    )
    model = StreamingModel(
        (["Dejame mirar la fábrica un segundo. "], Reply(
            text="Dejame mirar la fábrica un segundo.",
            tool_calls=[ToolCall(id="c1", name="factory_status")],
        )),
        (["Todo en orden, sin tareas pendientes."], Reply(text="Todo en orden, sin tareas pendientes.")),
        pause=0,
    )
    assistant, speaker = make(model, registry=registry)
    answer = asyncio.run(assistant.handle("estado"))

    assert answer == "Todo en orden, sin tareas pendientes."
    assert [s for _, s in speaker.said] == [
        "Dejame mirar la fábrica un segundo.",
        "Todo en orden, sin tareas pendientes.",
    ]


def test_a_tool_turn_with_an_empty_answer_still_says_something():
    registry = ToolRegistry()
    registry.register(
        "factory_status", "estado", object_schema({}), lambda **_: json.dumps({"ok": True})
    )
    model = StreamingModel(
        (["Un momento que reviso todo. "], Reply(
            text="Un momento que reviso todo.",
            tool_calls=[ToolCall(id="c1", name="factory_status")],
        )),
        ([], Reply(text="")),
        pause=0,
    )
    assistant, speaker = make(model, registry=registry)
    answer = asyncio.run(assistant.handle("estado"))
    spoken = [s for _, s in speaker.said]
    assert spoken[0] == "Un momento que reviso todo."
    assert spoken[-1] == answer and answer  # the "done" line, said once


def test_a_failure_mid_stream_is_said_after_what_was_already_spoken():
    class Failing(StreamingModel):
        def stream(self, messages, tools, on_text):
            on_text("Empiezo a contarte lo que veo. ")
            raise ModelError("se cortó")

    assistant, speaker = make(Failing(pause=0))
    answer = asyncio.run(assistant.handle("estado"))
    spoken = [s for _, s in speaker.said]
    assert spoken[0] == "Empiezo a contarte lo que veo."
    assert spoken[-1] == answer and "se cortó" in answer


def test_streaming_can_be_turned_off():
    class Both(StreamingModel):
        def complete(self, messages, tools):
            return Reply(text="Respuesta entera, de una sola vez.")

    model = Both((["no"], Reply(text="no")))
    assistant, speaker = make(model, model_stream=False)
    asyncio.run(assistant.handle("hola"))
    assert [s for _, s in speaker.said] == ["Respuesta entera, de una sola vez."]
    assert model.turns, "stream() was called although it was turned off"
