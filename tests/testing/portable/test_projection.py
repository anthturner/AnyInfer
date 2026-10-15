"""Projection tests built from native records, never fixture expectations."""

from __future__ import annotations

from dataclasses import replace

import pytest

from anyinfer._client.async_client import AsyncClient
from anyinfer.errors import SchemaViolationError
from anyinfer.redaction import REDACTED, register_secret
from anyinfer.schema._capture import (
    EnteredWire,
    Issue,
    NativeAssessment,
    RepairPreparation,
    _OperationCapture,
    capture_enabled,
)
from anyinfer.types.events import StreamEnded, TextDelta, TimingMark, UsageUpdate
from anyinfer.types.messages import assistant, system, user
from anyinfer.types.requests import Repair, ResolvedTarget, Sampling
from anyinfer.types.results import Generation, Timing, Usage

from .adapter import FixtureProvider
from .projection import (
    MissingEvidenceError,
    extension_evidence,
    native_feedback_for_call,
    project_run,
    sampling_for_call,
    validate_capture,
)
from .records import NativeRun
from .values import schema_prompt


def _wire(model: str = "alpha", *, temperature: float | None = None, messages=(), mechanism=None):
    from anyinfer.providers.base import WireRequest

    return WireRequest(model=model, messages=messages, sampling=Sampling(temperature=temperature), mechanism=mechanism)


def _snapshot(wire, messages=()):
    return {
        "model": wire.model,
        "messages": list(messages),
        "sampling": {"temperature": wire.sampling.temperature, "top_p": None, "max_output_tokens": None, "stop": (), "seed": None, "presence_penalty": None, "frequency_penalty": None},
        "mechanism": wire.mechanism,
        "stream": wire.stream,
        "timeout_s": wire.timeout_s,
        "max_response_bytes": wire.max_response_bytes,
    }


def _captured_run() -> NativeRun:
    raw_messages = (user("person"),)
    schema = {"type": "object", "properties": {"age": {"type": "integer"}}, "required": ["age"]}
    original_messages = ({"role": "user", "text": "person"},)
    built = (
        {"role": "user", "text": "person"},
        {"role": "assistant", "text": '{"name":"x"}'},
        {"role": "user", "text": "Your previous response did not match the required JSON schema. Errors:\n- 'age' is a required property\nRespond again with ONLY a corrected JSON value that satisfies the schema. No prose, no code fences."},
    )
    original_wire_messages = ({"role": "system", "text": schema_prompt(schema)}, *original_messages)
    correction_wire_messages = ({"role": "system", "text": schema_prompt(schema)}, *built)
    make_message = {"user": user, "assistant": assistant, "system": system}
    original = _wire(temperature=0.0, messages=tuple(make_message[item["role"]](item["text"]) for item in original_wire_messages), mechanism="prompt")
    correction = _wire(temperature=0.0, messages=tuple(make_message[item["role"]](item["text"]) for item in correction_wire_messages), mechanism="prompt")
    operation = _OperationCapture()
    assessment = NativeAssessment(
        operation.operation_id, "assessment", 0, "validation", (Issue("required", (), ("required",), {"property": "age"}),),
        ("'age' is a required property",), ({"validator": "required", "path": ()},),
    )
    preparation = RepairPreparation(
        0, "assessment", original_messages, '{"name":"x"}', assessment.native_messages, built,
    )
    operation.assessments.append(assessment)
    operation.preparations.append(preparation)
    operation.entries.extend(
        (
            EnteredWire(0, "original", None, _snapshot(original, original_wire_messages)),
            EnteredWire(1, "correction", "assessment", _snapshot(correction, correction_wire_messages)),
        )
    )
    result = Generation(
        "{\"age\":7}", {"age": 7}, (), ResolvedTarget("fixture", "alpha"), "stop",
        Usage(input_tokens=2, output_tokens=1, total_tokens=3), Timing(0, first_token_ms=1, total_ms=2),
        "prompt", repair_attempts=1,
    )
    return NativeRun(
        "repair/case",
        events=(TimingMark("attempt_start", 0), TextDelta("{\"age\":"), TextDelta("7}"), UsageUpdate(result.usage), StreamEnded(result)),
        result=result, operations=(operation,), requests=(original, correction), clock_advances_ms=(500,),
        input_messages=raw_messages, input_schema=schema,
    )


async def _real_repair_run(script, *, repair_attempts: int) -> NativeRun:
    provider = FixtureProvider(
        {
            "max_repair_attempts": None,
            "models": {"alpha": {"capabilities": {"grammar": False, "json_schema": False, "json_mode": False}}},
            "health_preset": [],
            "script": script,
        }
    )
    schema = {"type": "object", "properties": {"age": {"type": "integer"}}, "required": ["age"]}
    async with AsyncClient([provider.settings], registry=provider.registry, use_default_catalog=False) as client:
        with capture_enabled() as operations:
            try:
                result = await client.generate("person", target="fixture:alpha", schema=schema, repair=Repair(max_attempts=repair_attempts))
                error = None
            except SchemaViolationError as caught:
                result, error = None, caught
    assert provider.adapter is not None
    return NativeRun("real", result=result, error=error, error_stage="operation" if error else None, operations=tuple(operations), requests=tuple(provider.adapter.requests), input_messages=(user("person"),), input_schema=schema)


async def test_projects_real_async_client_capture_without_synthetic_wire() -> None:
    run = await _real_repair_run(
        [{"events": [{"text": '{"name":"x"}'}, {"final": {}}]}, {"events": [{"text": '{"age":7}'}, {"final": {}}]}],
        repair_attempts=1,
    )
    projected = project_run(run)
    assert projected["calls"][1]["role"] == "correction"
    assert native_feedback_for_call(run, 1)


def test_capture_fails_closed_for_missing_or_wrong_correction_evidence() -> None:
    run = _captured_run()
    run.operations[0].evidence_available = False
    with pytest.raises(MissingEvidenceError, match="unavailable"):
        validate_capture(run)

    run = _captured_run()
    run.operations[0].entries[1] = EnteredWire(1, "correction", "wrong", run.operations[0].entries[1].wire_snapshot)
    with pytest.raises(MissingEvidenceError, match="missing native assessment"):
        validate_capture(run)


async def test_schema_error_uses_real_terminal_exhaustion_assessment() -> None:
    run = await _real_repair_run(
        [{"events": [{"text": '{"name":"x"}'}, {"final": {}}]}, {"events": [{"text": '{"name":"y"}'}, {"final": {}}]}],
        repair_attempts=1,
    )
    assert isinstance(run.error, SchemaViolationError)
    assert run.operations[0].assessments[-1].source_entry_ordinal == 1
    projected = project_run(run)
    assert projected["outcome"]["error"]["category"] == "schema_violation"
    assert projected["outcome"]["error"]["issues"][0]["rule"] == "required"


async def test_extension_rejects_invented_role_on_real_nonportable_capture() -> None:
    run = await _real_repair_run(
        [{"events": [{"text": '{"name":"x"}'}, {"final": {}}]}, {"events": [{"text": '{"age":7}'}, {"final": {}}]}],
        repair_attempts=1,
    )
    request = replace(run.requests[0], mechanism="json_schema")
    snapshot = dict(run.operations[0].entries[0].wire_snapshot or {})
    snapshot["mechanism"] = "json_schema"
    run.operations[0].entries[0] = EnteredWire(0, "invented", None, snapshot)
    mutated = replace(run, requests=(request, *run.requests[1:]))
    with pytest.raises(MissingEvidenceError, match="unknown entered wire role"):
        extension_evidence(mutated)


async def test_schema_error_rejects_stale_terminal_assessment_source() -> None:
    run = await _real_repair_run(
        [{"events": [{"text": '{"name":"x"}'}, {"final": {}}]}, {"events": [{"text": '{"name":"y"}'}, {"final": {}}]}],
        repair_attempts=1,
    )
    terminal = run.operations[0].assessments[-1]
    run.operations[0].assessments[-1] = replace(terminal, source_entry_ordinal=0)
    with pytest.raises(MissingEvidenceError, match="not from the final entry"):
        project_run(run)


def test_sampling_omits_unset_fields_and_retains_actual_native_values() -> None:
    run = _captured_run()
    assert sampling_for_call(run, 0) == {"temperature": 0.0}


def test_construction_value_error_and_harness_error_are_not_conflated() -> None:
    construction = NativeRun("bad", error=ValueError("sampling seed must not be negative"), error_stage="construction", construction_origin="sampling")
    assert project_run(construction)["outcome"]["error"]["category"] == "invalid_request"
    with pytest.raises(MissingEvidenceError, match="harness"):
        project_run(NativeRun("broken", error=RuntimeError("driver"), error_stage="harness"))


def test_extension_evidence_preserves_an_honest_unmapped_native_error() -> None:
    evidence = extension_evidence(NativeRun("extension", error=RuntimeError("native boundary"), error_stage="operation"))
    assert evidence["native_outcome"]["error"] == {"native_type": "RuntimeError", "message": "native boundary", "category": None}


def test_capture_rejects_type_and_signed_zero_wire_mutations() -> None:
    run = _captured_run()
    snapshot = dict(run.operations[0].entries[0].wire_snapshot or {})
    sampling = dict(snapshot["sampling"])
    sampling["seed"] = True
    snapshot["sampling"] = sampling
    run.operations[0].entries[0] = EnteredWire(0, "original", None, snapshot)
    with pytest.raises(MissingEvidenceError, match="sampling differs"):
        validate_capture(run)

    run = _captured_run()
    snapshot = dict(run.operations[0].entries[0].wire_snapshot or {})
    snapshot["timeout_s"] = -0.0
    run.operations[0].entries[0] = EnteredWire(0, "original", None, snapshot)
    with pytest.raises(MissingEvidenceError, match="timeout_s differs"):
        validate_capture(run)


def test_control_sampling_allows_int_float_equivalence_but_not_messages() -> None:
    run = _captured_run()
    snapshot = dict(run.operations[0].entries[0].wire_snapshot or {})
    sampling = dict(snapshot["sampling"])
    sampling["temperature"] = 0
    snapshot["sampling"] = sampling
    run.operations[0].entries[0] = EnteredWire(0, "original", None, snapshot)
    validate_capture(run)

    run = _captured_run()
    snapshot = dict(run.operations[0].entries[0].wire_snapshot or {})
    snapshot["messages"] = [{"role": "system", "text": schema_prompt(run.input_schema)}, {"role": "user", "text": "other"}]
    run.operations[0].entries[0] = EnteredWire(0, "original", None, snapshot)
    with pytest.raises(MissingEvidenceError, match="messages differ"):
        validate_capture(run)


def test_extension_evidence_redacts_and_validates_native_error_text() -> None:
    secret = "projection-secret-123"
    register_secret(secret)
    evidence = extension_evidence(NativeRun("extension", error=RuntimeError(f"failed {secret}"), error_stage="operation"))
    assert REDACTED in evidence["native_outcome"]["error"]["message"]
    with pytest.raises(MissingEvidenceError, match="lone surrogate"):
        extension_evidence(NativeRun("extension", error=RuntimeError("bad \ud800"), error_stage="operation"))
