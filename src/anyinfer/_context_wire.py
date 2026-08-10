"""Wire-neutral serialization helpers for stateless corpus context requests."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .context.documents import ContextDocument
from .context.settings import ContextTuning
from .context_request import ContextRequest

__all__ = ["decode_context_request", "encode_context_request"]

_FIELD = "anyinfer_context"


def decode_context_request(raw: Any) -> ContextRequest | None:
    """Decode a bounded caller-approved corpus request from a JSON-shaped value."""
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise ValueError(f"{_FIELD} must be an object")
    known = {
        "documents",
        "query",
        "strategy",
        "max_tokens",
        "placement",
        "tuning",
        "max_request_documents",
        "max_request_bytes",
    }
    unknown = set(raw) - known
    if unknown:
        raise ValueError(f"{_FIELD} has unknown key(s): {', '.join(sorted(unknown))}")
    documents = raw.get("documents")
    if not isinstance(documents, list) or not documents:
        raise ValueError(f"{_FIELD}.documents must be a non-empty array")
    decoded: list[ContextDocument] = []
    document_keys = {"path", "content", "pinned", "language", "extract"}
    for index, item in enumerate(documents):
        if not isinstance(item, Mapping):
            raise ValueError(f"{_FIELD}.documents[{index}] must be an object")
        extra = set(item) - document_keys
        if extra:
            raise ValueError(
                f"{_FIELD}.documents[{index}] has unknown key(s): {', '.join(sorted(extra))}"
            )
        path, content = item.get("path"), item.get("content")
        if not isinstance(path, str) or not isinstance(content, str):
            raise ValueError(f"{_FIELD}.documents[{index}] needs string path and content")
        decoded.append(
            ContextDocument.of(
                path,
                content,
                pinned=bool(item.get("pinned", False)),
                language=(str(item["language"]) if item.get("language") else None),
                extract=(str(item["extract"]) if "extract" in item else None),
            )
        )
    tuning_raw = raw.get("tuning", {})
    if not isinstance(tuning_raw, Mapping):
        raise ValueError(f"{_FIELD}.tuning must be an object")
    values = dict(raw)
    values["documents"] = tuple(decoded)
    values["tuning"] = ContextTuning.from_mapping(tuning_raw)
    try:
        return ContextRequest(**values)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{_FIELD} is invalid: {exc}") from exc


def encode_context_request(request: ContextRequest) -> dict[str, Any]:
    """Encode every context request field without performing reduction."""
    return {
        "documents": [
            {
                "path": document.path,
                "content": document.content,
                "pinned": document.pinned,
                "language": document.language,
                "extract": document.extract,
            }
            for document in request.documents
        ],
        "query": request.query,
        "strategy": request.strategy,
        "max_tokens": request.max_tokens,
        "placement": request.placement,
        "tuning": request.tuning.to_mapping(),
        "max_request_documents": request.max_request_documents,
        "max_request_bytes": request.max_request_bytes,
    }
