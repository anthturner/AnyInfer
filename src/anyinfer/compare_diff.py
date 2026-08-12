"""Portability diff tool: snapshot `compare()` output for a fixture set, diff two snapshots.

**Complementary to `contracts/DRIFT-CHECK.md`, not overlapping.** That procedure audits
whether AnyInfer's *claims* about a provider's wire protocol still match that provider's
*current* public docs — an external-facing check with network calls involved. This module
audits whether AnyInfer's own *decisions* (mechanism selection, parameter dropping, cache
planning, cost estimation) for a *fixed* request are stable over time and across a code
change — an internal, mechanical check with no network calls to a provider's docs at all. A
drift-check failure means "the world changed and our contract snapshot is stale." A
portability-diff failure means "our own code changed what it decides, and nobody noticed."

Two needs, one primitive: snapshot `TargetComparison.to_dict()` output for a fixed set of
requests against a fixed set of targets, and diff two snapshots structurally.

1. **Regression detection**: does a code change silently alter what a fixed request becomes
   on a fixed target? Run this project's own gate list against a checked-in baseline
   snapshot.
2. **Portability reporting**: "here's a diff of exactly what changes" moving a workload from
   provider A to provider B — a falsifiable fact sheet instead of prose documentation of
   feature parity.

**No ranking, scoring, or recommendation of any kind.** Every diff reports facts in caller
order, exactly as `compare()` itself already does — adding a verdict would cross the same
boundary adaptive routing would. This module never dispatches: it only ever calls
`compare()`/`compare_embedding()`, which are themselves no-dispatch by design.

**The fixture format is a public, versioned schema** (`FIXTURE_SCHEMA_VERSION`), not an
internal-only file: a vendor embedding AnyInfer defines fixtures against their own real
request shapes, because their regression risk is their own requests, not AnyInfer's
illustrative examples. A fixture file that validates against one schema version keeps
validating across patch/minor releases of this module.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .errors import ConfigError
from .types.messages import Message, assistant, system, user
from .types.requests import GenerationRequest

if TYPE_CHECKING:
    from ._client.sync_client import Client

__all__ = [
    "FIXTURE_SCHEMA_VERSION",
    "DiffEntry",
    "DiffReport",
    "Fixture",
    "diff",
    "diff_targets",
    "load_fixtures",
    "render_text",
    "snapshot",
]

FIXTURE_SCHEMA_VERSION = 1
"""The fixture file format this module reads and writes. Additive, never breaking: a
future version adds fields or fixture kinds, it never repurposes an existing key."""


@dataclass(frozen=True, slots=True)
class Fixture:
    """One request to snapshot against one ordered set of targets.

    Attributes:
        id: Stable identifier — the key snapshots and diffs are organized by. Renaming a
            fixture's id is a breaking change to any baseline snapshot that references it,
            the same way renaming a test would be.
        request: The request to compare, already resolved to a `GenerationRequest`.
        targets: Target strings to compare `request` against, in the order results are
            reported (never reordered — `compare()`'s own ordering discipline).
    """

    id: str
    request: GenerationRequest
    targets: tuple[str, ...]


def load_fixtures(path: str | Path) -> tuple[Fixture, ...]:
    """Parse and validate a fixture file.

    Raises:
        anyinfer.errors.ConfigError: The file is missing, not valid JSON, declares an
            unsupported `schema_version`, or a fixture entry is malformed.
    """
    file_path = Path(path)
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"could not read fixture file {file_path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"fixture file {file_path} is not valid JSON: {exc}") from exc

    if not isinstance(data, Mapping) or data.get("schema_version") != FIXTURE_SCHEMA_VERSION:
        raise ConfigError(
            f"fixture file {file_path} has an unsupported format",
            hint=f"expected a JSON object with schema_version: {FIXTURE_SCHEMA_VERSION}",
        )
    raw_fixtures = data.get("fixtures")
    if not isinstance(raw_fixtures, list):
        raise ConfigError(f"fixture file {file_path} is missing a 'fixtures' array")

    return tuple(_parse_fixture(raw, index) for index, raw in enumerate(raw_fixtures))


def _parse_fixture(raw: Any, index: int) -> Fixture:
    if not isinstance(raw, Mapping):
        raise ConfigError(f"fixture #{index} must be an object")
    try:
        fixture_id = str(raw["id"])
        request_raw = raw["request"]
        targets = tuple(str(t) for t in raw["targets"])
    except KeyError as missing:
        raise ConfigError(f"fixture #{index} is missing field {missing.args[0]!r}") from None
    if not targets:
        raise ConfigError(f"fixture {fixture_id!r} has no targets")
    return Fixture(id=fixture_id, request=_parse_request(request_raw, fixture_id), targets=targets)


def _parse_request(raw: Any, fixture_id: str) -> GenerationRequest:
    if not isinstance(raw, Mapping):
        raise ConfigError(f"fixture {fixture_id!r}: 'request' must be an object")
    raw_messages = raw.get("messages")
    if not isinstance(raw_messages, list) or not raw_messages:
        raise ConfigError(f"fixture {fixture_id!r}: 'request.messages' must be a non-empty array")
    messages = tuple(_parse_message(m, fixture_id) for m in raw_messages)
    return GenerationRequest(messages=messages)


_ROLE_BUILDERS = {"system": system, "user": user, "assistant": assistant}


def _parse_message(raw: Any, fixture_id: str) -> Message:
    if not isinstance(raw, Mapping):
        raise ConfigError(f"fixture {fixture_id!r}: each message must be an object")
    role = str(raw.get("role", "user"))
    text = str(raw.get("text", ""))
    builder = _ROLE_BUILDERS.get(role)
    if builder is None:
        raise ConfigError(
            f"fixture {fixture_id!r}: unsupported message role {role!r}",
            hint="use 'system', 'user', or 'assistant'",
        )
    return builder(text)


def snapshot(fixtures: Sequence[Fixture], *, client: Client) -> dict[str, Any]:
    """Run `compare()` over every fixture and serialize the results.

    No new result data model — this only persists `TargetComparison.to_dict()`'s existing
    shape, keyed by fixture id and then by target string, so a diff can address any single
    (fixture, target) pair directly.

    Args:
        fixtures: Fixtures to snapshot, typically from `load_fixtures()`.
        client: A configured `anyinfer.Client` — its provider settings determine which
            targets actually resolve.

    Returns:
        A JSON-safe mapping: ``{"schema_version": ..., "fixtures": {id: {target: {...}}}}``.
    """
    result: dict[str, dict[str, Any]] = {}
    for fixture in fixtures:
        comparisons = client.compare(fixture.request, targets=fixture.targets)
        result[fixture.id] = {c.requested: c.to_dict() for c in comparisons}
    return {"schema_version": FIXTURE_SCHEMA_VERSION, "fixtures": result}


@dataclass(frozen=True, slots=True)
class DiffEntry:
    """One reported difference between two snapshots.

    Attributes:
        fixture_id: Which fixture this entry belongs to.
        target: Which target this entry belongs to.
        kind: ``"added"`` (present only in the newer snapshot), ``"removed"`` (present only
            in the baseline), or ``"changed"`` (present in both with a different value).
        field: Dotted path within `TargetComparison.to_dict()`'s shape, e.g.
            ``"structured_mechanism"`` or ``"dropped.0.name"``.
        before: The baseline value, or ``None`` when `kind` is ``"added"``.
        after: The current value, or ``None`` when `kind` is ``"removed"``.
        summary: A plain-language line reusing `compare()`'s own field vocabulary.
    """

    fixture_id: str
    target: str
    kind: str
    field: str
    before: Any
    after: Any
    summary: str


@dataclass(frozen=True, slots=True)
class DiffReport:
    """The full result of diffing two snapshots (or two live comparisons).

    Attributes:
        entries: Every difference found, in a stable order (fixture, then target, then
            field) — never ranked or filtered by significance.
    """

    entries: tuple[DiffEntry, ...]

    @property
    def is_empty(self) -> bool:
        """Whether the two snapshots reported were identical."""
        return not self.entries


def diff(baseline: Mapping[str, Any], current: Mapping[str, Any]) -> DiffReport:
    """Structurally diff two snapshots produced by `snapshot()`.

    Raises:
        anyinfer.errors.ConfigError: Either mapping is not a valid snapshot document.
    """
    base_fixtures = _snapshot_fixtures(baseline, "baseline")
    current_fixtures = _snapshot_fixtures(current, "current")

    entries: list[DiffEntry] = []
    for fixture_id in sorted(set(base_fixtures) | set(current_fixtures)):
        base_targets = base_fixtures.get(fixture_id, {})
        current_targets = current_fixtures.get(fixture_id, {})
        for target in sorted(set(base_targets) | set(current_targets)):
            before = base_targets.get(target)
            after = current_targets.get(target)
            if before is None and after is not None:
                entries.append(
                    DiffEntry(
                        fixture_id, target, "added", "", None, after,
                        f"{fixture_id}/{target}: new in this snapshot",
                    )
                )
                continue
            if after is None and before is not None:
                entries.append(
                    DiffEntry(
                        fixture_id, target, "removed", "", before, None,
                        f"{fixture_id}/{target}: no longer present in this snapshot",
                    )
                )
                continue
            entries.extend(_diff_values(fixture_id, target, "", before, after))
    return DiffReport(tuple(entries))


def _snapshot_fixtures(document: Mapping[str, Any], label: str) -> dict[str, dict[str, Any]]:
    version = document.get("schema_version") if isinstance(document, Mapping) else None
    if version != FIXTURE_SCHEMA_VERSION:
        raise ConfigError(f"{label} snapshot has an unsupported format")
    fixtures = document.get("fixtures")
    if not isinstance(fixtures, Mapping):
        raise ConfigError(f"{label} snapshot is missing its 'fixtures' mapping")
    return {str(k): dict(v) for k, v in fixtures.items()}


def _diff_values(
    fixture_id: str, target: str, path: str, before: Any, after: Any
) -> list[DiffEntry]:
    if before == after:
        return []
    if isinstance(before, Mapping) and isinstance(after, Mapping):
        entries: list[DiffEntry] = []
        for key in sorted(set(before) | set(after)):
            sub_path = f"{path}.{key}" if path else key
            if key not in before:
                entries.append(
                    DiffEntry(
                        fixture_id, target, "added", sub_path, None, after[key],
                        f"{fixture_id}/{target}: {sub_path} appeared ({after[key]!r})",
                    )
                )
            elif key not in after:
                entries.append(
                    DiffEntry(
                        fixture_id, target, "removed", sub_path, before[key], None,
                        f"{fixture_id}/{target}: {sub_path} disappeared (was {before[key]!r})",
                    )
                )
            else:
                entries.extend(_diff_values(fixture_id, target, sub_path, before[key], after[key]))
        return entries
    if isinstance(before, list) and isinstance(after, list) and len(before) == len(after):
        entries = []
        for index, (b_item, a_item) in enumerate(zip(before, after, strict=True)):
            entries.extend(_diff_values(fixture_id, target, f"{path}.{index}", b_item, a_item))
        return entries
    return [
        DiffEntry(
            fixture_id, target, "changed", path, before, after,
            f"{fixture_id}/{target}: {path or '(value)'} changed from {before!r} to {after!r}",
        )
    ]


def diff_targets(
    fixture: Fixture, target_a: str, target_b: str, *, client: Client
) -> DiffReport:
    """The ad hoc, no-baseline-file "should I move from A to B" report.

    Runs `compare()` live for exactly `[target_a, target_b]` under `fixture` and diffs the
    two resulting comparisons directly — the customer-facing portability report.
    """
    comparisons = client.compare(fixture.request, targets=(target_a, target_b))
    by_target = {c.requested: c.to_dict() for c in comparisons}
    # Reuse the same structural differ used for baseline/current snapshots, comparing
    # target_a's record against target_b's directly rather than a second implementation.
    entries = _diff_values(
        fixture.id,
        f"{target_a} -> {target_b}",
        "",
        by_target.get(target_a),
        by_target.get(target_b),
    )
    return DiffReport(tuple(entries))


def render_text(report: DiffReport) -> str:
    """Human-readable rendering of a `DiffReport`, one line per entry."""
    if report.is_empty:
        return "no differences"
    return "\n".join(entry.summary for entry in report.entries)
