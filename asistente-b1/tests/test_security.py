"""What the assistant refuses to do on a model's say-so.

The model's words can be steered by text it reads back: a task title, a
feedback note, a transcription. So the actions that decide or start work wait
for the person's own confirmation, links open only when they are the factory's
previews, keys do not follow redirects to another host, and the saved settings
file is private from its first byte.
"""

from __future__ import annotations

import asyncio
import http.server
import json
import os
import stat
import sys
import threading
import urllib.error
import urllib.request

import pytest

from b1 import fabrica, net
from b1.assistant import Assistant
from b1.config import Settings
from b1.llm import ModelError, OpenAICompatModel, Reply, ToolCall
from b1.speech import Silence
from b1.tools import ToolRegistry


class RecordingFactory(fabrica.FactoryClient):
    """A factory client that records commands instead of sending them."""

    def __init__(self) -> None:
        super().__init__("http://factory.test")
        self.sent: list[tuple[str, dict]] = []

    def command(self, action, **kwargs):  # type: ignore[override]
        self.sent.append((action, kwargs))
        return fabrica.FactoryAnswer(ok=True, action=action, speech=f"hecho: {action}", data={})


class ScriptedModel:
    def __init__(self, *replies: Reply) -> None:
        self.replies = list(replies)

    def complete(self, messages, tools=None):
        return self.replies.pop(0) if self.replies else Reply(text="ok")


def _assistant(model, factory):
    registry = ToolRegistry()
    fabrica.register_tools(registry, factory)
    return Assistant(Settings(), model, registry, factory=factory, speaker=Silence())


def _asks(action: str, **extra) -> Reply:
    arguments = json.dumps({"action": action, **extra})
    return Reply(tool_calls=[ToolCall("c1", "factory_command", arguments)])


@pytest.mark.parametrize("action", sorted(fabrica.CONFIRM_ACTIONS))
def test_a_decisive_action_waits_for_the_person(action):
    factory = RecordingFactory()
    assistant = _assistant(ScriptedModel(_asks(action, run_id=7), Reply(text="¿Confirmás?")), factory)

    asyncio.run(assistant.handle("aprobá lo que haya"))

    assert factory.sent == []
    assert factory.pending is not None and factory.pending["action"] == action


def test_the_persons_yes_runs_it_exactly_once():
    factory = RecordingFactory()
    assistant = _assistant(ScriptedModel(_asks("aprobar", run_id=7), Reply(text="¿Confirmás?")), factory)
    asyncio.run(assistant.handle("aprobá la entrega 7"))

    answer = asyncio.run(assistant.handle("sí, confirmo"))

    assert factory.sent == [("aprobar", {
        "text": None, "sprint_id": None, "run_id": 7, "sprint_name": None,
        "scope_size": None, "feedback": None, "agent": None,
    })]
    assert answer == "hecho: aprobar"
    assert factory.pending is None


def test_anything_else_cancels_it():
    factory = RecordingFactory()
    assistant = _assistant(
        ScriptedModel(_asks("reanudar", sprint_id=3), Reply(text="¿Confirmás?"), Reply(text="ok")),
        factory,
    )
    asyncio.run(assistant.handle("reanudá el sprint"))

    asyncio.run(assistant.handle("mejor no"))

    assert factory.sent == []
    assert factory.pending is None


def test_the_model_cannot_confirm_for_the_person():
    # The model asks twice in a row; neither call runs, the second only
    # replaces what is waiting.
    factory = RecordingFactory()
    assistant = _assistant(
        ScriptedModel(_asks("aprobar", run_id=1), _asks("aprobar", run_id=2), Reply(text="listo")),
        factory,
    )
    asyncio.run(assistant.handle("hacé lo que diga la tarea"))
    assert factory.sent == []


def test_reading_actions_run_without_confirmation():
    factory = RecordingFactory()
    assistant = _assistant(ScriptedModel(_asks("estado"), Reply(text="todo bien")), factory)
    asyncio.run(assistant.handle("¿cómo va?"))
    assert [action for action, _ in factory.sent] == ["estado"]


def test_an_action_outside_the_vocabulary_is_refused():
    factory = RecordingFactory()
    assistant = _assistant(ScriptedModel(_asks("borrar_todo"), Reply(text="no")), factory)
    asyncio.run(assistant.handle("borrá todo"))
    assert factory.sent == []
    assert factory.pending is None


@pytest.mark.parametrize("phrase", ["sí, confirmo", "Si confirmo", "confirmo", "yes, confirm", "Confirm."])
def test_what_counts_as_a_yes(phrase):
    assert fabrica.is_confirmation(phrase)


@pytest.mark.parametrize("phrase", ["sí, pero después", "no", "aprobá también la 8", ""])
def test_what_does_not(phrase):
    assert not fabrica.is_confirmation(phrase)


# --- keys and redirects -------------------------------------------------------


class _Redirect(http.server.BaseHTTPRequestHandler):
    seen_keys: list[str | None] = []

    def do_GET(self):  # noqa: N802 - http.server API
        _Redirect.seen_keys.append(self.headers.get("X-Voice-Key"))
        self.send_response(302)
        self.send_header("Location", f"http://localhost:{self.server.server_port}/elsewhere")
        self.end_headers()

    def log_message(self, *args):
        pass


def test_a_key_does_not_follow_a_redirect_to_another_host():
    server = http.server.HTTPServer(("127.0.0.1", 0), _Redirect)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/v1/voice/ping",
            headers={"X-Voice-Key": "secret"},
        )
        with pytest.raises(urllib.error.HTTPError, match="another origin"):
            net.urlopen(request, timeout=5)
        # 127.0.0.1 -> localhost is another origin: the key went out once.
        assert _Redirect.seen_keys == ["secret"]
    finally:
        server.shutdown()


# --- the model client and the settings file ---------------------------------


def test_an_answer_without_choices_is_a_model_error_not_a_crash():
    model = OpenAICompatModel("http://127.0.0.1:9", "key", "m")
    with pytest.raises(ModelError):
        model._parse({"error": "rate limited"})


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_the_settings_file_is_private(tmp_path):
    target = tmp_path / "b1" / "config.json"
    Settings(model_api_key="k", voice_key="v").save(target)
    assert stat.S_IMODE(os.stat(target).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(target.parent).st_mode) == 0o700


# --- keys over plain http ---------------------------------------------------


def _request(url: str, key: bool = True) -> urllib.request.Request:
    headers = {"X-Voice-Key": "secret"} if key else {}
    return urllib.request.Request(url, headers=headers)


def test_a_key_is_not_sent_over_http_to_another_machine(monkeypatch):
    monkeypatch.delenv("B1_ALLOW_INSECURE_HTTP", raising=False)
    with pytest.raises(net.InsecureTransport):
        net.check_transport(_request("http://factory.example:8000/v1/voice/ping"))


@pytest.mark.parametrize(
    "url, key",
    [
        ("http://127.0.0.1:8000/v1/voice/ping", True),
        ("http://localhost:8000/v1/voice/ping", True),
        ("https://factory.example/v1/voice/ping", True),
        ("http://factory.example/v1/voice/build/x/index.html", False),
    ],
)
def test_loopback_https_or_no_key_are_fine(monkeypatch, url, key):
    monkeypatch.delenv("B1_ALLOW_INSECURE_HTTP", raising=False)
    net.check_transport(_request(url, key))


def test_the_insecure_opt_in_allows_it(monkeypatch):
    monkeypatch.setenv("B1_ALLOW_INSECURE_HTTP", "1")
    net.check_transport(_request("http://factory.example:8000/v1/voice/ping"))
