---
kind: spec
title: "C# SDK API parity inventory"
---

# C# SDK API parity inventory

**Current reconciliation:** the 2026-10-24
[foundation and SDK audit](SDK_FOUNDATION_ALIGNMENT.md) confirms partial SDK parity,
not an empty implementation. Accepted SDK.1–7 and the current seven native descriptors /
ten operation bindings are bounded development scope. The historical milestone notes
below describe their own checkpoints; they are not current missing-feature lists.
ALIGN.3 will add per-export evidence/status separately from the final completion boxes.
All 235 boxes remain open; broad provider, context/local/integration and final qualification
gaps remain assigned to SDK.6c/8–12.

> Baseline: `199c3f833e568334b629edd7d89f41a3b76efe2a`. Source inventory is static; no Python package imports.
> Status: SDK.1 vocabulary, generation convenience calls and stream contracts passed the full workspace gate on 2026-10-17. The root checklist remains unchecked until each feature is complete across its assigned milestones; a renamed type alone is not completion. Passing the frozen 102-case profile is not full-library parity.
> SDK.2's provider/settings pool, credential/error foundation and supported active configuration subset also passed the full 18-step gate: 222 native unit tests, 93 conformance tests, independent configured Python/C# execution, package-only consumption and executable C# documentation. Broader configuration policies, credential refresh/platform stores, provider breadth and operation APIs remain assigned to later milestones; this is not full completion of similarly named Python exports.
> SDK.3's synchronous `Client` and `SyncStream` facade passed the final 18-step gate, including 238 native unit tests, 93 conformance tests, package-only async/sync consumption and eight source-linked offline C# examples. Its lifetime controls cover concurrent callers, bounded queues, original cancellation/errors and callback re-entry. All 235 root rows remain unchecked until their broader assigned milestones and final completeness audit pass.
> SDK.4a's catalog, provenance capability/pricing metadata and explicit async/sync provider discovery/health passed all 18 workspace steps: 304 native unit tests, 93 conformance tests, package-only consumption and 15 rendered C# blocks matching executed source across six pages. Source checkpoint `aca24ddf2097ca9a33ff33039a2285f0b0b0bdb7` passed clean-revision package qualification. General schema, probes, accounting and broader provider/operation parity remain assigned to later milestones; all root rows remain unchecked.
> SDK.4b's SchemaSpec, modern Draft 6/7/2019-09/2020-12 validation, explicit resource retrieval and typed structured-result convenience passed 39 focused native cases, 24 independent Python cases, 343 native unit/93 conformance tests and all 18 workspace steps. Source `dbf82a949fca6ee7321b921233c0cda198b3a506` passes clean-revision isolated package qualification. Legacy Draft 3/4 remain SDK.11c; native numeric comparison/regex limits and C# retrieval policy are documented differences. Probes, accounting and later operation/provider semantics remain unfinished; all 235 root rows stay unchecked.
> SDK.7's typed rich-generation contract and bounded registered-tool loop are accepted at clean source `b315ef73173b81ace643c41e95f4e6339db636b6`: all 24 workspace steps, registered provider-change qualification, 947 native unit/93 conformance tests, actual rich 43/tool 10 paired matches, preserved prior profiles/Frozen 102, compiled examples, strict docs and package-only consumers pass. Dedicated provider dialects, context/local/session/batch integrations and final SDK qualification remain unfinished. All 235 root rows remain unchecked until their complete assigned semantics and SDK.11c audit pass.

## Root exports (235)

SDK.5a's typed observers, opt-in sinks and generation manifests are accepted at source
`68d2cc06914aaa8539eb3cc5ee8d20acdbd2a906`: all 18 workspace steps, 474 native unit tests,
93 frozen conformance tests, compiled documentation/examples and clean-revision isolated
package consumption pass. The minimum EDecimal/Pricing/Usage value foundation is present;
automatic accounting, ledgers and policies remain SDK.5b/5c. Complete event DTOs do not
claim later operation/tool/context/local/batch producers. All 235 root rows remain
unchecked until their broader assigned milestones and the final completeness audit pass.

This checklist is generated from the literal `__all__` in `src/python/anyinfer/__init__.py`; source module is taken from root `ImportFrom` AST aliases. All are unchecked until implemented and reconciled. `SDK.11c` is the final completeness audit, not an unassigned feature bucket.

| Done | Python export | Source module | Assigned C# milestone |
|---|---|---|---|
| [ ] | `BENCHMARK_OUTPUT_TOKENS` | `.benchmark` | SDK.11a sessions/evaluate/benchmark/batch |
| [ ] | `BENCHMARK_PROMPT_TOKENS` | `.benchmark` | SDK.11a sessions/evaluate/benchmark/batch |
| [ ] | `BEST_AT` | `.catalog` | SDK.4–5 catalog/capabilities/accounting |
| [ ] | `CONFIG_FORMAT_VERSION` | `.config` | SDK.2 providers/credentials/config |
| [ ] | `DEFAULT_PROBE_FEATURES` | `.capabilities` | SDK.4c probes/setup metadata |
| [ ] | `MANIFEST_FORMAT` | `.manifest` | SDK.5 events/manifest/accounting |
| [ ] | `MAX_CONFIG_BYTES` | `.config` | SDK.2 providers/credentials/config |
| [ ] | `MODEL_KINDS` | `.catalog` | SDK.4–5 catalog/capabilities/accounting |
| [ ] | `PROBEABLE_FEATURES` | `.capabilities` | SDK.4c probes/setup metadata |
| [ ] | `AllTargetsFailedError` | `.errors` | SDK.1–3 generation/API; errors in 2b |
| [ ] | `AnthropicCountTokensEstimator` | `.capabilities` | SDK.4–5 catalog/capabilities/accounting |
| [ ] | `AnyInferConfig` | `.config` | SDK.2 providers/credentials/config |
| [ ] | `AnyInferError` | `.errors` | SDK.1–3 generation/API; errors in 2b |
| [ ] | `ArenaCompleted` | `.events` | SDK.11 sessions/evaluate/benchmark/batch |
| [ ] | `ArenaPolicy` | `.types` | SDK.11 sessions/evaluate/benchmark/batch |
| [ ] | `ArenaResult` | `.evaluate.arena` | SDK.11 sessions/evaluate/benchmark/batch |
| [ ] | `AsyncClient` | `._client` | SDK.1–3 generation/API; errors in 2b |
| [ ] | `AsyncStream` | `._client` | SDK.1–3 generation/API; errors in 2b |
| [ ] | `AttemptCompleted` | `.events` | SDK.5 events/manifest/accounting |
| [ ] | `AttemptFacet` | `.manifest` | SDK.5 events/manifest/accounting |
| [ ] | `AttemptFailed` | `.types` | SDK.1–3 generation/API; errors in 2b |
| [ ] | `AttemptRecord` | `.types` | SDK.1–3 generation/API; errors in 2b |
| [ ] | `AttemptStarted` | `.events` | SDK.5 events/manifest/accounting |
| [ ] | `AudioPart` | `.types` | SDK.7 rich content/tools |
| [ ] | `AuthError` | `.errors` | SDK.1–3 generation/API; errors in 2b |
| [ ] | `BatchCompleted` | `.events` | SDK.11 sessions/evaluate/benchmark/batch |
| [ ] | `BatchGenerationRequest` | `.types` | SDK.11 sessions/evaluate/benchmark/batch |
| [ ] | `BatchHandle` | `.types` | SDK.11 sessions/evaluate/benchmark/batch |
| [ ] | `BatchLine` | `.types` | SDK.11 sessions/evaluate/benchmark/batch |
| [ ] | `BatchPolicy` | `.types` | SDK.11 sessions/evaluate/benchmark/batch |
| [ ] | `BatchReport` | `.types` | SDK.11 sessions/evaluate/benchmark/batch |
| [ ] | `BatchResult` | `.types` | SDK.11 sessions/evaluate/benchmark/batch |
| [ ] | `BatchStatus` | `.types` | SDK.11 sessions/evaluate/benchmark/batch |
| [ ] | `BatchSubmitted` | `.events` | SDK.11 sessions/evaluate/benchmark/batch |
| [ ] | `BenchmarkSample` | `.benchmark` | SDK.11 sessions/evaluate/benchmark/batch |
| [ ] | `CacheFacet` | `.manifest` | SDK.5 events/manifest/accounting |
| [ ] | `CacheMechanism` | `.types` | SDK.9 cache placement (policy primitive referenced by SDK.5c) |
| [ ] | `CacheMode` | `.types` | SDK.9 cache placement (policy primitive referenced by SDK.5c) |
| [ ] | `CachePlanned` | `.events` | SDK.5 events/manifest/accounting |
| [ ] | `CachePolicy` | `.types` | SDK.9 cache placement (policy primitive referenced by SDK.5c) |
| [ ] | `Candidate` | `.evaluate.arena` | SDK.11 sessions/evaluate/benchmark/batch |
| [ ] | `CapabilityFacet` | `.manifest` | SDK.5 events/manifest/accounting |
| [ ] | `Catalog` | `.catalog` | SDK.4–5 catalog/capabilities/accounting |
| [ ] | `CatalogEntryFit` | `._client` | SDK.4–5 catalog/capabilities/accounting |
| [ ] | `CatalogView` | `._client` | SDK.4–5 catalog/capabilities/accounting |
| [ ] | `Citation` | `.types` | SDK.7 rich content/tools |
| [ ] | `CitationDelta` | `.types` | SDK.7 rich content/tools |
| [ ] | `Client` | `._client` | SDK.1–3 generation/API; errors in 2b |
| [ ] | `ConfidentialExecutionError` | `.errors` | SDK.2b error vocabulary; SDK.10 local attestation integration (separate add-on remains excluded) |
| [ ] | `ConfigError` | `.errors` | SDK.1–3 generation/API; errors in 2b |
| [ ] | `ContentPart` | `.types` | SDK.1–3 generation/API; errors in 2b |
| [ ] | `ContextBudget` | `.capabilities` | SDK.4–5 catalog/capabilities/accounting |
| [ ] | `ContextFacet` | `.manifest` | SDK.9 context |
| [ ] | `ContextLengthError` | `.errors` | SDK.1–3 generation/API; errors in 2b |
| [ ] | `ContextReduced` | `.events` | SDK.9 context |
| [ ] | `ContextRequest` | `.context_request` | SDK.9 context |
| [ ] | `ContextSummary` | `.context_request` | SDK.9 context |
| [ ] | `CostEstimate` | `.capabilities` | SDK.4–5 catalog/capabilities/accounting |
| [ ] | `CredentialError` | `.errors` | SDK.1–3 generation/API; errors in 2b |
| [ ] | `CredentialResolver` | `.credentials` | SDK.2 providers/credentials/config |
| [ ] | `CredentialRotated` | `.events` | SDK.5 events/manifest/accounting |
| [ ] | `Diagnostic` | `.types` | SDK.7 rich content/tools |
| [ ] | `DiagnosticSeverity` | `.types` | SDK.7 rich content/tools |
| [ ] | `DiscoveredModel` | `.types` | SDK.4–5 catalog/capabilities/accounting |
| [ ] | `DocumentPart` | `.types` | SDK.7 rich content/tools |
| [ ] | `DownloadProgress` | `.events` | SDK.10 local runtime |
| [ ] | `DroppedParameter` | `.manifest` | SDK.5 events/manifest/accounting |
| [ ] | `EmbeddingCapabilities` | `.types` | SDK.4–5 catalog/capabilities/accounting |
| [ ] | `EmbeddingInputIntent` | `.types` | SDK.6 embedding/reranking |
| [ ] | `EmbeddingRequest` | `.types` | SDK.6 embedding/reranking |
| [ ] | `EmbeddingResult` | `.types` | SDK.6 embedding/reranking |
| [ ] | `EmbeddingSpace` | `.types` | SDK.6 embedding/reranking |
| [ ] | `EmbeddingTargetComparison` | `.evaluate.compare` | SDK.6 embedding/reranking |
| [ ] | `EmbeddingVector` | `.types` | SDK.6 embedding/reranking |
| [ ] | `ErrorInfo` | `.types` | SDK.1–3 generation/API; errors in 2b |
| [ ] | `FallbackTriggered` | `.events` | SDK.5 events/manifest/accounting |
| [ ] | `Feature` | `.types` | SDK.1–3 generation/API; errors in 2b |
| [ ] | `FeatureProbe` | `.capabilities` | SDK.4–5 catalog/capabilities/accounting |
| [ ] | `FinishReason` | `.types` | SDK.1–3 generation/API; errors in 2b |
| [ ] | `FirstToken` | `.events` | SDK.5 events/manifest/accounting |
| [ ] | `Generation` | `.types` | SDK.1–3 generation/API; errors in 2b |
| [ ] | `GenerationRequest` | `.types` | SDK.1–3 generation/API; errors in 2b |
| [ ] | `Health` | `.types` | SDK.1–3 generation/API; errors in 2b |
| [ ] | `HeuristicTokenEstimator` | `.capabilities` | SDK.5b accounting/token estimation |
| [ ] | `HistoryPolicy` | `.types` | SDK.9 history compaction |
| [ ] | `HostShorthand` | `.registry` | SDK.2 providers/credentials/config |
| [ ] | `ImagePart` | `.types` | SDK.7 rich content/tools |
| [ ] | `InferenceOperation` | `.types` | SDK.1–3 generation/API; errors in 2b |
| [ ] | `JsonlObserver` | `.events` | SDK.5 events/manifest/accounting |
| [ ] | `LlamaServerTokenizeEstimator` | `.capabilities` | SDK.4–5 catalog/capabilities/accounting |
| [ ] | `LocalModelInfo` | `.types` | SDK.10 local runtime |
| [ ] | `LocalRuntimeError` | `.errors` | SDK.1–3 generation/API; errors in 2b |
| [ ] | `LoggingObserver` | `.events` | SDK.5 events/manifest/accounting |
| [ ] | `Measurement` | `.benchmark` | SDK.11 sessions/evaluate/benchmark/batch |
| [ ] | `MeasurementIdentity` | `.benchmark` | SDK.11 sessions/evaluate/benchmark/batch |
| [ ] | `MeasurementStore` | `.benchmark` | SDK.11 sessions/evaluate/benchmark/batch |
| [ ] | `Mechanism` | `.types` | SDK.1–3 generation/API; errors in 2b |
| [ ] | `MechanismRung` | `.manifest` | SDK.5 events/manifest/accounting |
| [ ] | `Message` | `.types` | SDK.1–3 generation/API; errors in 2b |
| [ ] | `MessagesInput` | `._client` | SDK.1–3 generation/API; errors in 2b |
| [ ] | `ModelCapabilities` | `.types` | SDK.4–5 catalog/capabilities/accounting |
| [ ] | `ModelEntry` | `.catalog` | SDK.4–5 catalog/capabilities/accounting |
| [ ] | `ModelKind` | `.catalog` | SDK.4–5 catalog/capabilities/accounting |
| [ ] | `ModelNotFoundError` | `.errors` | SDK.1–3 generation/API; errors in 2b |
| [ ] | `ModelVariant` | `.catalog` | SDK.4–5 catalog/capabilities/accounting |
| [ ] | `Observer` | `.events` | SDK.5 events/manifest/accounting |
| [ ] | `OllamaChannel` | `.catalog` | SDK.4–5 catalog/capabilities/accounting |
| [ ] | `Outcome` | `.types` | SDK.1–3 generation/API; errors in 2b |
| [ ] | `ParameterDropped` | `.events` | SDK.5 events/manifest/accounting |
| [ ] | `PayloadFacet` | `.manifest` | SDK.5 events/manifest/accounting |
| [ ] | `Phase` | `.errors` | SDK.1–3 generation/API; errors in 2b |
| [ ] | `PrewarmsCounts` | `.capabilities` | SDK.4–5 catalog/capabilities/accounting |
| [ ] | `Pricing` | `.types` | SDK.4–5 catalog/capabilities/accounting |
| [ ] | `PricingTable` | `.capabilities` | SDK.4–5 catalog/capabilities/accounting |
| [ ] | `ProbeOutcome` | `.capabilities` | SDK.4–5 catalog/capabilities/accounting |
| [ ] | `ProbeReport` | `.capabilities` | SDK.4–5 catalog/capabilities/accounting |
| [ ] | `Provenance` | `.types` | SDK.4–5 catalog/capabilities/accounting |
| [ ] | `ProviderDescriptor` | `.registry` | SDK.2 providers/credentials/config |
| [ ] | `ProviderDiagnostic` | `.events` | SDK.5 events/manifest/accounting |
| [ ] | `ProviderError` | `.errors` | SDK.1–3 generation/API; errors in 2b |
| [ ] | `ProviderRegistry` | `.registry` | SDK.2 providers/credentials/config |
| [ ] | `ProviderSettings` | `._client` | SDK.2 providers/credentials/config |
| [ ] | `ProviderSetupSpec` | `.registry` | SDK.2 providers/credentials/config |
| [ ] | `ProviderUnavailableError` | `.errors` | SDK.1–3 generation/API; errors in 2b |
| [ ] | `PullReport` | `.local.services` | SDK.10 local runtime |
| [ ] | `PullRequest` | `.local.services` | SDK.10 local runtime |
| [ ] | `RankedItem` | `.types` | SDK.6 embedding/reranking |
| [ ] | `RateLimitError` | `.errors` | SDK.1–3 generation/API; errors in 2b |
| [ ] | `RateLimitHeaders` | `.types` | SDK.4–5 catalog/capabilities/accounting |
| [ ] | `RateLimitObserved` | `.events` | SDK.5 events/manifest/accounting |
| [ ] | `RateLimitWaited` | `.events` | SDK.5 events/manifest/accounting |
| [ ] | `RateLimits` | `.types` | SDK.4–5 catalog/capabilities/accounting |
| [ ] | `ReasoningDelta` | `.types` | SDK.7 rich content/tools |
| [ ] | `ReasoningEffort` | `.types` | SDK.1–3 generation/API; errors in 2b |
| [ ] | `RedactionRegistry` | `.redaction` | SDK.2 providers/credentials/config |
| [ ] | `ReductionRecord` | `.manifest` | SDK.9 context |
| [ ] | `Repair` | `.types` | SDK.1–3 generation/API; errors in 2b |
| [ ] | `RepairAttempted` | `.events` | SDK.5 events/manifest/accounting |
| [ ] | `RepairRecord` | `.manifest` | SDK.5 events/manifest/accounting |
| [ ] | `RequestCompleted` | `.events` | SDK.5 events/manifest/accounting |
| [ ] | `RequestEstimate` | `.capabilities` | SDK.4–5 catalog/capabilities/accounting |
| [ ] | `RequestFacet` | `.manifest` | SDK.5 events/manifest/accounting |
| [ ] | `RequestFailed` | `.events` | SDK.5 events/manifest/accounting |
| [ ] | `RequestStarted` | `.events` | SDK.5 events/manifest/accounting |
| [ ] | `RerankCapabilities` | `.types` | SDK.4–5 catalog/capabilities/accounting |
| [ ] | `RerankDocument` | `.types` | SDK.6 embedding/reranking |
| [ ] | `RerankRequest` | `.types` | SDK.6 embedding/reranking |
| [ ] | `RerankResult` | `.types` | SDK.6 embedding/reranking |
| [ ] | `ResolvedTarget` | `.types` | SDK.1–3 generation/API; errors in 2b |
| [ ] | `ResolverChain` | `.credentials` | SDK.2 providers/credentials/config |
| [ ] | `Retry` | `.routing` | SDK.1–3 generation/API; errors in 2b |
| [ ] | `RetryScheduled` | `.events` | SDK.5 events/manifest/accounting |
| [ ] | `Role` | `.types` | SDK.1–3 generation/API; errors in 2b |
| [ ] | `Route` | `.routing` | SDK.1–3 generation/API; errors in 2b |
| [ ] | `RouteFacet` | `.manifest` | SDK.5 events/manifest/accounting |
| [ ] | `RouteStep` | `.manifest` | SDK.5 events/manifest/accounting |
| [ ] | `RunManifest` | `.manifest` | SDK.5 events/manifest/accounting |
| [ ] | `Sampling` | `.types` | SDK.1–3 generation/API; errors in 2b |
| [ ] | `SchemaFacet` | `.manifest` | SDK.5 events/manifest/accounting |
| [ ] | `SchemaSpec` | `.types` | SDK.1–3 generation/API; errors in 2b |
| [ ] | `SchemaViolationError` | `.errors` | SDK.1–3 generation/API; errors in 2b |
| [ ] | `ServerLifecycle` | `.events` | SDK.5 events/manifest/accounting |
| [ ] | `ServerToolDelta` | `.types` | SDK.7 rich content/tools |
| [ ] | `ServerToolKind` | `.types` | SDK.7 rich content/tools |
| [ ] | `ServerToolSource` | `.types` | SDK.7 rich content/tools |
| [ ] | `ServerToolSpec` | `.types` | SDK.7 rich content/tools |
| [ ] | `ServerToolUse` | `.types` | SDK.7 rich content/tools |
| [ ] | `Session` | `.session` | SDK.11 sessions/evaluate/benchmark/batch |
| [ ] | `SessionReuse` | `.session` | SDK.11 sessions/evaluate/benchmark/batch |
| [ ] | `SetupField` | `.registry` | SDK.2 providers/credentials/config |
| [ ] | `Sourced` | `.types` | SDK.4–5 catalog/capabilities/accounting |
| [ ] | `SourcedFact` | `.manifest` | SDK.5 events/manifest/accounting |
| [ ] | `SpendLedger` | `.capabilities` | SDK.4–5 catalog/capabilities/accounting |
| [ ] | `SpendLimitError` | `.errors` | SDK.1–3 generation/API; errors in 2b |
| [ ] | `SpendPolicy` | `.types` | SDK.5b/c accounting and request policy |
| [ ] | `SpendStore` | `.capabilities` | SDK.4–5 catalog/capabilities/accounting |
| [ ] | `SpendTotals` | `.capabilities` | SDK.4–5 catalog/capabilities/accounting |
| [ ] | `StreamEnded` | `.types` | SDK.1–3 generation/API; errors in 2b |
| [ ] | `StreamEvent` | `.types` | SDK.1–3 generation/API; errors in 2b |
| [ ] | `StreamProtocolError` | `.errors` | SDK.1–3 generation/API; errors in 2b |
| [ ] | `SupportsJSONSchema` | `.types` | SDK.1–3 generation/API; errors in 2b |
| [ ] | `SyncStream` | `._client` | SDK.1–3 generation/API; errors in 2b |
| [ ] | `Target` | `.types` | SDK.1–3 generation/API; errors in 2b |
| [ ] | `TargetAwareTokenEstimator` | `.capabilities` | SDK.4–5 catalog/capabilities/accounting |
| [ ] | `TargetComparison` | `.evaluate.compare` | SDK.11 evaluate/compare |
| [ ] | `TargetResolved` | `.events` | SDK.5 events/manifest/accounting |
| [ ] | `TelemetryEvent` | `.events` | SDK.5 events/manifest/accounting |
| [ ] | `Text` | `.types` | SDK.1–3 generation/API; errors in 2b |
| [ ] | `TextDelta` | `.types` | SDK.1–3 generation/API; errors in 2b |
| [ ] | `TiktokenEstimator` | `.capabilities` | SDK.4–5 catalog/capabilities/accounting |
| [ ] | `Timing` | `.types` | SDK.1–3 generation/API; errors in 2b |
| [ ] | `TimingFacet` | `.manifest` | SDK.5 events/manifest/accounting |
| [ ] | `TimingMark` | `.types` | SDK.1–3 generation/API; errors in 2b |
| [ ] | `TimingMarkName` | `.types` | SDK.1–3 generation/API; errors in 2b |
| [ ] | `TokenCalibration` | `.types` | SDK.4–5 catalog/capabilities/accounting |
| [ ] | `TokenEstimate` | `.capabilities` | SDK.4–5 catalog/capabilities/accounting |
| [ ] | `TokenEstimator` | `.capabilities` | SDK.4–5 catalog/capabilities/accounting |
| [ ] | `TokenLogprob` | `.types` | SDK.7 rich content/tools |
| [ ] | `TokenizerKind` | `.types` | SDK.4–5 catalog/capabilities/accounting |
| [ ] | `Tool` | `._client` | SDK.7 rich content/tools |
| [ ] | `ToolCall` | `.types` | SDK.7 rich content/tools |
| [ ] | `ToolCallDelta` | `.types` | SDK.7 rich content/tools |
| [ ] | `ToolChoice` | `.types` | SDK.7 rich content/tools |
| [ ] | `ToolLoopError` | `.errors` | SDK.1–3 generation/API; errors in 2b |
| [ ] | `ToolResult` | `.types` | SDK.7 rich content/tools |
| [ ] | `ToolSpec` | `.types` | SDK.7 rich content/tools |
| [ ] | `TransportError` | `.errors` | SDK.1–3 generation/API; errors in 2b |
| [ ] | `UnsupportedInputError` | `.errors` | SDK.1–3 generation/API; errors in 2b |
| [ ] | `Usage` | `.types` | SDK.1–3 generation/API; errors in 2b |
| [ ] | `UsageEstimated` | `.events` | SDK.5 events/manifest/accounting |
| [ ] | `UsageFacet` | `.manifest` | SDK.5 events/manifest/accounting |
| [ ] | `UsageUpdate` | `.types` | SDK.1–3 generation/API; errors in 2b |
| [ ] | `Verification` | `.verification` | SDK.11 sessions/evaluate/benchmark/batch |
| [ ] | `VideoPart` | `.types` | SDK.7 rich content/tools |
| [ ] | `__version__` | `(inspect root import; implicit/indirect export)` | SDK.0 inventory / metadata |
| [ ] | `assistant` | `.types` | SDK.7 rich content/tools |
| [ ] | `build_context_budget` | `.capabilities` | SDK.4–5 catalog/capabilities/accounting |
| [ ] | `check_context_fit` | `.capabilities` | SDK.4–5 catalog/capabilities/accounting |
| [ ] | `default_registry` | `.registry` | SDK.2 providers/credentials/config |
| [ ] | `default_resolver` | `.credentials` | SDK.2 providers/credentials/config |
| [ ] | `dump_config` | `.config` | SDK.2 providers/credentials/config |
| [ ] | `dumps_config` | `.config` | SDK.2 providers/credentials/config |
| [ ] | `estimate_request` | `.capabilities` | SDK.4–5 catalog/capabilities/accounting |
| [ ] | `fetch_pricing` | `.capabilities` | SDK.4–5 catalog/capabilities/accounting |
| [ ] | `load_config` | `.config` | SDK.2 providers/credentials/config |
| [ ] | `load_default_catalog` | `.catalog` | SDK.4–5 catalog/capabilities/accounting |
| [ ] | `load_default_pricing` | `.capabilities` | SDK.4–5 catalog/capabilities/accounting |
| [ ] | `loads_config` | `.config` | SDK.2 providers/credentials/config |
| [ ] | `manifest_json_schema` | `.manifest` | SDK.5 events/manifest/accounting |
| [ ] | `redact` | `.redaction` | SDK.2 providers/credentials/config |
| [ ] | `register_secret` | `.redaction` | SDK.2 providers/credentials/config |
| [ ] | `semantic_ranker` | `._client` | SDK.9 context |
| [ ] | `system` | `.types` | SDK.7 rich content/tools |
| [ ] | `tool` | `._client` | SDK.7 rich content/tools |
| [ ] | `user` | `.types` | SDK.7 rich content/tools |

## Per-export evidence ledger

This ledger is separate from the final-completion checklist. It records bounded, source- and test-backed public C# behavior, not an overall parity percentage. `implemented` is the stated bounded native behavior; `partial` names a concrete remaining gap; `deferred` has no current public equivalent; and `different` is an approved behavior difference. The original 235 checkboxes remain the final-completion signal.

| Python export | Status | C# public symbols | Native source | Test evidence | Milestone | Scope and remaining gap |
|---|---|---|---|---|---|---|
| `BENCHMARK_OUTPUT_TOKENS` | `deferred` | — | — | `src/python/anyinfer/benchmark.py`<br>`tests/test_benchmark.py` | SDK.11a | Benchmark output-token key and persisted measurement path have no native benchmark API. |
| `BENCHMARK_PROMPT_TOKENS` | `deferred` | — | — | `src/python/anyinfer/benchmark.py`<br>`tests/test_benchmark.py` | SDK.11a | Benchmark prompt-token key and persisted measurement path have no native benchmark API. |
| `BEST_AT` | `implemented` | `P:AnyInfer.Catalog.Catalog.BestAtCategories`<br>`P:AnyInfer.Catalog.ModelEntry.BestAt` | `src/csharp/AnyInfer/Catalog/CatalogTypes.cs`<br>`src/csharp/AnyInfer/Catalog/Catalog.cs` | `src/csharp/AnyInfer.Tests/CatalogTests.cs` | SDK.4a | Catalog.BestAtCategories exposes the same 14-category immutable ordinal set as Python BEST_AT; the native parser validates tags against that same set, while ModelEntry exposes stored tags. |
| `CONFIG_FORMAT_VERSION` | `implemented` | `F:AnyInfer.Config.AnyInferConfig.FormatVersion1` | `src/csharp/AnyInfer/Config/AnyInferConfig.cs` | `src/csharp/AnyInfer.Tests/ConfigTests.cs` | SDK.2c | Native v1 configuration format constant has the same value. |
| `DEFAULT_PROBE_FEATURES` | `implemented` | `P:AnyInfer.Capabilities.CapabilityProbes.DefaultProbeFeatures` | `src/csharp/AnyInfer/Capabilities/Probes.cs` | `src/csharp/AnyInfer.Tests/CapabilityProbeTests.cs` | SDK.4c | Native immutable ordered default probe-feature selection matches Python's four defaults. |
| `MANIFEST_FORMAT` | `implemented` | `F:AnyInfer.Manifest.ManifestUtilities.Format` | `src/csharp/AnyInfer/Manifest/ManifestUtilities.cs` | `src/csharp/AnyInfer.Tests/ManifestFormatTests.cs` | SDK.5a | Manifest format constant and serialization contract |
| `MAX_CONFIG_BYTES` | `implemented` | `F:AnyInfer.Config.AnyInferConfig.MaximumBytes` | `src/csharp/AnyInfer/Config/AnyInferConfig.cs` | `src/csharp/AnyInfer.Tests/ConfigTests.cs` | SDK.2c | Native configuration maximum is the same 1 MiB bound. |
| `MODEL_KINDS` | `implemented` | `T:AnyInfer.Catalog.ModelKind`<br>`F:AnyInfer.Catalog.ModelKind.Generation`<br>`F:AnyInfer.Catalog.ModelKind.Embedding` | `src/csharp/AnyInfer/Catalog/CatalogTypes.cs` | `src/csharp/AnyInfer.Tests/CatalogTests.cs` | SDK.4a | Native ModelKind enum carries the same generation and embedding categories. |
| `PROBEABLE_FEATURES` | `implemented` | `P:AnyInfer.Capabilities.CapabilityProbes.ProbeableFeatures` | `src/csharp/AnyInfer/Capabilities/Probes.cs` | `src/csharp/AnyInfer.Tests/CapabilityProbeTests.cs` | SDK.4c | Native immutable ordered probeable-feature selection matches Python's five features. |
| `AllTargetsFailedError` | `implemented` | `T:AnyInfer.AllTargetsFailedException` | `src/csharp/AnyInfer/Errors.cs` | `src/csharp/AnyInfer.Tests/PublicModelTests.cs` | SDK.2b | AllTargetsFailedError maps to the native typed exception hierarchy, retaining category, retryability, nullable phase, and provider/HTTP diagnostic context. |
| `AnthropicCountTokensEstimator` | `deferred` | — | — | `tests/test_remote_tokenizers.py` | SDK.5b | Python remote Anthropic count_tokens estimator has no native public API. |
| `AnyInferConfig` | `partial` | `T:AnyInfer.Config.AnyInferConfig`<br>`M:AnyInfer.Config.AnyInferConfig.Load`<br>`M:AnyInfer.Config.AnyInferConfig.Loads`<br>`M:AnyInfer.Config.AnyInferConfig.Dump`<br>`M:AnyInfer.Config.AnyInferConfig.Dumps`<br>`P:AnyInfer.Config.AnyInferConfig.Providers`<br>`P:AnyInfer.Config.AnyInferConfig.Route`<br>`P:AnyInfer.Config.AnyInferConfig.Repair`<br>`P:AnyInfer.Config.AnyInferConfig.FormatVersion`<br>`P:AnyInfer.Config.AnyInferConfig.Cache`<br>`P:AnyInfer.Config.AnyInferConfig.OperationRoutes`<br>`F:AnyInfer.Config.AnyInferConfig.FormatVersion1`<br>`F:AnyInfer.Config.AnyInferConfig.MaximumBytes` | `src/csharp/AnyInfer/Config/AnyInferConfig.cs` | `src/csharp/AnyInfer.Tests/ConfigTests.cs` | SDK.2c | Validated v1 providers/routes/repair/cache/operation-routes subset is native; Python context, history, observers, arena, MCP, and related configuration remain unsupported. |
| `AnyInferError` | `implemented` | `T:AnyInfer.AnyInferException` | `src/csharp/AnyInfer/Errors.cs` | `src/csharp/AnyInfer.Tests/PublicModelTests.cs` | SDK.2b | AnyInferError maps to the native typed exception hierarchy, retaining category, retryability, nullable phase, and provider/HTTP diagnostic context. |
| `ArenaCompleted` | `partial` | `T:AnyInfer.Events.ArenaCompleted` | `src/csharp/AnyInfer/Events/TelemetryEvent.cs` | `src/csharp/AnyInfer.Tests/TelemetryTests.cs` | SDK.11a | Public telemetry DTO is serializable, but bounded arena evaluation has no native producer. |
| `ArenaPolicy` | `deferred` | — | — | `src/python/anyinfer/types/requests.py` | SDK.11a | Arena candidate fan-out, judging, accounting, and policy hooks have no native implementation. |
| `ArenaResult` | `deferred` | — | — | `src/python/anyinfer/evaluate/arena.py`<br>`tests/test_arena.py` | SDK.11a | Arena aggregate result and deterministic selection are unported. |
| `AsyncClient` | `partial` | `T:AnyInfer.AsyncClient` | `src/csharp/AnyInfer/AsyncClient.cs` | `src/csharp/AnyInfer.Tests/SdkMigrationTests.cs`<br>`src/csharp/AnyInfer.Tests/SyncClientTests.cs` | SDK.1a | AsyncClient supports bounded generation and retrieval execution; context, local lifecycle, session, arena, and provider batch-job breadth remain unimplemented. |
| `AsyncStream` | `partial` | `T:AnyInfer.AsyncStream` | `src/csharp/AnyInfer/GenerationStream.cs` | `src/csharp/AnyInfer.Tests/SdkMigrationTests.cs`<br>`src/csharp/AnyInfer.Tests/SyncClientTests.cs` | SDK.1a | Lazy single-consumer async generation events, Result, CollectAsync, cancellation/disposal and optional manifest capture are native. Terminal Generation still lacks Python cache_mechanism, arena and context_reduction fields. Retrieval APIs are buffered and do not return this stream. |
| `AttemptCompleted` | `implemented` | `T:AnyInfer.Events.AttemptCompleted` | `src/csharp/AnyInfer/Core/GenerationCore.cs`<br>`src/csharp/AnyInfer/Core/RetrievalCore.cs` | `src/csharp/AnyInfer.Tests/EventLifecycleTests.cs` | SDK.5a | Generation and retrieval cores emit successful attempt facts. |
| `AttemptFacet` | `implemented` | `T:AnyInfer.Manifest.AttemptFacet` | `src/csharp/AnyInfer/Manifest/ManifestFacets.cs` | `src/csharp/AnyInfer.Tests/ManifestValueTests.cs` | SDK.5a | Typed manifest facet/DTO is present; ordinary request/result manifest projection bounded to implemented facets |
| `AttemptFailed` | `implemented` | `T:AnyInfer.AttemptFailed` | `src/csharp/AnyInfer/GenerationEvent.cs` | `src/csharp/AnyInfer.Tests/SdkMigrationTests.cs` | SDK.1a | AttemptFailed is emitted by the native typed stream and is exercised while reconstructing a terminal generation from actual stream events. |
| `AttemptRecord` | `implemented` | `T:AnyInfer.AttemptRecord` | `src/csharp/AnyInfer/Models.cs` | `src/csharp/AnyInfer.Tests/PublicModelTests.cs`<br>`src/csharp/AnyInfer.Tests/SdkMigrationTests.cs` | SDK.1a | AttemptRecord preserves the nullable target/error/timing and the outcome for each routed attempt; its copied trail is asserted with a provider failure. |
| `AttemptStarted` | `implemented` | `T:AnyInfer.Events.AttemptStarted` | `src/csharp/AnyInfer/Core/GenerationCore.cs`<br>`src/csharp/AnyInfer/Core/RetrievalCore.cs` | `src/csharp/AnyInfer.Tests/EventLifecycleTests.cs` | SDK.5a | Generation and retrieval cores emit attempt-start facts. |
| `AudioPart` | `implemented` | `T:AnyInfer.AudioPart` | `src/csharp/AnyInfer/MediaParts.cs` | `src/csharp/AnyInfer.Tests/RichGenerationTypesTests.cs`<br>`src/csharp/AnyInfer.Tests/RichGenerationParityTests.cs` | SDK.7a | AudioPart is represented by the native rich-generation DTO/event surface, with immutable copied data and provider-wire parity exercised by rich-generation tests. |
| `AuthError` | `implemented` | `T:AnyInfer.AuthException` | `src/csharp/AnyInfer/Errors.cs` | `src/csharp/AnyInfer.Tests/PublicModelTests.cs` | SDK.2b | AuthError maps to the native typed exception hierarchy, retaining category, retryability, nullable phase, and provider/HTTP diagnostic context. |
| `BatchCompleted` | `partial` | `T:AnyInfer.Events.BatchCompleted` | `src/csharp/AnyInfer/Events/TelemetryEvent.cs` | `src/csharp/AnyInfer.Tests/TelemetryTests.cs` | SDK.11a | Public telemetry DTO is serializable, but provider batch collection has no native producer. |
| `BatchGenerationRequest` | `deferred` | — | — | `src/python/anyinfer/types/operations.py` | SDK.11a | Provider-managed generation batch submission is absent; BatchPolicy only covers core retrieval splitting. |
| `BatchHandle` | `deferred` | — | — | `src/python/anyinfer/types/operations.py` | SDK.11a | No native provider batch-job handle, polling, cancellation, or result-download API exists. |
| `BatchLine` | `deferred` | — | — | `src/python/anyinfer/types/operations.py` | SDK.11a | No native provider batch input-line representation exists because provider batch jobs are deferred. |
| `BatchPolicy` | `implemented` | `T:AnyInfer.BatchPolicy` | `src/csharp/AnyInfer/BatchPolicy.cs` | `src/csharp/AnyInfer.Tests/RetrievalDomainTests.cs`<br>`src/csharp/AnyInfer.Tests/RetrievalRoutingBatchTests.cs` | SDK.11a | BatchPolicy controls core-owned retrieval input splitting and bounded concurrent dispatch; it does not implement provider generation-batch submission, polling, cancellation, or collection. |
| `BatchReport` | `deferred` | — | — | `src/python/anyinfer/types/operations.py` | SDK.11a | No native batch progress/report aggregate exists because provider batch jobs are deferred. |
| `BatchResult` | `deferred` | — | — | `src/python/anyinfer/types/operations.py` | SDK.11a | No native provider batch result envelope exists because provider batch jobs are deferred. |
| `BatchStatus` | `deferred` | — | — | `src/python/anyinfer/types/operations.py` | SDK.11a | No native queued/in-progress/completed/failed/expired/cancelled provider-job state exists. |
| `BatchSubmitted` | `partial` | `T:AnyInfer.Events.BatchSubmitted` | `src/csharp/AnyInfer/Events/TelemetryEvent.cs` | `src/csharp/AnyInfer.Tests/TelemetryTests.cs` | SDK.11a | Public telemetry DTO is serializable, but provider batch submission has no native producer. |
| `BenchmarkSample` | `deferred` | — | — | `src/python/anyinfer/benchmark.py`<br>`tests/test_benchmark.py` | SDK.11a | Benchmark sample collection and persistence are unported. |
| `CacheFacet` | `implemented` | `T:AnyInfer.Manifest.CacheFacet` | `src/csharp/AnyInfer/Manifest/ManifestFacets.cs` | `src/csharp/AnyInfer.Tests/ManifestValueTests.cs` | SDK.5a | Typed manifest facet/DTO is present; ordinary request/result manifest projection bounded to implemented facets |
| `CacheMechanism` | `implemented` | `T:AnyInfer.Capabilities.CacheMechanism` | `src/csharp/AnyInfer/Capabilities/CachePlan.cs` | `src/csharp/AnyInfer.Tests/CapabilityTests.cs`<br>`src/csharp/AnyInfer.Tests/CapabilityAssemblyTests.cs` | SDK.9a | CacheMechanism maps to provenance-aware native capability metadata; catalog/probe assembly tests exercise its operation-specific fields. |
| `CacheMode` | `implemented` | `T:AnyInfer.CacheMode` | `src/csharp/AnyInfer/CachePolicy.cs` | `src/csharp/AnyInfer.Tests/CachePlanningTests.cs` | SDK.9a | CacheMode exposes Off, Auto, and Explicit policy values used by CachePolicy. |
| `CachePlanned` | `implemented` | `T:AnyInfer.Events.CachePlanned` | `src/csharp/AnyInfer/Core/GenerationCore.cs` | `src/csharp/AnyInfer.Tests/CachePlanningTests.cs` | SDK.5c | Generation policy emits cache-plan telemetry when a plan is engaged. |
| `CachePolicy` | `implemented` | `T:AnyInfer.CachePolicy` | `src/csharp/AnyInfer/CachePolicy.cs` | `src/csharp/AnyInfer.Tests/CachePlanningTests.cs` | SDK.9a | CachePolicy carries cache placement mode and optional retention/placement controls into request policy. |
| `Candidate` | `deferred` | — | — | `src/python/anyinfer/evaluate/arena.py`<br>`tests/test_arena.py` | SDK.11a | Arena candidate selection, fan-out and cancellation behavior are unported. |
| `CapabilityFacet` | `implemented` | `T:AnyInfer.Manifest.CapabilityFacet` | `src/csharp/AnyInfer/Manifest/ManifestFacets.cs` | `src/csharp/AnyInfer.Tests/ManifestValueTests.cs` | SDK.5a | Typed manifest facet/DTO is present; ordinary request/result manifest projection bounded to implemented facets |
| `Catalog` | `implemented` | `T:AnyInfer.Catalog.Catalog`<br>`M:AnyInfer.Catalog.Catalog.Alias`<br>`M:AnyInfer.Catalog.Catalog.AliasNames`<br>`M:AnyInfer.Catalog.Catalog.Artifact`<br>`M:AnyInfer.Catalog.Catalog.FromMapping`<br>`M:AnyInfer.Catalog.Catalog.HasAlias`<br>`M:AnyInfer.Catalog.Catalog.Load`<br>`M:AnyInfer.Catalog.Catalog.LoadDefault`<br>`M:AnyInfer.Catalog.Catalog.Loads`<br>`M:AnyInfer.Catalog.Catalog.Model`<br>`M:AnyInfer.Catalog.Catalog.ModelsFor`<br>`M:AnyInfer.Catalog.Catalog.Overlay`<br>`M:AnyInfer.Catalog.Catalog.ResolveTarget`<br>`M:AnyInfer.Catalog.Catalog.TargetsForAlias`<br>`M:AnyInfer.Catalog.Catalog.WithAliasTarget` | `src/csharp/AnyInfer/Catalog/Catalog.cs`<br>`src/csharp/AnyInfer/Catalog/CatalogTypes.cs` | `src/csharp/AnyInfer.Tests/CatalogTests.cs`<br>`tests/test_sdk_catalog_parity.py` | SDK.4a | Native catalog loads, overlays, resolves aliases, models, and artifacts. |
| `CatalogEntryFit` | `deferred` | — | — | `src/python/anyinfer/_client/models.py` | SDK.4a | Native catalog lookup lacks the Python catalog-fit record and its requested-versus-available comparison. |
| `CatalogView` | `deferred` | — | — | `src/python/anyinfer/_client/models.py` | SDK.4a | Native catalog lookup lacks the Python catalog view wrapper and its filtered entry presentation. |
| `Citation` | `implemented` | `T:AnyInfer.Citation` | `src/csharp/AnyInfer/RichGeneration.cs` | `src/csharp/AnyInfer.Tests/RichGenerationTypesTests.cs`<br>`src/csharp/AnyInfer.Tests/RichGenerationParityTests.cs` | SDK.7a | Citation is represented by the native rich-generation DTO/event surface, with immutable copied data and provider-wire parity exercised by rich-generation tests. |
| `CitationDelta` | `implemented` | `T:AnyInfer.CitationDelta` | `src/csharp/AnyInfer/GenerationEvent.cs` | `src/csharp/AnyInfer.Tests/RichGenerationTypesTests.cs`<br>`src/csharp/AnyInfer.Tests/RichGenerationParityTests.cs` | SDK.7a | CitationDelta is represented by the native rich-generation DTO/event surface, with immutable copied data and provider-wire parity exercised by rich-generation tests. |
| `Client` | `partial` | `T:AnyInfer.Client` | `src/csharp/AnyInfer/Client.cs` | `src/csharp/AnyInfer.Tests/SdkMigrationTests.cs`<br>`src/csharp/AnyInfer.Tests/SyncClientTests.cs` | SDK.1a | Client supports bounded generation and retrieval execution; context, local lifecycle, session, arena, and provider batch-job breadth remain unimplemented. |
| `ConfidentialExecutionError` | `deferred` | — | — | `src/python/anyinfer/errors.py` | SDK.2b | The native SDK does not expose confidential execution/attestation failure handling. |
| `ConfigError` | `implemented` | `T:AnyInfer.ConfigException` | `src/csharp/AnyInfer/Errors.cs` | `src/csharp/AnyInfer.Tests/PublicModelTests.cs` | SDK.2b | ConfigError maps to the native typed exception hierarchy, retaining category, retryability, nullable phase, and provider/HTTP diagnostic context. |
| `ContentPart` | `implemented` | `T:AnyInfer.ContentPart` | `src/csharp/AnyInfer/Models.cs` | `src/csharp/AnyInfer.Tests/PublicModelTests.cs`<br>`src/csharp/AnyInfer.Tests/SdkMigrationTests.cs` | SDK.1a | ContentPart is the native base for immutable message content; concrete Text and media parts are defensively copied into Message.Content. |
| `ContextBudget` | `implemented` | `T:AnyInfer.Capabilities.ContextBudget`<br>`P:AnyInfer.Capabilities.ContextBudget.ContextWindow`<br>`P:AnyInfer.Capabilities.ContextBudget.Estimate`<br>`P:AnyInfer.Capabilities.ContextBudget.EstimatedCost`<br>`P:AnyInfer.Capabilities.ContextBudget.Fits`<br>`P:AnyInfer.Capabilities.ContextBudget.HeadroomTokens`<br>`P:AnyInfer.Capabilities.ContextBudget.InputAllowanceTokens`<br>`P:AnyInfer.Capabilities.ContextBudget.OutputReserveTokens`<br>`P:AnyInfer.Capabilities.ContextBudget.Pricing`<br>`P:AnyInfer.Capabilities.ContextBudget.RemainingTokens` | `src/csharp/AnyInfer/Capabilities/ContextBudget.cs` | `src/csharp/AnyInfer.Tests/PricingAndBudgetTests.cs` | SDK.4b | Native budget result exposes allowance, fit, headroom, remaining tokens, and cost. |
| `ContextFacet` | `partial` | `T:AnyInfer.Manifest.ContextFacet` | `src/csharp/AnyInfer/Manifest/ManifestFacets.cs` | `src/csharp/AnyInfer.Tests/ManifestValueTests.cs` | SDK.9 | DTO exists, but native context-reduction producer/arena-batch context accounting is absent |
| `ContextLengthError` | `implemented` | `T:AnyInfer.ContextLengthException` | `src/csharp/AnyInfer/Errors.cs` | `src/csharp/AnyInfer.Tests/PublicModelTests.cs` | SDK.2b | ContextLengthError maps to the native typed exception hierarchy, retaining category, retryability, nullable phase, and provider/HTTP diagnostic context. |
| `ContextReduced` | `partial` | `T:AnyInfer.Events.ContextReduced` | `src/csharp/AnyInfer/Events/TelemetryEvent.cs` | `src/csharp/AnyInfer.Tests/TelemetryTests.cs` | SDK.9 | Telemetry DTO is serializable, but native context reduction has no producer. |
| `ContextRequest` | `deferred` | — | — | `src/python/anyinfer/context_request.py`<br>`tests/test_sidecar_context.py` | SDK.9 | Context request construction, compaction and history controls are unported. |
| `ContextSummary` | `deferred` | — | — | `src/python/anyinfer/context_request.py`<br>`tests/test_sidecar_context.py` | SDK.9 | Context reduction summary and sidecar projection are unported. |
| `CostEstimate` | `implemented` | `T:AnyInfer.Capabilities.CostEstimate`<br>`P:AnyInfer.Capabilities.CostEstimate.Currency`<br>`P:AnyInfer.Capabilities.CostEstimate.High`<br>`P:AnyInfer.Capabilities.CostEstimate.Low` | `src/csharp/AnyInfer/Capabilities/PricingCalculator.cs` | `src/csharp/AnyInfer.Tests/PricingAndBudgetTests.cs` | SDK.4b | Native low/high bounded cost estimate retains currency. |
| `CredentialError` | `implemented` | `T:AnyInfer.CredentialException` | `src/csharp/AnyInfer/Errors.cs` | `src/csharp/AnyInfer.Tests/PublicModelTests.cs` | SDK.2b | CredentialError maps to the native typed exception hierarchy, retaining category, retryability, nullable phase, and provider/HTTP diagnostic context. |
| `CredentialResolver` | `implemented` | `T:AnyInfer.Credentials.ICredentialResolver`<br>`M:AnyInfer.Credentials.ICredentialResolver.Handles`<br>`M:AnyInfer.Credentials.ICredentialResolver.ResolveAsync` | `src/csharp/AnyInfer/Credentials/ICredentialResolver.cs` | `src/csharp/AnyInfer.Tests/CredentialsTests.cs` | SDK.2b | Native asynchronous resolver interface is the C# equivalent of the Python credential resolver protocol. |
| `CredentialRotated` | `partial` | `T:AnyInfer.Events.CredentialRotated` | `src/csharp/AnyInfer/Events/TelemetryEvent.cs` | `src/csharp/AnyInfer.Tests/TelemetryTests.cs` | SDK.11c | Telemetry DTO exists, but credential TTL, refresh and rotation execution are outstanding. |
| `Diagnostic` | `implemented` | `T:AnyInfer.Diagnostic` | `src/csharp/AnyInfer/Diagnostic.cs` | `src/csharp/AnyInfer.Tests/RichGenerationTypesTests.cs`<br>`src/csharp/AnyInfer.Tests/RichGenerationParityTests.cs` | SDK.7a | Diagnostic is represented by the native rich-generation DTO/event surface, with immutable copied data and provider-wire parity exercised by rich-generation tests. |
| `DiagnosticSeverity` | `implemented` | `P:AnyInfer.Diagnostic.Severity` | `src/csharp/AnyInfer/Diagnostic.cs` | `src/csharp/AnyInfer.Tests/RichGenerationDiagnosticParityTests.cs` | SDK.7a | Advisory info/warning severity is retained as Diagnostic.Severity and travels with diagnostic parity events. |
| `DiscoveredModel` | `implemented` | `T:AnyInfer.Capabilities.DiscoveredModel` | `src/csharp/AnyInfer/Capabilities/CapabilityMetadata.cs` | `src/csharp/AnyInfer.Tests/CapabilityTests.cs`<br>`src/csharp/AnyInfer.Tests/CapabilityAssemblyTests.cs` | SDK.4a | DiscoveredModel maps to provenance-aware native capability metadata; catalog/probe assembly tests exercise its operation-specific fields. |
| `DocumentPart` | `implemented` | `T:AnyInfer.DocumentPart` | `src/csharp/AnyInfer/MediaParts.cs` | `src/csharp/AnyInfer.Tests/RichGenerationTypesTests.cs`<br>`src/csharp/AnyInfer.Tests/RichGenerationParityTests.cs` | SDK.7a | DocumentPart is represented by the native rich-generation DTO/event surface, with immutable copied data and provider-wire parity exercised by rich-generation tests. |
| `DownloadProgress` | `partial` | `T:AnyInfer.Events.DownloadProgress` | `src/csharp/AnyInfer/Events/TelemetryEvent.cs` | `src/csharp/AnyInfer.Tests/TelemetryTests.cs` | SDK.10 | Telemetry DTO exists, but native local runtime download supervision is unported. |
| `DroppedParameter` | `implemented` | `T:AnyInfer.Manifest.DroppedParameter` | `src/csharp/AnyInfer/Manifest/ManifestFacets.cs` | `src/csharp/AnyInfer.Tests/ManifestValueTests.cs` | SDK.5a | Typed manifest facet/DTO is present; ordinary request/result manifest projection bounded to implemented facets |
| `EmbeddingCapabilities` | `implemented` | `T:AnyInfer.Capabilities.EmbeddingCapabilities` | `src/csharp/AnyInfer/Capabilities/CapabilityMetadata.cs` | `src/csharp/AnyInfer.Tests/CapabilityTests.cs`<br>`src/csharp/AnyInfer.Tests/CapabilityAssemblyTests.cs` | SDK.4a | EmbeddingCapabilities maps to provenance-aware native capability metadata; catalog/probe assembly tests exercise its operation-specific fields. |
| `EmbeddingInputIntent` | `implemented` | `T:AnyInfer.Capabilities.EmbeddingInputIntent` | `src/csharp/AnyInfer/Capabilities/CapabilityMetadata.cs` | `src/csharp/AnyInfer.Tests/CapabilityTests.cs`<br>`src/csharp/AnyInfer.Tests/CapabilityAssemblyTests.cs` | SDK.6a | EmbeddingInputIntent maps to provenance-aware native capability metadata; catalog/probe assembly tests exercise its operation-specific fields. |
| `EmbeddingRequest` | `implemented` | `T:AnyInfer.EmbeddingRequest` | `src/csharp/AnyInfer/EmbeddingRequest.cs` | `src/csharp/AnyInfer.Tests/RetrievalDomainTests.cs`<br>`src/csharp/AnyInfer.Tests/RetrievalRoutingBatchTests.cs` | SDK.6a | EmbeddingRequest is the native retrieval value/policy surface; its request ordering, copied inputs, provider result identity, and batch-routing behavior are exercised by retrieval tests. |
| `EmbeddingResult` | `implemented` | `T:AnyInfer.EmbeddingResult` | `src/csharp/AnyInfer/EmbeddingResult.cs` | `src/csharp/AnyInfer.Tests/RetrievalDomainTests.cs`<br>`src/csharp/AnyInfer.Tests/RetrievalRoutingBatchTests.cs` | SDK.6a | EmbeddingResult is the native retrieval value/policy surface; its request ordering, copied inputs, provider result identity, and batch-routing behavior are exercised by retrieval tests. |
| `EmbeddingSpace` | `implemented` | `T:AnyInfer.EmbeddingSpace` | `src/csharp/AnyInfer/EmbeddingSpace.cs` | `src/csharp/AnyInfer.Tests/RetrievalDomainTests.cs`<br>`src/csharp/AnyInfer.Tests/RetrievalRoutingBatchTests.cs` | SDK.6a | EmbeddingSpace is the native retrieval value/policy surface; its request ordering, copied inputs, provider result identity, and batch-routing behavior are exercised by retrieval tests. |
| `EmbeddingTargetComparison` | `deferred` | — | — | `src/python/anyinfer/evaluate/compare.py`<br>`tests/test_compare.py` | SDK.11a | Cross-target embedding comparison and evaluation result aggregation are unported. |
| `EmbeddingVector` | `implemented` | `T:AnyInfer.EmbeddingVector` | `src/csharp/AnyInfer/EmbeddingVector.cs` | `src/csharp/AnyInfer.Tests/RetrievalDomainTests.cs`<br>`src/csharp/AnyInfer.Tests/RetrievalRoutingBatchTests.cs` | SDK.6a | EmbeddingVector is the native retrieval value/policy surface; its request ordering, copied inputs, provider result identity, and batch-routing behavior are exercised by retrieval tests. |
| `ErrorInfo` | `implemented` | `T:AnyInfer.ErrorInfo` | `src/csharp/AnyInfer/Errors.cs` | `src/csharp/AnyInfer.Tests/PublicModelTests.cs`<br>`src/csharp/AnyInfer.Tests/SdkMigrationTests.cs` | SDK.1a | ErrorInfo exposes category, retryability, phase, provider, retry-after, HTTP status, bounded detail, and actionable hint from a typed failure. |
| `FallbackTriggered` | `implemented` | `T:AnyInfer.Events.FallbackTriggered` | `src/csharp/AnyInfer/Core/GenerationCore.cs`<br>`src/csharp/AnyInfer/Core/RetrievalCore.cs` | `src/csharp/AnyInfer.Tests/EventLifecycleTests.cs` | SDK.5a | Generation and retrieval routing emit fallback facts. |
| `Feature` | `implemented` | `T:AnyInfer.Capabilities.Feature` | `src/csharp/AnyInfer/Capabilities/CapabilityMetadata.cs` | `src/csharp/AnyInfer.Tests/CapabilityTests.cs`<br>`src/csharp/AnyInfer.Tests/CapabilityAssemblyTests.cs` | SDK.1a | Feature maps to provenance-aware native capability metadata; catalog/probe assembly tests exercise its operation-specific fields. |
| `FeatureProbe` | `implemented` | `T:AnyInfer.Capabilities.FeatureProbe`<br>`P:AnyInfer.Capabilities.FeatureProbe.Feature`<br>`P:AnyInfer.Capabilities.FeatureProbe.Outcome`<br>`P:AnyInfer.Capabilities.FeatureProbe.Detail`<br>`P:AnyInfer.Capabilities.FeatureProbe.Conclusive` | `src/csharp/AnyInfer/Capabilities/Probes.cs` | `src/csharp/AnyInfer.Tests/CapabilityProbeTests.cs` | SDK.4c | Immutable native feature-probe result and conclusive outcome. |
| `FinishReason` | `implemented` | `P:AnyInfer.Generation.FinishReason` | `src/csharp/AnyInfer/Models.cs` | `src/csharp/AnyInfer.Tests/SdkMigrationTests.cs` | SDK.1a | The normalized terminal reason is exposed as Generation.FinishReason rather than a standalone C# alias type. |
| `FirstToken` | `implemented` | `T:AnyInfer.Events.FirstToken` | `src/csharp/AnyInfer/Core/GenerationCore.cs` | `src/csharp/AnyInfer.Tests/EventLifecycleTests.cs` | SDK.5a | Generation streaming emits first-token timing facts. |
| `Generation` | `partial` | `T:AnyInfer.Generation` | `src/csharp/AnyInfer/Models.cs` | `src/csharp/AnyInfer.Tests/PublicModelTests.cs`<br>`src/csharp/AnyInfer.Tests/RichGenerationTypesTests.cs` | SDK.1a/9/11a | Generation retains text, structured value, target, finish reason, usage, timing, structured mechanism, repair trail, warnings, manifest, tool calls, raw payload, logprobs, citations and server-tool uses; Python cache_mechanism, arena result and context_reduction fields are absent. |
| `GenerationRequest` | `partial` | `T:AnyInfer.GenerationRequest` | `src/csharp/AnyInfer/Models.cs` | `src/csharp/AnyInfer.Tests/PublicModelTests.cs`<br>`src/csharp/AnyInfer.Tests/RichGenerationTypesTests.cs` | SDK.1a/9/11a | GenerationRequest snapshots messages/tools/options/metadata and retains route, sampling, repair, schema/mechanism, timeout, response/input byte ceilings, stream, cache, reasoning, logprobs, citations and server tools; Python history, arena, context and effective_timeout_s convenience are absent. |
| `Health` | `implemented` | `T:AnyInfer.Capabilities.Health` | `src/csharp/AnyInfer/Capabilities/CapabilityMetadata.cs` | `src/csharp/AnyInfer.Tests/CapabilityTests.cs`<br>`src/csharp/AnyInfer.Tests/CapabilityAssemblyTests.cs` | SDK.1a | Health maps to provenance-aware native capability metadata; catalog/probe assembly tests exercise its operation-specific fields. |
| `HeuristicTokenEstimator` | `implemented` | `T:AnyInfer.Capabilities.HeuristicTokenEstimator`<br>`M:AnyInfer.Capabilities.HeuristicTokenEstimator.Estimate`<br>`P:AnyInfer.Capabilities.HeuristicTokenEstimator.Multiplier` | `src/csharp/AnyInfer/Capabilities/HeuristicTokenEstimator.cs` | `src/csharp/AnyInfer.Tests/CapabilityTests.cs` | SDK.5b | Native UTF-8 heuristic token estimator. |
| `HistoryPolicy` | `deferred` | — | — | `src/python/anyinfer/types/requests.py` | SDK.9a | Native request execution has no conversation-history compaction policy. |
| `HostShorthand` | `implemented` | `T:AnyInfer.Providers.HostShorthand`<br>`M:AnyInfer.Providers.HostShorthand.Expand`<br>`P:AnyInfer.Providers.HostShorthand.Scheme`<br>`P:AnyInfer.Providers.HostShorthand.DefaultPort` | `src/csharp/AnyInfer/Providers/ProviderSetupSpec.cs` | `src/csharp/AnyInfer.Tests/ProviderSetupTests.cs`<br>`src/csharp/AnyInfer.Tests/ConfigTests.cs` | SDK.2a | Native host shorthand expands with the configured scheme and default port. |
| `ImagePart` | `implemented` | `T:AnyInfer.ImagePart` | `src/csharp/AnyInfer/MediaParts.cs` | `src/csharp/AnyInfer.Tests/RichGenerationTypesTests.cs`<br>`src/csharp/AnyInfer.Tests/RichGenerationParityTests.cs` | SDK.7a | ImagePart is represented by the native rich-generation DTO/event surface, with immutable copied data and provider-wire parity exercised by rich-generation tests. |
| `InferenceOperation` | `implemented` | `T:AnyInfer.Capabilities.InferenceOperation` | `src/csharp/AnyInfer/Capabilities/CapabilityMetadata.cs` | `src/csharp/AnyInfer.Tests/CapabilityTests.cs`<br>`src/csharp/AnyInfer.Tests/CapabilityAssemblyTests.cs` | SDK.1a | InferenceOperation maps to provenance-aware native capability metadata; catalog/probe assembly tests exercise its operation-specific fields. |
| `JsonlObserver` | `implemented` | `T:AnyInfer.Events.JsonlObserver`<br>`M:AnyInfer.Events.JsonlObserver.OnEvent` | `src/csharp/AnyInfer/Events/EventSinks.cs` | `src/csharp/AnyInfer.Tests/TelemetryTests.cs` | SDK.5a | Explicit caller-owned redacted JSONL telemetry sink. |
| `LlamaServerTokenizeEstimator` | `deferred` | — | — | `tests/test_remote_tokenizers.py` | SDK.5b | Python llama-server tokenize estimator has no native public API. |
| `LocalModelInfo` | `implemented` | `T:AnyInfer.Capabilities.LocalModelInfo` | `src/csharp/AnyInfer/Capabilities/CapabilityMetadata.cs` | `src/csharp/AnyInfer.Tests/CapabilityTests.cs`<br>`src/csharp/AnyInfer.Tests/CapabilityAssemblyTests.cs` | SDK.10a | LocalModelInfo maps to provenance-aware native capability metadata; catalog/probe assembly tests exercise its operation-specific fields. |
| `LocalRuntimeError` | `deferred` | — | — | `src/python/anyinfer/errors.py` | SDK.2b | Native SDK does not supervise a local runtime, so it has no local-runtime typed error. |
| `LoggingObserver` | `implemented` | `T:AnyInfer.Events.LoggingObserver`<br>`M:AnyInfer.Events.LoggingObserver.OnEvent` | `src/csharp/AnyInfer/Events/EventSinks.cs` | `src/csharp/AnyInfer.Tests/TelemetryTests.cs` | SDK.5a | Explicit redacted TraceSource telemetry observer. |
| `Measurement` | `deferred` | — | — | `src/python/anyinfer/benchmark.py`<br>`tests/test_benchmark.py` | SDK.11a | Versioned benchmark measurement and aggregate accounting store are unported. |
| `MeasurementIdentity` | `deferred` | — | — | `src/python/anyinfer/benchmark.py`<br>`tests/test_benchmark.py` | SDK.11a | Stable benchmark measurement identity is unported. |
| `MeasurementStore` | `deferred` | — | — | `src/python/anyinfer/benchmark.py`<br>`tests/test_benchmark.py` | SDK.11a | Opt-in persistent benchmark measurement store is unported. |
| `Mechanism` | `implemented` | `P:AnyInfer.Generation.StructuredMechanism`<br>`P:AnyInfer.GenerationRequest.SchemaMechanism` | `src/csharp/AnyInfer/Models.cs` | `src/csharp/AnyInfer.Tests/SchemaIntegrationTests.cs` | SDK.1a | Structured-output mechanism strings are carried on request and result properties, preserving grammar/json-schema/json-mode/prompt selection evidence. |
| `MechanismRung` | `implemented` | `T:AnyInfer.Schema.MechanismRung` | `src/csharp/AnyInfer/Schema/MechanismRung.cs` | `src/csharp/AnyInfer.Tests/ManifestSchemaTests.cs` | SDK.5a | Schema ladder DTO used by manifest |
| `Message` | `implemented` | `T:AnyInfer.Message` | `src/csharp/AnyInfer/Models.cs` | `src/csharp/AnyInfer.Tests/PublicModelTests.cs`<br>`src/csharp/AnyInfer.Tests/SdkMigrationTests.cs` | SDK.1a | Message snapshots its content and offers User/System/Assistant factories; the role and immutable content are preserved through the public generation path. |
| `MessagesInput` | `implemented` | `M:AnyInfer.AsyncClient.GenerateAsync`<br>`M:AnyInfer.Client.Generate` | `src/csharp/AnyInfer/AsyncClient.cs` | `src/csharp/AnyInfer.Tests/SdkMigrationTests.cs` | SDK.1a | Python prompt/one-message/message-sequence input maps to native prompt and IReadOnlyList<Message> generation overloads, which snapshot caller input before dispatch. |
| `ModelCapabilities` | `implemented` | `T:AnyInfer.Capabilities.ModelCapabilities` | `src/csharp/AnyInfer/Capabilities/ModelCapabilities.cs` | `src/csharp/AnyInfer.Tests/CapabilityTests.cs`<br>`src/csharp/AnyInfer.Tests/CapabilityAssemblyTests.cs` | SDK.4a | ModelCapabilities retains operation-aware context, schema, media, tools, and retrieval metadata with provenance-aware source values. |
| `ModelEntry` | `implemented` | `T:AnyInfer.Catalog.ModelEntry`<br>`M:AnyInfer.Catalog.ModelEntry.MatchesBestAt`<br>`M:AnyInfer.Catalog.ModelEntry.VariantsFor`<br>`M:AnyInfer.Catalog.ModelEntry.Variant`<br>`P:AnyInfer.Catalog.ModelEntry.Id`<br>`P:AnyInfer.Catalog.ModelEntry.Kind`<br>`P:AnyInfer.Catalog.ModelEntry.Family`<br>`P:AnyInfer.Catalog.ModelEntry.DisplayName`<br>`P:AnyInfer.Catalog.ModelEntry.ParameterSize`<br>`P:AnyInfer.Catalog.ModelEntry.Quantization`<br>`P:AnyInfer.Catalog.ModelEntry.ContextWindow`<br>`P:AnyInfer.Catalog.ModelEntry.License`<br>`P:AnyInfer.Catalog.ModelEntry.BestAt`<br>`P:AnyInfer.Catalog.ModelEntry.EstFileBytes`<br>`P:AnyInfer.Catalog.ModelEntry.EstRamBytes`<br>`P:AnyInfer.Catalog.ModelEntry.EstVramBytes`<br>`P:AnyInfer.Catalog.ModelEntry.LastVerified`<br>`P:AnyInfer.Catalog.ModelEntry.Source`<br>`P:AnyInfer.Catalog.ModelEntry.Variants`<br>`P:AnyInfer.Catalog.ModelEntry.Ollama`<br>`P:AnyInfer.Catalog.ModelEntry.Embedding`<br>`P:AnyInfer.Catalog.ModelEntry.Description` | `src/csharp/AnyInfer/Catalog/CatalogTypes.cs` | `src/csharp/AnyInfer.Tests/CatalogTests.cs` | SDK.4a | Native model metadata, variants, sources, pinning facts, and best-at matching. |
| `ModelKind` | `implemented` | `T:AnyInfer.Catalog.ModelKind`<br>`F:AnyInfer.Catalog.ModelKind.Generation`<br>`F:AnyInfer.Catalog.ModelKind.Embedding` | `src/csharp/AnyInfer/Catalog/CatalogTypes.cs` | `src/csharp/AnyInfer.Tests/CatalogTests.cs` | SDK.4a | Native ModelKind enum carries the same generation and embedding categories. |
| `ModelNotFoundError` | `implemented` | `T:AnyInfer.ModelNotFoundException` | `src/csharp/AnyInfer/Errors.cs` | `src/csharp/AnyInfer.Tests/PublicModelTests.cs` | SDK.2b | ModelNotFoundError maps to the native typed exception hierarchy, retaining category, retryability, nullable phase, and provider/HTTP diagnostic context. |
| `ModelVariant` | `implemented` | `T:AnyInfer.Catalog.ModelVariant`<br>`P:AnyInfer.Catalog.ModelVariant.Id`<br>`P:AnyInfer.Catalog.ModelVariant.Engine`<br>`P:AnyInfer.Catalog.ModelVariant.Kind`<br>`P:AnyInfer.Catalog.ModelVariant.Quantization`<br>`P:AnyInfer.Catalog.ModelVariant.QualityRank`<br>`P:AnyInfer.Catalog.ModelVariant.EstFileBytes`<br>`P:AnyInfer.Catalog.ModelVariant.EstRamBytes`<br>`P:AnyInfer.Catalog.ModelVariant.EstVramBytes`<br>`P:AnyInfer.Catalog.ModelVariant.MinComputeCapability`<br>`P:AnyInfer.Catalog.ModelVariant.Source`<br>`P:AnyInfer.Catalog.ModelVariant.ArtifactId`<br>`P:AnyInfer.Catalog.ModelVariant.IsPinned` | `src/csharp/AnyInfer/Catalog/CatalogTypes.cs` | `src/csharp/AnyInfer.Tests/CatalogTests.cs` | SDK.4a | Native variant metadata and pinning facts. |
| `Observer` | `implemented` | `T:AnyInfer.Events.IObserver`<br>`M:AnyInfer.Events.IObserver.OnEvent` | `src/csharp/AnyInfer/Events/IObserver.cs`<br>`src/csharp/AnyInfer/Events/EventDispatcher.cs` | `src/csharp/AnyInfer.Tests/TelemetryTests.cs` | SDK.5a | Typed opt-in in-process observer interface and dispatch. |
| `OllamaChannel` | `implemented` | `T:AnyInfer.Catalog.OllamaChannel`<br>`P:AnyInfer.Catalog.OllamaChannel.Tag`<br>`P:AnyInfer.Catalog.OllamaChannel.Digest` | `src/csharp/AnyInfer/Catalog/CatalogTypes.cs` | `src/csharp/AnyInfer.Tests/CatalogTests.cs` | SDK.4a | Native tag and digest channel metadata. |
| `Outcome` | `implemented` | `P:AnyInfer.AttemptRecord.Outcome` | `src/csharp/AnyInfer/Models.cs` | `src/csharp/AnyInfer.Tests/SdkMigrationTests.cs` | SDK.1a | Routing-attempt outcome is represented by AttemptRecord.Outcome, including failed and retried attempt trail values. |
| `ParameterDropped` | `implemented` | `T:AnyInfer.Events.ParameterDropped` | `src/csharp/AnyInfer/Core/GenerationCore.cs` | `src/csharp/AnyInfer.Tests/TelemetryTests.cs` | SDK.5c | Generation policy emits parameter-drop diagnostics. |
| `PayloadFacet` | `implemented` | `T:AnyInfer.Manifest.PayloadFacet` | `src/csharp/AnyInfer/Manifest/ManifestFacets.cs` | `src/csharp/AnyInfer.Tests/ManifestValueTests.cs` | SDK.5a | Typed manifest facet/DTO is present; ordinary request/result manifest projection bounded to implemented facets |
| `Phase` | `implemented` | `P:AnyInfer.AnyInferException.Phase` | `src/csharp/AnyInfer/Errors.cs` | `src/csharp/AnyInfer.Tests/PublicModelTests.cs` | SDK.2b | Lifecycle phase is a nullable AnyInferException.Phase property; tests cover absent phase and validate/generate phase assignment. |
| `PrewarmsCounts` | `deferred` | — | — | `tests/test_remote_tokenizers.py` | SDK.5b | Python tokenizer warm-cache protocol has no native public equivalent. |
| `Pricing` | `implemented` | `T:AnyInfer.Capabilities.Pricing` | `src/csharp/AnyInfer/Capabilities/CapabilityMetadata.cs` | `src/csharp/AnyInfer.Tests/CapabilityTests.cs`<br>`src/csharp/AnyInfer.Tests/CapabilityAssemblyTests.cs` | SDK.4a | Pricing maps to provenance-aware native capability metadata; catalog/probe assembly tests exercise its operation-specific fields. |
| `PricingTable` | `implemented` | `T:AnyInfer.Capabilities.PricingTable`<br>`M:AnyInfer.Capabilities.PricingTable.EntriesFor`<br>`M:AnyInfer.Capabilities.PricingTable.FromMapping`<br>`M:AnyInfer.Capabilities.PricingTable.LoadDefault`<br>`M:AnyInfer.Capabilities.PricingTable.Lookup`<br>`P:AnyInfer.Capabilities.PricingTable.Providers` | `src/csharp/AnyInfer/Capabilities/PricingTable.cs` | `src/csharp/AnyInfer.Tests/PricingTableTests.cs` | SDK.5b | Native provider/model pricing lookup table. |
| `ProbeOutcome` | `implemented` | `T:AnyInfer.Capabilities.ProbeOutcome`<br>`F:AnyInfer.Capabilities.ProbeOutcome.Supported`<br>`F:AnyInfer.Capabilities.ProbeOutcome.Unsupported`<br>`F:AnyInfer.Capabilities.ProbeOutcome.Inconclusive` | `src/csharp/AnyInfer/Capabilities/Probes.cs` | `src/csharp/AnyInfer.Tests/CapabilityProbeTests.cs` | SDK.4c | Native probe outcome enum carries supported, unsupported, and inconclusive states. |
| `ProbeReport` | `implemented` | `T:AnyInfer.Capabilities.ProbeReport`<br>`M:AnyInfer.Capabilities.ProbeReport.OutcomeFor`<br>`P:AnyInfer.Capabilities.ProbeReport.Target`<br>`P:AnyInfer.Capabilities.ProbeReport.Probes`<br>`P:AnyInfer.Capabilities.ProbeReport.Capabilities`<br>`P:AnyInfer.Capabilities.ProbeReport.Requests`<br>`P:AnyInfer.Capabilities.ProbeReport.Usage`<br>`P:AnyInfer.Capabilities.ProbeReport.Summary` | `src/csharp/AnyInfer/Capabilities/Probes.cs` | `src/csharp/AnyInfer.Tests/CapabilityProbeTests.cs` | SDK.4c | Native report retains ordered observations, usage, capabilities, and summary. |
| `Provenance` | `implemented` | `T:AnyInfer.Capabilities.Provenance` | `src/csharp/AnyInfer/Capabilities/Provenance.cs` | `src/csharp/AnyInfer.Tests/CapabilityTests.cs`<br>`src/csharp/AnyInfer.Tests/CapabilityAssemblyTests.cs` | SDK.4a | Provenance maps to provenance-aware native capability metadata; catalog/probe assembly tests exercise its operation-specific fields. |
| `ProviderDescriptor` | `partial` | `T:AnyInfer.Providers.ProviderDescriptor`<br>`P:AnyInfer.Providers.ProviderDescriptor.Id`<br>`P:AnyInfer.Providers.ProviderDescriptor.DisplayName`<br>`P:AnyInfer.Providers.ProviderDescriptor.Factory`<br>`P:AnyInfer.Providers.ProviderDescriptor.Aliases`<br>`P:AnyInfer.Providers.ProviderDescriptor.Setup`<br>`P:AnyInfer.Providers.ProviderDescriptor.DefaultBaseUrl`<br>`P:AnyInfer.Providers.ProviderDescriptor.RequiresBaseUrl`<br>`P:AnyInfer.Providers.ProviderDescriptor.Locality`<br>`P:AnyInfer.Providers.ProviderDescriptor.Operations`<br>`P:AnyInfer.Providers.ProviderDescriptor.ModelInventory`<br>`P:AnyInfer.Providers.ProviderDescriptor.HonorsConnectionSettings`<br>`P:AnyInfer.Providers.ProviderDescriptor.DefaultCapabilities`<br>`P:AnyInfer.Providers.ProviderDescriptor.StaticCapabilities`<br>`P:AnyInfer.Providers.ProviderDescriptor.StaticEmbeddingCapabilities`<br>`P:AnyInfer.Providers.ProviderDescriptor.StaticRerankCapabilities`<br>`P:AnyInfer.Providers.ProviderDescriptor.CacheMechanism`<br>`P:AnyInfer.Providers.ProviderDescriptor.CacheMaxMarks`<br>`P:AnyInfer.Providers.ProviderDescriptor.CacheMinTokens`<br>`P:AnyInfer.Providers.ProviderDescriptor.RateLimitHeaders` | `src/csharp/AnyInfer/Providers/ProviderDescriptor.cs` | `src/csharp/AnyInfer.Tests/ProviderSettingsTests.cs`<br>`src/csharp/AnyInfer.Tests/ProviderLifecycleTests.cs`<br>`src/csharp/AnyInfer.Tests/CompatPresetDataTests.cs` | SDK.2a | Native descriptor covers registered settings and capability metadata; Python entry-point plugins, local model acquisition, and broader setup metadata remain absent. |
| `ProviderDiagnostic` | `implemented` | `T:AnyInfer.Events.ProviderDiagnostic` | `src/csharp/AnyInfer/Core/GenerationCore.cs` | `src/csharp/AnyInfer.Tests/TelemetryTests.cs` | SDK.5a | Generation core emits provider diagnostic telemetry. |
| `ProviderError` | `implemented` | `T:AnyInfer.ProviderException` | `src/csharp/AnyInfer/Errors.cs` | `src/csharp/AnyInfer.Tests/PublicModelTests.cs` | SDK.2b | ProviderError maps to the native typed exception hierarchy, retaining category, retryability, nullable phase, and provider/HTTP diagnostic context. |
| `ProviderRegistry` | `partial` | `T:AnyInfer.Providers.ProviderRegistry`<br>`M:AnyInfer.Providers.ProviderRegistry.CreateDefault`<br>`M:AnyInfer.Providers.ProviderRegistry.Register`<br>`M:AnyInfer.Providers.ProviderRegistry.Get`<br>`M:AnyInfer.Providers.ProviderRegistry.Has`<br>`M:AnyInfer.Providers.ProviderRegistry.ResolveId`<br>`M:AnyInfer.Providers.ProviderRegistry.NormalizeProviderId`<br>`P:AnyInfer.Providers.ProviderRegistry.Descriptors` | `src/csharp/AnyInfer/Providers/ProviderRegistry.cs` | `src/csharp/AnyInfer.Tests/ProviderSettingsTests.cs`<br>`src/csharp/AnyInfer.Tests/ProviderLifecycleTests.cs`<br>`src/csharp/AnyInfer.Tests/ConfigTests.cs` | SDK.2a | Collision-safe aliases and default descriptors are native; Python entry-point discovery and issue reporting remain absent. |
| `ProviderSettings` | `implemented` | `T:AnyInfer.ProviderSettings` | `src/csharp/AnyInfer/ProviderSettings.cs` | `src/csharp/AnyInfer.Tests/ProviderSettingsTests.cs` | SDK.1a | ProviderSettings builds the immutable provider endpoint, credential reference, headers, transport, proxy, TLS, and rate-limit setup. |
| `ProviderSetupSpec` | `partial` | `T:AnyInfer.Providers.ProviderSetupSpec`<br>`M:AnyInfer.Providers.ProviderSetupSpec.UnsatisfiedGroups`<br>`M:AnyInfer.Providers.ProviderSetupSpec.LabelFor`<br>`P:AnyInfer.Providers.ProviderSetupSpec.Fields`<br>`P:AnyInfer.Providers.ProviderSetupSpec.ModelSelection`<br>`P:AnyInfer.Providers.ProviderSetupSpec.HostShorthand`<br>`P:AnyInfer.Providers.ProviderSetupSpec.AnyOf`<br>`P:AnyInfer.Providers.ProviderSetupSpec.RequirementNote`<br>`P:AnyInfer.Providers.ProviderSetupSpec.EssentialFields`<br>`P:AnyInfer.Providers.ProviderSetupSpec.AdvancedFields` | `src/csharp/AnyInfer/Providers/ProviderSetupSpec.cs` | `src/csharp/AnyInfer.Tests/ProviderSetupTests.cs`<br>`src/csharp/AnyInfer.Tests/CompatPresetDataTests.cs` | SDK.2a | Native declarative setup metadata exists, but provider/plugin/auth/model/local-connection coverage is narrower. |
| `ProviderUnavailableError` | `implemented` | `T:AnyInfer.ProviderUnavailableException` | `src/csharp/AnyInfer/Errors.cs` | `src/csharp/AnyInfer.Tests/PublicModelTests.cs` | SDK.2b | ProviderUnavailableError maps to the native typed exception hierarchy, retaining category, retryability, nullable phase, and provider/HTTP diagnostic context. |
| `PullReport` | `deferred` | — | — | `src/python/anyinfer/local/services.py`<br>`tests/test_service_models.py` | SDK.10 | Native local model pull lifecycle, transfer report and supervision are unported. |
| `PullRequest` | `deferred` | — | — | `src/python/anyinfer/local/services.py`<br>`tests/test_service_models.py` | SDK.10 | Native local model pull request and loopback service control are unported. |
| `RankedItem` | `implemented` | `T:AnyInfer.RankedItem` | `src/csharp/AnyInfer/RankedItem.cs` | `src/csharp/AnyInfer.Tests/RetrievalDomainTests.cs`<br>`src/csharp/AnyInfer.Tests/RetrievalRoutingBatchTests.cs` | SDK.6a | RankedItem is the native retrieval value/policy surface; its request ordering, copied inputs, provider result identity, and batch-routing behavior are exercised by retrieval tests. |
| `RateLimitError` | `implemented` | `T:AnyInfer.RateLimitException` | `src/csharp/AnyInfer/Errors.cs` | `src/csharp/AnyInfer.Tests/PublicModelTests.cs` | SDK.2b | RateLimitError maps to the native typed exception hierarchy, retaining category, retryability, nullable phase, and provider/HTTP diagnostic context. |
| `RateLimitHeaders` | `implemented` | `T:AnyInfer.Capabilities.RateLimitHeaders` | `src/csharp/AnyInfer/Capabilities/CapabilityMetadata.cs` | `src/csharp/AnyInfer.Tests/CapabilityTests.cs`<br>`src/csharp/AnyInfer.Tests/CapabilityAssemblyTests.cs` | SDK.4a | RateLimitHeaders maps to provenance-aware native capability metadata; catalog/probe assembly tests exercise its operation-specific fields. |
| `RateLimitObserved` | `implemented` | `T:AnyInfer.Events.RateLimitObserved` | `src/csharp/AnyInfer/Routing/RateLimiter.cs` | `src/csharp/AnyInfer.Tests/RateLimiterTests.cs` | SDK.5c | Rate limiter records provider-reported limit state. |
| `RateLimitWaited` | `implemented` | `T:AnyInfer.Events.RateLimitWaited` | `src/csharp/AnyInfer/Routing/RateLimiter.cs` | `src/csharp/AnyInfer.Tests/RateLimiterTests.cs` | SDK.5c | Rate limiter emits client-side pacing waits. |
| `RateLimits` | `implemented` | `T:AnyInfer.RateLimits` | `src/csharp/AnyInfer/RateLimits.cs` | `src/csharp/AnyInfer.Tests/RateLimiterTests.cs` | SDK.4a | RateLimits controls maximum concurrency, request pacing, token rate, and response-header participation for native routing. |
| `ReasoningDelta` | `implemented` | `T:AnyInfer.ReasoningDelta` | `src/csharp/AnyInfer/GenerationEvent.cs` | `src/csharp/AnyInfer.Tests/RichGenerationTypesTests.cs`<br>`src/csharp/AnyInfer.Tests/RichGenerationParityTests.cs` | SDK.7a | ReasoningDelta is represented by the native rich-generation DTO/event surface, with immutable copied data and provider-wire parity exercised by rich-generation tests. |
| `ReasoningEffort` | `implemented` | `P:AnyInfer.GenerationRequest.Reasoning` | `src/csharp/AnyInfer/Models.cs` | `src/csharp/AnyInfer.Tests/RawToolGenerationTests.cs` | SDK.1a | The normalized reasoning effort is carried as GenerationRequest.Reasoning; native descriptors translate the string per provider. |
| `RedactionRegistry` | `implemented` | `T:AnyInfer.RedactionRegistry`<br>`M:AnyInfer.RedactionRegistry.Register`<br>`M:AnyInfer.RedactionRegistry.Redact`<br>`M:AnyInfer.RedactionRegistry.Clear` | `src/csharp/AnyInfer/Redaction.cs` | `src/csharp/AnyInfer.Tests/CredentialsTests.cs` | SDK.2b | Native redaction registry |
| `ReductionRecord` | `partial` | `T:AnyInfer.Manifest.ReductionRecord` | `src/csharp/AnyInfer/Manifest/ManifestFacets.cs` | `src/csharp/AnyInfer.Tests/ManifestValueTests.cs` | SDK.9 | DTO exists, but native context reduction producer is absent |
| `Repair` | `implemented` | `T:AnyInfer.Repair` | `src/csharp/AnyInfer/Models.cs` | `src/csharp/AnyInfer.Tests/PublicModelTests.cs`<br>`src/csharp/AnyInfer.Tests/SdkMigrationTests.cs` | SDK.1a | Repair carries the bounded maximum repair-attempt count used by schema retry execution. |
| `RepairAttempted` | `implemented` | `T:AnyInfer.Events.RepairAttempted` | `src/csharp/AnyInfer/Core/GenerationCore.cs` | `src/csharp/AnyInfer.Tests/EventLifecycleTests.cs` | SDK.5a | Generation repair path emits typed repair attempts. |
| `RepairRecord` | `implemented` | `T:AnyInfer.Manifest.RepairRecord` | `src/csharp/AnyInfer/Manifest/ManifestFacets.cs` | `src/csharp/AnyInfer.Tests/ManifestValueTests.cs` | SDK.5a | Typed manifest facet/DTO is present; ordinary request/result manifest projection bounded to implemented facets |
| `RequestCompleted` | `implemented` | `T:AnyInfer.Events.RequestCompleted` | `src/csharp/AnyInfer/AsyncClient.cs`<br>`src/csharp/AnyInfer/Internal/RequestTelemetry.cs` | `src/csharp/AnyInfer.Tests/EventLifecycleTests.cs` | SDK.5c | Client terminal path emits completed-request usage and timing facts. |
| `RequestEstimate` | `implemented` | `T:AnyInfer.Capabilities.RequestEstimate`<br>`P:AnyInfer.Capabilities.RequestEstimate.Messages`<br>`P:AnyInfer.Capabilities.RequestEstimate.Tools`<br>`P:AnyInfer.Capabilities.RequestEstimate.Schema`<br>`P:AnyInfer.Capabilities.RequestEstimate.Envelope`<br>`P:AnyInfer.Capabilities.RequestEstimate.UnpricedParts`<br>`P:AnyInfer.Capabilities.RequestEstimate.Tokens`<br>`P:AnyInfer.Capabilities.RequestEstimate.Floor` | `src/csharp/AnyInfer/Capabilities/TokenEstimation.cs` | `src/csharp/AnyInfer.Tests/PricingAndBudgetTests.cs` | SDK.5b | Native request token components and envelope/floor accounting. |
| `RequestFacet` | `implemented` | `T:AnyInfer.Manifest.RequestFacet` | `src/csharp/AnyInfer/Manifest/ManifestFacets.cs` | `src/csharp/AnyInfer.Tests/ManifestValueTests.cs` | SDK.5a | Typed manifest facet/DTO is present; ordinary request/result manifest projection bounded to implemented facets |
| `RequestFailed` | `implemented` | `T:AnyInfer.Events.RequestFailed` | `src/csharp/AnyInfer/Internal/RequestTelemetry.cs`<br>`src/csharp/AnyInfer/Core/RetrievalCore.cs` | `src/csharp/AnyInfer.Tests/EventLifecycleTests.cs` | SDK.5a | Terminal request failures are emitted for generation and retrieval paths. |
| `RequestStarted` | `implemented` | `T:AnyInfer.Events.RequestStarted` | `src/csharp/AnyInfer/AsyncClient.cs`<br>`src/csharp/AnyInfer/Internal/RequestTelemetry.cs` | `src/csharp/AnyInfer.Tests/EventLifecycleTests.cs` | SDK.5a | Client request entry emits typed request-start facts. |
| `RerankCapabilities` | `implemented` | `T:AnyInfer.Capabilities.RerankCapabilities` | `src/csharp/AnyInfer/Capabilities/CapabilityMetadata.cs` | `src/csharp/AnyInfer.Tests/CapabilityTests.cs`<br>`src/csharp/AnyInfer.Tests/CapabilityAssemblyTests.cs` | SDK.4a | RerankCapabilities maps to provenance-aware native capability metadata; catalog/probe assembly tests exercise its operation-specific fields. |
| `RerankDocument` | `implemented` | `T:AnyInfer.RerankDocument` | `src/csharp/AnyInfer/RerankDocument.cs` | `src/csharp/AnyInfer.Tests/RetrievalDomainTests.cs`<br>`src/csharp/AnyInfer.Tests/RetrievalRoutingBatchTests.cs` | SDK.6a | RerankDocument is the native retrieval value/policy surface; its request ordering, copied inputs, provider result identity, and batch-routing behavior are exercised by retrieval tests. |
| `RerankRequest` | `implemented` | `T:AnyInfer.RerankRequest` | `src/csharp/AnyInfer/RerankRequest.cs` | `src/csharp/AnyInfer.Tests/RetrievalDomainTests.cs`<br>`src/csharp/AnyInfer.Tests/RetrievalRoutingBatchTests.cs` | SDK.6a | RerankRequest is the native retrieval value/policy surface; its request ordering, copied inputs, provider result identity, and batch-routing behavior are exercised by retrieval tests. |
| `RerankResult` | `implemented` | `T:AnyInfer.RerankResult` | `src/csharp/AnyInfer/RerankResult.cs` | `src/csharp/AnyInfer.Tests/RetrievalDomainTests.cs`<br>`src/csharp/AnyInfer.Tests/RetrievalRoutingBatchTests.cs` | SDK.6a | RerankResult is the native retrieval value/policy surface; its request ordering, copied inputs, provider result identity, and batch-routing behavior are exercised by retrieval tests. |
| `ResolvedTarget` | `implemented` | `T:AnyInfer.ResolvedTarget` | `src/csharp/AnyInfer/Models.cs` | `src/csharp/AnyInfer.Tests/PublicModelTests.cs`<br>`src/csharp/AnyInfer.Tests/SdkMigrationTests.cs` | SDK.1a | ResolvedTarget separates provider, model, and optional alias and renders provider:model without losing a model revision colon. |
| `ResolverChain` | `partial` | `T:AnyInfer.Credentials.ResolverChain`<br>`M:AnyInfer.Credentials.ResolverChain.Add`<br>`M:AnyInfer.Credentials.ResolverChain.CreateDefault`<br>`M:AnyInfer.Credentials.ResolverChain.Handles`<br>`M:AnyInfer.Credentials.ResolverChain.ResolveAsync` | `src/csharp/AnyInfer/Credentials/ResolverChain.cs` | `src/csharp/AnyInfer.Tests/CredentialsTests.cs` | SDK.2b | Native literal, environment, and keyring chain resolves lazily with redaction; Python plugin discovery and issues coverage remain absent. |
| `Retry` | `implemented` | `T:AnyInfer.Retry` | `src/csharp/AnyInfer/Models.cs` | `src/csharp/AnyInfer.Tests/RoutingTests.cs` | SDK.1–3 | Native retry policy DTO |
| `RetryScheduled` | `implemented` | `T:AnyInfer.Events.RetryScheduled` | `src/csharp/AnyInfer/Core/GenerationCore.cs`<br>`src/csharp/AnyInfer/Core/RetrievalCore.cs` | `src/csharp/AnyInfer.Tests/EventLifecycleTests.cs` | SDK.5a | Generation and retrieval retries emit scheduled-retry facts. |
| `Role` | `implemented` | `P:AnyInfer.Message.Role` | `src/csharp/AnyInfer/Models.cs` | `src/csharp/AnyInfer.Tests/SdkMigrationTests.cs` | SDK.1a | The Python role literal is a native Message.Role string; Message.System, User, Assistant, and tool-role construction preserve the normalized message role. |
| `Route` | `implemented` | `T:AnyInfer.Route` | `src/csharp/AnyInfer/Models.cs` | `src/csharp/AnyInfer.Tests/RoutingTests.cs` | SDK.1–3 | Native route policy DTO |
| `RouteFacet` | `implemented` | `T:AnyInfer.Manifest.RouteFacet` | `src/csharp/AnyInfer/Manifest/ManifestFacets.cs` | `src/csharp/AnyInfer.Tests/ManifestValueTests.cs` | SDK.5a | Typed manifest facet/DTO is present; ordinary request/result manifest projection bounded to implemented facets |
| `RouteStep` | `implemented` | `T:AnyInfer.Manifest.RouteStep` | `src/csharp/AnyInfer/Manifest/ManifestFacets.cs` | `src/csharp/AnyInfer.Tests/ManifestValueTests.cs` | SDK.5a | Typed manifest facet/DTO is present; ordinary request/result manifest projection bounded to implemented facets |
| `RunManifest` | `implemented` | `T:AnyInfer.Manifest.RunManifest` | `src/csharp/AnyInfer/Manifest/RunManifest.cs` | `src/csharp/AnyInfer.Tests/ManifestValueTests.cs` | SDK.5a | Typed manifest facet/DTO is present; ordinary request/result manifest projection bounded to implemented facets |
| `Sampling` | `implemented` | `T:AnyInfer.Sampling` | `src/csharp/AnyInfer/Models.cs` | `src/csharp/AnyInfer.Tests/PublicModelTests.cs`<br>`src/csharp/AnyInfer.Tests/SdkMigrationTests.cs` | SDK.1a | Sampling preserves seed, temperature/top-p/top-k, stop values, output limit and penalties without construction-time coercion. |
| `SchemaFacet` | `implemented` | `T:AnyInfer.Manifest.SchemaFacet` | `src/csharp/AnyInfer/Manifest/ManifestFacets.cs` | `src/csharp/AnyInfer.Tests/ManifestValueTests.cs` | SDK.5a | Typed manifest facet/DTO is present; ordinary request/result manifest projection bounded to implemented facets |
| `SchemaSpec` | `different` | `T:AnyInfer.SchemaSpec` | `src/csharp/AnyInfer/SchemaSpec.cs` | `src/csharp/AnyInfer.Tests/ModernSchemaTests.cs` | SDK.1a | C# accepts modern Draft 6/7/2019-09/2020-12 JSON Schema with opt-in external references and decimal/regex limits; this is an intentional semantic difference from the Python schema surface. |
| `SchemaViolationError` | `implemented` | `T:AnyInfer.SchemaViolationException` | `src/csharp/AnyInfer/Errors.cs` | `src/csharp/AnyInfer.Tests/PublicModelTests.cs` | SDK.2b | SchemaViolationError maps to the native typed exception hierarchy, retaining category, retryability, nullable phase, and provider/HTTP diagnostic context. |
| `ServerLifecycle` | `partial` | `T:AnyInfer.Events.ServerLifecycle` | `src/csharp/AnyInfer/Events/TelemetryEvent.cs` | `src/csharp/AnyInfer.Tests/TelemetryTests.cs` | SDK.10 | Telemetry DTO exists, but native supervised local-server lifecycle is unported. |
| `ServerToolDelta` | `implemented` | `T:AnyInfer.ServerToolDelta` | `src/csharp/AnyInfer/GenerationEvent.cs` | `src/csharp/AnyInfer.Tests/RichGenerationTypesTests.cs`<br>`src/csharp/AnyInfer.Tests/RichGenerationParityTests.cs` | SDK.7a | ServerToolDelta is represented by the native rich-generation DTO/event surface, with immutable copied data and provider-wire parity exercised by rich-generation tests. |
| `ServerToolKind` | `implemented` | `P:AnyInfer.ServerToolSpec.Kind` | `src/csharp/AnyInfer/RichGeneration.cs` | `src/csharp/AnyInfer.Tests/RichGenerationTypesTests.cs` | SDK.7a | ServerToolSpec validates and exposes only web_search or code_execution through its Kind property, without a separate enum. |
| `ServerToolSource` | `implemented` | `T:AnyInfer.ServerToolSource` | `src/csharp/AnyInfer/RichGeneration.cs` | `src/csharp/AnyInfer.Tests/RichGenerationTypesTests.cs`<br>`src/csharp/AnyInfer.Tests/RichGenerationParityTests.cs` | SDK.7a | ServerToolSource is represented by the native rich-generation DTO/event surface, with immutable copied data and provider-wire parity exercised by rich-generation tests. |
| `ServerToolSpec` | `implemented` | `T:AnyInfer.ServerToolSpec` | `src/csharp/AnyInfer/RichGeneration.cs` | `src/csharp/AnyInfer.Tests/RichGenerationTypesTests.cs`<br>`src/csharp/AnyInfer.Tests/RichGenerationParityTests.cs` | SDK.7a | ServerToolSpec is represented by the native rich-generation DTO/event surface, with immutable copied data and provider-wire parity exercised by rich-generation tests. |
| `ServerToolUse` | `implemented` | `T:AnyInfer.ServerToolUse` | `src/csharp/AnyInfer/RichGeneration.cs` | `src/csharp/AnyInfer.Tests/RichGenerationTypesTests.cs`<br>`src/csharp/AnyInfer.Tests/RichGenerationParityTests.cs` | SDK.7a | ServerToolUse is represented by the native rich-generation DTO/event surface, with immutable copied data and provider-wire parity exercised by rich-generation tests. |
| `Session` | `deferred` | — | — | `src/python/anyinfer/session.py` | SDK.11a | Native SDK has no multi-turn Session state, resume policy, or transcript lifecycle. |
| `SessionReuse` | `deferred` | — | — | `src/python/anyinfer/session.py` | SDK.11a | Native SDK has no fresh/resumed/unsupported session reuse outcome because Session is absent. |
| `SetupField` | `implemented` | `T:AnyInfer.Providers.SetupField`<br>`P:AnyInfer.Providers.SetupField.Key`<br>`P:AnyInfer.Providers.SetupField.Label`<br>`P:AnyInfer.Providers.SetupField.Kind`<br>`P:AnyInfer.Providers.SetupField.Required`<br>`P:AnyInfer.Providers.SetupField.HelpText`<br>`P:AnyInfer.Providers.SetupField.Placeholder`<br>`P:AnyInfer.Providers.SetupField.EnvVar`<br>`P:AnyInfer.Providers.SetupField.Advanced`<br>`P:AnyInfer.Providers.SetupField.DefaultValue`<br>`P:AnyInfer.Providers.SetupField.Choices` | `src/csharp/AnyInfer/Providers/ProviderSetupSpec.cs` | `src/csharp/AnyInfer.Tests/ProviderSetupTests.cs` | SDK.2a | Native setup-field metadata retains labels, validation hints, defaults, and choices. |
| `Sourced` | `implemented` | ``T:AnyInfer.Capabilities.Sourced`1`` | `src/csharp/AnyInfer/Capabilities/Provenance.cs` | `src/csharp/AnyInfer.Tests/CapabilityTests.cs`<br>`src/csharp/AnyInfer.Tests/CapabilityAssemblyTests.cs` | SDK.4a | Sourced maps to provenance-aware native capability metadata; catalog/probe assembly tests exercise its operation-specific fields. |
| `SourcedFact` | `implemented` | `T:AnyInfer.Manifest.SourcedFact` | `src/csharp/AnyInfer/Manifest/ManifestFacets.cs` | `src/csharp/AnyInfer.Tests/ManifestValueTests.cs` | SDK.5a | Typed manifest facet/DTO is present; ordinary request/result manifest projection bounded to implemented facets |
| `SpendLedger` | `implemented` | `T:AnyInfer.Capabilities.SpendLedger`<br>`M:AnyInfer.Capabilities.SpendLedger.ByLabel`<br>`M:AnyInfer.Capabilities.SpendLedger.ByTarget`<br>`M:AnyInfer.Capabilities.SpendLedger.OnEvent`<br>`M:AnyInfer.Capabilities.SpendLedger.Record`<br>`M:AnyInfer.Capabilities.SpendLedger.Release`<br>`M:AnyInfer.Capabilities.SpendLedger.Reserve`<br>`M:AnyInfer.Capabilities.SpendLedger.Reserved`<br>`M:AnyInfer.Capabilities.SpendLedger.Reset`<br>`M:AnyInfer.Capabilities.SpendLedger.Totals`<br>`M:AnyInfer.AsyncClient.Spend` | `src/csharp/AnyInfer/Capabilities/SpendLedger.cs`<br>`src/csharp/AnyInfer/AsyncClient.cs` | `src/csharp/AnyInfer.Tests/SpendLedgerTests.cs`<br>`src/csharp/AnyInfer.Tests/AccountingLifecycleTests.cs` | SDK.5b | Native reserve/release/record/event accounting and grouped totals are exposed through AsyncClient.Spend. |
| `SpendLimitError` | `implemented` | `T:AnyInfer.SpendLimitException` | `src/csharp/AnyInfer/SpendLimitException.cs` | `src/csharp/AnyInfer.Tests/PublicModelTests.cs` | SDK.2b | SpendLimitError maps to the native typed exception hierarchy, retaining category, retryability, nullable phase, and provider/HTTP diagnostic context. |
| `SpendPolicy` | `implemented` | `T:AnyInfer.SpendPolicy` | `src/csharp/AnyInfer/SpendPolicy.cs` | `src/csharp/AnyInfer.Tests/AccountingValueTests.cs`<br>`src/csharp/AnyInfer.Tests/PolicyContextTests.cs`<br>`src/csharp/AnyInfer.Tests/PolicyAdmissionHttpTests.cs` | SDK.5b | SpendPolicy carries per-request and aggregate monetary ceilings into configured policy admission before the outbound HTTP attempt. |
| `SpendStore` | `implemented` | `T:AnyInfer.Capabilities.SpendStore`<br>`F:AnyInfer.Capabilities.SpendStore.FormatVersion`<br>`M:AnyInfer.Capabilities.SpendStore.Load`<br>`M:AnyInfer.Capabilities.SpendStore.Accumulate`<br>`P:AnyInfer.Capabilities.SpendStore.Path` | `src/csharp/AnyInfer/Capabilities/SpendStore.cs` | `src/csharp/AnyInfer.Tests/SpendStoreTests.cs` | SDK.5b | Native persistent spend-store load and accumulation. |
| `SpendTotals` | `implemented` | `T:AnyInfer.Capabilities.SpendTotals`<br>`M:AnyInfer.Capabilities.SpendTotals.FromDictionary`<br>`M:AnyInfer.Capabilities.SpendTotals.Plus`<br>`M:AnyInfer.Capabilities.SpendTotals.ToDictionary`<br>`P:AnyInfer.Capabilities.SpendTotals.Requests`<br>`P:AnyInfer.Capabilities.SpendTotals.InputTokens`<br>`P:AnyInfer.Capabilities.SpendTotals.OutputTokens`<br>`P:AnyInfer.Capabilities.SpendTotals.CacheReadTokens`<br>`P:AnyInfer.Capabilities.SpendTotals.Cost`<br>`P:AnyInfer.Capabilities.SpendTotals.Currency`<br>`P:AnyInfer.Capabilities.SpendTotals.UnknownRequests`<br>`P:AnyInfer.Capabilities.SpendTotals.Complete` | `src/csharp/AnyInfer/Capabilities/SpendTotals.cs` | `src/csharp/AnyInfer.Tests/AccountingValueTests.cs`<br>`src/csharp/AnyInfer.Tests/SpendLedgerTests.cs` | SDK.5b | Native spend totals support values and dictionary conversion. |
| `StreamEnded` | `implemented` | `T:AnyInfer.StreamEnded` | `src/csharp/AnyInfer/GenerationEvent.cs` | `src/csharp/AnyInfer.Tests/SdkMigrationTests.cs` | SDK.1a | StreamEnded is emitted by the native typed stream and is exercised while reconstructing a terminal generation from actual stream events. |
| `StreamEvent` | `implemented` | `T:AnyInfer.StreamEvent` | `src/csharp/AnyInfer/GenerationEvent.cs` | `src/csharp/AnyInfer.Tests/SdkMigrationTests.cs` | SDK.1a | StreamEvent is emitted by the native typed stream and is exercised while reconstructing a terminal generation from actual stream events. |
| `StreamProtocolError` | `implemented` | `T:AnyInfer.StreamProtocolException` | `src/csharp/AnyInfer/Errors.cs` | `src/csharp/AnyInfer.Tests/PublicModelTests.cs` | SDK.2b | StreamProtocolError maps to the native typed exception hierarchy, retaining category, retryability, nullable phase, and provider/HTTP diagnostic context. |
| `SupportsJSONSchema` | `implemented` | `T:AnyInfer.SchemaSpec`<br>`M:AnyInfer.SchemaSpec.Coerce` | `src/csharp/AnyInfer/SchemaSpec.cs` | `src/csharp/AnyInfer.Tests/ModernSchemaTests.cs` | SDK.1a | C# replaces Python duck-typed model_json_schema() with explicit JsonValue/JsonElement SchemaSpec coercion, preserving supplied JSON Schema admission. |
| `SyncStream` | `partial` | `T:AnyInfer.SyncStream` | `src/csharp/AnyInfer/SyncStream.cs` | `src/csharp/AnyInfer.Tests/SdkMigrationTests.cs`<br>`src/csharp/AnyInfer.Tests/SyncClientTests.cs` | SDK.1a | Single-consumer synchronous generation events over AsyncStream, terminal Result, collection, cancellation/disposal and optional manifest capture are native. Terminal Generation still lacks Python cache_mechanism, arena and context_reduction fields. Retrieval APIs are buffered and do not return this stream. |
| `Target` | `implemented` | `M:AnyInfer.AsyncClient.GenerateAsync`<br>`M:AnyInfer.Client.Generate` | `src/csharp/AnyInfer/AsyncClient.cs` | `src/csharp/AnyInfer.Tests/SdkMigrationTests.cs` | SDK.1a | Python Target is the provider:model or alias string accepted by generation overloads; native calls retain the same target grammar without a wrapper type. |
| `TargetAwareTokenEstimator` | `deferred` | — | — | `tests/test_tokenizers.py` | SDK.5b | Python provider/model token-estimator dispatch protocol has no native public API. |
| `TargetComparison` | `deferred` | — | — | `src/python/anyinfer/evaluate/compare.py`<br>`tests/test_compare.py` | SDK.11a | Cross-target generation comparison and persisted evaluation are unported. |
| `TargetResolved` | `implemented` | `T:AnyInfer.Events.TargetResolved` | `src/csharp/AnyInfer/Core/GenerationCore.cs`<br>`src/csharp/AnyInfer/Core/RetrievalCore.cs` | `src/csharp/AnyInfer.Tests/EventLifecycleTests.cs` | SDK.5a | Generation and retrieval target resolution emits typed facts. |
| `TelemetryEvent` | `implemented` | `T:AnyInfer.Events.TelemetryEvent`<br>`M:AnyInfer.Events.TelemetryEvent.ToDictionary` | `src/csharp/AnyInfer/Events/TelemetryEvent.cs`<br>`src/csharp/AnyInfer/Events/TelemetrySerialization.cs` | `src/csharp/AnyInfer.Tests/TelemetryTests.cs` | SDK.5a | Payload-private typed telemetry base and redacted serialization. |
| `Text` | `implemented` | `T:AnyInfer.Text` | `src/csharp/AnyInfer/Models.cs` | `src/csharp/AnyInfer.Tests/PublicModelTests.cs`<br>`src/csharp/AnyInfer.Tests/SdkMigrationTests.cs` | SDK.1a | Text is the immutable textual content part and rejects a null value. |
| `TextDelta` | `implemented` | `T:AnyInfer.TextDelta` | `src/csharp/AnyInfer/GenerationEvent.cs` | `src/csharp/AnyInfer.Tests/SdkMigrationTests.cs` | SDK.1a | TextDelta is emitted by the native typed stream and is exercised while reconstructing a terminal generation from actual stream events. |
| `TiktokenEstimator` | `deferred` | — | — | `tests/test_tokenizers.py` | SDK.5b | Python optional tiktoken backend is absent; native only supplies the heuristic estimator. |
| `Timing` | `implemented` | `T:AnyInfer.Timing` | `src/csharp/AnyInfer/Models.cs` | `src/csharp/AnyInfer.Tests/PublicModelTests.cs`<br>`src/csharp/AnyInfer.Tests/SdkMigrationTests.cs` | SDK.1a | Timing snapshots named nonnegative phases plus started, first-token, total, and output-rate measurements. |
| `TimingFacet` | `implemented` | `T:AnyInfer.Manifest.TimingFacet` | `src/csharp/AnyInfer/Manifest/ManifestFacets.cs` | `src/csharp/AnyInfer.Tests/ManifestValueTests.cs` | SDK.5a | Typed manifest facet/DTO is present; ordinary request/result manifest projection bounded to implemented facets |
| `TimingMark` | `implemented` | `T:AnyInfer.TimingMark` | `src/csharp/AnyInfer/GenerationEvent.cs` | `src/csharp/AnyInfer.Tests/SdkMigrationTests.cs` | SDK.1a | TimingMark is emitted by the native typed stream and is exercised while reconstructing a terminal generation from actual stream events. |
| `TimingMarkName` | `implemented` | `P:AnyInfer.TimingMark.Name` | `src/csharp/AnyInfer/GenerationEvent.cs` | `src/csharp/AnyInfer.Tests/SdkMigrationTests.cs` | SDK.1a | Named attempt_start and first_token stream marks are retained as TimingMark.Name string values and verified on fallback/repair streams. |
| `TokenCalibration` | `implemented` | `T:AnyInfer.Capabilities.TokenCalibration` | `src/csharp/AnyInfer/Capabilities/CapabilityMetadata.cs` | `src/csharp/AnyInfer.Tests/CapabilityTests.cs`<br>`src/csharp/AnyInfer.Tests/CapabilityAssemblyTests.cs` | SDK.4a | TokenCalibration maps to provenance-aware native capability metadata; catalog/probe assembly tests exercise its operation-specific fields. |
| `TokenEstimate` | `implemented` | `T:AnyInfer.Capabilities.TokenEstimate`<br>`M:AnyInfer.Capabilities.TokenEstimate.Add`<br>`P:AnyInfer.Capabilities.TokenEstimate.Tokens`<br>`P:AnyInfer.Capabilities.TokenEstimate.Floor` | `src/csharp/AnyInfer/Capabilities/TokenEstimate.cs` | `src/csharp/AnyInfer.Tests/CapabilityTests.cs`<br>`src/csharp/AnyInfer.Tests/PricingAndBudgetTests.cs` | SDK.5b | Native token/floor value with addition. |
| `TokenEstimator` | `implemented` | `T:AnyInfer.Capabilities.ITokenEstimator`<br>`M:AnyInfer.Capabilities.ITokenEstimator.Estimate` | `src/csharp/AnyInfer/Capabilities/ITokenEstimator.cs` | `src/csharp/AnyInfer.Tests/CapabilityTests.cs` | SDK.5b | Native interface is the C# equivalent of the Python token-estimator protocol. |
| `TokenLogprob` | `implemented` | `T:AnyInfer.TokenLogprob` | `src/csharp/AnyInfer/RichGeneration.cs` | `src/csharp/AnyInfer.Tests/RichGenerationTypesTests.cs`<br>`src/csharp/AnyInfer.Tests/RichGenerationParityTests.cs` | SDK.7a | TokenLogprob is represented by the native rich-generation DTO/event surface, with immutable copied data and provider-wire parity exercised by rich-generation tests. |
| `TokenizerKind` | `implemented` | `T:AnyInfer.Capabilities.TokenizerKind` | `src/csharp/AnyInfer/Capabilities/CapabilityMetadata.cs` | `src/csharp/AnyInfer.Tests/CapabilityTests.cs`<br>`src/csharp/AnyInfer.Tests/CapabilityAssemblyTests.cs` | SDK.4a | TokenizerKind maps to provenance-aware native capability metadata; catalog/probe assembly tests exercise its operation-specific fields. |
| `Tool` | `implemented` | `T:AnyInfer.Tool` | `src/csharp/AnyInfer/Tool.cs` | `src/csharp/AnyInfer.Tests/RichGenerationTypesTests.cs`<br>`src/csharp/AnyInfer.Tests/RichGenerationParityTests.cs` | SDK.7a | Tool is represented by the native rich-generation DTO/event surface, with immutable copied data and provider-wire parity exercised by rich-generation tests. |
| `ToolCall` | `implemented` | `T:AnyInfer.ToolCall` | `src/csharp/AnyInfer/Models.cs` | `src/csharp/AnyInfer.Tests/RichGenerationTypesTests.cs`<br>`src/csharp/AnyInfer.Tests/RichGenerationParityTests.cs` | SDK.7a | ToolCall is represented by the native rich-generation DTO/event surface, with immutable copied data and provider-wire parity exercised by rich-generation tests. |
| `ToolCallDelta` | `implemented` | `T:AnyInfer.ToolCallDelta` | `src/csharp/AnyInfer/GenerationEvent.cs` | `src/csharp/AnyInfer.Tests/RichGenerationTypesTests.cs`<br>`src/csharp/AnyInfer.Tests/RichGenerationParityTests.cs` | SDK.7a | ToolCallDelta is represented by the native rich-generation DTO/event surface, with immutable copied data and provider-wire parity exercised by rich-generation tests. |
| `ToolChoice` | `implemented` | `P:AnyInfer.GenerationRequest.ToolChoice` | `src/csharp/AnyInfer/Models.cs` | `src/csharp/AnyInfer.Tests/RawToolGenerationTests.cs` | SDK.7a | The string choice auto/none/required or a named tool is retained by GenerationRequest.ToolChoice and forwarded through the raw-tool generation path. |
| `ToolLoopError` | `implemented` | `T:AnyInfer.ToolLoopException` | `src/csharp/AnyInfer/Errors.cs` | `src/csharp/AnyInfer.Tests/ToolLoopTests.cs`<br>`src/csharp/AnyInfer.Tests/ToolBindingControlsTests.cs` | SDK.2b | ToolLoopError maps to the native typed exception hierarchy, retaining category, retryability, nullable phase, and provider/HTTP diagnostic context. |
| `ToolResult` | `implemented` | `T:AnyInfer.ToolResult` | `src/csharp/AnyInfer/Models.cs` | `src/csharp/AnyInfer.Tests/RichGenerationTypesTests.cs`<br>`src/csharp/AnyInfer.Tests/RichGenerationParityTests.cs` | SDK.7a | ToolResult is represented by the native rich-generation DTO/event surface, with immutable copied data and provider-wire parity exercised by rich-generation tests. |
| `ToolSpec` | `implemented` | `T:AnyInfer.ToolSpec` | `src/csharp/AnyInfer/ToolSpec.cs` | `src/csharp/AnyInfer.Tests/RichGenerationTypesTests.cs`<br>`src/csharp/AnyInfer.Tests/RichGenerationParityTests.cs` | SDK.7a | ToolSpec is represented by the native rich-generation DTO/event surface, with immutable copied data and provider-wire parity exercised by rich-generation tests. |
| `TransportError` | `implemented` | `T:AnyInfer.TransportException` | `src/csharp/AnyInfer/Errors.cs` | `src/csharp/AnyInfer.Tests/PublicModelTests.cs` | SDK.2b | TransportError maps to the native typed exception hierarchy, retaining category, retryability, nullable phase, and provider/HTTP diagnostic context. |
| `UnsupportedInputError` | `implemented` | `T:AnyInfer.UnsupportedInputException` | `src/csharp/AnyInfer/Errors.cs` | `src/csharp/AnyInfer.Tests/PublicModelTests.cs` | SDK.2b | UnsupportedInputError maps to the native typed exception hierarchy, retaining category, retryability, nullable phase, and provider/HTTP diagnostic context. |
| `Usage` | `implemented` | `T:AnyInfer.Usage`<br>`M:AnyInfer.Usage.Normalized`<br>`M:AnyInfer.Usage.Merge`<br>`M:AnyInfer.Usage.Sum`<br>`P:AnyInfer.Usage.ServerToolUses` | `src/csharp/AnyInfer/Models.cs` | `src/csharp/AnyInfer.Tests/UsageValueTests.cs`<br>`src/csharp/AnyInfer.Tests/AccountingValueTests.cs` | SDK.5b | Within the native numeric domain, normalized totals, later-known scalar overlay and all-known scalar sums match Python. Normalized preserves server-tool counts; Merge and Sum omit them in both implementations at the pinned Python baseline. This shared behavior is not a missing C# aggregation feature. |
| `UsageEstimated` | `implemented` | `T:AnyInfer.Events.UsageEstimated` | `src/csharp/AnyInfer/Core/GenerationCore.cs` | `src/csharp/AnyInfer.Tests/EventLifecycleTests.cs` | SDK.5c | Generation accounting labels estimated usage fields. |
| `UsageFacet` | `implemented` | `T:AnyInfer.Manifest.UsageFacet` | `src/csharp/AnyInfer/Manifest/ManifestFacets.cs` | `src/csharp/AnyInfer.Tests/ManifestValueTests.cs` | SDK.5a | Typed manifest facet/DTO is present; ordinary request/result manifest projection bounded to implemented facets |
| `UsageUpdate` | `implemented` | `T:AnyInfer.UsageUpdate` | `src/csharp/AnyInfer/GenerationEvent.cs` | `src/csharp/AnyInfer.Tests/SdkMigrationTests.cs` | SDK.1a | UsageUpdate is emitted by the native typed stream and is exercised while reconstructing a terminal generation from actual stream events. |
| `Verification` | `deferred` | — | — | `src/python/anyinfer/verification.py`<br>`tests/test_verify.py` | SDK.11a | Target verification operation, result summary and runtime diagnostics are unported. |
| `VideoPart` | `implemented` | `T:AnyInfer.VideoPart` | `src/csharp/AnyInfer/MediaParts.cs` | `src/csharp/AnyInfer.Tests/RichGenerationTypesTests.cs`<br>`src/csharp/AnyInfer.Tests/RichGenerationParityTests.cs` | SDK.7a | VideoPart is represented by the native rich-generation DTO/event surface, with immutable copied data and provider-wire parity exercised by rich-generation tests. |
| `__version__` | `deferred` | — | — | `src/python/anyinfer/__init__.py`<br>`tests/test_packaging.py` | SDK.12b | Native internal and assembly package version metadata exists, but no public root-version equivalent is verified. |
| `assistant` | `implemented` | `M:AnyInfer.Message.Assistant` | `src/csharp/AnyInfer/Models.cs` | `src/csharp/AnyInfer.Tests/RichGenerationTypesTests.cs`<br>`src/csharp/AnyInfer.Tests/RichGenerationParityTests.cs` | SDK.7a | assistant is represented by the native rich-generation DTO/event surface, with immutable copied data and provider-wire parity exercised by rich-generation tests. |
| `build_context_budget` | `implemented` | `M:AnyInfer.Capabilities.ContextBudgeting.BuildContextBudget` | `src/csharp/AnyInfer/Capabilities/ContextBudgeting.cs` | `src/csharp/AnyInfer.Tests/PricingAndBudgetTests.cs` | SDK.4b | Builds a budget from context window, request estimate, and reserve. |
| `check_context_fit` | `implemented` | `M:AnyInfer.Capabilities.ContextBudgeting.CheckContextFit` | `src/csharp/AnyInfer/Capabilities/ContextBudgeting.cs` | `src/csharp/AnyInfer.Tests/PricingAndBudgetTests.cs` | SDK.4b | Checks context fit and reports a context-gate failure. |
| `default_registry` | `partial` | `M:AnyInfer.Providers.ProviderRegistry.CreateDefault` | `src/csharp/AnyInfer/Providers/ProviderRegistry.cs` | `src/csharp/AnyInfer.Tests/ProviderSettingsTests.cs`<br>`src/csharp/AnyInfer.Tests/ProviderLifecycleTests.cs` | SDK.2a | Native static default registry factory has the C# shape, but its descriptor population lacks Python plugin discovery and provider breadth. |
| `default_resolver` | `partial` | `M:AnyInfer.Credentials.ResolverChain.CreateDefault` | `src/csharp/AnyInfer/Credentials/ResolverChain.cs` | `src/csharp/AnyInfer.Tests/CredentialsTests.cs` | SDK.2b | Native static default resolver factory covers built-ins, but lacks Python plugin discovery and issue reporting. |
| `dump_config` | `partial` | `M:AnyInfer.Config.AnyInferConfig.Dump` | `src/csharp/AnyInfer/Config/AnyInferConfig.cs` | `src/csharp/AnyInfer.Tests/ConfigTests.cs` | SDK.2c | Native instance dump matches the supported v1 subset; Python-only configuration sections remain unsupported. |
| `dumps_config` | `partial` | `M:AnyInfer.Config.AnyInferConfig.Dumps` | `src/csharp/AnyInfer/Config/AnyInferConfig.cs` | `src/csharp/AnyInfer.Tests/ConfigTests.cs` | SDK.2c | Native instance serialization matches the supported v1 subset; Python-only configuration sections remain unsupported. |
| `estimate_request` | `implemented` | `M:AnyInfer.Capabilities.TokenEstimation.EstimateRequest` | `src/csharp/AnyInfer/Capabilities/TokenEstimation.cs` | `src/csharp/AnyInfer.Tests/PricingAndBudgetTests.cs` | SDK.5b | Estimates messages, tools, schema, envelope, and unpriced parts. |
| `fetch_pricing` | `deferred` | — | — | `tests/test_pricing_drift.py`<br>`tests/test_pricing.py` | SDK.5b | Python HTTP pricing fetch and merge has no native public counterpart; native LoadDefault is local only. |
| `load_config` | `partial` | `M:AnyInfer.Config.AnyInferConfig.Load` | `src/csharp/AnyInfer/Config/AnyInferConfig.cs` | `src/csharp/AnyInfer.Tests/ConfigTests.cs` | SDK.2c | Native file loading validates the supported v1 subset; Python-only configuration sections remain unsupported. |
| `load_default_catalog` | `implemented` | `M:AnyInfer.Catalog.Catalog.LoadDefault` | `src/csharp/AnyInfer/Catalog/Catalog.cs` | `src/csharp/AnyInfer.Tests/CatalogTests.cs` | SDK.4a | Native static catalog loader reads the packaged default catalog. |
| `load_default_pricing` | `implemented` | `M:AnyInfer.Capabilities.PricingTable.LoadDefault` | `src/csharp/AnyInfer/Capabilities/PricingTable.cs` | `src/csharp/AnyInfer.Tests/PricingTableTests.cs` | SDK.5b | Native static pricing loader reads the packaged local table. |
| `loads_config` | `partial` | `M:AnyInfer.Config.AnyInferConfig.Loads` | `src/csharp/AnyInfer/Config/AnyInferConfig.cs` | `src/csharp/AnyInfer.Tests/ConfigTests.cs` | SDK.2c | Native string loading validates the supported v1 subset; Python-only configuration sections remain unsupported. |
| `manifest_json_schema` | `implemented` | `M:AnyInfer.Manifest.ManifestUtilities.JsonSchema` | `src/csharp/AnyInfer/Manifest/ManifestUtilities.cs` | `src/csharp/AnyInfer.Tests/ManifestSchemaTests.cs` | SDK.5a | Manifest JSON schema projection |
| `redact` | `implemented` | `M:AnyInfer.Redaction.Redact` | `src/csharp/AnyInfer/Redaction.cs` | `src/csharp/AnyInfer.Tests/CredentialsTests.cs` | SDK.2b | Native redaction helper |
| `register_secret` | `implemented` | `M:AnyInfer.Redaction.RegisterSecret` | `src/csharp/AnyInfer/Redaction.cs` | `src/csharp/AnyInfer.Tests/CredentialsTests.cs` | SDK.2b | Native secret registration helper |
| `semantic_ranker` | `deferred` | — | — | `src/python/anyinfer/_client/rankers.py` | SDK.9a | Native SDK has no helper that binds client embedding/rerank operations into a context semantic ranker. |
| `system` | `implemented` | `M:AnyInfer.Message.System` | `src/csharp/AnyInfer/Models.cs` | `src/csharp/AnyInfer.Tests/RichGenerationTypesTests.cs`<br>`src/csharp/AnyInfer.Tests/RichGenerationParityTests.cs` | SDK.7a | system is represented by the native rich-generation DTO/event surface, with immutable copied data and provider-wire parity exercised by rich-generation tests. |
| `tool` | `implemented` | `T:AnyInfer.Tool` | `src/csharp/AnyInfer/Tool.cs` | `src/csharp/AnyInfer.Tests/RichGenerationTypesTests.cs`<br>`src/csharp/AnyInfer.Tests/RichGenerationParityTests.cs` | SDK.7a | tool is represented by the native rich-generation DTO/event surface, with immutable copied data and provider-wire parity exercised by rich-generation tests. |
| `user` | `implemented` | `M:AnyInfer.Message.User` | `src/csharp/AnyInfer/Models.cs` | `src/csharp/AnyInfer.Tests/RichGenerationTypesTests.cs`<br>`src/csharp/AnyInfer.Tests/RichGenerationParityTests.cs` | SDK.7a | user is represented by the native rich-generation DTO/event surface, with immutable copied data and provider-wire parity exercised by rich-generation tests. |
## Subsystem public entry points

The following grouped inventory follows subsystem `__all__` declarations and API modules. These are not all duplicated at the root. Optional integrations and Python-only frontends are called out separately.

### `src/python/anyinfer/_client/__init__.py`

`AsyncClient`, `AsyncStream`, `CatalogEntryFit`, `CatalogView`, `Client`, `MessagesInput`, `ProviderSettings`, `SyncStream`, `Tool`, `semantic_ranker`, `tool`.

### `src/python/anyinfer/config/__init__.py`

`BUILTIN_OBSERVERS`, `COMMENT_KEY`, `CONFIG_FORMAT_VERSION`, `MAX_CONFIG_BYTES`, `AnyInferConfig`, `ObserverSpec`, `build_observers`, `dump_config`, `dumps_config`, `load_config`, `loads_config`.

### `src/python/anyinfer/credentials/__init__.py`

`KEYRING_SERVICE`, `CredentialResolver`, `EnvResolver`, `KeyringResolver`, `LiteralResolver`, `ResolverChain`, `default_resolver`.

### `src/python/anyinfer/registry.py`

`ENTRY_POINT_GROUP`, `AdapterFactory`, `HostShorthand`, `ModelPuller`, `PluginLoadIssue`, `PluginLoadReason`, `ProviderDescriptor`, `ProviderRegistry`, `ProviderSetupSpec`, `ReasoningTranslator`, `SetupField`, `SetupFieldKind`, `default_registry`, `normalize_provider_id`.

### `src/python/anyinfer/providers/__init__.py`

`builtin_descriptors`.

### `src/python/anyinfer/providers/presets.py`

`COMPAT_PRESETS`, `CompatPreset`, `PresetCompatAdapter`, `PresetEmbeddingAdapter`, `ReasoningStyle`, `preset_descriptors`.

### `src/python/anyinfer/capabilities/__init__.py`

`AUTO_SENTINELS`, `DEFAULT_ENCODING`, `DEFAULT_OUTPUT_RESERVE_TOKENS`, `DEFAULT_PRICING_URL`, `DEFAULT_PROBE_FEATURES`, `PROBEABLE_FEATURES`, `TRUSTED_PROVENANCE`, `AnthropicCountTokensEstimator`, `CapabilityStore`, `ContextBudget`, `CostEstimate`, `FeatureProbe`, `HeuristicTokenEstimator`, `LlamaServerTokenizeEstimator`, `PrewarmsCounts`, `PricingEntry`, `PricingTable`, `ProbeOutcome`, `ProbeReport`, `RequestEstimate`, `SpendLedger`, `SpendStore`, `SpendTotals`, `TargetAwareTokenEstimator`, `TiktokenEstimator`, `TokenEstimate`, `TokenEstimator`, `build_context_budget`, `capabilities_for`, `check_context_fit`, `compute_cost`, `context_gate_error`, `estimate_cost`, `estimate_request`, `estimator_for`, `fetch_pricing`, `headroom_for`, `load_default_pricing`, `with_cost`.

### `src/python/anyinfer/catalog/__init__.py`

`BEST_AT`, `FORMAT_VERSION`, `MODEL_KINDS`, `AliasEntry`, `ArtifactKind`, `Catalog`, `GgufArtifact`, `GgufFile`, `ModelEntry`, `ModelKind`, `ModelVariant`, `OllamaChannel`, `TargetEntry`, `load_default_catalog`, `resolve_target`.

### `src/python/anyinfer/local/__init__.py`

`ALLOWED_LICENSES`, `ATTESTATION_CACHE_BYPASS_ENV`, `ATTESTATION_CACHE_REFRESH_ENV`, `BACKEND_RANK`, `CACHE_BYPASS_ENV`, `CACHE_REFRESH_ENV`, `CONTEXT_LADDER`, `KEYRING_IDENTIFIER_SUFFIX`, `LOOPBACK_HOST`, `Accelerator`, `AcceleratorKind`, `AcquisitionPhase`, `AcquisitionPlan`, `AcquisitionProgress`, `AcquisitionReport`, `Backend`, `ConfidentialExecutionStatus`, `CpuTeeKind`, `DiscoveredProvider`, `DiscoveryEvidence`, `DownloadReport`, `FitLevel`, `GgufArtifact`, `GgufFile`, `HardwareProfile`, `InstallReport`, `LifecycleCallback`, `ManagedServer`, `ModelFit`, `ModelManifest`, `ModelStore`, `Posture`, `ProgressCallback`, `ProgressSink`, `PrunePlan`, `PruneProposal`, `Recommendation`, `RemoteFile`, `RemovalReport`, `ResolvedArtifact`, `ResolvedModel`, `ResourceSample`, `RuntimeArtifact`, `RuntimeManifest`, `RuntimeTable`, `ServerHandle`, `ServerPlan`, `ServerSupervisor`, `SizedEntry`, `SourceRef`, `SourceResolver`, `StorageProfile`, `StoreEntry`, `SystemSampler`, `Tier`, `TierSource`, `TuningInputs`, `VariantChoice`, `VariantPrefs`, `VerifiedWeights`, `WeightsProvenance`, `acquire`, `acquire_sync`, `allocate_port`, `artifact_paths`, `attestation_cache_path`, `available_backends`, `cache_path`, `check_cuda_preconditions`, `classify_fit`, `confidential_execution_status`, `default_model_dir`, `default_runtime_kind`, `detect`, `discover`, `download_artifact`, `endpoint_candidates`, `evaluate_variants`, `hash_model_weights`, `install_hint`, `install_runtime`, `installed_runtimes`, `is_loopback`, `iter_missing`, `kv_bytes_per_token`, `license_allowed`, `load_runtime_table`, `memory_budget`, `open_verified_weights`, `plan_acquisition`, `plan_server`, `probe_signature`, `recommend_alias`, `remove_runtime`, `runtime_root`, `select_backend`, `select_variant`, `sort_by_fit`, `storage_profile`, `verify_file`, `verify_model_manifest`.

### `src/python/anyinfer/context/__init__.py`

`DEFAULT_CHUNK_TOKENS`, `DEFAULT_KEEP_RECENT`, `DEFAULT_MAX_BYTES`, `DEFAULT_MAX_DOCUMENTS`, `DEFAULT_ROLLUP_SHARE`, `ENVELOPE_FORMAT`, `SELECTION_ORDERS`, `VALID_STRATEGIES`, `Chunk`, `CompactSource`, `ContextDocument`, `ContextRequest`, `ContextSummary`, `ContextTuning`, `Distillation`, `DuplicateMap`, `HistoryCompaction`, `RankCache`, `Reduction`, `ReductionPlan`, `ReductionState`, `RenderOrder`, `SelectionOrder`, `SemanticRanker`, `Strategy`, `StrategyOutlook`, `SupportsGenerate`, `build_rank_cache`, `compact_history`, `compact_source`, `detect_language`, `distill`, `distill_sync`, `expand_query`, `find_duplicates`, `imported_names`, `is_generated_path`, `module_surfaces`, `normalize_strategy`, `plan`, `rank`, `render_chunk_block`, `render_compact_block`, `render_corpus`, `render_duplicate_block`, `render_extract_block`, `render_file_block`, `salience`, `select`, `split_document`, `structural_extract`, `supports_compaction`, `tokenize`.

> NOTE: `AnyInfer.Context.ContextTuning` now implements the standalone 17-setting model,
> default/recommended constants and strict mapping/merge helpers. Source and independent
> observer review, 24 native controls and 57 shared development cases plus one separate
> native range boundary pass; full qualification is tracked by CTUNE.4 in
> [native context tuning](SDK_CONTEXT_TUNING.md). This subsystem export is outside the 235
> root rows. Reducers, document/ranking/selection/history and request/config wiring remain
> open; settings evidence does not complete SDK.9a or a root completion mark.

### `src/python/anyinfer/events/__init__.py`

`PAYLOAD_FIELDS`, `REDACTED`, `ArenaCompleted`, `AttemptCompleted`, `AttemptStarted`, `BatchCompleted`, `BatchSubmitted`, `CachePlanned`, `ContextReduced`, `CredentialRotated`, `DownloadProgress`, `EventDispatcher`, `FallbackTriggered`, `FirstToken`, `JsonlObserver`, `LoggingObserver`, `Observer`, `ParameterDropped`, `ProviderDiagnostic`, `RateLimitObserved`, `RateLimitWaited`, `RedactionRegistry`, `RepairAttempted`, `RequestCompleted`, `RequestFailed`, `RequestStarted`, `RetryScheduled`, `ServerLifecycle`, `Subscription`, `TargetResolved`, `TelemetryEvent`, `UsageEstimated`, `event_to_dict`, `redact`, `register_secret`, `strip_payloads`.

### `src/python/anyinfer/manifest.py`

`MANIFEST_FORMAT`, `AttemptFacet`, `CacheFacet`, `CapabilityFacet`, `ContextFacet`, `DroppedParameter`, `ManifestBuilder`, `MechanismRung`, `PayloadFacet`, `ReductionRecord`, `RepairRecord`, `RequestFacet`, `RouteFacet`, `RouteStep`, `RunManifest`, `SchemaFacet`, `SourcedFact`, `TimingFacet`, `UsageFacet`, `build_operation_manifest`, `manifest_json_schema`, `render`, `schema_digest`.

### `src/python/anyinfer/session.py`

`Session`, `SessionReuse`.

### `src/python/anyinfer/evaluate/arena.py`

`ARENA_ENVELOPE_FORMAT`, `ArenaResult`, `Candidate`, `arena_to_dict`, `candidate_envelope`, `canonical_json`, `select_candidates`.

### `src/python/anyinfer/evaluate/compare.py`

`EmbeddingTargetComparison`, `TargetComparison`.

### `src/python/anyinfer/benchmark.py`

`BENCHMARK_OUTPUT_TOKENS`, `BENCHMARK_PROMPT_TOKENS`, `BenchmarkSample`, `Measurement`, `MeasurementIdentity`, `MeasurementStore`, `benchmark_prompt`, `identity_for`, `measurement_from`, `normalize_endpoint`.

### `src/python/anyinfer/types/operations.py`

`DEFAULT_MAX_DOCUMENTS`, `DEFAULT_MAX_EMBEDDING_INPUTS`, `DEFAULT_MAX_EMBEDDING_RESPONSE_BYTES`, `DEFAULT_MAX_RERANK_RESPONSE_BYTES`, `TERMINAL_BATCH_STATUSES`, `BatchFailure`, `BatchGenerationRequest`, `BatchHandle`, `BatchLine`, `BatchPolicy`, `BatchReport`, `BatchResult`, `BatchStatus`, `EmbeddingCapabilities`, `EmbeddingInputIntent`, `EmbeddingRequest`, `EmbeddingResult`, `EmbeddingSpace`, `EmbeddingVector`, `InferenceOperation`, `RankedItem`, `RerankCapabilities`, `RerankDocument`, `RerankRequest`, `RerankResult`, `embedding_conjunction`, `rerank_conjunction`.

### `src/python/anyinfer/mcp/__init__.py`

`ACCEPTED_PROTOCOL_VERSIONS`, `NAMESPACE_SEPARATOR`, `PROTOCOL_VERSION`, `HTTPTransport`, `MCPServer`, `MCPToolset`, `MCPTransport`, `ServerInfo`, `StdioTransport`.

### `src/python/anyinfer/testing/__init__.py`

`CONFORMANCE_CASES`, `CONFORMANCE_SCENARIOS`, `DEFAULT_SCRIPTED_CAPABILITIES`, `SECRET_SHAPES`, `VOLATILE_FIELDS`, `AuditFinding`, `Capabilities`, `CaseResult`, `Cassette`, `CassetteTransport`, `ConformanceCase`, `ConformanceHarness`, `FailureKind`, `FakeAnthropicServer`, `FakeBedrockServer`, `FakeEmbeddingRerankProvider`, `FakeGeminiServer`, `FakeMCPServer`, `FakeMCPTool`, `FakeOllamaServer`, `FakeOpenAIServer`, `FakeResponse`, `FakeResponsesServer`, `FakeRetrievalServer`, `Interaction`, `ScriptedEmbeddingFailure`, `ScriptedFailure`, `ScriptedModel`, `ScriptedProvider`, `assert_manifest_matches`, `audit_cassette`, `audit_interaction`, `chunk_text`, `eventstream_frame`, `matrix_row`, `ndjson_lines`, `normalize`, `results_to_json`, `run_conformance`, `scenario_responses`, `sse_lines`.

### `src/python/anyinfer/otel.py`

`GEN_AI`, `OTelObserver`, `install`.

### `src/python/anyinfer/verification.py`

`VERIFY_MAX_OUTPUT_TOKENS`, `VERIFY_PROMPT`, `VERIFY_REASONING_OUTPUT_TOKENS`, `VERIFY_SCHEMA`, `Verification`, `excerpt`, `judge_reply`.

## Product and packaging boundaries

- **Core SDK:** `src/python/anyinfer/` except `cli.py` and `serve/`; migrate library-owned behavior through the milestones.
- **Explicitly separate:** CLI command surface (`cli.py`) and demo (`src/python/anyinfer_demo/`) are not core SDK parity. `serve/` is a separately scoped OpenAI-compatible ASGI frontend; core integration is through `AsyncClient` and shared config.
- **Separate add-on distributions:** `anyinfer-store`, `anyinfer-shared`, and `anyinfer-confidential` under `src/python/`; their integration points must be inventoried, but each C# sibling requires its own package/scope decision.
- **Native/platform counterparts:** Python async/sync maps to Task/IAsyncEnumerable and a lifetime-bound sync facade; pathlib/path APIs to `System.IO`; entry points/plugins to .NET assembly/plugin loading; keyring and OpenTelemetry are optional platform assemblies; Python decorators/callables require explicit delegate/attribute/function registration APIs; subprocess/local runtime behavior must be qualified per OS. Python type/runtime introspection has no automatic equivalent and is not silently promised.
- **Frozen v0 boundary:** `specification/core-generation.md` covers async explicit-target generation, text messages, schema subset/prompt repair, retry/fallback/health, typed events/results/errors, fixture and OpenAI chat adapters only. Catalog/aliases, other provider breadth, model listing/probes, sync API, multimodal, tools, accounting and local lifecycle are outside that profile.

## Verification record

Root exports parsed as a literal AST list: 235 entries, 235 unique, zero duplicates. Static comparison procedure: parse `src/python/anyinfer/__init__.py`, locate assignment to `__all__`, read each string constant, and compare as a set against the `Python export` table cells in this document. No import of `anyinfer` was performed. The `__all__` declaration is literal (not computed).

SDK.4c's accepted source checkpoint adds explicit async/sync generation probes, immutable
FeatureProbe/ProbeReport helpers and complete declarative setup metadata. Its four default
measurements include real raw tool translation; this does not complete normal generation
tool calls or tool loops. Token counting/accounting remains SDK.5/11, embedding/rerank
probes SDK.6, and rich tool behavior SDK.7. All root rows remain unchecked until their
full assigned semantics and the final audit pass. Source checkpoint and clean-revision
qualification are recorded in the parent/child execution plans; source is
`0fd3fb47cd08295537674aa23571dffcc9482888`.
