"""Embed text and rank documents against a query — the two operations alongside generation.

`Client.embed()` and `Client.rerank()` are typed, routed operations distinct from
generation; this panel is not a chat surface reusing the composer, because the two things
it does are not conversation turns. It renders vector length and top-ranked documents, and
never dumps raw floats into the transcript — a printed 1536-float vector is not something a
person reads.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from anyinfer import EmbeddingResult, RerankResult

from ..engine import Engine
from ..fake_provider import DEMO_EMBEDDING_MODEL, DEMO_EMBEDDING_PROVIDER_ID, DEMO_RERANK_MODEL

__all__ = ["EMBED_KEY", "RERANK_KEY", "EmbeddingsPanel"]

EMBED_KEY = "embeddings.embed"
RERANK_KEY = "embeddings.rerank"

_DEMO_EMBED_TARGET = f"{DEMO_EMBEDDING_PROVIDER_ID}:{DEMO_EMBEDDING_MODEL}"
_DEMO_RERANK_TARGET = f"{DEMO_EMBEDDING_PROVIDER_ID}:{DEMO_RERANK_MODEL}"

_SAMPLE_DOCUMENTS = (
    "Paris is the capital of France.",
    "Berlin is the capital of Germany.",
    "The Eiffel Tower is located in Paris.",
)


class EmbeddingsPanel(QWidget):
    """Embed a line of text, and rank a small fixed document set against a query."""

    def __init__(self, engine: Engine) -> None:
        super().__init__()
        self._engine = engine
        self._embed_target = ""
        self._rerank_target = ""

        layout = QVBoxLayout(self)
        caption = QLabel(
            "Two operations distinct from generation. <code>Client.embed()</code> turns "
            "text into vectors; <code>Client.rerank()</code> ranks documents by relevance "
            "to a query. Neither is a chat turn, and neither shares a request type with "
            "the composer above."
        )
        caption.setWordWrap(True)
        caption.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(caption)

        embed_row = QHBoxLayout()
        self._embed_input = QLineEdit("The quick brown fox jumps over the lazy dog.")
        self._embed_input.setAccessibleName("Text to embed")
        self._embed_input.returnPressed.connect(self._on_embed)
        embed_row.addWidget(self._embed_input, 1)
        self._embed_button = QPushButton("Embed")
        self._embed_button.setEnabled(False)
        self._embed_button.clicked.connect(self._on_embed)
        embed_row.addWidget(self._embed_button)
        layout.addLayout(embed_row)

        rerank_row = QHBoxLayout()
        self._rerank_query = QLineEdit("capital of France")
        self._rerank_query.setAccessibleName("Rerank query")
        self._rerank_query.returnPressed.connect(self._on_rerank)
        rerank_row.addWidget(self._rerank_query, 1)
        self._rerank_button = QPushButton("Rank documents")
        self._rerank_button.setEnabled(False)
        self._rerank_button.clicked.connect(self._on_rerank)
        rerank_row.addWidget(self._rerank_button)
        layout.addLayout(rerank_row)

        self._hint = QLabel(
            f"<i>Offline targets: <code>{_DEMO_EMBED_TARGET}</code> and "
            f"<code>{_DEMO_RERANK_TARGET}</code>. Rerank always scores this fixed "
            "three-document set against your query.</i>"
        )
        self._hint.setTextFormat(Qt.TextFormat.RichText)
        self._hint.setWordWrap(True)
        layout.addWidget(self._hint)

        self._output = QTextEdit()
        self._output.setReadOnly(True)
        self._output.setAccessibleName("Embeddings and rerank output")
        layout.addWidget(self._output, 1)

        engine.task_done.connect(self._on_task_done)
        engine.task_failed.connect(self._on_task_failed)

    def set_target(self, target: str) -> None:
        """Adopt the window's currently selected target, when it is offline-capable.

        The generation target selector names a chat model; embedding and rerank models
        are a separate operation with their own target space, so this panel offers the
        demo's own offline targets rather than reinterpreting the bar's selection.
        """
        del target  # the bar's chat target does not name an embedding/rerank model
        self._embed_target = _DEMO_EMBED_TARGET
        self._rerank_target = _DEMO_RERANK_TARGET
        self._embed_button.setEnabled(True)
        self._rerank_button.setEnabled(True)

    def _on_embed(self) -> None:
        text = self._embed_input.text().strip()
        if not text or not self._embed_target:
            return
        self._output.setHtml("<i>Embedding…</i>")
        self._engine.embed_text(EMBED_KEY, [text], self._embed_target)

    def _on_rerank(self) -> None:
        query = self._rerank_query.text().strip()
        if not query or not self._rerank_target:
            return
        self._output.setHtml("<i>Ranking…</i>")
        self._engine.rerank_documents(
            RERANK_KEY, query, list(_SAMPLE_DOCUMENTS), self._rerank_target
        )

    def _on_task_done(self, key: str, result: object) -> None:
        if key == EMBED_KEY and isinstance(result, EmbeddingResult):
            self._render_embed_result(result)
        elif key == RERANK_KEY and isinstance(result, RerankResult):
            self._render_rerank_result(result)

    def _render_embed_result(self, result: EmbeddingResult) -> None:
        vector = result.vectors[0]
        preview = ", ".join(f"{v:.3f}" for v in vector.values[:6])
        lines = [
            f"<b>Embedded via <code>{result.target}</code></b>",
            f"Space: <code>{result.space.provider_id}:{result.space.model}</code>, "
            f"{result.space.dimensions} dimensions",
            f"First 6 of {len(vector)} values: [{preview}, …]",
        ]
        if result.usage.input_tokens is not None:
            lines.append(f"Input tokens: {result.usage.input_tokens}")
        for warning in result.warnings:
            lines.append(f"<i>warning: {warning}</i>")
        self._output.setHtml("<br>".join(lines))

    def _render_rerank_result(self, result: RerankResult) -> None:
        lines = [f"<b>Ranked via <code>{result.target}</code></b>", ""]
        for rank, item in enumerate(result.items, start=1):
            document = _SAMPLE_DOCUMENTS[item.index]
            lines.append(f"{rank}. ({item.score:.3f}) {document}")
        self._output.setHtml("<br>".join(lines))

    def _on_task_failed(self, key: str, message: str, error: object) -> None:
        if key not in (EMBED_KEY, RERANK_KEY):
            return
        hint = getattr(error, "hint", "")
        lines = ["<b>Request failed</b>", message]
        if hint:
            lines.append(f"<i>Hint: {hint}</i>")
        self._output.setHtml("<br>".join(lines))
