"""Direct checks for the native HTTP core-driver proof predicates."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import cast

import pytest

from anyinfer.errors import StreamProtocolError

from . import proof_transport
from .adapter import HarnessError
from .transport import TransportRun, run_transport_fixture
from .values import MissingEvidenceError


async def _correction_run() -> TransportRun:
    run = await run_transport_fixture(proof_transport._correction_fixture())
    proof_transport._correction_facts(run)
    return run


async def _overflow_run(*, stream: bool) -> TransportRun:
    run = await run_transport_fixture(proof_transport._overflow_fixture(stream=stream))
    proof_transport._overflow_facts(run, stream=stream)
    return run


def _mapping(value: object) -> Mapping[str, object]:
    assert isinstance(value, Mapping)
    return cast(Mapping[str, object], value)


def _rows(value: object) -> Sequence[Mapping[str, object]]:
    return [_mapping(item) for item in _items(value)]


def _items(value: object) -> Sequence[object]:
    assert isinstance(value, Sequence)
    return value


def _integer(value: object) -> int:
    assert isinstance(value, int)
    return value


def test_proof_builders_do_not_copy_pending_expectations() -> None:
    correction = proof_transport._correction_fixture()
    buffered = proof_transport._overflow_fixture(stream=False)
    streamed = proof_transport._overflow_fixture(stream=True)

    assert "expected" not in correction
    assert "expected" not in buffered
    assert "expected" not in streamed


@pytest.mark.asyncio
async def test_correction_facts_use_actual_buffered_repair_capture_and_reset_bytes() -> None:
    run = await _correction_run()
    facts = proof_transport._correction_facts(run)
    responses = _rows(facts["responses"])
    assessment = _mapping(facts["selected_assessment"])
    terminal = _mapping(facts["terminal_assessment"])
    outcome = _mapping(facts["outcome"])
    result = _mapping(outcome["result"])

    assert facts["mode"] == "buffered"
    assert facts["request_count"] == 2
    assert [response["total_bytes"] for response in responses] == [78, 74]
    assert facts["cumulative_bytes"] == 152
    assert facts["wire_limits"] == [
        {"timeout_s": 120, "max_response_bytes": 100},
        {"timeout_s": 120, "max_response_bytes": 100},
    ]
    assert facts["entries"] == [
        {"entry_ordinal": 0, "role": "original", "repair_assessment_ref": None},
        {
            "entry_ordinal": 1,
            "role": "correction",
            "repair_assessment_ref": assessment["assessment_id"],
        },
    ]
    assert assessment["source_entry_ordinal"] == 0
    assert assessment["kind"] == "validation"
    assert assessment["native_feedback"]
    assert terminal["source_entry_ordinal"] == 1
    assert terminal["kind"] == "validation"
    assert terminal["assessment_id"] != assessment["assessment_id"]
    assert terminal["issues"] == []
    assert terminal["native_messages"] == []
    assert terminal["selected_native"] == []
    assert result["structured"] == {"age": 7}
    assert result["repair_attempts"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_overflow_facts_preserve_native_raw_byte_domains(stream: bool) -> None:
    run = await _overflow_run(stream=stream)
    facts = proof_transport._overflow_facts(run, stream=stream)
    response = _rows(facts["responses"])[0]
    error = _mapping(facts["error"])
    cap = run.requests[0].max_response_bytes

    assert facts["mode"] == ("stream" if stream else "buffered")
    assert error["category"] == "stream_protocol"
    assert error["phase"] == "stream"
    chunk_bytes = [_integer(size) for size in _items(response["chunk_bytes"])]
    total_bytes = _integer(response["total_bytes"])
    assert all(size <= cap for size in chunk_bytes)
    assert total_bytes > cap
    assert facts["cumulative_bytes"] == response["total_bytes"]
    raw = b"".join(run.delivered_chunks[0])
    assert len(raw.decode("utf-8")) <= cap < len(raw)
    assert "é" in raw.decode("utf-8")
    assert isinstance(run.error, StreamProtocolError)
    assert not any(type(event).__name__ == "AdapterFinal" for event in run.adapter_events)


@pytest.mark.asyncio
async def test_overflow_facts_reject_mode_mismatch_with_actual_buffered_run() -> None:
    buffered = await _overflow_run(stream=False)

    with pytest.raises(AssertionError):
        proof_transport._overflow_facts(buffered, stream=True)


@pytest.mark.asyncio
async def test_correction_facts_reject_missing_raw_capture_and_cardinality() -> None:
    run = await _correction_run()

    with pytest.raises(MissingEvidenceError):
        proof_transport._correction_facts(replace(run, requests=()))
    with pytest.raises(MissingEvidenceError):
        proof_transport._correction_facts(replace(run, http_requests=run.http_requests[:1]))
    with pytest.raises(MissingEvidenceError):
        proof_transport._correction_facts(replace(run, delivered_chunks=()))


@pytest.mark.asyncio
async def test_correction_facts_reject_wrong_cap_missing_roles_link_and_outcome() -> None:
    run = await _correction_run()
    assert run.core is not None
    operation = run.core.operations[0]
    entries = list(operation.entries)

    wrong_cap = replace(run.requests[0], max_response_bytes=99)
    with pytest.raises(AssertionError):
        proof_transport._correction_facts(replace(run, requests=(wrong_cap, *run.requests[1:])))

    operation.entries[:] = entries[:1]
    try:
        with pytest.raises(MissingEvidenceError):
            proof_transport._correction_facts(run)
    finally:
        operation.entries[:] = entries

    operation.entries[1] = replace(entries[1], repair_assessment_ref=None)
    try:
        with pytest.raises(MissingEvidenceError):
            proof_transport._correction_facts(run)
    finally:
        operation.entries[:] = entries

    with pytest.raises(MissingEvidenceError):
        proof_transport._correction_facts(replace(run, core=replace(run.core, result=None)))


@pytest.mark.asyncio
async def test_correction_facts_reject_request_capture_and_http_identity_mismatches() -> None:
    run = await _correction_run()
    assert run.core is not None
    operation = run.core.operations[0]
    entries = list(operation.entries)

    with pytest.raises(MissingEvidenceError):
        proof_transport._correction_facts(
            replace(run, core=replace(run.core, requests=tuple(reversed(run.core.requests))))
        )

    with pytest.raises(MissingEvidenceError):
        proof_transport._correction_facts(replace(run, http_requests=run.http_requests[:1]))
    with pytest.raises(MissingEvidenceError):
        proof_transport._correction_facts(
            replace(run, http_requests=(*run.http_requests, run.http_requests[-1]))
        )

    operation.entries[:] = list(reversed(entries))
    try:
        with pytest.raises(MissingEvidenceError):
            proof_transport._correction_facts(run)
    finally:
        operation.entries[:] = entries

    first_http = dict(run.http_requests[0])
    first_body = dict(_mapping(first_http["body"]))
    first_body["model"] = "incorrect-model"
    first_http["body"] = first_body
    with pytest.raises(AssertionError):
        proof_transport._correction_facts(
            replace(run, http_requests=(first_http, *run.http_requests[1:]))
        )

    message_http = dict(run.http_requests[0])
    message_body = dict(_mapping(message_http["body"]))
    encoded_messages = list(_items(message_body["messages"]))
    first_message = dict(_mapping(encoded_messages[0]))
    first_message["content"] = "wrong caller content"
    encoded_messages[0] = first_message
    message_body["messages"] = encoded_messages
    message_http["body"] = message_body
    with pytest.raises(AssertionError):
        proof_transport._correction_facts(
            replace(run, http_requests=(message_http, *run.http_requests[1:]))
        )

    reordered_http = tuple(reversed(run.http_requests))
    with pytest.raises(AssertionError):
        proof_transport._correction_facts(replace(run, http_requests=reordered_http))


@pytest.mark.asyncio
async def test_correction_facts_require_exact_invalid_and_terminal_assessments() -> None:
    run = await _correction_run()
    assert run.core is not None
    operation = run.core.operations[0]
    assessments = list(operation.assessments)
    invalid = next(assessment for assessment in assessments if assessment.source_entry_ordinal == 0)
    terminal = next(assessment for assessment in assessments if assessment.source_entry_ordinal == 1)

    assert invalid.kind == "validation"
    issues = invalid.issues
    assert issues is not None
    assert len(issues) == 1
    issue = issues[0]
    assert issue.rule == "type"
    assert issue.instance_path == ("age",)
    assert issue.schema_path == ("properties", "age", "type")
    assert terminal.kind == "validation"
    assert terminal.issues == ()
    assert terminal.native_messages == ()
    assert terminal.selected_native == ()

    operation.assessments[:] = [assessment for assessment in assessments if assessment != terminal]
    try:
        with pytest.raises(MissingEvidenceError):
            proof_transport._correction_facts(run)
    finally:
        operation.assessments[:] = assessments

    operation.assessments[assessments.index(terminal)] = replace(
        terminal, issues=(issue,)
    )
    try:
        with pytest.raises(AssertionError):
            proof_transport._correction_facts(run)
    finally:
        operation.assessments[:] = assessments

    operation.assessments[assessments.index(terminal)] = replace(
        terminal, source_entry_ordinal=0
    )
    try:
        with pytest.raises(MissingEvidenceError):
            proof_transport._correction_facts(run)
    finally:
        operation.assessments[:] = assessments

    operation.assessments[assessments.index(invalid)] = replace(invalid, kind="extraction")
    try:
        with pytest.raises(AssertionError):
            proof_transport._correction_facts(run)
    finally:
        operation.assessments[:] = assessments

    operation.assessments[assessments.index(invalid)] = replace(
        invalid, issues=(replace(issue, rule="minimum"),)
    )
    try:
        with pytest.raises(AssertionError, match="lacks the age type issue"):
            proof_transport._correction_facts(run)
    finally:
        operation.assessments[:] = assessments

    operation.assessments[assessments.index(invalid)] = replace(
        invalid, issues=(replace(issue, instance_path=("other",)),)
    )
    try:
        with pytest.raises(AssertionError, match="lacks the age type issue"):
            proof_transport._correction_facts(run)
    finally:
        operation.assessments[:] = assessments

    operation.assessments[assessments.index(invalid)] = replace(invalid, issues=(issue, issue))
    try:
        with pytest.raises(AssertionError, match="does not retain one age type issue"):
            proof_transport._correction_facts(run)
    finally:
        operation.assessments[:] = assessments


@pytest.mark.asyncio
async def test_overflow_facts_reject_missing_chunks_wrong_cap_and_invalid_byte_domain() -> None:
    run = await _overflow_run(stream=True)

    with pytest.raises(MissingEvidenceError):
        proof_transport._overflow_facts(replace(run, delivered_chunks=()), stream=True)

    with pytest.raises(AssertionError):
        fixture = proof_transport._overflow_fixture(stream=True)
        input_data = _mapping(fixture["input"])
        wire = cast(dict[str, object], _mapping(input_data["wire"]))
        wire["max_response_bytes"] = 79
        capped = await run_transport_fixture(fixture)
        proof_transport._overflow_facts(capped, stream=True)

    chunks = run.delivered_chunks[0]
    invalid_utf8_chunks = (bytes([0xFF]) + chunks[0][1:], *chunks[1:])
    with pytest.raises(MissingEvidenceError):
        proof_transport._overflow_facts(
            replace(run, delivered_chunks=(invalid_utf8_chunks,)), stream=True
        )


@pytest.mark.asyncio
async def test_recipe_retains_three_real_native_observations() -> None:
    facts = await proof_transport.observe_transport_recipe(
        "driver/http-correction-byte-budget-reset"
    )

    assert facts["recipe_ref"] == "driver/http-correction-byte-budget-reset"
    assert set(facts) == {
        "recipe_ref",
        "correction",
        "buffered_overflow",
        "streamed_overflow",
    }
    assert _mapping(facts["correction"])["request_count"] == 2
    assert _mapping(facts["buffered_overflow"])["mode"] == "buffered"
    assert _mapping(facts["streamed_overflow"])["mode"] == "stream"


@pytest.mark.asyncio
async def test_recipe_propagates_cancellation_and_fatal_base_exceptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def cancelled(_fixture: object) -> TransportRun:
        raise asyncio.CancelledError()

    monkeypatch.setattr(proof_transport, "run_transport_fixture", cancelled)
    with pytest.raises(asyncio.CancelledError):
        await proof_transport.observe_transport_recipe("driver/http-correction-byte-budget-reset")

    async def fatal(_fixture: object) -> TransportRun:
        raise KeyboardInterrupt()

    monkeypatch.setattr(proof_transport, "run_transport_fixture", fatal)
    with pytest.raises(KeyboardInterrupt):
        await proof_transport.observe_transport_recipe("driver/http-correction-byte-budget-reset")


@pytest.mark.asyncio
async def test_transport_recipe_rejects_unknown_id() -> None:
    with pytest.raises(HarnessError):
        await proof_transport.observe_transport_recipe("driver/nope")
