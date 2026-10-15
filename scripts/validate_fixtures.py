"""Validate language-neutral corpus assets before a driver executes them.

The validator deliberately owns only asset shape, corpus identity, and inventory coverage.
It does not interpret fixture behavior or compare reports; those are driver and release-tool
responsibilities.  An empty corpus is valid during initial authoring, but coverage mode is
deliberately unavailable until an inventory has been authored.
"""
# ruff: noqa: E501 -- §17's complete, space-delimited case lists are kept auditable here.

from __future__ import annotations

import argparse
import base64
import binascii
import json
import math
import re
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
SPECIFICATION = ROOT / "specification"
FIXTURES = SPECIFICATION / "fixtures"
SCHEMAS = SPECIFICATION / "schemas"
INVENTORY_NAME = "core-generation-v0.json"

EXTENSIONS = frozenset(
    {
        "schema.ref",
        "schema.combinators",
        "schema.other_dialects",
        "schema.boolean_subschema",
        "schema.unknown_keywords_ignored",
        "messages.tool_role",
        "targets.alias",
        "messages.non_text_parts",
    }
)

_CASE_GROUPS = {
    "normalization": "roles-ordered-text multi-part-text-concatenated sampling-omitted-when-unset sampling-supplied-fields target-first-colon-model-with-colon target-model-whitespace-stripped target-empty-model-invalid invalid-sampling-negative-seed empty-messages unsupported-tool-role unsupported-alias-target unsupported-image-part",
    "schema-admission": "admitted-full-subset-valid-response unknown-keyword-ignored unsupported-ref unsupported-anyof unsupported-dialect-draft7 unsupported-dialect-null unsupported-boolean-subschema",
    "extraction": "whole-json-object fenced-object-in-prose prose-then-array braces-inside-string empty-response malformed-first-candidate-no-rescue scalar-root-42 integer-above-2pow53-preserved duplicate-key-last-value-first-position",
    "validation": "missing-required-one six-missing-required-first-five-in-order additional-properties-aggregate type-mismatch-string-for-integer integral-float-is-integer enum-numeric-equality enum-empty-always-fails const-fails minimum-fails maximum-fails minlength-counts-code-points maxlength-fails minitems-fails maxitems-fails nested-deeper-issue-first ordering-tied-rules dotted-key-nested-path-collision literal-reserved-key-objects boolean-not-number-or-integer malformed-required-17-invalid-schema malformed-type-17-invalid-schema malformed-title-17-invalid-schema malformed-examples-17-invalid-schema malformed-schema-extraction-precedes-assessment",
    "repair": "valid-no-correction invalid-without-repair-fails invalid-then-valid exhaustion-two-invalid zero-budget provider-ceiling-clamp-parameter-dropped negative-budget-behaves-as-zero correction-prompt-exact-template",
    "routing": "retryable-then-ok-same-target nonretryable-falls-over auth-never-retried backoff-retry-after-floor backoff-cap health-skip-in-trail health-recovery-after-ttl duplicate-target-skipped all-targets-failed-trail restart-after-correction-transport-failure cleanup-failure-after-final-restarts post-content-stream-protocol-no-retry post-content-stream-protocol-in-correction-fatal post-content-transport-error-retries lazy-invalid-second-target",
    "streaming": "buffered-equals-streamed failed-attempt-deltas-visible first-token-mark-once-per-attempt synthesized-usage-update-from-final finish-reason-other cancel-mid-stream zero-advance-close usage-overlay-and-null-preservation reported-total-not-recomputed",
    "lifecycle": "repeated-close-idempotent",
    "transport/openai-chat": "single-frame frame-split-mid-json trailing-usage-chunk done-sentinel protocol-error-after-content non-sse-error-body-status-503 outbound-buffered-message-projection outbound-streamed-sampling-supplied outbound-sampling-omitted raw-byte-cap-multibyte-utf8 correction-byte-budget-reset",
    "driver": "concurrent-operations-independent assessment-completeness timeout-effective-default-explicit timeout-reset-per-entry timeout-cleanup-disposal http-correction-byte-budget-reset",
}
EXPECTED_CASE_IDS = frozenset(
    f"{family}/{slug}" for family, slugs in _CASE_GROUPS.items() for slug in slugs.split()
)
RECIPES = frozenset(case_id for case_id in EXPECTED_CASE_IDS if case_id.startswith("driver/"))
EXTENSION_CASES = {
    "normalization/unsupported-tool-role": "messages.tool_role",
    "normalization/unsupported-alias-target": "targets.alias",
    "normalization/unsupported-image-part": "messages.non_text_parts",
    "schema-admission/unknown-keyword-ignored": "schema.unknown_keywords_ignored",
    "schema-admission/unsupported-ref": "schema.ref",
    "schema-admission/unsupported-anyof": "schema.combinators",
    "schema-admission/unsupported-dialect-draft7": "schema.other_dialects",
    "schema-admission/unsupported-dialect-null": "schema.other_dialects",
    "schema-admission/unsupported-boolean-subschema": "schema.boolean_subschema",
}
_REPAIR_PREFIX = "Your previous response did not match the required JSON schema. Errors:\n"
_REPAIR_SUFFIX = "\nRespond again with ONLY a corrected JSON value that satisfies the schema. No prose, no code fences."
_SAME_CALL = re.compile(r"^same_as_call_([1-9][0-9]*)$")


def _bounded_int(text: str) -> int:
    value = int(text)
    if not -(2**63) <= value <= 2**63:
        raise ValueError("integer outside the v0 ±2^63 JSON bound")
    return value


def _finite_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise ValueError("non-finite JSON number")
    return value


def _reject_constant(text: str) -> None:
    raise ValueError(f"non-finite JSON token {text!r}")


def _read_json(path: Path) -> Any:
    data = json.loads(
        path.read_text(encoding="utf-8"),
        parse_int=_bounded_int,
        parse_float=_finite_float,
        parse_constant=_reject_constant,
    )
    _reject_surrogates(data)
    return data


def _reject_surrogates(value: Any) -> None:
    if isinstance(value, str):
        if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
            raise ValueError("lone surrogate in JSON string")
    elif isinstance(value, list):
        for item in value:
            _reject_surrogates(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            _reject_surrogates(key)
            _reject_surrogates(item)


def _schema(name: str) -> Draft202012Validator:
    raw = _read_json(SCHEMAS / name)
    Draft202012Validator.check_schema(raw)
    return Draft202012Validator(raw)


def _errors(validator: Draft202012Validator, data: Any) -> list[str]:
    return [
        error.message
        for error in sorted(validator.iter_errors(data), key=lambda item: list(item.path))
    ]


def _safe_json_files(directory: Path) -> Iterable[Path]:
    if not directory.exists():
        return ()
    root = directory.resolve()
    files: list[Path] = []
    for path in directory.rglob("*.json"):
        if path.is_symlink():
            raise ValueError(f"unsafe symlink fixture path: {path}")
        try:
            path.resolve().relative_to(root)
        except ValueError as error:
            raise ValueError(f"unsafe fixture path: {path}") from error
        files.append(path)
    return sorted(files)


def _validate_fixture_tree(
    root: Path, validators: dict[str, Draft202012Validator]
) -> tuple[dict[str, tuple[Path, str | None]], list[str]]:
    ids: dict[str, tuple[Path, str | None]] = {}
    problems: list[str] = []
    for directory, schema_name in (
        ("core-generation", "fixture-v0.schema.json"),
        ("transport", "transport-v0.schema.json"),
    ):
        try:
            paths = _safe_json_files(root / directory)
        except ValueError as error:
            problems.append(str(error))
            continue
        for path in paths:
            try:
                document = _read_json(path)
            except (OSError, ValueError, json.JSONDecodeError) as error:
                problems.append(f"{path}: invalid JSON: {error}")
                continue
            for schema_error in _errors(validators[schema_name], document):
                problems.append(f"{path}: {schema_error}")
            if schema_name == "transport-v0.schema.json":
                problems.extend(_transport_base64_errors(path, document))
            case_id = document.get("id") if isinstance(document, dict) else None
            document_family = document.get("family") if isinstance(document, dict) else None
            if isinstance(case_id, str):
                if case_id in ids:
                    problems.append(f"duplicate fixture id {case_id!r}: {ids[case_id]} and {path}")
                else:
                    ids[case_id] = (
                        path,
                        document_family if isinstance(document_family, str) else None,
                    )
    return ids, problems


def _transport_base64_errors(path: Path, document: Any) -> list[str]:
    """Return strict base64 decoding errors that JSON Schema annotations cannot express."""
    if not isinstance(document, dict) or not isinstance(document.get("responses"), list):
        return []
    problems: list[str] = []
    for response_index, response in enumerate(document["responses"]):
        if not isinstance(response, dict) or not isinstance(response.get("byte_chunks"), list):
            continue
        for chunk_index, chunk in enumerate(response["byte_chunks"]):
            value = chunk.get("bytes") if isinstance(chunk, dict) else None
            if not isinstance(value, str):
                continue
            try:
                base64.b64decode(value, validate=True)
            except (binascii.Error, ValueError):
                problems.append(
                    f"{path}: responses[{response_index}].byte_chunks[{chunk_index}].bytes "
                    "is not strict base64"
                )
    return problems


def _inventory_path(root: Path) -> Path:
    if root.resolve() == FIXTURES.resolve():
        return SPECIFICATION / "inventories" / INVENTORY_NAME
    return root / "inventories" / INVENTORY_NAME


def _corpus_fixture_path(root: Path, path_value: str) -> Path | None:
    """Resolve one canonical inventory fixture path inside the selected corpus only."""
    canonical_prefix = Path("specification") / "fixtures"
    path = Path(path_value)
    if path.is_absolute() or ".." in path.parts:
        return None
    try:
        relative = path.relative_to(canonical_prefix)
    except ValueError:
        return None
    if not relative.parts:
        return None
    candidate = root.resolve() / relative
    try:
        candidate.resolve().relative_to(root.resolve())
    except ValueError:
        return None
    return candidate


def _validate_inventory(
    path: Path,
    validator: Draft202012Validator,
    fixture_ids: dict[str, tuple[Path, str | None]],
    root: Path,
    *,
    coverage: bool,
    family: str | None,
) -> list[str]:
    try:
        inventory = _read_json(path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return [f"{path}: invalid JSON: {error}"]
    problems = [f"{path}: {error}" for error in _errors(validator, inventory)]
    if not isinstance(inventory, dict):
        return problems
    cases = inventory.get("cases", [])
    requirements = inventory.get("requirements", [])
    if not isinstance(cases, list) or not isinstance(requirements, list):
        return problems
    by_id: dict[str, dict[str, Any]] = {}
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("id"), str):
            continue
        case_id = case["id"]
        if case_id in by_id:
            problems.append(f"duplicate inventory case id {case_id!r}")
        by_id[case_id] = case
    missing_named = EXPECTED_CASE_IDS - set(by_id)
    extra_named = set(by_id) - EXPECTED_CASE_IDS
    if missing_named:
        problems.append(f"inventory omits named §17 cases: {', '.join(sorted(missing_named))}")
    if extra_named:
        problems.append(f"inventory has non-v0 case IDs: {', '.join(sorted(extra_named))}")
    mapped: set[str] = set()
    requirement_ids: set[str] = set()
    for requirement in requirements:
        if not isinstance(requirement, dict):
            continue
        requirement_id = requirement.get("id")
        if isinstance(requirement_id, str):
            if requirement_id in requirement_ids:
                problems.append(f"duplicate requirement id {requirement_id!r}")
            requirement_ids.add(requirement_id)
        for case_id in requirement.get("case_ids", []):
            if case_id not in by_id:
                problems.append(f"requirement {requirement_id!r} maps unknown case {case_id!r}")
            else:
                mapped.add(case_id)
    if coverage and set(by_id) - mapped:
        problems.append(
            "inventory cases missing requirement mapping: "
            f"{', '.join(sorted(set(by_id) - mapped))}"
        )
    for case_id, case in by_id.items():
        expected_extension = EXTENSION_CASES.get(case_id)
        if case.get("extension") != expected_extension:
            problems.append(f"{case_id}: extension must be {expected_extension!r}")
        if case.get("kind") == "driver_assertion":
            if case.get("recipe_ref") not in RECIPES:
                problems.append(f"{case_id}: recipe_ref must name its §17 driver predicate")
            continue
        path_value = case.get("path")
        if not isinstance(path_value, str):
            problems.append(f"{case_id}: unsafe or missing fixture path")
            continue
        actual = _corpus_fixture_path(root, path_value)
        if actual is None:
            problems.append(f"{case_id}: unsafe or missing fixture path")
            continue
        if coverage and (
            family is None or not path_value.startswith("specification/fixtures/transport/")
        ):
            if not actual.is_file():
                problems.append(f"{case_id}: inventory fixture is missing: {path_value}")
            elif case_id not in fixture_ids:
                problems.append(f"{case_id}: fixture ID is absent from fixture tree")
            else:
                actual_path, document_family = fixture_ids[case_id]
                if actual_path.resolve() != actual.resolve():
                    problems.append(f"{case_id}: inventory path does not name its fixture ID")
                if document_family != case.get("family"):
                    problems.append(f"{case_id}: fixture family does not match inventory family")
                if not case_id.startswith(f"{case.get('family')}/"):
                    problems.append(f"{case_id}: fixture ID does not match inventory family")
    if coverage and family == "core-generation":
        unexpected = set(fixture_ids) - {
            case_id for case_id, case in by_id.items() if case.get("kind") == "fixture"
        }
        if unexpected:
            problems.append(
                f"fixture files lack inventory records: {', '.join(sorted(unexpected))}"
            )
    return problems


def validate_report(report: Any) -> list[str]:
    """Validate a report document, including extension-call ordinal semantics."""
    validator = _schema("report-v0.schema.json")
    problems = _errors(validator, report)
    if not isinstance(report, dict) or not isinstance(report.get("cases"), list):
        return problems
    for case in report["cases"]:
        if not isinstance(case, dict) or case.get("verdict") != "extension":
            continue
        evidence = case.get("evidence")
        entries = evidence.get("adapter_entries") if isinstance(evidence, dict) else None
        if not isinstance(entries, list):
            continue
        ordinals = [entry.get("entry_ordinal") for entry in entries if isinstance(entry, dict)]
        if ordinals != list(range(len(entries))):
            problems.append(
                f"{case.get('id', '<unknown>')}: extension adapter_entries must have "
                "consecutive zero-based entry_ordinal values"
            )
    return problems


def _resolved_messages(calls: list[Any], index: int) -> tuple[list[Any] | None, str | None]:
    """Resolve a call's earlier-message reference chain without accepting cycles."""
    seen: set[int] = set()
    current = index
    while True:
        if current in seen:
            return None, "same_as_call reference cycle"
        seen.add(current)
        call = calls[current] if current < len(calls) else None
        messages = call.get("messages") if isinstance(call, dict) else None
        if isinstance(messages, list):
            return messages, None
        if not isinstance(messages, str):
            return None, "messages must be literal or same_as_call_n"
        match = _SAME_CALL.fullmatch(messages)
        if match is None:
            return None, "invalid same_as_call reference"
        target = int(match.group(1)) - 1
        if target < 0 or target >= current:
            return None, "same_as_call reference must name an earlier call"
        current = target


def _marker_positions(messages: list[Any], marker: str) -> list[tuple[int, int]]:
    positions: list[tuple[int, int]] = []
    for message_index, message in enumerate(messages):
        text = message.get("text") if isinstance(message, dict) else None
        if not isinstance(text, list):
            continue
        for segment_index, segment in enumerate(text):
            if isinstance(segment, dict) and segment.get(marker) is True and len(segment) == 1:
                positions.append((message_index, segment_index))
    return positions


def _expected_message_problems(document: Any) -> list[str]:
    if not isinstance(document, dict):
        return []
    expected = document.get("expected")
    calls = expected.get("calls") if isinstance(expected, dict) else None
    if not isinstance(calls, list):
        return []
    problems: list[str] = []
    for index, call in enumerate(calls):
        messages, error = _resolved_messages(calls, index)
        if error:
            problems.append(f"expected.calls[{index}]: {error}")
            continue
        if messages is None:
            continue
        repair_positions = _marker_positions(messages, "$repair_feedback")
        schema_positions = _marker_positions(messages, "$schema_prompt")
        role = call.get("role") if isinstance(call, dict) else None
        if role == "correction":
            if len(repair_positions) != 1:
                problems.append(
                    f"expected.calls[{index}]: correction needs exactly one $repair_feedback"
                )
            else:
                message_index, segment_index = repair_positions[0]
                message = messages[message_index]
                text = message.get("text") if isinstance(message, dict) else None
                before = (
                    "".join(part for part in text[:segment_index] if isinstance(part, str))
                    if isinstance(text, list)
                    else ""
                )
                after = (
                    "".join(part for part in text[segment_index + 1 :] if isinstance(part, str))
                    if isinstance(text, list)
                    else ""
                )
                if (
                    message_index != len(messages) - 1
                    or message.get("role") != "user"
                    or before != _REPAIR_PREFIX
                    or after != _REPAIR_SUFFIX
                ):
                    problems.append(
                        f"expected.calls[{index}]: $repair_feedback is not in the exact final repair user template"
                    )
        elif repair_positions:
            problems.append(
                f"expected.calls[{index}]: $repair_feedback is only valid for correction calls"
            )
        if schema_positions:
            request = document.get("request")
            if not isinstance(request, dict) or "schema" not in request:
                problems.append(f"expected.calls[{index}]: $schema_prompt requires request.schema")
            if len(schema_positions) != 1:
                problems.append(f"expected.calls[{index}]: $schema_prompt may appear exactly once")
            else:
                message_index, segment_index = schema_positions[0]
                message = messages[message_index]
                text = message.get("text") if isinstance(message, dict) else None
                system_indices = [
                    position
                    for position, item in enumerate(messages)
                    if isinstance(item, dict) and item.get("role") == "system"
                ]
                if (
                    not system_indices
                    or message_index != system_indices[-1]
                    or not isinstance(text, list)
                    or segment_index != len(text) - 1
                ):
                    problems.append(
                        f"expected.calls[{index}]: $schema_prompt must end the injected last system message"
                    )
    return problems


def validate(root: Path, *, coverage: bool = False, family: str | None = None) -> list[str]:
    """Return fixture and optional inventory validation problems for one asset tree."""
    validators = {
        name: _schema(name)
        for name in (
            "fixture-v0.schema.json",
            "transport-v0.schema.json",
            "inventory-v0.schema.json",
        )
    }
    fixture_ids, problems = _validate_fixture_tree(root, validators)
    for fixture_path, _family in fixture_ids.values():
        try:
            problems.extend(
                f"{fixture_path}: {problem}"
                for problem in _expected_message_problems(_read_json(fixture_path))
            )
        except (OSError, ValueError, json.JSONDecodeError) as error:
            problems.append(f"{fixture_path}: invalid JSON: {error}")
    inventory = _inventory_path(root)
    if inventory.exists():
        problems.extend(
            _validate_inventory(
                inventory,
                validators["inventory-v0.schema.json"],
                fixture_ids,
                root,
                coverage=coverage,
                family=family,
            )
        )
    elif coverage:
        problems.append(f"coverage requires an inventory: {inventory}")
    return problems


def main(argv: list[str] | None = None) -> int:
    """Run the portable-asset validator command."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=FIXTURES, help="fixture-root directory")
    parser.add_argument("--check-coverage", action="store_true")
    parser.add_argument("--family", choices=("core-generation",))
    args = parser.parse_args(argv)
    if args.family and not args.check_coverage:
        parser.error("--family requires --check-coverage")
    problems = validate(args.root, coverage=args.check_coverage, family=args.family)
    if problems:
        for problem in problems:
            print(f"error: {problem}", file=sys.stderr)
        return 1
    print(f"fixtures ok: {args.root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
