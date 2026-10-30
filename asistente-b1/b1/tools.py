"""Tool declarations and dispatch.

A tool is a JSON-schema declaration plus a Python callable. The registry owns the
translation to the model's ``tools`` format, argument coercion (models send
numbers as strings more often than anyone expects) and error containment: a tool
that raises answers the model with a sentence, it never kills the turn.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from dataclasses import dataclass
from typing import Any, Callable, Iterable

DEFAULT_TOOL_TIMEOUT = 60.0
MAX_RESULT_CHARS = 4000


class ToolError(Exception):
    """Raised when a tool name is unknown or its arguments are unusable."""


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., Any]
    timeout: float = DEFAULT_TOOL_TIMEOUT

    def declaration(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def object_schema(properties: dict[str, Any], required: Iterable[str] = ()) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


def _coerce(value: Any, schema: dict[str, Any]) -> Any:
    """Best-effort cast of one argument to the type its schema declares."""
    kind = schema.get("type")
    if value is None:
        return None
    if kind == "integer" or kind == "number":
        if isinstance(value, str):
            text = value.strip()
            try:
                return int(text) if kind == "integer" else float(text)
            except ValueError:
                raise ToolError(f"esperaba un número y recibí {value!r}") from None
        return value
    if kind == "boolean":
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "si", "sí", "yes", "on"}
        return bool(value)
    if kind == "string":
        return value if isinstance(value, str) else str(value)
    return value


class ToolRegistry:
    """Holds the tools the assistant may call and runs them safely."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def add(self, tool: Tool) -> Tool:
        if not tool.name or not tool.name.replace("_", "").isalnum():
            raise ToolError(f"nombre de herramienta inválido: {tool.name!r}")
        self._tools[tool.name] = tool
        return tool

    def register(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        handler: Callable[..., Any],
        *,
        timeout: float = DEFAULT_TOOL_TIMEOUT,
    ) -> Tool:
        return self.add(Tool(name, description, parameters, handler, timeout))

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError:
            raise ToolError(f"no existe la herramienta {name!r}") from None

    def names(self) -> list[str]:
        return sorted(self._tools)

    def declarations(self) -> list[dict[str, Any]]:
        return [tool.declaration() for _, tool in sorted(self._tools.items())]

    async def dispatch(self, name: str, arguments: dict[str, Any] | str | None) -> str:
        """Run one call and answer with text, whatever happens inside."""
        try:
            tool = self.get(name)
            args = self._arguments(arguments, tool)
            result = await self._invoke(tool, args)
        except ToolError as exc:
            return f"ERROR: {exc}"
        except asyncio.TimeoutError:
            return f"ERROR: la herramienta {name} tardó demasiado y la cancelé."
        except Exception as exc:  # noqa: BLE001 - the model reads the message.
            return f"ERROR: {type(exc).__name__}: {exc}"
        return self._render(result)

    @staticmethod
    def _arguments(arguments: dict[str, Any] | str | None, tool: Tool) -> dict[str, Any]:
        if arguments in (None, ""):
            raw: dict[str, Any] = {}
        elif isinstance(arguments, str):
            try:
                raw = json.loads(arguments)
            except ValueError:
                raise ToolError(f"los argumentos de {tool.name} no son JSON") from None
        else:
            raw = dict(arguments)
        if not isinstance(raw, dict):
            raise ToolError(f"los argumentos de {tool.name} no son un objeto")

        properties = tool.parameters.get("properties", {})
        unknown = set(raw) - set(properties)
        for key in unknown:
            raw.pop(key)
        for key, schema in properties.items():
            if key in raw and raw[key] not in (None, ""):
                raw[key] = _coerce(raw[key], schema)
            elif key in tool.parameters.get("required", []):
                raise ToolError(f"falta el argumento {key} de {tool.name}")
            elif key in raw:
                raw.pop(key)  # Empty optional strings are how models say "null".
        return raw

    @staticmethod
    async def _invoke(tool: Tool, args: dict[str, Any]) -> Any:
        if inspect.iscoroutinefunction(tool.handler):
            call = tool.handler(**args)
            return await asyncio.wait_for(call, timeout=tool.timeout)
        return await asyncio.wait_for(
            asyncio.to_thread(tool.handler, **args), timeout=tool.timeout
        )

    @staticmethod
    def _render(result: Any) -> str:
        if result is None:
            return "LISTO"
        if isinstance(result, str):
            text = result
        else:
            try:
                text = json.dumps(result, ensure_ascii=False)
            except (TypeError, ValueError):
                text = str(result)
        return text[:MAX_RESULT_CHARS]
