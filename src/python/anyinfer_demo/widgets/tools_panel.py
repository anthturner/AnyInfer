"""The tool loop, run by the library rather than by this application.

A tool-using turn is not one request. The model answers with a *call*, the application runs
the named function, the result goes back as another message, and the model answers again —
possibly several times. `run_tools()` owns that loop, including
matching a returned call to a declared tool, encoding the result, counting rounds, and
stopping when the budget is spent.

What the demo supplies is the part that is genuinely the application's: two ordinary Python
functions. Their JSON schemas are derived from the annotations by
`tool()`, so nothing here maintains a hand-written schema
alongside a signature that can drift from it.

The offline provider serves a ``tools`` model that scripts a tool call on its first request,
so the whole round trip is visible with no credentials and no network. The transcript below
shows each round as it happened, which is the point: an application that only sees the final
string cannot tell whether a tool ran at all.
"""

from __future__ import annotations

import datetime as _datetime
from typing import Any

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

from anyinfer import Generation, tool

from ..engine import Engine

__all__ = ["TOOLS", "TOOLS_KEY", "ToolsPanel"]

TOOLS_KEY = "tools.run"

_CALLS: list[str] = []
"""Every tool invocation this session, newest last.

Recorded because "the model said it called the function" and "the function ran" are
different claims, and only one of them is evidence.
"""


@tool
def current_time(timezone: str = "UTC") -> str:
    """Report the current time in a named timezone."""
    _CALLS.append(f"current_time(timezone={timezone!r})")
    if timezone.upper() == "UTC":
        now = _datetime.datetime.now(_datetime.UTC)
    else:
        now = _datetime.datetime.now()
    return now.isoformat(timespec="seconds")


@tool
def word_count(text: str) -> int:
    """Count the words in a piece of text."""
    _CALLS.append(f"word_count(text={text[:32]!r})")
    return len(text.split())


TOOLS: tuple[Any, ...] = (current_time, word_count)
"""The tools offered to the model, declared once as plain functions."""


class ToolsPanel(QWidget):
    """Run one tool-loop turn and show every round it took."""

    def __init__(self, engine: Engine) -> None:
        super().__init__()
        self._engine = engine
        self._target = ""

        layout = QVBoxLayout(self)
        caption = QLabel(
            "Two ordinary Python functions, offered to the model. "
            "<code>run_tools()</code> issues the request, dispatches whatever the model "
            "asks for, feeds the result back, and repeats until there is an answer — this "
            "panel contains no loop of its own."
        )
        caption.setWordWrap(True)
        caption.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(caption)

        declared = ", ".join(f"<code>{t.name}</code>" for t in TOOLS)
        tools_label = QLabel(f"Available: {declared}")
        tools_label.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(tools_label)

        row = QHBoxLayout()
        self._prompt = QLineEdit("What time is it in UTC?")
        self._prompt.setAccessibleName("Tool-loop prompt")
        self._prompt.returnPressed.connect(self._on_run)
        row.addWidget(self._prompt, 1)

        self._run = QPushButton("Run tool loop")
        self._run.setEnabled(False)
        self._run.clicked.connect(self._on_run)
        row.addWidget(self._run)
        layout.addLayout(row)

        self._hint = QLabel(
            "<i>Pick <code>demo-fake:tools</code> above to watch this offline — that model "
            "answers its first request with a tool call.</i>"
        )
        self._hint.setTextFormat(Qt.TextFormat.RichText)
        self._hint.setWordWrap(True)
        layout.addWidget(self._hint)

        self._output = QTextEdit()
        self._output.setReadOnly(True)
        self._output.setAccessibleName("Tool loop transcript")
        layout.addWidget(self._output, 1)

        engine.task_done.connect(self._on_task_done)
        engine.task_failed.connect(self._on_task_failed)

    def set_target(self, target: str) -> None:
        """Adopt the window's currently selected target."""
        self._target = target
        self._run.setEnabled(bool(target))

    def _on_run(self) -> None:
        prompt = self._prompt.text().strip()
        if not prompt or not self._target:
            return
        _CALLS.clear()
        self._output.setHtml("<i>Running — the loop may take several rounds…</i>")
        self._engine.run_tools(TOOLS_KEY, prompt, self._target, TOOLS)

    def _on_task_done(self, key: str, result: object) -> None:
        if key != TOOLS_KEY or not isinstance(result, Generation):
            return
        lines = [
            f"<b>Answered via <code>{result.target}</code></b>",
            f"Finish reason: {result.finish_reason}",
            f"Rounds recorded as attempts: {len(result.attempts)}",
            "",
            "<b>Tools actually executed</b>",
        ]
        # The record kept by the functions themselves, not a count parsed back out of the
        # answer: a model claiming to have called something is not evidence that it did.
        if _CALLS:
            lines.extend(f"• <code>{call}</code>" for call in _CALLS)
        else:
            lines.append("None — the model answered without asking for one.")
        lines.extend(["", "<b>Answer</b>", result.text or "<i>(empty)</i>"])
        for warning in result.warnings:
            lines.append(f"<i>warning: {warning}</i>")
        self._output.setHtml("<br>".join(lines))

    def _on_task_failed(self, key: str, message: str, error: object) -> None:
        if key != TOOLS_KEY:
            return
        hint = getattr(error, "hint", "")
        lines = ["<b>Tool loop failed</b>", message]
        if hint:
            lines.append(f"<i>Hint: {hint}</i>")
        self._output.setHtml("<br>".join(lines))
