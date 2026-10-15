"""JSON-RPC framing, correlation, and the Model Context Protocol handshake.

Transport-agnostic on purpose: this module turns method calls into JSON-RPC objects and
matches responses back to them, and knows nothing about subprocesses or HTTP. What carries
the bytes lives in `anyinfer.mcp.transport`.

The protocol is spoken directly rather than through the `mcp` SDK — the same call the
slim-core rule makes for provider SDKs and for the Hugging Face API. What we depend on is
recorded in ``contracts/mcp.md`` and audited by the ordinary drift check.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ..errors import ToolLoopError

__all__ = [
    "ACCEPTED_PROTOCOL_VERSIONS",
    "JSONRPC_VERSION",
    "PROTOCOL_VERSION",
    "JSONRPCError",
    "ServerInfo",
    "decode_message",
    "encode_notification",
    "encode_request",
    "initialize_params",
    "read_initialize",
    "read_result",
]

JSONRPC_VERSION = "2.0"
"""The only JSON-RPC version this protocol uses."""

PROTOCOL_VERSION = "2025-06-18"
"""MCP revision AnyInfer asks for. Recorded in ``contracts/mcp.md``."""

ACCEPTED_PROTOCOL_VERSIONS: frozenset[str] = frozenset({"2025-06-18", "2025-03-26", "2024-11-05"})
"""Revisions AnyInfer will speak if a server answers with one of them.

A server that answers with anything else fails loudly. Proceeding on an unrecognized
version means guessing at field semantics, and a guess that happens to work today is a
silent breakage waiting for the next revision.
"""


@dataclass(frozen=True, slots=True)
class ServerInfo:
    """What a server said about itself during the handshake.

    Attributes:
        name: The server's self-reported name.
        version: Its self-reported version.
        protocol_version: The revision it agreed to speak.
        capabilities: Its advertised capabilities, recorded for diagnostics. AnyInfer uses
            only the presence of a tool surface; the rest is not acted on.
    """

    name: str = ""
    version: str = ""
    protocol_version: str = ""
    capabilities: Mapping[str, Any] = field(default_factory=dict)

    @property
    def serves_tools(self) -> bool:
        """Whether the server advertised a tool surface."""
        return "tools" in self.capabilities


class JSONRPCError(ToolLoopError):
    """A JSON-RPC error object returned in place of a result.

    A protocol-level failure, not a tool failure: an unknown method or invalid params
    cannot be recovered from by re-asking, so it raises rather than becoming an
    error-flagged tool result.

    Attributes:
        code: The JSON-RPC error code.
        data: Whatever the server attached, bounded and redacted by the base class.
    """

    def __init__(self, code: int, message: str, data: Any = None, *, hint: str | None = None):
        super().__init__(f"MCP server returned error {code}: {message}", hint=hint)
        self.code = code
        self.data = data


def encode_request(request_id: int, method: str, params: Mapping[str, Any] | None = None) -> bytes:
    """Encode one JSON-RPC request as a UTF-8 payload."""
    body: dict[str, Any] = {
        "jsonrpc": JSONRPC_VERSION,
        "id": request_id,
        "method": method,
    }
    if params is not None:
        body["params"] = dict(params)
    return json.dumps(body).encode("utf-8")


def encode_notification(method: str, params: Mapping[str, Any] | None = None) -> bytes:
    """Encode one JSON-RPC notification — a call with no id and no reply."""
    body: dict[str, Any] = {"jsonrpc": JSONRPC_VERSION, "method": method}
    if params is not None:
        body["params"] = dict(params)
    return json.dumps(body).encode("utf-8")


def decode_message(raw: bytes | str) -> dict[str, Any]:
    """Decode one JSON-RPC message.

    Raises:
        ToolLoopError: If the payload is not a JSON object. A server that emits garbage on
            its protocol stream cannot be reasoned about, and continuing would mean
            correlating replies to the wrong requests.
    """
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ToolLoopError(
            "an MCP server sent a message that is not valid JSON",
            hint="check the server's stdout for log output written to the protocol stream",
        ) from exc
    if not isinstance(parsed, dict):
        raise ToolLoopError(
            f"an MCP server sent a {type(parsed).__name__} where a JSON-RPC object was expected"
        )
    return parsed


def read_result(message: Mapping[str, Any]) -> Mapping[str, Any]:
    """Extract a result, converting a JSON-RPC error object into an exception.

    Raises:
        JSONRPCError: If the message carries an ``error`` instead of a ``result``.
        ToolLoopError: If it carries neither.
    """
    if "error" in message:
        error = message["error"]
        if isinstance(error, Mapping):
            code = error.get("code")
            error_message = error.get("message")
            if isinstance(code, bool) or not isinstance(code, int) or not isinstance(
                error_message, str
            ):
                raise ToolLoopError("an MCP server sent a malformed JSON-RPC error object")
            raise JSONRPCError(
                code,
                error_message,
                error.get("data"),
                hint=("the server does not expose a tool surface" if code == -32601 else None),
            )
        raise ToolLoopError("an MCP server sent a malformed JSON-RPC error object")

    result = message.get("result")
    if not isinstance(result, Mapping):
        raise ToolLoopError("an MCP response carried neither a result nor an error")
    return result


def initialize_params(client_version: str) -> dict[str, Any]:
    """Build the ``initialize`` params.

    Capabilities are deliberately empty. AnyInfer implements none of the client-side
    features a capability would claim — sampling, roots, elicitation, and advertising one
    it does not honour is how a server ends up waiting on a request that never comes.
    """
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {},
        "clientInfo": {"name": "anyinfer", "version": client_version},
    }


def read_initialize(result: Mapping[str, Any]) -> ServerInfo:
    """Read an ``initialize`` result, enforcing version negotiation.

    Raises:
        ToolLoopError: If the server answered with a revision this client does not speak.
    """
    negotiated_raw = result.get("protocolVersion")
    negotiated = negotiated_raw if isinstance(negotiated_raw, str) else ""
    if negotiated not in ACCEPTED_PROTOCOL_VERSIONS:
        accepted = ", ".join(sorted(ACCEPTED_PROTOCOL_VERSIONS))
        raise ToolLoopError(
            f"an MCP server answered with protocol version {negotiated!r}, "
            f"which this client does not speak",
            hint=f"AnyInfer asks for {PROTOCOL_VERSION} and accepts: {accepted}",
        )

    info = result.get("serverInfo")
    name = version = ""
    if isinstance(info, Mapping):
        name = str(info.get("name", ""))
        version = str(info.get("version", ""))

    capabilities = result.get("capabilities")
    return ServerInfo(
        name=name,
        version=version,
        protocol_version=negotiated,
        capabilities=dict(capabilities) if isinstance(capabilities, Mapping) else {},
    )
