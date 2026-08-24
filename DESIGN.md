# AnyInfer — Design Foundation

> Status: v0.1.
> Companions: [AGENTS.md](AGENTS.md) — repository automation rules;
> [contracts/](contracts/) — per-provider wire-protocol snapshots.

---

## 1. Product definition

**AnyInfer** is an application-owned hybrid inference runtime for Python. It provides one
normalized inference contract across hosted AI providers, routing hubs, existing local
services, and a supervised `llama.cpp` process owned by the application.

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
11. **Stateless embedding and reranking as first-class operations.** `EmbeddingRequest →
    EmbeddingResult` and `RerankRequest → RerankResult` receive the same batteries as
    generation — typed async APIs and a sync facade, target resolution and routing,
    retries and health gating, capability provenance, usage/pricing/telemetry, and fake/
    cassette/live conformance — without becoming a vector database or a retrieval
    framework (see §28).

### Non-goals (v1)
- **No daemon in the core.** The core is a library; nothing listens on a socket by default.
  The implemented **OpenAI-compatible loopback serve frontend** (`anyinfer.serve`, `[serve]`
  extra) is an optional frontend over that library — see §22 and ADR-009. Its wire-codec
  boundary and the invariants that keep it a thin projection are enforced in tests.
- **Not an agent framework.** A tool-execution loop is provided (late in v1), but no planning,
  memory, or multi-agent constructs. *Clarified:*
  `anyinfer.context.distill` is a bounded, deterministic map/reduce fan-out — fixed
  two-phase shape, no planning — permitted on the same grounds as the schema-repair
  loop's bounded extra calls. *Clarified again:* `anyinfer.context.compact_history` is a
  pure `Sequence[Message] → HistoryCompaction` function that elides and drops by fixed
  rules. It is *not* conversation memory: nothing is stored, summarized, or recalled, no
  call is issued, and the client never applies it — the app decides whether to send the
  result. It is the same class of mechanical size arithmetic as the token estimator, and
  it lives here because every consumer was otherwise rebuilding it, tool-call pairing bugs
  and all. *Amended (§27):* the client may apply it on the request path when a
  `HistoryPolicy` is configured. That is opt-in, emits a typed event, and is the second
  half of an overflow answer the router already owned — not memory, and not a planner.
  *Amended again:* an opt-in arena is a fixed, bounded fan-out followed by one terminal
  selection. Its call ceiling is known before dispatch; candidates never see or prune one
  another, nothing is stored, and outcomes never influence a later route. Selecting which
  branch to continue would be planning and remains out of scope.
- **No load balancing or cost/latency-adaptive routing** (deferred; the router's policy
  interface must not preclude them). *Clarified:* `anyinfer.routing.limits` paces **this
  process's own requests** to a provider it is already going to call — a semaphore and a
  token bucket, seeded from the rate-limit headers the provider sends back. It shares no
  state with any other process, enforces no quota the provider did not state, and never
  chooses a *different* target because one is busy. That last clause is the boundary: the
  moment pacing informs target selection it has become load balancing, and that is a
  reversal to argue, not a config option. Defaults are inert — an unconfigured client
  behaves exactly as it did before pacing existed.
  *Clarified again:* reporting how one request would degrade, fit, and cost across targets
  is not target selection. `compare()` returns those facts in caller order and the router
  never consumes them. A built-in ranking or “pick the best” helper would cross the same
  boundary as pacing-informed routing and is a reversal to argue. Non-OpenAI operations
  exposed by the sidecar live under `/v1/anyinfer/*`; they remain projections over public
  client APIs, never a second policy layer.
- **No image generation, audio output, or fine-tuning APIs.** Generation still produces text
  and tool calls only. Multimodal *inputs* — images, documents, and audio content attached to
  a generation request — are implemented as typed message parts; they do not introduce a
  second inference primitive or any multimodal output API. *Amended (§28):* embeddings and
  reranking are no longer excluded — they are stateless inference operations distinct from
  generation, scoped narrowly to text in the first release. AnyInfer remains an inference
  layer, never a vector database, corpus store, or retrieval framework: it produces vectors
  and relevance rankings and does not decide what an application indexes, persists,
  retrieves, or deletes.
- **No cross-provider continuation of interrupted streams.** A continuation would need to
  replay a provider's partial assistant output into another target without duplicating or
  revising it. The feasibility gate was rechecked on **2026-08-10** and required verified
  assistant-prefill semantics on at least three hosted providers. It failed:

  | Dialect | Evidence checked 2026-08-10 | Gate result |
  |---|---|---|
  | OpenAI | Current request references accept prior assistant history but document no append-only continuation guarantee for a partial assistant turn. | fail |
  | Anthropic | The current Messages guide says prefilling returns HTTP 400 on Claude 4.6 and later; older model-specific support is not a provider-wide continuation contract. | fail |
  | Ollama | `/api/chat` accepts assistant history and the streaming guide shows accumulated assistant output being appended for a later request, but this is a local engine, not a hosted provider. | local evidence only |

  The hosted-provider count is therefore below three. Official evidence:
  [OpenAI messages](https://platform.openai.com/docs/api-reference/messages),
  [Anthropic Messages](https://platform.claude.com/docs/en/build-with-claude/working-with-messages),
  and [Ollama streaming](https://docs.ollama.com/capabilities/streaming).
  Structured output, reasoning, and tool-call fragments are additionally unsafe continuation
  boundaries. The core therefore exposes deterministic complete top-level JSON members on a
  schema error, but does not stitch generations or label guessed continuation as salvage.
- **No prompt templating.** Applications keep their own prompt construction. *Amended:*
  the optional `anyinfer.context` subsystem renders a mechanical,
  documented context envelope (file/extract/compact/duplicate/rollup blocks) as reducer
  output — a data format like the C3/C4 injection prompts, not a template engine. Apps
  still own all surrounding prompt text, and the core client never constructs prompts on
  their behalf.
  Arena judge and synthesis calls use one versioned mechanical candidate envelope and a
  documented default instruction, on the same narrow terms as context distillation. A
  caller may replace the instruction wholesale; there is no general template facility.
- **Not an OpenAI-API clone.** OpenAI-compatible is one dialect among several, not the core
  abstraction (see ADR-001).
- **Not an organization gateway or control plane.** Virtual keys, multi-tenancy, RBAC,
  organization spend limits, distributed rate accounting, guardrails, and an admin UI belong
  in a deployment around AnyInfer, not in the library. *Clarified:* `SpendLedger` and
  `SpendPolicy` are neither. A ledger observes the client it was subscribed to and totals
  what that client already spent; a policy is a ceiling the same caller set on the same
  object, enforced before dispatch beside the context gate. Nothing is shared across
  processes, nothing is authorized, no identity is known, and no other consumer of the same
  API key is visible. It is accounting policy handed to a client — the same category as
  `Retry` — not an admin plane. A requirement for limits enforced *elsewhere*, or shared
  between workers, remains the deployment's job, unchanged.

## 3. Architecture overview

```
                                   Application
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


ContentPart = Text | ToolCall | ToolResult | ImagePart | DocumentPart | AudioPart


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


ReasoningEffort = Literal["minimal", "low", "medium", "high"]  # normalized; adapters translate


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    messages: tuple[Message, ...]
    schema: SchemaSpec | None = None  # structured-output contract
    tools: tuple[ToolSpec, ...] = ()
    sampling: Sampling = Sampling()
    reasoning: ReasoningEffort | None = None
    timeout_s: float | None = None
    max_response_bytes: int = 1 << 20  # hard cap on a single response body
    provider_options: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    # ^ escape hatch, namespaced by provider id: {"ollama": {"keep_alive": "10m"}}
    #   Never consulted by the core; passed verbatim to the matching adapter only.
```

**Targets** name where a request goes. Three spellings, one resolution path:

```python
Target = str  # "anthropic:claude-sonnet-4-5" | "ollama:qwen3:8b" | alias "medium"
# engine aliases normalize: "claude:..." → "anthropic:..."


@dataclass(frozen=True, slots=True)
class ResolvedTarget:
    provider_id: str
    model: str  # may be the sentinel "auto" (Copilot) — see §7
    via_alias: str | None  # "medium" if resolved through the catalog
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
    cost_usd: Decimal | None = None  # computed from pricing metadata when known


@dataclass(frozen=True, slots=True)
class Timing:
    started_at: float
    first_token_ms: float | None  # TTFT, measured centrally at first visible delta
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
    structured: Any | None  # present iff request.schema; already validated
    tool_calls: tuple[ToolCall, ...]
    target: ResolvedTarget  # what actually served it (post-fallback)
    finish_reason: Literal["stop", "length", "tool_calls", "content_filter", "other"]
    usage: Usage
    timing: Timing
    structured_mechanism: Literal["grammar", "json_schema", "json_mode", "prompt"] | None
    repair_attempts: int
    attempts: tuple[AttemptRecord, ...]  # full routing trail
    warnings: tuple[str, ...]
    raw: Any | None  # provider payload escape hatch (opt-in retention)
```

## 6. Streaming event model

One typed event stream is the generation primitive; non-streaming is "drain the stream, return
the final result" (ADR-001).

```python
@dataclass(frozen=True, slots=True)
class TextDelta:
    text: str


@dataclass(frozen=True, slots=True)
class ReasoningDelta:
    text: str


@dataclass(frozen=True, slots=True)
class ToolCallDelta:
    call_id: str
    name: str | None
    arguments_fragment: str


@dataclass(frozen=True, slots=True)
class UsageUpdate:
    usage: Usage


@dataclass(frozen=True, slots=True)
class TimingMark:
    name: Literal["first_token", "attempt_start", ...]
    at_ms: float


@dataclass(frozen=True, slots=True)
class AttemptFailed:
    record: AttemptRecord  # emitted before a retry/fallback


@dataclass(frozen=True, slots=True)
class StreamEnded:
    result: Generation


StreamEvent = (
    TextDelta
    | ReasoningDelta
    | ToolCallDelta
    | UsageUpdate
    | TimingMark
    | AttemptFailed
    | StreamEnded
)
```

Consumption patterns this must serve:
- **Interactive CLI**: iterate, print `TextDelta.text`, done.
- **Instrumented harness**: iterate for `TimingMark("first_token")`, then read
  `StreamEnded.result` — the "stream for timing, one authoritative buffered result" pattern.
- **Batch document filler**: never iterates; calls the non-streaming method, which drains
  internally.

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
    STREAMING = auto()
    JSON_SCHEMA = auto()
    GRAMMAR = auto()
    JSON_MODE = auto()
    TOOLS = auto()
    REASONING = auto()
    SYSTEM_PROMPT = auto()
    CACHE_USAGE = auto()


@dataclass(frozen=True, slots=True)
class ModelCapabilities:
    context_window: Sourced[int] | None
    max_output_tokens: Sourced[int] | None
    features: Sourced[Feature]
    pricing: Sourced[Pricing] | None
    local: LocalModelInfo | None  # artifact size, quantization, est. RAM/VRAM,
    # observed VRAM residency
```

Assembly is layered, later layers overriding earlier, every field provenance-tagged:
1. **Static catalog** — bundled data: pricing, known context windows for hosted models.
2. **Live discovery** — `list_models()`, Ollama `/api/tags`/`/api/ps`, Anthropic paginated
   `/v1/models`, Copilot SDK model list.
3. **Active probes** (opt-in, costs a request) — `capabilities/probes.py`: one
   forced-mechanism request per feature, recording only conclusive outcomes.

**The `auto` problem (Copilot):** when `model == "auto"`, capabilities are the *conjunction*
(tightest bound per field) across the models the provider might pick. This is the general
rule for any delegating provider.

**Structured-output mechanism selection** reads `features`: `GRAMMAR > JSON_SCHEMA >
JSON_MODE > prompt injection`. The chosen mechanism is recorded on the result. Per-provider
wire projection (e.g. the Ollama schema stripping of `minLength`/huge `maxItems`) lives
in the adapter; the *original* schema always validates the response client-side.

## 8. Provider-adapter contract

```python
@runtime_checkable
class ProviderAdapter(Protocol):
    descriptor: ClassVar[ProviderDescriptor]

    async def list_models(self) -> Sequence[DiscoveredModel]: ...
    async def health(self) -> Health: ...  # cheap readiness probe; router consults
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
- Optional capabilities (e.g. session reuse, runtime diagnostics) are declared on the
  descriptor, not duck-typed via `getattr`.

```python
@dataclass(frozen=True, slots=True)
class ProviderDescriptor:
    id: str  # "anthropic"
    aliases: tuple[str, ...]  # ("claude",)
    display_name: str
    factory: AdapterFactory
    locality: Literal["hosted", "local"]
    default_base_url: str | None
    requires_base_url: bool
    setup: ProviderSetupSpec  # declarative fields → app UIs need no engine branches
    reasoning_translator: ReasoningTranslator
    static_capabilities: Mapping[str, ModelCapabilities]  # catalog layer seed
    token_calibration: TokenCalibration = TokenCalibration()  # envelope this provider bills for
    max_repair_attempts: int | None = None  # ceiling on schema-repair round trips
    supports_sessions: bool = False
    reports_diagnostics: bool = False  # adapter implements diagnostics()
```

Registration: built-ins pre-registered; third parties via entry points
(`[project.entry-points."anyinfer.providers"]`), loaded lazily, collision-safe (duplicate
id/alias rejection at registration).

### v1 adapters and their dialects

| Adapter | Transport | Notes |
|---|---|---|
| `openai-compat` | httpx2, chat completions + SSE | Base class for several below |
| `openai` | httpx2, **Responses API** | reasoning items and tool calls off the item stream |
| `anthropic` | httpx2, Messages API | thinking deltas excluded from text, counted for TTFT |
| `ollama` | httpx2, native `/api/chat`, `/api/tags`, `/api/ps` | GPU-spill warning; `keep_alive` sessions |
| `openrouter` | openai-compat subclass | + model metadata from `/models` (rich pricing/context data) |
| `azure-foundry` | openai-compat subclass | Entra via `azure-identity` (extra); `max_completion_tokens` |
| `copilot` | `github-copilot-sdk` (extra) | `auto` sentinel; session resume; usage from events |
| `m365-copilot` | httpx2 + interactive Entra | interactive-auth-only — degraded headless story, documented |
| `llama-cpp` | supervised `llama-server`, openai-compat dialect | see §12; loopback only |
| `gemini` | httpx2, native `generateContent` | thinking levels, discovered windows |
| `deepseek` | httpx2, chat completions | separate reasoning channel and cache accounting |
| `xai` | httpx2, chat completions | provider-reported cost and discovered pricing |
| `vertex` | httpx2, native `generateContent` | project-scoped GCP auth and addressing |
| `bedrock` | httpx2, Converse + event stream | SigV4/API-key auth and binary stream framing |
| `cohere` | httpx2, native v2 chat | grounded generation and thinking channel |
| `lm-studio` | httpx2, native discovery + chat | quantization and residency discovery |
| `nebius` | httpx2, chat completions | live pricing, context, and quantization discovery |

## 9. Structured output

1. Request carries `SchemaSpec` (JSON-schema dict, or anything with `model_json_schema()`).
2. Core selects the mechanism from capabilities; adapter projects the schema to its wire form.
3. Response text is parsed and validated against the **original** schema with `jsonschema`.
4. On violation: if `repair=Repair(max_attempts=N)` was set, the core re-prompts with the
   validation errors appended, within the same routing budget; otherwise raises
   `SchemaViolationError` carrying the raw text and errors.
5. `Generation.structured` is the parsed value; `structured_mechanism` and `repair_attempts`
   record how it was obtained.

## 10. Error hierarchy

Shallow tree, rich fields. Every error carries: `provider`, `phase`
(`configure|discover|generate|stream|validate|cleanup`), `retryable: bool`,
`retry_after_s: float | None`, `http_status: int | None`, `detail: str` (bounded, redacted),
`hint: str | None` (an actionable next step, kept separate from the diagnostic detail).

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

Retryable status classification: `{408, 409, 425, 429} ∪ ≥500`.
All `detail` strings pass the redaction registry before construction.

## 11. Routing

```python
@dataclass(frozen=True, slots=True)
class Retry:
    max_attempts: int = 2
    backoff_base_s: float = 0.5  # exponential, honors retry_after when larger
    retry_on: Callable[[ProviderError], bool] | None = None  # default: e.retryable


@dataclass(frozen=True, slots=True)
class Route:
    targets: tuple[Target, ...]  # ordered fallback chain
    retry: Retry = Retry()
    health_gate: bool = True  # skip targets whose health() failed recently
    on_fallback: Literal["same_request", "revalidate_capabilities"] = "same_request"
```

Semantics: for each target in order → health gate → resolve → attempt with per-target retry
policy → on non-retryable failure or retry exhaustion, emit `AttemptFailed`, move to next
target. All targets exhausted → `AllTargetsFailedError` with the complete attempt trail.
Health results cache with a short TTL; a skipped target records `skipped_unhealthy`.

Deferred by decision: load balancing, cost/latency-adaptive selection. `Route` is deliberately
a policy object so richer policies can be added without new client methods.

`compare()` is the reporting side of that boundary: it resolves a concrete request against
caller-supplied targets without dispatching and reports capability provenance, degradation,
fit, and estimated cost. Routing never reads a comparison; applications remain responsible
for any ranking or selection they derive from it.

## 12. Local subsystem

All four components are v1 core:

- **`local.hardware`** — one detector for every platform: RAM (`GlobalMemoryStatusEx`/`sysconf`),
  GPU (nvidia-smi, ROCm, Vulkan, lspci, CIM, system_profiler), CPU topology, unified-memory
  detection. Disk-cached, keyed by probe-executable signatures, with invalidation env vars.
  **Advisory-only semantics**: detection proposes; callers/apps decide.
- **`local.backends`** — which llama-server runtime variants are available/installed:
  CPU/CUDA/ROCm/Vulkan/Metal, ranked (`{"cuda":30,"metal":25,"vulkan":20,"cpu":10}`),
  manifest-validated, pinned llama.cpp build, architecture and path-containment checks.
- **`local.tuning`** — posture (`conservative|balanced|aggressive`)
  × hardware profile × per-model KV-bytes/token table → `ServerPlan` (threads, batch/ubatch,
  gpu layers, KV cache type, largest context that fits the memory budget).
- **`local.gguf`** — catalog schema: SHA-256 + size + revision-pinned URL + license per
  artifact, sharded-file support; atomic downloads (`.download` → rename), file locking,
  resume, progress callbacks.
- **`local.server`** — llama-server supervisor: spawn, readiness poll, crash detection,
  graceful shutdown; **binds 127.0.0.1 with ephemeral port only**; non-loopback requires an
  explicit `allow_remote_exposure=True`.
- **`local.recommend`** — hardware→tier, driven by the alias catalog rather than hardcoded
  thresholds.
- **`local.runtimes`** — the acquisition side of `backends`: a pinned per-platform,
  per-backend artifact table (`runtimes.json`, written from the upstream release API by
  `scripts/pin_runtimes.py`), `runtime.json` manifest validation, and `install_runtime()`.
  CUDA is an explicit opt-in gated on driver major and compute capability; the default path
  installs Metal on Apple Silicon, Vulkan on any other GPU machine, CPU otherwise.
- **`local.fit`** — catalog entry × hardware → `gpu | cpu | tight | no | unknown`, with
  reasons. Consumes catalog entries structurally, the same protocol trick `recommend` uses,
  so the `catalog → local` dependency stays one-directional.
- **`local.variants`** — which quantization to acquire: the highest-quality rung whose
  weights *and* KV cache fit, with per-engine gates (vLLM kernels on compute capability) and
  a stated quality floor at Q4_K_M.
- **`local.sources`** — `SourceRef` → `ResolvedArtifact` behind a resolver protocol:
  `huggingface` (spoken directly, ADR-007; `contracts/huggingface.md`), `url`, `local`.
- **`local.acquire` / `local.store`** — plan → preflight → concurrent fetch → verify →
  place → register, and a revision-scoped store with a rebuildable index. Model acquisition
  lives here, never in an adapter: fetching forty gigabytes is not protocol translation.

The `llama-cpp` adapter composes these: resolve GGUF via catalog → locate in the store (or
acquire) → plan → supervise server → speak openai-compat over loopback. In-process
`llama-cpp-python` is explicitly **not** supported (ADR-004); the subprocess model is the
only supported shape.

## 13. Alias catalog

Schema:

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

The bundle is **two documents with different cadences**, overlaid at load:
`default.json` is the hand-edited alias policy above, and `models.json` is the
machine-maintained logical model table — one row per browsable local model, with a
quantization ladder (`variants[]`), per-channel sources (pinned GGUF artifacts and an Ollama
tag with its manifest digest), memory estimates, a closed `best_at` vocabulary, and a real
`last_verified` date. Artifacts derived from GGUF variants are registered into the same id
space the alias targets use, so the two shapes reference one body of data.
`Catalog.with_alias_target()` bridges them: a user's catalog pick becomes a tier target
through the existing overlay machinery, with no resolver changes.

- AnyInfer **bundles a maintained default catalog** (an accepted curation burden, tracked as
  risk R6); apps may replace or overlay it (merge: app entries win).
- Resolution: `alias × provider → concrete target`; unresolvable combinations are
  `ConfigError`s at resolve time, not silent fallbacks.
- `local.recommend` picks a default alias from hardware; apps surface it as the novice default.

## 14. Telemetry and events

- **Contract:** typed lifecycle events → registered in-process observers. Nothing is written
  anywhere by default.
- Event set: `RequestStarted`, `TargetResolved`, `AttemptStarted`, `FirstToken`,
  `AttemptCompleted` (usage/timing), `RetryScheduled`, `FallbackTriggered`, `RepairAttempted`,
  `RequestCompleted`, `RequestFailed`, `ParameterDropped`, `UsageEstimated`,
  `ContextReduced`, `ServerLifecycle` (local), `DownloadProgress`.
- **Privacy levels:** events are payload-free by default (ids, counts, timings, model names).
  An observer must be registered with `payloads=True` to receive prompt/response text.
- **Redaction:** every secret resolved through `anyinfer.credentials` is auto-registered; all
  `detail` strings, event fields, and log lines pass redaction before emission.
- **OTel bridge** (`anyinfer.otel`): maps events to spans/metrics; imports
  `opentelemetry-api` lazily and only when enabled; recommended packaging is the `[otel]`
  extra. Application-side sinks (JSONL trails, SQLite evidence stores) are observers in
  *their* codebases, or a shared `anyinfer.sinks` contrib module later.
- **Cost:** `Usage.cost_usd` computed from capability-layer pricing when provenance is
  `catalog` or `discovered` (OpenRouter reports pricing); `None` otherwise — never guessed.
- **Run manifest** (`anyinfer.manifest`, ADR-014): a terminal *projection* of one request's
  events plus its `Generation`, carried on `Generation.manifest`. It adds no source of
  truth — every field is derivable from the event stream, the request, the resolved
  capabilities, and the result — and it is content-free by default on the same terms as
  events. Events remain the contract for an observer watching a system; the manifest is
  the contract for a developer holding one call.

## 15. Configuration and credentials

- **Core is programmatic:** `AsyncClient(providers=[…], catalog=…, route_defaults=…)` from
  plain typed objects. No file I/O in the core path.
- **`anyinfer.config` (optional layer):** canonical JSON schema versioned with
  `format_version`; `load()/save()/validate()`; precedence **explicit args > env vars >
  config file > defaults**; hygiene rules (size caps, unknown-credential-shaped-field
  rejection); per-provider sections driven
  by `ProviderSetupSpec` so a config wizard/UI is generic across engines — including which
  fields to *ask* for, since the spec marks the ones it already has a standard value for
  (`SetupField.advanced` / `default_value`) rather than presenting all fields as equals and
  leaving each consuming app to sort them out; `HostShorthand` expansion
  (`myserver` → `http://myserver:11434`).
- **Credentials:** config/API accept `"sk-literal"`, `"env://OPENAI_API_KEY"`, or
  `"credential://system/openai"`. `CredentialResolver` protocol; shipped resolvers: literal,
  env, keyring (`[keyring]` extra). Apps register custom resolvers. Every
  resolved secret feeds the redaction registry. Env-var naming: `ANYINFER_*`.
- **`history` block:** optional conversation-compaction policy, parsed into
  `HistoryPolicy` (§27) and handed to the client by every frontend, so one file makes
  the SDK, the CLI, and the sidecar agree. Absent means no compaction.
- **`context` block:** optional advanced context-reduction settings, parsed into
  `anyinfer.context.ContextTuning` (§26). Keys are the dataclass field names, so one
  vocabulary spans the file, the `--context-*` CLI flags, and the `tuning=` keyword
  argument. Unknown keys are an error rather than being ignored, since a misspelled tuning
  setting that silently does nothing is worse than one that fails loudly. The sidecar reads
  the same file — so one config serves every frontend — but does not reduce: that would
  make it a second core (ADR-009).

## 16. Sync and async surfaces

- **Async core.** `AsyncClient` is the real implementation.
- **Sync facade.** `Client` owns a dedicated background event-loop thread (not
  `asyncio.run()` per call — that would break streaming iterators, connection pooling, and
  supervised-server lifetimes). Sync `stream()` returns a thread-safe blocking iterator fed
  from the loop. `Client` is safe to call from multiple threads; one loop, serialized I/O
  scheduling, concurrent requests still overlap on the loop.
- No per-call loop churn and no cross-loop client locking: the facade owns its loop, and
  async consumers use `AsyncClient` bound to their own loop as usual.

## 17. Example public API

```python
import anyinfer as ai

# --- one-liner, alias target, sync ---
client = ai.Client()  # default registry, bundled catalog
result = client.generate("Summarize:\n" + text, target="medium")
print(result.text, result.usage.output_tokens, result.timing.first_token_ms)

# --- streaming ---
with client.stream(messages, target="ollama:qwen3:8b") as stream:
    for ev in stream:
        match ev:
            case ai.TextDelta(text=t):
                print(t, end="", flush=True)
    final = stream.result  # Generation

# --- structured contract with repair ---
result = client.generate(
    messages,
    target="copilot:auto",
    schema=ANSWER_SCHEMA,
    repair=ai.Repair(max_attempts=1),
)
answer = result.structured  # validated against ANSWER_SCHEMA

# --- fallback chain + retries (router) ---
route = ai.Route(
    targets=("anthropic:claude-sonnet-4-5", "azure-foundry:gpt-5-mini", "ollama:qwen3:8b"),
    retry=ai.Retry(max_attempts=3),
)
result = client.generate(messages, route=route)
for a in result.attempts:
    print(a.target, a.outcome)

# --- instrumented benchmarking ---
async with ai.AsyncClient(observers=[metrics_writer]) as ac:
    async with ac.stream(messages, target=t) as s:
        async for ev in s:
            if isinstance(ev, ai.TimingMark) and ev.name == "first_token":
                note_ttft(ev.at_ms)
        record(s.result.usage, s.result.timing)

# --- discovery & capabilities ---
for m in client.models("openrouter"):
    print(m.id, m.capabilities.context_window, m.capabilities.pricing)

# --- local inference, hardware-aware ---
hw = ai.local.detect()  # cached HardwareProfile
alias = ai.local.recommend_alias(hw)  # e.g. "large" on a 24 GB GPU
result = client.generate(prompt, target=alias)  # llama-cpp: download → tune → serve → answer


# --- bounded tool loop ---
@ai.tool
def read_file(path: str) -> str:
    """Read a project file."""
    ...


result = client.run_tools(
    messages, tools=[read_file], target="anthropic:claude-sonnet-4-5", max_rounds=8
)

# --- provider escape hatch ---
result = client.generate(
    messages, target="ollama:qwen3:8b", provider_options={"ollama": {"keep_alive": "10m"}}
)
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
  session.py             # the session handle
  benchmark.py           # throughput measurement, live samples + caller-owned store
  verification.py        # the end-to-end target probe
  config/                # shared, versioned JSON configuration
  catalog/               # model.py resolve.py default.json models.json
  capabilities/          # assemble.py probes.py pricing.py estimate.py budget.py gating.py
  local/                 # hardware.py metrics.py backends.py runtimes.py runtimes.json tuning.py
                         # services.py discovery.py fit.py variants.py artifacts.py downloads.py
                         # acquire.py store.py sources/ server.py recommend.py
  providers/             # base.py sse.py openai_compat.py openai.py anthropic.py
                         # ollama.py openrouter.py azure_foundry.py copilot.py
                         # m365_copilot.py llama_cpp.py gemini.py deepseek.py xai.py
                         # vertex.py bedrock.py cohere.py lm_studio.py nebius.py presets.py
  context/               # corpus reduction: documents.py rank.py structure.py
                         # envelope.py select.py tiers.py pack.py distill.py
                         # settings.py dedup.py compact.py history.py
  mcp/                   # protocol.py transport.py toolset.py
  testing/               # conformance.py scripted.py fakes.py cassettes.py plugin.py
  cli.py                 # init, agents-md, run, verify, benchmark, doctor, providers,
                         # models, runtime, context, mcp, conform, serve
  serve/                 # openai_codec.py app.py __main__.py — see §22, ADR-009

tests/                   # unit + conformance runs (cassette & fake modes)
contracts/               # per-provider protocol snapshots + DRIFT-CHECK.md (§24)
docs/                    # provider guides, published site sources (§25)
```

**Packaging:** mandatory deps `httpx2`, `jsonschema`. Extras: `[copilot]`
github-copilot-sdk · `[azure]` azure-identity · `[vertex]` cryptography · `[keyring]`
keyring · `[otel]` opentelemetry-api · `[serve]` ASGI server deps · `[demo]` PySide6 and
Markdown · `[mcp]` an explicit dependency-free feature marker · `[all]`. The complete local
subsystem is core; llama-server binaries and model weights are runtime-fetched, never pip
dependencies. Missing-extra errors raise `ConfigError` with an install hint.

## 19. MVP scope and roadmap

Tiered milestones inside v1. The original scope was nine providers plus the tool loop;
provider breadth expanded through dedicated adapters and compatibility presets.

- **M0 — skeleton (the contract):** types, errors, events/redaction, registry, schema
  subsystem, router (retry+fallback+health), `AsyncClient` + sync facade, `openai-compat`
  adapter, conformance harness + fake SSE server + cassette tooling. *Tool types exist in the
  message/event model from day one; no loop yet.*
- **M1 — core four + local subsystem:** `ollama`, `copilot`, `llama-cpp` (with the full local
  subsystem: hardware, backends, tuning, gguf, server, recommend), alias catalog + bundled
  default. This tier exercises aliases, local inference, streaming, and the sync facade at
  once.
- **M2 — hosted breadth:** `openai` (Responses), `anthropic`, `azure-foundry`;
  repair loop hardening; OTel bridge.
- **M3 — long tail:** `openrouter`, `m365-copilot`; active capability probes.
- **M4 — tool loop + stabilization:** `run_tools` executor, conformance matrix complete for
  the dedicated adapters, API freeze review, docs, publish publicly.
- **M5 — sidecar + binaries:** delivered in the 0.1 beta: `anyinfer.serve`
  OpenAI-compatible loopback service (§22), shared versioned configuration, the CLI process
  boundary, and standalone `anyinfer-serve` bundles for macOS/Linux/Windows (ADR-010) with a
  native CI build matrix and checksums. Signing/notarization remains external release
  infrastructure to resolve before 1.0.

## 20. Major unresolved decisions

1. **Token estimation / prompt budgeting.** *Resolved.* Pluggable
   `TokenEstimator` protocol with a dependency-free byte-heuristic default
   (`capabilities/estimate.py`); every estimate carries a conservative-high planning figure
   *and* a defensible floor. The provider-neutral budget calculator
   (`capabilities/budget.py`) computes input allowance = context window − derived output
   reserve − clamped 5% headroom, tri-state per ADR-005: an unknown window yields an unknown
   budget, never a guessed default. Pre-dispatch gating (`capabilities/gating.py`) raises
   `ContextLengthError` only when the estimate's *floor* exceeds a trusted-provenance window,
   feeding `Route.context_window_targets`; `default`-provenance windows never gate. Exposed as
   `Client.budget()` / `AsyncClient.budget()` for app preflight. Exact
   tokenizers (tiktoken, llama-server `/tokenize`) plug in via the protocol; none ship.
2. ~~**Session/conversation reuse** (Copilot session resume, Ollama
   keep_alive).~~ *Resolved:* `client.session(target)` returns an opaque,
   target-bound handle threaded through `generate()`/`stream()`; it never changes an answer,
   and the three capable providers each exploit it differently behind one shape.
3. ~~**Cancellation semantics** across the sync facade.~~ *Resolved:* an interrupt cancels
   the loop-thread future, early stream exit closes the async iterator, and facade shutdown
   cancels outstanding tasks with bounded waits. Dedicated tests cover early exit and thread
   stress; supervised local servers survive request cancellation.
4. **Default catalog contents and update cadence** — which models, who bumps them, does a
   catalog update constitute a library release? (Risk R6.)
5. ~~**M365 Copilot headless story.**~~ *Resolved as a documented degraded mode:* auth is
   interactive-only, the adapter is exempt from credentialed headless live runs, and its
   fixed capability surface is covered offline.
6. ~~**Ollama GPU-spill warning + observed-VRAM checks** — capability layer or
   Ollama-adapter warnings?~~ *Resolved:* adapter-reported runtime
   diagnostics, declared on the descriptor and surfaced on `Generation.warnings` plus a
   `ProviderDiagnostic` event.

## 21. Risks and complexity traps

- **R1 — sync facade correctness** (streaming iterators, cancellation, thread affinity).
  Mitigated by the background-loop ownership rules, bounded cancellation, early-exit tests,
  and thread-stress coverage; retain those as release gates.
- **R2 — multi-provider conformance drift**, now across twenty dedicated adapters plus a
  preset registry. Mitigate: cassette CI + nightly live runs; the matrix doc is the source
  of truth for "native vs emulated vs unsupported", and presets are covered by
  representatives per quirk axis rather than one row each.
- **R3 — llama-server supervision on Windows** (process trees, GPU runtime DLLs, antivirus
  interference). Mitigate: process-tree termination, reader-thread stream ownership, and
  bounded waits, each covered by a dedicated Windows test.
- **R4 — structured-output mechanism divergence** (grammar limits, schema projection edge
  cases). Mitigate: original-schema client validation is always authoritative; projections
  are provider-quirk code with dedicated conformance cases.
- **R5 — tool loop shipped ahead of demand.** Mitigate: last milestone, types proven
  earlier, keep the executor minimal (no parallel calls in v1).
- **R8 — retrieval-quality expectations creep** — a lexical ranker invites "why didn't it
  find X" reports and pressure toward embeddings/rerankers the slim core forbids.
  Mitigate: docs state the ranking model plainly (ASCII-alphanumeric lexical matching with
  path boosting); the ranker sits behind a protocol so exact or semantic implementations
  can be supplied by apps; open question 8 owns the embeddings decision. Identifier
  splitting and pseudo-relevance feedback (§26) close part of the gap *within* the lexical
  model and are off by default, so they narrow the pressure without changing what the
  default ranker is. The structural-extract language table is a staleness surface like the
  catalog (R6) — languages are added by one suffix-map entry plus one extract branch,
  covered by tests. The commentary-syntax table behind `compact_fallback` is the same kind
  of surface, and degrades to "no compaction" rather than to mangled source.
- **R9 — advanced-settings sprawl.** `ContextTuning` is sixteen knobs, and every one of
  them is a way for two deployments to behave differently while reading the same
  documentation. Mitigate: defaults reproduce the unconfigured behaviour exactly, so a
  setting only matters once someone changes it; `recommended()` is a named preset rather
  than a scattering of "you probably want" advice; the CLI generates its flags from the
  dataclass, so the config block, the flag, and the keyword argument cannot name different
  things; and every reduction reports which of them changed the outcome
  (`collapsed_*`, `compacted_count`, `partial_count`, `carried_over`).
- **R6 — bundled catalog staleness** (decision: bundle anyway). Mitigate: catalog is data
  with its own `format_version`; overlay mechanism lets apps pin; consider a separate
  release cadence.
- **R7 — Copilot `auto` sentinel** breaking "model is a known string" assumptions —
  conjunction-of-capabilities rule (§7) must be enforced in the capability assembler, not
  ad hoc per caller.
- **R10 — Embedding-space mismatch and retrieval-scope creep** (§28). A silently-wrong
  fallback embedding target is a correctness failure disguised as a success, worse than an
  ordinary provider error because nothing in the response signals it (ADR-018's whole
  reason to exist). Mitigate: same-target-only retries by default, refuse-before-send on
  unknown equivalence, conformance tests asserting the refusal. Separately, "batteries
  included" pressure will keep inviting a built-in vector database; the boundary in §28 and
  the scale ceiling in §29.2 exist to keep that pressure from quietly expanding the core's
  product definition.

## 22. Serve frontend: OpenAI-compatible loopback federation

**Requirement:** as an optional batteries-included module, AnyInfer
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
  parsed as a `Target`: `"medium"` (alias), `"anthropic:claude-sonnet-4-5"`,
  `"ollama:qwen3:8b"`, or a named route configured server-side. Federation is therefore free.
- `GET /v1/models` — enumerates catalog aliases, named routes, and (optionally) concrete
  `provider:model` targets, with capability metadata in OpenAI's `model` object shape.
- Mappings: `messages`/`tools`/`tool_choice`/`response_format.json_schema` →
  `GenerationRequest` fields; `temperature`/`top_p`/`max_tokens`/`stop` → `Sampling`;
  unrecognized extra-body fields → `provider_options` passthrough (namespaced), so OpenAI
  clients keep the escape hatch. Usage blocks and `finish_reason` come from `Generation`.
- Out of scope for the frontend: endpoints AnyInfer itself doesn't model (images, audio,
  files) return 404 with a clear error body. `POST /v1/embeddings` and
  `POST /v1/anyinfer/rerank` are modeled endpoints as of §28 — see that section.

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

**Security posture (inherits the core security rules: redaction §14, loopback-only §12,
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
**Why.** Maintaining dual implementations ≈ doubles test surface; per-call `asyncio.run()`
breaks streaming and pooling. **Consequences.** Sync consumers go through the facade;
cancellation semantics must be explicitly designed (open decision 3); no cross-loop client
locking is needed.

### ADR-003 — Adapters translate; the core orchestrates
**Decision.** Adapters expose exactly `list_models / health / generate(→events) / aclose` and
never retry, validate, or measure. Retry, fallback, schema validation/repair, timing, usage
normalization, telemetry, redaction live in the core. **Why.** Nine thin adapters are
testable by one conformance suite, whereas orchestration smeared into provider code has to
be re-proven per adapter. **Consequences.** `WireRequest`
must carry everything pre-resolved; provider quirks surface as declarative descriptor data or
small projection hooks, not control flow.

### ADR-004 — llama.cpp via supervised llama-server only
**Decision.** No in-process `llama-cpp-python`; the library supervises `llama-server`
(loopback-only) and speaks the OpenAI-compatible dialect. External servers are just
openai-compat targets. **Why.** One wire protocol for all engines, crash isolation, no
GPU-wheel/DLL build matrix in the dependency tree. **Consequences.** In-process embedding
of the runtime is given up (accepted); subprocess lifecycle on Windows is a named risk (R3);
server startup latency is mitigated by keep-alive supervision.

### ADR-005 — Layered, provenance-tagged capability metadata
**Decision.** `ModelCapabilities` assembled from static catalog → live discovery → optional
probes; every field carries provenance; delegating models (`auto`) get
conjunction-of-candidates bounds. **Why.** Providers omit or misreport; consumers (routing,
schema mechanism selection, context budgeting, pricing) need to know *how much to trust* a
number. **Consequences.** A `Sourced[T]` wrapper appears in public types; probe cost is
opt-in; the static layer creates catalog-maintenance work.
**Amended:** a fifth provenance, `override` (rank above `probed`), for
values the integrating application set deliberately — a user's explicit correction must
never lose to data the library merely collected. The static layer now includes the bundled
per-provider pricing table (`capabilities/pricing.json`), keyed by provider *and* model
because engines price the same model differently; its maintenance burden is carried by the
weekly `pricing-refresh` workflow.

### ADR-006 — Typed in-process events; OTel as a bridge
**Decision.** The telemetry contract is typed Python events to registered observers,
payload-free by default; an optional bridge maps them to OpenTelemetry. **Why.** Applications
that consume telemetry in-process as structured data (JSONL trails, SQLite evidence stores)
find round-tripping through OTel spans awkward, and a CLI wants zero telemetry and zero deps;
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
**Why.** A CLI install must stay light; raw httpx (of which httpx2 is the drop-in
continuation — see the note below) covers every hosted dialect, and official provider SDKs
add churn without coverage gains. **Consequences.**
SSE/NDJSON parsing is first-party code (shared module); missing-extra UX must be excellent
(actionable `ConfigError`s).

> **httpx → httpx2.** The HTTP dependency was originally `httpx`. Upstream
> httpx stagnated (last release 2024-12) and stewardship moved to Pydantic Services under the
> `httpx2` name (same BSD-3-Clause license, original author credited, API-compatible);
> starlette ≥ 1.0 deprecates plain httpx in its test client in favor of httpx2. The core
> migrated wholesale — the full gate suite passes unchanged against httpx2 2.9.x.

### ADR-008 — Descriptor registry with entry-point discovery
**Decision.** Frozen `ProviderDescriptor`s in a collision-safe registry; declarative
`ProviderSetupSpec` per provider; third-party adapters register via the `anyinfer.providers`
entry-point group. **Why.** A descriptor registry eliminates per-engine branches across CLI
*and* GUI consumers; entry points let future engines (and experiments) plug in without core
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
the frontend inherits the loopback-only and redaction rules (§12, §14, §15).

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
PyInstaller also has the best-documented answers to the platform quirks, including the
Windows AV-heuristics problem that motivates **onedir over onefile** (onefile's
self-extraction both slows startup and trips AV scanners; risk R3 adjacency).
**Consequences.** A native CI build matrix performs a binary `--help` smoke test,
while the package suite covers `/v1/models` and fake-provider round trips; macOS signing +
notarization and Windows Authenticode become release-pipeline concerns (open question 9);
the canonical config layer (§15) is mandatory in binary mode since there is no Python API
surface; `shiv`-style zipapps may be offered later as a secondary artifact for hosts that
do have Python, without changing the contract.

### ADR-011 — Context reduction: apps collect, the library reduces
**Decision.** Ship an optional `anyinfer.context` subpackage implementing corpus reduction
(rank / select / represent / distill) against an explicit token budget, with collection
(filesystem traversal, approval, secret exclusion) permanently app-side. Reduction composes
the estimator/budget surfaces of §20 #1; it never performs I/O and adds no dependencies.
**Why.** Applications otherwise build and maintain divergent copies of this layer — ranked
selectors, tiered rollups, chunkers — all on top of the same byte-heuristic arithmetic the
estimator already centralizes. Collection stays out because it is where the
security policy lives (what exists, what is safe to send) and where every app differs;
reduction is where the apps converge. **Consequences.** The §2 "No prompt templating"
non-goal is narrowed: the library owns one mechanical envelope format, apps own all prompt
language around it. `distill` spends inference calls, so it is separated by construction
(an async function taking the client by structural protocol, reporting aggregate `Usage`)
from the pure strategies. Lexical ranking sets retrieval-quality expectations the docs must
manage (risk R8); embeddings stay out until open question 8 reopens.

### ADR-012 — Prompt-cache placement is core policy; adapters only spell it
**Decision.** A request may carry a `CachePolicy`. The core segments the prompt, decides
which segments are worth marking, and picks the strongest mechanism the target offers —
`explicit` (per-segment marks, e.g. Anthropic `cache_control`), `implicit` (the provider
caches stable prefixes on its own, so the core's duty is to leave the prefix undisturbed),
or nothing. Adapters translate marks onto their wire format and do nothing else. Providers
declare `cache_mechanism`, `cache_max_marks`, and `cache_min_tokens` on their descriptor.
Off by default: `GenerationRequest.cache` is `None` unless a caller or client asks.
**Why.** The library already reads cache accounting (`Usage.cache_read_tokens` /
`cache_write_tokens`) and prices it, and had no way to *cause* it — so an application
wanting a cached prefix wrote per-provider `provider_options` branches, which is the
per-engine `if/elif` this project exists to delete (§2 goal 1). The mechanism ladder is the
same shape structured output already uses, and for the same reason: the caller states an
intent, the core picks the strongest available implementation, and losing a rung is
observable rather than silent. **Consequences.** Degradation emits `ParameterDropped`; a
plan emits `CachePlanned`; realized savings are attributed **only** from provider-reported
usage, never from the plan, so an intention is never billed as a fact. Cache floors and
TTLs are wire facts, recorded in `contracts/<id>.md` and audited by the drift check.
Response caching remains out of scope permanently — this caches the prefix a provider is
sent, on the provider's side, and never skips a call.

### ADR-013 — MCP is a tool *source*, spoken directly
**Decision.** Ship an optional `anyinfer.mcp` subpackage (`[mcp]` extra) that connects to
Model Context Protocol servers, discovers their tools, and exposes them as ordinary
`ToolSpec`/`Tool` values for the existing loop. Scope is `tools/list` and `tools/call`
over stdio and streamable HTTP. `prompts/*`, `resources/*`, `roots/*`, and `sampling/*` are
excluded. The protocol is spoken directly against `httpx2` and the stdlib; the `mcp` SDK is
not a dependency, and the pinned protocol version lives in `contracts/mcp.md`.
**Why.** MCP has become how tools are *distributed*, and the bridge from a server's
`inputSchema` to a `ToolSpec` is identical for every consumer — including the protocol
details (handshake, version negotiation, content-block flattening, error semantics) that
are quietly easy to get wrong. Supplying tool definitions and an execution transport for
tools the application already chose to trust is the same category as a Python function
passed to `run_tools`: it adds no planning, no memory, and no loop semantics, so the "not
an agent framework" non-goal holds. Speaking the protocol directly is ADR-007's rule
applied unchanged — the same call made for provider SDKs and for the Hugging Face API.
**Consequences.** `sampling/*` stays excluded on a security ground, not a scheduling one:
honoring it would let a remote server drive generations through the caller's credentials,
which is a capability to grant deliberately, not a convenience to inherit. stdio servers
are child processes and reuse `local/server.py`'s supervision shape (sole stream ownership,
process-tree termination, bounded waits) rather than growing a second one. Tool results are
attacker-influenceable text entering a model's context; that trust decision is the
application's and the documentation says so. This ships ahead of a named consumer — risk R5
knowingly accepted, bounded by living entirely behind an extra.

### ADR-014 — The run manifest is a projection of events, never a second source of truth
**Decision.** Ship `anyinfer.manifest`: one versioned, serializable `RunManifest` per call,
carried on `Generation.manifest`, readable mid-flight from a stream handle, printed by
`anyinfer run --trace`, and offered by the sidecar as an opt-in `anyinfer_manifest`
response extension. **The derivation rule is the decision**: every field is computed from
one request's telemetry events, the `GenerationRequest` they came from, the capabilities
the router resolved for its targets, and the `Generation` it produced. No field is measured
independently, nothing on the request path reports to the manifest and nowhere else, and
`tests/test_manifest.py` records a run through both a subscribed observer and the builder
and fails when the two disagree. On by default: it allocates one small object per in-flight
request, writes nothing, sends nothing, and is content-free — the invited/uninvited line in
this codebase has always been about spend and side effects, and this has neither.
**Why.** ADR-006 makes typed events *the* telemetry contract, and this is a second
representation of the same facts, so it needs a reason not to be a fork. The reason is that
the two answer different questions. Events serve an observer watching a *system*: they
arrive as things happen, they must be subscribed before dispatch, and a developer who did
not subscribe has lost the story. The manifest serves a developer holding *one call*: it is
terminal, it is a value, and it can be diffed, pasted into an issue, or asserted against as
a golden file. That last use is why it exists at all — a golden manifest lets an application
regression-test its inference *behaviour* (route, mechanism, repair budget, reduction)
rather than the model's prose, which is untestable. It is also the fix for a parity defect:
before it, all twenty typed events were Python-only and the sidecar had no observability
surface whatsoever, so a developer on the standalone binary got every provider, route, and
mechanism with no way to see which fired.
**Consequences.** Content-free by default on the same terms as events, and structurally so:
the payload strings live in their own `payloads` facet which is `None` unless a client asks
for them, and every string in it passes redaction. A schema is recorded as a digest plus its
title, never its body. **No I/O anywhere in the subsystem** — writing manifests to a
directory, rotating them, or querying them is a durable store, which §2 rules out, and the
caller serializes if it wants one. The sidecar extension is response-scoped and stateless:
`/v1/anyinfer/runs`, retention, and a query API are permanently out of scope, the same fence
§27 puts around corpus storage. `serve/` imports the manifest *types* only and assembles
nothing. Format versioning follows §26's envelope rule — a bump means an existing field
changed meaning, and adding a field does not, because a reader ignoring unknown keys
survives additions.


### ADR-015 — Arena is bounded terminal comparison, never adaptive routing
**Decision.** Ship an opt-in client-layer `ArenaPolicy` that fans one request or tool loop
out to a fixed caller-supplied target set, waits for every branch, preserves every candidate,
and applies one terminal deterministic, judge, or synthesis strategy. The generation-call
ceiling is known before dispatch (`N`, or `N × max_rounds`, plus at most one judge call),
and a summed spend reservation is acquired before any branch starts. Candidates are
anonymized in the versioned judge envelope by default, never see another candidate's output
or tool history, are never pruned mid-run, and arena results are never stored or consumed by
routing. The sidecar and CLI decode policy only; orchestration remains in `AsyncClient`.
**Why.** Applications otherwise rebuild concurrent fan-out with inconsistent usage, timing,
schema validation, cancellation, and cost controls. A fixed terminal comparison has the same
bounded character as schema repair and context distillation, while mid-run branch selection
or feedback into later routing would cross the project's agent and adaptive-routing
boundaries.
**Consequences.** Cost is visibly multiplied, candidates are evidence and are never dropped
when a winner is promoted, consensus is available only for validated structured values, and
judge failures degrade to deterministic selection. Tool memoization is exact, single-flight,
and run-scoped. Because failed attempts do not carry usage today, any failed candidate makes
the arena aggregate usage unknown rather than silently understating spend.


### ADR-016 — Multimodal inputs are typed payloads; outputs remain text-only
**Decision.** Activate the message model's input reservation with image, document, and
audio parts carrying bytes or a remote reference. Adapters alone encode those parts into
provider dialects, and unsupported projections fail explicitly. Trusted capability absence
may refuse before dispatch; unknown capability data does not pretend to be absence.
Multimodal bytes are bounded before dispatch, remain payload-private, and are never logged.
When no catalog formula can price a part's token contribution, fit and cost remain unknown
and the context gate declines to guess.
**Why.** The sidecar's request model must preserve the OpenAI chat surface, and silently
flattening an image or PDF into an empty text turn violates that boundary. Typed parts make
every projection site compiler-visible while retaining one request-to-event-stream
primitive.
**Consequences.** Text-only requests are byte-for-byte unchanged. Provider and model support
is partial and provenance-tagged, remote-reference rules stay provider-specific, and local
vision remains unavailable until the pinned model catalog can represent and verify a
projector artifact. Image generation, speech output, transcription endpoints, embeddings,
and fine-tuning remain non-goals.


### ADR-017 — Embedding and reranking are operation-typed, not a `ProviderAdapter` superset

**Decision.** Generation, embedding, and reranking are three separately typed operations. The
provider contract splits into a lifecycle every adapter implements (`list_models`, `health`,
`aclose`) plus operation protocols an adapter opts into individually: `GeneratesText.generate`,
`EmbedsText.embed`, `ReranksText.rerank`. A descriptor declares which operations its adapter
supports; the registry validates the built object actually satisfies each declared protocol.
One adapter instance and one connection pool may serve several operations when a single
provider offers more than one; a retrieval-only provider needs no dummy `generate()`.
`GenerationRequest` never grows embedding or rerank fields — each operation keeps its own
request/result types, sharing only genuinely operation-neutral shapes (`ResolvedTarget`, the
shape of `Usage`, `AttemptRecord`). **Why.** `ProviderAdapter` as originally specified
requires every provider to generate text, which cannot represent a retrieval-only runtime
(a hosted reranker, a TEI deployment) without a dummy method that lies about what the
provider does. Folding embedding/rerank fields into `GenerationRequest` would also make the
core's most central type a union of unrelated inference shapes, which ADR-003's "adapters
only translate" discipline exists specifically to prevent generation code from becoming.
**Consequences.** Model discovery must stop filtering out embedding-only and rerank-only
models as "not chat models." Capability assembly gains per-operation capability records
(`EmbeddingCapabilities`, `RerankCapabilities`) beside `ModelCapabilities`, both provenance-
tagged on the same terms as §7. Third-party entry-point discovery, scaffolding, and
certification must validate declared-vs-implemented protocols per operation rather than
assuming every registered provider can generate.

### ADR-018 — Embedding-space identity gates cross-target fallback

**Decision.** Every embedding result carries an `EmbeddingSpace` (provider, model, revision
when pinned, dimensions, input-intent sensitivity, normalization, and an optional caller-
asserted compatibility id). Embedding routes retry on the same resolved target only by
default; cross-target fallback is refused unless both targets share a trusted compatibility
id or the caller explicitly opts into an unsafe fallback, which is recorded on the result and
in telemetry. When equivalence is unknown, the request fails before a fallback is sent, with
an actionable hint — the core never guesses that two models are interchangeable. Reranking
gets ordinary fallback (there is no persisted "index" to invalidate), but scores from
separate attempts are never merged or compared. **Why.** A query embedded with a fallback
model produces numbers that look exactly as plausible as the primary model's, and will
silently fail to find anything in an index built against the primary model's space. That
failure mode is worse than an ordinary provider error because nothing about the response
signals it went wrong — routing safety here has to be a refusal, not a warning.
**Consequences.** `capabilities/pricing.json`-style bundled data cannot assert cross-provider
embedding equivalence; only an application-supplied `compatibility_id` can. Batching must
preserve one embedding space per request (a split request's batches all target the same
resolved target). The context-reduction ranker boundary (ADR-011) may accept an embedding-
backed ranker built on this guarantee once §9's `ER.6.9` decision is exercised.

## 24. Provider conformance test matrix (draft)

**Contract snapshots and drift checking.** Each provider's exact wire dependencies
(endpoints, auth headers, version pins, fields sent/read, streaming framing, error shapes)
are recorded in `contracts/<provider>.md` — updated in the same change as any adapter
wire-behavior change. A semi-automated **drift check** (procedure:
`contracts/DRIFT-CHECK.md`, with the tool-specific entry points listed in `AGENTS.md`,
and the weekly `contract-drift` workflow as its scheduled track)
audits these snapshots against live provider documentation and classifies
findings as `OK / DRIFT / DEPRECATION / NEW-CAPABILITY / UNVERIFIABLE`, proposing contract,
adapter, and matrix updates. Division of labor: the conformance suite proves *our code
matches our claims*; the drift check proves *our claims still match upstream*. Repo-level automation
instructions live in `AGENTS.md` (canonical), with `CLAUDE.md` and
`.github/copilot-instructions.md` as thin adapters.

Legend: ✅ native · Ⓔ emulated by core/adapter · ➖ unsupported (documented) · ? verify in
milestone. Every cell backed by a parametrized conformance case run in cassette, fake-server,
and (nightly, where auth permits) live modes.

> **Implementation status.** Twenty dedicated adapters are implemented
> (the original nine plus Gemini, DeepSeek, xAI, Vertex AI, Bedrock, Cohere, LM Studio,
> Voyage AI, Jina AI, and Text Embeddings Inference), alongside a preset registry of
> eighty-six OpenAI-compatible providers
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
> Ten snapshots still say, in their own words, that they were never verified against
> live provider documentation — most of them code-survey-derived. The weekly
> `contract-drift` workflow ranks exactly that signal above age, so those are what its
> first rotations audit; until a run clears one, it cannot claim live verification.

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
2. **Installation matrix** — extras (`[copilot]`, `[azure]`, `[vertex]`, `[keyring]`,
   `[otel]`, `[mcp]`, `[serve]`, `[demo]`, `[all]`), Python/OS support, the core local
   subsystem, and the serve-binary download table for users who want no Python at all.
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
7. **Cookbook** — complete runnable programs mirroring the three consumption shapes: an
   interactive streaming CLI, a schema-contract document filler, and an instrumented
   benchmark harness — plus a serve-binary federation setup with an off-the-shelf OpenAI
   client.
8. **API reference** — generated; grouped by module per §4.
9. **Error catalog** — every exception class: when it's raised, its fields, whether it
   retries, and the `hint` text a user will see.
10. **Serve binary manual** — download/verify, config file reference (§15 canonical layer),
    ports and tokens, running as a service (launchd/systemd/Windows service), upgrade path.
11. **Migration guides** — for applications replacing a hand-rolled provider layer; they
    double as real-world integration tutorials and stay in the published docs.

**Milestone obligations:** M0 — site skeleton, quickstart, concepts for whatever exists,
reference generation wired into CI. M1–M3 — provider page lands in the same PR as each
adapter. M4 — cookbook complete, error catalog complete,
site published publicly with the API freeze. M5 — integration-path decision page and serve
binary manual.


## 26. Context reduction subsystem (`anyinfer.context`)

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
fidelity: module rollup → structural extracts → compact or verbatim files, with optional
app-supplied module digests), `packed` (chunk-level rank-and-pack for sub-document
granularity), and `distill` (map/reduce through the client itself — the only strategy that
spends inference calls, async-first). `auto` dispatches `whole` when the corpus fits, else
`tiered`. `plan()` runs every deterministic strategy and reports what each *would* produce,
discarding the text — a dry run for context preparation, the counterpart to the D42
pre-dispatch preflight, spending nothing.

Reduction is emulation of a larger context window, and emulation announces itself: every
reduction returns full metadata plus a content-free summary, and emits a `ContextReduced`
telemetry event when an observer is supplied. Rendering is deterministic and path-ordered
by default so repeated turns over the same corpus keep a stable prompt prefix (provider
prompt caches, llama-server slot reuse). Passing the previous turn's `ReductionState` back
in as `previous=` gives unchanged documents a rank bonus, so the selected *set* — and
therefore that prefix — stays put unless the corpus actually moved.

**Advanced settings (`ContextTuning`).** Everything algorithmic is a setting on one frozen
record rather than a constant: duplicate collapse, selection order, diversity, query
expansion, corpus centrality, compact fallback, chunk size, rollup share, carry-over bonus.
The same record is the `context` block of the shared configuration file (§15) and the
`--context-*` flags of `anyinfer context`, and the CLI generates its flags from the
dataclass so the three cannot drift. **Defaults reproduce the previous behaviour exactly**;
`ContextTuning.recommended()` is the named preset that turns on the set worth having for a
source-code corpus. The one default that is *on* is exact-duplicate collapse, which is
lossless and announced in the envelope.

**Duplicate collapse.** Byte-identical documents render once with the rest as `<duplicate
identical="true"/>` pointers — lossless, so completeness is preserved. Above
`near_duplicate_threshold`, MinHash-over-banded-signatures grouping collapses merely
*similar* documents too; that loses their differences, so it is opt-in, forfeits
`Reduction.complete`, and never touches a pinned document. Hashing is `hashlib`-based, not
`hash()`-based, because the grouping must be identical across processes.

**Fidelity between extract and verbatim.** With `compact_fallback`, a document that will
not fit whole is retried with comments, docstrings, and blank runs removed
(`<file-compact elided_lines="N">`) before it is dropped. Only whole-line comments are
removed: stripping a trailing `//` needs a parser this subpackage deliberately does not
have, and getting it wrong corrupts code rather than shortening it.

**Ranking** is lexical (a BM25-style scorer with path-match boosting and anchor-file
bonuses). Three settings narrow the vocabulary-mismatch gap without an index or a model:
identifier splitting (`resolveCredentials` → also `resolve`, `credentials`),
pseudo-relevance feedback (rank, harvest distinctive terms from the top documents, re-rank),
and import-graph centrality — a query-*independent* signal, and therefore what orders a
corpus when the query is weak or absent, where the plain ranker falls through to the path
tie-break. Embeddings-based ranking remains out of scope (a §2 non-goal; open question 8) —
the ranker protocol accepts a replacement when that changes.

**Envelope versioning.** Both wrappers carry `format="1"`. Version 1 is the first to declare
itself; an envelope with no `format` attribute predates the duplicate and compact elements.
The version is bumped when an existing element's meaning changes, not when one is added,
since a reader that ignores unknown elements survives additions. Selection charges the
wrapper's cost in tokens as well as bytes — counting it in bytes alone let a reduction
render a handful of tokens over the budget it had just checked.

**History compaction (`compact_history`).** The corpus strategies reduce what an app
*collected*; this reduces what it *produced*. In an agentic loop the window goes to tool
results, and a transcript past the budget is the most common way a working application
starts failing. Three passes over the unprotected middle, cheapest loss first: tool-result
payloads elided, then text payloads, then plain messages dropped. Each pass stops the
moment the request fits, so the least-recent turns are elided and whatever is still
affordable is left whole. System messages and the recent window are never touched, and a
message carrying a `ToolCall` or `ToolResult` is never dropped — only emptied — because
half a pairing turns an oversized request into a rejected one. A conversation whose
protected messages alone exceed the budget comes back with `fits=False` rather than
mutilated: giving up a system prompt is the application's decision. It is a pure
`Sequence[Message] → HistoryCompaction` function that issues no calls; placement stays with
the caller, exactly as the envelope's does.

## 27. Context policy is the client's, not a frontend's

*Amends §26 and the §2 non-goal clarification.*

The overflow question — "this prompt does not fit" — has exactly two answers: send it
somewhere with a bigger window, or make it smaller. The router has always owned the first
(`context_gate` → `ContextLengthError` → `Route.context_window_targets`), and it owns it at
the **client** layer, which is why the Python API, the CLI, and the sidecar have always
behaved identically about it: all three are the same `AsyncClient` wearing different skins.

`HistoryPolicy` puts the second answer at that same layer, for the same reason. It is a
field on `AsyncClient`/`Client` and, per request, on `GenerationRequest.history`. The
sidecar implements none of it: it decodes an `anyinfer_history` object into that field and
hands the request to the client, staying the codec ADR-009 requires. `anyinfer run` and the
tool loop inherit it with no wiring of their own.

- **`last_resort`** (the default shape) changes nothing until every target, including the
  overflow chain, is exhausted; only then is one compaction pass attempted and the route
  retried once. Losing history is worse than using a bigger model, so it is the floor
  rather than the first move.
- **`proactive`** compacts to fit the resolved target before the gate can refuse it. One
  fewer failed preflight, at the documented cost that a larger-window target further down
  the route is never reached — there is no longer an overflow to redirect.

Two rules keep it from being a silent truncation. It is **off unless configured**: no
policy means today's behaviour, which is to reroute or fail. And it **announces itself** —
every compaction emits `ContextReduced(strategy="history")`, content-free like every other
event. Two guards keep it from being pointless: an unknown context window is never
compacted against (unknown stays unknown — the client will not invent a window to justify
discarding a conversation), and neither is a window whose output reserve leaves no input
allowance, since there is nothing to compact *into*.

**Corpus reduction uses the same client-layer rule when the caller supplies the corpus.**
The earlier exclusion conflated collection with reduction. A remote caller that places
documents in `anyinfer_context` has already collected, reviewed, and deliberately approved
those bytes; the sidecar decides only what fits, exactly as `anyinfer.context.select` does
in-process. Reduction therefore runs after target resolution and before the context gate,
while the sidecar remains a decoder. The real constraints are bandwidth and state: request
payloads are bounded, inference-spending `distill` is excluded, and no document, corpus id,
or cache survives the response. Upload-once/reference-later corpus storage remains outside
the sidecar permanently because it would make the frontend a stateful second core.

Arena follows the same client-policy rule as history. `ArenaPolicy` may be configured on a
client or carried by one request; the CLI and sidecar only decode it and the client alone
fans out, selects, accounts, and emits telemetry. The shape is fixed and candidates remain
independent through their final turns. A named sidecar arena is still the same client
policy selected through configuration, not frontend orchestration.

The event contract cannot currently recover provider usage for a failed attempt. Therefore
an arena with any failed candidate reports its aggregate usage as unknown rather than
summing only successful candidates into a falsely authoritative total. Calls, successful
candidate usage, and attempt trails remain visible; provider invoices remain authoritative
for failed-attempt billing.

## 28. Embedding and reranking operations (`EmbeddingRequest`/`RerankRequest`)

*Amends §2 goal 11 and the multimodal non-goal.* Implemented. The implementation plan this
section grew from was retired once its work landed; its full text, per-item audit, and
progress log are in git history (`plans/EMBEDDING_RERANKING_CONTINUATION.md`, last version
at commit `b36bb4e`). Everything below is the durable record.

Embeddings and reranking are stateless inference operations, typed and routed on the same
terms as generation (ADR-017) but never folded into `GenerationRequest`. `EmbeddingRequest`
carries non-empty ordered text inputs, an optional input intent (`query`/`document`/
`classification`/`clustering`), optional requested dimensionality, and an optional
`expected_space` contract; `EmbeddingResult` returns vectors in input order alongside the
concrete `EmbeddingSpace` that produced them. `RerankRequest` carries a query and a
caller-owned ordered document collection (opaque ids, unique per request); `RerankResult`
preserves original index and document id on every ranked item so a malformed provider
response can never be silently attributed to the wrong document.

**Batching is core policy, never adapter behavior** (extending ADR-003): a `BatchPolicy`
bounds concurrency and whether splitting is allowed at all; splitting only occurs from a
discovered, cataloged, probed, or override limit — an unknown limit means one bounded
request, never a guessed provider maximum. Embedding batch failure is all-or-error: a
partial internal-batch failure never becomes an `EmbeddingResult` missing vectors. Reranking
is not naively batched and concatenated, because scores from separate document batches are
not assumed globally comparable (ADR-018) unless a provider documents otherwise.

**Retrieval-infrastructure boundary.** AnyInfer produces vectors and rankings; it does not
persist them, build an index, crawl a corpus, or decide what an application sends to a model.
A small, separately-packaged, single-process vector store exists as an optional add-on
built entirely on these public types (§29), explicitly scoped to
personal/prototype-sized corpora and never marketed as a scalable or clustered vector
database (§29) — that remains a deployment the application brings, fed by this operation
layer the same way any other consumer is.

**Sidecar.** `POST /v1/embeddings` is a shared OpenAI-compatible codec, implemented
alongside (not inside) the chat-completions codec, over `AsyncClient.embed`. Reranking has no
established OpenAI-shaped wire dialect, so the sidecar exposes an AnyInfer-native
`POST /v1/anyinfer/rerank` route rather than emulating a specific vendor's rerank endpoint.
Both inherit the existing loopback-only, redaction, and payload-privacy rules (§12, §14) and
add request-size limits suited to large document/vector payloads. Both remain thin wire
codecs over public client APIs, never a second policy layer, on the same terms ADR-009
establishes for chat completions.

**Context reduction boundary unchanged.** `anyinfer.context.select()` may accept a caller-
supplied semantic ranker built on `embed()`, but its default stays lexical and offline
(ADR-011); nothing here makes an embedding provider a hidden dependency of context reduction.

### 28.1 Scope boundary

**Included:** text embeddings, scalar and batch; query/document intent where providers
distinguish it; provider-native dimensionality reduction; reranking one query against a
caller-supplied ordered document collection (text plus caller-owned ids and metadata, with
only text sent unless a provider option asks for more); usage, provider-native billing
units, centrally computed cost where pricing is known, timing, attempt trails, warnings,
and optional raw retention; core-owned batching against verified limits; operation-aware
discovery, capabilities, routing, and fallback; semantic-ranker injection into context
reduction through the client-side helper (`anyinfer.semantic_ranker`).

**Excluded:** vector databases, ANN indexes, persistence, corpus lifecycle, and retrieval
services (§29); automatic embedding of `ContextDocument` values; opaque automatic model
selection; cross-model vector conversion; training, fine-tuning, and evaluation;
image/audio/multimodal embeddings; streaming vectors or incremental rerank results — both
operations are buffered.

### 28.2 Operation decisions

Resolved during implementation and binding on later work:

1. Embeddings and reranking are **core inference primitives**, not provider options, and
   support is declared **per operation** — retrieval-only providers are first-class (TEI,
   Voyage, and Jina exist as proof).
2. Cross-target embedding fallback requires **provable space equivalence**: refused
   pre-dispatch unless the target is an identical `provider:model`, with an
   `allow_incompatible_fallback` opt-in that always warns (ADR-018).
3. Scores from separate rerank batches are **never assumed globally comparable** —
   `rerank_cross_batch` refuses by default and warns when overridden.
4. `Usage` stays operation-neutral: billed search units are `Usage.search_units` and are
   **never encoded as tokens** (`Pricing.per_search_unit` prices them). Because an
   embedding call has no completion tokens by construction, a provider reporting only
   `total_tokens` has that read as input tokens for embeddings **only** — never for rerank.
5. **No new exception types.** The embed/rerank failure classes raise `ConfigError` with
   distinguishing messages, and those message contracts are documented in the error
   catalog (`docs/reference/errors.md`).
6. **No novice embedding aliases** (`embed-small` and friends). Revisit only when each
   alias would resolve to one verified hosted *and* one verified local target.
7. The catalog describes embedding models with a `kind` on the existing model table rather
   than a parallel artifact section, because acquisition is identical and only
   interpretation differs (§13). An embedding row states `dimensions` and
   `max_input_tokens` and nothing else: the remaining capability fields are
   provider-specific or measurable, and `probe_embedding()` measures those. The
   `small`/`medium`/`large` ladder is a generation-model ladder, and the catalog validator
   refuses an alias that points at an embedding model.
8. Per-provider evidence questions — normalized vectors, intent spellings, stable model
   ids, trustworthy limits, billing units — are answered in dated contract snapshots as
   each provider lands, never in prose alone.

## 29. Vector store add-on (`anyinfer-store`)

*Implemented.* A separate package, not a core change; its plan retired once the work landed
and its full text is in git history (`plans/VECTOR_STORE_ADDON.md`, last version at commit
`b36bb4e`).

### 29.1 Why a separate package

The core produces vectors and rankings; it does not persist them (§28.1). A store built
*on* the public `embed()`/`rerank()` types does not move that line, but a store built
*into* the core would. So `anyinfer-store` ships as its own distribution with its own
`pyproject.toml`, depending on `anyinfer` and never the reverse — the packaging shape §30.1
established for every optional piece. Nothing in core imports it, and removing it removes
the feature entirely rather than leaving a stub.

### 29.2 The scale ceiling is stated first, not in a caveats section

It is for personal and prototype-sized corpora: single-process, single-file, brute-force
cosine similarity in pure Python, no approximate index, no clustering, no concurrent
writers. The published guide says so in its opening paragraph. This is the discipline that
keeps "batteries included" pressure (R10) from turning an honest small tool into an
implied-scalable database — a claim the implementation would not survive.

### 29.3 Resolved by the implementation

- On-disk format is SQLite: one table for the bound `EmbeddingSpace`, one for entries, with
  vectors packed as `array.array('d')` BLOBs and metadata as JSON text.
- **No approximate index was built.** The design record's framing was "add one only if
  benchmark evidence shows it's needed", and no such evidence exists yet; brute force is
  the whole v1 backend. This is the cost the package deliberately does not pay in advance.
- A store binds the `EmbeddingSpace` that filled it and refuses vectors from another, which
  is §28's same-space rule enforced at the persistence boundary rather than restated.

## 30. Confidential execution tiers (`anyinfer-confidential`, `local/attestation.py`)

*Tiers 1-4 implemented.* Its plan retired once the work landed; full text, research
findings with sources, and the dated decision record are in git history
(`plans/TIERED_ENCRYPTED_PLANS.md`, last version at commit `b36bb4e`).

### 30.0 The problem this answers, and the one it does not

Two confidentiality problems are easily confused, and only the second is in scope.
Protecting the *customer's* data from AnyInfer is already answered: the call goes from the
caller's process to the provider the caller configured, AnyInfer is never a proxy, and
redaction keeps secrets out of logs, errors, and events. What needed building is protecting
the *vendor's* prompt IP — templates, orchestration, few-shot curation — when the vendor's
software runs on the customer's own infrastructure. The customer owns the machine, the OS,
and the network, so no purely client-side technique produces a cryptographic guarantee. The
honest ceiling is raising cost and friction (Tiers 1-2) up to the one case where a real
guarantee exists (Tier 3).

**Every tier states its ceiling in its own first paragraph**, the way §29.2 does. A tier
that oversells is worse than no tier.

### 30.1 Packaging

`src/anyinfer-confidential/` and `src/anyinfer-shared/`, each with its own
`pyproject.toml`, hyphenated directory and underscored importable package,
`anyinfer-confidential` depending on `anyinfer` and never the reverse, `anyinfer-shared`
imported by neither core nor the add-on's dependents by accident. Tiers 1 and 2 touch
prompt content, which core's non-goals forbid core from doing, so they cannot live in core;
Tiers 3 and 4 do not touch prompt content at all and extend `anyinfer/local/` directly.

### 30.2 Tier 1 — `SealedTemplate`: encrypted-at-rest prompt assets

Template plaintext never lives on disk unencrypted. A build step seals templates into an
opaque asset; at runtime the vault decrypts one into memory immediately before rendering
and discards it — overwritten where the runtime allows, not merely dereferenced.

**Protects against** static extraction: unzipping the bundle, grepping the binary, reading
the asset. **Does not protect against** live network capture, memory inspection of a
running process, or a debugger attached to a live render.

Decryption is gated on a vendor-issued entitlement, which doubles as a licensing hook: an
install without a valid entitlement cannot produce prompts at all. Entitlement is hybrid —
an offline signed Ed25519 license blob always applies, with opt-in online revocation
defaulting to **fail-open to the cached answer**, and a `revocation_fail_closed` override
for vendors who want the stricter posture. Keys rotate via `key_id`, so a compromised
historical build's key does not decrypt current templates.

### 30.3 Tier 2 — Relay: zero-retention remote prompt assembly

An optional service owning prompt *orchestration* — which templates fire in what order,
routing, example selection — so that logic never ships to the client. The client sends
structured slot-fill inputs; the relay assembles the request server-side.

**Protects** the pipeline, the part of the IP a single captured request would not reveal.
**Costs** the vendor's re-entry into the customer's data path for that call, which trades
directly against the BYOK posture in §30.0. That tension is documented rather than hidden:
what the relay sees (the assembled request, transiently) and what it persists (nothing, by
design and by audit) are both stated, with logs carrying metadata only.

### 30.4 Tier 3 — attested local execution

The only tier with a real cryptographic guarantee, because it targets the local adapters
rather than a cloud call. Where the host exposes a trusted execution environment, the
runtime executes inside it and remote attestation proves that to the vendor's software
before any prompt is sent.

It **fails closed**: a caller who requests confidential execution on a host that cannot
provide it gets a refusal and a typed signal, never a silent downgrade to unattested
execution. A silent downgrade would make the guarantee a lie in exactly the way silent
relay logging would. `confidential_execution_status()` is the one queryable capability
check every other Tier 3 behaviour is built on, and the adapter composes the local
adapters rather than subclassing them.

Market facts that gate what may be *claimed*, and that will move — re-verify on the cadence
`contracts/DRIFT-CHECK.md` applies to provider claims:

- **Lead with H100 and name it.** H200 is architecturally the same Hopper CC stack but no
  hyperscaler doc independently names an H200 confidential-VM SKU the way Azure names
  `NCCadsH100v5-series`; say "architecturally plausible, not SKU-confirmed" rather than
  rounding up.
- **Blackwell/B200 CC is not GA on any hyperscaler** — preview or absent, available only
  through smaller confidential-GPU providers.
- **AWS GPU confidential computing remains unfound** in AWS's own P5/P5en announcements and
  instance pages. Document AWS as unsupported for Tier 3 GPU offload; this is a strong
  negative finding, not proof of absence.
- **The open-source NVIDIA kernel modules (OpenRM) do support Hopper CC**, implementing the
  SPDM attestation protocol; Blackwell platforms *require* them. No driver-choice caveat is
  needed, and OpenRM is the forward-looking default rather than a fallback.
- **Owner decision: invest in real Nitro Enclaves support**, against the original plan's
  "skip for v1" lean — real new scope, since enclaves have no GPU, no persistent storage,
  and vsock-only networking.
- Attestation-quote cryptographic verification is **deliberately not implemented**: this
  environment cannot exercise the positive case against real CC-capable hardware, and
  shipping unverified security-critical code is worse than an honest, documented gap.

### 30.5 Tier 4 — model and weight provenance

Tier 3 proves *where* a prompt ran; Tier 4 proves *what* ran there — that the weights are
the exact artifact the vendor signed, unmodified. It extends the existing manifest
discipline (`local/runtimes.json` already pins runtime build identity;
`GgufArtifact`/`GgufFile` already model the weights) rather than inventing a parallel one,
and reports through an additional field on `ConfidentialExecutionStatus` so callers keep
one place to look.

**Each vendor signs their own manifests with their own keys. AnyInfer never operates a
signing service** — it ships verification tooling and public-key registration only, never
private-key handling. That keeps AnyInfer out of key-custody liability and makes signing
the vendor's own PKI problem.

**Excluded:** any model-integrity claim outside the attested path. Verifying a hash on an
unattested host is a weaker, different claim and must not be marketed as Tier 4.

### 30.6 Considered and not pursued

BYOK fleet governance and allowlisting — deliberately out of scope, not merely unbuilt.

