"""Embedding and reranking types: the second and third inference operations.

Generation, embedding, and reranking are three first-class, provider-neutral inference
operations, not variations on one request shape. `GenerationRequest` never grows embedding
or rerank fields — each operation gets its own request and result types, sharing only what
is genuinely operation-neutral (`ResolvedTarget`, `Usage`'s shape, `AttemptRecord`).

Embedding vectors from different models are not interchangeable, even when both calls
succeed and both return plausible numbers. `EmbeddingSpace` exists to make that fact
checkable instead of merely documented — see the routing layer for the fallback guard this
type feeds.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from .requests import DEFAULT_TIMEOUT_S, ResolvedTarget
from .results import AttemptRecord, Timing, Usage

__all__ = [
    "DEFAULT_MAX_DOCUMENTS",
    "DEFAULT_MAX_EMBEDDING_INPUTS",
    "DEFAULT_MAX_EMBEDDING_RESPONSE_BYTES",
    "DEFAULT_MAX_RERANK_RESPONSE_BYTES",
    "BatchFailure",
    "BatchPolicy",
    "EmbeddingCapabilities",
    "EmbeddingInputIntent",
    "EmbeddingRequest",
    "EmbeddingResult",
    "EmbeddingSpace",
    "EmbeddingVector",
    "InferenceOperation",
    "RankedItem",
    "RerankCapabilities",
    "RerankDocument",
    "RerankRequest",
    "RerankResult",
]

InferenceOperation = Literal["generation", "embedding", "rerank"]
"""The inference operations AnyInfer models as first-class primitives."""

EmbeddingInputIntent = Literal["query", "document", "classification", "clustering"]
"""What an embedded text will be used for, when the provider or model distinguishes it.

Several embedding models produce measurably better retrieval when a query and the
documents it will be compared against are embedded with different instructions even though
both pass through the same model. A provider that has no such distinction ignores this
field entirely; one that requires it but received `None` degrades per its own documented
default, recorded as a warning rather than silently substituted.
"""

DEFAULT_MAX_EMBEDDING_INPUTS = 2_048
"""Sanity ceiling on `EmbeddingRequest.inputs` when no verified provider limit exists.

When the resolved target declares no batch limit and the caller supplies no override,
a request up to this size is sent as one call and anything larger is refused locally —
splitting it would require inventing a provider maximum, which AnyInfer never guesses.
"""

DEFAULT_MAX_DOCUMENTS = 1_000
"""Sanity ceiling on `RerankRequest.documents` when no verified provider limit exists.

Same rule as `DEFAULT_MAX_EMBEDDING_INPUTS`: one call up to this size, a local refusal
beyond it, never a guessed split size.
"""

DEFAULT_MAX_EMBEDDING_RESPONSE_BYTES = 64 * 1024 * 1024
"""Cap on one embedding response body.

Float-vector batches dwarf chat responses — 2,048 inputs of 1,536 dimensions is tens of
megabytes of JSON — so embedding requests default to a larger cap than generation's
`DEFAULT_MAX_RESPONSE_BYTES` rather than failing on ordinary batches.
"""

DEFAULT_MAX_RERANK_RESPONSE_BYTES = 8 * 1024 * 1024
"""Cap on one rerank response body.

Rankings are small (indexes and scores) unless document text is echoed back; this covers
`return_documents=True` over large batches with room to spare.
"""


@dataclass(frozen=True, slots=True)
class EmbeddingSpace:
    """Identity of the vector space one embedding call's output lives in.

    Two embedding results are only safely comparable — for storage, search, or a fallback
    retry — when they came from the same space. This is the strongest identity AnyInfer can
    construct from what a provider tells it; it is deliberately not a guess when a provider
    tells us too little.

    Attributes:
        provider_id: The provider that produced the vectors.
        model: The concrete model id, verbatim as resolved (not an alias).
        model_revision: A pinned revision/snapshot identifier, when the provider or catalog
            exposes one; ``None`` when the model string is the only version signal available.
        dimensions: The vector length actually returned.
        input_intent_aware: Whether this model's output depends on the requested
            `EmbeddingInputIntent` — if ``True``, a query embedded without the same intent
            handling as the documents it will be compared against is not safely comparable
            even within the same model.
        normalized: Whether the provider states its vectors are unit-normalized; ``None``
            when undocumented.
        compatibility_id: An application-supplied identifier asserting that this space is
            interchangeable with another sharing the same id. Never inferred by AnyInfer —
            a guessed equivalence is exactly what this type exists to refuse to produce.
            ``None`` means no compatibility claim has been made.
    """

    provider_id: str
    model: str
    model_revision: str | None = None
    dimensions: int | None = None
    input_intent_aware: bool = False
    normalized: bool | None = None
    compatibility_id: str | None = None

    def compatible_with(self, other: EmbeddingSpace) -> bool:
        """Whether a vector from ``other`` may be safely compared with one from this space.

        True only when both spaces carry the same caller-asserted `compatibility_id`, or
        when provider, model, and revision are all identical. Matching dimensions alone is
        not sufficient — two different models can share a dimension count while encoding
        semantically incompatible spaces.
        """
        if self.compatibility_id is not None and self.compatibility_id == other.compatibility_id:
            return True
        return (
            self.provider_id == other.provider_id
            and self.model == other.model
            and self.model_revision == other.model_revision
        )


@dataclass(frozen=True, slots=True)
class EmbeddingCapabilities:
    """What an embedding-capable model can do, sourced only from facts a provider states.

    Every field mirrors the provenance discipline of `ModelCapabilities`: a field this
    provider does not document stays ``None`` rather than becoming a guess.

    Attributes:
        dimensions: The vector length this model produces, when fixed.
        dimension_choices: Alternative dimensions this model supports via provider-native
            dimensionality reduction (e.g. Matryoshka-trained models), when documented.
        max_batch_inputs: Most inputs one request may carry, when the provider states a
            limit.
        max_input_tokens: Largest single input this model accepts, in tokens.
        max_input_bytes: Largest single input this model accepts, in bytes, when the
            provider bounds by bytes rather than tokens.
        input_intents: Which `EmbeddingInputIntent` values this model distinguishes; empty
            when the model does not support the concept at all.
        normalized: Whether output vectors are unit-normalized; ``None`` when undocumented.
    """

    dimensions: int | None = None
    dimension_choices: tuple[int, ...] = ()
    max_batch_inputs: int | None = None
    max_input_tokens: int | None = None
    max_input_bytes: int | None = None
    input_intents: tuple[EmbeddingInputIntent, ...] = ()
    normalized: bool | None = None


@dataclass(frozen=True, slots=True)
class RerankCapabilities:
    """What a reranking-capable model can do, sourced only from facts a provider states.

    Attributes:
        max_documents: Most documents one request may carry, when the provider states a
            limit.
        max_tokens_per_document: Largest single document this model accepts, in tokens.
        max_bytes_per_document: Largest single document this model accepts, in bytes.
        native_top_n: Whether the provider accepts `RerankRequest.top_n` natively rather
            than the core truncating a full ranking locally.
    """

    max_documents: int | None = None
    max_tokens_per_document: int | None = None
    max_bytes_per_document: int | None = None
    native_top_n: bool = False


@dataclass(frozen=True, slots=True)
class EmbeddingVector:
    """One immutable embedding vector, validated on construction.

    Attributes:
        values: The vector's components, in order.
    """

    values: tuple[float, ...]

    def __post_init__(self) -> None:
        """Reject ragged, non-numeric, boolean, or non-finite vector data.

        Raises:
            ValueError: If ``values`` is empty, contains a `bool` (which is a `int`
                subclass in Python and would otherwise pass a numeric check silently), or
                contains a non-finite float (``NaN`` or infinity).
        """
        if not self.values:
            raise ValueError("embedding vector must not be empty")
        for component in self.values:
            if isinstance(component, bool):
                raise ValueError("embedding vector must not contain boolean values")
            if not isinstance(component, (int, float)):
                raise ValueError(
                    f"embedding vector component must be numeric, got {type(component).__name__}"
                )
            if not math.isfinite(component):
                raise ValueError("embedding vector must not contain NaN or infinite values")

    def __len__(self) -> int:
        """Number of dimensions."""
        return len(self.values)


@dataclass(frozen=True, slots=True)
class BatchPolicy:
    """Core-owned policy for splitting a request that exceeds a provider's verified limit.

    Batching is centralized policy, not adapter behavior — providers disagree on maximum
    inputs, documents, tokens, and bytes, and an adapter never decides how to split a
    request; it only ever sees one already-sized wire call.

    Attributes:
        max_concurrency: Most internal batches dispatched concurrently for one request.
        allow_split: Whether the core may split this request across multiple provider
            calls at all. ``False`` means a request exceeding the resolved limit fails
            locally rather than being silently divided.
        rerank_cross_batch: Whether reranking may be split across documents when the
            provider offers no documented globally-comparable batch contract. Off by
            default because concatenating scores from separate rerank calls is not a valid
            global ordering unless the provider says otherwise.
        max_items_override: Caller-supplied ceiling on items per provider call — inputs
            for embedding, documents for reranking. Beats any provider-declared limit;
            useful when a provider misbehaves below its documented maximum, or to enable
            splitting against a target with no verified limit. ``None`` defers to the
            resolved target's verified capability.
    """

    max_concurrency: int = 4
    allow_split: bool = True
    rerank_cross_batch: bool = False
    max_items_override: int | None = None

    def __post_init__(self) -> None:
        """Reject a non-positive concurrency bound or item ceiling.

        Raises:
            ValueError: If ``max_concurrency`` or ``max_items_override`` is less than 1.
        """
        if self.max_concurrency < 1:
            raise ValueError("batch policy max_concurrency must be at least 1")
        if self.max_items_override is not None and self.max_items_override < 1:
            raise ValueError("batch policy max_items_override must be at least 1 when set")


@dataclass(frozen=True, slots=True)
class BatchFailure:
    """One internal batch's outcome, for aggregating a multi-batch attempt.

    Attributes:
        batch_index: Position of this batch among the request's internal batches.
        item_count: Number of inputs/documents this batch carried.
        succeeded: Whether this batch completed without error.
        error: Snapshot of the failure, when ``succeeded`` is ``False``.
    """

    batch_index: int
    item_count: int
    succeeded: bool
    error: str | None = None


@dataclass(frozen=True, slots=True)
class EmbeddingRequest:
    """A request to embed one or more texts into vectors.

    Attributes:
        inputs: Texts to embed, in order. Duplicates are preserved exactly — deduplication
            is never implicit, because it would change reported usage and may change
            provider-side billing or behavior.
        input_type: What the embedded text will be used for, when the target model
            distinguishes it. ``None`` means no intent is asserted.
        dimensions: Requested output dimensionality, for models supporting native
            dimensionality reduction. ``None`` means the model's default.
        expected_space: An `EmbeddingSpace` the caller expects the result to match. When
            set, a successful but incompatible provider response is rejected rather than
            returned, per the cross-space safety rule.
        timeout_s: Per-attempt wall-clock budget; ``None`` means `DEFAULT_TIMEOUT_S`.
        max_response_bytes: Hard cap on one provider response body. Defaults to
            `DEFAULT_MAX_EMBEDDING_RESPONSE_BYTES` — vector batches are far larger than
            chat responses.
        metadata: Caller-supplied, opaque request metadata carried through telemetry.
        provider_options: Escape hatch, namespaced by provider id, passed through verbatim
            to the matching adapter and consulted by no core logic.
        batch: Core-owned batching policy for this request.
        retain_raw: Whether to keep the provider's raw response payload on the result.
        allow_incompatible_fallback: Explicit opt-in permitting fallback to a route target
            that cannot be proven to share the primary target's embedding space. Off by
            default because wrong-space vectors fail silently when compared; a result
            served through this opt-in always carries a warning naming both targets.
    """

    inputs: tuple[str, ...]
    input_type: EmbeddingInputIntent | None = None
    dimensions: int | None = None
    expected_space: EmbeddingSpace | None = None
    timeout_s: float | None = None
    max_response_bytes: int = DEFAULT_MAX_EMBEDDING_RESPONSE_BYTES
    metadata: Mapping[str, str] = field(default_factory=dict)
    provider_options: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    batch: BatchPolicy = BatchPolicy()
    retain_raw: bool = False
    allow_incompatible_fallback: bool = False

    def __post_init__(self) -> None:
        """Reject a request with no inputs.

        Empty input is a local validation error performing no provider call — it is never
        sent, never billed, and never retried.

        Raises:
            ValueError: If ``inputs`` is empty.
        """
        if not self.inputs:
            raise ValueError("embedding request inputs must not be empty")

    @property
    def effective_timeout_s(self) -> float:
        """The timeout that applies, honoring the module default when unset."""
        return DEFAULT_TIMEOUT_S if self.timeout_s is None else self.timeout_s


@dataclass(frozen=True, slots=True)
class EmbeddingResult:
    """The result of one embedding request.

    Attributes:
        vectors: Embedding vectors in the exact order of `EmbeddingRequest.inputs`.
        target: The provider and model that actually produced these vectors.
        space: Identity of the vector space these vectors live in.
        usage: Token/billing accounting, normalized across providers.
        timing: Centrally-measured latency for the winning attempt.
        attempts: The full routing trail, including failed and retried attempts.
        warnings: Non-fatal notices accumulated along the way.
        raw: The provider-native response payload, when the request asked to keep it.
        manifest: The run manifest for this call, or ``None`` when manifests are off.
    """

    vectors: tuple[EmbeddingVector, ...]
    target: ResolvedTarget
    space: EmbeddingSpace
    usage: Usage
    timing: Timing
    attempts: tuple[AttemptRecord, ...] = ()
    warnings: tuple[str, ...] = ()
    raw: Any | None = None
    manifest: Any | None = None


@dataclass(frozen=True, slots=True)
class RerankDocument:
    """One document offered to a rerank request.

    Attributes:
        id: Caller-owned opaque identifier, unique within one request. Never interpreted
            or generated by AnyInfer.
        text: The document text sent to the provider.
        metadata: Caller-owned metadata retained locally; never sent to a provider unless a
            provider option explicitly requests it.
    """

    id: str
    text: str
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RerankRequest:
    """A request to rank documents by relevance to a query.

    Attributes:
        query: The query text every document is scored against.
        documents: Documents to rank, in the caller's original order. Document ids must be
            unique within the request; duplicate text under distinct ids is permitted and
            preserved.
        top_n: Return only the top N ranked items. ``None`` returns every document ranked.
        timeout_s: Per-attempt wall-clock budget; ``None`` means `DEFAULT_TIMEOUT_S`.
        max_response_bytes: Hard cap on one provider response body.
        metadata: Caller-supplied, opaque request metadata carried through telemetry.
        provider_options: Escape hatch, namespaced by provider id.
        batch: Core-owned batching policy for this request.
        return_documents: Whether the result should echo document text back on each
            `RankedItem`. Off by default — the caller already has the text it sent.
        retain_raw: Whether to keep the provider's raw response payload on the result.
    """

    query: str
    documents: tuple[RerankDocument, ...]
    top_n: int | None = None
    timeout_s: float | None = None
    max_response_bytes: int = DEFAULT_MAX_RERANK_RESPONSE_BYTES
    metadata: Mapping[str, str] = field(default_factory=dict)
    provider_options: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    batch: BatchPolicy = BatchPolicy()
    return_documents: bool = False
    retain_raw: bool = False

    def __post_init__(self) -> None:
        """Reject a request with an empty query, no documents, or duplicate document ids.

        Raises:
            ValueError: If ``query`` is blank, ``documents`` is empty, ``top_n`` is not
                positive when set, or two documents share an id.
        """
        if not self.query:
            raise ValueError("rerank request query must not be empty")
        if not self.documents:
            raise ValueError("rerank request documents must not be empty")
        if self.top_n is not None and self.top_n < 1:
            raise ValueError("rerank request top_n must be at least 1 when set")
        seen: set[str] = set()
        for doc in self.documents:
            if doc.id in seen:
                raise ValueError(f"rerank request documents contain duplicate id {doc.id!r}")
            seen.add(doc.id)

    @property
    def effective_timeout_s(self) -> float:
        """The timeout that applies, honoring the module default when unset."""
        return DEFAULT_TIMEOUT_S if self.timeout_s is None else self.timeout_s


@dataclass(frozen=True, slots=True)
class RankedItem:
    """One document's position and score in a rerank result.

    Attributes:
        index: The document's position in `RerankRequest.documents`, preserved so callers
            can recover order or metadata without a lookup.
        document_id: The caller-supplied id of the ranked document.
        score: The provider's relevance score. Finite by construction; meaningful only
            within the result produced by the same target and not comparable across
            different providers or models.
        text: The document's text, present only when the request asked for it.
    """

    index: int
    document_id: str
    score: float
    text: str | None = None

    def __post_init__(self) -> None:
        """Reject a non-finite score, a negative index, or a blank document id.

        Raises:
            ValueError: If ``score`` is ``NaN``/infinite, ``index`` is negative, or
                ``document_id`` is empty.
        """
        if not math.isfinite(self.score):
            raise ValueError("ranked item score must be finite")
        if self.index < 0:
            raise ValueError("ranked item index must not be negative")
        if not self.document_id:
            raise ValueError("ranked item document_id must not be empty")


@dataclass(frozen=True, slots=True)
class RerankResult:
    """The result of one rerank request.

    Attributes:
        items: Ranked documents, ordered by descending relevance (or by whatever order the
            provider certifies as its ranking — always the intended reading order).
        target: The provider and model that actually produced this ranking.
        usage: Token/billing accounting, normalized across providers.
        timing: Centrally-measured latency for the winning attempt.
        attempts: The full routing trail, including failed and retried attempts.
        warnings: Non-fatal notices accumulated along the way.
        raw: The provider-native response payload, when the request asked to keep it.
        manifest: The run manifest for this call, or ``None`` when manifests are off.
    """

    items: tuple[RankedItem, ...]
    target: ResolvedTarget
    usage: Usage
    timing: Timing
    attempts: tuple[AttemptRecord, ...] = ()
    warnings: tuple[str, ...] = ()
    raw: Any | None = None
    manifest: Any | None = None
