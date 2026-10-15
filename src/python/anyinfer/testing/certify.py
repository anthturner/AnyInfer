"""Run the conformance suite against an adapter you wrote.

The suite that certifies the built-in adapters is the same suite a third-party adapter
runs. This module is the documented way in: it reads what a provider *claims* not to
support from its own project file, drives `run_conformance`, and renders the result as the
matrix row, JSON, or a terminal report.

Declared-unsupported cases are read from the plugin's ``pyproject.toml`` rather than passed
on a command line, so "what we do not support" is a checked-in statement that review can
see, not a flag someone can quietly flip on a bad day.

```toml
[tool.anyinfer.conformance]
reasoning = false     # this provider has no reasoning channel
retry_after = false   # its rate limiting cannot be provoked on demand
```
"""

from __future__ import annotations

import tomllib
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import fields as dataclass_fields
from pathlib import Path

from ..errors import ConfigError
from .conformance import (
    CONFORMANCE_CASES,
    Capabilities,
    CaseResult,
    ConformanceHarness,
    run_conformance,
)

__all__ = [
    "CONFORMANCE_TABLE",
    "ClientFactory",
    "case_names",
    "certify",
    "load_declared_capabilities",
    "render_report",
]

CONFORMANCE_TABLE = ("tool", "anyinfer", "conformance")
"""Path to the declaration table inside a plugin's ``pyproject.toml``."""

ClientFactory = Callable[[str], Awaitable[object]]
"""Builds a client for one conformance scenario.

Called once per case and closed by the runner, so it must return a *fresh* client rather
than a shared one.
"""


def case_names() -> tuple[str, ...]:
    """Every conformance case name, in matrix order."""
    return tuple(case.name for case in CONFORMANCE_CASES)


def load_declared_capabilities(project: Path | None = None) -> Capabilities:
    """Read a plugin's declared capabilities from its ``pyproject.toml``.

    Args:
        project: The project directory, or the ``pyproject.toml`` itself. Defaults to the
            current directory. A missing file means "supports everything", which is the
            right default: an adapter that has declared nothing has excused nothing.

    Returns:
        The declared capabilities.

    Raises:
        ConfigError: If the table names a capability that does not exist, or gives one a
            non-boolean value. A typo that silently read as "unsupported" would let an
            adapter certify itself by omission.
    """
    path = _resolve_project(project)
    if path is None or not path.exists():
        return Capabilities()

    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(
            f"could not read {path}",
            hint="conformance declarations live in [tool.anyinfer.conformance]",
        ) from exc

    table: object = document
    for key in CONFORMANCE_TABLE:
        if not isinstance(table, dict):
            return Capabilities()
        table = table.get(key, {})
    if not isinstance(table, dict) or not table:
        return Capabilities()

    known = {field.name for field in dataclass_fields(Capabilities)}
    values: dict[str, bool] = {}
    for key, value in table.items():
        if key not in known:
            raise ConfigError(
                f"unknown conformance capability {key!r} in {path}",
                hint=f"known capabilities: {', '.join(sorted(known))}",
            )
        if not isinstance(value, bool):
            raise ConfigError(
                f"conformance capability {key!r} must be true or false, not {value!r}",
                hint="declaring false documents an unsupported case as ➖, not as a pass",
            )
        values[key] = value
    return Capabilities(**values)


async def certify(
    provider_id: str,
    model: str,
    build_client: ClientFactory,
    *,
    supports: Capabilities | None = None,
    only: Sequence[str] | None = None,
) -> list[CaseResult]:
    """Run the conformance suite against one adapter.

    Args:
        provider_id: The provider under test, as registered.
        model: Model id to send.
        build_client: Builds a fresh client for a scenario name.
        supports: Declared capabilities; unsupported cases are skipped rather than failed.
        only: Restrict the run to these case names.

    Returns:
        One result per case, in matrix order.

    Raises:
        ConfigError: If ``only`` names a case that does not exist.
    """
    if only:
        unknown = sorted(set(only) - set(case_names()))
        if unknown:
            raise ConfigError(
                f"unknown conformance case(s): {', '.join(unknown)}",
                hint=f"known cases: {', '.join(case_names())}",
            )

    harness = ConformanceHarness(
        provider_id=provider_id,
        model=model,
        build_client=build_client,  # type: ignore[arg-type]
        supports=supports or Capabilities(),
    )
    return await run_conformance(harness, only=only)


def render_report(provider_id: str, results: Sequence[CaseResult]) -> str:
    """Render results as an aligned terminal report.

    Failures carry their detail, because a bare ❌ tells an adapter author nothing about
    what to fix.
    """
    if not results:
        return f"{provider_id}: no cases ran"

    width = max(len(r.name) for r in results)
    lines = [f"{provider_id}", ""]
    for result in results:
        line = f"  {result.symbol}  {result.name.ljust(width)}"
        if result.detail:
            line = f"{line}  {result.detail}"
        lines.append(line)

    passed = sum(1 for r in results if r.passed and not r.skipped)
    skipped = sum(1 for r in results if r.skipped)
    failed = sum(1 for r in results if not r.passed and not r.skipped)
    lines.extend(
        [
            "",
            f"  {passed} passed, {failed} failed, {skipped} declared unsupported",
        ]
    )
    return "\n".join(lines)


def _resolve_project(project: Path | None) -> Path | None:
    if project is None:
        return Path.cwd() / "pyproject.toml"
    if project.is_dir():
        return project / "pyproject.toml"
    return project
