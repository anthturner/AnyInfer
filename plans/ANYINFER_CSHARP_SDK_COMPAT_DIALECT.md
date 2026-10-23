# Prepare the native compatibility dialect boundary

Resume from the first unchecked box. This is a private codec prerequisite within the
authorized SDK.8a implementation. It adds no builtin preset registration, public API,
provider-support claim, or operation flag. Parent SDK.8a and SDK.6c remain unchecked.

## Starting point and settled boundary

- Qualified executable predecessor: `c3d0e9a0d26bd253d58620f4bca623c02fac3d85`,
  tree `1c7c12b0c0e0704a940e68adfaed9d1374f1f1e1`; auth plan-only acceptance:
  `8583dff26fd737e438d9f54aad75f974d0dac159`.
- Follow DESIGN.md's typed-core, translating-adapter, declarative-descriptor and async-core
  boundaries. Python `PresetCompatAdapter` in `src/python/anyinfer/providers/presets.py`
  is the behavior source for these three mechanics. No new upstream behavior is adopted.
- Current default C# descriptors and settings remain unchanged. The internal default dialect
  remains Bearer auth, model listing enabled and `max_tokens`. Existing FrozenV0 and modern
  generic requests must remain unchanged under those defaults.
- Do not load the maintenance inventory into the production library. Runtime-data generation,
  reasoning/setup/capability mapping, provider research, registration and embedding/batch
  implementation follow separately. Full Python operations remain separate from native
  implemented-protocol declarations; seven native bindings still leave 122 memberships open.
- This inert internal preparation requires no new immutable provider-change declaration:
  it changes neither registered-provider behavior nor shared normalized specifications.
  Preserve the accepted auth and rich declarations and all released/profile assets exactly.

## Exact internal contract

Add `src/csharp/AnyInfer/Providers/OpenAICompatDialectOptions.cs` with an internal sealed,
immutable record named `OpenAICompatDialectOptions`. Its constructor is
`(string authHeader = "bearer", bool modelsListing = true,
string outputTokensField = "max_tokens")`; expose read-only `AuthHeader`, `ModelsListing`
and `OutputTokensField`. Accept only ordinal `bearer` or `x-api-key` and ordinal
`max_tokens` or `max_completion_tokens`. Reject null or other spellings with argument
exceptions, without invoking HTTP. Do not add a mandatory dependency or public symbol.

Keep `OpenAIChatAdapter.Create(ProviderConfig, CancellationToken)` intact and forwarding
to default options. Add the internal overload
`Create(ProviderConfig config, OpenAICompatDialectOptions dialect,
CancellationToken cancellationToken)`. Append optional dialect options after all existing
arguments on the adapter's internal constructor; preserve every existing positional slot.
The overload retains existing settings/header/URL validation, API-version/options refusal,
provider identity, pool transport ownership and cancellation behavior. Null explicit factory
options are rejected. The direct constructor's omitted/null optional options select defaults.

### Auth translation

Apply the selected spelling to both chat POST and models GET. A configured nonempty key
supplies `Authorization: Bearer <key>` for `bearer`, or `x-api-key: <key>` for `x-api-key`.
Do not add a default when a caller supplied the matching header, case-insensitively.
Preserve caller headers, including an explicitly supplied other auth header; Python allows
both when the caller asks for them. With no key, do not invent either credential header.
Keep content-type and existing header validation/precedence unchanged. No credential query
parameter, runtime credential suppression policy, or provider-ID branch is introduced.

### No-listing lifecycle

When `ModelsListing` is false, `ListModelsAsync` returns an empty list and `HealthAsync`
returns `new Health(true, "no cheap readiness probe; failures surface on use")` without
HTTP or a generation probe. Before either answer, retain disposed-adapter refusal and
caller-cancellation behavior, including the existing resolved caller token identity.
Use a shared no-listing preflight immediately after `ThrowIfDisposed()`: if the passed
token is canceled, call `CancellationIdentityContext.Resolve(cancellationToken)` and throw
`OperationCanceledException` with the resolved token when that token is canceled, otherwise
with the passed token. A raw `ThrowIfCancellationRequested()` on the linked token is not
sufficient. Run this before constructing either answer or doing transport work.
Transport ownership/disposal remains the same as ordinary adapters. Listing-enabled
behavior, parsing, timeouts, HTTP errors and stream disposal stay unchanged.

### Output-token translation

Build the ordinary payload, including sampling, reasoning and the final raw provider-option
overlay, before the dialect rename. For `max_completion_tokens`, if the final object has
`max_tokens`, remove that key and assign its actual final JsonValue to
`max_completion_tokens`. This matches Python's `payload[field] = payload.pop("max_tokens")`:

| Final overlaid input | Alternate-dialect result |
| --- | --- |
| Sampling max output only | Same value under `max_completion_tokens` |
| Sampling plus raw `max_tokens` | Raw value wins, then is renamed |
| Both raw spellings | Final `max_tokens` value wins over the alternate value |
| Only raw alternate spelling | Retained as supplied |
| No token field | Neither token field is invented |
| Raw `max_tokens` null or another tagged JSON type | Exact tagged value is renamed |

Do not mutate request JSON, change immutable snapshots, coerce raw values, normalize unrelated
keys, or alter generic `max_tokens` behavior. Buffered stream-option cleanup retains its
existing precedence. The rename must apply to both buffered and streamed generation.

## Execution checklist

- [x] **DIALECT.0** Coordinator: cold-critique this exact contract against the adapter,
  Python preset codec and lifecycle boundaries before production edits. Gate: every P1/P2
  is corrected or explicitly resolved; no registration/capability scope expansion.
  > NOTE: Cold critique's P1 is closed after specifying resolved caller-token preflight
  > and direct linked-token controls that cannot be masked by client exception mapping.
  > Exact correction rereview is bounded clean; no other P1/P2 remains.
- [x] **DIALECT.1** Production owner: own only
  `src/csharp/AnyInfer/Providers/OpenAICompatDialectOptions.cs` and
  `src/csharp/AnyInfer/Providers/OpenAIChatAdapter.cs`, plus the assigned artifact and a
  minimal update to this box after rereading. Implement the exact private contract.
  Gate: held-source diff has no whitespace defects and independent source critique has no
  unresolved P1/P2; native compilation remains coordinator-owned.
  > NOTE: Held implementation adds the private immutable dialect options, applies its auth
  > spelling to both request shapes, returns no-listing lifecycle answers only after the
  > resolved-token preflight, and renames the final overlaid tagged `max_tokens` value only
  > for the alternate field. Source diff check passed; DIALECT.1 remains open for the
  > independent source critique and coordinator-native gate.
  > NOTE: Independent held-source review is bounded clean for constructor/factory
  > compatibility, auth precedence, no-list cancellation/disposal and final tagged-value
  > renaming. The source-review gate is closed; compilation and causal controls remain
  > assigned to DIALECT.2/3 rather than implied by this checkbox.
- [x] **DIALECT.2** Independent controls owner: own only
  `src/csharp/AnyInfer.Tests/CompatDialectTests.cs`, plus the assigned artifact and a minimal
  update to this box after rereading. Use the agreed internal factory through synthetic
  descriptors with real public configured AsyncClient calls and offline HTTP transports;
  use direct internal lifecycle calls only for disposed/canceled adapter boundary controls.
  Test defaults and invalid option spellings; both auth styles on actual GET/POST;
  mixed-case caller overrides and other-header coexistence; keyless behavior; listing false
  with zero HTTP; caller-token identity, post-dispose refusal and exact transport disposal;
  exercise both no-listing methods through configured client lifecycle calls with original
  caller cancellation at adapter entry, and directly under a controlled linked-token
  `CancellationIdentityContext.Push` scope so an outer client cannot mask a wrong token;
  the full token-overlay table in buffered and streamed requests; no mutation of inputs.
  Gate: independent controls review finds actual causal observations and no oracle derived
  from expected case IDs. No .NET/build/test invocation by either owner.
  > NOTE: Held independent controls exercise selected auth on actual models/chat HTTP,
  > caller auth precedence, keyless behavior, private option rejection, no-listing linked
  > cancellation identity, and buffered/streamed final-overlay token rename. Root retains
  > compilation and the broader configured-client lifecycle controls review.
  > NOTE: First controls review found codec assertions still bypassed the configured
  > public client and omitted explicit-null factory rejection. The corrected held controls
  > use the synthetic public factory path for codec cases and exact disposal counts.
  > First native compile retained CS0246/CS0738 from the test's missing Capabilities import;
  > the product library compiled. Namespace/HealthAsync return-type corrections and the
  > complete public-path controls are held for exact rereview and the second native run.
  > NOTE: Exact corrected control-source review closes P1/P2: codec cases now traverse the
  > configured public factory, explicit-null rejection and constructor defaults are distinct,
  > and disposal uses actual counters. The second compile exposed only JsonProperty import
  > ambiguity; an exact AnyInfer.Json alias fixes it without semantic change. The source
  > control gate is closed; native execution remains DIALECT.3 and is not implied here.
- [x] **DIALECT.3** Coordinator: serialize native compile/targeted controls once both sources
  are held, retaining fresh logs/TRX and any first failure. Use
  `.venv/Scripts/python.exe .tmp-tests/run_rich_generation_tests.py <fresh-label>` with filter
  `FullyQualifiedName~CompatDialectTests|FullyQualifiedName~OpenAIChat|FullyQualifiedName~ProviderLifecycle|FullyQualifiedName~RichGenerationWireTests|FullyQualifiedName~FrozenTimingCompatibilityTests`.
  Gate: all selected tests pass; exact compiler/runtime diagnostics go to the relevant owner
  for minimal correction, then rerun only the affected coherent scope.
  > NOTE: Third targeted native run passes 59/59, zero failures/skips, after the two
  > test-only import corrections. Evidence is .tmp-tests/compat-dialect-native-third/
  > {native.txt,rich-generation.trx,exit-code.txt}; both failed-first compile logs remain.
  > Product adapter source required no correction, and exact source/control reviews are clean.
- [x] **DIALECT.4** Coordinator: inspect the source/control reviews and run the full coherent
  `workspace.py check` once, through the existing fresh-root wrapper with external pytest
  basetemp. Record source input digests before/after and protected-file digests.
  Gate: all workspace steps pass, including source-stamped shared pairs, package-only consumer,
  executable examples and strict docs; frozen/profile/declaration bytes remain unchanged.
  > NOTE: The first ignored-wrapper preflight stopped before workspace execution because
  > it reused the earlier clean checkout's CRLF registry digest. Root bytes match HEAD's
  > LF blob exactly; the prior checkout differs only by CRLF. Only the ignored wrapper
  > pin was corrected, with proof retained at .tmp-tests/compat-dialect-full-first-coherence/
  > preflight-failure.json. Tracked registry/declaration/profile bytes were not edited.
  > NOTE: The actual full workspace passes all 24 steps in 180.9s at
  > .tmp-tests/compat-dialect-full-second/workspace.txt, including 967 native tests,
  > 93 conformance tests, all shared profile checks, package-only consumer/examples and docs.
  > The coherence proof records 154 input digests unchanged, including the five owned paths,
  > accepted declarations/profiles and user-owned files; no protected bytes changed.
  > Source and causal-control reviews are bounded clean; root is committing only the five
  > explicit owned paths before fresh clean-source qualification.
- [ ] **DIALECT.5** Coordinator: commit only the leaf's explicit owned source/test/plan paths,
  then verify the private seam at that clean source in a fresh managed checkout. Run the
  registered C# workspace gate and Frozen DEVELOPMENT at the selected clean import/source;
  retain compiled source metadata and exact release hash. Gate: clean before/after,
  C# gate passes, Frozen 102/0/0/0 with unchanged released input, independent evidence review.
- [ ] **DIALECT.6** Coordinator: reconcile this leaf and parent SDK.8a without ticking SDK.8a.
  Gate: qualified executable source stays distinct from the plan-only acceptance commit;
  resume the reviewed runtime-data generation/registration boundary, preserving all mixed
  operation assignments and the unchanged public provider-support boundary.

## Ownership and execution rules

Workers are not alone: do not revert another owner's edits. Reread shared plans immediately
before minimal box updates and add `> NOTE:` lines for deviations or retained failure evidence.
Root owns shared plan reconciliation, generated files, heavy/native gates, Git and acceptance.
Children run no .NET/restore/build/pack/native/full suite or Git mutation. Avoid concurrent
heavy suites. Preserve user-owned `uv.lock`, `v/cache/nodeids`, immutable declarations and all
released/profile bytes. Evidence belongs in fresh ignored roots, never an old passing run.
