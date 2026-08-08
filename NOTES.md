# AnyInfer — Interview Running Record

Interview conducted 2026-08-05, grounded in a code survey of Frisket, ModelFit, and mote-cli.
Companion to [DESIGN.md](DESIGN.md).

## Confirmed requirements (interview decisions)

| # | Area | Decision |
|---|---|---|
| D1 | Audience | Internal-first (Frisket/ModelFit/mote are the v1 customers), designed as if public, published after migrations prove the API. |
| D2 | Core abstraction | `GenerationRequest → typed event stream / final result`. Not an OpenAI-API clone. |
| D3 | Concurrency | Async core + sync facade (background event-loop thread). |
| D4 | Providers (v1) | All nine: Copilot, Ollama, OpenAI-compatible, llama.cpp, OpenAI, Anthropic, Azure Foundry, M365 Copilot, OpenRouter — delivered in tiered milestones with a real app migration at each tier. |
| D5 | llama.cpp mode | Supervised `llama-server` only; no in-process llama-cpp-python. |
| D6 | Structured output | Validated contract: best native mechanism, always client-side validated against the original schema, opt-in bounded repair loop. |
| D7 | Aliases | Core feature (small/medium/large × engine), **bundled default catalog** with app overlay. |
| D8 | Credentials | Pluggable resolver protocol; literal / `env://` / `credential://` (keyring extra) shipped; auto-redaction. |
| D9 | Telemetry | Hybrid: typed in-process events (payload-free by default) + optional OTel bridge (`opentelemetry-api` only, lazy). |
| D10 | Routing (v1) | Retries + explicit fallback chains + health-aware skip. Load balancing and cost/latency-aware selection deferred. |
| D11 | Errors | Shallow class tree (~10 classes) with rich structured fields (provider, phase, retryable, retry_after, http_status, detail, hint). |
| D12 | Capabilities | Layered assembly: static catalog → live discovery → opt-in probes; provenance-tagged fields; conjunction bounds for `auto` models. |
| D13 | Config | Programmatic core + canonical versioned JSON config layer (schema, precedence, hygiene, setup-spec-driven UIs), shared by the SDK, CLI, demo, and sidecar. |
| D14 | Extensibility | Frozen ProviderDescriptor registry + `anyinfer.providers` entry points, collision-safe, lazy. |
| D15 | Packaging | Slim core (`httpx2`, `jsonschema`) + per-provider extras; llama-server binaries runtime-fetched. |
| D16 | Local subsystem | All four in v1 core: hardware detection, llama-server tuning, GGUF catalog + downloads, hardware→tier recommendation. |
| D17 | Tool calling | **Full tool loop in v1** (user decision, against architect recommendation) — types from M0, executor in M4. |
| D18 | Conformance | Shared contract suite × {cassettes, fake servers, opt-in live}; public matrix doc. |
| D19 | Naming | `anyinfer` locked (package, import, CLI). |
| D20 | Security | Redaction registry, loopback-only local servers, payload-free events by default, strict config hygiene — all core. |
| D21 | Sidecar frontend | An OpenAI-compatible loopback HTTP frontend (`anyinfer.serve`, `[serve]` extra) federates to any abstracted backend. It is a pure wire codec around `AsyncClient` (ADR-009); its four enabling invariants (request superset, event-stream sufficiency, Target-in-model-string, concurrent streams) are round-trip-tested. Pulled forward into the 0.1 beta with standalone bundles. |
| D22 | Binary distribution | The serve frontend must also ship as self-contained cross-platform executables (`anyinfer-serve` for macOS/Linux/Windows, no host Python) as a first-class integration path alongside the SDK. PyInstaller onedir recommended (in-house prior art in Frisket + ModelFit; cheaper options evaluated and rejected in ADR-010). llama-server runtimes and models stay runtime-fetched, never bundled. |
| D23 | SDK documentation | A published, developer-friendly docs site is a shipped deliverable with per-milestone obligations (DESIGN.md §25): quickstart, integration-path decision guide, concepts, how-tos, per-provider pages (embedding live conformance-matrix rows), executable cookbook, generated API reference, error catalog, serve-binary manual, migration guides. CI gates: docstring coverage, all examples executed against fake providers. |
| D24 | Agent instructions + drift check | Repo ships agent instructions for Claude (`CLAUDE.md`), Copilot (`.github/copilot-instructions.md`), and Codex (`AGENTS.md`, the canonical file the others defer to), plus per-provider protocol contract snapshots (`contracts/*.md`) and an invocable semi-automated drift check (Claude skill `check-provider-drift`, Copilot prompt, canonical procedure `contracts/DRIFT-CHECK.md`) that audits snapshots against live provider docs. Snapshots update in the same change as any adapter wire change. |
| D25 | Token estimation + context budgeting (2026-08-07, resolves open question 1 / DESIGN.md §20 #1) | Pluggable `TokenEstimator` protocol, dependency-free byte-heuristic default (no tokenizer deps, ADR-007). Estimates are two-sided: a conservative-high planning figure and a defensible floor. `ContextBudget` calculator (allowance = window − derived output reserve − clamped headroom) is tri-state per ADR-005 — an unknown window is reported unknown, never defaulted (deliberate departure from Frisket's 16k fallback). Pre-dispatch gate (L6, `capabilities/gating.py`) fires only when the *floor* exceeds a *trusted-provenance* window, raising `ContextLengthError` so `Route.context_window_targets` redirects identically to a provider-reported overflow. Surface: `capabilities/{estimate,budget,gating}.py`, `Client.budget()`/`AsyncClient.budget()`, client knobs `estimator=` and `context_gate=` (default on). Ported and generalized from Frisket `prompt_budget.py`; Frisket's app-shaped component taxonomy replaced by the typed request's own anatomy (messages/tools/schema). |
| D26 | HTTP dependency: httpx → httpx2 (2026-08-07, supersedes the dependency named in D15 and the 2026-08-05 "raw httpx" assumption) | Core migrated wholesale to `httpx2>=2.0`, the Pydantic-stewarded continuation of httpx (same BSD-3-Clause license, original author credited, API-compatible; upstream httpx stagnant since 2024-12). Trigger: starlette ≥ 1.0 deprecates plain httpx in its TestClient in favor of httpx2, which `filterwarnings = ["error"]` escalated to a suite failure. Provenance verified before adoption: PyPI maintainer = Pydantic Services Inc., source = github.com/pydantic/httpx2. All imports, docs, and the import-linter leaf-types contract renamed; ADR-007's slim-core shape is unchanged (`httpx2` + `jsonschema`). Full gate suite green against httpx2 2.9.x + starlette 1.4.x with zero call-site changes. |
| D27 | Cost tables + estimated cost + override provenance (2026-08-07, amends ADR-005) | Bundled per-provider pricing table (`capabilities/pricing.json`) feeds capability assembly as the `catalog` layer; keyed by provider **and** model — engines price the same model differently, so a price is never copied across providers. Entries carry real `last_verified` dates and source URLs (D24 discipline). Deliberately absent: azure-foundry (region/deployment-specific; app-side via the Azure retail prices API), copilot/m365-copilot (subscription-billed, no per-token price), openrouter (live `discovered` pricing), local engines (assembly supplies a genuine `Pricing(0,0)` zero). `ContextBudget.estimated_cost` is a tri-state `CostEstimate` *range* (floor-priced low, estimate+reserve-priced high), never mixed with reported `Usage.cost_usd` (L4/L5). Fifth provenance `override` (rank 4, trusted): client `capability_overrides=` keyed `"provider:model"`, re-tagged automatically, beats every collected layer. Freshness: weekly `pricing-refresh` workflow — deterministic OpenRouter cross-check (`scripts/check_pricing_drift.py`), then a web-search-capable Claude pass verifying provider pages and opening a human-reviewed PR (never auto-merged; `scripts/validate_pricing.py` + CI gate it); apps opt into newer data via `fetch_pricing()` + `pricing_table=` — the library itself never fetches implicitly. |
| D28 | Context reduction subsystem (2026-08-07, amends the DESIGN.md §2 "No prompt templating" non-goal; see plans/TOKEN_REDUCTION_ALGS.md, ADR-011, §26) | Optional dependency-free subpackage `anyinfer.context`: apps collect documents (filesystem, approval, secrets policy stay app-side), the library reduces them to a caller-supplied token budget. Five strategies: `whole` (passthrough when the corpus fits), `ranked` (lexical BM25-style greedy selection ported from Frisket `context_selector.py`, constants preserved), `tiered` (rollup/extract/verbatim coverage ported from Frisket `context_tiers.py` + `_context_structure.py`), `packed` (chunk-level rank-and-pack, new), `distill` (map/reduce over the client, generalizing mote-cli `runtime/chunking.py`; the only strategy that spends inference, async-first with a sequential sync facade). Packing targets `ContextBudget.remaining_tokens` (planning side); unknown windows stay unknown — the caller must supply an explicit budget (no 16k fallback, ADR-005 discipline). Reduction is always observable: `ContextReduced` telemetry event (content-free) + `Reduction.summary()`. Rendering is deterministic and path-ordered by default for prompt-cache stability. No embeddings (open question 8 stands), no filesystem access, no new dependencies (slim core, ADR-007). Frisket and mote migrations are the acceptance test (D1). |
| D29 | Shared config and frontend boundaries (2026-08-08) | `anyinfer.config` owns format version 1 and returns validated `ProviderSettings` plus a default `Route`; the SDK, `anyinfer run`, demo, and sidecar consume it. `anyinfer.cli` owns process-level commands. `anyinfer.serve` contains only the OpenAI codec/ASGI boundary and a module-runner shim. Standalone sidecar bundles invoke the same CLI dispatch and core. Tool-specific coding-agent files are discovery shims over `AGENTS.md`; drift-check shims defer to `contracts/DRIFT-CHECK.md`. |

| D30 | Local model catalog + hardware-aware fit + runtime add-ons (2026-08-08, resolves open question 4; the plan it landed from, plans/LLAMACPP_MODEL_CATALOG.md, was removed on landing and is not in the public history) | A bundled logical-model table (`catalog/models.json`, 42 curated entries) sits beside the hand-edited alias policy (`default.json`), machine-maintained by `scripts/pin_catalog.py`, validated by `scripts/validate_catalog.py`, and drift-checked weekly by `scripts/check_catalog_drift.py` + `.github/workflows/catalog-refresh.yml` — the same five-part shape as the pricing table (D27). One logical model, two channels: pinned GGUF artifacts (URL + commit + sha256 + size per file, read from the Hugging Face tree API, never hand-typed) and Ollama registry tags with recorded manifest digests (tags are mutable, so only a digest makes a move detectable). Each entry carries a quantization ladder (`variants[]`) rather than one pinned quant. `best_at` is a closed vocabulary enforced at parse time. **Fit engine** (`local/fit.py`): gpu | cpu | tight | no | unknown against a `HardwareProfile`, advisory, never raising, always with reasons; `unknown` is a real answer and never a guess. **CUDA is an add-on, never a pack-in** (`local/runtimes.py` + `runtimes.json`, pinned from the ggml-org release API): the default install path is Metal on Apple Silicon, Vulkan on any other GPU machine, CPU otherwise; `install_runtime('cuda')` is explicit opt-in gated on driver major and compute capability, and `runtime.json` manifest validation makes "are the CUDA extensions installed?" answerable without inferring from a directory name. **Locality amendment to D12:** `ProviderDescriptor.locality` gains `"remote"`, and a client downgrades a `local` engine reached over a non-loopback URL to `remote` — so capability assembly withholds the genuine-zero local price from someone else's metered proxy, and hardware probing is not offered for a machine we cannot see. **Excluded for licensing** (reachable via overlay): Qwen2.5 3B/72B, Codestral 22B, Command R7B, Ministral 8B, DeepSeek-Coder-V2-Lite; the `medium` tier consequently moves from Qwen2.5 3B (research-licensed) to Qwen3 4B (Apache-2.0). Surface: `Client.local_catalog()` → `CatalogView`, `Catalog.with_alias_target()`, `HardwareProfile.from_user_input()`, `anyinfer models list`, `anyinfer runtime …`. |
| D31 | Model retrieval: acquisition, placement, and location (2026-08-08; the plan it landed from, plans/MODEL_RETRIEVAL.md, was removed on landing and is not in the public history) | One library-owned path from catalog pick → bytes on disk → a path an engine can be pointed at, for GGUF file sets and Hugging Face repository snapshots. **Sources are a resolver protocol** (`local/sources/`): `huggingface` (the API spoken directly — no `huggingface_hub`, per ADR-007 — recorded in `contracts/huggingface.md` and joined to the drift check), `url`, and `local`; an internal mirror is a registered resolver, not a dependency. **A store with an index** (`local/store.py`): revision-scoped placement under `gguf/`/`hf/`, an atomic `store.json` that is a cache rather than the truth (`rebuild_index()` recovers), adoption of pre-store flat-layout GGUFs and of externally-owned caches (never written to, never deleted). **Variant selection** (`local/variants.py`): highest-quality rung whose weights *and* KV cache fit; a GPU-resident rung beats a better RAM-resident one; the default ladder stops at Q4_K_M (below it, a smaller model at a good quant beats a bigger model at a bad one) and refusing carries the rejection reasons; vLLM gates on compute capability, and an unreported capability excludes rather than permits. **Aggregate progress**: `AcquisitionProgress` reports whole-acquisition bytes, knows its total before the first byte, counts what was already on disk, throttles to 250 ms / 4 MB but never misses a phase transition, and disables a raising sink instead of failing the download. **Amendment to D6:** `DownloadProgress.downloaded_bytes`/`total_bytes` are redefined as *aggregate* (they were per-file, which silently restarted the counter on every shard of a sharded artifact); new optional fields carry the per-file detail. An observable behavior change, called out rather than silently redefined. Verification tiers are explicit and never silent: an undigested file is refused unless `allow_unverified=True` and stays marked unverified through `locate_model()`. Path containment and pickle-weight exclusion are non-optional. `dry_run=True` reports the exact cost before a byte moves; cancelling keeps `.part` files. The llama-cpp adapter's existence-only fast path is replaced with a verified one. Surface: `Client.acquire_model/installed_models/locate_model/remove_model`, `anyinfer models add|installed|where|rm`. Deliberately out of scope: supervising vLLM (launch hints are advisory data, not process control), `ollama pull`, local quantization, and LoRA acquisition. |
| D32 | Public product boundary (2026-08-08, competitive review) | AnyInfer is positioned as an **application-owned hybrid inference runtime**, not a universal provider wrapper or organization gateway. Provider count, OpenAI compatibility, basic retries, and calling existing local endpoints are compatibility features, not differentiators. The public thesis has three pillars: (1) one application-owned route across hosted APIs, hubs, existing local services, and managed `llama.cpp`; (2) portable behavior with evidence — typed events, client validation, provenance, conformance, and explicit degradation; (3) context engineering tied to dispatch — D25 budgets/cost ranges plus D28 deterministic reduction/distillation. Apps still collect and approve context; the library never acquires filesystem or secret-selection policy. Public docs must say when a focused provider client, gateway/control plane, or dedicated local platform is the better tool. New provider expansion is subordinate to conformance and the three sibling migrations. |

| D33 | Setup fields carry prominence, not just requiredness (2026-08-08, amends D13/D14 and ADR-008) | `SetupField` gains `advanced: bool` and `default_value: str`, and `ProviderSetupSpec` exposes `essential_fields` / `advanced_fields`. The defect: the spec described *what* a provider accepts but not *what to ask for*, so every consuming app re-derived that from prose help text — and the demo, doing exactly what the spec said, showed a base URL and an API version beside the one field that mattered. A provider now marks the fields it already has a working value for; a UI renders those behind a disclosure and shows `default_value` rather than pre-filling it (a saved copy of today's default outlives the default). Required and `any_of`-member fields may not be advanced — `ProviderSetupSpec.__post_init__` raises `ConfigError` — because a UI honoring the disclosure would otherwise refuse a save naming a field that is not on screen. Registry-wide effect: 25 providers now declare **no** essential fields (every local engine, plus GitHub Copilot), and no provider with a default endpoint prompts for one. Second fix in the same change: keyless local presets declared no credential field at all, so a vLLM server started with `--api-key` was unconfigurable from any spec-driven UI; they now declare an optional advanced one, except Lemonade (`?api_key=` query parameter) and Docker Model Runner (ignores `Authorization`), which declare `accepts_api_key=False` rather than take a credential they would not authenticate with. |

## Assumptions (working, unconfirmed)

- Python ≥ 3.11; raw httpx2 for all HTTP providers (no official OpenAI/Anthropic SDKs), matching all three current projects.
- The three apps migrate fully — no long-term dual-stack support for their old provider layers.
- Frozen dataclasses + Protocols for public types; no pydantic dependency (pydantic models accepted as schema *inputs* via `model_json_schema()` duck-typing).
- mote-cli accepts subprocess llama-server latency in exchange for dropping llama-cpp-python.
- Windows is a first-class platform (all three apps ship there).

## Open questions (carried into design/milestones)

1. ~~Token estimation / prompt budgeting design (Frisket preflight needs) — pluggable estimator?~~ **Resolved as D25** (2026-08-07).
2. Session/conversation reuse API (mote token-cache: Copilot resume, Ollama keep_alive) → design during M0, needed M1.
3. Cancellation semantics across the sync facade → specify in M0 (risk R1).
4. ~~Default catalog contents, ownership, and update cadence.~~ **Resolved as D30** (2026-08-08): bundled `models.json`, machine-maintained by the pin script, refreshed weekly by the `catalog-refresh` workflow against a deterministic drift check, never auto-merged.
5. M365 Copilot headless/CI story (interactive-only auth) → M3.
6. Where Ollama GPU-spill/observed-VRAM checks live (adapter warnings vs capability layer) → M1.
7. Anthropic structured-output mechanism (tool-based json emulation vs newer native support) — verify current API in M2.
8. Embeddings and multimodal inputs — explicitly out of v1; revisit for v2 scope.
9. Code signing for the sidecar binaries — macOS notarization identity and Windows Authenticode cert: whose identities, and does binary release cadence differ from PyPI cadence? The 0.1 beta ships checksummed but unsigned native bundles; resolve before 1.0.
10. ~~Docs hosting.~~ **Resolved:** GitHub Pages via `.github/workflows/pages.yml`; no parallel hosting stack.
11. Drift-check cadence automation — scheduled agent runs (CI cron invoking the skill) vs manual pre-milestone runs; initial contract snapshots are code-survey-derived and need a first live-verification run → before M1 adapter work.

## Deferred features

- Non-chat OpenAI endpoints (embeddings, images, audio) remain outside the sidecar's scope.
- Load balancing across equivalent endpoints; cost/latency-adaptive routing (Route policy object designed not to preclude them).
- Parallel tool-call execution in the tool loop (v1 loop is sequential).
- Shared telemetry sinks module (`anyinfer.sinks` JSONL/SQLite contrib) — apps keep their own observers for now.
- Embeddings, image/audio modalities, fine-tuning management.

## Interview deviations from recommendations (accepted, tracked)

- **OTel-native** was initially selected, then refined to the hybrid events+bridge model after probing in-process consumption needs.
- **Full router in v1** was initially selected, then scoped down to retries + fallback + health after probing actual project needs.
- **Bundled default catalog** (vs app-supplied only): accepted curation/staleness burden → risk R6.
- **Full tool loop in v1** (vs types-only): zero current consumers → risk R5, scheduled last (M4).

## Risks

See DESIGN.md §21 (R1 sync facade, R2 conformance drift, R3 Windows subprocess supervision,
R4 structured-output divergence, R5 tool loop without consumers, R6 catalog staleness,
R7 `auto` sentinel).

## Comparative review — LiteLLM and peers (2026-08-05, during M0 implementation)

Requested mid-implementation: survey LiteLLM (and, for contrast, aisuite / Portkey) for
features and failure modes worth reacting to. Findings that changed the build are recorded
here as deviations/additions per IMPLEMENTATION.md's "record the deviation" rule. None of
these contradict a numbered decision or an ADR; they refine within them.

**Adopted (implemented in M0 unless noted):**

| # | Idea | Where it landed | Rationale |
|---|---|---|---|
| L1 | Typed fallback *classes* (LiteLLM splits `fallbacks` / `context_window_fallbacks` / `content_policy_fallbacks`) | `routing/policy.py` — `Route.context_window_targets` / `Route.content_policy_targets` | A context overflow and a content-policy refusal need *different* next targets than a 500. Cheap because `Route` was already a policy object (D10). |
| L2 | Per-exception-class retry policy | `routing/policy.py` — `Retry.standard()` / `RetryPolicy` predicate helpers | Immediate-vs-backoff-vs-never differs by error class; `retry_on` already allowed it, this ships the sensible default. |
| L3 | Streaming edge cases as explicit conformance rows | `testing/conformance.py` | LiteLLM's bug tail is concentrated here: usage lost by closing on `finish_reason`; usage in the second-to-last chunk; synthetic usage chunks with non-empty `choices`; tool-call deltas needing index-keyed accumulation; tool calls dropped on `finish_reason=="length"`; non-standard `finish_reason` crashing reassembly. Our rules: **drain to the terminal sentinel, never to `finish_reason`**; **`FinishReason` is an open enum** (unknown → `"other"`); **usage is a late-arriving optional event**. |
| L4 | Cost is tri-state, never a silent `0.00` | `capabilities/pricing.py`, `Usage.cost_usd` | LiteLLM ships a whole cost-discrepancy troubleshooting page. `None` means unknown and must stay distinguishable from a real zero. Reinforces ADR-005. |
| L5 | Degradations are typed events, not silence | `events/telemetry.py` — `ParameterDropped`, `UsageEstimated` | Inverts LiteLLM's `drop_params=True` (silent) and its estimator-as-fallback. Anything we drop or estimate is observable. |
| L6 | Pre-dispatch capability gating | `capabilities/gating.py` | Fail fast (or route elsewhere) when a request provably cannot fit the target's context window, instead of paying a round trip. Uses the provenance model — only *known* bounds gate. |
| L7 | Health-gate isolation is per **deployment**, not per model group | `routing/health.py` (keyed by `provider:model`) | Already true in our implementation; recorded so it stays true. |
| L8 | Explicit provider passthrough escape hatch | already `provider_options` (DESIGN.md §5) | Confirmed as load-bearing: LiteLLM's lack of one early is why `drop_params`/`additional_drop_params` accreted. |

**Explicitly rejected (recorded so they are not revisited casually):** virtual keys,
multi-tenancy, RBAC, budget/spend limits, admin UI, Redis-backed cross-instance TPM/RPM
accounting, usage-based routing v2, semantic caching, response caching, guardrail/PII
plugins, MCP gateway, 100+ provider breadth. All require shared state, heavy dependencies,
or a control plane — they belong in a *deployment* around AnyInfer, not in the library
(consistent with D15/ADR-007 and the §2 non-goals). Portkey's OSS-gateway/SaaS-governance
split independently confirms this boundary.

**Pitfalls being designed against:** breadth-over-correctness (mitigated by the fixed
provider set + contract snapshots, D24); module-level mutable global config (our types are
frozen; no global knobs ship); silent degradation (L5); monolith drift (import-linter
contract enforcing ADR-003); estimator-as-fallback contaminating reported data (L4 + the
provenance model). LiteLLM's 2026 supply-chain compromise and RCE also reframe the slim-core
decision (ADR-007) as a *security* argument, and reinforce that the M5 serve frontend must
stay a pure wire codec with no config-execution or dynamic-configuration endpoints (ADR-009).

**Contrast note:** aisuite validates the slim-core/per-provider-extras posture but refuses
streaming complexity (callers reassemble chunks themselves) — precisely the gap the typed
event stream (ADR-001) exists to fill.

## The "flat ground" objective (added 2026-08-05, user directive)

**Stated goal:** bring together the best of hosted multiplexers and local multiplexers, and
expose *equivalent features wherever possible*, so an integrating system gets genuinely flat
ground regardless of which inference engine backs a request. This is now a first-class
design objective alongside DESIGN.md §2, and it sharpens D4/D16: breadth of *providers* is
not enough — breadth of *capability parity* is the product.

Surveyed for this: Bifrost (maximhq), llama-swap, LocalAI, LM Studio, GPUStack, vLLM's
OpenAI server, llama.cpp's llama-server, Ollama, OpenRouter's provider routing.
("LLM-Proxy" turned out to be ambiguous — no dominant project by that name; most references
to "an LLM proxy" mean LiteLLM. Dropped as a target.)

### Capability parity model (three states, not two)

Every capability, per provider, is one of:

1. **Native** — the engine does it. Pass through.
2. **Emulated** — the core makes it work anyway, and says so. (Schema via prompt +
   validation + repair; `n>1` via fan-out; token counts via estimator.)
3. **Unflattenable** — surfaced as an honest capability flag, never faked.

The failure mode this exists to prevent is a fourth state peers actually ship: **silently
ignored** — the parameter is accepted, does nothing, and looks like success (Ollama's `/v1`
layer discards `logprobs` and `n`). `ProviderDescriptor.ignored_parameters` +
`ParameterDropped` telemetry make that state explicit and observable.

### Findings that changed the code (M0)

| # | Finding | Change |
|---|---|---|
| F1 | **llama.cpp/Ollama grammars *constrain* but do not *inform*.** A GBNF grammar guarantees well-formed JSON, not meaningful JSON — a model never shown the schema emits schema-shaped nonsense. | `ProviderDescriptor.grammar_needs_prompt_injection`; the core injects the schema into the prompt for grammar mode too, not just for `prompt`/`json_mode`. |
| F2 | **Backends silently disable constraint enforcement under thinking** (llama.cpp [#20345](https://github.com/ggml-org/llama.cpp/issues/20345); vLLM [#39130](https://github.com/vllm-project/vllm/issues/39130)) — no error, unconstrained output. | Never trust a backend's constraint claim: the core always validates the parsed result against the original schema (already true, now conformance-tested). Thinking+schema is a capability *combination*, not two independent flags. |
| F3 | **Silently-ignored parameters.** | `ignored_parameters` + `ParameterDropped` (above). |
| F4 | **Usage lost by closing on `finish_reason`** rather than the terminal sentinel; usage sometimes arrives in the second-to-last chunk. | Parser drains to `[DONE]`; usage is a late-arriving optional event; both conformance-tested. |
| F5 | **`finish_reason` is an open enum**; unknown values crash naive reassemblers. | Unknown → `"other"`, conformance-tested. |

### Findings scheduled for M1 (local subsystem / llama-cpp supervisor)

llama-swap is the closest prior art for the supervisor and its semantics are worth copying
closely:

- **Serialized model swaps, block-until-ready.** Two requests for two unloaded models: the
  first swaps, the second *waits* — never a 503 to the caller during load. Health-check
  timeout bounded (llama-swap: 120 s default, 15 s minimum).
- **Distinguish "loading" from "failed"** in health gating, and capture the child's stderr —
  polling `/health` alone hangs the full timeout on a genuinely broken model
  (llama-swap [#146](https://github.com/mostlygeek/llama-swap/issues/146), [#789](https://github.com/mostlygeek/llama-swap/issues/789)).
- **Idle TTL unload with a `persist` pin**, TTL overridable per request (LM Studio). The
  idle timer must key on **active-stream count, not last-request time** — LocalAI
  [#5221](https://github.com/mudler/LocalAI/issues/5221) killed a process mid-generation
  because a long generation with no *new* requests looked idle.
- **Process reaping is fallible.** Verify the process is gone and VRAM reclaimed before
  reporting a free slot (LocalAI [#1760](https://github.com/mudler/LocalAI/issues/1760),
  [#2277](https://github.com/mudler/LocalAI/issues/2277)).
- **VRAM admission control before spawn** — "will this fit alongside what's loaded?" No
  surveyed local multiplexer does this (llama-swap evicts by TTL/cost, not memory), and
  AnyInfer already has the hardware detection to do it. Genuine differentiator (D16).
- **Size local context as `n_ctx × parallel`**, not `n_ctx`: llama.cpp's fixed slots grow KV
  cache linearly with concurrency, so KV VRAM is what exhausts first.
- **`--jinja` on by default** in the supervisor — without it, local tool calling silently
  does not exist.
- Use llama-server's `/tokenize` and `timings_per_token` for exact counts and honest TTFT
  rather than estimates (feeds the provenance model).
- Per-adapter **bounded concurrency** (Bifrost's per-provider worker queues, llama-swap's
  `concurrencyLimit`): one slow provider must not starve the others.
- The serve frontend must set `X-Accel-Buffering: no` or intermediaries buffer the stream.

### Also adopted from this survey

- **Capability-filtered fallback candidate selection** (OpenRouter's provider routing): do
  not fall back to a target that provably cannot serve the request as sent. Pairs with L6.
- **Pre-flight fit check** exposed in the API (LM Studio's `--estimate-only`): answer "will
  this model fit?" without loading it.

### Rejected from this survey

Bifrost's semantic caching, clustering, governance/virtual keys, and web UI; LocalAI's gRPC
backend plugin system; distributed tensor-parallel scheduling; MCP hosting. All are
gateway-*server* or control-plane concerns. Note Bifrost's headline performance comes from
Go-specific byte-level stream manipulation and object pooling — not a portable idea for a
typed Python library, and not the axis AnyInfer competes on.

## Implementation record (updated 2026-08-08)

All product milestones M0–M5 are implemented; native code signing remains external release
infrastructure. This section records what was built, and the
deviations from IMPLEMENTATION.md that the work required — per that file's instruction to
record deviations here before proceeding.

### Deviations from IMPLEMENTATION.md

| # | Spec | What was built | Why |
|---|---|---|---|
| I1 | §B: `registry.py` exports a module-level `registry` singleton | Renamed to `default_registry` | A module-level name equal to its own module shadows the module on the package, breaking introspection, docs generation, and `monkeypatch`. Caught by a failing entry-point test. |
| I2 | §C8: redaction lives in `events/` | Moved to a top-level `anyinfer/redaction.py` | `errors.py` needs redaction at construction, so every adapter transitively imported `events`, breaking the ADR-003 import contract. Redaction is a security primitive, not a telemetry concern. `events` re-exports it, so the public surface is unchanged. |
| I3 | §B: `GgufArtifact`/`GgufFile` live in `catalog/` | Moved to `local/artifacts.py`, re-exported from `catalog` | The llama-cpp adapter needs artifact *identity*, and importing `catalog` from an adapter broke the ADR-003 contract. Artifacts describe local files; the catalog merely references them by id. |
| I4 | §E.4: adapters must not import `events` | Contract narrowed to forbid `routing`, `schema.validate`, `schema.repair`, `_client`, `capabilities` | The llama-cpp supervisor legitimately emits `ServerLifecycle` telemetry, and `events.telemetry` carries no policy. The rule ADR-003 actually protects is "no *orchestration* in adapters"; the contract now states that precisely. `local` is likewise excluded — composing the local subsystem is translation. |
| I5 | §C2: usage flows only from adapter events | Core synthesizes a `UsageUpdate` when a provider reports usage only on its terminal object | Ollama reports usage solely on the `done` message. Without this, a streaming consumer sees usage from some providers and not others — precisely the unevenness the library exists to remove. |
| I6 | §C4: prompt injection for `prompt` and `json_mode` only | Also for `grammar`, gated by `ProviderDescriptor.grammar_needs_prompt_injection` | See F1 below. A grammar constrains form without conveying meaning. |
| I7 | §D T0.9/T1.x: cassette mode for every adapter | Cassette *infrastructure* is complete; only fake-server harnesses ship | Recording cassettes requires live credentials across the dedicated providers. The harness, transport, and redaction-on-write are all implemented and tested; recording is an operator task. Flagged as remaining work below. |

### Beyond the spec (from the competitive review)

`Route.context_window_targets`, `Retry`'s deterministic-failure predicate,
`ParameterDropped`/`UsageEstimated` telemetry, tri-state cost, and VRAM admission control
were added as recorded in the LiteLLM and Bifrost/local-multiplexer sections above.

### Token budgeting and pre-dispatch gating (2026-08-07, D25)

Open question 1 closed. Built by porting Frisket's `prompt_budget.py` calculator and
generalizing it against this library's capability model:

- `capabilities/estimate.py` — `TokenEstimator` protocol; `HeuristicTokenEstimator`
  (ceil(bytes/3) planning figure, bytes//8 floor, calibration multiplier that never
  inflates the floor); `estimate_request` derives the breakdown (messages / tools /
  schema, per-message framing overhead in the planning figure only) from the typed
  request rather than hand-fed strings.
- `capabilities/budget.py` — `ContextBudget` / `build_context_budget`. Frisket's
  arithmetic kept (allowance = window − reserve − 5% headroom clamped to [256, 8192]);
  Frisket's 16k fallback window deliberately dropped — unknown stays `None` (ADR-005,
  same tri-state rule as cost). The output reserve is derived: the request's
  `max_output_tokens` when set, else the default capped by the model's known maximum.
- `capabilities/gating.py` — the L6 gate NOTES previously recorded as shipped but which
  had never actually landed (it was blocked on exactly this estimator). Gates on the
  estimate's **floor** against the **whole** trusted-provenance window, so a heuristic
  overestimate can never refuse a servable request; raises `ContextLengthError` on the
  same path a provider overflow takes, so `Route.context_window_targets` works
  identically, minus the round trip. `default`-provenance windows never gate.
- Clients: `budget()` preflight calculator on both clients (the Frisket-migration
  consumer); constructor knobs `estimator=` (pluggable, e.g. tiktoken or llama-server
  `/tokenize` later) and `context_gate=` (default on).

### Cost tables and estimated cost (2026-08-07, D27)

Built on D25's two-sided estimates; see the D27 row for the full decision. Notes beyond it:

- Bundled prices were verified against OpenRouter's public listing on 2026-08-07 (the
  entries' `last_verified` dates are real). The weekly workflow's LLM pass re-verifies
  drifted entries against the providers' *own* pricing pages before proposing changes —
  OpenRouter is the cheap deterministic tripwire, not the authority.
- `_retag_override` in `capabilities/assemble.py` stamps `override` provenance on every
  field the app supplies, so callers write plain values — supplying them deliberately *is*
  the provenance.
- The referenced `../Frisket/plans/ESTIMATIONS.md` (mid-implementation pointer for
  Foundry/Copilot pricing URLs) does not exist in the Frisket tree; the Azure retail
  prices API (`prices.azure.com/api/retail/prices`) is recorded in the workflow and table
  comments as the Foundry source instead.

### Bugs found and fixed during implementation

Three real concurrency defects in the llama-server supervisor (risk R3), all caught by the
suite's `filterwarnings = ["error"]` and by tests hanging rather than failing:

1. **Non-daemon log-reader thread** blocked interpreter shutdown — `readline` on a pipe is
   uninterruptible.
2. **Cross-thread pipe close deadlocked** against a reader blocked in `readline`. On
   Windows an orphaned grandchild keeps the write end open, so the close never returned.
   Fixed by giving the reader thread sole ownership of the stream for its whole life.
3. **`Popen.wait` hung** on an unreaped process tree. Fixed by always killing the tree —
   even after a graceful parent exit — and bounding the wait.

The third is exactly the "reaping is fallible" failure the local-multiplexer survey warned
about, reproduced here before any user hit it.

### Remaining work

- **Cassette recording** for each provider (needs live credentials), then a cassette-mode
  conformance row per adapter.
- **A first drift-check run** (open question 11). Every contract snapshot is still
  code-survey-derived and says so; none claims live verification.
- **Live conformance** in CI for providers whose auth permits it.
- **Native signing** — macOS notarization and Windows Authenticode require external
  certificates. The 0.1 beta bundles are smoke-tested and accompanied by SHA-256 checksums.
- **Sibling-app migrations** (T1.10, T2.6, T3.3) — separate change sets in those repos.
- Open questions 2 (session reuse API) and 9 (code signing) remain
  open. Question 1 (token estimation) was resolved as D25 on 2026-08-07.
