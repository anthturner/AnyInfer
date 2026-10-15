"""Model Context Protocol servers as a source of tools for the existing loop.

What this adds is a *source* of `ToolSpec` plus a dispatcher. It adds no loop semantics —
no planning, no memory, no parallelism, so the tool loop it feeds is exactly the bounded,
sequential one that already shipped. That distinction is the whole reason this can exist
without becoming the agent framework this project refuses to be.

```python
async with await MCPToolset.connect(MCPServer(name="fs", command=("mcp-server-fs", "."))) as tools:
    result = await client.run_tools(prompt, tools=tools.tools, target="anthropic:...")
```
"""

from __future__ import annotations

import itertools
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .._client.tools import Tool
from ..credentials import ResolverChain, default_resolver
from ..errors import ToolLoopError
from ..types.requests import ToolAnnotations, ToolSpec
from .protocol import (
    encode_notification,
    encode_request,
    initialize_params,
    read_initialize,
    read_result,
)
from .transport import HTTPTransport, MCPTransport, StdioTransport

__all__ = ["NAMESPACE_SEPARATOR", "MCPServer", "MCPToolset"]

NAMESPACE_SEPARATOR = "__"
"""Separator between a server's name and its tool's name.

Double underscore rather than a dot or a slash: every provider that accepts tools
constrains the name charset, and ``[a-zA-Z0-9_-]`` is the intersection that all of them
accept. A dot would be rejected outright by some and silently mangled by others.
"""

_MAX_RESULT_CHARS = 100_000
"""Bound on one tool result's text, so a runaway server cannot exhaust a context window."""


@dataclass(frozen=True, slots=True)
class MCPServer:
    """How to reach one MCP server.

    Exactly one of ``command`` (stdio) or ``url`` (streamable HTTP) is required.

    Attributes:
        name: Local name for this server; namespaces its tools.
        command: argv to spawn, for a stdio server.
        url: Endpoint, for an HTTP server.
        env: Extra environment for a spawned server. Values may be credential references
            (``env://``, ``credential://``) and are resolved and registered for redaction
            before the process starts.
        headers: Extra request headers for an HTTP server, where authentication goes.
            Values may use the same credential references as ``env``.
        cwd: Working directory for a spawned server.
        timeout_s: How long any one call may take.
        allow_tools: If non-empty, only these tool names are exposed.
        deny_tools: Tool names to withhold, applied after ``allow_tools``.
    """

    name: str
    command: tuple[str, ...] = ()
    url: str | None = None
    env: Mapping[str, str] = field(default_factory=dict)
    headers: Mapping[str, str] = field(default_factory=dict)
    cwd: str | None = None
    timeout_s: float = 30.0
    allow_tools: tuple[str, ...] = ()
    deny_tools: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Reject a server that cannot be reached.

        Raises:
            ToolLoopError: If neither or both of ``command`` and ``url`` are supplied, or
                the name is blank.
        """
        if not isinstance(self.name, str) or not self.name.strip():
            raise ToolLoopError("an MCP server needs a name to namespace its tools")
        if self.command and any(
            not isinstance(part, str) or not part for part in self.command
        ):
            raise ToolLoopError(
                f"MCP server {self.name!r} command entries must be non-empty strings"
            )
        if self.url is not None and (
            not isinstance(self.url, str) or not self.url.strip()
        ):
            raise ToolLoopError(f"MCP server {self.name!r} url must be a non-empty string")
        if bool(self.command) == bool(self.url):
            raise ToolLoopError(
                f"MCP server {self.name!r} needs exactly one of command= or url=",
                hint="command=(...) spawns a stdio server; url=... reaches one over HTTP",
            )
        if (
            isinstance(self.timeout_s, bool)
            or not isinstance(self.timeout_s, int | float)
            or self.timeout_s <= 0
        ):
            raise ToolLoopError(f"MCP server {self.name!r} timeout_s must be positive")
        for label, values in (("env", self.env), ("headers", self.headers)):
            if not isinstance(values, Mapping) or not all(
                isinstance(key, str)
                and bool(key)
                and isinstance(value, str)
                for key, value in values.items()
            ):
                raise ToolLoopError(
                    f"MCP server {self.name!r} {label} must map non-empty strings to strings"
                )
        for label, names in (("allow_tools", self.allow_tools), ("deny_tools", self.deny_tools)):
            if any(not isinstance(name, str) or not name for name in names):
                raise ToolLoopError(
                    f"MCP server {self.name!r} {label} entries must be non-empty strings"
                )

    def exposes(self, tool_name: str) -> bool:
        """Whether this server's filters permit exposing ``tool_name``."""
        if self.allow_tools and tool_name not in self.allow_tools:
            return False
        return tool_name not in self.deny_tools


class MCPToolset:
    """Tools discovered from one or more MCP servers, as ordinary AnyInfer tools.

    Use it as an async context manager so the servers are shut down — and, for stdio
    servers, their process trees killed — even when the loop raises.
    """

    def __init__(
        self,
        connections: Sequence[tuple[MCPServer, MCPTransport, tuple[Tool, ...]]],
    ) -> None:
        self._connections = list(connections)

    @classmethod
    async def connect(
        cls,
        *servers: MCPServer,
        resolver: ResolverChain | None = None,
        client_version: str | None = None,
        transport_factory: Any | None = None,
    ) -> MCPToolset:
        """Connect to each server, handshake, and discover its tools.

        Args:
            servers: The servers to connect to.
            resolver: Credential resolver for ``env`` and HTTP-header values; the default
                chain resolves ``env://`` and, with the keyring extra, ``credential://``.
            client_version: Version to report in the handshake; defaults to the installed
                package version.
            transport_factory: Test seam — called with the server to build its transport.

        Returns:
            A toolset whose `tools` can be handed straight to ``run_tools``.

        Raises:
            ToolLoopError: If a server fails to start, refuses the handshake, or answers
                with a protocol version this client does not speak.
        """
        from .. import __version__

        seen_names: set[str] = set()
        repeated_names: set[str] = set()
        for server in servers:
            if server.name in seen_names:
                repeated_names.add(server.name)
            seen_names.add(server.name)
        duplicate_names = sorted(repeated_names)
        if duplicate_names:
            rendered = ", ".join(repr(name) for name in duplicate_names)
            raise ToolLoopError(
                f"MCP server names must be unique; repeated: {rendered}",
                hint="server names namespace discovered tools",
            )

        chain = resolver or default_resolver()
        version = client_version or __version__
        connections: list[tuple[MCPServer, MCPTransport, tuple[Tool, ...]]] = []

        try:
            for server in servers:
                transport = (
                    transport_factory(server)
                    if transport_factory is not None
                    else _build_transport(server, chain)
                )
                counter = itertools.count(1)
                await _handshake(transport, server, version, counter)
                discovered = await _discover(transport, server, counter)
                connections.append((server, transport, discovered))
        except BaseException:
            # A partially-connected toolset would leave orphaned processes behind.
            for _, transport, _ in connections:
                await transport.aclose()
            raise

        return cls(connections)

    @property
    def tools(self) -> tuple[Tool, ...]:
        """Every discovered tool, namespaced by its server."""
        return tuple(tool for _, _, tools in self._connections for tool in tools)

    @property
    def servers(self) -> tuple[MCPServer, ...]:
        """The servers this toolset is connected to."""
        return tuple(server for server, _, _ in self._connections)

    async def aclose(self) -> None:
        """Shut down every server, whatever happened to the others."""
        for _, transport, _ in self._connections:
            await transport.aclose()
        self._connections.clear()

    async def __aenter__(self) -> MCPToolset:
        """Enter a context that closes every server on exit."""
        return self

    async def __aexit__(self, *_: object) -> None:
        """Close every server."""
        await self.aclose()


def _build_transport(server: MCPServer, resolver: ResolverChain) -> MCPTransport:
    """Build the transport a server description asks for, resolving its credentials."""
    if server.url is not None:
        headers = {
            key: resolver.resolve(value) or "" for key, value in server.headers.items()
        }
        return HTTPTransport(server.url, headers=headers)

    # Environment values are credential-shaped: resolve references and register them for
    # redaction before they reach a process listing, an error, or an event.
    resolved = {key: resolver.resolve(value) or "" for key, value in server.env.items()}
    return StdioTransport(server.command, env=resolved, cwd=server.cwd)


async def _handshake(
    transport: MCPTransport,
    server: MCPServer,
    version: str,
    counter: itertools.count[int],
) -> None:
    """Run ``initialize`` and complete it with the required notification."""
    payload = encode_request(next(counter), "initialize", initialize_params(version))
    message = await transport.request(payload, timeout_s=server.timeout_s)
    read_initialize(read_result(message))
    await transport.notify(encode_notification("notifications/initialized"))


async def _discover(
    transport: MCPTransport,
    server: MCPServer,
    counter: itertools.count[int],
) -> tuple[Tool, ...]:
    """List a server's tools, following pagination, and wrap each as a `Tool`."""
    tools: list[Tool] = []
    cursor: str | None = None

    while True:
        params = {"cursor": cursor} if cursor else None
        payload = encode_request(next(counter), "tools/list", params)
        result = read_result(await transport.request(payload, timeout_s=server.timeout_s))

        for entry in result.get("tools") or ():
            if not isinstance(entry, Mapping):
                continue
            name = str(entry.get("name", ""))
            if not name or not server.exposes(name):
                continue
            tools.append(_build_tool(transport, server, entry, name, counter))

        next_cursor = result.get("nextCursor")
        if not isinstance(next_cursor, str) or not next_cursor:
            return tuple(tools)
        cursor = next_cursor


def _build_tool(
    transport: MCPTransport,
    server: MCPServer,
    entry: Mapping[str, Any],
    name: str,
    counter: itertools.count[int],
) -> Tool:
    """Wrap one advertised tool as a callable `Tool`."""
    parameters = entry.get("inputSchema")
    spec = ToolSpec(
        name=f"{server.name}{NAMESPACE_SEPARATOR}{name}",
        description=str(entry.get("description", "")),
        # Passed through unmodified: it is already the shape providers expect, and
        # re-deriving it could only lose fidelity.
        parameters=dict(parameters) if isinstance(parameters, Mapping) else {},
        annotations=_read_annotations(entry.get("annotations")),
    )

    async def call(**arguments: Any) -> str:
        payload = encode_request(
            next(counter), "tools/call", {"name": name, "arguments": arguments}
        )
        result = read_result(await transport.request(payload, timeout_s=server.timeout_s))
        text, is_error = _flatten_content(result)
        if is_error:
            # A tool that failed its own work is a normal conversational event; the loop
            # feeds the failure back so the model can recover.
            raise _ToolReportedError(text)
        return text

    return Tool(spec=spec, func=call)


class _ToolReportedError(Exception):
    """A server reported that its own tool failed.

    Raised rather than returned so the tool loop's dispatcher does what it already does
    with any raising tool: turn it into an error-flagged `ToolResult` the model can try to
    recover from. A tool that fails is a normal conversational event, not a caller's
    exception.
    """


def _read_annotations(raw: Any) -> ToolAnnotations:
    """Read the optional behavioural hints, absent fields staying ``None``.

    These are untrusted server-supplied hints — the protocol says so, so they are captured
    for a caller to reason about and are never acted on as a permission.
    """
    if not isinstance(raw, Mapping):
        return ToolAnnotations()

    def flag(key: str) -> bool | None:
        value = raw.get(key)
        return value if isinstance(value, bool) else None

    title = raw.get("title")
    return ToolAnnotations(
        title=str(title) if isinstance(title, str) and title else None,
        read_only=flag("readOnlyHint"),
        destructive=flag("destructiveHint"),
        idempotent=flag("idempotentHint"),
        open_world=flag("openWorldHint"),
    )


def _flatten_content(result: Mapping[str, Any]) -> tuple[str, bool]:
    """Flatten ``content[]`` into text, naming whatever had to be dropped.

    A silently discarded image is a wrong answer with no evidence, so a non-text block
    leaves a bounded placeholder describing what was there.
    """
    parts: list[str] = []
    for block in result.get("content") or ():
        if not isinstance(block, Mapping):
            continue
        kind = str(block.get("type", ""))
        if kind == "text":
            parts.append(str(block.get("text", "")))
        else:
            parts.append(f"[{kind or 'unknown'} content omitted]")

    text = "\n".join(part for part in parts if part)
    if len(text) > _MAX_RESULT_CHARS:
        text = text[:_MAX_RESULT_CHARS] + "\n[truncated]"
    return text, bool(result.get("isError"))
