"""Typed per-request corpus reduction policy and content-free outcome summary.

The records live at the core boundary rather than inside ``anyinfer.context`` so request
and result types can refer to them without importing the reduction implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from .context.documents import ContextDocument
from .context.select import VALID_STRATEGIES
from .context.settings import DEFAULT_TUNING, ContextTuning

if TYPE_CHECKING:
    from .context.select import Reduction

__all__ = [
    "DEFAULT_REQUEST_BYTES",
    "DEFAULT_REQUEST_DOCUMENTS",
    "ContextRequest",
    "ContextSummary",
]

DEFAULT_REQUEST_DOCUMENTS = 1_000
DEFAULT_REQUEST_BYTES = 5 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ContextRequest:
    """Documents explicitly approved by the caller for stateless reduction."""

    documents: tuple[ContextDocument, ...]
    query: str | None = None
    strategy: str = "auto"
    max_tokens: int | None = None
    placement: Literal["system", "prepend_user"] = "system"
    tuning: ContextTuning = DEFAULT_TUNING
    max_request_documents: int = DEFAULT_REQUEST_DOCUMENTS
    max_request_bytes: int = DEFAULT_REQUEST_BYTES

    def __post_init__(self) -> None:
        """Reject inference-spending strategies and oversized request payloads."""
        if not self.documents:
            raise ValueError("context documents must not be empty")
        if self.strategy == "distill":
            raise ValueError("context strategy 'distill' is not allowed per request")
        if self.strategy not in VALID_STRATEGIES:
            raise ValueError(
                f"unknown context strategy {self.strategy!r}; valid strategies are "
                f"{', '.join(VALID_STRATEGIES)}"
            )
        if self.placement not in ("system", "prepend_user"):
            raise ValueError("context placement must be 'system' or 'prepend_user'")
        if self.max_tokens is not None and self.max_tokens < 1:
            raise ValueError("context max_tokens must be positive")
        if self.max_request_documents < 1 or self.max_request_bytes < 1:
            raise ValueError("context request ceilings must be positive")
        if len(self.documents) > self.max_request_documents:
            raise ValueError(
                f"context has {len(self.documents)} documents; the request limit is "
                f"{self.max_request_documents}"
            )
        size = sum(
            len(document.path.encode("utf-8")) + document.bytes_length
            for document in self.documents
        )
        if size > self.max_request_bytes:
            raise ValueError(
                f"context documents occupy {size} bytes; the request limit is "
                f"{self.max_request_bytes}"
            )


@dataclass(frozen=True, slots=True)
class ContextSummary:
    """Content-free account of what corpus reduction sent and omitted."""

    strategy: str
    representation: str
    candidate_count: int
    selected_count: int
    omitted_count: int
    estimated_tokens: int
    complete: bool

    @classmethod
    def from_reduction(cls, reduction: Reduction) -> ContextSummary:
        """Project a full reduction onto the response-safe summary."""
        return cls(
            strategy=reduction.strategy,
            representation=reduction.representation,
            candidate_count=reduction.candidate_count,
            selected_count=len(reduction.documents),
            omitted_count=reduction.omitted_count,
            estimated_tokens=reduction.estimated_tokens,
            complete=reduction.complete,
        )

    def to_dict(self) -> dict[str, object]:
        """Serialize for the sidecar extension."""
        return {
            "strategy": self.strategy,
            "representation": self.representation,
            "candidate_count": self.candidate_count,
            "selected_count": self.selected_count,
            "omitted_count": self.omitted_count,
            "estimated_tokens": self.estimated_tokens,
            "complete": self.complete,
        }
