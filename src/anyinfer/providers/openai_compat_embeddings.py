"""The shared OpenAI-compatible `/v1/embeddings` dialect.

A separate module from `openai_compat.py`, not a subclass of `OpenAICompatAdapter` — the
plan is explicit that this lives *alongside*, not inside, the chat-completions codec, since
an endpoint that speaks OpenAI-compatible chat completions does not automatically speak
OpenAI-compatible embeddings, and a preset must opt in to each separately rather than
inheriting embedding support merely because its chat endpoint is compatible.

Wire shape verified against OpenAI's public embeddings reference
(https://platform.openai.com/docs/api-reference/embeddings), 2026-08-11: request carries
``model``, ``input`` (string or array of strings — token-array input is not modeled),
optional ``dimensions``, optional ``encoding_format`` (``"float"`` default, or
``"base64"``); response carries ``data: [{embedding, index}]``, ``model``, and
``usage: {prompt_tokens, total_tokens}``.
"""

from __future__ import annotations

import base64
import struct
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

import httpx2

from ..errors import ProviderError
from ..types.results import Usage
from .base import EmbeddingWireRequest, EmbeddingWireResult
from .http import map_transport_error

if TYPE_CHECKING:
    from typing import Protocol

    class _EmbeddingsHost(Protocol):
        """The attributes a host adapter must provide; checked only by the type checker.

        `OpenAICompatEmbeddingsMixin` does not inherit this — inheriting it would give the
        mixin its own (unimplemented) copies of these members, which shadow the real ones
        the host class defines when the mixin is listed first in an MRO. Declaring it only
        as the annotated type of ``self`` gets the same static checking without that
        runtime hazard.
        """

        provider_id: str
        _client: httpx2.AsyncClient

        def _classify(
            self, status: int, detail: str, headers: Mapping[str, str], phase: str = "generate"
        ) -> ProviderError: ...

__all__ = ["OpenAICompatEmbeddingsMixin", "decode_embedding_value"]


def decode_embedding_value(value: Any) -> tuple[float, ...]:
    """Decode one embedding as OpenAI's dialect may have encoded it.

    ``encoding_format="float"`` (the default) returns a plain JSON array of numbers.
    ``encoding_format="base64"`` returns a base64 string of packed little-endian float32
    values — verified against the OpenAI embeddings reference, 2026-08-11.

    Raises:
        anyinfer.errors.ProviderError: The value is neither a numeric array nor a
            base64-decodable string of a whole number of float32 values.
    """
    if isinstance(value, list):
        return tuple(float(v) for v in value)
    if isinstance(value, str):
        try:
            raw = base64.b64decode(value, validate=True)
        except Exception as exc:
            raise ProviderError(
                f"embedding value is not valid base64: {exc}", phase="validate"
            ) from exc
        if len(raw) % 4 != 0:
            raise ProviderError(
                "base64-decoded embedding is not a whole number of float32 values",
                phase="validate",
            )
        count = len(raw) // 4
        return struct.unpack(f"<{count}f", raw)
    raise ProviderError(
        f"embedding value has unsupported type {type(value).__name__}", phase="validate"
    )


class OpenAICompatEmbeddingsMixin:
    """`EmbedsText` support for any adapter built on the OpenAI-compatible transport.

    Composed into an adapter class alongside `OpenAICompatAdapter`; expects the host class
    to provide ``self._client`` (an `httpx2.AsyncClient` already pointed at the right base
    URL), ``self.provider_id``, and ``self._classify`` for error mapping — the same
    attributes `OpenAICompatAdapter` already sets up. This mixin declares none of them
    itself, so it never shadows the host class's real implementations regardless of MRO
    order.
    """

    embeddings_path = "/embeddings"
    """Path relative to the client's base URL. Overridden by dialects that nest it
    differently (a preset with a non-standard mount point)."""

    async def embed(self, req: EmbeddingWireRequest) -> EmbeddingWireResult:
        """Run one embedding call against ``POST {base}/embeddings``."""
        host: _EmbeddingsHost = self  # type: ignore[assignment]
        payload = self._build_embedding_payload(req)
        try:
            response = await host._client.post(
                self.embeddings_path, json=payload, timeout=req.timeout_s
            )
        except httpx2.HTTPError as exc:
            raise map_transport_error(exc, provider=host.provider_id, phase="generate") from exc
        if response.status_code >= 400:
            from .http import read_error_detail

            raise host._classify(
                response.status_code,
                read_error_detail(response.content),
                response.headers,
                "generate",
            )
        return self._parse_embedding_response(req, response.json())

    def _build_embedding_payload(self, req: EmbeddingWireRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": req.model,
            "input": list(req.inputs) if len(req.inputs) != 1 else req.inputs[0],
        }
        if req.dimensions is not None:
            payload["dimensions"] = req.dimensions
        payload.update(req.extra_options)
        return payload

    def _parse_embedding_response(
        self, req: EmbeddingWireRequest, payload: Any
    ) -> EmbeddingWireResult:
        if not isinstance(payload, Mapping):
            raise ProviderError("embeddings response is not a JSON object", phase="validate")
        data = payload.get("data")
        if not isinstance(data, Sequence) or isinstance(data, (str, bytes)):
            raise ProviderError(
                "embeddings response is missing a 'data' array", phase="validate"
            )
        by_index: dict[int, tuple[float, ...]] = {}
        for entry in data:
            if not isinstance(entry, Mapping):
                continue
            index = entry.get("index")
            embedding = entry.get("embedding")
            if not isinstance(index, int) or embedding is None:
                continue
            by_index[index] = decode_embedding_value(embedding)
        try:
            vectors = tuple(by_index[i] for i in range(len(req.inputs)))
        except KeyError as exc:
            raise ProviderError(
                f"embeddings response is missing vector(s) for input index {exc}",
                phase="validate",
            ) from exc

        model = payload.get("model")
        usage_block = payload.get("usage")
        usage = None
        if isinstance(usage_block, Mapping):
            prompt_tokens = usage_block.get("prompt_tokens")
            total_tokens = usage_block.get("total_tokens")
            usage = Usage(
                input_tokens=prompt_tokens if isinstance(prompt_tokens, int) else None,
                total_tokens=total_tokens if isinstance(total_tokens, int) else None,
            ).normalized()

        return EmbeddingWireResult(
            vectors=vectors,
            model=model if isinstance(model, str) else None,
            dimensions=len(vectors[0]) if vectors else None,
            usage=usage,
            raw=payload,
        )
