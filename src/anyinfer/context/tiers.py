"""The ``tiered`` strategy: full coverage at decreasing fidelity.

Where ``ranked`` answers "which files fit?", ``tiered`` answers "how do I say something
about *every* file?" Three tiers, each cheaper per document than the last:

1. **Module rollup** — one line per directory: how many files, what share of the corpus,
   which languages, its dependencies and symbols. Every document is covered here.
2. **Structural extracts** — signatures and imports for the highest-ranked documents.
3. **Verbatim** — whole files for whatever budget remains.

The rollup gets a fixed share of the budget so it cannot be crowded out: a model that
knows a module exists can ask about it, while one that never saw it cannot.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import PurePosixPath

from ..capabilities.estimate import TokenEstimator
from .dedup import DuplicateMap
from .documents import ContextDocument
from .envelope import (
    TIERS_TAG,
    block_bytes,
    render_digest_block,
    render_extract_block,
    render_module_block,
    render_tiers,
    wrapper_bytes,
    wrapper_text,
)
from .select import (
    Reduction,
    _blocks_for,
    _collapse_counts,
    _compact_block,
    _order_constraints,
)
from .settings import DEFAULT_TUNING, ContextTuning

__all__ = ["DEFAULT_ROLLUP_SHARE", "module_surfaces", "reduce_tiered"]

DEFAULT_ROLLUP_SHARE = 0.45
"""Share of the token and byte budget reserved for the module rollup.

The default for `ContextTuning.rollup_share`, which is what actually applies.
"""

_ROLLUP_MIN_BYTES = 256
"""Floor on the rollup's byte share, so a tiny budget still gets a map of the corpus."""

_SYMBOL_LIMIT_LADDER = (18, 12, 8, 4, 2, 0)
"""Symbols per module, tried in order until the rollup fits. Zero still names modules."""

_LINE_LIMIT = 120
"""Character cap on a rollup's dependency and symbol lines."""

_DEPENDENCY_PREFIXES = ("import", "from", "using", "#include", "require", "package", "use")
_SYMBOL_PREFIXES = (
    "class",
    "interface",
    "function",
    "def",
    "async",
    "enum",
    "struct",
    "trait",
    "impl",
    "namespace",
    "fun",
    "type",
    "record",
    "module",
    "pub",
)


def reduce_tiered(
    *,
    strategy: str,
    candidates: list[ContextDocument],
    ordered: list[ContextDocument],
    max_tokens: int,
    max_bytes: int,
    max_documents: int,
    estimator: TokenEstimator,
    render_order: str,
    module_digests: Mapping[str, str] | None = None,
    tuning: ContextTuning = DEFAULT_TUNING,
    duplicates: DuplicateMap = DuplicateMap(),
) -> Reduction:
    """Build a tiered envelope: rollup, then extracts, then verbatim files.

    Args:
        strategy: The requested strategy name, preserved on the result.
        candidates: Every offered document.
        ordered: The documents that survived duplicate collapse, in rank order.
        max_tokens: Token budget.
        max_bytes: Byte ceiling.
        max_documents: Ceiling on documents rendered at detail fidelity.
        estimator: Token counting strategy.
        render_order: ``path`` or ``rank``, applied within each detail tier.
        module_digests: App-supplied module summaries; rendered when they fit. The
            library never generates these — spending inference to summarize is an
            application's decision.
        tuning: Supplies ``rollup_share`` and ``compact_fallback``. With compaction on,
            the verbatim tier gains a step: a file that will not fit whole is sent
            without its commentary rather than left at extract fidelity.
        duplicates: Documents collapsed into others, rendered as pointers beside their
            representative.

    Returns:
        The `Reduction`. Coverage is total by construction: every document appears in
        the rollup even when no budget remained for its content.
    """
    constraints: set[str] = set()
    rollup_token_share = max(1, int(max_tokens * tuning.rollup_share))
    rollup_byte_share = max(_ROLLUP_MIN_BYTES, int(max_bytes * tuning.rollup_share))

    rollup, rollup_tokens, rollup_bytes = _render_rollup(
        candidates,
        max_tokens=rollup_token_share,
        max_bytes=rollup_byte_share,
        estimator=estimator,
    )

    used_tokens = rollup_tokens + estimator.estimate(wrapper_text(TIERS_TAG)).tokens
    used_bytes = rollup_bytes + wrapper_bytes(TIERS_TAG)

    digest_block = ""
    if module_digests:
        candidate_block = render_digest_block(module_digests)
        cost_tokens = estimator.estimate(candidate_block).tokens
        cost_bytes = block_bytes(candidate_block)
        if used_tokens + cost_tokens <= max_tokens and used_bytes + cost_bytes <= max_bytes:
            digest_block = candidate_block
            used_tokens += cost_tokens
            used_bytes += cost_bytes
        else:
            constraints.add("tokens" if used_tokens + cost_tokens > max_tokens else "bytes")

    extract_blocks: list[tuple[ContextDocument, str]] = []
    extracted: set[str] = set()
    for document in ordered:
        if not document.extract:
            continue
        if len(extracted) >= max_documents:
            constraints.add("document count")
            break
        block = render_extract_block(document)
        cost_tokens = estimator.estimate(block).tokens
        cost_bytes = block_bytes(block)
        if used_tokens + cost_tokens > max_tokens:
            constraints.add("tokens")
            continue
        if used_bytes + cost_bytes > max_bytes:
            constraints.add("bytes")
            continue
        extract_blocks.append((document, block))
        extracted.add(document.path)
        used_tokens += cost_tokens
        used_bytes += cost_bytes

    verbatim_blocks: list[tuple[ContextDocument, str]] = []
    compacted = 0
    for document in ordered:
        if document.path in extracted:
            continue
        if len(extracted) + len(verbatim_blocks) >= max_documents:
            constraints.add("document count")
            break

        block = _blocks_for(document, duplicates)
        cost_tokens = estimator.estimate(block).tokens
        cost_bytes = block_bytes(block)
        overflow = _overflowing(
            used_tokens + cost_tokens, max_tokens, used_bytes + cost_bytes, max_bytes
        )

        if overflow is not None:
            fallback = _compact_block(document, duplicates, tuning)
            if fallback is None:
                constraints.add(overflow)
                continue
            block = fallback
            cost_tokens = estimator.estimate(block).tokens
            cost_bytes = block_bytes(block)
            overflow = _overflowing(
                used_tokens + cost_tokens, max_tokens, used_bytes + cost_bytes, max_bytes
            )
            if overflow is not None:
                constraints.add(overflow)
                continue
            compacted += 1

        verbatim_blocks.append((document, block))
        used_tokens += cost_tokens
        used_bytes += cost_bytes

    detailed = [document for document, _ in (*extract_blocks, *verbatim_blocks)]
    text = _assemble(rollup, digest_block, extract_blocks, verbatim_blocks, render_order)
    exact, near = _collapse_counts(duplicates)

    return Reduction(
        strategy=strategy,
        representation="tiered",
        documents=tuple(_sorted_for_render(detailed, render_order)),
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
        tier_metadata={
            "rollup_modules": rollup.count("<module "),
            "extract_count": len(extract_blocks),
            "verbatim_count": len(verbatim_blocks),
            "compact_count": compacted,
            "digests_rendered": bool(digest_block),
            # Every document is named in the rollup, whatever else fit.
            "coverage_fraction": 1.0 if candidates else 0.0,
        },
    )


def _overflowing(used_tokens: int, max_tokens: int, used_bytes: int, max_bytes: int) -> str | None:
    """Which ceiling a prospective admission would breach, if any.

    Tokens are checked first here, matching the order this strategy has always reported
    them in — the constraint set is order-independent, but which one gets recorded when
    both would bind is not.
    """
    if used_tokens > max_tokens:
        return "tokens"
    if used_bytes > max_bytes:
        return "bytes"
    return None


def _assemble(
    rollup: str,
    digest_block: str,
    extract_blocks: Sequence[tuple[ContextDocument, str]],
    verbatim_blocks: Sequence[tuple[ContextDocument, str]],
    render_order: str,
) -> str:
    """Join the tiers, ordering each detail tier for prompt-cache stability."""
    parts: list[str] = []
    if rollup:
        parts.append(rollup)
    if digest_block:
        parts.append(digest_block)
    for group in (extract_blocks, verbatim_blocks):
        pairs = list(group)
        if render_order != "rank":
            pairs.sort(key=lambda pair: (pair[0].path, pair[0].sha256))
        parts.extend(block for _, block in pairs)
    return "\n".join(parts)


def _sorted_for_render(
    documents: Sequence[ContextDocument], render_order: str
) -> list[ContextDocument]:
    if render_order == "rank":
        return list(documents)
    return sorted(documents, key=lambda d: (d.path, d.sha256))


def _render_rollup(
    documents: Sequence[ContextDocument],
    *,
    max_tokens: int,
    max_bytes: int,
    estimator: TokenEstimator,
) -> tuple[str, int, int]:
    """Render the deepest module rollup that fits its share of the budget.

    Sweeps grouping depth from deepest to shallowest, then degrades the symbol limit.
    The final attempt — depth 1 with no symbols — always renders even if it overruns:
    a corpus map is the one thing this strategy must never drop.
    """
    if not documents:
        return "", 0, 0

    max_depth = max(_depth(document.path) for document in documents)
    for depth in range(max_depth, 0, -1):
        rendered = _render_at(documents, depth=depth, symbol_limit=_SYMBOL_LIMIT_LADDER[0])
        tokens = estimator.estimate(rendered).tokens
        size = block_bytes(rendered)
        if tokens <= max_tokens and size <= max_bytes:
            return rendered, tokens, size

    for symbol_limit in _SYMBOL_LIMIT_LADDER[1:]:
        rendered = _render_at(documents, depth=1, symbol_limit=symbol_limit)
        tokens = estimator.estimate(rendered).tokens
        size = block_bytes(rendered)
        if tokens <= max_tokens and size <= max_bytes:
            return rendered, tokens, size

    rendered = _render_at(documents, depth=1, symbol_limit=0)
    return rendered, estimator.estimate(rendered).tokens, block_bytes(rendered)


def _render_at(documents: Sequence[ContextDocument], *, depth: int, symbol_limit: int) -> str:
    """Render every module at one grouping depth and symbol budget."""
    groups = _group_by_module(documents, depth=depth)
    total_bytes = sum(document.bytes_length for document in documents) or 1

    blocks: list[str] = []
    for module, members in sorted(groups.items(), key=lambda item: (-len(item[1]), item[0])):
        languages = sorted({m.language for m in members if m.language})
        share = sum(m.bytes_length for m in members) / total_bytes
        blocks.append(
            render_module_block(
                module,
                file_count=len(members),
                corpus_share=share,
                languages=languages,
                dependencies=_summarize(members, _DEPENDENCY_PREFIXES, symbol_limit),
                symbols=_summarize(members, _SYMBOL_PREFIXES, symbol_limit),
            )
        )
    return render_tiers(blocks, coverage_files=len(documents))


def _group_by_module(
    documents: Sequence[ContextDocument], *, depth: int
) -> dict[str, list[ContextDocument]]:
    """Group documents by their path prefix at ``depth`` segments."""
    groups: dict[str, list[ContextDocument]] = defaultdict(list)
    for document in documents:
        groups[_module_of(document.path, depth)].append(document)
    return dict(groups)


def _module_of(path: str, depth: int) -> str:
    parts = PurePosixPath(path).parts
    if len(parts) <= 1:
        return "."
    return "/".join(parts[: min(depth, len(parts) - 1)])


def _depth(path: str) -> int:
    return max(1, len(PurePosixPath(path).parts) - 1)


def _summarize(members: Sequence[ContextDocument], prefixes: Sequence[str], limit: int) -> str:
    """Collect distinct leading tokens from members' extracts, capped and deduplicated."""
    if limit <= 0:
        return ""
    seen: Counter[str] = Counter()
    for member in members:
        source = member.extract or ""
        for line in source.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            head = stripped.split(" ", 1)[0].rstrip(":")
            if head in prefixes:
                seen[_significant_token(stripped)] += 1

    # most_common ties break on insertion order, which depends on the order documents
    # were supplied in — sorting by (-count, name) keeps the rollup byte-identical
    # across corpus orderings, which is what prompt caches rely on.
    ranked = sorted(seen.items(), key=lambda item: (-item[1], item[0]))
    names = [name for name, _ in ranked[:limit] if name]
    if not names:
        return ""
    line = ", ".join(names)
    return line[:_LINE_LIMIT] if len(line) > _LINE_LIMIT else line


_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _significant_token(line: str) -> str:
    """The identifier a declaration line is about.

    The first identifier after the keywords that introduce it — ``async def resolve(self)``
    is about ``resolve``, not ``async``. Punctuation is excluded rather than trimmed, so a
    signature never leaks a dangling paren into the rollup.
    """
    identifiers: list[str] = _IDENTIFIER.findall(line)
    for name in identifiers:
        if name not in _DECLARATION_KEYWORDS:
            return name
    return identifiers[0] if identifiers else ""


_DECLARATION_KEYWORDS = frozenset(
    {
        "abstract",
        "async",
        "class",
        "const",
        "def",
        "enum",
        "export",
        "extension",
        "final",
        "fun",
        "function",
        "impl",
        "import",
        "interface",
        "internal",
        "let",
        "mixin",
        "mod",
        "module",
        "namespace",
        "object",
        "override",
        "package",
        "partial",
        "private",
        "protected",
        "pub",
        "public",
        "record",
        "require",
        "sealed",
        "static",
        "struct",
        "trait",
        "type",
        "typedef",
        "using",
        "var",
        "virtual",
        "from",
        "use",
    }
)
"""Words that introduce a declaration rather than naming it."""


def module_surfaces(documents: Sequence[ContextDocument], *, depth: int = 2) -> dict[str, str]:
    """Group a corpus into modules and render each one's surface text.

    Offered as a public helper for the app-side digest recipe: generate a summary per
    module with your own client, cache it keyed on the surface's digest, and hand the
    results back as ``module_digests``. Deterministic, so the cache key is stable.

    Args:
        documents: The corpus.
        depth: Path-prefix depth at which to group.

    Returns:
        Module path to concatenated extract (or content) text, in path order.
    """
    surfaces: dict[str, str] = {}
    for module, members in sorted(_group_by_module(documents, depth=depth).items()):
        ordered = sorted(members, key=lambda d: (d.path, d.sha256))
        surfaces[module] = "\n\n".join(
            f"{document.path}\n{document.extract or document.content}" for document in ordered
        )
    return surfaces
