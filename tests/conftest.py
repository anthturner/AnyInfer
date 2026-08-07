"""Shared fixtures.

Tests use the in-process fakes rather than sockets, so the suite is deterministic and
identical on every platform.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from anyinfer.redaction import registry as redaction_registry


@pytest.fixture(autouse=True)
def _clean_redaction_registry() -> Iterator[None]:
    """Keep secrets registered by one test from leaking into another's assertions."""
    redaction_registry.clear()
    yield
    redaction_registry.clear()
