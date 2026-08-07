"""Corpus selection: the strategies, the result type, and the dispatch rule.

Reduction is *emulation of a larger context window*, and emulation announces itself. Every
reduction returns what it kept, what it dropped, which ceiling bound it, and a
content-free summary — plus a `ContextReduced` telemetry event when an observer is
supplied. A silent truncation that looks like a complete answer is the failure mode this
module exists to prevent.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from ..capabilities.estimate import HeuristicTokenEstimator, TokenEstimator
from ..events.observers import Observer
from ..events.telemetry import ContextReduced
from .documents import ContextDocument, RankCache
from .envelope import block_bytes, render_corpus, render_file_block, wrapper_bytes
from .rank import rank

__all__ = [
    "DEFAULT_MAX_BYTES",
    "DEFAULT_MAX_DOCUMENTS",
    "VALID_STRATEGIES",
    "Reduction",
    "RenderOrder",
    "Strategy",
    "normalize_strategy",
    "select",
]

DEFAULT_MAX_DOCUMENTS = 200
"""Ceiling on documents in one envelope; a long tail of tiny files helps nobody."""

DEFAULT_MAX_BYTES = 4 * 1024 * 1024
"""Byte ceiling, enforced independently of tokens because transports cap bytes."""

VALID_STRATEGIES = ("auto", "whole", "ranked", "tiered", "packed")
"""Strategy names `select()` accepts."""

Strategy = Literal["auto", "whole", "ranked", "tiered", "packed"]
"""Names accepted by `select`'s strategy argument."""

RenderOrder = Literal["path", "rank"]
"""Whether selected documents render by stable path order or relevance rank."""

_CONSTRAINT_ORDER = ("document count", "bytes", "tokens")
"""Fixed reporting order, so `binding_constraints` is comparable across runs."""


@dataclass(frozen=True, slots=True)
class Reduction:
    """What a reduction produced, and what it cost.

    Attributes:
        strategy: The strategy that was *requested*. ``auto`` stays ``auto`` even after
            dispatch, so the caller can see what they asked for.
        representation: The strategy actually applied — what ``auto`` resolved to.
        documents: Documents represented at full or extract fidelity. In ``tiered`` this
            is the set actually rendered in detail, not the ranked prefix.
        candidate_count: How many documents were offered.
        text: The rendered envelope. Always present — place it in your own message.
        estimated_tokens: Planning-side estimate of ``text``.
        max_tokens: The token budget this reduction was held to.
        max_bytes: The byte ceiling in force.
        max_documents: The document-count ceiling in force.
        total_bytes: UTF-8 byte length of ``text``.
        binding_constraints: Which ceilings excluded at least one document, in the fixed
            order ``("document count", "bytes", "tokens")``. Empty means everything fit.
        tier_metadata: Strategy-specific detail (tier composition, chunk counts).
    """

    strategy: str
    representation: str
    documents: tuple[ContextDocument, ...]
    candidate_count: int
    text: str
    estimated_tokens: int
    max_tokens: int
    max_bytes: int
    max_documents: int
    total_bytes: int
    binding_constraints: tuple[str, ...] = ()
    tier_metadata: Mapping[str, Any] | None = None

    @property
    def omitted_count(self) -> int:
        """How many offered documents are not represented in detail."""
        return max(0, self.candidate_count - len(self.documents))

    @property
    def complete(self) -> bool:
        """Whether every offered document was represented without any ceiling binding."""
        return not self.binding_constraints and self.omitted_count == 0

    def metadata(self) -> dict[str, Any]:
        """The full machine-readable record, for logging or a debug pane."""
        record: dict[str, Any] = {
            "strategy": self.strategy,
            "representation": self.representation,
            "candidate_count": self.candidate_count,
            "selected_count": len(self.documents),
            "omitted_count": self.omitted_count,
            "estimated_tokens": self.estimated_tokens,
            "max_tokens": self.max_tokens,
            "total_bytes": self.total_bytes,
            "max_bytes": self.max_bytes,
            "max_documents": self.max_documents,
            "binding_constraints": list(self.binding_constraints),
        }
        if self.tier_metadata is not None:
            record["tier_metadata"] = dict(self.tier_metadata)
        return record

    def summary(self) -> str:
        """A one-line, content-free description of what happened.

        Safe to show a user or write to a log: counts and ceilings only, never paths or
        content — a path name can itself be sensitive.
        """
        parts = [
            f"{self.representation}: {len(self.documents)} of {self.candidate_count} document(s)",
            f"~{self.estimated_tokens} of {self.max_tokens} tokens",
        ]
        if self.omitted_count:
            parts.append(f"{self.omitted_count} omitted")
        if self.binding_constraints:
            parts.append(f"limited by {', '.join(self.binding_constraints)}")
        return "; ".join(parts)

    def event(self, *, calls: int = 0) -> ContextReduced:
        """Build the telemetry event describing this reduction."""
        return ContextReduced(
            strategy=self.strategy,
            representation=self.representation,
            candidate_count=self.candidate_count,
            selected_count=len(self.documents),
            omitted_count=self.omitted_count,
            estimated_tokens=self.estimated_tokens,
            max_tokens=self.max_tokens,
            binding_constraints=self.binding_constraints,
            calls=calls,
        )


def normalize_strategy(value: str | None) -> str:
    """Normalize a strategy name.

    Args:
        value: The requested strategy; ``None`` or blank means ``"auto"``.

    Returns:
        The lowercase strategy name.

    Raises:
        ValueError: On an unrecognized strategy, listing the valid names.
    """
    name = (value or "").strip().lower() or "auto"
    if name not in VALID_STRATEGIES:
        raise ValueError(
            f"unknown context strategy {value!r}; valid strategies are "
            f"{', '.join(VALID_STRATEGIES)}"
        )
    return name


def select(
    documents: Iterable[ContextDocument],
    query: str,
    *,
    max_tokens: int,
    strategy: str = "auto",
    max_documents: int = DEFAULT_MAX_DOCUMENTS,
    max_bytes: int = DEFAULT_MAX_BYTES,
    estimator: TokenEstimator | None = None,
    rank_cache: RankCache | None = None,
    module_digests: Mapping[str, str] | None = None,
    render_order: RenderOrder = "path",
    observer: Observer | None = None,
) -> Reduction:
    """Reduce a corpus to fit a token budget.

    Args:
        documents: The corpus the app has already collected and approved.
        query: What the request is about, used for relevance ranking.
        max_tokens: The token budget. Normally
            ``client.budget(messages, target=...).remaining_tokens`` — an explicit
            number, because an unknown context window stays unknown rather than being
            guessed at.
        strategy: ``auto`` (default), ``whole``, ``ranked``, ``tiered``, or ``packed``.
        max_documents: Ceiling on documents represented.
        max_bytes: Ceiling on envelope bytes.
        estimator: Token counting strategy; defaults to the byte heuristic.
        rank_cache: Precomputed corpus statistics, for repeated queries.
        module_digests: App-supplied per-module summaries, rendered by ``tiered``. The
            library never generates these.
        render_order: ``path`` (default) renders selected documents in path order
            regardless of rank, so consecutive turns over the same corpus share a stable
            prompt prefix and provider prompt caches hit. ``rank`` renders
            strongest-first.
        observer: Receives a `ContextReduced` event describing the outcome.

    Returns:
        The `Reduction`, whose ``text`` is the envelope to place in your own message.

    Raises:
        ValueError: On an unknown strategy or a non-positive budget.
    """
    name = normalize_strategy(strategy)
    _validate_budgets(max_tokens=max_tokens, max_bytes=max_bytes, max_documents=max_documents)

    candidates = list(documents)
    counter = estimator or HeuristicTokenEstimator()
    ordered = rank(candidates, query, rank_cache=rank_cache)

    reduction = _dispatch(
        name,
        candidates=candidates,
        ordered=ordered,
        query=query,
        max_tokens=max_tokens,
        max_bytes=max_bytes,
        max_documents=max_documents,
        estimator=counter,
        module_digests=module_digests,
        render_order=render_order,
    )
    if observer is not None:
        observer.on_event(reduction.event())
    return reduction


def _dispatch(
    name: str,
    *,
    candidates: list[ContextDocument],
    ordered: list[ContextDocument],
    query: str,
    max_tokens: int,
    max_bytes: int,
    max_documents: int,
    estimator: TokenEstimator,
    module_digests: Mapping[str, str] | None,
    render_order: RenderOrder,
) -> Reduction:
    """Route to a strategy, resolving ``auto`` by whether the whole corpus fits."""
    common: dict[str, Any] = {
        "candidates": candidates,
        "ordered": ordered,
        "max_tokens": max_tokens,
        "max_bytes": max_bytes,
        "max_documents": max_documents,
        "estimator": estimator,
        "render_order": render_order,
    }

    if name in ("auto", "whole"):
        whole = _try_whole(strategy=name, **common)
        if whole is not None:
            return whole
        if name == "auto":
            from .tiers import reduce_tiered

            return reduce_tiered(strategy=name, module_digests=module_digests, **common)
        return _greedy(strategy=name, representation="ranked", **common)

    if name == "ranked":
        return _greedy(strategy=name, representation="ranked", **common)

    if name == "tiered":
        from .tiers import reduce_tiered

        return reduce_tiered(strategy=name, module_digests=module_digests, **common)

    from .pack import reduce_packed

    return reduce_packed(strategy=name, query=query, **common)


def _try_whole(
    *,
    strategy: str,
    candidates: list[ContextDocument],
    ordered: list[ContextDocument],
    max_tokens: int,
    max_bytes: int,
    max_documents: int,
    estimator: TokenEstimator,
    render_order: RenderOrder,
) -> Reduction | None:
    """Return the whole corpus when it fits every ceiling, else ``None``."""
    if len(candidates) > max_documents:
        return None

    selected = _ordered_for_render(ordered, render_order)
    text = render_corpus(render_file_block(document) for document in selected)
    total_bytes = len(text.encode("utf-8"))
    if total_bytes > max_bytes:
        return None
    tokens = estimator.estimate(text).tokens
    if tokens > max_tokens:
        return None

    return Reduction(
        strategy=strategy,
        representation="whole",
        documents=tuple(selected),
        candidate_count=len(candidates),
        text=text,
        estimated_tokens=tokens,
        max_tokens=max_tokens,
        max_bytes=max_bytes,
        max_documents=max_documents,
        total_bytes=total_bytes,
    )


def _greedy(
    *,
    strategy: str,
    representation: str,
    candidates: list[ContextDocument],
    ordered: list[ContextDocument],
    max_tokens: int,
    max_bytes: int,
    max_documents: int,
    estimator: TokenEstimator,
    render_order: RenderOrder,
) -> Reduction:
    """Admit documents in rank order while they fit.

    Two different reactions to the two ceilings, and the asymmetry is deliberate: hitting
    the *count* limit ends selection, because no later document can satisfy it — but
    overflowing bytes or tokens only skips that document, since a smaller lower-ranked
    one may still fit.
    """
    selected: list[ContextDocument] = []
    constraints: set[str] = set()
    used_bytes = wrapper_bytes()
    used_tokens = estimator.estimate("").tokens

    for document in ordered:
        if len(selected) >= max_documents:
            constraints.add("document count")
            break

        block = render_file_block(document)
        cost_bytes = block_bytes(block)
        cost_tokens = estimator.estimate(block).tokens

        if used_bytes + cost_bytes > max_bytes:
            constraints.add("bytes")
            continue
        if used_tokens + cost_tokens > max_tokens:
            constraints.add("tokens")
            continue

        selected.append(document)
        used_bytes += cost_bytes
        used_tokens += cost_tokens

    rendered = _ordered_for_render(selected, render_order)
    text = render_corpus(render_file_block(document) for document in rendered)
    return Reduction(
        strategy=strategy,
        representation=representation,
        documents=tuple(rendered),
        candidate_count=len(candidates),
        text=text,
        estimated_tokens=estimator.estimate(text).tokens,
        max_tokens=max_tokens,
        max_bytes=max_bytes,
        max_documents=max_documents,
        total_bytes=len(text.encode("utf-8")),
        binding_constraints=_order_constraints(constraints),
    )


def _ordered_for_render(
    documents: Sequence[ContextDocument], render_order: RenderOrder
) -> list[ContextDocument]:
    """Apply the render ordering to an already-selected set."""
    if render_order == "rank":
        return list(documents)
    return sorted(documents, key=lambda d: (d.path, d.sha256))


def _order_constraints(constraints: Iterable[str]) -> tuple[str, ...]:
    """Put binding constraints in the fixed reporting order."""
    present = set(constraints)
    return tuple(name for name in _CONSTRAINT_ORDER if name in present)


def _validate_budgets(*, max_tokens: int, max_bytes: int, max_documents: int) -> None:
    """Reject budgets that cannot admit anything."""
    if max_tokens < 1 or max_bytes < 1 or max_documents < 1:
        raise ValueError(
            "context selection budgets must be positive "
            f"(max_tokens={max_tokens}, max_bytes={max_bytes}, "
            f"max_documents={max_documents})"
        )
