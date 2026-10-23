# Shared provider HTTP redirect hardening

Resume from the first unchecked box. This is the redirect prerequisite of SDK.8a in
`ANYINFER_CSHARP_SDK.md`, before researched provider registration. Root owns this plan,
generated assets, Git, shared compilation and every native/full gate. Workers own only the
files in their brief; they must reread shared files before minimal changes and must not
revert another worker's work. Root records checklist completion after inspecting evidence.

## Reference, authorization and scope

Qualified connection executable: `8758b0eedf9f69077274a666da3919e9f83380a0`, tree
`1f20c9fa0f95142a28f7713b6de9ebfb12a424b5`. Connection plan-only reconciliation:
`1b9857c19cd446321594f9dcc3f1239dee809ccc`, tree
`4212ea32ef5b43dbf73fe685ed1942e7d7d57a02`. The latter is not a new executable qualification.
Redirect source checkpoint: `4faf9ecb22206715e01f8bd2faff8a39defe5565`, tree
`44f6f2499762f11280badf16039034e35604fc4d`; clean qualification is complete.
RDIR.8 reconciliation is complete. Its separate plan-only commit does not qualify a new executable.

On 2026-10-23 the user selected **Harden both SDKs**: remove provider credentials and
configured custom headers on origin-changing redirects, retaining ordinary HTTP headers
and the narrow same-host HTTP:80 to HTTPS:443 exception. This deliberately changes Python
as well as adding native redirect following. It does not waive redirects as a platform
difference. The earlier native TLS exception remains exactly as qualified in the connection
leaf. Keep net8.0, existing packages and `httpx2>=2.0`; add no public redirect/config knob.

This work covers provider traffic through Python `providers/http.py::build_client` and the
four native builtins (OpenAI-compatible, TEI, Voyage, Jina). The local-services caller of the
Python helper receives its harmless baseline policy too. Separate Google token exchange,
foreign Copilot SDK HTTP, model/download/capability/pricing/MCP clients and Hugging Face's
manual download contract are outside this seam; do not claim they are covered or alter them.
There is no provider-ID branch or new provider registration. Default registry stays four
descriptors/seven bindings, with 122 operation memberships pending.

HTTP Location handling is transport behavior, not the normalized core routing outcome named
"redirected". Do not revise released core v0, its 102 observations, frozen manifests or the
five existing paired profiles to manufacture evidence for this feature. A shared test-input
matrix and independent public wire controls suffice; no new published conformance profile
or provider certification is introduced. The provider propagation procedure is not a reason
to rewrite 86 upstream contract snapshots for this library-owned policy.

## Closed observable contract

### Following, methods, URL resolution and failures

- Follow 301, 302, 303, 307 and 308 only when Location is present. Missing Location is terminal:
  return the response to ordinary adapter parsing/status classification. Do not classify it
  inside the redirect sender. An empty present Location follows the selected HTTP client's
  URL-resolution behavior; include it in the shared controls.
- Allow 20 followed redirects: at most 21 sends including the initial request. If response 21
  is another eligible redirect, dispose it and fail before constructing or sending request 22.
- For the builtins' GET/POST methods: 301 rewrites POST to GET; 302/303 rewrite POST to GET;
  307/308 preserve method and body. GET stays GET. A rewrite drops body and stale body framing.
  Native may implement HEAD consistently with the reference, but this slice makes no generic
  QUERY-method claim: httpx2 2.0 and 2.15 differ there and no current builtin sends QUERY.
- Resolve relative, scheme-relative, query-only and fragment-bearing targets against the
  current request URL, preserving the reference's inherited-fragment and missing-host repair
  behavior where applicable. Use public parsers and test actual resolution, including explicit
  default ports. Send only HTTP(S). Refuse redirect targets containing userinfo instead of
  deriving new credentials from a response Location; the initial request's existing admission
  rules remain unchanged. Invalid/unusable targets fail before the next dispatch.
- Redirect limit/invalid-target/unsupported-replay failures are bounded transport failures in
  the current operation phase, preserving existing retryability and caller error mapping.
  They must not contain Location, cookie/header values, userinfo or request body. Native
  generated failures use constant-message HttpRequestException with no raw parser inner;
  existing adapter HttpRequestException mapping remains authoritative. Actual inner-handler
  failures and foreign cancellation exceptions retain existing identity/mapping rules.
- Python retains HTTPX's redirect engine. In `map_transport_error`, safely render redirect/
  protocol failures (TooManyRedirects, RemoteProtocolError, LocalProtocolError and
  UnsupportedProtocol) using constant bounded text rather than interpolating raw parser
  messages. Keep the actual exception as the existing explicit cause; raw cause/NativeInner
  inspection is not the library's safe string/snapshot/event surface.
- Explicitly align native OpenAI generation's existing non-2xx predicate to `>=400`, matching
  Python. This is a named parity correction: a terminal 3xx with a valid generation body can
  parse, and malformed content fails through the usual payload path. Discovery/health and
  retrieval paths retain their existing >=400/<400 behavior.

### Header provenance and concurrency

Origin is normalized scheme, host and effective port (HTTP 80, HTTPS 443). Compare these
components using public APIs; Python must not use URL.origin, absent in httpx2 2.0. The only
origin-changing exemption is same normalized host, HTTP effective 80 to HTTPS effective 443.
Downgrades, nondefault-port upgrades and other host/port changes strip protected values.

The protected-name set is case-insensitive: every configured `ProviderConfig.headers` name
plus adapter-declared credential/signature names, always including Authorization. Pass names
separately from merged header values. Never infer credentials from values or select behavior
by provider ID. Once any unsafe crossing occurs, stripping stays true for that request chain,
including A-to-B-to-A. Do not restore credentials or re-sign/re-authenticate a redirected hop.
Concurrent logical operations have independent chain state.

Ordinary SDK HTTP/protocol/version defaults survive only when their name was not configured.
A configured override does not turn into a trusted default after crossing: omit the whole
name rather than silently restoring the SDK fallback. The exceptions are derived wire state:

- Preserve initial configured Host/framing behavior. Same-origin hops may retain configured
  Host, as Python does. Every origin change (including the exempt upgrade) regenerates Host
  from the current destination; never forward the old configured value to that new origin.
  Native factories must retain enough transition/provenance information to make this choice.
- On unsafe-origin preserved-body redirects with configured Content-Length or Transfer-Encoding, discard
  both old framing fields and derive correct framing from the already-available JSON bytes.
  No body read, generic buffering or new payload-size cap is allowed. After a GET rewrite,
  omit the body and stale framing. Ordinary platform-derived empty-body framing need not be
  byte-identical; controls must prove no old custom value and a valid empty body.
  A compatible, method-preserving hop need not normalize the initial configured framing;
  the mandatory repairs are body rewrites and stripping across an unsafe origin change.
- Python saves length only when public `Request.content` is already buffered. Never read or
  aread an unknown stream to obtain it. When an unsafe, method-preserving hop requires framing
  repair, unknown-stream plus protected custom framing fails closed before the followed send
  with constant LocalProtocolError. Compatible-hop literal framing remains preserved. Do not widen header
  admission, normalize initial user input, or reject ordinary supported buffered JSON.
- Literal Cookie is handled separately: preserve an explicit initial value, remove it from
  every followed request (even same-origin), and recalculate only destination-scoped jar
  cookies. Cookie policy is independent of the sticky credential/custom-header bit.

### Cookie state and injected transports

Python keeps its HTTPX client jar. Native adds one private `RedirectCookieJar` per adapter's
HTTP-client lifetime, above either owned or injected handlers. It is neither global nor per
redirect chain and is not shared just because two clients borrow the same handler.

Use `CookieContainer(int.MaxValue, int.MaxValue, int.MaxValue)` to avoid introducing its default
300-total/20-domain/4096-byte limits. This does not claim identical cookie-parser acceptance or
ordering for every possible cookie; qualify domain/path/secure/expiry/replacement behavior
with focused controls. Include more than 20 same-domain cookies, more than 300 total cookies
and a cookie longer than 4096 bytes so default eviction is not accidentally reintroduced.

Minimal internal seam: `Apply(Uri destination, HttpRequestMessage request, bool isRedirect)`
and `Observe(Uri responseUri, HttpResponseHeaders headers)`. Initial Apply preserves an
explicit Cookie, otherwise supplies scoped jar state; redirected Apply always removes and
recalculates it. Observe every intermediate AND final response before returning/disposal.
For each separate Set-Cookie value, call SetCookies under a private gate and ignore only
CookieException for that field without rendering its value/message. Other failures propagate.
Lock individual jar operations, never a send/body/whole redirect chain; concurrent updates
are safe but naturally order-dependent, like a shared Python client.

Set `UseCookies=false` only on SDK-created SocketsHttpHandler; keep AllowAutoRedirect=false.
Never mutate/reflection-inspect/reject an injected handler based on its concrete type. The
SDK applies policy and per-hop governance to each visible request. An injected handler may
add its own cookies/credentials or internally follow redirects; those hidden operations are
caller-owned and cannot be covered by the SDK's per-visible-hop guarantees. Document that
handlers must return each hop to obtain those guarantees. This preserves connection takeover
without pretending that an opaque transport can be controlled internally.

## Implementation boundaries

### Python shared hook and auth declarations

Append the backward-compatible optional keyword
`origin_bound_header_names: Iterable[str] = ()` to `providers/http.py::build_client`.
It is a low-level provider-plumbing argument, not a new setting. Always union Authorization;
each adapter passes the union of its config.headers keys and declared credential names.
Install a public async request event hook with namespaced Request.extensions state containing
origin, sticky flag, previous method and known buffered length. Preserve other extensions;
store no secret values. Avoid private HTTPX overrides and any shared mutable origin cursor.
Use public scheme/host/port on both minimum and current versions. Existing independent custom
auth flows that create unrelated requests are not promised extension propagation; all current
AnyInfer auth paths must be covered. Do not expand a future auth API by assumption.

Production ownership for Python worker (no tests):

| Files under src/python/anyinfer/ | Required change |
| --- | --- |
| providers/http.py | Hook/state/origin/framing/error-rendering helper; optional names keyword and docstring |
| providers/openai_compat.py | Protected `_origin_bound_header_names(config)` class seam; union config names before build_client |
| providers/presets.py | Override class seam using preset auth_header (Bearer or x-api-key), not provider ID |
| providers/azure_foundry.py | Declare api-key plus Authorization through class seam; Entra remains lazy |
| providers/gemini.py, providers/vertex.py | Analogous class seam; Gemini x-goog-api-key, Vertex Authorization; preserve reconstructed config headers |
| providers/openai.py, anthropic.py | Declare Authorization; Anthropic additionally x-api-key |
| providers/bedrock.py | Declare Authorization, x-amz-date, x-amz-content-sha256, x-amz-security-token, including dynamic signing |
| providers/cohere.py, jina.py, m365_copilot.py, ollama.py, tei.py, voyage.py | Pass config names; Authorization protected even when supplied later |
| testing/scaffold.py | Generated example must call the actual keyword-only helper and declare configured/credential names |

`local/services.py` needs no policy opt-out and currently has only ordinary content-type.
Do not change cloud_auth token exchange or foreign SDK clients under this lease. No registry,
config schema, credential resolver or dependency/lock changes.

### Native shared sender and request ownership

Add internal `Providers/ProviderHttpRedirects.cs` and `Providers/RedirectCookieJar.cs`.
`ProviderHttpRedirects` is instantiated once per existing adapter/transport HttpClient and
borrows that HttpClient; the existing adapter/transport remains its disposer. Its SendAsync
receives initial URI/method, a fresh-request factory, operation phase and the existing effective
linked cancellation token. It returns a disposable `RedirectExchange` retaining final request
and response. A small immutable `RedirectRequestContext` conveys current URI/method,
IncludeBody, IncludeOriginBoundHeaders and IsRedirect to the factory. Initial IncludeBody is
true (the factory preserves the operation's existing request shape); a POST-to-GET rewrite
makes it false for all later hops. Initial IsRedirect is false.

Factories capture the operation's existing serialized JSON byte array (or existing empty-body
shape), config-name set and separately retained SDK defaults/credentials. Construct a new
HttpRequestMessage/content for every send, including the first; no HttpRequestMessage resend,
arbitrary HttpContent clone, second serialization, generic stream read or new request-size cap.
Omit configured/credential values when IncludeOriginBoundHeaders is false, including SDK
fallbacks whose name appeared in config. Never copy prior Host/framing/Cookie blindly.

The sender is OUTSIDE HttpClient/governed handler: every hop calls the same HttpClient with
ResponseHeadersRead and the same effective token. It observes that response's cookies, drains
intermediate body with a fixed-size buffer and the token (no full-body allocation), disposes
response then request before the next send, and releases each content-bound governor lease.
It disposes terminal limit/error responses too. Terminal success/missing-Location ownership
passes only through RedirectExchange; existing parsers/streams keep final response lifetime.
On any failure, preserve the primary exception while attempting all owned cleanup. Do not
turn a foreign OCE/I/O failure into caller cancellation merely because a token later cancels.
Existing pool/adapter cancellation identity and phase mapping remain authoritative.

Python retains the public HTTPX redirect engine, including its cleanup-fault boundary.
When an intermediate body read and its cleanup both fail, HTTPX can surface the cleanup
exception with the original read exception retained in its context chain. A public response
hook cannot interpose below its already-installed bound stream, and replacing the default
transport would change environment-proxy handling. This slice therefore preserves that
dependency behavior and must record a causal dual-fault control and the limitation; it must
not claim Python preserves the primary exception object in this case. The native sender's
SDK-owned cleanup continues to preserve the primary. No private HTTPX override, dependency
change or injected-only workaround is introduced to manufacture parity.

Native production worker owns only the two new files, ConnectionHandlerFactory.cs,
OpenAIChatAdapter.cs, and Tei/Voyage/Jina Adapter.cs + HttpTransport.cs. Change owned cookie
flag, all four request factories and their send/final-cleanup seams together. Keep existing
legacy internal constructors usable by frozen tests. No core router, credentials, registry,
generated table, tests, public API, package, shared spec or plan mutation under this lease.

## Execution checklist and leases

- [x] **RDIR.0 — contract closure and cold critique.** Root writes this leaf and updates the
  redirect ticket/parent resume point. Fresh reviewers read the contract plus source seams and
  all evidence artifacts, pressure-test origin/provenance/framing/cookies/error/lifetime/minimum
  version scope, and record concrete P1/P2 findings. Resolve them before production leases.
  Gate: bounded independent contract reviews clean; exact first implementation box recorded.
  > NOTE: Independent Python and native contract critiques are bounded clean at plan SHA256
  > f2319b13556bfc2b840a9fb895510be32e47c1d6ffed21bab6309a2872e623a7. Both physically
  > retained review artifacts bind that whole plan and source seams; neither claims runtime
  > evidence. RDIR.1/RDIR.2 production and RDIR.3/RDIR.4 test-input work may proceed under
  > disjoint leases. Root retains every plan edit and shared native/full gate.
- [x] **RDIR.1 — Python shared policy.** Python worker owns only the production paths above.
  Independently owned tests must be in place before claiming the phase complete. Hold source
  for cold review; run only Ruff/format/py_compile and the named focused Python tests after
  test owner hands off. No full/native gate. Gate: all current builtin declarations, injected
  transport behavior, safe failures and focused current-runtime policy controls pass.
  > NOTE: The sixteen leased Python production paths are saved and held, with worker Ruff/
  > format/py_compile checks reported. Fresh implementation review is running; independent
  > current/minimum runtime controls have not run. RDIR.1 remains unchecked.
  > NOTE: Fresh Python review found derived Cookie removal after HTTPX jar regeneration,
  > plus an overbroad injected-transport docstring. Narrow http.py corrections are assigned;
  > retain configured Cookie provenance while preserving the destination-derived jar header.
  > NOTE: Exact rereview closes both findings at http.py SHA256
  > 3a048684e464a5dd2d5bca579a9ad6042d41ad17df18b71a697cde501b10808c; the other fifteen
  > source hashes are unchanged. Source review is clean, but RDIR.1's control gate is pending.
  > NOTE: Source inspection of current and minimum HTTPX establishes the dual read/cleanup
  > failure boundary above. Root retains it explicitly rather than replacing environment
  > proxy behavior or using private engine hooks. Independent controls must prove the actual
  > surfaced cleanup failure, retained original read context and no followed dispatch; this
  > is limitation evidence, not a primary-preservation pass.
  > NOTE: Current Python third now passes48/failed0/skipped0 on Python3.13.15/httpx2 2.15.1,
  > with all510 scoped inputs and HEAD/tree unchanged. JUnit SHA256
  > 43ce168d4f41c17ae7d604164cb1805d0486bc7f00eac61534a8bb13fe591e6e binds test
  > a2b3e2fd... and the reviewed production bodies. This completes the current-runtime gate;
  > actual minimum2.0/full/clean gates remain unchecked and both earlier failures remain retained.
  > NOTE: Full-gate source correction is cold-reviewed at http.py73ad4b15...; only precise
  > async hook-factory typing and the existing helper's __all__ declaration changed. Strict
  > types210files and docstring/link/example checks now pass (462 exports/171 markdown files/
  >50 examples). Current fourth revalidation passes80/0/0 including the original48 redirect/
  > scaffold controls plus32 metadata/docstring controls; all512 guarded inputs and HEAD/tree
  > unchanged, JUnit1d172446.... RDIR.1 is complete again; minimum revalidation remains pending.
- [x] **RDIR.2 — native sender and integration.** Native worker owns only the stated production
  files, preserving ownership/cancellation. Root owns compile/runtime commands. Gate: fresh
  source/lifetime review clean and root library/test compilation succeeds with real APIs.
  > NOTE: First held native library compile failed CS1501 at the proposed
  > LoadIntoBufferAsync(4096, token), unsupported by net8. Source handoff is not accepted.
  > Root requested a fixed-buffer read-to-EOF drain (no response-size cap), safe target
  > resolution, actual-rewrite-only body dropping and complete primary-preserving ownership
  > cleanup before the next compile/cold review. No redirect runtime has been executed.
  > NOTE: Corrected helper SHA256 0acbebd30d50321a15e59590a2e69ac96da1958d66e5b187dfae27e1a36d9511
  > now compiles in the root net8 library build with zero warnings/errors. Fresh native
  > source/lifetime review is running; this is compile evidence only, not phase acceptance.
  > NOTE: Fresh native source review found stale reserved-header copying/bodyless GET handling,
  > configured-name fallback restoration, primary-error replacement during OpenAI cleanup and
  > missing-vs-malformed raw Location conflation. A coherent native correction batch is leased.
  > Initial configured-header behavior must remain; the reserved-field clarification above
  > matches Python's actual same-origin versus origin-changing handling rather than dropping
  > initial user headers globally. RDIR.2 remains unchecked.
  > NOTE: The first correction handoff still leaves the explicit OpenAI primary-cleanup P1
  > unresolved, mishandles multiple raw Location values as absence and does not yet carry
  > the Host transition distinction. Root specified a wrapper/core async-iterator resource
  > owner and sole caller-owned intermediate cleanup; completion remains assigned before
  > another compile/cold rereview. Do not treat a partial handoff as source acceptance.
  > NOTE: Helper/factory corrections are held at helper SHA256
  > 8d848543e94be5edfa12058284468559aaf473b1506fe3b5ea04a85e569f17f2.
  > The remaining OpenAI cleanup refactor now has a separate exclusive file owner; the native
  > helper/factory worker is held and must not edit OpenAIChatAdapter.cs concurrently. Root
  > compilation and coherent source rereview wait for that mandatory cleanup handoff.
  > NOTE: The focused cleanup worker completed the wrapper/core resource-owner correction.
  > Root compile fixed one missing HttpResponseHeaders import and an explicit lazy null guard;
  > the native library now compiles. Test-project compilation exposed five errors from two
  > mechanical test-source issues (dictionary fallback and ConcurrentQueue indexing), now
  > assigned narrowly. Coherent source/test reviews and runtime gates remain outstanding.
  > NOTE: Both mechanical test fixes are held; root now compiles the whole test project
  > (including library and request-policy dependency) with zero warnings/errors. Current
  > helper SHA256 3b48cfbda2fddb65c07733ea9e97416b85e2215f360c3a0e05eb2739f1c88063 and
  > OpenAI SHA256 bee856fe458791680219861541e9653f69f870ca207fdb33d3cc2e38fd2f0840 are
  > under fresh coherent native source review. No runtime result follows from compilation.
  > NOTE: Coherent rereview closes the previous four source findings, but retains strict
  > Host-transition handling for the exempt upgrade, missing-host/inherited-fragment URI
  > repairs and OpenAI intermediate-drain IOException mapping. These final narrow helper/send
  > corrections are assigned; the completed OpenAI cleanup owner must not be rewritten.
  > NOTE: Latest URI correction failed library compile (CS1729, nonexistent six-argument
  > UriBuilder constructor). Root also found strict Host comparison after current-URI
  > reassignment and directly checked that .NET 8.0.32 rejects hostless scheme references
  > before the proposed repair branch. A focused worker now exclusively owns helper repair;
  > the earlier native worker is held. These diagnostics are not redirect runtime proof.
  > NOTE: Focused repair plus root nullable-flow corrections now compile in the complete
  > native test project with zero warnings/errors. Root also fixed four mechanical test API
  > errors (Task.AsTask and dictionary Contains). A source rereview found query-/fragment-only
  > scheme references rejected before repair; root routed those through the same hostless
  > repair. Current helper SHA256 ffab7d6d21bdea449173bba7db7dafc28158427484add086b8f2d8eee4c7f3f0
  > and adapter-control SHA256 23001a2adbdf5620356573bba3a25aee12a1f7c999177536bf157b63ed68102c
  > compile together. Exact source/control rereview and runtime gates remain pending.
  > NOTE: Exact native source rereview is now bounded clean at helper ffab7d6d... and
  > OpenAI 18f8e2f3..., with the earlier integration/provenance/lifetime findings closed.
  > The whole native test project compiled with zero warnings/errors at these source bodies.
  > This completes the RDIR.2 source/compile gate only. RDIR.3 control corrections include
  > malformed positive JSON fixture literals discovered after compilation; no runtime gate,
  > redirect qualification or overall SDK completion follows.
  > NOTE: The first focused runtime run passed45/failed21/skipped0 with all317 guarded native
  > inputs and Git identity unchanged. It exposed an overbroad new send-I/O mapping plus a
  > pre-existing retrieval default/configured-header duplication. Source correction is assigned
  > and this box is reopened until exact rereview/compilation of the new bodies. Failed evidence
  > is retained separately from earlier source/compile acceptance.
  > NOTE: The runtime-informed production correction is bounded-clean in exact source review
  > at sender13de4ad4..., OpenAIbee856fe... and retrieval defaults42fb0ca6/530bfd6e/0eb37b6a.
  > The full test project compiles with zero warnings/errors. This source/compile gate is
  > closed again; a second focused runtime run is active and the control gate remains open.
  > NOTE: Fourth native focused run passes66/failed0/skipped0 with317 scoped inputs,
  > HEAD/tree/status unchanged; TRX6c383c12... joins14 sender,5 cookie,26 adapter and21 governed
  > cases. A subsequent public HTTPX reference probe exposed a hostless-scheme edge absent
  > from those controls: repair inherits only host, not the old port, and preserves path
  > slashes after the two empty-authority delimiters. Current and minimum source agree.
  > RDIR.2 is reopened for that narrow source correction; independent controls are leased.
  > The66-pass result remains valid for its archived input bodies, not the pending correction.
  > NOTE: Exact raw-control critique exposed doubled query/fragment loss under UriBuilder's
  > separator normalization. Root's actual .NET8 setter probe confirmed it; known delimiter
  > prefixes and semantic-empty bare-fragment inheritance now preserve the HTTPX reference.
  > Sender8eadb22a... has bounded-clean source review and the complete test project compiles
  > with zero warnings/errors. RDIR.2's source/compile gate is complete again. Independent
  >11-case raw Location controls are held at0142adf2...; focused native rerun is pending.
- [x] **RDIR.3 — independent causal controls.** Test owner owns new
  `tests/test_provider_redirects.py`, `src/csharp/AnyInfer.Tests/RedirectTransportTests.cs`,
  `RedirectCookieJarTests.cs`, `RedirectAdapterTests.cs` and `LoopbackRedirectFixture.cs`;
  minimal existing GovernedTransportTests.cs/scaffold-test changes require a named lease.
  Reuse existing fake adapters/recorders and loopback certificate helpers where safe without
  editing the connection fixture concurrently. No source changes to make tests pass.
  Gate: exact coverage below, native root focused gate and independent review clean.
  > NOTE: The minimal scaffold regression lease is explicitly `tests/test_provider_template.py`;
  > exercise the actual generated adapter with injected transport where practical. The Python
  > production worker owns only the template producer, not this test file.
  > NOTE: Initial test handoff is incomplete: descriptor/factory presence is not actual
  > all-adapter wire evidence, and reading shared JSON only for schema/count does not use its
  > stimuli. Required public loopback, shared-input execution, concurrency and cancellation/
  > cleanup witnesses are assigned for completion before cold review or execution.
  > NOTE: Expanded control source now drives all shared stimuli and public all-adapter paths,
  > with actual body captures and concurrency/failure controls. The final two explicit source
  > gaps (public borrowed-handler opacity and unfinished-stream early-close/cancellation
  > cleanup) remain assigned before cold test review. No test runtime has run.
  > NOTE: Final held control source now includes both remaining witnesses. Cold independent
  > test/fixture review is running before execution; all current/minimum/native runtime gates
  > remain unexecuted. Root compilation waits for the OpenAI cleanup source handoff.
  > NOTE: Cold controls review found four P1 areas despite the source inventory: shared
  > runners suppress failures/discard wire data, public all-four reserved-header/fallback
  > checks are incomplete, cookies lack public operation/scoping coverage, and Python uses
  > a generic client rather than the named auth paths and lacks lifecycle controls. Correct
  > these before execution. Ownership is now split: a fresh focused worker exclusively owns
  > tests/test_provider_redirects.py; the existing test worker owns native controls/fixture.
  > The shared input JSON and template test remain held. No runtime pass is claimed.
  > NOTE: Python controls have a useful partial correction checkpoint (literal shared-case
  > assertions and selected builtin/concurrency coverage), but named late Azure/Vertex/M365,
  > Bedrock signing and cleanup precedence remain assigned. Native controls likewise remain
  > assigned until their broader public wire/cookie P1 coverage is complete. Do not tick
  > either phase from a partial source handoff.
  > NOTE: The next cold rereview closes the all-eight stimulus, public POST-to-GET framing,
  > readiness-concurrency, opaque-handler and SSE control gaps at source level. Two native
  > P1s remain assigned: all-four initial configured/credential values paired with destination
  > omission, and public Domain/path-negative/Secure cookie scope across redirect and next
  > operation. The native test project compiles; this is not runtime acceptance.
  > NOTE: Final source cross-check found seventeen expected-positive C# raw JSON literals
  > with doubled quotes. Their mechanical correction is assigned together with two precise
  > assertion deltas: retrieval destination Content-Length equals captured byte count, and
  > an explicit matching Domain cookie is accepted on owned HTTP redirect plus next operation.
  > Do not execute or accept the compiled-but-malformed fixture checkpoint.
  > NOTE: After raw literal repair, root decoded23 positive JSON strings and compiled current
  > controls; the first actual run still failed21/66. Assigned test corrections preserve the
  > contract while fixing missing vector indexes, wrong header collections, overstrict zero-body
  > framing, explicit scheme expectations and stimulus/body wiring. Readiness waits in Python
  > are now bounded at test SHA9d583637...; its current runtime gate remains unperformed.
  > NOTE: Root strengthened Python concurrency to one unsafe chain followed before a safe
  > chain; exact source review is clean at05fb2683.... The first current-runtime run then
  > passed42/failed6/skipped0 with510inputs andHEAD/tree unchanged. Six test/fixture expectation
  > corrections are assigned; no production success is inferred. Native control correction
  > D0EB8AFB.../0E0FB2A1... is held for cold rereview and its second focused run is active.
  > NOTE: Native second and third runs each passed65/failed1 with317stableinputs. The remaining
  > shared missing-Location case needed literal302 and one request, leaving its extra scripted
  > response unused. Those assertions and deterministic unsafe-before-safe concurrency are
  > now held at transport4583a485.../adapterba56bc6e...; the fourth run is active. Current Python
  > second passed47/failed1 with510stableinputs. Its unread-stream fixture now uses an unsafe
  > destination to require framing repair, at testa2b3e2fd...; third current run is pending.
  > NOTE: Fifth native focused run passes77/failed0/skipped0, including all11 raw Location
  > cases, at sender8eadb22a.../transport0142adf2.... All317 inputs and HEAD/tree/scoped status
  > remain unchanged. TRX SHA256 c612a80762cf26be334bc58e32bdd34c8a5279456f35f9ffa19572126e06740c joins
  >25 sender,5 cookie,26 adapter and21 governed cases. Exact source/control reviews are clean.
  > Alongside current Python48/0/0, this completes RDIR.3's focused gate. Earlier failed
  > attempts and the Python dual-fault/native external-close limitations remain retained.
  > NOTE: Expanded sixth native batch passes133/fails1/skips0 with318 inputs and Git identity
  > unchanged. Both terminal307 controls pass. The sole failure is the independent inventory
  > pin still naming47c2...; root updates only that expected literal to verified46dd..., keeping
  > the independent file-byte SHA and generated-table join assertions. CompatPresetDataTests
  > nowcf3524e7..., fresh critique/seventh expanded gate pending. No validator is removed.
  > NOTE: Seventh expanded native gate now passes134/0/0, including25 sender,5 cookie,
  >26 adapter,21 governed,10 OpenAI and47 preset-data cases. All318 inputs and HEAD/tree/
  >scoped status remain equal; TRX759c0dda.... The singleliteral expected-pin rereview remains
  >pending before closing this box; actual minimum/full still require refreshed metadata pins.
  > NOTE: Exact expected-pin critique is now bounded clean atcf3524e7.... With the134/0/0
  > gate and unchanged318 input/identity guards, RDIR.3 is complete again. The source checkpoint
  > candidate includes44 paths (prior43 plus the independently pinned preset-data control).
- [x] **RDIR.4 — shared stimuli and declared-minimum proof.** Test owner writes
  `tests/fixtures/provider_redirects.json`, consumed independently by Python and native test
  readers (explicit test csproj copy/link under this lease). It contains inputs/IDs only:
  request method/path/body/header classes and response status/Location/Set-Cookie sequence;
  no expected outcomes, Python labels or captured result fields. Each language asserts public
  behavior independently; no branching on case ID to fabricate an observation. Prepare an
  ignored root-run recipe for an isolated Python environment with exactly httpx2 2.0.0 and
  compatible dependencies, never altering active venv/pyproject/user lock. Reuse verified wheel
  source identity below; installation/execution is separate from its completed static audit.
  Gate: same focused tests run on current and actual minimum runtime; retain exact environment,
  imports, commands, case inventory, JUnit and skips/errors. No new published profile claim.
  > NOTE: Ignored run_redirect_minimum.py/full.py/clean.py preparation is leased separately.
  > Existing accepted NCON operators/helpers stay unchanged. No isolated environment,
  > installation, network/native runner or full/clean redirect gate is authorized to a worker;
  > root invocation follows cold operator review and a coherent held source/control slice.
  > NOTE: Cold proof-preparation review found imported common/helper behavior unbound,
  > admission failures before durable final facts and ambient pip policy inheritance.
  > A correction batch is leased; no operator/environment installation has run.
  > NOTE: Exact proof preparation rereview is now bounded clean at common 0334bcd5...,
  > clean14771762..., full8878849f... and minimumcd1a705e.... Verified-buffer helper admission,
  > selected-checkout invalid facts, collision-safe attempts and pip isolation are closed in
  > preparation only. Current/minimum/full/clean operator execution remains unperformed.
  > NOTE: Root local pip CLI help rejected the minimum operator's index-url before the install
  > command. Root corrected command placement and retained verified-wheel admission with a
  > version-only resolver constraint (editable source cannot use global hash mode). The new
  > minimum operator SHA8eb27f81... needs exact rereview before any environment/install run.
  > NOTE: Exact rereview closes the minimum CLI/constraint correction at8eb27f81... with
  > unchanged common0334bcd5.... The recipe now records those current pins. No minimum venv,
  > dependency install or actual declared-floor runtime has run.
  > NOTE: Actual isolated minimum run redirect-minimum-first passes48/failed0/skipped0 using
  > httpx2 2.0.0 from the admitted local wheel, selected AnyInfer source and a system-site-free
  > Python3.13.15 venv. JUnitb6ebfda0... and environmentd1b140b5... retain imports/freeze/commands;
  > operator1268-input before/after maps match93647fb7.... Root's verified-buffer admission and
  >1269-input guard additionally include the wheel; HEAD/tree/status/path inventory remain equal.
  > Current-runtime48/0/0 is separate. No dependency-floor change, full or clean gate follows.
  > NOTE: Fresh minimum-second now passes48/0/0 on actual isolatedhttpx2 2.0.0/selectedsource,
  > with systemsitefalse/Python3.13.15 and fresh inventory46dd.../table2dd.../commonb316... pins.
  > JUnitb79eea2d... and environmentbcd849e3... retain actualimports/freeze/commands. Operator1268
  > maps match042a7f2d...; root1269-input guards (includingwheel) confirm unchanged hashes and
  > HEAD/tree/status/pathinventory. RDIR.4 closes again; first minimum proof remains archived.
- [x] **RDIR.5 — durable docs and runnable example boundaries.** Docs worker owns
  docs/reference/configuration.md (canonical provider redirect policy), docs/guides/csharp-sdk.md,
  docs/guides/python-to-csharp.md, docs/reference/csharp-sdk.md and contracts/NEW-PROVIDER.md
  (credential-name declaration procedure). Update all repeated unfinished-redirect statements
  to the achieved scope after source is held. Preserve TLS limits, prerelease/full-SDK and
  borrowed-handler qualifications; no plan links or ADR identifiers. Existing public examples
  and package consumer remain the API proof because this adds no root public API/config knob.
  Gate: source/doc critique, strict docs, existing examples/package consumption pass.
  > NOTE: The five-path durable-docs lease is active under a separate owner. Source-only
  > edits must preserve native TLS/support limits and document visible-hop handler behavior;
  > no documentation build, runtime qualification or readiness claim is delegated.
  > NOTE: Five-path docs handoff and cold source/doc review are bounded clean. Canonical
  > redirect policy links and credential-name declaration procedure are saved; strict docs,
  > existing examples/package and actual runtime qualification remain pending root gates.
  > NOTE: First full run failed5/25 steps with1272 inputs and Git identity unchanged. Python
  > has8 failures/10 documented skips (7 reject stale generated provider source hashes;1 public
  > helper export coverage), plus a missing hook-factory return annotation. Native has1107pass/
  >1fail/0skip from the obsolete terminal3xx status assertion; conformance93/0/0 and five pairs,
  > docs build/examples/package pass, but this is not a full gate pass and explicit Frozen was
  > not run. Corrections have disjoint source/test leases; validators stay intact.
  > NOTE: Root authorizes source-derived inventory refresh after the Python correction settles,
  > then official C# table regeneration solely for InventorySha256. This accommodates actual
  > Python source drift caused by the authorized shared policy, not native behavior or provider
  > breadth. Preserve all descriptor/binding/preset/factory facts, default4/7 and122 pending.
  > The inherited47c2f58b.../f0ae5f9a... pins remain archived NCON identities. Redirect operators
  > must bind the freshly generated metadata; never rewrite accepted NCON helpers or evidence.
  > Source/current/minimum gates reopen for the corrected coherent slice; release16122..., user
  > uv.lock and nodeids pins remain immutable. Root will record new metadata hashes after a
  > structured before/after comparison and cold review, then repeat narrow gates before full.
- [x] **RDIR.6 — full held-source gate.** Root freezes writers, snapshots all tracked/nonignored
  untracked inputs plus new files/operators/user pins, and runs workspace check once for the
  coherent slice with recording disabled, controlled pytest env, retained primary JUnit/totals/
  skip reasons and explicit Frozen DEVELOPMENT102. Reuse reviewed capture mechanisms from NCON,
  updating held slices for this leaf instead of assuming old lists include it. Gate: every
  registered step, five existing pairs, native suites, package/docs/examples and Frozen pass;
  input hashes and initial/final Git identity match; failures remain invalid evidence.
  > NOTE: Full-second passes all25 steps:4531 Python pass/10 documented platform skips,
  >1109 native unit and93 conformance passes/zero native skips, strict docs/package/examples,
  >five paired reports and explicit Frozen DEVELOPMENT102/0/0/0. All1272 maps and HEAD/tree/
  >status/path inventory match, mapSHAa9f4e6d4..., workspace3c10a9b2..., JUnitda4a570c...,
  >Frozen4fab258b.... Independent full evidence review is bounded clean; first full failure
  >remains retained. This closes docs/full held-source gates, not clean qualification.
  > NOTE: All44 explicit source candidates byte-match the passed full map; index is initially
  >empty and no other source changes are present. Source commit excludes both plans and user
  >inputs. Two future clean-runner preparation defects are separately assigned: root-only
  >protected lock/cache inputs must not be required inside the fresh checkout, and the focused
  >project path must resolve correctly from src/csharp. These ignored proof-only edits will
  >retain old helper buffers and receive fresh critique/admission; they do not change the44 SDK
  >source bytes or rewrite the completed full snapshot's helper identities.
- [x] **RDIR.7 — explicit source checkpoint and clean qualification.** Root commits only the
  reviewed explicit path set after full gate, creates fresh selected checkout, externally binds
  source commit/tree, reviewed helper hashes/import roots and all immutable pins, then runs the
  exact registered C# gate plus nonzero all-passing Redirect* controls and focused Python/current
  and minimum evidence as appropriate. Preserve native TLS and all existing Frozen/pair gates.
  Gate: clean source/status and protected inputs unchanged; independent evidence critique clean.
  Keep any failed prior attempt and unresolved lifecycle limitation; do not relabel retries.
  > NOTE: Root committed exactly44 source paths as4faf9ecb22206715e01f8bd2faff8a39defe5565,
  > tree44f6f2499762f11280badf16039034e35604fc4d. Both plans and user inputs are outside that
  > checkpoint. All44 worktree bytes stayed equal to the passed full map after commit. Fresh
  > selected checkout is
  > `C:/Users/antho/.traycer/worktrees/anthturner__anyinfer/feature-native-redirect-clean-4faf9ec`,
  > initially clean with exactcommit/tree. All44 source files match the
  > full-passed source after LF normalization; inventory46dd... andtable2dd... retain exactbytes.
  > Selected factoryrawf9f3e602... normalizes tob044991d... (reviewed full source). Root-bound
  > clean launch waits for fresh proof-helper critique; no clean result is claimed yet.
  > NOTE: Clean-first qualification completes at the exact source/tree above. The selected
  > `.tmp-tests/local-redirect-4faf9ecb-20261023T172122Z/` records all12 registered C# steps,
  >1109 unit/93 conformance passes with zero skips, five paired reports (42/29/32/43/10),
  > package/examples,56 focused Redirect cases (25/5/26) and Frozen DEVELOPMENT102/0/0/0.
  > Both1263 maps matchd850634f...; root's independent1263 map and commit/tree/status/path
  > guards also match, with no missing/changed inputs or guard errors. Root user-file and
  > ignored helper hashes are independently equal before/after. Loge69f9bb7...,TRX03ede38a...,
  > Frozen2178f010...,facts24ce7e59...,rootfactsfb417053.... Independent clean evidence
  > critique is bounded clean. This closes RDIR.7 without removing earlier failed attempts.
  > Clean used reviewed common32365d26.../operatord2ca06f1...; full/minimum retain their own
  > archived commonb316... identities. SDK source44 is unchanged; no extra full gate is implied.
- [x] **RDIR.8 — reconciliation.** Root updates this leaf, parent and ticket with exact executable
  identity, evidence counts/paths/limits and the next unchecked SDK.8a researched-registration
  box. Independent plan critique, then a separate explicit plan-only commit. Do not tick SDK.8a
  provider breadth, SDK.6c, SDK.8b-c/9-12 or any of the 235 root API rows from redirect success.
  Gate: parent/leaf/artifacts agree and user-facing claims match achieved source.
  > NOTE: Independent reconciliation critique is bounded clean at leafa01975fc... and
  > parentca79e797.... Root's final closure changes only checklist/resume state and records
  > that review; the separate reconciliation commit contains only this leaf and its parent.
  > The qualified executable stays4faf9ecb22206715e01f8bd2faff8a39defe5565/tree44f6f2499762f11280badf16039034e35604fc4d.
  > Resume SDK.8a researched provider registration from that source; no provider binding,
  > broader API/OS qualification or release action is completed by this plan-only commit.

## Required causal coverage (not implementation-mirroring tests)

Both languages: same-origin retention; arbitrary configured headers; Authorization and every
nonstandard builtin credential spelling; late M365/Vertex/Entra auth and Bedrock signing names;
case-insensitive configured Accept/Content-Type/version collisions; exact upgrade, nondefault
port, host change, downgrade, A-B-A sticky stripping; concurrent chains; initial configured Host
and framing versus derived destination fields; POST 301/302/303 and GET/POST 307/308 byte replay;
relative/scheme-relative/query/fragment/empty/missing/invalid/userinfo Location; exact 21 sends;
terminal valid/malformed 3xx bodies through public generation/discovery/health/retrieval; safe
errors with planted short/long values in Location/headers/cookies; never log credentials/body.

Cookies: initial explicit value, same-origin redirect recalculation, final-response cookies on
the next logical operation, domain/path/secure/expiry/replacement, multiple Set-Cookie fields
including malformed neighbor, initial request without explicit Cookie receiving jar state,
separate clients sharing a borrowed handler, concurrent calls and removal of default capacity
limits. Unknown Python stream/custom-framing failure must prove no second transport dispatch
and no body read. Nonsecret synthetic fixture values may be asserted literally in tests.

Governance/lifetime: one acquire/header observation/release per visible hop; intermediate body
and response disposed before next acquire; request objects are distinct; final streaming body
remains owned until close; cancellation at headers/drain/follow, foreign OCE preservation,
read/close/send faults with primary-error precedence, no stale leases and joined fixture tasks.
Use event/readiness coordination rather than sleeps and finite caller tokens/await bounds.
The Python engine's simultaneous read/cleanup exception boundary above remains separately
recorded; its control must establish both actual exception identities through the context
chain, rather than assert the stronger native SDK-owned cleanup guarantee.

Real owned-handler loopback must prove the SDK's raw handler does not auto-follow internally,
fresh body/Host/framing reach each destination, header omission is on the actual wire, cookies
persist correctly and governance observes each hop across all four native adapter paths.
Injected recorders alone cannot prove owned-handler behavior. Existing safe TLS fixtures may
be reused without permissive callbacks, external provider calls or OS-store mutations.

## Evidence anchors and protected state

Design/source artifacts under `csharp-sdk/sdk-eleven-connection`: redirect-parity,
redirect-python-reference, redirect-python-design, redirect-python-minimum-source,
redirect-native-boundary, redirect-native-design and redirect-control-matrix. They are design
or source evidence, never execution proof. Root's closed contract here supersedes historical
candidate seams in those notes.

The minimum static wheel audit fetched only PyPI metadata and the wheel on 2026-10-23:
`httpx2-2.0.0-py3-none-any.whl`, SHA256
`dfb5ae245f3985681296a000453f1e5fffee322eb531feabcdaf1557ad978b6a`.
Public per-hop hooks/extensions exist; URL.origin does not. The audit did not import/install/
execute it and must not be reported as a minimum runtime pass.

Inherited NCON baseline byte identities (archive, not a redirect-source refresh prohibition): inventory
`47c2f58b2f4a8f9d0586c6f8ff92a171de485ef7cc73dfe496a679180e132b16`;
released manifest `16122cca198d9e688d3c4b5724ac11f0324a4390d8e8589e443fe04a48e81391`;
v3 generated table `f0ae5f9ac7a0ee9420d882a503590d6bf9de470c6185cefbcc8f8c5c29c2f845`.

Current redirect source-derived pins after the bounded official refresh:
- inventory `46dd2eb1681b9e78c5daa97c446e28934cc128e6b7875e7509a229436810bfb4`;
- generated v3 table `2dd389e81fededac8287801b7a8beede47dfbb714182beb8ad33c41241b309e2`;
- full/minimum common helper `b316506ebe4e382253e6ecf0f59c2de63672df631162e232c6c35b8fca7df8bd`;
- later clean common helper `32365d263ce9aebc5e3e9f33b2a4fd18f10d01d6f047f559b77a350e0c83a25a`
  and clean operator `d2ca06f16859eccbdd7bc1df11618c9167e8ddd1950c952058298c717be1509c`.

Only14 existing provider source digest values changed; all inventory facts and source paths
are equal. The table changes only its inventory SHA comment/constant. Cold refresh critique
is clean. Release/user input pins and accepted NCON operators remain unchanged.

Never edit/stage/delete user inputs `uv.lock` (1e51c63f...11ec) or `v/cache/nodeids`
(4f53cda1...2b945), or delete the file `.pytest_cache/v`.

Resume: **SDK.8a researched provider registration** in the parent plan. All RDIR boxes are complete.
Current80/0/0, actual minimum48/0/0, expanded native134/0/0, full-second all25 and clean-first
all12+56 Redirect controls are independently reviewed at their retained source/helper identities.
The qualified redirect executable remains4faf9ecb22206715e01f8bd2faff8a39defe5565/tree44f6f2499762f11280badf16039034e35604fc4d.
The separate plan-only reconciliation follows bounded-clean independent critique; it is not
a new executable qualification. Default4/7,122 pending memberships, SDK.6c/8b-c/9–12 and all235 API rows remain
open. Python's dual-fault and injected-handler opacity limits remain stated above. The native
connection's first clean-run external-close5s timeout remains unexplained; isolated/full retry
passed without source or timeout changes. This leaf does not erase that limitation.
