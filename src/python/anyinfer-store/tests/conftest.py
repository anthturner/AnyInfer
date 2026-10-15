"""Shared fixtures for the vector-store suite."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from anyinfer_store import VectorStore


@pytest.fixture
def open_store() -> Iterator[Callable[[str | Path], VectorStore]]:
    """Open a `VectorStore` that closes itself when the test ends.

    `VectorStore` has `close()` and works as a context manager, but a test that opens two
    stores to compare them reads worse nested, so most of this suite opened them bare and
    left the SQLite connections to the garbage collector. From Python 3.13 that raises
    `ResourceWarning: unclosed database` at collection time, which this project's
    warnings-as-errors turns into a failure — attributed to whichever unlucky test was
    running when the collector fired, not to the one that leaked.

    Registering here keeps the call sites as short as `VectorStore.open` was, and a test
    added later cannot forget the teardown.
    """
    opened: list[VectorStore] = []

    def _open(path: str | Path) -> VectorStore:
        store = VectorStore.open(path)
        opened.append(store)
        return store

    yield _open

    for store in opened:
        store.close()
