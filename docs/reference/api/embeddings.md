# Embeddings and reranking

Two stateless inference operations alongside generation: turning text into vectors, and
ranking documents against a query. Both are typed and routed the same way generation is —
target resolution, retries, fallback, usage, and telemetry — but neither is a field on
`GenerationRequest`. See [the embeddings concept page](../../concepts/embeddings.md) for the
embedding-space safety rule that governs fallback.

## Embedding

<div class="anyinfer-api-block" markdown>

::: anyinfer.EmbeddingRequest

::: anyinfer.EmbeddingResult

::: anyinfer.EmbeddingVector

::: anyinfer.EmbeddingSpace

::: anyinfer.EmbeddingCapabilities

::: anyinfer.EmbeddingInputIntent

</div>

## Reranking

<div class="anyinfer-api-block" markdown>

::: anyinfer.RerankRequest

::: anyinfer.RerankResult

::: anyinfer.RerankDocument

::: anyinfer.RankedItem

::: anyinfer.RerankCapabilities

</div>

## Shared

<div class="anyinfer-api-block" markdown>

::: anyinfer.InferenceOperation

::: anyinfer.BatchPolicy

</div>
