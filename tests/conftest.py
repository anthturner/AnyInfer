"""Shared fixtures.

Tests use the in-process fakes rather than sockets, so the suite is deterministic and
identical on every platform.
"""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from anyinfer.redaction import registry as redaction_registry


@pytest.fixture(autouse=True)
def _clean_redaction_registry() -> Iterator[None]:
    """Keep secrets registered by one test from leaking into another's assertions."""
    redaction_registry.clear()
    yield
    redaction_registry.clear()


@asynccontextmanager
async def _build_adapter(
    provider_id: str, *, base_url: str = "https://fake.invalid/v1", **options: object
) -> AsyncIterator[Any]:
    """Build one provider's adapter and close it, whatever the test does with it.

    Building an adapter is not free of resources: each opens an HTTP client, which on a
    default trust store opens CA files, and a local engine's adapter can supervise a child
    process. Dropped rather than closed, those surface as unraisable exceptions during
    whichever test the garbage collector happens to interrupt — so the failure lands on
    innocent code, in another file, on some interpreters and some shardings only. One such
    leak cost an afternoon; this exists so the next one cannot.

    Required whenever the provider is one that may own more than an HTTP client — the
    Copilot adapter spawns a CLI process, and a mock transport does nothing about a child
    process. A helper that builds only HTTP-dialect adapters against a mock transport
    holds no OS resources and does not need this.

    Yields ``None`` when the provider cannot be constructed from these settings, which
    lets a registry-walking test skip it without a try/except of its own.
    """
    from anyinfer.providers.base import ProviderConfig
    from anyinfer.registry import default_registry

    try:
        adapter = default_registry.get(provider_id).factory(
            ProviderConfig(provider_id=provider_id, base_url=base_url, **options)  # type: ignore[arg-type]
        )
    except Exception:
        yield None
        return
    try:
        yield adapter
    finally:
        closer = getattr(adapter, "aclose", None)
        if closer is not None:
            await closer()


@pytest.fixture
def built_adapter():
    """Hand a test the adapter builder that closes what it builds.

    A fixture rather than an import because ``tests`` is not a package, so a module-level
    import of a conftest helper works only by accident of ``sys.path``.
    """
    return _build_adapter
