"""Model Context Protocol servers as a source of tools.

MCP has become how tools are *distributed*. This subpackage connects to a server, discovers
its tools, and hands them to the existing tool loop as ordinary `anyinfer.tool` values —
nothing more. It adds no planning, no memory, and no loop semantics, which is what keeps it
on the right side of the "not an agent framework" line.

Scope is deliberately two protocol methods wide: ``tools/list`` and ``tools/call``. Prompts,
resources, roots, and — pointedly — sampling are out. Honouring a server's sampling request
would let it drive generations through the caller's credentials; that is a capability to
grant deliberately, not one to inherit from a tool integration.

The protocol is spoken directly against ``httpx2`` and the standard library. What AnyInfer
depends on is recorded in ``contracts/mcp.md`` and audited by the ordinary drift check.

```python
from anyinfer.mcp import MCPServer, MCPToolset

async with await MCPToolset.connect(MCPServer(name="fs", command=("mcp-server-fs", "."))) as tools:
    result = await client.run_tools("What is in this directory?", tools=tools.tools, target=...)
```

!!! warning "Tool results are attacker-influenceable"

    Text a server returns enters the model's context. Connect servers you trust, and use
    ``allow_tools`` / ``deny_tools`` to narrow what a server may expose.
"""

from .protocol import ACCEPTED_PROTOCOL_VERSIONS, PROTOCOL_VERSION, ServerInfo
from .toolset import NAMESPACE_SEPARATOR, MCPServer, MCPToolset
from .transport import HTTPTransport, MCPTransport, StdioTransport

__all__ = [
    "ACCEPTED_PROTOCOL_VERSIONS",
    "NAMESPACE_SEPARATOR",
    "PROTOCOL_VERSION",
    "HTTPTransport",
    "MCPServer",
    "MCPToolset",
    "MCPTransport",
    "ServerInfo",
    "StdioTransport",
]
