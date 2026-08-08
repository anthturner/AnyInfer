# AnyInfer — Implementation Guide

Normative build plan. [DESIGN.md](DESIGN.md) explains *why*; this file specifies *what to
build, in what order, and how to know it's done*. Where DESIGN.md says "illustrative", this
file is authoritative. Follow [AGENTS.md](AGENTS.md) rules throughout. Wire-level provider
details live in [contracts/](contracts/) — transcribe them, don't invent them.

**How to use this file:** work the tasks in §D in order. Do not
start a task whose dependencies are unmet. Each task lists the files it creates and its
acceptance criteria; a task is done when its criteria pass under `pytest`. If you must
deviate from a spec here, record the deviation and reason in NOTES.md before proceeding.

---

## A. Project setup (normative)

- Python `>=3.11`. Build backend: `hatchling`. Layout: `src/anyinfer/` per DESIGN.md §18.
- `pyproject.toml`: dependencies `httpx2>=2.0`, `jsonschema>=4.21`. Extras:
  `copilot = ["github-copilot-sdk>=0.1"]`, `azure = ["azure-identity>=1.17"]`,
  `keyring = ["keyring>=24"]`, `otel = ["opentelemetry-api>=1.25"]`, `local = []` (reserved),
  `serve = ["starlette>=0.37", "uvicorn>=0.30"]`,
  `all = [union of the above]`.
- Dev tooling: `pytest`, `pytest-asyncio` (mode=auto), `ruff` (line length 99), `mypy --strict`
  on `src/`. CI runs: ruff, mypy, pytest, docs build (once docs exist).
- All public dataclasses: `@dataclass(frozen=True, slots=True)`. All public modules export
  through `anyinfer/__init__.py` explicitly (`__all__`).

## B. Normative core types

These replace DESIGN.md §5–§8's illustrative sketches. Field names, defaults, and semantics
below are binding. (Imports elided; `Mapping`/`Sequence` from `collections.abc`.)

```python
# ---- content & messages (types/messages.py) ----
Role = Literal["system", "user", "assistant", "tool"]

@dataclass(frozen=True, slots=True)
class Text:
    text: str

@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str                      # provider call id; synthesize "call_0", "call_1"… if absent
    name: str
    arguments: Mapping[str, Any] # parsed JSON object; {} if unparseable (warning added)

@dataclass(frozen=True, slots=True)
class ToolResult:
    call_id: str
    content: str
    is_error: bool = False

ContentPart = Text | ToolCall | ToolResult

@dataclass(frozen=True, slots=True)
class Message:
    role: Role
    content: tuple[ContentPart, ...]

def user(text: str) -> Message: ...        # convenience constructors, exported
def system(text: str) -> Message: ...
def assistant(text: str) -> Message: ...

# ---- request (types/requests.py) ----
@dataclass(frozen=True, slots=True)
class Sampling:
    temperature: float | None = None       # None = provider default; never invent a value
    top_p: float | None = None
    max_output_tokens: int | None = None
    stop: tuple[str, ...] = ()

ReasoningEffort = Literal["minimal", "low", "medium", "high"]

@dataclass(frozen=True, slots=True)
class SchemaSpec:
    json_schema: Mapping[str, Any]         # canonical form
    name: str = "response"                 # some providers require a schema name
    @classmethod
    def coerce(cls, obj) -> "SchemaSpec":  # dict → as-is; has model_json_schema() → call it
        ...

@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    parameters: Mapping[str, Any]          # JSON schema for arguments

@dataclass(frozen=True, slots=True)
class Repair:
    max_attempts: int = 1

@dataclass(frozen=True, slots=True)
class GenerationRequest:
    messages: tuple[Message, ...]
    schema: SchemaSpec | None = None
    tools: tuple[ToolSpec, ...] = ()
    tool_choice: Literal["auto", "none", "required"] | str = "auto"  # str = specific tool name
    sampling: Sampling = Sampling()
    reasoning: ReasoningEffort | None = None
    timeout_s: float | None = None         # per-attempt wall clock; None = 120.0
    max_response_bytes: int = 1_048_576
    provider_options: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    metadata: Mapping[str, str] = field(default_factory=dict)  # opaque; echoed in events

# ---- targets & routing (types/requests.py, routing/policy.py) ----
Target = str   # grammar: ALIAS | PROVIDER ":" MODEL ; PROVIDER = [a-z0-9-]+ (after alias
               # normalization: lower, strip, "_"→"-"); MODEL = rest of string verbatim
               # (models may contain ":" — split on the FIRST ":" only). An ALIAS is any
               # target without ":" that matches a catalog alias; without ":" and not an
               # alias → ConfigError.

@dataclass(frozen=True, slots=True)
class ResolvedTarget:
    provider_id: str
    model: str
    via_alias: str | None = None

@dataclass(frozen=True, slots=True)
class Retry:
    max_attempts: int = 2                  # total attempts per target, incl. the first
    backoff_base_s: float = 0.5
    backoff_max_s: float = 30.0
    retry_on: Callable[["ProviderError"], bool] | None = None

@dataclass(frozen=True, slots=True)
class Route:
    targets: tuple[Target, ...]
    retry: Retry = Retry()
    health_gate: bool = True
    health_ttl_s: float = 30.0

# ---- results (types/results.py) ----
@dataclass(frozen=True, slots=True)
class Usage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None        # if provider omits, compute in+out when both known
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    reasoning_tokens: int | None = None
    cost_usd: Decimal | None = None

@dataclass(frozen=True, slots=True)
class Timing:
    started_at: float                      # time.monotonic() at attempt start (core-measured)
    first_token_ms: float | None = None
    total_ms: float = 0.0
    output_tokens_per_s: float | None = None   # output_tokens / (total_ms - first_token_ms)
    phases: Mapping[str, float] = field(default_factory=dict)

@dataclass(frozen=True, slots=True)
class ErrorInfo:                           # serializable snapshot of a ProviderError
    type_name: str
    provider: str | None
    phase: str
    retryable: bool
    http_status: int | None
    detail: str                            # already redacted, ≤512 chars

@dataclass(frozen=True, slots=True)
class AttemptRecord:
    target: ResolvedTarget
    outcome: Literal["ok", "retried", "failed", "skipped_unhealthy"]
    error: ErrorInfo | None = None
    timing: Timing | None = None

FinishReason = Literal["stop", "length", "tool_calls", "content_filter", "other"]
Mechanism = Literal["grammar", "json_schema", "json_mode", "prompt"]

@dataclass(frozen=True, slots=True)
class Generation:
    text: str
    structured: Any | None
    tool_calls: tuple[ToolCall, ...]
    target: ResolvedTarget
    finish_reason: FinishReason
    usage: Usage
    timing: Timing
    structured_mechanism: Mechanism | None = None
    repair_attempts: int = 0
    attempts: tuple[AttemptRecord, ...] = ()
    warnings: tuple[str, ...] = ()
    raw: Any | None = None                 # only populated when client(retain_raw=True)

# ---- stream events (types/events.py) ----
@dataclass(frozen=True, slots=True)
class TextDelta:
    text: str
@dataclass(frozen=True, slots=True)
class ReasoningDelta:
    text: str
@dataclass(frozen=True, slots=True)
class ToolCallDelta:
    index: int                             # tool-call slot index within the response
    call_id: str | None
    name: str | None
    arguments_fragment: str                # concatenate fragments per index, then JSON-parse
@dataclass(frozen=True, slots=True)
class UsageUpdate:
    usage: Usage
@dataclass(frozen=True, slots=True)
class TimingMark:
    name: Literal["attempt_start", "first_token"]
    at_ms: float                           # ms since attempt start
@dataclass(frozen=True, slots=True)
class AttemptFailed:
    record: AttemptRecord
@dataclass(frozen=True, slots=True)
class StreamEnded:
    result: Generation

StreamEvent = (TextDelta | ReasoningDelta | ToolCallDelta | UsageUpdate
               | TimingMark | AttemptFailed | StreamEnded)
```

**Event-stream ordering guarantees (binding; conformance-tested):**
1. Zero or more `AttemptFailed` may precede content (failed targets/retries).
2. Per successful attempt: `TimingMark("attempt_start")` first; `TimingMark("first_token")`
   exactly once, immediately before the first `TextDelta`/`ReasoningDelta`/`ToolCallDelta`.
3. `StreamEnded` is always the final event, exactly once, even after errors mid-stream are
   recovered by fallback. Unrecoverable failure raises instead of yielding `StreamEnded`.
4. Text reconstructed by concatenating `TextDelta.text` equals `StreamEnded.result.text`.

```python
# ---- adapter contract (providers/base.py) ----
@dataclass(frozen=True, slots=True)
class WireRequest:                         # what adapters receive; fully resolved
    model: str
    messages: tuple[Message, ...]
    sampling: Sampling
    reasoning_wire: Mapping[str, Any]      # already translated by descriptor's translator
    mechanism: Mechanism | None            # chosen structured-output mechanism
    wire_schema: Mapping[str, Any] | None  # already projected for this provider
    schema_name: str | None
    tools: tuple[ToolSpec, ...]
    tool_choice: str
    stream: bool                           # hint; adapter may ignore (core handles both)
    timeout_s: float
    max_response_bytes: int
    extra_options: Mapping[str, Any]       # provider_options[this provider] verbatim

# Adapter events are a SUBSET of StreamEvent: TextDelta, ReasoningDelta, ToolCallDelta,
# UsageUpdate, plus the terminal:
@dataclass(frozen=True, slots=True)
class AdapterFinal:
    finish_reason: FinishReason
    usage: Usage | None
    phases: Mapping[str, float]            # provider-reported phase timings, ms
    raw: Any | None
AdapterEvent = TextDelta | ReasoningDelta | ToolCallDelta | UsageUpdate | AdapterFinal

@runtime_checkable
class ProviderAdapter(Protocol):
    descriptor: ClassVar["ProviderDescriptor"]
    async def list_models(self) -> Sequence["DiscoveredModel"]: ...
    async def health(self) -> "Health": ...
    def generate(self, req: WireRequest) -> AsyncIterator[AdapterEvent]: ...
    async def aclose(self) -> None: ...

@dataclass(frozen=True, slots=True)
class Health:
    ok: bool
    detail: str = ""

@dataclass(frozen=True, slots=True)
class DiscoveredModel:
    id: str
    capabilities: "ModelCapabilities | None" = None   # discovered-provenance fields only
```

Capability types (`Sourced[T]`, `Feature`, `ModelCapabilities`, `Pricing(input_per_1m: Decimal,
output_per_1m: Decimal, currency="USD")`, `LocalModelInfo(artifact_size_bytes, parameter_size,
quantization, est_ram_bytes, est_vram_bytes, observed_vram_bytes)`) follow DESIGN.md §7
verbatim. Descriptor/setup-spec types follow DESIGN.md §8 verbatim plus:
`ProviderSetupSpec(fields: tuple[SetupField, ...], model_selection:
Literal["discover-or-manual","manual-only"], host_shorthand: HostShorthand | None,
any_of: tuple[tuple[str, ...], ...], requirement_note: str)` exposing
`essential_fields` / `advanced_fields`;
`SetupField(key, label, kind, required, help_text, placeholder, advanced, default_value)`
with `kind ∈ {"endpoint","secret","api-version","model-list","reasoning-efforts",
"host-profile"}`; `HostShorthand(scheme: str, default_port: int)`.

`advanced` splits the fields by *prominence*: a field the provider already has a working
value for (`default_value`) folds behind a disclosure, leaving only what the user alone
can answer in front of them. It is rejected at construction alongside `required` or
`any_of` membership, since a UI that honors the disclosure would otherwise refuse a save
naming a field that is not on screen.

## C. Normative algorithms

### C1. Target resolution (`registry.py` + `catalog/resolve.py`)
```
resolve(target, registry, catalog, provider_id_hint=None) -> ResolvedTarget:
1. s = target.strip()
2. if ":" in s:
     provider_raw, model = s.split(":", 1)
     provider_id = registry.resolve_alias(normalize(provider_raw))   # unknown → ConfigError
     return ResolvedTarget(provider_id, model, via_alias=None)
3. if catalog.has_alias(s):
     candidates = catalog.targets_for_alias(s)          # {provider_id: entry}
     pick the first candidate whose provider is configured on this client, in the
     client's configured-provider order (deterministic)  # none → ConfigError w/ hint
     return ResolvedTarget(provider_id, entry.model_or_gguf_ref, via_alias=s)
4. raise ConfigError(hint="use 'provider:model' or a catalog alias; known aliases: …")
```

### C2. Router generate loop (`routing/` + `_client/async_client.py`)
```
async def _routed_stream(request, route) -> AsyncIterator[StreamEvent]:
  attempts = []
  for target in route.targets:
    rt = resolve(target)
    if route.health_gate and health_cache.recently_failed(rt, route.health_ttl_s):
        attempts.append(AttemptRecord(rt, "skipped_unhealthy")); continue
    for attempt_n in 1..route.retry.max_attempts:
        emit TimingMark("attempt_start"); t0 = monotonic()
        try:
            wire = build_wire_request(request, rt)        # C4 mechanism + projection here
            first_token_seen = False; buffers = fresh()
            async for ev in adapter.generate(wire):       # wrapped in asyncio.timeout(timeout_s)
                if ev is content-bearing and not first_token_seen:
                    first_token_seen = True
                    emit TimingMark("first_token", (monotonic()-t0)*1000)
                if isinstance(ev, AdapterFinal): final = ev
                else: accumulate(buffers, ev); emit ev    # re-emit deltas verbatim
            result = assemble_generation(buffers, final, rt, t0, attempts)   # C3 validation
            attempts.append(AttemptRecord(rt, "ok", timing=result.timing))
            emit StreamEnded(result); return
        except ProviderError as e:
            rec = AttemptRecord(rt, "retried" if retryable_and_budget_left else "failed",
                                error=snapshot(e), timing=partial_timing())
            attempts.append(rec); emit AttemptFailed(rec)
            if retryable(e) and attempt_n < max_attempts:
                await sleep(min(max(backoff_base * 2**(attempt_n-1), e.retry_after_s or 0),
                                backoff_max)); continue
            health_cache.mark_failed(rt) if isinstance(e, (TransportError,
                                ProviderUnavailableError)); break   # next target
  raise AllTargetsFailedError(attempts=attempts)
```
Retryability: `e.retryable` unless `route.retry.retry_on` overrides. Timeout of an attempt
→ `TransportError(retryable=True)`. Mid-stream `StreamProtocolError` after content was
emitted: do NOT fall back silently (consumer already saw text) — record and raise unless
zero content events were emitted, in which case treat as a normal retryable failure.

### C3. Structured-output validation & repair (`schema/`)
```
assemble_generation(...):
1. text = concat(TextDelta); tool_calls = merge ToolCallDelta by index (concat fragments,
   json-parse arguments; parse failure → arguments={}, warning added)
2. if request.schema is None: structured=None; skip to usage/cost.
3. candidate = extract_json(text):  try json.loads(text); on failure, try the largest
   {...} or [...] substring (first-balanced scan); on failure → violation("not JSON")
4. jsonschema.validate(candidate, request.schema.json_schema)
   → on success: structured=candidate
   → on violation: if repair budget remains (client-level or per-call Repair):
        build repair messages = original messages
          + assistant(text)
          + user(REPAIR_PROMPT.format(errors=first_5_validation_errors_as_bullets))
        re-run THE SAME resolved target (not the whole route), repair_attempts += 1
     else raise SchemaViolationError(raw_text=text, errors=…)
REPAIR_PROMPT = "Your previous response did not match the required JSON schema. Errors:\n
{errors}\nRespond again with ONLY a corrected JSON value that satisfies the schema. No
prose, no code fences."
```

### C4. Mechanism selection & schema projection (`schema/mechanism.py`, `project.py`)
```
choose_mechanism(caps: ModelCapabilities | None) -> Mechanism:
  features = caps.features.value if caps else Feature(0)   # unknown → weakest
  GRAMMAR in features → "grammar" ; JSON_SCHEMA → "json_schema" ;
  JSON_MODE → "json_mode" ; else "prompt"
Projection (adapter hook `project_schema(schema) -> Mapping`): default = identity.
ollama/llama-cpp override: deep-copy schema, drop minLength/maxLength everywhere, drop
minItems/maxItems where value >= 2000 (Frisket's rule). "prompt" mechanism: wire_schema
None; core appends to the LAST system message (or prepends one):
"Respond with ONLY a JSON value matching this JSON Schema. No prose. Schema:\n{schema}".
"json_mode": wire response_format json_object + same system-prompt injection.
Original schema ALWAYS validates client-side regardless of mechanism.
```

### C5. Sync facade (`_client/sync_client.py`)
```
Client.__init__: threading.Thread(daemon=True) runs asyncio.new_event_loop() forever;
AsyncClient constructed ON that loop (run_coroutine_threadsafe, wait).
generate(): run_coroutine_threadsafe(async_generate(...)).result(timeout=None) —
  KeyboardInterrupt in the waiting thread → future.cancel() → loop cancels the task →
  httpx2 stream closed via async context manager unwind → re-raise KeyboardInterrupt.
stream(): returns SyncStream (context manager + iterator) backed by a
  queue.Queue(maxsize=256); a loop-side task pumps events into the queue; SENTINEL on end;
  exceptions are put on the queue and re-raised in the consumer thread.
  Early close (context exit before drain) → cancel pump task, drain queue.
close()/atexit: cancel pending tasks, aclose() adapters, stop loop, join thread (5s cap).
```

### C6. SSE / NDJSON parsing (`providers/sse.py`)
```
SSE: split on "\n\n" record boundaries across chunk fragments (carry partial buffer);
lines starting ":" are comments → ignore (OpenRouter keep-alives); accumulate multi-line
"data:" fields joined by "\n"; "data: [DONE]" → end; enforce max_response_bytes across
TOTAL streamed bytes → StreamProtocolError on excess. Yield parsed JSON objects.
NDJSON (ollama): one JSON object per line; partial-line buffering; same byte cap.
```

### C7. Capability assembly (`capabilities/assemble.py`)
```
capabilities_for(provider_id, model) -> ModelCapabilities:
  start = descriptor.static_capabilities.get(model)            # provenance "catalog"
  overlay discovered fields from cached list_models() metadata # provenance "discovered"
  overlay probe results if operator ran probes                 # provenance "probed"
  unknown fields stay None; features fall back to descriptor-level defaults with
  provenance "default".
  model == "auto" (or descriptor marks delegating): conjunction over candidate set —
  min(context_window), min(max_output_tokens), intersection of features.
```

### C8. Redaction & events (`events/`)
```
RedactionRegistry: register(secret: str) for every resolved credential (len ≥ 6);
redact(text) replaces each registered secret with "•••" + last4? NO — replace fully with
"[redacted]". Applied to: ErrorInfo.detail, all event string fields, log lines.
Observer protocol: class Observer(Protocol): def on_event(self, event: TelemetryEvent) -> None
(sync, non-blocking; exceptions from observers are swallowed + warned once).
Registration: AsyncClient(observers=[...]) or client.subscribe(obs, payloads=False).
TelemetryEvent set per DESIGN.md §14; payload-carrying fields (prompt/response text) are
None unless the observer registered payloads=True.
```

### C9. Tool loop (M4, `_client/tools.py`)
```
@ai.tool decorator: derives ToolSpec from signature + docstring (params → JSON schema via
annotations; only str/int/float/bool/list/dict supported in v1).
run_tools(messages, tools, target, max_rounds=8):
  loop: result = generate(messages, tools=specs)
        if result.finish_reason != "tool_calls" or no tool_calls: return result
        for call in result.tool_calls (sequentially):
            out = registered_fn(**call.arguments)  → ToolResult(call_id, str(out))
            exceptions → ToolResult(is_error=True, content=f"{type}: {msg}")
        messages += assistant(tool_calls) + tool results
  rounds exhausted → ToolLoopError(hint="raise max_rounds or simplify tools")
```

## D. Task plan

Legend: each task = **id · name → files · [depends on]** then acceptance criteria (AC).
Milestones M0–M5 per DESIGN.md §19. Work strictly in order within a milestone; tasks in
different milestones may not be reordered across milestone boundaries.

### M0 — skeleton

- **T0.1 · project scaffold** → `pyproject.toml`, `src/anyinfer/__init__.py`, CI config ·
  [none]. AC: `pip install -e .[all]` succeeds; ruff/mypy/pytest run clean on empty suite.
- **T0.2 · types** → `types/*` per §B · [T0.1]. AC: all §B types importable from
  `anyinfer`; mypy strict passes; equality/immutability unit tests.
- **T0.3 · errors** → `errors.py` per DESIGN.md §10 + `ErrorInfo.snapshot()` · [T0.2].
  AC: hierarchy matches §10 exactly; every error carries the six structured fields;
  `detail` truncated to 512 chars.
- **T0.4 · redaction + events** → `events/*` per §C8 · [T0.3]. AC: registered secrets never
  appear in any emitted event/error detail (property test); observers receive lifecycle
  events; payload fields None unless opted in; observer exceptions don't propagate.
- **T0.5 · credentials** → `credentials/*` · [T0.4]. AC: literal, `env://NAME`,
  `credential://…` (keyring extra) resolve; unresolvable → CredentialError with hint;
  resolved values auto-register for redaction; missing keyring extra → ConfigError with
  install hint.
- **T0.6 · registry** → `registry.py` (descriptor, setup spec, alias normalization,
  collision-safe registration, entry-point loading) · [T0.2]. AC: duplicate id/alias
  rejected; `"claude"`→`"anthropic"`-style alias resolution; entry-point group
  `anyinfer.providers` discovered lazily (test via a dummy package fixture).
- **T0.7 · schema subsystem** → `schema/*` per §C3/C4 · [T0.2]. AC: dict + duck-typed
  pydantic accepted; mechanism ladder correct for synthetic capability sets; projection
  rules for ollama-style limits; extract_json handles fenced/prose-wrapped JSON; repair
  prompt matches §C3 template.
- **T0.8 · SSE/NDJSON parser** → `providers/sse.py` per §C6 · [T0.2]. AC: fragmented
  chunks reassemble; comment lines ignored; `[DONE]` terminates; byte cap raises
  StreamProtocolError; NDJSON partial lines handled.
- **T0.9 · fake servers + cassettes** → `testing/fakes.py`, `testing/cassettes.py` ·
  [T0.8]. AC: in-process ASGI fake speaking openai-compat (configurable: streaming,
  errors, malformed SSE, slow first token, usage chunk); cassette record/replay wraps
  httpx2 transport deterministically.
- **T0.10 · openai-compat adapter** → `providers/openai_compat.py` per
  `contracts/openai-compat.md` · [T0.6–T0.9]. AC: passes conformance suite (T0.12)
  against the fake server.
- **T0.11 · router + AsyncClient + sync facade** → `routing/*`, `_client/*` per §C2/C5 ·
  [T0.10]. AC: retry honors retryable/retry-after with capped backoff; fallback proceeds
  in order; health gate skips (TTL respected); attempt trail complete; event ordering
  guarantees §B hold (property test); sync stream survives KeyboardInterrupt and early
  close without hangs (stress test with 8 threads × 50 requests).
- **T0.12 · conformance suite v1** → `testing/conformance.py` · [T0.10]. AC: parametrized
  suite covering every §B ordering guarantee + matrix rows: list_models, health,
  non-streaming, streaming, TTFT, json_schema/json_mode/prompt mechanisms, client-side
  validation, tool-call types, usage, retry-after, error mapping; runs in fake + cassette
  modes; documented harness for third-party adapters.
- **T0.13 · serve-invariant round-trip tests** → `tests/test_openai_roundtrip.py` ·
  [T0.11]. AC: OpenAI chat-completions request JSON → GenerationRequest → back, lossless
  for: messages, tools, tool_choice, response_format.json_schema, temperature, top_p,
  max_tokens, stop, stream flag; chunk reconstruction from StreamEvents matches a
  reference chunk sequence (ADR-009 invariants 1–3).
- **T0.14 · docs skeleton** → `docs/`, mkdocs config, quickstart, concepts stubs ·
  [T0.11]. AC: docs build in CI; docstring-coverage gate on public API; quickstart
  example executes against fake server.

### M1 — core four + local subsystem (pilot: mote-cli)

- **T1.1 · ollama adapter** → `providers/ollama.py` per `contracts/ollama.md` ·
  [M0]. AC: conformance vs fake ollama (NDJSON); phase timings mapped to Timing.phases
  (ns→ms); `format` schema mechanism; GPU-spill warning from /api/ps deltas.
- **T1.2 · hardware detection** → `local/hardware.py`, `local/backends.py` · [T0.1].
  Port mote's detection (widest coverage) + ModelFit's advisory semantics; disk cache
  keyed by probe signatures; `ANYINFER_HARDWARE_CACHE_BYPASS/_REFRESH`. AC: never raises
  (returns warnings); cache invalidates on signature change; unit tests with mocked
  probes for windows/linux/macos × cpu/nvidia/amd/apple paths.
- **T1.3 · gguf catalog + downloads** → `local/gguf.py`, `local/downloads.py` · [T0.1].
  AC: sha256 verify, atomic rename, filelock, resume, sharded files, progress events
  (`DownloadProgress`); license allowlist (MIT/Apache-2.0) for user-added entries.
- **T1.4 · tuning** → `local/tuning.py` · [T1.2]. Port Frisket's tuner: postures,
  KV-bytes/token table, context ladder (8192/16384/32768/65536), q8_0 under aggressive.
  AC: golden-file tests: (hardware profile × posture × model) → expected ServerPlan flags.
- **T1.5 · llama-server supervisor** → `local/server.py` · [T1.3, T1.4]. AC: spawn →
  /health poll → ready; crash detected and reported with log tail; graceful shutdown;
  loopback-only unless `allow_remote_exposure=True`; Windows process-tree termination
  test.
- **T1.6 · llama-cpp adapter** → `providers/llama_cpp.py` per contract · [T1.5, T0.10].
  AC: end-to-end vs a real llama-server in CI (tiny GGUF, cpu backend); grammar
  mechanism; conformance suite passes.
- **T1.7 · alias catalog** → `catalog/*` + bundled `default.json` · [T0.6]. AC: schema
  validation; overlay merge (app wins); resolution per §C1; hardware→tier
  `local/recommend.py` driven by catalog metadata (est_ram/vram vs detected).
- **T1.8 · copilot adapter** → `providers/copilot.py` per contract · [M0]. AC:
  conformance vs mocked SDK; `auto` conjunction capabilities; usage from events; missing
  extra/CLI → actionable ConfigError.
- **T1.9 · session reuse API** (open question 2 — design then implement) · [T1.1, T1.8].
  AC: recorded decision in NOTES.md; ollama keep_alive + copilot resume behind one
  interface; off by default.
- **T1.10 · migrate mote-cli** (in `../mote-cli`, separate change set) · [T1.1–T1.9].
  AC: mote's engines/ deleted; its CLI behavior preserved (its test suite passes);
  migration guide drafted.

### M2 — hosted breadth (pilot: Frisket)

- **T2.1 · openai adapter** (Responses API per contract) · **T2.2 · anthropic adapter**
  (per contract; thinking-delta TTFT rule) · **T2.3 · azure-foundry adapter**
  (openai-compat subclass; Entra credential provider behind `[azure]`) · [M0 each].
  AC each: conformance in fake + cassette modes; contract file updated w/ live
  verification (run the drift check first — see AGENTS.md).
- **T2.4 · OTel bridge** → `otel.py` · [T0.4]. AC: no otel import unless enabled; spans
  per request/attempt, GenAI semconv attribute names; events mirrored.
- **T2.5 · capability probes** (basic) → `capabilities/probes.py` · [T2.1–T2.3]. AC:
  opt-in probe measures context acceptance + schema-mechanism support; provenance
  "probed" overrides.
- **T2.6 · migrate Frisket** · AC: Frisket providers/ deleted except its app glue; its
  JSONL trail implemented as an Observer; schema/repair parity verified against its
  existing test fixtures.

### M3 — long tail (pilot: ModelFit)

- **T3.1 · openrouter adapter** (verify contract live first — it's greenfield) ·
  **T3.2 · m365-copilot adapter** (transcribe Frisket's routes into the contract, then
  port) · **T3.3 · migrate ModelFit** (evidence pipeline as Observer; its providers/
  deleted). AC: conformance; matrix `?` cells resolved for these columns.

### M4 — tool loop + freeze

- **T4.1 · tool loop** per §C9. AC: sequential dispatch; error-carrying ToolResults;
  round bound; conformance additions for tool_calls finish path.
- **T4.2 · API freeze review** — every `?` in the matrix resolved or documented ➖;
  deprecation policy written; docs complete (cookbook, error catalog); publish.

### M5 — sidecar + binaries

- **T5.1 · codec** → `serve/openai_codec.py` (reuses T0.13 round-trip tests) ·
  **T5.2 · ASGI app** → `serve/app.py` (auth token, loopback default, /v1/models from
  catalog+registry) · **T5.3 · `anyinfer serve` CLI + shared config-file loading** ·
  **T5.4 · PyInstaller onedir builds + native CI smoke tests** (ADR-010) ·
  **T5.5 · signing/notarization pipeline** (external release-infrastructure follow-up;
  0.1 beta artifacts are checksummed but unsigned). AC: an unmodified
  `openai` Python client pointed at the binary completes streaming + non-streaming +
  structured requests against both a hosted target and a local llama-cpp alias.

## E. Verification ledger

Global "done" checks, run at every milestone boundary:
1. Conformance suite green in fake + cassette modes for every implemented adapter.
2. Event-ordering property tests green (§B guarantees).
3. Round-trip serve-invariant tests green (ADR-009).
4. No adapter module imports `routing`, `schema.validate`, `schema.repair`, or `events`
   (architectural lint — enforce with an import-linter contract).
5. Redaction property test green (no registered secret in any output channel).
6. `mypy --strict` and ruff clean; docs build green; docstring coverage 100% of public API.
7. Drift check run before starting each adapter task; contract `Last verified` updated.
