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
def close_top_level_widgets(qapp):
    """Keep the session-scoped Qt application from retaining UI state between tests."""
    yield
    for widget in qapp.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    qapp.processEvents()


@pytest.fixture
def wait_for_models():
    """Return a waiter for one provider's background model discovery."""
    from PySide6.QtCore import QEventLoop, QTimer

    def wait(engine, provider_id: str, timeout_ms: int = 15_000):
        loop = QEventLoop()
        outcome: dict[str, object] = {}

        def on_listed(done_provider: str, models: object) -> None:
            if done_provider == provider_id:
                outcome["models"] = models
                loop.quit()

        def on_failed(failed_provider: str, message: str, _error: object) -> None:
            if failed_provider == provider_id:
                outcome["error"] = message
                loop.quit()

        engine.models_listed.connect(on_listed)
        engine.discovery_failed.connect(on_failed)
        QTimer.singleShot(timeout_ms, loop.quit)
        loop.exec()

        if "error" in outcome:
            raise AssertionError(f"model discovery failed: {outcome['error']}")
        if "models" not in outcome:
            raise AssertionError("model discovery timed out")
        return outcome["models"]

    return wait


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
