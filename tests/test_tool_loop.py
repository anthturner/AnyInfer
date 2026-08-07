"""The tool loop (§C9): schema derivation, sequential dispatch, error handling, bounds."""

from __future__ import annotations

import json

import pytest

import anyinfer as ai
from anyinfer._client.tools import Tool, ToolRegistry, tool
from anyinfer.errors import ToolLoopError
from anyinfer.testing.fakes import FakeOpenAIServer, FakeResponse
from support import make_client, make_sync_client

# ---- schema derivation ---------------------------------------------------------------


def test_spec_is_derived_from_the_signature() -> None:
    @tool
    def read_file(path: str, encoding: str = "utf-8") -> str:
        """Read a project file."""
        return f"{path}:{encoding}"

    assert isinstance(read_file, Tool)
    spec = read_file.spec
    assert spec.name == "read_file"
    assert spec.description == "Read a project file."
    assert spec.parameters["properties"]["path"] == {"type": "string"}
    assert spec.parameters["required"] == ["path"], "defaulted params are optional"


def test_supported_scalar_types() -> None:
    @tool
    def every_type(a: str, b: int, c: float, d: bool, e: list, f: dict) -> None:
        """Take one of each."""

    properties = every_type.spec.parameters["properties"]
    assert properties["a"]["type"] == "string"
    assert properties["b"]["type"] == "integer"
    assert properties["c"]["type"] == "number"
    assert properties["d"]["type"] == "boolean"
    assert properties["e"]["type"] == "array"
    assert properties["f"]["type"] == "object"


def test_typed_containers() -> None:
    @tool
    def search(terms: list[str], filters: dict[str, str]) -> None:
        """Search with terms."""

    properties = search.spec.parameters["properties"]
    assert properties["terms"] == {"type": "array", "items": {"type": "string"}}
    assert properties["filters"]["type"] == "object"


def test_optional_reduces_to_its_inner_type() -> None:
    @tool
    def maybe(value: str | None = None) -> None:
        """Take an optional value."""

    assert maybe.spec.parameters["properties"]["value"] == {"type": "string"}


def test_unsupported_type_is_rejected_at_declaration() -> None:
    """Better to fail when the tool is declared than to misdescribe it to the model."""

    class Custom:
        pass

    with pytest.raises(ToolLoopError) as excinfo:
        @tool
        def bad(value: Custom) -> None:
            """Take something unsupported."""

    assert excinfo.value.hint is not None
    assert "str, int, float, bool, list, and dict" in excinfo.value.hint


def test_name_and_description_can_be_overridden() -> None:
    @tool(name="fetch", description="Fetch a URL.")
    def original(url: str) -> str:
        """Original docstring."""
        return url

    assert original.spec.name == "fetch"
    assert original.spec.description == "Fetch a URL."


def test_plain_callables_are_accepted() -> None:
    def plain(value: str) -> str:
        """A plain function."""
        return value

    registry = ToolRegistry([plain])
    assert registry.specs[0].name == "plain"


# ---- dispatch ------------------------------------------------------------------------


async def test_dispatch_invokes_the_function() -> None:
    @tool
    def add(a: int, b: int) -> int:
        """Add two numbers."""
        return a + b

    registry = ToolRegistry([add])
    result = await registry.dispatch(
        ai.ToolCall(id="c1", name="add", arguments={"a": 2, "b": 3})
    )

    assert result.call_id == "c1"
    assert result.content == "5"
    assert result.is_error is False


async def test_dispatch_awaits_async_tools() -> None:
    """An ``async def`` tool works identically: its coroutine is awaited, not stringified."""

    @tool
    async def fetch(key: str) -> str:
        """Fetch a value."""
        return f"value-for-{key}"

    registry = ToolRegistry([fetch])
    result = await registry.dispatch(ai.ToolCall(id="c", name="fetch", arguments={"key": "a"}))

    assert result.content == "value-for-a"
    assert result.is_error is False


async def test_a_raising_async_tool_becomes_an_error_result() -> None:
    @tool
    async def explode(value: str) -> str:
        """Always fail."""
        raise ValueError("async boom")

    registry = ToolRegistry([explode])
    result = await registry.dispatch(ai.ToolCall(id="c", name="explode", arguments={"value": "x"}))

    assert result.is_error is True
    assert "ValueError: async boom" in result.content


async def test_non_string_results_are_serialized() -> None:
    @tool
    def lookup(key: str) -> dict:
        """Look something up."""
        return {"key": key, "found": True}

    registry = ToolRegistry([lookup])
    result = await registry.dispatch(ai.ToolCall(id="c", name="lookup", arguments={"key": "a"}))
    assert json.loads(result.content) == {"key": "a", "found": True}


async def test_a_raising_tool_becomes_an_error_result() -> None:
    """A failing tool is a normal conversational event, not a caller-facing exception."""

    @tool
    def explode(value: str) -> str:
        """Always fail."""
        raise ValueError("that did not work")

    registry = ToolRegistry([explode])
    result = await registry.dispatch(
        ai.ToolCall(id="c", name="explode", arguments={"value": "x"})
    )

    assert result.is_error is True
    assert "ValueError: that did not work" in result.content


async def test_an_unknown_tool_is_a_loop_failure() -> None:
    """The model cannot recover from this by retrying, so it raises."""

    @tool
    def known(value: str) -> str:
        """A known tool."""
        return value

    registry = ToolRegistry([known])
    with pytest.raises(ToolLoopError) as excinfo:
        await registry.dispatch(ai.ToolCall(id="c", name="unknown", arguments={}))

    assert excinfo.value.hint is not None
    assert "known" in excinfo.value.hint


# ---- the loop ------------------------------------------------------------------------


@tool
def lookup(key: str) -> str:
    """Look up a value by key."""
    return f"value-for-{key}"


async def test_loop_dispatches_then_returns_the_final_answer() -> None:
    server = FakeOpenAIServer(
        [
            FakeResponse(
                text="",
                tool_calls=(("call_1", "lookup", '{"key": "alpha"}'),),
                finish_reason="tool_calls",
            ),
            FakeResponse(text="The value is value-for-alpha."),
        ]
    )
    async with make_client(server) as client:
        result = await client.run_tools(
            "look up alpha", tools=[lookup], target="openai-compat:m"
        )

    assert result.text == "The value is value-for-alpha."
    assert server.call_count == 2

    # The second request must echo the assistant's call and then the tool result.
    messages = server.requests[1]["messages"]
    assert messages[-2]["role"] == "assistant"
    assert messages[-2]["tool_calls"][0]["function"]["name"] == "lookup"
    assert messages[-1]["role"] == "tool"
    assert messages[-1]["content"] == "value-for-alpha"


async def test_loop_returns_immediately_when_no_tools_are_called() -> None:
    server = FakeOpenAIServer(FakeResponse(text="No tools needed."))
    async with make_client(server) as client:
        result = await client.run_tools("hi", tools=[lookup], target="openai-compat:m")

    assert result.text == "No tools needed."
    assert server.call_count == 1


async def test_multiple_calls_dispatch_sequentially() -> None:
    order: list[str] = []

    @tool
    def record(name: str) -> str:
        """Record a name."""
        order.append(name)
        return name

    server = FakeOpenAIServer(
        [
            FakeResponse(
                text="",
                tool_calls=(
                    ("c1", "record", '{"name": "first"}'),
                    ("c2", "record", '{"name": "second"}'),
                ),
                finish_reason="tool_calls",
            ),
            FakeResponse(text="done"),
        ]
    )
    async with make_client(server) as client:
        await client.run_tools("go", tools=[record], target="openai-compat:m")

    assert order == ["first", "second"], "v1 dispatch is sequential and ordered"


async def test_tool_errors_reach_the_model() -> None:
    @tool
    def flaky(value: str) -> str:
        """Fail on purpose."""
        raise RuntimeError("upstream is down")

    server = FakeOpenAIServer(
        [
            FakeResponse(
                text="",
                tool_calls=(("c1", "flaky", '{"value": "x"}'),),
                finish_reason="tool_calls",
            ),
            FakeResponse(text="I could not complete that."),
        ]
    )
    async with make_client(server) as client:
        result = await client.run_tools("go", tools=[flaky], target="openai-compat:m")

    assert result.text == "I could not complete that."
    tool_message = server.requests[1]["messages"][-1]
    assert "RuntimeError: upstream is down" in tool_message["content"]


async def test_round_bound_is_enforced() -> None:
    """Without a bound, a model that keeps calling tools never terminates."""
    server = FakeOpenAIServer(
        FakeResponse(
            text="",
            tool_calls=(("c", "lookup", '{"key": "a"}'),),
            finish_reason="tool_calls",
        )
    )
    async with make_client(server) as client:
        with pytest.raises(ToolLoopError) as excinfo:
            await client.run_tools(
                "go", tools=[lookup], target="openai-compat:m", max_rounds=3
            )

    assert server.call_count == 3
    assert excinfo.value.hint is not None
    assert "max_rounds" in excinfo.value.hint


async def test_tool_specs_reach_the_provider() -> None:
    server = FakeOpenAIServer(FakeResponse(text="done"))
    async with make_client(server) as client:
        await client.run_tools("hi", tools=[lookup], target="openai-compat:m")

    tools = server.requests[0]["tools"]
    assert tools[0]["function"]["name"] == "lookup"
    assert tools[0]["function"]["parameters"]["properties"]["key"] == {"type": "string"}


def test_loop_works_through_the_sync_facade() -> None:
    server = FakeOpenAIServer(
        [
            FakeResponse(
                text="",
                tool_calls=(("c1", "lookup", '{"key": "beta"}'),),
                finish_reason="tool_calls",
            ),
            FakeResponse(text="value-for-beta"),
        ]
    )
    with make_sync_client(server) as client:
        result = client.run_tools("go", tools=[lookup], target="openai-compat:m")

    assert result.text == "value-for-beta"
