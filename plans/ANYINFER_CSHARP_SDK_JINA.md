# Native Jina retrieval binding

Resume from the first unchecked box. Parent: `ANYINFER_CSHARP_SDK.md` SDK.6c.
Root alone owns Git, shared manifests, checklist updates and serialized heavy gates.

## Settled scope

The user's 2026-10-22 continuation authorizes the next complete retrieval-only provider
after TEI and Voyage. Baseline is `06408e8f519a85f50ca8fea6c179adac1c7cfbac`.
Preserve frozen foundational assets and accepted retrieval/accounting/policy contracts,
corpus bytes, comparison rules and public core ownership. This is provider-wire translation
with no normalized behavior or foundational specification delta.

Current official https://api.jina.ai/openapi.json (fetched 2026-10-22) is accessible,
version 2026.10.13.1624. It documents model listing and additional usage fields.
The supported text-only subset remains total-token-only with manual selection and empty
discovery: explicit SDK limitations, not assertions about upstream absence.
Correct one demonstrated wire defect in BOTH SDKs: four known v5 embedding IDs use task
`clustering`; v3 uses `separation`; v4 supports only query/document normalized intents. The product FAQ's generic separation guidance conflicts
with the model-specific OpenAPI enum; the model-specific enum governs this literal choice.
For exact v4 omit classification/clustering task fields and narrow its advertised intents
to query/document; existing core warns on unsupported intents. No catalog expansion, new
usage normalization, model discovery or multimodal support.
Health remains any-status reachability; shared Python mixin and native Voyage diagnostic
change `no listing API` to `reachability only`, without accepted transport refactoring.

## Binding contract

- Internal JinaAdapter implements IEmbedsText, IReranksText, IProviderLifecycle,
  IAsyncDisposable. Builtin jina, alias jinaai, hosted, https://api.jina.ai/v1,
  required JINA_API_KEY, optional base URL, manual-only; embedding/rerank only.
- Mirror six Python embedding/four rerank static rows including v5 dimensions, choices,
  token limits and model-specific intents (v4 only query/document). Unknown batch/document limits/prices stay unknown.
- POST embeddings: model, array input, optional task and dimensions; query maps to
  retrieval.query, document to retrieval.passage, classification verbatim, clustering
  to clustering for EXACT four known v5 IDs, omitted for exact v4, separation otherwise.
  V4 also omits classification. Options overlay
  last; config options/API version ignored as in Python. POST rerank: model/query/text
  documents/optional top_n, results envelope, strict positional index/numeric nonbool score.
- Restore embedding index order; require exact count, unique integer nonbool indexes.
  Preserve Python bool/string float conversion; public core validates finite/ragged vectors.
  Optional model/raw retained; normalization unknown. Rerank preserves returned order/count
  without local sorting/TopN and maps positions to original indexes/caller IDs.
- Only integer nonbool usage.total_tokens normalized; input/output remain null.
  Preserve other usage raw; native long overflow rejects explicitly.
- Provider-local BCL transport based on accepted bounded Voyage mechanics, no refactor of
  TEI/OpenAI/core. Preserve base paths, header overrides, handler/pool ownership, typed
  failures, caller-token identity, owned timeout, numeric Retry-After, actual stream cap,
  status precedence, conversion-before-cleanup and primary failure precedence. No retries.
- Empty list_models performs no HTTP. Health GET models reads headers only, any status
  healthy, transport failure unhealthy, caller cancellation propagates; detail bounded/redacted.
- No credentials/hosted spend/model acquisition/remote publication/new spec release.
  Offline evidence is labeled honestly; no full-library parity claim.

## Execution checklist

- [x] **JINA.0** Research, truthful contracts/jina.md snapshot BEFORE adapter edits;
  cold critique against Python/core/spec. Gate: current citations, model-specific task
  conflict settled and upstream versus library limitations explicit.
  > NOTE: Cold plan critique closes v4/v5 source conflicts. Both control suites must
  > prove the full model/intent matrix, including options-last overrides. Raw OpenAPI
  > retained at .tmp-tests/jina-research/openapi.json; hosted behavior remains unverified.
- [x] **JINA.1** Native owner: new Providers/JinaAdapter.cs and JinaHttpTransport.cs,
  minimal ProviderRegistry.cs registration, Voyage health diagnostic only. No new mutable
  tests read. Gate: cold source review, root serialized compile and independent controls.
  > NOTE: Native source is held. Root library build passes with zero warnings/errors
  > at .tmp-tests/jina-native-first/library.txt; independent cold source review is clean.
  > Focused native controls and the final full/clean gates below close this source gate.
- [x] **JINA.2P** Python owner: providers/jina.py task/capability correction;
  openai_shaped_retrieval.py discovery/health wording; new input-only
  tests/fixtures/jina-wire-v1/inputs.json and tests/test_jina_binding.py. Both runtimes
  consume literal request AND response fields; no expected SDK output/verdict in fixture.
  Gate: focused test_jina/test_jina_binding/test_voyage/test_voyage_binding with
  cacheprovider disabled, fresh ignored log/JUnit/basetemp and targeted Ruff. No .NET.
  > NOTE: Independent Python gate passes 62 cases, including all 28 model/intent pairs
  > and both public v4 warning/omission cases. Retained evidence:
  > .tmp-tests/jina-python-controls-final/junit.xml; targeted Ruff is clean.
  > Subsequent exact-membership review adds a v5-shaped unknown: both matrices now cover
  > 32 model/intent pairs; the final binding-only Python gate passes 40 cases at
  > .tmp-tests/jina-unknown-model-controls/. The full suite exercises all updated controls.
- [x] **JINA.2N** Independent controls owner: JinaAdapterTests.cs/JinaLifecycleTests.cs
  authored from contract, Python and public APIs WITHOUT new adapter source. Cover all
  task variants, overlay/headers/index/order/raw/usage/metadata/health/discovery, errors,
  caps, cancellation/timeout/ownership and primary cleanup precedence. Root adds fixture
  project link. Gate: root filtered native execution, no sleeps/disconnected spies.
  > NOTE: Root native gate passes 28/28 with zero skips, including full task matrix
  > controls inside the fact cases. Native log/TRX retained at
  > .tmp-tests/jina-native-controls-first/. Cold test-oracle review remains in JINA.5.
- [x] **JINA.3** Root exporter mapping and expected seven native rows; new immutable
  maintenance/changes/jina-native-binding.json with actual affected paths, all mandatory
  registered gates and no_delta rationale. Old declarations unchanged.
  Gate: schema/FormatChecker and actual native metadata controls.
  > NOTE: Declaration validates against the strict change schema. Native inventory
  > shape/provenance/determinism and malformed-context controls pass with seven actual
  > bindings at .tmp-tests/jina-inventory/native.txt (dirty development evidence).
- [x] **JINA.4** Delivery owner: compiled async/sync JinaExample + Program invocation,
  NuGet-only builtin witness + packaging source tests, retrieval guide and consistent C#
  guide/reference/README/enumeration. No new page/nav/provider count.
  Gate: source controls/Ruff, root examples/package/strict docs execution.
  > NOTE: Delivery source controls pass 23/23 and targeted Ruff/format checks. Root
  > compiled and executed async/sync public examples at .tmp-tests/jina-public-native/;
  > isolated NuGet-only consumer also compiles/runs with zero warnings/errors
  > at package.txt. Subsequent bounded delivery review findings are closed below.
  > NOTE: Final raw-prompt witnesses are wired only to Jina. Root actual compiled
  > examples and NuGet consumer pass with zero warnings/errors at
  > .tmp-tests/jina-public-native-final/. Failed BigInteger-pattern and helper-placement
  > compile logs remain retained; final source review closes both corrections.
- [x] **JINA.5** Cold source/test/delivery review and fixes; root exact
  `.venv/Scripts/python.exe workspace.py check`, cacheprovider disabled.
  Gate: all 22 steps, shared retrieval 32/policy 29/accounting 42+2 and Frozen 102 preserved.
  > NOTE: The first operator aborted on PowerShell stderr handling. The next full run
  > exposes the canonical not-yet-live-verified marker and raw-witness compile issues;
  > all 872 native unit/93 conformance and shared profiles already pass. Marker wording
  > is restored (17 focused drift controls pass), public witnesses compile/run, and root
  > reruns the exact full gate. Both failed runs remain in .tmp-tests.
  > NOTE: Final coherent root gate passes all 22 steps in 178.4 s at
  > .tmp-tests/jina-workspace-final/ (exit-code.txt=0), including 872 native unit and
  > 93 conformance tests, all prior shared comparisons, strict docs, actual examples and
  > NuGet-only consumer. The canonical loader verifies all 106 Frozen assets unchanged.
- [x] **JINA.6** Root explicit-path source commit; clean isolated checkout actual registered
  Python/native producers + aggregate, stamped profiles/package/examples and explicit
  Frozen development. Retain raw artifacts/hashes, clean before/after; plans-only closure.
  Gate: no invented hosted/spec qualification; exact resume source recorded.

Root retains plan ownership to avoid concurrent edits. Workers report box/evidence and root
checks after actual gates. Preserve user uv.lock, v/ and .pytest_cache/v. Artifacts go only
under the epic's csharp-sdk/sdk-six-c-jina directory. Full SDK.6c remains open afterward.

## Resume

All boxes are complete at accepted source `a3b0cc785c723616d5e724f7f7b7b20f432ce647`, tree
`c76532ea37af84819ade720064a8941630608f9c`. Clean run `local-jina-a3b0cc78-20261022T203641Z` attempt 1
passes all five actual registered gates and pure aggregation with dirty=false. Retained
packet `.tmp-tests/jina-acceptance/source-a3b0cc7/` contains both inventories/verification
files, shared profile observations/reports, source-stamped packages and explicit Frozen
DEVELOPMENT 102/102. An independent read-only audit verifies raw child hashes and identity;
root also verifies all six observer stamps and the package repository commit.

The primary full22 gate is development evidence (178.4 s, 872 unit/93 conformance). Clean
acceptance runs the registered behavioral gates; it does not relabel primary logs as clean.
All106 Frozen assets and previous declarations remain unchanged. No hosted Jina verification,
new spec qualification/support declaration, public package or release is claimed.

Next executable work is parent **SDK.7a**, followed by the relevant SDK.8 prerequisites.
TEI, Voyage and Jina exhaust the standalone retrieval-only Python descriptors. Remaining
retrieval providers also expose generation/batch; keep SDK.6c unchecked for those until
those prerequisites permit complete descriptors. Generic OpenAI compatibility stays chat-only.
This is dependency ordering, not reduced parity scope. Each later binding still requires
current research and its own accepted plan. Temporary checkout registration/content were
removed after evidence retention; Windows retains its empty root directory.
