"""Opt-in pytest integration for UNRELEASED portable observations."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from .driver import _DEFAULT_ROOT, observe_core, write_json


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("portable development observation")
    group.addoption(
        "--portable-report", type=Path, help="write an UNRELEASED portable development observation"
    )
    group.addoption(
        "--portable-root",
        type=Path,
        default=_DEFAULT_ROOT,
        help="selected specification directory",
    )
    group.addoption(
        "--write-reference",
        type=Path,
        help="reserved; fails closed until reference preflight exists",
    )


def pytest_sessionstart(session: pytest.Session) -> None:
    if session.config.getoption("write_reference") is not None:
        raise pytest.UsageError(
            "--write-reference is unavailable until M1.5c/M1.7 reference preflight exists"
        )


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    config = session.config
    path = config.getoption("portable_report")
    if path is None or hasattr(config, "workerinput"):
        return
    report: dict[str, Any] = asyncio.run(observe_core(config.getoption("portable_root")))
    report["pytest"] = {"exit_status": exitstatus, "passed": exitstatus == pytest.ExitCode.OK}
    write_json(path, report)
