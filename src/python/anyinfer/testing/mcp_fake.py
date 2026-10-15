"""An in-process fake MCP server.

Public for the same reason the scripted provider is: an application testing an MCP-backed
tool loop would otherwise rebuild this, and would rebuild the protocol details — handshake,
version negotiation, content-block shapes, error semantics — slightly wrong.

It is a *transport*, not a socket or a subprocess: no ports, no process trees, and
identical behaviour on every platform.

```python
server = FakeMCPServer([FakeMCPTool("read_file", result="file contents")])
toolset = await MCPToolset.connect(
    MCPServer(name="fs", url="http://fake.invalid/mcp"),
    transport_factory=lambda _: server.transport(),
)
```
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from ..mcp.protocol import JSONRPC_VERSION, PROTOCOL_VERSION

__all__ = ["FakeMCPServer", "FakeMCPTool"]


@dataclass(frozen=True, slots=True)
class FakeMCPTool:
    """One tool a fake server advertises, and what calling it produces.

    Attributes:
        name: The tool's name, un-namespaced.
        description: What the model is told it does.
        parameters: JSON Schema for its arguments; an empty object accepts anything.
        result: Text the tool returns.
        is_error: Whether the call reports its own failure, which a loop feeds back to the
            model rather than raising.
        annotations: Behavioural hints to advertise, in the protocol's own spelling
            (``readOnlyHint`` and friends).
        blocks: Overrides ``result`` with raw content blocks, for testing what happens to
            non-text content.
    """

    name: str
    description: str = "A fake tool."
    parameters: Mapping[str, Any] = field(default_factory=dict)
    result: str = "fake tool result"
    is_error: bool = False
    annotations: Mapping[str, Any] = field(default_factory=dict)
    blocks: tuple[Mapping[str, Any], ...] = ()


class FakeMCPServer:
    """A scripted MCP server that answers over an in-process transport.

    Args:
        tools: The tools to advertise.
        protocol_version: Version to answer the handshake with. Override it to test a
            client's version negotiation.
        page_size: Advertise tools across several ``tools/list`` pages, to exercise
            pagination. ``0`` means one page.

    Attributes:
        calls: Every ``tools/call`` received, as ``(name, arguments)`` pairs.
    """

    def __init__(
        self,
        tools: Sequence[FakeMCPTool] | None = None,
        *,
        protocol_version: str = PROTOCOL_VERSION,
        page_size: int = 0,
    ) -> None:
        self._tools = list(tools or [])
        self._protocol_version = protocol_version
        self._page_size = page_size
        self.calls: list[tuple[str, Mapping[str, Any]]] = []
        self.initialized = False

    def transport(self) -> _FakeMCPTransport:
        """An `anyinfer.mcp.MCPTransport` serving this fake."""
        return _FakeMCPTransport(self)

    # ---- protocol ---------------------------------------------------------------------

    def handle(self, message: Mapping[str, Any]) -> dict[str, Any] | None:
        """Answer one JSON-RPC message, or ``None`` for a notification."""
        method = str(message.get("method", ""))
        request_id = message.get("id")

        if request_id is None:
            if method == "notifications/initialized":
                self.initialized = True
            return None

        if method == "initialize":
            return self._ok(request_id, self._initialize())
        if method == "tools/list":
            params = message.get("params") or {}
            cursor = params.get("cursor") if isinstance(params, Mapping) else None
            return self._ok(request_id, self._list(cursor))
        if method == "tools/call":
            params = message.get("params") or {}
            return self._call(request_id, params if isinstance(params, Mapping) else {})

        return {
            "jsonrpc": JSONRPC_VERSION,
            "id": request_id,
            "error": {"code": -32601, "message": f"method not found: {method}"},
        }

    def _initialize(self) -> dict[str, Any]:
        return {
            "protocolVersion": self._protocol_version,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "fake-mcp", "version": "0.0.0"},
        }

    def _list(self, cursor: Any) -> dict[str, Any]:
        entries = [self._describe(tool) for tool in self._tools]
        if not self._page_size:
            return {"tools": entries}

        start = int(cursor) if isinstance(cursor, str) and cursor.isdigit() else 0
        page = entries[start : start + self._page_size]
        result: dict[str, Any] = {"tools": page}
        if start + self._page_size < len(entries):
            result["nextCursor"] = str(start + self._page_size)
        return result

    @staticmethod
    def _describe(tool: FakeMCPTool) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "name": tool.name,
            "description": tool.description,
            "inputSchema": dict(tool.parameters) or {"type": "object", "properties": {}},
        }
        if tool.annotations:
            entry["annotations"] = dict(tool.annotations)
        return entry

    def _call(self, request_id: Any, params: Mapping[str, Any]) -> dict[str, Any]:
        name = str(params.get("name", ""))
        arguments = params.get("arguments")
        self.calls.append((name, dict(arguments) if isinstance(arguments, Mapping) else {}))

        tool = next((t for t in self._tools if t.name == name), None)
        if tool is None:
            return {
                "jsonrpc": JSONRPC_VERSION,
                "id": request_id,
                "error": {"code": -32602, "message": f"unknown tool: {name}"},
            }

        content = (
            [dict(block) for block in tool.blocks]
            if tool.blocks
            else [{"type": "text", "text": tool.result}]
        )
        return self._ok(request_id, {"content": content, "isError": tool.is_error})

    @staticmethod
    def _ok(request_id: Any, result: Mapping[str, Any]) -> dict[str, Any]:
        return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "result": dict(result)}


class _FakeMCPTransport:
    """Routes JSON-RPC payloads to a `FakeMCPServer` without leaving the process."""

    def __init__(self, server: FakeMCPServer) -> None:
        self._server = server
        self.closed = False

    async def request(self, payload: bytes, *, timeout_s: float) -> dict[str, Any]:
        """Answer one request."""
        message = json.loads(payload)
        reply = self._server.handle(message)
        if reply is None:  # pragma: no cover — notifications go through notify()
            return {"jsonrpc": JSONRPC_VERSION, "id": message.get("id"), "result": {}}
        return reply

    async def notify(self, payload: bytes) -> None:
        """Absorb one notification."""
        self._server.handle(json.loads(payload))

    async def aclose(self) -> None:
        """Record that the toolset shut this server down."""
        self.closed = True
