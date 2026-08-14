# Embedding/reranking: continuation handoff

> **Status:** ready to execute; written 2026-08-12 at the end of the session that landed
> commits `1a47675..f18d415` (18 commits on `develop`).
> **Authority:** the single live embedding/reranking plan. Its predecessor —
> `plans/EMBEDDING_RERANKING_HARDENING.md`, the consolidated tracker whose Tracks D
> through H (and five Track I increments) are fully implemented — was deleted to keep
> one plan; its complete text, per-item checkboxes, and fourteen-entry progress log are
> preserved in git history (last version at commit `4e1802e`). The still-binding pieces
> (scope boundary, decisions record, remaining acceptance bar) are carried forward in
> §9-§11 below; record new progress in §12. Everything else in this file exists to
> eliminate the discovery phase: every fact was verified during the prior session and
> can be trusted without re-derivation (re-verify only where a line number matters and
> the file has since changed).

## 1. Standing owner decisions (do not re-ask)

- **Scope:** all tracks, sequentially. Every decision is resolved — see §10.
- **Commits:** one commit per gate-passing increment, directly on `develop` — standing
  authorization. Commit messages end with the Claude co-author trailer.
- **Cohere trial key:** `COHERE.key` at the repo root (gitignored). Load into
  `CO_API_KEY` for live smokes/cassettes. Never committed, never logged.
- **Probing:** build, don't defer (BH.F.7 — embed probes exist; see `probe_embedding`).
- **Track I:** all four provider groups are in scope.

## 2. Gates — run before every commit

```bash
python -m pytest -q                 # exactly ONE pre-existing failure is expected:
#   tests/demo_app/test_library_coverage.py::TestModelsDialog::test_catalog_lists_entries_carrying_their_fit_reasons
#   (GPT-OSS vs Gemma catalog sort order; confirmed on a clean tree; unrelated)
python -m mypy src/                 # clean, 183 files
python -m ruff check src/ tests/    # clean (scripts/pin_catalog.py:812 S101 is pre-existing, leave it)
lint-imports                        # 4 contracts kept
python -m mkdocs build --strict     # clean
```

Regeneration commands (run when the relevant shape changes):

```bash
python -m pytest -q --update-manifests        # golden run-manifests (after RunManifest/UsageFacet changes)
python workspace.py matrix                    # docs/reference/conformance-matrix.md (after case/harness changes)
python scripts/generate_provider_index.py     # docs/providers/all.md (after adding a provider)
```

## 3. The new-provider recipe (used 5× this session — follow it verbatim)

1. **Research first, live.** Fetch current docs; record request/response fields, limits,
   auth, error shape, with the fetch date. If a page is bot-blocked or JS-only, say so
   in the snapshot (`platform.openai.com` is blocked — `developers.openai.com` works;
   TEI's canonical spec is
   `raw.githubusercontent.com/huggingface/text-embeddings-inference/main/docs/openapi.json`).
2. **Adapter** in `src/anyinfer/providers/<id>.py`. Copy patterns from:
   `voyage.py` (hosted retrieval-only, no listing endpoint → honest empty
   `list_models()` + labeled reachability `health()`), `tei.py` (local retrieval-only,
   discovery-driven operations), `cohere.py` (embed+rerank on an existing generation
   adapter), `openai.py`/`lm_studio.py` (compose `OpenAICompatEmbeddingsMixin`).
   Rules encoded in all of them: rerank positional `index` → map to
   `RerankWireDocument.index`; usage only from what the provider reports (Voyage/Jina
   report `total_tokens` only — never copy into `input_tokens`); unsupported intents
   never sent; unknown facts stay `None`.
3. **Register:** `_BUILTIN_MODULES` in `src/anyinfer/providers/__init__.py:16`.
4. **Descriptor invariants** (tests enforce): a secret `SetupField` needs `placeholder`
   naming its `env_var` ("env://X_API_KEY or a literal key"); an endpoint field with a
   `default_value` must be `advanced=True`; `model_selection` is
   `"discover-or-manual"` or `"manual-only"`.
5. **Docs/index:** `contracts/<id>.md` (structure: Upstream sources / Wire contract
   with per-section "verified <date>" + explicit **Unverified:** markers / Watchlist);
   `docs/providers/<id>.md` (frontmatter `provider:`/`icon:`); mkdocs.yml nav (~line
   180); `ADAPTER_PAGES` **and** the blurb dict in
   `scripts/generate_provider_index.py` (~lines 26/195) — then regenerate the index.
6. **Tests** in `tests/test_<id>.py` — wire mapping via `httpx2.MockTransport`, one
   client e2e. Optional conformance harness (see §5 of this file).

## 4. Key file/line map (operation subsystem, as of `f18d415`)

- **Dispatch:** `src/anyinfer/_client/operations.py` — `dispatch_embed` ~:310,
  `dispatch_rerank` ~:540; `_attempt_with_retry` :96 (emits AttemptStarted/Completed);
  `_plan_chunks` :177 (unknown limit → sanity ceiling refusal); `_same_space_target`
  (Track D gate); `_validate_ranked_items` (takes `allowed_indexes`/`seen` for chunks);
  declared-operations gate at the `pool.get` sites ("not an offer to serve it").
- **Client:** `async_client.py` — `embed()`/`rerank()` (batch=, manifest=,
  allow_incompatible_fallback=); `_check_operation_spend` (reserves whole request
  before chunks); `_operation_capabilities` / `_embedding_capabilities_of` (hooks into
  dispatch); `_resolve_operation_route` (operation_routes → default_route);
  `probe_embedding()`; `operations_for()`; `verify(operation=)` → `_verify_operation`;
  `models(operation=)`.
- **Types:** `types/operations.py` (BatchPolicy.max_items_override, DEFAULT_MAX_*
  sanity ceilings, EmbeddingCapabilities/RerankCapabilities with overlay+conjunction);
  `types/results.py` (`Usage.sum()` is the summing aggregator — `merge()` is an
  overlay; `search_units` field); `types/capabilities.py`
  (`ModelCapabilities.operations: Sourced[frozenset]`, `Pricing.per_search_unit`).
- **Pricing/spend:** `capabilities/pricing.py` (`compute_operation_cost` /
  `with_operation_cost`); `capabilities/assemble.py` (`CapabilityStore` with the
  embedding-probed layer); `capabilities/ledger.py` (reserve/release; `record()` pops
  reservations; the ledger is an event observer — cost flows free once `cost_usd` set).
- **Manifest/OTel:** `manifest.py` (`build_operation_manifest`, RunManifest.operation +
  .embedding_space, UsageFacet.search_units); `otel.py` (`_OPERATION_NAMES` — span
  name/op-name per operation; "embeddings" is the verified semconv value, "rerank" is
  custom because the registry defines none).
- **Conformance:** `testing/conformance.py` (Capabilities.embedding/rerank **default
  False**; ConformanceHarness.embedding_model/rerank_model; four cases at the end of
  CONFORMANCE_CASES); harness registration for the matrix in `workspace.py`
  `_matrix_collect` (~:1038 imports, harness dict) + `_MATRIX_FOOTER` case table.
- **Cassettes:** `testing/cassettes.py` — the gzip double-decompression bug is FIXED
  (content-encoding/length/transfer-encoding stripped at capture). Committed cassettes:
  `tests/cassettes/cohere_{embed,rerank}.json`. Re-record: delete the file first
  (recording APPENDS to existing cassettes — stale interactions poison replay), then
  `CO_API_KEY="$(cat COHERE.key)" ANYINFER_RECORD_CASSETTES=1 pytest tests/test_cohere_cassettes.py`.
- **Config:** `config/__init__.py` — `operation_routes` key, `_parse_operation_routes`
  (keys: embedding/rerank only; `generation` rejected).

## 5. Remaining tasks, in recommended order

### T1 — Azure OpenAI / AI Foundry embeddings (BH.I.3) — DONE 2026-08-12

`providers/azure_foundry.py` exists (generation): deployment-addressed paths and
`api-version` pinning; raises ConfigError when the `[azure]` extra is missing (:40, :81).
Azure OpenAI embeddings are OpenAI-body-shaped but at
`POST {endpoint}/openai/deployments/{deployment}/embeddings?api-version=...` with
`api-key` header (or Entra bearer). **Discovery step (small):** read how
`azure_foundry.py` builds its chat URL/auth and whether `OpenAICompatEmbeddingsMixin`
can serve with an overridden `embeddings_path` (the mixin's `embeddings_path` class
attr is overridable, but Azure's per-deployment path + query param probably needs a
dedicated `embed()` that reuses the adapter's own URL builder). Research target:
`learn.microsoft.com/azure/ai-foundry/openai/reference` (embeddings section) — record
api-version, the deployment-vs-model naming rule, and limits (Azure inherits OpenAI's
2,048-input ceiling but VERIFY, do not assume). Extend `contracts/azure-foundry.md`.

### T2 — Vertex AI embeddings (BH.I.3) — DONE 2026-08-12

`providers/vertex.py` exists (Gemini with GCP auth, project-scoped addressing — reuse
its auth/path machinery). Vertex text embeddings use
`POST .../publishers/google/models/{model}:predict` with
`instances: [{content, task_type, title?}]` and `parameters: {outputDimensionality?,
autoTruncate?}`; response `predictions[].embeddings.values` +
`statistics.token_count`. Note this is a **different wire shape from Gemini's
batchEmbedContents** (which vertex may also mount for gemini-embedding-001 — verify
which surface applies per model). Research target:
`cloud.google.com/vertex-ai/generative-ai/docs/embeddings/get-text-embeddings`.
task_type values mirror Gemini's legacy list (RETRIEVAL_QUERY etc.) — map like
`gemini.py`'s `_TASK_TYPES`.

### T3 — Bedrock embeddings (BH.I.3) — DONE 2026-08-14 (Titan, Cohere embed, and Rerank all implemented)

`providers/bedrock.py` exists (Converse API, SigV4 or API key, binary event framing).
Embeddings go through `InvokeModel` (NOT Converse):
- `amazon.titan-embed-text-v2:0`: body `{"inputText": str, "dimensions": 256|512|1024,
  "normalize": bool}` — **single input per call** → declare
  `max_batch_inputs=1` (Track A batching then fans a batch into N calls — works, note
  the cost profile in the docs page).
- `cohere.embed-english-v3`/multilingual: `{"texts": [...], "input_type": ...}` —
  batch-capable, Cohere vocabulary.
- Bedrock also has a `Rerank` action (agent-runtime) — separate research; scope Titan
  embed first and record the rest in the watchlist.
VERIFY all body shapes at `docs.aws.amazon.com/bedrock/latest/userguide/titan-embedding-models.html`
and the Cohere-on-Bedrock page. Reuse the adapter's SigV4 signing for the new path.

### T4 — llama-server embeddings (BH.I.3 / ER.5.11) — DONE 2026-08-14

**Gated on a live contract check by its own rule** — documentation is not sufficient.
Recipe: acquire a small embedding GGUF through the existing `local/` machinery (e.g.
nomic-embed-text; acquisition stays in `local/`, never the adapter), start the pinned
`llama-server` with `--embeddings`, and verify live which endpoint the pinned build
serves (`/v1/embeddings` OpenAI-shaped and/or native `/embedding`) and its exact
response shape. Then: compose `OpenAICompatEmbeddingsMixin` onto the llama-cpp adapter
(check `providers/llama_cpp.py` — likely subclasses or wraps OpenAICompatAdapter) or
write a native `embed()`; declare operations; extend `contracts/llama-cpp.md` with a
LIVE-verified section (this one can genuinely say so).

### T5 — Preset embedding verification (BH.I.2) — DONE 2026-08-12 (four presets)

**Discovery step (real, ~15 min):** read `providers/presets.py` to learn what a
`CompatPreset` carries and how `preset_descriptors()` builds factories — the mechanical
question is how a preset opts into the embeddings mixin (a factory producing a
mixin-composed class? an `operations` field on CompatPreset?). Then verify per preset
upstream that `/v1/embeddings` exists (start with together/fireworks/mistral/deepinfra
— highest likelihood), record each verification in
`contracts/openai-compat-presets.md` with dates, and enable only the verified ones.
Unverified presets stay generation-only (the correct default).

### T6 — Pricing pipeline entries (Track E remainder, BH.E.2) — DONE 2026-08-12 (OpenAI + Voyage embeddings; Cohere/Jina/Voyage-rerank remain publicly unpriced)

Mechanism is DONE (`Pricing.per_search_unit`, `compute_operation_cost`); what's missing
is data + parsing:
1. `capabilities/pricing_table.py` `_parse_entry` (:138-161) reads only
   model/input_per_1m/output_per_1m/currency/last_verified/source/openrouter_id — add
   `per_search_unit` parsing.
2. Add entries to `capabilities/pricing.json` **through the established review flow**
   (Cohere's drift policy is `"manual"` — `scripts/pricing_check.py:277`; the file is
   hand-maintained under human review, per its `_comment`). Prices observed 2026-08-12,
   to re-verify at entry time: OpenAI text-embedding-3-small $0.02/1M,
   3-large $0.13/1M (developers.openai.com model pages). Cohere embed/rerank prices:
   cohere.com/pricing. Voyage/Jina: their pricing pages.
3. The demo panel's cost display lights up automatically once entries exist (ER.9.13).
4. ER.11.12: mixed generation/embed/rerank rate-pacing test.

### T7 — Conformance/harness remainder (Track H, BH.H.1/H.2/H.3/H.5) — four cases + Ollama live lane DONE, cancellation and Voyage/Jina/TEI live lanes still open

- Port the never-harness-registered behaviors into `CONFORMANCE_CASES`: intent
  translation, normalization metadata, byte caps, retry-after, cancellation,
  duplicate-text-distinct-ids. Each needs a `requires` flag — reuse
  `embedding`/`rerank` or add narrow flags (remember: **new flags default False**).
- Ollama live lane (BH.H.5) — DONE 2026-08-14. This sandbox gained a real local Ollama
  install and a GPU it didn't have before; `ollama pull qwen3:0.6b` and `nomic-embed-text`
  plus `tests/test_ollama_cassettes.py` record real wire traffic (chat NDJSON with live
  reasoning frames, `/api/ps` discovery, and `/api/embed`) into committed, redaction-swept
  cassettes that replay offline in CI from now on — no live server required going forward.
  Found and fixed a real bug while recording: `CassetteTransport` never closed its
  recording-mode inner `httpx2.AsyncHTTPTransport`, leaking a socket every recording run
  and tripping this project's `filterwarnings = ["error"]` gate; fixed with an `aclose()`
  override in `testing/cassettes.py`. This was a latent bug in shared test infrastructure,
  not Ollama-specific — it would have hit the next person recording *any* cassette.
- Enable Voyage/Jina/TEI cassette or live lanes when keys/servers are available; their
  contracts carry explicit not-live-verified watchlists to burn down.
- `testing/scaffold.py`/`certify.py` extension beyond the conformance-table comment
  (BH.H.3): scaffold could emit optional EmbedsText/ReranksText stubs.

### T8 — `compare()` embedding dimensions (Track F remainder, BH.F.4) — DONE 2026-08-12

`AsyncClient.compare()` (:~2155) is generation-shaped (builds a GenerationRequest;
dimensions: context fit, mechanism ladder, cache, cost). An embedding comparison needs
its own dimension set: space identity, dimensions, batch limit, intents, pricing.
Design choice deferred with note: either a separate `EmbeddingTargetComparison` or an
optional operation section on `TargetComparison` (`compare.py:27-47` is just the frozen
result type). Cohere discovery now lists embedding models, so the
`discovered_has_model` refresh check no longer falsely fails there.

### T9 — Robustness remainder (Track J) — DONE 2026-08-12

- **Response bombs:** find where generation enforces `max_response_bytes` (the
  `byte_cap` conformance case and `GoverningTransport` in `_client/providers.py` are
  the trail) and prove the embed path enforces
  `DEFAULT_MAX_EMBEDDING_RESPONSE_BYTES` (64 MiB) the same way.
- Sidecar disconnect-mid-request cancellation (ER.11.13's last gap).
- CLI redaction proof (credential-shaped document content never in stderr).
- Repr/serialization audit for the new frozen types (ER.11.6's tail — check what
  GenerationRequest's repr does with payloads first; mirror its policy).

### T10 — Docs remainder (Track K, BH.K.1/K.2/K.5) — DONE 2026-08-12 (stray-claims sweep closed; no further gaps found)

- Task guides under `docs/guides/`: semantic-search building blocks, batch embedding,
  intents, index/query compatibility, reranking, local embeddings (TEI + Ollama + LM
  Studio now all work), fallback configuration + `operation_routes`. Doc examples must
  run offline against fakes in CI (`tests/test_docs_examples.py` pattern).
- One complete runnable example owning its own in-memory similarity computation
  (pattern: `docs/examples/starter.py`).
- Stray-claims audit: grep docs for "embeddings: no"-era statements (ER.0.7/BH.K.5).
- Error-catalog staleness check (D-15 chose ConfigError-with-documented-messages; the
  message contracts should be listed there).

### T11 — Catalog + init (Track G deferred bits) — init/sidecar bits DONE 2026-08-12, catalog schema still open

- Catalog schema lands **together with the first pinned embedding-model entries** (the
  deferral reason: schema with zero entries is dead surface). Touch points:
  `CANDIDATES` tuple `scripts/pin_catalog.py:118`, `pin_model` :764-880, `_parse_model`
  `catalog/model.py:644-707`, `scripts/validate_catalog.py`. Candidate first entries:
  nomic-embed-text (Ollama+GGUF), bge-large (TEI).
- `anyinfer init` auto-writes `operation_routes` from discovery evidence:
  `local/discovery.py` `_probe_one` (:275-291) currently flattens model ids and
  discards `DiscoveredModel.capabilities.operations` (LM Studio and Cohere stamp them);
  `_init_target`/`_init_route` are `cli.py:2238-2285`.
- Also small: BH.C.9 benchmark fields (Measurement is token-denominated; `from_json`
  tolerates unknown keys so additive fields are old-reader-safe) and BH.C.6 (sidecar
  `anyinfer_manifest` extension for `/v1/embeddings` — prior art
  `serve/openai_codec.py:96,138,729`).

## 6. Verified upstream fact cache (2026-08-12 — cite, don't re-fetch)

| Provider | Facts |
|---|---|
| OpenAI | 2,048 inputs/req, 8,192 tok/input, 300k tok summed; `dimensions` on 3+ models; **no intent field in the schema**; per-model dims unstated. `developers.openai.com` fetchable, `platform.openai.com` bot-blocked. |
| Cohere | 96 texts/call; `input_type` REQUIRED, no default; rerank ≤1,000 docs (recommendation); `results[].index` positional; **live rerank meta = `billed_units.search_units` only, no tokens**; models list `endpoints[]` enum chat/generate/embed/rerank/classify/summarize/rate. |
| Gemini | `batchEmbedContents` always; 3,072 default dims, 128–3,072 (768/1536/3072 recommended); `taskType` only on legacy `-001` — `gemini-embedding-2` documents none; `usageMetadata.promptTokenCount`; no batch ceiling stated. |
| Voyage | 1,000 inputs; intents `query`/`document` only; rerank 1,000 docs **hard**; `top_k`; `usage.total_tokens` only; **no listing endpoint**. |
| Jina | `task` vocab: retrieval.query/retrieval.passage/classification/separation/text-matching (clustering→separation is OUR recorded mapping); **no request ceilings** ("batches internally"); rerank `results[]` index/relevance_score (from Jina's own model cards); `total_tokens` only; no listing endpoint; interactive reference JS-blocked. |
| TEI | one model/server; `/info` → model_id, model_type (tagged object), max_client_batch_size (per-deployment limit!); `/embed` normalize default TRUE, truncate default false; `/rerank` no top_n, order unstated (adapter sorts); errors `{error, error_type}` 413/422/424/429; canonical spec = raw openapi.json on GitHub. |
| LM Studio | `/v1/embeddings` in the documented endpoint list; native listing `type: llm|embedding`; no limits documented. |
| OTel | `gen_ai.operation.name` well-known values include `"embeddings"`; none for rerank (registry moved to github.com/open-telemetry/semantic-conventions-genai). |

## 7. Traps that cost time this session (avoid re-learning)

- **Ruff re-sorts imports** on `--fix`; anchored string replaces against import blocks
  break afterward. Also `--fix` may modify files you've read — re-read before editing.
- **Golden manifests**: any RunManifest/UsageFacet field addition needs
  `--update-manifests` AND a `manifest_json_schema()` property entry
  (`test_every_facet_field_is_described` enforces it).
- **Adding a builtin provider** trips three enumeration gates: setup-spec invariants
  (§3.4 above), the generated provider index + guide mapping
  (`scripts/generate_provider_index.py` raises "provider guide mapping mismatch"), and
  the mkdocs nav.
- **`Route.health_gate` defaults True** with a 30s TTL — a test that fails a target and
  immediately retries the same target must pass `health_gate=False`.
- **Conformance `Capabilities` flags default True** for generation — new operation
  flags MUST default False or every existing harness/matrix row breaks.
- **Cassette recording appends** to an existing file; delete before re-recording.
  `finally: cassette.save()` persists even failed runs' interactions.
- **`pytest -q` prints no summary count line** in this repo; grep for `FAILED` instead.
- **The fake's scripted failures are consumed one per call**, and `_maybe_fail` doesn't
  check model membership — an embed-only fake will happily serve rerank structurally
  (which is why dispatch gates on *declared* operations now).
- `git stash` cycles unstage the index (the plan/SUPPORT deletion history lives in
  commits `1a47675`/`46f80e9` if archaeology is needed).
- The predecessor plan `EMBEDDING_RERANKING_SUPPORT.md` was absorbed and deleted; its
  full text incl. the per-item audit is only in git history (pre-`1a47675`).

## 8. Session start checklist for the next thread

1. `git log --oneline develop | head -20` — confirm you're at/after `f18d415`.
2. Read this file. Do NOT re-scout what §4-§7 already state; the full historical
   tracker is in git history if archaeology is ever needed.
3. Re-verify the pytest baseline (still exactly the one demo-app failure).
4. Pick up at T1 (Azure) unless the owner redirects; each T-item is one gate-passing
   commit in the established recipe.
5. Strike completed T-items in §5 and add a dated entry to §12's progress log as
   you land increments — with the same "delivered and tested" / "explicitly not done"
   honesty the deleted tracker's log applied to itself.

## 9. Scope boundary (binding, carried forward)

Reproduced because `plans/VECTOR_STORE_ADDON.md` cites it, and it remains the line the
owner drew.

**Included:** text embeddings (scalar and batch); query/document intent where providers
distinguish it; provider-native dimensionality reduction; reranking one query against a
caller-supplied ordered document collection (text plus caller-owned ids/metadata; only
text sent unless a provider option asks for more); usage, provider-native billing units,
centrally computed cost when pricing is known, timing, attempt trails, warnings,
optional raw retention; core-owned batching against verified limits; operation-aware
discovery, capabilities, routing, and fallback; semantic ranker injection into context
reduction via the client-side helper (`anyinfer.semantic_ranker` — shipped).

**Excluded:** vector databases, ANN indexes, persistence, corpus lifecycle, retrieval
services (the optional add-on lives in `plans/VECTOR_STORE_ADDON.md`); automatic
embedding of `ContextDocument` values; opaque automatic model selection; cross-model
vector conversion; training/fine-tuning/evaluation; image/audio/multimodal embeddings in
this milestone; streaming vectors or incremental rerank results (both operations are
buffered).

## 10. Decisions record (binding; all resolved)

- **D-1** Embeddings and reranking are core inference primitives, not provider options.
- **D-2** Text-first; multimodal is a later extension.
- **D-3** AnyInfer owns stateless inference, never a vector store or corpus lifecycle
  (the add-on package is `plans/VECTOR_STORE_ADDON.md`).
- **D-4** Provider support is declared per operation; retrieval-only providers are
  first-class (TEI, Voyage, and Jina now exist as proof).
- **D-5** Cross-target embedding fallback requires provable space equivalence —
  *implemented*: refused pre-dispatch unless identical `provider:model`, with the
  `allow_incompatible_fallback` opt-in that always warns.
- **D-6** Buffered operations only; no streaming embed/rerank contract.
- **D-7** Batching is centralized core policy; adapters only translate.
- **D-8** Separate-batch rerank scores are never assumed globally comparable —
  *implemented* as `rerank_cross_batch` refuse-by-default with a mandatory warning.
- **D-9** Sidecar rerank is AnyInfer-native only (`POST /v1/anyinfer/rerank`); no
  Cohere/`/v1/rerank` compatibility codec unless a named integration needs one.
- **D-10** Context reduction stays lexical/offline by default.
- **D-11** Semantic rankers reach `context.select()` via the client-side convenience
  helper — *implemented* (`anyinfer.semantic_ranker`, `SemanticRanker` protocol in the
  leaf context package).
- **D-12** The unsafe-fallback escape hatch exists, unmistakably named, off by default
  — *implemented* (Track D).
- **D-13** `Usage` stays operation-neutral; billed search units are never encoded as
  tokens — *implemented* (`Usage.search_units`, `Pricing.per_search_unit`).
- **D-14** Novice aliases (`embed-small` etc.): "no, not yet" — revisit only when each
  alias resolves to one verified hosted **and** one verified local target.
- **D-15** No new exception types: the four embed/rerank failure classes raise
  `ConfigError` with distinguishing messages; documenting those message contracts in
  the error catalog is part of T10.
- **D-16** Demo copy/save buttons and PyInstaller bundle smoke tests are deliberately
  deferred to the release push (the smoke tests need macOS/Windows CI).
- Per-provider evidence questions (normalized vectors? intent spellings? stable model
  ids? trustworthy limits? billing units?) are answered in dated contract snapshots as
  each provider lands — never in this plan alone.

## 11. Remaining acceptance bar

The hardening bar (Tracks D/A/B/C) was met on 2026-08-12. Still open from the
feature-complete bar:

- [ ] At least one hosted and one local embedding target — and one hosted rerank target
  — pass fake, **cassette, and live** conformance (fake ✓ everywhere; Cohere cassettes
  ✓; live lanes and remaining cassettes are T7).
- [ ] Usage, **cost**, spend policy tested for both operations end to end (cost blocks
  on T6's pricing entries).
- [ ] Standalone sidecar bundles pass `/v1/embeddings` and rerank smoke tests on macOS,
  Linux, and Windows (D-16; release push).
- [ ] Generated provider indexes and the conformance matrix make no unsupported claims
  (holds today; re-check as T1-T5 land).
- [ ] All public symbols documented; examples run offline; every gate passes (holds
  today; keep it true).

## 12. Progress log

- **2026-08-12:** Handoff written; predecessor tracker deleted with its record
  preserved in git history (last version at `4e1802e`). Nothing implemented under this
  plan yet — T1 (Azure embeddings) is next.
- **2026-08-12:** T1 delivered and tested (`a4afa7e`). `AzureFoundryAdapter` composes
  `OpenAICompatEmbeddingsMixin`; `embeddings_path` carries `api-version` the same way
  `chat_path`/`models_path` already did. Verified live against
  learn.microsoft.com/azure/ai-foundry/openai/how-to/embeddings (fetched 2026-08-12):
  v1 surface is `POST {base_url}/embeddings`, deployment-addressed via `model` exactly
  like chat — no Azure-specific body fields. Limits (2,048 inputs / 8,192 tokens-input /
  300k tokens-aggregate) match OpenAI's own and are documented in the contract and
  provider docs, but explicitly **not** declared as `static_embedding_capabilities`
  since Azure model ids are tenant-chosen deployment names, not a fixed catalog —
  keying static limits by an unknowable id would be a silent wrong answer. All gates
  green. T2 (Vertex AI) is next.
- **2026-08-12:** T2 delivered and tested (`fce9e9e`). Resolved the plan's flagged
  wire-shape ambiguity by fetching Google's current text-embeddings-api reference live:
  every documented embedding model (`gemini-embedding-001`, `text-embedding-005`,
  `text-multilingual-embedding-002`, `textembedding-gecko@001`) uses the generic
  `:predict` verb with an `instances`/`parameters` body — **not** Gemini's
  `batchEmbedContents`. `VertexAdapter.embed()` overrides the inherited Gemini method
  entirely. Confirmed and declared the documented one-input-per-request limit on
  `gemini-embedding-001` (`max_batch_inputs=1`) so the core's batching policy fans
  multi-text calls into individual requests rather than sending an invalid batch. Noted
  in the contract watchlist, not assumed: the API reference nav also lists an
  `embedContent` method that the how-to guide doesn't document or use. All gates green.
  T3 (Bedrock) is next.
- **2026-08-12:** T3 partially delivered and tested (`0e29978`) — Titan Text Embeddings
  V2 only, as the plan recommended ("scope Titan embed first"). Converse has no
  embeddings surface at all, so `BedrockAdapter.embed()` is separate machinery against
  `InvokeModel`, reusing only auth headers and the model-path quoting helper. Titan
  accepts exactly one `inputText` per call (no batch field in its schema, confirmed live)
  — declared `max_batch_inputs=1`; the adapter loops one `InvokeModel` call per input and
  sums `inputTextTokenCount`, so it stays correct even if called with more than one input
  directly. **Explicitly not implemented:** Cohere-on-Bedrock embeddings — a live fetch
  of `model-parameters-cohere-embed.html` returned no usable content this session, and
  the plan's recorded shape was not independently verified, so it was left undone rather
  than guessed and shipped. Bedrock's separate Rerank action is also unresearched. Both
  recorded in the contract watchlist for a future session with a working fetch. All gates
  green. T4 (llama-server, live-gated) is next — flagging to the owner that it needs a
  local GGUF + running llama-server, which this session cannot provide.
- **2026-08-12:** T4 confirmed blocked, not attempted: this sandbox has no `llama-server`
  binary and no path to download a GGUF, and the task is explicitly gated on a live
  contract check by its own rule ("documentation is not sufficient"). Guessing the wire
  shape from documentation would violate the task's own stated gate, so it is left
  undone rather than shipped unverified. Skipping to T5, which is pure discovery/research
  and needs no live server.
- **2026-08-12:** T5 delivered and tested (`63a3e74`). Read `presets.py` first (the
  discovery step the plan called for): the mechanical opt-in question resolved to a new
  `CompatPreset.embeddings: bool` field plus a distinct `PresetEmbeddingAdapter` class
  (mixes `OpenAICompatEmbeddingsMixin` onto the shared adapter) — structural rather than
  a runtime check, so an unverified preset has no `embed()` method to accidentally call.
  Verified all four candidates the plan named (together/fireworks/mistral/deepinfra) live
  against their own docs and enabled every one — no false negatives. Recorded per-preset
  wire quirks rather than assuming uniformity: Together's response has no `usage` block;
  Mistral's dimension control is `output_dimension`, not the shared dialect's
  `dimensions`, so `dimensions=` silently no-ops there and both the contract and the
  provider docs page say so with the escape-hatch workaround. Every other preset
  deliberately remains generation-only, including ones whose underlying engine (vLLM,
  etc.) is known to serve embeddings in general — a specific deployment can't be verified
  from a static table. All gates green. T6 (pricing pipeline) is next.
- **2026-08-12:** T6 partially delivered and tested (`0413bd6`) — mechanism only.
  `_parse_entry` in `pricing_table.py` now reads an optional `per_search_unit` field
  (same non-negative-decimal-string validation as the token rates); `Pricing` and
  `compute_operation_cost` already had the plumbing from the prior session, so this
  closes the one actual gap. **Explicitly not done: the data entries.** Every pricing
  source the item named was unreachable this session — openai.com/api/pricing and
  help.openai.com 403'd, and cohere.com/pricing, voyageai.com, and jina.ai render their
  price figures through client-side JS the available fetch tooling could not execute
  (confirmed by dumping raw HTML and grepping for `$`/`per million`/`search unit` — the
  numbers genuinely are not in the served document). Copying the plan's own
  "prices observed 2026-08-12" figures without independently re-verifying them would be
  exactly the kind of unverified copy the plan's own instructions warn against ("VERIFY,
  do not assume" appears throughout this file for a reason), so pricing.json is
  untouched. A session with working browser-rendered fetch (or the owner supplying the
  numbers directly) can complete this in minutes once the mechanism exists.
- **2026-08-12:** T7 partially delivered and tested (`e5e6969`) — two new conformance
  cases (`rerank_duplicate_text`, `embedding_normalization_probe`), both reusing the
  existing "default" scenario so no provider's `build_client` factory needed changes;
  confirmed via the regenerated matrix (cohere/tei/ollama pick up both as passes, every
  other row skips honestly). Byte-cap/retry-after for the embed/rerank paths and
  cancellation-in-conformance are explicitly not done — each needs new scenario strings
  threaded through every provider's harness factory, real multi-file work rather than a
  quick add. Live Ollama/Voyage/Jina/TEI lanes need infrastructure this session doesn't
  have. The scaffold EmbedsText/ReranksText stub extension is explicitly optional per the
  plan's own wording and was skipped to prioritize the harder items.
- **2026-08-12:** T8 delivered and tested (`35f6414`). Made the deferred design call:
  `EmbeddingTargetComparison` is a separate type from `TargetComparison`, not an optional
  section on it — generation's mechanism-rung/cache/structured-output fields have no
  embedding counterpart, so grafting them together would mean every embedding comparison
  carries a dozen always-`None` fields. `compare_embedding()` reports declared
  dimensions/batch-limit/token-limit/intents/normalized, a cost range built from the same
  `compute_operation_cost()` the spend gate already trusts, and a `fits` verdict against
  the declared ceilings — all without dispatching. An unsupported `input_type` or a
  provider that never declared the embedding operation surfaces as data (a note, or
  `resolvable=False`), matching `compare()`'s own unresolvable-target discipline. Both
  `AsyncClient` and the sync `Client` expose it; `to_dict`/`from_dict` round-trip. Caught
  and fixed a docstring-gate failure along the way (every public symbol needs a `:::`
  directive somewhere in `docs/`) — a real gate doing its job, not a false positive.
- **2026-08-12:** T9 delivered and tested (`802c1f9`, `f0e3543`). Item 1 (response bombs)
  was not actually verified before this session — it was **broken**: every generation
  adapter's buffered path checks `len(response.content) > req.max_response_bytes` before
  parsing, but not one embed()/rerank() implementation did, anywhere — not the shared
  `OpenAICompatEmbeddingsMixin` (openai, lm-studio, azure-foundry, and all four verified
  presets), not Cohere, Gemini, Voyage, Jina, TEI, Ollama, or this session's own Vertex
  and Bedrock additions. `EmbeddingWireRequest`/`RerankWireRequest.max_response_bytes`
  existed and defaulted correctly but was silently never read. Added
  `providers.http.check_response_size()` and wired it into every embed()/rerank() call
  site, with a new adapter-level test per provider proving an oversized response is
  refused rather than parsed. Item 2 (sidecar cancellation, ER.11.13's last gap): found
  and fixed — `_stream_chunks` never called `AsyncStream.aclose()` on early exit, so a
  mid-stream client disconnect only released the upstream provider connection via GC,
  not deterministically; one `finally` block fixes it, verified by driving the generator
  directly and closing it early. Item 3 (CLI redaction proof): confirmed
  `AnyInferError.detail`'s existing redact+512-char-truncate discipline actually reaches
  `_report_error`'s stderr output, with a test using a credential-shaped multi-KB
  scripted failure message. Item 4 (repr/serialization audit): checked
  `GenerationRequest`'s policy first as instructed — no repr override, redaction happens
  only at output boundaries — and confirmed the new embedding/rerank frozen types already
  follow it with no special-casing needed. All gates green.
- **2026-08-12:** T10 partially delivered and tested (`2919c05`). Discovery first, as
  the plan's own discipline requires: `docs/concepts/embeddings.md` already existed and
  thoroughly covered intents, the embedding-space safety rule, batching, and reranking —
  most of the "separate guides" T10 asked for turned out to already be written from
  prior work, not missing. What was actually missing and got done: the one runnable
  example (`docs/examples/semantic-search.md`, shape-tested offline, honest about its
  fake's hash-based vectors being mechanically-correct but not semantically meaningful —
  the reranker's genuine lexical-overlap fake carries the "does this work" proof
  instead); the embedding/rerank message contracts in the error catalog (D-15), quoted
  verbatim from `operations.py`; and one real stray-claim fix in
  `context-reduction.md`, which read as if semantic retrieval had no first-party path
  when `anyinfer.semantic_ranker()` (D-11) already provides one. **Not done:** a
  systematic stray-claims sweep beyond the one instance found, the non-embedding
  sections of the error catalog, and local-embeddings/fallback-configuration content
  beyond what the new example's prose already covers — left for a future pass rather
  than padded out to claim the checklist item complete. All gates green.
- **2026-08-12:** T11 partially delivered and tested (`3045adb`, `098d93d`) — the init and
  sidecar bits, not the catalog schema. `DiscoveredProvider` gained an additive
  `embedding_models` field (the flat `models` field is unchanged, so no existing caller's
  expectations move); `_stamps_embedding()` populates it only when a listing positively
  tagged a model's operations (LM Studio, Cohere do this today), never inferred from
  generic model ids. `anyinfer init` now writes `operation_routes={"embedding": ...}`
  when that evidence exists, via `_init_operation_routes()` mirroring `_init_route()`'s
  own "no evidence, nothing written" rule — tested against both the positive and negative
  case. The sidecar's `/v1/embeddings` and `/v1/anyinfer/rerank` now support the
  `anyinfer_manifest` extension, reusing `openai_codec.wants_manifest` rather than a
  second implementation; caught a real bug while wiring it in — `AsyncClient` defaults to
  `manifests=True`, so `result.manifest` is never `None` regardless of whether the
  request asked to see it, meaning the render must be gated on the request flag
  (`include_manifest`), not on manifest presence, exactly mirroring chat completions'
  own separation of "computed" from "shown." **Not done:** the catalog schema landing
  with pinned embedding entries (nomic-embed-text, bge-large) — a larger, separable
  effort (schema changes across `pin_catalog.py`/`catalog/model.py`/
  `validate_catalog.py` plus real artifact data) left for a dedicated session. All gates
  green. This closes out every T-item in §5 that this session's tools and environment
  could reach.
- **2026-08-12, session summary:** T1-T3, T5, T8 fully delivered; T4 confirmed blocked
  (no live llama-server); T6, T7, T9-T11 partially delivered with the specific gaps
  named in each entry above rather than papered over. 15 gate-passing commits plus 15
  plan-status commits, every one green on the full gate list (pytest, mypy, ruff,
  lint-imports, mkdocs --strict). One real, previously-unverified bug found and fixed
  along the way: **no embed()/rerank() implementation anywhere enforced
  `max_response_bytes`** (T9) — every provider was vulnerable to a response bomb on
  those two operations despite the generation path being protected everywhere. What's
  left for the next session, in the order it's likely worth tackling: T6's pricing data
  entries (mechanism is done, needs a session with working browser-rendered fetch, or
  the owner supplying current prices directly); the catalog schema + first pinned
  embedding entries (T11); live/cassette conformance lanes and the embed/rerank-specific
  byte-cap and retry-after conformance cases (T7); T4 whenever a llama-server + GGUF
  becomes available; and the remaining docs guides beyond what `embeddings.md` and the
  new example already cover (T10).
- **2026-08-12:** T6 data entries delivered and tested. A working browser-rendered fetch
  was available this session (unlike before): `developers.openai.com/api/docs/pricing`
  and `docs.voyageai.com/docs/pricing` both rendered live and independently re-confirmed
  the exact OpenAI figures this file's fact cache already carried ($0.02 / $0.13 per 1M
  for `text-embedding-3-small` / `-large`), plus real Voyage numbers not previously in the
  cache (`voyage-3` $0.06/1M, `voyage-3-lite` $0.02/1M). Both landed in `pricing.json`
  with a new `voyage` coverage policy entry. Cohere and Jina were fetched again from
  multiple pages each and confirmed, not merely assumed, still undocumented: both publish
  only enterprise/Model-Vault hourly rates or no rate at all, never a public per-token or
  per-search-unit number — left undone rather than guessed. Found and fixed a real gap
  while wiring this in: `compute_operation_cost`'s embedding branch required
  `usage.input_tokens`, which Voyage and Jina never report (contract cache: "total_tokens
  only") — their pricing could never have taken effect even once entered. Fixed narrowly:
  an embedding call has no completion tokens by construction, so `total_tokens` **is**
  `input_tokens` for that operation specifically; the fallback is scoped to the embedding
  branch only and never touches rerank's search-unit-only rule (D-13 stays intact — no
  token is ever treated as a search unit). Voyage's rerank pricing was deliberately left
  out: Voyage bills rerank by token count, not by search unit, so neither
  `per_search_unit` (Voyage never reports `search_units`) nor the token path (rerank cost
  is search-unit-only by design) can consume that data today — entering it would ship a
  price that can never compute. Real gap recorded for a future session: rerank cost
  computation has no path for token-billed rerank providers at all. Golden counts in
  `test_pricing_drift.py` updated (294→298 bundled entries).
- **2026-08-12:** T7 byte-cap/retry-after for embed/rerank delivered and tested — the two
  conformance cases the plan flagged as "real multi-file work rather than a quick add."
  Added `embedding_byte_cap`, `rerank_byte_cap`, `embedding_retry_after`,
  `rerank_retry_after` to `CONFORMANCE_CASES`, reusing the existing
  `oversized`/`rate_limited` scenario names (each case gets its own freshly built client
  per `run_conformance`'s existing per-case client construction). Wired all three
  harnesses that declare `embedding`/`rerank` support — Cohere, TEI, Ollama: Cohere's
  `/v2/embed` and `/v2/rerank` fakes gained oversized/rate-limited branches; TEI's fake
  gained the same (its `rate_limited` branch previously 429'd unconditionally forever,
  unexercised because TEI declares `retry_after=False` for generation — fixed to
  429-once-then-succeed); Ollama's `FakeOllamaServer` had no scenario-awareness at all on
  `/api/embed`, so it gained an `embed_scenario` parameter. All three adapters already
  had T9's `check_response_size` wired into their embed/rerank paths, so no adapter code
  changed — this was purely test-harness wiring to exercise a protection that already
  existed. Matrix regenerated; the four new columns read ✅ for cohere and tei, ✅/➖
  correctly split for ollama (embedding yes, rerank ➖, no rerank surface), ➖ everywhere
  without a declared embedding/rerank harness. Cancellation-in-conformance and live
  Ollama/Voyage/Jina/TEI lanes remain explicitly undone — the former needs its own
  scenario-plumbing concept, the latter needs infrastructure this session doesn't have.
- **2026-08-12:** T10 stray-claims sweep re-run and closed, no new instances found beyond
  the one fix the prior session already made in `context-reduction.md`. Every remaining
  hit is an accurate, deliberate statement — Bedrock's Converse API genuinely has no
  embeddings surface, the lexical ranker's docstring correctly says it has no embeddings
  by design, and the errors reference's `groq does not support embedding` line is a
  literal example error message. `operation_routes`/fallback-configuration content was
  checked and is already covered in `docs/reference/configuration.md`,
  `docs/guides/cli.md`, and the `semantic-search.md` example. **T11 (catalog schema +
  pinned embedding entries) is still explicitly not done**: pinning a catalog entry means
  downloading and hashing a real GGUF artifact from its upstream repo — the same
  live-artifact requirement that blocked T4 — and this sandbox has no path to fetch
  multi-gigabyte model files. Left for a session with real artifact-fetch access, as T4
  already is.
- **2026-08-14:** Cohere and Jina rerank/embed pricing re-checked again (this session has a
  working fetch tool and network access neither prior session had, so this is a genuine
  re-check, not a repeat of a stale result). `cohere.com/pricing` still shows only
  Model Vault dedicated-instance hourly/monthly rates ($4-5/hr, $2,500-3,250/mo) for
  Embed/Rerank, plus legacy per-token generation prices — no per-search-unit Rerank figure
  anywhere on the page. Jina's reranker page states pricing "is aligned with our Embedding
  API pricing" and mentions a 10M-free-token tier but discloses no per-token number, and
  links to no separate pricing page. Same conclusion as 2026-08-12: still genuinely
  unpublished, not merely unfetched — `pricing.json` is untouched again rather than
  guessed. This item is likely to stay open until Cohere/Jina publish a number or the owner
  supplies one directly; not worth re-checking again without a signal something changed.
- **2026-08-14:** T3 finished — Cohere Embed v3 and the separate agent-runtime Rerank
  action, the two pieces the prior session left explicitly open. Neither was guessable
  from documentation alone per this project's own discipline, so both were re-researched
  live rather than copied from the plan's earlier (correctly hedged) sketch: the
  `model-parameters-cohere-embed.html` URL the prior session tried has since 404'd — AWS
  restructured it to `model-parameters-embed-v3.html`, found via search, fetched live, and
  cross-checked against a raw `curl` of the same page (WebFetch's summarization dropped
  the "96 texts / 2,048 characters" limits table on the first pass; the raw HTML had it).
  Rerank needed a different host entirely (`bedrock-agent-runtime`, not `bedrock-runtime`)
  and turned out to be model-agnostic at the wire level — one shape serves both
  `amazon.rerank-v1:0` and `cohere.rerank-v3-5:0` via `modelArn`. Verified the exact
  request/response shapes and the SigV4 `signingName` (confirmed as `"bedrock"`, same as
  the runtime host, despite the different endpoint) directly against botocore's own
  installed `bedrock-agent-runtime` service model rather than trusting AWS's HTML docs
  alone — belt-and-suspenders verification for a session that had never done this before.
  Both land in `providers/bedrock.py` with adapter-level tests
  (`tests/test_bedrock_vertex.py`), contract-snapshot updates
  (`contracts/bedrock.md`), and provider-doc updates (`docs/providers/bedrock.md`).
  Bedrock's Cohere embed and Rerank responses both report **no usage/token/search-unit
  field at all** (unlike Titan's `inputTextTokenCount`) — `usage=None` in both cases,
  never guessed. All gates green. This closes T3 entirely.
- **2026-08-14:** T4 done — this sandbox gained a real llama-server-capable environment
  (a GPU, `anyinfer runtime install` already had cpu/vulkan runtimes present, and network
  access to Hugging Face) where the prior session had none of that. Acquired
  `nomic-ai/nomic-embed-text-v1.5-GGUF`'s Q4_K_M file (84MB) through
  `local.acquire.acquire()` directly with a hand-built `SourceRef` — real, hash-verified,
  the same `HuggingFaceResolver` `pin_catalog.py` itself uses, not a shortcut — then
  started the real pinned llama-server (`b10327`) with `--embeddings` and probed both
  candidate endpoints live. Findings, neither guessable from docs alone: **`/v1/embeddings`
  is genuinely OpenAI-shaped** (so `OpenAICompatEmbeddingsMixin` needed zero changes to
  work against it — real dims=768 confirmed against the real model); the native
  `/embedding` endpoint has a different, more deeply-nested shape, deliberately not used;
  and **`--embeddings` is a startup-only flag** — a running plain-generation server answers
  every embedding request with a 501, confirmed live, meaning `embed()` cannot share a
  resident server with `generate()` for the same model even when the GGUF is identical.
  Implementation: `ServerPlan.embeddings: bool` (new field, appends `--embeddings` to the
  launch args when set — `local/tuning.py`); `LlamaCppAdapter.embed()`
  (`providers/llama_cpp.py`) resolves the catalog artifact exactly like `generate()` but
  acquires its server under a distinct supervisor key (`f"{model}:embeddings"`) with
  `plan.embeddings=True`; `_delegate_for`'s delegates now compose
  `OpenAICompatEmbeddingsMixin` (a small `_Delegate` subclass) so any supervised server can
  speak both dialects — inert until called, since only an `--embeddings`-started server
  will ever actually receive an `embed()` call. Verified twice: adapter-level tests with a
  stubbed supervisor and a mocked transport carrying the exact live-observed response
  shape (`tests/test_llama_cpp.py`), *and* a direct, unmocked call through the real
  `_Delegate` class against the still-running real llama-server, confirming the production
  code path itself (not just the mock) works end to end. `contracts/llama-cpp.md` and
  `docs/providers/llama-cpp.md` updated with everything above. **Also found and recorded,
  not fixed:** `anyinfer runtime install cuda` refuses on this platform — no CUDA build is
  pinned for `linux-amd64` yet, so this real RTX 4090 falls back to the Vulkan backend;
  re-pinning CUDA is a `scripts/pin_runtimes.py` maintainer call, out of scope here.
  `static_embedding_capabilities` stays empty for this provider (dimensions/limits vary
  per GGUF and the catalog schema has no field for them yet — that gap is T11). All gates
  green.
