"""Compare independently observed request-policy-v1 experiments.

This checker deliberately owns only profile-specific qualification and comparison.
Raw JSON, provenance headers, fresh evidence directories, and process invocation come
from :mod:`_csharp_observation` so accounting keeps its established semantics.
"""

from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

import _csharp_observation as observation
from jsonschema import Draft202012Validator, ValidationError
from jsonschema.exceptions import SchemaError

ROOT = Path(__file__).resolve().parents[1]
CSHARP_ROOT = ROOT / "src" / "csharp"
PROFILE = "request-policy-v1"
DEFAULT_INPUT = ROOT / "tests" / "fixtures" / PROFILE / "inputs.json"
INPUT_SCHEMA = ROOT / "tests" / "fixtures" / PROFILE / "schema.json"
OBSERVATION_SCHEMA = ROOT / "tests" / "fixtures" / PROFILE / "observations.schema.json"
PYTHON_OBSERVER = ROOT / "tests" / "test_request_policy_parity.py"
DEFAULT_OUTPUT_ROOT = ROOT / ".tmp-tests" / "request-policy"
FROZEN_CORPUS_SHA256 = "92e0fc9f6e128db05719446a91b891e9ee9cacc989d97f392496a8f08e649316"

_ERROR_PAIRS = {
    ("ProviderError", "ProviderException"),
    ("ProviderUnavailableError", "ProviderUnavailableException"),
    ("ContextLengthError", "ContextLengthException"),
    ("SpendLimitError", "SpendLimitException"),
    ("AllTargetsFailedError", "AllTargetsFailedException"),
}
_CHECKPOINTS = {
    "single": (),
    "retry_replacement": (
        "before_dispatch",
        "after_initial_reserve",
        "after_retry_replacement",
        "after_terminal_cleanup",
    ),
    "fallback_handoff": (
        "before_dispatch",
        "after_initial_reserve",
        "after_fallback_handoff",
        "after_terminal_cleanup",
    ),
    "repair_no_recheck": (
        "before_dispatch",
        "after_initial_reserve",
        "after_repair",
        "after_terminal_cleanup",
    ),
    "stream_early_close": (
        "after_initial_reserve",
        "while_stream_open",
        "after_close",
        "after_terminal_cleanup",
    ),
    "concurrent_reservation_recovery": (
        "before_dispatch",
        "after_initial_reserve",
        "after_cancel",
        "after_terminal_cleanup",
    ),
    "context_route": (),
    "tool_stream": (),
    "cache_sequence": (),
    "governor_body_gate": (),
    "config_consumer": (),
}
_ESTIMATE_GROWTH_CHECKPOINTS = {
    "after_initial_reserve",
    "after_retry_replacement",
    "after_fallback_handoff",
}
_RECOVERY_TERMINAL_PROCEDURES = frozenset(
    {"stream_early_close", "concurrent_reservation_recovery"}
)
_CACHE_OFF_DIAGNOSTIC_CODES = frozenset({"cache.prefix-unstable"})
_IMPLICIT_DEGRADATION_REASON = "the target offers implicit caching, not explicit marks"
_FROZEN_MALFORMED_TOOL_ARGUMENTS = {
    "not-json": "had unparseable arguments; using an empty argument object",
    '{"x":': "had unparseable arguments; using an empty argument object",
    "[]": "arguments were not a JSON object; using an empty argument object",
}
_DIRECT_SPEND_TYPES = {
    "python": "SpendLimitError",
    "csharp": "SpendLimitException",
}
_CONCURRENT_TELEMETRY_PROCEDURES = frozenset(
    {"concurrent_reservation_recovery", "governor_body_gate", "config_consumer"}
)
_TRANSPORT_DEFAULT_HEADERS = frozenset(
    {"host", "user-agent", "accept-encoding", "connection", "content-length"}
)
_REDACTED_HEADER_VALUE = "[redacted]"
_REDACTED_BEARER_HEADER_VALUE = "Bearer [redacted]"
_NO_JSON_CANDIDATE_TEXT = frozenset({"not-json", "not json"})
_NO_JSON_CANDIDATE_DIAGNOSTICS = {
    "python": "response was not JSON and contained no JSON object or array",
    "csharp": "No balanced JSON object or array candidate was found.",
}
_REPAIR_PREFIX = "Your previous response did not match the required JSON schema. Errors:\n- "
_REPAIR_SUFFIX = (
    "\nRespond again with ONLY a corrected JSON value that satisfies the schema. No prose, "
    "no code fences."
)


class ObservationError(RuntimeError):
    """Signals unqualified policy evidence or a profile comparison mismatch."""


@dataclass(frozen=True)
class Comparison:
    """Profile-local comparison facts written into the evidence report."""

    profile: str
    matched: tuple[str, ...]
    mismatches: tuple[dict[str, str], ...]
    runtime_specific: tuple[dict[str, Any], ...]

    @property
    def status(self) -> str:
        """Return the command status without hiding unmatched raw evidence."""
        return "pass" if not self.mismatches else "fail"


def _fail(message: str) -> NoReturn:
    raise ObservationError(message)


def _mapping(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(f"{where} must be an object")
    return value


def _schema(path: Path) -> Draft202012Validator:
    value = _mapping(observation.read_json_bytes(path), f"schema {path}")
    try:
        Draft202012Validator.check_schema(value)
    except SchemaError as error:
        _fail(f"invalid schema {path}: {error}")
    return Draft202012Validator(value)


def _validate(validator: Draft202012Validator, value: Any, where: str) -> None:
    try:
        validator.validate(value)
    except ValidationError as error:
        location = "/".join(str(part) for part in error.absolute_path)
        _fail(f"{where} fails its closed schema at {location or '<root>'}: {error.message}")


def read_cases(path: Path) -> tuple[dict[str, Any], tuple[observation.Case, ...]]:
    """Read the frozen input grammar before choosing procedure obligations."""
    source, cases = observation.read_cases(path, profile=PROFILE)
    _validate(_schema(INPUT_SCHEMA), source, "input envelope")
    if observation.corpus_sha256(path) != FROZEN_CORPUS_SHA256:
        _fail("frozen request-policy corpus bytes do not match the accepted SHA-256")
    return source, cases


def _names(items: Sequence[Mapping[str, Any]], key: str) -> tuple[Any, ...]:
    return tuple(item[key] for item in items)


def _procedure(case: observation.Case) -> Mapping[str, Any]:
    return _mapping(case.raw.get("procedure"), f"case {case.identifier}.procedure")


def _request_components(case: observation.Case) -> int:
    request = case.raw.get("request", case.raw.get("action", {}))
    if not isinstance(request, dict):
        return 0
    messages = request.get("messages", [])
    tools = request.get("tools", [])
    return (
        (len(messages) if isinstance(messages, list) else 0)
        + (len(tools) if isinstance(tools, list) else 0)
        + int(request.get("schema") is not None)
    )


def _terminal_manifest_operation(value: Mapping[str, Any]) -> Mapping[str, Any] | None:
    successful = [
        operation
        for operation in value["operations"]
        if operation["outcome"] == "ok"
        and operation["result"] is not None
        and operation["result"]["manifest"] is not None
    ]
    return successful[0] if len(successful) == 1 else None


def _original_estimator_components(
    case: observation.Case,
    expected: Sequence[str],
    histories: Sequence[tuple[Any, ...]],
) -> tuple[Any, ...]:
    """Return the declared original-request prefix of the initial admission pass."""
    component_count = _request_components(case)
    initial_index = next(
        (
            index
            for index, checkpoint in enumerate(expected)
            if checkpoint == "after_initial_reserve"
        ),
        None,
    )
    if initial_index is None:
        _fail(f"case {case.identifier} terminal manifest lacks original admission inputs")
    initial_prior = histories[initial_index - 1] if initial_index else ()
    admission_delta = histories[initial_index][len(initial_prior) :]
    if len(admission_delta) < component_count:
        _fail(
            f"case {case.identifier} initial admission lacks declared original-request "
            "estimator components"
        )
    return admission_delta[:component_count]


def _concurrent_refusal_components(
    case: observation.Case,
    value: Mapping[str, Any],
    runtime: str,
    expected: Sequence[str],
    histories: Sequence[tuple[Any, ...]],
) -> tuple[Any, ...]:
    """Return the only concurrent middle-operation estimate growth we admit.

    The frozen concurrent procedure starts a held request, then lets a second request
    estimate its original input before its direct total-reservation refusal.  It is neither
    a retry nor recovery work, so it is permitted only when the real unsent middle
    operation exposes the declared direct-spend shape.
    """
    operations = value["operations"]
    if len(operations) != 3:
        _fail(f"case {case.identifier} concurrent procedure lacks three operations")
    middle = operations[1]
    if not _is_direct_spend(case, middle, runtime) or middle["relations"]["send_count"] != 0:
        _fail(
            f"case {case.identifier} concurrent after_cancel growth lacks an unsent "
            "direct-spend middle operation"
        )
    after_cancel = expected.index("after_cancel")
    prior = histories[after_cancel - 1]
    growth = histories[after_cancel][len(prior) :]
    components = _original_estimator_components(case, expected, histories)
    if growth != components:
        _fail(
            f"case {case.identifier} concurrent after_cancel must add exactly the "
            "middle original-request estimator components"
        )
    return components


def _recovery_estimator_components(
    case: observation.Case,
    expected: Sequence[str],
    histories: Sequence[tuple[Any, ...]],
) -> tuple[Any, ...]:
    """Return the source-order spend and context passes for a recovery request.

    A successful recovery re-enters the ordinary request path: the automatic spend
    admission estimates the original request first, then the context gate estimates that
    same request.  Each pass preserves the message/tool/schema component sequence.  This
    keeps the checker out of pricing or context arithmetic while rejecting made-up terminal
    history growth.
    """
    components = _original_estimator_components(case, expected, histories)
    return components + components


def _check_checkpoint_sequence(
    case: observation.Case, value: Mapping[str, Any], runtime: str = "python"
) -> None:
    procedure = _procedure(case)
    name = procedure.get("name")
    if name not in _CHECKPOINTS:
        _fail(f"case {case.identifier} has unsupported procedure {name!r}")
    expected = tuple(procedure.get("checkpoints", _CHECKPOINTS[name]))
    if not expected and name == "single" and "checkpoints" not in procedure:
        expected = ()
    actual = _names(value["checkpoints"], "name")
    if actual != expected:
        _fail(f"case {case.identifier} checkpoint sequence is {actual!r}, expected {expected!r}")
    if expected:
        if value["ledger"] is None:
            _fail(f"case {case.identifier} checkpoint procedure requires an actual ledger")
        histories = [tuple(checkpoint["estimator_inputs"]) for checkpoint in value["checkpoints"]]
        if expected[0] == "before_dispatch" and histories[0]:
            _fail(f"case {case.identifier} before_dispatch must have an empty estimator history")
        if expected[0] == "after_initial_reserve" and not histories[0]:
            _fail(f"case {case.identifier} post-admission checkpoint lacks estimator history")
        terminal_manifest = _terminal_manifest_operation(value)
        recovery_terminal = name in _RECOVERY_TERMINAL_PROCEDURES
        for checkpoint_name, prior, current in zip(
            expected[1:], histories[:-1], histories[1:], strict=True
        ):
            if current[: len(prior)] != prior:
                _fail(f"case {case.identifier} checkpoints rewrite estimator history")
            terminal_suffix = checkpoint_name == "after_terminal_cleanup" and (
                recovery_terminal or (terminal_manifest is not None and runtime == "python")
            )
            concurrent_refusal_growth = (
                name == "concurrent_reservation_recovery" and checkpoint_name == "after_cancel"
            )
            if (
                len(current) > len(prior)
                and checkpoint_name not in _ESTIMATE_GROWTH_CHECKPOINTS
                and not terminal_suffix
                and not concurrent_refusal_growth
            ):
                _fail(
                    f"case {case.identifier} checkpoint {checkpoint_name!r} invents an "
                    "estimator call"
                )
            if checkpoint_name == "after_initial_reserve" and not current:
                _fail(f"case {case.identifier} post-admission checkpoint lacks estimator history")
        if name == "concurrent_reservation_recovery":
            _concurrent_refusal_components(case, value, runtime, expected, histories)
        if name == "repair_no_recheck" and histories[1] != histories[2]:
            _fail(f"case {case.identifier} repair may not repeat the admission estimate")
        if expected[-1] == "after_terminal_cleanup":
            prior = histories[-2]
            terminal = histories[-1]
            component_count = _request_components(case)
            shared_terminal = terminal
            if runtime == "python" and terminal_manifest is not None:
                suffix = terminal[-component_count:] if component_count else ()
                shared_terminal = terminal[:-component_count] if component_count else terminal
                if suffix != _original_estimator_components(case, expected, histories):
                    _fail(
                        f"case {case.identifier} Python terminal manifest appends unrelated "
                        "estimator inputs"
                    )
            if recovery_terminal:
                recovery = shared_terminal[len(prior) :]
                expected_recovery = _recovery_estimator_components(case, expected, histories)
                if recovery != expected_recovery:
                    _fail(
                        f"case {case.identifier} terminal checkpoint does not preserve the "
                        "source recovery estimator components"
                    )
            elif shared_terminal != prior:
                _fail(
                    f"case {case.identifier} terminal checkpoint invents non-recovery estimator "
                    "work"
                )


def _has_active_spend_policy(case: observation.Case) -> bool:
    request = case.raw.get("request", case.raw.get("action", {}))
    candidates: list[Any] = [case.raw.get("spend_policy"), case.raw.get("policy")]
    if isinstance(request, dict):
        candidates.extend((request.get("spend_policy"), request.get("policy")))
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        spend = candidate.get("spend", candidate)
        if not isinstance(spend, dict):
            continue
        if any(
            spend.get(key) is not None
            for key in ("max_request_usd", "max_total_usd", "unknown_cost")
        ):
            return True
    return False


def _is_direct_spend(case: observation.Case, operation: Mapping[str, Any], runtime: str) -> bool:
    error = operation["error"]
    expected_type = _DIRECT_SPEND_TYPES.get(runtime)
    return (
        isinstance(error, dict)
        and error.get("runtime_type") == expected_type
        and expected_type is not None
        and _has_active_spend_policy(case)
    )


def _check_operations(
    value: Mapping[str, Any], case: observation.Case, runtime: str = "python"
) -> None:
    operations = value["operations"]
    indices = _names(operations, "index")
    if indices != tuple(range(len(operations))):
        _fail(f"case {case.identifier} operations must have contiguous ordinal indexes")
    if not operations:
        _fail(f"case {case.identifier} cannot qualify with no operations")
    procedure = _procedure(case)["name"]
    request = case.raw.get("request", case.raw.get("action", {}))
    calls = request.get("calls") if isinstance(request, dict) else None
    capture_modes = _procedure(case).get("capture_modes")
    if isinstance(calls, list):
        expected_count = len(calls)
    elif isinstance(capture_modes, list):
        expected_count = len(capture_modes)
    elif procedure == "concurrent_reservation_recovery" or (
        procedure == "governor_body_gate"
        and any(script.get("gate", {}).get("name") == "queue" for script in case.raw["scripts"])
    ):
        expected_count = 3
    elif procedure in {"stream_early_close", "governor_body_gate", "config_consumer"}:
        expected_count = len(case.raw["scripts"])
    else:
        expected_count = 1
    if len(operations) != expected_count:
        _fail(
            f"case {case.identifier} has {len(operations)} operations, "
            f"expected {expected_count} from its frozen procedure"
        )
    for operation in operations:
        outcome = operation["outcome"]
        terminal = operation["relations"]["terminal_event"]
        if _is_direct_spend(case, operation, runtime):
            expected_terminal = "none" if runtime == "python" else "failed"
            if outcome != "error" or terminal != expected_terminal:
                _fail(
                    f"case {case.identifier} direct spend does not preserve the {runtime} "
                    "terminal relation"
                )
            continue
        if outcome == "ok" and terminal != "completed":
            _fail(
                f"case {case.identifier} successful operation lacks RequestCompleted correlation"
            )
        if outcome == "error" and terminal != "failed":
            _fail(f"case {case.identifier} failed operation lacks RequestFailed correlation")
        if outcome == "cancelled" and terminal != "none":
            _fail(f"case {case.identifier} cancelled operation has a terminal event")
        attempts = operation["attempts"]
        if outcome == "ok" and not attempts[-1:]:
            _fail(f"case {case.identifier} successful operation lacks an attempt trail")


def _check_primary_seams(case: observation.Case, value: Mapping[str, Any]) -> None:
    scripts = {item["id"]: item for item in case.raw["scripts"]}
    captured: dict[str, list[tuple[str, Mapping[str, Any]]]] = {
        identifier: [] for identifier in scripts
    }
    for kind, captures in (("http", value["http"]), ("adapter_wire", value["adapter_wires"])):
        for capture in captures:
            script_id = capture["script_id"]
            if script_id not in scripts:
                _fail(f"case {case.identifier} capture names undeclared script {script_id!r}")
            script = scripts[script_id]
            expected_kind = "http" if script["transport"] == "http" else "adapter_wire"
            if kind != expected_kind:
                _fail(f"case {case.identifier} script {script_id!r} has cross-transport capture")
            if capture["instance"] != script["instance"]:
                _fail(
                    f"case {case.identifier} capture instance does not match script {script_id!r}"
                )
            if capture["operation_index"] >= len(value["operations"]):
                _fail(f"case {case.identifier} capture has an invalid operation index")
            if kind == "http":
                if capture["status"] != script["status"] or capture["method"] != "POST":
                    _fail(
                        f"case {case.identifier} HTTP capture does not preserve "
                        "script method/status"
                    )
                if not capture["path"] or not isinstance(capture["query"], str):
                    _fail(f"case {case.identifier} HTTP capture lacks actual path/query facts")
                if "messages" not in capture["request_json"]:
                    _fail(
                        f"case {case.identifier} HTTP capture lacks the declared request messages"
                    )
            else:
                _check_wire_literal(case, script, capture)
            captured[script_id].append((kind, capture))
    for script_id, script in scripts.items():
        expected_key = "http" if script["transport"] == "http" else "adapter_wire"
        matching = [capture for kind, capture in captured[script_id] if kind == expected_key]
        if len(matching) != 1:
            _fail(
                f"case {case.identifier} script {script_id!r} requires exactly one "
                f"actual {expected_key} primary seam"
            )
    for transport, captures in (("http", value["http"]), ("recording", value["adapter_wires"])):
        expected_ids = tuple(
            script["id"] for script in case.raw["scripts"] if script["transport"] == transport
        )
        actual_ids = tuple(capture["script_id"] for capture in captures)
        if actual_ids != expected_ids:
            _fail(f"case {case.identifier} primary captures do not preserve frozen script order")
    sends = {operation["index"]: 0 for operation in value["operations"]}
    for entries in captured.values():
        for _, capture in entries:
            sends[capture["operation_index"]] += 1
    for operation in value["operations"]:
        if operation["relations"]["send_count"] != sends[operation["index"]]:
            _fail(f"case {case.identifier} send count does not match actual primary captures")
    _check_unsent_operations(case, value)


def _check_unsent_operations(case: observation.Case, value: Mapping[str, Any]) -> None:
    procedure = _procedure(case)["name"]
    operations = value["operations"]
    zero_sends = [
        operation for operation in operations if operation["relations"]["send_count"] == 0
    ]
    if procedure == "concurrent_reservation_recovery" and (
        len(zero_sends) != 1 or zero_sends[0]["index"] != 1
    ):
        _fail(f"case {case.identifier} needs one middle unsent refusal")
    queued_cancel = procedure == "governor_body_gate" and any(
        script.get("gate", {}).get("name") == "queue" for script in case.raw["scripts"]
    )
    if queued_cancel:
        if len(operations) != 3 or len(zero_sends) != 1 or zero_sends[0]["index"] != 1:
            _fail(f"case {case.identifier} needs held, unsent-cancelled, recovery operations")
        if zero_sends[0]["outcome"] != "cancelled":
            _fail(f"case {case.identifier} queued middle operation must be cancelled")


def _check_wire_literal(
    case: observation.Case, script: Mapping[str, Any], capture: Mapping[str, Any]
) -> None:
    descriptor = case.raw.get("descriptor")
    expected_descriptor = descriptor["id"] if isinstance(descriptor, dict) else "recording"
    if capture["descriptor"] != expected_descriptor:
        _fail(f"case {case.identifier} recording descriptor does not match the public input")
    request = case.raw.get("request", case.raw.get("action", {}))
    if not isinstance(request, dict):
        _fail(f"case {case.identifier} has no public request shape")
    target = request.get("target")
    if isinstance(target, str) and capture["target"] != target:
        _fail(f"case {case.identifier} recording target does not match the public input")
    tools = request.get("tools")
    if isinstance(tools, list) and tuple(tool["name"] for tool in capture["tools"]) != tuple(
        tool["name"] for tool in tools
    ):
        _fail(f"case {case.identifier} recording tools do not match the public input")
    if "tool_choice" in request and capture["tool_choice"] != request["tool_choice"]:
        _fail(f"case {case.identifier} recording tool choice does not match the public input")


def _check_direct_spend(
    case: observation.Case,
    operation: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
    runtime: str,
) -> None:
    starts = [event for event in events if event["type"] == "AttemptStarted"]
    if len(starts) != 1 or starts[0]["attempt"] != 1:
        _fail(f"case {case.identifier} direct spend needs one actual one-based AttemptStarted")
    if operation["relations"]["send_count"] != 0 or operation["attempts"]:
        _fail(f"case {case.identifier} direct spend must retain zero sends and an empty trail")
    if any(event["type"] in {"AttemptCompleted", "RequestCompleted"} for event in events):
        _fail(f"case {case.identifier} direct spend must not complete an attempt or request")
    failed = [event for event in events if event["type"] == "RequestFailed"]
    if runtime == "python":
        if failed:
            _fail(f"case {case.identifier} Python direct spend must not emit RequestFailed")
        return
    if len(failed) != 1 or events.index(failed[0]) < events.index(starts[0]):
        _fail(f"case {case.identifier} native direct spend needs one post-start RequestFailed")
    if not _same_error(operation["error"], failed[0]["error"]):
        _fail(f"case {case.identifier} native direct spend failure does not preserve its error")


def _check_correlations(
    case: observation.Case, value: Mapping[str, Any], runtime: str = "python"
) -> None:
    operations = value["operations"]
    telemetry = value["telemetry"]
    for operation in operations:
        index = operation["index"]
        events = [event for event in telemetry if event["operation_index"] == index]
        if not events:
            _fail(f"case {case.identifier} operation {index} has no typed telemetry")
        if _is_direct_spend(case, operation, runtime):
            _check_direct_spend(case, operation, events, runtime)
            continue
        if operation["outcome"] == "ok":
            completed = [event for event in events if event["type"] == "RequestCompleted"]
            if len(completed) != 1:
                _fail(
                    f"case {case.identifier} successful operation lacks one RequestCompleted event"
                )
            result = operation["result"]
            if (
                completed[0]["target"] != result["target"]
                or completed[0]["usage"] != result["usage"]
            ):
                _fail(f"case {case.identifier} RequestCompleted does not preserve result facts")
            manifest = result["manifest"]
            if manifest is not None and manifest["request_id_relation"] != "same_operation":
                _fail(f"case {case.identifier} manifest is not causally tied to its operation")
            if (
                manifest is not None
                and manifest["usage"] is not None
                and not _same_manifest_usage(
                    manifest["usage"], result["usage"], completed[0]["usage"]
                )
            ):
                _fail(
                    f"case {case.identifier} manifest usage does not preserve the common "
                    "public usage facts"
                )
        elif operation["outcome"] == "error":
            failed = [event for event in events if event["type"] == "RequestFailed"]
            if len(failed) != 1:
                _fail(f"case {case.identifier} failed operation lacks one RequestFailed event")
            if not _same_error(operation["error"], failed[0]["error"]):
                _fail(
                    f"case {case.identifier} RequestFailed does not preserve terminal error facts"
                )
        starts = [event for event in events if event["type"] == "AttemptStarted"]
        if operation["outcome"] == "cancelled" and not operation["attempts"]:
            if len(starts) != 1 or starts[0]["attempt"] != 1:
                _fail(
                    f"case {case.identifier} direct cancellation needs one actual one-based "
                    "AttemptStarted"
                )
            if any(event["type"] == "AttemptCompleted" for event in events):
                _fail(f"case {case.identifier} direct cancellation must not complete an attempt")
            if any(event["type"] == "RequestCompleted" for event in events):
                _fail(f"case {case.identifier} direct cancellation must not complete a request")
            if any(event["type"] == "RequestFailed" for event in events):
                _fail(f"case {case.identifier} direct cancellation must not fail a request")
            continue
        eligible_attempts = [
            attempt
            for attempt in operation["attempts"]
            if attempt["outcome"] != "skipped_unhealthy"
        ]
        if len(starts) != len(eligible_attempts):
            _fail(f"case {case.identifier} AttemptStarted does not preserve the attempt trail")
        prior_target: str | None = None
        expected_attempt = 0
        for start, attempt in zip(starts, eligible_attempts, strict=True):
            if attempt["target"] != prior_target:
                expected_attempt = 1
            else:
                expected_attempt += 1
            if start["attempt"] != expected_attempt or start["target"] != attempt["target"]:
                _fail(
                    f"case {case.identifier} AttemptStarted does not preserve attempt "
                    "ordinal/target"
                )
            prior_target = attempt["target"]
        completed_attempts = [
            (position, event)
            for position, event in enumerate(events)
            if event["type"] == "AttemptCompleted"
        ]
        successful_ordinals = [
            ordinal
            for ordinal, attempt in enumerate(eligible_attempts)
            if attempt["outcome"] == "ok"
        ]
        if len(completed_attempts) != len(successful_ordinals):
            _fail(
                f"case {case.identifier} attempt telemetry does not preserve successful attempts"
            )
        terminal_positions = [
            position
            for position, event in enumerate(events)
            if event["type"] == "RequestCompleted"
        ]
        used_starts: set[int] = set()
        for (completion_position, completion), ordinal in zip(
            completed_attempts, successful_ordinals, strict=True
        ):
            if completion["outcome"] != "ok":
                _fail(f"case {case.identifier} AttemptCompleted has a non-success outcome")
            start_position = next(
                (position for position, event in enumerate(events) if event is starts[ordinal]),
                None,
            )
            if (
                start_position is None
                or ordinal in used_starts
                or start_position >= completion_position
                or any(
                    terminal_position <= completion_position
                    for terminal_position in terminal_positions
                )
            ):
                _fail(
                    f"case {case.identifier} AttemptCompleted is not causally bound to "
                    "its successful AttemptStarted"
                )
            used_starts.add(ordinal)
    _check_kind_witnesses(case, value)


def _same_error(terminal: Mapping[str, Any], attempt: Mapping[str, Any]) -> bool:
    return all(
        terminal[key] == attempt[key]
        for key in ("runtime_type", "provider", "phase", "retryable", "http_status")
    )


def _same_manifest_usage(
    manifest_usage: Mapping[str, Any],
    result_usage: Mapping[str, Any],
    completed_usage: Mapping[str, Any] | None,
) -> bool:
    if completed_usage is None:
        return False
    common = (
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "reasoning_tokens",
        "cost_usd",
        "search_units",
    )
    return all(manifest_usage[key] == result_usage[key] == completed_usage[key] for key in common)


def _operation_target(operation: Mapping[str, Any]) -> str | None:
    result = operation["result"]
    if result is not None:
        return result["target"]
    for attempt in reversed(operation["attempts"]):
        if attempt["target"] is not None:
            return attempt["target"]
    return None


def _operation_window(
    telemetry: Sequence[Mapping[str, Any]], operation_index: int
) -> tuple[int, int] | None:
    start = next(
        (
            position
            for position, event in enumerate(telemetry)
            if event["type"] == "RequestStarted" and event["operation_index"] == operation_index
        ),
        None,
    )
    if start is None:
        return None
    terminal = next(
        (
            position
            for position, event in enumerate(telemetry[start + 1 :], start=start + 1)
            if event["operation_index"] == operation_index
            and event["type"] in {"RequestCompleted", "RequestFailed"}
        ),
        None,
    )
    return None if terminal is None else (start, terminal)


def _has_cache_placement(case: observation.Case) -> bool:
    capabilities = case.raw.get("capabilities", [])
    return isinstance(capabilities, list) and any(
        "CACHE_PLACEMENT" in item.get("features", [])
        for item in capabilities
        if isinstance(item, dict)
    )


def _message_text(message: Mapping[str, Any]) -> str:
    """Project only the text that participates in a cache prefix relation."""
    content = message.get("content")
    if isinstance(content, str):
        return content
    parts = message.get("parts")
    if not isinstance(parts, list):
        return ""
    return "".join(
        part["text"]
        for part in parts
        if isinstance(part, dict)
        and part.get("type") == "text"
        and isinstance(part.get("text"), str)
    )


def _implicit_prefixes(case: observation.Case) -> tuple[tuple[str, str], ...]:
    """Compare declared prefix equality without reproducing process-local hashes."""
    request = case.raw.get("request")
    if not isinstance(request, dict):
        _fail(f"case {case.identifier} implicit cache has no public request")
    calls = request.get("calls")
    calls = calls if isinstance(calls, list) else [request]
    tools = request.get("tools", [])
    try:
        tools_relation = json.dumps(
            tools, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        )
    except (TypeError, ValueError) as error:
        _fail(f"case {case.identifier} has an uncomparable public tool prefix: {error}")
    prefixes: list[tuple[str, str]] = []
    for call in calls:
        if not isinstance(call, dict):
            _fail(f"case {case.identifier} implicit cache call is not an object")
        messages = call.get("messages", request.get("messages"))
        if not isinstance(messages, list):
            _fail(f"case {case.identifier} implicit cache call has no message sequence")
        system = "\n".join(
            _message_text(message)
            for message in messages
            if isinstance(message, dict) and message.get("role") == "system"
        )
        prefixes.append((system, tools_relation))
    return tuple(prefixes)


def _is_implicit_degradation(cache: Any, descriptor: Any) -> bool:
    return (
        isinstance(cache, dict)
        and cache.get("mode") == "explicit"
        and isinstance(descriptor, dict)
        and descriptor.get("cache_mechanism") == "implicit"
    )


def _check_implicit_degradation(
    case: observation.Case,
    value: Mapping[str, Any],
    telemetry: Sequence[Mapping[str, Any]],
    wires_by_operation: Mapping[int, Sequence[Mapping[str, Any]]],
) -> None:
    """Require the public implicit-cache downgrade and stability order per call."""
    prefixes = _implicit_prefixes(case)
    operations = [
        operation for operation in value["operations"] if operation["relations"]["send_count"] > 0
    ]
    if len(operations) != len(prefixes):
        _fail(f"case {case.identifier} implicit cache calls do not match dispatched operations")
    prior_prefix: tuple[str, str] | None = None
    for operation, prefix in zip(operations, prefixes, strict=True):
        operation_index = operation["index"]
        window = _operation_window(telemetry, operation_index)
        if window is None:
            _fail(f"case {case.identifier} implicit cache operation lacks a request window")
        start, terminal = window
        window_events = list(enumerate(telemetry[start + 1 : terminal], start=start + 1))
        drops = [
            (position, event)
            for position, event in window_events
            if event["type"] == "ParameterDropped"
            and event["operation_index"] == operation_index
            and event["parameter"] == "cache.mode"
        ]
        plans = [
            (position, event)
            for position, event in window_events
            if event["type"] == "CachePlanned" and event["operation_index"] == operation_index
        ]
        diagnostics = [
            (position, event)
            for position, event in window_events
            if event["type"] == "ProviderDiagnostic"
            and event["operation_index"] is None
            and event["code"] == "cache.prefix-unstable"
        ]
        if (
            len(drops) != 1
            or drops[0][1]["reason"] != _IMPLICIT_DEGRADATION_REASON
            or len(plans) != 1
            or plans[0][1]["mechanism"] != "implicit"
            or plans[0][1]["count"] != 0
            or drops[0][0] >= plans[0][0]
        ):
            _fail(
                f"case {case.identifier} implicit cache operation {operation_index} lacks "
                "the ordered Explicit-to-Implicit drop and zero-mark plan"
            )
        if any(wire["cache_marks"] for wire in wires_by_operation.get(operation_index, ())):
            _fail(f"case {case.identifier} implicit cache retains explicit wire marks")
        changed = prior_prefix is not None and prefix != prior_prefix
        if changed:
            if len(diagnostics) != 1 or diagnostics[0][0] >= drops[0][0]:
                _fail(
                    f"case {case.identifier} changed implicit prefix lacks its ordered "
                    "stability diagnostic"
                )
        elif diagnostics:
            _fail(f"case {case.identifier} first or stable implicit prefix must remain silent")
        prior_prefix = prefix


def _check_kind_witnesses(case: observation.Case, value: Mapping[str, Any]) -> None:
    telemetry = value["telemetry"]
    request = case.raw.get("request", case.raw.get("action", {}))
    request = request if isinstance(request, dict) else {}
    cache = request.get("cache")
    if case.kind == "config_policy":
        configuration = value["configuration"]
        if configuration is None:
            _fail(f"case {case.identifier} needs a typed configuration witness")
        expected_ids = tuple(provider["id"] for provider in case.raw["config"]["providers"])
        if tuple(configuration["provider_ids"]) != expected_ids:
            _fail(f"case {case.identifier} configuration witness does not preserve provider order")
        if not value["http"] and not value["adapter_wires"]:
            _fail(f"case {case.identifier} parser-only configuration cannot qualify")
    if case.kind == "cache":
        off = isinstance(cache, dict) and cache.get("mode") == "off"
        planned = [event for event in telemetry if event["type"] == "CachePlanned"]
        drops = [event for event in telemetry if event["type"] == "ParameterDropped"]
        if off and planned:
            _fail(f"case {case.identifier} Cache Off must not emit CachePlanned")
        if not off and not planned and not drops:
            _fail(f"case {case.identifier} needs an actual cache witness")
        if off and any(wire["cache_marks"] for wire in value["adapter_wires"]):
            _fail(f"case {case.identifier} Cache Off must not retain cache marks")
        if off:
            for operation in value["operations"]:
                if operation["relations"]["send_count"] == 0:
                    continue
                operation_index = operation["index"]
                window = _operation_window(telemetry, operation_index)
                if window is None:
                    _fail(
                        f"case {case.identifier} Cache Off operation {operation_index} "
                        "lacks an actual request window"
                    )
                start, terminal = window
                window_events = telemetry[start + 1 : terminal]
                if any(
                    event["type"] == "ParameterDropped"
                    and event["operation_index"] == operation_index
                    and event["parameter"] == "cache.mode"
                    for event in window_events
                ):
                    _fail(
                        f"case {case.identifier} Cache Off must not drop cache.mode "
                        f"for operation {operation_index}"
                    )
                if any(
                    event["type"] == "ProviderDiagnostic"
                    and event["operation_index"] is None
                    and event["code"] in _CACHE_OFF_DIAGNOSTIC_CODES
                    for event in window_events
                ):
                    _fail(
                        f"case {case.identifier} Cache Off must not emit a cache "
                        f"diagnostic for operation {operation_index}"
                    )
        descriptor = case.raw.get("descriptor")
        supports_placement = _has_cache_placement(case)
        if (
            isinstance(cache, dict)
            and cache.get("mode") == "explicit"
            and isinstance(descriptor, dict)
            and descriptor.get("cache_mechanism") == "explicit"
            and not supports_placement
            and not any(event["type"] == "ParameterDropped" for event in telemetry)
        ):
            _fail(f"case {case.identifier} refused explicit cache needs a drop witness")
        plans_by_operation: dict[int, list[Mapping[str, Any]]] = {}
        drops_by_operation: dict[int, list[Mapping[str, Any]]] = {}
        for event in planned:
            plans_by_operation.setdefault(event["operation_index"], []).append(event)
        for event in drops:
            drops_by_operation.setdefault(event["operation_index"], []).append(event)
        wires_by_operation: dict[int, list[Mapping[str, Any]]] = {}
        for wire in value["adapter_wires"]:
            wires_by_operation.setdefault(wire["operation_index"], []).append(wire)
        implicit_degradation = _is_implicit_degradation(cache, descriptor)
        if implicit_degradation:
            _check_implicit_degradation(case, value, telemetry, wires_by_operation)
        elif not off:
            for operation in value["operations"]:
                operation_index = operation["index"]
                if operation["relations"]["send_count"] == 0:
                    continue
                operation_plans = plans_by_operation.get(operation_index, [])
                operation_drops = drops_by_operation.get(operation_index, [])
                capability_refusal = (
                    isinstance(descriptor, dict)
                    and descriptor.get("cache_mechanism") == "explicit"
                    and not supports_placement
                )
                if capability_refusal:
                    if operation_plans or len(operation_drops) != 1:
                        _fail(
                            f"case {case.identifier} operation {operation_index} must expose "
                            "the explicit-cache capability refusal"
                        )
                    drop = operation_drops[0]
                    if (
                        drop["parameter"] != "cache.mode"
                        or drop["reason"]
                        != "the target's capabilities do not include cache placement"
                    ):
                        _fail(
                            f"case {case.identifier} operation {operation_index} does not "
                            "preserve the cache capability-refusal reason"
                        )
                    if any(
                        wire["cache_marks"] for wire in wires_by_operation.get(operation_index, [])
                    ):
                        _fail(f"case {case.identifier} refused explicit cache retains wire marks")
                    continue
                if len(operation_plans) != 1 or operation_drops:
                    _fail(
                        f"case {case.identifier} operation {operation_index} lacks one "
                        "actual active cache-plan witness"
                    )
                for wire in wires_by_operation.get(operation_index, []):
                    if len(wire["cache_marks"]) != operation_plans[0]["count"]:
                        _fail(
                            f"case {case.identifier} cache marks do not match the actual "
                            "plan count"
                        )
    if case.kind == "config_policy":
        config = case.raw["config"]
        action = case.raw["action"]
        if (
            config.get("cache", {}).get("mode") == "auto"
            and action.get("caller_cache", {}).get("mode") == "off"
        ):
            wires = value["adapter_wires"]
            if len(wires) != 2 or any(wire["cache_marks"] for wire in wires):
                _fail(f"case {case.identifier} needs empty caller-Off/configured-Auto marks")
            plans = [event for event in telemetry if event["type"] == "CachePlanned"]
            drops = [event for event in telemetry if event["type"] == "ParameterDropped"]
            supports_placement = _has_cache_placement(case)
            if supports_placement:
                if (
                    len([event for event in plans if event["operation_index"] == 0]) != 1
                    or any(event["operation_index"] == 0 for event in drops)
                    or any(event["operation_index"] == 1 for event in plans + drops)
                ):
                    _fail(f"case {case.identifier} lacks the active Auto/caller-Off effect")
            else:
                refused = [event for event in drops if event["operation_index"] == 0]
                if (
                    plans
                    or len(refused) != 1
                    or refused[0]["parameter"] != "cache.mode"
                    or refused[0]["reason"]
                    != "the target's capabilities do not include cache placement"
                    or any(event["operation_index"] == 1 for event in drops)
                ):
                    _fail(
                        f"case {case.identifier} lacks the configured-Auto capability-refusal "
                        "and caller-Off absence"
                    )
    if case.kind == "governor" and not value["resources"]:
        _fail(f"case {case.identifier} needs resource-boundary witnesses")
    if case.kind == "tool_stream":
        _check_tool_witnesses(case, value, request)
    _check_redaction(case, value)


def _check_tool_witnesses(
    case: observation.Case, value: Mapping[str, Any], request: Mapping[str, Any]
) -> None:
    primary = {
        capture["script_id"]: capture["operation_index"]
        for captures in (value["http"], value["adapter_wires"])
        for capture in captures
    }
    expected_by_operation: dict[int, list[tuple[Any, ...]]] = {}
    for script in case.raw["scripts"]:
        deltas = [
            event for event in script.get("events", []) if event["type"] == "tool_call_delta"
        ]
        if not deltas:
            continue
        operation_index = primary.get(script["id"])
        if operation_index is None:
            _fail(f"case {case.identifier} tool script lacks its primary operation capture")
        expected_by_operation.setdefault(operation_index, []).extend(
            (
                event["index"],
                event["call_id"],
                event["name"],
                event["arguments_fragment"],
            )
            for event in deltas
        )
    if expected_by_operation:
        actual_by_operation: dict[int, list[tuple[Any, ...]]] = {}
        for event in value["stream_events"]:
            if event["type"] == "tool_call_delta":
                actual_by_operation.setdefault(event["operation_index"], []).append(
                    (event["index"], event["id"], event["name"], event["arguments"])
                )
        for operation_index, expected in expected_by_operation.items():
            if actual_by_operation.get(operation_index, []) != expected:
                _fail(
                    f"case {case.identifier} tool deltas do not preserve the literal "
                    "ordered script subsequence"
                )
        for operation_index, expected in expected_by_operation.items():
            result = value["operations"][operation_index]["result"]
            warnings = [] if result is None else result["warnings"]
            expected_warnings = _source_tool_warnings(case, expected)
            if warnings != expected_warnings:
                _fail(
                    f"case {case.identifier} malformed tool warnings do not preserve "
                    "source index order"
                )
    feedback = _tool_feedback(request)
    if feedback:
        _check_first_tool_feedback(case, value, feedback[0])
        if isinstance(request.get("repair"), dict):
            _check_tool_repair(case, value, feedback[0], expected_by_operation)
    modes = _procedure(case).get("capture_modes")
    if modes == ["default", "explicit"]:
        first, second = value["operations"]
        first_payload = first["result"]["manifest"]["payload"]
        second_payload = second["result"]["manifest"]["payload"]
        if (
            first_payload is not None
            or second_payload is None
            or not second_payload["tool_arguments"]
        ):
            _fail(f"case {case.identifier} needs distinct default/explicit payload captures")


def _source_tool_warnings(case: observation.Case, deltas: Sequence[tuple[Any, ...]]) -> list[str]:
    """Derive the frozen malformed-call warning taxonomy in source build order.

    `AttemptBuffer` retains delta arrival order within an index but finalizes its call slots
    in ascending index order.  This deliberately recognizes only the frozen malformed
    literals; terminal normalized calls carry all other argument semantics, so the checker
    does not become a second JSON/tool-call parser.
    """
    fragments: dict[int, list[str]] = {}
    names: dict[int, str] = {}
    for index, _call_id, name, fragment in deltas:
        if not isinstance(index, int) or isinstance(index, bool):
            _fail(f"case {case.identifier} tool delta index is not an integer")
        if (name is not None and not isinstance(name, str)) or not isinstance(fragment, str):
            _fail(f"case {case.identifier} tool delta has non-string name or fragment")
        fragments.setdefault(index, []).append(fragment)
        if name:
            names[index] = name
    warnings: list[str] = []
    for index in sorted(fragments):
        joined = "".join(fragments[index]).strip()
        suffix = _FROZEN_MALFORMED_TOOL_ARGUMENTS.get(joined)
        if suffix is None:
            continue
        label = names.get(index) or index
        warnings.append(f"tool call {label} {suffix}")
    return warnings


def _tool_feedback(request: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Return typed tool feedback in caller order without inferring any tool calls."""
    feedback: list[tuple[str, str]] = []
    messages = request.get("messages", [])
    if not isinstance(messages, list):
        return feedback
    for message in messages:
        if not isinstance(message, dict):
            continue
        parts = message.get("parts", [])
        if not isinstance(parts, list):
            continue
        for part in parts:
            if (
                isinstance(part, dict)
                and part.get("type") == "tool_result"
                and isinstance(part.get("call_id"), str)
                and isinstance(part.get("content"), str)
            ):
                feedback.append((part["call_id"], part["content"]))
    return feedback


def _http_tool_feedback(capture: Mapping[str, Any]) -> list[tuple[str, str]]:
    request_json = capture.get("request_json")
    if not isinstance(request_json, dict):
        return []
    messages = request_json.get("messages")
    if not isinstance(messages, list):
        return []
    return [
        (message["tool_call_id"], message["content"])
        for message in messages
        if isinstance(message, dict)
        and message.get("role") == "tool"
        and isinstance(message.get("tool_call_id"), str)
        and isinstance(message.get("content"), str)
    ]


def _check_first_tool_feedback(
    case: observation.Case, value: Mapping[str, Any], first: tuple[str, str]
) -> None:
    """Require a public outbound HTTP witness for the first caller tool result."""
    observed = [feedback for capture in value["http"] for feedback in _http_tool_feedback(capture)]
    if first not in observed:
        _fail(f"case {case.identifier} missing first typed tool-feedback witness")


def _check_tool_repair(
    case: observation.Case,
    value: Mapping[str, Any],
    first: tuple[str, str],
    expected_by_operation: Mapping[int, Sequence[tuple[Any, ...]]],
) -> None:
    """Verify a repair that carries outbound feedback without inventing inbound evidence."""
    scripts = case.raw["scripts"]
    if len(scripts) < 2:
        _fail(f"case {case.identifier} repair lacks a corrected outbound script")
    repair_scripts = {script["id"] for script in scripts[1:]}
    repair_captures = [
        capture for capture in value["http"] if capture["script_id"] in repair_scripts
    ]
    if len(repair_captures) != len(repair_scripts):
        _fail(f"case {case.identifier} repair lacks each typed outbound feedback wire")
    if any(first not in _http_tool_feedback(capture) for capture in repair_captures):
        _fail(f"case {case.identifier} repair wire does not preserve first tool feedback")
    repaired = [
        operation
        for operation in value["operations"]
        if operation["result"] is not None
        and operation["result"]["repair_attempts"] > 0
        and operation["result"]["structured"] is not None
    ]
    if len(repaired) != 1:
        _fail(f"case {case.identifier} repair lacks one corrected structured result")
    repair_events = [
        event
        for event in value["telemetry"]
        if event["type"] == "RepairAttempted" and event["operation_index"] == repaired[0]["index"]
    ]
    if len(repair_events) != repaired[0]["result"]["repair_attempts"]:
        _fail(f"case {case.identifier} repair telemetry does not preserve its actual sequence")
    if not expected_by_operation:
        if any(event["type"] == "tool_call_delta" for event in value["stream_events"]):
            _fail(f"case {case.identifier} outbound-only repair invents inbound tool deltas")
        if repaired[0]["result"]["tool_calls"]:
            _fail(f"case {case.identifier} outbound-only repair invents inbound tool calls")


def _check_redaction(case: observation.Case, value: Mapping[str, Any]) -> None:
    client = case.raw.get("client")
    if not isinstance(client, dict):
        return
    for secret in client.get("registered_secrets", []):
        if secret in json.dumps(value, ensure_ascii=False, separators=(",", ":")):
            _fail(f"case {case.identifier} leaks a registered secret into capture evidence")


def _check_resources(case: observation.Case, value: Mapping[str, Any]) -> None:
    resources = value["resources"]
    primary = {
        capture["script_id"]: capture
        for captures in (value["http"], value["adapter_wires"])
        for capture in captures
    }
    for resource in resources:
        script_id = resource["script_id"]
        if script_id is None:
            continue
        if script_id not in primary:
            _fail(f"case {case.identifier} resource names a script without a primary capture")
        capture = primary[script_id]
        if (
            resource["instance"] != capture["instance"]
            or resource["operation_index"] != capture["operation_index"]
        ):
            _fail(f"case {case.identifier} resource is not bound to its script primary operation")
    positions: dict[tuple[str | None, str], int] = {}
    for index, resource in enumerate(resources):
        key = (resource["script_id"], resource["type"])
        positions.setdefault(key, index)
    for script_index, script in enumerate(case.raw["scripts"]):
        gate = script.get("gate")
        if gate is None:
            continue
        script_id = script["id"]
        entry = positions.get((script_id, "handler_entry"))
        ready = positions.get((script_id, "body_ready"))
        released = positions.get((script_id, "body_released"))
        closed = positions.get((script_id, "body_closed"))
        if entry is None or ready is None or released is None or closed is None:
            _fail(f"case {case.identifier} gate {gate['name']!r} lacks resource boundary records")
        if not (entry < ready < released < closed):
            _fail(f"case {case.identifier} gate {gate['name']!r} violates resource partial order")
        if script_index + 1 < len(case.raw["scripts"]):
            later_id = case.raw["scripts"][script_index + 1]["id"]
            later_entry = positions.get((later_id, "handler_entry"))
            if later_entry is not None and closed > later_entry:
                _fail(f"case {case.identifier} later dispatch precedes required resource cleanup")
    procedure = _procedure(case)["name"]
    queued_cancel = procedure == "governor_body_gate" and any(
        script.get("gate", {}).get("name") == "queue" for script in case.raw["scripts"]
    )
    if queued_cancel:
        scripts = case.raw["scripts"]
        if len(scripts) != 2:
            _fail(f"case {case.identifier} queued cancellation needs held and recovery scripts")
        held_id, recovery_id = scripts[0]["id"], scripts[1]["id"]
        held_released = positions.get((held_id, "body_released"))
        held_closed = positions.get((held_id, "body_closed"))
        recovery_entry = positions.get((recovery_id, "handler_entry"))
        if (
            held_released is None
            or held_closed is None
            or recovery_entry is None
            or held_released >= recovery_entry
            or held_closed >= recovery_entry
        ):
            _fail(f"case {case.identifier} recovery dispatch precedes held-gate cleanup")
        queued_resources = [resource for resource in resources if resource["operation_index"] == 1]
        if not any(
            resource["type"] == "cancel_requested" for resource in queued_resources
        ) or not any(resource["type"] == "pending_observed" for resource in queued_resources):
            _fail(f"case {case.identifier} unsent queued cancellation lacks public evidence")
        if any(
            resource["type"] in {"body_ready", "body_released", "body_closed", "stream_closed"}
            for resource in queued_resources
        ):
            _fail(f"case {case.identifier} unsent queued cancellation invents acquired resources")

    cancelled = [
        operation
        for operation in value["operations"]
        if operation["relations"]["cancel_requested"]
    ]
    for operation in cancelled:
        operation_index = operation["index"]
        cancels = [
            index
            for index, resource in enumerate(resources)
            if resource["type"] == "cancel_requested"
            and resource["operation_index"] == operation_index
        ]
        closed = [
            index
            for index, resource in enumerate(resources)
            if resource["type"] in {"body_closed", "stream_closed"}
            and resource["operation_index"] == operation_index
        ]
        if operation["relations"]["send_count"] == 0:
            if not cancels:
                _fail(
                    f"case {case.identifier} lacks cancellation evidence for its unsent operation"
                )
            if any(
                resource["operation_index"] == operation_index
                and resource["type"]
                in {"body_ready", "body_released", "body_closed", "stream_closed"}
                for resource in resources
            ):
                _fail(f"case {case.identifier} unsent cancellation invents acquired resources")
            continue
        if queued_cancel and operation_index == 1:
            continue
        if not cancels or not closed or min(cancels) > max(closed):
            _fail(f"case {case.identifier} lacks cancellation-before-cleanup resource ordering")
    if procedure == "concurrent_reservation_recovery" and len(cancelled) != 1:
        _fail(f"case {case.identifier} needs one requested cancellation relation")


def qualify(case: observation.Case, record: dict[str, Any], runtime: str) -> None:
    """Apply frozen input-procedure obligations to one schema-valid record."""
    if runtime not in {"python", "csharp"}:
        _fail(f"case {case.identifier} has unsupported runtime {runtime!r}")
    if record["id"] != case.identifier or record["kind"] != case.kind:
        _fail(f"case {case.identifier} observer identity does not match the frozen input")
    value = _mapping(record["value"], f"case {case.identifier}.value")
    _check_checkpoint_sequence(case, value, runtime)
    _check_operations(value, case, runtime)
    _check_primary_seams(case, value)
    _check_correlations(case, value, runtime)
    _check_resources(case, value)


def read_observations(
    path: Path,
    *,
    expected_cases: Sequence[observation.Case],
    expected_runtime: str,
    expected_corpus_sha256: str,
) -> observation.ObserverRun:
    """Validate a closed envelope then index and qualify each nested operation."""
    source = _mapping(observation.read_json_bytes(path), f"observation envelope {path}")
    _validate(_schema(OBSERVATION_SCHEMA), source, f"observation envelope {path}")
    by_id = {case.identifier: case for case in expected_cases}
    return observation.read_observations(
        path,
        profile=PROFILE,
        expected_cases=expected_cases,
        expected_runtime=expected_runtime,
        expected_corpus_sha256=expected_corpus_sha256,
        validate_observation=lambda record, _where: qualify(
            by_id[record["id"]], record, expected_runtime
        ),
    )


def _difference_error(python: Any, native: Any, path: str) -> str | None:
    if not isinstance(python, dict) or not isinstance(native, dict):
        return _difference(python, native, path)
    if set(python) != set(native):
        return f"{path} has distinct object keys"
    for key in python:
        left = python[key]
        right = native[key]
        if key == "runtime_type":
            if (left, right) not in _ERROR_PAIRS:
                return f"{path}.runtime_type is not an approved runtime-local error pair"
            continue
        difference = _difference(left, right, f"{path}.{key}")
        if difference is not None:
            return difference
    return None


def _difference_operation(
    python: Mapping[str, Any], native: Mapping[str, Any], path: str
) -> str | None:
    if set(python) != set(native):
        return f"{path} has distinct object keys"
    for key in python:
        left = python[key]
        right = native[key]
        child = f"{path}.{key}"
        if key == "error" and left is not None:
            difference = _difference_error(left, right, child)
        elif key == "attempts":
            if len(left) != len(right):
                return f"{child} has distinct list lengths"
            difference = None
            for index, (left_attempt, right_attempt) in enumerate(zip(left, right, strict=True)):
                if set(left_attempt) != set(right_attempt):
                    return f"{child}[{index}] has distinct object keys"
                for attempt_key in left_attempt:
                    attempt_child = f"{child}[{index}].{attempt_key}"
                    if attempt_key == "error" and left_attempt[attempt_key] is not None:
                        difference = _difference_error(
                            left_attempt[attempt_key], right_attempt[attempt_key], attempt_child
                        )
                    else:
                        difference = _difference(
                            left_attempt[attempt_key], right_attempt[attempt_key], attempt_child
                        )
                    if difference is not None:
                        return difference
        else:
            difference = _difference(left, right, child)
        if difference is not None:
            return difference
    return None


def _difference_telemetry(
    python: Mapping[str, Any], native: Mapping[str, Any], path: str
) -> str | None:
    if set(python) != set(native):
        return f"{path} has distinct object keys"
    for key in python:
        child = f"{path}.{key}"
        if key == "error":
            difference = _difference_error(python[key], native[key], child)
        else:
            difference = _difference(python[key], native[key], child)
        if difference is not None:
            return difference
    return None


def _difference(python: Any, native: Any, path: str = "value") -> str | None:
    if type(python) is not type(native):
        return (
            f"{path} has distinct JSON types ({type(python).__name__} != {type(native).__name__})"
        )
    if isinstance(python, dict):
        if set(python) != set(native):
            return f"{path} has distinct object keys"
        for key in python:
            left = python[key]
            right = native[key]
            child = f"{path}.{key}"
            if key == "resources" and path == "value":
                # Qualification has already checked the frozen causal edges by script.
                # Retain raw traces in reports, but do not equate unconstrained cleanup order.
                continue
            if key == "operations" and path == "value":
                if len(left) != len(right):
                    return f"{child} has distinct list lengths"
                for index, (left_operation, right_operation) in enumerate(
                    zip(left, right, strict=True)
                ):
                    difference = _difference_operation(
                        left_operation, right_operation, f"{child}[{index}]"
                    )
                    if difference is not None:
                        return difference
                continue
            if key == "telemetry" and path == "value":
                if len(left) != len(right):
                    return f"{child} has distinct list lengths"
                for index, (left_event, right_event) in enumerate(zip(left, right, strict=True)):
                    difference = _difference_telemetry(
                        left_event, right_event, f"{child}[{index}]"
                    )
                    if difference is not None:
                        return difference
                continue
            difference = _difference(left, right, child)
            if difference is not None:
                return difference
        return None
    if isinstance(python, list):
        if len(python) != len(native):
            return f"{path} has distinct list lengths"
        for index, (left, right) in enumerate(zip(python, native, strict=True)):
            difference = _difference(left, right, f"{path}[{index}]")
            if difference is not None:
                return difference
        return None
    return None if python == native else f"{path} differs ({python!r} != {native!r})"


def _difference_operations(
    python: Sequence[Mapping[str, Any]], native: Sequence[Mapping[str, Any]], path: str
) -> str | None:
    if len(python) != len(native):
        return f"{path} has distinct list lengths"
    for index, (left_operation, right_operation) in enumerate(zip(python, native, strict=True)):
        difference = _difference_operation(left_operation, right_operation, f"{path}[{index}]")
        if difference is not None:
            return difference
    return None


def _difference_telemetry_events(
    python: Sequence[Mapping[str, Any]], native: Sequence[Mapping[str, Any]], path: str
) -> str | None:
    if len(python) != len(native):
        return f"{path} has distinct list lengths"
    for index, (left_event, right_event) in enumerate(zip(python, native, strict=True)):
        difference = _difference_telemetry(left_event, right_event, f"{path}[{index}]")
        if difference is not None:
            return difference
    return None


def _concurrent_telemetry(case: observation.Case) -> bool:
    return _procedure(case)["name"] in _CONCURRENT_TELEMETRY_PROCEDURES


def _difference_concurrent_telemetry(
    python: Sequence[Mapping[str, Any]], native: Sequence[Mapping[str, Any]], path: str
) -> str | None:
    """Compare per-request event order without claiming scheduler interleaving parity."""
    python_started = [event for event in python if event["type"] == "RequestStarted"]
    native_started = [event for event in native if event["type"] == "RequestStarted"]
    difference = _difference_telemetry_events(python_started, native_started, f"{path}.starts")
    if difference is not None:
        return difference
    python_indexes = {
        event["operation_index"] for event in python if event["operation_index"] is not None
    }
    native_indexes = {
        event["operation_index"] for event in native if event["operation_index"] is not None
    }
    if python_indexes != native_indexes:
        return f"{path} has distinct request-scoped operation indexes"
    for operation_index in sorted(python_indexes):
        python_events = [event for event in python if event["operation_index"] == operation_index]
        native_events = [event for event in native if event["operation_index"] == operation_index]
        difference = _difference_telemetry_events(
            python_events, native_events, f"{path}.operation[{operation_index}]"
        )
        if difference is not None:
            return difference
    python_provider = [event for event in python if event["operation_index"] is None]
    native_provider = [event for event in native if event["operation_index"] is None]
    return _difference_telemetry_events(python_provider, native_provider, f"{path}.provider")


def _header_map(headers: Mapping[str, Any], path: str) -> tuple[dict[str, str], str | None]:
    normalized: dict[str, str] = {}
    for name, value in headers.items():
        if not isinstance(name, str) or not isinstance(value, str):
            return {}, f"{path} has a non-string header"
        normalized_name = name.lower()
        if normalized_name in normalized:
            return {}, f"{path} has duplicate case-insensitive header names"
        normalized[normalized_name] = value
    return normalized, None


def _is_stream_capture(value: Mapping[str, Any], capture: Mapping[str, Any]) -> bool:
    operation_index = capture["operation_index"]
    return (
        isinstance(operation_index, int)
        and 0 <= operation_index < len(value["operations"])
        and value["operations"][operation_index]["entry_point"] == "stream"
    )


def _configured_header_names(case: observation.Case, capture: Mapping[str, Any]) -> frozenset[str]:
    """Return literal extra-header names for the capture's configured instance.

    Provider settings merge a literal ``headers`` mapping into every request.  The frozen
    corpus does not infer configuration from a request capture: only a matching instance or
    provider entry that actually carries such a mapping marks a transport-looking name as
    configured.  Malformed synthetic case data is deliberately ignored here; the closed
    input grammar rejects it before a real qualification run.
    """
    instance_id = capture.get("instance")
    if not isinstance(instance_id, str):
        return frozenset()
    configured: set[str] = set()
    candidates: list[Any] = []
    instances = case.raw.get("instances")
    if isinstance(instances, list):
        candidates.extend(
            instance
            for instance in instances
            if isinstance(instance, dict) and instance.get("id") == instance_id
        )
    config = case.raw.get("config")
    if isinstance(config, dict):
        providers = config.get("providers")
        if isinstance(providers, list):
            candidates.extend(
                provider
                for provider in providers
                if isinstance(provider, dict) and provider.get("id") == instance_id
            )
    for candidate in candidates:
        headers = candidate.get("headers")
        if isinstance(headers, dict) and all(
            isinstance(name, str) and isinstance(header_value, str)
            for name, header_value in headers.items()
        ):
            configured.update(name.lower() for name in headers)
    return frozenset(configured)


def _difference_headers(
    case: observation.Case,
    capture: Mapping[str, Any],
    python: Mapping[str, Any],
    native: Mapping[str, Any],
    *,
    stream: bool,
    path: str,
) -> tuple[str | None, tuple[str, ...]]:
    left, difference = _header_map(python, path)
    if difference is not None:
        return difference, ()
    right, difference = _header_map(native, path)
    if difference is not None:
        return difference, ()
    if "content-type" not in left or "content-type" not in right:
        return f"{path} lacks a semantic content-type header", ()
    if stream and (
        left.get("accept") != "text/event-stream" or right.get("accept") != "text/event-stream"
    ):
        return f"{path} lacks an explicit SSE accept header", ()
    configured = _configured_header_names(case, capture)
    differing: list[str] = []
    for name in sorted(set(left) | set(right)):
        left_value = left.get(name)
        right_value = right.get(name)
        if name == "authorization":
            safe_values = {
                None,
                _REDACTED_HEADER_VALUE,
                _REDACTED_BEARER_HEADER_VALUE,
            }
            if left_value not in safe_values or right_value not in safe_values:
                return f"{path}.authorization exposes a credential", ()
            if left_value == right_value:
                continue
            differing.append(name)
            continue
        if left_value == right_value:
            continue
        if name in configured:
            return f"{path}.{name} differs ({left_value!r} != {right_value!r})", ()
        if name in _TRANSPORT_DEFAULT_HEADERS or (name == "accept" and not stream):
            differing.append(name)
            continue
        return f"{path}.{name} differs ({left_value!r} != {right_value!r})", ()
    return None, tuple(differing)


def _difference_http_captures(
    case: observation.Case,
    python: Sequence[Mapping[str, Any]],
    native: Sequence[Mapping[str, Any]],
    value: Mapping[str, Any],
    path: str,
) -> tuple[str | None, tuple[str, ...]]:
    if len(python) != len(native):
        return f"{path} has distinct list lengths", ()
    differing_headers: list[str] = []
    for index, (left, right) in enumerate(zip(python, native, strict=True)):
        if "headers" not in left or "headers" not in right:
            return f"{path}[{index}] lacks a semantic content-type header", ()
        if set(left) != set(right):
            return f"{path}[{index}] has distinct object keys", ()
        for key in left:
            child = f"{path}[{index}].{key}"
            if key == "headers":
                difference, names = _difference_headers(
                    case,
                    left,
                    left[key],
                    right[key],
                    stream=_is_stream_capture(value, left),
                    path=child,
                )
                if difference is not None:
                    return difference, ()
                differing_headers.extend(f"{index}:{name}" for name in names)
                continue
            difference = _difference(left[key], right[key], child)
            if difference is not None:
                return difference, ()
    return None, tuple(differing_headers)


def _difference_value_field(key: str, python: Any, native: Any, path: str) -> str | None:
    """Compare one root field without losing its typed comparison rule."""
    if key == "resources" and path == "value":
        # Qualification has already checked the frozen causal edges by script.
        # Retain raw traces in reports, but do not equate unconstrained cleanup order.
        return None
    if key == "operations" and path == "value":
        return _difference_operations(python, native, f"{path}.{key}")
    if key == "telemetry" and path == "value":
        return _difference_telemetry_events(python, native, f"{path}.{key}")
    return _difference(python, native, f"{path}.{key}")


def _difference_except(
    python: Mapping[str, Any], native: Mapping[str, Any], excluded: set[str], path: str
) -> str | None:
    if set(python) != set(native):
        return f"{path} has distinct object keys"
    for key in python:
        if key in excluded:
            continue
        difference = _difference_value_field(key, python[key], native[key], path)
        if difference is not None:
            return difference
    return None


def _difference_direct_spend_operation(
    operation: Mapping[str, Any], native_operation: Mapping[str, Any], path: str
) -> str | None:
    difference = _difference_except(operation, native_operation, {"relations", "error"}, path)
    if difference is not None:
        return difference
    if (
        operation["relations"].get("terminal_event") != "none"
        or native_operation["relations"].get("terminal_event") != "failed"
    ):
        return f"{path}.relations does not preserve the direct-spend terminal profile"
    if set(operation["relations"]) != set(native_operation["relations"]):
        return f"{path}.relations has distinct object keys"
    for key in operation["relations"]:
        if key == "terminal_event":
            continue
        difference = _difference(
            operation["relations"][key],
            native_operation["relations"].get(key),
            f"{path}.relations.{key}",
        )
        if difference is not None:
            return difference
    error_difference = _difference_error(
        operation["error"], native_operation["error"], f"{path}.error"
    )
    return error_difference


def _direct_spend_indexes(
    case: observation.Case, python: Mapping[str, Any], native: Mapping[str, Any]
) -> tuple[int, ...]:
    python_operations = python["operations"]
    native_operations = native["operations"]
    if len(python_operations) != len(native_operations):
        return ()
    indexes: list[int] = []
    for index, (operation, native_operation) in enumerate(
        zip(python_operations, native_operations, strict=True)
    ):
        python_direct = _is_direct_spend(case, operation, "python")
        native_direct = _is_direct_spend(case, native_operation, "csharp")
        if python_direct != native_direct:
            return ()
        if python_direct:
            indexes.append(index)
    return tuple(indexes)


def _difference_with_profiles(
    case: observation.Case,
    python: Mapping[str, Any],
    native: Mapping[str, Any],
    direct_indexes: Sequence[int],
    *,
    exclude_checkpoints: bool,
) -> str | None:
    """Compare root facts while composing only the approved local differences."""
    if set(python) != set(native):
        return "value has distinct object keys"
    direct = set(direct_indexes)
    for key in python:
        if key == "checkpoints" and exclude_checkpoints:
            continue
        if key == "operations":
            if len(python[key]) != len(native[key]):
                return "value.operations has distinct list lengths"
            for index, (operation, native_operation) in enumerate(
                zip(python[key], native[key], strict=True)
            ):
                path = f"value.operations[{index}]"
                difference = (
                    _difference_direct_spend_operation(operation, native_operation, path)
                    if index in direct
                    else _difference_operation(operation, native_operation, path)
                )
                if difference is not None:
                    return difference
            continue
        if key == "telemetry":
            python_events = [
                event
                for event in python[key]
                if not (event["type"] == "RequestFailed" and event["operation_index"] in direct)
            ]
            native_failures = [
                event
                for event in native[key]
                if event["type"] == "RequestFailed" and event["operation_index"] in direct
            ]
            native_events = [
                event
                for event in native[key]
                if not (event["type"] == "RequestFailed" and event["operation_index"] in direct)
            ]
            if len(native_failures) != len(direct):
                return "value.telemetry lacks a native direct-spend RequestFailed"
            difference = (
                _difference_concurrent_telemetry(python_events, native_events, "value.telemetry")
                if _concurrent_telemetry(case)
                else _difference_telemetry_events(python_events, native_events, "value.telemetry")
            )
            if difference is not None:
                return difference
            continue
        if key == "http":
            difference, _ = _difference_http_captures(
                case, python[key], native[key], python, "value.http"
            )
            if difference is not None:
                return difference
            continue
        difference = _difference_value_field(key, python[key], native[key], "value")
        if difference is not None:
            return difference
    return None


def _difference_manifest_suffix(
    case: observation.Case,
    python: Mapping[str, Any],
    native: Mapping[str, Any],
    direct_indexes: Sequence[int],
) -> tuple[str | None, dict[str, Any] | None]:
    operation = _terminal_manifest_operation(python)
    native_operation = _terminal_manifest_operation(native)
    if operation is None or native_operation is None:
        return "value has a manifest estimator suffix without a completed manifest result", None
    difference = _difference_with_profiles(
        case, python, native, direct_indexes, exclude_checkpoints=True
    )
    if difference is not None:
        return difference, None
    checkpoints, native_checkpoints = python["checkpoints"], native["checkpoints"]
    if len(checkpoints) != len(native_checkpoints) or len(checkpoints) < 2:
        return "value has an unqualified manifest estimator suffix", None
    for index, (checkpoint, native_checkpoint) in enumerate(
        zip(checkpoints, native_checkpoints, strict=True)
    ):
        if checkpoint["name"] != native_checkpoint["name"]:
            return f"value.checkpoints[{index}].name differs", None
        if set(checkpoint) != set(native_checkpoint):
            return f"value.checkpoints[{index}] has distinct object keys", None
        for key in checkpoint:
            if key == "estimator_inputs":
                continue
            difference = _difference(
                checkpoint[key], native_checkpoint[key], f"value.checkpoints[{index}].{key}"
            )
            if difference is not None:
                return difference, None
        if index < len(checkpoints) - 1:
            difference = _difference(
                checkpoint["estimator_inputs"],
                native_checkpoint["estimator_inputs"],
                f"value.checkpoints[{index}].estimator_inputs",
            )
            if difference is not None:
                return difference, None
    if checkpoints[-1]["name"] != "after_terminal_cleanup":
        return "value has a manifest estimator suffix outside terminal cleanup", None
    native_terminal = tuple(native_checkpoints[-1]["estimator_inputs"])
    python_terminal = tuple(checkpoints[-1]["estimator_inputs"])
    if python_terminal[: len(native_terminal)] != native_terminal:
        return "value has a non-append-only manifest estimator suffix", None
    histories = [tuple(checkpoint["estimator_inputs"]) for checkpoint in checkpoints]
    expected = tuple(checkpoint["name"] for checkpoint in checkpoints)
    original_components = _original_estimator_components(case, expected, histories)
    suffix = python_terminal[len(native_terminal) :]
    if suffix != original_components:
        return "value has an invalid terminal manifest estimator suffix", None
    return (
        None,
        {
            "id": case.identifier,
            "kind": "python_terminal_manifest_estimate",
            "python_components": len(suffix),
            "native_components": 0,
        },
    )


def _repair_feedback_slot(
    capture: Mapping[str, Any], *, expected_text: str
) -> tuple[str, list[Any]] | None:
    """Return the sole selected diagnostic from one actual correction wire.

    The shared repair wrapper is fixed in both SDKs.  This helper intentionally permits no
    broader prose equivalence: it recognizes one assistant echo, one final user feedback
    turn, and exactly the single bullet slot between their literal wrapper fragments.
    """
    request_json = capture.get("request_json")
    if not isinstance(request_json, dict):
        return None
    messages = request_json.get("messages")
    if not isinstance(messages, list) or len(messages) < 2:
        return None
    assistant, prompt = messages[-2:]
    if (
        not isinstance(assistant, dict)
        or assistant.get("role") != "assistant"
        or assistant.get("content") != expected_text
        or not isinstance(prompt, dict)
        or prompt.get("role") != "user"
        or not isinstance(prompt.get("content"), str)
    ):
        return None
    feedback = prompt["content"]
    if not feedback.startswith(_REPAIR_PREFIX) or not feedback.endswith(_REPAIR_SUFFIX):
        return None
    diagnostic = feedback[len(_REPAIR_PREFIX) : -len(_REPAIR_SUFFIX)]
    if not diagnostic or "\n" in diagnostic:
        return None
    return diagnostic, messages


def _no_json_candidate_repair_profile(
    case: observation.Case,
    python: Mapping[str, Any],
    native: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None, str | None]:
    """Prepare the one admitted native scanner-message difference for comparison.

    The selected diagnostic lives in the actual correction request; every other correction
    wire field remains in the ordinary comparison.  A source-triggering first response that
    fails this closed shape is an unqualified record rather than a generic prose waiver.
    """
    scripts = case.raw.get("scripts")
    request = case.raw.get("request")
    procedure_name = _procedure(case).get("name")
    admitted_procedure = procedure_name == "repair_no_recheck" or (
        case.kind == "tool_stream" and procedure_name == "tool_stream"
    )
    if (
        not admitted_procedure
        or not isinstance(scripts, list)
        or len(scripts) != 2
        or not isinstance(request, dict)
        or not isinstance(request.get("schema"), dict)
        or request.get("repair") != {"max_attempts": 1}
    ):
        return dict(python), dict(native), None, None
    first_body = scripts[0].get("body") if isinstance(scripts[0], dict) else None
    first_value = first_body.get("value") if isinstance(first_body, dict) else None
    choices = first_value.get("choices") if isinstance(first_value, dict) else None
    first_message = (
        choices[0].get("message")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict)
        else None
    )
    initial_text = first_message.get("content") if isinstance(first_message, dict) else None
    if initial_text not in _NO_JSON_CANDIDATE_TEXT:
        return dict(python), dict(native), None, None
    if not all(isinstance(script, dict) for script in scripts):
        return dict(python), dict(native), None, "repair scripts are malformed"
    invalid_id, corrected_id = scripts[0].get("id"), scripts[1].get("id")
    if not isinstance(invalid_id, str) or not isinstance(corrected_id, str):
        return dict(python), dict(native), None, "repair scripts lack identities"
    operation = python.get("operations")
    native_operation = native.get("operations")
    python_http, native_http = python.get("http"), native.get("http")
    if (
        not isinstance(operation, list)
        or not isinstance(native_operation, list)
        or len(operation) != 1
        or len(native_operation) != 1
        or not isinstance(python_http, list)
        or not isinstance(native_http, list)
        or len(python_http) != 2
        or len(native_http) != 2
    ):
        return (
            dict(python),
            dict(native),
            None,
            "no-JSON repair lacks one operation and two captures",
        )
    for operation_value, runtime in ((operation[0], "python"), (native_operation[0], "csharp")):
        result = operation_value.get("result") if isinstance(operation_value, dict) else None
        attempts = operation_value.get("attempts") if isinstance(operation_value, dict) else None
        if (
            not isinstance(result, dict)
            or not isinstance(result.get("target"), str)
            or not isinstance(attempts, list)
            or len(attempts) != 1
            or not isinstance(attempts[0], dict)
            or attempts[0].get("target") != result["target"]
        ):
            return (
                dict(python),
                dict(native),
                None,
                (f"{runtime} no-JSON repair does not preserve its resolved target"),
            )
    expected_scripts = (invalid_id, corrected_id)
    for captures, value, runtime in (
        (python_http, python, "python"),
        (native_http, native, "csharp"),
    ):
        if tuple(
            capture.get("script_id") for capture in captures if isinstance(capture, dict)
        ) != (expected_scripts) or any(
            not isinstance(capture, dict) or capture.get("operation_index") != 0
            for capture in captures
        ):
            return (
                dict(python),
                dict(native),
                None,
                (f"{runtime} no-JSON repair does not preserve ordered correction captures"),
            )
        events = [
            event
            for event in value.get("telemetry", [])
            if isinstance(event, dict)
            and event.get("type") == "RepairAttempted"
            and event.get("operation_index") == 0
        ]
        if (
            len(events) != 1
            or events[0].get("count") != 1
            or events[0].get("mechanism") != "prompt"
        ):
            return (
                dict(python),
                dict(native),
                None,
                (f"{runtime} no-JSON repair lacks its one prompt RepairAttempted"),
            )
        event_positions = [
            index for index, event in enumerate(value["telemetry"]) if event is events[0]
        ]
        terminal_positions = [
            index
            for index, event in enumerate(value["telemetry"])
            if isinstance(event, dict)
            and event.get("operation_index") == 0
            and event.get("type") in {"AttemptCompleted", "RequestCompleted"}
        ]
        if not event_positions or any(
            position < event_positions[0] for position in terminal_positions
        ):
            return (
                dict(python),
                dict(native),
                None,
                (f"{runtime} RepairAttempted does not precede correction completion"),
            )
    python_slot = _repair_feedback_slot(python_http[1], expected_text=initial_text)
    native_slot = _repair_feedback_slot(native_http[1], expected_text=initial_text)
    if python_slot is None or native_slot is None:
        return dict(python), dict(native), None, "no-JSON repair lacks its fixed feedback wrapper"
    python_diagnostic, python_messages = python_slot
    native_diagnostic, native_messages = native_slot
    if (
        python_diagnostic != _NO_JSON_CANDIDATE_DIAGNOSTICS["python"]
        or native_diagnostic != _NO_JSON_CANDIDATE_DIAGNOSTICS["csharp"]
    ):
        return (
            dict(python),
            dict(native),
            None,
            "no-JSON repair has an unknown selected diagnostic",
        )
    if len(python_messages) != len(native_messages):
        return dict(python), dict(native), None, "no-JSON repair has distinct message counts"
    for index, (left, right) in enumerate(zip(python_messages, native_messages, strict=True)):
        if index == len(python_messages) - 1:
            if set(left) != set(right) or {
                key: value for key, value in left.items() if key != "content"
            } != {key: value for key, value in right.items() if key != "content"}:
                return (
                    dict(python),
                    dict(native),
                    None,
                    "no-JSON repair changes its feedback wrapper",
                )
            continue
        if left != right:
            return (
                dict(python),
                dict(native),
                None,
                "no-JSON repair changes preserved wire messages",
            )
    prepared_python = copy.deepcopy(python)
    prepared_native = copy.deepcopy(native)
    prepared_native["http"][1]["request_json"]["messages"][-1]["content"] = python_http[1][
        "request_json"
    ]["messages"][-1]["content"]
    return (
        prepared_python,
        prepared_native,
        {
            "id": case.identifier,
            "kind": "no_json_candidate_repair_feedback",
            "operation_index": 0,
            "initial_script_id": invalid_id,
            "correction_script_id": corrected_id,
            "python_diagnostic": python_diagnostic,
            "csharp_diagnostic": native_diagnostic,
        },
        None,
    )


def compare_observations(
    cases: Sequence[observation.Case],
    python: Mapping[str, dict[str, Any]],
    native: Mapping[str, dict[str, Any]],
) -> Comparison:
    """Compare exact observed facts, except the finite approved runtime name pairs."""
    matched: list[str] = []
    mismatches: list[dict[str, str]] = []
    runtime_specific: list[dict[str, Any]] = []
    for case in cases:
        python_value, native_value, repair_specific, repair_error = (
            _no_json_candidate_repair_profile(
                case, python[case.identifier]["value"], native[case.identifier]["value"]
            )
        )
        if repair_error is not None:
            mismatches.append({"id": case.identifier, "difference": repair_error})
            continue
        original_difference = _difference(python_value, native_value)
        direct_indexes = _direct_spend_indexes(case, python_value, native_value)
        profile_difference = _difference_with_profiles(
            case,
            python_value,
            native_value,
            direct_indexes,
            exclude_checkpoints=False,
        )
        difference = profile_difference
        specifics: list[dict[str, Any]] = [
            {
                "id": case.identifier,
                "kind": "direct_spend",
                "operation_index": index,
                "python_terminal_event": "none",
                "native_terminal_event": "failed",
            }
            for index in direct_indexes
        ]
        if repair_specific is not None:
            specifics.append(repair_specific)
        manifest_candidate = (
            _terminal_manifest_operation(python_value) is not None
            or _terminal_manifest_operation(native_value) is not None
        )
        if difference is not None and manifest_candidate:
            suffix_difference, suffix_specific = _difference_manifest_suffix(
                case, python_value, native_value, direct_indexes
            )
            if suffix_difference is None:
                difference = None
                if suffix_specific is not None:
                    specifics.append(suffix_specific)
            elif not direct_indexes:
                # A non-manifest mismatch should retain its original diagnostic rather than
                # being replaced by an attempted manifest-profile explanation.
                difference = original_difference
        if difference is None:
            _, header_names = _difference_http_captures(
                case, python_value["http"], native_value["http"], python_value, "value.http"
            )
            if header_names:
                specifics.append(
                    {
                        "id": case.identifier,
                        "kind": "transport_default_headers",
                        "captures": list(header_names),
                    }
                )
            if _concurrent_telemetry(case):
                direct = set(direct_indexes)
                python_events = [
                    event
                    for event in python_value["telemetry"]
                    if not (
                        event["type"] == "RequestFailed" and event["operation_index"] in direct
                    )
                ]
                native_events = [
                    event
                    for event in native_value["telemetry"]
                    if not (
                        event["type"] == "RequestFailed" and event["operation_index"] in direct
                    )
                ]
                if _difference_telemetry_events(python_events, native_events, "value.telemetry"):
                    specifics.append(
                        {
                            "id": case.identifier,
                            "kind": "concurrent_telemetry_interleaving",
                            "procedure": _procedure(case)["name"],
                        }
                    )
            matched.append(case.identifier)
            runtime_specific.extend(specifics)
        else:
            mismatches.append({"id": case.identifier, "difference": difference})
    return Comparison(PROFILE, tuple(matched), tuple(mismatches), tuple(runtime_specific))


def _run(command: list[str], *, cwd: Path) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def _source_identity() -> tuple[str, bool]:
    try:
        return observation.source_identity()
    except observation.ObservationError as error:
        _fail(str(error))


def run_observers(
    inputs: Path, directory: Path, *, source_revision: str, source_dirty: bool
) -> tuple[Path, Path]:
    """Run the two independent public observers using the frozen build handshake."""
    return observation.run_observers(
        observation.RunnerConfig(
            PYTHON_OBSERVER,
            "AnyInfer.RequestPolicy",
            "AnyInfer.RequestPolicy/AnyInfer.RequestPolicy.csproj",
            "RequestPolicySourceDirty",
        ),
        inputs,
        directory,
        source_revision=source_revision,
        source_dirty=source_dirty,
        run=lambda command, cwd: _run(command, cwd=cwd),
    )


def _report(
    comparison: Comparison,
    *,
    input_path: Path,
    python_path: Path,
    native_path: Path,
    python_run: observation.ObserverRun,
    native_run: observation.ObserverRun,
) -> dict[str, Any]:
    return {
        "profile": PROFILE,
        "status": comparison.status,
        "corpus_sha256": observation.corpus_sha256(input_path),
        "observers": {
            "python": {
                key: getattr(python_run, key)
                for key in ("runtime", "source_revision", "source_dirty", "corpus_sha256")
            },
            "native": {
                key: getattr(native_run, key)
                for key in ("runtime", "source_revision", "source_dirty", "corpus_sha256")
            },
        },
        "python_observation": str(python_path),
        "native_observation": str(native_path),
        "shared": {"matched": list(comparison.matched), "mismatches": list(comparison.mismatches)},
        "runtime_specific": list(comparison.runtime_specific),
        "native_only": [],
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse default orchestration or a byte-preserving evidence-only comparison."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--compare", nargs=2, type=Path, metavar=("PYTHON", "NATIVE"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Write a provenance-bound comparison report without transforming evidence bytes."""
    options = parse_args(sys.argv[1:] if argv is None else argv)
    input_path = options.input.resolve()
    _, cases = read_cases(input_path)
    digest = observation.corpus_sha256(input_path)
    directory = observation.fresh_run_directory(options.output_root.resolve())
    stamped_identity: tuple[str, bool] | None = None
    if options.compare is None:
        stamped_identity = _source_identity()
        python_path, native_path = run_observers(
            input_path,
            directory,
            source_revision=stamped_identity[0],
            source_dirty=stamped_identity[1],
        )
    else:
        python_path, native_path = observation.copy_comparison_evidence(
            directory, *(path.resolve() for path in options.compare)
        )
    python_run = read_observations(
        python_path, expected_cases=cases, expected_runtime="python", expected_corpus_sha256=digest
    )
    native_run = read_observations(
        native_path, expected_cases=cases, expected_runtime="csharp", expected_corpus_sha256=digest
    )
    try:
        observation.validate_handshake(python_run, native_run, stamped_identity=stamped_identity)
    except observation.ObservationError as error:
        _fail(str(error))
    comparison = compare_observations(cases, python_run.observations, native_run.observations)
    report_path = directory / "report.json"
    report_path.write_text(
        json.dumps(
            _report(
                comparison,
                input_path=input_path,
                python_path=python_path,
                native_path=native_path,
                python_run=python_run,
                native_run=native_run,
            ),
            ensure_ascii=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"{comparison.status}: {report_path}")
    return 0 if comparison.status == "pass" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ObservationError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1) from None
