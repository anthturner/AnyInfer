"""The ``vnd.amazon.eventstream`` binary framing.

AWS streams Bedrock's ConverseStream as length-prefixed binary frames rather than SSE or
NDJSON, and offers no text alternative, so speaking Converse at all means decoding this.
It is first-party for the same reason the SSE parser is: the core carries no provider SDKs,
and one well-tested decoder beats a dependency.

Each frame is::

    [total length : uint32] [headers length : uint32] [prelude CRC32 : uint32]
    [headers ...] [payload ...] [message CRC32 : uint32]

Both CRCs are verified. A corrupted frame is a protocol error rather than something to
parse through — silently accepting a bad frame would surface as mysteriously truncated
model output.
"""

from __future__ import annotations

import binascii
import json
import struct
from collections.abc import AsyncGenerator, AsyncIterator, Mapping
from contextlib import aclosing
from dataclasses import dataclass
from typing import Any, cast

from ..errors import StreamProtocolError
from .sse import _ByteBudget

__all__ = ["EventStreamMessage", "iter_event_stream"]

_PRELUDE_LENGTH = 12
"""Total length, headers length, and the prelude CRC."""

_CRC_LENGTH = 4

# Header value types, per the event-stream specification. Bedrock only ever sends string
# headers (`:event-type`, `:message-type`, `:content-type`), but a decoder that guesses at
# the others would mis-frame the moment one appeared, so all of them are handled.
_HEADER_BOOL_TRUE = 0
_HEADER_BOOL_FALSE = 1
_HEADER_BYTE = 2
_HEADER_SHORT = 3
_HEADER_INTEGER = 4
_HEADER_LONG = 5
_HEADER_BYTES = 6
_HEADER_STRING = 7
_HEADER_TIMESTAMP = 8
_HEADER_UUID = 9


@dataclass(frozen=True, slots=True)
class EventStreamMessage:
    """One decoded frame.

    Attributes:
        headers: The frame's headers. ``:event-type`` names the event (``messageStart``,
            ``contentBlockDelta``, …), and ``:message-type`` distinguishes ``event`` from
            ``exception``.
        payload: The raw payload bytes, usually a JSON object.
    """

    headers: Mapping[str, Any]
    payload: bytes

    @property
    def event_type(self) -> str:
        """The ``:event-type`` header, or ``""`` when absent."""
        value = self.headers.get(":event-type")
        return value if isinstance(value, str) else ""

    @property
    def message_type(self) -> str:
        """The ``:message-type`` header, or ``""`` when absent."""
        value = self.headers.get(":message-type")
        return value if isinstance(value, str) else ""

    @property
    def is_exception(self) -> bool:
        """Whether this frame carries an in-stream error rather than an event."""
        return self.message_type == "exception"

    def json(self) -> Any:
        """Decode the payload as JSON.

        Raises:
            anyinfer.errors.StreamProtocolError: When the payload is not valid JSON.
        """
        if not self.payload:
            return {}
        try:
            return json.loads(self.payload)
        except ValueError as exc:
            raise StreamProtocolError(f"malformed JSON in an event-stream frame: {exc}") from exc


async def iter_event_stream(
    chunks: AsyncIterator[bytes],
    *,
    max_bytes: int,
    provider: str | None = None,
) -> AsyncGenerator[EventStreamMessage, None]:
    """Decode a binary event stream into frames.

    Network chunk boundaries have nothing to do with frame boundaries, so a partial buffer
    is carried across chunks until a whole frame is available.

    Args:
        chunks: Raw response byte chunks.
        max_bytes: Cap across the whole stream.
        provider: Provider id, for error attribution.

    Yields:
        Each decoded frame, in order.

    Raises:
        anyinfer.errors.StreamProtocolError: On a CRC mismatch, an impossible frame
            length, or a byte-cap breach.
    """
    buffer = bytearray()
    budget = _ByteBudget(max_bytes, provider)

    # `aclosing` rather than a bare `async for`: see the matching comment in
    # `sse.iter_sse` for why an early exit here would otherwise orphan `chunks`, and why
    # the cast below is safe.
    async with aclosing(cast(AsyncGenerator[bytes, None], chunks)) as chunks:
        async for chunk in chunks:
            budget.consume(chunk)
            buffer.extend(chunk)

            while True:
                frame = _take_frame(buffer, provider)
                if frame is None:
                    break
                yield frame

    if buffer:
        raise StreamProtocolError(
            f"event stream ended mid-frame with {len(buffer)} trailing byte(s)",
            provider=provider,
        )


def _take_frame(buffer: bytearray, provider: str | None) -> EventStreamMessage | None:
    """Consume one complete frame from the head of ``buffer``, or return ``None``.

    Raises:
        anyinfer.errors.StreamProtocolError: On a corrupt prelude or payload.
    """
    if len(buffer) < _PRELUDE_LENGTH:
        return None

    total_length, headers_length, prelude_crc = struct.unpack(">III", buffer[:_PRELUDE_LENGTH])

    computed = binascii.crc32(bytes(buffer[:8])) & 0xFFFFFFFF
    if computed != prelude_crc:
        raise StreamProtocolError("event-stream prelude failed its checksum", provider=provider)
    if total_length < _PRELUDE_LENGTH + _CRC_LENGTH or headers_length > total_length:
        raise StreamProtocolError(
            f"event-stream frame declares an impossible length ({total_length})",
            provider=provider,
        )
    if len(buffer) < total_length:
        return None

    frame = bytes(buffer[:total_length])
    del buffer[:total_length]

    message_crc = struct.unpack(">I", frame[-_CRC_LENGTH:])[0]
    if binascii.crc32(frame[:-_CRC_LENGTH]) & 0xFFFFFFFF != message_crc:
        raise StreamProtocolError("event-stream frame failed its checksum", provider=provider)

    headers_end = _PRELUDE_LENGTH + headers_length
    headers = _decode_headers(frame[_PRELUDE_LENGTH:headers_end], provider)
    payload = frame[headers_end : total_length - _CRC_LENGTH]
    return EventStreamMessage(headers=headers, payload=payload)


def _decode_headers(raw: bytes, provider: str | None) -> dict[str, Any]:
    """Decode the header block of one frame.

    Raises:
        anyinfer.errors.StreamProtocolError: On a truncated or unknown-typed header.
    """
    headers: dict[str, Any] = {}
    offset = 0
    size = len(raw)

    while offset < size:
        try:
            name_length = raw[offset]
            offset += 1
            name = raw[offset : offset + name_length].decode("utf-8")
            offset += name_length
            value_type = raw[offset]
            offset += 1
            value, offset = _decode_header_value(raw, offset, value_type, provider)
        except (IndexError, UnicodeDecodeError, struct.error) as exc:
            raise StreamProtocolError(
                f"malformed event-stream header block: {exc}", provider=provider
            ) from exc
        headers[name] = value

    return headers


def _decode_header_value(
    raw: bytes, offset: int, value_type: int, provider: str | None
) -> tuple[Any, int]:
    """Decode one header value, returning it with the new offset."""
    if value_type == _HEADER_BOOL_TRUE:
        return True, offset
    if value_type == _HEADER_BOOL_FALSE:
        return False, offset
    if value_type == _HEADER_BYTE:
        return struct.unpack_from(">b", raw, offset)[0], offset + 1
    if value_type == _HEADER_SHORT:
        return struct.unpack_from(">h", raw, offset)[0], offset + 2
    if value_type == _HEADER_INTEGER:
        return struct.unpack_from(">i", raw, offset)[0], offset + 4
    if value_type in (_HEADER_LONG, _HEADER_TIMESTAMP):
        return struct.unpack_from(">q", raw, offset)[0], offset + 8
    if value_type in (_HEADER_BYTES, _HEADER_STRING):
        length = struct.unpack_from(">H", raw, offset)[0]
        offset += 2
        chunk = raw[offset : offset + length]
        decoded = chunk.decode("utf-8") if value_type == _HEADER_STRING else chunk
        return decoded, offset + length
    if value_type == _HEADER_UUID:
        return raw[offset : offset + 16].hex(), offset + 16

    raise StreamProtocolError(f"unknown event-stream header type {value_type}", provider=provider)
