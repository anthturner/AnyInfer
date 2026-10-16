"""Independent real-run coverage for causal expectation reconciliation."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

from . import reconcile as reconcile_module
from .comparison import compare_fixture
from .reconcile import ReconciledFixture, reconcile_fixture
from .reference import _validator_module
from .runner import run_fixture
from .transport import compare_transport_fixture, run_transport_fixture
from .values import MissingEvidenceError, ValueDomainError, schema_prompt

_CORE_ROOT = Path("specification/fixtures/core-generation")
_TRANSPORT_ROOT = Path("specification/fixtures/transport/openai-chat")


def _load_core(family: str, name: str) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads((_CORE_ROOT / family / f"{name}.json").read_text(encoding="utf-8")),
    )


def _load_transport(name: str) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads((_TRANSPORT_ROOT / f"{name}.json").read_text(encoding="utf-8")),
    )


def _fresh_pending_authoring_fixture(fixture: dict[str, Any]) -> dict[str, Any]:
    authoring = deepcopy(fixture)
    authoring["expected"] = {
        "status": "to_be_observed",
        "calls": [],
        "clock_advances_ms": [],
        "telemetry": {"repair_attempted": [], "parameter_dropped": []},
        "events": [],
        "outcome": {"none": True},
        "accounting": None,
    }
    return authoring


def _validate_staged(tmp_path: Path, fixture: dict[str, Any], *, name: str) -> None:
    kind = fixture.get("kind")
    if kind in {"adapter", "core_http"}:
        path = tmp_path / "transport" / "openai-chat" / f"{name}.json"
    else:
        family = fixture.get("family")
        assert isinstance(family, str)
        path = tmp_path / "core-generation" / family / f"{name}.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(fixture), encoding="utf-8")
    problems = _validator_module().validate(
        tmp_path, specification_root=Path("specification"), fixture_paths=[path]
    )
    assert problems == []


def _messages(expected: Mapping[str, Any], ordinal: int) -> list[dict[str, Any]]:
    calls = expected["calls"]
    assert isinstance(calls, list)
    call = calls[ordinal]
    assert isinstance(call, Mapping)
    messages = call["messages"]
    assert isinstance(messages, list)
    return cast(list[dict[str, Any]], messages)


@pytest.mark.asyncio
async def test_reconcile_rewrites_only_expected_and_markerizes_actual_repair_causally(
    tmp_path: Path,
) -> None:
    fixture = _load_core("repair", "invalid-then-valid")
    original = deepcopy(fixture)
    run = await run_fixture(fixture)

    reconciled = reconcile_fixture(fixture, run)

    assert isinstance(reconciled, ReconciledFixture)
    assert fixture == original
    assert reconciled.fixture is not fixture
    assert list(reconciled.fixture) == list(original)
    assert all(
        reconciled.fixture[key] == original[key] for key in original if key != "expected"
    )
    assert reconciled.audit["verdict"] == "pass"
    assert compare_fixture(reconciled.fixture, run)["verdict"] == "pass"
    _validate_staged(tmp_path, reconciled.fixture, name="repair")

    first = _messages(reconciled.fixture["expected"], 0)
    correction = _messages(reconciled.fixture["expected"], 1)
    assert first[0]["role"] == "system"
    assert first[0]["text"][-1] == {"$schema_prompt": True}
    assert correction[-1]["role"] == "user"
    assert correction[-1]["text"].count({"$repair_feedback": True}) == 1


@pytest.mark.asyncio
async def test_reconcile_preserves_existing_valid_marker_segments_and_literal_splitting() -> None:
    fixture = _load_core("repair", "invalid-then-valid")
    run = await run_fixture(fixture)
    staged = reconcile_fixture(fixture, run).fixture
    calls = staged["expected"]["calls"]
    assert isinstance(calls, list)
    first_messages = calls[0]["messages"]
    assert isinstance(first_messages, list)
    system_text = first_messages[0]["text"]
    assert isinstance(system_text, list)
    literal = system_text[0]
    assert isinstance(literal, str)
    system_text[0:1] = [literal[:3], literal[3:]]

    reconciled = reconcile_fixture(staged, run)

    assert reconciled.fixture["expected"] == staged["expected"]
    assert reconciled.audit["verdict"] == "pass"


@pytest.mark.asyncio
async def test_reconcile_appends_prompt_to_last_actual_system_message() -> None:
    fixture = _fresh_pending_authoring_fixture(_load_core("repair", "invalid-then-valid"))
    messages = fixture["request"]["messages"]
    assert isinstance(messages, list)
    messages[:0] = [
        {"role": "system", "text": "first system"},
        {"role": "system", "text": "last system"},
    ]
    run = await run_fixture(fixture)

    staged = reconcile_fixture(fixture, run).fixture
    first = _messages(staged["expected"], 0)

    assert first[0]["text"] == "first system"
    assert first[1]["text"][-1] == {"$schema_prompt": True}
    assert first[1]["text"][0] == "last system\n\n"


@pytest.mark.asyncio
async def test_reconcile_preserves_caller_literals_that_resemble_prompt_and_feedback() -> None:
    fixture = _load_core("repair", "invalid-then-valid")
    schema = fixture["request"]["schema"]
    assert isinstance(schema, Mapping)
    fixture["request"]["messages"][0]["text"] = (
        schema_prompt(schema)
        + " Your previous response did not match the required JSON schema. Errors:\n"
        + "- caller literal\nRespond again with ONLY a corrected JSON value that satisfies the schema. "
        + "No prose, no code fences. {\"$schema_prompt\":true}"
    )
    run = await run_fixture(fixture)

    staged = reconcile_fixture(fixture, run).fixture
    messages = _messages(staged["expected"], 0)

    caller = next(message for message in messages if message["role"] == "user")
    assert isinstance(caller["text"], str)
    assert "{\"$schema_prompt\":true}" in caller["text"]


@pytest.mark.asyncio
async def test_reconcile_preserves_structured_member_order_and_does_not_alias_run() -> None:
    fixture = _load_core("extraction", "duplicate-key-last-value-first-position")
    run = await run_fixture(fixture)

    reconciled = reconcile_fixture(fixture, run)
    expected = reconciled.fixture["expected"]
    assert isinstance(expected, Mapping)
    outcome = expected["outcome"]
    assert isinstance(outcome, Mapping)
    result = outcome["result"]
    assert isinstance(result, Mapping)
    structured = result["structured"]
    assert isinstance(structured, Mapping)
    assert list(structured) == ["z", "a"]
    assert json.loads(json.dumps(reconciled.fixture))["expected"]["outcome"]["result"]["structured"] == {
        "z": 3,
        "a": 2,
    }
    assert reconciled.fixture is not reconciled.audit
    again = reconcile_fixture(fixture, run)
    assert again.fixture is not reconciled.fixture
    assert again.audit is not reconciled.audit


@pytest.mark.asyncio
async def test_reconcile_preserves_native_primary_mirror_comparison_behavior() -> None:
    fixture = _load_core("streaming", "buffered-equals-streamed")
    run = await run_fixture(fixture)
    assert run.mirror is not None

    reconciled = reconcile_fixture(fixture, run)

    assert reconciled.audit["verdict"] == "pass"
    assert compare_fixture(reconciled.fixture, run)["verdict"] == "pass"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("family", "name"),
    (
        ("routing", "retryable-then-ok-same-target"),
        ("routing", "nonretryable-falls-over"),
        ("streaming", "failed-attempt-deltas-visible"),
    ),
)
async def test_reconcile_preserves_later_original_user_messages_after_retry_or_fallback(
    family: str, name: str
) -> None:
    fixture = _fresh_pending_authoring_fixture(_load_core(family, name))
    fixture["request"]["schema"] = {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"],
    }
    run = await run_fixture(fixture)

    staged = reconcile_fixture(fixture, run).fixture
    reconciled = reconcile_fixture(staged, run)
    calls = reconciled.fixture["expected"]["calls"]

    assert [call["role"] for call in calls] == ["original", "original"]
    assert all(isinstance(call["messages"], list) for call in calls)
    assert all(call["messages"][-1]["text"] == "fixture input" for call in calls)
    assert reconciled.audit["verdict"] == "pass"
    assert compare_fixture(reconciled.fixture, run)["verdict"] == "pass"


@pytest.mark.asyncio
async def test_reconcile_rejects_identity_kind_marker_and_capture_provenance_faults() -> None:
    fixture = _load_core("repair", "invalid-then-valid")
    run = await run_fixture(fixture)
    staged = reconcile_fixture(fixture, run).fixture

    with pytest.raises(MissingEvidenceError):
        reconcile_fixture({**fixture, "id": "repair/not-the-run"}, run)
    with pytest.raises(ValueDomainError):
        reconcile_fixture({**fixture, "kind": "adapter"}, run)
    with pytest.raises(MissingEvidenceError):
        reconcile_fixture(fixture, replace(run, operations=()))

    malformed = deepcopy(staged)
    calls = malformed["expected"]["calls"]
    assert isinstance(calls, list)
    messages = calls[0]["messages"]
    assert isinstance(messages, list)
    messages[0]["text"] = [{"$schema_prompt": 1}]
    with pytest.raises(ValueDomainError):
        reconcile_fixture(malformed, run)


@pytest.mark.asyncio
async def test_reconcile_transport_core_markers_are_scoped_to_http_content(tmp_path: Path) -> None:
    fixture = _load_transport("correction-byte-budget-reset")
    original = deepcopy(fixture)
    run = await run_transport_fixture(fixture)

    reconciled = reconcile_fixture(fixture, run)

    assert fixture == original
    assert reconciled.audit["verdict"] == "pass"
    assert compare_transport_fixture(reconciled.fixture, run)["verdict"] == "pass"
    _validate_staged(tmp_path, reconciled.fixture, name="transport-core")
    expected = reconciled.fixture["expected"]
    assert isinstance(expected, Mapping)
    core = expected["core"]
    assert isinstance(core, Mapping)
    assert _messages(core, 0)[0]["text"][-1] == {"$schema_prompt": True}
    rows = expected["http_requests"]
    assert isinstance(rows, list)
    body = rows[0]["body"]
    assert isinstance(body, Mapping)
    messages = body["messages"]
    assert isinstance(messages, list)
    assert messages[0]["content"][-1] == {"$schema_prompt": True}


@pytest.mark.asyncio
async def test_reconcile_transport_adapter_body_remains_literal(tmp_path: Path) -> None:
    fixture = _load_transport("single-frame")
    run = await run_transport_fixture(fixture)

    reconciled = reconcile_fixture(fixture, run)

    body = reconciled.fixture["expected"]["http_requests"][0]["body"]
    assert isinstance(body, Mapping)
    assert isinstance(body["messages"][0]["content"], str)
    assert compare_transport_fixture(reconciled.fixture, run)["verdict"] == "pass"
    _validate_staged(tmp_path, reconciled.fixture, name="transport-adapter")


@pytest.mark.asyncio
async def test_reconcile_extension_stages_nondeclaring_baseline_with_honest_audit() -> None:
    fixture = _load_core("schema-admission", "unsupported-anyof")
    run = await run_fixture(fixture)

    reconciled = reconcile_fixture(fixture, run, extensions=["schema.combinators"])

    assert reconciled.audit["verdict"] == "extension"
    evidence = reconciled.audit["evidence"]
    assert isinstance(evidence, Mapping)
    assert evidence["native_outcome"] is not None
    assert evidence["adapter_entries"]
    expected = reconciled.fixture["expected"]
    assert expected["status"] == "observed"
    assert expected["calls"] == []
    assert expected["clock_advances_ms"] == []
    assert expected["events"] == []
    assert expected["accounting"] is None
    assert expected["outcome"]["error"]["category"] == "unsupported_input"


@pytest.mark.asyncio
@pytest.mark.parametrize("extensions", [(), ("unknown.extension",)])
async def test_reconcile_does_not_license_an_unlisted_extension_baseline(
    extensions: tuple[str, ...],
) -> None:
    fixture = _load_core("schema-admission", "unsupported-anyof")
    run = await run_fixture(fixture)

    with pytest.raises(ValueDomainError, match="extension"):
        reconcile_fixture(fixture, run, extensions=extensions)


@pytest.mark.asyncio
async def test_reconcile_rejects_unmarked_extension_authoring() -> None:
    fixture = _fresh_pending_authoring_fixture(_load_core("schema-admission", "unsupported-anyof"))
    run = await run_fixture(fixture)
    fixture.pop("extension")

    reconciled = reconcile_fixture(fixture, run, extensions=["schema.combinators"])

    assert reconciled.audit["verdict"] == "pass"
    assert compare_fixture(reconciled.fixture, run)["verdict"] == "pass"


@pytest.mark.asyncio
async def test_reconcile_refuses_extension_baseline_without_capture() -> None:
    fixture = _load_core("schema-admission", "unsupported-anyof")
    run = await run_fixture(fixture)

    with pytest.raises(MissingEvidenceError):
        reconcile_fixture(
            fixture,
            replace(run, operations=()),
            extensions=["schema.combinators"],
        )


@pytest.mark.asyncio
async def test_reconcile_rejects_noncausal_and_mismatched_preserved_markers() -> None:
    fixture = _load_core("repair", "invalid-then-valid")
    run = await run_fixture(fixture)
    staged = reconcile_fixture(fixture, run).fixture

    noncausal = deepcopy(staged)
    calls = noncausal["expected"]["calls"]
    assert isinstance(calls, list)
    messages = calls[0]["messages"]
    assert isinstance(messages, list)
    messages[-1]["text"] = ["ordinary caller text", {"$repair_feedback": True}]
    with pytest.raises(ValueDomainError):
        reconcile_fixture(noncausal, run)

    mismatched = deepcopy(staged)
    calls = mismatched["expected"]["calls"]
    assert isinstance(calls, list)
    messages = calls[0]["messages"]
    assert isinstance(messages, list)
    prompt = messages[0]["text"]
    assert isinstance(prompt, list)
    prompt[0] = "wrong literal prefix"
    with pytest.raises(MissingEvidenceError):
        reconcile_fixture(mismatched, run)


@pytest.mark.asyncio
async def test_reconcile_rejects_causal_marker_kind_count_and_placement_faults() -> None:
    fixture = _load_core("repair", "invalid-then-valid")
    run = await run_fixture(fixture)
    staged = reconcile_fixture(fixture, run).fixture

    wrong_kind = deepcopy(staged)
    calls = wrong_kind["expected"]["calls"]
    assert isinstance(calls, list)
    messages = calls[0]["messages"]
    assert isinstance(messages, list)
    prompt = messages[0]["text"]
    assert isinstance(prompt, list)
    prompt[-1] = {"$repair_feedback": True}
    with pytest.raises(ValueDomainError):
        reconcile_fixture(wrong_kind, run)

    extra_marker = deepcopy(staged)
    calls = extra_marker["expected"]["calls"]
    assert isinstance(calls, list)
    messages = calls[0]["messages"]
    assert isinstance(messages, list)
    prompt = messages[0]["text"]
    assert isinstance(prompt, list)
    prompt.append({"$schema_prompt": True})
    with pytest.raises(ValueDomainError):
        reconcile_fixture(extra_marker, run)

    misplaced = deepcopy(staged)
    calls = misplaced["expected"]["calls"]
    assert isinstance(calls, list)
    messages = calls[0]["messages"]
    assert isinstance(messages, list)
    prompt = messages[0]["text"]
    assert isinstance(prompt, list)
    marker = prompt.pop()
    prompt.insert(0, marker)
    with pytest.raises(ValueDomainError):
        reconcile_fixture(misplaced, run)


@pytest.mark.asyncio
async def test_reconcile_rejects_missing_and_mismatched_transport_provenance() -> None:
    fixture = _load_transport("correction-byte-budget-reset")
    run = await run_transport_fixture(fixture)

    with pytest.raises(MissingEvidenceError):
        reconcile_fixture(fixture, replace(run, http_requests=run.http_requests[:1]))

    first = dict(run.http_requests[0])
    body = dict(cast(Mapping[str, Any], first["body"]))
    messages = list(cast(list[dict[str, Any]], body["messages"]))
    messages[0] = {**messages[0], "role": "assistant"}
    body["messages"] = messages
    first["body"] = body
    with pytest.raises(MissingEvidenceError):
        reconcile_fixture(fixture, replace(run, http_requests=(first, *run.http_requests[1:])))


@pytest.mark.asyncio
async def test_reconcile_rejects_transport_kind_and_child_identity_mismatches() -> None:
    adapter_fixture = _load_transport("single-frame")
    adapter_run = await run_transport_fixture(adapter_fixture)
    core_fixture = _load_transport("correction-byte-budget-reset")
    core_run = await run_transport_fixture(core_fixture)
    assert core_run.core is not None

    assert reconcile_fixture(adapter_fixture, adapter_run).audit["verdict"] == "pass"
    assert reconcile_fixture(core_fixture, core_run).audit["verdict"] == "pass"

    with pytest.raises(ValueDomainError, match="kind does not match"):
        reconcile_fixture({**adapter_fixture, "id": core_run.case_id}, core_run)
    with pytest.raises(ValueDomainError, match="kind does not match"):
        reconcile_fixture({**core_fixture, "id": adapter_run.case_id}, adapter_run)
    with pytest.raises(MissingEvidenceError):
        reconcile_fixture(
            core_fixture,
            replace(core_run, core=replace(core_run.core, case_id="core/not-the-outer-run")),
        )


@pytest.mark.asyncio
async def test_reconcile_does_not_invent_a_policy_for_actual_cancellation() -> None:
    fixture = _load_core("streaming", "cancel-mid-stream")
    run = await run_fixture(fixture)
    assert isinstance(run.error, asyncio.CancelledError)

    reconciled = reconcile_fixture(fixture, run)

    assert reconciled.audit["verdict"] == "pass"
    assert compare_fixture(reconciled.fixture, run)["verdict"] == "pass"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("family", "name"),
    [("normalization", "invalid-sampling-negative-seed")],
)
async def test_reconcile_projects_valid_zero_entry_construction_outcomes(
    family: str, name: str
) -> None:
    fixture = _load_core(family, name)
    run = await run_fixture(fixture)
    assert run.requests == ()

    reconciled = reconcile_fixture(fixture, run)

    assert reconciled.audit["verdict"] == "pass"
    assert compare_fixture(reconciled.fixture, run)["verdict"] == "pass"


@pytest.mark.asyncio
async def test_reconcile_uses_input_positions_when_caller_literals_match_templates() -> None:
    fixture = _fresh_pending_authoring_fixture(_load_core("repair", "invalid-then-valid"))
    schema = fixture["request"]["schema"]
    assert isinstance(schema, Mapping)
    prompt = schema_prompt(schema)
    messages = fixture["request"]["messages"]
    assert isinstance(messages, list)
    messages[:0] = [
        {"role": "system", "text": f"caller suffix {prompt}"},
        {"role": "system", "text": "causal system"},
    ]
    messages[-1]["text"] = (
        "Your previous response did not match the required JSON schema. Errors:\n"
        "- caller literal\nRespond again with ONLY a corrected JSON value that satisfies the schema. "
        "No prose, no code fences."
    )
    run = await run_fixture(fixture)

    reconciled = reconcile_fixture(fixture, run)
    first = _messages(reconciled.fixture["expected"], 0)
    correction = _messages(reconciled.fixture["expected"], 1)

    assert first[0]["text"] == f"caller suffix {prompt}"
    assert first[1]["text"][-1] == {"$schema_prompt": True}
    caller = next(
        message
        for message in correction
        if message["role"] == "user"
        and isinstance(message["text"], str)
        and message["text"].startswith("Your previous response")
    )
    assert caller["text"].startswith("Your previous response")
    assert correction[-1]["text"].count({"$repair_feedback": True}) == 1


@pytest.mark.asyncio
async def test_reconcile_propagates_cancelled_and_fatal_delegated_helpers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _load_core("repair", "invalid-then-valid")
    run = await run_fixture(fixture)

    def cancelled(_run: object) -> dict[str, Any]:
        raise asyncio.CancelledError()

    monkeypatch.setattr(reconcile_module, "project_run", cancelled)
    with pytest.raises(asyncio.CancelledError):
        reconcile_fixture(fixture, run)

    def fatal(_run: object) -> dict[str, Any]:
        raise KeyboardInterrupt()

    monkeypatch.setattr(reconcile_module, "project_run", fatal)
    with pytest.raises(KeyboardInterrupt):
        reconcile_fixture(fixture, run)
