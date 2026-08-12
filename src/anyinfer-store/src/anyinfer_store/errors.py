"""Exception hierarchy for `anyinfer_store`."""

from __future__ import annotations

__all__ = ["EmbeddingSpaceMismatchError", "VectorStoreError"]


class VectorStoreError(Exception):
    """Base class for every error this package raises."""


class EmbeddingSpaceMismatchError(VectorStoreError):
    """A vector was added or queried against a store bound to a different embedding space.

    The same cross-space safety rule `anyinfer`'s own routing applies, extended to
    persistence: a wrong-but-plausible vector comparison fails loudly rather than
    returning a confident-looking, meaningless result.
    """
