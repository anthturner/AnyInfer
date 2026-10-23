"""Synthetic, input-only controls for the rich-generation verifier."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import _csharp_observation as observation  # noqa: E402
import check_csharp_rich_generation as checker  # noqa: E402


def _case(identifier: str = "media-invalid-image-two-sources") -> observation.Case:
    _, cases = observation.read_cases(
        ROOT / "tests" / "fixtures" / "rich-generation-v1" / "inputs.json",
        profile=checker.PROFILE,
    )
    return next(case for case in cases if case.identifier == identifier)


def _error(type_name: str = "ValueError") -> dict[str, Any]:
    return {
        "type_name": type_name,
        "provider": None,
        "phase": None,
        "retryable": False,
        "retry_after_s": None,
        "http_status": None,
        "detail": "invalid",
        "hint": None,
    }


def _record(case: observation.Case | None = None, *, manifest: bool = False) -> dict[str, Any]:
    case = _case() if case is None else case
    manifest_value: Any = None
    if manifest:
        manifest_value = {
            "operation": "generation",
            "target": None,
            "request": {
                "message_count": 0,
                "role_counts": [],
                "schema_present": False,
                "schema_name": None,
                "tool_names": [],
                "tool_choice": "auto",
                "metadata_keys": [],
            },
            "payloads": "null",
            "serialized": {"field_paths": [], "string_leaves": []},
        }
    return {
        "id": case.identifier,
        "kind": case.kind,
        "public": {
            "entry_point": "construct_request",
            "events": [],
            "result": None,
            "error": _error(),
        },
        "wire": {"calls": []},
        "cleanup": [],
        "telemetry": {"events": [], "manifest": manifest_value},
    }


def _envelope(
    records: list[dict[str, Any]],
    *,
    runtime: str = "python",
    revision: str = "a" * 40,
    dirty: bool = False,
    digest: str = checker.FROZEN_CORPUS_SHA256,
) -> dict[str, Any]:
    return {
        "profile": checker.PROFILE,
        "runtime": runtime,
        "source_revision": revision,
        "source_dirty": dirty,
        "corpus_sha256": digest,
        "observations": records,
    }


def test_validation_record_is_schema_valid_and_qualifies() -> None:
    record = _record(manifest=True)
    checker._validate_schema(checker.OBSERVATION_SCHEMA, _envelope([record]), label="test")


def test_validation_rejects_dispatch_and_unrelated_error() -> None:
    record = _record()
    record["wire"]["calls"].append(
        {"transport": "http", "provider": "x", "model": "m", "body": {}}
    )
    with pytest.raises(observation.ObservationError, match="must not dispatch"):
        checker.qualify_observation(_case(), record, runtime="python")
    record = _record()
    record["public"]["error"]["type_name"] = "ProviderError"
    with pytest.raises(observation.ObservationError, match="approved"):
        checker.qualify_observation(_case(), record, runtime="python")


def test_validation_without_a_client_request_requires_null_manifest() -> None:
    record = _record()
    record["telemetry"]["manifest"] = None
    checker.qualify_observation(_case(), record, runtime="python")
    record = _record()
    record["telemetry"]["manifest"] = _record(manifest=True)["telemetry"]["manifest"]
    with pytest.raises(observation.ObservationError, match="must not dispatch"):
        checker.qualify_observation(_case(), record, runtime="python")


def test_validation_constructor_success_has_no_error_or_side_effects() -> None:
    record = _record()
    record["public"]["error"] = None
    checker._validate_schema(checker.OBSERVATION_SCHEMA, _envelope([record]), label="success")
    checker.qualify_observation(_case(), record, runtime="python")
    for mutate in (
        lambda item: item["public"].update(entry_point="async_generate"),
        lambda item: item["public"].update(result={}),
        lambda item: item["public"]["events"].append({"type": "TextDelta", "text": "x"}),
        lambda item: item["wire"]["calls"].append({}),
    ):
        invalid = copy.deepcopy(record)
        mutate(invalid)
        with pytest.raises(observation.ObservationError, match="must not dispatch"):
            checker.qualify_observation(_case(), invalid, runtime="python")


def test_constructor_error_spelling_is_the_only_normalization() -> None:
    case = _case()
    python, native = _record(case), _record(case)
    native["public"]["error"]["type_name"] = "ArgumentException"
    assert checker.compare_case(case, python, native) == []
    native["public"]["error"]["detail"] = "different"
    assert checker.compare_case(case, python, native) == []
    python["public"]["error"]["retryable"] = True
    assert checker.compare_case(case, python, native)


def test_constructor_alias_cannot_leak_to_generation_or_raw_payloads() -> None:
    case = _case("media-image-inline-order")
    python, native = _record(case), _record(case)
    native["public"]["error"]["type_name"] = "ArgumentException"
    assert checker.compare_case(case, python, native)
    raw_python = {"wire": {"calls": [{"body": {"public": {"error": _error()}}}]}}
    raw_native = copy.deepcopy(raw_python)
    raw_native["wire"]["calls"][0]["body"]["public"]["error"]["type_name"] = "ArgumentException"
    assert checker._compare(raw_python, raw_native)


def test_provider_errors_are_strict_without_recursive_comparison() -> None:
    left = _error("ProviderError")
    right = copy.deepcopy(left)
    assert checker._compare_error(left, right, "error", constructor_alias=False) is None
    right["detail"] = "different provider error"
    assert checker._compare_error(left, right, "error", constructor_alias=False)


def test_portable_errors_map_only_at_typed_observation_slots() -> None:
    python = _error("ProviderError")
    python.update(provider="p", phase="generate", retryable=True, http_status=503)
    native = copy.deepcopy(python)
    native.update(type_name="ProviderException", detail="native wording", hint="native hint")
    assert checker._compare({"public": {"error": python}}, {"public": {"error": native}}) is None
    for key, value in (("provider", "other"), ("phase", "wire"), ("retryable", False)):
        changed = copy.deepcopy(native)
        changed[key] = value
        assert checker._compare({"public": {"error": python}}, {"public": {"error": changed}})
    assert checker._compare({"raw": {"error": python}}, {"raw": {"error": native}})


def test_literal_provider_failure_requires_attempt_and_fallback_detail() -> None:
    literal = {"retryable": True, "http_status": 503, "detail": "first-failure-marker"}
    case = observation.Case(
        "synthetic",
        "generation",
        {
            "scripts": [
                {
                    "provider": "first",
                    "model": "model",
                    "actions": [{"action": "provider_failure", "failure": literal}],
                }
            ]
        },
    )
    error = {
        "type_name": "ProviderError",
        **literal,
        "provider": "first",
        "phase": "generate",
        "retry_after_s": None,
        "hint": None,
    }
    record = {
        "wire": {"calls": [{"provider": "first", "model": "model"}]},
        "public": {
            "events": [
                {
                    "type": "AttemptFailed",
                    "record": {
                        "target": {"provider_id": "first", "model": "model"},
                        "error": error,
                    },
                }
            ],
            "result": None,
        },
        "telemetry": {
            "events": [
                {
                    "stable": {
                        "event": "FallbackTriggered",
                        "from_target": {"provider_id": "first", "model": "model"},
                        "error": copy.deepcopy(error),
                    }
                }
            ]
        },
    }
    checker._qualify_literal_failures(case, record)
    for location in (
        record["public"]["events"][0]["record"]["error"],
        record["telemetry"]["events"][0]["stable"]["error"],
    ):
        broken = copy.deepcopy(record)
        if location is record["public"]["events"][0]["record"]["error"]:
            broken["public"]["events"] = []
        else:
            broken["telemetry"]["events"][0]["stable"]["error"]["detail"] = "changed"
        with pytest.raises(observation.ObservationError):
            checker._qualify_literal_failures(case, broken)
    for field, value in (("provider", "wrong"), ("phase", "wire")):
        broken = copy.deepcopy(record)
        broken["public"]["events"][0]["record"]["error"][field] = value
        with pytest.raises(observation.ObservationError, match="facts"):
            checker._qualify_literal_failures(case, broken)


def test_content_shape_and_order_are_exact() -> None:
    case = _case("media-image-inline-order")
    python, native = _record(case, manifest=True), _record(case, manifest=True)
    native["cleanup"].append({"kind": "client_close", "id": "one"})
    assert checker.compare_case(case, python, native)
    native = copy.deepcopy(python)
    native["telemetry"]["manifest"]["request"]["tool_choice"] = "required"
    assert checker.compare_case(case, python, native)


def test_strict_json_rejects_bom_duplicate_and_nonfinite(tmp_path: Path) -> None:
    for name, payload in (
        ("bom.json", b"\xef\xbb\xbf{}"),
        ("dup.json", b'{"a":1,"a":2}'),
        ("nan.json", b'{"a":NaN}'),
    ):
        path = tmp_path / name
        path.write_bytes(payload)
        with pytest.raises(observation.ObservationError):
            observation.read_json_bytes(path)


def test_envelope_rejects_stale_source_dirty_and_duplicate_missing_unknown(tmp_path: Path) -> None:
    cases = [_case(), _case("media-invalid-video-window")]
    records = [_record(cases[0]), _record(cases[1])]
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(_envelope(records)), encoding="utf-8")
    run = checker.read_observations(
        path, cases=cases, runtime="python", digest=checker.FROZEN_CORPUS_SHA256
    )
    stale = copy.deepcopy(run)
    with pytest.raises(observation.ObservationError, match="source revisions differ"):
        observation.validate_handshake(
            run,
            stale.__class__(
                run.runtime, "b" * 40, run.source_dirty, run.corpus_sha256, run.observations
            ),
        )
    duplicate = _envelope([records[0], records[0]])
    path.write_text(json.dumps(duplicate), encoding="utf-8")
    with pytest.raises(observation.ObservationError, match="duplicate"):
        checker.read_observations(
            path, cases=cases, runtime="python", digest=checker.FROZEN_CORPUS_SHA256
        )
    unknown = copy.deepcopy(records)
    unknown[1]["id"] = "unknown-case"
    path.write_text(json.dumps(_envelope(unknown)), encoding="utf-8")
    with pytest.raises(observation.ObservationError, match="unexpected"):
        checker.read_observations(
            path, cases=cases, runtime="python", digest=checker.FROZEN_CORPUS_SHA256
        )
    path.write_text(json.dumps(_envelope([records[0]])), encoding="utf-8")
    with pytest.raises(observation.ObservationError, match="missing"):
        checker.read_observations(
            path, cases=cases, runtime="python", digest=checker.FROZEN_CORPUS_SHA256
        )


def test_timing_presence_and_order_are_invariants_not_durations() -> None:
    # Timing values are intentionally absent from this profile; only the documented boolean
    # presence and ordered phase names are compared.
    assert (
        checker._compare(
            {
                "timing": {
                    "first_token_present": True,
                    "total_present": True,
                    "phase_order": ["attempt_start", "first_token"],
                }
            },
            {
                "timing": {
                    "first_token_present": True,
                    "total_present": True,
                    "phase_order": ["attempt_start", "first_token"],
                }
            },
        )
        is None
    )
    assert checker._compare(
        {"timing": {"first_token_present": True}}, {"timing": {"first_token_present": False}}
    )


def test_timing_accepts_multiple_attempts_and_rejects_bad_marks() -> None:
    record = {
        "public": {
            "events": [
                {"type": "TimingMark", "name": "attempt_start"},
                {"type": "TimingMark", "name": "first_token"},
                {"type": "TextDelta", "text": "one"},
                {"type": "AttemptFailed", "record": {}},
                {"type": "TimingMark", "name": "attempt_start"},
                {"type": "TimingMark", "name": "first_token"},
                {"type": "TextDelta", "text": "two"},
                {"type": "StreamEnded", "result": {}},
            ],
            "result": {"timing": {"first_token_present": True, "total_present": True}},
        },
        "telemetry": {"events": []},
    }
    checker._qualify_timing(record)
    for events, match in (
        ([{"type": "TimingMark", "name": "first_token"}], "lacks"),
        (
            [
                {"type": "TimingMark", "name": "attempt_start"},
                {"type": "TimingMark", "name": "first_token"},
                {"type": "TextDelta", "text": "x"},
                {"type": "TimingMark", "name": "first_token"},
            ],
            "duplicate",
        ),
        (
            [{"type": "TimingMark", "name": "attempt_start"}, {"type": "TextDelta", "text": "x"}],
            "immediately",
        ),
    ):
        invalid = copy.deepcopy(record)
        invalid["public"]["events"] = events
        with pytest.raises(observation.ObservationError, match=match):
            checker._qualify_timing(invalid)
    next_attempt = copy.deepcopy(record)
    next_attempt["public"]["events"] = [
        {"type": "TimingMark", "name": "attempt_start"},
        {"type": "TimingMark", "name": "first_token"},
        {"type": "TextDelta", "text": "first"},
        {"type": "AttemptFailed", "record": {}},
        {"type": "TimingMark", "name": "attempt_start"},
        {"type": "TimingMark", "name": "first_token"},
    ]
    with pytest.raises(observation.ObservationError, match="first_token"):
        checker._qualify_timing(next_attempt)
    intervening = copy.deepcopy(record)
    intervening["public"]["events"] = [
        {"type": "TimingMark", "name": "attempt_start"},
        {"type": "TimingMark", "name": "first_token"},
        {"type": "CitationDelta", "citation": {}},
        {"type": "TextDelta", "text": "late"},
    ]
    with pytest.raises(observation.ObservationError, match="immediately"):
        checker._qualify_timing(intervening)


def test_repair_boundary_requires_correlated_repair_telemetry() -> None:
    record = {
        "public": {
            "events": [
                {"type": "TimingMark", "name": "attempt_start"},
                {"type": "TimingMark", "name": "first_token"},
                {"type": "TextDelta", "text": "invalid"},
                {"type": "TimingMark", "name": "attempt_start"},
                {"type": "TimingMark", "name": "first_token"},
                {"type": "TextDelta", "text": "repaired"},
                {"type": "StreamEnded", "result": {}},
            ],
            "result": {
                "timing": {"first_token_present": True, "total_present": True},
                "attempts": [{"attempt_number": 1}],
            },
        },
        "telemetry": {"events": [{"stable": {"event": "RepairAttempted", "attempt_number": 1}}]},
    }
    checker._qualify_timing(record)
    record["telemetry"]["events"] = []
    with pytest.raises(observation.ObservationError, match="duplicate"):
        checker._qualify_timing(record)


def _repair_record() -> dict[str, Any]:
    """Actual-capture-shaped normalized streamed repair evidence."""
    error = "ok: True was expected"
    rejected = '{"ok": false}'
    prefix = "Your previous response did not match the required JSON schema. Errors:\n"
    suffix = (
        "\nRespond again with ONLY a corrected JSON value that satisfies the schema. "
        "No prose, no code fences."
    )
    feedback = prefix + f"- {error}" + suffix

    def leaf(path: str, text: str) -> dict[str, Any]:
        return {
            "path": path,
            "utf8_length": len(text.encode("utf-8")),
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        }

    initial = [{"role": "system", "content": [{"type": "text", "text": "rule"}]}]
    return {
        "public": {
            "events": [
                {"type": "TimingMark", "name": "attempt_start"},
                {"type": "TimingMark", "name": "first_token"},
                {"type": "TextDelta", "text": rejected},
                {"type": "TimingMark", "name": "attempt_start"},
                {"type": "TimingMark", "name": "first_token"},
                {"type": "TextDelta", "text": '{"ok": true}'},
            ]
        },
        "wire": {
            "calls": [
                {
                    "transport": "adapter",
                    "provider": "repair",
                    "model": "model",
                    "request": {"messages": initial},
                },
                {
                    "transport": "adapter",
                    "provider": "repair",
                    "model": "model",
                    "request": {
                        "messages": [
                            *initial,
                            {"role": "assistant", "content": [{"type": "text", "text": rejected}]},
                            {"role": "user", "content": [{"type": "text", "text": feedback}]},
                        ]
                    },
                },
            ]
        },
        "telemetry": {
            "events": [
                {
                    "stable": {"event": "RepairAttempted", "attempt_number": 1, "errors": [error]},
                    "serialized": {"string_leaves": [leaf("/errors/0", error)]},
                }
            ],
            "manifest": {
                "serialized": {
                    "field_paths": ["/structured/repairs/0/errors/0"],
                    "string_leaves": [leaf("/structured/repairs/0/errors/0", error)],
                }
            },
        },
    }


def test_repair_evidence_joins_actual_stream_template_and_manifest() -> None:
    record = _repair_record()
    checker._qualify_repair_evidence(record)

    mismatched_rejected = copy.deepcopy(record)
    mismatched_rejected["wire"]["calls"][1]["request"]["messages"][-2]["content"][0]["text"] = (
        "other"
    )
    with pytest.raises(observation.ObservationError, match="rejected text"):
        checker._qualify_repair_evidence(mismatched_rejected)

    invalid_template = copy.deepcopy(record)
    invalid_template["wire"]["calls"][1]["request"]["messages"][-1]["content"][0]["text"] = "wrong"
    with pytest.raises(observation.ObservationError, match="feedback"):
        checker._qualify_repair_evidence(invalid_template)


@pytest.mark.parametrize("location", ["telemetry", "manifest"])
def test_repair_evidence_rejects_stale_error_digest(location: str) -> None:
    record = _repair_record()
    if location == "telemetry":
        leaf = record["telemetry"]["events"][0]["serialized"]["string_leaves"][0]
    else:
        leaf = record["telemetry"]["manifest"]["serialized"]["string_leaves"][0]
    leaf["sha256"] = "0" * 64
    with pytest.raises(observation.ObservationError, match="actual error snapshot"):
        checker._qualify_repair_evidence(record)


def test_repair_qualification_does_not_interpret_raw_error_lookalikes() -> None:
    record = _repair_record()
    record["telemetry"]["events"] = []
    record["wire"]["calls"] = [{"transport": "http", "body": {"errors": ["opaque"]}}]
    checker._qualify_repair_evidence(record)


def test_declared_numeric_controls_allow_int_float_only_at_named_paths() -> None:
    left = {"wire": {"calls": [{"request": {"timeout_s": 120.0}}]}}
    right = {"wire": {"calls": [{"request": {"timeout_s": 120}}]}}
    assert checker._compare(left, right) is None
    wrong = {"wire": {"calls": [{"request": {"timeout_s": 121}}]}}
    assert checker._compare(left, wrong)
    boolean = {"wire": {"calls": [{"request": {"timeout_s": False}}]}}
    assert checker._compare(left, boolean)
    raw_left = {"wire": {"calls": [{"body": {"timeout_s": 120.0}}]}}
    raw_right = {"wire": {"calls": [{"body": {"timeout_s": 120}}]}}
    assert checker._compare(raw_left, raw_right)
    null_left = {"wire": {"calls": [{"request": {"sampling": {"temperature": None}}}]}}
    null_right = copy.deepcopy(null_left)
    assert checker._compare(null_left, null_right) is None
    nonnull = {"wire": {"calls": [{"request": {"sampling": {"temperature": 0}}}]}}
    assert checker._compare(null_left, nonnull)


@pytest.mark.parametrize(
    "event",
    [
        {"type": "TextDelta", "text": ""},
        {"type": "ReasoningDelta", "text": ""},
        {
            "type": "ToolCallDelta",
            "index": 0,
            "call_id": "id",
            "name": "tool",
            "arguments_fragment": "",
        },
    ],
)
def test_empty_content_events_follow_first_token(event: dict[str, Any]) -> None:
    record = {
        "public": {
            "events": [
                {"type": "TimingMark", "name": "attempt_start"},
                {"type": "TimingMark", "name": "first_token"},
                event,
                {"type": "StreamEnded", "result": {}},
            ],
            "result": {"timing": {"first_token_present": True, "total_present": True}},
        },
        "telemetry": {"events": []},
    }
    checker._qualify_timing(record)


def test_canonical_data_requires_strict_json_and_matching_digest() -> None:
    text = '{"nested":[1,true]}'
    value = {"canonical_json": text, "sha256": hashlib.sha256(text.encode()).hexdigest()}
    record = {
        "public": {"result": None},
        "wire": {
            "calls": [
                {
                    "transport": "adapter",
                    "request": {
                        "reasoning_wire": value,
                        "extra_options": value,
                        "wire_schema": None,
                        "session_state": {"state": "absent"},
                        "tools": [],
                        "messages": [],
                    },
                }
            ]
        },
    }
    checker._qualify_canonical_slots(record)
    for broken in ({**value, "sha256": "0" * 64}, {**value, "canonical_json": '{"x":1,"x":2}'}):
        with pytest.raises(observation.ObservationError):
            invalid = copy.deepcopy(record)
            invalid["wire"]["calls"][0]["request"]["reasoning_wire"] = broken
            checker._qualify_canonical_slots(invalid)


def test_raw_and_http_canonical_shaped_objects_are_not_verifier_metadata() -> None:
    opaque = {"canonical_json": "not JSON", "sha256": "not-a-digest"}
    record = {
        "public": {"result": None},
        "wire": {"calls": [{"transport": "http", "body": {"raw": opaque}}]},
    }
    checker._qualify_canonical_slots(record)


def test_request_ids_are_runtime_local_but_internally_correlated() -> None:
    def record(request_id: str) -> dict[str, Any]:
        digest = hashlib.sha256(request_id.encode()).hexdigest()
        leaf = {"path": "/request_id", "utf8_length": len(request_id), "sha256": digest}
        return {
            "telemetry": {
                "events": [
                    {
                        "stable": {"event": "RequestStarted", "request_id": request_id},
                        "serialized": {"string_leaves": [leaf]},
                    },
                    {
                        "stable": {
                            "event": "FirstToken",
                            "request_id": request_id,
                            "at_ms_present": True,
                        },
                        "serialized": {"string_leaves": [copy.deepcopy(leaf)]},
                    },
                ],
                "manifest": {"serialized": {"string_leaves": [copy.deepcopy(leaf)]}},
            }
        }

    python, native = record("python-id"), record("native-id")
    checker._qualify_request_identity(python)
    checker._qualify_request_identity(native)
    assert checker._comparison_value(python) == checker._comparison_value(native)
    native["telemetry"]["events"][1]["stable"]["request_id"] = "wrong"
    with pytest.raises(observation.ObservationError, match="correlation"):
        checker._qualify_request_identity(native)
    native = record("native-id")
    native["telemetry"]["manifest"]["serialized"]["string_leaves"][0]["sha256"] = "0" * 64
    with pytest.raises(observation.ObservationError, match="manifest serialized"):
        checker._qualify_request_identity(native)
    native = record("native-id")
    native["telemetry"]["manifest"]["serialized"]["string_leaves"] = []
    with pytest.raises(observation.ObservationError, match="manifest must retain"):
        checker._qualify_request_identity(native)
    native = record("native-id")
    native["telemetry"]["events"][1]["serialized"]["string_leaves"] = []
    with pytest.raises(observation.ObservationError, match="telemetry must retain"):
        checker._qualify_request_identity(native)


def test_privacy_requires_visible_public_markers_and_absent_serialized_digests() -> None:
    case = _case("raw-retained-versus-private-telemetry")
    record = _record(case, manifest=True)
    record["public"]["entry_point"] = "async_stream"
    record["public"]["error"] = None
    record["public"]["result"] = {
        "text": "answer-marker",
        "tool_calls": [],
        "target": {"provider_id": "privacy", "model": "model", "via_alias": None},
        "finish_reason": "stop",
        "usage": {
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
            "cache_read_tokens": None,
            "cache_write_tokens": None,
            "reasoning_tokens": None,
            "cost_usd": None,
            "search_units": None,
            "server_tool_uses": [],
        },
        "logprobs": [],
        "citations": [],
        "server_tool_uses": [],
        "raw": {"raw": "raw-marker"},
        "timing": {"first_token_present": False, "total_present": True, "phase_order": []},
        "attempts": [],
        "warnings": [],
    }
    # Reasoning is deliberately public event content while default serialization remains empty.
    record["public"]["events"] = [{"type": "ReasoningDelta", "text": "reasoning-marker"}]
    checker._qualify_privacy(case, record)
    digest = hashlib.sha256(b"answer-marker").hexdigest()
    record["telemetry"]["manifest"]["serialized"]["string_leaves"].append(
        {"path": "x", "utf8_length": 13, "sha256": digest}
    )
    with pytest.raises(observation.ObservationError, match="planted"):
        checker._qualify_privacy(case, record)
