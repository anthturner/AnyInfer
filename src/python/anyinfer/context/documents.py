"""The corpus input type and the ranking cache.

A `ContextDocument` is inert data: a path, its content, and enough identity to render and
deduplicate it. The library never reads one off disk — collecting documents, deciding
which are safe to send, and applying ignore rules are all app-side concerns, because that
is where the security policy lives and where every application differs.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass, field

__all__ = ["ContextDocument", "RankCache"]


@dataclass(frozen=True, slots=True)
class ContextDocument:
    """One document offered to the reducer.

    Attributes:
        path: POSIX-style relative path. Doubles as identity and as a ranking signal —
            a query term matching the path outweighs the same term in the body.
        content: The document's text.
        sha256: Hex digest of ``content``, used for identity in rendered envelopes and
            for deterministic tie-breaking.
        pinned: Sorts before every unpinned document and is selected first. This is how
            an app says "the user explicitly chose this file".
        language: Language name for rendering and rollups, detected when omitted.
        extract: A structural summary (signatures, imports, headings) used by the
            ``tiered`` strategy when the whole document does not fit. Empty means none.
    """

    path: str
    content: str
    sha256: str
    pinned: bool = False
    language: str | None = None
    extract: str = ""

    @classmethod
    def of(
        cls,
        path: str,
        content: str,
        *,
        pinned: bool = False,
        language: str | None = None,
        extract: str | None = None,
    ) -> ContextDocument:
        """Build a document, computing its digest and filling in what was omitted.

        Args:
            path: POSIX-style relative path.
            content: The document's text.
            pinned: Whether the document must be included ahead of ranked candidates.
            language: Overrides language detection.
            extract: Overrides extraction. Pass ``""`` to opt out of it entirely;
                omit it to have one derived from the content.

        Returns:
            The document, with ``sha256`` computed and language/extract derived unless
            they were supplied.
        """
        from .structure import detect_language, structural_extract

        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        resolved_language = language if language is not None else detect_language(path)
        if extract is None:
            resolved_extract = structural_extract(content, language=resolved_language)
        else:
            resolved_extract = extract
        return cls(
            path=path,
            content=content,
            sha256=digest,
            pinned=pinned,
            language=resolved_language,
            extract=resolved_extract,
        )

    @property
    def bytes_length(self) -> int:
        """UTF-8 byte length of the content."""
        return len(self.content.encode("utf-8"))


@dataclass(frozen=True, slots=True)
class RankCache:
    """Precomputed term statistics for one corpus.

    Ranking a corpus repeatedly — as an interactive app does on every turn — otherwise
    re-tokenizes every document each time. Build one with
    `anyinfer.context.rank.build_rank_cache()` and pass it back in.

    Validity is the caller's responsibility: key it on a corpus hash and rebuild when
    the corpus changes. Passing a cache built from *different* documents produces
    undefined ranking rather than an error, which is why the cache is not consulted for
    document identity.

    Attributes:
        term_counts: Per-document term frequencies, keyed by document path.
        document_frequency: How many documents contain each term.
        document_lengths: Total token count per document, for length normalization.
        total_documents: Corpus size, for the inverse-document-frequency term.
        split_identifiers: Which tokenization produced these counts. Ranking checks it
            and rebuilds rather than scoring a query tokenized one way against statistics
            gathered the other — a mismatch there produces plausible, wrong ordering.
    """

    term_counts: dict[str, Counter[str]] = field(default_factory=dict)
    document_frequency: Counter[str] = field(default_factory=Counter)
    document_lengths: dict[str, int] = field(default_factory=dict)
    total_documents: int = 0
    split_identifiers: bool = False
