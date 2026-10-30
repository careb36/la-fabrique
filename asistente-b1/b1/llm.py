"""Model access over plain HTTP, no SDK.

The assistant speaks to any endpoint that implements OpenAI's
``chat/completions`` with function calling: Token Factory / Nebius (Nemotron),
OpenAI itself, vLLM, Ollama, LM Studio. Keeping the transport in the standard
library means the install has no pinned client version to break, and the tests
can point the same code at a localhost server.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from .i18n import normalize, t
from dataclasses import dataclass, field
from typing import Any, Protocol


class ModelError(Exception):
    """The endpoint answered something the assistant cannot use."""


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str = "{}"


@dataclass
class Reply:
    """One assistant turn: either words, or tool calls, or both."""

    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    # Nemotron's hidden deliberation, when the template enables it.  It is
    # never spoken and never shown as an answer; it only feeds the log.
    reasoning: str = ""

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


class ChatModel(Protocol):
    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Reply:
        ...


class OpenAICompatModel:
    """A ``/chat/completions`` client that returns tool calls instead of text."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        *,
        timeout: float = 180.0,
        temperature: float = 0.6,
        max_tokens: int = 4096,
        top_p: float | None = 0.95,
        thinking: bool = False,
        language: str = "es",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.top_p = top_p
        self.thinking = thinking
        self.language = normalize(language)

    def speaks_nemotron(self) -> bool:
        """True when the endpoint serves Nemotron, the only model that reads
        ``chat_template_kwargs``."""
        host = self.base_url.split("//", 1)[-1].split("/", 1)[0].lower()
        return (
            "nemotron" in self.model.lower()
            or host.endswith("integrate.api.nvidia.com")
            or host.endswith("api.tokenfactory.nebius.com")
        )

    # -- public API ---------------------------------------------------------
    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Reply:
        body = self._request(self._payload(messages, tools))
        return self._parse(body)

    def ping(self) -> tuple[bool, str]:
        """Cheap credential check used by the settings screen."""
        try:
            self.complete([{"role": "user", "content": "ping"}], [])
        except ModelError as exc:
            return False, str(exc)
        return True, t(self.language, "model.answers", model=self.model)

    # -- internals ----------------------------------------------------------
    def _payload(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": False,
        }
        if self.top_p is not None:
            payload["top_p"] = self.top_p
        if self.thinking and self.speaks_nemotron():
            # Nemotron reads the switch from the chat template; a strict server
            # that does not would reject the unknown field, so it only goes to
            # the endpoints known to serve that family.
            payload["chat_template_kwargs"] = {"enable_thinking": True}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        return payload

    def _request(self, payload: dict) -> dict:
        url = f"{self.base_url}/chat/completions"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            # A local proxy or Ollama rejects an empty bearer; send none instead.
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(url, data=data, method="POST", headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            detail = _short_body(exc)
            raise ModelError(
                t(self.language, "model.http", code=exc.code, url=url, detail=detail)
            ) from None
        except urllib.error.URLError as exc:
            raise ModelError(
                t(self.language, "model.unreachable", url=url, reason=exc.reason)
            ) from None
        except TimeoutError:
            raise ModelError(
                t(self.language, "model.timeout", url=url, seconds=self.timeout)
            ) from None
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError:
            raise ModelError(t(self.language, "model.not_json")) from None

    @staticmethod
    def _parse(body: dict) -> Reply:
        try:
            message = body["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            raise ModelError(
                t(self.language, "model.no_choices", body=str(body)[:200])
            ) from None

        text = (message.get("content") or "").strip()
        reasoning = (message.get("reasoning_content") or "").strip()
        calls: list[ToolCall] = []
        for index, call in enumerate(message.get("tool_calls") or []):
            function = call.get("function") or {}
            name = (function.get("name") or "").strip()
            if not name:
                continue
            calls.append(
                ToolCall(
                    id=call.get("id") or f"call_{index}",
                    name=name,
                    arguments=function.get("arguments") or "{}",
                )
            )
        return Reply(text=text, tool_calls=calls, reasoning=reasoning)


def model_from_settings(settings) -> OpenAICompatModel:
    """The one place that turns saved settings into a model client."""
    return OpenAICompatModel(
        settings.model_url_clean(),
        settings.model_api_key,
        settings.model,
        timeout=float(settings.model_timeout),
        temperature=float(settings.model_temperature),
        max_tokens=int(settings.model_max_tokens),
        top_p=float(settings.model_top_p),
        thinking=bool(settings.model_thinking),
        language=getattr(settings, "language", "es"),
    )


def _short_body(error: urllib.error.HTTPError) -> str:
    try:
        return error.read().decode("utf-8", "replace")[:300]
    except Exception:  # noqa: BLE001 - the status code is already the message.
        return error.reason or "?"
