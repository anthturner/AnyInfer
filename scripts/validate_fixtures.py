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
import importlib.util
import json
import math
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError
from referencing import Registry, Resource
from referencing.exceptions import (
    CannotDetermineSpecification,
    NoSuchResource,
    Unresolvable,
    Unretrievable,
)

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


def read_json(path: Path) -> Any:
    """Read one ordinary-JSON asset under the v0 numeric and Unicode rules."""
    data = json.loads(
        path.read_text(encoding="utf-8"),
        parse_int=_bounded_int,
        parse_float=_finite_float,
        parse_constant=_reject_constant,
    )
    _reject_surrogates(data)
    return data


# Kept for existing private callers while release tooling adopts ``read_json``.
_read_json = read_json


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


class SchemaEvaluationError(ValueError):
    """A selected schema attempted an unbound reference during evaluation."""


def _deny_schema_retrieval(uri: str) -> None:
    raise NoSuchResource(uri)


def build_schema_validator(
    raw: Any, *, resources: Mapping[str, Any] | None = None
) -> Draft202012Validator:
    """Build a selected-asset validator with only explicit local resources."""
    Draft202012Validator.check_schema(raw)
    registry = cast(Any, Registry)(retrieve=_deny_schema_retrieval)
    for uri, resource in (resources or {}).items():
        if not isinstance(uri, str) or not uri:
            raise ValueError("selected schema resource URI is invalid")
        if (
            not isinstance(resource, Mapping)
            or resource.get("$schema") != "https://json-schema.org/draft/2020-12/schema"
        ):
            raise ValueError(
                f"selected schema resource {uri!r} must declare the Draft 2020-12 $schema"
            )
        Draft202012Validator.check_schema(resource)
        try:
            registry = registry.with_resource(uri, Resource.from_contents(resource))
        except CannotDetermineSpecification as error:
            raise ValueError(f"selected schema resource {uri!r} has no usable specification") from error
    return Draft202012Validator(raw, registry=registry)


def schema_errors(validator: Draft202012Validator, data: Any) -> list[ValidationError]:
    """Evaluate one selected schema, translating unresolved references for callers."""
    try:
        return sorted(validator.iter_errors(data), key=lambda item: list(item.path))
    except (Unresolvable, Unretrievable) as error:
        raise SchemaEvaluationError(f"selected schema reference is unavailable: {error}") from error


def _schema(
    name: str, *, specification_root: Path | None = None
) -> Draft202012Validator:
    root = SPECIFICATION if specification_root is None else specification_root
    raw = read_json(root / "schemas" / name)
    resources: dict[str, Any] = {}
    if name == "transport-v0.schema.json":
        resources["fixture-v0.schema.json"] = read_json(root / "schemas" / "fixture-v0.schema.json")
    return build_schema_validator(raw, resources=resources)


def _errors(validator: Draft202012Validator, data: Any) -> list[str]:
    try:
        return [error.message for error in schema_errors(validator, data)]
    except SchemaEvaluationError as error:
        return [str(error)]


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
    root: Path,
    validators: dict[str, Draft202012Validator],
    fixture_paths: Sequence[Path] | None = None,
) -> tuple[dict[str, tuple[Path, str | None]], list[str]]:
    ids: dict[str, tuple[Path, str | None]] = {}
    problems: list[str] = []
    selected: list[tuple[Path, str]] = []
    if fixture_paths is None:
        for directory, schema_name in (
            ("core-generation", "fixture-v0.schema.json"),
            ("transport", "transport-v0.schema.json"),
        ):
            try:
                selected.extend((path, schema_name) for path in _safe_json_files(root / directory))
            except ValueError as error:
                problems.append(str(error))
    else:
        selected, selected_problems = _selected_fixture_files(root, fixture_paths)
        problems.extend(selected_problems)
    for path, schema_name in selected:
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


def _selected_fixture_files(
    root: Path, fixture_paths: Sequence[Path]
) -> tuple[list[tuple[Path, str]], list[str]]:
    """Return explicitly selected corpus files after containment and family checks."""
    selected: list[tuple[Path, str]] = []
    problems: list[str] = []
    lexical_root = root.absolute()
    resolved_root = root.resolve()
    seen: set[Path] = set()
    schemas = {
        "core-generation": "fixture-v0.schema.json",
        "transport": "transport-v0.schema.json",
    }
    for supplied in fixture_paths:
        path = supplied.absolute() if supplied.is_absolute() else lexical_root / supplied
        try:
            relative = path.relative_to(lexical_root)
        except ValueError:
            problems.append(f"unsafe selected fixture path: {supplied}")
            continue
        if ".." in relative.parts or any(
            _is_link_or_reparse(lexical_root.joinpath(*relative.parts[:index]))
            for index in range(1, len(relative.parts) + 1)
        ):
            problems.append(f"unsafe selected fixture path: {supplied}")
            continue
        resolved = path.resolve()
        try:
            resolved.relative_to(resolved_root)
        except ValueError:
            problems.append(f"unsafe selected fixture path: {supplied}")
            continue
        if resolved in seen:
            problems.append(f"unsafe or duplicate selected fixture path: {supplied}")
            continue
        if (
            path.suffix.lower() != ".json"
            or len(relative.parts) < 2
            or relative.parts[0] not in schemas
        ):
            problems.append(f"invalid selected fixture path: {supplied}")
            continue
        if not path.is_file():
            problems.append(f"selected fixture is missing: {supplied}")
            continue
        seen.add(resolved)
        selected.append((path, schemas[relative.parts[0]]))
    return selected, problems


def _is_link_or_reparse(path: Path) -> bool:
    """Identify final or intermediate links, including Windows junctions when available."""
    is_junction = getattr(path, "is_junction", None)
    return path.is_symlink() or (callable(is_junction) and is_junction())


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


def _inventory_path(
    root: Path, specification_root: Path, *, explicit_specification_root: bool
) -> Path:
    if explicit_specification_root or root.resolve() == (specification_root / "fixtures").resolve():
        return specification_root / "inventories" / INVENTORY_NAME
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
    specification_root: Path | None = None,
) -> list[str]:
    normative_root = root.parent.parent if root.name == "fixtures" else ROOT
    selected_specification = (
        normative_root / "specification" if specification_root is None else specification_root
    )
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
    for requirement in requirements:
        if not isinstance(requirement, dict) or not isinstance(requirement.get("spec_ref"), str):
            continue
        ref = requirement["spec_ref"]
        path_text, separator, fragment = ref.partition("#")
        path = Path(path_text)
        resolved_specification = selected_specification.resolve()
        noncanonical = (
            "\\" in path_text
            or path.is_absolute()
            or path_text.startswith(("/", "\\"))
            or bool(re.match(r"^[A-Za-z]:", path_text))
            or ".." in path.parts
            or not path.parts
            or path.parts[0] != "specification"
        )
        target = (
            normative_root / path
            if specification_root is None
            else selected_specification.joinpath(*path.parts[1:])
        ).resolve()
        try:
            target.relative_to(resolved_specification)
        except ValueError:
            noncanonical = True
        if (
            not separator
            or not fragment
            or noncanonical
            or not target.is_file()
            or target.suffix.lower() != ".md"
        ):
            problems.append(f"requirement {requirement.get('id')!r} has invalid spec_ref {ref!r}")
            continue
        module_spec = importlib.util.spec_from_file_location(
            "markdown_link_anchors", ROOT / "scripts" / "check_markdown_links.py"
        )
        if module_spec is None or module_spec.loader is None:
            problems.append("cannot load Markdown anchor validator")
            continue
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
        if fragment not in module.anchors(target):
            problems.append(
                f"requirement {requirement.get('id')!r} references missing fragment {ref!r}"
            )
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
        if case_id in RECIPES:
            if (
                case.get("kind") != "driver_assertion"
                or case.get("family") != "driver"
                or case.get("path") is not None
                or case.get("recipe_ref") != case_id
            ):
                problems.append(f"{case_id}: must be its canonical driver_assertion record")
            continue
        if case.get("kind") != "fixture" or case.get("family") != case_id.rsplit("/", 1)[0]:
            problems.append(f"{case_id}: must be its canonical fixture record")
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


def validate_report(
    report: Any, *, specification_root: Path | None = None
) -> list[str]:
    """Validate a report document, including extension-call ordinal semantics."""
    try:
        validator = _schema("report-v0.schema.json", specification_root=specification_root)
    except (OSError, ValueError, json.JSONDecodeError, SchemaError) as error:
        return [f"report schema is unavailable or invalid: {error}"]
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


def validate(
    root: Path,
    *,
    coverage: bool = False,
    family: str | None = None,
    specification_root: Path | None = None,
    fixture_paths: Sequence[Path] | None = None,
) -> list[str]:
    """Return fixture and optional inventory validation problems for one asset tree."""
    explicit_specification_root = specification_root is not None
    selected_specification = SPECIFICATION if specification_root is None else specification_root
    try:
        validators = {
            name: _schema(name, specification_root=selected_specification)
            for name in (
                "fixture-v0.schema.json",
                "transport-v0.schema.json",
                "inventory-v0.schema.json",
            )
        }
    except (OSError, ValueError, json.JSONDecodeError, SchemaError) as error:
        return [f"selected schema is unavailable or invalid: {error}"]
    fixture_ids, problems = _validate_fixture_tree(root, validators, fixture_paths)
    for fixture_path, _family in fixture_ids.values():
        try:
            problems.extend(
                f"{fixture_path}: {problem}"
                for problem in _expected_message_problems(_read_json(fixture_path))
            )
        except (OSError, ValueError, json.JSONDecodeError) as error:
            problems.append(f"{fixture_path}: invalid JSON: {error}")
    inventory = _inventory_path(
        root,
        selected_specification,
        explicit_specification_root=explicit_specification_root,
    )
    if inventory.exists():
        problems.extend(
            _validate_inventory(
                inventory,
                validators["inventory-v0.schema.json"],
                fixture_ids,
                root,
                coverage=coverage,
                family=family,
                specification_root=specification_root,
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
