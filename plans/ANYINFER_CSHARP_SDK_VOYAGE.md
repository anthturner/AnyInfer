# Native Voyage retrieval binding

Resume from the first unchecked box. Execute under the parent
`ANYINFER_CSHARP_SDK.md` SDK.6c. Root alone owns Git, shared manifests/plans and heavy gates.

## Settled scope and authority

The user asked on 2026-10-22 to continue Python/C# SDK parity founded on the shared
specification. TEI is accepted at `af5d0d64840cb8ec81ecdcb92acb9a457958d814`;
the current baseline is `c5b274d0445a0ac9ec36792e1f4606bc5797133b` (plans-only closure).
Voyage is the next complete retrieval-only descriptor. Generic `openai-compat` stays
chat-only; no incomplete native OpenAI generation/batch descriptor is introduced.

Authority order: frozen `specification/core-generation.md` plus its exact released corpus;
existing accepted accounting/request-policy/retrieval contracts; current
`contracts/voyage.md` for provider wire facts; Python `providers/voyage.py` and
`openai_shaped_retrieval.py` for the existing provider behavior. Neither implementation
calls the other, and observers/comparators are never implementation oracles.

This is a wire-only addition, preserving normalized behavior. Do not edit frozen
specification/reference/release/corpus assets or accepted retrieval fixture bytes.
No new profile/release/support claim, package publication, hosted inference spending,
model acquisition, or credential discovery is authorized by this tranche. Live Voyage
traffic is unverified unless an already-authorized credential lane becomes available;
offline handler evidence is labelled as such.

## Binding contract

- Internal `VoyageAdapter` implements `IEmbedsText`, `IReranksText`, `IProviderLifecycle`
  and `IAsyncDisposable`; no dummy generation method. Register `voyage`, alias `voyageai`,
  hosted, default URL `https://api.voyageai.com/v1`, required secret `VOYAGE_API_KEY`,
  optional base URL, manual model selection, exactly embedding/rerank operations.
- Mirror the existing nine Python static embedding and four rerank capability rows;
  1000 input/document limits, query/document intents and native TopN. Unknown dimensions,
  normalization, pricing, and discovery facts stay unknown. Do not expand model tables.
- A single BCL HTTP client/handler lifetime, with explicit configured-handler pool
  ownership. Base URL path is preserved; append `/embeddings`, `/rerank`, `/models`.
  Default JSON/Bearer headers are overridden case-insensitively by configured headers.
  Resolve credentials in the existing core. Config options/API version follow Python
  Voyage (ignored); only per-operation extra options overlay the payload last.
- Embedding body: `model`, array `input` even for singleton; mapped `input_type` only
  query/document, nullable `output_dimension`. Parse object `data` array with exactly
  input count, unique integer non-Boolean positional indexes and array vectors. Restore
  input order, preserve Python numeric/bool/string component conversion and let public
  core reject nonfinite/ragged/invalid vectors. Response string model is optional.
  Dimensions derive from vector length; normalization unknown. Retain raw tagged JSON.
- Rerank body: `model`, `query`, text-only `documents`, optional `top_k`; overlay last.
  Parse `data` entries with strict integer non-Boolean positional index and numeric
  non-Boolean `relevance_score`; map to each wire document's original index. Adapter
  preserves response order; existing core validates without sorting or local truncation.
  TopN is an outbound `top_k` request, with returned order/cardinality owned by the service.
- Raw usage accepts only integer non-Boolean `usage.total_tokens`, otherwise unknown;
  leave input/output breakdown unknown in both wire and public results. Existing cost
  normalization may interpret embedding totals without mutating the returned Usage;
  rerank never infers input tokens from total tokens.
- Discovery is empty without HTTP. Health GET `/models` reports reachability for every
  HTTP status, including 404/401; transport failure means unhealthy, caller cancellation
  propagates. Health detail bounded to 200 characters, diagnostics bounded/redacted.
- All response bytes bounded while reading, independent of Content-Length. Classify
  error statuses before success-body caps; bounded error detail reads top-level `detail`
  and ordinary shared error shapes. Match shared HTTP status categories, typed
  connection-vs-IO failures, numeric finite nonnegative Retry-After, caller-token identity,
  configured/per-call timeout. Conversion runs before owned cleanup so status/JSON/shape
  primary failures survive throwing stream/response disposal. Attempt all cleanup;
  success-only cleanup faults escape. No retry/routing/timing/usage policy in adapter.

## Ownership and execution checklist

- [x] **VOY.0a** Read parent plan, DESIGN and provider procedure; fetch current official
  embeddings/rerank/error references before adapter code. Update snapshot truthfully.
  Gate: 2026-10-22 pages confirm existing vocabulary; current dimensions and absence of
  live evidence are explicit. Source no-listing behavior is distinguished from API facts.
  > NOTE: Raw reference `ssr-props` OpenAPI schemas independently confirm response
  > rows/usage/error detail. Retained public pages: `.tmp-tests/voyage-research/`.
  > Python Voyage/shared parser/HTTP/types have no Git diff from the parent baseline
  > `199c3f833e568334b629edd7d89f41a3b76efe2a`; no moving-source baseline is introduced.
- [x] **VOY.0b** Cold-review this binding contract against Python and foundational
  boundaries. Gate: settle any source-contract contradiction before runtime acceptance.
  > NOTE: Cold review found that both operation cores preserve rerank provider order;
  > neither stable-sorts nor applies a local TopN. Voyage preserves the Python behavior.
  > The input-only TopN fixture therefore supplies one server-selected response row;
  > direct unsorted-response controls assert preservation rather than TEI-specific sorting.
- [x] **VOY.1** Native owner: new `src/csharp/AnyInfer/Providers/VoyageAdapter.cs` and
  `VoyageHttpTransport.cs`, minimal `ProviderRegistry.cs` registration only. Re-read
  shared registry before edit. Do not refactor TEI/OpenAI/core. Gate: source review and
  root serialized library compile; independent tests own expected behavior.
  > NOTE: Cold review closed error-body status preservation, headers-only health,
  > custom Content-Type and strict rerank score parsing. Native counter-width conversion
  > is explicitly range-checked. First failed compile and review controls are retained.
- [x] **VOY.2a** Python controls owner: input-only
  `tests/fixtures/voyage-wire-v1/inputs.json` and `tests/test_voyage_binding.py`.
  Fixture has two records with literal request input and HTTP response JSON, no expected
  SDK verdict/output. Embed uses reverse-index response, rerank uses caller document IDs
  distinct from positions. Run through public Python client; verify exact requests and
  actual result/usage/raw/manifest. Cover current adapter mapping/error boundaries in
  focused existing Voyage tests. Gate: `.venv/Scripts/python.exe -m pytest
  tests/test_voyage.py tests/test_voyage_binding.py -p no:cacheprovider` with fresh ignored
  basetemp/JUnit and targeted Ruff. No Python product changes absent a real defect.
  > NOTE: Fresh corrected-fixture run passes 15 tests, with Ruff check/format clean.
  > Evidence: `.tmp-tests/voyage-python-controls-rerank/{pytest.log,junit.xml}`.
- [x] **VOY.2b** Native controls owner: new
  `src/csharp/AnyInfer.Tests/VoyageAdapterTests.cs` and `VoyageLifecycleTests.cs`.
  Author from Python/contracts/public API, without reading mutable adapter implementation.
  Independently consume the saved input-only fixture. Cover exact paths/headers/options,
  indexed embedding and rerank IDs/TopN, raw usage vs public normalization, capabilities,
  health/discovery, caps/status/Retry-After, caller/timeout, handler ownership, and primary
  failure precedence under throwing stream/response cleanup. Root links fixture in csproj.
  Gate: root serial filtered native tests; no wall-clock sleeps or disconnected spies.
  > NOTE: The coherent filtered native gate passes 29/29 with zero skips at
  > `.tmp-tests/voyage-native-final/`. Shared inputs and responses are independently
  > consumed; malformed-score controls pre-parse their JSON. Subsequent redaction setup
  > explicitly registers its own secret and exercises the real health-detail bound.
- [ ] **VOY.3** Root integrates exact exporter dependency mapping and native inventory
  expected rows for `voyage` embedding/rerank; public registry controls reflect achieved
  count. New immutable `maintenance/changes/voyage-native-binding.json` uses adopted
  inference embedding/rerank and no_delta rationale plus all applicable gates; the existing
  TEI declaration remains byte-identical. Gate: schema/FormatChecker and native inventory
  actual metadata controls; pure propagation planning accepts honest current inventory.
- [x] **VOY.4** Delivery owner: executable `examples/csharp-sdk/VoyageExample.cs`, invoke
  it from existing Program; same public builtin witness in isolated NuGet consumer
  `scripts/check_csharp_package.py` plus its source tests. Update
  `docs/providers/retrieval.md`, C# guide/reference, source README and guide enumeration
  consistently. Use exact compiled example include; disclose no live Voyage evidence.
  Gate: targeted Python packaging source tests/Ruff, root serial examples and isolated
  package compile/run, strict docs. No broad parity/provider-readiness claim.
  > NOTE: Repository mapping already groups Voyage/Jina in `docs/providers/retrieval.md`.
  > Extend that canonical guide; no new provider page, nav entry or Python provider count.
  > NOTE: Public calls omit the unsupported illustrative dimension 2; small scripted
  > response vectors are offline stimuli only. Source-linked async/sync examples and
  > NuGet-only consumer compile/run with zero warnings/errors. Strict docs also pass.
  > Retained evidence: `.tmp-tests/voyage-public-native/` and full workspace log below.
- [x] **VOY.5** Cold source/test/delivery review; fix bounded findings without weakening
  controls. Root full `.venv/Scripts/python.exe workspace.py check` with cacheprovider
  disabled; all 22 steps plus Frozen native development 102 remain passing. Existing
  retrieval 32, policy 29 and accounting 42+2 bytes/comparison remain unchanged.
  > NOTE: All 22 workspace steps pass in 155.0s, including 844 native unit and 93
  > conformance tests, all prior shared comparisons, native inventory and strict docs.
  > `.tmp-tests/voyage-workspace/workspace.txt` is the retained full log. Explicit Frozen
  > development output `.tmp-tests/voyage-frozen-primary.json` has 102 pass, zero
  > fail/error/unavailable. Cold reviews close all findings; no released asset changed.
- [ ] **VOY.6** Root explicit-path commit after full gate, fresh clean checkout execution
  with import provenance, isolated package/native/profile evidence, then plans-only
  acceptance closure. Record exact source/tree/evidence and remaining SDK.6c providers.
  Gate: clean source and no fabricated qualification; no remote publication.

## Resume

VOY.3/VOY.6 at baseline `c5b274d0445a0ac9ec36792e1f4606bc5797133b`: source and
all 22 primary gates pass. Commit explicit source paths, then run actual registered
Python/C# producers and pure aggregation against this declaration from a clean checkout,
with import provenance, native profiles/package/examples and Frozen development proof.
Preserve user-owned `uv.lock`, `v/`, and `.pytest_cache/v`.
