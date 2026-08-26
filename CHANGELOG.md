# Changelog

What changed in each released version, for people who build against AnyInfer rather than
on it. This is a curated list, not a commit log: public API and configuration changes,
provider and capability bindings, behavior changes, critical fixes, and anything a demo
app or sidecar user would notice. Everything else lives in git.

Entries accrue under **Unreleased** as work merges, so what is queued for the next
release is a section you can read rather than a diff between two tags. Cutting a release
promotes that heading in place: the entries are pinned to the version, and a fresh empty
Unreleased opens above them.

What qualifies and how entries are written is documented in
[the changelog rules](https://anyinfer.dev/contributing/changelog/). Released sections are
never rewritten.

## Unreleased

## 0.1.3 — 2026-08-26

### Added
- Deferred batch inference at a provider's discounted tier, via `submit_batch()`,
  `batch_status()`, and `fetch_batch()`.
- Provider-run tools: `server_tools=` asks a target to search or run code in one
  request; `ServerToolDelta` returns what it found, priced per invocation.
- The sidecar serves `POST /v1/responses`, OpenAI's current-generation dialect, with
  its semantic streaming events — so a Responses-first SDK no longer 404s.
- Typed citations for grounded generation: `Generation.citations` and a
  `CitationDelta` stream event, with `cite_documents=True` asking for them.
- `VideoPart`, alongside the existing text, image, and audio input parts.
- `Sampling` gained typed `seed`, `presence_penalty`, and `frequency_penalty`;
  `GenerationRequest` gained `logprobs`.
- Exact token counting where estimation was used before: the `tokenizers` extra,
  Anthropic's count-tokens endpoint, and llama-server's `/tokenize`.
- Credentials can be rotated at runtime: a replaced key takes effect without restarting
  the process.
- Telemetry sinks, plugin groups, proxy and TLS settings, and a decision log.
- The confidential Relay paces and bounds its own traffic: pooled pacing, per-tenant
  admission limits, and 429s carrying `Retry-After` and `RateLimit-*` headers.
- `anyinfer models prune` proposes least-recently-used deletions to fit a disk budget.

### Fixed
- The demo app no longer persists literal API keys, and writes its configuration with
  owner-only permissions.
- The confidential Relay is authenticated, and its key material is written with
  owner-only permissions.
- Tier 3 attestation fails closed on an unknown GPU confidential-compute state, and
  local weight verification is bound to the load rather than a skippable call.
- The sidecar accepts base64 embeddings and typed `reasoning_effort`, honors repair and
  context configuration, and caps request bodies.

Curated to the entries a partner would act on. [Everything in 0.1.3](https://github.com/anthturner/AnyInfer/compare/v0.1.2...v0.1.3).

## 0.1.2 — 2026-08-25

### Added
- `Client.embed()` and `Client.rerank()` — embeddings and reranking as first-class typed
  operations across hosted, local, and retrieval-only providers.
- Confidentiality tiers — a per-call confidentiality contract spanning four execution
  modes, from ordinary hosted inference through to attested local execution.
  Sealed templates keep prompt text out of a provider's logs, the relay strips caller
  identity from a hosted request, and model provenance is recorded on every run manifest
  so a completed call can be audited after the fact. See
  [confidentiality tiers](https://anyinfer.dev/guides/confidentiality-tiers/).
- `anyinfer-store`, an optional vector-store add-on shipped as its own package, with
  brute-force search and rerank-aware querying.
- `Client.compare()` and `Client.compare_embedding()` report how two targets differ
  without dispatching a call.
- `Client.probe()` and `Client.verify()` check what a declared target actually supports
  before a call depends on it.
- Session reuse, throughput benchmarking against a caller-owned store, and per-adapter
  runtime diagnostics.
- Engine-managed model acquisition for supervised llama.cpp: the engine stages weights
  instead of the caller handing it a path.
- The sidecar serves an `anyinfer_manifest` extension on `/v1/embeddings` and the rerank
  route.
- The demo app gained tabbed conversations, an in-app SDK help system, and a visual
  refresh.

### Changed
- Capability-gated parameters and a preflight dry run reject an unsupported request
  before it reaches a provider, rather than after.
- Naming a target redirects a call; it no longer discards the policy attached to it.

### Fixed
- Streaming generators are closed at every layer on early exit, so an abandoned stream
  no longer leaks provider connections.
- `max_response_bytes` is enforced on every `embed()` and `rerank()` path.
- The sidecar cancels in-flight work when a client disconnects instead of running it to
  completion.

## 0.1.1 — 2026-08-08

### Added
- The demo app's settings dialog gained an advanced-fields disclosure.

### Fixed
- Acquiring a local model from a filesystem path works on POSIX.

## 0.1.0 — 2026-08-08

### Added
- First public release: the typed inference contract, hosted and local providers, the
  pack-in demo app, and the OpenAI-compatible sidecar.
