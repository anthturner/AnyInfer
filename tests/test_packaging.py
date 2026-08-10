"""Packaging invariants: what an installed distribution must get right."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

import anyinfer

ROOT = Path(__file__).resolve().parent.parent


def test_version_matches_pyproject() -> None:
    """`anyinfer.__version__` and `project.version` are the same string.

    The release workflow tags and publishes from pyproject; a drifted `__version__`
    would ship wheels that report the wrong version at runtime.
    """
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert anyinfer.__version__ == pyproject["project"]["version"]


def test_license_file_is_present_and_mit() -> None:
    """The MIT license text GitHub and PyPI detect must exist at the repo root."""
    text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert text.startswith("MIT License")
    assert "Permission is hereby granted, free of charge" in text


def test_the_sidecar_bundle_carries_its_service_instructions(tmp_path, monkeypatch) -> None:
    """SI.5: the standalone download explains how to keep itself running.

    The archive is built by PyInstaller in CI, which is too slow to do here, so what is
    asserted is the function that populates its layout — and, more importantly, that the
    text comes from the same renderer `anyinfer serve install` uses, so the download and
    the command can never describe different definitions.
    """
    import sys
    import tempfile

    sys.path.insert(0, str(ROOT))
    import workspace

    from anyinfer.serve.service import ServiceRequest, render_service

    # The renderer refuses an executable inside a temporary directory, which is exactly
    # the guard SI.3 asks for — and exactly where pytest puts this fixture. Move the
    # notion of "temporary" out from under it so the guard stays armed for real paths.
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path / "elsewhere"))

    app_dir = tmp_path / "anyinfer-serve"
    app_dir.mkdir()
    workspace._write_service_install_text(app_dir)

    text = (app_dir / "INSTALL.txt").read_text(encoding="utf-8")
    executable = app_dir / ("anyinfer-serve.exe" if os.name == "nt" else "anyinfer-serve")
    definition = render_service(ServiceRequest(executable=executable.resolve()))

    assert definition.content in text
    assert "anyinfer-serve install" in text
    assert "127.0.0.1" in text


def test_the_sidecar_bundle_info_points_at_those_instructions() -> None:
    """A file nobody is told about is a file nobody reads."""
    source = (ROOT / "workspace.py").read_text(encoding="utf-8")
    marker = source.split("product=\"AnyInfer sidecar\"", 1)[1][:400]
    assert "INSTALL.txt" in marker
