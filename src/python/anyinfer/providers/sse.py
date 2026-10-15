"""Server-sent-events and NDJSON framing.

First-party because the core carries no provider SDKs and every HTTP
adapter needs identical, well-tested framing. Both parsers are byte-capped: a runaway or
hostile response cannot exhaust memory.

Chunk boundaries from the network have nothing to do with record boundaries, so both parsers
carry a partial buffer across chunks.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import aclosing
from typing import Any, cast

from ..errors import StreamProtocolError

__all__ = ["DONE_SENTINEL", "iter_ndjson", "iter_sse"]

DONE_SENTINEL = "[DONE]"
"""OpenAI-dialect stream terminator."""


class _ByteBudget:
    """Enforces a cap across the total bytes of a streamed response."""

    def __init__(self, limit: int, provider: str | None) -> None:
        self._limit = limit
        self._provider = provider
        self._seen = 0

    def consume(self, chunk: bytes) -> None:
        self._seen += len(chunk)
        if self._seen > self._limit:
            raise StreamProtocolError(
                f"response exceeded max_response_bytes ({self._limit} bytes)",
                provider=self._provider,
                hint="raise GenerationRequest.max_response_bytes if this is expected",
            )


async def iter_sse(
    chunks: AsyncIterator[bytes],
    *,
    max_bytes: int,
    provider: str | None = None,
) -> AsyncGenerator[Any, None]:
    """Parse an SSE byte stream into decoded JSON data payloads.

    Handles the framing quirks that matter in practice: records separated by a blank line,
    comment lines (OpenRouter sends ``: OPENROUTER PROCESSING`` keep-alives) ignored,
    multi-line ``data:`` fields joined with newlines, and ``data: [DONE]`` terminating the
    stream.

    Args:
        chunks: Raw response byte chunks.
        max_bytes: Cap across the whole stream.
        provider: Provider id, for error attribution.

    Yields:
        Each record's ``data`` field, JSON-decoded.

    Raises:
        anyinfer.errors.StreamProtocolError: On malformed JSON or a byte-cap breach.
    """
    budget = _ByteBudget(max_bytes, provider)
    buffer = ""

    # `aclosing` rather than a bare `async for`: an early exit here (the caller closes its
    # own generator mid-stream, e.g. SyncStream.close()) throws GeneratorExit at this
    # suspension point, which a plain `async for` does not translate into closing `chunks`
    # — leaving the response body's async generator to finalize during GC instead, which
    # Python 3.14 surfaces as a hard "was never awaited" failure rather than a silent leak.
    # `chunks` is always a real async generator (httpx2's `Response.aiter_bytes()`, typed
    # as the weaker `AsyncIterator` by httpx2 itself); the cast tells mypy what's already
    # true rather than widening this function's own, honestly-typed parameter.
    async with aclosing(cast(AsyncGenerator[bytes, None], chunks)) as chunks:
        async for chunk in chunks:
            budget.consume(chunk)
            buffer += chunk.decode("utf-8", errors="replace")
            buffer = buffer.replace("\r\n", "\n")

            while "\n\n" in buffer:
                record, buffer = buffer.split("\n\n", 1)
                payload = _parse_record(record, provider)
                if payload is _DONE:
                    return
                if payload is not None:
                    yield payload

    # A stream that ends without a trailing blank line still has a final record.
    if buffer.strip():
        payload = _parse_record(buffer, provider)
        if payload is not None and payload is not _DONE:
            yield payload


class _Done:
    """Sentinel marking the stream terminator."""


_DONE = _Done()


def _parse_record(record: str, provider: str | None) -> Any:
    """Decode one SSE record, or return ``None`` when it carries no data."""
    data_lines: list[str] = []
    for line in record.split("\n"):
        if not line or line.startswith(":"):
            continue
        field, _, value = line.partition(":")
        if field != "data":
            continue
        data_lines.append(value[1:] if value.startswith(" ") else value)

    if not data_lines:
        return None
    data = "\n".join(data_lines)
    if data.strip() == DONE_SENTINEL:
        return _DONE
    try:
        return json.loads(data)
    except ValueError as exc:
        raise StreamProtocolError(
            f"malformed JSON in SSE data field: {exc}",
            provider=provider,
        ) from exc


async def iter_ndjson(
    chunks: AsyncIterator[bytes],
    *,
    max_bytes: int,
    provider: str | None = None,
) -> AsyncGenerator[Any, None]:
    """Parse a newline-delimited JSON byte stream (Ollama's framing).

    Args:
        chunks: Raw response byte chunks.
        max_bytes: Cap across the whole stream.
        provider: Provider id, for error attribution.

    Yields:
        One decoded JSON value per line.

    Raises:
        anyinfer.errors.StreamProtocolError: On malformed JSON or a byte-cap breach.
    """
    budget = _ByteBudget(max_bytes, provider)
    buffer = ""

    # See the matching comment in `iter_sse` for why this needs `aclosing` rather than a
    # bare `async for`, and why `chunks` needs the cast.
    async with aclosing(cast(AsyncGenerator[bytes, None], chunks)) as chunks:
        async for chunk in chunks:
            budget.consume(chunk)
            buffer += chunk.decode("utf-8", errors="replace")
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                value = _parse_line(line, provider)
                if value is not None:
                    yield value

    if buffer.strip():
        value = _parse_line(buffer, provider)
        if value is not None:
            yield value


def _parse_line(line: str, provider: str | None) -> Any:
    stripped = line.strip()
    if not stripped:
        return None
    try:
        return json.loads(stripped)
    except ValueError as exc:
        raise StreamProtocolError(
            f"malformed JSON in NDJSON stream: {exc}",
            provider=provider,
        ) from exc
