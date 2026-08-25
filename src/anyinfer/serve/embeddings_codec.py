"""Wire codecs for ``POST /v1/embeddings`` and ``POST /v1/anyinfer/rerank``.

Kept alongside, not inside, `openai_codec.py`: an OpenAI-compatible chat-completions
request body has nothing in common with an embeddings or rerank request, and there is no
established OpenAI-shaped wire dialect for reranking to emulate at all. Both codecs are
pure encode/decode functions with no client, routing, or validation logic of their own —
the sidecar app wires them to `AsyncClient.embed`/`AsyncClient.rerank`.
"""

from __future__ import annotations

import base64
import struct
import time
from collections.abc import Mapping, Sequence
from typing import Any

from ..types.operations import EmbeddingResult, RerankResult
from .openai_codec import MANIFEST_FIELD

__all__ = [
    "embedding_request_from_openai",
    "embeddings_response",
    "rerank_request_from_body",
    "rerank_response",
]


def embedding_request_from_openai(
    body: Mapping[str, Any],
) -> tuple[str, list[str], dict[str, Any], str]:
    """Decode an OpenAI-compatible ``POST /v1/embeddings`` request body.

    Args:
        body: The parsed request JSON.

    Returns:
        A ``(target, inputs, kwargs, encoding_format)`` tuple. ``target`` is the ``model``
        field verbatim, the same target-in-model-string convention chat completions uses.
        ``kwargs`` holds the optional fields ready to splice into `AsyncClient.embed`.
        ``encoding_format`` is ``"float"`` or ``"base64"``, for `embeddings_response` to
        apply on the way out — it is a wire-encoding choice, so it never reaches the
        client call.

    Raises:
        ValueError: ``model`` is missing, ``input`` is not a string or array of strings,
            or ``encoding_format`` is neither ``"float"`` nor ``"base64"``.
    """
    target = str(body.get("model", "")).strip()
    if not target:
        raise ValueError("the 'model' field is required")

    raw_input = body.get("input")
    if isinstance(raw_input, str):
        inputs = [raw_input]
    elif isinstance(raw_input, list) and all(isinstance(item, str) for item in raw_input):
        inputs = list(raw_input)
    else:
        raise ValueError("'input' must be a string or an array of strings")
    if not inputs:
        raise ValueError("'input' must not be empty")

    kwargs: dict[str, Any] = {}
    dimensions = body.get("dimensions")
    if isinstance(dimensions, int):
        kwargs["dimensions"] = dimensions

    # base64 is the official `openai` Python client's default, so refusing it broke the
    # most common stock client against an endpoint whose reason to exist is stock-client
    # compatibility. EmbeddingResult still carries plain floats — re-encoding at the wire
    # is exactly this codec's job, so it happens here and never reaches the client call.
    encoding_format = body.get("encoding_format")
    if encoding_format is None:
        encoding_format = "float"
    if encoding_format not in ("float", "base64"):
        raise ValueError("encoding_format must be 'float' or 'base64'")

    return target, inputs, kwargs, str(encoding_format)


def _pack_base64(values: Sequence[float]) -> str:
    """Pack a vector as OpenAI does: little-endian float32, base64-encoded."""
    return base64.b64encode(struct.pack(f"<{len(values)}f", *values)).decode("ascii")


def embeddings_response(
    result: EmbeddingResult,
    *,
    model: str,
    include_manifest: bool = False,
    encoding_format: str = "float",
) -> dict[str, Any]:
    """Render an `EmbeddingResult` as an OpenAI-compatible ``list`` object.

    Args:
        result: The embedding result to render.
        model: The ``model`` string to echo back.
        include_manifest: Attach the run manifest under `MANIFEST_FIELD` — opt-in, so a
            stock OpenAI client's response shape never changes (see `wants_manifest`).
        encoding_format: ``"float"`` for a JSON array, or ``"base64"`` for OpenAI's
            packed little-endian float32 string. Comes from the request via
            `embedding_request_from_openai`.
    """
    as_base64 = encoding_format == "base64"
    body: dict[str, Any] = {
        "object": "list",
        "data": [
            {
                "object": "embedding",
                "index": i,
                "embedding": (
                    _pack_base64(vector.values) if as_base64 else list(vector.values)
                ),
            }
            for i, vector in enumerate(result.vectors)
        ],
        "model": model,
        "usage": {
            "prompt_tokens": result.usage.input_tokens or 0,
            "total_tokens": result.usage.total_tokens or result.usage.input_tokens or 0,
        },
    }
    if include_manifest and result.manifest is not None:
        body[MANIFEST_FIELD] = result.manifest.to_dict()
    return body


def rerank_request_from_body(
    body: Mapping[str, Any],
) -> tuple[str, str, list[tuple[str, str]], dict[str, Any]]:
    """Decode a ``POST /v1/anyinfer/rerank`` request body.

    Args:
        body: The parsed request JSON: ``{"model", "query", "documents", "top_n"?,
            "return_documents"?}``. Each entry in ``documents`` is either a plain string
            (assigned an id by position) or ``{"id", "text"}``.

    Returns:
        A ``(target, query, documents, kwargs)`` tuple, where ``documents`` is a list of
        ``(id, text)`` pairs in request order.

    Raises:
        ValueError: ``model``/``query`` are missing, or ``documents`` is empty or malformed.
    """
    target = str(body.get("model", "")).strip()
    if not target:
        raise ValueError("the 'model' field is required")

    query = body.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ValueError("the 'query' field is required")

    raw_documents = body.get("documents")
    if not isinstance(raw_documents, list) or not raw_documents:
        raise ValueError("'documents' must be a non-empty array")

    documents: list[tuple[str, str]] = []
    for i, entry in enumerate(raw_documents):
        if isinstance(entry, str):
            documents.append((str(i), entry))
        elif isinstance(entry, Mapping) and isinstance(entry.get("text"), str):
            doc_id = entry.get("id")
            documents.append((str(doc_id) if doc_id is not None else str(i), entry["text"]))
        else:
            raise ValueError(
                f"document at index {i} must be a string or an object with a 'text' field"
            )

    kwargs: dict[str, Any] = {}
    top_n = body.get("top_n")
    if isinstance(top_n, int):
        kwargs["top_n"] = top_n
    if body.get("return_documents") is True:
        kwargs["return_documents"] = True

    return target, query, documents, kwargs


def rerank_response(
    result: RerankResult, *, model: str, include_manifest: bool = False
) -> dict[str, Any]:
    """Render a `RerankResult` as the AnyInfer-native rerank response shape.

    Args:
        result: The rerank result to render.
        model: The ``model`` string to echo back.
        include_manifest: Attach the run manifest under `MANIFEST_FIELD` — opt-in, same
            discipline as `embeddings_response`.
    """
    body: dict[str, Any] = {
        "object": "anyinfer.rerank",
        "model": model,
        "results": [
            {
                "index": item.index,
                "document_id": item.document_id,
                "relevance_score": item.score,
                **({"document": {"text": item.text}} if item.text is not None else {}),
            }
            for item in result.items
        ],
        "usage": {
            "prompt_tokens": result.usage.input_tokens or 0,
            "total_tokens": result.usage.total_tokens or result.usage.input_tokens or 0,
        },
        "created": int(time.time()),
    }
    if include_manifest and result.manifest is not None:
        body[MANIFEST_FIELD] = result.manifest.to_dict()
    return body
