# Clients and Streams

The two entry points, `Client` (sync) and `AsyncClient` (async), expose the same
surface; the sync client is a facade over the async core (see the
[architecture overview](../../contributing/architecture.md)).

<div class="anyinfer-api-block" markdown>

::: anyinfer.Client

::: anyinfer.AsyncClient

::: anyinfer.SyncStream

::: anyinfer.AsyncStream

::: anyinfer.MessagesInput

::: anyinfer.ProviderSettings

::: anyinfer.Session

::: anyinfer.SessionReuse

::: anyinfer.Verification

::: anyinfer.Measurement

::: anyinfer.MeasurementIdentity

::: anyinfer.MeasurementStore

::: anyinfer.BenchmarkSample

::: anyinfer.BENCHMARK_PROMPT_TOKENS

::: anyinfer.BENCHMARK_OUTPUT_TOKENS

::: anyinfer.tool

::: anyinfer.Tool

</div>

## Deferred Batches

<div class="anyinfer-api-block" markdown>

::: anyinfer.BatchGenerationRequest

::: anyinfer.BatchHandle

::: anyinfer.BatchReport

::: anyinfer.BatchResult

::: anyinfer.BatchLine

::: anyinfer.BatchStatus

</div>
