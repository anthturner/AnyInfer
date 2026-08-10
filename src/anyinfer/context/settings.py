"""Advanced reduction settings: one record, every knob.

Reduction has accumulated real algorithmic choices — how duplicates are collapsed, whether
selection optimizes relevance or relevance *per token*, whether a query is expanded before
ranking, what a document degrades to when it will not fit whole. Each is a legitimate
tradeoff for some corpus and the wrong answer for another, so each is a setting rather than
a constant.

They live in one frozen record instead of a dozen keyword arguments. `select()` takes
``tuning=``; the shared configuration file carries a ``context`` block; the CLI exposes the
same names as flags. One vocabulary across all three.

**Defaults preserve the shipped behaviour.** Every setting that changes what gets sent is
off by default, because a reduction that silently changes shape between releases is exactly
the failure this subsystem exists to prevent. The one exception is
`collapse_duplicates`, which is on: rendering the same bytes twice is never the better
answer, the collapse is announced in the envelope, and no information is lost.

```python
from anyinfer import context

tuning = context.ContextTuning.recommended()
reduction = context.select(docs, query, max_tokens=8_000, tuning=tuning)
```
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, fields, replace
from typing import Any, Literal

__all__ = [
    "DEFAULT_TUNING",
    "SELECTION_ORDERS",
    "ContextTuning",
    "SelectionOrder",
]

SelectionOrder = Literal["rank", "density"]
"""How the greedy selector orders candidates."""

SELECTION_ORDERS = ("rank", "density")
"""Accepted `ContextTuning.selection_order` values."""


@dataclass(frozen=True, slots=True)
class ContextTuning:
    """Advanced settings for corpus reduction.

    Every field defaults to the behaviour AnyInfer has always had, except
    ``collapse_duplicates``. Construct one, or start from `recommended()` and override.

    Attributes:
        collapse_duplicates: Render byte-identical documents once, with the rest as
            pointer elements. Lossless — the content is still present, and on by
            default, since sending the same bytes twice helps nobody.
        near_duplicate_threshold: Jaccard similarity at or above which two documents are
            treated as duplicates of each other. ``0.0`` disables near-duplicate
            detection; ``0.9`` is a good starting point for vendored or generated
            siblings. Lossy: the near-duplicate's differences are not sent, so it is off
            by default.
        shingle_size: Word count per shingle for near-duplicate comparison. Larger is
            stricter.
        selection_order: ``rank`` admits documents strongest-first. ``density`` admits
            them by score *per token*, which fits measurably more relevance into the same
            budget at the cost of sometimes preferring two good small files to one great
            large one.
        diversity: Similarity penalty applied to candidates resembling what is already
            selected, between ``0.0`` (pure relevance) and ``1.0`` (near-pure novelty).
            Stops a budget being spent on eight files that say the same thing.
        split_identifiers: Tokenize ``resolve_credentials`` and ``resolveCredentials`` as
            their parts *and* as the whole, so a query of "resolve credentials" matches
            the identifier that names it.
        query_expansion: Rank once, harvest distinctive terms from the strongest
            documents, then re-rank with the expanded query. The lexical answer to
            vocabulary mismatch: it finds "login" from "authentication" whenever the two
            co-occur anywhere in the corpus. Costs a second ranking pass, no inference.
        expansion_terms: How many harvested terms to add.
        feedback_documents: How many top-ranked documents to harvest them from.
        expansion_weight: Weight of an expansion term relative to an original query term.
        salience_weight: How much a document's centrality in the corpus's own import
            graph contributes to its score. The signal is query-independent, so this is
            what orders a corpus when the query is weak or absent; ``0.0`` disables the
            graph pass entirely.
        salience_damping: Random-restart probability complement for the centrality
            iteration. The conventional ``0.85``.
        salience_iterations: Fixed iteration count. Fixed rather than
            convergence-tested, because determinism outranks the last decimal place.
        compact_fallback: When a document will not fit whole, send it with comments,
            docstrings, and blank runs removed before giving up on it. Elisions are
            counted in the rendered element, never silent.
        chunk_tokens: Target chunk size for ``packed`` and for ``distill``.
        rollup_share: Share of the budget ``tiered`` reserves for its module rollup.
        carry_over_bonus: Rank bonus applied to documents an earlier reduction already
            sent unchanged, when ``previous=`` is supplied. Keeps the selected set — and
            therefore the rendered prefix — stable across turns so provider prompt caches
            keep hitting. ``0.0`` ranks each turn from scratch.
    """

    collapse_duplicates: bool = True
    near_duplicate_threshold: float = 0.0
    shingle_size: int = 5

    selection_order: SelectionOrder = "rank"
    diversity: float = 0.0

    split_identifiers: bool = False
    query_expansion: bool = False
    expansion_terms: int = 8
    feedback_documents: int = 5
    expansion_weight: float = 0.4

    salience_weight: float = 0.0
    salience_damping: float = 0.85
    salience_iterations: int = 20

    compact_fallback: bool = False

    chunk_tokens: int = 512
    rollup_share: float = 0.45

    carry_over_bonus: float = 0.0

    def __post_init__(self) -> None:
        """Reject settings that cannot produce a usable reduction.

        Raises:
            ValueError: On an out-of-range or non-finite value, naming the field.
        """
        if self.selection_order not in SELECTION_ORDERS:
            raise ValueError(
                f"selection_order must be one of {', '.join(SELECTION_ORDERS)}; "
                f"got {self.selection_order!r}"
            )
        _unit("near_duplicate_threshold", self.near_duplicate_threshold)
        _unit("diversity", self.diversity)
        _unit("salience_damping", self.salience_damping, low=0.0, high=1.0)
        _non_negative("expansion_weight", self.expansion_weight)
        _non_negative("salience_weight", self.salience_weight)
        _non_negative("carry_over_bonus", self.carry_over_bonus)
        _positive_int("shingle_size", self.shingle_size)
        _positive_int("salience_iterations", self.salience_iterations)
        _positive_int("chunk_tokens", self.chunk_tokens)
        _non_negative_int("expansion_terms", self.expansion_terms)
        _non_negative_int("feedback_documents", self.feedback_documents)
        if not 0.0 < self.rollup_share < 1.0:
            raise ValueError(
                f"rollup_share must be between 0 and 1 exclusive; got {self.rollup_share!r}"
            )

    @property
    def ranking_is_default(self) -> bool:
        """Whether ranking behaves exactly as the unconfigured ranker does.

        Selection consults this to skip the expansion and centrality passes entirely
        rather than running them with neutral parameters.
        """
        return (
            not self.split_identifiers
            and not self.query_expansion
            and self.salience_weight == 0.0
            and self.carry_over_bonus == 0.0
        )

    @classmethod
    def recommended(cls) -> ContextTuning:
        """The settings worth turning on for a typical source-code corpus.

        Near-duplicate collapse at a strict threshold, density-ordered selection with a
        mild diversity penalty, identifier splitting and query expansion, a light
        centrality signal, and compact fallback instead of dropping a file outright. Every
        one of these changes what gets sent, which is why they are a named preset rather
        than the default.
        """
        return cls(
            near_duplicate_threshold=0.9,
            selection_order="density",
            diversity=0.25,
            split_identifiers=True,
            query_expansion=True,
            salience_weight=0.5,
            compact_fallback=True,
            carry_over_bonus=0.5,
        )

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> ContextTuning:
        """Build settings from a JSON-shaped mapping.

        Used by the shared configuration loader and the CLI, so a ``context`` block in a
        config file and a ``--context-*`` flag mean exactly the same thing.

        Args:
            values: Field names to values. Unknown names are an error rather than being
                ignored, so a typo does not silently do nothing.

        Returns:
            The settings.

        Raises:
            ValueError: On an unknown key, a wrong type, or an out-of-range value.
        """
        known = {field.name for field in fields(cls)}
        unknown = set(values) - known
        if unknown:
            raise ValueError(
                f"unknown context setting(s): {', '.join(sorted(unknown))}; "
                f"valid settings are {', '.join(sorted(known))}"
            )

        coerced: dict[str, Any] = {}
        for name, value in values.items():
            coerced[name] = _coerce(cls, name, value)
        return cls(**coerced)

    def merged(self, **overrides: Any) -> ContextTuning:
        """Return a copy with ``overrides`` applied, dropping any that are ``None``.

        The shape command-line parsing wants: unspecified flags arrive as ``None`` and
        must leave the configured value alone.
        """
        applied = {name: value for name, value in overrides.items() if value is not None}
        return replace(self, **applied) if applied else self

    def to_mapping(self) -> dict[str, Any]:
        """The settings as a JSON-shaped mapping, for logging or round-tripping."""
        return {field.name: getattr(self, field.name) for field in fields(self)}


def _coerce(cls: type[ContextTuning], name: str, value: Any) -> Any:
    """Validate one mapping entry against its field's declared type."""
    annotation = {field.name: field.type for field in fields(cls)}[name]
    text = annotation if isinstance(annotation, str) else str(annotation)

    if "bool" in text:
        if not isinstance(value, bool):
            raise ValueError(f"context setting {name!r} must be true or false")
        return value
    if "SelectionOrder" in text:
        if not isinstance(value, str) or value not in SELECTION_ORDERS:
            raise ValueError(
                f"context setting {name!r} must be one of {', '.join(SELECTION_ORDERS)}"
            )
        return value
    if "int" in text:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"context setting {name!r} must be an integer")
        return value
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"context setting {name!r} must be a number")
    return float(value)


def _unit(name: str, value: float, *, low: float = 0.0, high: float = 1.0) -> None:
    """Require a finite value within an inclusive range."""
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name} must be between {low} and {high}; got {value!r}")


def _non_negative(name: str, value: float) -> None:
    """Require a finite value at or above zero."""
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a non-negative finite number; got {value!r}")


def _positive_int(name: str, value: int) -> None:
    """Require a whole number of at least one."""
    if value < 1:
        raise ValueError(f"{name} must be at least 1; got {value!r}")


def _non_negative_int(name: str, value: int) -> None:
    """Require a whole number at or above zero."""
    if value < 0:
        raise ValueError(f"{name} must be zero or greater; got {value!r}")


DEFAULT_TUNING = ContextTuning()
"""The shipped defaults, shared so an unconfigured reduction allocates nothing.

Built after the validators it runs on construction, which is why it sits at the foot of
the module rather than beside the class.
"""
