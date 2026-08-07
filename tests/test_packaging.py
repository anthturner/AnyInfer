"""Packaging invariants: what an installed distribution must get right."""

from __future__ import annotations

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
