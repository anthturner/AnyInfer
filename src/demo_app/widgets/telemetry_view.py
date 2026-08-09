"""A live inspector for the typed telemetry contract, rendered as a card timeline.

Everything shown here arrives as a `TelemetryEvent` through a
plain observer callable. The rendering is structural — event type, target, and the fields that
type carries — rather than a formatted log string, because the contract is *typed events*, not
text.

Payload privacy is demonstrated too: the observer is registered without ``payloads=True``, so
``prompt_text`` and ``response_text`` arrive as ``None`` and the inspector shows them as
withheld rather than empty.
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from anyinfer.events.telemetry import (
    PAYLOAD_FIELDS,
    AttemptCompleted,
    AttemptStarted,
    CachePlanned,
    ContextReduced,
    FallbackTriggered,
    FirstToken,
    ParameterDropped,
    RepairAttempted,
    RequestCompleted,
    RequestFailed,
    RequestStarted,
    RetryScheduled,
    TargetResolved,
)

from .. import theme
from ..strings import TELEMETRY_TITLE

__all__ = ["TelemetryView"]

_SEVERITY: dict[type, str] = {
    RequestFailed: "danger",
    RetryScheduled: "warn",
    FallbackTriggered: "warn",
    RepairAttempted: "warn",
    ParameterDropped: "warn",
    # Trimming is legal but consequential — content was dropped, and that deserves the
    # same visual weight as any other "something gave way" event.
    ContextReduced: "warn",
    RequestCompleted: "ok",
    AttemptCompleted: "ok",
    FirstToken: "ok",
}

_BADGE = {"danger": "✕", "warn": "⚠", "ok": "✓"}


class _RequestCard(QFrame):
    """One request's whole trail, collapsed into a single expandable card."""

    def __init__(self, request_id: str, targets: tuple[str, ...]) -> None:
        super().__init__()
        self.setObjectName("TelemetryCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.request_id = request_id

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(14, 12, 14, 12)
        self._layout.setSpacing(8)

        target_chain = " → ".join(targets) or "(no targets)"
        header = QLabel(f"<b>{target_chain}</b> <code>{request_id[:8]}</code>")
        header.setTextFormat(Qt.TextFormat.RichText)
        header.setAccessibleName(f"Request {request_id}")
        self._layout.addWidget(header)

        self._events = QVBoxLayout()
        self._events.setContentsMargins(12, 4, 0, 4)
        self._events.setSpacing(4)
        self._layout.addLayout(self._events)

    def add_event(self, event: Any) -> None:
        severity = _SEVERITY.get(type(event))
        badge = _BADGE.get(severity, "•") if severity else "•"
        color = theme.color(severity) if severity else theme.color("muted")
        line = QLabel(
            f"<span style='color:{color}'>{badge} <b>{type(event).__name__}</b></span> "
            f"{_details_of(event)}"
        )
        line.setTextFormat(Qt.TextFormat.RichText)
        line.setWordWrap(True)
        self._events.addWidget(line)


class TelemetryView(QWidget):
    """A vertical timeline of request cards, newest last."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(10)
        caption = QLabel(
            f"<b>{TELEMETRY_TITLE}</b> — typed, in-process events. Registered "
            "<b>without</b> payloads, so prompt and response text are withheld."
        )
        caption.setObjectName("Caption")
        caption.setWordWrap(True)
        caption.setTextFormat(Qt.TextFormat.RichText)
        header.addWidget(caption, 1)

        self._clear_button = QPushButton()
        self._clear_button.setObjectName("IconButton")
        self._clear_button.setFixedSize(28, 28)
        self._clear_button.setToolTip("Clear telemetry")
        self._clear_button.setAccessibleName("Clear telemetry")
        self._clear_button.clicked.connect(self.clear)
        self.reapply_theme()
        header.addWidget(self._clear_button)
        layout.addLayout(header)

        self._scroll = QScrollArea()
        self._scroll.setObjectName("TelemetryScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setAccessibleName("Telemetry timeline")
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        container = QWidget()
        self._cards_layout = QVBoxLayout(container)
        self._cards_layout.setContentsMargins(10, 10, 10, 10)
        self._cards_layout.setSpacing(10)
        self._cards_layout.addStretch(1)
        self._scroll.setWidget(container)
        layout.addWidget(self._scroll, 1)

        self._requests: dict[str, _RequestCard] = {}
        self._count = 0

    def reapply_theme(self) -> None:
        """Re-render the themed clear icon after a theme change."""
        from .icons import themed_icon

        self._clear_button.setIcon(themed_icon(self._clear_button, "eraser", size=16))

    def clear(self) -> None:
        """Drop every recorded event."""
        for card in self._requests.values():
            self._cards_layout.removeWidget(card)
            card.setParent(None)
        self._requests.clear()
        self._count = 0

    @property
    def event_count(self) -> int:
        """How many events have been recorded since the last clear."""
        return self._count

    def add_event(self, event: Any) -> None:
        """Record one telemetry event."""
        self._count += 1

        if isinstance(event, RequestStarted):
            card = _RequestCard(event.request_id, event.targets)
            self._cards_layout.insertWidget(self._cards_layout.count() - 1, card)
            self._requests[event.request_id] = card
            self._scroll_to_bottom()
            return

        request_id = getattr(event, "request_id", "")
        existing = self._requests.get(request_id)
        if existing is not None:
            existing.add_event(event)
            self._scroll_to_bottom()

    def _scroll_to_bottom(self) -> None:
        bar = self._scroll.verticalScrollBar()
        bar.setValue(bar.maximum())


def _details_of(event: Any) -> str:
    """A structural rendering of the fields this event type carries."""
    if isinstance(event, TargetResolved):
        alias = event.target.via_alias
        return f"via alias {alias!r}" if alias else "direct target"
    if isinstance(event, AttemptStarted):
        return f"attempt {event.attempt_number}"
    if isinstance(event, FirstToken):
        return f"TTFT {event.at_ms:.0f} ms (measured by the core)"
    if isinstance(event, AttemptCompleted):
        return f"{event.finish_reason}, {_usage_summary(event.usage)}"
    if isinstance(event, RetryScheduled):
        return (
            f"attempt {event.attempt_number} failed ({event.error.type_name}); "
            f"retrying in {event.delay_s:.2f}s"
        )
    if isinstance(event, FallbackTriggered):
        reason = event.error.type_name if event.error else "unknown"
        return f"→ {event.to_target} after {reason}"
    if isinstance(event, RepairAttempted):
        first = event.errors[0] if event.errors else "schema violation"
        return f"repair {event.attempt_number} via {event.mechanism}: {first}"
    if isinstance(event, RequestCompleted):
        detail = f"{_usage_summary(event.usage)}, {event.timing.total_ms:.0f} ms total"
        if event.repair_attempts:
            detail += f", {event.repair_attempts} repair(s)"
        return f"{detail}. {_payload_note(event)}"
    if isinstance(event, RequestFailed):
        return f"{event.error.type_name}: {event.error.detail}"
    if isinstance(event, ParameterDropped):
        return f"dropped {event.parameter!r} — {event.reason}"
    if isinstance(event, CachePlanned):
        return (
            f"{event.mechanism or 'no'} caching, {event.mark_count} mark(s), "
            f"~{event.estimated_cacheable_tokens:,} cacheable tokens"
        )
    if isinstance(event, ContextReduced):
        return (
            f"{event.strategy}: kept {event.selected_count} of {event.candidate_count}, "
            f"omitted {event.omitted_count} — ~{event.estimated_tokens:,} of "
            f"{event.max_tokens:,} tokens"
        )
    return _generic_details(event)


def _generic_details(event: Any) -> str:
    """Fallback rendering for event types this view has no special case for."""
    if not is_dataclass(event):
        return str(event)
    parts = []
    for spec in fields(event):
        if spec.name in {"request_id", "target", "from_target"}:
            continue
        parts.append(f"{spec.name}={getattr(event, spec.name)!r}")
    return ", ".join(parts)


def _payload_note(event: Any) -> str:
    """Say explicitly whether text payloads were delivered or withheld."""
    payload_fields = PAYLOAD_FIELDS.get(type(event))
    if not payload_fields:
        return ""
    withheld = [f for f in payload_fields if getattr(event, f, None) is None]
    if withheld:
        return f"{', '.join(withheld)} withheld (observer did not opt into payloads)"
    return "payload delivered"


def _usage_summary(usage: Any) -> str:
    """Compact token/cost line that never invents a number it was not given."""
    parts = []
    if usage.input_tokens is not None:
        parts.append(f"in {usage.input_tokens}")
    if usage.output_tokens is not None:
        parts.append(f"out {usage.output_tokens}")
    if usage.cost_usd is not None:
        parts.append(f"${usage.cost_usd:.6f}")
    return ", ".join(parts) if parts else "usage not reported"
