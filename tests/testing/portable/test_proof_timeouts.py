"""Focused verification for the native portable timeout recipes."""

from __future__ import annotations

import pytest

from anyinfer._client import generation
from anyinfer.types.results import ErrorInfo

from .adapter import HarnessError
from .proof_timeouts import _context_facts, _snapshot_category, _TimeoutSpy, observe_timeout_recipe
from .values import MissingEvidenceError


@pytest.mark.parametrize(
    "recipe",
    [
        "driver/timeout-effective-default-explicit",
        "driver/timeout-reset-per-entry",
        "driver/timeout-cleanup-disposal",
    ],
)
async def test_timeout_recipe_returns_native_evidence_after_its_predicate(recipe: str) -> None:
    facts = await observe_timeout_recipe(recipe)

    assert facts
    assert facts["contexts"]
    assert all(context["entered"] and context["exited"] for context in facts["contexts"])
    assert [event["kind"] for event in facts["context_events"]] == [
        kind for _ in facts["contexts"] for kind in ("enter", "exit")
    ]


def test_missing_native_context_observation_cannot_be_evidence() -> None:
    with pytest.raises(MissingEvidenceError):
        _context_facts([], [])
    with pytest.raises(MissingEvidenceError):
        _context_facts(
            [{"configured_timeout_s": 1.0, "entered": False, "exited": True, "expired": False}], []
        )


@pytest.mark.parametrize(
    "events",
    [
        [
            {"event_ordinal": 0, "context_ordinal": 0, "kind": "enter"},
            {"event_ordinal": 1, "context_ordinal": 1, "kind": "enter"},
            {"event_ordinal": 2, "context_ordinal": 0, "kind": "exit"},
            {"event_ordinal": 3, "context_ordinal": 1, "kind": "exit"},
        ],
        [
            {"event_ordinal": 0, "context_ordinal": 0, "kind": "enter"},
            {"event_ordinal": 1, "context_ordinal": 1, "kind": "exit"},
            {"event_ordinal": 2, "context_ordinal": 1, "kind": "enter"},
            {"event_ordinal": 3, "context_ordinal": 0, "kind": "exit"},
        ],
        [{"event_ordinal": 0, "context_ordinal": 0, "kind": "enter"}],
    ],
)
def test_overlapping_out_of_order_or_missing_disposal_cannot_fake_evidence(
    events: list[dict[str, object]],
) -> None:
    records = [
        {"configured_timeout_s": 1.0, "entered": True, "exited": True, "expired": False},
        {"configured_timeout_s": 1.0, "entered": True, "exited": True, "expired": False},
    ]
    if len(events) == 1:
        records = records[:1]
    with pytest.raises((AssertionError, MissingEvidenceError)):
        _context_facts(records, events)


async def test_unknown_timeout_recipe_is_harness_fault() -> None:
    with pytest.raises(HarnessError, match="unknown timeout proof recipe"):
        await observe_timeout_recipe("driver/not-a-timeout-recipe")


def test_timeout_terminal_uses_actual_error_info_type_not_detail() -> None:
    snapshot = ErrorInfo(
        type_name="TransportError",
        provider="fixture",
        phase="generate",
        retryable=True,
        http_status=None,
        detail="deliberately unrelated detail",
    )

    assert _snapshot_category(snapshot) == "transport"
    with pytest.raises(AssertionError, match="ProviderUnavailableError"):
        _snapshot_category(
            ErrorInfo(
                type_name="ProviderUnavailableError",
                provider="fixture",
                phase="generate",
                retryable=True,
                http_status=None,
                detail="would otherwise be misleading",
            )
        )


async def test_timeout_spy_preserves_native_exit_suppression(monkeypatch: pytest.MonkeyPatch) -> None:
    """The observer delegates the native context's exit result, not just its cleanup."""
    native_exited = False

    class NativeTimeout:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, *args: object) -> bool:
            nonlocal native_exited
            native_exited = True
            return True

        def expired(self) -> bool:
            return False

    monkeypatch.setattr(generation.asyncio, "timeout", lambda delay: NativeTimeout())
    spy = _TimeoutSpy()
    with spy.installed():
        async with generation.asyncio.timeout(1.0):
            if bool(monkeypatch):
                raise RuntimeError("the delegated native exit must suppress this")

    assert native_exited
    assert spy.events[-1]["kind"] == "exit"
