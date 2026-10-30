"""El cliente mínimo de Nemotron y el reparto del catálogo, sin salir a la red.

La demo y el verificador comparten este módulo para no depender del checkout
``profesor3/``, que no se distribuye. Lo que se fija aquí es el contrato:
``/models`` y ``/chat/completions`` contra un servidor de verdad en localhost.
"""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from demo import nemotron


class _Provider(BaseHTTPRequestHandler):
    """Un proveedor OpenAI-compatible de juguete, con la forma del real."""

    seen_auth = ""
    seen_payload: ClassVar[dict] = {}

    def do_GET(self):
        if self.path != "/models":
            self.send_response(404)
            self.end_headers()
            return
        body = json.dumps({"data": [
            {"id": "nvidia/nemotron-3-ultra-550b-a55b"},
        ]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/chat/completions":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length") or 0)
        type(self).seen_payload = json.loads(self.rfile.read(length))
        type(self).seen_auth = self.headers.get("Authorization", "")
        body = json.dumps({"choices": [{"message": {
            "content": "listo",
            "reasoning_content": "pensé antes de contestar",
        }}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


@pytest.fixture
def provider():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Provider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_the_catalogue_is_split_into_reasoning_and_fast():
    strategic, fast = nemotron.tier_models([
        "nvidia/nemotron-3-ultra-550b-a55b",
        "nvidia/nemotron-3-super-120b-a12b",
    ])

    assert strategic == "nvidia/nemotron-3-ultra-550b-a55b"
    assert fast == "nvidia/nemotron-3-super-120b-a12b"


def test_non_chat_models_are_never_chosen():
    strategic, fast = nemotron.tier_models([
        "nvidia/nemotron-3-ultra-embed",
        "nvidia/nemotron-3-super-whisper",
        "nvidia/nemotron-3-super-120b-a12b",
    ])

    assert strategic == ""
    assert fast == "nvidia/nemotron-3-super-120b-a12b"


def test_the_default_is_used_when_no_ultra_is_offered():
    strategic, _ = nemotron.tier_models(
        ["nvidia/nemotron-3-super-120b-a12b"],
        default="nvidia/nemotron-3-super-120b-a12b",
    )

    assert strategic == "nvidia/nemotron-3-super-120b-a12b"


@pytest.mark.parametrize("raw, expected", [
    ('"nvapi-abc"', "nvapi-abc"),
    ("'nvapi-abc'", "nvapi-abc"),
    ("Bearer nvapi-abc", "nvapi-abc"),
    ("  bearer nvapi-abc  ", "nvapi-abc"),
])
def test_a_pasted_key_is_cleaned(raw, expected):
    assert nemotron.clean_key(raw) == expected


def test_the_factory_dotenv_is_read(tmp_path, monkeypatch):
    (tmp_path / "backend").mkdir()
    (tmp_path / ".env").write_text(
        '# comentario\nNEBIUS_API_KEY="nvapi-abc"\nAGENT_MODEL=x\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("FABRICA_HOME", str(tmp_path))

    assert nemotron.read_env() == {
        "NEBIUS_API_KEY": "nvapi-abc",
        "AGENT_MODEL": "x",
    }


def test_the_client_lists_models_and_completes(provider):
    llm = nemotron.ChatClient({
        "base_url": provider,
        "model": "nvidia/nemotron-3-ultra-550b-a55b",
        "api_key": '"nvapi-abc"',
        "max_tokens": 64,
    })

    assert llm.models() == ["nvidia/nemotron-3-ultra-550b-a55b"]

    text, reasoning = llm.complete([{"role": "user", "content": "hola"}])

    assert (text, reasoning) == ("listo", "pensé antes de contestar")
    assert _Provider.seen_auth == "Bearer nvapi-abc"
    assert _Provider.seen_payload["model"] == (
        "nvidia/nemotron-3-ultra-550b-a55b")
    assert _Provider.seen_payload["max_tokens"] == 64


def test_an_http_error_becomes_a_model_error(provider):
    llm = nemotron.ChatClient({"base_url": f"{provider}/otra-puerta",
                               "api_key": "k"})

    with pytest.raises(nemotron.ModelError):
        llm.models()
