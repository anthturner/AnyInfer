"""Opt-in pytest integration for UNRELEASED portable observations."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from .driver import (
    _DEFAULT_ROOT,
    _REPOSITORY_ROOT,
    _reference_revision,
    observe_core,
    reference_output_paths,
    reference_report_publisher,
    write_json,
)
from .reference import ReferencePreflightError, preflight_reference
from .reference_writer import write_reference


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
        metavar="REVISION",
        help="write a clean-source reference for this lowercase 40-hex revision",
    )


def pytest_sessionstart(session: pytest.Session) -> None:
    config = session.config
    if hasattr(config, "workerinput"):
        return
    revision = config.getoption("write_reference")
    if revision is None:
        return
    root = config.getoption("portable_root")
    try:
        revision = _reference_revision(revision)
        manifest, environment = reference_output_paths(revision)
        preflight_reference(
            root,
            expected_revision=revision,
            output_manifest=manifest,
            output_environment=environment,
            repository_root=_REPOSITORY_ROOT,
        )
        report = config.getoption("portable_report")
        if report is not None:
            reference_report_publisher(
                report,
                selected_root=root,
                manifest_path=manifest,
                environment_path=environment,
            )
    except (ReferencePreflightError, ValueError) as error:
        raise pytest.UsageError(str(error)) from error


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    config = session.config
    path = config.getoption("portable_report")
    if hasattr(config, "workerinput"):
        return
    root = config.getoption("portable_root")
    revision = config.getoption("write_reference")
    metadata: dict[str, Any] = {
        "exit_status": exitstatus,
        "passed": exitstatus == pytest.ExitCode.OK,
    }
    if revision is None:
        if path is None:
            return
        report: dict[str, Any] = asyncio.run(observe_core(root))
        report["pytest"] = metadata
        write_json(path, report)
        return

    revision = _reference_revision(revision)
    manifest, environment = reference_output_paths(revision)
    publisher = (
        reference_report_publisher(
            path,
            selected_root=root,
            manifest_path=manifest,
            environment_path=environment,
            pytest_metadata=metadata,
        )
        if path is not None
        else None
    )
    if exitstatus != pytest.ExitCode.OK:
        if publisher is not None:
            publisher(asyncio.run(observe_core(root)))
        return
    asyncio.run(
        write_reference(
            root,
            expected_revision=revision,
            output_manifest=manifest,
            output_environment=environment,
            repository_root=_REPOSITORY_ROOT,
            observe=observe_core,
            publish_observation=publisher,
        )
    )
