"""Compare independent rich-generation-v1 observation recordings strictly.

The fixture is deliberately input-only.  This checker validates evidence produced by
two observers; it never derives an SDK outcome from the fixture's requests or scripts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, NoReturn

import _csharp_observation as observation
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

PROFILE = "rich-generation-v1"
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "tests" / "fixtures" / PROFILE / "inputs.json"
DEFAULT_OUTPUT_ROOT = ROOT / ".tmp-tests" / "rich-generation"
INPUT_SCHEMA = ROOT / "tests" / "fixtures" / PROFILE / "schema.json"
OBSERVATION_SCHEMA = ROOT / "tests" / "fixtures" / PROFILE / "observations.schema.json"
FROZEN_CORPUS_SHA256 = "9cff7a50fbfd553ebcfed25186173579fff582796721d0e83cc656e116cc1777"
FROZEN_SCHEMA_SHA256 = "5c02e14c8ebf96432755e19b63a4a065b3a7696a8c7f6eb0c300c880c9080cae"
FROZEN_OBSERVATION_SCHEMA_SHA256 = (
    "da4ab3ac0c084bd2cfc6ca762dfeabfbe7eb67998b08e01d6ae94c0de21f6951"
)
FROZEN_README_SHA256 = "dd5037a5fe159fe1ecba2c1c16d25762d0717f2013f791b654c668692c23404e"
RUNNER = observation.RunnerConfig(
    python_observer=ROOT / "scripts" / "observe_python_rich_generation.py",
    native_project="AnyInfer.RichGeneration",
    native_csproj="AnyInfer.RichGeneration/AnyInfer.RichGeneration.csproj",
    dirty_property="RichGenerationSourceDirty",
)
_VALIDATION_TYPES = frozenset(
    {"ValueError", "ArgumentException", "ArgumentOutOfRangeException", "ArgumentNullException"}
)
_MARKER = "marker"
_PORTABLE_ERROR_TYPES = {
    "ProviderError": "ProviderException",
    "UnsupportedInputError": "UnsupportedInputException",
    "AllTargetsFailedError": "AllTargetsFailedException",
    "CancelledError": "OperationCanceledException",
}
_TYPED_ERROR_PATH = re.compile(
    r"^observation\.(?:public\.error|public\.events\[\d+\]\.record\.error|"
    r"public\.(?:result|events\[\d+\]\.result)\.attempts\[\d+\]\.error|"
    r"telemetry\.events\[\d+\]\.stable\.error)$"
)
_NUMERIC_CONTROL_PATH = re.compile(
    r"^observation\.(?:wire\.calls\[\d+\]\.request\.(?:timeout_s|sampling\.(?:temperature|top_p|presence_penalty|frequency_penalty))|"
    r"(?:public|telemetry\.events\[\d+\]\.stable)\..*error\.retry_after_s|"
    r"telemetry\.events\[\d+\]\.stable\.delay_s)$"
)


def _fail(message: str) -> NoReturn:
    raise observation.ObservationError(message)


def _validate_schema(path: Path, value: Any, *, label: str) -> None:
    try:
        Draft202012Validator(observation.read_json_bytes(path)).validate(value)
    except (SchemaError, ValidationError) as error:
        _fail(f"{label} does not satisfy its frozen schema: {error.message}")


def _verify_frozen_assets() -> None:
    """Reject changed profile grammar or prose before accepting its recordings."""
    for path, expected in (
        (INPUT_SCHEMA, FROZEN_SCHEMA_SHA256),
        (OBSERVATION_SCHEMA, FROZEN_OBSERVATION_SCHEMA_SHA256),
        (INPUT_SCHEMA.with_name("README.md"), FROZEN_README_SHA256),
    ):
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            _fail(f"{path.name} bytes do not match its frozen SHA-256")


def _finite(value: Any, where: str) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        _fail(f"{where} contains a nonfinite number")
    if isinstance(value, dict):
        for nested in value.values():
            _finite(nested, where)
    elif isinstance(value, list):
        for nested in value:
            _finite(nested, where)


def _marker_strings(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, str) and _MARKER in value:
        found.add(value)
    elif isinstance(value, dict):
        for key, nested in value.items():
            found.update(_marker_strings(key))
            found.update(_marker_strings(nested))
    elif isinstance(value, list):
        for nested in value:
            found.update(_marker_strings(nested))
    return found


def _leaf_digests(serialized: Mapping[str, Any]) -> set[str]:
    return {
        item["sha256"]
        for item in serialized["string_leaves"]
        if isinstance(item, dict) and isinstance(item.get("sha256"), str)
    }


def _strict_json(text: str, where: str) -> None:
    """Parse canonical JSON without accepting duplicate keys or nonfinite constants."""
    try:
        json.loads(
            text,
            object_pairs_hook=lambda pairs: _unique_json_object(pairs, where),
            parse_constant=lambda value: _fail(f"{where} has nonstandard constant {value!r}"),
        )
    except json.JSONDecodeError as error:
        _fail(f"{where} is not JSON: {error}")


def _unique_json_object(pairs: list[tuple[str, Any]], where: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail(f"{where} has duplicate JSON key {key!r}")
        result[key] = value
    return result


def _verify_canonical_data(value: Any, where: str) -> None:
    """Verify one schema-defined canonical-data slot, never arbitrary JSON payloads."""
    if not isinstance(value, dict) or set(value) != {"canonical_json", "sha256"}:
        _fail(f"{where} is not canonical-data evidence")
    text, digest = value["canonical_json"], value["sha256"]
    if not isinstance(text, str) or not isinstance(digest, str):
        _fail(f"{where} canonical data has invalid fields")
    _strict_json(text, f"{where}.canonical_json")
    if hashlib.sha256(text.encode("utf-8")).hexdigest() != digest:
        _fail(f"{where} canonical-data SHA-256 does not match canonical_json")


def _qualify_canonical_slots(record: Mapping[str, Any]) -> None:
    """Walk only canonicalData locations named by observations.schema.json."""
    result = record["public"]["result"]
    if result is not None:
        for index, call in enumerate(result["tool_calls"]):
            _verify_canonical_data(
                call["arguments"], f"public.result.tool_calls[{index}].arguments"
            )
    for call_index, call in enumerate(record["wire"]["calls"]):
        if call["transport"] != "adapter":
            continue
        request = call["request"]
        _verify_canonical_data(
            request["reasoning_wire"], f"wire.calls[{call_index}].reasoning_wire"
        )
        _verify_canonical_data(request["extra_options"], f"wire.calls[{call_index}].extra_options")
        if request["wire_schema"] is not None:
            _verify_canonical_data(request["wire_schema"], f"wire.calls[{call_index}].wire_schema")
        state = request["session_state"]
        if state["state"] == "value":
            _verify_canonical_data(state["value"], f"wire.calls[{call_index}].session_state.value")
        for tool_index, tool in enumerate(request["tools"]):
            _verify_canonical_data(
                tool["parameters"], f"wire.calls[{call_index}].tools[{tool_index}].parameters"
            )
        for message_index, message in enumerate(request["messages"]):
            for part_index, part in enumerate(message["content"]):
                if part["type"] == "tool_call":
                    _verify_canonical_data(
                        part["arguments"],
                        f"wire.calls[{call_index}].messages[{message_index}].content[{part_index}].arguments",
                    )


def _qualify_privacy(case: observation.Case, record: Mapping[str, Any]) -> None:
    """Require serialization evidence to retain privacy claims without retaining payloads."""
    if case.identifier != "raw-retained-versus-private-telemetry":
        return
    public = record["public"]
    visible = _marker_strings(public)
    if not {"answer-marker", "reasoning-marker", "raw-marker"}.issubset(visible):
        _fail("privacy case public capture omits planted marker evidence")
    telemetry = record["telemetry"]
    blobs = [event["serialized"] for event in telemetry["events"]]
    if telemetry["manifest"] is not None:
        blobs.append(telemetry["manifest"]["serialized"])
    leaves = {digest for blob in blobs for digest in _leaf_digests(blob)}
    # A recorder may not replace a visible string with an unproved omission: each marker's
    # digest must be absent from default telemetry/manifest leaves.
    if any(hashlib.sha256(marker.encode()).hexdigest() in leaves for marker in visible):
        _fail("privacy serialization exposes a planted public marker")


def _qualify_timing(record: Mapping[str, Any]) -> None:
    """Validate the finite per-attempt public timing state, not elapsed values."""
    public = record["public"]
    events = public["events"]
    open_attempt = False
    attempt_first_token = False
    any_first_token = False
    pending_first_content = False
    entry_has_content = False
    repair_events = [
        event["stable"]
        for event in record["telemetry"]["events"]
        if event["stable"]["event"] == "RepairAttempted"
    ]
    result_attempts = (public["result"] or {}).get("attempts", [])
    known_attempts = {attempt["attempt_number"] for attempt in result_attempts}
    consumed_repairs = 0
    for event in events:
        if pending_first_content and event["type"] not in {
            "TextDelta",
            "ReasoningDelta",
            "ToolCallDelta",
            "AttemptFailed",
            "StreamEnded",
        }:
            _fail("first_token timing mark is not immediately adjacent to first content")
        if event["type"] in {"AttemptFailed", "StreamEnded"}:
            if event["type"] == "StreamEnded" and pending_first_content:
                _fail("completed entry has first_token timing mark without content")
            open_attempt = False
            attempt_first_token = False
            pending_first_content = False
            entry_has_content = False
            continue
        if event["type"] in {"TextDelta", "ReasoningDelta", "ToolCallDelta"}:
            if not open_attempt:
                _fail("content event lacks a preceding attempt_start")
            if not attempt_first_token:
                _fail("first content lacks an immediately preceding first_token timing mark")
            pending_first_content = False
            entry_has_content = True
            continue
        if event["type"] != "TimingMark":
            continue
        if event["name"] == "attempt_start":
            if open_attempt:
                repair = (
                    repair_events[consumed_repairs]
                    if consumed_repairs < len(repair_events)
                    else None
                )
                if (
                    not entry_has_content
                    or pending_first_content
                    or repair is None
                    or repair["attempt_number"] not in known_attempts
                ):
                    _fail("timing marks duplicate attempt_start before a terminal event")
                consumed_repairs += 1
            open_attempt = True
            attempt_first_token = False
            pending_first_content = False
            entry_has_content = False
        elif event["name"] == "first_token":
            if not open_attempt:
                _fail("first_token timing mark lacks a preceding attempt_start")
            if attempt_first_token:
                _fail("attempt has duplicate first_token timing marks")
            attempt_first_token = True
            pending_first_content = True
            any_first_token = True
        else:
            _fail("unknown timing mark")
        if event is not events[-1] and event["name"] == "first_token":
            pass
    result = public["result"]
    if result is not None:
        if pending_first_content:
            _fail("completed entry has first_token timing mark without content")
        timing = result["timing"]
        telemetry_first = [
            event["stable"]
            for event in record["telemetry"]["events"]
            if event["stable"]["event"] == "FirstToken"
        ]
        telemetry_present = any(event["at_ms_present"] for event in telemetry_first)
        if timing["first_token_present"] != (any_first_token or telemetry_present):
            _fail("terminal first-token timing presence disagrees with ordered marks")
        if not timing["total_present"]:
            _fail("completed result must retain total timing presence")


def _qualify_request_identity(record: Mapping[str, Any]) -> None:
    events = record["telemetry"]["events"]
    if not events:
        return
    stable = [event["stable"] for event in events]
    started = [event for event in stable if event["event"] == "RequestStarted"]
    if len(started) != 1 or not started[0]["request_id"]:
        _fail("telemetry must carry one nonempty RequestStarted request_id")
    request_id = started[0]["request_id"]
    if any(event["request_id"] != request_id for event in stable):
        _fail("telemetry request_id correlation is broken")
    digest = hashlib.sha256(request_id.encode("utf-8")).hexdigest()
    expected_length = len(request_id.encode("utf-8"))

    def require_identity_leaf(serialized: Mapping[str, Any], where: str) -> None:
        leaves = [leaf for leaf in serialized["string_leaves"] if leaf["path"] == "/request_id"]
        if len(leaves) != 1:
            _fail(f"{where} must retain exactly one serialized request_id leaf")
        leaf = leaves[0]
        if leaf["sha256"] != digest or leaf["utf8_length"] != expected_length:
            _fail(f"{where} serialized request_id evidence does not match its stable request_id")

    for event in events:
        require_identity_leaf(event["serialized"], "telemetry")
    manifest = record["telemetry"]["manifest"]
    if manifest is not None:
        require_identity_leaf(manifest["serialized"], "manifest")


def _error_leaf(serialized: Mapping[str, Any], path: str, value: str, where: str) -> None:
    leaves = [leaf for leaf in serialized["string_leaves"] if leaf["path"] == path]
    if len(leaves) != 1:
        _fail(f"{where} must retain exactly one {path} string leaf")
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    if leaves[0]["utf8_length"] != len(value.encode("utf-8")) or leaves[0]["sha256"] != digest:
        _fail(f"{where} {path} leaf does not match its actual error snapshot")


def _qualify_error_evidence(record: Mapping[str, Any]) -> None:
    """Join named serialized error leaves to their actual typed snapshots."""
    for event in record["telemetry"]["events"]:
        error = event["stable"].get("error")
        if error is None:
            continue
        _error_leaf(event["serialized"], "/error/type_name", error["type_name"], "telemetry")
        if "/error/detail" not in event["serialized"]["field_paths"]:
            _fail("telemetry error detail field path is missing")
        if error["detail"] is not None:
            _error_leaf(event["serialized"], "/error/detail", error["detail"], "telemetry")
    manifest = record["telemetry"]["manifest"]
    result = record["public"]["result"]
    if manifest is None or result is None:
        return
    for index, attempt in enumerate(result["attempts"]):
        error = attempt["error"]
        if error is None:
            continue
        prefix = f"/attempts/{index}/error"
        _error_leaf(manifest["serialized"], f"{prefix}/type_name", error["type_name"], "manifest")
        if f"{prefix}/detail" not in manifest["serialized"]["field_paths"]:
            _fail("manifest error detail field path is missing")
        if error["detail"] is not None:
            _error_leaf(manifest["serialized"], f"{prefix}/detail", error["detail"], "manifest")


def _qualify_literal_failures(case: observation.Case, record: Mapping[str, Any]) -> None:
    """Join invoked literal provider-failure stimuli to their actual public failure evidence."""
    literals: list[tuple[str, str, Mapping[str, Any]]] = []
    for script in case.raw.get("scripts", []):
        actions = script.get("actions", [])
        if actions and actions[0].get("action") == "provider_failure":
            literals.append((script["provider"], script["model"], actions[0]["failure"]))
    if not literals:
        return
    invoked = {(wire["provider"], wire["model"]) for wire in record["wire"]["calls"]}
    events = record["public"]["events"]
    records = [event["record"] for event in events if event["type"] == "AttemptFailed"]
    result = record["public"]["result"]
    if result is not None:
        records.extend(result["attempts"])
    for provider, model, literal in literals:
        if (provider, model) not in invoked:
            continue
        matching = [
            item
            for item in records
            if item.get("target", {}).get("provider_id") == provider
            and item.get("target", {}).get("model") == model
            and item.get("error") is not None
        ]
        if not matching:
            _fail("invoked literal provider failure has no reported public attempt failure")
        error = matching[0]["error"]
        expected = {
            "provider": provider,
            "phase": literal.get("phase", "generate"),
            "retryable": literal.get("retryable"),
            "http_status": literal.get("http_status"),
        }
        for key, value in expected.items():
            if error.get(key) != value:
                _fail("reported provider failure facts differ from literal script failure")
        if error.get("detail") != literal.get("detail"):
            _fail("reported provider failure detail differs from literal script failure")
        fallback = [
            event["stable"]
            for event in record["telemetry"]["events"]
            if event["stable"]["event"] == "FallbackTriggered"
            and event["stable"]["from_target"]["provider_id"] == provider
            and event["stable"]["from_target"]["model"] == model
        ]
        for event in fallback:
            if event["error"] is None or event["error"].get("detail") != literal.get("detail"):
                _fail("fallback error detail differs from literal script failure")


def _qualify_repair_evidence(record: Mapping[str, Any]) -> None:
    """Join normalized streamed repair feedback to its actual telemetry and adapter calls."""
    repairs = [
        event
        for event in record["telemetry"]["events"]
        if event["stable"]["event"] == "RepairAttempted"
    ]
    wires = record["wire"]["calls"]
    public_events = record["public"]["events"]
    attempt_starts = [
        position
        for position, entry in enumerate(public_events)
        if entry["type"] == "TimingMark" and entry["name"] == "attempt_start"
    ]
    manifest = record["telemetry"]["manifest"]
    for index, event in enumerate(repairs):
        errors = event["stable"]["errors"]
        for error_index, text in enumerate(errors):
            _error_leaf(event["serialized"], f"/errors/{error_index}", text, "repair telemetry")
            if manifest is not None:
                manifest_path = f"/structured/repairs/{index}/errors/{error_index}"
                if manifest_path not in manifest["serialized"]["field_paths"]:
                    _fail("repair manifest is missing its error field path")
                _error_leaf(manifest["serialized"], manifest_path, text, "repair manifest")
        if (
            index + 1 >= len(wires)
            or wires[index]["transport"] != "adapter"
            or wires[index + 1]["transport"] != "adapter"
        ):
            _fail("RepairAttempted has no adjacent normalized adapter correction call")
        previous, correction = wires[index], wires[index + 1]
        if (previous["provider"], previous["model"]) != (
            correction["provider"],
            correction["model"],
        ):
            _fail("repair correction call changes provider or model")
        first_messages = previous["request"]["messages"]
        messages = correction["request"]["messages"]
        preserved = messages[: len(first_messages)] == first_messages
        if not preserved or len(messages) != len(first_messages) + 2:
            _fail("repair correction must preserve prior messages plus correction entries")
        rejected, feedback = messages[-2:]
        if rejected["role"] != "assistant" or feedback["role"] != "user":
            _fail("repair correction history roles are invalid")
        attempt_number = event["stable"]["attempt_number"]
        if not isinstance(attempt_number, int) or isinstance(attempt_number, bool):
            _fail("RepairAttempted must name an integer failed attempt")
        failed_attempt = attempt_number - 1
        if failed_attempt < 0 or failed_attempt + 1 >= len(attempt_starts):
            _fail("RepairAttempted has no following streamed repair attempt")
        start, next_start = attempt_starts[failed_attempt : failed_attempt + 2]
        rejected_text = "".join(
            entry["text"]
            for entry in public_events[start + 1 : next_start]
            if entry["type"] == "TextDelta"
        )
        if rejected["content"] != [{"type": "text", "text": rejected_text}]:
            _fail("repair correction rejected text does not match streamed TextDelta evidence")
        prefix = "Your previous response did not match the required JSON schema. Errors:\n"
        suffix = (
            "\nRespond again with ONLY a corrected JSON value that satisfies the schema. "
            "No prose, no code fences."
        )
        expected = prefix + "\n".join(f"- {item}" for item in errors) + suffix
        if feedback["content"] != [{"type": "text", "text": expected}]:
            _fail("repair correction feedback does not join actual RepairAttempted errors")


def qualify_observation(case: observation.Case, record: dict[str, Any], *, runtime: str) -> None:
    """Apply profile-local evidence invariants only; do not predict SDK behavior."""
    if record.get("id") != case.identifier or record.get("kind") != case.kind:
        _fail("observation identity or kind does not match frozen input")
    _finite(record, "observation")
    public = record["public"]
    if case.kind == "validation":
        if (
            public["entry_point"] != "construct_request"
            or public["result"] is not None
            or public["events"]
            or record["wire"]["calls"]
            or record["telemetry"]["events"]
            or record["telemetry"]["manifest"] is not None
        ):
            _fail("validation case must not dispatch or return a generation result")
        error = public["error"]
        if error is not None and error["type_name"] not in _VALIDATION_TYPES:
            _fail("validation case error is not an approved constructor-error spelling")
        _qualify_canonical_slots(record)
        return
    close = case.raw["procedure"]["name"] == "async_stream_close"
    if not close and (public["result"] is None) == (public["error"] is None):
        _fail("public observation must contain exactly one terminal result or error")
    if close and public["result"] is not None and public["error"] is not None:
        _fail("early-close observation cannot contain both result and error")
    _qualify_timing(record)
    _qualify_request_identity(record)
    _qualify_error_evidence(record)
    _qualify_literal_failures(case, record)
    _qualify_repair_evidence(record)
    _qualify_canonical_slots(record)
    _qualify_privacy(case, record)


def _compare_error(
    left: Mapping[str, Any], right: Mapping[str, Any], path: str, *, constructor_alias: bool
) -> str | None:
    if (
        constructor_alias
        and left["type_name"] in _VALIDATION_TYPES
        and right["type_name"] in _VALIDATION_TYPES
    ):
        for key in ("provider", "phase", "retryable", "retry_after_s", "http_status"):
            if left[key] != right[key]:
                return f"{path}.{key} differs"
        return None
    if _PORTABLE_ERROR_TYPES.get(left["type_name"]) == right["type_name"]:
        for key in ("provider", "phase", "retryable", "retry_after_s", "http_status"):
            if left[key] != right[key]:
                return f"{path}.{key} differs"
        return None
    return _compare_dict(left, right, path, constructor_alias=False)


def _is_timing_path(path: str) -> bool:
    return path.endswith(
        (".timing.first_token_present", ".timing.total_present", ".timing.phase_order")
    )


def _numeric_control_equal(left: Any, right: Any, path: str) -> bool | None:
    """Compare only declared typed numeric controls, preserving all other JSON types."""
    if _NUMERIC_CONTROL_PATH.fullmatch(path) is None:
        return None
    if left is None or right is None:
        return left is right
    if type(left) not in (int, float) or type(right) not in (int, float):
        return False
    return math.isfinite(left) and math.isfinite(right) and left == right


def _compare(
    left: Any, right: Any, path: str = "observation", *, constructor_alias: bool = False
) -> str | None:
    if (
        constructor_alias
        and path == "observation.public.error"
        and isinstance(left, dict)
        and isinstance(right, dict)
    ):
        return _compare_error(left, right, path, constructor_alias=True)
    if (
        _TYPED_ERROR_PATH.fullmatch(path) is not None
        and isinstance(left, dict)
        and isinstance(right, dict)
    ):
        return _compare_error(left, right, path, constructor_alias=False)
    if _is_timing_path(path):
        return None if left == right else f"{path} differs"
    numeric = _numeric_control_equal(left, right, path)
    if numeric is not None:
        return None if numeric else f"{path} differs"
    if type(left) is not type(right):
        return f"{path} types differ"
    if isinstance(left, dict):
        return _compare_dict(left, right, path, constructor_alias=constructor_alias)
    if isinstance(left, list):
        if len(left) != len(right):
            return f"{path} lengths differ"
        for index, (first, second) in enumerate(zip(left, right, strict=True)):
            difference = _compare(
                first, second, f"{path}[{index}]", constructor_alias=constructor_alias
            )
            if difference:
                return difference
        return None
    return None if left == right else f"{path} differs"


def _compare_dict(
    left: Mapping[str, Any], right: Mapping[str, Any], path: str, *, constructor_alias: bool
) -> str | None:
    """Compare an ordinary mapping without re-entering the special error dispatch."""
    if left.keys() != right.keys():
        return f"{path} keys differ"
    for key in left:
        difference = _compare(
            left[key], right[key], f"{path}.{key}", constructor_alias=constructor_alias
        )
        if difference:
            return difference
    return None


def _comparison_value(record: dict[str, Any]) -> dict[str, Any]:
    """Normalize only declared per-runtime request identity evidence for comparison."""
    result = json.loads(json.dumps(record))
    for event in result["telemetry"]["events"]:
        event["stable"]["request_id"] = "<request-id>"
        error = event["stable"].get("error")
        for leaf in event["serialized"]["string_leaves"]:
            if leaf["path"] == "/request_id":
                leaf["utf8_length"] = "<request-id-length>"
                leaf["sha256"] = "<request-id-sha256>"
            if error is not None and leaf["path"] == "/error/type_name":
                leaf["utf8_length"] = "<portable-error-type-length>"
                leaf["sha256"] = "<portable-error-type-sha256>"
            if error is not None and leaf["path"] == "/error/detail":
                leaf["utf8_length"] = "<free-detail-length>"
                leaf["sha256"] = "<free-detail-sha256>"
        if event["stable"]["event"] == "RepairAttempted":
            event["stable"]["errors"] = ["<repair-diagnostic>" for _ in event["stable"]["errors"]]
            for leaf in event["serialized"]["string_leaves"]:
                if re.fullmatch(r"/errors/\d+", leaf["path"]):
                    leaf["utf8_length"] = "<repair-diagnostic-length>"
                    leaf["sha256"] = "<repair-diagnostic-sha256>"
    repairs = [
        event
        for event in record["telemetry"]["events"]
        if event["stable"]["event"] == "RepairAttempted"
    ]
    for index, repair in enumerate(repairs):
        if index + 1 < len(result["wire"]["calls"]):
            content = result["wire"]["calls"][index + 1]["request"]["messages"][-1]["content"]
            if content and content[0].get("type") == "text":
                prefix = "Your previous response did not match the required JSON schema. Errors:\n"
                suffix = (
                    "\nRespond again with ONLY a corrected JSON value that satisfies the schema. "
                    "No prose, no code fences."
                )
                content[0]["text"] = (
                    prefix
                    + "\n".join("- <repair-diagnostic>" for _ in repair["stable"]["errors"])
                    + suffix
                )
    manifest = result["telemetry"].get("manifest")
    if manifest is not None:
        attempts = (result.get("public", {}).get("result") or {}).get("attempts", [])
        for leaf in manifest["serialized"]["string_leaves"]:
            if leaf["path"] == "/request_id":
                leaf["utf8_length"] = "<request-id-length>"
                leaf["sha256"] = "<request-id-sha256>"
            if leaf["path"] == "/anyinfer_version":
                if leaf["utf8_length"] <= 0:
                    _fail("serialized anyinfer_version identity must be nonempty")
                leaf["utf8_length"] = "<runtime-version-length>"
                leaf["sha256"] = "<runtime-version-sha256>"
            match = re.fullmatch(r"/attempts/(\d+)/error/(type_name|detail)", leaf["path"])
            index = int(match.group(1)) if match else -1
            if match and index < len(attempts) and attempts[index]["error"]:
                leaf["utf8_length"] = f"<portable-{match.group(2)}-length>"
                leaf["sha256"] = f"<portable-{match.group(2)}-sha256>"
            if re.fullmatch(r"/structured/repairs/\d+/errors/\d+", leaf["path"]):
                leaf["utf8_length"] = "<repair-diagnostic-length>"
                leaf["sha256"] = "<repair-diagnostic-sha256>"
    return result


def compare_case(
    case: observation.Case, python: dict[str, Any], native: dict[str, Any]
) -> list[dict[str, str]]:
    """Qualify both captures then report their first strict observable difference."""
    qualify_observation(case, python, runtime="python")
    qualify_observation(case, native, runtime="csharp")
    difference = _compare(
        _comparison_value(python),
        _comparison_value(native),
        constructor_alias=case.kind == "validation",
    )
    return [] if difference is None else [{"id": case.identifier, "difference": difference}]


def read_observations(
    path: Path, *, cases: Sequence[observation.Case], runtime: str, digest: str
) -> observation.ObserverRun:
    """Read, schema-validate, and provenance-index one runtime's evidence."""
    raw = observation.read_json_bytes(path)
    _validate_schema(OBSERVATION_SCHEMA, raw, label=f"{runtime} observation")
    by_id = {case.identifier: case for case in cases}
    return observation.read_observations(
        path,
        profile=PROFILE,
        expected_cases=cases,
        expected_runtime=runtime,
        expected_corpus_sha256=digest,
        validate_observation=lambda record, _where: qualify_observation(
            by_id[record["id"]], record, runtime=runtime
        ),
    )


def _run(command: list[str], cwd: Path) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def main(argv: list[str] | None = None) -> int:
    """Run observers or compare supplied evidence and write a bounded report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--compare", nargs=2, type=Path, metavar=("PYTHON", "NATIVE"))
    options = parser.parse_args(sys.argv[1:] if argv is None else argv)
    input_path = options.input.resolve()
    _verify_frozen_assets()
    raw_input = observation.read_json_bytes(input_path)
    _validate_schema(INPUT_SCHEMA, raw_input, label="rich-generation input")
    _, cases = observation.read_cases(input_path, profile=PROFILE)
    digest = observation.corpus_sha256(input_path)
    if digest != FROZEN_CORPUS_SHA256:
        _fail("rich-generation-v1 input bytes do not match the frozen corpus SHA-256")
    directory = observation.fresh_run_directory(options.output_root.resolve())
    identity: tuple[str, bool] | None = None
    if options.compare:
        python_path, native_path = observation.copy_comparison_evidence(
            directory, *(path.resolve() for path in options.compare)
        )
    else:
        identity = observation.source_identity()
        python_path, native_path = observation.run_observers(
            RUNNER,
            input_path,
            directory,
            source_revision=identity[0],
            source_dirty=identity[1],
            run=_run,
        )
    python = read_observations(python_path, cases=cases, runtime="python", digest=digest)
    native = read_observations(native_path, cases=cases, runtime="csharp", digest=digest)
    observation.validate_handshake(python, native, stamped_identity=identity)
    mismatches = [
        difference
        for case in cases
        for difference in compare_case(
            case, python.observations[case.identifier], native.observations[case.identifier]
        )
    ]
    mismatched_ids = {item["id"] for item in mismatches}
    report = {
        "profile": PROFILE,
        "status": "pass" if not mismatches else "fail",
        "corpus_sha256": digest,
        "shared": {
            "matched": [
                case.identifier for case in cases if case.identifier not in mismatched_ids
            ],
            "mismatches": mismatches,
        },
        "runtime_specific": [],
        "native_only": [],
    }
    report_path = directory / "report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=True, indent=2) + "\n", encoding="utf-8"
    )
    print(f"{report['status']}: {report_path}")
    return int(bool(mismatches))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, observation.ObservationError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1) from None
