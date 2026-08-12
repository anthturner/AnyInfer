"""Lexical relevance ranking.

A BM25-style scorer, deliberately lexical and dependency-free: term frequency saturated
and length-normalized, weighted by inverse document frequency, plus two signals that
matter a great deal in a code or document corpus and nothing in classical IR — a path
match outweighs a body match, and well-known anchor files (README, pyproject.toml,
ARCHITECTURE) get a small bonus.

**What this is not.** There are no embeddings and no semantic matching. That is a
deliberate boundary — see the concept documentation, and the reason ranking is exposed as
a function you can replace rather than hidden inside selection.

Three optional settings narrow the gap without an index or a model. **Identifier
splitting** tokenizes ``resolve_credentials`` as its parts as well as the whole, so a query
phrased in words matches an identifier phrased in code. **Query expansion** ranks once,
harvests distinctive terms from the strongest documents, and re-ranks, which does find
"login" from "authentication" whenever the two co-occur anywhere in the corpus. And
**centrality** scores a document by its position in the corpus's own import graph, a
query-independent signal that is what orders a corpus when the query is weak or absent.

Tokenization is ASCII alphanumeric. Ranking is fully deterministic: ties break on path
depth, then path, then digest, so the same corpus and query always produce the same order
regardless of the order documents were supplied in.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from pathlib import PurePosixPath
from typing import Protocol

from .documents import ContextDocument, RankCache
from .settings import DEFAULT_TUNING, ContextTuning

__all__ = [
    "ANCHOR_NAMES",
    "ANCHOR_SCORE",
    "LENGTH_NORMALIZATION",
    "PATH_MATCH_WEIGHT",
    "STOP_WORDS",
    "TERM_SATURATION",
    "SemanticRanker",
    "build_rank_cache",
    "expand_query",
    "query_terms",
    "rank",
    "salience",
    "score_document",
    "scores_for",
    "tokenize",
]

_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]+")
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")

STOP_WORDS = frozenset(
    {
        "a",
        "about",
        "all",
        "an",
        "and",
        "any",
        "are",
        "as",
        "at",
        "be",
        "been",
        "but",
        "by",
        "can",
        "do",
        "does",
        "for",
        "from",
        "get",
        "has",
        "have",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "please",
        "should",
        "so",
        "some",
        "than",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "this",
        "to",
        "use",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
    }
)
"""Words carrying no retrieval signal, dropped from queries and documents alike."""

TERM_SATURATION = 1.2
"""BM25's ``k1``: how fast repeated occurrences of a term stop adding score."""

LENGTH_NORMALIZATION = 0.001
"""Penalty per token of document length, so a long file cannot win on volume alone."""

PATH_MATCH_WEIGHT = 4.0
"""How much more a query term in the path counts than the same term in the body.

Deliberately large: someone asking about ``credentials`` almost always means the file
named for it, even when a dozen other files mention the word more often.
"""

ANCHOR_SCORE = 0.25
"""Bonus for files that orient a reader regardless of the query."""

ANCHOR_NAMES = frozenset(
    {
        "architecture",
        "changelog",
        "contributing",
        "design",
        "overview",
        "readme",
        "cargo.toml",
        "go.mod",
        "package.json",
        "pom.xml",
        "pyproject.toml",
    }
)
"""Filenames (and stems) worth a small unconditional boost."""


def tokenize(text: str, *, split_identifiers: bool = False) -> list[str]:
    """Split text into lowercase alphanumeric terms, dropping stop words.

    ASCII-only by design — the tradeoff is stated in the module documentation.

    Args:
        text: What to tokenize.
        split_identifiers: Also emit the parts of compound identifiers.
            ``resolveCredentials`` and ``resolve_credentials`` both yield the compound
            *and* ``resolve`` and ``credentials``, so a query written in words matches an
            identifier written in code. The compound is kept as well, so an exact match on
            the full identifier still scores highest.

    Returns:
        The terms, in order of appearance.
    """
    tokens: list[str] = []
    for raw in _TOKEN_PATTERN.findall(text):
        token = raw.lower()
        if token not in STOP_WORDS:
            tokens.append(token)
        if not split_identifiers:
            continue
        for part in _split_identifier(raw):
            if part != token and part not in STOP_WORDS:
                tokens.append(part)
    return tokens


def _split_identifier(raw: str) -> list[str]:
    """Break a compound identifier into its lowercase parts.

    Handles ``camelCase``, ``PascalCase``, ``SCREAMING_SNAKE``, and the acronym boundary
    in ``HTTPServer``, which splits as ``http`` and ``server``, not ``h`` and
    ``ttpserver``.
    """
    parts: list[str] = []
    for chunk in raw.split("_"):
        if not chunk:
            continue
        parts.extend(piece.lower() for piece in _CAMEL_BOUNDARY.split(chunk) if piece)
    return parts if len(parts) > 1 else []


def build_rank_cache(
    documents: Iterable[ContextDocument], *, split_identifiers: bool = False
) -> RankCache:
    """Precompute term statistics for a corpus.

    Pass the result to `rank()` on subsequent queries over the same corpus. The caller
    owns invalidation; see `RankCache`.

    Args:
        documents: The corpus.
        split_identifiers: Tokenize compound identifiers into their parts as well. Must
            match the setting ranking will use; `rank()` rebuilds a cache that disagrees.

    Returns:
        The statistics.
    """
    term_counts: dict[str, Counter[str]] = {}
    document_frequency: Counter[str] = Counter()
    document_lengths: dict[str, int] = {}
    total = 0

    for document in documents:
        tokens = tokenize(document.content, split_identifiers=split_identifiers)
        counts = Counter(tokens)
        term_counts[document.path] = counts
        document_lengths[document.path] = len(tokens)
        document_frequency.update(counts.keys())
        total += 1

    return RankCache(
        term_counts=term_counts,
        document_frequency=document_frequency,
        document_lengths=document_lengths,
        total_documents=total,
        split_identifiers=split_identifiers,
    )


def score_document(
    document: ContextDocument,
    query_terms: Mapping[str, float],
    cache: RankCache,
) -> float:
    """Score one document against a query.

    Args:
        document: The candidate.
        query_terms: Query terms mapped to their weights. ``Counter(tokenize(query))``
            for a plain query; `expand_query` produces a weighted one.
        cache: Corpus statistics covering this document.

    Returns:
        A non-negative relevance score. Zero means nothing matched, which is still a
        valid candidate, just an unranked one.
    """
    counts = cache.term_counts.get(document.path, Counter())
    length = cache.document_lengths.get(document.path, 0)
    path_terms = Counter(tokenize(document.path, split_identifiers=cache.split_identifiers))

    score = 0.0
    for term, weight in query_terms.items():
        document_frequency = cache.document_frequency.get(term, 0)
        idf = math.log((cache.total_documents + 1) / (document_frequency + 1)) + 1.0

        frequency = counts.get(term, 0)
        if frequency:
            saturated = frequency / (frequency + TERM_SATURATION + LENGTH_NORMALIZATION * length)
            score += weight * idf * saturated

        in_path = path_terms.get(term, 0)
        if in_path:
            score += weight * in_path * PATH_MATCH_WEIGHT

    if _is_anchor(document.path):
        score += ANCHOR_SCORE
    return score


def query_terms(query: str, *, tuning: ContextTuning = DEFAULT_TUNING) -> dict[str, float]:
    """Tokenize a query into weighted terms, without expansion.

    The base a `expand_query` call starts from, and what `score_document` wants when no
    expansion is configured.
    """
    return {
        term: float(count)
        for term, count in Counter(
            tokenize(query, split_identifiers=tuning.split_identifiers)
        ).items()
    }


def expand_query(
    query: str,
    documents: Sequence[ContextDocument],
    *,
    cache: RankCache,
    tuning: ContextTuning = DEFAULT_TUNING,
) -> dict[str, float]:
    """Add distinctive terms from the strongest documents to the query.

    Pseudo-relevance feedback: rank once against the query as written, take the top
    documents on faith, and harvest the terms that make them distinctive — high frequency
    within that set, low frequency across the corpus. Those terms join the query at a
    reduced weight and everything is ranked again.

    This is the lexical answer to vocabulary mismatch. It has no index and no model, and
    it finds a file that says "login" from a query that says "authentication" whenever
    some document in the corpus uses both. It also inherits the classic failure mode: if
    the top documents are wrong, expansion makes them wronger, which is why
    ``expansion_weight`` defaults well below one.

    Args:
        query: The query as written.
        documents: The corpus.
        cache: Statistics for that corpus.
        tuning: Supplies ``expansion_terms``, ``feedback_documents``, and
            ``expansion_weight``.

    Returns:
        Term weights, with the original query terms at full weight. Returns the
        unexpanded terms when expansion is disabled, the query is empty, or the corpus
        has nothing to harvest.
    """
    base = query_terms(query, tuning=tuning)
    if (
        not tuning.query_expansion
        or not base
        or not documents
        or tuning.expansion_terms < 1
        or tuning.feedback_documents < 1
        or tuning.expansion_weight <= 0
    ):
        return base

    scored = sorted(
        ((score_document(document, base, cache), document) for document in documents),
        key=lambda pair: (-pair[0], pair[1].path, pair[1].sha256),
    )
    feedback = [document for score, document in scored[: tuning.feedback_documents] if score > 0]
    if not feedback:
        return base

    weights: dict[str, float] = {}
    for document in feedback:
        counts = cache.term_counts.get(document.path)
        if not counts:
            continue
        length = max(1, cache.document_lengths.get(document.path, 1))
        for term, frequency in counts.items():
            if term in base:
                continue
            document_frequency = cache.document_frequency.get(term, 0)
            idf = math.log((cache.total_documents + 1) / (document_frequency + 1)) + 1.0
            weights[term] = weights.get(term, 0.0) + (frequency / length) * idf

    if not weights:
        return base

    ranked = sorted(weights.items(), key=lambda item: (-item[1], item[0]))
    top = ranked[: tuning.expansion_terms]
    ceiling = top[0][1] or 1.0

    expanded = dict(base)
    for term, weight in top:
        expanded[term] = tuning.expansion_weight * (weight / ceiling)
    return expanded


def salience(
    documents: Sequence[ContextDocument],
    *,
    tuning: ContextTuning = DEFAULT_TUNING,
) -> dict[str, float]:
    """Score documents by their centrality in the corpus's own import graph.

    An edge runs from a document to every document whose filename stem it imports. The
    stationary distribution of a damped random walk over those edges answers "what does
    this corpus depend on?", which is query-independent, and therefore what orders a
    corpus when the query is weak or missing entirely. Ranking with an empty query
    otherwise falls through to the path tie-break, which is arbitrary.

    Args:
        documents: The corpus.
        tuning: Supplies ``salience_damping`` and ``salience_iterations``.

    Returns:
        Path to a score in ``[0, 1]``, normalized so the most central document scores
        one. An empty mapping when the corpus has no resolvable edges at all, so callers
        can skip the blend entirely.
    """
    from .structure import imported_names

    paths = sorted(document.path for document in documents)
    if len(paths) < 2:
        return {}

    by_stem: dict[str, list[str]] = {}
    for path in paths:
        by_stem.setdefault(_stem(path), []).append(path)

    edges: dict[str, list[str]] = {}
    for document in sorted(documents, key=lambda d: d.path):
        targets: set[str] = set()
        for name in imported_names(document.content, language=document.language):
            targets.update(by_stem.get(name, ()))
        targets.discard(document.path)
        if targets:
            edges[document.path] = sorted(targets)

    if not edges:
        return {}

    count = len(paths)
    uniform = 1.0 / count
    scores = dict.fromkeys(paths, uniform)
    damping = tuning.salience_damping

    for _ in range(tuning.salience_iterations):
        incoming = dict.fromkeys(paths, 0.0)
        dangling = 0.0
        for path in paths:
            outgoing = edges.get(path)
            if not outgoing:
                dangling += scores[path]
                continue
            share = scores[path] / len(outgoing)
            for target in outgoing:
                incoming[target] += share
        spread = dangling / count
        scores = {
            path: (1.0 - damping) * uniform + damping * (incoming[path] + spread) for path in paths
        }

    ceiling = max(scores.values())
    if ceiling <= 0:
        return {}
    return {path: value / ceiling for path, value in scores.items()}


def _stem(path: str) -> str:
    """The name another document would import this one by.

    A package's ``__init__`` is imported by its directory name, not by ``__init__``.
    """
    pure = PurePosixPath(path.lower())
    if pure.stem in ("__init__", "index", "mod"):
        parents = pure.parent.name
        return parents or pure.stem
    return pure.stem


class SemanticRanker(Protocol):
    """Caller-supplied relevance scoring for context reduction.

    The default ranking is lexical and offline on purpose; this protocol is the opt-in
    seam for a semantic ranker backed by a rerank model. Scores are keyed by
    `ContextDocument.path` — a document absent from the mapping scores 0.0. Scores are
    only compared against each other within one call, never persisted.

    Implementations live *outside* this package (context reduction is a leaf consumer
    and never imports the client); `anyinfer.semantic_ranker` builds one from a client
    and a rerank target.
    """

    def scores(self, documents: Sequence[ContextDocument], query: str) -> Mapping[str, float]:
        """Score every document's relevance to ``query``, keyed by document path."""
        ...


def rank(
    documents: Sequence[ContextDocument],
    query: str,
    *,
    rank_cache: RankCache | None = None,
    tuning: ContextTuning = DEFAULT_TUNING,
    carry_over: Iterable[str] = (),
) -> list[ContextDocument]:
    """Order documents by relevance, pinned ones first.

    Args:
        documents: The corpus.
        query: What the app is asking about. An empty query ranks everything at zero,
            leaving the deterministic tie-break as the order — unless
            ``tuning.salience_weight`` is set, which is exactly what that setting is for.
        rank_cache: Precomputed statistics for this corpus; built on the fly when absent,
            and rebuilt when its tokenization disagrees with ``tuning``.
        tuning: Advanced settings. Defaults reproduce the plain lexical ranker.
        carry_over: Paths an earlier reduction already sent unchanged. Each receives
            ``tuning.carry_over_bonus``, which keeps a turn's selection, and therefore
            its rendered prefix — stable enough for a prompt cache to hit.

    Returns:
        A new list, most relevant first. Ordering is total and deterministic: every
        pinned document precedes every unpinned one, then higher score, then shallower
        path, then path, then digest.
    """
    cache = (
        rank_cache
        if rank_cache is not None
        else build_rank_cache(documents, split_identifiers=tuning.split_identifiers)
    )
    if cache.split_identifiers != tuning.split_identifiers:
        cache = build_rank_cache(documents, split_identifiers=tuning.split_identifiers)

    terms = expand_query(query, documents, cache=cache, tuning=tuning)
    central = salience(documents, tuning=tuning) if tuning.salience_weight > 0 else {}
    carried = frozenset(carry_over)

    scored = [(document, score_document(document, terms, cache)) for document in documents]
    if central:
        scored = [
            (document, score + tuning.salience_weight * central.get(document.path, 0.0))
            for document, score in scored
        ]
    if carried and tuning.carry_over_bonus > 0:
        scored = [
            (
                document,
                score + (tuning.carry_over_bonus if document.path in carried else 0.0),
            )
            for document, score in scored
        ]

    scored.sort(
        key=lambda pair: (
            not pair[0].pinned,
            -pair[1],
            pair[0].path.count("/"),
            pair[0].path,
            pair[0].sha256,
        )
    )
    return [document for document, _ in scored]


def scores_for(
    documents: Sequence[ContextDocument],
    query: str,
    *,
    cache: RankCache,
    tuning: ContextTuning = DEFAULT_TUNING,
) -> dict[str, float]:
    """Relevance scores keyed by path, for selectors that need magnitudes not order.

    `rank()` returns an ordering, which is all a greedy fill needs. Density ordering and
    the diversity penalty need the numbers themselves.
    """
    terms = expand_query(query, documents, cache=cache, tuning=tuning)
    central = salience(documents, tuning=tuning) if tuning.salience_weight > 0 else {}
    return {
        document.path: score_document(document, terms, cache)
        + tuning.salience_weight * central.get(document.path, 0.0)
        for document in documents
    }


def _is_anchor(path: str) -> bool:
    """Whether a path names a file that orients a reader regardless of the query."""
    name = PurePosixPath(path.lower()).name
    return name in ANCHOR_NAMES or PurePosixPath(name).stem in ANCHOR_NAMES
