"""Declarative fake providers for embedding and reranking, on the same terms as `ScriptedProvider`.

`EmbedsText`/`ReranksText` are plain in-process async methods, not an HTTP dialect, so these
fakes implement the protocols directly rather than going through an `httpx2` mock transport
— there is no wire shape to reproduce. Behaviour still lives in a declarative table, exactly
as `ScriptedProvider` does for generation, so a test reads as a description of what the
provider does rather than a sequence of mock-patching steps.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from ..errors import ProviderError, RateLimitError, TransportError
from ..providers.base import (
    EmbeddingWireRequest,
    EmbeddingWireResult,
    RerankWireRequest,
    RerankWireResult,
    WireRankedItem,
)
from ..registry import ProviderDescriptor, ProviderRegistry, ProviderSetupSpec, SetupField
from ..types.capabilities import DiscoveredModel, Health, ModelCapabilities, Pricing, Sourced
from ..types.operations import EmbeddingCapabilities, InferenceOperation, RerankCapabilities
from ..types.results import Usage

__all__ = [
    "FakeEmbeddingRerankProvider",
    "ScriptedEmbeddingFailure",
]

_EmbeddingFailureKind = Literal["status", "rate-limit", "transport"]


@dataclass(frozen=True, slots=True)
class ScriptedEmbeddingFailure:
    """One scripted failure, consumed by the next call to the model it is attached to.

    Attributes:
        kind: ``"status"`` raises a generic retryable `ProviderError`; ``"rate-limit"``
            raises `RateLimitError` with ``retry_after_s``; ``"transport"`` raises
            `TransportError`.
        retry_after_s: Advertised retry delay for a ``rate-limit`` failure.
        message: Error text reported. Test data only.
    """

    kind: _EmbeddingFailureKind = "status"
    retry_after_s: float | None = None
    message: str = "scripted failure"


def _deterministic_vector(text: str, dimensions: int) -> tuple[float, ...]:
    """A small, fully deterministic pseudo-embedding, so tests can assert on values.

    Not a real embedding model — two different texts reliably produce different vectors
    (hashed), and the same text always reproduces the same vector, which is exactly what
    tests need and nothing a random vector would guarantee.
    """
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    values = []
    for i in range(dimensions):
        byte = digest[i % len(digest)]
        values.append((byte / 255.0) * 2.0 - 1.0)
    norm = math.sqrt(sum(v * v for v in values)) or 1.0
    return tuple(v / norm for v in values)


def _lexical_overlap_score(query: str, text: str) -> float:
    """A small deterministic relevance score: fraction of query words present in text."""
    query_words = set(query.lower().split())
    if not query_words:
        return 0.0
    text_words = set(text.lower().split())
    overlap = len(query_words & text_words)
    return overlap / len(query_words)


class FakeEmbeddingRerankProvider:
    """An in-process fake supporting `EmbedsText` and `ReranksText`, or both.

    Args:
        provider_id: Id to register under, and the left half of every target it serves.
        embedding_dimensions: Vector length `embed()` produces, keyed by model id. A model
            id absent here does not embed.
        rerank_models: Model ids that support reranking. A model id absent here does not
            rerank.
        embedding_failures: Failures consumed in order before any success, keyed by model
            id.
        normalized: Whether vectors this provider produces are reported as unit-normalized.
        locality: Recorded on the descriptor.
        embedding_capabilities: Static `EmbeddingCapabilities` recorded on the descriptor,
            keyed by model id — the way tests declare a verified batch limit
            (``max_batch_inputs``) for core-owned batching to resolve.
        rerank_capabilities: Static `RerankCapabilities` recorded on the descriptor,
            keyed by model id (``max_documents`` drives rerank batching).
        pricing: Trusted per-model pricing recorded on the descriptor (provenance
            ``"catalog"``), so cost computation and spend ceilings can be tested offline.

    Attributes:
        embed_requests: Every `EmbeddingWireRequest` received, oldest first.
        rerank_requests: Every `RerankWireRequest` received, oldest first.
    """

    def __init__(
        self,
        provider_id: str = "fake-embed",
        *,
        embedding_dimensions: Mapping[str, int] | None = None,
        rerank_models: Sequence[str] = (),
        embedding_failures: Mapping[str, Sequence[ScriptedEmbeddingFailure]] | None = None,
        normalized: bool = True,
        locality: Literal["hosted", "local", "remote"] = "local",
        embedding_capabilities: Mapping[str, EmbeddingCapabilities] | None = None,
        rerank_capabilities: Mapping[str, RerankCapabilities] | None = None,
        pricing: Mapping[str, Pricing] | None = None,
    ) -> None:
        self.provider_id = provider_id
        self._embedding_dimensions = dict(embedding_dimensions or {"fake-embed-small": 8})
        self._rerank_models = set(rerank_models)
        self._normalized = normalized
        self._locality = locality
        self._embedding_capabilities = dict(embedding_capabilities or {})
        self._rerank_capabilities = dict(rerank_capabilities or {})
        self._pricing = dict(pricing or {})
        self._failures: dict[str, list[ScriptedEmbeddingFailure]] = {
            model: list(failures) for model, failures in (embedding_failures or {}).items()
        }
        self.embed_requests: list[EmbeddingWireRequest] = []
        self.rerank_requests: list[RerankWireRequest] = []

    def operations(self) -> frozenset[InferenceOperation]:
        """Which operations this provider declares, for building its descriptor."""
        ops: set[InferenceOperation] = set()
        if self._embedding_dimensions:
            ops.add("embedding")
        if self._rerank_models:
            ops.add("rerank")
        return frozenset(ops)

    def descriptor(self) -> ProviderDescriptor:
        """The declarative descriptor this provider registers."""
        return ProviderDescriptor(
            id=self.provider_id,
            display_name=f"Fake ({self.provider_id})",
            factory=lambda _config: self,
            locality=self._locality,
            default_base_url="http://fake-embed.invalid",
            setup=ProviderSetupSpec(
                fields=(
                    SetupField(
                        key="base_url",
                        label="Base URL",
                        kind="endpoint",
                        advanced=True,
                        default_value="http://fake-embed.invalid",
                        help_text="Ignored — this provider never opens a socket.",
                    ),
                ),
            ),
            operations=self.operations(),
            static_embedding_capabilities=self._embedding_capabilities,
            static_rerank_capabilities=self._rerank_capabilities,
            static_capabilities={
                model: ModelCapabilities(pricing=Sourced(price, "catalog"))
                for model, price in self._pricing.items()
            },
        )

    def register(self, registry: ProviderRegistry) -> ProviderRegistry:
        """Register this provider's descriptor, replacing any earlier registration."""
        registry.register(self.descriptor(), replace=True)
        return registry

    # ---- ProviderLifecycle ------------------------------------------------------------

    async def list_models(self) -> Sequence[DiscoveredModel]:
        """Enumerate the models this fake serves."""
        ids = set(self._embedding_dimensions) | self._rerank_models
        return tuple(DiscoveredModel(id=model_id) for model_id in sorted(ids))

    async def health(self) -> Health:
        """Always healthy — this fake never simulates transport-level outages at health time."""
        return Health(ok=True)

    async def aclose(self) -> None:
        """No resources to release."""
        return None

    # ---- EmbedsText ---------------------------------------------------------------------

    async def embed(self, req: EmbeddingWireRequest) -> EmbeddingWireResult:
        """Return deterministic pseudo-embeddings, or raise a scripted failure."""
        self.embed_requests.append(req)
        self._maybe_fail(req.model)
        dimensions = req.dimensions or self._embedding_dimensions.get(req.model, 8)
        vectors = tuple(_deterministic_vector(text, dimensions) for text in req.inputs)
        usage = Usage(input_tokens=sum(len(t.split()) for t in req.inputs))
        return EmbeddingWireResult(
            vectors=vectors,
            model=req.model,
            dimensions=dimensions,
            normalized=self._normalized,
            usage=usage,
        )

    # ---- ReranksText --------------------------------------------------------------------

    async def rerank(self, req: RerankWireRequest) -> RerankWireResult:
        """Return documents ranked by deterministic lexical overlap with the query."""
        self.rerank_requests.append(req)
        scored = [
            WireRankedItem(index=doc.index, score=_lexical_overlap_score(req.query, doc.text))
            for doc in req.documents
        ]
        scored.sort(key=lambda item: item.score, reverse=True)
        if req.top_n is not None:
            scored = scored[: req.top_n]
        usage = Usage(input_tokens=sum(len(d.text.split()) for d in req.documents))
        return RerankWireResult(items=tuple(scored), model=req.model, usage=usage)

    # ---- scripting ------------------------------------------------------------------

    def _maybe_fail(self, model: str) -> None:
        queue = self._failures.get(model)
        if not queue:
            return
        failure = queue.pop(0)
        raise _build_error(failure)


def _build_error(failure: ScriptedEmbeddingFailure) -> ProviderError:
    if failure.kind == "rate-limit":
        return RateLimitError(failure.message, retry_after_s=failure.retry_after_s)
    if failure.kind == "transport":
        return TransportError(failure.message)
    return ProviderError(failure.message, retryable=True, retry_after_s=failure.retry_after_s)
