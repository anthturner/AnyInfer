"""Lexical relevance ranking.

A BM25-style scorer, deliberately lexical and dependency-free: term frequency saturated
and length-normalized, weighted by inverse document frequency, plus two signals that
matter a great deal in a code or document corpus and nothing in classical IR — a path
match outweighs a body match, and well-known anchor files (README, pyproject.toml,
ARCHITECTURE) get a small bonus.

**What this is not.** There are no embeddings and no semantic matching: a query for
"authentication" will not find a file that only says "login". That is a deliberate
boundary — see the concept documentation — and the reason ranking is exposed as a
function you can replace rather than hidden inside selection.

Tokenization is ASCII alphanumeric. Ranking is fully deterministic: ties break on path
depth, then path, then digest, so the same corpus and query always produce the same order
regardless of the order documents were supplied in.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from pathlib import PurePosixPath

from .documents import ContextDocument, RankCache

__all__ = [
    "ANCHOR_NAMES",
    "ANCHOR_SCORE",
    "LENGTH_NORMALIZATION",
    "PATH_MATCH_WEIGHT",
    "STOP_WORDS",
    "TERM_SATURATION",
    "build_rank_cache",
    "rank",
    "score_document",
    "tokenize",
]

_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]+")

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


def tokenize(text: str) -> list[str]:
    """Split text into lowercase alphanumeric terms, dropping stop words.

    ASCII-only by design — the tradeoff is stated in the module documentation.
    """
    return [
        token for raw in _TOKEN_PATTERN.findall(text) if (token := raw.lower()) not in STOP_WORDS
    ]


def build_rank_cache(documents: Iterable[ContextDocument]) -> RankCache:
    """Precompute term statistics for a corpus.

    Pass the result to `rank()` on subsequent queries over the same corpus. The caller
    owns invalidation; see `RankCache`.
    """
    term_counts: dict[str, Counter[str]] = {}
    document_frequency: Counter[str] = Counter()
    document_lengths: dict[str, int] = {}
    total = 0

    for document in documents:
        tokens = tokenize(document.content)
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
    )


def score_document(
    document: ContextDocument,
    query_terms: Counter[str],
    cache: RankCache,
) -> float:
    """Score one document against a query.

    Args:
        document: The candidate.
        query_terms: Query term frequencies, from ``Counter(tokenize(query))``.
        cache: Corpus statistics covering this document.

    Returns:
        A non-negative relevance score. Zero means nothing matched — which is still a
        valid candidate, just an unranked one.
    """
    counts = cache.term_counts.get(document.path, Counter())
    length = cache.document_lengths.get(document.path, 0)
    path_terms = Counter(tokenize(document.path))

    score = 0.0
    for term, query_frequency in query_terms.items():
        document_frequency = cache.document_frequency.get(term, 0)
        idf = math.log((cache.total_documents + 1) / (document_frequency + 1)) + 1.0

        frequency = counts.get(term, 0)
        if frequency:
            saturated = frequency / (frequency + TERM_SATURATION + LENGTH_NORMALIZATION * length)
            score += query_frequency * idf * saturated

        in_path = path_terms.get(term, 0)
        if in_path:
            score += query_frequency * in_path * PATH_MATCH_WEIGHT

    if _is_anchor(document.path):
        score += ANCHOR_SCORE
    return score


def rank(
    documents: Sequence[ContextDocument],
    query: str,
    *,
    rank_cache: RankCache | None = None,
) -> list[ContextDocument]:
    """Order documents by relevance, pinned ones first.

    Args:
        documents: The corpus.
        query: What the app is asking about. An empty query ranks everything at zero,
            leaving the deterministic tie-break as the order.
        rank_cache: Precomputed statistics for this corpus; built on the fly when absent.

    Returns:
        A new list, most relevant first. Ordering is total and deterministic: every
        pinned document precedes every unpinned one, then higher score, then shallower
        path, then path, then digest.
    """
    cache = rank_cache if rank_cache is not None else build_rank_cache(documents)
    query_terms = Counter(tokenize(query))

    scored = [(document, score_document(document, query_terms, cache)) for document in documents]
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


def _is_anchor(path: str) -> bool:
    """Whether a path names a file that orients a reader regardless of the query."""
    name = PurePosixPath(path.lower()).name
    return name in ANCHOR_NAMES or PurePosixPath(name).stem in ANCHOR_NAMES
