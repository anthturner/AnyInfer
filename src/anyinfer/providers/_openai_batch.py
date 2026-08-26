"""The OpenAI Batch API lifecycle, shared by every dialect that speaks it.

OpenAI's batch tier is a three-step dance where Anthropic's is one step: a JSONL job is
uploaded to ``/files``, a batch is created referencing that file id, and the answers come
back as *two* more files to download — one for the lines that succeeded and one for the
lines that did not. The dance is identical for every provider that copied the API, so it
lives here once rather than in each adapter.

What differs between dialects is exactly two things, and they are the two hooks below: the
endpoint each line targets (`batch_endpoint`), and how one answered line's body becomes a
`Generation` (`generation_from_batch_body`). A provider serving the Responses API and one
serving chat completions differ in those and nothing else.

The endpoint is written with its version prefix (``/v1/responses``), which is *not* the
same string the adapter posts a live request to (``/responses``, resolved against a base
URL that already carries the version). The batch API validates this field against a fixed
list of absolute paths, so borrowing the live path silently fails validation at submit.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterable, Mapping
from typing import Any, ClassVar, Protocol

import httpx2

from ..errors import ProviderError, StreamProtocolError
from ..types.operations import (
    BatchHandle,
    BatchLine,
    BatchReport,
    BatchResult,
    BatchStatus,
)
from ..types.results import DETAIL_MAX_CHARS, ErrorInfo, Generation
from .base import BatchWireRequest, WireRequest
from .http import map_transport_error, read_error_detail

__all__ = ["BATCH_STATUSES", "OpenAIBatchMixin", "batch_error", "line_failure"]


class _BatchHost(Protocol):
    """What the mixin needs from the adapter it is mixed into."""

    provider_id: str

    def build_payload(self, req: WireRequest) -> dict[str, Any]: ...


class OpenAIBatchMixin:
    """`SubmitsBatches` for any adapter speaking the OpenAI Batch API.

    Mixed in beside the adapter's own generation code; it reuses that adapter's HTTP
    client, error classifier, and — importantly — its `build_payload`, so a batched line
    is serialized by the same code a live request is. A second serializer for the batch
    path is the classic way for the two to drift.
    """

    batch_endpoint: ClassVar[str] = "/v1/chat/completions"
    """The absolute path each line targets, version prefix included."""

    default_completion_window: ClassVar[str] = "24h"
    """Used when the caller names none. The only window OpenAI documents."""

    def generation_from_batch_body(self, body: Mapping[str, Any]) -> Generation:
        """Assemble one answered line's `Generation` from its response body.

        Raises:
            NotImplementedError: The dialect did not supply a reader.
        """
        raise NotImplementedError

    # ---- submit ------------------------------------------------------------------------

    async def submit_batch(self, req: BatchWireRequest) -> BatchHandle:
        """Upload the job as a JSONL file, then submit a batch referencing it.

        Raises:
            anyinfer.errors.ProviderError: The upload or the submission was refused.
        """
        jsonl = "\n".join(
            json.dumps(
                {
                    "custom_id": custom_id,
                    "method": "POST",
                    "url": self.batch_endpoint,
                    "body": self._batch_body(line),
                }
            )
            for custom_id, line in req.lines
        )
        file_id = await self._upload_batch_input(jsonl)

        payload: dict[str, Any] = {
            "input_file_id": file_id,
            "endpoint": self.batch_endpoint,
            "completion_window": req.completion_window or self.default_completion_window,
        }
        if req.metadata:
            payload["metadata"] = dict(req.metadata)
        body = await self._batch_call("POST", "/batches", json=payload)
        return BatchHandle(
            batch_id=str(body.get("id", "")),
            provider_id=self.provider_id,  # type: ignore[attr-defined]
            model=req.model,
            line_count=len(req.lines),
            submitted_at=time.time(),
            line_ids=tuple(custom_id for custom_id, _ in req.lines),
        )

    def _batch_body(self, line: WireRequest) -> dict[str, Any]:
        """One line's request body: the live shape, with streaming removed.

        A batch is answered whole, so `stream` is meaningless and the API rejects it.
        Everything else is identical, which is the point of reusing `build_payload`.
        """
        body: dict[str, Any] = self.build_payload(line)  # type: ignore[attr-defined]
        body.pop("stream", None)
        body.pop("stream_options", None)
        return body

    async def _upload_batch_input(self, jsonl: str) -> str:
        """Upload the job to ``POST /files`` with ``purpose=batch``.

        Raises:
            anyinfer.errors.ProviderError: The upload failed, or returned no file id.
        """
        try:
            response = await self._client.post(  # type: ignore[attr-defined]
                "/files",
                files={"file": ("batch.jsonl", jsonl.encode("utf-8"), "application/jsonl")},
                data={"purpose": "batch"},
            )
        except httpx2.HTTPError as exc:
            raise map_transport_error(
                exc,
                provider=self.provider_id,  # type: ignore[attr-defined]
                phase="generate",
            ) from exc
        if response.status_code >= 400:
            raise self._classify(  # type: ignore[attr-defined]
                response.status_code, read_error_detail(response.content), response.headers
            )
        body = response.json()
        file_id = body.get("id") if isinstance(body, Mapping) else None
        if not isinstance(file_id, str) or not file_id:
            raise StreamProtocolError(
                "the batch input upload returned no file id",
                provider=self.provider_id,  # type: ignore[attr-defined]
            )
        return file_id

    # ---- poll and cancel ---------------------------------------------------------------

    async def batch_status(self, handle: BatchHandle) -> BatchReport:
        """Report state from ``GET /batches/{id}``."""
        return self._report(handle, await self._batch_call("GET", f"/batches/{handle.batch_id}"))

    async def cancel_batch(self, handle: BatchHandle) -> BatchReport:
        """Ask the provider to cancel, via ``POST /batches/{id}/cancel``."""
        body = await self._batch_call("POST", f"/batches/{handle.batch_id}/cancel")
        return self._report(handle, body)

    def _report(self, handle: BatchHandle, body: Mapping[str, Any]) -> BatchReport:
        """Normalize one batch object into a report."""
        counts = body.get("request_counts")
        counts = counts if isinstance(counts, Mapping) else {}
        errors = body.get("errors")
        detail = ""
        if isinstance(errors, Mapping):
            data = errors.get("data")
            if isinstance(data, list) and data and isinstance(data[0], Mapping):
                detail = str(data[0].get("message", ""))[:DETAIL_MAX_CHARS]
        return BatchReport(
            handle=handle,
            status=BATCH_STATUSES.get(str(body.get("status", "")), "in_progress"),
            completed=int(counts.get("completed", 0) or 0),
            failed=int(counts.get("failed", 0) or 0),
            detail=detail,
        )

    # ---- fetch -------------------------------------------------------------------------

    async def fetch_batch(self, handle: BatchHandle) -> BatchResult:
        """Download the output files and parse their lines.

        Raises:
            anyinfer.errors.ProviderError: The batch has not finished, or the download
                failed. Refused rather than returning an empty result, which a caller
                would read as "every line failed".
        """
        body = await self._batch_call("GET", f"/batches/{handle.batch_id}")
        report = self._report(handle, body)
        if not report.finished:
            raise ProviderError(
                f"batch {handle.batch_id} is {report.status}, not finished",
                provider=self.provider_id,  # type: ignore[attr-defined]
                retryable=True,
                hint="poll batch_status until it reports finished",
            )

        lines: list[BatchLine] = []
        # Two files, not one: successful lines land in `output_file_id` and rejected ones
        # in `error_file_id`. Reading only the first would silently drop every failure and
        # return a batch that looks smaller than it was.
        for field, ok in (("output_file_id", True), ("error_file_id", False)):
            file_id = body.get(field)
            if isinstance(file_id, str) and file_id:
                lines.extend(self._parse_lines(await self._download_file(file_id), ok=ok))
        return BatchResult(handle=handle, status=report.status, lines=tuple(lines))

    async def _download_file(self, file_id: str) -> str:
        """Fetch one result file's content.

        Raises:
            anyinfer.errors.ProviderError: The download failed.
        """
        try:
            response = await self._client.get(f"/files/{file_id}/content")  # type: ignore[attr-defined]
        except httpx2.HTTPError as exc:
            raise map_transport_error(
                exc,
                provider=self.provider_id,  # type: ignore[attr-defined]
                phase="generate",
            ) from exc
        if response.status_code >= 400:
            raise self._classify(  # type: ignore[attr-defined]
                response.status_code, read_error_detail(response.content), response.headers
            )
        return str(response.text)

    def _parse_lines(self, jsonl: str, *, ok: bool) -> Iterable[BatchLine]:
        """Parse one manifest file, one entry per submitted request."""
        for raw in jsonl.splitlines():
            if not raw.strip():
                continue
            try:
                entry = json.loads(raw)
            except ValueError:
                continue
            if isinstance(entry, Mapping):
                yield self._parse_line(entry, ok=ok)

    def _parse_line(self, entry: Mapping[str, Any], *, ok: bool) -> BatchLine:
        """Turn one manifest entry into a line.

        A successful entry's `response.body` is byte-identical to a non-streaming body of
        the same dialect, so it is read by the same reader a live call uses — which is what
        makes a batched answer carry the tool calls, usage, and finish reason a live one
        would.
        """
        custom_id = str(entry.get("custom_id", ""))
        response = entry.get("response")
        status = response.get("status_code") if isinstance(response, Mapping) else None
        body = response.get("body") if isinstance(response, Mapping) else None

        if not ok or (isinstance(status, int) and status >= 400) or not isinstance(body, Mapping):
            return BatchLine(
                custom_id=custom_id,
                error=batch_error(
                    self.provider_id,  # type: ignore[attr-defined]
                    line_failure(entry, body),
                ),
            )
        return BatchLine(custom_id=custom_id, result=self.generation_from_batch_body(body))

    async def _batch_call(
        self, method: str, path: str, *, json: Any = None
    ) -> Mapping[str, Any]:
        """Issue one batch-control request, classifying failures the usual way.

        Raises:
            anyinfer.errors.ProviderError: The call failed or returned a non-object body.
        """
        try:
            response = await self._client.request(method, path, json=json)  # type: ignore[attr-defined]
        except httpx2.HTTPError as exc:
            raise map_transport_error(
                exc,
                provider=self.provider_id,  # type: ignore[attr-defined]
                phase="generate",
            ) from exc
        if response.status_code >= 400:
            raise self._classify(  # type: ignore[attr-defined]
                response.status_code, read_error_detail(response.content), response.headers
            )
        body = response.json()
        if not isinstance(body, Mapping):
            raise StreamProtocolError(
                "the provider returned a non-object batch body",
                provider=self.provider_id,  # type: ignore[attr-defined]
            )
        return body


BATCH_STATUSES: Mapping[str, BatchStatus] = {
    "validating": "queued",
    "in_progress": "in_progress",
    "finalizing": "in_progress",
    "completed": "completed",
    "failed": "failed",
    "expired": "expired",
    "cancelling": "in_progress",
    "cancelled": "cancelled",
}
"""OpenAI's batch states, normalized. Richer than Anthropic's two, and mapped rather than
passed through so a caller polls one vocabulary whichever provider ran the job."""


def batch_error(provider_id: str, detail: str) -> ErrorInfo:
    """Record one line's failure without inventing a status code for it."""
    return ErrorInfo(
        type_name="ProviderError",
        provider=provider_id,
        phase="generate",
        retryable=False,
        http_status=None,
        detail=detail[:DETAIL_MAX_CHARS],
    )


def line_failure(entry: Mapping[str, Any], body: Any) -> str:
    """Extract the most specific failure message a manifest entry offers.

    Three places can carry it — the entry's own `error`, the response body's `error`, or
    nothing at all — because the two manifest files use different shapes for the same
    fact.
    """
    body_error = body.get("error") if isinstance(body, Mapping) else None
    for candidate in (entry.get("error"), body_error):
        if isinstance(candidate, Mapping):
            message = candidate.get("message") or candidate.get("code")
            if message:
                return str(message)
        elif isinstance(candidate, str) and candidate:
            return candidate
    return "the provider rejected this line without a message"
