# Native .NET connection settings

Resume from the first unchecked box. This leaf implements the connection-settings prerequisite
of SDK.8a; it does not register presets, complete provider breadth, or qualify the full SDK.
Root alone owns Git, generated output, shared compilation, native runs and final gates.

## Settled scope and reference

Reference HEAD: `c83816f4157ee0e371ec12ba08311d57d3ba447e`, tree
`a051157bfb1d11b3cd7117129e2f7a33d1507b14`. Parent: `ANYINFER_CSHARP_SDK.md`.
On 2026-10-23 the user selected **Native .NET TLS**: use platform certificate validation,
document custom-trust differences from Python, reject unsupported settings, and avoid an
additional crypto runtime. This is an explicit TLS semantic exception, not permission to
ignore policy or claim exact Python/OpenSSL trust behavior. Keep net8.0 and existing packages.
Python behavior, released core v0 and its 102 observations stay unchanged.

The selected implementation supports HTTP(S) proxy URIs, default/disabled/PEM-bundle TLS
verification, and combined/split/encrypted-pair PEM client certificates. OpenSSL hashed CA
directories fail explicitly at materialization. No PFX/config key/resolver scheme is invented.
Literal proxy credentials and PEM passwords remain literal, like the existing Python inputs;
credential-reference/rotation expansion remains SDK.11. Literal config output remains lossless
configuration data, while object/error/event representations stay safe.

The previous scratch experiments explain the exception; they are not production tests or a
shared trust oracle. In particular, no AllowUnknownCertificateAuthority, peer-trust shortcut,
manual prefix acceptance, P/Invoke, OpenSSL library or raw-peer collection assumption is used.

Redirect behavior stays unchanged in this bounded slice. SDK-created handlers continue with
`AllowAutoRedirect = false`. Python enables redirects; its method/header/hop-count and per-hop
pacing contract remains an explicit SDK.8a/11c prerequisite after this leaf. This is unfinished
parity work, not a new user-approved HTTP exception. Never enable redirects incidentally as
part of the TLS factory.

## Closed API and configuration contract

Add root-namespace public sealed immutable records with explicit constructors, get-only
properties, XML docs and explicit constant/identity-only ToString. Do not use positional
records or derived record cases whose generated PrintMembers/ToString can expose values.

- `ProviderProxy(Uri address, string? userName = null, string? password = null)` exposes
  `Address`, `UserName`, `Password`; `static ProviderProxy Parse(string value)` decodes a
  literal proxy URI. Require absolute HTTP(S), a host, no query/fragment, and no path other
  than empty or `/`. Direct constructor address must have no userinfo; Parse splits at the
  first userinfo colon, percent-decodes credential components, and retains a userinfo-free
  address. Parse also retains the exact validated trimmed original literal in a get-only
  internal ConfigurationValue for Dumps (including host case, explicit default port and
  percent-escape spelling). Never reconstruct that parsed literal from Uri/decoded userinfo.
  The direct public constructor has no prior config literal: derive its ConfigurationValue
  once from the supplied address and correctly escaped explicit credentials. Preserve all
  connection meaning, then retain that value unchanged. This secret-bearing internal value
  is never part of ToString/diagnostics. Reject malformed input using constant messages and
  TryCreate, never echo a URI. HTTP(S)-only admission is an explicit supported subset; SOCKS
  and other schemes fail with a supported-schemes hint, not an ignored proxy setting.
  Null settings proxy preserves .NET default/environment proxy policy. Explicit proxy uses
  WebProxy plus NetworkCredential; no credentials may become origin Authorization.
- `TlsVerification` has a private constructor, `static TlsVerification Disabled { get; }`,
  `static TlsVerification FromPemBundle(string path)`, and get-only `string? PemBundlePath`.
  Null settings verification means system default. Non-null with null PemBundlePath is
  Disabled; non-null path is a custom PEM bundle. Empty paths are rejected without I/O.
- `ClientCertificate` has a private constructor and factories
  `FromPemFile(string certificatePath)`,
  `FromPemPair(string certificatePath, string privateKeyPath)`, and
  `FromEncryptedPemPair(string certificatePath, string privateKeyPath, string password)`.
  Expose get-only `CertificatePath`, nullable `PrivateKeyPath`, nullable `Password`. Validate
  nonempty path/password shape without file I/O; same certificate/key paths are legal.
  Null PrivateKeyPath means combined unencrypted PEM. No init setters or public derivation.
- Append `ProviderProxy? proxy = null, TlsVerification? verify = null,
  ClientCertificate? clientCertificate = null` after `limits` in ProviderSettings constructor
  and Of. Expose `Proxy`, `Verify`, `ClientCertificate`. Copy all three in ProviderConfig and
  its private WithTransport constructor. Preserve them by name in default-base-URL settings
  reconstruction. Async and sync facades continue consuming the same settings object.
- Append `bool honorsConnectionSettings = true` after modelInventory in ProviderDescriptor;
  expose `HonorsConnectionSettings`. Active means any of the three settings is non-null.
  Config parsing rejects active settings for a descriptor that declares false (config files
  cannot inject Transport). Lazy direct-settings build applies that gate only when the original
  ProviderSettings.Transport is null. A non-null original Transport bypasses the connection-
  capability gate as well as all connection material validation/loading; ordinary structural
  settings and provider-specific factory validation remain. Default/verify:true are inactive.
  The four existing builtins honor them through the shared factory; custom factories declare
  and implement their own support. No provider-id branches in generic config/pool code.

`AnyInferConfig` keeps format version 1 and existing field spellings and precedence.

| JSON input | Native projection / output |
| --- | --- |
| proxy omitted/null | null; omit on output |
| nonblank proxy string | Parse trimmed string; Dumps emits the exact retained trimmed literal |
| verify omitted/true | null; omit on output |
| verify false | Disabled; output false |
| verify nonblank string | FromPemBundle(trimmed path); output path |
| verify null, wrong type or blank string | ConfigException; actual Python rejects explicit null |
| client_cert omitted/null | null; omit on output |
| nonblank client_cert string | FromPemFile(trimmed path); output string |
| two nonempty string elements | FromPemPair; retain component literals; output two-element array |
| three nonempty string elements | FromEncryptedPemPair; retain component literals; output three-element array |
| other certificate shapes | ConfigException without printing values |

Parsing, typed construction, Dumps, registry creation, client construction and unadvanced
streams perform no certificate-path checks, environment reads, credential resolution, adapter
construction or HTTP work. Do not call Directory.Exists at parse time. During lazy owned-handler
materialization, distinguish directory inputs and refuse them with an actionable PEM-file hint;
missing files, empty/malformed CA files, missing keys and bad passwords fail as ConfigException
before network dispatch. This deliberately corrects the earlier native inactive subset's
acceptance of explicit verify:null; retain the old test and update it with the actual Python
source reason, rather than silently widening the new parser.

Literal config serialization may contain configured secrets, as existing api_key serialization
does. Do not replace secrets with redaction markers in Dumps or add implicit resolver behavior.
Register literal proxy username/password and certificate password before any connection-specific
operation can produce diagnostics; cover direct types and parsed settings. URI admission errors
must use TryCreate/constant diagnostics even before registration succeeds. Do not rely on the
redactor's six-scalar threshold to make short secrets safe: stable messages/details/hints must
contain no supplied connection values at all. Preserve existing NativeInner semantics for actual
materialization failures; library ToString/snapshots/events must remain safe.

## Shared material and handler ownership

New internal `Providers/ConnectionHandlerFactory.cs` exposes
`CreateOwned(ProviderConfig config, CancellationToken cancellationToken)` returning an owned
HttpMessageHandler. An internal material owner and private delegating-handler wrapper retain
imported certificate objects. Use SocketsHttpHandler;
leave default proxy and SslOptions untouched unless explicitly configured, and preserve redirects
OFF. This factory is the sole SDK-created HTTP handler construction point, including legacy
internal adapter constructors exercised by frozen/native tests.

- Default verification installs no validation callback or custom chain policy.
- Disabled installs an accept-all callback only on that one owned handler. No automatic
  fallback reaches this case. The public setting explicitly disables certificate validation.
- Custom CA bundle imports PEM certificates into handler-local CustomRootTrust with NoFlag,
  NoCheck revocation (normal default HTTP behavior), certificate downloads disabled, and TLS
  server-auth purpose. Preserve hostname and ordinary platform errors: do not override an
  invalid certificate with a custom success callback. Reject a bundle with zero certificates.
  System roots are replaced, not augmented. Platform handling of intermediate/leaf anchors,
  chain selection and strictness differs from the selected Python/OpenSSL runtime and is not
  normalized. Tests use actual platform results and negative controls, not rewritten Python
  oracle labels. No global store mutation or ambient environment changes.
- Combined/split PEM use BCL CreateFromPemFile; encrypted pair uses
  CreateFromEncryptedPemFile, with same-path pairs supported. Own all imported certificates
  through handler lifetime. On Windows, reimport client PEM certificates from an in-memory
  PKCS#12 byte buffer using UserKeySet for Schannel compatibility; zero that buffer in finally
  and own only the replacement after disposing the source. Do not use PersistKeySet,
  MachineKeySet, EphemeralKeySet, an X509 store or a PFX file. This uses temporary OS-managed
  user-key backing, which may be on disk; it is not memory-only. Dispose the handler before
  the material certificate; native context references can defer normal key cleanup, and
  abnormal process termination is outside that cleanup guarantee. Non-Windows keeps its
  original PEM certificate. Cold review and actual client TLS gates must pass before accepting
  this conversion; no permissive verification workaround is allowed.
- Pass the effective construction token from all four adapter factories and the governed
  raw-handler branch. Legacy internal constructor callers use an explicit default token.
  Check it before materialization, before and after each synchronous file/import operation,
  after adopting material into the local owner, and immediately before returning the handler.
  Synchronous BCL import is not interruptible mid-call; cancellation is observed at the next
  owned checkpoint, not by claiming prompt interruption of that native call.
- Dispose the inner handler before its retained certificate material, exactly once. On any
  failure, including an owned cancellation checkpoint, dispose every partially imported
  certificate and handler and rethrow the same exception. Never catch an arbitrary I/O/native
  failure and replace it merely because a token is now cancelled. The factory preserves its
  supplied token; the existing pool CancellationIdentityContext/owned-cancellation mapping
  remains authoritative for caller-token identity. Do not invent a second cancellation map.
  Do not cache failed builds or dispose injected resources before adoption. After successful
  publication, the existing pool owns cancellation-versus-adoption cleanup.
- A caller-supplied Transport is total takeover: bypass the connection capability gate even
  for a false-capability descriptor, load/apply no proxy/TLS/certificate material, and do not
  wrap or mutate the caller's connection policy. This decision uses original settings, not
  merely config.Transport after an internal governor was inserted. Preserve the current pool
  ownership flags and transferred/borrowed-handler rules. A governor wrapping an SDK-created
  raw handler still receives the real configured connection policy, not a null-config default.

Replace fallback constructors in OpenAIChatAdapter, TeiHttpTransport, VoyageHttpTransport,
JinaHttpTransport and Core/ProviderRegistry.CreateRawTransport. Forward ProviderConfig (or a
single immutable internal snapshot) rather than copying only Transport. Direct adapter
factories validate base URL, headers and options before creating owned material; any later
failure cleans it. The existing governed-pool path constructs its raw transport before the
provider factory validates provider-specific fields. Preserve that established lazy-build
ordering rather than adding a provider-id branch or new generic validator: materialization
still occurs only for the selected adapter build, and either configuration failure precedes
wire dispatch. Preserve narrow provider exception and cancellation identity contracts. No
retries, timing, routing or provider-specific connection branches enter adapters/core.

## Inert preset/source boundary

CompatPresetSourceFacts keeps full declaration operations and source facts. Generation rows
remain exactly singleton Generation, inert and disjoint from the default registry. Require an
explicit honorsConnectionSettings argument after modelInventory in CompatPresetGenerationRow;
forward it to the descriptor and enforce source/native agreement in CompatPresetDefinition.
After the actual shared factory/control gates pass, no connection-settings pending entry remains
for these generation rows within the approved native TLS contract. This is no claim of redirect,
other operation, registered provider, live-server or full-SDK support.

Update the closed generator projection to emit the source boolean explicitly. Bump
GeneratorVersion from 2 to 3; SchemaVersion stays 1. Root regenerates CompatPresetTable.g.cs.
Independent native reader joins every source boolean to every descriptor and catches real-row
mutations; Python controls prove fresh-render byte equality and closed vocabulary. Do not alter
maintenance/provider-parity/python-builtins.json or its source inventory to accommodate native
behavior. Existing default registry stays four descriptors/seven bindings.

## Ownership and executable checklist

Owners are the existing designated agents, on disjoint files. They are not alone and must never
revert another owner's edits. No child touches Git or invokes restore/build/native/full tests.
Root grants one plan-note edit lease at a time after each saved-source handoff; each owner
re-reads the leaf immediately before ticking its assigned box/adding a deviation note. No box
is checked from source review alone when its gate requires runtime evidence.

- [x] **NCON.0 — Contract.** Root records user exception and this leaf in the parent, then a
  cold reviewer runs traycer-artifact-critique against live source, prior ownership plans and
  the selected native scope. Close P1/P2 before production leases. Gate: exact reviewed leaf,
  no unresolved public-shape/ownership/semantic decisions; no TLS waiver beyond user choice.
  > NOTE: Source/ownership review closed injected-handler gating and cancellation checkpoint
  > P1s at contract 25ec7af...; acceptance review closed retained proxy-literal P1 and checked
  > the coherent current leaf f61d2bb8c7676fecc7cbf72a958c579818e241e3baf6f8ae1f4f60cd265a1db2.
  > Both are bounded clean with no residual P1/P2. This closes the contract only, not runtime
  > or platform qualification. Reviews: Traycer sdk-eleven-connection/native-connection-contract-
  > source-review and native-connection-contract-acceptance-review.
- [x] **NCON.1 — Values and propagation.** 3add owns new ProviderProxy.cs, TlsVerification.cs,
  ClientCertificate.cs plus ProviderSettings.cs, Providers/ProviderConfig.cs,
  Providers/ProviderDescriptor.cs and the default-URL/direct-capability portions of
  Core/ProviderRegistry.cs. Save exact shapes; get cold source review. Gate: root compile plus
  meaningful immutable/safe-display/copy/false-capability controls after NCON.4 is saved.
  > NOTE: Closed by exact values/copy source review, zero-warning builds, the passing
  > 195-case focused-third gate (10 settings/20 transport), and full-third all25. Literal
  > proxy roundtrip, immutable safe displays, injected false-capability bypass and settings
  > reconstructions are exercised. Clean source qualification remains NCON.7.
- [x] **NCON.2 — Owned handler integration.** 3add owns ConnectionHandlerFactory.cs and the four
  adapter/transport construction sites, their direct dependent factory calls, and the governed
  CreateRawTransport branch in Core/ProviderRegistry.cs. Integrate only after NCON.1 shapes.
  Gate: root zero-warning compile and actual shared-handler/TLS/proxy/lifecycle controls;
  no direct default handler constructor remains outside the common factory.
  > NOTE: Closed by integration/handler source review and actual full-third native gates.
  > The common factory is the only default handler allocation path. Controls exercise all
  > four adapters, governed raw transport, instance-local Disabled, custom-root positives/
  > negatives, authenticated HTTP/HTTPS proxy, all four mTLS forms and cancellation/disposal.
  > Actual Schannel client failure justified Windows UserKeySet reimport; cold ownership
  > review and seven positive cases pass. Safe ConfigException rendering omits the native
  > chain while NativeInner/InnerException preserve exact identity. Earlier compile/runtime
  > failures and their corrections remain in named .tmp-tests directories and task artifacts.
- [x] **NCON.3 — Config and generated projection.** After NCON.1 signatures are saved, 8969
  owns Config/AnyInferConfig.cs, scripts/generate_csharp_compat_presets.py and its Python tests,
  Providers/CompatPresetData.cs, and the assigned generator/config artifact. No overlapping
  Core edits or generated-table writes. Root emits the table and inspects exact byte change.
  Gate: focused generator/config tests, no-write --check, all-row independent semantic join,
  config roundtrip/no-I/O and source-derived mutation controls. Inventory bytes stay pinned.
  > NOTE: Closed by source/generator review, all Python generator controls in full-third,
  > no-write --check and independent native semantic joins/config tests. The root-generated
  > v3 table SHA is f0ae5f9ac7a0ee9420d882a503590d6bf9de470c6185cefbcc8f8c5c29c2f845;
  > inventory stays47c2f58b... and schema stays1. Single-string client_cert is trimmed;
  > array component/password literals are retained. No default registry addition.
- [x] **NCON.4 — Independent controls.** 04d owns new ConnectionSettingsTests.cs and
  ConnectionTransportTests.cs plus needed minimal changes to ConfigTests.cs,
  ProviderSettingsTests.cs, CompatPresetDataTests.cs, ConfiguredTransportOwnershipTests.cs and
  GovernedTransportTests.cs. Preserve existing public/lifecycle controls. Use a test-only
  synthetic loopback TLS/proxy helper, no real keys/certificates/provider endpoints and no
  production hooks added for manufactured booleans. Gate: actual public client + shared
  factory witnesses, reviewed raw effects, all targeted tests pass with zero skips.
  > NOTE: Closed by exact independent source/control rereview, focused-third195/0/0 and
  > full-third1051/0/0 unit tests. The 30 new settings/transport cases pass; inherited config,
  > preset joins, ownership, governance and credentials controls remain passing. Negative TLS
  > cases retain public rejection/no HTTP plus bounded direct client secure-TLS errors;
  > actual matching-root/mTLS positives establish the fixture first. Final fixture corrections
  > cover Schannel server keys, PEM boundaries, authenticated proxy counts, joined tunnel
  > shutdown, 15-second caller bounds and nonvacuous started/failed secret event projections.
  > Real imported material exercises the production Adopt(cert, token) ownership checkpoint.
  > Prior failed gates remain retained; no TLS relaxation or test weakening closed them.
- [x] **NCON.5 — Public delivery.** After shapes and behavior are saved, docs owner e588 owns
  C# SDK/reference/porting text and source-shared runnable examples; 8969 owns the isolated
  package consumer and its causal Python controls after NCON.3. Gate: exact public types
  compile from packed package, same snippet source executes offline, strict docs pass; native
  TLS differences/directory refusal/injected takeover and still-open redirects are precise.
  > NOTE: Closed by public-delivery source review, actual full-third package-only consumer,
  > source-shared offline examples and strict docs. Docs bound native trust/directory refusal,
  > injected takeover, still-disabled redirects and temporary Windows OS user-key backing
  > without a memory-only/immediate-deletion claim. No package publication or cross-OS SDK
  > support follows. Clean source/package evidence remains NCON.7.
- [x] **NCON.6 — Held-source checkpoint.** Root runs one guarded full workspace check using
  the existing all-phase registry, preserving all tracked/untracked slice sources and pinned
  user inputs. Cold source/control/docs/generator reviews must close. Gate: all development
  steps, all native suites, five existing paired profiles, package/examples/docs, Frozen 102;
  no changed protected input, no hidden skips or claim based only on injected handlers.
  Then root commits only explicit slice paths; uv.lock and v/cache/nodeids remain untouched.
  > NOTE: Full-third complete evidence and independent rereview are bounded clean.
  > Root committed exactly39 slice paths as8758b0eedf9f69077274a666da3919e9f83380a0,
  > tree1f20c9fa0f95142a28f7713b6de9ebfb12a424b5. Only useruv.lock/v/cache/nodeids
  > remain untracked; both pins are unchanged. The checkpoint plan records the pre-commit
  > state; clean acceptance and later plan-only reconciliation remain separate.
- [x] **NCON.7 — Clean qualification.** Root creates a clean checkout of that executable
  revision and runs the registry-derived exact C# gate plus targeted connection loopback
  controls and Frozen DEVELOPMENT. Retain selected checkout/import, commands/exits,
  initial/final HEAD/tree/clean state, hashes and source stamps. Gate: successful clean
  package/examples and native connection witnesses, unchanged protected inputs, independent
  evidence-only review; no cross-OS promise from one Windows run.
  > NOTE: Clean run local-native-connection-8758b0ee-20261023T134450Z qualifies executable
  > 8758b0eedf9f69077274a666da3919e9f83380a0/tree1f20c9fa0f95142a28f7713b6de9ebfb12a424b5.
  > Registered12steps,1051unit/93conformance zero skips,173focused(10settings/20transport),
  > five clean-stamped pairs, package/examples and explicit Frozen102 pass. All1255 tracked
  > inputs, external helper/operator/factory bindings and initial/final clean identity match.
  > Independent qualification review is bounded clean. First clean attempt's existing
  > external-close5-second timeout remains retained and unexplained; isolated and full retry
  > passed without code or timeout changes. No all-attempts/cross-OS/full-SDK claim follows.
- [x] **NCON.8 — Reconciliation.** Root re-reads parent/leaf, updates achieved docs and
  records executable evidence separately from the later plan-only commit. Gate: bounded
  source/gates/checks agree, default registry remains 4/7, all still-open SDK rows remain
  open. Resume the explicit redirect contract, then researched preset registration and
  remaining SDK.6c/8b-c/9–12; do not ask again to continue already authorized core SDK work.

  > NOTE: Independent parent/leaf critique is bounded clean after correcting the immediate
  > resume heading. This plan-only record completes reconciliation and does not replace
  > executable source `8758b0eedf9f69077274a666da3919e9f83380a0` or its clean evidence.
  > Resume SDK.8a's explicit redirect contract, then researched registration. All broader
  > API, operation, platform and release requirements remain open.

## Required independent witnesses

Use existing provider/config/ownership controls rather than duplicate assertions of private
implementation. Tests must prove these observable effects:

1. Every literal config form roundtrips through real settings/config/default URL/WithTransport
   copies. Proxy controls include mixed host case, explicit default ports, percent-escaped
   username/password spelling and colon-containing passwords: parsed connection values are
   decoded correctly while Dumps retains the trimmed original literal exactly. Direct typed
   construction serializes a valid stable equivalent. Reject SOCKS/other unsupported schemes.
   Counting resolver/factory/transport spies stay at zero through parse/construct and
   unadvanced streams, then the same spies become positive on real iteration.
2. All four owned adapter paths and the governed raw-handler path reach the same connection
   factory. At least one real public generation client and each retrieval transport use an
   actual loopback TLS or proxy witness; an injected handler cannot prove owned TLS/proxy use.
3. Synthetic root-signed localhost server accepts the matching CAfile and rejects unrelated CA,
   wrong hostname, wrong server EKU and expired leaf/root without permissive callbacks. Native
   partial-anchor limitations are documented/tested as platform behavior. Empty/malformed and
   directory CA input fail before send. Disabled works only for the explicitly configured
   instance and does not alter another instance or global validation.
4. Server-required mTLS sees the configured client certificate for combined, split and
   encrypted pair (including same-path encrypted pair); wrong/missing keys/passwords fail
   before dispatch. Cancellation/failure/disposal release owned resources and preserve
   original caller cancellation. Verify pre-cancelled construction does no material I/O; an
   internal material-owner control uses actual imported certificates and cancellation at an
   ownership checkpoint to prove disposal, without sleep/race timing or a production hook
   that fabricates success. A readiness-gated public factory wrapper cancels after the real
   builtin returns an owned adapter, proving pool late-adoption cleanup and caller-token
   identity. Do not claim cancellation interrupts synchronous import. No key/payload/password
   is emitted to retained test evidence.
5. Actual loopback proxy observes forwarding/CONNECT and credential separation; an explicit
   proxy bypasses ambient proxy ambiguity. Malformed/unsupported proxy input fails safely.
   Do not depend on the developer machine's process proxy/CA environment or change it globally.
6. Injected Transport plus deliberately nonexistent/invalid certificate files still performs
   the real request with no file materialization and retains existing adoption/disposal rules.
   Include an HonorsConnectionSettings=false descriptor with active connection values and an
   injected handler: its factory is invoked and the real request succeeds. The same descriptor
   and active settings without injected Transport reject before factory/network work.
   Default URL binding and governor reconstruction preserve the exact connection values.
7. Planted short and long proxy/password secrets never appear in safe ToString, nested errors,
   snapshots, diagnostics or events. Config Dumps retains literals intentionally. Test actual
   failure/copy paths, not just a standalone redactor. No raw native inner-message interpolation.
8. Every compiled preset row agrees with independently parsed source honors_connection_settings,
   all prior setup/capability/provenance/dialect/reasoning joins and singleton operation checks
   remain, and default-registry identifier disjointness stays true.

## Verification commands and invariants

Root runs native commands serially from src/csharp so global.json remains effective. Existing
`.tmp-tests/run_rich_generation_tests.py LABEL FILTER` can retain focused native runs, with
FILTER containing `ConnectionSettingsTests|ConnectionTransportTests|ConfigTests|ProviderSettingsTests|
CompatPresetDataTests|ConfiguredTransportOwnershipTests|GovernedTransportTests` using fully
qualified-name filters. A narrow library/solution compile may precede actual runtime controls.
Generator author may run only its named focused pytest controls with `-p no:cacheprovider`
and a fresh ignored basetemp; root owns heavy suites and full gates. No tests for plan-only edits.

Preserve these immutable bytes (recompute, never hand-edit a pin):

- Python inventory: `47c2f58b2f4a8f9d0586c6f8ff92a171de485ef7cc73dfe496a679180e132b16`.
- Released core manifest: `16122cca198d9e688d3c4b5724ac11f0324a4390d8e8589e443fe04a48e81391`.
- User uv.lock: `1e51c63f999c63b929798da5bc602adafa0d9e7f0ee082851c06db01323011ec`.
- User v/cache/nodeids: `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945`.
- Before regeneration, table v2: `3ed02395c0c7040f6e43044ad32166f28e44ac8224361a76b73420ce5bd9f9a5`.
  New table digest is computed after the reviewed generator runs; this leaf does not invent it.

## Current resume

All NCON boxes are complete. Resume **SDK.8a's explicit redirect contract**, then researched
provider registration. The qualified executable source remains
`8758b0eedf9f69077274a666da3919e9f83380a0`, tree
`1f20c9fa0f95142a28f7713b6de9ebfb12a424b5`. This later plan-only reconciliation record
preserves that identity; it is not a replacement executable qualification.

Held-source full-third passed all 25 workspace steps: 4,492 Python passes and 10 documented
Windows/platform skips, 1,051 native unit and 93 conformance passes with zero native skips,
five paired profiles, strict docs, package/examples and explicit Frozen DEVELOPMENT
102/0/0/0. All 1,260 protected inputs and initial/final Git identity stayed unchanged.
Independent full-gate review is bounded clean. Evidence is in
`.tmp-tests/native-connection-full-third/` and `-coherence/`.

| Full evidence | SHA-256 |
| --- | --- |
| Workspace log | `9442a32a712fccd1dd8f871e72c7cfb38a101434d29a2cca9b2298313f38ac04` |
| Primary Python JUnit | `e5a605194e6ef777ed8a8787f26765d260d3816feaa3223ee04690fb7fbf2db7` |
| Frozen DEVELOPMENT | `ca2a6aa1d8304d7e66bfb6098dbea012521ca03b3e61bd123633936c831e9b3a` |

The accepted clean checkout is
`C:/Users/antho/.traycer/worktrees/anthturner__anyinfer/feature-native-connection-clean-8758b0e`.
Its accepted run is `.tmp-tests/local-native-connection-8758b0ee-20261023T134450Z/`:
all 12 registry-derived C# steps, 1,051 unit and 93 conformance passes with zero skips,
173 focused cases (10 settings, 20 transport), five source-clean paired reports,
package/examples and Frozen 102/0/0/0. All 1,255 tracked inputs and initial/final
commit/tree/clean state match. Independent qualification review is bounded clean.

| Clean evidence | SHA-256 |
| --- | --- |
| Qualification log | `bb64dff9c1a62a513943db0502229c713bd4f26cf5a57bc2412949d162b277f3` |
| Frozen DEVELOPMENT | `15a7755eafa70fe9e3fd17dd1c604df741e68aa92bc7b6bb055f7c82a758ef56` |
| Final facts | `b990c50bbed55c61138be7fac6f48f672991d43aed2d98a7e71db0fef1fc85f3` |
| Identical before/after tracked maps | `7b714bd24081d59b2dc6d4fdcd7a06b545c67a4f7667027231d636d0599b4ec3` |

External bindings in `.tmp-tests/native-connection-clean-bound/` confirm the ignored focused
helper `a0fa5952dda9b8b52b134b78dc01b014a649c4191220dc1b46e81b78bfc5f195` and clean operator
`cc05b50a119fc5eeb582db1fd2d61b57e85d0aa02d31acfcd501bd17de772bd9` stayed unchanged.
The clean factory raw hash `707c144ff2811094edda5a317fc847f62f4492f466dbc85c2d43031f953bd725`
normalizes only CRLF to the reviewed LF hash
`ac29cde31bf0f8fb5cabc3eab3d42b5a97122321837b030b9416b09fdbec6bb8`.
The exact v3 table is `f0ae5f9ac7a0ee9420d882a503590d6bf9de470c6185cefbcc8f8c5c29c2f845`.

Retain the failed/incomplete attempts. Full-first lacked explicit Python/Frozen evidence;
full-second failed because capture environment reached a nested pytester process, corrected
only in the ignored capture helper. First clean attempt 133934Z failed one existing external-
close five-second wait. Its isolated case and the complete clean retry passed without code
or timeout changes. The earlier timeout's cause remains unresolved; no claim that every
attempt passed, or that host load or a deadlock was proved, follows from acceptance.

User-pinned `uv.lock` and `v/cache/nodeids` remain excluded and unchanged. Default registry
remains four descriptors/seven bindings. Redirects, researched registration, SDK.6c/8b-c/9-12
and all 235 root API rows remain open. No full-SDK, cross-OS support or release/publication
claim follows from this bounded connection slice.
