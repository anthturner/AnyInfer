"""Closed input grammar controls for the request-policy proof corpus."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

_ROOT = Path(__file__).parent / "fixtures" / "request-policy-v1"
_INPUTS = _ROOT / "inputs.json"
_SCHEMA = _ROOT / "schema.json"
_KINDS = {
    "admission",
    "context_route",
    "tool_stream",
    "cache",
    "governor",
    "config_policy",
}


def _strict_loads(data: bytes) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, child in pairs:
            if key in value:
                raise ValueError(f"duplicate JSON key: {key}")
            value[key] = child
        return value

    return json.loads(data, object_pairs_hook=reject_duplicates)


def _corpus() -> dict[str, Any]:
    return _strict_loads(_INPUTS.read_bytes())


def _validator() -> Draft202012Validator:
    schema = _strict_loads(_SCHEMA.read_bytes())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _errors(value: dict[str, Any]) -> list[object]:
    return list(_validator().iter_errors(value))


def _case_by_id(corpus: dict[str, Any], case_id: str) -> dict[str, Any]:
    return next(case for case in corpus["cases"] if case["id"] == case_id)


def _assert_input_only(corpus: dict[str, Any]) -> None:
    forbidden = {"expected", "verdict", "result_template", "output_template"}
    for case in corpus["cases"]:
        assert not (set(case) & forbidden)


def _assert_references(corpus: dict[str, Any]) -> None:
    for case in corpus["cases"]:
        descriptors = {case["descriptor"]["id"]} if "descriptor" in case else set()
        instances = {
            item["id"]: item
            for item in case.get("instances", case.get("config", {}).get("providers", []))
        }
        for instance in instances.values():
            if "descriptor" in instance:
                assert instance["descriptor"] in descriptors
                assert instance["adapter"] == "recording"
        script_ids: set[str] = set()
        for script in case["scripts"]:
            assert script["id"] not in script_ids
            script_ids.add(script["id"])
            assert script["instance"] in instances
            if script["transport"] == "recording":
                assert instances[script["instance"]]["adapter"] == "recording"
                assert "descriptor" in instances[script["instance"]]
            if "gate" in script:
                assert script["gate"]["owner"] == "observer"
                assert script["gate"]["release"] == "finally"
        procedure = case["procedure"]
        assert procedure["consume"] == "exact"
        if procedure["name"] == "config_consumer":
            assert case["kind"] == "config_policy"


def _assert_complete_success_usage(corpus: dict[str, Any]) -> None:
    for case in corpus["cases"]:
        for script in case["scripts"]:
            if script["transport"] == "recording":
                finals = [event for event in script["events"] if event["type"] == "final"]
                assert len(finals) == 1
                assert finals[0]["usage"] is not None
                continue
            if script["status"] < 200 or script["status"] >= 300:
                continue
            body = script["body"]
            if body["kind"] == "sse" and not body["complete"]:
                continue
            if body["kind"] == "json":
                response = body["value"]
            elif body["kind"] == "raw_utf8":
                response = json.loads("".join(body["chunks"]))
            else:
                frames = "".join(body["chunks"])
                assert '"usage"' in frames
                continue
            assert isinstance(response, dict)
            assert isinstance(response.get("usage"), dict)
            assert {"prompt_tokens", "completion_tokens"} <= set(response["usage"])


def test_request_policy_corpus_is_closed_and_input_only() -> None:
    corpus = _corpus()
    assert corpus["profile"] == "request-policy-v1"
    assert not _errors(corpus)

    cases = corpus["cases"]
    assert 12 <= len(cases) <= 32
    assert {case["kind"] for case in cases} == _KINDS
    assert all(sum(case["kind"] == kind for case in cases) >= 2 for kind in _KINDS)
    identifiers = [case["id"] for case in cases]
    assert len(identifiers) == len(set(identifiers))
    _assert_input_only(corpus)
    _assert_references(corpus)
    _assert_complete_success_usage(corpus)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: _case_by_id(value, "admission-unknown-zero-refuse")["instances"][
            0
        ].__setitem__("unknown", True),
        lambda value: _case_by_id(value, "governor-body-cleanup-before-later-send")["instances"][
            0
        ]["limits"].__setitem__("max_concurrent", True),
        lambda value: _case_by_id(value, "admission-early-stream-close-release")["scripts"][0][
            "body"
        ].pop("chunks"),
        lambda value: _case_by_id(value, "admission-tight-equality")["request"].__setitem__(
            "route",
            {
                "targets": ["alpha:model"],
                "retry": {"max_attempts": 1, "backoff_base_s": 0, "backoff_max_s": 0},
                "health_gate": False,
            },
        ),
        lambda value: _case_by_id(value, "admission-unknown-zero-refuse")["procedure"].__setitem__(
            "name", "unknown-action"
        ),
        lambda value: value.__setitem__("cases", []),
        lambda value: _case_by_id(value, "admission-early-stream-close-release")["scripts"][0][
            "body"
        ].__setitem__("chunks", ["not-sse"]),
        lambda value: _case_by_id(value, "tool-first-feedback-call-only")["request"]["messages"][
            1
        ]["parts"][0].pop("type"),
        lambda value: _case_by_id(value, "tool-first-feedback-call-only")["request"]["messages"][
            1
        ]["parts"][0].__setitem__("arguments", "not-an-object"),
        lambda value: _case_by_id(value, "tool-first-feedback-call-only")["request"]["tools"][
            0
        ].__setitem__("parameters", []),
        lambda value: _case_by_id(value, "tool-fragments-empty-malformed-nonobject-undeclared")[
            "scripts"
        ][0].__setitem__("status", 200),
        lambda value: _case_by_id(value, "admission-tight-equality")["scripts"][0].__setitem__(
            "events", []
        ),
    ],
)
def test_request_policy_schema_rejects_closed_grammar_mutations(
    mutate: Any,
) -> None:
    value = deepcopy(_corpus())
    mutate(value)
    assert _errors(value)


def test_request_policy_reference_checks_reject_unmatched_instance_and_descriptor() -> None:
    value = deepcopy(_corpus())
    _case_by_id(value, "admission-tight-equality")["scripts"][0]["instance"] = "missing"
    with pytest.raises(AssertionError):
        _assert_references(value)


def test_context_known_to_unknown_uses_distinct_literal_models_on_one_descriptor() -> None:
    """The shared descriptor must not collapse alpha pricing into beta's unknown model."""
    case = _case_by_id(_corpus(), "context-specialized-known-to-unknown-held")
    models = {instance["id"]: instance["model"] for instance in case["instances"]}
    assert models == {"alpha": "model", "beta": "unpriced-model"}
    route = case["request"]["route"]
    assert route["targets"] == ["alpha:model", "beta:unpriced-model"]
    assert route["context_window_targets"] == ["beta:unpriced-model"]
    assert [item["target"] for item in case["pricing"]] == ["alpha:model"]

    value = deepcopy(_corpus())
    cache = _case_by_id(value, "cache-explicit-marks")
    cache["instances"][0]["descriptor"] = "missing"
    with pytest.raises(AssertionError):
        _assert_references(value)


def test_request_policy_static_controls_reject_duplicate_identifiers_and_unclosed_input_keys() -> (
    None
):
    value = deepcopy(_corpus())
    value["cases"][1]["id"] = value["cases"][0]["id"]
    with pytest.raises(AssertionError):
        identifiers = [case["id"] for case in value["cases"]]
        assert len(identifiers) == len(set(identifiers))

    value = deepcopy(_corpus())
    value["cases"][0]["expected_result"] = "forbidden"
    assert _errors(value)


@pytest.mark.parametrize(
    "payload",
    [
        b'{"profile":"request-policy-v1","profile":"duplicate","cases":[]}',
        b'{"$schema":"https://json-schema.org/draft/2020-12/schema","$schema":"duplicate"}',
    ],
)
def test_request_policy_strict_parser_rejects_duplicate_json_keys(payload: bytes) -> None:
    with pytest.raises(ValueError, match="duplicate JSON key"):
        _strict_loads(payload)
