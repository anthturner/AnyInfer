# Embedding and reranking: consolidated completion plan

> **Status:** proposed; implementation of the tracks below has not started.
> **Plan date:** 2026-08-12.
> **Authority:** living implementation plan, not an architecture decision. Amends nothing in
> `DESIGN.md` beyond what ADR-017/ADR-018 and §28 already establish — everything here fills
> in scope those sections already anticipated.
> **Predecessor:** this plan absorbs and replaces `plans/EMBEDDING_RERANKING_SUPPORT.md`
> (deleted in the same change that landed this consolidation; its full text, including the
> per-item 2026-08-12 checkbox audit, is in git history). Everything from that plan that was
> still open lives in a track below, cross-referenced by its original `ER.x.y` id. §1
> records what already shipped so this plan stands alone.

## Status legend

| Marker | Meaning |
|---|---|
| [ ] | Not started |
| [~] | In progress / partially done, gap stated inline |
| [x] | Complete and verified |
| [?] | Waiting on a product or architecture decision |
| [-] | Deliberately excluded, with the reason recorded |

## 1. Where the work stands (verified baseline, 2026-08-12)

The 2026-08-11 implementation pass shipped a real, tested vertical slice, confirmed by a
per-item code audit on 2026-08-12:

- **Core types** — `InferenceOperation`, `EmbeddingRequest`/`Result`/`Vector`/`Space`,
  `RerankRequest`/`Result`/`Document`/`RankedItem`, `EmbeddingCapabilities`,
  `RerankCapabilities`, `BatchPolicy`, `BatchFailure` (`src/anyinfer/types/operations.py`),
  all frozen/slotted, all validated at construction, exported from `anyinfer.__init__` with
  passing docstring gates.
- **Provider architecture** — `ProviderLifecycle` + `GeneratesText`/`EmbedsText`/
  `ReranksText` protocols and normalized wire records (`src/anyinfer/providers/base.py`),
  `ProviderDescriptor.operations` with build-time validation, retrieval-only providers
  supported without dummy methods.
- **Routing/dispatch** — `dispatch_embed`/`dispatch_rerank`
  (`src/anyinfer/_client/operations.py`): target resolution, retry/backoff, health gate,
  fallback, attempt trail, `expected_space` enforcement, malformed-rerank-index rejection,
  telemetry event reuse.
- **Providers** — Ollama `POST /api/embed` (contract-verified live 2026-08-11,
  `contracts/ollama.md`), plus a shared OpenAI-compatible `/v1/embeddings` dialect mixin
  (`providers/openai_compat_embeddings.py`, float+base64 decoding) not yet attached to any
  concrete preset.
- **Frontends** — `AsyncClient.embed`/`rerank` + sync facade; CLI `anyinfer embed`/`rerank`;
  sidecar `POST /v1/embeddings` and `POST /v1/anyinfer/rerank`; demo-app `EmbeddingsPanel`
  with an offline `FakeEmbeddingRerankProvider` in `anyinfer.testing`.
- **Docs and tests** — concepts page, API reference page, Ollama provider section,
  quickstart section; 83 new tests; the full suite (`pytest`, `mypy`, `ruff`,
  `mkdocs build --strict`, `lint-imports`) passing with one pre-existing unrelated failure.

Everything else from the original plan is open and now lives in exactly one track below.

## 2. Scope boundary (carried forward unchanged)

This boundary was adopted in the predecessor plan and remains binding; it is reproduced
here because other documents (`plans/VECTOR_STORE_ADDON.md`) cite it.

### Included

- Text embeddings, scalar and batch; query/document input intent where a provider
  distinguishes them; provider-supported dimensionality reduction.
- Reranking one query against a caller-supplied ordered document collection; text plus
  caller-owned ids/metadata, only text sent unless a provider option requests more.
- Provider usage, provider-specific billing units, centrally computed cost when pricing is
  known, timing, target, attempt trail, warnings, optional raw retention.
- Core-owned batching against verified provider limits; operation-aware discovery and
  capabilities; operation-safe routing and fallback.
- Injection of an embedding-backed or reranking-backed ranker into context reduction,
  via a client/target convenience helper (decided 2026-08-12 — see §16, D-11 and BH.F.8).

### Explicitly excluded

- Vector databases, ANN indexes, persistence, corpus lifecycle, retrieval services
  (a separate optional add-on package is proposed in `plans/VECTOR_STORE_ADDON.md`).
- Automatic embedding of `ContextDocument` values; opaque automatic model selection;
  cross-model vector conversion; training/fine-tuning/evaluation.
- Image, audio, and multimodal embeddings in this milestone.
- Streaming vectors or incremental rerank results; both operations are buffered.

## 3. Verified fact base (audited 2026-08-12)

Facts the tracks below rely on, each checked directly against the code. Where the
predecessor plan or its progress log said otherwise, the correction is flagged — do not
re-derive these during implementation, and do not trust the older statements.

1. `BatchPolicy` (`src/anyinfer/types/operations.py:200`) has exactly `max_concurrency=4`,
   `allow_split=True`, `rerank_cross_batch=False`. `EmbeddingRequest.batch` carries it
   (`operations.py:281`). `BatchFailure` (`operations.py:233`: `batch_index`, `item_count`,
   `succeeded`, `error`) is never constructed anywhere. `EmbeddingCapabilities.max_batch_inputs`
   and `RerankCapabilities.max_documents` are populated by nothing and read by nothing, as
   are `ProviderDescriptor.static_embedding_capabilities`/`static_rerank_capabilities`
   (`src/anyinfer/registry.py:425-433`). `DEFAULT_MAX_EMBEDDING_INPUTS = 2_048` and
   `DEFAULT_MAX_DOCUMENTS = 1_000` (`operations.py:56-59`) are exported but enforced nowhere.
2. Generation reads static capabilities via
   `descriptor.static_capabilities.get(model)` + overlay in
   `src/anyinfer/capabilities/assemble.py:68` — that is the house idiom for Track A's limit
   resolution.
3. **Correction:** `Usage.merge()` (`src/anyinfer/types/results.py:102`) is an overlay —
   later non-`None` values *win*, nothing is added. It cannot aggregate usage across batch
   chunks; a summing helper does not exist yet.
4. **Correction:** `dispatch_embed`/`dispatch_rerank` emit `RequestStarted`,
   `TargetResolved`, `AttemptStarted`, `RetryScheduled`, `FallbackTriggered`,
   `RequestCompleted`, `RequestFailed` — and **not** `AttemptCompleted` or `FirstToken`
   (`src/anyinfer/_client/operations.py:24-32` imports; the predecessor's §19 log and audit
   claimed `AttemptCompleted` was reused — it is not).
5. The OTel bridge already produces spans for embed/rerank calls today, but every span is
   named `"generate"` and stamped `gen_ai.operation.name: "chat"`
   (`src/anyinfer/otel.py:111-114`; constant `GEN_AI = "gen_ai"` at `otel.py:45`). Because
   `AttemptCompleted`/`FirstToken` never fire (fact 4), token and TTFT metrics are silently
   absent; the duration histogram works. Payload gating already exists in two layers for
   generation: `record_payloads` (`otel.py:74,119,323`) and `strip_payloads`/`PAYLOAD_FIELDS`
   (`src/anyinfer/events/telemetry.py:488-508`); embed/rerank events currently carry no
   payload fields at all.
6. `RequestStarted` is a frozen/slotted dataclass with defaulted optional fields already
   (`src/anyinfer/events/telemetry.py:48-63`); adding another defaulted field follows ample
   precedent. `InferenceOperation = Literal["generation", "embedding", "rerank"]` exists at
   `src/anyinfer/types/operations.py:43`. The `TelemetryEvent` union is at
   `telemetry.py:464-485` with a drift-guard test
   (`tests/test_otel_bridge.py::test_every_event_type_has_a_handler`, line 145).
7. `RunManifest` (`src/anyinfer/manifest.py:426`) facets split cleanly: operation-neutral —
   `route`, `attempts`, `usage`, `timing`, `capability`, `dropped`, `notes`, envelope;
   generation-specific — `request` (message/role counts, sampling), `structured`, `cache`,
   `context`, `payloads`. `ManifestBuilder` (`manifest.py:574`) takes a `GenerationRequest`
   and a token estimator (`manifest.py:618-627`); neutral facets fold from events via
   `observe()`, but usage/timing facets read from the `Generation` result object
   (`manifest.py:956,972`). `AsyncClient.embed()`/`rerank()` (`_client/async_client.py:1214,
   1285`) accept no `manifest` parameter and never call `_new_run`.
8. `AllTargetsFailedError` (`src/anyinfer/errors.py:301`) carries
   `attempts: tuple[AttemptRecord, ...]`; `AttemptRecord` (`results.py:188`) has no
   item-count fields, so per-chunk batch outcomes cannot be represented by the attempt
   trail as-is.
9. The house concurrency idiom is `asyncio.Semaphore` + `asyncio.gather`
   (`routing/limits.py:276-278`; `_client/async_client.py:1488,1540`). No `TaskGroup`
   anywhere in `_client/`.
10. **Correction:** there is no `pytest.mark.live` (or any registered marker) in this repo —
    `[tool.pytest.ini_options]` registers no markers and the suite is offline by design.
    Live verification runs through the conformance kit (`anyinfer conform`, live mode
    opt-in via real credentials) and cassette recording is gated by
    `ANYINFER_RECORD_CASSETTES` (`src/anyinfer/testing/plugin.py:50-51`).
11. The HTTP stack is `httpx2` (`pyproject.toml:27`); wire tests use
    `httpx2.MockTransport` (`tests/test_ollama_embeddings.py:16`).
12. `src/anyinfer/providers/cohere.py` is a generation-only adapter (native v2 Chat); its
    descriptor (`cohere.py:527-560`) declares no `operations`, inheriting generation-only.
    Its `_parse_usage` (`cohere.py:446-475`) already distinguishes Cohere's `tokens` vs
    `billed_units` blocks. `contracts/cohere.md` exists (chat only). The only descriptor
    declaring embedding today is Ollama's (`providers/ollama.py:656`).
13. Ollama's `embed()` silently drops `EmbeddingRequest.input_type`
    (`providers/ollama.py:619`, `_build_embedding_payload`) — a silent-degradation
    precedent Track B must not repeat and Track J should backfill a warning for.
14. `Usage` (`results.py:68`) has no extensibility field; a billed-search-unit count has no
    honest home today. Raw provider payloads survive only via `retain_raw`
    (`EmbeddingWireResult.raw`/`RerankWireResult.raw`).
15. **Citation correction:** the "an unknown limit is never guessed" rule lives in
    DESIGN.md §28 ("an unknown limit means one bounded request, never a guessed provider
    maximum") and §14's cost bullet — not §7, which is the capability-provenance model.
    The "never encode billed search units as fake output tokens" rule was the predecessor
    plan's ER.1.20, not DESIGN.md §21 (§21 is the risk register, R1-R10).
16. The sidecar already has an opt-in run-manifest response extension for chat
    (`anyinfer_manifest`: `serve/openai_codec.py:96,138,729`, wired in
    `serve/app.py:325-373`) — prior art for Track C's stretch goal. The sidecar rerank
    route is `POST /v1/anyinfer/rerank` (`serve/app.py:268-269`), AnyInfer-native by
    decision (§16, D-9).
17. **Defect found by the 2026-08-12 audit, fixed by Track D the same day:** cross-target
    embedding fallback into an incompatible or unknown space was allowed through —
    worse, the warning branch meant to flag it was unreachable (the dispatch loop
    returns on first success, so its guard variable was never set), so such a fallback
    produced *no signal at all*. Now refused before dispatch; see the progress log.

## 4. Track map and suggested order

| Track | What | Why this order |
|---|---|---|
| D | Embedding-space fallback gate | A found safety defect; small, self-contained, highest severity |
| A | Core-owned batching | Pure core work; prerequisite for exercising any real provider ceiling |
| B | Cohere embedding + reranking | First provider with native rerank + input intents; proves the type system |
| C | Manifests, OTel, benchmark parity | Verifiable once B gives real attempt variety; can run parallel to B |
| E | Pricing, billable units, spend | Needs B's verified billing facts; unblocks demo cost display |
| F | Operation-aware capability/discovery surfaces | Feeds A's limits and the CLI/sidecar listings |
| G | Config and catalog | Named routes, catalog schema; feeds F |
| H | Conformance kit, cassettes, live lanes, drift | Formalizes what A-D proved ad hoc |
| I | Provider expansion backlog | Strictly after H exists, so each new adapter lands with conformance |
| J | Robustness and test-depth backlog | Continuous; individual items attach to the tracks they verify |
| K | Documentation completion | Rolling; each track updates its own docs, K sweeps the rest |

**Owner direction (2026-08-12): execute all tracks sequentially in this order.** The
decisions §16 flags are resolved, so no track blocks on an owner call.

Tracks are independently shippable. Land them as separate changes — the predecessor pass's
retrospective is a reminder that reviewing one enormous diff against nine architecture
rules at once is how things get missed. Re-run `lint-imports` after each track, not just at
the end; batching logic in particular has the shape of something tempting to leak into an
adapter (all of it belongs in `_client/operations.py` — if a change starts wanting an
adapter to know about batch limits beyond receiving one already-sized wire request, the
"Adapters never orchestrate" contract is being violated).

## 5. Track D — embedding-space fallback gate (defect fix; absorbs ER.3.3, ER.3.4, Q5)

The audit found `dispatch_embed` sends a fallback request to a target whose embedding space
is unknown or incompatible and only *warns afterward* (fact 17). ADR-018's rule is that a
wrong-space vector fails silently downstream, which is worse than an error — so the gate
must refuse *before* spending the fallback request.

- [x] **BH.D.1** In `dispatch_embed`'s fallback path, refuse to dispatch to a next target
  whose space is not provably compatible — raise before the wire call with an actionable
  hint. *(Done 2026-08-12: `_same_space_target` gate after the health-gate skip, before
  `pool.get`. Pre-dispatch the only provable equivalence is identical provider+model —
  a `compatibility_id` lives on `EmbeddingSpace`, which is built from the response;
  trusted per-target ids arrive with BH.G.4 and the gate should honor them then.)*
- [x] **BH.D.2** Add the explicit unsafe opt-in the predecessor's Q5 recommended default
  called for. *(Done 2026-08-12: `EmbeddingRequest.allow_incompatible_fallback`, exposed
  on `AsyncClient.embed`/`Client.embed`, off by default; an opt-in result always carries
  a warning naming both targets. The telemetry/manifest visibility of an opt-in
  incompatible fallback lands with Track C's operation tag, per this item's own
  sequencing.)*
- [x] **BH.D.3** Tests (closes ER.11.8's gaps). *(Done 2026-08-12 in
  `tests/test_embeddings_reranking.py`: aliased same-`provider:model` fallback serves
  with no opt-in and no warning; unknown equivalence refused with zero calls recorded on
  the second model; opt-in serves from the fallback with the mandatory warning; the
  index/query mismatch case was already covered by
  `test_embed_rejects_response_incompatible_with_expected_space`.)*

## 6. Track A — core-owned batching (absorbs ER.4.1-ER.4.8, ER.10.5, ER.11.9, ER.11.10)

### Where the pieces already are

Facts 1, 2, 3, 8, 9 in §3. The single change site is `dispatch_embed`/`dispatch_rerank`
(`src/anyinfer/_client/operations.py:142,267`): "resolve the limit, split if needed,
dispatch N chunks, merge" wraps around one target's dispatch — routing, retry, health
gate, and the embedding-space check stay as they are.

### Design

- [ ] **BH.A.1** Resolve the effective per-request limit at dispatch time, in priority
  order: an explicit caller override on `BatchPolicy` (new field — e.g.
  `max_inputs_override`/`max_documents_override`) beats the resolved target's
  `EmbeddingCapabilities.max_batch_inputs`/`RerankCapabilities.max_documents` (read via
  `descriptor.static_embedding_capabilities.get(resolved.model)`, mirroring
  `capabilities/assemble.py:68`), which beats "unknown — send one request, never split"
  (DESIGN.md §28's rule, fact 15). While here, settle the two dead `DEFAULT_MAX_*`
  constants (fact 1): they must **not** become implied provider ceilings — either enforce
  them as local pre-dispatch sanity bounds (BH.A.8) or delete them; do not leave them
  exported and meaningless.
- [ ] **BH.A.2** When the input/document count exceeds the resolved limit and
  `allow_split=True`, split into ordered chunks no larger than the limit and dispatch with
  concurrency bounded by `BatchPolicy.max_concurrency`, using `asyncio.Semaphore` +
  `gather` (the house idiom, fact 9).
- [ ] **BH.A.3** When `allow_split=False` and the request exceeds the limit, raise
  `ConfigError` locally before any provider call — matching
  `EmbeddingRequest.__post_init__`'s "never sent, never billed, never retried" precedent
  (`operations.py:284-294`).
- [ ] **BH.A.4** Embedding aggregation: preserve vector order across concurrently
  completing chunks (original request positions, not arrival order). Failure is
  all-or-error (ER.4.4/ER.10.5): if any chunk exhausts its retry budget, the whole call
  raises `AllTargetsFailedError` extended with a new optional
  `batch_failures: tuple[BatchFailure, ...] = ()` field — the investigation is done
  (fact 8): the attempt trail cannot carry item counts, and `BatchFailure` already has
  exactly the right shape and zero consumers. No `EmbeddingResult` with holes, ever. The
  post-dispatch vector-count check (`operations.py:240-246`) must validate the *merged*
  result against the *original* request.
- [ ] **BH.A.5** Rerank aggregation is deliberately **not symmetric**: per
  `BatchPolicy.rerank_cross_batch` (default `False`), an over-limit rerank request is
  refused locally unless the caller opts in, in which case chunks are reranked
  independently, results concatenated chunk-locally (never globally re-sorted), and a
  **mandatory warning** on `RerankResult.warnings` states that cross-batch scores are not
  a provider-certified global ordering. This is the correctness rule ADR-018's sibling
  decision (§16, D-8) exists to protect, not a batching nuance.
- [ ] **BH.A.6** Aggregate usage by **summing** across chunks — `Usage.merge()` is an
  overlay and unusable here (fact 3). Add a small explicit helper (e.g. `Usage.sum()`
  classmethod: fields sum when all known, stay `None` if any chunk's value is unknown —
  never understate spend by treating unknown as zero, ER.4.6). Aggregate timing and
  warnings alongside.
- [ ] **BH.A.7** Emit one `RequestStarted`/`RequestCompleted`/`RequestFailed` set per
  logical `embed()`/`rerank()` call regardless of chunk count; per-chunk
  `AttemptStarted` (and, once Track C adds it, `AttemptCompleted`) events are expected.
- [ ] **BH.A.8** Size bounds (ER.4.7/ER.4.8): give `EmbeddingRequest`/`RerankRequest` an
  operation-appropriate `max_response_bytes` default (the generation default is too small
  for large float-vector batches — today they reuse it unchanged), and bound vector count,
  dimensions, document count, and total response bytes *before allocation* so an unbounded
  response cannot be materialized in memory ahead of any check. Count-based *splitting* is
  this track; byte/token-aware splitting stays out of scope (below).

### Tests

- [ ] **BH.A.9** Limit-resolution priority (override > capability > unknown-never-split)
  using `FakeEmbeddingRerankProvider` — its constructor
  (`testing/scripted_operations.py:101-110`) does not accept static capabilities today, so
  extend it (that is a confirmed subtask, not a maybe).
- [ ] **BH.A.10** Order preservation across 3 chunks with staggered fake completion
  latency.
- [ ] **BH.A.11** All-or-error: one chunk fails after retries → whole call raises with
  every chunk's outcome visible in `batch_failures`; no silent discard of the successes'
  existence.
- [ ] **BH.A.12** `allow_split=False` over-limit → local raise, `fake.embed_requests == []`.
- [ ] **BH.A.13** Rerank cross-batch: default refusal; opt-in with non-empty warning;
  items chunk-locally sorted, never globally re-sorted (a global re-sort would assert a
  false comparability claim).
- [ ] **BH.A.14** Cancellation mid-batch (ER.11.9's hardest case): cancelling a split
  `embed()` cancels in-flight chunks and never returns partial success.
- [ ] **BH.A.15** CLI and sidecar smoke: one oversized request through `anyinfer embed`
  and `POST /v1/embeddings` against a fake with a small declared `max_batch_inputs` —
  regression guard that batching is reachable from every frontend with zero
  frontend-specific code.

### Explicitly out of scope for this track

- Byte/token-aware splitting (`max_input_tokens`, `max_bytes_per_document`) — count limits
  only; token-aware splitting needs an estimator in the loop and blocks nothing below.
- Spend-ledger reservation across concurrent chunks — Track E (BH.E.5); note it as a
  known follow-up in the new code's docstrings.

## 7. Track B — Cohere embedding + reranking adapter (absorbs ER.5.3)

### Why Cohere specifically

Cohere is the one initial-milestone provider offering native input intents (`input_type`),
native rerank scores, and billed search units in one adapter — the single best proof that
`EmbeddingInputIntent` and `RerankCapabilities` work against something other than the fake
and Ollama's embed-only, intent-blind API. `providers/cohere.py` already exists for
generation (fact 12) — this track extends that file; setup spec, bearer-auth client
construction, and `classify_status`/`map_transport_error` error hooks are in place to
reuse, and `_parse_usage` already reads `billed_units`.

### Required first step: verify, don't guess

AGENTS.md's rule ("never fabricate a last-verified date without actually verifying")
applies with full force. Before writing wire code:

- [ ] **BH.B.1** Fetch and cite Cohere's current embed and rerank API documentation
  (verify the live URLs — do not assume paths from training data). Record exact
  request/response field names, batch limits, `input_type` enum values, billing unit
  names, and error-body shape, each with the fetch date, following
  `contracts/DRIFT-CHECK.md`'s procedure and `contracts/ollama.md`'s embeddings-section
  format (endpoint, auth, version pins, request fields, response fields, streaming,
  errors, watchlist — with explicit "unverified" markers for anything the docs don't
  state).
- [ ] **BH.B.2** Confirm embed batch support and its stated ceiling (feeds
  `EmbeddingCapabilities.max_batch_inputs`; directly exercises Track A).
- [ ] **BH.B.3** Confirm the rerank document ceiling per call and whether Cohere documents
  any cross-batch score comparability (almost certainly not — confirm rather than assume;
  a "yes" would change the `rerank_cross_batch` recommendation for this provider only).
- [ ] **BH.B.4** Extend `contracts/cohere.md` (exists, chat-only today) with dated, cited
  embeddings and rerank sections.

### Implementation

- [ ] **BH.B.5** Add `embed()` to `CohereAdapter` implementing `EmbedsText`
  (`providers/base.py:276`), translating `EmbeddingWireRequest` → Cohere's embed shape,
  with an explicit mapping function from `EmbeddingInputIntent` to Cohere's spelling
  (pattern: `ollama.py`'s `_translate_reasoning`). Do not assume Cohere's vocabulary
  matches AnyInfer's literals. An unsupported intent must degrade loudly (result warning),
  not silently — Ollama's current silent drop (fact 13) is the anti-pattern.
- [ ] **BH.B.6** Add `rerank()` implementing `ReranksText` (`providers/base.py:359`),
  translating to/from `RerankWireRequest`/`RerankWireResult`/`WireRankedItem`. Translation
  only — malformed-index handling stays in the core's `_validate_ranked_items`
  (`_client/operations.py:411`).
- [ ] **BH.B.7** Update the descriptor (`cohere.py:527-560`) with
  `operations=frozenset({"generation", "embedding", "rerank"})` (build-time validation
  will hold the adapter to it) and populate
  `static_embedding_capabilities`/`static_rerank_capabilities` with only what BH.B.1-B.3
  verified — an unverifiable fact stays `None`, matching `contracts/ollama.md`'s explicit
  unverified markers. The only existing precedent is Ollama's descriptor
  (`ollama.py:656`).
- [ ] **BH.B.8** Billed search units: `Usage` has no honest field for them (fact 14) —
  leave them out of `Usage` rather than encode them as fake tokens (§16, D-13). They
  remain reachable via `retain_raw`. First-class billable-unit representation is Track E
  (BH.E.1); note the gap in the adapter docstring and do not block this track on it.

### Tests

- [ ] **BH.B.9** Wire-mapping unit tests with `httpx2.MockTransport` (fact 11), following
  `tests/test_ollama_embeddings.py` / `tests/test_openai_compat_embeddings.py`: scalar
  input, batch order preservation, dimensions, malformed response rejection, HTTP error
  mapping (auth, rate limit, model-not-found).
- [ ] **BH.B.10** `input_type` translation: every `EmbeddingInputIntent` value maps to the
  verified Cohere wire value; unsupported combinations degrade loudly per BH.B.5.
- [ ] **BH.B.11** Rerank wire-mapping: score ordering, `top_n`, malformed-index rejection
  feeding the existing core validation with real wire shapes.
- [ ] **BH.B.12** End-to-end through `AsyncClient.embed()`/`.rerank()` targeting
  `cohere:<model>` against the mock transport (adapt
  `tests/test_embeddings_reranking.py`'s `_client_with_fake` pattern, line 154, for a real
  adapter + mock transport).
- [ ] **BH.B.13** Live verification: there is **no** pytest live-marker convention in this
  repo (fact 10) — do not invent one ad hoc. Live conformance for Cohere goes through the
  conformance kit's opt-in live mode (Track H registers the cases; `anyinfer conform`
  runs them with real credentials). A trial key is available at `COHERE.key` in the
  repository root (owner, 2026-08-12; gitignored the same day so it cannot be
  committed): load it into `CO_API_KEY` at test time for the opt-in live smoke and
  cassette recording. The key is never logged and never embedded in fixtures —
  credentials go through `anyinfer.credentials` and its redaction registry. Owner
  approved (2026-08-12) spending trial quota *during this track*: one live smoke per
  operation while building the adapter, plus early sanitized cassettes — so the contract
  snapshot is validated against live traffic, not documentation alone.

### Explicitly out of scope for this track

- Any provider beyond Cohere (Track I owns the tail).
- A Cohere-compatible sidecar rerank route — resolved as "AnyInfer-native only"
  (§16, D-9); nothing here reopens it.

## 8. Track C — manifests, OTel, and benchmark parity (absorbs ER.8.1, ER.8.3, ER.8.5-ER.8.7, ER.1.23's manifest/OTel half)

The investigation the earlier draft of this plan called for is done — facts 4-7 and 16.
The bridge already spans embed/rerank calls; they are mislabeled `"chat"`, missing
attempt-level events, and produce no manifest.

### Event parity (prerequisite for both manifests and OTel)

- [ ] **BH.C.1** Emit `AttemptCompleted` (with per-attempt usage/timing) from
  `_attempt_with_retry`'s success path in `_client/operations.py` — generation emits it,
  embed/rerank do not (fact 4), and both the manifest attempt facet and the OTel bridge's
  per-attempt handling hang off it.
- [ ] **BH.C.2** Add `operation: InferenceOperation = "generation"` as a defaulted field
  on `RequestStarted` (and any other event whose handler stamps operation-flavored
  attributes) — frozen/slotted with defaulted-field precedent, fact 6 — set by
  `dispatch_embed`/`dispatch_rerank` vs. generation's `_route_events`. Extending the
  shared event beats forking parallel event types: ADR-006's single typed-event contract
  must not grow two families that drift.

### Manifests

- [ ] **BH.C.3** Build the manifest for embed/rerank from dispatch-local state. The
  investigation (fact 7) points at a lean shape: neutral facets (`route`, `attempts`,
  `usage`, `timing`, `capability`, `notes`) assembled by a small free function or slim
  builder from the events plus the local result — `ManifestBuilder`'s constructor is
  generation-shaped (`GenerationRequest` + token estimator) and its `request`/`structured`/
  `cache`/`context` facets are meaningless here. Prefer reusing the `RunManifest` type
  with generation-only facets empty over introducing a second manifest type (ADR-014's
  "second source of truth" concern); if `RequestFacet` cannot honestly represent an
  embed request even as empty, decide then — with these facts, not from scratch. Either
  way ADR-014's derivation rule holds: every field computed from this call's events,
  request, resolved capabilities, and result; the manifest must carry embedding-space
  identity (ER.8.5). No I/O anywhere in the subsystem.
- [ ] **BH.C.4** Wire it behind the existing `self._manifests` client toggle and add the
  per-call `manifest: bool | None = None` parameter to `embed()`/`rerank()` — they lack it
  today (fact 7) — matching `generate()`/`stream()`'s resolution in `_new_run`
  (`async_client.py:1747`).
- [ ] **BH.C.5** CLI `--trace`/`--trace-json` for `anyinfer embed`/`rerank`, mirroring
  `run`'s flags (`cli.py:352-370`, `_emit_trace` at `cli.py:1841`); parsers at
  `cli.py:371` and `cli.py:423`. Only after BH.C.3-C.4.
- [ ] **BH.C.6** Stretch: sidecar `anyinfer_manifest` response extension for
  `/v1/embeddings`, reusing the chat mechanism (fact 16). Optional; note if skipped.

### OTel bridge

- [ ] **BH.C.7** Read the operation tag in `otel.py`'s handlers: span name and
  `gen_ai.operation.name` become operation-correct (the value for embeddings has an
  established GenAI semantic-convention spelling — verify against the current spec at
  opentelemetry.io before hardcoding; the repo pins no semconv constants, fact 5). Extend
  `tests/test_otel_bridge.py` (don't fork a parallel file) and keep its union drift guard
  failing loudly on unmapped events.
- [ ] **BH.C.8** Payloads: embed/rerank events carry no payload fields today (fact 5). If
  this track adds any (input texts, query/document text as gated span attributes), they
  must be registered in `PAYLOAD_FIELDS` and gated behind `payloads=True`/`record_payloads`
  exactly like `prompt_text` — and embedding *vectors* are never exported as span
  attributes under any flag (ER.8.3/ER.8.6). If no payload fields are added, record that
  as the (safe) status quo rather than implementing a gate with nothing to gate.

### Benchmark metrics

- [ ] **BH.C.9** Embedding metrics (inputs/s, vectors/s, tokens/s where reported,
  cold/warm) and rerank metrics (documents/s, query latency) need new fields —
  `Measurement`'s rate fields are all token-denominated (`benchmark.py:190-198`), and
  `Measurement.from_json` already degrades to `None` on unknown keys (`benchmark.py:
  233-237`), so an additive extension is old-reader-safe. Smallest, lowest-priority piece
  of this track; land last.

### Tests

- [ ] **BH.C.10** Manifest dual-path test mirroring
  `tests/test_manifest.py::TestDerivation::test_matches_a_subscribed_observer` (line 327)
  adapted for `embed()`/`rerank()`: the manifest and the event stream may not disagree.
- [ ] **BH.C.11** OTel: an `embed()`/`rerank()` call produces a span with the correct
  non-`"chat"` operation name and no vector/document content in attributes by default.
- [ ] **BH.C.12** Regression: generation's existing span shape and manifest output are
  byte-identical to before this track — the entire point of a defaulted operation tag is
  that `_route_events` behavior does not change.

## 9. Track E — pricing, billable units, and spend (absorbs ER.1.20-ER.1.23, ER.8.8, ER.11.12)

Blocked on Track B for real billing facts (Cohere search units are the forcing case).

- [ ] **BH.E.1** Represent provider-native billable units first-class with stable names
  and exact numeric types (ER.1.21) — a deliberate design, not a `dict[str, float]` grab
  bag; `cost_usd` stays the only normalized spend field. Record the ER.1.20 decision
  explicitly (in `Usage`'s docstring or DESIGN.md §28): `Usage` remains operation-neutral,
  search units are never encoded as fake tokens.
- [ ] **BH.E.2** Add embedding pricing (input-token based) and rerank pricing (token,
  request, document, or search-unit based) to the pricing data without forcing one
  invented unit (ER.1.22) — entries go through the pricing refresh scripts, never
  hand-edited (AGENTS.md).
- [ ] **BH.E.3** Compute `cost_usd` for embed/rerank results where pricing is known;
  unknown stays `None`, never inferred from a sibling model (ER.1.24 stays honored).
- [ ] **BH.E.4** Extend spend ledgers and ceilings to the new operations (ER.1.23) —
  today there is no ceiling enforcement whatsoever for embed/rerank calls.
- [ ] **BH.E.5** Spend reservations across Track A's concurrent chunks so bounded
  concurrency cannot overshoot a caller's ceiling unnoticed (ER.8.8).
- [ ] **BH.E.6** Tests: rate pacing and spend across mixed generation/embed/rerank calls
  (ER.11.12); demo panel shows cost once it exists (the ER.9.13 gap was a consequence of
  pricing, not a UI omission).

## 10. Track F — operation-aware capability and discovery surfaces (absorbs ER.1.3, ER.1.6-ER.1.8, ER.3.10, ER.6.6, ER.9.4, ER.9.9)

- [ ] **BH.F.1** Add operation support to `ModelCapabilities` with provenance (ER.1.3) —
  today only the coarse `ProviderDescriptor.operations` set exists; model-level operation
  facts have no home, which is why discovery can't filter honestly.
- [ ] **BH.F.2** Extend `conjunction()`/overlay in `types/capabilities.py` to
  `EmbeddingCapabilities`/`RerankCapabilities` (ER.1.6), including delegating/`auto`
  targets — Track A reads these records, so overlay semantics must be defined, not
  accidental.
- [ ] **BH.F.3** Audit `list_models()` paths so embedding-only and rerank-only models are
  preserved rather than filtered as non-chat (ER.1.7) — includes LM Studio's current
  filtering (ER.5.10's discovery half).
- [ ] **BH.F.4** Operation-aware `models()`, `capabilities()`, `compare()`, `verify()`,
  and benchmark surfaces (ER.1.8/ER.6.6) so callers can inspect fit/degradation/pricing
  without dispatching.
- [ ] **BH.F.5** CLI: extend `providers`, `models`, `verify`, `benchmark`, `doctor` output
  with operation support and embedding-space diagnostics (ER.9.4).
- [ ] **BH.F.6** Sidecar: distinguish generation/embedding/rerank models in `/v1/models`
  or an AnyInfer-native listing (ER.9.9), then cover it in the sidecar tests (the
  model-listing half of ER.11.13).
- [ ] **BH.F.7** Build minimal embed/rerank capability probes (ER.3.10; decided by owner
  2026-08-12 — build, not defer): a tiny real request per target, results
  provenance-tagged `probed` on the same terms as generation's probing, feeding the
  capability assembly so batch limits and intent support can resolve at runtime where
  static/catalog facts are absent. Probes cost real spend — they run only where probing
  is already invoked deliberately, never implicitly on ordinary dispatch.
- [ ] **BH.F.8** Context semantic-ranker helper (D-11): define/confirm the ranker
  protocol `context.select()` accepts inside `anyinfer.context` (leaf module), and ship
  the convenience constructor client-side (a rerank-backed ranker built from a client +
  target string). `anyinfer.context` must not import `_client` — verify with
  `lint-imports`. Default stays lexical/offline; the helper is opt-in.

## 11. Track G — config and catalog (absorbs ER.7.2-ER.7.4, ER.7.6-ER.7.8)

Cross-cutting per AGENTS.md: schema, loader, writer, examples, migration, and reference
docs move in one change.

- [ ] **BH.G.1** Operation-specific named routes in the config schema (ER.7.2/ER.7.3) —
  an embedding route must not be selectable for generation or vice versa; extend loader,
  writer, examples, and migration together.
- [ ] **BH.G.2** Catalog schema: model operations, embedding dimensions, normalization,
  input intents, local artifact/runtime compatibility, verified pricing (ER.7.4) — then
  extend the pin/refresh scripts (ER.7.6); never hand-edit pinned values.
- [ ] **BH.G.3** `anyinfer init` and generic setup UIs discover usable operation models
  without prompting for descriptor-supplied fields (ER.7.7).
- [ ] **BH.G.4** Provenance-tag `EmbeddingSpace.compatibility_id` (ER.7.8) — it is
  caller-supplied and never guessed today (good), but carries no `Sourced[T]` provenance;
  a config-supplied equivalence must be distinguishable from a caller-asserted one.

## 12. Track H — conformance kit, cassettes, live lanes, drift (absorbs ER.11.1, ER.11.2, ER.11.4, ER.11.5, ER.11.15-ER.11.17, ER.2.7)

The 2026-08-11 pass wrote conventional pytest suites; the conformance *kit* — the shared
parametrized harness third-party adapters run — was never extended.

- [ ] **BH.H.1** Register embedding conformance cases in `anyinfer.testing.conformance`
  (ER.11.1): scalar/batch ordering, duplicates, dimensions, float/base64 decode, usage,
  error mapping (already proven ad hoc — port them), plus the never-covered behaviors:
  input-intent translation, normalization metadata, byte caps, retry-after timing,
  cancellation.
- [ ] **BH.H.2** Register rerank conformance cases (ER.11.2): index/id preservation,
  descending finite scores, `top_n`, malformed indexes (port), plus
  duplicate-text-distinct-ids, byte caps, retry-after, cancellation.
- [ ] **BH.H.3** Extend third-party certification manifests and scaffolding for
  operation-specific adapters (ER.2.7/ER.11.4): `testing/scaffold.py`, `testing/certify.py`,
  and the registry entry-point loader.
- [ ] **BH.H.4** Operation-aware conformance matrix generation (ER.11.5) — one generated
  matrix or per-operation views; either way generated from descriptors so docs cannot
  overstate coverage (also closes ER.5.16).
- [ ] **BH.H.5** Record sanitized cassettes for each implemented dialect (ER.11.15, via
  `ANYINFER_RECORD_CASSETTES`) and stand up the opt-in live lanes (ER.11.16) — including
  a live lane for Ollama's embed endpoint (its 2026-08-11 verification was documentation
  research, not live traffic) and Cohere's once Track B lands (BH.B.13).
- [ ] **BH.H.6** Extend drift-check coverage (`contracts/DRIFT-CHECK.md`) to the new wire
  surfaces (ER.11.17) so `contracts/ollama.md`'s embeddings watchlist and
  `contracts/cohere.md`'s new sections are actually audited on the next drift pass.

## 13. Track I — provider expansion backlog (absorbs ER.5.2, ER.5.5-ER.5.15, ER.2.12, ER.2.13)

Strictly after Track H, so every adapter lands with conformance, a dated contract
snapshot, a matrix column, and a provider docs page (AGENTS.md's adapter-PR bar; provider
docs per adapter close ER.12.3's remainder). Audit-first for every entry: current primary
sources or live traffic, never training-data memory.

**Owner direction (2026-08-12): all four groups below are in scope for this run** — the
OpenAI attach + presets, TEI + local runtimes, the big-cloud adapters, and the
specialists. The ordering below is sequencing, not optionality.

- [ ] **BH.I.1** Attach OpenAI embeddings for real (ER.5.2): wire the proven
  `openai_compat_embeddings` mixin into the concrete OpenAI adapter/preset descriptor,
  verify against the live endpoint, snapshot the contract. The dialect is tested; no
  concrete provider opts in today.
- [ ] **BH.I.2** Preset operation flags (ER.2.12/ER.2.13): compose the mixin into
  compatibility presets only with per-preset verification recorded in
  `contracts/openai-compat-presets.md` — a preset never inherits embedding support merely
  because its chat endpoint is OpenAI-compatible. The 86-preset audit (ER.5.14) proceeds
  incrementally; unverified presets simply stay generation-only, which is the correct
  conservative default.
- [ ] **BH.I.3** Milestone providers, each its own change: Hugging Face TEI (ER.5.5,
  externally managed local, OpenAI-compatible embed + native rerank), Azure (ER.5.6),
  Gemini (ER.5.7), Vertex (ER.5.8), Bedrock (ER.5.9), LM Studio (ER.5.10), llama-server
  embeddings behind a live contract check with acquisition staying in `local/` (ER.5.11),
  Voyage AI (ER.5.12), Jina AI (ER.5.13), named local presets for verified TEI/vLLM/SGLang
  deployments (ER.5.15).
- [ ] **BH.I.4** Ollama loose ends from the audit: surface `total_duration`/
  `load_duration` on `EmbeddingWireResult` (read but dropped today), and re-verify the
  model-pulling hook on the embeddings path specifically.

## 14. Track J — robustness and test-depth backlog (absorbs ER.3.12, ER.6.2/ER.6.4, ER.8.4, ER.10.4, ER.11.6-ER.11.8, ER.11.11, ER.11.13, ER.11.14, and fact 13)

Independent, individually landable test/robustness items. None block the tracks above;
several verify them.

- [ ] **BH.J.1** Cancellation of a single in-flight `embed()`/`rerank()` closes HTTP work
  and never returns partial results (ER.3.12; the mid-batch case is BH.A.14).
- [ ] **BH.J.2** Sync-facade thread-stress and cancellation coverage for
  `Client.embed`/`rerank` (ER.6.2/ER.6.4/ER.11.11) — generation's facade has this; the new
  methods got only basic coverage.
- [ ] **BH.J.3** Frozen-type hygiene for the new types: equality, repr safety,
  serialization round-trips (ER.11.6).
- [ ] **BH.J.4** Vector-validation gaps (ER.11.7): huge dimensions, ragged arrays
  (inconsistent per-vector lengths from a provider), response bombs against
  `max_response_bytes` (pairs with BH.A.8), integer/float mixtures.
- [ ] **BH.J.5** Payload-leak proofs: no raised error's text contains vector values or
  document text (ER.10.4); redaction never serializes vectors into ordinary diagnostics
  (ER.8.4); a credential-shaped string inside a document does not leak into CLI error
  output (ER.11.14's redaction half).
- [ ] **BH.J.6** Sidecar concurrency and disconnect-mid-request cancellation tests
  (ER.11.13's remainder).
- [ ] **BH.J.7** Warn on silently dropped request fields: Ollama ignores `input_type`
  today with no signal (fact 13) — emit a result warning (or `ParameterDropped`-style
  event) when an adapter cannot honor a requested intent.

## 15. Track K — documentation completion (absorbs ER.0.7, ER.12.2, ER.12.4-ER.12.6)

- [ ] **BH.K.1** Task guides under `docs/guides/` (ER.12.2): semantic-search building
  blocks, batch embedding, query/document intents, index/query space compatibility,
  reranking candidates, local embeddings, fallback configuration. Doc examples must run
  offline against the fakes in CI.
- [ ] **BH.K.2** One complete runnable application example owning its own tiny in-memory
  similarity computation explicitly (ER.12.4) — demonstrating the inference/retrieval
  boundary rather than blurring it.
- [ ] **BH.K.3** Sweep the remaining reference pages (ER.12.5): installation matrix,
  integration-paths page, configuration reference, CLI reference (the `embed`/`rerank`
  commands exist but are documented only in `--help`), sidecar endpoint list, error
  catalog staleness.
- [ ] **BH.K.4** Regenerate `llms.txt`, agent instructions, and `anyinfer agents-md` from
  canonical metadata (ER.12.6) — generated, never hand-authored; no ADR identifiers in
  outward text.
- [ ] **BH.K.5** Audit all public docs for stray "embeddings: no" claims (ER.0.7's
  remainder).

## 16. Decisions record

Adopted decisions carried forward from the predecessor plan (binding unless explicitly
reversed):

1. **D-1 First-class operations:** embeddings and reranking are core inference
   primitives, not provider options on generation.
2. **D-2 Text-first:** multimodal embeddings are a later extension.
3. **D-3 Inference boundary:** AnyInfer owns stateless inference and its cross-cutting
   policy — not a vector store or corpus lifecycle (Q2, resolved: stateless-only in core;
   the optional add-on lives in `plans/VECTOR_STORE_ADDON.md`).
4. **D-4 Typed protocols:** provider support is declared per operation; retrieval-only
   providers are valid.
5. **D-5 Safe embedding routes:** cross-target fallback requires embedding-space
   equivalence; same-target retries remain automatic. (Track D closes the gap between
   this decision and the current warn-only behavior.)
6. **D-6 Buffered operations:** no streaming embedding/rerank contract.
7. **D-7 Core batching:** batching is centralized policy; adapters only translate.
8. **D-8 Rerank integrity:** separate-batch scores are never assumed globally comparable.
9. **D-9 Sidecar rerank is AnyInfer-native only** (`POST /v1/anyinfer/rerank`); no
   Cohere/`/v1/rerank` compatibility codec unless a named integration needs one (Q4).
10. **D-10 Offline default:** context reduction remains lexical unless a caller
    explicitly supplies a semantic ranker.
11. **D-11 Context semantic-ranker hook** (ER.0.5/ER.6.9): *resolved by owner,
    2026-08-12* — ship a client/target convenience helper. Architecture constraint: the
    ranker protocol `context.select()` accepts is defined inside `anyinfer.context` (a
    leaf), and the convenience constructor lives client-side, so `anyinfer.context` never
    imports `_client` and the "Context reduction is a leaf consumer" contract holds.
    Default context behavior stays lexical/offline (D-10 unchanged); the helper is
    opt-in. Implemented by BH.F.8.
12. **D-12 Q5, unsafe fallback escape hatch:** adopted per the recommended default —
    explicit, unmistakably named, off by default, marked in results/telemetry.
    Implemented by Track D (BH.D.2).
13. **D-13 Usage stays operation-neutral** (ER.1.20): billed search units are never
    encoded as fake tokens; first-class unit representation is Track E. Track E records
    this in code/DESIGN.md so it stops being implicit.
14. **D-14 Q6, novice aliases** (`embed-small`, `embed-multilingual`, `rerank`):
    resolved "no, not yet" — revisit only once each alias resolves to at least one
    verified hosted and one verified local target (Track B + Ollama would satisfy the
    embedding bar; rerank needs a second verified target).
15. **D-15 Typed error growth** (ER.10.1): *resolved by owner, 2026-08-12* — no new
    exception types. Unsupported-operation, space-mismatch, invalid-vector-response, and
    invalid-rerank-response keep raising `ConfigError` with distinguishing messages
    (AGENTS.md's warning against error-hierarchy growth). The message contracts callers
    can rely on get documented in the error catalog (BH.K.3).
16. **D-16 [-] Demo copy/save actions** (ER.9.14) and **PyInstaller bundle smoke tests**
    (ER.9.11): deliberately deferred backlog — the first is small UX polish (the demo
    truncates vectors safely today but offers no full-vector export path; CLI/SDK do),
    the second is release-gating infrastructure that belongs to the release push (it
    appears in §17's release criteria; it does not block any track).

Implementation-time questions resolved by evidence, not preference (each answer that
changes wire behavior belongs in a dated contract snapshot and a conformance case):

- [ ] Which providers return normalized vectors, and is that model-specific?
- [ ] Which providers distinguish query/document intents, and how do they spell them?
- [ ] Which embedding model ids are stable spaces versus moving aliases?
- [ ] Which providers expose trustworthy batch/token/document limits?
- [ ] Which rerank providers make scores comparable across separately submitted batches?
- [ ] Which providers bill by tokens, requests, documents, or search units?
- [ ] Which local runtimes expose both discovery and operation endpoints in pinned
  releases?
- [ ] What response-size default safely covers common vector batches without enabling an
  unbounded allocation? (Feeds BH.A.8.)

## 17. Acceptance criteria

### This hardening pass (Tracks D, A, B, C)

- [x] Cross-space embedding fallback is refused before dispatch by default, with a tested
  explicit opt-in. *(Track D, 2026-08-12.)*
- [ ] A caller can `embed()`/`rerank()` past a provider's declared limit and get a
  correct, order-preserved result or an honest all-or-error failure, without knowing the
  limit themselves.
- [ ] Cohere passes the same class of wire-mapping and end-to-end tests Ollama has, with
  a dated, cited contract snapshot.
- [ ] `embed()`/`rerank()` calls appear in OTel with a correct non-generation operation
  name and produce a manifest on request, content-free by default.
- [ ] The full suite (`pytest`, `mypy`, `ruff`, `mkdocs build --strict`, `lint-imports`)
  passes with zero new failures against a freshly re-verified baseline (do not assume the
  2026-08-11 "one pre-existing unrelated failure" baseline still holds).

### Feature-complete (all tracks; carried from the predecessor's release bar)

- [ ] Async and sync APIs, CLI, sidecar, demo, configuration, discovery, and docs agree
  on the same semantics.
- [ ] At least one hosted and one local embedding target — and one hosted reranking
  target — pass fake, cassette, and live conformance (a local rerank live lane may be an
  explicit recorded exception).
- [ ] Rerank results preserve caller document identity; malformed indexes cannot escape.
- [ ] Usage, cost, spend policy, telemetry, redaction, manifests, and raw retention are
  tested for both operations.
- [ ] Standalone sidecar bundles pass `/v1/embeddings` and rerank smoke tests on macOS,
  Linux, and Windows (D-16).
- [ ] Generated provider indexes and conformance matrices make no unsupported claims.
- [ ] All public symbols documented; examples run offline; lint, strict typing,
  architecture contracts, tests, and strict docs build pass.

## 18. Notes for whoever picks this up

- §1 and §3 are the context a fresh session needs; the deleted predecessor plan's full
  text (including its per-item audit) is in git history if archaeology is required.
- `dispatch_embed`/`dispatch_rerank` in `_client/operations.py` is the home for all
  batching and aggregation logic. If an adapter starts needing to know about batch limits
  beyond receiving one already-sized wire request, stop — that is the "Adapters never
  orchestrate" contract being violated. Re-run `lint-imports` after each track.
- Never fabricate a "last verified" date on any contract snapshot. If live documentation
  can't be reached, say so explicitly in the snapshot and in this plan's progress log,
  exactly as `contracts/ollama.md`'s embeddings section does for its two unconfirmed
  fields.
- Add to the progress log below with the same "delivered and tested" / "explicitly not
  done" honesty the predecessor plan's log applied to itself — including when a track is
  only partially finished at session end.

## 19. Progress log

- **2026-08-11:** Predecessor plan (`EMBEDDING_RERANKING_SUPPORT.md`) drafted and its
  implementation pass landed the vertical slice summarized in §1. Its §19 log recorded
  delivered/not-done in detail.
- **2026-08-12:** Predecessor's checkboxes audited item-by-item against the code; audit
  surfaced the warn-instead-of-refuse fallback defect (→ Track D) and corrected the test
  count (83, not ~120). This consolidated plan then absorbed every open item, verified
  the fact base in §3 against the code (three parallel audits, corrections flagged
  inline), and replaced the predecessor file, which was deleted. No production code has
  changed under this plan yet.
- **2026-08-12 (owner interview):** Remaining open decisions resolved — scope: all
  tracks, sequentially (D → A → B → C → E → … → K). D-11: client/target convenience
  helper (BH.F.8 added). D-15: keep `ConfigError`; document message contracts. Cohere:
  trial key supplied at `COHERE.key` for opt-in live testing (never committed, never
  logged). Implementation begins with Track D.
- **2026-08-12 (Track D — delivered and tested):** `dispatch_embed` now refuses, before
  any request is sent, a fallback target that is not the identical `provider:model` as
  the route's primary target (`_same_space_target` gate in `_client/operations.py`);
  `EmbeddingRequest.allow_incompatible_fallback` — exposed on `AsyncClient.embed` and
  `Client.embed` — is the explicit opt-in, and an opt-in result always carries a warning
  naming both targets. The old post-success warning branch, which was unreachable dead
  code, was removed. `docs/concepts/embeddings.md` updated to describe the shipped
  behavior (its previous text promised a per-target compatibility-id mechanism that does
  not exist yet — that is BH.G.4). Gates: full pytest (only the documented pre-existing
  demo-app sort-order failure, re-confirmed), mypy clean, ruff clean on `src/`+`tests/`
  (one pre-existing S101 in `scripts/pin_catalog.py`, untouched, confirmed on a clean
  tree), `lint-imports` 4/4 kept, `mkdocs build --strict` clean. Explicitly not done
  here: telemetry/manifest marking of the opt-in path (Track C dependency, by design);
  CLI/sidecar exposure of the opt-in flag (decide with BH.F.5/ER.9.4 whether operators
  need it). Housekeeping: `COHERE.key` added to `.gitignore`.
- **2026-08-12 (second owner interview):** Commit cadence: one commit per gate-passing
  track, directly on `develop` (standing authorization; Track D and the plan
  consolidation are the first two commits under it). Track I: all four provider groups
  confirmed in scope for this run. Track B: approved to spend trial quota on live smokes
  and early cassettes. BH.F.7: resolved as *build* minimal embed/rerank probes, not
  defer.
