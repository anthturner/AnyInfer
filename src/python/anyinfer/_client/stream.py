"""`AsyncStream` — the handle returned by `AsyncClient.stream()`.

Its own module because it is a value type over an event iterator, not part of the
client's orchestration: it holds no providers, no routing, and no policy, and nothing in
it needs the client. DESIGN.md §18 has listed a `_client/stream.py` since before the
split; this is that file.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import TracebackType

from ..manifest import ManifestBuilder, RunManifest
from ..types.events import StreamEnded, StreamEvent
from ..types.results import Generation

__all__ = ["AsyncStream"]


class AsyncStream:
    """An async iterator over stream events, with the final result attached.

    Supports the three consumption shapes the design targets: iterate deltas, watch for the
    first-token mark and then read the result, or ignore events and read the result.
    """

    def __init__(
        self,
        source: AsyncIterator[StreamEvent],
        *,
        builder: ManifestBuilder | None = None,
    ) -> None:
        self._source = source
        self._result: Generation | None = None
        self._closed = False
        self._builder = builder

    def __aiter__(self) -> AsyncStream:
        """Iterate stream events."""
        return self

    async def __anext__(self) -> StreamEvent:
        """Yield the next event, capturing the result when the stream ends."""
        event = await self._source.__anext__()
        if isinstance(event, StreamEnded):
            self._result = event.result
        return event

    async def __aenter__(self) -> AsyncStream:
        """Enter a context that guarantees the stream is closed."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Close the underlying generator, cancelling any in-flight request."""
        await self.aclose()

    async def aclose(self) -> None:
        """Close the stream early, releasing the provider connection."""
        if self._closed:
            return
        self._closed = True
        aclose = getattr(self._source, "aclose", None)
        if aclose is not None:
            await aclose()

    @property
    def result(self) -> Generation:
        """The final result.

        Raises:
            RuntimeError: If the stream has not been fully consumed yet.
        """
        if self._result is None:
            raise RuntimeError(
                "stream result is not available until the stream has been consumed; "
                "iterate the stream to completion first"
            )
        return self._result

    @property
    def manifest(self) -> RunManifest | None:
        """What this call has done so far, as a `RunManifest`.

        Available at any point, which is the whole reason the handle lives on the stream
        rather than only on the result: a stream that was cancelled or that failed
        part-way has no `Generation` to carry a manifest, and that is precisely the call
        whose story a caller needs. Such a record has ``complete=False``.

        ``None`` when the client was built with manifests switched off.
        """
        return self._builder.build() if self._builder is not None else None

    async def collect(self) -> Generation:
        """Drain the stream and return the final result."""
        async for _ in self:
            pass
        return self.result
