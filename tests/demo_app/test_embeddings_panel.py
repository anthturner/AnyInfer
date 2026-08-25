"""The demo's embeddings/rerank panel, driven end to end against the offline fake provider.

Same pattern as `test_library_coverage.py`'s `TestToolLoop`: build the panel, trigger the
action, drain the engine's background task through the Qt event loop, and assert on the
real `EmbeddingResult`/`RerankResult` the fake provider returned — not on the widget alone.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QEventLoop, QTimer

from anyinfer_demo.config import default_config
from anyinfer_demo.engine import Engine


def _drain_task(engine: Engine, key: str, timeout_ms: int = 15_000) -> object:
    loop = QEventLoop()
    outcome: dict[str, object] = {}

    def on_done(done_key: str, result: object) -> None:
        if done_key == key:
            outcome["result"] = result
            loop.quit()

    def on_failed(failed_key: str, message: str, _error: object) -> None:
        if failed_key == key:
            outcome["error"] = message
            loop.quit()

    engine.task_done.connect(on_done)
    engine.task_failed.connect(on_failed)
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()

    if "error" in outcome:
        raise AssertionError(f"task {key} failed: {outcome['error']}")
    if "result" not in outcome:
        raise AssertionError(f"task {key} timed out")
    return outcome["result"]


@pytest.fixture
def engine(qapp: object) -> Engine:
    built = Engine(default_config())
    yield built
    built.close()


def test_embed_button_disabled_until_target_set(engine: Engine, qapp: object) -> None:
    from anyinfer_demo.widgets.embeddings_panel import EmbeddingsPanel

    panel = EmbeddingsPanel(engine)
    assert panel._embed_button.isEnabled() is False
    assert panel._rerank_button.isEnabled() is False

    panel.set_target("anything")  # the panel ignores the value and uses its own targets
    assert panel._embed_button.isEnabled() is True
    assert panel._rerank_button.isEnabled() is True


def test_embed_runs_against_the_offline_fake(engine: Engine, qapp: object) -> None:
    from anyinfer import EmbeddingResult
    from anyinfer_demo.widgets.embeddings_panel import EMBED_KEY, EmbeddingsPanel

    panel = EmbeddingsPanel(engine)
    panel.set_target("ignored")
    panel._embed_input.setText("hello world")
    panel._on_embed()

    result = _drain_task(engine, EMBED_KEY)
    assert isinstance(result, EmbeddingResult)
    assert len(result.vectors) == 1

    panel._on_task_done(EMBED_KEY, result)
    assert "Embedded via" in panel._output.toPlainText()
    assert str(result.space.dimensions) in panel._output.toPlainText()


def test_rerank_runs_against_the_offline_fake(engine: Engine, qapp: object) -> None:
    from anyinfer import RerankResult
    from anyinfer_demo.widgets.embeddings_panel import RERANK_KEY, EmbeddingsPanel

    panel = EmbeddingsPanel(engine)
    panel.set_target("ignored")
    panel._rerank_query.setText("capital of France")
    panel._on_rerank()

    result = _drain_task(engine, RERANK_KEY)
    assert isinstance(result, RerankResult)
    assert len(result.items) == 3

    panel._on_task_done(RERANK_KEY, result)
    assert "Ranked via" in panel._output.toPlainText()


def test_embed_with_no_text_does_nothing(engine: Engine, qapp: object) -> None:
    from anyinfer_demo.widgets.embeddings_panel import EmbeddingsPanel

    panel = EmbeddingsPanel(engine)
    panel.set_target("ignored")
    panel._embed_input.setText("   ")
    panel._on_embed()
    # No crash, no task fired — the output box stays at its initial empty state.
    assert panel._output.toPlainText() == ""
