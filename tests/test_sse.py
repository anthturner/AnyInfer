"""SSE and NDJSON framing (§C6).

Chunk boundaries from the network have nothing to do with record boundaries, so the central
property is that any chunking of the same bytes yields the same records.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from anyinfer.errors import StreamProtocolError
from anyinfer.providers.sse import iter_ndjson, iter_sse


async def _chunks(*parts: bytes) -> AsyncIterator[bytes]:
    for part in parts:
        yield part


async def _collect_sse(*parts: bytes, max_bytes: int = 1_000_000) -> list[object]:
    return [item async for item in iter_sse(_chunks(*parts), max_bytes=max_bytes)]


async def _collect_ndjson(*parts: bytes, max_bytes: int = 1_000_000) -> list[object]:
    return [item async for item in iter_ndjson(_chunks(*parts), max_bytes=max_bytes)]


# ---- SSE -----------------------------------------------------------------------------


async def test_simple_records() -> None:
    events = await _collect_sse(b'data: {"a": 1}\n\ndata: {"a": 2}\n\n')
    assert events == [{"a": 1}, {"a": 2}]


async def test_records_split_across_chunks() -> None:
    """A record arriving in fragments must reassemble identically."""
    events = await _collect_sse(b'data: {"va', b'lue": 42}', b"\n\n")
    assert events == [{"value": 42}]


async def test_boundary_split_across_chunks() -> None:
    events = await _collect_sse(b'data: {"a": 1}\n', b'\ndata: {"a": 2}\n\n')
    assert events == [{"a": 1}, {"a": 2}]


async def test_done_sentinel_terminates() -> None:
    events = await _collect_sse(b'data: {"a": 1}\n\ndata: [DONE]\n\ndata: {"never": 1}\n\n')
    assert events == [{"a": 1}]


async def test_comment_lines_are_ignored() -> None:
    """OpenRouter sends ``: OPENROUTER PROCESSING`` keep-alives."""
    events = await _collect_sse(
        b": OPENROUTER PROCESSING\n\n" b'data: {"a": 1}\n\n' b": keep-alive\n\n"
    )
    assert events == [{"a": 1}]


async def test_multiline_data_fields_are_joined() -> None:
    events = await _collect_sse(b'data: {"a":\ndata:  1}\n\n')
    assert events == [{"a": 1}]


async def test_non_data_fields_are_ignored() -> None:
    events = await _collect_sse(b'event: message\nid: 7\ndata: {"a": 1}\n\n')
    assert events == [{"a": 1}]


async def test_crlf_line_endings() -> None:
    events = await _collect_sse(b'data: {"a": 1}\r\n\r\n')
    assert events == [{"a": 1}]


async def test_trailing_record_without_a_blank_line() -> None:
    """A stream that ends abruptly still has a final usable record."""
    events = await _collect_sse(b'data: {"a": 1}')
    assert events == [{"a": 1}]


async def test_malformed_json_raises() -> None:
    with pytest.raises(StreamProtocolError, match="malformed JSON"):
        await _collect_sse(b"data: {not json\n\n")


async def test_byte_cap_is_enforced() -> None:
    with pytest.raises(StreamProtocolError, match="max_response_bytes"):
        await _collect_sse(b"data: " + b"x" * 5000 + b"\n\n", max_bytes=100)


async def test_byte_cap_counts_across_chunks() -> None:
    with pytest.raises(StreamProtocolError):
        await _collect_sse(b"a" * 60, b"a" * 60, max_bytes=100)


async def test_empty_stream_yields_nothing() -> None:
    assert await _collect_sse() == []


async def test_data_field_without_a_leading_space() -> None:
    events = await _collect_sse(b'data:{"a": 1}\n\n')
    assert events == [{"a": 1}]


@pytest.mark.parametrize("size", [1, 3, 7, 13, 64])
async def test_any_chunking_yields_the_same_records(size: int) -> None:
    """The parser must be indifferent to how the transport fragmented the bytes."""
    body = b'data: {"a": 1}\n\ndata: {"b": [1, 2, 3]}\n\ndata: [DONE]\n\n'
    parts = [body[i : i + size] for i in range(0, len(body), size)]
    events = await _collect_sse(*parts)
    assert events == [{"a": 1}, {"b": [1, 2, 3]}]


# ---- NDJSON --------------------------------------------------------------------------


async def test_ndjson_lines() -> None:
    events = await _collect_ndjson(b'{"a": 1}\n{"a": 2}\n')
    assert events == [{"a": 1}, {"a": 2}]


async def test_ndjson_partial_lines_buffer() -> None:
    events = await _collect_ndjson(b'{"a":', b" 1}\n")
    assert events == [{"a": 1}]


async def test_ndjson_final_line_without_a_newline() -> None:
    events = await _collect_ndjson(b'{"a": 1}')
    assert events == [{"a": 1}]


async def test_ndjson_blank_lines_are_skipped() -> None:
    events = await _collect_ndjson(b'{"a": 1}\n\n\n{"a": 2}\n')
    assert events == [{"a": 1}, {"a": 2}]


async def test_ndjson_malformed_raises() -> None:
    with pytest.raises(StreamProtocolError, match="malformed JSON"):
        await _collect_ndjson(b"{broken\n")


async def test_ndjson_byte_cap() -> None:
    with pytest.raises(StreamProtocolError, match="max_response_bytes"):
        await _collect_ndjson(b'{"a": "' + b"x" * 500 + b'"}\n', max_bytes=100)


@pytest.mark.parametrize("size", [1, 5, 11])
async def test_ndjson_any_chunking(size: int) -> None:
    body = b'{"a": 1}\n{"b": 2}\n{"c": 3}\n'
    parts = [body[i : i + size] for i in range(0, len(body), size)]
    assert await _collect_ndjson(*parts) == [{"a": 1}, {"b": 2}, {"c": 3}]
