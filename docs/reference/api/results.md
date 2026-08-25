# Results and Stream Events

The output side: the final `Generation`, its usage and timing, and the typed events a
stream yields on the way there. Ordering guarantees are documented in
[the event stream](../../concepts/events.md).

## The Final Result

<div class="anyinfer-api-block" markdown>

::: anyinfer.Generation

::: anyinfer.Usage

::: anyinfer.Timing

::: anyinfer.TokenLogprob

::: anyinfer.AttemptRecord

::: anyinfer.Outcome

::: anyinfer.ErrorInfo

::: anyinfer.Diagnostic

::: anyinfer.DiagnosticSeverity

::: anyinfer.FinishReason

::: anyinfer.ArenaResult

::: anyinfer.Candidate

::: anyinfer.TargetComparison

::: anyinfer.EmbeddingTargetComparison

::: anyinfer.RunManifest

::: anyinfer.ContextSummary

</div>

## Run Manifest Facets

<div class="anyinfer-api-block" markdown>

::: anyinfer.MANIFEST_FORMAT

::: anyinfer.RequestFacet

::: anyinfer.RouteFacet

::: anyinfer.RouteStep

::: anyinfer.CapabilityFacet

::: anyinfer.SourcedFact

::: anyinfer.AttemptFacet

::: anyinfer.SchemaFacet

::: anyinfer.MechanismRung

::: anyinfer.CacheFacet

::: anyinfer.ContextFacet

::: anyinfer.ReductionRecord

::: anyinfer.RepairRecord

::: anyinfer.DroppedParameter

::: anyinfer.UsageFacet

::: anyinfer.TimingFacet

::: anyinfer.PayloadFacet

::: anyinfer.manifest_json_schema

::: anyinfer.context.ContextSummary

</div>

## Stream Events

<div class="anyinfer-api-block" markdown>

::: anyinfer.StreamEvent

::: anyinfer.TextDelta

::: anyinfer.ReasoningDelta

::: anyinfer.ToolCall

::: anyinfer.ToolCallDelta

::: anyinfer.UsageUpdate

::: anyinfer.TimingMark

::: anyinfer.TimingMarkName

::: anyinfer.AttemptFailed

::: anyinfer.StreamEnded

</div>
