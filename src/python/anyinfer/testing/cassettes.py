"""HTTP cassette record/replay for deterministic conformance runs.

Cassettes capture real provider traffic once, then replay it forever. They are the second
conformance mode (fakes prove we handle *shapes*; cassettes prove we handle *what a provider
actually sent*), and they let CI verify adapters without a live credential set for each one.

Recorded bodies pass through the redaction registry before hitting disk, so a cassette
committed to the repository cannot carry a key.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx2

from ..redaction import redact

__all__ = ["Cassette", "CassetteTransport", "Interaction"]


@dataclass(frozen=True, slots=True)
class Interaction:
    """One recorded request/response exchange.

    Attributes:
        method: HTTP method of the recorded request; replay matches on it.
        url: Full request URL; replay matches on its path, and redaction scrubs it before
            it reaches disk.
        request_body: The request body as text, redacted at save time.
        status: HTTP status code of the recorded response.
        headers: Response headers. Secret-bearing headers are replaced wholesale at save
            time; the rest pass through redaction.
        body: The response body as text, redacted at save time and replayed verbatim.
    """

    method: str
    url: str
    request_body: str
    status: int
    headers: dict[str, str]
    body: str

    def to_json(self) -> dict[str, Any]:
        """Serialize for storage."""
        return {
            "method": self.method,
            "url": self.url,
            "request_body": self.request_body,
            "status": self.status,
            "headers": self.headers,
            "body": self.body,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Interaction:
        """Deserialize from storage."""
        return cls(
            method=str(data["method"]),
            url=str(data["url"]),
            request_body=str(data.get("request_body", "")),
            status=int(data["status"]),
            headers={str(k): str(v) for k, v in dict(data.get("headers", {})).items()},
            body=str(data.get("body", "")),
        )


class Cassette:
    """A file of recorded interactions."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.interactions: list[Interaction] = []
        if path.exists():
            self.load()

    def load(self) -> None:
        """Read interactions from disk."""
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.interactions = [Interaction.from_json(i) for i in data.get("interactions", [])]

    def save(self) -> None:
        """Write interactions to disk, redacting secrets first."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "interactions": [self._redacted(i).to_json() for i in self.interactions],
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @staticmethod
    def _redacted(interaction: Interaction) -> Interaction:
        """Strip registered secrets and authorization headers from an interaction."""
        headers = {
            k: ("[redacted]" if k.lower() in _SECRET_HEADERS else redact(v))
            for k, v in interaction.headers.items()
        }
        return Interaction(
            method=interaction.method,
            url=redact(interaction.url),
            request_body=redact(interaction.request_body),
            status=interaction.status,
            headers=headers,
            body=redact(interaction.body),
        )

    def append(self, interaction: Interaction) -> None:
        """Record an interaction."""
        self.interactions.append(interaction)


_SECRET_HEADERS = frozenset({"authorization", "x-api-key", "api-key", "cookie"})


class CassetteTransport(httpx2.AsyncBaseTransport):
    """Replays a cassette, or records live traffic into one.

    Args:
        cassette: The cassette to read or write.
        record: When ``True``, forward requests to ``inner`` and record the results.
        inner: The transport used while recording. Required in record mode.
    """

    def __init__(
        self,
        cassette: Cassette,
        *,
        record: bool = False,
        inner: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        if record and inner is None:
            inner = httpx2.AsyncHTTPTransport()
        self._cassette = cassette
        self._record = record
        self._inner = inner
        self._cursor = 0

    async def aclose(self) -> None:
        """Close the recording-mode inner transport, when one was opened.

        `AsyncBaseTransport.aclose` is a no-op by default; recording opens a real
        `httpx2.AsyncHTTPTransport` in `__init__` and nothing else was closing its
        connection pool, which leaked a socket per test under this project's
        ``filterwarnings = ["error"]`` gate. Replay mode has no `inner` to close.
        """
        if self._inner is not None:
            await self._inner.aclose()

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        """Serve one request from the cassette, or record it live."""
        if self._record:
            return await self._record_request(request)
        return self._replay(request)

    async def _record_request(self, request: httpx2.Request) -> httpx2.Response:
        inner = self._inner
        if inner is None:
            raise RuntimeError("cassette recording requires an inner HTTP transport")
        response = await inner.handle_async_request(request)
        body = await response.aread()
        await response.aclose()
        # `aread()` returns *decoded* bytes, so the content-transformation headers no
        # longer describe the body we hold — keeping them would make every consumer
        # (including the re-wrapped response below) try to decompress plain text.
        headers = {
            k: v
            for k, v in response.headers.items()
            if k.lower() not in ("content-encoding", "content-length", "transfer-encoding")
        }
        self._cassette.append(
            Interaction(
                method=request.method,
                url=str(request.url),
                request_body=request.content.decode("utf-8", errors="replace"),
                status=response.status_code,
                headers=headers,
                body=body.decode("utf-8", errors="replace"),
            )
        )
        return httpx2.Response(
            response.status_code, headers=headers, content=body, request=request
        )

    def _replay(self, request: httpx2.Request) -> httpx2.Response:
        interaction = self._match(request)
        if interaction is None:
            raise RuntimeError(
                f"no cassette interaction matches {request.method} {request.url}; "
                f"re-record {self._cassette.path.name}"
            )
        return httpx2.Response(
            interaction.status,
            headers=interaction.headers,
            content=interaction.body.encode(),
            request=request,
        )

    def _match(self, request: httpx2.Request) -> Interaction | None:
        """Match in recorded order, falling back to a path-and-method search.

        Ordered matching keeps multi-turn scenarios (retries, repairs) faithful; the
        fallback keeps a cassette usable when a client reorders independent calls.
        """
        if self._cursor < len(self._cassette.interactions):
            candidate = self._cassette.interactions[self._cursor]
            if candidate.method == request.method and _same_path(candidate.url, request.url):
                self._cursor += 1
                return candidate
        for interaction in self._cassette.interactions:
            if interaction.method == request.method and _same_path(interaction.url, request.url):
                return interaction
        return None


def _same_path(recorded: str, actual: httpx2.URL) -> bool:
    return httpx2.URL(recorded).path == actual.path
