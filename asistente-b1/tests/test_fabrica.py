"""The factory client, exercised against a real HTTP server on localhost.

No mocks: a throwaway ``http.server`` speaks the same contract the backend does,
so the test covers URL building, headers, JSON bodies and error mapping.
"""

from __future__ import annotations

import ast
import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from b1 import fabrica
from b1.tools import ToolRegistry

VOICE_KEY = "clave-de-prueba"


class _Handler(BaseHTTPRequestHandler):
    server_version = "FakeFactory/1.0"

    def log_message(self, *args):  # silence the test output
        return

    # -- helpers ------------------------------------------------------------
    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8") or "{}")

    def _send(self, status: int, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _record(self, payload=None) -> None:
        self.server.requests.append(
            {
                "method": self.command,
                "path": urlparse(self.path).path,
                "query": parse_qs(urlparse(self.path).query),
                "key": self.headers.get("X-Voice-Key"),
                "payload": payload,
            }
        )

    def _authorised(self) -> bool:
        if self.server.mode == "locked":
            return False
        if self.server.mode == "unconfigured":
            return False
        return self.headers.get("X-Voice-Key") == VOICE_KEY

    # -- routes -------------------------------------------------------------
    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlparse(self.path).path
        if self.server.mode == "unconfigured":
            self._record()
            self._send(503, {"detail": "Voice control is not configured"})
            return
        if path == "/v1/voice/ping":
            self._record()
            if not self._authorised():
                self._send(401, {"detail": "Invalid or missing X-Voice-Key"})
                return
            self._send(200, {"ok": True, "speech": "Conexión con la fábrica correcta."})
            return
        if path == "/v1/voice/status":
            self._record()
            if not self._authorised():
                self._send(401, {"detail": "Invalid or missing X-Voice-Key"})
                return
            self._send(
                200,
                {
                    "ok": True,
                    "action": "estado",
                    "speech": "Hay un sprint en curso con tres tareas hechas.",
                    "data": {"sprint_name": "Landing", "progress": 0.42, "pending": 2},
                },
            )
            return
        self._send(404, {"detail": "not found"})

    def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlparse(self.path).path
        payload = self._body()
        self._record(payload)
        if self.server.mode == "unconfigured":
            self._send(503, {"detail": "Voice control is not configured"})
            return
        if not self._authorised():
            self._send(401, {"detail": "Invalid or missing X-Voice-Key"})
            return
        if path == "/v1/voice/command":
            self._send(
                200,
                {
                    "ok": payload.get("action") != "pausar",
                    "action": payload.get("action"),
                    "speech": f"Recibí {payload.get('action')}.",
                    "data": {"echo": payload},
                },
            )
            return
        if path == "/v1/voice/build":
            self._send(
                200,
                {
                    "ok": True,
                    "action": "crear_proyecto",
                    "speech": "Listo: armé el proyecto con 2 archivos.",
                    "data": {"slug": "calculadora-propinas", "files": ["index.html", "style.css"]},
                },
            )
            return
        self._send(404, {"detail": "not found"})


@pytest.fixture()
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    httpd.requests = []
    httpd.mode = "ok"
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd
    httpd.shutdown()
    httpd.server_close()


def client_for(httpd, key: str = VOICE_KEY, language: str = "es") -> fabrica.FactoryClient:
    host, port = httpd.server_address[:2]
    return fabrica.FactoryClient(f"http://{host}:{port}", key, language=language)


def test_ping_ok(server):
    ok, sentence = client_for(server).ping()
    assert ok is True
    assert "Conexión" in sentence


def test_ping_without_key_is_reported(server):
    ok, sentence = client_for(server, key="").ping()
    assert ok is False
    assert "clave de voz" in sentence


def test_unconfigured_factory_is_reported(server):
    server.mode = "unconfigured"
    with pytest.raises(fabrica.FactoryError) as excinfo:
        client_for(server).status()
    assert "VOICE_API_KEY" in str(excinfo.value)


def test_status_sends_query_and_key(server):
    answer = client_for(server).status(company_id=4)
    assert answer.ok and answer.speech.startswith("Hay un sprint")
    assert answer.data["pending"] == 2

    request = server.requests[-1]
    assert request["query"]["company_id"] == ["4"]
    assert request["query"]["language"] == ["es"]
    assert request["key"] == VOICE_KEY


def test_command_sends_only_the_fields_it_was_given(server):
    answer = client_for(server).command("planear", text="una landing de café")
    assert answer.ok is True
    payload = server.requests[-1]["payload"]
    assert payload["action"] == "planear"
    assert payload["text"] == "una landing de café"
    assert "sprint_id" not in payload
    assert "feedback" not in payload


def test_failed_command_is_not_ok(server):
    answer = client_for(server).command("pausar")
    assert answer.ok is False
    assert answer.action == "pausar"


def test_build_adds_preview_url(server):
    answer = client_for(server).build("una calculadora de propinas")
    assert answer.ok is True
    assert answer.data["files"] == ["index.html", "style.css"]
    assert answer.data["url"].endswith("/v1/voice/build/calculadora-propinas/index.html")
    assert server.requests[-1]["payload"]["texto"] == "una calculadora de propinas"


def test_english_language_is_forwarded(server):
    client_for(server, language="en").status()
    assert server.requests[-1]["query"]["language"] == ["en"]


def test_unreachable_factory_says_so():
    client = fabrica.FactoryClient("http://127.0.0.1:1", "")
    with pytest.raises(fabrica.FactoryError) as excinfo:
        client.status()
    assert "no puedo alcanzar" in str(excinfo.value)


def test_tools_talk_to_the_factory(server):
    registry = ToolRegistry()
    fabrica.register_tools(registry, client_for(server))

    status = asyncio.run(registry.dispatch("factory_status", {}))
    assert json.loads(status)["ok"] is True

    built = asyncio.run(registry.dispatch("factory_build", {"texto": "un formulario"}))
    body = json.loads(built)
    assert body["data"]["url"].startswith("http://127.0.0.1")


def test_tools_turn_transport_errors_into_sentences():
    registry = ToolRegistry()
    fabrica.register_tools(registry, fabrica.FactoryClient("http://127.0.0.1:1", ""))
    body = json.loads(asyncio.run(registry.dispatch("factory_status", {})))
    assert body["ok"] is False
    assert "no puedo alcanzar" in body["speech"]


@pytest.mark.parametrize(
    ("language", "opening"),
    [("es", "la fábrica"), ("en", "the factory")],
)
def test_guide_is_complete_in_both_languages(language, opening):
    text = fabrica.guide_text(language)
    summary = fabrica.spoken_summary(language)
    title = fabrica.guide_title(language)
    assert len(text) > 300
    assert text.lower().startswith(opening)
    assert title
    assert 80 < len(summary) < 700


def test_guide_mentions_the_paused_sprint_rule():
    assert "pausa" in fabrica.guide_text("es")
    assert "paused" in fabrica.guide_text("en")


def test_unknown_language_falls_back_to_spanish():
    assert fabrica.guide_text("fr") == fabrica.guide_text("es")


def test_assignment_carries_the_agent_name(server):
    answer = client_for(server).command(
        "asignar", text="revisá el login", agent="QA"
    )
    assert answer.ok is True
    payload = server.requests[-1]["payload"]
    assert payload["agent"] == "QA"
    assert payload["text"] == "revisá el login"


def test_every_action_the_factory_accepts_is_offered_to_the_model():
    """The tool schema must not hide a verb the factory implements."""
    backend = Path(__file__).resolve().parents[2] / "la-fabrique" / "backend"
    source = backend / "app" / "services" / "voice_control.py"
    if not source.is_file():
        pytest.skip("no está el árbol de la fábrica")

    namespace: dict = {}
    tree = ast.parse(source.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "VOICE_ACTIONS":
            namespace["VOICE_ACTIONS"] = ast.literal_eval(node.value)
    accepted = set(namespace["VOICE_ACTIONS"].values())

    registry = fabrica.ToolRegistry()
    fabrica.register_tools(registry, fabrica.FactoryClient("http://127.0.0.1:9"))
    schema = next(
        d for d in registry.declarations() if d["function"]["name"] == "factory_command"
    )
    offered = set(schema["function"]["parameters"]["properties"]["action"]["enum"])

    assert accepted <= offered, f"la fábrica acepta verbos que no se ofrecen: {accepted - offered}"
