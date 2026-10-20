"""Independent structural controls for the retrieval-v1 input and observation grammars."""

from __future__ import annotations

import math
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from _csharp_observation import ObservationError, read_json_bytes  # noqa: E402
from _csharp_retrieval_inputs import validate_inputs  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "retrieval-v1"
INPUT_PATH = FIXTURE / "inputs.json"
INPUT_SCHEMA_PATH = FIXTURE / "schema.json"
OBSERVATION_SCHEMA_PATH = FIXTURE / "observations.schema.json"
CASE_IDS = (
    "embedding-scalar-unknown-intent",
    "embedding-known-empty-intents",
    "embedding-unsupported-intent",
    "embedding-supported-classification-intent",
    "embedding-unknown-limit",
    "embedding-known-limit-caller-override",
    "embedding-2048-success-default-cap",
    "embedding-2049-refusal-default-cap",
    "embedding-retry-success",
    "embedding-repeated-route-position",
    "embedding-unsplit-exhaustion",
    "embedding-unsafe-fallback",
    "embedding-optin-fallback",
    "embedding-split-mixed-failure",
    "embedding-split-all-failed",
    "embedding-wrong-count",
    "embedding-ragged-vectors",
    "embedding-actual-space-mismatch",
    "embedding-raw-default-secret",
    "embedding-raw-optin-secret",
    "embedding-priced-caller-cancel",
    "embedding-priced-provider-spend-manifest",
    "rerank-1000-success",
    "rerank-1001-refusal",
    "rerank-partial-returntext-topn",
    "rerank-empty-response",
    "rerank-invalid-index-geometry",
    "embedding-route-precedence",
    "embedding-normal-close",
    "rerank-unknown-spend-refusal",
    "embedding-requested-unsupported-operation",
    "embedding-provider-phases",
)


def _schema() -> dict[str, Any]:
    value = read_json_bytes(INPUT_SCHEMA_PATH)
    assert isinstance(value, dict)
    return value


def _inputs() -> dict[str, Any]:
    value = read_json_bytes(INPUT_PATH)
    assert isinstance(value, dict)
    return deepcopy(value)


def _case(source: dict[str, Any], kind: str = "embedding") -> dict[str, Any]:
    return next(item for item in source["cases"] if item["kind"] == kind)


def _selector(case: dict[str, Any]) -> dict[str, Any]:
    return case["scripts"][0]


def _assert_invalid(source: dict[str, Any]) -> None:
    with pytest.raises(ObservationError):
        validate_inputs(source, _schema())


def _assert_schema_invalid(source: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Draft202012Validator(_schema()).validate(source)


def test_full_literal_corpus_is_strict_utf8_lf_meta_schema_and_semantically_valid() -> None:
    raw = INPUT_PATH.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert raw.endswith(b"\n")
    assert b"\r" not in raw
    Draft202012Validator.check_schema(_schema())
    source = _inputs()
    Draft202012Validator(_schema()).validate(source)
    assert tuple(case["id"] for case in source["cases"]) == CASE_IDS
    validate_inputs(source, _schema())


def test_corpus_supplies_literal_routing_for_every_public_call() -> None:
    route_fields = ("default_route", "operation_route", "per_call_route", "per_call_target")
    for case in _inputs()["cases"]:
        assert any(case["client"][field] is not None for field in route_fields), case["id"]


@pytest.mark.parametrize(
    ("identifier", "operation", "limit_field", "items_field", "count"),
    [
        ("embedding-2048-success-default-cap", "embedding", "max_batch_inputs", "inputs", 2048),
        ("embedding-2049-refusal-default-cap", "embedding", "max_batch_inputs", "inputs", 2049),
        ("rerank-1000-success", "rerank", "max_documents", "documents", 1000),
        ("rerank-1001-refusal", "rerank", "max_documents", "documents", 1001),
    ],
)
def test_ceiling_cases_supply_unknown_limits_without_a_caller_override(
    identifier: str, operation: str, limit_field: str, items_field: str, count: int
) -> None:
    case = next(item for item in _inputs()["cases"] if item["id"] == identifier)
    assert case["descriptors"][0]["capabilities"][operation][limit_field] is None
    assert case["request"]["batch"]["max_items_override"] is None
    assert len(case["request"][items_field]) == count
    if identifier == "rerank-1001-refusal":
        assert case["request"]["batch"]["rerank_cross_batch"] is True


@pytest.mark.parametrize(
    ("identifier", "selector_id", "second_id"),
    [
        ("embedding-split-mixed-failure", "mixed-right", "mixed-right-fail-2"),
        ("embedding-split-all-failed", "allfail-left", "allfail-left-fail-2"),
        ("embedding-split-all-failed", "allfail-right", "allfail-right-fail-2"),
    ],
)
def test_split_failure_selectors_supply_two_literal_retryable_steps(
    identifier: str, selector_id: str, second_id: str
) -> None:
    case = next(item for item in _inputs()["cases"] if item["id"] == identifier)
    selector = next(item for item in case["scripts"] if item["id"] == selector_id)
    first, second = selector["steps"]
    assert [first["ordinal"], second["ordinal"]] == [1, 2]
    assert first["action"] == second["action"] == "provider_failure"
    assert first["failure"]["retryable"] is True
    assert second["failure"] == first["failure"]
    assert second["id"] == second_id and first["id"] != second_id


@pytest.mark.parametrize(
    "mutate",
    [
        lambda source: source.update(extra=True),
        lambda source: source["cases"][0].update(id=source["cases"][1]["id"]),
        lambda source: source["cases"][0]["descriptors"].append(
            deepcopy(source["cases"][0]["descriptors"][0])
        ),
        lambda source: source["cases"][0]["descriptors"][0].update(instance="missing-instance"),
        lambda source: source["cases"][0]["scripts"][0].update(instance="missing-instance"),
        lambda source: source["cases"][0]["scripts"][0].update(model="missing-model"),
    ],
)
def test_input_grammar_and_identity_controls_reject_duplicates_unknowns_and_bad_references(
    mutate: Any,
) -> None:
    source = _inputs()
    mutate(source)
    _assert_invalid(source)


def test_selector_identity_step_and_gate_controls_are_fail_closed() -> None:
    source = _inputs()
    case = next(case for case in source["cases"] if len(case["scripts"]) >= 2)
    validate_inputs(source, _schema())
    case["scripts"][1]["id"] = case["scripts"][0]["id"]
    _assert_invalid(source)

    source = _inputs()
    selector = _selector(_case(source))
    selector["steps"].append(deepcopy(selector["steps"][0]))
    selector["steps"][1]["ordinal"] = 2
    _assert_invalid(source)

    source = _inputs()
    selector = _selector(_case(source))
    selector["steps"][0]["ordinal"] = 2
    _assert_invalid(source)

    source = _inputs()
    barrier_case = next(
        case
        for case in source["cases"]
        if any(
            step["action"] == "barrier" for script in case["scripts"] for step in script["steps"]
        )
    )
    barrier = next(
        step
        for script in barrier_case["scripts"]
        for step in script["steps"]
        if step["action"] == "barrier"
    )
    barrier["gate"]["release"] = barrier["gate"]["readiness"]
    _assert_invalid(source)

    source = _inputs()
    routed = next(case for case in source["cases"] if case["client"]["default_route"] is not None)
    routed["client"]["default_route"]["targets"][0] = "missing:model"
    _assert_invalid(source)

    source = _inputs()
    selector = _selector(_case(source))
    selector["operation"] = "rerank"
    _assert_invalid(source)

    source = _inputs()
    selector = _selector(_case(source))
    selector["steps"][0]["action"] = "rerank_response"
    selector["steps"][0]["response"] = _rerank_wire_response()
    Draft202012Validator(_schema()).validate(source)
    _assert_invalid(source)

    source = _inputs()
    barrier_case = next(
        case
        for case in source["cases"]
        if any(
            step["action"] == "barrier" for script in case["scripts"] for step in script["steps"]
        )
    )
    barrier = next(
        step
        for script in barrier_case["scripts"]
        for step in script["steps"]
        if step["action"] == "barrier"
    )
    barrier["continuation"]["action"] = "rerank_response"
    barrier["continuation"]["response"] = _rerank_wire_response()
    Draft202012Validator(_schema()).validate(source)
    _assert_invalid(source)

    source = _inputs()
    declared = _case(source, "embedding")
    declared["descriptors"][0]["operations"] = ["rerank"]
    declared["descriptors"][0]["runtime_protocols"] = ["rerank"]
    _assert_invalid(source)

    source = _inputs()
    declared = _case(source, "embedding")
    declared["descriptors"][0]["operations"] = []
    declared["descriptors"][0]["runtime_protocols"] = []
    _assert_invalid(source)

    source = _inputs()
    cancel_case = next(
        case
        for case in source["cases"]
        if case["procedure"]["name"] == "caller_cancel_while_provider_held"
    )
    barrier_script = next(
        script
        for script in cancel_case["scripts"]
        if any(step["action"] == "barrier" for step in script["steps"])
    )
    extra_barrier = deepcopy(
        next(step for step in barrier_script["steps"] if step["action"] == "barrier")
    )
    extra_barrier["id"] = "second-barrier"
    extra_barrier["ordinal"] = 2
    extra_barrier["gate"] = {
        "readiness": "second-ready",
        "release": "second-release",
        "finally_cleanup": "second-cleanup",
    }
    barrier_script["steps"].append(extra_barrier)
    _assert_invalid(source)

    source = _inputs()
    ordinary = next(
        case
        for case in source["cases"]
        if case["procedure"]["name"]
        not in {"caller_cancel_while_provider_held", "requested_unsupported_operation"}
        and case["scripts"]
    )
    ordinary["scripts"] = []
    _assert_invalid(source)

    source = _inputs()
    unsupported = next(
        case
        for case in source["cases"]
        if case["procedure"]["name"] == "requested_unsupported_operation"
    )
    assert unsupported["scripts"] == []
    validate_inputs(source, _schema())


@pytest.mark.parametrize(
    "slot,value",
    [
        ("input_per_1m", None),
        ("output_per_1m", None),
        ("per_server_tool_use", {"tool": None}),
    ],
)
def test_required_pricing_money_is_not_nullable(slot: str, value: Any) -> None:
    source = _inputs()
    pricing = next(
        descriptor["capabilities"]["pricing"]
        for case in source["cases"]
        for descriptor in case["descriptors"]
        if descriptor["capabilities"]["pricing"] is not None
    )
    pricing[slot] = value
    _assert_schema_invalid(source)


def test_nullable_optional_money_and_empty_provider_detail_are_admitted() -> None:
    source = _inputs()
    pricing = next(
        descriptor["capabilities"]["pricing"]
        for case in source["cases"]
        for descriptor in case["descriptors"]
        if descriptor["capabilities"]["pricing"] is not None
    )
    pricing["cache_read_per_1m"] = None
    pricing["cache_write_per_1m"] = None
    pricing["per_search_unit"] = None
    failure = next(
        step["failure"]
        for case in source["cases"]
        for script in case["scripts"]
        for step in script["steps"]
        if step["action"] == "provider_failure"
    )
    failure["detail"] = ""
    Draft202012Validator(_schema()).validate(source)
    validate_inputs(source, _schema())


@pytest.mark.parametrize("value", [None, "true", 1])
def test_native_top_n_requires_a_real_boolean(value: Any) -> None:
    source = _inputs()
    rerank = next(
        descriptor["capabilities"]["rerank"]
        for case in source["cases"]
        for descriptor in case["descriptors"]
        if descriptor["capabilities"]["rerank"] is not None
    )
    rerank["native_top_n"] = value
    _assert_schema_invalid(source)


def test_semantics_preserve_deliberate_wrong_count_ragged_and_invalid_rerank_wire_stimuli() -> (
    None
):
    source = _inputs()
    validate_inputs(source, _schema())
    ids = {case["id"] for case in source["cases"]}
    assert {
        "embedding-wrong-count",
        "embedding-ragged-vectors",
        "rerank-invalid-index-geometry",
    }.issubset(ids)


def test_optional_max_response_bytes_and_repeated_route_positions_remain_literal_input_data() -> (
    None
):
    source = _inputs()
    request = _case(source)["request"]
    request.pop("max_response_bytes", None)
    validate_inputs(source, _schema())

    source = _inputs()
    request = _case(source)["request"]
    request["max_response_bytes"] = None
    validate_inputs(source, _schema())
    request["max_response_bytes"] = 2 * 1024 * 1024
    validate_inputs(source, _schema())

    source = _inputs()
    repeated_route = next(
        case for case in source["cases"] if case["id"] == "embedding-repeated-route-position"
    )
    assert len(repeated_route["client"]["default_route"]["targets"]) > 1
    validate_inputs(source, _schema())


def test_corrected_embed_many_validation_cases_are_positive_and_scalar_order_is_not() -> None:
    source = _inputs()
    for identifier in (
        "embedding-raw-default-secret",
        "embedding-raw-optin-secret",
        "embedding-provider-phases",
    ):
        case = next(item for item in source["cases"] if item["id"] == identifier)
        assert case["request"]["entry_point"] == "embed_many"
        assert case["procedure"]["name"] == "embedding_validation"
    validate_inputs(source, _schema())

    source = _inputs()
    case = next(item for item in source["cases"] if item["id"] == "embedding-provider-phases")
    case["procedure"]["name"] = "embedding_scalar_order"
    _assert_invalid(source)


@pytest.mark.parametrize("numeric", [math.nan, math.inf, -math.inf, 1.0e309, True])
def test_non_finite_or_boolean_numeric_slots_are_rejected_without_mutating_source(
    numeric: Any,
) -> None:
    source = _inputs()
    original = deepcopy(source)
    response = _selector(_case(source))["steps"][0]["response"]
    response["vectors"][0][0] = numeric
    _assert_invalid(source)
    assert original["cases"][0]["scripts"][0]["steps"][0]["response"]["vectors"][0][0] == 0.1


def test_slice_and_procedure_semantics_reject_cross_operation_and_noncontiguous_literals() -> None:
    source = _inputs()
    case = _case(source, "embedding")
    _selector(case)["slice"]["inputs"] = ["not caller input"]
    _assert_invalid(source)

    source = _inputs()
    rerank = _case(source, "rerank")
    _selector(rerank)["slice"]["documents"] = [
        {"index": 1, "text": rerank["request"]["documents"][1]["text"]},
        {"index": 0, "text": rerank["request"]["documents"][0]["text"]},
    ]
    _assert_invalid(source)

    source = _inputs()
    case = _case(source, "embedding")
    case["procedure"]["name"] = "rerank_integrity"
    _assert_invalid(source)

    source = _inputs()
    rerank = _case(source, "rerank")
    rerank["procedure"]["name"] = "capability_intent"
    _assert_invalid(source)

    source = _inputs()
    rerank = _case(source, "rerank")
    rerank["request"]["documents"][1]["id"] = rerank["request"]["documents"][0]["id"]
    _assert_invalid(source)


def test_complete_overlapping_embedding_slices_remain_admissible_literal_stimuli() -> None:
    source = _inputs()
    case = next(
        item
        for item in source["cases"]
        if item["kind"] == "embedding"
        and item["request"]["entry_point"] == "embed_many"
        and len(item["request"]["inputs"]) >= 3
    )
    selector = _selector(case)
    first = deepcopy(selector)
    second = deepcopy(selector)
    first["id"] = "overlap-first"
    first["slice"]["inputs"] = case["request"]["inputs"][:2]
    first["steps"][0]["id"] = "overlap-first-response"
    second["id"] = "overlap-second"
    second["slice"]["inputs"] = case["request"]["inputs"][1:3]
    second["steps"][0]["id"] = "overlap-second-response"
    case["scripts"] = [first, second]
    validate_inputs(source, _schema())


@pytest.mark.parametrize(
    "schema",
    [
        {"$ref": "https://invalid.example/schema.json"},
        {"$dynamicRef": "https://invalid.example/schema.json#node"},
        {"$recursiveRef": "https://invalid.example/schema.json#node"},
        {"type": "object", "properties": {"nested": {"$ref": "https://invalid.example/nested"}}},
    ],
)
def test_external_schema_references_fail_closed_without_network(
    monkeypatch: pytest.MonkeyPatch, schema: dict[str, Any]
) -> None:
    import urllib.request

    calls: list[object] = []
    monkeypatch.setattr(urllib.request, "urlopen", lambda *args, **kwargs: calls.append(args))
    with pytest.raises(ObservationError):
        validate_inputs(_inputs(), schema)
    assert calls == []


def test_local_schema_and_literal_ref_data_remain_local_data() -> None:
    validate_inputs(_inputs(), _schema())

    source = _inputs()
    _case(source)["request"]["provider_options"] = {"alpha": {"$ref": "literal-data"}}
    validate_inputs(source, _schema())

    literal_schema = deepcopy(_schema())
    literal_schema["$defs"]["literal-ref-data"] = {
        "type": "object",
        "properties": {
            "$ref": {"const": "property-name"},
            "const": {"const": {"$ref": "literal-const"}},
            "enum": {"enum": [{"$ref": "literal-enum"}]},
            "default": {"default": {"$ref": "literal-default"}},
            "examples": {"examples": [{"$ref": "literal-example"}]},
        },
    }
    validate_inputs(_inputs(), literal_schema)

    unresolved = deepcopy(_schema())
    unresolved["$defs"]["case"] = {"$ref": "#/$defs/missing"}
    with pytest.raises(ObservationError):
        validate_inputs(_inputs(), unresolved)


def _complete_usage(cost_usd: str | None) -> dict[str, Any]:
    return {
        "input_tokens": 7,
        "output_tokens": 0,
        "total_tokens": 7,
        "cache_read_tokens": None,
        "cache_write_tokens": None,
        "reasoning_tokens": None,
        "cost_usd": cost_usd,
        "search_units": None,
        "server_tool_uses": {},
    }


def _usage_response_source(cost_usd: str | None) -> dict[str, Any]:
    source = _inputs()
    case = next(
        value
        for value in source["cases"]
        if value["procedure"]["name"] == "spend_and_manifest" and value["kind"] == "embedding"
    )
    case["scripts"][0]["steps"][0]["response"]["usage"] = _complete_usage(cost_usd)
    return source


def _response_usage(source: dict[str, Any]) -> dict[str, Any]:
    case = next(
        value
        for value in source["cases"]
        if value["procedure"]["name"] == "spend_and_manifest" and value["kind"] == "embedding"
    )
    usage = case["scripts"][0]["steps"][0]["response"]["usage"]
    assert isinstance(usage, dict)
    return usage


@pytest.mark.parametrize("cost_usd", [None, "1.25"])
def test_complete_literal_usage_admits_null_and_decimal_cost(cost_usd: str | None) -> None:
    source = _usage_response_source(cost_usd)
    Draft202012Validator(_schema()).validate(source)
    validate_inputs(source, _schema())


def test_complete_literal_usage_requires_cost_and_rejects_legacy_estimated() -> None:
    missing = _usage_response_source(None)
    usage = _response_usage(missing)
    del usage["cost_usd"]
    _assert_schema_invalid(missing)
    _assert_invalid(missing)

    legacy = _usage_response_source(None)
    usage = _response_usage(legacy)
    usage["estimated"] = False
    _assert_schema_invalid(legacy)
    _assert_invalid(legacy)


def _usage() -> dict[str, Any]:
    return {
        "input_tokens": 1,
        "output_tokens": 0,
        "total_tokens": 1,
        "cache_read_tokens": None,
        "cache_write_tokens": None,
        "reasoning_tokens": None,
        "cost_usd": "0",
        "search_units": None,
        "server_tool_uses": {},
    }


def _exception(runtime_type: str = "ProviderError") -> dict[str, Any]:
    return {
        "runtime_type": runtime_type,
        "message": "provider refused",
        "provider": None,
        "phase": "embedding",
        "retryable": False,
        "http_status": None,
        "retry_after_s": None,
        "detail": None,
        "hint": None,
    }


def _rerank_wire_response() -> dict[str, Any]:
    return {"items": [{"index": 0, "score": 1.0}], "model": "model", "usage": None, "raw": None}


def _rerank_result() -> dict[str, Any]:
    return {
        "target": {"provider_id": "alpha", "model": "model", "via_alias": None},
        "items": [{"index": 0, "document_id": "doc", "score": 1.0, "text": None}],
        "usage": _usage(),
        "timing": {
            "started_at": 0.0,
            "first_token_ms": None,
            "total_ms": 1.0,
            "output_tokens_per_s": None,
            "phases": {},
        },
        "warnings": [],
        "raw": None,
    }


def _embedding_wire_response() -> dict[str, Any]:
    return {
        "vectors": [[1.0]],
        "model": "model",
        "dimensions": 1,
        "normalized": None,
        "usage": None,
        "phases": {},
        "raw": None,
    }


def _observation() -> dict[str, Any]:
    target = {"provider_id": "alpha", "model": "model", "via_alias": None}
    timing = {
        "started_at": 0.0,
        "first_token_ms": None,
        "total_ms": 1.0,
        "output_tokens_per_s": None,
        "phases": {},
    }
    result = {
        "target": target,
        "vectors": [[1.0]],
        "space": {
            "provider_id": "alpha",
            "model": "model",
            "model_revision": None,
            "dimensions": 1,
            "input_intent_aware": False,
            "normalized": None,
            "compatibility_id": None,
        },
        "usage": _usage(),
        "timing": timing,
        "warnings": [],
        "raw": None,
    }
    value = {
        "operation": {
            "kind": "embedding",
            "outcome": "ok",
            "result": result,
            "error": None,
            "attempts": [],
            "request_relation": "operation",
            "cancellation_relation": "none",
        },
        "factories": [],
        "wires": [],
        "telemetry": [],
        "ledger": None,
        "manifest": None,
        "resources": [],
        "batch_failures": None,
    }
    return {
        "profile": "retrieval-v1",
        "runtime": "python",
        "source_revision": "a" * 40,
        "source_dirty": True,
        "corpus_sha256": "b" * 64,
        "observations": [{"id": "case", "kind": "embedding", "status": "ok", "value": value}],
    }


def test_output_schema_baseline_and_result_wire_manifest_unions_are_strict() -> None:
    schema = read_json_bytes(OBSERVATION_SCHEMA_PATH)
    assert isinstance(schema, dict)
    validator = Draft202012Validator(schema)
    baseline = _observation()
    validator.validate(baseline)

    wrong_result = deepcopy(baseline)
    wrong_result["observations"][0]["value"]["operation"]["result"] = _rerank_result()
    with pytest.raises(ValidationError):
        validator.validate(wrong_result)

    valid_wire = deepcopy(baseline)
    wire = {
        "selector_id": "selector",
        "step_ordinal": 1,
        "instance": "alpha",
        "target": {"provider_id": "alpha", "model": "model", "via_alias": None},
        "kind": "embedding",
        "entered_order": 1,
        "terminal_order": 2,
        "request": {
            "model": "model",
            "inputs": ["a"],
            "input_type": None,
            "dimensions": None,
            "timeout_s": 1.0,
            "max_response_bytes": 1,
            "extra_options": {},
        },
        "outcome": "response",
        "response": _embedding_wire_response(),
        "failure": None,
    }
    valid_wire["observations"][0]["value"]["wires"] = [wire]
    validator.validate(valid_wire)

    wrong_wire = deepcopy(valid_wire)
    wrong_wire["observations"][0]["value"]["wires"][0]["response"] = None
    with pytest.raises(ValidationError):
        validator.validate(wrong_wire)

    wrong_failure = deepcopy(valid_wire)
    wrong_failure["observations"][0]["value"]["wires"][0]["failure"] = _exception()
    with pytest.raises(ValidationError):
        validator.validate(wrong_failure)

    cancelled_wire = deepcopy(valid_wire)
    cancelled = cancelled_wire["observations"][0]["value"]["wires"][0]
    cancelled["outcome"] = "cancelled"
    cancelled["response"] = None
    cancelled["failure"] = None
    validator.validate(cancelled_wire)
    cancelled["response"] = _embedding_wire_response()
    with pytest.raises(ValidationError):
        validator.validate(cancelled_wire)

    ordinary_batch_failures = deepcopy(baseline)
    ordinary_batch_failures["observations"][0]["value"]["batch_failures"] = []
    with pytest.raises(ValidationError):
        validator.validate(ordinary_batch_failures)

    result_and_exception = deepcopy(baseline)
    operation = result_and_exception["observations"][0]["value"]["operation"]
    operation["outcome"] = "error"
    operation["result"] = None
    operation["error"] = _exception()
    validator.validate(result_and_exception)

    unexpected_category = deepcopy(result_and_exception)
    unexpected_category["observations"][0]["value"]["operation"]["error"]["category"] = "provider"
    with pytest.raises(ValidationError):
        validator.validate(unexpected_category)

    spend_limit = deepcopy(result_and_exception)
    spend_error = spend_limit["observations"][0]["value"]["operation"]["error"]
    spend_error["runtime_type"] = "SpendLimitError"
    spend_error.update(
        limit_usd="1.25",
        spent_usd=None,
        estimated_usd="0.125",
    )
    validator.validate(spend_limit)

    spend_with_category = deepcopy(spend_limit)
    spend_with_category["observations"][0]["value"]["operation"]["error"]["category"] = (
        "spend_limit"
    )
    with pytest.raises(ValidationError):
        validator.validate(spend_with_category)

    missing_all_spend_money = deepcopy(spend_limit)
    missing_all_error = missing_all_spend_money["observations"][0]["value"]["operation"]["error"]
    for field in ("limit_usd", "spent_usd", "estimated_usd"):
        del missing_all_error[field]
    with pytest.raises(ValidationError):
        validator.validate(missing_all_spend_money)

    missing_one_spend_money = deepcopy(spend_limit)
    del missing_one_spend_money["observations"][0]["value"]["operation"]["error"]["estimated_usd"]
    with pytest.raises(ValidationError):
        validator.validate(missing_one_spend_money)

    result_and_exception["observations"][0]["value"]["operation"]["result"] = _observation()[
        "observations"
    ][0]["value"]["operation"]["result"]
    with pytest.raises(ValidationError):
        validator.validate(result_and_exception)

    typed_telemetry = deepcopy(baseline)
    typed_telemetry["observations"][0]["value"]["telemetry"] = [
        {
            "type": "RequestStarted",
            "order": 1,
            "request_relation": "operation",
            "targets": ["alpha:model"],
            "metadata": {},
            "operation": "embedding",
        }
    ]
    validator.validate(typed_telemetry)
    typed_telemetry["observations"][0]["value"]["telemetry"][0]["operation"] = "generation"
    with pytest.raises(ValidationError):
        validator.validate(typed_telemetry)

    manifest = deepcopy(baseline)
    manifest["observations"][0]["value"]["manifest"] = {
        "request_relation": "operation",
        "format": "1",
        "complete": True,
        "operation": "embedding",
        "route": {"requested": ["alpha:model"], "resolved": "alpha:model", "considered": []},
        "attempts": [],
        "usage": {key: value for key, value in _usage().items() if key != "server_tool_uses"}
        | {"estimated_fields": {}},
        "timing": {
            "first_token_ms": None,
            "total_ms": 1.0,
            "output_tokens_per_s": None,
            "phases": {},
        },
        "notes": [],
        "embedding_space": None,
        "payloads": None,
    }
    validator.validate(manifest)
    manifest["observations"][0]["value"]["manifest"]["timing"]["started_at"] = 0.0
    with pytest.raises(ValidationError):
        validator.validate(manifest)

    aggregate = deepcopy(baseline)
    aggregate_value = aggregate["observations"][0]["value"]
    aggregate_operation = aggregate_value["operation"]
    aggregate_operation["outcome"] = "error"
    aggregate_operation["result"] = None
    aggregate_operation["error"] = _exception("AllTargetsFailedError")
    aggregate_value["batch_failures"] = [
        {"batch_index": 0, "item_count": 1, "succeeded": False, "error": "provider refused"}
    ]
    validator.validate(aggregate)
    aggregate_value["batch_failures"] = None
    with pytest.raises(ValidationError):
        validator.validate(aggregate)
