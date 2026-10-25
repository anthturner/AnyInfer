# Search a Corpus with Embeddings and Reranking

A help-center search in native C#. It embeds a small corpus of passages that carry the
application's own IDs, keeps the vectors in an in-memory index together with the embedding space
they belong to, shortlists passages for a query by cosine similarity, and asks a reranker to
order the shortlist. The same program runs against local Text Embeddings Inference servers or the
hosted Voyage AI and Jina AI APIs; only the provider settings and targets change.

The SDK owns batching, ordering, embedding-space checks, and the provider wire formats. The
application owns its index and the similarity math, which is a few lines for a corpus that fits in
memory.

## Before You Start

- The .NET 8 SDK and a reference to the local C# prerelease, as described in
  [Install the C# SDK](../guides/csharp-installation.md), and the first call from the
  [C# quickstart](../guides/csharp-quickstart.md). The C# SDK is a locally packaged
  `0.1.0-proof` prerelease, not a NuGet package.
- Nothing else to run it offline. For real retrieval, one of the deployments in
  [Hosted and local setup](#hosted-and-local-setup-optional).

## The Program

```csharp
--8<-- "examples/csharp-sdk/CookbookRetrievalExample.cs"
```

## How It Works

- **Three deployments, one program.** `Tei`, `Voyage`, and `Jina` are `ProviderSettings` plus an
  embedding target and a rerank target. TEI serves one model per server process, so it uses two
  instances, `tei-embed` and `tei-rerank`; Voyage and Jina serve both operations from one instance
  whose key stays an `env://` reference.
- **Document IDs stay yours.** Embedding returns one vector per input, in input order, even when
  the request was split into batches or the provider returned items out of order; the program
  pairs vectors with passages by position. Reranking takes `RerankDocument` values whose IDs come
  back on each `RankedItem`, so scores map to passages without index bookkeeping.
- **The batch ceiling is a fact you supply.** The TEI descriptor does not learn a server's batch
  limit, so without a ceiling the SDK sends the input in one request (up to 2,048 inputs) rather
  than guessing. A `BatchPolicy` with `maxItemsOverride` states a ceiling you have verified for
  your deployment; the SDK then splits the corpus, runs up to `maxConcurrency` batches at once,
  and fails the whole call if any batch fails. The program sets no batch policy on reranking; by default the SDK does not
  split a rerank request, because scores from separate requests may not share a scale.
- **Vectors are comparable only within a space.** Each `EmbeddingResult` reports its
  `EmbeddingSpace`: provider instance, model, revision when known, and dimensions. The index keeps
  the space of its vectors, and the query embedding passes it as `expectedSpace`. If the embedding
  target has changed since the index was built, the SDK raises `ConfigException` after the query
  embedding returns and before any vector math or reranking. `CompatibleWith` compares instance,
  model, and revision, or a caller-asserted `CompatibilityId`.
- **Input intent follows the provider.** The program marks passages as documents and the query as
  a query. Voyage sends that as `input_type`, Jina as its `task`; a TEI request carries no intent
  field.
- **Usage is what the provider reported.** TEI reports no token counts, so usage stays unknown;
  Voyage and Jina report a total only.

## Offline Run

The example runner answers TEI-, Voyage-, and Jina-shaped requests from a deterministic offline
server whose vectors count a few vocabulary concepts, so the expected ranking is exact. The cases
are in [`Cases/CookbookRetrievalCases.cs`](../../examples/csharp-sdk/Cases/CookbookRetrievalCases.cs); from `src/csharp`, run:

```bash
dotnet run --project ../../examples/csharp-sdk/AnyInfer.Examples.csproj --configuration Release
```

The runner executes every example case, not only this page's, and prints
`example case <name>: ok` for each one that passes.

The `cookbook.retrieval.*` cases check that:

- with a ceiling of two, TEI indexing of five passages takes three requests (two, two, and one
  input), every indexed vector belongs to its passage's ID, the three-passage shortlist reaches
  the reranker in corpus order, and the top two results are `kb-late` and `kb-refunds` with their
  reranker scores;
- usage the TEI server did not report stays unknown, and no warnings are raised;
- Voyage and Jina produce the same ranking from reversed, indexed responses; their requests carry
  the offline key from the `env://` reference, the native intent spellings, and native top-N, and
  their reported totals are summed across batches;
- a query embedded with a different model than the stored index is refused with
  `ConfigException`, and the reranker receives no request;
- every transport is disposed once.

## Hosted and Local Setup (Optional)

- **TEI:** start one TEI server per model, here an embedding model on port 8080 and a reranker on
  port 8081, and use model IDs that match what each server loaded. Buffered C# embedding and
  reranking were exercised against a TEI 1.9.4 CPU deployment on 2026-10-22.
- **Voyage AI or Jina AI:** export `VOYAGE_API_KEY` or `JINA_API_KEY` and pass the `Voyage` or
  `Jina` deployment. These hosted adapters are verified offline against scripted responses only.

## Before Production

- Persist the index together with its `EmbeddingSpace`, and rebuild it when the space changes.
- Set the program's `maxBatchInputs` (which becomes the `BatchPolicy` `maxItemsOverride`) from
  your deployment's documented or tested limit, and choose `maxConcurrency` for the provider's
  rate limits.
- Replace the linear scan with a vector store once the corpus no longer fits comfortably in
  memory; keep the space check and the caller-owned IDs.
- Ask for more shortlist candidates than results, so the reranker has something to reorder.

## See Also

<div class="anyinfer-see-also" markdown>

- [Embeddings and reranking](../concepts/embeddings.md): spaces, intent, and batching.
- [Retrieval providers](../providers/retrieval.md) and [TEI](../providers/tei.md).
- [C# SDK guide](../guides/csharp-sdk.md#embed-and-rerank-text) for the single-call examples.
- API: [`EmbeddingResult`](/csharp/api/anyinfer.embeddingresult/),
  [`EmbeddingSpace`](/csharp/api/anyinfer.embeddingspace/),
  [`EmbeddingVector`](/csharp/api/anyinfer.embeddingvector/),
  [`BatchPolicy`](/csharp/api/anyinfer.batchpolicy/),
  [`RerankDocument`](/csharp/api/anyinfer.rerankdocument/),
  [`RerankResult`](/csharp/api/anyinfer.rerankresult/),
  [`RankedItem`](/csharp/api/anyinfer.rankeditem/),
  [`EmbeddingInputIntent`](/csharp/api/anyinfer.capabilities.embeddinginputintent/).
- The Python version of this pattern: [Semantic search over a small corpus](semantic-search.md).

</div>
