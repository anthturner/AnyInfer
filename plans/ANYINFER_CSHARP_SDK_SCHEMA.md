# C# modern schema support

Resume from the first unchecked box. This executes SDK.4b in
`ANYINFER_CSHARP_SDK.md`. Read this file completely before editing. Root owns this shared
plan, Git, restore/build/test/pack and final gates. Other agents own only their assigned
paths; they do not revert another owner's work or run unassigned processes.

## Accepted scope and baseline

- Python authority: `199c3f833e568334b629edd7d89f41a3b76efe2a`. SDK.4a source is
  `aca24ddf2097ca9a33ff33039a2285f0b0b0bdb7`, with clean plan/package checkpoint
  `c2bed9e6137305aa91cda07444dd9c71a3b728b9`.
- The user chose modern drafts first: Draft 6, 7, 2019-09 and 2020-12. Legacy Draft 3/4
  remain explicitly unfinished SDK.11c work. Do not claim complete Python schema parity.
- The user chose native numeric/regex semantics with documented differences: e.g.
  `0.3/multipleOf:0.1`, Unicode regex matching and Python named groups. Do not silently
  translate Python regex syntax or reproduce binary floating artifacts.
- C# resolves internal and caller-registered resources by default. URL/file retrieval
  requires an explicit caller delegate. No default HTTP client, file reader or global
  fetch handler. Python behavior remains unchanged.
- Preserve all 102 frozen observations, release assets and old native validator behavior.
  Internal registration/clock constructors retain their signatures and frozen profile.
- No publication, release, upload, paid dependency or license change is authorized.

## Dependency and qualification

Use qualified `JsonSchema.Net` **8.0.5**. Its exact restored net8 graph is:

| Package | Qualified version | Declared license |
| --- | --- | --- |
| JsonSchema.Net | 8.0.5 | MIT |
| JsonPointer.Net | 6.0.1 | MIT |
| Json.More.Net | 2.2.0 | MIT |
| Humanizer.Core | 2.14.1 | MIT |

Add one direct PackageReference with exact range `[8.0.5]`; do not float into 9.x,
whose binary terms differ. Do not add redundant direct references without a concrete
restore constraint. Verify the actual resolved graph independently of the root nuspec's
direct dependency group. Preserve net8.0, pinned SDK, warnings-as-errors and archive payload.
Package/license/hash qualification concerns the listed versions, not future upgrades.

The isolated console restore produced four packages and 894,753 bytes of recursive output
on this host. This is a qualification observation, not a universal size promise. Corvus
4.6.7 was rejected for this slice: 43-package/code-generation graph, runtime compilation,
no Draft 3 and a process-global URI-only compiled callback cache. Newtonsoft's documented
schema package choices are AGPL/rate-limited or commercial; neither is selected.

Pinned native source: JsonSchema.Net commit
`3520d7ac43e5c6c9b91abeac5af992eb82ffbf63`. `SchemaRegistry.Fetch` is synchronous;
returning null falls back to Global.Fetch. `Register(Uri, IBaseDocument)` registers an
alias to the same document registration. Do not invent an async upstream resolver or a
no-global-lookup switch.

## Public contract

### SchemaSpec and request migration

Add root `SchemaSpec` in `src/csharp/AnyInfer/SchemaSpec.cs`:

```csharp
public sealed record SchemaSpec
{
    public SchemaSpec(JsonValue jsonSchema, string name = "response");
    public JsonValue JsonSchema { get; }
    public string Name { get; }
    public static SchemaSpec Coerce(SchemaSpec schema);
    public static SchemaSpec Coerce(JsonValue schema);
    public static SchemaSpec Coerce(JsonElement schema);
    public static SchemaSpec FromJson(string json);
    public static implicit operator SchemaSpec?(JsonValue? schema);
}
```

- Constructor checks null references only; do not validate schema keywords or fetch.
  Explicit construction can carry malformed JSON schema for late validation/frozen admission.
- Existing spec coercion returns the same object. Mapping coercion accepts JsonObject,
  takes a nonempty string `title` without trimming as Name, else `response`. JsonElement
  and FromJson are object bridges. Unsupported coercion shapes fail immediately with
  ArgumentException. No reflection/model generator or retained caller model type.
- Null implicit input stays no schema; non-null delegates to public mapping coercion.
  Frozen drivers must use the explicit constructor with literal `response` instead.
- Change GenerationRequest.Schema and its constructor schema argument to SchemaSpec? in
  the same position/name/default. Substitute the same type in every prompt/messages
  Generate/Stream overload on AsyncClient/Client. Preserve all other tails and precedence.
- Normalization carries canonical JSON, Name and the internal profile. Canonical schema
  always validates; provider projection cannot replace it.
- Append optional `string schemaName = "response"` to WireRequest's existing constructor
  and expose SchemaName. Public wire projection forwards Name; frozen uses literal response.
  OpenAI JSON-schema format uses that name. No event/released JSON contract changes.

### Policy and standalone validation

Under `AnyInfer.Schema` add:

```csharp
public delegate ValueTask<JsonValue?> SchemaResourceRetriever(
    Uri resourceUri, CancellationToken cancellationToken);

public sealed class SchemaValidationOptions
{
    public SchemaValidationOptions(
        IReadOnlyDictionary<Uri, JsonValue>? resources = null,
        SchemaResourceRetriever? retrieve = null,
        Uri? baseUri = null,
        TimeSpan? regexTimeout = null);
    public IReadOnlyDictionary<Uri, JsonValue> Resources { get; }
    public SchemaResourceRetriever? Retrieve { get; }
    public Uri? BaseUri { get; }
    public TimeSpan RegexTimeout { get; }
}

public enum SchemaValidationKind { Validation, InvalidSchema }

public sealed record SchemaValidationIssue(
    string Rule, string? InstanceLocation, string? SchemaLocation, string Message);

public sealed class SchemaValidationResult
{
    public SchemaValidationKind Kind { get; }
    public bool IsValid { get; }
    public IReadOnlyList<SchemaValidationIssue> Issues { get; }
    public IReadOnlyList<string> Messages { get; }
}

public static class SchemaValidator
{
    public const int MaxReportedErrors = 5;
    public static Task<SchemaValidationResult> ValidateAsync(
        JsonValue value, SchemaSpec schema,
        SchemaValidationOptions? options = null,
        CancellationToken cancellationToken = default);
}
```

Result construction can be internal. Snapshot every exposed collection. IsValid is true
only for a Validation result with no issues; invalid schemas always have false validity.
Locations are JSON Pointer strings/absolute schema-location strings from native evidence,
not dotted-path guesses. Invalid-schema InstanceLocation is null and SchemaLocation points
into the canonical schema; retain native meta-schema location in internal facts.
Do not expose Json.Schema package types in the AnyInfer public API.

Options construction is inert. Resource keys/BaseUri must be absolute; resource keys cannot
contain nonempty fragments. Reject null map values and duplicate normalized identities.
Canonical JSON domain values are immutable; copy the map, never retain a mutable dictionary.
Default schema base without `$id`/BaseUri is stable `urn:anyinfer:schema:<SHA256>` of canonical
JSON. Callers needing relative external refs supply BaseUri or `$id`.
RegexTimeout defaults to one second per match. Require
a positive finite duration accepted by native Regex (at most Int32.MaxValue-1 milliseconds).
This is not a total evaluation deadline; cancellation/close can wait for a synchronous
evaluation containing multiple bounded matches. No infinite/global regex option.

Append `SchemaValidationOptions? schemaValidation = null` to public AsyncClient/Client
constructor and FromConfig tails. Append it to the existing FromAdapters factory method;
one-argument calls still compile. No public registration constructor or config key.
The internal registrations+clock path accepts no options and remains frozen.

### Typed result convenience

Add on Generation:

```csharp
public T? DeserializeStructured<T>(JsonSerializerOptions? options = null);
public T? DeserializeStructured<T>(JsonTypeInfo<T> typeInfo);
```

Use framework System.Text.Json on Structured, never Text. Missing Structured throws an
actionable InvalidOperationException; a JSON null value follows native deserializer
semantics. Preserve native JsonException/converter failure identity. No Generation<T>,
implicit model instantiation, schema inference, event, retry or accounting changes.

## Mechanism and failure contract

1. Add immutable internal `SchemaExecutionProfile { FrozenV0, ModernSdk }`. Public
   constructors/FromAdapters choose ModernSdk, retained internal clock path chooses FrozenV0.
   Carry it through RequestNormalizer/NormalizedRequest/GenerationCore separately from
   target resolution. Public RequestAdmission.Validate(one argument) stays frozen; profile
   overloads are internal. All non-schema admission remains shared.
2. Move the old algorithm to internal FrozenSchemaValidator, preserving its body/order.
   Conformance/frozen tests use the friend boundary. No obsolete public forwarding alias.
3. Extraction remains first, with the existing whole-value/first-balanced-region algorithm.
   Keep the frozen JsonReader envelope unchanged. A separate internal SDK parse mode must
   admit arbitrary-size BigInteger while retaining finite numbers, valid Unicode and the
   existing depth bound; use it only for modern SchemaSpec bridges/extraction. Do not globally
   relax v0 parsing or alter its failures.
4. Select Draft2020-12 when absent; recognize the four published dialect IDs with empty
   fragment equivalence. Deferred/unknown root dialects are controlled invalid-schema
   outcomes, with actionable modern-coverage feedback. Do not silently substitute Draft 3/4.
5. Validate canonical schema against selected MetaSchemas.Draft6/Draft7/Draft201909/
   Draft202012 before compiling it. Schema syntax checking enables native format checks;
   instance checking explicitly disables format assertion. Keep invalid-schema feedback
   late, after extraction, and preserve existing repair budget behavior for assessments.
6. Each assessment uses fresh local SchemaRegistry/DialectRegistry and raw cloned documents.
   No shared compile cache or mutations of package globals. Local registries can see global
   registrations by library design; do not claim a stronger hidden isolation switch.
   Every root/resource/meta raw document uses an owned IBaseDocument
   decorator. It preprocesses only native compiled KeywordData.Value Regex/map values before
   returning nodes, retaining pattern text/options/map keys and all standard handlers. A
   separate private `$ref` wrapper forces root/meta documents through that same hook. Follow
   compiled Subschemas with reference identity; never interpret raw unknown-keyword payloads.
   Inline preprocessing stops at reference-handler edges: referenced nodes must be decorated
   by their own raw document. Independently walk the full resolved graph before evaluation
   and refuse any executable node outside wrapper/assessment decorator ownership.
   Do not mutate nodes from global/unwrapped documents. Require owned nodes before evaluation
   or refuse the unregistered reference; rebuild standard meta resource sources privately.
7. Local synchronous Fetch throws a private owned missing-resource signal; it never returns
   null and never performs retrieval. Catch only that signal outside the native call, await
   the explicit user delegate, snapshot its result and rebuild with fresh registries. No
   Task.Run for async I/O and no GetResult bridge. No delegate means terminal refusal with
   zero caller invocation/global Fetch/file/network work.
8. Track attempted/cache keys as fragment-free absolute requested document URIs. Each URI
   is attempted once; no progress or null result terminates. Do not refetch an existing
   document because a fragment is absent. Requested URI remains an alias; root fetched `$id`
   defines canonical base/relative ref resolution. Use one JsonElementBaseDocument and
   Register(requestedUri, document). Never overwrite a distinct canonical/alias binding;
   detect conflicts before calling the library's alias overwrite path. Root `$id` handling
   is not permission to write a second schema walker or custom dialect implementation.
   A content conflict between distinct documents claiming one canonical ID is a terminal
   SchemaReferenceException at that canonical fragment-free ResourceUri, retaining the
   owned conflict as NativeInner. Registered-key constructor validation remains separate.
9. Add shallow root SchemaReferenceException : AnyInferException: category schema_reference,
   phase validate, Retryable false, ResourceUri fragment-free, optional Fragment, selected
   provider when called from generation, exact NativeInner (owned signal/native ref failure).
   Use bounded/redacted generic message and register/retrieve hint. Throw directly before
   RecordAssessment/repair/provider retry/attempt aggregation/success. Actual caller callback
   exceptions/OCE propagate unchanged. Do not manufacture dependency exceptions.
10. Actual validation/retrieval stays within the existing AsyncStream MoveNext ownership
    boundary. After every awaited retrieval, check owned effective/original-caller
    cancellation before caching/re-evaluating. Check again on return to GenerationCore
    before recording assessment, building repair or publishing success. Only owned checks
    can map original token identity; preserve callback OCE objects. A late token-ignoring
    callback cannot publish success. Off-lock cancellation retains AsyncClient/captured
    Client ownership, including UnsafeRegister; external consumer continuations stay unmarked.
11. Convert general results into the existing assessment/repair capture at one narrow
    internal bridge. Preserve native keyword/path facts and cap selected feedback at five.
    Do not normalize native feedback text to Python wording. Add invalid-schema kind only
    on the modern path; frozen observations/kinds/order remain exact.
12. Timeout handling uses shallow root SchemaEvaluationException:
    category schema_evaluation, phase validate, retryable false, selected provider or null
    for standalone, exact RegexMatchTimeoutException NativeInner. Map only owned native
    build/meta/evaluate calls; retriever-origin exceptions of that same type remain unchanged.
    Throw before assessment/repair/provider retry/attempt aggregation, just like reference
    failure. Use a generic bounded/redacted message without regex/input contents. Invalid
    regex syntax remains a controlled invalid-schema assessment, not a timeout.
13. Preserve the selected dependency's numeric domain. Root execution demonstrated that
    comparing a 10^70 `const` uses Json.More's decimal conversion and throws FormatException.
    Catch that exception only at owned native build/meta/instance evaluation calls and
    carry it through an internal EvaluationFailure signal to terminal SchemaEvaluationException.
    Retain its exact inner/provider, bypass assessment/repair/retry/fallback, and leave
    retriever/parser/serializer exceptions outside this mapping. Modern parsing/writing
    and permissive-schema structured retention still admit arbitrary BigInteger values.
    Test exact 10^20 const success separately from 10^70 retention and controlled comparison
    failure. Document native numeric limits; add no replacement arithmetic or dependency.

## Ownership and executable checklist

- [x] **SIG.0a** Inventory Python SchemaSpec/results and native admission/core/wire/repair
  seams. Gate: source-backed reports establish no Python model instantiation, late validation,
  constructor-controlled frozen path and shared orchestration.
- [x] **SIG.0b** Qualify dependency/license/dialect footprint and common semantics on isolated
  native/Python probes. Gate: root inspected four-package MIT metadata and 22 input-only
  observations; user explicitly selected modern/native scope; Python/frozen assets untouched.
- [x] **SIG.0c** Prove selected meta-schema validity, native diagnostic locations, fresh
  registries/same-ID isolation, raw cyclic resources and async owned-fetch bridge. Gate:
  root inspected extended/async JSONL, original pre/post-await tokens and Global.Fetch=0.
  > NOTE: Null-returning Fetch demonstrably fell through to globals; throwing the private
  > owned signal is mandatory. Refusal prototype still supplied an explicit null-returning
  > async resolver; production needs its distinct no-opt-in zero-invocation test.
- [x] **SIG.0d** Close requested/canonical URI alias/conflict/fragment proof and bounded
  contract/lifetime reviews against the exact contract above. Gate: requested alias and
  declared base both usable, no overwrite, no fragment refetch, final cold review closure.
  > NOTE: Root ran the revised alias bridge: declared-first/requested-second aliases both
  > validate; the relative child is fetched once at the declared base. Conflicting content
  > claiming the same canonical ID fails before registration. An absent fragment fetches
  > its document once, then retains native RefResolutionException. All nine async bridge
  > observations pass. Independent alias rereview is clean in Traycer
  > `csharp-sdk/sdk-four-schema-design-review`; the earlier profile/terminal/lifetime P1
  > closures remain valid. SIG.0e is the only remaining pre-implementation gate.
- [x] **SIG.0e** Qualify bounded regex execution before production selection. Pinned
  PatternKeyword/PatternPropertiesKeyword compile ECMAScript regexes without a timeout;
  official dialect IDs cannot be replaced in a local registry. The derived-handler clone
  probe failed at construction because native annotation dependencies require exact handler
  types; do not ship that approach. Test the public KeywordData.Value preprocessing hook
  on fresh privately owned compiled nodes supplied through a raw IBaseDocument decorator.
  Preserve standard handlers/dialects; substitute only native Regex values with identical
  pattern/options and finite timeout before evaluation. Traverse native compiled metadata,
  never re-interpret raw schema. Never mutate global/shared meta-schema nodes. Gate: four
  official dialects, nested/resource switches, patternProperties/additional/unevaluated
  annotation behavior, private ownership, finite timeout inspection and bounded failures,
  then cold contract/lifetime closure. If this
  public extension fails, record the blocker and settle a user-visible limitation before
  implementation; never imply cancellation bounds an unbounded native regex.
  > NOTE: Root's compiled-metadata probe passes all nine observations. Four official
  > dialects keep original handlers with 50ms regex values; external Draft7 conditional
  > semantics and exact timeout survive; property annotations and unknown-key omission
  > agree. Private copies of 18 meta resources validate valid/type-invalid/required-invalid
  > inputs across all four drafts, with five bounded regexes. Before/after identity plus
  > timeout snapshots prove all four original static meta Regex objects remain unchanged.
  > Final cold review found one P1: inline recursion can follow populated reference edges
  > into foreign nodes on a later pointer lookup. Correction must stop that recursion and
  > add independent full-graph provenance refusal plus an unchanged-unwrapped-resource
  > negative control before this gate closes. No source handoff yet.
  > Correction is saved and root's ten-observation run passes: inline traversal stops at
  > ref/recursive/dynamic edges; a separate provenance walk guards every evaluation. The
  > negative's wrapper/intermediates are owned, its actual target is unwrapped, and refusal
  > preserves target Regex identity and original timeout. Final P1 rereview is pending.
  > Final acceptance supersedes the holds above: independent contract and lifetime
  > ownership rereviews are clean in the two schema review artifacts. Root inspected
  > source and all ten observations; SIG.1 production handoff is authorized.
  No production source handoff before SIG.0d and SIG.0e are both checked.
- [x] **SIG.1** Runtime source wave — c708 owns new SchemaSpec.cs; Schema modern types
  and FrozenSchemaValidator; Errors.cs reference/evaluation exceptions; Models.cs typed helpers/request;
  AsyncClient.cs/Client.cs options/schema signatures; Core RequestNormalizer/GenerationCore;
  GenerationStream.cs/Internal/CancellationIdentityContext.cs minimal actual-execution
  identity integration; internal schema profile; JsonReader/JsonWriter SDK modes; WireRequest
  and builtin adapter schema name/SDK-only JSON serialization; AnyInfer.csproj exact dependency. Do not change provider lifecycle,
  catalog/pricing, route semantics or frozen assets. Hand exact saved public signatures to
  dependent owners. Gate: held source plus cold API/lifetime review, root guarded compile.
  > NOTE: c708 reports the saved public API foundation and has sent exact signatures to
  > dependent owners. Modern validation still temporarily reaches the frozen assessment
  > bridge while the qualified native registry/meta/resource/regex engine and core terminal
  > integration are being finished. This is an in-progress source state, not accepted
  > modern semantics; root compilation/review waits for a coherent complete handoff.
  > Later intermediate update: standalone evaluation now reaches JsonSchema.Net, but the
  > qualified private registry/meta/resource/retrieval/regex path and core integration are
  > still outstanding. Do not run this intermediate evaluator or count SIG.1 complete.
  > Latest saved source now includes private registries, 18 copied meta resources,
  > finite compiled-regex decoration and resolved graph ownership; modern extraction
  > assessment reaches that engine. Remaining SIG.1 symbols: async outside-native
  > retrieval/rebuild, canonical/requested alias conflict/progress, native-only regex timeout
  > mapping and owned post-await/core cancellation checks. Continuation is granted to c708;
  > no source review/compilation until this remaining integration is coherent.
  > Full source handoff was saved. Root restored dependencies and corrected three compiler
  > mechanics through c708; complete solution build02 passes with zero warnings/errors.
  > Native tests have not run: root/500e source review requires actual selected-meta
  > validation/dialect refusal, native error mapping and IsValid/path projection, seeded
  > canonical alias/conflict handling, owned-graph typed refusal and selected-provider
  > attribution. One coherent correction batch is assigned; lifetime token-flow rereview
  > is also pending. Logs: `.tmp-tests/schema-native-build-01.log` and `-02.log`.
  > ec8 confirmed original caller identity is not mapped over the linked generation stream
  > execution, so that file/helper scope is explicitly assigned. Root also confirmed modern
  > SchemaSpec/extraction still use the frozen integer ceiling; the original internal SDK
  > parser mode is required, with two focused >64-bit public controls assigned to 04f.
  > Modern-only parser and ordinary location/provider corrections are saved and cold-reviewed.
  > Root confirmed two semantic gaps still remain: selected private meta schemas are copied
  > but never evaluated, and canonical IDs are checked without governing root/seeded bindings.
  > c708 explicitly released ONLY `Schema/ModernSchemaEngine.cs`; c16 now owns that file's
  > meta validation/canonical binding/native validity correction. c708 retains all wrapper,
  > public result, parser, stream/Core/identity and exception integration, including native
  > reference fragment projection. Their file leases are disjoint; neither runs processes.
  > Root waits for coherent held snapshots and cold review before the next guarded compile.
  > ec8's retained lifetime rereview is clean: actual MoveNext effective/original identity,
  > nested sync identity, close-only cancellation, callback exception identity and selected
  > provider terminal construction are source-verified. Engine/meta/canonical acceptance
  > and runtime gates remain pending; this does not tick SIG.1.
  > Root's combined reread found the modern assessment bridge still ignored native
  > Kind/IsValid and discarded location facts. c708 also owns a minimal NativeAssessment
  > kind allow-list extension for modern `invalid_schema`; frozen producers stay unchanged.
  > The bridge must retain native locations, honor validity independently of diagnostics
  > and supply a fallback finding for native invalidity without projected issues. Fetched
  > cache inputs stay requested-keyed so relative `$id` is not re-applied to an alias.
  > c16's held engine correction passed 500e's cold source review: canonical preflight
  > and binding, selected private meta evaluation, native validity/locations/cap and the
  > decorator/ref-edge/provenance guard are accepted. The retained wrapper assessment
  > bridge correction is still pending; no new compile/runtime result is claimed.
  > Joint engine/wrapper source and lifetime reviews are now clean. Root's complete
  > build04 passes with zero warnings/errors after narrow compiler fixes. Focused native
  > run01 passes 28/33: two real failures expose the remaining frozen writer ceiling in
  > modern schema hashing/prompt projection. c708 owns a shared SDK-only writer mode and
  > its prompt/wire/typed-result propagation; c16 migrates only engine calls after handoff.
  > Public/frozen writer behavior stays exact. Three independent test setup corrections
  > (framework metadata resolver/case policy, unsupported exact diagnostic count, unquoted
  > regex instance) are assigned to 04f with strict causal assertions retained. Native
  > BigInteger tests stay unchanged; add a real builtin HTTP payload regression. Logs are
  > `.tmp-tests/schema-native-build-04.log` and `schema-native-focused-01.log`.
  > Root build06 passes with zero warnings/errors. Focused run02 passes 31/34, including
  > timeout, refs, repair and lifetime controls. The three remaining failures share one
  > newly measured dependency limit: a 10^70 `const` comparison calls native
  > `JsonElement.GetDecimal` through Json.More and throws FormatException. Modern parsing,
  > writing and retention are separate from native numeric comparison range. c16 is
  > auditing the exact dependency source; 500e is reviewing a controlled terminal mapping
  > and explicit numeric-limit coverage within the user's accepted native semantics.
  > No replacement arithmetic, package upgrade or test expectation change is yet accepted.
  > Logs: `.tmp-tests/schema-native-build-06.log` and `schema-native-focused-02.log`.
  > The native-limit policy is now accepted within the user's existing native numeric
  > decision after 500e critique. Step 13 pins the narrow terminal mapping and explicit
  > supported-comparison/retention/failure controls; c16 owns engine signal/docs, c708 owns
  > wrapper/error projection, and 04f owns independent tests. This records a measured
  > native limit rather than claiming arbitrary-range comparison support.
  > Root build07 is clean. Focused run03 passes 35/38, including actual native-range const
  > success, arbitrary-size retention, controlled numeric failure and raw retriever identity.
  > Two remaining failures are new tests expecting the reader's FormatException from the
  > frozen writer, whose unchanged exception is ArgumentOutOfRangeException. The real builtin
  > wire control also exposed missing `response_format`: c708 owns modern-only Python-aligned
  > json_schema/name/schema/strict:false and json_mode/json_object projection plus the
  > existing contract note. Frozen payloads stay exact. 04f retains the strict wire test
  > and adds a json_mode control. No full gate until these corrections pass.
  > Final source is accepted: root build09 has zero warnings/errors, cold source/lifetime
  > reviews are clean and all 39 focused native cases pass in run05. The builtin HTTP
  > controls execute json_schema/name/schema/strict:false and json_mode with the exact
  > canonical prompt. The copied frozen validator body matches HEAD byte-for-byte after
  > its class visibility/name migration, and all three released manifest/report hashes
  > remain unchanged. Full workspace gate is running as Traycer shell
  > `15700c60-aab8-4e7d-ba59-caa873941eb0`; no broad acceptance or commit yet.
- [x] **SIG.2** Independent test wave — 04f owns new ModernSchemaTests.cs and
  SchemaIntegrationTests.cs, `tests/fixtures/sdk-schema-v1/` input-only stimuli and
  `tests/test_sdk_schema_parity.py` independent Python helper bridge. Read saved signatures
  first. Cover four drafts, malformed schema/extraction precedence, refs/cycles/aliases/
  conflicts, default no retrieval/explicit async opt-in, format off, documented native
  numeric/regex differences, metadata/name, typed options/typeinfo/null, single repair/no
  fallback, callback fault/OCE identity, close/late result and unsafe self-dispose. Cover public
  timeout options, invalid-regex feedback and planted retriever timeout identity. Use actual
  public clients/readiness gates; no private test hooks or expected-driven adapter outputs.
  Gate: cold causal review, root focused native/Python runs with no changed frozen oracles.
  > NOTE: Shared input and independent Python helper are saved. Root py_compile/Ruff pass;
  > all 24 Python bridge tests pass. The initial shared pytest cache was inaccessible at
  > session finish; the unchanged suite exits zero with task-specific cache
  > `.tmp-tests/schema-qualification/pytest-cache`. Native tests await saved SIG.1 API.
  > The public API handoff is now saved. Native authoring proceeds against strict agreed
  > behavior while engine internals finish; incomplete stubs are not an oracle or a reason
  > to defer all authoring. Root execution still waits for coherent runtime/tests.
  > First native snapshot is saved. Required remaining timeout, alias/cycle/conflict and
  > retrieval cancellation/close/unsafe-owner cases are being added using public callback
  > readiness gates; they are not deferred past this milestone. No native execution yet.
  > Expanded two-file native snapshot is now complete, including alias/cycle/conflict,
  > patternProperties timeout, raw retriever CLR-timeout/OCE identity and async/sync unsafe
  > owner controls. Cold causal review is clean in `sdk-four-schema-tests-review`; lifetime
  > review remains pending. No native compilation/execution until coherent SIG.1 handoff.
  > Both final causal/lifetime reviews are now clean, including late retrieval under
  > cancellation with one primary request, zero fallback requests and original-token OCE.
  > This is held-source review closure only; native execution/box acceptance still pending.
  > Accepted after cold review and root execution: 39/39 focused native cases pass in
  > `.tmp-tests/schema-native-focused-05.log`; the independent Python bridge passes 24/24.
  > Corrections use actual native numeric limits and the unchanged frozen writer exception,
  > with explicit retention/comparison/failure controls. Shared input remains input-only;
  > no frozen fixture verdict or expected result was changed.
- [x] **SIG.3** Mechanical callers/package wave — c16 owns frozen conformance callers and
  existing admission/schema tests only for exact SchemaSpec/internal-validator migration;
  scripts/check_csharp_package.py and tests/test_csharp_packaging.py; src/csharp/README.md.
  Do not edit fixture expected data or simplify assertions. Preserve root archive payload,
  root MIT/source metadata and local-feed/private-cache consumer. Check root exact direct
  dependency separately from resolved four-package graph/license/hash evidence. Stage only
  verified dependency nupkgs into that local feed, never restore consumer from user/global
  sources. Public-only consumer must run modern schema/typed result and retain all prior
  generation/lifecycle/disposal checks. Gate: static review, root fresh local-feed consumer
  and negative dependency/archive tests.
  > NOTE: Independent package checker/tests/README slice is saved. Root py_compile and all
  > 20 focused packaging tests pass. Ruff found seven line-wrap/import mechanics routed
  > back to c16; public modern consumer and frozen mechanical migration await SIG.1 API.
  > Those seven mechanics are corrected and root's targeted Ruff rerun passes. The 20
  > behavioral checks are unchanged; no redundant test rerun was needed for formatting.
  > Public API handoff is now available: dependent mechanical/consumer/docs authoring
  > proceeds while runtime internals finish, with execution held for the coherent gate.
  > Dependent consumer/docs/caller snapshot is saved. Root found Python/C# nested quote
  > delimiter syntax failure and required an actual schema-bearing client generation for
  > the package typed-result proof; both are routed to c16. Cold review also identified
  > NativeProofs' public FromAdapters profile: its factory now uses the friend-only
  > registrations/VirtualClock constructor so frozen observations retain their profile.
  > Corrected actual-client consumer passes root py_compile/Ruff and all 20 focused
  > packaging tests. Final cold rereview accepts consumer/docs and all schema-bearing
  > conformance paths using frozen clock construction. Real package/native/example/docs
  > execution still waits for completed SIG.1; SIG.3/SIG.4 remain unchecked.
  > Accepted after actual execution: root's isolated package checker passes at
  > `.tmp-tests/nuget/run-hqj97joa/`, including closed archive/dependency/hash/license checks
  > and fresh local-feed/private-cache consumer restore/build/run with zero warnings/errors.
  > All 20 package tests, targeted Ruff and py_compile pass after the generated C# JSON
  > raw-literal correction. Frozen RoutingTests helper now explicitly wraps raw schemas
  > with literal response name. This proves working-tree functionality; clean-revision
  > package qualification remains SIG.5 after the source commit.
- [x] **SIG.4** Exact docs/examples wave — c16 owns StructuredOutputExample.cs, its Program.cs
  integration and affected C# guide/porting/reference/task pages. Show actual SchemaSpec and
  typed deserialization in the same compiled source rendered by the site. Document four
  supported drafts, deferred3/4, native numeric/regex limits, registered/explicit-retrieval
  behavior and Python distinction. No plan links/ADR identifiers or paid-release claims.
  Gate: root offline example run, strict docs and exact rendered-source equality.
  > Accepted: workspace01 strict docs and actual offline C# examples pass. Root independently
  > compared all 15 included C# blocks across six rendered guide pages with the exact source
  > files; every block matches. Typed sample and external consumer explicitly map lowercase
  > answer to normal C# properties. No hand-copied snippet or plan link was introduced.
- [x] **SIG.5** Root final checkpoint: inspect reviews/diff; zero-warning solution; focused
  modern schema/Python/package tests; complete native conformance including unchanged all102;
  full workspace check once; unchanged frozen digests; update achieved inventory limitations
  without ticking broad root exports. Commit explicit paths and run clean-revision isolated
  package proof. Gate: accepted source checkpoint/evidence, clean tree, main SDK.4b checked
  only for the user-approved modern scope, resume SDK.4c with legacy3/4 still SDK.11c.
  > NOTE: Callback test ordering is corrected and both independent reviews are clean.
  > Production lifecycle code is unchanged. Root native-full-02 passes 343/343 unit and
  > 93/93 conformance tests, including the released 102 observations. Fresh package retry
  > passes at `.tmp-tests/nuget/run-hqj97joa/`. Final full workspace rerun is active as shell
  > `cb367dce-c8f6-471c-843a-43376e1d8a69`; commit/clean-revision proof still pending.
  > Final workspace02 passed all 18 steps in 114.6s: 343 native unit tests, 93 conformance
  > tests, full Python suite, strict docs, offline examples and isolated package execution
  > at `.tmp-tests/nuget/run-dj9uqmc8/`. Exact rendered-source and frozen hash checks also
  > pass. Root is committing explicit source paths, then qualifying the clean revision;
  > do not mark this final box complete before that proof.
  > Accepted source checkpoint: `dbf82a949fca6ee7321b921233c0cda198b3a506`.
  > Working tree was clean before and after fresh package/symbol inspection and isolated
  > local-feed/private-cache restore/build/run at `.tmp-tests/nuget/run-cgy2od91/`.
  > The consumer builds with zero warnings/errors and package metadata names this exact
  > committed revision. SDK.4b is complete for the approved modern/native scope; parent
  > resume is SDK.4c. Legacy Draft 3/4 and broader parity remain explicit outstanding work.

## Resume/evidence

This child plan is complete at source `dbf82a949fca6ee7321b921233c0cda198b3a506`.
All SIG.0–SIG.5 gates pass. Final workspace02 passed 18/18 in 114.6s; the clean-source
package proof is `.tmp-tests/nuget/run-cgy2od91/`. Resume parent SDK.4c capability probes
and metadata. No full-library parity or legacy Draft 3/4 completion is implied. Prototype
files remain ignored; they qualify mechanisms but do not replace production gates.
Root scratch transcripts: `.tmp-tests/schema-qualification/shared/` JSONL files.
Durable interpretation/reviews are in Traycer `csharp-sdk/sdk-four-schema-{qualification,
design,design-review}` and `foundation-execution/csharp-sdk/sdk-four-schema-mechanism-review`.
Re-read this plan after each wave and reconcile checked boxes with actual results.
