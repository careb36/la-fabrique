"""The proxy client: what it sends, how long it waits, and when it asks again."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import llm_proxy_client
from llm_proxy_client import DEFAULT_TIMEOUT_SECONDS, LLMProxyClient


class _Response:
    def __init__(self, status: int, body: dict):
        self.status_code = status
        self.ok = status < 400
        self._body = body
        self.text = str(body)

    def json(self):
        return self._body


def _posting(monkeypatch, answers):
    """Fake ``requests.post`` answering in order; records every call."""
    calls: list[dict] = []

    def post(url, json=None, headers=None, timeout=None):
        calls.append({"url": url, "json": json, "timeout": timeout})
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(llm_proxy_client.requests, "post", post)
    monkeypatch.setattr(llm_proxy_client.time, "sleep", lambda s: None)
    return calls


def test_the_default_wait_covers_the_proxy_s_upstream_budget():
    """A client that gives up before the proxy does discards an answer the
    provider has already billed; the default follows the proxy's budget."""
    assert DEFAULT_TIMEOUT_SECONDS == 120.0
    assert LLMProxyClient("http://p").timeout == DEFAULT_TIMEOUT_SECONDS


def test_max_tokens_travels_only_when_set(monkeypatch):
    ok = {"choices": [{"message": {"content": "hi"}}]}
    calls = _posting(
        monkeypatch, [_Response(200, ok), _Response(200, ok), _Response(200, ok)]
    )
    client = LLMProxyClient("http://p")
    client.max_retries = 0

    client.chat([{"role": "user", "content": "q"}], model="m")
    assert "max_tokens" not in calls[0]["json"]

    client.max_tokens = 600
    client.chat([{"role": "user", "content": "q"}], model="m")
    assert calls[1]["json"]["max_tokens"] == 600

    client.chat([{"role": "user", "content": "q"}], model="m", max_tokens=50)
    assert calls[2]["json"]["max_tokens"] == 50, (
        "an explicit cap wins over the client's"
    )
    assert calls[2]["timeout"] == DEFAULT_TIMEOUT_SECONDS


def test_an_error_the_proxy_answered_is_not_sent_again(monkeypatch):
    """The proxy already spent the upstream call and its fallbacks on it."""
    calls = _posting(
        monkeypatch,
        [_Response(502, {"error": "upstream_error", "detail": {"status": 500}})],
    )
    client = LLMProxyClient("http://p")
    assert client.max_retries == 2

    result = client.chat([{"role": "user", "content": "q"}], model="m")

    assert len(calls) == 1
    assert result["ok"] is False and result["status_code"] == 502


def test_a_request_that_never_reached_the_proxy_is_retried(monkeypatch):
    ok = {"choices": [{"message": {"content": "hi"}}]}
    calls = _posting(
        monkeypatch,
        [requests.ConnectionError("refused"), _Response(200, ok)],
    )
    client = LLMProxyClient("http://p")

    assert client.chat([{"role": "user", "content": "q"}], model="m") == ok
    assert len(calls) == 2


@pytest.mark.parametrize("status", [429, 500, 503])
def test_no_status_is_retried(monkeypatch, status):
    calls = _posting(monkeypatch, [_Response(status, {"error": "x"})])
    LLMProxyClient("http://p").chat([{"role": "user", "content": "q"}], model="m")
    assert len(calls) == 1
