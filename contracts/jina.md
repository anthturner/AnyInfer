# jina — Protocol Contract

Status: **implemented** — Python and native C# text embeddings and reranking.

Last verified: 2026-10-22 — documentation and machine-readable schema.
Hosted traffic is **not yet live-verified**.

## Upstream sources

- https://api.jina.ai/openapi.json — OpenAPI 3.1 version `2026.10.13.1624`, fetched
  2026-10-22. Model-specific requests, responses, errors and model listing.
- https://jina.ai/embeddings/ — request/auth examples, task/model and batching guidance;
  fetched 2026-10-22.
- https://jina.ai/reranker/ — request examples, top_n and model guidance; fetched 2026-10-22.
- https://jina.ai/en-US/news/jina-embeddings-v5-text-distilling-4b-quality-into-sub-1b-multilingual-embeddings/
- https://jina.ai/en-US/news/jina-embeddings-v5-omni-multimodal-embeddings-for-text-image-audio-and-video/
  — existing v5 static capability evidence (verified 2026-10-15).

## Wire contract

### Endpoints

POST `https://api.jina.ai/v1/embeddings` and POST `https://api.jina.ai/v1/rerank`.

### Auth

`Authorization: Bearer <api_key>`; convention `env://JINA_API_KEY`.

### Version pins

Version is in the /v1 path; no API-version header/query is sent.

Upstream now documents unauthenticated GET `/v1/models`. The current supported SDK
subset keeps manual model selection and empty discovery without HTTP: a library
limitation, not an assertion that upstream has no listing endpoint. Health GET `/models`
is any-status reachability only, not authentication or model-readiness verification.

### Request fields

#### Embeddings

- Send model and array-of-string input; optional task and dimensions. Per-operation
  provider options overlay last. No default normalized/format/truncate flags invented.
- Query maps to retrieval.query, document to retrieval.passage, classification verbatim.
  Clustering maps to **clustering** for the exact four known v5 IDs below and to
  **separation** otherwise (including v3); exact v4 omits unsupported classification/clustering tasks. OpenAPI's model-specific EmbeddingsV5Request
  enum differs from v3. V4 accepts retrieval.query/retrieval.passage and other
  upstream text/code tasks, but no classification/separation/clustering; its normalized
  capability intents are therefore only query/document. The product FAQ still gives generic separation guidance;
  the model-specific enum governs this literal wire choice. Unknown future model IDs
  retain the existing separation mapping; no claim of support for future vocabularies.
- Dense-float subset: object data array, each entry integer positional index and embedding
  array. Require exact input count, unique in-range integer nonbool indexes; restore input
  order. Public core validates nonempty/finite/consistent vectors. Optional string model
  preserved, dimensions observed from vectors, normalization unknown. Complete raw retained
  when opted in. Quantized/base64/sparse/multivector/multimodal outputs are not normalized.
- OpenAPI EmbeddingUsage documents total_tokens and prompt_tokens plus optional modality
  counters. Existing normalized text-only SDK subset consumes integer nonbool total_tokens
  ONLY; input_tokens/output_tokens remain unknown. Other fields remain raw, without a
  fabricated token breakdown.

#### Reranking

- Send model/query/documents (text strings), optional top_n. No top_k; no default
  return_documents sent. Defaults differ across model-specific schemas; options may set it.
- Parse results array: integer nonbool positional index and numeric nonbool relevance_score.
  Map to original caller indexes/IDs, preserving returned order and cardinality. No local
  sorting/TopN truncation. Optional model; total_tokens-only usage; raw retained.
- Cross-batch score comparability undocumented; refuse-by-default remains.

### Response fields

The embedding data/index/embedding fields and rerank results/index/relevance_score
fields above are the consumed response subset. Model is optional, usage is total-only,
and unknown facts remain unknown.

### Streaming

Neither embedding nor rerank produces incremental SDK results; responses are buffered.

### Errors, limits and lifetime

- OpenAPI ErrorResponse: required detail, optional code/request_id/errors; error entries
  contain field/message/type. Shared HTTP status classification and bounded/redacted
  detail extraction apply; code strings do not invent new normalized categories.
- Documented statuses include 400/401/403/404/409/422/429/500/503/504. Product and OpenAPI
  RPM/TPM tables conflict; no rate/price estimates enter capability metadata.
- Numeric finite nonnegative Retry-After seconds (including fractions) are consumed by
  shared HTTP behavior; upstream emission remains unverified.
- No hard count ceiling published; input/document metadata stays unknown and the core
  sanity ceiling applies. Successful response bytes bounded before parsing; error statuses
  retain classification with bounded diagnostic bodies. Responses are buffered.
- Native cancellation evidence concerns client transport cleanup; no upstream computation
  cancellation claim. Primary status/JSON/shape failures survive owned cleanup failures.

### Existing static capability subset

- jina-embeddings-v3: four intents; v4: query/document only. Old dimensions/token limits
  remain unknown in metadata.
- jina-embeddings-v5-text-small and jina-embeddings-v5-omni-small: dimensions 1,024,
  choices 32/64/128/256/512/1024, input 32,768 tokens.
- jina-embeddings-v5-text-nano and jina-embeddings-v5-omni-nano: dimensions 768,
  choices 32/64/128/256/512/768, input 8,192 tokens.
- jina-reranker-v3, jina-reranker-v3.5, jina-reranker-m0 and
  jina-reranker-v2-base-multilingual: native top_n, unknown per-document/count limits.
  v3.5's shared context window is not a per-document limit.

Omni IDs are included only for their text-compatible operation. This subset does not
expand Python's existing model inventory.

## Watchlist

- **Not yet live-verified:** first hosted lane must confirm response/error/usage and v5 task
  behavior. No credentials or hosted spending used for documentation evidence.
- Documented model discovery remains unimplemented in this bounded SDK subset.
- Prompt/modality usage, multimodal inputs, sparse/quantized/multivector outputs and batch
  endpoints remain outside normalized text retrieval.
- Resolve generic-task versus model-schema and RPM/TPM source conflicts explicitly.
