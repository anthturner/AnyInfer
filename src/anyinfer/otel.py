"""Optional OpenTelemetry bridge for AnyInfer telemetry events.

A *bridge*, not the telemetry contract. The contract is typed in-process events
(`anyinfer.events`); this module is one optional consumer of them, and nothing here is
imported unless an application explicitly enables it.

That layering matters: it keeps ``opentelemetry-api`` out of the mandatory dependency set
keeps the core dependency set small and lets applications consume telemetry without
through spans, and means a zero-telemetry deployment pays nothing at all.

Attribute names follow the OpenTelemetry GenAI semantic conventions so traces are readable
by standard tooling.
"""

from __future__ import annotations

from typing import Any

from .events.telemetry import (
    AttemptCompleted,
    AttemptStarted,
    ContextReduced,
    DownloadProgress,
    FallbackTriggered,
    FirstToken,
    ParameterDropped,
    ProviderDiagnostic,
    RepairAttempted,
    RequestCompleted,
    RequestFailed,
    RequestStarted,
    RetryScheduled,
    ServerLifecycle,
    TargetResolved,
    TelemetryEvent,
    UsageEstimated,
)

__all__ = ["GEN_AI", "OTelObserver", "install"]

GEN_AI = "gen_ai"
"""Prefix of the GenAI semantic-convention attribute namespace."""

_INSTRUMENTATION_NAME = "anyinfer"


class OTelObserver:
    """Maps AnyInfer telemetry events onto OpenTelemetry spans and metrics.

    One span per request, with attempts as span events. Requests and attempts are
    correlated by ``request_id``, so a fallback chain reads as a single trace rather than
    several disconnected ones.

    Args:
        tracer: An OpenTelemetry tracer. Defaults to one from the global provider.
        meter: An OpenTelemetry meter. Defaults to one from the global provider.
        record_payloads: Attach prompt and response text to spans. Off by default, matching
            the payload-free default of the event contract itself. Subscribe with
            ``payloads=True`` as well for this to have any effect.

    Raises:
        ConfigError: If ``opentelemetry-api`` is not installed.
    """

    def __init__(
        self,
        *,
        tracer: Any = None,
        meter: Any = None,
        record_payloads: bool = False,
    ) -> None:
        trace, metrics = _import_otel()
        self._tracer = tracer or trace.get_tracer(_INSTRUMENTATION_NAME)
        self._record_payloads = record_payloads
        self._spans: dict[str, Any] = {}

        active_meter = meter or metrics.get_meter(_INSTRUMENTATION_NAME)
        self._token_counter = active_meter.create_counter(
            f"{GEN_AI}.client.token.usage",
            unit="token",
            description="Tokens consumed by generation requests.",
        )
        self._duration = active_meter.create_histogram(
            f"{GEN_AI}.client.operation.duration",
            unit="s",
            description="End-to-end duration of generation requests.",
        )
        self._ttft = active_meter.create_histogram(
            f"{GEN_AI}.server.time_to_first_token",
            unit="s",
            description="Time to first token.",
        )

    def on_event(self, event: TelemetryEvent) -> None:
        """Handle one telemetry event.

        Never raises: the dispatcher isolates observer failures, but a telemetry bridge
        that can break a generation would be a poor trade regardless.
        """
        handler = getattr(self, f"_on_{type(event).__name__}", None)
        if handler is not None:
            handler(event)

    # ---- request lifecycle -----------------------------------------------------------

    def _on_RequestStarted(self, event: RequestStarted) -> None:  # noqa: N802
        span = self._tracer.start_span(
            "generate",
            attributes={
                f"{GEN_AI}.operation.name": "chat",
                f"{GEN_AI}.anyinfer.request_id": event.request_id,
                f"{GEN_AI}.anyinfer.targets": ", ".join(event.targets),
            },
        )
        if self._record_payloads and event.prompt_text:
            span.set_attribute(f"{GEN_AI}.prompt", event.prompt_text)
        self._spans[event.request_id] = span

    def _on_TargetResolved(self, event: TargetResolved) -> None:  # noqa: N802
        span = self._spans.get(event.request_id)
        if span is not None:
            span.add_event(
                "target.resolved",
                attributes={
                    f"{GEN_AI}.system": event.target.provider_id,
                    f"{GEN_AI}.request.model": event.target.model,
                },
            )

    def _on_AttemptStarted(self, event: AttemptStarted) -> None:  # noqa: N802
        span = self._spans.get(event.request_id)
        if span is None:
            return
        span.add_event(
            "attempt.started",
            attributes={
                f"{GEN_AI}.system": event.target.provider_id,
                f"{GEN_AI}.request.model": event.target.model,
                f"{GEN_AI}.anyinfer.attempt": event.attempt_number,
            },
        )

    def _on_FirstToken(self, event: FirstToken) -> None:  # noqa: N802
        span = self._spans.get(event.request_id)
        if span is not None:
            span.add_event("first_token", attributes={f"{GEN_AI}.anyinfer.at_ms": event.at_ms})
        self._ttft.record(
            event.at_ms / 1000.0,
            {f"{GEN_AI}.system": event.target.provider_id,
             f"{GEN_AI}.request.model": event.target.model},
        )

    def _on_AttemptCompleted(self, event: AttemptCompleted) -> None:  # noqa: N802
        labels = {
            f"{GEN_AI}.system": event.target.provider_id,
            f"{GEN_AI}.request.model": event.target.model,
        }
        if event.usage.input_tokens is not None:
            self._token_counter.add(
                event.usage.input_tokens, {**labels, f"{GEN_AI}.token.type": "input"}
            )
        if event.usage.output_tokens is not None:
            self._token_counter.add(
                event.usage.output_tokens, {**labels, f"{GEN_AI}.token.type": "output"}
            )

        span = self._spans.get(event.request_id)
        if span is None:
            return
        span.set_attribute(f"{GEN_AI}.response.finish_reasons", [event.finish_reason])
        span.set_attribute(f"{GEN_AI}.system", event.target.provider_id)
        span.set_attribute(f"{GEN_AI}.response.model", event.target.model)
        if event.usage.input_tokens is not None:
            span.set_attribute(f"{GEN_AI}.usage.input_tokens", event.usage.input_tokens)
        if event.usage.output_tokens is not None:
            span.set_attribute(f"{GEN_AI}.usage.output_tokens", event.usage.output_tokens)
        if event.usage.cost_usd is not None:
            span.set_attribute(f"{GEN_AI}.anyinfer.cost_usd", float(event.usage.cost_usd))

    def _on_RetryScheduled(self, event: RetryScheduled) -> None:  # noqa: N802
        span = self._spans.get(event.request_id)
        if span is not None:
            span.add_event(
                "retry.scheduled",
                attributes={
                    f"{GEN_AI}.anyinfer.delay_s": event.delay_s,
                    f"{GEN_AI}.anyinfer.error_type": event.error.type_name,
                },
            )

    def _on_FallbackTriggered(self, event: FallbackTriggered) -> None:  # noqa: N802
        span = self._spans.get(event.request_id)
        if span is not None:
            attributes = {
                f"{GEN_AI}.anyinfer.from_target": (
                    f"{event.from_target.provider_id}:{event.from_target.model}"
                ),
                f"{GEN_AI}.anyinfer.to_target": event.to_target,
            }
            if event.error is not None:
                attributes[f"{GEN_AI}.anyinfer.error_type"] = event.error.type_name
            span.add_event("fallback.triggered", attributes=attributes)

    def _on_RepairAttempted(self, event: RepairAttempted) -> None:  # noqa: N802
        span = self._spans.get(event.request_id)
        if span is not None:
            span.add_event(
                "schema.repair",
                attributes={
                    f"{GEN_AI}.anyinfer.attempt": event.attempt_number,
                    f"{GEN_AI}.anyinfer.mechanism": event.mechanism or "unknown",
                },
            )

    def _on_ParameterDropped(self, event: ParameterDropped) -> None:  # noqa: N802
        span = self._spans.get(event.request_id)
        if span is not None:
            span.add_event(
                "parameter.dropped",
                attributes={
                    f"{GEN_AI}.anyinfer.parameter": event.parameter,
                    f"{GEN_AI}.anyinfer.reason": event.reason,
                },
            )

    def _on_ProviderDiagnostic(self, event: ProviderDiagnostic) -> None:  # noqa: N802
        # Straddles both halves of this bridge: collected during a request it belongs on
        # that span, and collected directly it has no owning request at all.
        attributes = {
            f"{GEN_AI}.anyinfer.code": event.diagnostic.code,
            f"{GEN_AI}.anyinfer.severity": event.diagnostic.severity,
            f"{GEN_AI}.anyinfer.message": event.diagnostic.message,
        }
        span = self._spans.get(event.request_id) if event.request_id else None
        if span is not None:
            span.add_event("provider.diagnostic", attributes=attributes)
            return
        if event.target is not None:
            attributes[f"{GEN_AI}.system"] = event.target.provider_id
            attributes[f"{GEN_AI}.request.model"] = event.target.model
        self._standalone("provider.diagnostic", attributes).end()

    def _on_UsageEstimated(self, event: UsageEstimated) -> None:  # noqa: N802
        span = self._spans.get(event.request_id)
        if span is not None:
            span.add_event(
                "usage.estimated",
                attributes={
                    f"{GEN_AI}.anyinfer.field": event.field_name,
                    f"{GEN_AI}.anyinfer.method": event.method,
                },
            )

    def _on_RequestCompleted(self, event: RequestCompleted) -> None:  # noqa: N802
        span = self._spans.pop(event.request_id, None)
        self._duration.record(
            event.timing.total_ms / 1000.0,
            {
                f"{GEN_AI}.system": event.target.provider_id,
                f"{GEN_AI}.request.model": event.target.model,
            },
        )
        if span is None:
            return
        if self._record_payloads and event.response_text:
            span.set_attribute(f"{GEN_AI}.completion", event.response_text)
        span.set_attribute(f"{GEN_AI}.anyinfer.repair_attempts", event.repair_attempts)
        span.end()

    def _on_RequestFailed(self, event: RequestFailed) -> None:  # noqa: N802
        span = self._spans.pop(event.request_id, None)
        if span is None:
            return
        trace, _ = _import_otel()
        span.set_status(trace.Status(trace.StatusCode.ERROR, event.error.detail))
        span.set_attribute("error.type", event.error.type_name)
        span.end()

    # ---- events outside a request scope -----------------------------------------------
    #
    # Context reduction, server supervision, and artifact downloads carry no `request_id`,
    # so there is no in-flight span to attach them to. Each becomes a standalone zero-
    # duration span: dropping them would make the bridge lossy, and inventing a parent
    # would misattribute work that genuinely happens outside any one request.

    def _on_ContextReduced(self, event: ContextReduced) -> None:  # noqa: N802
        self._standalone(
            "context.reduced",
            {
                f"{GEN_AI}.anyinfer.strategy": event.strategy,
                f"{GEN_AI}.anyinfer.representation": event.representation,
                f"{GEN_AI}.anyinfer.candidate_count": event.candidate_count,
                f"{GEN_AI}.anyinfer.selected_count": event.selected_count,
                f"{GEN_AI}.anyinfer.omitted_count": event.omitted_count,
                f"{GEN_AI}.anyinfer.estimated_tokens": event.estimated_tokens,
                f"{GEN_AI}.anyinfer.max_tokens": event.max_tokens,
                f"{GEN_AI}.anyinfer.binding_constraints": list(event.binding_constraints),
                f"{GEN_AI}.anyinfer.calls": event.calls,
            },
        ).end()

    def _on_ServerLifecycle(self, event: ServerLifecycle) -> None:  # noqa: N802
        attributes = {
            f"{GEN_AI}.anyinfer.server_id": event.server_id,
            f"{GEN_AI}.anyinfer.state": event.state,
        }
        if event.detail:
            attributes[f"{GEN_AI}.anyinfer.detail"] = event.detail
        span = self._standalone("server.lifecycle", attributes)
        if event.state == "crashed":
            trace, _ = _import_otel()
            span.set_status(trace.Status(trace.StatusCode.ERROR, event.detail))
        span.end()

    def _on_DownloadProgress(self, event: DownloadProgress) -> None:  # noqa: N802
        # Only the terminal event becomes a span; per-chunk progress would flood the
        # exporter with spans that say nothing a completion span does not.
        if not event.done:
            return
        attributes = {
            f"{GEN_AI}.anyinfer.artifact_id": event.artifact_id,
            f"{GEN_AI}.anyinfer.downloaded_bytes": event.downloaded_bytes,
        }
        if event.total_bytes is not None:
            attributes[f"{GEN_AI}.anyinfer.total_bytes"] = event.total_bytes
        self._standalone("download.completed", attributes).end()

    def _standalone(self, name: str, attributes: dict[str, Any]) -> Any:
        """Start a self-contained span for an event with no owning request.

        The caller ends it, so a status can be set first.
        """
        return self._tracer.start_span(name, attributes=attributes)


def install(client: Any, *, record_payloads: bool = False) -> OTelObserver:
    """Attach an `OTelObserver` to a client.

    Args:
        client: An `AsyncClient` or `Client`.
        record_payloads: Attach prompt and response text to spans.

    Returns:
        The observer, so it can be detached later.
    """
    observer = OTelObserver(record_payloads=record_payloads)
    client.subscribe(observer, payloads=record_payloads)
    return observer


def _import_otel() -> tuple[Any, Any]:
    """Import the OTel API, or explain how to install it."""
    try:
        from opentelemetry import metrics, trace
    except ImportError as exc:
        from .errors import ConfigError

        raise ConfigError(
            "the OpenTelemetry bridge requires the otel extra",
            hint="pip install 'anyinfer[otel]'",
        ) from exc
    return trace, metrics
