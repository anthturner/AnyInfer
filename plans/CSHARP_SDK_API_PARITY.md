---
kind: spec
title: "C# SDK API parity inventory"
---

# C# SDK API parity inventory

> Baseline: `199c3f833e568334b629edd7d89f41a3b76efe2a`. Source inventory is static; no Python package imports.
> Status: SDK.1 vocabulary, generation convenience calls and stream contracts passed the full workspace gate on 2026-10-17. The root checklist remains unchecked until each feature is complete across its assigned milestones; a renamed type alone is not completion. Passing the frozen 102-case profile is not full-library parity.
> SDK.2's provider/settings pool, credential/error foundation and supported active configuration subset also passed the full 18-step gate: 222 native unit tests, 93 conformance tests, independent configured Python/C# execution, package-only consumption and executable C# documentation. Broader configuration policies, credential refresh/platform stores, provider breadth and operation APIs remain assigned to later milestones; this is not full completion of similarly named Python exports.
> SDK.3's synchronous `Client` and `SyncStream` facade passed the final 18-step gate, including 238 native unit tests, 93 conformance tests, package-only async/sync consumption and eight source-linked offline C# examples. Its lifetime controls cover concurrent callers, bounded queues, original cancellation/errors and callback re-entry. All 235 root rows remain unchecked until their broader assigned milestones and final completeness audit pass.
> SDK.4a's catalog, provenance capability/pricing metadata and explicit async/sync provider discovery/health passed all 18 workspace steps: 304 native unit tests, 93 conformance tests, package-only consumption and 15 rendered C# blocks matching executed source across six pages. Source checkpoint `aca24ddf2097ca9a33ff33039a2285f0b0b0bdb7` passed clean-revision package qualification. General schema, probes, accounting and broader provider/operation parity remain assigned to later milestones; all root rows remain unchecked.
> SDK.4b's SchemaSpec, modern Draft 6/7/2019-09/2020-12 validation, explicit resource retrieval and typed structured-result convenience passed 39 focused native cases, 24 independent Python cases, 343 native unit/93 conformance tests and all 18 workspace steps. Source `dbf82a949fca6ee7321b921233c0cda198b3a506` passes clean-revision isolated package qualification. Legacy Draft 3/4 remain SDK.11c; native numeric comparison/regex limits and C# retrieval policy are documented differences. Probes, accounting and later operation/provider semantics remain unfinished; all 235 root rows stay unchecked.

## Root exports (235)

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
