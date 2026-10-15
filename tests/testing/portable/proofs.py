"""Native development proofs for the portable core driver recipes.

These assertions are deliberately private development predicates.  They execute the
Python core and retain its native capture records; they do not produce a qualified
conformance report or release claim.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from anyinfer.redaction import redact
from anyinfer.schema import _capture as capture_module
from anyinfer.schema._capture import _ACTIVE

from .adapter import HarnessError
from .projection import native_feedback_for_call, project_run, validate_capture
from .runner import run_fixture
from .values import MissingEvidenceError, ValueDomainError, ensure_value_domain

CORE_DRIVER_RECIPE_IDS = (
    "driver/concurrent-operations-independent",
    "driver/assessment-completeness",
    "driver/timeout-effective-default-explicit",
    "driver/timeout-reset-per-entry",
    "driver/timeout-cleanup-disposal",
)

_TIMEOUT_IDS = frozenset(CORE_DRIVER_RECIPE_IDS[2:])
_ROOT = Path(__file__).parents[3] / "specification" / "fixtures" / "core-generation"


def _fixture(family: str, name: str) -> dict[str, Any]:
    value = json.loads((_ROOT / family / f"{name}.json").read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise HarnessError("portable proof fixture must be an object")
    return value


def _detail(exc: BaseException) -> str:
    return redact(str(exc))[:4096]


def _evidence(recipe_ref: str, observations: Mapping[str, Any]) -> dict[str, Any]:
    facts = dict(observations)
    ensure_value_domain(facts)
    if not facts:
        raise MissingEvidenceError("proof produced no native observations")
    return {"recipe_ref": recipe_ref, "observations": facts}


async def _concurrent_operations() -> dict[str, Any]:
    """Run two independently-created native repair operations at once."""
    dotted = _fixture("validation", "dotted-key-nested-path-collision")
    valid = _fixture("repair", "invalid-then-valid")
    left, right = await asyncio.gather(run_fixture(dotted), run_fixture(valid))
    if _ACTIVE.get() is not None:
        raise AssertionError("native capture scope leaked after concurrent operations")
    left_capture = validate_capture(left)
    right_capture = validate_capture(right)
    if len(left.operations) != 1 or len(right.operations) != 1:
        raise AssertionError("concurrent operations did not retain one capture each")
    left_operation, right_operation = left.operations[0], right.operations[0]
    if left_operation is right_operation or left_operation.operation_id == right_operation.operation_id:
        raise AssertionError("concurrent operations reused an operation identity")
    if not left_operation.assessments or not right_operation.assessments:
        raise AssertionError("concurrent operations lack native assessments")
    left_ids = {assessment.assessment_id for assessment in left_operation.assessments}
    right_ids = {assessment.assessment_id for assessment in right_operation.assessments}
    if left_ids & right_ids:
        raise AssertionError("concurrent operations shared assessment identities")
    if any(assessment.operation_id != left_operation.operation_id for assessment in left_operation.assessments):
        raise AssertionError("left assessment crossed operation boundary")
    if any(assessment.operation_id != right_operation.operation_id for assessment in right_operation.assessments):
        raise AssertionError("right assessment crossed operation boundary")
    left_projection, right_projection = project_run(left), project_run(right)
    if left_projection["outcome"] == right_projection["outcome"]:
        raise AssertionError("distinguishable concurrent scripts yielded indistinguishable outcomes")
    return {
        "left": {"operation_id": left_operation.operation_id, "capture": left_capture, "outcome": left_projection["outcome"]},
        "right": {"operation_id": right_operation.operation_id, "capture": right_capture, "outcome": right_projection["outcome"]},
        "active_capture_after_gather": False,
    }


async def _assessment_completeness() -> dict[str, Any]:
    """Observe selection, feedback, terminal failure, and typed paths once each."""
    extraction, invalid_schema, exhaustion, dotted, repaired = await asyncio.gather(
        run_fixture(_fixture("validation", "malformed-schema-extraction-precedes-assessment")),
        run_fixture(_fixture("validation", "malformed-required-17-invalid-schema")),
        run_fixture(_fixture("repair", "exhaustion-two-invalid")),
        run_fixture(_fixture("validation", "dotted-key-nested-path-collision")),
        run_fixture(_fixture("repair", "invalid-then-valid")),
    )
    runs = (extraction, invalid_schema, exhaustion, dotted, repaired)
    captures = [validate_capture(run) for run in runs]
    if any(capture["assessments"] < 1 for capture in captures):
        raise AssertionError("assessment recipe lacks an actual native assessment")
    extraction_observation = _extraction_observation(extraction.operations[0].assessments)
    invalid_schema_observation = _invalid_schema_observation(
        invalid_schema.operations[0].assessments
    )
    exhausted = project_run(exhaustion)
    if exhausted["outcome"].get("error", {}).get("category") != "schema_violation":
        raise AssertionError("terminal exhaustion did not retain native schema failure")
    repaired_capture = repaired.operations[0]
    corrections = [entry for entry in repaired_capture.entries if entry.role == "correction"]
    if len(corrections) != 1 or corrections[0].repair_assessment_ref is None:
        raise AssertionError("repair entry lacks its selected assessment linkage")
    feedback = native_feedback_for_call(repaired, corrections[0].entry_ordinal)
    if not feedback:
        raise AssertionError("repair correction lacks selected native feedback")
    dotted_paths = [
        issue.instance_path
        for assessment in dotted.operations[0].assessments
        for issue in assessment.issues or ()
        if issue.instance_path is not None
    ]
    if ("a.b",) not in dotted_paths or ("a", "b") not in dotted_paths:
        raise AssertionError("dotted and nested native issue paths were not distinguished")
    _assert_assessment_rejection_controls(
        extraction.operations[0].assessments, invalid_schema.operations[0].assessments
    )
    unavailable_controls = await _unavailable_assessment_controls(repaired)
    return {
        "captures": captures,
        "extraction": extraction_observation,
        "invalid_schema": invalid_schema_observation,
        "terminal_outcome": exhausted["outcome"],
        "correction": {"assessment_ref": corrections[0].repair_assessment_ref, "native_feedback": list(feedback), "entry_ordinal": corrections[0].entry_ordinal},
        "typed_paths": [list(path) for path in dotted_paths],
        "unavailable_controls": unavailable_controls,
    }


def _one_assessment(assessments: list[Any], kind: str) -> Any:
    selected = [assessment for assessment in assessments if assessment.kind == kind]
    if not selected:
        raise AssertionError(f"native assessment kind {kind!r} was not retained")
    if len(selected) != 1:
        raise AssertionError(f"native assessment kind {kind!r} was retained more than once")
    return selected[0]


def _extraction_observation(assessments: list[Any]) -> dict[str, Any]:
    assessment = _one_assessment(assessments, "extraction")
    if assessment.issues is None or len(assessment.issues) != 1:
        raise MissingEvidenceError("extraction assessment lacks its portable issue")
    issue = assessment.issues[0]
    if issue.rule != "no_json_candidate" or issue.instance_path is not None or issue.schema_path is not None:
        raise AssertionError("extraction assessment has the wrong portable rule or paths")
    if len(assessment.native_messages) != 1 or not assessment.native_messages[0]:
        raise MissingEvidenceError("extraction assessment lacks its native message")
    if len(assessment.selected_native) != 1:
        raise MissingEvidenceError("extraction assessment lacks its selected native occurrence")
    occurrence = assessment.selected_native[0]
    if set(occurrence) != {"rule", "message"} or occurrence["rule"] != issue.rule:
        raise MissingEvidenceError("extraction selected occurrence has invalid metadata")
    if occurrence["message"] != assessment.native_messages[0]:
        raise AssertionError("extraction selected occurrence differs from native feedback")
    return {
        "assessment_id": assessment.assessment_id,
        "source_entry_ordinal": assessment.source_entry_ordinal,
        "rule": issue.rule,
        "instance_path": None,
        "schema_path": None,
        "selected_occurrences": [{"rule": occurrence["rule"], "message": occurrence["message"]}],
    }


def _invalid_schema_observation(assessments: list[Any]) -> dict[str, Any]:
    assessment = _one_assessment(assessments, "invalid_schema")
    required_path = ("required",)
    if assessment.schema_error_input_path != required_path:
        raise MissingEvidenceError("invalid-schema assessment lacks the exact defective input path")
    if assessment.issues is None or len(assessment.issues) != 1:
        raise MissingEvidenceError("invalid-schema assessment lacks its portable issue")
    issue = assessment.issues[0]
    if issue.rule != "invalid_schema" or issue.instance_path is not None or issue.schema_path != required_path:
        raise AssertionError("invalid-schema assessment has the wrong typed issue paths")
    if len(assessment.native_messages) != 1 or not assessment.native_messages[0]:
        raise MissingEvidenceError("invalid-schema assessment lacks native feedback")
    if len(assessment.selected_native) != 1:
        raise MissingEvidenceError("invalid-schema assessment lacks its selected native occurrence")
    occurrence = assessment.selected_native[0]
    if set(occurrence) != {"input_path", "message"}:
        raise MissingEvidenceError("invalid-schema selected occurrence has invalid metadata")
    if occurrence["input_path"] != required_path:
        raise AssertionError("invalid-schema selected occurrence has the wrong typed input path")
    if not isinstance(occurrence["message"], str) or not occurrence["message"]:
        raise MissingEvidenceError("invalid-schema selected occurrence lacks a native message")
    return {
        "assessment_id": assessment.assessment_id,
        "source_entry_ordinal": assessment.source_entry_ordinal,
        "rule": issue.rule,
        "schema_error_input_path": list(required_path),
        "selected_occurrences": [{"input_path": list(occurrence["input_path"]), "message": occurrence["message"]}],
    }


def _assert_assessment_rejection_controls(extraction: list[Any], invalid_schema: list[Any]) -> None:
    """Ensure malformed capture records cannot turn the real positives into passes."""
    checks: tuple[tuple[Any, type[BaseException]], ...] = (
        (replace(_one_assessment(extraction, "extraction"), kind="validation"), AssertionError),
        (replace(_one_assessment(extraction, "extraction"), selected_native=()), MissingEvidenceError),
        (replace(_one_assessment(invalid_schema, "invalid_schema"), schema_error_input_path=None), MissingEvidenceError),
        (replace(_one_assessment(invalid_schema, "invalid_schema"), selected_native=({"input_path": ("required",)},)), MissingEvidenceError),
    )
    for mutated, expected in checks:
        try:
            if mutated.kind == "invalid_schema":
                _invalid_schema_observation([mutated])
            else:
                _extraction_observation([mutated])
        except expected:
            continue
        except BaseException as exc:
            raise AssertionError("capture mutation raised the wrong predicate outcome") from exc
        raise AssertionError("malformed capture mutation was accepted as proof evidence")


async def _unavailable_assessment_controls(baseline: Any) -> dict[str, Any]:
    """Fault only the observation sink; native result behavior must remain intact."""
    baseline_text = getattr(getattr(baseline, "result", None), "text", None)
    if not isinstance(baseline_text, str):
        raise AssertionError("baseline repair fixture did not produce a native result")
    original_append = capture_module._OperationCapture.append

    def fault_append(self: Any, target: list[Any], record: Any, *, assessment: bool = False) -> bool:
        if assessment:
            self.evidence_available = False
            return False
        return original_append(self, target, record, assessment=assessment)

    setattr(capture_module._OperationCapture, "append", fault_append)  # noqa: B010 - restore requires dynamic patch
    try:
        faulted = await run_fixture(_fixture("repair", "invalid-then-valid"))
    finally:
        setattr(capture_module._OperationCapture, "append", original_append)  # noqa: B010 - restore dynamic patch
    original_cap = capture_module._MAX_ASSESSMENTS
    capture_module._MAX_ASSESSMENTS = 0
    try:
        capped = await run_fixture(_fixture("repair", "invalid-then-valid"))
    finally:
        capture_module._MAX_ASSESSMENTS = original_cap
    details: dict[str, str] = {}
    for name, run in (("fault", faulted), ("cap", capped)):
        if getattr(getattr(run, "result", None), "text", None) != baseline_text or run.error is not None:
            raise AssertionError(f"{name} observation control changed native repair behavior")
        try:
            validate_capture(run)
        except MissingEvidenceError as exc:
            details[name] = _detail(exc)
        else:
            raise AssertionError(f"{name} observation control falsely projected evidence")
    return {"native_result_preserved": True, "unavailable": details}


async def run_core_driver_assertion(recipe_ref: str) -> dict[str, Any]:
    """Execute one development-only native driver predicate.

    A failed predicate is distinct from unavailable evidence.  Cancellation and fatal
    base exceptions propagate so the caller cannot turn them into an invented result.
    """
    if recipe_ref not in CORE_DRIVER_RECIPE_IDS:
        raise HarnessError(f"unknown core driver recipe {recipe_ref!r}")
    try:
        if recipe_ref == "driver/concurrent-operations-independent":
            observations = await _concurrent_operations()
        elif recipe_ref == "driver/assessment-completeness":
            observations = await _assessment_completeness()
        else:
            from .proof_timeouts import observe_timeout_recipe

            observations = await observe_timeout_recipe(recipe_ref)
        return {"id": recipe_ref, "verdict": "pass", "detail": None, "evidence": _evidence(recipe_ref, observations)}
    except asyncio.CancelledError:
        raise
    except AssertionError as exc:
        return {"id": recipe_ref, "verdict": "fail", "detail": _detail(exc), "evidence": None}
    except (MissingEvidenceError, ValueDomainError, Exception) as exc:
        return {"id": recipe_ref, "verdict": "error", "detail": _detail(exc), "evidence": None}
