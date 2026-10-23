# Rich generation and bounded tools in the C# SDK

Resume from the first unchecked box. This executes SDK.7a/b of
`ANYINFER_CSHARP_SDK.md`; it does not reduce the full-library destination. The user
renewed authorization on 2026-10-22 to continue until both core SDKs are functional
and ready. The coordinator owns Git and serial native/full gates.

## Settled contract

- Python reference baseline remains `199c3f833e568334b629edd7d89f41a3b76efe2a`.
  Current starting source is `cbc4aeb5a4922cb14506d578b90fade87e059942`; executable
  predecessor `a3b0cc785c723616d5e724f7f7b7b20f432ce647` is independently verified.
  Read actual current `types/messages.py`, `requests.py`, `results.py`, `events.py`,
  `providers/base.py`, `_client/{generation,wire,buffer}.py` and focused tests.
  Record meaningful baseline drift explicitly; do not reproduce an observed Python bug.
- Preserve frozen core-generation-v0 and all released assets/comparators, plus accepted
  accounting, request-policy and retrieval profiles. Rich behavior gets a NEW shared
  input-only `tests/fixtures/rich-generation-v1/` profile and independent native observers.
  This is additional behavioral evidence, not a rewritten foundational release.
- Generation remains text/tool output. Media are typed inputs. No image/audio generation,
  autonomous planning, implicit tool approval, or provider SDK/process dependency.
- Public names follow Python with PascalCase members; use `Text.Value` as already settled.
  Add `ImagePart`, `DocumentPart`, `AudioPart`, `VideoPart` using this source matrix:

  | Part | Source and metadata contract |
  | --- | --- |
  | ImagePart | Exactly one of copied inline bytes or URL; image/*; optional detail |
  | DocumentPart | Exactly one of copied inline bytes or URL; nonempty media type; optional filename |
  | AudioPart | Required nonempty copied inline bytes only; audio/*; no URL property |
  | VideoPart | Exactly one of copied inline bytes or URL; video/*; optional offsets/fps |

  Count inline bytes for all four types, and never assign an inline size to URL references.
  Snapshot byte inputs
  into read-only collections (never expose a mutable caller-owned byte array). URL inputs
  are references: the core never fetches them. Do not stringify or log media bytes/URLs.
- Add `Citation`, `TokenLogprob`, `ServerToolUse`, `ServerToolSpec`, `ServerToolSource`,
  `ReasoningDelta`, `CitationDelta`, `ServerToolDelta` and adapter counterparts. String
  kind/effort/status values use Python's literal spellings. Existing ToolCall/ToolResult/
  ToolSpec/ToolAnnotations remain the one public vocabulary. Citation.SpanOf uses Unicode
  scalar positions like Python, including clamping. Preserve null/empty distinctions.
  Keep the existing separate adapter/public event hierarchies: raw counterparts are
  `AdapterReasoningDelta`, `AdapterCitationDelta`, `AdapterServerToolDelta`. Do not fork
  provider protocols or invent runtime event validation absent Python. `ServerToolUse.Uses`
  is `long`, matching usage counts. Add Message.Text as concatenated Text.Value only.
  Tagged native JSON values are immutable; copy container maps and reuse their immutable
  children without serialization/reparse. Media diagnostic strings expose shape only.
- Append request fields with defaults matching Python: `reasoning=null`, namespaced
  `providerOptions`, `metadata`, `logprobs=null` (integer 0..20), `citeDocuments=false`,
  `serverTools=[]`, `maxInputPartBytes=20*1024*1024`, `maxInputBytes=50*1024*1024`.
  Snapshot maps, nested namespace maps, lists and bytes. Validate inline input ceilings
  before dispatch; remote references do not invent an inline byte count. All request
  clone/normalization/repair paths preserve the fields. Async and sync convenience paths
  forward to the same request path without changing existing positional-call meaning.
  Python's frozen dataclasses are shallow; C# defensive snapshots are the native ownership
  guarantee, not a claim of Python deep freezing. Caller-mutation tests are native-only;
  paired profile cases use fixed inputs and do not change Python container semantics.
- Add immutable result `Logprobs`, `Citations`, `ServerToolUses`; reasoning remains a
  separate stream event, never appended to visible answer text. AdapterFinal adds copied
  phase timings, logprobs and server-tool-use counts. Preserve them through terminal
  manifests and WithManifest. Raw remains opt-in; no synthetic streaming raw payload.
- First content means TextDelta, ReasoningDelta or ToolCallDelta, including their existing
  empty-event semantics. Citation/server-tool/usage events alone do not set first-token
  timing or commit the route. Failed/repaired entries cannot leak terminal rich fields
  into a later winning entry. Preserve current early-close/cancellation/failure identity.
- Core constructs WireRequest with reasoning fields, narrowed options, logprobs, citations
  and server tools. Add a descriptor reasoning translator and ignored-parameter metadata;
  also add descriptor-declared `ServerTools` wire support (empty by default). A missing
  reasoning translator returns an empty object. Options merge wildcard then resolved
  instance namespace, matching `_client/wire.py`; adapters overlay explicit extra options
  last. Config construction options remain a separate concept and keep existing admission.
- Capability gates follow actual Python provenance: trusted catalog/discovered/probed/override
  absence can withhold reasoning/logprobs/citations and emits ParameterDropped. Default
  guesses cannot withhold them. Caller override facts are trusted too, matching the actual
  TRUSTED_PROVENANCE constant in capabilities/pricing.py. Media and server-tool requests use the actual Python
  predispatch known-absence/unsupported rules. Unknown media token contribution makes fit
  and spend unknown, never zero. Preserve core ownership of these decisions.
- OpenAI-compatible remains a chat-completions dialect. Implement only Python's existing
  media projections (image, inline document, audio; explicitly refuse video), tool history,
  logprob ask/parse, terminal raw, and extra-options precedence. Do not invent reasoning,
  citations or server-tool wire support that Python's generic adapter does not implement.
  Custom adapters prove the complete normalized event contract independently of this wire.
  > NOTE: 2026-10-22 official file-input guide explicitly excludes file URLs from Chat
  > Completions; its create schema lists file_data/file_id/filename, not file_url. Current
  > Python emits the unsupported file_url field. Adopt the bounded wire correction in BOTH
  > generic chat adapters: reject DocumentPart(url=...) before HTTP with UnsupportedInput,
  > keep DocumentPart URL support in the general domain/other dialects, and never fetch it
  > in core. Add an exact no-send negative. Evidence: `sdk-seven-rich-generation/wire-research`.
  > This preserves frozen text behavior and requires no existing normalized-spec change.
- Bounded tool execution follows `_client/tools*`, public Python tools APIs and tests;
  caller registration is the permission boundary. The initial read found a parent-plan
  conflict: current Python has max_rounds=8 but no total call limit, no explicit argument
  schema enforcement, duplicate names last-wins, and no ordinary-loop call deduplication.
  Returned usage/timing/manifest describe only the final generation round. The bounded
  baseline contract below resolves the parent gate wording; RICH.4a's cold review and
  exact native API handoff are accepted below. No reflection-based
  authorization inference or hidden tools.

### Bounded tool-loop baseline for RICH.4a review

This slice ports the existing public Python loop. It does not add a stricter execution
policy to one SDK. The authority is `_client/tools.py`, `_client/async_client.py:run_tools`,
the sync wrapper, and `tests/test_tool_loop.py` at the recorded Python baseline/current
source. The native API shape and reflection binding passed the RICH.4a cold review;
the following execution behavior is settled.

- Registration is explicit caller permission. A model may select only a registered name;
  unknown names raise ToolLoopError/ToolLoopException with the registered-name hint. No
  import, subprocess, expression evaluation, filesystem or network operation is inferred
  from model arguments. Annotation hints do not authorize execution.
- Ordinary loops derive or accept ToolSpec declarations, use last registration for a
  duplicate name, and retain the surviving name's first insertion position. Declaration
  support must cover Python's string/integer/number/boolean/array/object/optional shapes;
  unsupported callable signatures fail at registration. Native numeric ranges and typed
  delegate binding are explicit language mappings, not Python runtime type enforcement.
- The core invokes Generate for at most maxRounds rounds (default 8), forwarding ordinary
  generation options and the registered specs each round. A result whose finish reason is
  not tool_calls, or whose call list is empty, returns immediately. The round that reaches
  the limit still dispatches its returned calls, then exhaustion raises the loop error.
  Zero/negative bounds follow Python's zero-generation exhaustion path. There is no
  separate maxCalls setting in the baseline and none is claimed by this milestone.
- Calls dispatch sequentially in returned order, once per returned list entry. A repeated
  call id/name/arguments in a later round is another explicit model call and executes again.
  The no-double-execution gate checks that facade, retry/repair and bookkeeping do not
  replay one dispatch. Arena memoization/single-flight is separate SDK.11a behavior.
- Missing/extra/invalid arguments are ordinary handler/binder failures returned to the
  model as ToolResult(is_error=true), not provider retries. Python does not run arbitrary
  JSON Schema validation before invoking a function. The native typed binder must reject
  values it cannot represent rather than coerce them silently, with this language boundary
  covered separately. Do not retrofit a JSON Schema policy into either SDK under this port.
- A registered handler may be synchronous or asynchronous. Normal handler failures become
  error results containing the native exception class and message; exact runtime class
  spellings are language-specific and must be documented in the shared trace projection.
  Cancellation escapes unchanged and stops later dispatch; it never becomes a tool error.
- String returns remain literal, null becomes the empty string, JSON-compatible values
  serialize as JSON, and other return values use the native display fallback. Preserve
  semantic JSON values across languages while documenting native number/format boundaries;
  do not compare unrelated serializer whitespace as SDK policy.
- After dispatch, append one assistant message containing the ordered calls and one tool
  message per ordered result, preserving call ids and error flags. Return the final round's
  actual Generation, with its usage/timing/attempts/manifest. Do not synthesize loop-wide
  accounting. The caller owns handler side effects and cancellation cooperation.

> NOTE: Coordinator source review on 2026-10-22 resolved the parent plan's shorthand
> "argument validation / max-round/call limits / no-double-execution" as the actual
> callable binding, round bound and once-per-returned-entry semantics above. General
> schema enforcement, a new total-call policy and ordinary-loop deduplication would be
> separate changes to both SDKs, rather than claims about the existing Python contract.

### Native tool API handoff accepted at RICH.4a

This is the coordinator's concrete native mapping after the bounded cold review closed.
Use new `Tool.cs`, `ToolRegistry.cs`,
private `Internal/ToolBinding.cs` and `Internal/ToolLoop.cs`; integrate the existing clients
and request copy path rather than adding a parallel generation engine.

- `Tool` is an immutable pairing of `ToolSpec Spec` and a caller-owned handler. Its explicit
  constructor accepts `(ToolSpec spec, Func<JsonObject, CancellationToken, ValueTask<object?>>
  handler)`; `Name` reads Spec.Name. `CallAsync(JsonObject arguments, CancellationToken
  cancellationToken=default)` invokes this handler without hiding its exception. The
  explicit JSON boundary supports arbitrary app-owned binding without reflection.
- `Tool.From(Delegate function, string? name=null, string? description=null)` is the normal
  reflected equivalent of Python's decorator. Name defaults to Method.Name; description
  uses the override, then a BCL DescriptionAttribute on the method, then empty text. Do not
  scrape XML files at runtime. Reject multicast/open generic/ref/out/pointer and
  async-void signatures at registration with ToolLoopException and a useful hint. A single
  CancellationToken parameter is injected, excluded from the advertised schema, and never
  bound from model arguments. A final CLR params T[] parameter with supported element type
  is also excluded from properties/required and receives an empty array, matching Python's
  skipped variadic positional declaration. A model key with that omitted parameter's name
  remains an unknown argument; it cannot populate the variadic array. Sync void/value,
  Task/Task<T> and ValueTask/ValueTask<T>
  returns are awaited through this one path; unwrap TargetInvocationException so handler
  failures retain the original exception type.
- Reflected parameter support is deliberately explicit: string, bool, int, long,
  BigInteger, double; nullable value forms; JsonValue/JsonObject/JsonArray; one-dimensional
  arrays, List<T>/IReadOnlyList<T>, Dictionary<string,T>/IReadOnlyDictionary<string,T> of
  recursively supported values; object as the unconstrained JSON value shape. Scalars map
  to the same JSON schema types as Python. Reference null and Nullable<T> accept JSON null;
  nonnullable value types reject it. Optional CLR defaults omit a name from `required`.
  Reject unsupported types at registration; no string-to-number, bool-to-number,
  fractional-to-integer, overflow or nonfinite coercion. Other CLR numeric/date/enum/custom
  parameter types require the explicit handler constructor. This is a documented CLR
  binding boundary, not new JSON Schema validation or a change to Python's dynamic calls.
- Native container conversion uses the existing immutable tagged JSON values and modern
  writer; do not route through the frozen portable-v0 reader/writer range. Object-shaped
  inputs bind to string-keyed maps and array-shaped inputs to ordered lists. Actual return
  strings stay literal, null/void becomes empty, supported primitive/tagged/container values
  serialize as JSON, and unsupported values use their native ToString fallback. Reject a
  cyclic JSON-compatible container as a normal tool failure rather than overflowing the
  process stack. Serializer whitespace is not a cross-language semantic claim.
- Public `ToolRegistry(IEnumerable<Tool> tools)` exposes immutable ordered `Specs`,
  `long Dispatched`, and `Task<ToolResult> DispatchAsync(ToolCall call,
  CancellationToken cancellationToken=default)`. Names compare ordinally. Duplicate
  registration replaces the handler/spec in the first insertion slot. Unknown names fail
  before dispatch. Read/increment Dispatched through Interlocked; each known dispatch
  increments once after name resolution and before binding/handler, including their
  failure or cancellation, while an unknown name remains uncounted. The client loop checks
  cancellation before entering dispatch. Normal exceptions
  become native-class-and-message error results; OperationCanceledException propagates
  without conversion. No memoization policy is introduced here.
- Add nonretryable `ToolLoopException` with category `tool_loop`, phase `generate`, null
  provider/status/retry delay, normal bounded/redacted detail and separate hint. It covers
  declaration, unknown name and round exhaustion; handler failures remain conversational
  ToolResult values. Public direct Tool/ToolRegistry calls do not require a client.
- `AsyncClient.RunToolsAsync(GenerationRequest request, IEnumerable<Tool> tools,
  int maxRounds=8, CancellationToken cancellationToken=default, bool? manifest=null)` is
  the complete request path. Prompt and message overloads mirror GenerateAsync's options,
  with required registered tools immediately after prompt/messages and maxRounds appended
  after all ordinary generation options. Client.RunTools mirrors these through the existing
  RunOperation facade. A request's raw tool declarations are replaced by registry.Specs
  each round; every other generation field and client default continues through Generate.
  Add public GenerationRequest.WithMessages and one internal complete copy helper for
  messages+tools; preserve all existing fields, limits and route without lossy positional
  reconstruction. The final Generation is the actual final round object.
- Reserve the whole async operation through existing ReserveLifecycle/AsyncExecutionContext,
  including time inside user handlers between generation calls. Check caller/client
  cancellation before each dispatch and round; pass the owned linked token to handlers,
  preserve cancellation ownership via existing identity machinery, and complete the
  reservation in finally. Use existing callback self-dispose guards; do not await this
  same operation from inside its own handler. No background orphan handler or parallel
  dispatch is created. A noncooperative handler may delay disposal, as caller-owned work;
  do not invent timeout-abandonment or replay semantics.

The native-only controls must cover constructor/reflection binding, legacy request field
preservation, operation lifetime/caller token/foreign cancellation, sync facade, handler
failure, repeated call IDs, duplicate registration order, zero/negative/exhausted rounds,
and disposal from a callback. Shared input-only loop traces must separately execute actual
Python/native public loops and compare advertised declarations, wire history and dispatch
order/results; native binder-only signatures remain language-specific controls.

### Shared bounded-tool trace contract

Use a separate input-only `tests/fixtures/tool-loop-v1/` profile, with independent public
loop observers and the existing source/dirty/corpus envelope mechanics. This profile is
deliberately narrower than rich-generation-v1: compare actual handler invocation records,
advertised ToolSpec values, ordered outgoing message/tool history and the final round's
text/finish reason/target/token usage, or its actual typed loop error. No elapsed timing,
aggregate loop accounting, telemetry serialization or arena policy is inferred here;
those have their own profiles and native controls. Original runtime error diagnostics
remain retained, with only the explicit ToolLoopError/ToolLoopException typed boundary.

The ten literal case IDs are tools-final-no-calls, tools-one-call, tools-ordered-calls,
tools-repeated-id, tools-duplicate-name, tools-round-exhaustion, tools-zero-rounds,
tools-negative-rounds, tools-unknown-name and tools-sync-path. Requests contain literal
messages/target/max_rounds/entry_point, explicit context/catalog and route retry/health
settings, registered declarations plus controlled application handlers, and ordered
provider response inputs. Handlers are constant, echo-one-argument or per-registration
counter, with an explicit async flag; these model caller-owned functions, not SDK policy.
Provider inputs contain literal text/tool calls/finish reason and optional token counts.
There are no expected results, expected dispatches or expected request messages. Registration
duplicates remain ordered input. Handler failures and CLR reflection boundaries are
independent native/Python controls, not normalized arbitrary conversation text in this
paired profile. Freeze this small grammar/corpus only after a cold executable-input review.

## Execution checklist

- [x] **RICH.0a** Re-read parent plan, architecture and current source maps. Gate: three
  independent read-only maps cover types, execution/wire and profile boundaries.
- [x] **RICH.0b** Cold critique this contract against actual source and architecture.
  Resolve blocking ambiguity before dependent source edits. Gate: bounded review closure.
  > NOTE: Cold review `sdk-seven-rich-generation/contract-review` identified ambiguous
  > audio-source wording and unnamed manual reconstruction paths. The explicit matrix
  > and preservation checklist below resolve both without changing Python behavior.
- [x] **RICH.1a** Domain owner: `Models.cs`, `GenerationEvent.cs`, new rich domain files,
  `Providers/{WireRequest,AdapterEvent,ProviderDescriptor}.cs` only. Add immutable types,
  fields/defaults/validation and descriptor seams above, preserving existing constructors.
  Gate: source API handoff plus root serialized solution compile; no frozen caller changes.
  > NOTE: Root library and whole-solution compilation pass with zero warnings/errors;
  > actual SDK is 8.0.426, selected by the unchanged 8.0.425/latestPatch pin. Retained
  > `.tmp-tests/rich-domain-build-second` and `rich-domain-solution-first`. First compile's
  > 12 syntax diagnostics are preserved at `rich-domain-build-first`; corrections only
  > fixed XML-comment parameter syntax and lambda grouping, plus documented formatting.
  > NOTE: The original source handoff (subsequently compiled above) adds
  > four source-matrix media parts, rich event/result/request/wire values, structural JSON
  > snapshots, and descriptor translation metadata without changing orchestration or tests.
- [x] **RICH.1b** Independent controls owner: new `AnyInfer.Tests/RichGenerationTypesTests.cs`
  only. Tests derive from Python sources, not implementation internals: copied bytes/maps,
  source rules/ceilings, video offsets/fps, scalar citation spans, token alternatives and
  server-tool validation. Gate: root filtered native type tests after RICH.1a.
  > NOTE: Root filtered native gate passes 9/9, zero skips, at
  > `.tmp-tests/rich-types-native-first/{native.txt,rich-types.trx}`. This accepts the type
  > foundation only; rich request-path/wire behavior and profile comparison remain open.
  > NOTE: Native controls are authored in `RichGenerationTypesTests.cs`: nine public-API
  > cases cover media source/ceilings, snapshots, scalar citations, logprobs, server-tool
  > construction/defaults, request bounds, event hierarchy, Message.Text, and legacy parameter names.
  > The controls owner ran no native execution; the coordinator's retained gate above accepts them.
- [x] **RICH.2a** Core owner after API handoff: `Core/GenerationCore.cs`, `AsyncClient.cs`,
  `Client.cs`, request internal normalization files, relevant capability/admission/token
  estimation/manifest projection files. Preserve all new fields, implement public event
  buffering/first-content/terminal projection and provenance gates without provider branches.
  Explicit reconstruction checklist: AsyncClient default-repair request copy; AsyncClient
  convenience request factory and Client forwarding; GenerationCore winning terminal
  construction; Generation.WithManifest. Use named arguments or a complete owned factory
  to preserve new fields. NormalizedRequest/CreateWireRequest must retain them; fresh
  repair/fallback entry buffers isolate prior entry fields. Frozen normalization stays
  text-only and rejects rich requests before its existing Text cast.
  Gate: independent event/order/fallback/repair/unknown-fit/privacy/lifecycle controls.
  > NOTE: The first core handoff was partial and did not complete capability gates or convenience forwarding.
  > That owner is retired. A fresh bounded owner completed async/sync forwarding and policy/admission;
  > the subsequent independent development acceptance is recorded below.
  > NOTE: Final bounded source/control/cancellation reviews are clean. Root retained 115/115
  > rich plus existing lifecycle cases and final 38/38 rich cases, zero skips, under
  > rich-core-native-third/fourth. This accepts core propagation at the development boundary;
  > new paired observations, public delivery and clean-source qualification remain open.
  > NOTE: Actual rich captures exposed additional ModernSdk parity gaps after the bounded
  > controls: absent/inapplicable schema fields were still carried in WireRequest; native
  > AttemptRecord timing was never populated; terminal server-use maps could spuriously
  > synthesize UsageUpdate. Source corrections and independent wire/timing controls are
  > active. Preserve the earlier green evidence, but these corrections require a fresh
  > coherent native gate and actual paired capture before RICH.3 acceptance.
- [x] **RICH.2b** Wire owner after API handoff: `Providers/OpenAIChatAdapter.cs` and new
  private codec helpers only. Mirror existing Python encoding/parsing and caps/lifetime;
  update `contracts/openai-compat.md` only if evidence shows the shared snapshot missing
  relied-on protocol facts, after coordinator review. Gate: actual offline HTTP requests
  and buffered/SSE reconstruction; unchanged ordinary text payloads.
  Include the adopted Python `providers/openai_compat.py` document-URL correction and
  independent Python/C# no-send controls. Update the snapshot with bounded fetched-date
  evidence, and add an immutable propagation declaration; account for all Python inherited
  dialect/preset dependencies through the real inventory. Root coordinates those extra paths.
  > NOTE: 2026-10-22 wire source and focused controls are saved: inline image/document/audio,
  > document-URL/video pre-send refusal, tool history, request logprob forms, and buffered/SSE
  > logprob parsing. Review closure adds unconditional buffered raw payloads, bytes-only
  > logprob degradation, and reasoning/extra-option precedence controls. Python slice passed
  > 5 tests with Ruff clean; the collision assertion is connected to the actual dispatched
  > request. Native gate remains coordinator-owned.
  > NOTE: Root authored immutable openai-compat-rich-inputs declaration against the versioned
  > maintenance schema, retaining the bounded official source dates and no-shared-spec-delta
  > rationale. Actual inherited bindings come from producers; four Python gates plus native
  > C# and the pure aggregate remain pending for the eventual clean source. Schema-valid
  > declaration SHA is 10a45384786a7cd2187d5aeab3abec41f5c95dd736ff430a1776984c13888e35.
  > NOTE: Clean source b315ef73173b81ace643c41e95f4e6339db636b6 closes the wire and
  > propagation gate. All four registered Python gates and the registered C# workspace
  > gate pass against the original declaration bytes; the pure aggregate binds both
  > actual inventories and verification artifacts to this clean commit/tree. Independent
  > qualification review is bounded clean. Hosted upstream traffic remains unverified.
- [x] **RICH.2c** Independent tests owner: new rich generation/core/wire/lifecycle native
  tests and corresponding Python controls, not product files. Gate: both runtimes exercise
  literal requests/raw bytes, tool assembly, privacy, predispatch refusal, known/unknown
  capability facts, commit boundaries and no terminal-field carryover across attempts.
  Include connected controls for each of the four named reconstruction paths above.
  > NOTE: Independent native core/lifecycle controls are saved in `RichGenerationCoreTests.cs`
  > and `RichGenerationLifecycleTests.cs`, held for the core source handoff and coordinator's
  > serial native gate. Current convenience overloads have not yet appended the settled rich
  > arguments, so the public forwarding controls intentionally await that source release.
  > NOTE: Expanded held controls add trusted/default provenance withholding, descriptor server-wire
  > refusal, empty-event first-content, frozen-profile boundaries, trusted media/server feature gates,
  > ordinary-route fallback, and unpriced media budgets. No native execution ran.
  > NOTE: Compile-correction follow-up replaces nonexistent wire ceilings with public async/sync
  > convenience predispatch media-ceiling controls; uses configured descriptor support for positive
  > server-tool forwarding; corrects override provenance and Python parameter-drop order; and adds
  > terminal usage-count/metadata-privacy assertions plus separate schema-repair rich-final isolation.
  > Final execution is accepted below at the coordinator-owned bounded development gate.
- [x] **RICH.3a** Profile owner: new `tests/fixtures/rich-generation-v1/{inputs.json,
  schema.json,observations.schema.json,README.md}` and pure profile controls. Freeze literal
  cases only after an independent contract/oracle review; no expected SDK result fields.
  Cover media sources/order/bounds/refusal, tool history/fragments, reasoning-first and
  empty-content semantics, citations/server events without content, rich final fields,
  provenance withholding, wildcard/instance options, repair/fallback, raw/privacy, sync,
  cancellation/early close. Gate: schemas, exact unique IDs/references and no result oracle.
  Constructor negatives may be paired with a closed ValueError/ArgumentException semantic
  mapping. Scripted HTTP supplies response/SSE inputs, never expected request outputs.
  Public/wire observations compare exact synthetic fixture strings/options/URLs and exact
  normalized raw data (or canonical digest); media bytes compare actual length/hash.
  Never capture auth values. Product telemetry/manifest privacy is inspected from actual
  serialization, not achieved by deleting payload fields in the recorder. Synthetic caller
  metadata labels follow the existing explicit-telemetry contract. Include empty reasoning
  and the independent missing-descriptor-wire-support server-tool refusal.
  > NOTE: RICH.3a authoring began with a 43-case input-only draft, including the later
  > OpenAI document-URL no-send case. It remains unchecked until the independent
  > contract/oracle review freezes the corpus and schemas.
  > NOTE: Cold profile review found literal-input and grammar P1s. The authored corpus is
  > revised but remains unfrozen pending reviewer recheck; the original 3-pass structural
  > gate was insufficient coverage.
  > NOTE: Final independent oracle/schema review is clean. The 43-case profile is frozen
  > after JSON-preserving CRLF-to-LF canonicalization plus a scoped .gitattributes rule.
  > Root re-ran 65 tests and Ruff successfully at .tmp-tests/rich-profile-freeze/junit.xml.
  > Canonical input SHA-256: 041d82031d6df54144cd107ae8d886a92106cab3f7b334544b3cf2d5a2b03383.
  > Construction schema: 0aeb51ff92a0d7b5760cb91bffea70828869e827abb6a09096ad6e9dcca0419a.
  > Observation schema: 5070da87bf313f274afaa8d7abe6d31229e0663bcdf461f207638d96427ef959.
  > README: 79fa273424831d2ec015c3c950a6e7a080f60789d841b38ae9f4e46802371c73.
  > Pre-LF input 289c72... and schema 3a2c8... are retained only as byte-normalization
  > provenance under .tmp-tests/rich-profile-freeze; they are not current executable pins.
  > NOTE: Observer construction found that a request constructor can fail before any
  > manifest exists. Reopened only for a narrow observation-grammar erratum: manifest is
  > null-or-the-existing-complete-object; no attempted-input manifest may be fabricated.
  > Input and construction-schema hashes remain unchanged. Updated observation SHA is
  > 7fa0c172f1fa95fb926926575c9ac346a3008f46e08d5d288bd1011565d1000f; README SHA is
  > c1d1380a9fa4116251ba8952b3fc18ba5a2976ddd4d61fac1f7c91991ea68852.
  > README also fixes RFC 6901 evidence paths. Root retained 67 passing controls and Ruff
  > at .tmp-tests/rich-profile-absence-erratum. Fresh independent review confirms the
  > erratum is clean and the input-only contract remains intact; current hashes above
  > supersede the earlier observation/README pins. RICH.3a is accepted at this boundary.
  > NOTE: First actual recorder execution exposed two further prequalification defects:
  > the positive HTTP media input used a document URL despite the adopted refusal, and
  > actual TargetResolved telemetry had no projection branch. The provisional freeze is
  > withdrawn until actual 43-case executor outputs validate and a consolidated delta
  > review closes. Only the positive media document changed to one inline byte (ZA==),
  > URL null, total ceiling 4 for document 1 + audio 3; the separate URL-refusal input is
  > unchanged. No expected response/output changed. TargetResolved now has a closed
  > event/request_id/target projection. Root retained prior bytes and asserted the exact
  > parsed input delta. Current input SHA is
  > b395a19494165a807a1d59e22ec1f2a27c7f054c5e3cd9a05bd616527c0ff63f;
  > construction schema remains 0aeb51ff...; observation SHA is
  > ef821630cbe80a6fa96abff0fd9e87f7784e6a3846f9e36cb886750d660e6397;
  > README SHA is 28a4696f3ba0d50130298ac48c48ea47f1f5a8d868f2d372fe4cb6fbe65340b3.
  > Root's focused profile gate is 69 passed with Ruff clean at
  > .tmp-tests/rich-profile-execution-erratum. Released foundational assets are unchanged.
  > NOTE: The first all-43 native diagnostic completed as diagnostic-only evidence at
  > `.tmp-tests/rich-native-observer-diagnostic-first`: unknown actual event types were
  > UsageEstimated and RetryScheduled; observer transport/feature/route bugs were also
  > exposed. Candidate grammar now retains both typed events, including numeric retry
  > policy delay. Review identified that one-attempt fallback had been hidden observer
  > policy; client context/catalog settings and route retry/health settings are now literal
  > inputs. No SDK defaults or response scripts changed. Candidate hashes are retained in
  > `.tmp-tests/rich-profile-runtime-telemetry/hashes.json`; input fe3d9db7..., construction
  > 5c02e14c..., observations 4c359cdc..., README e3da97bc.... Root profile gate: 71 passed,
  > Ruff clean. Both actual recorder outputs must be rerun; RICH.3a remains reopened.
  > NOTE: This final disposition supersedes the earlier provisional holds. Fresh actual
  > Python/native captures agree on all 43 records at rich-compare-current-contract-root/
  > run-pobmbqsd/report.json. Consolidated profile/verifier review is bounded clean;
  > coherent Python controls pass 113/113 and native rich controls pass 53/53. The current
  > pins are input 9cff7a50..., construction 5c02e14c..., observations da4ab3ac..., README
  > dd5037a5.... The README records the causal repair-diagnostic comparison boundary;
  > original output remains retained. This accepts only the development profile contract,
  > not clean-source qualification or full SDK readiness.
- [x] **RICH.3b** Python observer owner: new native recorder using public AsyncClient/Client
  and controlled adapters/raw HTTP. C# observer owner: new nonpackable native executable
  with independent public API implementation. Each stamps actual commit/dirty/corpus bytes;
  recorder projects facts only and never runs another language or computes expected SDK
  behavior. Gate: independent source review of both observers before comparison.
  > NOTE: Independent Python and native recorder leases are now active. The native HTTP
  > recorder uses the existing public ProviderSettings.Transport seam; no new SDK access
  > API is required. Actual identity/serialization/privacy evidence remains recorder output,
  > with a narrow correlation rule and direct pre-hash privacy checks; no fabricated IDs.
  > NOTE: Initial recorder authors repeatedly returned incomplete foundations and are
  > retired. Their construction-only diagnostics are not RICH.3b evidence. Fresh native
  > and Python owners have the full executable leases; helper/source counts cannot close
  > this gate. The actual all-case CLI execution and output-schema check remain pending.
  > NOTE: Consolidated current observer review is closed. Its last Python admission P1
  > is fixed with raw frozen-SHA admission before decode and profile admission before
  > case execution, with direct no-execution negatives. The fresh Python capture at
  > rich-python-admission/output.json has 43 records/schema errors 0 and 12 focused
  > controls; native seventh capture has 43/schema errors 0. Root comparison against
  > those actual captures passes 43/43 at rich-compare-admission-root/run-w_xctlxr.
  > This accepts independent development observers; clean-source execution remains RICH.6.
- [x] **RICH.3c** Verifier owner: new strict pure comparison script/tests using existing
  `_csharp_observation.py` envelope facilities; add explicit SDK-pinned project/workspace
  registration only after observers work. Compare content/facts/order exactly; timing only
  through defined presence/order/invariants, never elapsed-value equality. Gate: fresh
  paired observations agree, plus stale/source/duplicate/mismatch/no-oracle negatives.
  > NOTE: A first pure-verifier handoff has 8 focused mocked controls passing and is held
  > for cold review. This is no paired runtime pass: generated request identifiers and
  > dynamic serialized evidence still need explicit correlation treatment before acceptance.
  > NOTE: The corrected verifier has 13 focused controls passing. Fresh review found two
  > remaining P1s: canonical-data recognition must stay out of arbitrary raw/HTTP JSON,
  > and first-content state must reset per attempt. A bounded fix lease is active; no
  > actual paired observation pass has occurred.
  > NOTE: Final current development gate supersedes the earlier checker holds. The pure
  > verifier has 27 focused controls and independent review closes typed error/canonical/
  > identity/repair diagnostic joins without a raw/HTTP oracle. Root actual comparison
  > passes all 43 cases. RichGeneration is registered in the solution and workspace C#
  > gate/lint paths; the root coherent profile/observer/checker/wire/workspace Python batch
  > passes 184/184 at .tmp-tests/rich-coherent-registered-root/junit.xml. The one old gate
  > count assertion failure is retained and corrected from 22 to 23. Full native/registered
  > propagation and clean-source gates remain RICH.6; this box accepts development evidence.
- [x] **RICH.4a** Tools contract handoff: inventory actual Python registration/reflection,
  validation/error/cancellation/round/call semantics into a bounded subsection here before
  implementation. Gate: cold contract review; no new product decision without coordinator.
  > NOTE: The native mapping above passed cold review in tools-contract-review. Its two
  > findings are closed by explicit final params-array omission/empty binding and exact
  > Interlocked known-dispatch counting. This accepts the contract only; RICH.4b source,
  > independent shared execution traces and native lifecycle controls remain unfinished.
- [x] **RICH.4b** Tools owner: new public tool registration/bounded execution files plus
  AsyncClient/Client integration under exclusive lease. Gate: shared native tool-loop traces
  and independent argument/error/limit/cancellation/no-double-execution controls.
  > NOTE: Native foundation passes 13/13 combined source-authored/independent controls at
  > tool-foundation-native-third, after retained compiler/BigInteger/nested-null corrections.
  > Foundation review is bounded clean. Client-loop integration, independent lifecycle
  > controls and the separate small input-only tool trace profile are now released as
  > disjoint work; whole RICH.4b remains open until actual shared execution passes.
  > NOTE: Root's combined client/foundation/binding/lifecycle gate passes 21/21 at
  > tool-loop-native-third; the narrow source reviews close the retained test compile
  > defects. The ten-case tool-loop-v1 candidate passed cold aggregate/decoder/provenance
  > rereview and is released for independent observer authoring, not final qualification.
  > Current input SHA is 4693fca5c88e2c3ca129b7197b819c5c55bfbe11d2621135184bb7bfcfbad5a9;
  > schema 7c445c33b494b2a5a0a4ca3204129fbd8630e776c5e50545f9a7bb11c7f80f7c;
  > observations 0eab305617e3563affe3dea43ad8360cf3a1b93cca29bd4b7bb48ccb994fa772;
  > README bd7ad073d1bdfc7bd737a747b37df48dceba47051d2c6a98e0b455f168ddc903.
  > NOTE: Development acceptance supersedes the authoring hold. Actual independent Python
  > and C# captures have ten schema-valid records each; root's current pin-bound comparison
  > passes all ten at tool-loop-compare-root-final-contract/run-9xjts1cj/report.json. Cold
  > observer/verifier/registration reviews are closed. The verifier has 10 focused controls;
  > registered workspace controls pass 70/70. README now documents directional native error
  > names and exact diagnostic-text exclusions; its current SHA is
  > 4467ff276cdb8d1d1c24b16d1cd0a3470343a6effc92d5469f46804585ffa1f1. Input and both schemas
  > remain unchanged. This accepts bounded tool behavior, not clean-source or full SDK readiness.
- [x] **RICH.5** Public delivery owner after APIs settle: source-linked offline C# example,
  `examples/csharp-sdk/Program.cs`, isolated NuGet consumer/source tests, C# guide/reference/
  porting and relevant language tabs. Explain achieved semantics without internal plan IDs.
  Gate: actual compiled examples, actual package-only consumer and strict docs build.
  > NOTE: The current rich-media and registered-tool examples executed successfully in
  > the offline harness at rich-public-delivery-first. The isolated NuGet consumer packed,
  > restored and compiled, then found an old prompt-mode witness that incorrectly required
  > wire Schema. Its correction preserves the schema-name/instruction/core-validation/
  > typed-result/count/disposal checks. The next run found generated C# escape errors in
  > that new assertion, retained at rich-public-delivery-second; the package-only owner is
  > correcting the template and rendered-source control. Public documentation has a
  > separate exclusive owner. No package/runtime or docs-build acceptance is claimed yet.
  > NOTE: Final bounded delivery acceptance supersedes those earlier holds. Both current
  > source examples execute through the offline harness. The third isolated NuGet consumer
  > run passes pack/restore/build/run with zero warnings/errors at rich-public-delivery-third;
  > old and new witnesses remain. Fresh docs/consumer review is bounded clean. The actual
  > registered strict docs-build gate passes at rich-public-docs-first. This closes this
  > public delivery slice, retaining C# prerelease qualification and broader RICH.6 gates.
- [x] **RICH.6** Coordinator: cold source, lifetime, oracle and delivery reviews; inspect
  evidence; full `.venv/Scripts/python.exe workspace.py check`, explicit source commit,
  isolated clean-checkout paired profiles/Frozen 102/package gates. Preserve failed-first
  logs. Gate: exact clean source metadata, unchanged released hashes and all required checks.
  > NOTE: Frozen timing repair is accepted after 6/6 focused controls and fresh narrow
  > review. Root's second full solution run passes 947/947 SDK tests and 93/93 conformance
  > tests, zero skips, at .tmp-tests/rich-tools-native-coherent-second. This closes the
  > retained runtime regression without changing released assets/comparators. It does
  > not replace the full workspace, propagation or isolated clean-source gates.
  > NOTE: The first full workspace gate passed 23/24 steps, including all registered native
  > profiles, package, examples and docs. Python test collection exposed a brittle new
  > scripts-package import; direct pytest-entrypoint correction passes 12/12. Two existing
  > portable tests also hit a different source-refusal diagnostic because the root wrapper
  > put basetemp inside the repository and passed Windows backslashes through PYTEST_ADDOPTS.
  > Moving the full-suite temp outside the repository with forward-slash formatting makes
  > both original tests pass unchanged. Retain rich-tools-full-workspace-first and
  > rich-portable-temp-root evidence. A complete second workspace run remains required.
  > NOTE: The complete second workspace gate passes all 24 steps in 176.3 seconds at
  > rich-tools-full-workspace-second. The original portable refusal checks remain unchanged;
  > the direct pytest observer import now collects correctly. Root is committing explicit
  > owned source next, then running the registered immutable-declaration and Frozen/paired/
  > package qualification from a clean checkout. This box remains open until that proof.
  > NOTE: Source commit a49258e96edd65af4d4e81d30fdb9d2633054c9f passes the full gate.
  > Its first clean checkout stopped before gates because Windows converted the immutable
  > rich declaration to CRLF (b5b286ad...) although the original and committed LF blob both
  > retain SHA 10a45384.... A scoped .gitattributes rule now preserves that file's committed
  > LF bytes. The declaration content/hash is unchanged; a small checkout-policy follow-up
  > commit and fresh clean qualification are required. The failed-first run is retained as
  > local-rich-a49258e9-20261023T023641Z in the original qualification worktree.
  > NOTE: Checkout-policy follow-up b315ef73173b81ace643c41e95f4e6339db636b6, tree
  > 7e00ab8f148f255b94c77b5c8673370a04ad2833, passes clean qualification run
  > local-rich-b315ef73-20261023T024719Z attempt 1. All five registered gates pass;
  > native suites are 947 unit/93 conformance, paired profiles are accounting 42+2 native
  > boundaries, request policy 29, retrieval 32, rich 43 and tool loop 10. Both captures
  > in every pair report this revision with source_dirty=false. Package-only consumption
  > and examples pass. Frozen DEVELOPMENT/UNRELEASED reports 102/0/0/0 with unchanged
  > release SHA 16122cca...81391, and final checkout status is clean. Aggregate SHA is
  > 2fe8e3b7d51a92829534742d4eab7e97537073a398c68ce8f0cac83a64f598e7.
  > Root and independent evidence review agree; no P1/P2 remains in this bounded slice.
  > The ignored operator's first import probe also had a PS5.1 quoting failure before
  > gates; stdin delivery fixes the probe without changing source or assertions. Both
  > failed-first attempts remain retained. Full workspace follow-up passes all 24 steps
  > in 176.6 seconds. No release/publication or whole-library readiness follows.
- [x] **RICH.7** Reconcile parent SDK.7a/b and parity inventory only for achieved scope,
  record acceptance and resume the remaining SDK.6c/8/9/10/11/12 work. Gate: no unfinished
  milestone is called complete; full core-library readiness remains the active user goal.
  > NOTE: Parent SDK.7a/b now record the accepted clean source and exact bounded semantics.
  > All 235 root API inventory rows remain unchecked until their complete assigned
  > semantics and SDK.11c audit pass. Resume SDK.8a's complete provider inventory and
  > reviewed preset-data boundary before remaining mixed-operation SDK.6c bindings.

## Ownership and evidence

Each brief owns disjoint source/test paths and named boxes. Re-read this file immediately
before ticking owned boxes, use minimal edits and add `> NOTE:` deviations. When a shared
file needs a new owner, wait for the prior owner to hold it and transfer the lease explicitly.
Do not touch Git state, `uv.lock`, `v/cache/nodeids`, released/profile assets, or other owners'
files. Workers run only named targeted Python checks. Coordinator serializes native builds,
packaging and full suites. Use explicit UTF-8, fresh ignored basetemp/JUnit and disabled pytest
cacheprovider. Artifacts live under `csharp-sdk/sdk-seven-rich-generation/` in the task.

This leaf is complete at qualified executable commit
`b315ef73173b81ace643c41e95f4e6339db636b6`, tree
`7e00ab8f148f255b94c77b5c8673370a04ad2833`. Resume the first unchecked parent milestone,
SDK.8a; remaining SDK.6c/8/9/10/11/12 work and full-library readiness remain active.
The plan-only acceptance commit does not replace this qualified executable identity.

Clean checkout:
`C:/Users/antho/.traycer/worktrees/anthturner__anyinfer/feature-rich-clean-b315ef7`.
Its retained `.tmp-tests/local-rich-b315ef73-20261023T024719Z/` packet contains the
qualification log, pure aggregate and Frozen report; sibling `-python` and `-csharp`
roots retain both registered producers and their gate logs. Actual clean paired reports
are `.tmp-tests/rich-generation/run-dph7l6gr/report.json` (43/43) and
`.tmp-tests/tool-loop/run-sw97myej/report.json` (10/10). Both runtime captures bind this
commit with source_dirty=false. Root and independent clean-qualification reviews are
closed. Original failed-first source, test, runtime, wrapper and checkout logs remain;
earlier provisional holds above are historical and superseded by these final notes.

The rich-generation profile is accepted at its bounded scope. Current pins are input
`9cff7a50fbfd553ebcfed25186173579fff582796721d0e83cc656e116cc1777`, construction schema
`5c02e14c8ebf96432755e19b63a4a065b3a7696a8c7f6eb0c300c880c9080cae`, observation schema
`da4ab3ac0c084bd2cfc6ca762dfeabfbe7eb67998b08e01d6ae94c0de21f6951`, README
`dd5037a5fe159fe1ecba2c1c16d25762d0717f2013f791b654c668692c23404e`.
The latest input correction supplies valid SSE provider input to the positive streamed
media case; the earlier JSON-only response was contradictory. The separate document-URL
refusal remains unchanged. Portable typed errors follow the foundational core fields;
runtime class spelling and free diagnostic detail/hint remain retained in original
evidence, with exact causal literal-failure joins. No broad raw/HTTP normalization applies.

Tool-loop input remains
`4693fca5c88e2c3ca129b7197b819c5c55bfbe11d2621135184bb7bfcfbad5a9`, construction schema
`7c445c33b494b2a5a0a4ca3204129fbd8630e776c5e50545f9a7bb11c7f80f7c`, observation schema
`0eab305617e3563affe3dea43ad8360cf3a1b93cca29bd4b7bb48ccb994fa772`, README
`4467ff276cdb8d1d1c24b16d1cd0a3470343a6effc92d5469f46804585ffa1f1`.
The session-state wire field is protocol data only; SDK.11a owns session lifecycle.
Generic chat remains chat-only; provider breadth and mixed-operation bindings need their
own current contract research and certification. Hosted live traffic remains unverified.
