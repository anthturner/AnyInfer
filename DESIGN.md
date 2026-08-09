# AnyInfer — Design Foundation

> Status: v0.1 draft, produced from the architecture interview on 2026-08-05.
> Companions: [NOTES.md](NOTES.md) — running record of decisions/assumptions/risks;
> [IMPLEMENTATION.md](IMPLEMENTATION.md) — normative types, algorithms, and the ordered
> build plan (implementers work from there); [AGENTS.md](AGENTS.md) — repository automation rules;
> [contracts/](contracts/) — per-provider wire-protocol snapshots.

---

## 1. Product definition

**AnyInfer** is an application-owned hybrid inference runtime for Python. It provides one
normalized inference contract across hosted AI providers, routing hubs, existing local
services, and a supervised `llama.cpp` process owned by the application.

It is the single AI substrate for Frisket, ModelFit, and mote-cli — replacing their three
independent provider layers — and is designed from day one as if public, to be published once
those migrations prove the API.

Provider breadth is compatibility inventory, not the product definition. The public boundary
is the combination of application-owned local lifecycle, portable behavior with explicit
degradation, and context preparation tied to the selected target's capabilities.

One sentence: *an application-owned hybrid inference runtime — approved context and normalized
requests in, typed event streams or validated results out, across cloud and local execution.*

## 2. Goals and non-goals

### Goals
1. **One adapter per provider, everywhere.** No per-engine branches in consuming apps — not in
   generation code, not in config UIs (declarative setup specs), not in error handling.
2. **Structured output as a contract.** A request carrying a schema always yields a
   client-side-validated result, using the strongest native mechanism the provider offers,
   with an opt-in bounded repair loop.
3. **Uniform observability.** TTFT, latency, throughput, token usage, and cost are measured
   centrally with identical definitions across all providers; consumers subscribe to typed
   in-process events; OTel export is a bridge, not the contract.
4. **First-class local inference.** Hardware detection, backend selection (CPU/CUDA/ROCm/
   Vulkan/Metal), llama-server supervision and tuning, pinned GGUF catalog with verified
   downloads, and hardware→tier model recommendation.
5. **Novice-friendly aliases.** `small`/`medium`/`large` tiers resolve per-engine to concrete
   models via a catalog (bundled default, app-overridable).
6. **Deterministic routing.** Retries honoring `retryable`/`retry-after`, explicit fallback
   chains, health-aware skip. Debuggable: every result carries its attempt trail.
7. **Typed, protocol-oriented, slim.** Frozen dataclasses, `Protocol` interfaces, mandatory
   deps ≈ `httpx2` + `jsonschema`; everything else is extras.
8. **Two first-class integration paths.** Direct SDK usage (`pip install anyinfer`) *or* the
   serve frontend shipped as a **self-contained cross-platform binary** (macOS, Linux,
   Windows — no Python required on the host) exposing the OpenAI-compatible service (§22,
   ADR-010). Consumers choose per project; behavior is identical because the binary is
   the same core (ADR-009).
9. **Published, developer-friendly SDK documentation.** A versioned docs site with
   quickstart, task-oriented guides, per-provider pages, an executable cookbook, a full API
   reference, and an error catalog ships *with* the system — documentation deliverables are
   part of each milestone, not an afterthought (§25).
10. **Context engineering tied to dispatch.** Token budgets, cost ranges, deterministic
    reduction, and bounded distillation use the same provenance-tagged target capabilities as
    pre-dispatch gating and context-overflow routing; omissions and uncertainty stay visible.

### Non-goals (v1)
- **No daemon in the core.** The core is a library; nothing listens on a socket by default.
  However, an **OpenAI-compatible loopback serve frontend** (`anyinfer.serve`, `[serve]`
  extra) is an explicitly *architecture-guaranteed* future module — see §22 and ADR-009.
  v1 core ships without it; the invariants that make it a thin projection are enforced
  from M0.
- **Not an agent framework.** A tool-execution loop is provided (late in v1), but no planning,
  memory, or multi-agent constructs. *Clarified (D28, 2026-08-07):*
  `anyinfer.context.distill` is a bounded, deterministic map/reduce fan-out — fixed
  two-phase shape, no planning — permitted on the same grounds as the schema-repair
  loop's bounded extra calls.
- **No load balancing or cost/latency-adaptive routing** (deferred; the router's policy
  interface must not preclude them).
- **No embeddings, images, audio, or fine-tuning APIs.** Text generation only. (Multimodal
  *inputs* are structurally reserved in the message model but not implemented.)
- **No prompt templating.** Frisket/mote keep their own prompt construction. *Amended
  (D28, 2026-08-07):* the optional `anyinfer.context` subsystem renders a mechanical,
  documented context envelope (file/extract/rollup blocks) as reducer output — a data
  format like the C3/C4 injection prompts, not a template engine. Apps still own all
  surrounding prompt text, and the core client never constructs prompts on their behalf.
- **Not an OpenAI-API clone.** OpenAI-compatible is one dialect among several, not the core
  abstraction (see ADR-001).
- **Not an organization gateway or control plane.** Virtual keys, multi-tenancy, RBAC,
  organization spend limits, distributed rate accounting, guardrails, and an admin UI belong
  in a deployment around AnyInfer, not in the library.

## 3. Architecture overview

```
                        Application (Frisket / ModelFit / mote-cli)
                                        │
            ┌───────────────────────────┼────────────────────────────┐
            │ sync facade (Client)      │ async core (AsyncClient)   │
            └───────────────────────────┴────────────────────────────┘
                                        │
      ┌──────────┬──────────────┬───────┴──────┬──────────────┬───────────┐
      │ catalog  │ schema       │  router      │ events       │ config    │
      │ (alias→  │ (validate,   │  (retry,     │ (observers,  │ (optional │
      │  model)  │  mechanism,  │   fallback,  │  redaction,  │  canonical│
      │          │  repair)     │   health)    │  otel bridge)│  layer)   │
      └──────────┴──────────────┴───────┬──────┴──────────────┴───────────┘
                                        │  normalized WireRequest / AdapterEvent
                              ┌─────────┴──────────┐
                              │  provider registry │  (descriptors, entry points)
                              └─────────┬──────────┘
        ┌──────────┬──────────┬────────┼─────────┬──────────┬─────────────┐
        │ openai-  │ openai   │anthropic│ ollama  │ copilot  │ azure-      │ …
        │ compat   │(Responses)│(Messages)│(native)│ (sdk)    │ foundry     │
        └──────────┴──────────┴─────────┴────┬────┴──────────┴─────────────┘
                                             │
                                   ┌─────────┴─────────┐
                                   │ local subsystem   │  llama-cpp adapter =
                                   │ hardware · tuning │  supervised llama-server
                                   │ gguf · downloads  │  + openai-compat dialect
                                   │ server supervisor │
                                   └───────────────────┘
```

**The one load-bearing rule:** adapters *only translate*. Every adapter exposes a single
generation entry point that yields a normalized event stream (even when the provider call was
buffered). The core owns retries, fallback, schema validation/repair, timing measurement,
usage normalization, telemetry, and redaction. This is what keeps every adapter thin — and
what makes a preset registry possible at all, since dozens of branded providers can share one
adapter precisely because the adapter holds no policy (see ADR-003).

## 4. Modules and responsibilities

| Module | Responsibility |
|---|---|
| `anyinfer.types` | Frozen dataclasses: messages, requests, results, events, capabilities, usage, timing. Zero I/O. |
| `anyinfer.errors` | Exception hierarchy (§10). |
| `anyinfer._client` | `AsyncClient` (core orchestration), `Client` (sync facade over a background event loop), tool loop. |
| `anyinfer.registry` | `ProviderDescriptor`, collision-safe `ProviderRegistry`, entry-point discovery (`anyinfer.providers` group), alias normalization. |
| `anyinfer.routing` | `Route`, `Retry`, health gate, attempt records, backoff. |
| `anyinfer.schema` | Schema normalization (dict / pydantic-duck-typed), mechanism selection, per-provider wire projection, client-side validation, repair loop. |
| `anyinfer.events` | Observer protocol, dispatch, secret-redaction registry, privacy levels. |
| `anyinfer.otel` | Lazy bridge: typed events → OTel spans/metrics (`opentelemetry-api` only, only if enabled). |
| `anyinfer.credentials` | `CredentialResolver` protocol; `env://`, literal, `credential://` (keyring extra) resolvers; auto-registration for redaction. |
| `anyinfer.config` | Optional canonical config: JSON schema, load/save, precedence (args > env > file), bounded parsing, credential-field hygiene, path containment. |
| `anyinfer.catalog` | Alias-tier catalog schema, bundled `default.json`, merge/override, `alias × engine → concrete target` resolution. |
| `anyinfer.capabilities` | Layered `ModelCapabilities` assembly: static catalog → live discovery → active probes; provenance tagging. |
| `anyinfer.local` | `hardware` (detection + disk cache), `backends` (CUDA/ROCm/Vulkan/Metal availability), `tuning` (posture → server plan), `gguf` (pinned catalog, atomic sharded downloads), `server` (llama-server supervisor, loopback-only), `recommend` (hardware→tier). |
| `anyinfer.providers.*` | One module per adapter; `openai_compat` is the base dialect several subclass. |
| `anyinfer.testing` | Conformance suite (parametrized), fake streaming servers, cassette record/replay helpers. Public so third-party adapters can certify themselves. |

## 5. Core domain types

Python ≥ 3.11. Frozen `dataclasses` with `slots=True` throughout; `typing.Protocol` for
interfaces; **no pydantic dependency** (schemas *supplied by callers* may be pydantic models —
accepted via duck-typed `model_json_schema()`).

```python
# anyinfer.types (illustrative signatures, not exhaustive)

Role = Literal["system", "user", "assistant", "tool"]

@dataclass(frozen=True, slots=True)
class Text:
    text: str

@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    arguments: Mapping[str, Any]

@dataclass(frozen=True, slots=True)
class ToolResult:
    call_id: str
    content: str
    is_error: bool = False

ContentPart = Text | ToolCall | ToolResult   # multimodal parts reserved for future

@dataclass(frozen=True, slots=True)
class Message:
    role: Role
    content: tuple[ContentPart, ...]

@dataclass(frozen=True, slots=True)
class Sampling:
    temperature: float | None = None
    top_p: float | None = None
    max_output_tokens: int | None = None
    stop: tuple[str, ...] = ()

ReasoningEffort = Literal["minimal", "low", "medium", "high"]   # normalized; adapters translate

@dataclass(frozen=True, slots=True)
class GenerationRequest:
    messages: tuple[Message, ...]
    schema: SchemaSpec | None = None          # structured-output contract
    tools: tuple[ToolSpec, ...] = ()
    sampling: Sampling = Sampling()
    reasoning: ReasoningEffort | None = None
    timeout_s: float | None = None
    max_response_bytes: int = 1 << 20         # ModelFit's cap, generalized
    provider_options: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    # ^ escape hatch, namespaced by provider id: {"ollama": {"keep_alive": "10m"}}
    #   Never consulted by the core; passed verbatim to the matching adapter only.
```

**Targets** name where a request goes. Three spellings, one resolution path:

```python
Target = str            # "anthropic:claude-sonnet-5" | "ollama:qwen3:8b" | alias "medium"
                        # engine aliases normalize (ModelFit rules): "claude:..." → "anthropic:..."

@dataclass(frozen=True, slots=True)
class ResolvedTarget:
    provider_id: str
    model: str            # may be the sentinel "auto" (Copilot) — see §7
    via_alias: str | None # "medium" if resolved through the catalog
```

**Results:**

```python
@dataclass(frozen=True, slots=True)
class Usage:
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    reasoning_tokens: int | None = None
    cost_usd: Decimal | None = None          # computed from pricing metadata when known

@dataclass(frozen=True, slots=True)
class Timing:
    started_at: float
    first_token_ms: float | None             # TTFT, measured centrally at first visible delta
    total_ms: float
    output_tokens_per_s: float | None
    phases: Mapping[str, float] = field(default_factory=dict)  # e.g. ollama model_load_ms

@dataclass(frozen=True, slots=True)
class AttemptRecord:
    target: ResolvedTarget
    outcome: Literal["ok", "retried", "failed", "skipped_unhealthy"]
    error: ErrorInfo | None
    timing: Timing | None

@dataclass(frozen=True, slots=True)
class Generation:
    text: str
    structured: Any | None                   # present iff request.schema; already validated
    tool_calls: tuple[ToolCall, ...]
    target: ResolvedTarget                   # what actually served it (post-fallback)
    finish_reason: Literal["stop", "length", "tool_calls", "content_filter", "other"]
    usage: Usage
    timing: Timing
    structured_mechanism: Literal["grammar", "json_schema", "json_mode", "prompt"] | None
    repair_attempts: int
    attempts: tuple[AttemptRecord, ...]      # full routing trail
    warnings: tuple[str, ...]
    raw: Any | None                          # provider payload escape hatch (opt-in retention)
```

## 6. Streaming event model

One typed event stream is the generation primitive; non-streaming is "drain the stream, return
the final result" (ADR-001).

```python
@dataclass(frozen=True, slots=True)
class TextDelta:        text: str
@dataclass(frozen=True, slots=True)
class ReasoningDelta:   text: str
@dataclass(frozen=True, slots=True)
class ToolCallDelta:    call_id: str; name: str | None; arguments_fragment: str
@dataclass(frozen=True, slots=True)
class UsageUpdate:      usage: Usage
@dataclass(frozen=True, slots=True)
class TimingMark:       name: Literal["first_token", "attempt_start", ...]; at_ms: float
@dataclass(frozen=True, slots=True)
class AttemptFailed:    record: AttemptRecord      # emitted before a retry/fallback
@dataclass(frozen=True, slots=True)
class StreamEnded:      result: Generation

StreamEvent = TextDelta | ReasoningDelta | ToolCallDelta | UsageUpdate \
            | TimingMark | AttemptFailed | StreamEnded
```

Consumption patterns this must serve (all verified against current app behavior):
- **mote**: iterate, print `TextDelta.text`, done.
- **ModelFit**: iterate for `TimingMark("first_token")`, then read `StreamEnded.result` —
  the "stream for timing, one authoritative buffered result" pattern, now free.
- **Frisket**: never iterates; calls the non-streaming method, which drains internally.

SSE parsing lives in one shared module used by all httpx2 adapters; adapters map wire deltas to
events. Providers without streaming (or when the transport refuses) degrade to a single
`TextDelta` + `StreamEnded` — the consumer contract never changes.

## 7. Capability model

```python
Provenance = Literal["catalog", "discovered", "probed", "default"]

@dataclass(frozen=True, slots=True)
class Sourced(Generic[T]):
    value: T
    provenance: Provenance

class Feature(Flag):
    STREAMING = auto(); JSON_SCHEMA = auto(); GRAMMAR = auto(); JSON_MODE = auto()
    TOOLS = auto(); REASONING = auto(); SYSTEM_PROMPT = auto(); CACHE_USAGE = auto()

@dataclass(frozen=True, slots=True)
class ModelCapabilities:
    context_window: Sourced[int] | None
    max_output_tokens: Sourced[int] | None
    features: Sourced[Feature]
    pricing: Sourced[Pricing] | None
    local: LocalModelInfo | None    # artifact size, quantization, est. RAM/VRAM (ModelFit's
                                    # ModelDiscoveryMetadata), observed VRAM residency
```

Assembly is layered, later layers overriding earlier, every field provenance-tagged:
1. **Static catalog** — bundled data: pricing, known context windows for hosted models.
2. **Live discovery** — `list_models()`, Ollama `/api/tags`/`/api/ps`, Anthropic paginated
   `/v1/models`, Copilot SDK model list.
3. **Active probes** (opt-in, costs a request) — `capabilities/probes.py` (D38): one
   forced-mechanism request per feature, recording only conclusive outcomes.

**The `auto` problem (Copilot):** when `model == "auto"`, capabilities are the *conjunction*
(tightest bound per field) across the models the provider might pick — Frisket's
`_copilot_capacity` approach, promoted to a general rule for any delegating provider.

**Structured-output mechanism selection** reads `features`: `GRAMMAR > JSON_SCHEMA >
JSON_MODE > prompt injection`. The chosen mechanism is recorded on the result. Per-provider
wire projection (e.g. Frisket's Ollama schema stripping of `minLength`/huge `maxItems`) lives
in the adapter; the *original* schema always validates the response client-side.

## 8. Provider-adapter contract

```python
@runtime_checkable
class ProviderAdapter(Protocol):
    descriptor: ClassVar[ProviderDescriptor]

    async def list_models(self) -> Sequence[DiscoveredModel]: ...
    async def health(self) -> Health: ...          # cheap readiness probe; router consults
    def generate(self, req: WireRequest) -> AsyncIterator[AdapterEvent]: ...
    async def aclose(self) -> None: ...
```

- `WireRequest` is the *post-resolution* form: concrete model, already-selected structured
  mechanism, projected schema, translated reasoning effort, merged provider options. Adapters
  never see aliases, routing policy, or repair state.
- `generate()` is the **only** generation entry point and always yields events. Buffered
  providers yield one delta + end. The core drains for non-streaming calls.
- Adapters raise only `ProviderError` subclasses with `retryable`/`retry_after` set; they never
  retry internally.
- Optional capabilities (e.g. session reuse for mote's token cache, runtime diagnostics) are
  declared on the descriptor, not duck-typed via `getattr` (improves on Frisket).

```python
@dataclass(frozen=True, slots=True)
class ProviderDescriptor:               # ModelFit's design, generalized
    id: str                             # "anthropic"
    aliases: tuple[str, ...]            # ("claude",)
    display_name: str
    factory: AdapterFactory
    locality: Literal["hosted", "local"]
    default_base_url: str | None
    requires_base_url: bool
    setup: ProviderSetupSpec            # declarative fields → app UIs need no engine branches
    reasoning_translator: ReasoningTranslator
    static_capabilities: Mapping[str, ModelCapabilities]   # catalog layer seed
    token_calibration: TokenCalibration = TokenCalibration()  # D34: envelope this provider bills for
    max_repair_attempts: int | None = None                    # D35: ceiling on schema-repair round trips
    supports_sessions: bool = False
    reports_diagnostics: bool = False                         # D36: adapter implements diagnostics()
```

Registration: built-ins pre-registered; third parties via entry points
(`[project.entry-points."anyinfer.providers"]`), loaded lazily, collision-safe (duplicate
id/alias rejection at registration, ModelFit rules).

### v1 adapters and their dialects

| Adapter | Transport | Notes |
|---|---|---|
| `openai-compat` | httpx2, chat completions + SSE | Base class for several below |
| `openai` | httpx2, **Responses API** | ModelFit's adapter modernized |
| `anthropic` | httpx2, Messages API | thinking deltas excluded from text, counted for TTFT |
| `ollama` | httpx2, native `/api/chat`, `/api/tags`, `/api/ps` | GPU-spill warning; `keep_alive` sessions |
| `openrouter` | openai-compat subclass | + model metadata from `/models` (rich pricing/context data) |
| `azure-foundry` | openai-compat subclass | Entra via `azure-identity` (extra); `max_completion_tokens` |
| `copilot` | `github-copilot-sdk` (extra) | `auto` sentinel; session resume; usage from events |
| `m365-copilot` | httpx2 + interactive Entra | interactive-auth-only — degraded headless story, documented |
| `llama-cpp` | supervised `llama-server`, openai-compat dialect | see §12; loopback only |

## 9. Structured output

1. Request carries `SchemaSpec` (JSON-schema dict, or anything with `model_json_schema()`).
2. Core selects the mechanism from capabilities; adapter projects the schema to its wire form.
3. Response text is parsed and validated against the **original** schema with `jsonschema`.
4. On violation: if `repair=Repair(max_attempts=N)` was set, the core re-prompts with the
   validation errors appended (Frisket's `_repair_prompt`, generalized), within the same
   routing budget; otherwise raises `SchemaViolationError` carrying the raw text and errors.
5. `Generation.structured` is the parsed value; `structured_mechanism` and `repair_attempts`
   record how it was obtained.

## 10. Error hierarchy

Shallow tree, rich fields. Every error carries: `provider`, `phase`
(`configure|discover|generate|stream|validate|cleanup`), `retryable: bool`,
`retry_after_s: float | None`, `http_status: int | None`, `detail: str` (bounded, redacted),
`hint: str | None` (mote's UX split — actionable next step).

```
AnyInferError
├── ConfigError                  # bad config/target/catalog
├── CredentialError              # resolution failed (ref missing, keyring locked…)
├── ProviderError                # base for anything a provider surfaced
│   ├── AuthError
│   ├── RateLimitError           # retryable=True, retry_after from headers
│   ├── ModelNotFoundError
│   ├── ContextLengthError       # prompt too large for resolved model
│   ├── TransportError           # connect/timeout/TLS; retryable per classification
│   ├── StreamProtocolError      # malformed SSE/NDJSON mid-stream
│   └── ProviderUnavailableError # health probe failed / server down
├── SchemaViolationError         # validation failed after repair budget; carries raw text
├── ToolLoopError                # tool dispatch failure / loop bound exceeded
├── AllTargetsFailedError        # router exhausted; .attempts = full trail
└── LocalRuntimeError            # llama-server lifecycle, runtime/model integrity
```

Retryable status classification follows ModelFit: `{408, 409, 425, 429} ∪ ≥500`.
All `detail` strings pass the redaction registry before construction.

## 11. Routing

```python
@dataclass(frozen=True, slots=True)
class Retry:
    max_attempts: int = 2
    backoff_base_s: float = 0.5          # exponential, honors retry_after when larger
    retry_on: Callable[[ProviderError], bool] | None = None   # default: e.retryable

@dataclass(frozen=True, slots=True)
class Route:
    targets: tuple[Target, ...]          # ordered fallback chain
    retry: Retry = Retry()
    health_gate: bool = True             # skip targets whose health() failed recently
    on_fallback: Literal["same_request", "revalidate_capabilities"] = "same_request"
```

Semantics: for each target in order → health gate → resolve → attempt with per-target retry
policy → on non-retryable failure or retry exhaustion, emit `AttemptFailed`, move to next
target. All targets exhausted → `AllTargetsFailedError` with the complete attempt trail.
Health results cache with a short TTL; a skipped target records `skipped_unhealthy`.

Deferred by decision: load balancing, cost/latency-adaptive selection. `Route` is deliberately
a policy object so richer policies can be added without new client methods.

## 12. Local subsystem

All four components are v1 core (interview decision), generalized from the best existing
implementation of each:

- **`local.hardware`** — one detector to replace three: RAM (`GlobalMemoryStatusEx`/`sysconf`),
  GPU (nvidia-smi, ROCm, Vulkan, lspci, CIM, system_profiler — mote has the widest coverage),
  CPU topology, unified-memory detection. Disk-cached, keyed by probe-executable signatures
  (mote), invalidation env vars. **Advisory-only semantics** (ModelFit's philosophy): detection
  proposes; callers/apps decide.
- **`local.backends`** — which llama-server runtime variants are available/installed:
  CPU/CUDA/ROCm/Vulkan/Metal, ranked (Frisket's `{"cuda":30,"metal":25,"vulkan":20,"cpu":10}`),
  manifest-validated, pinned llama.cpp build, architecture and path-containment checks.
- **`local.tuning`** — Frisket's tuner generalized: posture (`conservative|balanced|aggressive`)
  × hardware profile × per-model KV-bytes/token table → `ServerPlan` (threads, batch/ubatch,
  gpu layers, KV cache type, largest context that fits the memory budget).
- **`local.gguf`** — catalog schema: SHA-256 + size + revision-pinned URL + license per
  artifact, sharded-file support; atomic downloads (`.download` → rename), file locking,
  resume, progress callbacks (merging Frisket's catalog and mote's downloader).
- **`local.server`** — llama-server supervisor: spawn, readiness poll, crash detection,
  graceful shutdown; **binds 127.0.0.1 with ephemeral port only**; non-loopback requires an
  explicit `allow_remote_exposure=True`.
- **`local.recommend`** — hardware→tier: mote's `get_recommended_model_key` generalized and
  driven by the alias catalog rather than hardcoded thresholds.
- **`local.runtimes`** (D30) — the acquisition side of `backends`: a pinned per-platform,
  per-backend artifact table (`runtimes.json`, written from the upstream release API by
  `scripts/pin_runtimes.py`), `runtime.json` manifest validation, and `install_runtime()`.
  CUDA is an explicit opt-in gated on driver major and compute capability; the default path
  installs Metal on Apple Silicon, Vulkan on any other GPU machine, CPU otherwise.
- **`local.fit`** (D30) — catalog entry × hardware → `gpu | cpu | tight | no | unknown`, with
  reasons. Consumes catalog entries structurally, the same protocol trick `recommend` uses,
  so the `catalog → local` dependency stays one-directional.
- **`local.variants`** (D31) — which quantization to acquire: the highest-quality rung whose
  weights *and* KV cache fit, with per-engine gates (vLLM kernels on compute capability) and
  a stated quality floor at Q4_K_M.
- **`local.sources`** (D31) — `SourceRef` → `ResolvedArtifact` behind a resolver protocol:
  `huggingface` (spoken directly, ADR-007; `contracts/huggingface.md`), `url`, `local`.
- **`local.acquire` / `local.store`** (D31) — plan → preflight → concurrent fetch → verify →
  place → register, and a revision-scoped store with a rebuildable index. Model acquisition
  lives here, never in an adapter: fetching forty gigabytes is not protocol translation.

The `llama-cpp` adapter composes these: resolve GGUF via catalog → locate in the store (or
acquire) → plan → supervise server → speak openai-compat over loopback. In-process
`llama-cpp-python` is explicitly **not** supported (ADR-004); mote accepts the subprocess
model.

## 13. Alias catalog

Schema (evolved from mote's `models.lock.json`):

```jsonc
{
  "format_version": 1,
  "default_alias": "medium",
  "aliases": {
    "medium": {
      "description": "Balanced option for everyday analysis",
      "targets": {
        "llama-cpp":  { "gguf": "qwen3-8b-q4-k-m", "context_window": 8192 },
        "ollama":     { "model": "qwen3:8b" },
        "copilot":    { "model": "gpt-4.1" },
        "anthropic":  { "model": "claude-haiku-4-5" }
      }
    }
  },
  "gguf_artifacts": { "qwen3-8b-q4-k-m": { "url": "…", "sha256": "…", "size_bytes": 0,
                       "license": "Apache-2.0", "files": [] } }
}
```

Since D30 the bundle is **two documents with different cadences**, overlaid at load:
`default.json` is the hand-edited alias policy above, and `models.json` is the
machine-maintained logical model table — one row per browsable local model, with a
quantization ladder (`variants[]`), per-channel sources (pinned GGUF artifacts and an Ollama
tag with its manifest digest), memory estimates, a closed `best_at` vocabulary, and a real
`last_verified` date. Artifacts derived from GGUF variants are registered into the same id
space the alias targets use, so the two shapes reference one body of data.
`Catalog.with_alias_target()` bridges them: a user's catalog pick becomes a tier target
through the existing overlay machinery, with no resolver changes.

- AnyInfer **bundles a maintained default catalog** (interview decision — accepted curation
  burden, tracked as risk R6); apps may replace or overlay it (merge: app entries win).
- Resolution: `alias × provider → concrete target`; unresolvable combinations are
  `ConfigError`s at resolve time, not silent fallbacks.
- `local.recommend` picks a default alias from hardware; apps surface it as the novice default.

## 14. Telemetry and events

- **Contract:** typed lifecycle events → registered in-process observers. Nothing is written
  anywhere by default (mote's zero-telemetry policy holds).
- Event set: `RequestStarted`, `TargetResolved`, `AttemptStarted`, `FirstToken`,
  `AttemptCompleted` (usage/timing), `RetryScheduled`, `FallbackTriggered`, `RepairAttempted`,
  `RequestCompleted`, `RequestFailed`, `ParameterDropped`, `UsageEstimated`,
  `ContextReduced`, `ServerLifecycle` (local), `DownloadProgress`.
- **Privacy levels:** events are payload-free by default (ids, counts, timings, model names).
  An observer must be registered with `payloads=True` to receive prompt/response text
  (Frisket's `hide_report_data`, inverted into an opt-in).
- **Redaction:** every secret resolved through `anyinfer.credentials` is auto-registered; all
  `detail` strings, event fields, and log lines pass redaction before emission.
- **OTel bridge** (`anyinfer.otel`): maps events to spans/metrics; imports
  `opentelemetry-api` lazily and only when enabled; recommended packaging is the `[otel]`
  extra. Frisket's JSONL-trail sink and ModelFit's evidence writer become observers in *their*
  codebases (or a shared `anyinfer.sinks` contrib module later).
- **Cost:** `Usage.cost_usd` computed from capability-layer pricing when provenance is
  `catalog` or `discovered` (OpenRouter reports pricing); `None` otherwise — never guessed.

## 15. Configuration and credentials

- **Core is programmatic:** `AsyncClient(providers=[…], catalog=…, route_defaults=…)` from
  plain typed objects. No file I/O in the core path.
- **`anyinfer.config` (optional layer):** canonical JSON schema versioned with
  `format_version`; `load()/save()/validate()`; precedence **explicit args > env vars >
  config file > defaults** (Frisket's documented ladder, generalized); ModelFit's hygiene
  rules (size caps, unknown-credential-shaped-field rejection); per-provider sections driven
  by `ProviderSetupSpec` so a config wizard/UI is generic across engines — including which
  fields to *ask* for, since the spec marks the ones it already has a standard value for
  (`SetupField.advanced` / `default_value`) rather than presenting all fields as equals and
  leaving each consuming app to sort them out; `HostShorthand` expansion
  (`myserver` → `http://myserver:11434`).
- **Credentials:** config/API accept `"sk-literal"`, `"env://OPENAI_API_KEY"`, or
  `"credential://system/openai"`. `CredentialResolver` protocol; shipped resolvers: literal,
  env, keyring (`[keyring]` extra, Frisket's model). Apps register custom resolvers. Every
  resolved secret feeds the redaction registry. Env-var naming: `ANYINFER_*`.

## 16. Sync and async surfaces

- **Async core.** `AsyncClient` is the real implementation.
- **Sync facade.** `Client` owns a dedicated background event-loop thread (not
  `asyncio.run()` per call — that would break streaming iterators, connection pooling, and
  supervised-server lifetimes). Sync `stream()` returns a thread-safe blocking iterator fed
  from the loop. `Client` is safe to call from multiple threads; one loop, serialized I/O
  scheduling, concurrent requests still overlap on the loop.
- Frisket's loop-churn workaround (`client_lock_for_loop`) becomes unnecessary: the facade
  owns its loop; async consumers use `AsyncClient` bound to their loop as usual.

## 17. Example public API

```python
import anyinfer as ai

# --- one-liner, alias target, sync ---
client = ai.Client()                       # default registry, bundled catalog
result = client.generate("Summarize:\n" + text, target="medium")
print(result.text, result.usage.output_tokens, result.timing.first_token_ms)

# --- streaming (mote) ---
with client.stream(messages, target="ollama:qwen3:8b") as stream:
    for ev in stream:
        match ev:
            case ai.TextDelta(text=t): print(t, end="", flush=True)
    final = stream.result                    # Generation

# --- structured contract with repair (Frisket) ---
result = client.generate(
    messages, target="copilot:auto",
    schema=ANSWER_SCHEMA, repair=ai.Repair(max_attempts=1),
)
answer = result.structured                   # validated against ANSWER_SCHEMA

# --- fallback chain + retries (router) ---
route = ai.Route(
    targets=("anthropic:claude-sonnet-5", "azure-foundry:gpt-5-mini", "ollama:qwen3:8b"),
    retry=ai.Retry(max_attempts=3),
)
result = client.generate(messages, route=route)
for a in result.attempts: print(a.target, a.outcome)

# --- instrumented benchmarking (ModelFit) ---
async with ai.AsyncClient(observers=[evidence_writer]) as ac:
    async with ac.stream(messages, target=t) as s:
        async for ev in s:
            if isinstance(ev, ai.TimingMark) and ev.name == "first_token":
                note_ttft(ev.at_ms)
        record(s.result.usage, s.result.timing)

# --- discovery & capabilities ---
for m in client.models("openrouter"):
    print(m.id, m.capabilities.context_window, m.capabilities.pricing)

# --- local inference, hardware-aware ---
hw = ai.local.detect()                      # cached HardwareProfile
alias = ai.local.recommend_alias(hw)        # e.g. "large" on a 24 GB GPU
result = client.generate(prompt, target=alias)   # llama-cpp: download → tune → serve → answer

# --- tool loop (late v1) ---
@ai.tool
def read_file(path: str) -> str:
    """Read a project file."""
    ...
result = client.run_tools(messages, tools=[read_file],
                          target="anthropic:claude-sonnet-5", max_rounds=8)

# --- provider escape hatch ---
result = client.generate(messages, target="ollama:qwen3:8b",
                         provider_options={"ollama": {"keep_alive": "10m"}})
```

## 18. Package layout

```
src/anyinfer/
  __init__.py            # curated public surface
  types/                 # messages.py requests.py results.py events.py capabilities.py
  errors.py
  _client/               # async_client.py sync_client.py stream.py tools.py
  registry.py
  routing/               # policy.py health.py attempts.py
  schema/                # spec.py mechanism.py project.py validate.py repair.py
  events/                # observers.py dispatch.py redaction.py privacy.py
  otel.py
  credentials/           # resolver.py env.py literal.py keyring_store.py
  config/                # shared, versioned JSON configuration
  catalog/               # model.py resolve.py default.json models.json
  capabilities/          # assemble.py probes.py pricing.py estimate.py budget.py gating.py
  local/                 # hardware.py backends.py runtimes.py runtimes.json tuning.py
                         # fit.py variants.py artifacts.py downloads.py
                         # acquire.py store.py sources/ server.py recommend.py
  providers/             # base.py sse.py openai_compat.py openai.py anthropic.py
                         # ollama.py openrouter.py azure_foundry.py copilot.py
                         # m365_copilot.py llama_cpp.py
  context/               # (D28) corpus reduction: documents.py rank.py structure.py
                         # envelope.py select.py tiers.py pack.py distill.py
  testing/               # conformance.py fakes.py cassettes.py
  cli.py                 # run, verify, doctor, providers, models, runtime, sidecar entry points
  serve/                 # openai_codec.py app.py __main__.py — see §22, ADR-009

tests/                   # unit + conformance runs (cassette & fake modes)
contracts/               # per-provider protocol snapshots + DRIFT-CHECK.md (§24)
docs/                    # provider guides, published site sources (§25)
```

**Packaging:** mandatory deps `httpx2`, `jsonschema`. Extras: `[copilot]` github-copilot-sdk ·
`[azure]` azure-identity(+broker) · `[keyring]` keyring · `[otel]` opentelemetry-api ·
`[local]` download/tuning helpers (llama-server binaries fetched at runtime, never pip deps) ·
`[serve]` ASGI server deps for the OpenAI-compatible frontend (§22) ·
`[all]`. Missing-extra errors raise `ConfigError` with an install hint.

## 19. MVP scope and roadmap

Tiered milestones inside v1. The original scope was nine providers plus the tool loop;
provider breadth expanded through dedicated adapters and compatibility presets.

- **M0 — skeleton (the contract):** types, errors, events/redaction, registry, schema
  subsystem, router (retry+fallback+health), `AsyncClient` + sync facade, `openai-compat`
  adapter, conformance harness + fake SSE server + cassette tooling. *Tool types exist in the
  message/event model from day one; no loop yet.*
- **M1 — core four + pilot migration:** `ollama`, `copilot`, `llama-cpp` (with the full local
  subsystem: hardware, backends, tuning, gguf, server, recommend), alias catalog + bundled
  default. **Migrate mote-cli** — it exercises aliases, local inference, streaming, and the
  sync facade at once.
- **M2 — hosted breadth + Frisket:** `openai` (Responses), `anthropic`, `azure-foundry`;
  repair loop hardening; OTel bridge; **migrate Frisket** (schema contract, keyring
  credentials, telemetry observers as its JSONL trail).
- **M3 — long tail + ModelFit:** `openrouter`, `m365-copilot`; active capability probes;
  **migrate ModelFit** (evidence pipeline as observer; its 7 adapters deleted).
- **M4 — tool loop + stabilization:** `run_tools` executor, conformance matrix complete for
  the dedicated adapters, API freeze review, docs, publish publicly.
- **M5 — sidecar + binaries:** delivered in the 0.1 beta: `anyinfer.serve`
  OpenAI-compatible loopback service (§22), shared versioned configuration, the CLI process
  boundary, and standalone `anyinfer-serve` bundles for macOS/Linux/Windows (ADR-010) with a
  native CI build matrix and checksums. Signing/notarization remains external release
  infrastructure to resolve before 1.0.

## 20. Major unresolved decisions

1. **Token estimation / prompt budgeting.** *Resolved 2026-08-07 as D25.* Pluggable
   `TokenEstimator` protocol with a dependency-free byte-heuristic default
   (`capabilities/estimate.py`); every estimate carries a conservative-high planning figure
   *and* a defensible floor. The provider-neutral budget calculator
   (`capabilities/budget.py`) computes input allowance = context window − derived output
   reserve − clamped 5% headroom, tri-state per ADR-005: an unknown window yields an unknown
   budget, never a guessed default. Pre-dispatch gating (`capabilities/gating.py`, L6) raises
   `ContextLengthError` only when the estimate's *floor* exceeds a trusted-provenance window,
   feeding `Route.context_window_targets`; `default`-provenance windows never gate. Exposed as
   `Client.budget()` / `AsyncClient.budget()` for app preflight (Frisket's consumer). Exact
   tokenizers (tiktoken, llama-server `/tokenize`) plug in via the protocol; none ship.
2. **Session/conversation reuse** (mote's token-cache: Copilot session resume, Ollama
   keep_alive). Descriptor flag exists (`supports_sessions`); the session API itself is
   unspecified. Needed by M1 (mote) — design during M0.
3. **Cancellation semantics** across the sync facade (KeyboardInterrupt → loop-thread task
   cancellation → httpx2 stream close → llama-server survival). Must be specified in M0.
4. **Default catalog contents and update cadence** — which models, who bumps them, does a
   catalog update constitute a library release? (Risk R6.)
5. **M365 Copilot headless story** — interactive-only auth may make it conformance-exempt for
   CI; degraded-mode contract TBD in M3.
6. ~~**Frisket's Ollama GPU-spill warning + observed-VRAM checks** — capability layer or
   Ollama-adapter warnings?~~ *Resolved 2026-08-08 as D36:* adapter-reported runtime
   diagnostics, declared on the descriptor and surfaced on `Generation.warnings` plus a
   `ProviderDiagnostic` event.

## 21. Risks and complexity traps

- **R1 — sync facade correctness** (streaming iterators, cancellation, thread affinity).
  Mitigate: specify in M0, test under KeyboardInterrupt and thread stress from day one.
- **R2 — multi-provider conformance drift**, now across seventeen dedicated adapters plus a
  preset registry. Mitigate: cassette CI + nightly live runs; the matrix doc is the source
  of truth for "native vs emulated vs unsupported", and presets are covered by
  representatives per quirk axis rather than one row each.
- **R3 — llama-server supervision on Windows** (process trees, GPU runtime DLLs, antivirus
  interference). Frisket has prior art; port its supervisor patterns, not fresh code.
- **R4 — structured-output mechanism divergence** (grammar limits, schema projection edge
  cases). Mitigate: original-schema client validation is always authoritative; projections
  are provider-quirk code with dedicated conformance cases.
- **R5 — tool loop with zero current consumers** (decision: in v1 anyway). Mitigate: last
  milestone, types proven earlier, keep the executor minimal (no parallel calls in v1).
- **R8 — retrieval-quality expectations creep** — a lexical ranker invites "why didn't it
  find X" reports and pressure toward embeddings/rerankers the slim core forbids.
  Mitigate: docs state the ranking model plainly (ASCII-alphanumeric lexical matching with
  path boosting); the ranker sits behind a protocol so exact or semantic implementations
  can be supplied by apps; open question 8 owns the embeddings decision. The structural-
  extract language table is a staleness surface like the catalog (R6) — languages are added
  by one suffix-map entry plus one extract branch, covered by tests.
- **R6 — bundled catalog staleness** (decision: bundle anyway). Mitigate: catalog is data
  with its own `format_version`; overlay mechanism lets apps pin; consider a separate
  release cadence.
- **R7 — Copilot `auto` sentinel** breaking "model is a known string" assumptions —
  conjunction-of-capabilities rule (§7) must be enforced in the capability assembler, not
  ad hoc per caller.

## 22. Serve frontend: OpenAI-compatible loopback federation

**Requirement (confirmed 2026-08-05):** as an optional batteries-included module, AnyInfer
must be able to "snap on" a frontend — an OpenAI-compatible HTTP service on loopback that
federates incoming requests to **any** backend the library abstracts, local or hosted. Any
tool that can talk to an OpenAI base URL (IDE plugins, existing apps, third-party clients)
thereby gains access to every provider, alias, route, and supervised local model AnyInfer
manages.

**Why this is cheap here and expensive elsewhere:** ADR-001 made the internal primitive a
normalized event stream, *not* the OpenAI wire format. Adapters already project provider
dialects → events. The serve frontend is simply the **inverse projection at the edge**:

```
OpenAI client ──HTTP──▶ anyinfer.serve ──▶ GenerationRequest ──▶ router ──▶ any adapter
                            ▲                                                   │
                chat.completion.chunk SSE ◀── StreamEvent stream ◀──────────────┘
```

No routing, validation, telemetry, credential, or local-inference code is duplicated — the
frontend is a wire codec plus an ASGI app around an `AsyncClient`.

**Surface (initial):**
- `POST /v1/chat/completions` — streaming and non-streaming. The request's `model` field is
  parsed as a `Target`: `"medium"` (alias), `"anthropic:claude-sonnet-5"`,
  `"ollama:qwen3:8b"`, or a named route configured server-side. Federation is therefore free.
- `GET /v1/models` — enumerates catalog aliases, named routes, and (optionally) concrete
  `provider:model` targets, with capability metadata in OpenAI's `model` object shape.
- Mappings: `messages`/`tools`/`tool_choice`/`response_format.json_schema` →
  `GenerationRequest` fields; `temperature`/`top_p`/`max_tokens`/`stop` → `Sampling`;
  unrecognized extra-body fields → `provider_options` passthrough (namespaced), so OpenAI
  clients keep the escape hatch. Usage blocks and `finish_reason` come from `Generation`.
- Out of scope for the frontend: endpoints AnyInfer itself doesn't model (embeddings, images,
  audio, files) return 404 with a clear error body.

**Invariants enforced from M0 so this stays a thin projection (conformance-tested):**
1. `GenerationRequest` remains a **superset** of the OpenAI chat-completions request surface
   — any lossy gap is a design bug, caught by a round-trip test (OpenAI wire → request →
   OpenAI wire).
2. The event stream remains **sufficient to reconstruct** `chat.completion.chunk` sequences:
   ordered text deltas, indexed tool-call argument fragments, finish reason, terminal usage.
3. `Target` grammar stays representable as an OpenAI `model` string (no characters/structure
   a `model` field can't carry).
4. `AsyncClient` supports many concurrent independent streams (it must anyway; the server
   makes it load-bearing).

**Security posture (inherits the D20 security decisions: redaction §14, loopback-only §12,
payload privacy §14, config hygiene §15):** binds `127.0.0.1` on an explicit or ephemeral
port; non-loopback binding requires `allow_remote_exposure=True` *and* a configured bearer
token; loopback token optional. Standard redaction applies to logs; payload retention off by
default. The frontend authenticates *clients to itself*; backend credentials never transit.

**Binary distribution (requirement, 2026-08-05):** the sidecar also ships as a
**standalone per-platform executable** — `anyinfer-serve` for macOS (arm64 + x86_64),
Linux (x86_64, aarch64), and Windows (x86_64) — so that "run a local OpenAI-compatible
federation service" requires no Python on the host. This is the preferred integration path
for consumers who don't want the SDK in-process. Build tooling and trade-offs: ADR-010
(PyInstaller onedir recommended; cheaper alternatives evaluated). The binary bundles the
Python runtime, core, all pure-httpx2 adapters, and the local subsystem; llama-server
runtimes and GGUF models remain runtime-fetched, keeping the artifact small and the GPU
matrix out of the build. Configuration comes from the canonical config layer (§15) — the
binary is where that layer stops being optional. `anyinfer serve` and the standalone binary
use the same CLI dispatch, validated configuration, and core client.

**Status:** implemented for the 0.1 beta as a `[serve]` extra (ASGI app plus uvicorn,
embeddable in a host app's own ASGI stack) and as the standalone bundles above. Native
bundles are smoke-tested and checksummed; signing and notarization remain follow-up work.

## 23. Architecture Decision Records

### ADR-001 — Event-stream generation primitive, not an OpenAI clone
**Decision.** The core abstraction is `GenerationRequest → stream of typed events`, with the
non-streaming result as the drained stream's terminal event. **Why.** The three consumer
shapes (validated single answer, instrumented benchmark, interactive stream) are all natural
projections of one event stream; an OpenAI-shaped API would privilege one dialect and force
TTFT measurement, usage capture, and repair to live outside the abstraction. **Consequences.**
Buffered providers emit synthetic single-delta streams; adapters stay one-entry-point;
message/chat convenience layers sit on top, not underneath.

### ADR-002 — Async core, sync facade over a background loop thread
**Decision.** One async implementation; `Client` wraps it with a dedicated event-loop thread.
**Why.** Frisket/ModelFit are async-native; maintaining dual implementations ≈ doubles test
surface; per-call `asyncio.run()` breaks streaming and pooling. **Consequences.** mote
migrates to the facade; cancellation semantics must be explicitly designed (open decision 3);
Frisket's per-loop lock hack becomes obsolete.

### ADR-003 — Adapters translate; the core orchestrates
**Decision.** Adapters expose exactly `list_models / health / generate(→events) / aclose` and
never retry, validate, or measure. Retry, fallback, schema validation/repair, timing, usage
normalization, telemetry, redaction live in the core. **Why.** Nine thin adapters are
testable by one conformance suite; today's projects each smear orchestration into provider
code (Frisket's 944-line runner) and pay for it three times. **Consequences.** `WireRequest`
must carry everything pre-resolved; provider quirks surface as declarative descriptor data or
small projection hooks, not control flow.

### ADR-004 — llama.cpp via supervised llama-server only
**Decision.** No in-process `llama-cpp-python`; the library supervises `llama-server`
(loopback-only) and speaks the OpenAI-compatible dialect. External servers are just
openai-compat targets. **Why.** One wire protocol for all engines, crash isolation, no
GPU-wheel/DLL build matrix in the dependency tree; Frisket's tuner and supervisor already
prove the model. **Consequences.** mote loses in-process embedding (accepted); subprocess
lifecycle on Windows is a named risk (R3); server startup latency is mitigated by keep-alive
supervision.

### ADR-005 — Layered, provenance-tagged capability metadata
**Decision.** `ModelCapabilities` assembled from static catalog → live discovery → optional
probes; every field carries provenance; delegating models (`auto`) get
conjunction-of-candidates bounds. **Why.** Providers omit or misreport; consumers (routing,
schema mechanism selection, context budgeting, pricing) need to know *how much to trust* a
number. **Consequences.** A `Sourced[T]` wrapper appears in public types; probe cost is
opt-in; the static layer creates catalog-maintenance work.
**Amended by D27 (2026-08-07):** a fifth provenance, `override` (rank above `probed`), for
values the integrating application set deliberately — a user's explicit correction must
never lose to data the library merely collected. The static layer now includes the bundled
per-provider pricing table (`capabilities/pricing.json`), keyed by provider *and* model
because engines price the same model differently; its maintenance burden is carried by the
weekly `pricing-refresh` workflow.

### ADR-006 — Typed in-process events; OTel as a bridge
**Decision.** The telemetry contract is typed Python events to registered observers,
payload-free by default; an optional bridge maps them to OpenTelemetry. **Why.** Frisket and
ModelFit consume telemetry in-process as structured data (JSONL trails, SQLite evidence) —
round-tripping through OTel spans is awkward; mote requires zero telemetry and zero deps;
OTel-api-only bridging gives export standardization without a mandatory SDK. **Consequences.**
Two representations to keep mapped; OTel semantics (GenAI semconv) tracked in the bridge only.
The bridge must map *every* member of the `TelemetryEvent` union — it dispatches by method
name, so an unmapped type is dropped silently; `tests/test_otel_bridge.py` fails when the
union and the bridge drift apart. Events with no `request_id` (`ContextReduced`,
`ServerLifecycle`, `DownloadProgress`) become standalone spans rather than being attached to
an unrelated in-flight request.

### ADR-007 — Slim core (`httpx2` + `jsonschema`) with per-provider extras
**Decision.** Mandatory deps are httpx2 and jsonschema; copilot-sdk, azure-identity, keyring,
otel-api are extras; llama-server binaries are runtime-fetched artifacts, never pip deps.
**Why.** mote's CLI install must stay light; all current projects already standardize on raw
httpx (of which httpx2 is the drop-in continuation — see the note below); official provider
SDKs add churn without coverage gains (ModelFit proves raw dialects work). **Consequences.**
SSE/NDJSON parsing is first-party code (shared module); missing-extra UX must be excellent
(actionable `ConfigError`s).

> **httpx → httpx2 (2026-08-07, D26).** The HTTP dependency was originally `httpx`. Upstream
> httpx stagnated (last release 2024-12) and stewardship moved to Pydantic Services under the
> `httpx2` name (same BSD-3-Clause license, original author credited, API-compatible);
> starlette ≥ 1.0 deprecates plain httpx in its test client in favor of httpx2. The core
> migrated wholesale — the full gate suite passes unchanged against httpx2 2.9.x.

### ADR-008 — Descriptor registry with entry-point discovery
**Decision.** Frozen `ProviderDescriptor`s in a collision-safe registry; declarative
`ProviderSetupSpec` per provider; third-party adapters register via the `anyinfer.providers`
entry-point group. **Why.** ModelFit's registry already eliminated per-engine branches across
CLI *and* GUI; entry points let future engines (and experiments) plug in without core
releases. **Consequences.** Descriptor schema becomes a public compatibility surface;
lazy loading required so import cost stays flat.

### ADR-009 — Serve frontend is a wire codec at the edge, never a second core
**Decision.** The OpenAI-compatible loopback service (§22) is implemented purely as a
bidirectional codec (OpenAI wire ⇄ `GenerationRequest`/`StreamEvent`) wrapped in an ASGI app
around a normal `AsyncClient`. It contains no routing, retry, validation, credential, or
provider logic of its own, and the core enforces four invariants from M0: request-surface
superset of OpenAI chat completions, event-stream sufficiency to reconstruct
`chat.completion.chunk` sequences, `Target` representability in a `model` string, and
concurrent multi-stream support in `AsyncClient`. **Why.** Federation to every backend
(local or hosted) must fall out of the existing abstraction; a frontend with its own logic
would fork behavior between library callers and HTTP callers and double the conformance
surface. **Consequences.** Round-trip codec tests join the conformance suite; any future
core-type change is checked against the OpenAI projection;
the frontend inherits the loopback-only and redaction rules (D20; §12, §14, §15).

### ADR-010 — Standalone service binaries via PyInstaller (onedir)
**Decision.** `anyinfer-serve` ships as self-contained per-platform executables built with
**PyInstaller in onedir mode**: macOS arm64 (+ universal2 if Intel demand appears), Linux
x86_64/aarch64, Windows x86_64. llama-server runtimes, GGUF models, and the default catalog's
artifacts are never bundled — they stay runtime-fetched, exactly as in SDK usage.
**Why.** With no UI, the artifact is small and headless — but "no Python required on the
host" rules out the genuinely cheaper options: `zipapp`/`shiv`/`pex` produce single files
but require a system interpreter; **PyApp** (Rust launcher that fetches a Python at first
run) is attractive but reintroduces a first-run network dependency, which is wrong for a
tool whose selling point includes air-gapped local inference; **Nuitka** adds long compile
times and a C toolchain per platform for no needed speedup; **PyOxidizer** is unmaintained.
PyInstaller is also the in-house standard — Frisket (`frisket.spec`, cuda-addon packaging
boundary) and ModelFit (`packaging/`, macOS universal2 + Windows installers) already solved
its platform quirks, including the Windows AV-heuristics problem that motivates **onedir
over onefile** (onefile's self-extraction both slows startup and trips AV scanners; risk R3
adjacency). **Consequences.** A native CI build matrix performs a binary `--help` smoke test,
while the package suite covers `/v1/models` and fake-provider round trips; macOS signing +
notarization and Windows Authenticode become release-pipeline concerns (open question 9);
the canonical config layer (§15) is mandatory in binary mode since there is no Python API
surface; `shiv`-style zipapps may be offered later as a secondary artifact for hosts that
do have Python, without changing the contract.

### ADR-011 — Context reduction: apps collect, the library reduces
**Decision.** Ship an optional `anyinfer.context` subpackage implementing corpus reduction
(rank / select / represent / distill) against an explicit token budget, with collection
(filesystem traversal, approval, secret exclusion) permanently app-side. Reduction composes
the D25 estimator/budget surfaces; it never performs I/O and adds no dependencies.
**Why.** Two of the three v1 customers independently built and now maintain divergent copies
of this layer (Frisket's selector/tiers, mote's chunker); both already depend on the same
byte-heuristic arithmetic D25 centralized. Collection stays out because it is where the
security policy lives (what exists, what is safe to send) and where every app differs;
reduction is where the apps converge. **Consequences.** The §2 "No prompt templating"
non-goal is narrowed: the library owns one mechanical envelope format, apps own all prompt
language around it. `distill` spends inference calls, so it is separated by construction
(an async function taking the client by structural protocol, reporting aggregate `Usage`)
from the pure strategies. Lexical ranking sets retrieval-quality expectations the docs must
manage (risk R8); embeddings stay out until open question 8 reopens.


## 24. Provider conformance test matrix (draft)

**Contract snapshots and drift checking.** Each provider's exact wire dependencies
(endpoints, auth headers, version pins, fields sent/read, streaming framing, error shapes)
are recorded in `contracts/<provider>.md` — updated in the same change as any adapter
wire-behavior change. A semi-automated **drift check** (procedure:
`contracts/DRIFT-CHECK.md`; invocable as the Claude Code skill `check-provider-drift`
and the Copilot prompt of the same name; Codex and other agents follow the procedure via
`AGENTS.md`) audits these snapshots against live provider documentation and classifies
findings as `OK / DRIFT / DEPRECATION / NEW-CAPABILITY / UNVERIFIABLE`, proposing contract,
adapter, and matrix updates. Division of labor: the conformance suite proves *our code
matches our claims*; the drift check proves *our claims still match upstream*. Repo-level
AI instructions live in `AGENTS.md` (canonical), with `CLAUDE.md` and
`.github/copilot-instructions.md` as thin adapters.

Legend: ✅ native · Ⓔ emulated by core/adapter · ➖ unsupported (documented) · ? verify in
milestone. Every cell backed by a parametrized conformance case run in cassette, fake-server,
and (nightly, where auth permits) live modes.

> **Implementation status (2026-08-07).** Seventeen dedicated adapters are implemented
> (the original nine plus Gemini, DeepSeek, xAI, Vertex AI, Bedrock, Cohere, and LM
> Studio), alongside a preset registry of eighty-six OpenAI-compatible providers
> sharing the `openai_compat` adapter. The
> *executed* matrix — generated from a real conformance run rather than hand-maintained —
> lives at [docs/reference/conformance-matrix.md](docs/reference/conformance-matrix.md);
> regenerate it with `workspace matrix`. The table below remains the
> design-intent matrix. Cells marked `?` are design questions, several of which the
> implementation has now answered:
>
> - **anthropic json_schema** — resolved as Ⓔ: emulated with a single forced tool call,
>   which the API genuinely constrains (open question 7).
> - **copilot health / tool calls** — resolved: health probes via the SDK model listing;
>   tool calls are supported by the session API.
> - **openrouter reasoning / `auto`** — resolved: a unified `reasoning` object; per-model
>   capability comes from `supported_parameters` with `discovered` provenance.
> - **m365-copilot** — resolved as the documented degraded case: no streaming, no tools, no
>   sampling controls (declared in `ignored_parameters`), interactive auth only.
>
> Snapshots in `contracts/` are still code-survey-derived; a drift-check run is
> required before any of them can claim live verification.

| Behavior | openai-compat | openai | anthropic | ollama | openrouter | azure-foundry | copilot | m365-copilot | llama-cpp |
|---|---|---|---|---|---|---|---|---|---|
| list_models | ✅ | ✅ | ✅ (paginated) | ✅ /api/tags | ✅ +pricing | ✅ | ✅ sdk | ➖ fixed | ✅ |
| health probe | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ? | ? | ✅ supervisor |
| non-streaming generate | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| SSE/stream deltas | ✅ | ✅ | ✅ | ✅ NDJSON | ✅ | ✅ | ✅ events | ? | ✅ |
| TTFT measurable | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ? | ✅ |
| reasoning deltas | Ⓔ absent | ✅ | ✅ thinking | ✅ think | varies ? | ✅ | ? | ➖ | Ⓔ |
| json_schema mechanism | ✅ | ✅ | Ⓔ tool-based ? | ✅ format | varies/model | ✅ | ➖ | ➖ | ✅ grammar |
| grammar mechanism | ➖ | ➖ | ➖ | ✅ | ➖ | ➖ | ➖ | ➖ | ✅ |
| prompt-injected schema | Ⓔ | Ⓔ | Ⓔ | Ⓔ | Ⓔ | Ⓔ | ✅ only | ✅ only | Ⓔ |
| client-side validation | ✅ core | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| tool calls (types) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ? | ➖ | ✅ |
| usage tokens | ✅ | ✅ | ✅ +cache | ✅ +phases | ✅ | ✅ | ✅ events | ? | ✅ |
| cost computable | Ⓔ catalog | Ⓔ catalog | Ⓔ catalog | ➖ free | ✅ reported | Ⓔ | ➖ | ➖ | ➖ free |
| context window known | Ⓔ catalog | Ⓔ catalog | Ⓔ catalog | ✅ | ✅ | Ⓔ | Ⓔ conjunction | Ⓔ | ✅ config |
| retry-after honored | ✅ | ✅ | ✅ | Ⓔ | ✅ | ✅ | ? | ? | Ⓔ |
| auth: api key | ✅ | ✅ | ✅ | ✅ opt | ✅ | ✅ opt | ➖ | ➖ | ➖ |
| auth: entra | ➖ | ➖ | ➖ | ➖ | ➖ | ✅ | ➖ | ✅ interactive | ➖ |
| auth: device/cli | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ✅ gh auth | ➖ | ➖ |
| headless CI live-testable | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠ token | ➖ interactive | ✅ |
| model `auto` sentinel | ➖ | ➖ | ➖ | ➖ | ✅ router ? | ➖ | ✅ | ? | ➖ |
| sessions/keep-alive | ➖ | ? | ➖ | ✅ keep_alive | ➖ | ➖ | ✅ resume | ? | ✅ server |

## 25. SDK documentation plan

Documentation is a shipped deliverable with milestone-bound obligations, not a post-hoc
task. Target reader: a developer integrating AnyInfer into their application who has never
seen this repo.

**Tooling.** mkdocs-material + mkdocstrings (API reference generated from typed docstrings);
versioned docs (mike) so published SDK versions keep matching docs; docs build is a CI gate.

**Quality gates (enforced from M0):**
- Every public symbol has a docstring; the reference build fails on missing/undocumented
  public API (interrogate or equivalent).
- Every code sample in guides and the cookbook is executed in CI against the fake-provider
  servers from `anyinfer.testing` — examples cannot rot.
- Each provider page embeds its live row of the conformance matrix (§24), generated from the
  conformance suite's results, so docs never overpromise a provider's abilities.

**Site structure:**

1. **Quickstart** — install to first `generate()` in under five minutes; the three-line
   sync example, then streaming, then an alias target.
2. **Installation matrix** — extras (`[copilot]`, `[azure]`, `[keyring]`, `[otel]`,
   `[local]`, `[serve]`, `[all]`), Python/OS support, and the serve-binary download table
   for users who want no Python at all.
3. **Choosing an integration path** — decision page: embed the SDK (sync or async) vs run
   the `anyinfer-serve` binary and point existing OpenAI clients at it; latency, deployment,
   and capability trade-offs of each.
4. **Concepts** — one page each: targets & aliases; routes/retries/fallback; the event
   stream; structured-output contract & repair; capabilities & provenance; credentials;
   the local subsystem; observers & telemetry privacy.
5. **How-to guides** — task-oriented: stream to a terminal; enforce a JSON schema with
   repair; add a fallback chain; subscribe an observer / bridge to OTel; store keys in the
   OS keyring; point at a self-hosted OpenAI-compatible server; run a local model end-to-end
   (detect hardware → recommend tier → download GGUF → serve → generate); write and register
   a custom provider adapter (descriptor, entry point, passing the conformance suite);
   run the tool loop; embed `anyinfer.serve` in an existing ASGI app.
6. **Provider guides** — one page per adapter: auth setup (with each provider's quirks —
   Copilot CLI login, Entra flows, M365 interactive-only), supported features, known
   limitations, provider-specific `provider_options`.
7. **Cookbook** — complete runnable programs mirroring the three proven consumption shapes:
   an interactive streaming CLI (mote shape), a schema-contract document filler (Frisket
   shape), an instrumented benchmark harness (ModelFit shape) — plus a serve-binary
   federation setup with an off-the-shelf OpenAI client.
8. **API reference** — generated; grouped by module per §4.
9. **Error catalog** — every exception class: when it's raised, its fields, whether it
   retries, and the `hint` text a user will see.
10. **Serve binary manual** — download/verify, config file reference (§15 canonical layer),
    ports and tokens, running as a service (launchd/systemd/Windows service), upgrade path.
11. **Migration guides** — written *while* migrating Frisket/ModelFit/mote in M1–M3; they
    double as real-world integration tutorials and stay in the published docs.

**Milestone obligations:** M0 — site skeleton, quickstart, concepts for whatever exists,
reference generation wired into CI. M1–M3 — provider page lands in the same PR as each
adapter; migration guide per app migration. M4 — cookbook complete, error catalog complete,
site published publicly with the API freeze. M5 — integration-path decision page and serve
binary manual.


## 26. Context reduction subsystem (`anyinfer.context`)

*Added by D28 (2026-08-07); see plans/TOKEN_REDUCTION_ALGS.md for algorithms and port
provenance.*

An optional, dependency-free subpackage that answers one question: **given documents the
app has already collected and approved, what should actually be sent to fit a token
budget?** The boundary is strict — apps collect (filesystem, approval, secrets policy),
the library reduces (rank, select, represent). The subsystem never performs I/O, never
reads paths off disk, and adds no dependencies.

Inputs are `ContextDocument` values (path, content, sha256, pinned flag, optional language
and structural extract) and an explicit token budget. The budget is the app's number,
normally `ContextBudget.remaining_tokens` from a preflight `client.budget()` call; when the
window is unknown the budget is unknown, and the caller must choose — the library never
invents a window (the same tri-state rule as §7 and cost).

Strategies: `whole` (send everything when it fits), `ranked` (lexical relevance-ranked
whole documents, greedy skip-and-continue), `tiered` (full corpus coverage at decreasing
fidelity: module rollup → structural extracts → verbatim files, with optional app-supplied
module digests), `packed` (chunk-level rank-and-pack for sub-document granularity), and
`distill` (map/reduce through the client itself — the only strategy that spends inference
calls, async-first). `auto` dispatches `whole` when the corpus fits, else `tiered`.

Reduction is emulation of a larger context window, and emulation announces itself: every
reduction returns full metadata plus a content-free summary, and emits a `ContextReduced`
telemetry event when an observer is supplied. Rendering is deterministic and path-ordered
by default so repeated turns over the same corpus keep a stable prompt prefix (provider
prompt caches, llama-server slot reuse).

Ranking is lexical (a BM25-style scorer ported from Frisket, with path-match boosting and
anchor-file bonuses). Embeddings-based ranking remains out of scope (a §2 non-goal; open
question 8) — the ranker protocol accepts a replacement when that changes.
