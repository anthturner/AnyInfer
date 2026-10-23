"""Focused Draft 2020-12 closure controls for the rich-generation profile."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest

ROOT = Path(__file__).parent / "fixtures" / "rich-generation-v1"


def _read(name: str) -> dict[str, Any]:
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def _invalid_input(mutator: Any) -> dict[str, Any]:
    corpus = copy.deepcopy(_read("inputs.json"))
    mutator(corpus)
    return corpus


def _case(corpus: dict[str, Any], identifier: str) -> dict[str, Any]:
    return next(case for case in corpus["cases"] if case["id"] == identifier)


@pytest.mark.parametrize(
    "mutator",
    [
        lambda corpus: _case(corpus, "fallback-rich-fields-isolated")["request"]["route"].update(
            {"unknown": True}
        ),
        lambda corpus: corpus["cases"][36]["request"]["schema"].update({"unknown": True}),
        lambda corpus: corpus["cases"][36]["request"]["repair"].update({"unknown": True}),
        lambda corpus: corpus["cases"][0]["client"].update({"unknown": True}),
        lambda corpus: corpus["cases"][0]["descriptors"][0].update({"unknown": True}),
        lambda corpus: corpus["cases"][32]["scripts"][0]["actions"][0]["citation"].update(
            {"unknown": True}
        ),
        lambda corpus: corpus["cases"][33]["scripts"][0]["actions"][0]["sources"][0].update(
            {"unknown": True}
        ),
        lambda corpus: corpus["cases"][27]["scripts"][0]["actions"][1]["logprobs"][0].update(
            {"unknown": True}
        ),
        lambda corpus: _case(corpus, "fallback-rich-fields-isolated")["scripts"][1]["actions"][0][
            "logprobs"
        ][0].pop("logprob"),
        lambda corpus: _case(corpus, "server-tool-before-content")["scripts"][0]["actions"][-1][
            "server_tool_uses"
        ][0].update({"unknown": True}),
        lambda corpus: corpus["cases"][37]["scripts"][0]["actions"][0]["failure"].update(
            {"unknown": True}
        ),
        lambda corpus: corpus["cases"][40]["scripts"][0]["actions"][0]["next_actions"][0].update(
            {"unknown": True}
        ),
        lambda corpus: corpus["cases"][0]["request"]["messages"][0]["content"][0].update(
            {"unknown": True}
        ),
    ],
)
def test_input_schema_rejects_unknown_semantic_keys(mutator: Any) -> None:
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(_read("schema.json")).validate(_invalid_input(mutator))


def test_input_schema_accepts_all_43_literal_cases() -> None:
    corpus = _read("inputs.json")
    jsonschema.Draft202012Validator(_read("schema.json")).validate(corpus)
    assert len(corpus["cases"]) == 43


def test_observation_schema_rejects_unknown_projection_keys() -> None:
    validator = jsonschema.Draft202012Validator(_read("observations.schema.json"))
    record = _complete_observation()
    validator.validate(record)


def test_pre_request_validation_can_record_an_actually_absent_manifest() -> None:
    record = _complete_observation()
    case = record["observations"][0]
    case["kind"] = "validation"
    case["public"] = {
        "entry_point": "construct_request",
        "events": [],
        "result": None,
        "error": {
            "type_name": "ValueError",
            "provider": None,
            "phase": None,
            "retryable": False,
            "retry_after_s": None,
            "http_status": None,
            "detail": "invalid media source",
            "hint": None,
        },
    }
    case["wire"]["calls"] = []
    case["cleanup"] = []
    case["telemetry"] = {"events": [], "manifest": None}
    jsonschema.Draft202012Validator(_read("observations.schema.json")).validate(record)


def test_absence_branch_does_not_admit_a_fabricated_partial_manifest() -> None:
    record = _complete_observation()
    record["observations"][0]["telemetry"]["manifest"] = {}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(_read("observations.schema.json")).validate(record)


def test_target_resolution_has_its_own_closed_telemetry_projection() -> None:
    record = _complete_observation()
    events = record["observations"][0]["telemetry"]["events"]
    event = copy.deepcopy(events[1])
    event["stable"].pop("attempt_number")
    event["stable"]["event"] = "TargetResolved"
    events.insert(1, event)
    validator = jsonschema.Draft202012Validator(_read("observations.schema.json"))
    validator.validate(record)
    event["stable"]["response_text"] = "unexpected payload"
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(record)


def test_http_media_input_preserves_inline_document_and_url_refusal_boundaries() -> None:
    corpus = _read("inputs.json")
    request = _case(corpus, "openai-image-document-audio-wire")["request"]
    parts = request["messages"][0]["content"]
    document = next(part for part in parts if part["type"] == "document")
    assert document["data"] == {"encoding": "base64", "value": "ZA=="}
    assert document["url"] is None
    assert request["max_input_part_bytes"] == 3
    assert request["max_input_bytes"] == 4
    refusal = _case(corpus, "openai-document-url-refusal")
    assert refusal["scripts"] == []
    assert refusal["procedure"]["script_ids"] == []
    assert any(
        part["type"] == "document" and part["url"] is not None
        for message in refusal["request"]["messages"]
        for part in message["content"]
    )


def _complete_observation() -> dict[str, Any]:
    digest = "0" * 64
    canonical = {"canonical_json": '{"x":1}', "sha256": digest}
    target = {"provider_id": "fixture", "model": "rich", "via_alias": None}
    usage = {
        "input_tokens": 2,
        "output_tokens": 3,
        "total_tokens": 5,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "reasoning_tokens": 1,
        "cost_usd": "0.01",
        "search_units": None,
        "server_tool_uses": [{"kind": "web_search", "uses": 1}],
    }
    timing = {
        "first_token_present": True,
        "total_present": True,
        "phase_order": ["attempt_start", "first_token"],
    }
    error = {
        "type_name": "ProviderError",
        "provider": "fixture",
        "phase": "generate",
        "retryable": False,
        "retry_after_s": None,
        "http_status": None,
        "detail": "fixture",
        "hint": None,
    }
    attempt = {
        "target": target,
        "attempt_number": 1,
        "outcome": "failed",
        "error": error,
        "timing": timing,
    }
    citation = {
        "start_index": 0,
        "end_index": 1,
        "quoted_text": "quote",
        "document_index": 0,
        "title": "title",
        "uri": "https://fixture.test/doc",
    }
    logprob = {"token": "answer", "logprob": -0.1, "top": [], "bytes": [97]}
    result = {
        "text": "answer",
        "tool_calls": [{"id": "call", "name": "tool", "arguments": canonical}],
        "target": target,
        "finish_reason": "stop",
        "usage": usage,
        "logprobs": [logprob],
        "citations": [citation],
        "server_tool_uses": [{"kind": "web_search", "uses": 1}],
        "raw": {"fixture": "raw"},
        "timing": timing,
        "attempts": [attempt],
        "warnings": ["fixture"],
    }
    evidence = {
        "field_paths": ["event", "metadata.marker"],
        "string_leaves": [{"path": "metadata.marker", "utf8_length": 6, "sha256": digest}],
    }
    adapter_request = {
        "model": "rich",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "prompt"},
                    {"type": "tool_call", "id": "call", "name": "tool", "arguments": canonical},
                    {
                        "type": "tool_result",
                        "call_id": "call",
                        "content": "done",
                        "is_error": False,
                    },
                    {
                        "type": "image",
                        "data": {"length": 1, "sha256": digest},
                        "url": None,
                        "media_type": "image/png",
                        "detail": "high",
                    },
                    {
                        "type": "document",
                        "data": {"length": 1, "sha256": digest},
                        "url": None,
                        "media_type": "application/pdf",
                        "filename": "fixture.pdf",
                    },
                    {
                        "type": "audio",
                        "data": {"length": 1, "sha256": digest},
                        "media_type": "audio/wav",
                    },
                    {
                        "type": "video",
                        "data": {"length": 1, "sha256": digest},
                        "url": None,
                        "media_type": "video/mp4",
                        "start_offset_s": 0.0,
                        "end_offset_s": 1.0,
                        "fps": 24.0,
                    },
                ],
            }
        ],
        "sampling": {
            "temperature": 0.2,
            "top_p": None,
            "max_output_tokens": 8,
            "seed": 1,
            "stop": [],
            "presence_penalty": 0.0,
            "frequency_penalty": 0.0,
        },
        "reasoning_wire": canonical,
        "mechanism": "json_schema",
        "wire_schema": canonical,
        "schema_name": "answer",
        "tools": [
            {
                "name": "tool",
                "description": "fixture",
                "parameters": canonical,
                "annotations": {
                    "title": "Tool",
                    "read_only": None,
                    "destructive": None,
                    "idempotent": None,
                    "open_world": None,
                },
            }
        ],
        "tool_choice": "auto",
        "stream": False,
        "timeout_s": 1.0,
        "max_response_bytes": 8,
        "cache_marks": [0],
        "server_tools": [{"kind": "web_search", "max_uses": 2}],
        "cite_documents": True,
        "logprobs": 1,
        "extra_options": canonical,
        "session_state": {"state": "null"},
    }
    return {
        "profile": "rich-generation-v1",
        "runtime": "python",
        "source_revision": "0" * 40,
        "source_dirty": False,
        "corpus_sha256": "0" * 64,
        "observations": [
            {
                "id": "case",
                "kind": "generation",
                "public": {
                    "entry_point": "async_stream",
                    "events": [
                        {"type": "TextDelta", "text": "answer"},
                        {"type": "ReasoningDelta", "text": "thought"},
                        {
                            "type": "ToolCallDelta",
                            "index": 0,
                            "call_id": "call",
                            "name": "tool",
                            "arguments_fragment": "{}",
                        },
                        {"type": "CitationDelta", "citation": citation},
                        {
                            "type": "ServerToolDelta",
                            "kind": "web_search",
                            "status": "completed",
                            "sources": [{"url": "https://fixture.test", "title": "source"}],
                            "output": "output",
                            "detail": "detail",
                        },
                        {"type": "UsageUpdate", "usage": usage},
                        {"type": "TimingMark", "name": "first_token"},
                        {"type": "AttemptFailed", "record": attempt},
                        {"type": "StreamEnded", "result": result},
                    ],
                    "result": result,
                    "error": None,
                },
                "wire": {
                    "calls": [
                        {
                            "transport": "adapter",
                            "provider": "fixture",
                            "model": "rich",
                            "request": adapter_request,
                        },
                        {
                            "transport": "http",
                            "provider": "fixture",
                            "model": "rich",
                            "body": {"model": "rich"},
                        },
                    ]
                },
                "cleanup": [{"kind": "adapter_close", "id": "fixture"}],
                "telemetry": {
                    "events": [
                        {
                            "stable": {
                                "event": "RequestStarted",
                                "request_id": "request",
                                "targets": ["fixture:rich"],
                                "metadata": [{"key": "marker", "value": "marker"}],
                                "operation": "generation",
                                "prompt_text": None,
                            },
                            "serialized": evidence,
                        },
                        {
                            "stable": {
                                "event": "AttemptStarted",
                                "request_id": "request",
                                "target": target,
                                "attempt_number": 1,
                            },
                            "serialized": evidence,
                        },
                        {
                            "stable": {
                                "event": "FirstToken",
                                "request_id": "request",
                                "target": target,
                                "at_ms_present": True,
                            },
                            "serialized": evidence,
                        },
                        {
                            "stable": {
                                "event": "AttemptCompleted",
                                "request_id": "request",
                                "target": target,
                                "usage": usage,
                                "timing": timing,
                                "finish_reason": "stop",
                            },
                            "serialized": evidence,
                        },
                    ],
                    "manifest": {
                        "operation": "generation",
                        "target": target,
                        "request": {
                            "message_count": 1,
                            "role_counts": [{"role": "user", "count": 1}],
                            "schema_present": True,
                            "schema_name": "answer",
                            "tool_names": ["tool"],
                            "tool_choice": "auto",
                            "metadata_keys": ["marker"],
                        },
                        "payloads": "null",
                        "serialized": evidence,
                    },
                },
            }
        ],
    }


@pytest.mark.parametrize(
    "mutator",
    [
        lambda value: value["observations"][0]["public"]["events"][0].update({"unknown": True}),
        lambda value: value["observations"][0]["public"]["result"]["target"].update(
            {"unknown": True}
        ),
        lambda value: value["observations"][0]["public"]["result"]["usage"].update(
            {"unknown": True}
        ),
        lambda value: value["observations"][0]["public"]["result"]["logprobs"][0].update(
            {"unknown": True}
        ),
        lambda value: value["observations"][0]["wire"]["calls"][0]["request"]["messages"][
            0
        ].update({"unknown": True}),
        lambda value: value["observations"][0]["wire"]["calls"][0]["request"].update(
            {"schema_name": 99}
        ),
        lambda value: value["observations"][0]["wire"]["calls"][0]["request"][
            "server_tools"
        ].append("unknown"),
        lambda value: value["observations"][0]["wire"]["calls"][1].update({"request": {}}),
        lambda value: value["observations"][0]["cleanup"][0].update({"unknown": True}),
        lambda value: value["observations"][0]["telemetry"]["events"][0]["stable"].update(
            {"unknown": True}
        ),
        lambda value: value["observations"][0]["telemetry"]["manifest"].update({"unknown": True}),
        lambda value: value["observations"][0]["telemetry"]["manifest"]["serialized"][
            "string_leaves"
        ][0].update({"unknown": True}),
    ],
)
def test_observation_schema_rejects_unknown_semantic_keys(mutator: Any) -> None:
    validator = jsonschema.Draft202012Validator(_read("observations.schema.json"))
    invalid = _complete_observation()
    mutator(invalid)
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(invalid)


@pytest.mark.parametrize(
    "mutator",
    [
        lambda value: value["observations"][0]["wire"]["calls"][0]["request"]["messages"][0][
            "content"
        ][0].update({"unknown": True}),
        lambda value: value["observations"][0]["wire"]["calls"][0]["request"]["messages"][0][
            "content"
        ][1].update({"unknown": True}),
        lambda value: value["observations"][0]["wire"]["calls"][0]["request"]["messages"][0][
            "content"
        ][2].update({"unknown": True}),
        lambda value: value["observations"][0]["wire"]["calls"][0]["request"]["messages"][0][
            "content"
        ][3].update({"unknown": True}),
        lambda value: value["observations"][0]["wire"]["calls"][0]["request"]["messages"][0][
            "content"
        ][4].update({"unknown": True}),
        lambda value: value["observations"][0]["wire"]["calls"][0]["request"]["messages"][0][
            "content"
        ][5].update({"unknown": True}),
        lambda value: value["observations"][0]["wire"]["calls"][0]["request"]["messages"][0][
            "content"
        ][6].update({"unknown": True}),
        lambda value: value["observations"][0]["wire"]["calls"][0]["request"]["messages"][0][
            "content"
        ][3].pop("detail"),
        lambda value: value["observations"][0]["wire"]["calls"][0]["request"]["messages"][0][
            "content"
        ][6].pop("start_offset_s"),
        lambda value: value["observations"][0]["wire"]["calls"][0]["request"]["messages"][0][
            "content"
        ][6].pop("fps"),
        lambda value: value["observations"][0]["wire"]["calls"][0]["request"]["messages"][0][
            "content"
        ][1].pop("arguments"),
        lambda value: value["observations"][0]["wire"]["calls"][0]["request"]["messages"][0][
            "content"
        ][2].pop("is_error"),
        lambda value: value["observations"][0]["wire"]["calls"][0]["request"]["sampling"].update(
            {"unknown": True}
        ),
        lambda value: value["observations"][0]["wire"]["calls"][0]["request"]["sampling"].pop(
            "max_output_tokens"
        ),
        lambda value: value["observations"][0]["wire"]["calls"][0]["request"]["sampling"].pop(
            "presence_penalty"
        ),
        lambda value: value["observations"][0]["wire"]["calls"][0]["request"]["sampling"].pop(
            "frequency_penalty"
        ),
        lambda value: value["observations"][0]["wire"]["calls"][0]["request"]["tools"][0][
            "annotations"
        ].update({"unknown": True}),
        lambda value: value["observations"][0]["wire"]["calls"][0]["request"]["tools"][0][
            "annotations"
        ].pop("read_only"),
        lambda value: value["observations"][0]["wire"]["calls"][0]["request"]["tools"][0][
            "annotations"
        ].pop("open_world"),
        lambda value: value["observations"][0]["wire"]["calls"][0]["request"]["server_tools"][
            0
        ].update({"unknown": True}),
        lambda value: value["observations"][0]["wire"]["calls"][0]["request"]["server_tools"][
            0
        ].pop("max_uses"),
        lambda value: value["observations"][0]["wire"]["calls"][0]["request"]["messages"][
            0
        ].update({"tool_call_id": None}),
        lambda value: value["observations"][0]["wire"]["calls"][0]["request"].update(
            {"max_response_tokens": 8}
        ),
    ],
)
def test_observation_schema_closes_literal_adapter_projection(mutator: Any) -> None:
    invalid = _complete_observation()
    mutator(invalid)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(_read("observations.schema.json")).validate(invalid)


@pytest.mark.parametrize(
    "stable",
    [
        {
            "event": "UsageEstimated",
            "request_id": "request",
            "target": {"provider_id": "fixture", "model": "rich", "via_alias": None},
            "field_name": "input_tokens",
            "method": "fixture estimate",
        },
        {
            "event": "RetryScheduled",
            "request_id": "request",
            "target": {"provider_id": "fixture", "model": "rich", "via_alias": None},
            "attempt_number": 1,
            "delay_s": 0.5,
            "error": {
                "type_name": "ProviderError",
                "provider": "fixture",
                "phase": "generate",
                "retryable": True,
                "retry_after_s": None,
                "http_status": None,
                "detail": "fixture failure",
                "hint": None,
            },
        },
    ],
)
def test_observation_schema_retains_estimate_and_retry_facts(stable: dict[str, Any]) -> None:
    validator = jsonschema.Draft202012Validator(_read("observations.schema.json"))
    value = _complete_observation()
    value["observations"][0]["telemetry"]["events"][0]["stable"] = stable
    validator.validate(value)
    stable["unknown"] = True
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(value)
    del stable["unknown"]
    del stable["method" if stable["event"] == "UsageEstimated" else "delay_s"]
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(value)
