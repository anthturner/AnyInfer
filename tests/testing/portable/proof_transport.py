"""Native HTTP proof for correction-byte reset and multibyte raw-byte limits."""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from anyinfer.errors import StreamProtocolError

from .adapter import HarnessError
from .projection import _error, native_feedback_for_call, project_run, validate_capture
from .transport import TransportRun, run_transport_fixture
from .values import MissingEvidenceError, json_value

_ID = "driver/http-correction-byte-budget-reset"
_ROOT = Path(__file__).parents[3] / "specification" / "fixtures" / "transport" / "openai-chat"
# Both complete payloads have fewer than 80 Unicode code points but more than
# 80 UTF-8 bytes because their literal content includes sixteen ``é`` values.
_CAP = 80
_MULTIBYTE_TEXT = "é" * 16


def _correction_fixture() -> dict[str, object]:
    """Load fixed correction input and responses, never its pending expectation."""
    value = json.loads((_ROOT / "correction-byte-budget-reset.json").read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise HarnessError("transport proof correction fixture must be an object")
    value.pop("expected", None)
    return value


def _overflow_fixture(*, stream: bool) -> dict[str, object]:
    """Build a direct native adapter overflow stimulus without any expected outcome."""
    if stream:
        payload = (
            'data: {"choices":[{"delta":{"content":"'
            + _MULTIBYTE_TEXT
            + '"}}]}\n\n'
            + "data: [DONE]\n\n"
        ).encode("utf-8")
        headers = {"content-type": "text/event-stream"}
    else:
        payload = json.dumps(
            {"choices": [{"message": {"content": _MULTIBYTE_TEXT}, "finish_reason": "stop"}]},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        headers = {"content-type": "application/json"}
    midpoint = len(payload) // 2
    chunks = (payload[:midpoint], payload[midpoint:])
    if not all(len(chunk) <= _CAP for chunk in chunks) or len(payload) <= _CAP:
        raise AssertionError("overflow stimulus does not establish split cumulative byte cap")
    return {
        "fixture_version": "0",
        "id": "transport/openai-chat/proof-overflow-stream"
        if stream
        else "transport/openai-chat/proof-overflow-buffered",
        "family": "transport/openai-chat",
        "profile": "core-generation",
        "description": "direct multibyte native byte-cap proof stimulus",
        "kind": "adapter",
        "input": {
            "adapter_config": {
                "provider_id": "openai-compat",
                "base_url": "https://fixture.invalid/v1",
                "api_key": "fixture-token",
                "headers": {"x-fixture": "transport-proof"},
                "timeout_s": 120,
            },
            "wire": {
                "model": "fixture-model",
                "messages": [{"role": "user", "text": "prove UTF-8 cap"}],
                "sampling": {},
                "mechanism": None,
                "stream": stream,
                "timeout_s": 120,
                "max_response_bytes": _CAP,
            },
        },
        "responses": [
            {
                "status": 200,
                "headers": headers,
                "byte_chunks": [
                    {"bytes": base64.b64encode(chunk).decode("ascii")} for chunk in chunks
                ],
            }
        ],
    }


def _raw_facts(run: TransportRun) -> dict[str, object]:
    if not run.requests or not run.http_requests or not run.delivered_chunks:
        raise MissingEvidenceError("transport proof lacks raw native request or delivery facts")
    if len(run.requests) != len(run.http_requests) or len(run.requests) != len(
        run.delivered_chunks
    ):
        raise MissingEvidenceError(
            "transport raw request, HTTP, and delivery cardinalities disagree"
        )
    response_totals = [sum(len(chunk) for chunk in chunks) for chunks in run.delivered_chunks]
    responses: list[dict[str, object]] = [
        {
            "chunk_bytes": [len(chunk) for chunk in chunks],
            "total_bytes": total,
            "chunks_base64": [base64.b64encode(chunk).decode("ascii") for chunk in chunks],
        }
        for chunks, total in zip(run.delivered_chunks, response_totals, strict=True)
    ]
    return {
        "request_count": len(run.requests),
        "http_requests": list(run.http_requests),
        "wire_limits": [
            {"timeout_s": request.timeout_s, "max_response_bytes": request.max_response_bytes}
            for request in run.requests
        ],
        "wire_stream": [request.stream for request in run.requests],
        "http_stream": [request.get("stream") for request in run.http_requests],
        "responses": responses,
        "cumulative_bytes": sum(response_totals),
    }


def _core_request_and_http_facts(
    run: TransportRun, entries: tuple[object, ...], calls: object
) -> list[dict[str, object]]:
    """Bind the raw transport sink to the core's exact captured attempt order."""
    if run.core is None or not run.core.requests:
        raise MissingEvidenceError("correction proof lacks captured core wire requests")
    if len(run.requests) != len(run.core.requests):
        raise MissingEvidenceError("transport and core request cardinalities disagree")
    if len(entries) != len(run.requests) or not isinstance(calls, list):
        raise MissingEvidenceError("correction proof lacks ordered capture or projection calls")
    if len(calls) != len(run.requests) or len(run.http_requests) != len(run.requests):
        raise MissingEvidenceError("core projection or HTTP cardinality disagrees with transport")
    facts: list[dict[str, object]] = []
    for ordinal, (request, core_request, entry, http, call) in enumerate(
        zip(run.requests, run.core.requests, entries, run.http_requests, calls, strict=True)
    ):
        if request is not core_request:
            raise AssertionError("transport recorder did not retain the core wire request identity")
        entry_ordinal = getattr(entry, "entry_ordinal", None)
        snapshot = getattr(entry, "wire_snapshot", None)
        if entry_ordinal != ordinal or not isinstance(snapshot, Mapping):
            raise MissingEvidenceError("captured entry lacks its ordered wire snapshot")
        if not isinstance(http, Mapping) or not isinstance(call, Mapping):
            raise MissingEvidenceError("correction proof has unprojectable HTTP or core call")
        body = http.get("body")
        if not isinstance(body, Mapping):
            raise MissingEvidenceError("correction HTTP request lacks a JSON body")
        http_stream = http.get("stream")
        if type(http_stream) is not bool:
            raise MissingEvidenceError("correction HTTP request lacks a stream-mode fact")
        if (
            http.get("method") != "POST"
            or http.get("path") != "/v1/chat/completions"
            or http_stream is not request.stream
            or (body.get("stream") is True) is not request.stream
            or body.get("model") != request.model
            or call.get("model") != request.model
            or call.get("timeout_s") != request.timeout_s
            or call.get("max_response_bytes") != request.max_response_bytes
        ):
            raise AssertionError("correction HTTP request differs from captured native wire")
        body_messages = body.get("messages")
        call_messages = call.get("messages")
        if not isinstance(body_messages, list) or not isinstance(call_messages, list):
            raise MissingEvidenceError("correction request lacks ordered message evidence")
        if len(body_messages) != len(request.messages) or len(call_messages) != len(request.messages):
            raise AssertionError("correction HTTP or projected message cardinality differs from wire")
        for encoded, projected, message in zip(
            body_messages, call_messages, request.messages, strict=True
        ):
            if not isinstance(encoded, Mapping) or not isinstance(projected, Mapping):
                raise MissingEvidenceError("correction message evidence is not structured")
            if (
                encoded.get("role") != message.role
                or encoded.get("content") != message.text
                or projected.get("role") != message.role
                or projected.get("text") != message.text
            ):
                raise AssertionError("correction HTTP or projection messages differ from wire order")
        facts.append(
            {
                "entry_ordinal": ordinal,
                "method": http["method"],
                "path": http["path"],
                "model": request.model,
                "stream": request.stream,
                "message_count": len(request.messages),
            }
        )
    return facts


def _correction_facts(run: TransportRun) -> dict[str, object]:
    """Validate and retain correction-specific native HTTP and capture evidence."""
    if run.core is None:
        raise MissingEvidenceError("correction proof lacks a native core run")
    if run.error is not None or run.core.error is not None:
        raise AssertionError("correction proof did not complete natively")
    capture = validate_capture(run.core)
    projection = project_run(run.core)
    outcome = projection.get("outcome")
    result = outcome.get("result") if isinstance(outcome, Mapping) else None
    if not isinstance(result, Mapping):
        raise MissingEvidenceError("correction proof lacks projected native result")
    if result.get("structured") != {"age": 7} or result.get("repair_attempts") != 1:
        raise AssertionError("correction proof did not retain invalid-to-valid native result")
    if len(run.core.operations) != 1:
        raise MissingEvidenceError("correction proof lacks exactly one operation capture")
    operation = run.core.operations[0]
    entries = tuple(operation.entries)
    if len(entries) != 2 or [entry.role for entry in entries] != ["original", "correction"]:
        raise AssertionError("correction proof lacks original/correction entry order")
    wire_http = _core_request_and_http_facts(run, entries, projection.get("calls"))
    _, correction = entries
    if correction.repair_assessment_ref is None:
        raise MissingEvidenceError("correction entry lacks native assessment linkage")
    assessments = [
        assessment
        for assessment in operation.assessments
        if assessment.assessment_id == correction.repair_assessment_ref
    ]
    if len(assessments) != 1:
        raise MissingEvidenceError("correction linkage does not select one native assessment")
    assessment = assessments[0]
    if assessment.source_entry_ordinal != entries[0].entry_ordinal:
        raise AssertionError("correction assessment does not originate from invalid entry")
    if assessment.operation_id != operation.operation_id or assessment.issues is None:
        raise MissingEvidenceError("original correction assessment lacks validation issue facts")
    if assessment.kind != "validation":
        raise AssertionError("original correction assessment is not validation")
    if len(assessment.issues) != 1:
        raise AssertionError("original correction assessment does not retain one age type issue")
    issue = assessment.issues[0]
    if (
        issue.rule != "type"
        or issue.instance_path != ("age",)
        or issue.schema_path != ("properties", "age", "type")
    ):
        raise AssertionError("original correction assessment lacks the age type issue")
    valid_assessments = [
        item
        for item in operation.assessments
        if item.source_entry_ordinal == correction.entry_ordinal
    ]
    if not valid_assessments:
        raise MissingEvidenceError("valid terminal entry lacks one native assessment")
    if len(valid_assessments) != 1:
        raise AssertionError("valid terminal entry retained more than one assessment")
    valid_assessment = valid_assessments[0]
    if valid_assessment.operation_id != operation.operation_id:
        raise MissingEvidenceError("terminal assessment belongs to another operation")
    if valid_assessment.assessment_id == assessment.assessment_id:
        raise AssertionError("terminal assessment reuses the invalid assessment identity")
    if valid_assessment.issues is None:
        raise MissingEvidenceError("terminal assessment lacks validation issue facts")
    if (
        valid_assessment.kind != "validation"
        or valid_assessment.issues != ()
        or valid_assessment.native_messages != ()
        or valid_assessment.selected_native != ()
    ):
        raise AssertionError("terminal correction assessment is not valid")
    feedback = native_feedback_for_call(run.core, correction.entry_ordinal)
    if (
        not feedback
        or not assessment.native_messages
        or tuple(feedback) != assessment.native_messages
    ):
        raise MissingEvidenceError("correction proof lacks selected native feedback linkage")
    facts = _raw_facts(run)
    responses = facts["responses"]
    response_totals = [response.get("total_bytes") for response in responses] if isinstance(responses, list) else []
    if response_totals != [78, 74] or not all(type(total) is int for total in response_totals):
        raise AssertionError("correction response byte evidence is not the fixed 78/74 pair")
    typed_response_totals = [cast(int, total) for total in response_totals]
    limits = facts["wire_limits"]
    if not isinstance(limits, list) or len(limits) != 2:
        raise MissingEvidenceError("correction proof lacks two effective wire limits")
    if any(limit != {"timeout_s": 120, "max_response_bytes": 100} for limit in limits):
        raise AssertionError("correction entries did not retain matching timeout and byte cap")
    cumulative_bytes = facts["cumulative_bytes"]
    if (
        any(total >= 100 for total in typed_response_totals)
        or type(cumulative_bytes) is not int
        or cumulative_bytes <= 100
    ):
        raise AssertionError("correction proof did not establish per-entry cap reset")
    return cast(
        dict[str, object],
        json_value(
            {
                **facts,
                "mode": "buffered",
                "capture": capture,
                "outcome": outcome,
                "entries": [
                    {
                        "entry_ordinal": entry.entry_ordinal,
                        "role": entry.role,
                        "repair_assessment_ref": entry.repair_assessment_ref,
                    }
                    for entry in entries
                ],
                "wire_http": wire_http,
                "selected_assessment": {
                    "assessment_id": assessment.assessment_id,
                    "source_entry_ordinal": assessment.source_entry_ordinal,
                    "kind": assessment.kind,
                    "native_feedback": list(feedback),
                },
                "terminal_assessment": {
                    "assessment_id": valid_assessment.assessment_id,
                    "source_entry_ordinal": valid_assessment.source_entry_ordinal,
                    "kind": valid_assessment.kind,
                    "issues": [],
                    "native_messages": [],
                    "selected_native": [],
                },
            }
        ),
    )


def _overflow_facts(run: TransportRun, *, stream: bool) -> dict[str, object]:
    """Validate one real direct-adapter raw-byte overflow observation."""
    if run.core is not None:
        raise AssertionError("overflow proof unexpectedly used the core runner")
    if not isinstance(run.error, StreamProtocolError):
        raise AssertionError("overflow proof did not retain StreamProtocolError")
    if any(type(event).__name__ == "AdapterFinal" for event in run.adapter_events):
        raise AssertionError("overflow proof retained a native final event")
    error = _error(run.error, stage=run.error_stage)
    if error.get("category") != "stream_protocol" or error.get("phase") != "stream":
        raise AssertionError("overflow proof lacks normalized stream-protocol category and phase")
    facts = _raw_facts(run)
    limits = facts["wire_limits"]
    responses = facts["responses"]
    if not isinstance(limits, list) or limits != [{"timeout_s": 120, "max_response_bytes": _CAP}]:
        raise AssertionError("overflow proof lacks the effective byte cap")
    if not isinstance(responses, list) or len(responses) != 1:
        raise MissingEvidenceError("overflow proof lacks one delivered response")
    wire_stream = facts["wire_stream"]
    http_stream = facts["http_stream"]
    if not isinstance(wire_stream, list) or not isinstance(http_stream, list):
        raise MissingEvidenceError("overflow proof lacks actual stream-mode evidence")
    if wire_stream != [stream] or http_stream != [stream]:
        raise AssertionError("overflow proof wire or HTTP body mode differs from requested stream")
    response = responses[0]
    chunk_bytes = response["chunk_bytes"]
    if (
        not isinstance(chunk_bytes, list)
        or not chunk_bytes
        or any(size > _CAP for size in chunk_bytes)
    ):
        raise AssertionError("overflow proof chunks do not individually fit the cap")
    total_bytes = response.get("total_bytes")
    cumulative_bytes = facts["cumulative_bytes"]
    if (
        type(total_bytes) is not int
        or type(cumulative_bytes) is not int
        or total_bytes <= _CAP
        or cumulative_bytes <= _CAP
    ):
        raise AssertionError("overflow proof did not exceed the cumulative raw-byte cap")
    raw = b"".join(run.delivered_chunks[0])
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MissingEvidenceError("overflow proof has unprojectable non-UTF-8 delivery") from exc
    if (
        decoded.count("é") != len(_MULTIBYTE_TEXT)
        or len(decoded) > _CAP
        or len(raw) <= _CAP
    ):
        raise AssertionError("overflow proof lacks the literal bounded Unicode stimulus")
    return cast(
        dict[str, object],
        json_value({**facts, "mode": "stream" if stream else "buffered", "error": error}),
    )


async def observe_transport_recipe(recipe_ref: str) -> dict[str, object]:
    """Execute the sixth development-only core driver recipe with native HTTP facts."""
    if recipe_ref != _ID:
        raise HarnessError(f"unknown transport proof recipe {recipe_ref!r}")
    correction = await run_transport_fixture(_correction_fixture())
    buffered = await run_transport_fixture(_overflow_fixture(stream=False))
    streamed = await run_transport_fixture(_overflow_fixture(stream=True))
    return cast(
        dict[str, object],
        json_value(
            {
                "recipe_ref": recipe_ref,
                "correction": _correction_facts(correction),
                "buffered_overflow": _overflow_facts(buffered, stream=False),
                "streamed_overflow": _overflow_facts(streamed, stream=True),
            }
        ),
    )
