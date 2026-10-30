"""
Load ``llm-proxy/app.py`` without touching the network or a database.

The module validates API keys and refreshes the provider catalogues at import
time, so the keys are blanked before import (every refresh then returns early)
and OpenTelemetry export is disabled.  Tests set keys and catalogues on the
loaded module and replace ``requests.post`` with a fake.
"""

import importlib.util
import os
import sys
from pathlib import Path

import pytest

_APP_PATH = Path(__file__).resolve().parents[1] / "app.py"
# app.py imports its sibling modules (usage.py) by name, as it does in /app.
sys.path.insert(0, str(_APP_PATH.parent))

for _key in ("GEMINI_API_KEY", "DEEPSEEK_API_KEY", "QWEN_API_KEY", "NEBIUS_API_KEY",
             "NVIDIA_API_KEY"):
    os.environ[_key] = ""
os.environ["OTEL_SDK_DISABLED"] = "true"
os.environ.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
os.environ.pop("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", None)
os.environ.pop("LLM_UPSTREAM_TIMEOUT_SECONDS", None)


def _load_proxy():
    spec = importlib.util.spec_from_file_location("llm_proxy_app", _APP_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["llm_proxy_app"] = module
    spec.loader.exec_module(module)
    return module


proxy_module = _load_proxy()


class FakeResponse:
    def __init__(self, status_code: int, body=None, text: str | None = None):
        self.status_code = status_code
        self._body = body
        self.text = text if text is not None else ("" if body is None else str(body))

    def json(self):
        if self._body is None:
            raise ValueError("no JSON body")
        return self._body


class FakeUpstream:
    """Stands in for ``requests.post``; answers by provider host."""

    def __init__(self):
        self.calls: list[dict] = []
        self.responses: dict[str, FakeResponse] = {}

    def set(self, provider: str, response: FakeResponse) -> None:
        self.responses[provider] = response

    @staticmethod
    def provider_of(url: str) -> str:
        if "deepseek" in url:
            return "deepseek"
        if "qwen" in url:
            return "qwen"
        if "integrate.api.nvidia" in url:
            return "nvidia"
        if "tokenfactory" in url:
            return "nebius"
        if "generativelanguage" in url:
            return "gemini"
        raise AssertionError(f"unexpected upstream URL {url}")

    def __call__(self, url, headers=None, json=None, timeout=None):
        provider = self.provider_of(url)
        self.calls.append({"provider": provider, "url": url, "json": json, "timeout": timeout})
        return self.responses[provider]

    def providers_called(self) -> list[str]:
        return [call["provider"] for call in self.calls]


def openai_ok(content: str = "hello", model: str | None = None) -> FakeResponse:
    body = {
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": {"total_tokens": 12},
    }
    if model:
        body["model"] = model
    return FakeResponse(200, body)


def gemini_ok(content: str = "hello") -> FakeResponse:
    return FakeResponse(200, {"candidates": [{"content": {"parts": [{"text": content}]}}]})


@pytest.fixture()
def proxy(monkeypatch):
    """The proxy module with all three providers configured and catalogued."""
    mod = proxy_module
    monkeypatch.setattr(mod, "GEMINI_API_KEY", "g-key")
    monkeypatch.setattr(mod, "DEEPSEEK_API_KEY", "d-key")
    monkeypatch.setattr(mod, "QWEN_API_KEY", "q-key")
    monkeypatch.setattr(mod, "_available_models", {"gemini-3.8-flash", "gemini-3.1-pro-preview"})
    monkeypatch.setattr(mod, "_available_deepseek_models", {"deepseek-v4-pro", "deepseek-flash"})
    monkeypatch.setattr(mod, "_available_qwen_models", {"qwen3.7-plus", "qwen3.6-flash"})
    monkeypatch.setattr(mod, "track_usage_in_db", lambda bu_id, tokens: None)
    # A catalogue that is empty must stay empty: no refresh over the network.
    for name in ("_refresh_gemini_models", "_refresh_deepseek_models", "_refresh_qwen_models",
                 "_refresh_nebius_models", "_refresh_nvidia_models"):
        monkeypatch.setattr(mod, name, lambda: None)
    return mod


@pytest.fixture()
def nebius(proxy, monkeypatch):
    """The proxy with the Nebius Token Factory key and catalogue configured."""
    monkeypatch.setattr(proxy, "NEBIUS_API_KEY", "n-key")
    monkeypatch.setattr(proxy, "_available_nebius_models",
                        {"nvidia/Llama-3.1-Nemotron-70B-Instruct", "nvidia/Nemotron-Nano-9B"})
    monkeypatch.setattr(proxy, "_refresh_nebius_models", lambda: None)
    return proxy


@pytest.fixture()
def nvidia(proxy, monkeypatch):
    """The proxy with NVIDIA's own gateway configured instead of Nebius."""
    monkeypatch.setattr(proxy, "NVIDIA_API_KEY", "nvapi-test")
    monkeypatch.setattr(proxy, "_available_nvidia_models", {
        "nvidia/nemotron-3-ultra-550b-a55b",
        "nvidia/nemotron-3-nano-30b-a3b",
    })
    return proxy


@pytest.fixture()
def both_gateways(nvidia, monkeypatch):
    """Both keys answer for ``nvidia/`` ids: the NVIDIA gateway must win."""
    monkeypatch.setattr(nvidia, "NEBIUS_API_KEY", "n-key")
    monkeypatch.setattr(nvidia, "_available_nebius_models", {
        "nvidia/nemotron-3-ultra-550b-a55b",
        "meta-llama/Llama-3.3-70B-Instruct",
    })
    return nvidia


@pytest.fixture()
def upstream(proxy, monkeypatch):
    fake = FakeUpstream()
    monkeypatch.setattr(proxy.requests, "post", fake)
    return fake


@pytest.fixture()
def client(proxy):
    return proxy.app.test_client()
