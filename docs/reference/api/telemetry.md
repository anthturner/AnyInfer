# Telemetry and redaction

Typed in-process events, payload-free by default, plus the redaction registry that keeps
secrets out of everything. Concepts: [telemetry](../../concepts/telemetry.md) ·
[credentials and redaction](../../concepts/credentials.md).

## Observing

<div class="anyinfer-api-block" markdown>

::: anyinfer.Observer

::: anyinfer.TelemetryEvent

</div>

## Request lifecycle events

<div class="anyinfer-api-block" markdown>

::: anyinfer.RequestStarted

::: anyinfer.TargetResolved

::: anyinfer.AttemptStarted

::: anyinfer.FirstToken

::: anyinfer.AttemptCompleted

::: anyinfer.RetryScheduled

::: anyinfer.FallbackTriggered

::: anyinfer.RepairAttempted

::: anyinfer.ParameterDropped

::: anyinfer.ProviderDiagnostic

::: anyinfer.ContextReduced

::: anyinfer.ArenaCompleted

::: anyinfer.CachePlanned

::: anyinfer.RateLimitWaited

::: anyinfer.RateLimitObserved

::: anyinfer.UsageEstimated

::: anyinfer.RequestCompleted

::: anyinfer.RequestFailed

</div>

## Local subsystem events

<div class="anyinfer-api-block" markdown>

::: anyinfer.DownloadProgress

::: anyinfer.ServerLifecycle

</div>

## Redaction

<div class="anyinfer-api-block" markdown>

::: anyinfer.RedactionRegistry

::: anyinfer.register_secret

::: anyinfer.redact

</div>

## OpenTelemetry export

The optional `[otel]` extra maps these events onto OpenTelemetry spans and metrics.
Guide: [observability](../../guides/observability.md).

<div class="anyinfer-api-block" markdown>

::: anyinfer.otel.install

::: anyinfer.otel.OTelObserver

::: anyinfer.otel.GEN_AI

</div>
