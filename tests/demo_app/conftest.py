"""Headless Qt fixtures for the demo-app tests."""

from __future__ import annotations

import os

import pytest

# Must be set before QApplication is constructed, so no display is ever required.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qapp():
    """One QApplication for the whole session; Qt forbids a second."""
    pytest.importorskip("PySide6", reason="the demo app requires the 'demo' extra")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def isolated_config_path(tmp_path, monkeypatch):
    """Redirect the demo's config file into the test's tmp dir.

    Closing a MainWindow persists the session's selections; without this, tests would
    write into the developer's real per-user configuration.
    """
    try:
        import demo_app.config as demo_config
    except ImportError:
        yield
        return
    monkeypatch.setattr(demo_config, "CONFIG_PATH", tmp_path / "demo.json")
    yield
