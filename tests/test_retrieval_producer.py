"""Independent focused controls for the retrieval-v1 Python observer.

These checks exercise public-SDK construction and capture boundaries.  They deliberately
do not qualify corpus answers or reproduce the native checker policy.
"""

from __future__ import annotations

import asyncio
import copy
import importlib.util
import json
import sys
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
PRODUCER_PATH = ROOT / "tests" / "test_retrieval_parity.py"
INPUT_PATH = ROOT / "tests" / "fixtures" / "retrieval-v1" / "inputs.json"


def _producer() -> Any:
    name = "_retrieval_v1_producer_for_controls"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, PRODUCER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


P = _producer()


def _source() -> dict[str, Any]:
    source = json.loads(INPUT_PATH.read_text(encoding="utf-8"))
    schema = P.read_json_bytes(P.INPUT_SCHEMA)
    assert isinstance(schema, dict)
    P.validate_inputs(source, schema)
    return source


def _case(predicate: Callable[[dict[str, Any]], bool]) -> dict[str, Any]:
    matches = [case for case in _source()["cases"] if predicate(case)]
    assert len(matches) == 1
    return copy.deepcopy(matches[0])


def _first_case(predicate: Callable[[dict[str, Any]], bool]) -> dict[str, Any]:
    return copy.deepcopy(next(case for case in _source()["cases"] if predicate(case)))


def _observe(case: dict[str, Any]) -> dict[str, Any]:
    return asyncio.run(P._observe_case(case, 41))


def _priced_unit_case(provenance: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build one schema-valid local cost witness without changing frozen inputs."""
    source = _source()
    case = next(
        value
        for value in source["cases"]
        if value["procedure"]["name"] == "spend_and_manifest"
        and value["ledger"]
        and value["kind"] == "embedding"
    )
    pricing = case["descriptors"][0]["capabilities"]["pricing"]
    assert pricing is not None
    pricing["source"] = provenance
    pricing["per_server_tool_use"] = {"unit-tool": "0.25"}
    response = case["scripts"][0]["steps"][0]["response"]
    response["usage"] = {
        "input_tokens": 7,
        "output_tokens": 0,
        "total_tokens": 7,
        "cache_read_tokens": None,
        "cache_write_tokens": None,
        "reasoning_tokens": None,
        "cost_usd": None,
        "search_units": None,
        "server_tool_uses": {},
    }
    schema = P.read_json_bytes(P.INPUT_SCHEMA)
    assert isinstance(schema, dict)
    P.validate_inputs(source, schema)
    return copy.deepcopy(case), copy.deepcopy(pricing)


def _envelope(case: dict[str, Any], value: dict[str, Any]) -> dict[str, Any]:
    return {
        "profile": P.PROFILE,
        "runtime": "python",
        "source_revision": "a" * 40,
        "source_dirty": True,
        "corpus_sha256": P.FROZEN_INPUT_SHA256,
        "observations": [{"id": case["id"], "kind": case["kind"], "status": "ok", "value": value}],
    }


def _strictly_increasing(values: list[int]) -> bool:
    return values == sorted(values) and len(values) == len(set(values))


def test_public_constructor_and_config_routes_reach_registered_retrieval_adapter() -> None:
    constructor_case = _case(
        lambda value: (
            value["client"]["source"] == "constructor"
            and value["request"]["entry_point"] == "embed_scalar"
        )
    )
    config_case = _case(
        lambda value: (
            value["client"]["source"] == "from_config"
            and value["client"]["default_route"] is not None
            and value["client"]["operation_route"] is not None
        )
    )

    for case in (constructor_case, config_case):
        value = _observe(case)
        assert value["operation"]["outcome"] == "ok"
        assert value["factories"] and value["wires"]
        factory = value["factories"][-1]
        wire = value["wires"][-1]
        assert wire["target"]["provider_id"] == factory["instance"]
        assert wire["request"]["model"] == factory["model"]
        assert wire["request"]["timeout_s"] == (case["request"]["timeout_s"] or 120.0)
        assert wire["request"]["extra_options"] == case["request"]["provider_options"].get(
            factory["instance"], {}
        )
        close = [item for item in value["resources"] if "client_close" in item["type"]]
        adapter_close = [item for item in value["resources"] if "adapter_close" in item["type"]]
        assert [item["type"] for item in close] == [
            "normal_client_close_started",
            "normal_client_close_completed",
        ]
        assert [item["type"] for item in adapter_close] == [
            "adapter_close_started",
            "adapter_close_completed",
        ]


def test_runtime_protocols_are_actual_optional_interfaces_and_unsupported_has_no_wire() -> None:
    states = {
        ("embedding",): (P.EmbedsText,),
        ("rerank",): (P.ReranksText,),
        ("embedding", "rerank"): (P.EmbedsText, P.ReranksText),
        (): (),
    }
    for declared, expected in states.items():
        adapter = P._adapter_type(declared)(
            instance="protocol-control",
            descriptor="protocol-control",
            scripts=[],
            wires=[],
            resources=[],
            barriers={},
            order=lambda: 1,
        )
        assert (
            tuple(
                protocol
                for protocol in (P.EmbedsText, P.ReranksText)
                if isinstance(adapter, protocol)
            )
            == expected
        )

    refused = _observe(
        _case(lambda value: value["procedure"]["name"] == "requested_unsupported_operation")
    )
    assert refused["operation"]["outcome"] == "error"
    assert refused["factories"]
    returned = refused["factories"][-1]
    assert returned["runtime_protocols"] == ["rerank"]
    assert returned["declared_operations"] == ["rerank"]
    assert refused["wires"] == []


def test_json_embedding_capabilities_are_immutable_and_drive_public_intent_warnings() -> None:
    descriptor = {
        "capabilities": {
            "pricing": None,
            "embedding": {
                "dimensions": 3,
                "dimension_choices": [3, 2],
                "max_batch_inputs": None,
                "max_input_tokens": None,
                "max_input_bytes": None,
                "input_intents": ["query", "document"],
                "normalized": True,
            },
            "rerank": None,
        }
    }
    original = copy.deepcopy(descriptor)
    _, embedding, rerank = P._capabilities(descriptor)
    assert embedding is not None and rerank is None
    assert embedding.dimensions == 3
    assert embedding.dimension_choices == (3, 2)
    assert embedding.input_intents == ("query", "document")
    assert descriptor == original

    absent = copy.deepcopy(descriptor)
    absent["capabilities"]["embedding"] = None
    assert P._capabilities(absent)[1] is None

    known_empty = _case(
        lambda item: (
            item["procedure"]["name"] == "capability_intent"
            and item["descriptors"][0]["capabilities"]["embedding"]["input_intents"] == []
        )
    )
    empty_value = _observe(known_empty)
    empty_target = (
        f"{known_empty['descriptors'][0]['instance']}:{known_empty['descriptors'][0]['model']}"
    )
    assert empty_value["operation"]["result"]["warnings"] == [
        f"{empty_target} does not distinguish embedding input intents; "
        f"input_type={known_empty['request']['input_type']!r} has no effect on this target"
    ]

    unsupported = _case(
        lambda item: (
            item["procedure"]["name"] == "capability_intent"
            and item["request"]["input_type"]
            not in item["descriptors"][0]["capabilities"]["embedding"]["input_intents"]
            and item["descriptors"][0]["capabilities"]["embedding"]["input_intents"] != []
        )
    )
    unsupported_value = _observe(unsupported)
    unsupported_target = (
        f"{unsupported['descriptors'][0]['instance']}:{unsupported['descriptors'][0]['model']}"
    )
    supported = ", ".join(
        unsupported["descriptors"][0]["capabilities"]["embedding"]["input_intents"]
    )
    assert unsupported_value["operation"]["result"]["warnings"] == [
        f"{unsupported_target} does not support input_type={unsupported['request']['input_type']!r} "
        f"(supported: {supported}); the provider's own handling applies"
    ]


def test_pricing_failure_and_raw_evidence_keep_public_values_without_local_policy_math() -> None:
    default_case, default_pricing = _priced_unit_case("default")
    default_priced = _observe(default_case)
    assert default_priced["operation"]["result"]["usage"]["cost_usd"] is None

    priced_case, override_pricing = _priced_unit_case("override")
    source_copy = copy.deepcopy(override_pricing)
    built_pricing = P._pricing(override_pricing)
    assert built_pricing is not None
    assert built_pricing.per_server_tool_use == {"unit-tool": Decimal("0.25")}
    assert override_pricing == source_copy
    priced = _observe(priced_case)
    usage = priced["operation"]["result"]["usage"]
    assert usage["cost_usd"] is not None
    assert default_pricing["per_server_tool_use"] == {"unit-tool": "0.25"}
    assert priced["ledger"] is not None
    assert priced["ledger"][-1]["totals"]["cost"] == usage["cost_usd"]

    failure_cases = [
        copy.deepcopy(case)
        for case in _source()["cases"]
        if any(
            step["action"] == "provider_failure"
            for script in case["scripts"]
            for step in script["steps"]
        )
    ]
    assert failure_cases
    for case in failure_cases:
        value = _observe(case)
        wire_failures = [wire["failure"] for wire in value["wires"] if wire["failure"]]
        assert wire_failures
        assert all(
            set(error)
            >= {
                "runtime_type",
                "message",
                "provider",
                "phase",
                "retryable",
                "http_status",
                "retry_after_s",
                "detail",
                "hint",
            }
            for error in wire_failures
        )
        snapshots = [
            event["error"]
            for event in value["telemetry"]
            if event["type"] in {"RequestFailed", "RetryScheduled"}
        ] + [attempt["error"] for attempt in value["operation"]["attempts"] if attempt["error"]]
        assert all(
            set(snapshot)
            == {"runtime_type", "provider", "phase", "retryable", "http_status", "detail"}
            for snapshot in snapshots
        )
        if value["operation"]["outcome"] == "ok":
            assert value["operation"]["error"] is None
            assert snapshots
            assert any(
                event["type"] in {"RetryScheduled", "FallbackTriggered"}
                for event in value["telemetry"]
            )
        else:
            error = value["operation"]["error"]
            assert error is not None
            if case["procedure"]["name"] == "embedding_fallback_safety":
                assert error["runtime_type"] == "ConfigError"
                assert snapshots == []
            else:
                assert error["runtime_type"] == "AllTargetsFailedError"
                assert snapshots


def test_orders_are_causal_and_extra_script_steps_are_not_silently_consumed() -> None:
    value = _observe(
        _case(
            lambda item: (
                item["procedure"]["name"] == "embedding_retry_same_selector"
                and item["client"]["default_route"]["retry"]["max_attempts"] > 1
            )
        )
    )
    boundaries = [
        item["order"] for item in value["factories"] + value["resources"] + value["telemetry"]
    ]
    assert _strictly_increasing(sorted(boundaries))
    for wire in value["wires"]:
        assert wire["entered_order"] < wire["terminal_order"]
    assert value["manifest"] is not None
    assert value["manifest"]["request_relation"] == "operation"

    surplus = _case(lambda item: item["procedure"]["name"] == "embedding_scalar_order")
    surplus["scripts"][0]["steps"].append(copy.deepcopy(surplus["scripts"][0]["steps"][0]))
    with pytest.raises(RuntimeError, match="unconsumed literal retrieval scripts"):
        _observe(surplus)


def test_redaction_preserves_json_kinds_and_rejects_a_redacted_key_collision() -> None:
    secret = "producer-control-secret"
    P.ai.register_secret(secret)
    source = {
        f"key-{secret}": [1, 2.5, False, None, {"inner": secret}],
        "wide": {"after": ["first", "second"]},
    }
    redacted = P._redact_evidence(source)
    assert list(redacted) == ["key-[redacted]", "wide"]
    assert redacted["key-[redacted]"] == [1, 2.5, False, None, {"inner": "[redacted]"}]
    assert redacted["wide"] == {"after": ["first", "second"]}
    with pytest.raises(P.ObservationError, match="collapsed distinct evidence keys"):
        P._redact_evidence({secret: 1, "[redacted]": 2})


def test_caller_cancellation_releases_held_provider_and_never_completes() -> None:
    case = _case(lambda item: item["procedure"]["name"] == "caller_cancel_while_provider_held")
    selector = next(
        script for script in case["scripts"] if script["steps"][0]["action"] == "barrier"
    )
    value = _observe(case)
    operation = value["operation"]
    assert operation["outcome"] == "cancelled"
    assert operation["result"] is None and operation["error"] is None
    assert operation["cancellation_relation"] == "caller_cancelled"
    resources = value["resources"]

    def one(kind: str) -> dict[str, Any]:
        matches = [item for item in resources if item["type"] == kind]
        assert len(matches) == 1
        return matches[0]

    reached = one("barrier_reached")
    cancelled = one("caller_cancel_requested")
    cleanup = one("provider_cleanup_entered")
    released_resource = one("barrier_released")
    operation_finally = one("operation_finally")
    close_started = one("normal_client_close_started")
    assert (
        operation_finally["selector_id"],
        operation_finally["step_ordinal"],
        operation_finally["instance"],
    ) == (selector["id"], selector["steps"][0]["ordinal"], selector["instance"])
    assert reached["order"] < cancelled["order"] < operation_finally["order"]
    assert cleanup["order"] < operation_finally["order"]
    assert released_resource["order"] < operation_finally["order"] < close_started["order"]
    assert value["ledger"] is not None
    held = next(item for item in value["ledger"] if item["label"] == "while_provider_held")
    released = value["ledger"][-1]
    assert held["reserved"] != "0"
    assert released["reserved"] == "0"


def test_early_task_terminal_before_barrier_never_waits_for_unentered_cleanup() -> None:
    case = _case(lambda item: item["procedure"]["name"] == "caller_cancel_while_provider_held")
    case["scripts"][0]["model"] = "unselectable-model"

    async def observe() -> None:
        with pytest.raises(RuntimeError, match="unconsumed literal retrieval scripts"):
            await P._observe_case(case, 42)

    asyncio.run(asyncio.wait_for(observe(), timeout=0.25))


def test_unrelated_outer_cancellation_still_releases_and_joins_held_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _case(lambda item: item["procedure"]["name"] == "caller_cancel_while_provider_held")
    created: list[Any] = []
    constructed = asyncio.Event()
    original = P._Barrier

    def record_barrier(*args: Any) -> Any:
        barrier = original(*args)
        created.append(barrier)
        constructed.set()
        return barrier

    terminal = P._RecordingState._terminal
    cleanup_held = asyncio.Event()
    cleanup_release = asyncio.Event()

    async def hold_cleanup(self: Any, *args: Any) -> Any:
        try:
            return await terminal(self, *args)
        finally:
            cleanup_held.set()
            await cleanup_release.wait()

    monkeypatch.setattr(P, "_Barrier", record_barrier)
    monkeypatch.setattr(P._RecordingState, "_terminal", hold_cleanup)

    async def cancel_from_outside() -> None:
        task = asyncio.create_task(P._observe_case(case, 43))
        await asyncio.wait_for(constructed.wait(), timeout=0.25)
        barrier = created[0]
        await asyncio.wait_for(barrier.readiness.wait(), timeout=0.25)
        task.cancel()
        try:
            await asyncio.wait_for(cleanup_held.wait(), timeout=0.25)
            task.cancel()
            assert not task.done()
        finally:
            cleanup_release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=0.25)
        assert barrier.release.is_set() and barrier.cleanup.is_set() and task.done()

    asyncio.run(cancel_from_outside())


def test_close_faults_preserve_primary_error_and_do_not_claim_completed_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = P.ai.AsyncClient.aclose

    async def close_fault(self: Any) -> None:
        await original(self)
        raise RuntimeError("control close fault")

    monkeypatch.setattr(P.ai.AsyncClient, "aclose", close_fault)
    primary = _case(lambda item: item["procedure"]["name"] == "embedding_unsplit_exhaustion")
    value = _observe(primary)
    assert value["operation"]["outcome"] == "error"
    assert value["operation"]["error"]["runtime_type"] == "AllTargetsFailedError"
    assert "normal_client_close_completed" not in [item["type"] for item in value["resources"]]

    success = _case(lambda item: item["request"]["entry_point"] == "embed_scalar")
    with pytest.raises(RuntimeError, match="control close fault"):
        _observe(success)


def test_unconsumed_steps_invalidate_a_settled_sdk_error_path() -> None:
    case = _first_case(
        lambda item: any(
            step["action"] == "provider_failure"
            for script in item["scripts"]
            for step in script["steps"]
        )
    )
    case["scripts"][0]["steps"].append(copy.deepcopy(case["scripts"][0]["steps"][0]))
    with pytest.raises(RuntimeError, match="unconsumed literal retrieval scripts"):
        _observe(case)


def test_output_validation_refuses_nonfinite_raw_and_timing_values() -> None:
    case = _case(lambda item: item["request"]["entry_point"] == "embed_scalar")
    value = _observe(case)
    baseline = _envelope(case, value)
    P._validate_output(baseline, _source())

    bad_raw = copy.deepcopy(baseline)
    bad_raw["observations"][0]["value"]["operation"]["result"]["raw"] = {"finite": float("nan")}
    with pytest.raises(P.ObservationError):
        P._validate_output(bad_raw, _source())

    bad_timing = copy.deepcopy(baseline)
    bad_timing["observations"][0]["value"]["operation"]["result"]["timing"]["total_ms"] = float(
        "inf"
    )
    with pytest.raises(P.ObservationError):
        P._validate_output(bad_timing, _source())
