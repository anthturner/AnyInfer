"""Tests for private native core-driver proof predicates."""

from __future__ import annotations

import asyncio

import pytest

from . import proofs
from .adapter import HarnessError
from .proofs import CORE_DRIVER_RECIPE_IDS, run_core_driver_assertion


@pytest.mark.asyncio
@pytest.mark.parametrize("recipe_ref", CORE_DRIVER_RECIPE_IDS[:2])
async def test_native_core_proofs_return_nonempty_identity_bound_evidence(recipe_ref: str) -> None:
    result = await run_core_driver_assertion(recipe_ref)
    assert result["id"] == recipe_ref
    assert result["verdict"] == "pass", result["detail"]
    assert result["detail"] is None
    evidence = result["evidence"]
    assert evidence is not None
    assert evidence["recipe_ref"] == recipe_ref
    assert evidence["observations"]


@pytest.mark.asyncio
async def test_unknown_recipe_is_a_harness_error() -> None:
    with pytest.raises(HarnessError, match="unknown core driver recipe"):
        await run_core_driver_assertion("driver/http-correction-byte-budget-reset")


@pytest.mark.asyncio
async def test_dispatcher_does_not_convert_cancellation_to_a_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    async def cancelled() -> dict[str, object]:
        raise asyncio.CancelledError()

    monkeypatch.setattr(proofs, "_concurrent_operations", cancelled)
    with pytest.raises(asyncio.CancelledError):
        await run_core_driver_assertion("driver/concurrent-operations-independent")
