"""One full turn over real sockets: model server + factory server + assistant.

Both servers are local ``http.server`` instances that speak the real protocols
(OpenAI ``chat/completions`` with tool calls, and the factory's ``/v1/voice``).
Nothing is stubbed inside the assistant: the code path here is the one a person
gets when they press the button.
"""

from __future__ import annotations

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import pytest

from b1.assistant import Assistant
from b1.config import Settings
from b1.fabrica import FactoryClient, register_tools
from b1.llm import OpenAICompatModel, model_from_settings
from b1.speech import Silence
from b1.tools import ToolRegistry


class _ModelHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        return

    def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler API
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        messages = body.get("messages") or []
        self.server.seen.append({"auth": self.headers.get("Authorization"), "body": body})

        tool_messages = [m for m in messages if m.get("role") == "tool"]
        user_text = " ".join(
            m.get("content") or "" for m in messages if m.get("role") == "user"
        ).lower()

        if not tool_messages:
            if "constru" in user_text or "armá" in user_text:
                call = {
                    "id": "call_build",
                    "type": "function",
                    "function": {
                        "name": "factory_build",
                        "arguments": json.dumps({"texto": "una página de prueba"}),
                    },
                }
            else:
                call = {
                    "id": "call_status",
                    "type": "function",
                    "function": {"name": "factory_status", "arguments": "{}"},
                }
            message = {"role": "assistant", "content": None, "tool_calls": [call]}
        else:
            payload = json.loads(tool_messages[-1]["content"])
            message = {
                "role": "assistant",
                "content": payload.get("speech", "listo"),
                "reasoning_content": "PENSAMIENTO-INTERNO: elegir la respuesta hablada.",
            }

        data = json.dumps({"choices": [{"message": message}]}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class _FactoryHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        return

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlparse(self.path).path
        assert path == "/v1/voice/status", path
        self._send(
            {
                "ok": True,
                "action": "estado",
                "speech": "El sprint de la landing va por la mitad.",
                "data": {"sprint_name": "Landing", "progress": 0.5},
            }
        )

    def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler API
        length = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(length) or b"{}")
        self.server.seen.append(payload)
        self._send(
            {
                "ok": True,
                "action": "crear_proyecto",
                "speech": "Listo: armé dos archivos.",
                "data": {"slug": "pagina-de-prueba", "files": ["index.html", "app.js"]},
            }
        )

    def _send(self, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _serve(handler):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    httpd.seen = []
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


@pytest.fixture()
def stack():
    model = _serve(_ModelHandler)
    factory = _serve(_FactoryHandler)
    yield model, factory
    for httpd in (model, factory):
        httpd.shutdown()
        httpd.server_close()


def build(settings: Settings, model_url: str, factory_url: str):
    registry = ToolRegistry()
    client = FactoryClient(factory_url, "k")
    register_tools(registry, client)
    assistant = Assistant(
        settings,
        OpenAICompatModel(model_url, "test-key", "fake-model"),
        registry,
        factory=client,
        speaker=Silence(),
    )
    return assistant, client


def test_status_turn_end_to_end(stack):
    model, factory = stack
    settings = Settings(language="es", briefing=False, open_build_in_browser=False)
    assistant, _client = build(
        settings,
        f"http://127.0.0.1:{model.server_address[1]}",
        f"http://127.0.0.1:{factory.server_address[1]}",
    )

    answer = asyncio.run(assistant.handle("¿cómo va la fábrica?"))

    assert answer == "El sprint de la landing va por la mitad."
    # The model was asked twice: once to choose a tool, once to answer with it.
    assert len(model.seen) == 2
    first, second = model.seen
    assert first["auth"] == "Bearer test-key"
    assert [tool["function"]["name"] for tool in first["body"]["tools"]] == [
        "factory_build",
        "factory_command",
        "factory_status",
    ]
    tool_message = [m for m in second["body"]["messages"] if m["role"] == "tool"][0]
    assert "por la mitad" in tool_message["content"]


def test_build_turn_end_to_end(stack):
    model, factory = stack
    settings = Settings(language="es", briefing=False, open_build_in_browser=False)
    assistant, _client = build(
        settings,
        f"http://127.0.0.1:{model.server_address[1]}",
        f"http://127.0.0.1:{factory.server_address[1]}",
    )

    answer = asyncio.run(assistant.handle("armá una página de prueba"))

    assert answer == "Listo: armé dos archivos."
    assert factory.seen[-1]["texto"] == "una página de prueba"
    tool_message = [
        m for m in model.seen[-1]["body"]["messages"] if m["role"] == "tool"
    ][-1]
    payload = json.loads(tool_message["content"])
    assert payload["data"]["url"].endswith("/pagina-de-prueba/index.html")


def test_unreachable_factory_still_answers(stack):
    model, _factory = stack
    settings = Settings(language="es", briefing=False)
    assistant, _client = build(
        settings,
        f"http://127.0.0.1:{model.server_address[1]}",
        "http://127.0.0.1:1",
    )
    answer = asyncio.run(assistant.handle("¿cómo va la fábrica?"))
    # The tool answers with a sentence instead of raising, so the model still
    # has something to say back to the person.
    assert "no puedo alcanzar" in answer.lower()


def test_thinking_settings_travel_in_the_request_and_stay_unsaid(stack):
    model, factory = stack
    settings = Settings(
        language="es",
        briefing=False,
        open_build_in_browser=False,
        model_base_url=f"http://127.0.0.1:{model.server_address[1]}",
        model="nvidia/nemotron-3-ultra-550b-a55b",
        model_api_key="test-key",
        model_thinking=True,
        model_temperature=0.6,
        model_top_p=0.95,
        model_max_tokens=16384,
    )
    registry = ToolRegistry()
    client = FactoryClient(f"http://127.0.0.1:{factory.server_address[1]}", "k")
    register_tools(registry, client)
    assistant = Assistant(
        settings,
        model_from_settings(settings),
        registry,
        factory=client,
        speaker=Silence(),
    )

    answer = asyncio.run(assistant.handle("¿cómo va la fábrica?"))

    sent = model.seen[0]["body"]
    assert sent["model"] == "nvidia/nemotron-3-ultra-550b-a55b"
    assert sent["chat_template_kwargs"] == {"enable_thinking": True}
    assert sent["top_p"] == 0.95
    assert sent["temperature"] == 0.6
    assert sent["max_tokens"] == 16384
    # The hidden deliberation is never spoken.
    assert "PENSAMIENTO-INTERNO" not in answer
    assert answer == "El sprint de la landing va por la mitad."


def test_thinking_is_only_offered_where_it_is_understood():
    plain = OpenAICompatModel(
        "http://127.0.0.1:5100/v1", "", "llama-3-8b-instruct", thinking=True
    )
    nemotron = OpenAICompatModel(
        "https://integrate.api.nvidia.com/v1", "nvapi-x",
        "nvidia/nemotron-3-ultra-550b-a55b", thinking=True
    )
    through_proxy = OpenAICompatModel(
        "http://127.0.0.1:5100/v1", "", "nvidia/nemotron-3-ultra-550b-a55b",
        thinking=True,
    )

    assert "chat_template_kwargs" not in plain._payload([], [])
    assert nemotron._payload([], [])["chat_template_kwargs"] == {"enable_thinking": True}
    assert through_proxy._payload([], [])["chat_template_kwargs"] == {"enable_thinking": True}
