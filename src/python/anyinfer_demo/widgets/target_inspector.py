"""What the library knows about a target, and what it can find out by asking.

The Providers panel answers "is this engine reachable, and what models does it list". This
one goes a level down, to a single ``provider:model`` target, and covers the four questions
the library has separate calls for:

===========  ============  =================================================================
Button       Library call  What it costs
===========  ============  =================================================================
Capabilities ``resolve()`` Nothing — pure lookup, no request leaves the process
Verify       ``verify()``  One request, end to end
Probe        ``probe()``   One request *per feature* being probed
Benchmark    ``benchmark`` One deterministic request, timed
===========  ============  =================================================================

The cost column is displayed, not just documented. These are the demo's only buttons that
spend real tokens against a real provider, and a probe that quietly issues six requests is
exactly the sort of thing an application should not do on a user's behalf without saying so.

Capability values are rendered with their `Sourced`
provenance intact — ``catalog``, ``discovered``, ``probed``, or ``default``, because that
tag is the difference between a measured context window and a guess, and collapsing it to
a bare number is precisely what the library refuses to do.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from anyinfer import (
    Diagnostic,
    Measurement,
    ModelCapabilities,
    ProbeReport,
    ResolvedTarget,
    Verification,
)

from ..engine import Engine

__all__ = ["TargetInspector"]

RESOLVE_KEY = "target.resolve"
PROBE_KEY = "target.probe"
VERIFY_KEY = "target.verify"
BENCHMARK_KEY = "target.benchmark"
DIAGNOSTICS_KEY = "target.diagnostics"

_TASK_KEYS = (RESOLVE_KEY, PROBE_KEY, VERIFY_KEY, BENCHMARK_KEY, DIAGNOSTICS_KEY)


def _sourced(label: str, value: Any) -> str:
    """Render one capability with its provenance, or say it is unknown.

    The provenance is not decoration. "32,768 tokens (default)" means nobody measured it
    and the number is a fallback; "32,768 tokens (discovered)" means the provider said so.
    An application that shows only the number has thrown away the difference.
    """
    if value is None:
        return f"{label}: —"
    inner = getattr(value, "value", value)
    source = getattr(value, "provenance", "")
    rendered = f"{inner:,}" if isinstance(inner, int) else str(inner)
    return f"{label}: {rendered}" + (f" <i>({source})</i>" if source else "")


def _capabilities_lines(capabilities: ModelCapabilities) -> list[str]:
    """Render a capability set as display lines, provenance included."""
    lines = [
        _sourced("Context window", capabilities.context_window),
        _sourced("Max output tokens", capabilities.max_output_tokens),
    ]
    features = capabilities.features
    names = (
        ", ".join(sorted(f.name or "?" for f in type(features.value) if f & features.value))
        or "none"
    )
    lines.append(f"Features: {names} <i>({features.provenance})</i>")
    if capabilities.pricing is not None:
        pricing = capabilities.pricing.value
        lines.append(
            f"Pricing: {pricing.input_per_1m} in / {pricing.output_per_1m} out "
            f"per 1M {pricing.currency} <i>({capabilities.pricing.provenance})</i>"
        )
    else:
        lines.append("Pricing: — <i>(not on file)</i>")
    local = capabilities.local
    if local is not None:
        lines.append(f"Local: {local.parameter_size or '?'} params, {local.quantization or '?'}")
    return lines


class TargetInspector(QWidget):
    """Capabilities, verification, feature probes, and a benchmark for one target."""

    target_requested = Signal()
    """Emitted when the panel needs the window's currently selected target."""

    def __init__(self, engine: Engine) -> None:
        super().__init__()
        self._engine = engine
        self._target = ""
        self._blocks: list[str] = []

        layout = QVBoxLayout(self)
        caption = QLabel(
            "Four library calls against the selected target. Only the first is free — the "
            "rest issue real requests, so the button says how many."
        )
        caption.setWordWrap(True)
        layout.addWidget(caption)

        self._target_label = QLabel("<i>No target selected.</i>")
        self._target_label.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self._target_label)

        buttons = QHBoxLayout()
        self._resolve = self._button(
            buttons, "Capabilities", "No request — a pure lookup of what is already known."
        )
        self._resolve.clicked.connect(self._on_resolve)
        self._verify_button = self._button(
            buttons, "Verify (1 request)", "Ask the target something and prove it answers."
        )
        self._verify_button.clicked.connect(self._on_verify)
        self._probe_button = self._button(
            buttons,
            "Probe (1 request per feature)",
            "Measure what the target really supports, one request per feature probed.",
        )
        self._probe_button.clicked.connect(self._on_probe)
        self._benchmark_button = self._button(
            buttons,
            "Benchmark x2 (2 requests)",
            "Two deterministic requests, back to back. The second is warm by "
            "construction; comparing it with the first makes any cold-start cost "
            "visible instead of silently folded into one number.",
        )
        self._benchmark_button.clicked.connect(self._on_benchmark)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self._output = QTextEdit()
        self._output.setReadOnly(True)
        self._output.setAccessibleName("Target inspector output")
        self._output.setPlaceholderText(
            "Pick an engine and model above, then choose one of the calls."
        )
        layout.addWidget(self._output, 1)

        engine.task_done.connect(self._on_task_done)
        engine.task_failed.connect(self._on_task_failed)

    def _button(self, row: QHBoxLayout, label: str, tip: str) -> QPushButton:
        button = QPushButton(label)
        button.setToolTip(tip)
        button.setAccessibleName(label)
        button.setEnabled(False)
        row.addWidget(button)
        return button

    def set_target(self, target: str) -> None:
        """Adopt the window's currently selected ``provider:model`` target."""
        self._target = target
        self._target_label.setText(
            f"Target: <code>{target}</code>" if target else "<i>No target selected.</i>"
        )
        for button in (
            self._resolve,
            self._verify_button,
            self._probe_button,
            self._benchmark_button,
        ):
            button.setEnabled(bool(target))

    # ---- actions -----------------------------------------------------------------------

    def _on_resolve(self) -> None:
        if self._target:
            self._begin("Resolving…")
            self._engine.resolve(RESOLVE_KEY, self._target)

    def _on_verify(self) -> None:
        if self._target:
            self._begin("Verifying — one request in flight…")
            self._engine.verify(VERIFY_KEY, self._target)

    def _on_probe(self) -> None:
        if self._target:
            self._begin("Probing — one request per feature…")
            self._engine.probe(PROBE_KEY, self._target)

    def _on_benchmark(self) -> None:
        if self._target:
            self._begin("Benchmarking — two deterministic requests, back to back…")
            self._engine.benchmark_pair(BENCHMARK_KEY, self._target)

    def _begin(self, message: str) -> None:
        self._show([f"<i>{message}</i>"])

    # ---- results -----------------------------------------------------------------------

    def _on_task_done(self, key: str, result: object) -> None:
        """Render whichever of the four calls just came back."""
        if key not in _TASK_KEYS:
            return
        if key == RESOLVE_KEY and isinstance(result, ResolvedTarget):
            self._render_resolved(result)
        elif key == VERIFY_KEY and isinstance(result, Verification):
            self._render_verification(result)
        elif key == PROBE_KEY and isinstance(result, ProbeReport):
            self._render_probe(result)
        elif (
            key == BENCHMARK_KEY
            and isinstance(result, tuple)
            and len(result) == 2
            and all(isinstance(m, Measurement) for m in result)
        ):
            self._render_measurements(result[0], result[1])
        elif key == DIAGNOSTICS_KEY and isinstance(result, Sequence):
            self._render_diagnostics(result)

    def _render_resolved(self, resolved: ResolvedTarget) -> None:
        lines = [
            "<b>Resolved</b> (no request issued)",
            f"Provider: <code>{resolved.provider_id}</code>",
            f"Model: <code>{resolved.model}</code>",
        ]
        if resolved.via_alias:
            lines.append(f"Reached via alias: <code>{resolved.via_alias}</code>")
        self._show(lines)
        # Capabilities and runtime advisories are separate calls; ask for the advisory now
        # so the panel shows both halves of "what do we know about this provider".
        self._engine.diagnostics(DIAGNOSTICS_KEY, resolved.provider_id)

    def _render_diagnostics(self, diagnostics: Sequence[Any]) -> None:
        real = [d for d in diagnostics if isinstance(d, Diagnostic)]
        if not real:
            self._append(["", "<b>Diagnostics</b>", "Nothing reported."])
            return
        self._append(
            ["", "<b>Diagnostics</b>"]
            + [f"[{d.severity}] <code>{d.code}</code> — {d.message}" for d in real]
        )

    def _render_verification(self, verification: Verification) -> None:
        verdict = "✓ works" if verification.ok else "✕ failed"
        lines = [
            f"<b>Verification: {verdict}</b>",
            f"Reached the provider: {'yes' if verification.reached else 'no'}",
            f"Latency: {verification.latency_ms:.0f} ms",
        ]
        if verification.mechanism:
            lines.append(f"Structured-output mechanism: {verification.mechanism}")
        if verification.detail:
            lines.append(f"Detail: {verification.detail}")
        if verification.reply:
            lines.append(f"Reply: <code>{verification.reply}</code>")
        usage = verification.usage
        lines.append(f"Usage: {usage.input_tokens or '—'} in / {usage.output_tokens or '—'} out")
        for diagnostic in verification.diagnostics:
            lines.append(f"[{diagnostic.severity}] {diagnostic.code} — {diagnostic.message}")
        self._show(lines)

    def _render_probe(self, report: ProbeReport) -> None:
        lines = [
            f"<b>Probe of <code>{report.target.provider_id}:{report.target.model}</code></b>",
            f"Requests issued: {report.requests} · "
            f"tokens {report.usage.input_tokens or 0} in / "
            f"{report.usage.output_tokens or 0} out",
            "",
        ]
        for probe in report.probes:
            mark = {"supported": "✓", "unsupported": "✕"}.get(probe.outcome, "?")
            detail = f" — {probe.detail}" if probe.detail else ""
            lines.append(f"{mark} {probe.feature.name}: {probe.outcome}{detail}")
        if report.capabilities is not None:
            lines.append("")
            lines.append("<b>Capabilities after probing</b>")
            lines.extend(_capabilities_lines(report.capabilities))
        self._show(lines)

    def _render_measurements(self, first: Measurement, second: Measurement) -> None:
        """Render the back-to-back pair, with the warm-up delta made explicit.

        The claim is deliberately about the *protocol*, not the engine's memory: the
        second run is warm because the first just ran — that much is constructed here
        and is certain. Whether the first was cold is not knowable from outside the
        engine, so it is reported as the open question it is.
        """

        def rate(value: float | None, unit: str) -> str:
            return f"{value:.1f} {unit}" if value is not None else "—"

        def block(title: str, m: Measurement) -> list[str]:
            ttft = f"{m.ttft_ms:.0f} ms" if m.ttft_ms is not None else "—"
            return [
                f"<b>{title}</b>",
                f"Time to first token: {ttft}",
                f"Total: {m.total_ms:.0f} ms",
                f"Prefill: {rate(m.prefill_tokens_per_s, 'tok/s')}",
                f"Decode: {rate(m.decode_tokens_per_s, 'tok/s')}",
                f"Tokens: {m.input_tokens or '—'} in / {m.output_tokens or '—'} out",
            ]

        lines = [
            *block("Run 1 — engine state unknown (may include model load)", first),
            "",
            *block("Run 2 — warm by construction (ran immediately after run 1)", second),
            "",
        ]
        if first.ttft_ms is not None and second.ttft_ms is not None:
            delta = first.ttft_ms - second.ttft_ms
            if delta > max(500.0, second.ttft_ms):
                lines.append(
                    f"<b>Warm-up visible:</b> run 1 spent ~{delta:,.0f} ms more before its "
                    "first token — the cost of whatever loading run 2 no longer had to do."
                )
            else:
                lines.append(
                    "<b>No warm-up visible:</b> both runs started in similar time, so the "
                    "engine was already warm when run 1 arrived."
                )
        self._show(lines)

    def _show(self, lines: Sequence[str]) -> None:
        """Replace the output with ``lines``, remembering them so more can be added.

        The blocks are kept here rather than read back out of the widget: ``toHtml()``
        returns a whole HTML *document*, so concatenating onto it puts the new markup
        after ``</html>`` where it never renders.
        """
        self._blocks = list(lines)
        self._output.setHtml("<br>".join(self._blocks))

    def _append(self, lines: Sequence[str]) -> None:
        """Add to the output without discarding what is already there."""
        self._blocks.extend(lines)
        self._output.setHtml("<br>".join(self._blocks))

    def _on_task_failed(self, key: str, message: str, error: object) -> None:
        """Report a failed call with the library's hint, which is the actionable part."""
        if key not in _TASK_KEYS:
            return
        hint = getattr(error, "hint", "")
        lines = ["<b>Failed</b>", message]
        if hint:
            lines.append(f"<i>Hint: {hint}</i>")
        self._show(lines)
