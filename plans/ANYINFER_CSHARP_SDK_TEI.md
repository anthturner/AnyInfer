# TEI 1.9.4 — Python requalification and native C# retrieval binding

> Resume from the first unchecked box. The user authorized implementation of both
> C# SDK plans in parallel on 2026-10-22, with TEI as this wave's owner lane and
> Python TEI requalification included. TEI.1–8 are complete at verified source
> `af5d0d64840cb8ec81ecdcb92acb9a457958d814`. The parent SDK.6c remains open for
> its other provider bindings. The resume record below names the acceptance checkpoint.

## 1. Starting point and completion boundary

The repository starts at `acdc94469f86eca0a67f9226fbc2c7ae6a7e7bf8` on
`feature/language-neutral-foundation`. Its accepted SDK.6a/b source checkpoint is
`03f26fc88c7c96ff8272e99dadee8c6a26fa0616`: 21 clean workspace gates, 791 native
unit tests, 93 conformance tests, retrieval 32, request-policy 29, accounting 42
plus two native boundaries, and 102 Frozen development observations.

This slice has two deliverables:

1. Requalify the existing Python TEI adapter against the pinned TEI 1.9.4 build,
   refresh its real traffic cassettes and protocol/verification documentation,
   and preserve its supported public behavior.
2. Bind the same native TEI dialect to the existing C# buffered embedding/rerank
   APIs, including discovery, health, optional credentials, cancellation,
   transport ownership, public consumers, and offline replay.

Python has no TEI dependency version to bump. `src/python/anyinfer/providers/tei.py`
speaks HTTP directly; the old version belongs to the contract and recorded live
evidence. Do not add a vendor SDK or a TEI Python dependency.

This completes only the TEI tranche of parent SDK.6c. Other retrieval providers,
generic OpenAI-compatible retrieval, generation, model/runtime acquisition APIs,
vector storage, and SDK.7 onward remain outside this plan. The generic
`openai-compat` descriptor stays chat-only. The TEI adapter never starts Docker,
downloads models, selects routes, retries, calculates prices, or invents usage.

Authorities:

- `AGENTS.md`, `DESIGN.md`, and `contracts/NEW-PROVIDER.md`.
- `plans/ANYINFER_CSHARP_SDK.md`, parent SDK.6c.
- `plans/ANYINFER_CSHARP_SDK_RETRIEVAL.md`, leaf 6c.0 and accepted SDK.6a/b rules.
- Python baseline `199c3f833e568334b629edd7d89f41a3b76efe2a`; the TEI product source
  is unchanged at the starting checkpoint. Requalification does not silently
  redefine this baseline or change the frozen retrieval corpus.
- Research record: `epics/a4822703-eee2-44cb-960c-47b3ae3d4c73/artifacts/csharp-sdk/sdk-six-c-provider-research/index.md`.
- Independent research review: `epics/a4822703-eee2-44cb-960c-47b3ae3d4c73/artifacts/csharp-sdk/sdk-six-c-provider-research-review/index.md`.

## 2. Settled build, model, and deployment pins

| Item | Literal pin |
| --- | --- |
| TEI image | `ghcr.io/huggingface/text-embeddings-inference:cpu-1.9.4@sha256:8419f533857b503ebf6ec292a95d4f1cf9c0464ac8b8abeef39518cf110e5726` |
| Platform | Linux/amd64; CPU verification, independent of GPU availability |
| Embedding model | `BAAI/bge-small-en-v1.5` |
| Embedding revision | `5c38ec7c405ec4b44b94cc5a9bb96e735b38267a` |
| Rerank model | `BAAI/bge-reranker-base` |
| Rerank revision | `2cfc18c9415c912f9d8155881c133215df768a70` |
| Default embedding URL | `http://127.0.0.1:8080` |
| Local verification rerank URL | `http://127.0.0.1:8081` |

The image's advertised compressed layers plus config total 239,313,275 bytes.
The model repositories advertise alternative formats; the safetensors files are
133,466,304 and 1,112,206,140 bytes respectively. These are research facts, not
downloaded sizes, backend selection, or local-runtime evidence. Observe the actual
files/backend when running. Do not add downloaded artifacts to Git or NuGet.

Docker CLI/context `desktop-linux` exists on this host, but the Linux daemon was
not running during research. Startup and download are implementation prerequisites.
Use a run-specific `.tmp-tests/tei-<run>/` evidence directory and a reusable model
cache outside product/package paths. Run only owned, named/labeled containers.
Bind published ports explicitly to `127.0.0.1`, never all interfaces. If 8080/8081
are occupied, stop this preflight and choose/document a deliberate recording
configuration; do not kill an unrelated service or silently rewrite cassette URLs.

Use `--model-id` and the exact `--revision` for each model; record all launch
flags. Confirm actual `/info.version`, model identity, model type, limits, and
image inspection before claiming the build works. A tag/digest lookup alone is
not runtime evidence. Do not assume that `/info` reports the Hub revision:
retain the pinned launch argument and resolved model-cache evidence separately.

## 3. Translation contract to implement

### 3.1 Descriptor and configuration

Add internal `TeiAdapter` implementing `IEmbedsText`, `IReranksText`,
`IProviderLifecycle`, and `IAsyncDisposable`. It implements neither
`IGeneratesText` nor `IProviderAdapter`; there is no generation stub.

Register it in `Providers/ProviderRegistry.CreateDefault` with:

- ID `tei`, alias `text-embeddings-inference`, display name
  `Text Embeddings Inference`, locality `Local`.
- Operations exactly `Embedding` and `Rerank`; empty static model/operation
  capability maps and no guessed price, dimension, intent, or batching limit.
- Default URL `http://127.0.0.1:8080`, `requiresBaseUrl: false`.
- Advanced optional endpoint setup field with that default, and advanced optional
  secret field with `envVar: "TEI_API_KEY"` and matching placeholder.
- Discover-or-manual model selection and `PoolOwnsConfiguredTransport = true`.

Use configured instance identity in errors and telemetry. Descriptor ID and alias
resolution must not erase the configured instance alias. The core credential
resolver/redaction registry remains authoritative. `TEI_API_KEY` is AnyInfer's
client convention; TEI's server launch environment is `API_KEY` / `--api-key`.

Start with JSON Content-Type/Accept and optional Bearer authentication. Configured
headers override defaults case-insensitively, matching Python. Apply content
headers to the request content correctly. Preserve configured base-path semantics;
test URLs with and without a trailing slash and a non-root base path against
Python's actual `httpx2` joining behavior before fixing the C# URI helper.
Reject invalid URL/header construction through existing typed configuration errors.

Python's TEI adapter does not apply config `options` or `api_version`. Preserve
that behavior; do not copy OpenAIChatAdapter's rejection of these fields into TEI.
Per-operation provider options are separate and are applied last to the native
payload, including collisions with `inputs`, `dimensions`, `normalize`, `query`,
`texts`, and `return_text`. This is explicit compatibility behavior; do not add a
new reserved-field filter or merge configuration options into a request.

### 3.2 Discovery and health

Both use `GET /info`; `/health` is a raw deployment probe, not the SDK health path.
Discovery returns the one nonempty string `model_id` or an empty list. A one-key
tagged `model_type` object or string maps `embedding` to Embedding and `reranker`
to Rerank. An unknown recognized shape yields a discovered empty operation set;
missing/invalid shape leaves the fact unknown. Preserve that distinction.

Do not hydrate batching/token/dimension limits from `/info` in this slice: Python
does not do so. Ignore `served_model_name` and other unconsumed fields. Health
returns `serving <model_id>` on success, empty detail for missing identity, or
false with the first 200 Unicode scalar values of a provider failure detail.
Caller cancellation propagates. Lifecycle errors use phase `discover`.

### 3.3 Embedding

`POST /embed` starts with `inputs` as an array, adds `dimensions` only when
requested, then overlays the selected per-call provider options. Do not send
model or input intent as native fields. The target's model is advisory because a
TEI process serves one model. Do not replace the result's target/model with a
cached `/info` value or make an extra discovery request per operation.

The success body is a bare array with exactly one array per original wire input.
Preserve order. Return the parsed body as raw evidence; model and usage remain
null, phases empty, dimensions are the first row length or null for no rows.
Normalized is the final payload's boolean `normalize`, defaulting to true, and
null for a non-boolean override. Empty/ragged/nonfinite vectors reach the existing
core validation as in Python; do not tighten permissive wire DTO constructors.

Python converts vector components through `float`: JSON numeric values, booleans,
and numeric strings have distinct behavior from rerank scores. Cover those
categories, including string nonfinite values passed to core validation. Invalid
conversion must fail with cleanup; do not pretend all native conversion exceptions
are shared ProviderError facts. Do not change Python's coercion policy to simplify
C#. Exotic invalid-JSON number spellings are not an upstream promise.

### 3.4 Reranking

`POST /rerank` starts with `query`, `texts` in wire-document order, and
`return_text: false`, then overlays selected provider options. Do not send model,
caller IDs, original indexes, or `top_n`. The result body must be an array of
objects with an integer, non-boolean positional `index` and numeric, non-boolean
`score`; numeric score strings are rejected. Map position through the submitted
`RerankWireDocument.Index`, preserving the core's cross-chunk validation boundary.

Stable-sort descending by score, preserving provider order on ties, then apply
wire `TopN` client-side. Keep raw as the original response array. Ignore returned
text for normalized items; the core owns caller-ID/text projection. Model/usage
remain null. Do not compare scores across calls or relax `RerankCrossBatch`.

### 3.5 Error mapping

Use Python `providers/http.py:classify_status` semantics, not a blind copy of
OpenAIChatAdapter's classification. Required mapping:

| Condition | Native outcome |
| --- | --- |
| 401/403 | AuthException, nonretryable, configured provider, phase, status, existing actionable credential hint |
| 404 | ModelNotFoundException, nonretryable, existing model/listing hint |
| 429 | RateLimitException, retryable, optional numeric delta-seconds Retry-After |
| 413/422 with a shared context-overflow marker | ContextLengthException, nonretryable, existing shorten-input hint |
| >=500 | ProviderUnavailableException, retryable |
| Other >=400 | Base ProviderException; retryable only for the shared retryable statuses such as 408/409/425; do not relabel these as transport exceptions merely because retryable |
| Connection failure | ProviderUnavailableException with base-URL/server hint |
| Owned HTTP timeout / other transport IO | TransportException with correct phase; preserve underlying native cause |
| Documented response shape failure | Base ProviderException, phase validate, nonretryable; retain the Python message/provider-attribution boundary |

HTTP extraction reads a string `error` member, otherwise UTF-8 replacement-decoded
raw text, and retains the first 300 Unicode scalar values. General exception
redaction/bounding then remains in the core. `error_type` spelling is not consumed:
the tagged OpenAPI enum/source is capitalized while generated examples are lower
case. Do not build an unnecessary dependency on that contradiction.

Honor numeric delta-seconds Retry-After if present; Python `parse_retry_after` ignores HTTP-date forms. This is compatibility behavior, not a claim that TEI emits the header. Do not
read undocumented compute/usage/timing headers into public Usage or Timing.

> NOTE: The reviewed draft incorrectly included HTTP-date Retry-After support. Source review of
> `src/python/anyinfer/providers/http.py:205-218` shows Python accepts float delta-seconds
> only and ignores HTTP-date. Preserve parity in native TEI: accept numeric delta-seconds only.
> Tagged TEI OpenAPI documents no Retry-After header; this is not an emission claim.
Operation transport/status errors use phase `generate`, discovery phase
`discover`, and malformed response shape phase `validate`.

### 3.6 Transport and ownership

Keep transport code local to `TeiHttpTransport.cs` / `TeiAdapter.cs`, modeled on
the existing BCL OpenAI transport. No shared OpenAI/Frozen refactor or new package
dependency. Use `ResponseHeadersRead`, modern internal JSON reader/writer paths,
and the actual wire `MaxResponseBytes` unchanged. Count received bytes before
success parsing, including missing/false Content-Length and chunked content.

Make safety-only native bounds explicit: `/info` bodies are limited to 1 MiB;
HTTP error diagnostics read at most 64 KiB and use a bounded raw-prefix fallback
if the JSON error object is incomplete. These are local transport safeguards,
not discovered provider limits or changes to public operation response caps.
HTTP status classification precedes success-cap validation, matching Python's
ordering. Do not turn a large 401 body into a retryable vector-validation error.
Document these native-only bounds in the contract; Python's existing lifecycle
body buffering is not silently rewritten by this plan.

Use configuration timeout for lifecycle calls and wire TimeoutS for operation
HTTP calls. Keep HttpClient.Timeout infinite; a scoped linked transport timeout
must be disposed after started work settles. Preserve the outer core's existing
operation deadline and close/join behavior. If caller/effective cancellation won,
propagate OCE with the existing `CancellationIdentityContext` rules; only an
owned timeout becomes TransportException. Preserve an unrelated source OCE's
identity. Tests must distinguish these paths rather than comparing milliseconds.

Dispose each request, response and opened stream on success, parse failure,
oversize, cancellation, timeout, and transport failure. Preserve a primary
operation failure when only teardown also fails; do not swallow an independent
cleanup failure on an otherwise successful call. Adapter disposal is once-only.
Respect `ProviderConfig.TransportOwnedByPool`: an opted-in configured handler
is disposed by the pool, not transient adapters. Redirects stay disabled on the
owned default handler. A caller-supplied handler retains its configured behavior.

## 4. Files, ownership, and safe ordering

Every implementation brief includes its box IDs, these exact paths, a requirement
to re-read shared files before minimal edits, and the statement that other agents
are working in the tree and their changes must not be reverted. Workers never
change Git state. Root owns shared manifests and the final gate.

| Lane | Owned paths | Dependencies |
| --- | --- | --- |
| Contract / live Python refresh | `contracts/tei.md`; `tests/test_tei.py`; `tests/test_tei_cassettes.py`; the three `tests/cassettes/tei_*.json` files | TEI.1 then real-build TEI.2; cassette recording serialized |
| Native adapter | new `src/csharp/AnyInfer/Providers/TeiAdapter.cs`, `TeiHttpTransport.cs`; `Providers/ProviderRegistry.cs` | Contract + actual response facts held |
| Independent native controls | new `src/csharp/AnyInfer.Tests/TeiAdapterTests.cs`, `TeiLifecycleTests.cs`, `TeiCassetteTests.cs` | Settled contract; tests may be authored alongside adapter, execution waits for held files |
| Native live public probe | new `src/csharp/AnyInfer.TeiProbe/AnyInfer.TeiProbe.csproj` and `Program.cs` | Adapter + independent controls held; uses public APIs only |
| Public delivery | `docs/providers/tei.md`; `docs/guides/csharp-sdk.md`; `docs/reference/csharp-sdk.md`; `src/csharp/README.md`; new `examples/csharp-sdk/TeiExample.cs`; `examples/csharp-sdk/Program.cs` | Adapter held; verification claims wait for live results |
| Package witness | `scripts/check_csharp_package.py`; `tests/test_csharp_packaging.py` | Adapter held; no overlap with example owner |
| Root integration | `src/csharp/AnyInfer.sln`; `src/csharp/AnyInfer.Tests/AnyInfer.Tests.csproj`; this plan and parent/retrieval resume notes; narrowly necessary registry assertions | Serial after owners release files |

The Python product file is read-only unless real evidence demonstrates a TEI-local
defect necessary for 1.9.4. Root must record the failing response and minimally
amend this plan before assigning that correction. Changes to public core policy,
config schemas, pricing/catalog data, generic OpenAI behavior, or a frozen profile
require a new decision, not a workaround hidden in this tranche.

No new Python provider exists here, so do not change Python provider counts/nav,
registry inventory, conformance flags or matrix membership merely for a version
refresh. Regenerate the existing matrix only if its actual derived data changes.

## 5. Executable phases

Use the project's Python environment; commands below use `python` for its selected
interpreter. Run all .NET builds/tests serially. Root runs the full gate once
after the coherent tranche and repeats only for a new change/failure. Each owner
ticks only its assigned boxes after its gate and adds a `> NOTE:` for deviations.

- [x] **TEI.1 — Freeze the refreshed wire contract before adapter code.** Re-read
  current upstream tagged API/source and the research ledger. Update
  `contracts/tei.md` with separately dated sections for historical Python 1.8.3
  live evidence, current 1.9.4 documentation/source facts, selected immutable
  image/model pins, planned Python+C# mappings, and still-unverified runtime
  claims. Correct omitted/null truncate inheritance from server `auto_truncate`;
  retain the older snapshot's date/source scope without repeating it as current
  behavior. Explain no native top_n, unknown usage, no limit hydration, options
  precedence, numeric delta-seconds Retry-After handling, and native safety bounds.
  **Gate:** independent contract/source critique closes all actionable findings;
  no new last-verified/live date is assigned before TEI.2 observes it.

> NOTE: Contract/source draft saved 2026-10-22 from tagged v1.9.4 OpenAPI and
> router source; runtime facts remain unverified. Independent Terra critique closed on
> 2026-10-22 after correcting Retry-After to Python's numeric-only behavior; all 22 contract
> snapshots pass structural validation. TEI.2 is released to the pinned-runtime owner.

- [x] **TEI.2 — Run the pinned CPU build and establish current Python evidence.**
  Preflight daemon, architecture, free space and both loopback ports. Inspect/pull
  the exact image; launch two owned containers with pinned model revisions and
  explicit loopback bindings. Preserve the old three cassettes in ignored run
  evidence before replacing their owned files; never append new interactions to
  stale captures. Record `/info` and `/health` on both servers, actual version,
  image digest, model/cache revisions, flags, limits, startup/backend, and raw
  sanitized traffic. Exercise scalar/batch embedding, normalize false/default,
  requested dimensions, rerank positional indexes/order, explicit truncate
  true/false versus omitted/null, empty/oversize and wrong-model-type requests,
  and API-key mode with a disposable registered secret. An unsafe/unreproducible
  overload remains explicitly unverified. Do not force undocumented server
  cancellation semantics.
  Re-record the three existing cassette tests using
  `ANYINFER_RECORD_CASSETTES=1 python -m pytest tests/test_tei_cassettes.py`;
  clear that environment setting afterward. Record date/build only from the
  actual run. Update cassette-test recording instructions, and contract evidence.
  If the existing Python adapter does not work, retain the failed evidence and
  settle the smallest TEI-local correction before C# implementation proceeds.
  **Gate:** real Python requests work against both pinned servers, all three
  new cassettes contain only fresh sanitized interactions, and independent replay
  passes with no server and recording disabled. Actual pins match the selection.

> NOTE: Accepted 2026-10-22 after independent runtime review. Fresh recording and
> recording-disabled offline replay each pass 3/3. The pinned servers report 1.9.4
> and e80ef225ed0e6cb1717ce632a6a84b6cf211bb67; image/model identities match.
> Public Usage is an unknown-valued object, while adapter wire usage is null.
> Failed-first cache-teardown evidence and historical cassette bytes are retained;
> the unrelated user cache remains untouched. Overload, backend cancellation and
> actual Retry-After emission remain unverified.

- [x] **TEI.3 — Complete Python compatibility controls.** Extend
  `tests/test_tei.py` only where absent: tagged/string/unknown/absent model_type;
  no capability-limit hydration; configured headers/Bearer precedence; ignored
  config options/API version versus per-call reserved overrides; base-path joining;
  normalized override; dimensions and count/row coercion; response caps; stable
  rerank ties and TopN; non-contiguous original indexes; numeric/bool score rules;
  phase/status/retry-after/300-scalar detail; health's 200-scalar detail; unknown
  usage despite observed headers; transport close and cancellation. Retain the
  existing ConformanceHarness flags and successful end-to-end path. A mock's
  version literal is not a live pin and need not be changed merely to say 1.9.4.
  **Gate:** `python -m pytest tests/test_tei.py tests/test_tei_cassettes.py`,
  targeted Ruff check/format, and source-valid independent control review pass.

- [x] **TEI.4 — Implement the native adapter and default registration.** Add only
  the adapter/local transport and descriptor paths in section 4, following section
  3. Hold files before another owner runs tests. Root searches existing
  `CreateDefault`/`Descriptors` assertions and changes only actual builtin
  inventory expectations from the added TEI descriptor; no weakening of generic
  compatibility's generation-only contract. No extra discovery call, generated
  adapter stub, retry loop, dependency, or shared JSON/core rewrite.
  **Gate:** `dotnet build src/csharp/AnyInfer/AnyInfer.csproj --no-restore`
  has zero warnings, and independent source/ownership review closes findings.

- [x] **TEI.5 — Prove native mapping and lifecycle offline.** Add independent
  controls using scripted HttpMessageHandler/HttpContent/Stream ownership facts.
  Use existing real cassette body/status/header strings for common response truth;
  the replay handler reads those files rather than deriving provider answers from
  the C# implementation. Root adds explicit test-only cassette CopyToOutputDirectory
  entries to the test csproj. Check method/path/payload/headers, caller-config
  nonmutation, aliases, optional protocols and discovery provenance, stable ties,
  original-index mapping, unknown usage/raw default versus opt-in, phases/statuses,
  body caps above/below standalone defaults and missing/lying Content-Length.
  Drive public async and sync clients, operation_routes, result/manifest consistency
  and SpendLedger unknown-cost behavior; public manifests remain Payloads=null.
  Lifecycle controls hold send/open/read phases behind causal barriers, cancel the
  original caller token, distinguish owned timeout/unrelated OCE, assert all started
  work joined, and count real response/stream/handler disposal including transient
  retry/pool ownership. No wall-clock scheduler races or mock-only close counters.
  **Gate:** `dotnet test src/csharp/AnyInfer.Tests/AnyInfer.Tests.csproj --no-restore -m:1 --filter FullyQualifiedName~Tei`
  passes; cassette replay and independent source/oracle review close findings.

- [x] **TEI.6 — Exercise the native public API against the same live servers.**
  The small `AnyInfer.TeiProbe` executable is verification infrastructure, not a
  shipped assembly or an SDK adapter dependency. It accepts explicit embedding
  URL, rerank URL, expected version `1.9.4`, expected model IDs, output path, and
  build-stamped source revision/dirty metadata. It writes two separately named
  witnesses against the same explicitly supplied URLs: a minimal raw BCL
  `GET /info` deployment verifier checks version, identity and reported limits;
  a public-SDK witness uses AsyncClient/Client, ProviderSettings and the default
  registry for discovery and inference. The raw verifier never parses inference
  responses or claims SDK success. The public witness does not claim version/limit
  verification, because those fields are absent from public DiscoveredModel/Health.
  Neither starts/downloads a server/model or implements inference policy.
  Fail on mismatched readiness/identity, missing operation, invalid public result,
  unavailable endpoint, or cleanup failure; never label an unrun probe as passing.
  Exercise discovery, both operations, stable document IDs, TopN, dimensions,
  normalize, unknown usage, raw opt-in, null manifest payloads, ledger and disposal.
  Server error observations remain attached to the actual request/status/body.
  Use controlled fake HTTP streams from TEI.5 for deterministic delayed-body
  cancellation; record any real-server cancellation observation as such, without
  claiming backend work was cancelled merely because the client stopped waiting.
  Root registers the nonpackable project in the solution and invokes it explicitly
  against the same pinned containers. **Gate:** stamped successful native probe,
  same-runtime Python evidence, and offline replay all agree on supported wire
  fields/semantics. Compare no live floating values, duration, or backend ordering
  across separate inference calls as an exact parity oracle.

> NOTE: TEI.3 source/oracle review is closed with 33 focused Python passes plus the
> one-test complete unknown-usage assertion recheck. TEI.4/5 source and control reviews
> are closed with 24 native passes, including parse/shape/status/read/cancellation/timeout
> failures under throwing teardown. Conversion runs inside the response lifetime and
> configured provider attribution preserves the original phase. TEI.6 public live probe
> passed on 2026-10-22 with acdc944/dirty=true; raw deployment and public SDK evidence are
> separate. Failed-first stamp evidence is preserved; the corrected MSBuild hook runs before
> GetAssemblyAttributes. TEI.8 still requires the clean committed replay.

- [x] **TEI.7 — Deliver truthful docs, examples and packed-artifact consumers.**
  Update existing Python TEI docs/instructions to the qualified patch/digest/model
  revisions and real observed date. Preserve one-model-per-server guidance,
  loopback-only launch commands, client/server key-variable distinction, server
  truncation inheritance and unknown usage. Add C# TEI examples using two instance
  aliases, public default registry, async disposal and sync facade. The offline
  example verifier supplies a scripted HTTP handler to the real builtin; it does
  not substitute a fake retrieval adapter and call that TEI protocol proof.
  Extend the existing generated NuGet-only consumer with the same public builtin
  witness; no project-reference fallback and no package allowlist widening.
  Update C# registry/scope statements in guide/reference/readme together; do not
  imply all providers or generic retrieval are implemented. Docs never link plans.
  **Gate:** targeted packaging controls, compiled offline examples, isolated
  package checker, and strict docs build pass; cold public-delivery review closes.

> NOTE: Root compiled and ran the offline examples and the isolated NuGet-only consumer;
> both pass, with package build reporting zero warnings/errors. The consumer checks retained
> raw embedding/rerank results and unknown input/output usage. Strict docs build passes;
> cold delivery review is closed. Public pages share the bounded 2026-10-22 TEI 1.9.4
> exercise statement, while detailed source-state evidence remains in the execution artifact.

- [x] **TEI.8 — Preserve SDK proofs and qualify one clean source checkpoint.**
  Close all owner/source/test/protocol reviews, then root runs `python workspace.py check`
  (22 steps after the maintenance-exporter gate) with recording disabled and no local server requirement.
  Preserve retrieval32, policy29, accounting42+2 and Frozen102, with source/dirty/
  corpus metadata bound to the actual source. Verify Frozen release assets and run
  its explicit development mode; publish no release report. Stage only reviewed
  explicit paths after inspecting the diff, leaving existing uv.lock/v artifacts
  untouched. Commit only after the full gate. Re-run applicable full/package/profile
  and TEI live probes from an isolated clean checkout of that exact source commit;
  retain the clean-before/after status and actual image/model identities. The live
  containers/cache may be reused only if their inspected pins still match.
  **Gate:** full clean workspace, all unchanged profiles, isolated package execution,
  Python fresh-cassette replay and clean native live evidence pass; no false clean
  stamp, hash hand-edit, or comparison-policy waiver. Root records the exact commit,
  commands, counts, failed-first evidence, source state and container cleanup in
  this plan and the acceptance artifact. Only the TEI tranche closes; parent
  SDK.6c remains open for its other providers.

> NOTE: The first integrated 22-step gate on 2026-10-22 failed two test steps:
> a stale workspace assertion forbade the Python setup required by the maintenance runner,
> and the TEI timeout control's separate cancellation observer stalled in the full native
> suite. The other 20 steps passed, including strict docs, package/examples and preserved
> profiles. Failed-first log: root shell `6a2563c4-372a-45e3-a444-a8968ab12293`.
> Acceptance remains open until the exact controls are corrected and the full gate passes.
>
> The two test-only corrections are independently accepted: the workflow assertion now
> requires its actual pinned Python runner prerequisites, and HeldHandler observes cancellation
> in its own held await rather than a separate registration subject to callback ordering.
> The repeated root gate passes all 22 steps in 137.5s, with 815 unit and 93 conformance
> tests. Source commit and isolated clean-source replay are the remaining TEI.8 work.
>
> Initial source commit `3834e8e7387bf26637f5965a77ffd5125b0f82fb` passed the primary
> full gate but its isolated clean replay exposed a prebuilt-exporter dependency. The Python
> suite ran native controls before the native build, and the native shape step also assumed
> its non-test executable was built by `dotnet test`. Clean replay is not accepted for that
> commit. The existing native inventory step now builds the solution and executes all five
> exporter controls; Python checks only that boundary. The 9/22 step counts are unchanged.
> A new source checkpoint and full clean replay are required.
> The corrected native-boundary gate has clean independent review and the repeated root
> full gate passes all 22 steps in 156.1s. Clean replay of the correction is still required.

> NOTE: Final acceptance is source `af5d0d64840cb8ec81ecdcb92acb9a457958d814`, tree
> `8a4a30bcb174b1d1c17015860e91ea01b7647b1a`. Root's full gate passes in 155.5s;
> a fresh isolated checkout passes all 22 steps in 154.2s, including 815 native unit and
> 93 conformance tests, preserved retrieval32/policy29/accounting42+2, strict docs,
> compiled examples and the NuGet-only consumer. Recording is disabled. Frozen release
> verification retains `16122cca198d9e688d3c4b5724ac11f0324a4390d8e8589e443fe04a48e81391`;
> explicit development output records 102 pass, zero fail/error/unavailable.
>
> The clean public TEI probe records that exact commit with Dirty=false, expected 1.9.4
> models/deployment facts, normalized 384-dimensional embedding, rerank caller ID and unknown
> usage/cost. No live floating-value comparison or backend-cancellation claim is made.
> Before/after Git status is empty in the acceptance checkout. Both owned test containers
> are stopped; image/model caches and all failed-first logs are retained. Evidence was copied
> to `.tmp-tests/tei-propagation-acceptance/final-source-af5d0d6/` before retiring the three
> temporary Git worktrees. Windows retains their locked empty directories; no source/build
> files or Git registrations remain there. Unrelated uv.lock/v files retain their hashes.
> See the combined acceptance artifact at
> `epics/a4822703-eee2-44cb-960c-47b3ae3d4c73/artifacts/provider-maintenance/execution/acceptance/index.md`.

## 6. Integration and evidence rules

Heavy gates are serialized. Offline tests never contact public networks or require
Docker/model caches. The new live probe is explicitly invoked and fails closed;
normal CI builds it without running local inference. Do not add a C# phase step
or change the total workspace gate count just to run a local-only probe. The added
maintenance-exporter shape gate belongs to the parallel propagation plan.

The shared SDK6 retrieval fixture schema, inputs and observation schema stay byte
identical. Their hashes remain:

| File | SHA-256 |
| --- | --- |
| `tests/fixtures/retrieval-v1/schema.json` | `db8a6c122102bf23cf542ffd47d62f7bb6996e7ffd1f27d56877bfa16eb37f08` |
| `tests/fixtures/retrieval-v1/inputs.json` | `cbf8640aa19920044e652d2a095563c480b8a5e7b18c16a2e471f89eb24a4750` |
| `tests/fixtures/retrieval-v1/observations.schema.json` | `d3a8aa553fc2eb81c28122895b0ad7c443c170a9e8e5a0254782e1dcef783fac` |

Existing Python/C# observers and comparison scripts are preservation tools, not
implementation or expected-answer inputs for the TEI adapter. Do not edit them to
accept TEI discrepancies. Provider cassette replay is a separate test boundary.

For every live run, retain the UTC time, host/architecture, immutable image/model
pins, inspected version/limits, source commit/dirty status, launch flags, exact
sanitized request/response evidence, tool exits, and ownership/cleanup results.
Never hand-author a cassette or mark a research-only version as live-verified.
Backup/delete only the explicitly owned old cassette paths when re-recording;
preserve their history and failed-first evidence. Redact registered secrets before
persisting outputs, including keys/headers, not only exception messages.

Do not uninstall Docker, purge shared caches/images, delete another container,
modify protected branches, publish a package/report, or bump the package version
as part of this tranche. Model/runtime acquisition remains outside the adapter.

## 7. Resume record

Planning checkpoint: `acdc94469f86eca0a67f9226fbc2c7ae6a7e7bf8`.
Verified implementation checkpoint: `af5d0d64840cb8ec81ecdcb92acb9a457958d814`.
There is no unchecked TEI box. All focused/source/protocol reviews and full clean-source
acceptance are closed. The later closure commit changes plans only and does not claim a new
runtime observation. Continue the parent SDK.6c with its remaining providers; generic
OpenAI compatibility remains chat-only. No package release or qualified specification report
was published. Failed-first evidence and the earlier development checkpoint remain retained.
