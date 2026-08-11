# Embedding and reranking support

> **Status:** proposed; implementation has not started.
> **Plan date:** 2026-08-11.
> **Authority:** this is a living implementation plan, not an architecture decision.
> `DESIGN.md` remains authoritative until this plan's governance tasks amend it.
> **Product premise supplied by the owner:** AnyInfer is a batteries-included universal AI
> interaction engine intended to meet as many application inference needs as practical.

## Status legend

| Marker | Meaning |
|---|---|
| [ ] | Not started |
| [~] | In progress |
| [x] | Complete and verified |
| [?] | Waiting on a product or architecture decision |
| [-] | Deliberately excluded, with the reason recorded |

## 1. Outcome

Add two first-class, provider-neutral inference operations alongside generation:

```text
EmbeddingRequest -> EmbeddingResult
RerankRequest    -> RerankResult
```

They must receive the same batteries AnyInfer already supplies around generation:

- typed async APIs and a thread-safe sync facade;
- target resolution, provider instances, aliases, credentials, redaction, and config;
- deterministic retries, health gating, safe fallback, rate pacing, and attempt trails;
- capability provenance, model discovery, pricing, usage, spend policy, telemetry, and
  run manifests;
- fake, cassette, and opt-in live conformance modes;
- direct Python SDK, CLI, sidecar, generated reference, executable examples, and demo-app
  coverage;
- hosted, externally managed local, and application-supervised local implementations where
  the protocol and lifecycle justify each.

The result is an inference layer, not a vector database or a RAG framework. AnyInfer will
produce vectors and relevance rankings. It will not silently decide what an application
indexes, persists, retrieves, deletes, or sends to a model.

## 2. Governance change required before code

The current design explicitly excludes embeddings, the sidecar returns 404 for embedding
routes, and the context subsystem deliberately ships only a lexical ranker. This work is
therefore a proposed reversal, not an incremental provider feature.

- [ ] **ER.0.1** Amend the product goals to name stateless embedding and reranking inference
  as supported first-class operations.
- [ ] **ER.0.2** Replace the blanket “no embeddings” non-goal with the narrower boundary in
  section 3 below.
- [ ] **ER.0.3** Add an architecture decision establishing an operation-neutral provider
  lifecycle plus separately typed operation protocols. Do not make `GenerationRequest` a
  union of unrelated inference shapes.
- [ ] **ER.0.4** Amend the sidecar design: `/v1/embeddings` is a supported standard codec;
  reranking uses an AnyInfer-owned route until a wire dialect is deliberately adopted.
- [ ] **ER.0.5** Amend context reduction to permit caller-supplied semantic rankers while
  keeping indexing and corpus collection outside the context package.
- [ ] **ER.0.6** Add embedding-space mismatch and retrieval-scope risks to the design risk
  register.
- [ ] **ER.0.7** Remove or update every public “embeddings: no” claim in the docs only after
  its corresponding acceptance tests pass.

Governance text under `docs/`, the root README, public docstrings, and generated outward
instructions must state rules in plain language without internal decision identifiers.

## 3. Scope boundary

### Included

- Text embeddings, scalar and batch.
- Query/document input intent when the provider or model distinguishes them.
- Provider-supported dimensionality reduction.
- Reranking one query against a caller-supplied ordered document collection.
- Text plus caller-owned document ids and metadata; only text is sent unless a provider
  option explicitly requests more.
- Provider usage, provider-specific billing units, centrally computed cost when pricing is
  known, timing, target, attempt trail, warnings, and optional raw response retention.
- Core-owned batching when a request exceeds a verified provider batch limit.
- Operation-aware model discovery and capabilities.
- Operation-safe routing and fallback.
- Injection of an embedding-backed or reranking-backed ranker into context reduction.

### Explicitly excluded from this milestone

- Vector databases, approximate-nearest-neighbor indexes, and persistence.
- Corpus crawling, watchers, synchronization, deletion policy, or index invalidation.
- A hosted retrieval service or organization-wide control plane.
- Automatically embedding `ContextDocument` values merely because an embedding provider is
  configured.
- Automatic selection of an embedding or reranking model by an opaque quality score.
- Cross-model vector conversion or comparison.
- Training, fine-tuning, or evaluation of embedding/reranking models.
- Image, audio, and multimodal embeddings in the first milestone.
- Streaming vectors or incremental rerank results; both operations are buffered.

### Possible follow-on, requiring a separate decision

- A small application-owned local vector store.
- Multimodal embeddings.
- Hybrid lexical/vector fusion helpers.
- Index manifests and compatibility validation across a stored corpus.
- Supervision and acquisition of a dedicated embedding runtime such as TEI.

## 4. Core type design

Names below are targets, not final signatures. All public domain records remain frozen
dataclasses with `slots=True`.

### Operation and capability types

- [ ] **ER.1.1** Add an `InferenceOperation` enum or literal vocabulary with at least
  `generation`, `embedding`, and `rerank`.
- [ ] **ER.1.2** Keep generation features (`TOOLS`, `JSON_SCHEMA`, `REASONING`, etc.)
  distinct from supported operations. Do not treat “can embed” as a generation feature.
- [ ] **ER.1.3** Add operation support to `ModelCapabilities` with provenance.
- [ ] **ER.1.4** Add `EmbeddingCapabilities`, including only facts that can be sourced:
  dimensions or dimension choices, maximum batch inputs, maximum input tokens/bytes,
  accepted input intents, output encodings, and whether vectors are normalized.
- [ ] **ER.1.5** Add `RerankCapabilities`: maximum documents, maximum tokens/bytes per
  document, accepted document forms, and whether `top_n` is native.
- [ ] **ER.1.6** Define conjunction/overlay behavior for the new capability records,
  including delegating or `auto` targets.
- [ ] **ER.1.7** Make model discovery preserve embedding-only and rerank-only models rather
  than filtering them out as non-chat models.
- [ ] **ER.1.8** Extend `compare()` or add an operation-aware counterpart so callers can
  inspect fit, degradation, pricing, and provenance without dispatching.

### Embedding request and result

- [ ] **ER.1.9** Add `EmbeddingRequest` with:
  - non-empty `inputs: tuple[str, ...]`;
  - `input_type: query | document | classification | clustering | None`, with adapters
    accepting only supported values;
  - optional requested `dimensions`;
  - timeout, metadata, response byte limit, provider options, and batch policy;
  - optional expected embedding-space contract.
- [ ] **ER.1.10** Add `EmbeddingVector` or a documented immutable vector representation.
  Reject ragged data, booleans, NaN, infinity, and non-numeric values before returning it.
- [ ] **ER.1.11** Add `EmbeddingResult` with vectors in input order, resolved target,
  concrete model, dimensions, normalization fact, embedding-space identity, usage, timing,
  attempts, warnings, optional raw data, and optional manifest.
- [ ] **ER.1.12** Define zero-input behavior as a local validation error that performs no
  provider call.
- [ ] **ER.1.13** Preserve duplicate inputs and their positions exactly; deduplication is
  never implicit because it changes usage and may change provider-side behavior.

### Rerank request and result

- [ ] **ER.1.14** Add `RerankDocument(id, text, metadata)`; ids are caller-owned opaque
  strings, unique within one request, and metadata is retained locally by default.
- [ ] **ER.1.15** Add `RerankRequest` with a non-empty query, non-empty ordered documents,
  optional `top_n`, timeout, metadata, response byte limit, provider options, and batch
  policy.
- [ ] **ER.1.16** Add `RankedItem` containing the original index, caller document id,
  finite provider score, and optional returned document text only when requested.
- [ ] **ER.1.17** Add `RerankResult` with ordered ranked items, resolved target, model,
  usage, timing, attempts, warnings, optional raw data, and optional manifest.
- [ ] **ER.1.18** Validate that provider results contain unique, in-range indexes; never
  guess which document a malformed result meant.
- [ ] **ER.1.19** Document that scores are meaningful only within the result produced by
  that target and must not be compared across models/providers unless the caller owns a
  calibration.

### Usage and pricing

- [ ] **ER.1.20** Decide whether the current `Usage` becomes operation-neutral or whether
  operation-specific records share a small common protocol. Do not encode billed search
  units as fake output tokens.
- [ ] **ER.1.21** Represent provider-native billable units with stable names and exact
  numeric types; retain `cost_usd` as the normalized spend field.
- [ ] **ER.1.22** Add embedding pricing (normally input-token based) and reranking pricing
  (token, request, document, or search-unit based) without forcing every provider into one
  invented unit.
- [ ] **ER.1.23** Extend spend ledgers, ceilings, comparisons, manifests, and OTel export to
  include the new operations.
- [ ] **ER.1.24** Keep unknown usage or pricing unknown; never infer cost from a sibling
  provider or a similarly named model.

## 5. Provider architecture

### Lifecycle plus operation protocols

The existing `ProviderAdapter` requires generation from every provider. That cannot
represent a retrieval-only runtime cleanly. Refactor without losing the rule that optional
behavior is descriptor-declared rather than discovered through `hasattr`.

- [ ] **ER.2.1** Extract the common provider lifecycle:
  `list_models`, `health`, and `aclose`.
- [ ] **ER.2.2** Define separately typed operation protocols:
  `GeneratesText.generate`, `EmbedsText.embed`, and `ReranksText.rerank`.
- [ ] **ER.2.3** Add a descriptor-level set of supported operations and validate that the
  factory's object satisfies every declared protocol.
- [ ] **ER.2.4** Preserve one provider instance and connection pool when one adapter object
  supports several operations.
- [ ] **ER.2.5** Permit retrieval-only providers without dummy `generate()` methods.
- [ ] **ER.2.6** Add normalized wire request/result records for embedding and reranking;
  adapters translate only and never batch, retry, route, truncate, or compute cost.
- [ ] **ER.2.7** Update third-party entry-point discovery, scaffolding, certification, and
  collision handling for operation-specific adapters.
- [ ] **ER.2.8** Keep operation support generic in setup/config UIs; no per-engine branches.

### Shared OpenAI-compatible embedding dialect

- [ ] **ER.2.9** Add a shared `/v1/embeddings` implementation alongside, not inside, the
  chat-completions codec.
- [ ] **ER.2.10** Support verified request fields (`model`, scalar/batch `input`, dimensions,
  and encoding) and reject unsupported token-array forms until intentionally modeled.
- [ ] **ER.2.11** Decode float and base64 vectors where providers document them.
- [ ] **ER.2.12** Add operation flags and quirks to compatibility presets; a preset does not
  inherit embedding support merely because its chat endpoint is OpenAI-compatible.
- [ ] **ER.2.13** Record every compatible embedding endpoint and deviation in the preset
  contract snapshot with a real verification date.

## 6. Routing and embedding-space safety

### Required safety rule

Embedding vectors from different spaces are not interchangeable. A query embedded with a
fallback model will produce plausible numbers and silently fail against an index built with
the primary model. This is more dangerous than an ordinary provider error.

- [ ] **ER.3.1** Define `EmbeddingSpace` with the strongest identity AnyInfer can support:
  provider/model revision when pinned, effective dimensions, input intent behavior,
  normalization, and an optional caller-supplied compatibility id.
- [ ] **ER.3.2** Default embedding routes to retries on the same resolved target only.
- [ ] **ER.3.3** Permit cross-target fallback only when both targets have the same trusted
  compatibility id or the caller explicitly opts into an unsafe fallback.
- [ ] **ER.3.4** If equivalence is unknown, fail before sending the fallback request and
  provide an actionable hint.
- [ ] **ER.3.5** Include the concrete embedding space in results and manifests so an index
  builder can persist it and a query path can require it later.
- [ ] **ER.3.6** Add an `expected_space` request field that rejects a successful but
  incompatible provider response.
- [ ] **ER.3.7** Allow ordinary rerank fallback, but record the serving target and never
  merge or compare scores from separate attempts.

### General routing work

- [ ] **ER.3.8** Extract or generalize retry/health/fallback plumbing so all operations use
  one policy implementation while generation retains its context/content special chains.
- [ ] **ER.3.9** Reject a target that does not support the requested operation before
  dispatch when trusted capability data proves the absence.
- [ ] **ER.3.10** Unknown operation capability remains unknown; discovery/probing may
  resolve it, but the core must not invent support.
- [ ] **ER.3.11** Apply provider-instance rate limits and transport governance to every
  operation.
- [ ] **ER.3.12** Ensure cancellation closes in-flight HTTP work and does not return partial
  embedding batches or partial rankings as success.

## 7. Core-owned batching

Providers disagree on maximum inputs, documents, tokens, and bytes. Batching is policy and
therefore belongs in the core, not adapters.

- [ ] **ER.4.1** Add an explicit `BatchPolicy` with an automatic bounded default, maximum
  concurrency, and an option to refuse splitting.
- [ ] **ER.4.2** Split only from discovered/catalog/probed/override limits; when the limit
  is unknown, send one bounded request rather than guess a provider maximum.
- [ ] **ER.4.3** Preserve embedding vector order across concurrent batches.
- [ ] **ER.4.4** Define embedding batch failure as all-or-error. A failure may carry an
  attempt trail and completed-batch count, but no ordinary `EmbeddingResult` with missing
  vectors.
- [ ] **ER.4.5** Do not naively batch reranking and concatenate results: scores from
  separate document batches may not be globally comparable. Only batch reranking when the
  provider offers a documented globally comparable contract, or use an explicit
  approximation policy that announces degradation.
- [ ] **ER.4.6** Aggregate usage, cost, timing, warnings, and attempt records without
  understating failed-batch spend.
- [ ] **ER.4.7** Add operation-specific request/response byte limits; the generation
  default is too small for large float-vector batches.
- [ ] **ER.4.8** Bound vector count, dimensions, document count, per-document bytes, and
  total request bytes before allocation or dispatch.

## 8. Initial provider targets

Every provider entry below requires an upstream contract audit before implementation.
Protocol facts, supported fields, model limits, error shapes, and last-verified dates must
come from current primary sources or live traffic.

### Milestone A: prove every protocol axis

- [?] **ER.5.1** Implement the prospective integration's required provider first. Record
  its name and exact embedding/reranking requirements in the Decisions section.
- [ ] **ER.5.2** OpenAI embeddings: hosted OpenAI-compatible reference dialect, batching,
  dimensions, usage, float/base64 handling.
- [ ] **ER.5.3** Cohere embedding and reranking: native input intents plus native rerank
  scores and billed search units.
- [ ] **ER.5.4** Ollama embeddings: local native dialect, batch input, dimensions, token and
  phase timings, model pulling through the existing local-service hook.
- [ ] **ER.5.5** Hugging Face Text Embeddings Inference: externally managed local service,
  OpenAI-compatible embeddings plus native reranking; no runtime supervision in this
  milestone.

### Milestone B: extend existing dedicated adapters

- [ ] **ER.5.6** Azure AI Foundry / Azure OpenAI embedding deployments.
- [ ] **ER.5.7** Gemini embedding models.
- [ ] **ER.5.8** Vertex AI embedding models and task types.
- [ ] **ER.5.9** Bedrock embedding and reranking operations where the current public APIs
  fit the normalized contracts.
- [ ] **ER.5.10** LM Studio embedding models and discovery; stop filtering them out once
  the operation is supported.
- [ ] **ER.5.11** llama-server embeddings if the pinned runtime's actual endpoint and model
  requirements pass a live contract check. Keep acquisition in `local/`, not the adapter.

### Milestone C: specialist providers and compatibility inventory

- [ ] **ER.5.12** Audit Voyage AI as a specialist embedding/reranking provider.
- [ ] **ER.5.13** Audit Jina AI as a specialist embedding/reranking provider.
- [ ] **ER.5.14** Audit the 86 compatibility presets and mark only verified embedding
  surfaces; do not equate generation support with embedding support.
- [ ] **ER.5.15** Add named local presets for verified embedding/reranking servers such as
  TEI and operation-capable vLLM/SGLang deployments where a declarative preset is enough.
- [ ] **ER.5.16** Generate the public provider/operation inventory from descriptors so the
  documentation cannot overstate coverage.

## 9. Public SDK surfaces

- [ ] **ER.6.1** Add `AsyncClient.embed(...) -> EmbeddingResult`.
- [ ] **ER.6.2** Add `Client.embed(...) -> EmbeddingResult` through the existing background
  loop, with thread-stress and cancellation coverage.
- [ ] **ER.6.3** Add `AsyncClient.rerank(...) -> RerankResult`.
- [ ] **ER.6.4** Add `Client.rerank(...) -> RerankResult`.
- [ ] **ER.6.5** Accept a single target, a compatible ordered route, and named routes using
  the same target grammar as generation.
- [ ] **ER.6.6** Add operation-aware `models()`, `capabilities()`, `compare()`, `verify()`,
  and benchmark surfaces.
- [ ] **ER.6.7** Export a small curated public type surface from `anyinfer.__init__` and add
  complete public docstrings.
- [ ] **ER.6.8** Extend provider options without adding embedding/reranking fields to
  `GenerationRequest`.
- [ ] **ER.6.9** Decide whether semantic rankers are supplied to `context.select()` as a
  protocol implementation or constructed from a client/target convenience helper. Default
  context behavior remains lexical and offline.

## 10. Configuration and catalog

- [ ] **ER.7.1** Reuse `ProviderSettings`, credentials, headers, timeouts, instance aliases,
  limits, and setup specs across operations.
- [ ] **ER.7.2** Add operation-specific named routes without allowing an embedding route to
  be selected accidentally for generation.
- [ ] **ER.7.3** Extend the config schema, loader, writer, examples, and migration handling
  in one change.
- [ ] **ER.7.4** Extend the model catalog schema with model operations, embedding
  dimensions, normalization, input intents, local artifact/runtime compatibility, and
  verified pricing.
- [ ] **ER.7.5** Decide whether to ship novice aliases such as `embed-small`,
  `embed-multilingual`, and `rerank`. Alias resolution must be operation-aware.
- [ ] **ER.7.6** Extend catalog pin/refresh scripts; never hand-edit hashes, revisions,
  sizes, prices, or verification dates.
- [ ] **ER.7.7** Update `anyinfer init` and generic setup UIs to discover usable operation
  models without prompting for fields the descriptor already supplies.
- [ ] **ER.7.8** Keep embedding-space compatibility ids user-overridable and provenance
  tagged; a guessed equivalence is never authoritative.

## 11. Telemetry, manifests, benchmarking, and spend

- [ ] **ER.8.1** Add typed operation-started/completed/failed telemetry without embedding
  vectors, query text, or documents in payload-free events.
- [ ] **ER.8.2** Reuse target resolution, attempt, retry, fallback, rate-limit, and provider
  diagnostic events where their meanings remain operation-neutral; otherwise add explicit
  operation fields with a compatibility plan.
- [ ] **ER.8.3** Treat vectors, queries, and candidate documents as payloads that require
  an observer registered with `payloads=True`.
- [ ] **ER.8.4** Ensure redaction scans provider errors and retained raw payloads without
  serializing huge vectors into ordinary diagnostics.
- [ ] **ER.8.5** Add embedding and reranking run manifests derived from events/results,
  content-free by default and carrying embedding-space identity.
- [ ] **ER.8.6** Extend OTel mapping with operation, batch size/document count, dimensions,
  latency, throughput, usage, cost, and target attributes; never export vector values by
  default.
- [ ] **ER.8.7** Add embedding benchmark metrics (inputs/s, tokens/s where reported,
  vectors/s, cold/warm timing) and rerank metrics (documents/s, query latency).
- [ ] **ER.8.8** Apply spend reservations and ceilings across internal batches before
  dispatch so concurrency cannot overshoot the caller's policy unnoticed.

## 12. CLI, sidecar, and demo application

### CLI

- [ ] **ER.9.1** Add `anyinfer embed` with scalar input, newline/JSONL batch input, target or
  route, input intent, dimensions, machine-readable output, and safe output-size behavior.
- [ ] **ER.9.2** Add `anyinfer rerank` with query plus text/file/JSONL documents, `top_n`,
  target or route, and machine-readable output.
- [ ] **ER.9.3** Collection of files belongs to the CLI. The core receives text and ids,
  never paths to open.
- [ ] **ER.9.4** Extend `providers`, `models`, `verify`, `benchmark`, and `doctor` output with
  operation support and embedding-space diagnostics.
- [ ] **ER.9.5** Ensure terminal output never dumps thousands of vector values unless the
  caller explicitly chooses JSON/JSONL or an output file.

### Sidecar

- [ ] **ER.9.6** Implement OpenAI-compatible `POST /v1/embeddings` as a codec over
  `AsyncClient.embed`.
- [ ] **ER.9.7** Add an AnyInfer-native rerank route, initially
  `POST /v1/anyinfer/rerank`.
- [?] **ER.9.8** Decide whether to add compatibility aliases for Cohere `/v2/rerank` or the
  common `/v1/rerank` spelling; each alias is a separately conformance-tested codec.
- [ ] **ER.9.9** Extend `/v1/models` or an AnyInfer model endpoint so clients can distinguish
  generation, embedding, and reranking models.
- [ ] **ER.9.10** Preserve loopback/bearer-token security rules and add request-size limits
  suitable for large document batches.
- [ ] **ER.9.11** Smoke-test the new endpoints from the standalone PyInstaller bundle on
  every release platform.

### Demo application

- [ ] **ER.9.12** Add a discoverable embedding/reranking utility rather than forcing these
  operations into the chat composer.
- [ ] **ER.9.13** Show target, model, dimensions/space, usage, cost, timing, and warnings.
- [ ] **ER.9.14** Provide safe copy/save actions for vectors and ranked results; do not
  render unbounded vectors into the UI by default.
- [ ] **ER.9.15** Keep the demo offline-capable with fake embedding and reranking providers.

## 13. Error model

- [ ] **ER.10.1** Add shallow typed errors only where callers can act differently:
  unsupported operation, embedding-space mismatch, invalid vector response, and invalid
  rerank response.
- [ ] **ER.10.2** Map provider auth, rate limit, model-not-found, transport, timeout, and
  unavailability failures onto the existing provider error hierarchy.
- [ ] **ER.10.3** Distinguish local request validation from a provider rejection; local
  validation performs no attempt and spends nothing.
- [ ] **ER.10.4** Bound and redact all detail; vectors and documents never enter ordinary
  exception text.
- [ ] **ER.10.5** Define partial internal-batch failure data without presenting a partial
  success as a complete result.

## 14. Conformance and tests

### Public conformance kit

- [ ] **ER.11.1** Add embedding conformance cases for scalar/batch ordering, duplicates,
  dimensions, input intent, normalization metadata, float/base64 decode, usage, byte caps,
  error mapping, retry-after, cancellation, and malformed vectors.
- [ ] **ER.11.2** Add rerank conformance cases for index/id preservation, descending finite
  scores, `top_n`, duplicate text with distinct ids, truncation/degradation, usage, byte
  caps, error mapping, retry-after, cancellation, and malformed indexes.
- [ ] **ER.11.3** Add operation-aware fake providers and scripted outcomes to
  `anyinfer.testing` so integrating applications can test retrieval paths offline.
- [ ] **ER.11.4** Extend third-party certification manifests and generated matrix rows.
- [ ] **ER.11.5** Publish separate generation/embedding/rerank matrix views or one generated
  operation-aware matrix that remains readable.

### Core unit and integration tests

- [ ] **ER.11.6** Exhaustively test frozen type validation, public exports, repr safety,
  equality, serialization, and docstrings.
- [ ] **ER.11.7** Test vector validation against huge dimensions, ragged arrays, NaN,
  infinity, booleans, invalid base64, response bombs, and integer/float mixtures.
- [ ] **ER.11.8** Test embedding-space compatibility, same-model aliased deployments,
  unknown equivalence, explicit overrides, unsafe opt-in, and index/query mismatch.
- [ ] **ER.11.9** Test batching order and aggregation under concurrent completion,
  cancellation, timeout, retry, and one-batch failure.
- [ ] **ER.11.10** Test that rerank batching is refused by default rather than producing an
  invalid global ordering.
- [ ] **ER.11.11** Test sync facade calls from many threads and cancellation during a large
  batch.
- [ ] **ER.11.12** Test rate pacing and spend reservations across mixed generation,
  embedding, and reranking calls.
- [ ] **ER.11.13** Add sidecar request/response round trips, authentication, concurrency,
  disconnect cancellation, model listing, and size-limit tests.
- [ ] **ER.11.14** Add CLI parsing, stdin/file collection, output bounding, JSON round trip,
  exit-code, and redaction tests.
- [ ] **ER.11.15** Record sanitized real cassettes for every initial provider dialect.
- [ ] **ER.11.16** Add opt-in live tests for every dedicated implementation; include one
  local CPU-capable path in scheduled or release testing when practical.
- [ ] **ER.11.17** Add contract drift checks and changelog watchlists for every new wire
  surface.
- [ ] **ER.11.18** Add architecture-contract tests proving batching/routing/cost remain out
  of adapters and sidecar policy remains in the core.

## 15. Documentation and examples

- [ ] **ER.12.1** Add concepts pages for embeddings, embedding spaces, reranking, and the
  boundary between inference and retrieval infrastructure.
- [ ] **ER.12.2** Add task guides: semantic search building blocks, embedding a batch,
  query/document intents, safe index/query compatibility, reranking candidates, local
  embeddings, and fallback configuration.
- [ ] **ER.12.3** Add provider pages/sections with models, limits, pricing provenance,
  supported operations, quirks, and provider options.
- [ ] **ER.12.4** Add runnable fake-provider examples and at least one complete application
  example that owns its tiny in-memory similarity calculation explicitly.
- [ ] **ER.12.5** Update installation, integration-path, configuration, CLI, sidecar,
  testing, error-catalog, and API-reference pages.
- [ ] **ER.12.6** Update generated `llms.txt`, agent instructions, and `anyinfer agents-md`
  from canonical metadata rather than hand-authoring duplicated claims.
- [ ] **ER.12.7** Clearly state that an embedding model used for indexing must match the
  query embedding space; make the safe failure behavior prominent in quickstarts.
- [ ] **ER.12.8** Execute every example in CI without credentials or network.

## 16. Suggested implementation order

1. Settle the decisions in section 18 and write the design amendments.
2. Land operation, capability, request/result, error, usage, and pricing types.
3. Refactor the provider lifecycle into declared operation protocols without changing
   generation behavior.
4. Extract operation-neutral attempt/routing plumbing and implement embedding-space guards.
5. Build fake adapters and embedding/rerank conformance suites before real adapters.
6. Implement the prospective integration target plus one hosted and one local
   implementation that exercise different dialects.
7. Land core batching, spend, telemetry, manifests, compare, verify, and benchmarks.
8. Add sync facade, config/catalog, CLI, and sidecar surfaces.
9. Add demo support and executable documentation.
10. Expand dedicated adapters and presets only after their contracts are verified.
11. Run the full cross-platform suite, regenerate matrices/indexes/reference docs, and
    complete an API-freeze review.

## 17. Release acceptance criteria

The feature is not complete merely because one provider returns a vector.

- [ ] The design explicitly permits stateless embeddings and reranking while preserving a
  clear retrieval-infrastructure boundary.
- [ ] Async and sync APIs, CLI, sidecar, demo, configuration, discovery, and documentation
  agree on the same semantics.
- [ ] At least one hosted and one local embedding target pass fake, cassette, and live
  conformance.
- [ ] At least one hosted and one local reranking target pass fake, cassette, and live
  conformance, unless the local live lane is recorded as an explicit release exception.
- [ ] The prospective integration target passes its actual required flow.
- [ ] Cross-space embedding fallback is refused by default and conformance-tested.
- [ ] Rerank results preserve caller document identity and malformed indexes cannot escape.
- [ ] Core batching preserves embedding order and cannot return partial success silently.
- [ ] Usage, cost, spend policy, telemetry, redaction, manifests, and raw retention are
  tested for both operations.
- [ ] Standalone sidecar bundles pass `/v1/embeddings` and rerank smoke tests on macOS,
  Linux, and Windows.
- [ ] Generated provider indexes and conformance matrices make no unsupported claims.
- [ ] All public symbols have docstrings; examples run offline; lint, strict typing,
  architecture contracts, tests, and strict docs build pass.

## 18. Decisions and open questions

### Decisions adopted by this draft

1. **First-class operations:** embeddings and reranking are core inference primitives, not
   provider options on generation.
2. **Text-first:** the initial contract accepts text; multimodal embeddings are a later
   extension.
3. **Inference boundary:** AnyInfer owns stateless inference and its cross-cutting policy,
   not a vector store or corpus lifecycle.
4. **Typed protocols:** provider support is declared per operation; retrieval-only
   providers are valid.
5. **Safe embedding routes:** cross-target fallback requires explicit embedding-space
   equivalence; retries on one target remain automatic.
6. **Buffered operations:** no streaming embedding/reranking contract.
7. **Core batching:** batching is centralized policy and adapters only translate.
8. **Rerank integrity:** separate-batch scores are not assumed globally comparable.
9. **Frontend parity:** SDK, CLI, sidecar, demo, docs, and test kit are part of the feature,
   not follow-up polish.
10. **Offline default:** context reduction remains lexical unless the caller explicitly
    supplies a semantic ranker/client target.

### Owner decisions requested

- [?] **Q1 — Prospective target.** Which provider/service/runtime requires this, and does
  it require embeddings, reranking, or both? Record exact endpoints, auth mode, required
  models, input scale, latency target, and deployment environment.
  - **Recommended default:** implement that target in Milestone A and require its real flow
    as an acceptance test.

- [?] **Q2 — Retrieval ownership.** Does “batteries included universal AI interaction
  engine” extend to a built-in vector store/index now, or is stateless inference the right
  first boundary?
  - **Recommended default:** stateless inference now; consider a small store only after two
    integrations independently need the same lifecycle.

- [?] **Q3 — First release breadth.** Must the first usable release include every frontend,
  or may the SDK and sidecar land before CLI/demo polish?
  - **Recommended default:** implement core + SDK + sidecar + test kit as one usable slice,
    then CLI/demo in the same feature milestone before declaring completion.

- [?] **Q4 — Rerank wire compatibility.** Should the sidecar support only an AnyInfer-native
  rerank endpoint initially, or also emulate Cohere/common rerank routes?
  - **Recommended default:** AnyInfer-native endpoint first; add compatibility codecs only
    when a named integration needs them.

- [?] **Q5 — Unsafe embedding fallback.** Should an explicit escape hatch permit fallback
  across unknown/incompatible spaces?
  - **Recommended default:** yes for expert recovery workflows, named unmistakably and off
    by default; results and telemetry must mark the incompatibility.

- [?] **Q6 — Alias policy.** Should the bundled catalog ship novice retrieval aliases?
  - **Recommended default:** add `embed-small`, `embed-multilingual`, and `rerank` only once
    each resolves to at least one verified hosted and one verified local target.

### Implementation-time questions resolved by evidence, not preference

- [ ] Which providers return normalized vectors, and is that guarantee model-specific?
- [ ] Which providers distinguish query/document input types and how do they spell them?
- [ ] Which embedding model ids are stable spaces versus moving aliases?
- [ ] Which providers expose trustworthy batch/token/document limits?
- [ ] Which rerank providers make scores comparable across separately submitted batches?
- [ ] Which providers bill by tokens, requests, documents, or search units?
- [ ] Which local runtimes expose both discovery and operation endpoints in pinned releases?
- [ ] What response-size default safely covers common vector batches without enabling an
  unbounded allocation?

Every answer that changes wire behavior belongs in a dated contract snapshot and a
conformance case, not only in this plan.

## 19. Progress log

- **2026-08-11:** Initial plan drafted from the current implementation and product-owner
  direction. No production code changed. Owner interview questions Q1-Q6 remain open.
- **2026-08-11 (implementation pass):** Owner decisions resolved — Q1: Ollama/llama.cpp is
  the near-term real target, but the milestone was implemented to keep other providers
  addable without core changes. Q2/vector store: stateless-only in core; a small,
  explicitly non-scalable optional add-on package is tracked separately in
  `plans/VECTOR_STORE_ADDON.md`, not started. Q3: implemented core + SDK + CLI + sidecar +
  demo app together in one pass, per owner direction ("everything at once"). Q4: sidecar
  rerank is AnyInfer-native only (`POST /v1/anyinfer/rerank`); no Cohere-compatibility
  codec was added. Q5 (unsafe embedding fallback escape hatch) and Q6 (novice aliases like
  `embed-small`) remain unresolved and unimplemented.

  **Delivered and tested** (governance amendments in `DESIGN.md` §2, §23 ADR-017/ADR-018,
  §28, risk R10; full details in code):
  - Core types: `InferenceOperation`, `EmbeddingRequest`/`Result`/`Vector`/`Space`,
    `RerankRequest`/`Result`/`Document`/`RankedItem`, `EmbeddingCapabilities`,
    `RerankCapabilities`, `BatchPolicy` (§4, partially — see gaps below).
  - Provider contract split into `ProviderLifecycle` + `GeneratesText`/`EmbedsText`/
    `ReranksText`, with `ProviderDescriptor.operations` and build-time validation that a
    descriptor's declared operations are actually implemented (§5, ER.2.1-ER.2.5).
  - Embedding-space cross-target fallback safety guard: same-target-only by default,
    `expected_space` rejection, incompatible-fallback warning (§6, ER.3.1-ER.3.6) — the
    unsafe opt-in escape hatch (Q5, ER.3.3's second clause) was **not** implemented.
  - Routing/dispatch (`_client/operations.py`): target resolution, retry/backoff, health
    gate, fallback, attempt trail, telemetry reuse (`RequestStarted`/`TargetResolved`/
    `AttemptStarted`/`AttemptCompleted`/`RetryScheduled`/`FallbackTriggered`/
    `RequestCompleted`/`RequestFailed`) — reused generation's event types rather than
    adding operation-specific ones (partial ER.8.1/ER.8.2).
  - `AsyncClient.embed`/`rerank` and `Client.embed`/`rerank` sync facade (§9, ER.6.1-ER.6.5
    only — `models()`/`capabilities()`/`compare()`/`verify()`/benchmark surfaces from
    ER.6.6 were **not** extended for the new operations).
  - Ollama `POST /api/embed` adapter, contract-verified live against
    `docs.ollama.com/api/embed` and the GitHub `api.md` on 2026-08-11 (`contracts/ollama.md`
    updated; error-shape and batch-limit specifics remain explicitly flagged unverified).
  - Shared OpenAI-compatible `/v1/embeddings` dialect (`providers/openai_compat_embeddings.py`)
    as a mixin, float and base64 vector decoding, kept alongside not inside the chat codec
    (ER.2.9-ER.2.11) — **not yet wired into any concrete preset's descriptor** (ER.2.12/
    ER.2.13 undone; a provider must opt in explicitly and none currently do besides Ollama's
    own native dialect).
  - CLI `anyinfer embed` / `anyinfer rerank` (text/file/JSONL input, JSON output, `--out`)
    (§12 CLI, ER.9.1-ER.9.3, ER.9.5).
  - Sidecar `POST /v1/embeddings` and `POST /v1/anyinfer/rerank` (§12 sidecar,
    ER.9.6/ER.9.7) — model-listing distinction by operation (ER.9.9), compatibility-alias
    decision (ER.9.8, Q4 resolved as "no"), and PyInstaller-bundle smoke tests (ER.9.11)
    were **not** done.
  - Demo app `EmbeddingsPanel` wired into the inspector sidebar, backed by an in-process
    fake provider (`FakeEmbeddingRerankProvider`) added to `anyinfer.testing` and the demo's
    offline fake registry (§12 demo, ER.9.12-ER.9.15).
  - Docs: concepts page, API reference page, Ollama provider-page section, quickstart
    section (§15, ER.12.1/ER.12.2 partial, ER.12.3 partial, ER.12.4 not done — no complete
    standalone application example, ER.12.7 done in the concepts page).
  - Tests: ~120 new tests across types, provider protocols, routing/dispatch, the Ollama and
    OpenAI-compat adapters, the CLI, the sidecar, and the demo app; full project test suite,
    mypy, ruff, mkdocs --strict, and import-linter architecture contracts all pass with zero
    new failures (one pre-existing, unrelated demo-app sort-order test failure confirmed
    present on a clean checkout before this work started).

  **Explicitly not done in this pass** — real gaps, not implied by the above:
  - Core-owned batching (`BatchPolicy` exists as a type but request splitting across
    provider-verified limits is **not implemented** — every request is sent as one call;
    §7/ER.4.1-ER.4.8 remain undone).
  - Cohere, Azure, Gemini, Vertex, Bedrock, LM Studio, Voyage AI, Jina AI, and llama-server
    embedding/reranking (§8 Milestones A-C beyond Ollama and the generic OpenAI-compat
    dialect) — none implemented.
  - Config/catalog extensions for operation-specific named routes, catalog model-operation
    metadata, novice aliases (§10, all of ER.7.1-ER.7.8).
  - Manifests are not populated for embed/rerank results (`EmbeddingResult.manifest` and
    `RerankResult.manifest` stay `None` always) — `anyinfer.manifest` was not extended.
  - OTel bridge mapping, benchmark metrics, spend-ledger integration for the new operations
    (§11, ER.8.3-ER.8.8) — untouched.
  - The full conformance-kit treatment from §14 (ER.11.1-ER.11.5, ER.11.15-ER.11.18):
    scripted-provider-style conformance *cases* registered in the shared harness, cassette
    recordings, and drift-check coverage were not added — the new tests are conventional
    pytest suites, not entries in `anyinfer.testing.conformance`.
  - Third-party entry-point/scaffolding/certification updates for operation-specific
    adapters (ER.2.7).
  - PyInstaller standalone-bundle smoke tests for the new sidecar routes (ER.9.11).
  - The release acceptance criteria in §17 are **not** met as a whole: only one hosted-shape
    dialect (OpenAI-compatible, unattached to a live preset) and one local target (Ollama)
    exist, cassette/live conformance modes were not exercised, and the standalone-binary
    smoke tests were not run.

  Net effect: this pass proves the full architecture end-to-end through one real local
  provider and reuses that proof for a shared hosted dialect, across every stated frontend,
  but is a vertical slice — not the complete milestone. Treat the "explicitly not done"
  list above as the next actionable increment of this plan, not as background risk.

  Note: the per-item `[ ]`/`[x]` checkboxes throughout sections 4-14 were **not**
  individually updated to match this log, to avoid mismarking an item under time pressure.
  This log is the authoritative account of what shipped in this pass; treat any checkbox
  as unverified until it is checked against the "delivered and tested" / "explicitly not
  done" lists above.
