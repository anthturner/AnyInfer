"""Tests for private native core-driver proof predicates."""

from __future__ import annotations

import asyncio

import pytest

from . import proof_transport, proofs
from .adapter import HarnessError
from .proofs import CORE_DRIVER_RECIPE_IDS, run_core_driver_assertion
from .values import MissingEvidenceError


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
        await run_core_driver_assertion("driver/not-a-real-recipe")


@pytest.mark.asyncio
async def test_dispatcher_does_not_convert_cancellation_to_a_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def cancelled() -> dict[str, object]:
        raise asyncio.CancelledError()

    monkeypatch.setattr(proofs, "_concurrent_operations", cancelled)
    with pytest.raises(asyncio.CancelledError):
        await run_core_driver_assertion("driver/concurrent-operations-independent")


@pytest.mark.asyncio
async def test_dispatcher_uses_transport_recipe_and_binds_nonempty_native_facts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed = {"correction": {"request_count": 2}, "streamed_overflow": {"mode": "stream"}}
    called: list[str] = []

    async def transport(recipe_ref: str) -> dict[str, object]:
        called.append(recipe_ref)
        return observed

    monkeypatch.setattr(proof_transport, "observe_transport_recipe", transport)
    result = await run_core_driver_assertion("driver/http-correction-byte-budget-reset")

    assert called == ["driver/http-correction-byte-budget-reset"]
    assert result == {
        "id": "driver/http-correction-byte-budget-reset",
        "verdict": "pass",
        "detail": None,
        "evidence": {
            "recipe_ref": "driver/http-correction-byte-budget-reset",
            "observations": observed,
        },
    }


@pytest.mark.asyncio
async def test_transport_recipe_assertion_and_missing_evidence_keep_distinct_verdicts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def predicate_failure(_recipe_ref: str) -> dict[str, object]:
        raise AssertionError("wrong native predicate")

    monkeypatch.setattr(proof_transport, "observe_transport_recipe", predicate_failure)
    failed = await run_core_driver_assertion("driver/http-correction-byte-budget-reset")
    assert failed["verdict"] == "fail"
    assert failed["evidence"] is None

    async def missing_evidence(_recipe_ref: str) -> dict[str, object]:
        raise MissingEvidenceError("missing raw bytes")

    monkeypatch.setattr(proof_transport, "observe_transport_recipe", missing_evidence)
    unavailable = await run_core_driver_assertion("driver/http-correction-byte-budget-reset")
    assert unavailable["verdict"] == "error"
    assert unavailable["evidence"] is None


@pytest.mark.asyncio
async def test_transport_recipe_cancellation_and_fatal_errors_propagate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def cancelled(_recipe_ref: str) -> dict[str, object]:
        raise asyncio.CancelledError()

    monkeypatch.setattr(proof_transport, "observe_transport_recipe", cancelled)
    with pytest.raises(asyncio.CancelledError):
        await run_core_driver_assertion("driver/http-correction-byte-budget-reset")

    async def fatal(_recipe_ref: str) -> dict[str, object]:
        raise KeyboardInterrupt()

    monkeypatch.setattr(proof_transport, "observe_transport_recipe", fatal)
    with pytest.raises(KeyboardInterrupt):
        await run_core_driver_assertion("driver/http-correction-byte-budget-reset")


@pytest.mark.asyncio
async def test_transport_recipe_empty_observations_are_not_passing_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def empty(_recipe_ref: str) -> dict[str, object]:
        return {}

    monkeypatch.setattr(proof_transport, "observe_transport_recipe", empty)
    result = await run_core_driver_assertion("driver/http-correction-byte-budget-reset")
    assert result["verdict"] == "error"
    assert result["evidence"] is None


@pytest.mark.asyncio
async def test_dispatcher_binds_real_http_correction_evidence() -> None:
    result = await run_core_driver_assertion("driver/http-correction-byte-budget-reset")

    assert result["verdict"] == "pass", result["detail"]
    assert result["evidence"] is not None
    observations = result["evidence"]["observations"]
    assert observations["correction"]["request_count"] == 2
    assert observations["buffered_overflow"]["mode"] == "buffered"
    assert observations["streamed_overflow"]["mode"] == "stream"
