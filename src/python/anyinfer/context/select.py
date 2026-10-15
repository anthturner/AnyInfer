"""Corpus selection: the strategies, the result type, and the dispatch rule.

Reduction is *emulation of a larger context window*, and emulation announces itself. Every
reduction returns what it kept, what it dropped, what it collapsed, which ceiling bound it,
and a content-free summary — plus a `ContextReduced` telemetry event when an observer is
supplied. A silent truncation that looks like a complete answer is the failure mode this
module exists to prevent.

Everything algorithmic is a setting rather than a constant. `ContextTuning` decides how
duplicates collapse, whether candidates are ordered by relevance or relevance per token,
whether near-identical documents are penalized against each other, and what a document
degrades to instead of being dropped. The defaults reproduce the plain behaviour exactly,
so turning nothing on changes nothing.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal

from ..capabilities.estimate import HeuristicTokenEstimator, TokenEstimator
from ..events.observers import Observer
from ..events.telemetry import ContextReduced
from .compact import compact_source, supports_compaction
from .dedup import DuplicateMap, find_duplicates
from .documents import ContextDocument, RankCache
from .envelope import (
    block_bytes,
    render_compact_block,
    render_corpus,
    render_duplicate_block,
    render_file_block,
    wrapper_bytes,
    wrapper_text,
)
from .rank import SemanticRanker, build_rank_cache, rank, scores_for
from .settings import DEFAULT_TUNING, ContextTuning

__all__ = [
    "DEFAULT_MAX_BYTES",
    "DEFAULT_MAX_DOCUMENTS",
    "VALID_STRATEGIES",
    "Reduction",
    "ReductionPlan",
    "ReductionState",
    "RenderOrder",
    "Strategy",
    "StrategyOutlook",
    "normalize_strategy",
    "plan",
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

_PLANNED_STRATEGIES = ("whole", "ranked", "tiered", "packed")
"""What `plan()` costs out. ``auto`` is excluded: it resolves to one of these.

Also the fidelity order, highest first: whole documents beat ranked whole documents beat
summarized ones beat fragments. `ReductionPlan.best` breaks ties on it.
"""


@dataclass(frozen=True, slots=True)
class ReductionState:
    """What an earlier reduction sent, so the next one can send the same thing.

    Selection is deterministic given the same inputs, but a corpus changes between turns
    and a re-ranked selection can churn for no reason — swapping one file for an equally
    ranked other, moving the whole prompt prefix and missing the provider's cache. Hand
    the previous state back through ``select(previous=...)`` and unchanged documents get a
    rank bonus, so the set stays put unless something real moved it.

    Attributes:
        entries: ``(path, sha256)`` for every document rendered at detail fidelity, in
            path order.
        representation: The strategy that produced it, for diagnostics.
    """

    entries: tuple[tuple[str, str], ...] = ()
    representation: str = ""

    @classmethod
    def of(cls, reduction: Reduction) -> ReductionState:
        """Capture the state of a completed reduction."""
        return cls(
            entries=tuple(
                sorted((document.path, document.sha256) for document in reduction.documents)
            ),
            representation=reduction.representation,
        )

    def unchanged(self, documents: Sequence[ContextDocument]) -> frozenset[str]:
        """Paths present here and still byte-identical in ``documents``.

        A path whose content changed is deliberately excluded: carrying it over would
        move the prompt prefix anyway, so there is nothing to preserve.
        """
        previous = dict(self.entries)
        return frozenset(
            document.path
            for document in documents
            if previous.get(document.path) == document.sha256
        )

    def metadata(self) -> dict[str, Any]:
        """The machine-readable record, content-free apart from paths the caller owns."""
        return {"entry_count": len(self.entries), "representation": self.representation}


@dataclass(frozen=True, slots=True)
class Reduction:
    """What a reduction produced, and what it cost.

    Attributes:
        strategy: The strategy that was *requested*. ``auto`` stays ``auto`` even after
            dispatch, so the caller can see what they asked for.
        representation: The strategy actually applied — what ``auto`` resolved to.
        documents: Documents represented at full, compact, or extract fidelity. In
            ``tiered`` this is the set actually rendered in detail, not the ranked prefix.
        candidate_count: How many documents were offered.
        text: The rendered envelope. Always present — place it in your own message.
        estimated_tokens: Planning-side estimate of ``text``.
        max_tokens: The token budget this reduction was held to.
        max_bytes: The byte ceiling in force.
        max_documents: The document-count ceiling in force.
        total_bytes: UTF-8 byte length of ``text``.
        binding_constraints: Which ceilings excluded at least one document, in the fixed
            order ``("document count", "bytes", "tokens")``. Empty means everything fit.
        collapsed_exact: Documents rendered as a pointer because a byte-identical copy
            was sent. Lossless.
        collapsed_near: Documents rendered as a pointer because a *similar* copy was
            sent. Their differences are not in the envelope.
        compacted_count: Documents sent with commentary removed because they would not
            fit whole.
        partial_count: Documents represented by only part of their content — the spans
            ``packed`` selected, rather than the whole file.
        carried_over: Documents this reduction kept because the previous one had them,
            when ``previous=`` was supplied.
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
    collapsed_exact: int = 0
    collapsed_near: int = 0
    compacted_count: int = 0
    partial_count: int = 0
    carried_over: int = 0
    tier_metadata: Mapping[str, Any] | None = None

    @property
    def collapsed_count(self) -> int:
        """How many documents were represented by a pointer to another."""
        return self.collapsed_exact + self.collapsed_near

    @property
    def omitted_count(self) -> int:
        """How many offered documents are not represented at all.

        Collapsed duplicates are not omitted: their content reached the model under
        another path, and the envelope says so.
        """
        return max(0, self.candidate_count - len(self.documents) - self.collapsed_count)

    @property
    def complete(self) -> bool:
        """Whether every offered document reached the model at full fidelity.

        Exact collapse preserves completeness — the same bytes were sent, once. Near
        collapse, compaction, and chunk-level selection do not: each drops content that
        was offered, and a strategy that sends fragments must not report the same
        confidence as one that sends files.
        """
        return (
            not self.binding_constraints
            and self.omitted_count == 0
            and self.collapsed_near == 0
            and self.compacted_count == 0
            and self.partial_count == 0
        )

    def state(self) -> ReductionState:
        """Capture what was sent, to hand back as the next turn's ``previous=``."""
        return ReductionState.of(self)

    def metadata(self) -> dict[str, Any]:
        """The full machine-readable record, for logging or a debug pane."""
        record: dict[str, Any] = {
            "strategy": self.strategy,
            "representation": self.representation,
            "candidate_count": self.candidate_count,
            "selected_count": len(self.documents),
            "omitted_count": self.omitted_count,
            "collapsed_exact": self.collapsed_exact,
            "collapsed_near": self.collapsed_near,
            "compacted_count": self.compacted_count,
            "partial_count": self.partial_count,
            "carried_over": self.carried_over,
            "estimated_tokens": self.estimated_tokens,
            "max_tokens": self.max_tokens,
            "total_bytes": self.total_bytes,
            "max_bytes": self.max_bytes,
            "max_documents": self.max_documents,
            "binding_constraints": list(self.binding_constraints),
            "complete": self.complete,
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
        if self.collapsed_count:
            detail = f"{self.collapsed_count} collapsed"
            if self.collapsed_near:
                detail += f" ({self.collapsed_near} as near-duplicates)"
            parts.append(detail)
        if self.compacted_count:
            parts.append(f"{self.compacted_count} compacted")
        if self.partial_count:
            parts.append(f"{self.partial_count} partial")
        if self.carried_over:
            parts.append(f"{self.carried_over} carried over")
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


@dataclass(frozen=True, slots=True)
class StrategyOutlook:
    """What one strategy would produce, costed exactly rather than modelled.

    Attributes:
        strategy: The strategy this describes.
        representation: What it resolved to — identical to ``strategy`` here, since
            ``plan()`` never costs ``auto``.
        selected_count: Documents it would represent at detail fidelity.
        omitted_count: Documents it would not represent at all.
        collapsed_count: Documents it would render as a pointer to another.
        compacted_count: Documents it would shorten rather than drop.
        partial_count: Documents it would represent by fragments rather than whole.
        estimated_tokens: Planning-side estimate of the envelope it would render.
        total_bytes: Byte length of that envelope.
        binding_constraints: Which ceilings would bind.
        complete: Whether it would send everything at full fidelity.
    """

    strategy: str
    representation: str
    selected_count: int
    omitted_count: int
    collapsed_count: int
    compacted_count: int
    partial_count: int
    estimated_tokens: int
    total_bytes: int
    binding_constraints: tuple[str, ...]
    complete: bool

    @classmethod
    def of(cls, strategy: str, reduction: Reduction) -> StrategyOutlook:
        """Describe a reduction that was run purely to be measured."""
        return cls(
            strategy=strategy,
            representation=reduction.representation,
            selected_count=len(reduction.documents),
            omitted_count=reduction.omitted_count,
            collapsed_count=reduction.collapsed_count,
            compacted_count=reduction.compacted_count,
            partial_count=reduction.partial_count,
            estimated_tokens=reduction.estimated_tokens,
            total_bytes=reduction.total_bytes,
            binding_constraints=reduction.binding_constraints,
            complete=reduction.complete,
        )

    def metadata(self) -> dict[str, Any]:
        """The machine-readable record."""
        return {
            "strategy": self.strategy,
            "representation": self.representation,
            "selected_count": self.selected_count,
            "omitted_count": self.omitted_count,
            "collapsed_count": self.collapsed_count,
            "compacted_count": self.compacted_count,
            "partial_count": self.partial_count,
            "estimated_tokens": self.estimated_tokens,
            "total_bytes": self.total_bytes,
            "binding_constraints": list(self.binding_constraints),
            "complete": self.complete,
        }


@dataclass(frozen=True, slots=True)
class ReductionPlan:
    """What every strategy would do with this corpus and this budget.

    A dry run for context preparation, in the same spirit as the pre-dispatch request
    preflight: choose a strategy from measured outcomes instead of guessing and finding
    out in the transcript. Costing it spends no inference and touches no network — the
    deterministic strategies are actually executed and their envelopes measured, then
    discarded, so the numbers are exact rather than modelled.

    Attributes:
        candidate_count: Documents offered.
        max_tokens: The budget every option was held to.
        options: One outlook per deterministic strategy, in a fixed order.
        distill_chunks: How many chunks `anyinfer.context.distill` would split this
            corpus into at the configured chunk size.
        distill_calls: The floor on generation calls distillation would spend — one per
            chunk plus a single reduce. A corpus whose notes do not fit at once reduces
            hierarchically and spends more.
    """

    candidate_count: int
    max_tokens: int
    options: tuple[StrategyOutlook, ...]
    distill_chunks: int
    distill_calls: int

    def option(self, strategy: str) -> StrategyOutlook | None:
        """The outlook for one strategy, or ``None`` if it was not costed."""
        name = strategy.strip().lower()
        return next((option for option in self.options if option.strategy == name), None)

    def best(self) -> StrategyOutlook | None:
        """The option that gets the most of the corpus to the model.

        Prefers an option that sends everything at full fidelity; failing that, the one
        representing the most documents at detail fidelity; and among equals, the one that
        represents them most faithfully — a whole file beats a summary beats a fragment.
        It is a recommendation, not a decision: an app that would rather have twelve whole
        files than four hundred summarized ones should read ``options`` and pick for
        itself.
        """
        if not self.options:
            return None
        return min(
            self.options,
            key=lambda option: (
                not option.complete,
                -option.selected_count,
                _PLANNED_STRATEGIES.index(option.strategy),
            ),
        )

    def metadata(self) -> dict[str, Any]:
        """The full machine-readable record."""
        best = self.best()
        return {
            "candidate_count": self.candidate_count,
            "max_tokens": self.max_tokens,
            "options": [option.metadata() for option in self.options],
            "distill_chunks": self.distill_chunks,
            "distill_calls": self.distill_calls,
            "best": best.strategy if best else None,
        }

    def summary(self) -> str:
        """A one-line, content-free description of the plan."""
        best = self.best()
        head = f"{self.candidate_count} document(s) against {self.max_tokens} tokens"
        if best is None:
            return head
        return (
            f"{head}; best {best.strategy} "
            f"({best.selected_count} kept, {best.omitted_count} omitted, "
            f"~{best.estimated_tokens} tokens); "
            f"distill would spend {self.distill_calls}+ call(s)"
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
    tuning: ContextTuning | None = None,
    previous: ReductionState | None = None,
    observer: Observer | None = None,
    ranker: SemanticRanker | None = None,
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
        tuning: Advanced settings — duplicate collapse, selection order, diversity,
            query expansion, centrality, compact fallback. Defaults reproduce the plain
            behaviour exactly.
        previous: The state of the last reduction over this corpus. Unchanged documents
            get ``tuning.carry_over_bonus`` so the selected set, and the rendered prefix
            — stays stable across turns.
        observer: Receives a `ContextReduced` event describing the outcome.
        ranker: Caller-supplied semantic scoring (`SemanticRanker`). When set, its
            scores replace the lexical ranking for both ordering and admission — one
            scoring call per reduction. The default stays lexical and offline; build a
            rerank-backed implementation with `anyinfer.semantic_ranker`.

    Returns:
        The `Reduction`, whose ``text`` is the envelope to place in your own message.

    Raises:
        ValueError: On an unknown strategy or a non-positive budget.
    """
    name = normalize_strategy(strategy)
    _validate_budgets(max_tokens=max_tokens, max_bytes=max_bytes, max_documents=max_documents)

    settings = tuning or DEFAULT_TUNING
    candidates = list(documents)
    counter = estimator or HeuristicTokenEstimator()

    duplicates = find_duplicates(candidates, tuning=settings)
    unique = [document for document in candidates if document.path not in duplicates.canonical]

    cache = rank_cache
    if cache is None or cache.split_identifiers != settings.split_identifiers:
        cache = build_rank_cache(unique, split_identifiers=settings.split_identifiers)

    carry_over = previous.unchanged(unique) if previous is not None else frozenset()
    semantic_scores: dict[str, float] | None = None
    if ranker is not None:
        # One scoring call for the whole corpus; ordering and admission both read it, so
        # the two can never disagree about relevance the way two scorers could.
        semantic_scores = dict(ranker.scores(unique, query))
        ordered = sorted(
            unique,
            key=lambda d: (not d.pinned, -semantic_scores.get(d.path, 0.0), d.sha256),
        )
    else:
        ordered = rank(unique, query, rank_cache=cache, tuning=settings, carry_over=carry_over)

    reduction = _dispatch(
        name,
        candidates=candidates,
        ordered=ordered,
        query=query,
        semantic_scores=semantic_scores,
        max_tokens=max_tokens,
        max_bytes=max_bytes,
        max_documents=max_documents,
        estimator=counter,
        module_digests=module_digests,
        render_order=render_order,
        tuning=settings,
        duplicates=duplicates,
        rank_cache=cache,
    )
    reduction = _with_carry_over(reduction, carry_over)
    if observer is not None:
        observer.on_event(reduction.event())
    return reduction


def plan(
    documents: Iterable[ContextDocument],
    query: str,
    *,
    max_tokens: int,
    max_documents: int = DEFAULT_MAX_DOCUMENTS,
    max_bytes: int = DEFAULT_MAX_BYTES,
    estimator: TokenEstimator | None = None,
    module_digests: Mapping[str, str] | None = None,
    tuning: ContextTuning | None = None,
) -> ReductionPlan:
    """Cost every strategy against this corpus without committing to one.

    Spends no inference and performs no I/O: each deterministic strategy is run, its
    envelope measured, and the text discarded. The distillation figures are projections —
    that is the only strategy whose cost cannot be known without paying it.

    Args:
        documents: The corpus.
        query: What the request is about.
        max_tokens: The budget to hold every option to.
        max_documents: Ceiling on documents represented.
        max_bytes: Ceiling on envelope bytes.
        estimator: Token counting strategy; defaults to the byte heuristic.
        module_digests: App-supplied module summaries, costed into the ``tiered`` option.
        tuning: Advanced settings, applied to every option so the comparison is fair.

    Returns:
        The `ReductionPlan`.

    Raises:
        ValueError: On a non-positive budget.
    """
    from .pack import split_document

    settings = tuning or DEFAULT_TUNING
    corpus = list(documents)
    options = tuple(
        StrategyOutlook.of(
            name,
            select(
                corpus,
                query,
                max_tokens=max_tokens,
                strategy=name,
                max_documents=max_documents,
                max_bytes=max_bytes,
                estimator=estimator,
                module_digests=module_digests,
                tuning=settings,
            ),
        )
        for name in _PLANNED_STRATEGIES
    )

    chunks = sum(
        len(split_document(document, chunk_tokens=settings.chunk_tokens))
        for document in corpus
        if document.content.strip()
    )
    return ReductionPlan(
        candidate_count=len(corpus),
        max_tokens=max_tokens,
        options=options,
        distill_chunks=chunks,
        distill_calls=chunks + 1 if chunks else 0,
    )


def _with_carry_over(reduction: Reduction, carry_over: frozenset[str]) -> Reduction:
    """Record how many of the selected documents came from the previous turn."""
    if not carry_over:
        return reduction
    kept = sum(1 for document in reduction.documents if document.path in carry_over)
    return replace(reduction, carried_over=kept)


def _dispatch(
    name: str,
    *,
    candidates: list[ContextDocument],
    ordered: list[ContextDocument],
    query: str,
    semantic_scores: Mapping[str, float] | None = None,
    max_tokens: int,
    max_bytes: int,
    max_documents: int,
    estimator: TokenEstimator,
    module_digests: Mapping[str, str] | None,
    render_order: RenderOrder,
    tuning: ContextTuning,
    duplicates: DuplicateMap,
    rank_cache: RankCache,
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
        "tuning": tuning,
        "duplicates": duplicates,
    }

    if name in ("auto", "whole"):
        whole = _try_whole(strategy=name, **common)
        if whole is not None:
            return whole
        if name == "auto":
            from .tiers import reduce_tiered

            return reduce_tiered(strategy=name, module_digests=module_digests, **common)
        return _greedy(
            strategy=name,
            representation="ranked",
            query=query,
            rank_cache=rank_cache,
            semantic_scores=semantic_scores,
            **common,
        )

    if name == "ranked":
        return _greedy(
            strategy=name,
            representation="ranked",
            query=query,
            rank_cache=rank_cache,
            semantic_scores=semantic_scores,
            **common,
        )

    if name == "tiered":
        from .tiers import reduce_tiered

        return reduce_tiered(strategy=name, module_digests=module_digests, **common)

    from .pack import reduce_packed

    return reduce_packed(strategy=name, query=query, rank_cache=rank_cache, **common)


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
    tuning: ContextTuning,
    duplicates: DuplicateMap,
) -> Reduction | None:
    """Return the whole corpus when it fits every ceiling, else ``None``."""
    if len(ordered) > max_documents:
        return None

    selected = _ordered_for_render(ordered, render_order)
    text = render_corpus(_blocks_for(document, duplicates) for document in selected)
    total_bytes = len(text.encode("utf-8"))
    if total_bytes > max_bytes:
        return None
    tokens = estimator.estimate(text).tokens
    if tokens > max_tokens:
        return None

    exact, near = _collapse_counts(duplicates)
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
        collapsed_exact=exact,
        collapsed_near=near,
    )


def _greedy(
    *,
    strategy: str,
    representation: str,
    candidates: list[ContextDocument],
    ordered: list[ContextDocument],
    query: str,
    max_tokens: int,
    max_bytes: int,
    max_documents: int,
    estimator: TokenEstimator,
    render_order: RenderOrder,
    tuning: ContextTuning,
    duplicates: DuplicateMap,
    rank_cache: RankCache,
    semantic_scores: Mapping[str, float] | None = None,
) -> Reduction:
    """Admit documents while they fit, in the configured order.

    Two different reactions to the two ceilings, and the asymmetry is deliberate: hitting
    the *count* limit ends selection, because no later document can satisfy it — but
    overflowing bytes or tokens only skips that document, since a smaller lower-ranked
    one may still fit. With ``compact_fallback`` a document that overflows is retried
    without its commentary before being skipped.
    """
    selected: list[tuple[ContextDocument, str]] = []
    constraints: set[str] = set()
    compacted = 0
    used_bytes = wrapper_bytes()
    used_tokens = estimator.estimate(wrapper_text()).tokens

    for document in _admission_order(
        ordered,
        semantic_scores=semantic_scores,
        query=query,
        estimator=estimator,
        tuning=tuning,
        duplicates=duplicates,
        rank_cache=rank_cache,
    ):
        if len(selected) >= max_documents:
            constraints.add("document count")
            break

        block = _blocks_for(document, duplicates)
        cost_bytes = block_bytes(block)
        cost_tokens = estimator.estimate(block).tokens
        overflow = _overflow(
            used_bytes + cost_bytes, max_bytes, used_tokens + cost_tokens, max_tokens
        )

        if overflow is not None:
            fallback = _compact_block(document, duplicates, tuning)
            if fallback is None:
                constraints.add(overflow)
                continue
            block = fallback
            cost_bytes = block_bytes(block)
            cost_tokens = estimator.estimate(block).tokens
            overflow = _overflow(
                used_bytes + cost_bytes, max_bytes, used_tokens + cost_tokens, max_tokens
            )
            if overflow is not None:
                constraints.add(overflow)
                continue
            compacted += 1

        selected.append((document, block))
        used_bytes += cost_bytes
        used_tokens += cost_tokens

    rendered = _pairs_for_render(selected, render_order)
    text = render_corpus(block for _, block in rendered)
    exact, near = _collapse_counts(duplicates)
    return Reduction(
        strategy=strategy,
        representation=representation,
        documents=tuple(document for document, _ in rendered),
        candidate_count=len(candidates),
        text=text,
        estimated_tokens=estimator.estimate(text).tokens,
        max_tokens=max_tokens,
        max_bytes=max_bytes,
        max_documents=max_documents,
        total_bytes=len(text.encode("utf-8")),
        binding_constraints=_order_constraints(constraints),
        collapsed_exact=exact,
        collapsed_near=near,
        compacted_count=compacted,
    )


def _admission_order(
    ordered: Sequence[ContextDocument],
    *,
    query: str,
    estimator: TokenEstimator,
    tuning: ContextTuning,
    duplicates: DuplicateMap,
    rank_cache: RankCache,
    semantic_scores: Mapping[str, float] | None = None,
) -> list[ContextDocument]:
    """Decide the order candidates are offered to the budget.

    Plain rank order unless a setting says otherwise, and that path allocates nothing —
    an unconfigured reduction admits documents in exactly the order it always has.

    ``density`` divides each document's score by what it costs, which is the classic
    knapsack result: relevance per token packs measurably more relevance into a fixed
    budget than relevance alone. ``diversity`` then penalizes each remaining candidate by
    how much it resembles what is already chosen, so a budget is not spent on eight files
    that say the same thing. The penalty is multiplicative — ``value * (1 - diversity *
    similarity)``, because the two value scales differ by orders of magnitude and a
    subtractive penalty calibrated for one would be meaningless for the other.
    """
    if tuning.selection_order == "rank" and tuning.diversity <= 0:
        return list(ordered)

    pinned = [document for document in ordered if document.pinned]
    rest = [document for document in ordered if not document.pinned]
    if not rest:
        return list(ordered)

    scores = (
        semantic_scores
        if semantic_scores is not None
        else scores_for(rest, query, cache=rank_cache, tuning=tuning)
    )
    values: dict[str, float] = {}
    for document in rest:
        score = scores.get(document.path, 0.0)
        if tuning.selection_order == "density":
            cost = max(1, estimator.estimate(_blocks_for(document, duplicates)).tokens)
            values[document.path] = score / cost
        else:
            values[document.path] = score

    if tuning.diversity <= 0:
        rest.sort(key=lambda d: (-values[d.path], d.path.count("/"), d.path, d.sha256))
        return [*pinned, *rest]

    return [*pinned, *_diversified(rest, values, rank_cache, tuning.diversity)]


def _diversified(
    documents: Sequence[ContextDocument],
    values: Mapping[str, float],
    cache: RankCache,
    diversity: float,
) -> list[ContextDocument]:
    """Order documents by value, penalizing resemblance to what is already ordered."""
    norms = {document.path: _norm(cache.term_counts.get(document.path)) for document in documents}
    remaining = list(documents)
    chosen: list[ContextDocument] = []

    def key(document: ContextDocument) -> tuple[float, int, str, str]:
        similarity = max(
            (_cosine(cache, document.path, picked.path, norms) for picked in chosen),
            default=0.0,
        )
        adjusted = values.get(document.path, 0.0) * (1.0 - diversity * similarity)
        return (-adjusted, document.path.count("/"), document.path, document.sha256)

    while remaining:
        best = min(remaining, key=key)
        chosen.append(best)
        remaining.remove(best)
    return chosen


def _norm(counts: Mapping[str, int] | None) -> float:
    """Euclidean norm of a term-count vector."""
    if not counts:
        return 0.0
    return math.sqrt(sum(value * value for value in counts.values()))


def _cosine(cache: RankCache, left: str, right: str, norms: Mapping[str, float]) -> float:
    """Cosine similarity between two documents' term vectors.

    Iterating the shorter vector and probing the longer keeps this proportional to the
    smaller document rather than to the pair.
    """
    left_norm, right_norm = norms.get(left, 0.0), norms.get(right, 0.0)
    if left_norm <= 0 or right_norm <= 0:
        return 0.0
    empty: Counter[str] = Counter()
    left_counts: Mapping[str, int] = cache.term_counts.get(left, empty)
    right_counts: Mapping[str, int] = cache.term_counts.get(right, empty)
    if len(right_counts) < len(left_counts):
        left_counts, right_counts = right_counts, left_counts
    dot = sum(count * right_counts.get(term, 0) for term, count in left_counts.items())
    return dot / (left_norm * right_norm)


def _blocks_for(document: ContextDocument, duplicates: DuplicateMap) -> str:
    """Render a document together with pointers to everything collapsed into it.

    The pointers are part of the document's block, not a separate pass, so the byte and
    token accounting a selection loop performs is exactly what gets rendered — the
    invariant this subpackage's envelope module exists to hold.
    """
    block = render_file_block(document)
    return _with_pointers(block, document.path, duplicates)


def _with_pointers(block: str, path: str, duplicates: DuplicateMap) -> str:
    """Append duplicate pointers for one canonical document."""
    members = duplicates.members(path) if duplicates else ()
    if not members:
        return block
    pointers = "\n".join(
        render_duplicate_block(member, path, identical=duplicates.is_exact(member))
        for member in members
    )
    return f"{block}\n{pointers}"


def _compact_block(
    document: ContextDocument, duplicates: DuplicateMap, tuning: ContextTuning
) -> str | None:
    """The compacted rendering of a document, or ``None`` when it is not worth it."""
    if not tuning.compact_fallback or not supports_compaction(document.language):
        return None
    compacted = compact_source(document.content, language=document.language)
    if not compacted.is_reduced:
        return None
    block = render_compact_block(document, compacted.text, elided_lines=compacted.elided_lines)
    return _with_pointers(block, document.path, duplicates)


def _overflow(used_bytes: int, max_bytes: int, used_tokens: int, max_tokens: int) -> str | None:
    """Which ceiling a prospective admission would breach, if any."""
    if used_bytes > max_bytes:
        return "bytes"
    if used_tokens > max_tokens:
        return "tokens"
    return None


def _collapse_counts(duplicates: DuplicateMap) -> tuple[int, int]:
    """Split the duplicate map into the ``(exact, near)`` counts a `Reduction` reports.

    Shared with the tiered and packed strategies, which build their own `Reduction`.
    """
    exact = sum(1 for path in duplicates.canonical if duplicates.is_exact(path))
    return exact, duplicates.collapsed_count - exact


def _ordered_for_render(
    documents: Sequence[ContextDocument], render_order: RenderOrder
) -> list[ContextDocument]:
    """Apply the render ordering to an already-selected set."""
    if render_order == "rank":
        return list(documents)
    return sorted(documents, key=lambda d: (d.path, d.sha256))


def _pairs_for_render(
    pairs: Sequence[tuple[ContextDocument, str]], render_order: RenderOrder
) -> list[tuple[ContextDocument, str]]:
    """Apply the render ordering to selected ``(document, block)`` pairs."""
    if render_order == "rank":
        return list(pairs)
    return sorted(pairs, key=lambda pair: (pair[0].path, pair[0].sha256))


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
