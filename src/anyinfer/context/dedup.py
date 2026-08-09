"""Duplicate collapse: send repeated material once.

Real corpora repeat themselves. Vendored copies, generated siblings, a file forked and
lightly edited, the same license header on four hundred files — a reducer that ranks them
independently will happily spend a whole budget on eight renderings of the same thing.

Two mechanisms, deliberately separated by whether they lose anything:

**Exact collapse** groups byte-identical documents and renders one, pointing the rest at
it. Nothing is lost, so it is on by default.

**Near collapse** estimates Jaccard similarity over word shingles and groups documents
above a threshold. The near-duplicate's *differences* are then not sent, which is a real
loss of fidelity, so it is off unless asked for. Pinned documents are never collapsed this
way: pinning means "the user chose this file", and its differences are the reason.

Similarity is estimated with MinHash over banded signatures rather than compared pairwise,
so a corpus of thousands costs a linear pass instead of a quadratic one. Hashing is
`hashlib`-based rather than `hash()`-based, because `hash()` on `str` is salted per process
and this must produce the same grouping on every run.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from .documents import ContextDocument
from .rank import tokenize
from .settings import DEFAULT_TUNING, ContextTuning

__all__ = ["DuplicateMap", "find_duplicates"]

_SIGNATURE_SIZE = 64
"""MinHash permutations. Enough to estimate Jaccard within a few percent."""

_BAND_ROWS = 4
"""Rows per band. Four rows over sixteen bands finds pairs above roughly 0.7 similarity."""

_PRIME = (1 << 61) - 1
"""Mersenne prime modulus for the permutation family."""


@dataclass(frozen=True, slots=True)
class DuplicateMap:
    """Which documents were collapsed into which.

    Attributes:
        canonical: Duplicate path to the path that represents it. A path absent from this
            mapping is itself canonical.
        exact: Paths collapsed because they were byte-identical, as opposed to merely
            similar. Rendering distinguishes the two, because one is lossless and the
            other is not.
    """

    canonical: Mapping[str, str] = field(default_factory=dict)
    exact: frozenset[str] = frozenset()

    def __bool__(self) -> bool:
        """Whether anything was collapsed at all."""
        return bool(self.canonical)

    @property
    def collapsed_count(self) -> int:
        """How many documents are represented by another."""
        return len(self.canonical)

    def is_exact(self, path: str) -> bool:
        """Whether ``path`` was collapsed losslessly."""
        return path in self.exact

    def members(self, canonical_path: str) -> tuple[str, ...]:
        """Paths collapsed into ``canonical_path``, in path order."""
        return tuple(
            sorted(path for path, target in self.canonical.items() if target == canonical_path)
        )


def find_duplicates(
    documents: Sequence[ContextDocument],
    *,
    tuning: ContextTuning = DEFAULT_TUNING,
) -> DuplicateMap:
    """Group duplicate documents and choose one representative for each group.

    Args:
        documents: The corpus.
        tuning: Supplies ``collapse_duplicates``, ``near_duplicate_threshold``, and
            ``shingle_size``.

    Returns:
        The `DuplicateMap`. Empty when both mechanisms are disabled, when the corpus has
        fewer than two documents, or when nothing repeated.
    """
    if len(documents) < 2:
        return DuplicateMap()

    groups: list[list[ContextDocument]] = []

    if tuning.collapse_duplicates:
        groups.extend(_exact_groups(documents))

    if tuning.near_duplicate_threshold > 0:
        # Near grouping runs over exact-group representatives so an exact pair is never
        # re-discovered as a near pair and given a second, conflicting canonical.
        represented = {document.path for group in groups for document in group[1:]}
        remaining = [
            document
            for document in documents
            if document.path not in represented and not document.pinned
        ]
        groups.extend(
            _near_groups(
                remaining,
                threshold=tuning.near_duplicate_threshold,
                shingle_size=tuning.shingle_size,
            )
        )

    canonical: dict[str, str] = {}
    for group in groups:
        head, *rest = group
        for document in rest:
            canonical[document.path] = head.path

    # A document can be the near-duplicate of a document that is itself an exact
    # duplicate; resolve to the end of the chain so nothing points at something absent.
    resolved = {path: _resolve(path, canonical) for path in canonical}

    # Losslessness is a property of the bytes, not of which pass did the grouping: the
    # near pass also catches byte-identical files, and reporting those as merely similar
    # would understate the fidelity of a reduction that lost nothing.
    digests = {document.path: _digest(document) for document in documents}
    exact = frozenset(
        path for path, target in resolved.items() if digests[path] == digests[target]
    )
    return DuplicateMap(canonical=resolved, exact=exact)


def _resolve(path: str, canonical: Mapping[str, str], *, limit: int = 8) -> str:
    """Follow a duplicate chain to the document that is actually rendered."""
    seen = {path}
    current = canonical[path]
    for _ in range(limit):
        target = canonical.get(current)
        if target is None or target in seen:
            return current
        seen.add(current)
        current = target
    return current


def _exact_groups(documents: Sequence[ContextDocument]) -> list[list[ContextDocument]]:
    """Group byte-identical documents, representative first."""
    by_digest: dict[str, list[ContextDocument]] = {}
    for document in documents:
        by_digest.setdefault(_digest(document), []).append(document)
    return [
        sorted(members, key=_canonical_key)
        for _, members in sorted(by_digest.items())
        if len(members) > 1
    ]


def _digest(document: ContextDocument) -> str:
    """Content identity, computed when the document was built without one."""
    if document.sha256:
        return document.sha256
    return hashlib.sha256(document.content.encode("utf-8")).hexdigest()


def _canonical_key(document: ContextDocument) -> tuple[bool, int, str, str]:
    """Order a duplicate group so the representative is the least surprising member.

    Pinned first — an app that chose a file should see the file it chose named in the
    envelope — then the shallowest path, then path, then digest. Total and deterministic,
    the same rule ranking uses for its tie-break.
    """
    return (not document.pinned, document.path.count("/"), document.path, document.sha256)


def _near_groups(
    documents: Sequence[ContextDocument],
    *,
    threshold: float,
    shingle_size: int,
) -> list[list[ContextDocument]]:
    """Group documents whose estimated Jaccard similarity meets ``threshold``."""
    if len(documents) < 2:
        return []

    shingles: dict[str, frozenset[int]] = {}
    signatures: dict[str, tuple[int, ...]] = {}
    for document in documents:
        prints = _shingles(document.content, shingle_size)
        if not prints:
            continue
        shingles[document.path] = prints
        signatures[document.path] = _signature(prints)

    candidates = _candidate_pairs(signatures)
    parent: dict[str, str] = {path: path for path in shingles}
    for left, right in candidates:
        if _jaccard(shingles[left], shingles[right]) >= threshold:
            _union(parent, left, right)

    by_root: dict[str, list[ContextDocument]] = {}
    positions = {document.path: document for document in documents}
    for path in sorted(parent):
        by_root.setdefault(_find(parent, path), []).append(positions[path])

    return [
        sorted(members, key=_canonical_key)
        for _, members in sorted(by_root.items())
        if len(members) > 1
    ]


def _shingles(content: str, size: int) -> frozenset[int]:
    """Hash the document's overlapping word k-grams to 64-bit integers.

    Stop words are dropped first, so boilerplate prose and its lightly-reworded twin
    still land on the same shingles.
    """
    tokens = tokenize(content)
    if not tokens:
        return frozenset()
    if len(tokens) <= size:
        return frozenset({_hash64(" ".join(tokens))})
    return frozenset(
        _hash64(" ".join(tokens[index : index + size]))
        for index in range(len(tokens) - size + 1)
    )


def _hash64(text: str) -> int:
    """A stable 64-bit hash. Stable across processes, unlike ``hash()``."""
    return int.from_bytes(hashlib.blake2b(text.encode("utf-8"), digest_size=8).digest(), "big")


_PERMUTATIONS: tuple[tuple[int, int], ...] = tuple(
    (
        int.from_bytes(hashlib.blake2b(b"a%d" % index, digest_size=8).digest(), "big") % _PRIME
        or 1,
        int.from_bytes(hashlib.blake2b(b"b%d" % index, digest_size=8).digest(), "big") % _PRIME,
    )
    for index in range(_SIGNATURE_SIZE)
)
"""Fixed ``(a, b)`` coefficients for the hash family. Derived, not random, so a corpus
signs the same way in every process and on every platform."""


def _signature(prints: Iterable[int]) -> tuple[int, ...]:
    """Reduce a shingle set to its MinHash signature."""
    values = list(prints)
    return tuple(
        min((a * value + b) % _PRIME for value in values) for a, b in _PERMUTATIONS
    )


def _candidate_pairs(signatures: Mapping[str, tuple[int, ...]]) -> list[tuple[str, str]]:
    """Bucket signatures by band and return the pairs worth verifying exactly.

    Banding is what keeps this linear: two documents are compared in full only when some
    band of their signatures agrees, which similar documents almost always achieve and
    dissimilar ones almost never do.
    """
    buckets: dict[tuple[int, tuple[int, ...]], list[str]] = {}
    for path in sorted(signatures):
        signature = signatures[path]
        for band, start in enumerate(range(0, _SIGNATURE_SIZE, _BAND_ROWS)):
            buckets.setdefault((band, signature[start : start + _BAND_ROWS]), []).append(path)

    pairs: set[tuple[str, str]] = set()
    for members in buckets.values():
        if len(members) < 2:
            continue
        for index, left in enumerate(members):
            for right in members[index + 1 :]:
                pairs.add((left, right) if left < right else (right, left))
    return sorted(pairs)


def _jaccard(left: frozenset[int], right: frozenset[int]) -> float:
    """Exact Jaccard similarity of two shingle sets."""
    union = len(left | right)
    return len(left & right) / union if union else 0.0


def _find(parent: dict[str, str], path: str) -> str:
    """Union-find root, with path compression."""
    root = path
    while parent[root] != root:
        root = parent[root]
    while parent[path] != root:
        parent[path], path = root, parent[path]
    return root


def _union(parent: dict[str, str], left: str, right: str) -> None:
    """Merge two groups, keeping the lexicographically smaller root for determinism."""
    left_root, right_root = _find(parent, left), _find(parent, right)
    if left_root == right_root:
        return
    if right_root < left_root:
        left_root, right_root = right_root, left_root
    parent[right_root] = left_root
