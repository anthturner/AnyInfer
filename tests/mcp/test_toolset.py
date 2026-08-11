"""MCP servers as a tool source: discovery, dispatch, and the boundaries."""

from __future__ import annotations

import pytest

import anyinfer as ai
from anyinfer.credentials import default_resolver
from anyinfer.errors import ToolLoopError
from anyinfer.mcp import NAMESPACE_SEPARATOR, MCPServer, MCPToolset
from anyinfer.mcp.protocol import (
    ACCEPTED_PROTOCOL_VERSIONS,
    PROTOCOL_VERSION,
    decode_message,
    encode_request,
    read_initialize,
    read_result,
)
from anyinfer.mcp.toolset import _build_transport
from anyinfer.mcp.transport import HTTPTransport
from anyinfer.testing import FakeMCPServer, FakeMCPTool


def _server(**kwargs: object) -> MCPServer:
    fields: dict[str, object] = {"name": "fs", "url": "http://fake.invalid/mcp"}
    fields.update(kwargs)
    return MCPServer(**fields)  # type: ignore[arg-type]


async def _connect(fake: FakeMCPServer, server: MCPServer | None = None) -> MCPToolset:
    return await MCPToolset.connect(
        server or _server(), transport_factory=lambda _: fake.transport()
    )


# ---- protocol ------------------------------------------------------------------------


def test_a_request_encodes_as_json_rpc() -> None:
    message = decode_message(encode_request(7, "tools/list", {"cursor": "2"}))

    assert message == {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "tools/list",
        "params": {"cursor": "2"},
    }


def test_a_non_json_message_is_refused_with_a_useful_hint() -> None:
    with pytest.raises(ToolLoopError) as caught:
        decode_message(b"this is a log line, not protocol")

    assert "not valid JSON" in str(caught.value)
    assert "stdout" in str(caught.value.hint or "")


def test_an_error_object_becomes_an_exception() -> None:
    with pytest.raises(ToolLoopError) as caught:
        read_result({"jsonrpc": "2.0", "id": 1, "error": {"code": -32601, "message": "nope"}})

    assert "-32601" in str(caught.value) or "32601" in str(caught.value)


@pytest.mark.parametrize(
    "error",
    [
        {"code": "-32601", "message": "wrong type"},
        {"code": -32601, "message": ["wrong type"]},
    ],
)
def test_a_malformed_error_object_is_refused(error: object) -> None:
    with pytest.raises(ToolLoopError, match="malformed JSON-RPC error"):
        read_result({"jsonrpc": "2.0", "id": 1, "error": error})


def test_a_message_with_neither_result_nor_error_is_refused() -> None:
    with pytest.raises(ToolLoopError):
        read_result({"jsonrpc": "2.0", "id": 1})


def test_version_negotiation_accepts_known_revisions() -> None:
    for version in ACCEPTED_PROTOCOL_VERSIONS:
        info = read_initialize({"protocolVersion": version, "capabilities": {"tools": {}}})
        assert info.protocol_version == version
        assert info.serves_tools


def test_an_unknown_protocol_version_fails_loudly() -> None:
    """Proceeding on a guess is how field semantics silently change under you."""
    with pytest.raises(ToolLoopError) as caught:
        read_initialize({"protocolVersion": "1999-01-01"})

    assert "1999-01-01" in str(caught.value)
    assert PROTOCOL_VERSION in str(caught.value.hint or "")


# ---- discovery -----------------------------------------------------------------------


async def test_tools_are_discovered_and_namespaced() -> None:
    fake = FakeMCPServer([FakeMCPTool("read_file"), FakeMCPTool("write_file")])

    async with await _connect(fake) as toolset:
        names = [tool.name for tool in toolset.tools]

    assert names == [f"fs{NAMESPACE_SEPARATOR}read_file", f"fs{NAMESPACE_SEPARATOR}write_file"]


async def test_the_input_schema_passes_through_unmodified() -> None:
    """A rich schema is exactly why MCP tools bypass the Python annotation narrowing."""
    schema = {
        "type": "object",
        "properties": {"path": {"type": "string"}, "depth": {"type": "integer"}},
        "required": ["path"],
        "additionalProperties": False,
    }
    fake = FakeMCPServer([FakeMCPTool("read_file", parameters=schema)])

    async with await _connect(fake) as toolset:
        assert toolset.tools[0].spec.parameters == schema


async def test_the_handshake_completes_with_the_initialized_notification() -> None:
    fake = FakeMCPServer([FakeMCPTool("noop")])

    async with await _connect(fake):
        pass

    assert fake.initialized


async def test_pagination_is_followed() -> None:
    fake = FakeMCPServer([FakeMCPTool(f"tool_{index}") for index in range(5)], page_size=2)

    async with await _connect(fake) as toolset:
        assert len(toolset.tools) == 5


async def test_allow_and_deny_filters_narrow_what_is_exposed() -> None:
    fake = FakeMCPServer(
        [FakeMCPTool("read_file"), FakeMCPTool("write_file"), FakeMCPTool("delete_file")]
    )

    async with await _connect(
        fake, _server(allow_tools=("read_file", "write_file"), deny_tools=("write_file",))
    ) as toolset:
        assert [tool.spec.name for tool in toolset.tools] == [f"fs{NAMESPACE_SEPARATOR}read_file"]


async def test_annotations_are_captured_as_untrusted_hints() -> None:
    fake = FakeMCPServer(
        [
            FakeMCPTool(
                "read_file",
                annotations={
                    "title": "Read a file",
                    "readOnlyHint": True,
                    "destructiveHint": False,
                },
            )
        ]
    )

    async with await _connect(fake) as toolset:
        annotations = toolset.tools[0].spec.annotations

    assert annotations.title == "Read a file"
    assert annotations.read_only is True
    assert annotations.destructive is False
    # Unstated is not the same claim as stated-false.
    assert annotations.idempotent is None
    assert annotations.stated


async def test_a_tool_without_annotations_states_nothing() -> None:
    fake = FakeMCPServer([FakeMCPTool("read_file")])

    async with await _connect(fake) as toolset:
        assert not toolset.tools[0].spec.annotations.stated


# ---- dispatch ------------------------------------------------------------------------


async def test_calling_a_tool_reaches_the_server_with_its_own_name() -> None:
    """The model sees the namespaced name; the server must receive its own."""
    fake = FakeMCPServer([FakeMCPTool("read_file", result="file contents")])

    async with await _connect(fake) as toolset:
        output = await toolset.tools[0].call({"path": "README.md"})

    assert output == "file contents"
    assert fake.calls == [("read_file", {"path": "README.md"})]


async def test_non_text_content_leaves_a_placeholder_rather_than_silence() -> None:
    fake = FakeMCPServer(
        [
            FakeMCPTool(
                "screenshot",
                blocks=({"type": "image", "data": "..."}, {"type": "text", "text": "done"}),
            )
        ]
    )

    async with await _connect(fake) as toolset:
        output = await toolset.tools[0].call({})

    assert "[image content omitted]" in output
    assert "done" in output


async def test_a_server_reported_failure_becomes_an_error_flagged_result() -> None:
    """A failing tool is a normal conversational event, not an exception for the caller."""
    from anyinfer._client.tools import ToolRegistry
    from anyinfer.types.messages import ToolCall

    fake = FakeMCPServer([FakeMCPTool("read_file", result="no such file", is_error=True)])

    async with await _connect(fake) as toolset:
        registry = ToolRegistry(list(toolset.tools))
        result = await registry.dispatch(
            ToolCall(id="c1", name=toolset.tools[0].name, arguments={})
        )

    assert result.is_error
    assert "no such file" in result.content


async def test_an_unknown_method_raises_rather_than_returning_empty() -> None:
    """A server with no tool surface is a misconfiguration, not an empty tool set."""
    fake = FakeMCPServer([])
    fake.handle = lambda message: (  # type: ignore[method-assign]
        {
            "jsonrpc": "2.0",
            "id": message.get("id"),
            "result": {"protocolVersion": PROTOCOL_VERSION},
        }
        if message.get("method") == "initialize"
        else (
            None
            if message.get("id") is None
            else {
                "jsonrpc": "2.0",
                "id": message.get("id"),
                "error": {"code": -32601, "message": "method not found"},
            }
        )
    )

    with pytest.raises(ToolLoopError):
        await _connect(fake)


# ---- lifecycle -----------------------------------------------------------------------


async def test_closing_the_toolset_closes_every_server() -> None:
    fake = FakeMCPServer([FakeMCPTool("noop")])
    transport = fake.transport()

    toolset = await MCPToolset.connect(_server(), transport_factory=lambda _: transport)
    await toolset.aclose()

    assert transport.closed


async def test_a_failed_connection_does_not_leak_earlier_servers() -> None:
    """A partially-connected toolset would leave orphaned processes behind."""
    good = FakeMCPServer([FakeMCPTool("noop")])
    good_transport = good.transport()
    bad = FakeMCPServer([], protocol_version="1999-01-01")

    transports = {"good": good_transport, "bad": bad.transport()}

    with pytest.raises(ToolLoopError):
        await MCPToolset.connect(
            _server(name="good"),
            _server(name="bad"),
            transport_factory=lambda server: transports[server.name],
        )

    assert good_transport.closed


# ---- configuration guards ------------------------------------------------------------


def test_a_server_needs_exactly_one_transport() -> None:
    with pytest.raises(ToolLoopError):
        MCPServer(name="fs")
    with pytest.raises(ToolLoopError):
        MCPServer(name="fs", command=("x",), url="http://x.invalid")


@pytest.mark.parametrize(
    "overrides",
    [
        {"name": ""},
        {"command": ("",), "url": None},
        {"timeout_s": 0},
        {"headers": {"authorization": 42}},
        {"env": {"": "secret"}},
        {"allow_tools": ("",)},
    ],
)
def test_server_descriptions_reject_invalid_values(overrides: dict[str, object]) -> None:
    with pytest.raises(ToolLoopError):
        _server(**overrides)


async def test_server_names_must_be_unique_before_connecting() -> None:
    with pytest.raises(ToolLoopError, match="must be unique"):
        await MCPToolset.connect(_server(), _server())


async def test_http_header_credentials_are_resolved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANYINFER_TEST_MCP_TOKEN", "resolved-secret")
    transport = _build_transport(
        _server(headers={"authorization": "env://ANYINFER_TEST_MCP_TOKEN"}),
        default_resolver(),
    )
    assert isinstance(transport, HTTPTransport)
    try:
        assert transport._client.headers["authorization"] == "resolved-secret"
    finally:
        await transport.aclose()


def test_a_server_needs_a_name() -> None:
    with pytest.raises(ToolLoopError):
        MCPServer(name="  ", url="http://x.invalid")


# ---- end to end through the tool loop ------------------------------------------------


async def test_an_mcp_tool_runs_through_the_real_tool_loop() -> None:
    """The whole point: discovered tools feed run_tools untouched."""
    from anyinfer.registry import ProviderRegistry
    from anyinfer.testing import ScriptedModel, ScriptedProvider

    fake = FakeMCPServer([FakeMCPTool("current_time", result="2026-08-09T12:00:00Z")])
    registry = ProviderRegistry(load_builtins=True, load_entry_points=False)
    provider = ScriptedProvider(
        "acme",
        [
            ScriptedModel(
                "m",
                text="",
                tool_calls=(("c1", f"fs{NAMESPACE_SEPARATOR}current_time", "{}"),),
                finish_reason="tool_calls",
                answer_after_tools="It is midday UTC.",
            )
        ],
    )
    provider.register(registry)

    client = ai.AsyncClient([provider.settings()], registry=registry, use_default_catalog=False)
    try:
        async with await _connect(fake) as toolset:
            await client.run_tools(
                "what time is it?",
                tools=list(toolset.tools),
                target=provider.target("m"),
                max_rounds=2,
            )
    finally:
        await client.aclose()

    assert fake.calls == [("current_time", {})]
