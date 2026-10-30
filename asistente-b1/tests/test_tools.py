"""Tool dispatch has to survive whatever a model sends."""

import asyncio
import time

import pytest

from b1.tools import ToolRegistry, object_schema


def build() -> ToolRegistry:
    registry = ToolRegistry()

    def echo(text: str, times: int = 1) -> str:
        return text * times

    def boom() -> str:
        raise ValueError("no hay red")

    def slow() -> str:
        time.sleep(0.5)
        return "tarde"

    registry.register(
        "echo",
        "devuelve el texto",
        object_schema(
            {"text": {"type": "string"}, "times": {"type": "integer"}}, required=["text"]
        ),
        echo,
    )
    registry.register("boom", "falla siempre", object_schema({}), boom)
    registry.register("slow", "tarda", object_schema({}), slow, timeout=0.05)
    return registry


def run(registry, name, args):
    return asyncio.run(registry.dispatch(name, args))


def test_declaration_matches_openai_shape():
    registry = build()
    declaration = registry.declarations()[0]
    assert declaration["type"] == "function"
    assert declaration["function"]["name"] == "boom"
    assert "parameters" in declaration["function"]


def test_coerces_numbers_and_bools_from_strings():
    registry = build()
    assert run(registry, "echo", {"text": "a", "times": "3"}) == "aaa"
    assert run(registry, "echo", {"text": "a", "times": 2}) == "aa"


def test_accepts_arguments_as_json_string():
    registry = build()
    assert run(registry, "echo", '{"text": "x", "times": 2}') == "xx"


def test_drops_unknown_arguments():
    registry = build()
    assert run(registry, "echo", {"text": "z", "colour": "red"}) == "z"


def test_missing_required_argument_is_reported_not_raised():
    registry = build()
    assert run(registry, "echo", {}).startswith("ERROR:")


def test_unknown_tool_is_reported():
    registry = build()
    assert "no existe" in run(registry, "nope", {})


def test_broken_json_arguments_are_reported():
    registry = build()
    assert run(registry, "echo", "{not json").startswith("ERROR:")


def test_tool_exception_becomes_text():
    registry = build()
    answer = run(registry, "boom", {})
    assert answer.startswith("ERROR: ValueError")


def test_timeout_is_contained():
    registry = build()
    answer = run(registry, "slow", {})
    assert "tardó demasiado" in answer


def test_empty_string_optional_is_dropped():
    registry = build()
    assert run(registry, "echo", {"text": "q", "times": ""}) == "q"


def test_result_is_truncated():
    registry = ToolRegistry()
    registry.register(
        "big",
        "grande",
        object_schema({}),
        lambda: "x" * 10_000,
    )
    assert len(run(registry, "big", {})) == 4000


def test_async_handlers_are_awaited():
    registry = ToolRegistry()

    async def later(text: str) -> str:
        await asyncio.sleep(0)
        return text.upper()

    registry.register(
        "later", "mayúsculas", object_schema({"text": {"type": "string"}}, ["text"]), later
    )
    assert run(registry, "later", {"text": "hola"}) == "HOLA"


@pytest.mark.parametrize("name", ["factory_status", "factory_command", "factory_build"])
def test_factory_tool_names_are_stable(name):
    from b1.fabrica import FactoryClient, register_tools

    registry = ToolRegistry()
    register_tools(registry, FactoryClient("http://127.0.0.1:9"))
    assert name in registry.names()
