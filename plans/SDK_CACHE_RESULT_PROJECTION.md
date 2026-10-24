# Native cache result projection

**Resume from the first unchecked box.** The user's autonomous parity burn-down authorizes
this bounded correction. Read `AGENTS.md`, `DESIGN.md`, `ANYINFER_CSHARP_SDK.md`,
`SDK_FOUNDATION_ALIGNMENT.md` and this whole checklist before editing. Root owns Git,
ledger reconciliation and serialized native/full gates. Preserve other agents' changes.

## Scope and settled contract

Python `Generation.cache_mechanism` already exposes the effective mechanism selected for
the winning attempt. Native `GenerationCore` computes `CachePlan.Mechanism`, emits existing
telemetry and applies existing wire marks, but omits the value from terminal `Generation`.
Close that result projection gap without changing Python, cache planning, capability
authority, provider registration, request/event/wire shapes or manifest contents.

- Add read-only `AnyInfer.Capabilities.CacheMechanism? Generation.CacheMechanism`, with XML
  documentation describing the effective mechanism and null for no engaged mechanism.
  Reuse the existing `Explicit`/`Implicit` enum; this is not evidence of a cache hit or savings.
- Append optional `CacheMechanism? cacheMechanism = null` after `serverToolUses` in the
  public constructor. Assign it and preserve it in `Generation.WithManifest`. Existing
  positional source calls remain valid. Precompiled prerelease consumers must rebuild;
  this constructor change does not claim binary compatibility.
- At terminal construction in `Core/GenerationCore.cs`, pass the current winning attempt's
  `cachePlan.Mechanism`. Retry/fallback continues to replan; schema repair continues to reuse
  the existing marks. A failed attempt's plan must not leak into a later winning result.
- Preserve existing generated record equality/hash behavior, including collection-reference
  semantics. The new auto-property participates like other result state. Do not introduce
  whole-result structural equality, reflection-based tests or custom equality machinery.
  A public `with { }` clone is the equal/same-hash witness; separately constructed differing
  mechanisms may be unequal without claiming that test isolates only the new field.
- `AsyncStream`, `SyncStream` and the tool loop already pass terminal `Generation` through.
  Inspect those paths; do not rebuild their control flow to add this projection.
- Preserve frozen v0's ignored-cache behavior. No sealed/development corpus bytes change.
  Existing Python cache-placement controls are behavioral provenance; public native fake
  adapter controls qualify this additive projection without a new shared corpus.

Source baseline is the clean settings checkpoint
`146fbabed9e1b9fbbd90fb8242c7ea1109e333a9`. Its native context tuning is standalone;
context documents, ranking, reduction, history and request/config integration remain open.
The cache field does not close `Generation`'s separate arena/context-reduction gaps.

## Execution checklist

- [x] **CACHE.0 — Critique the bounded contract.** Inspect actual Python/native cache
  producers, result/copy paths, retry/repair and wrapper behavior, source compatibility,
  existing fake fixtures and frozen boundaries. Gate: no unresolved behavior/API decision.
  > NOTE: Accepted in Traycer `sdk-foundation-alignment/cache-result-projection-contract-review`.
  > Review required explicit existing equality semantics and actual retry/repair terminal
  > result assertions. Root retained collection-reference behavior and a clone witness;
  > no broader equality or cache-policy change was authorized.
- [ ] **CACHE.1 — Implement result state and propagation.** Own only
  `src/csharp/AnyInfer/Models.cs` and `src/csharp/AnyInfer/Core/GenerationCore.cs`.
  Implement the property/final optional argument, `WithManifest` copy and winning-plan
  projection above. Do not validate or reinterpret cache policy in the result constructor.
  After root grants the sole native slot, gate from `src/csharp/`:
  `dotnet build AnyInfer/AnyInfer.csproj --no-restore -m:1` passes with zero warnings.
  Re-read this plan immediately before ticking only this box and adding a completion note.
- [ ] **CACHE.2 — Independently control public behavior.** Own only
  `src/csharp/AnyInfer.Tests/CachePlanningTests.cs` and
  `src/csharp/AnyInfer.Tests/PublicModelTests.cs`. Extend real fake-provider public-client
  controls to retain and assert terminal results as well as existing events/wire marks:
  null/off/undeclared/no-placement remain null; engaged explicit is `Explicit`; explicit
  degraded to implicit is `Implicit`. Cover manifest capture on/off, async and sync stream
  collection/results, retry and schema repair. Add a differing-mechanism fallback witness
  (failed explicit target, successful implicit target) so the terminal value proves winning
  attempt selection. Preserve existing retry/repair counts/marks; assert their terminal
  `Explicit` value directly. Frozen client ignores policy and reports null. Public model
  controls cover constructor default, supplied enum and `with { }` clone preservation,
  equality and same hash without claiming structural collection equality.
  Gate, after root releases the native slot, from `src/csharp/`:
  `dotnet test AnyInfer.Tests/AnyInfer.Tests.csproj --no-restore -m:1 --filter "FullyQualifiedName~CachePlanningTests|FullyQualifiedName~PublicModelTests"`
  passes with zero warnings. No sleeps, private hooks, new dependencies or full suites.
  Re-read the plan before a minimal tick/note; serialize that edit with CACHE.1's owner.
- [ ] **CACHE.3 — Describe and consume the public field.** Own only
  `docs/reference/csharp-sdk.md` and `scripts/check_csharp_package.py`.
  Describe effective enum/null behavior and its distinction from provider-reported cache
  read/write usage. Extend the isolated package consumer with an actual constructor/property
  and clone witness; retain the existing fake-provider flows and exact examples. Avoid a
  new unexecuted documentation code block. Gate: focused Markdown link check and Python
  Ruff/compile checks pass; root's final package gate compiles/runs the exact consumer.
  Root marks this box only after that package execution, so no plan writer conflicts occur.
- [ ] **CACHE.4 — Reconcile scoped evidence.** Root updates only the `Generation` evidence
  row in `CSHARP_SDK_API_PARITY.md`: add the reflected public property and actual cache tests,
  remove the absent-cache-field claim, retain partial status for arena/context-reduction.
  Gate: fresh `check_sdk_api_parity.py` passes against real metadata and all 235 original
  completion marks remain untouched. Expected status totals remain 171 implemented,
  26 partial, 37 deferred and one different; no provider membership changes.
- [ ] **CACHE.5 — Review, qualify, commit and continue.** Independently review changed
  source/tests/docs/package/evidence. Root runs one serialized full workspace gate using
  a fresh cache to avoid this checkout's known root `.pytest_cache` ACL:
  set `PYTEST_ADDOPTS` to include
  `-o cache_dir=D:/projects/AnyInfer/.tmp-tests/pytest-cache/cache-result-full`, then run
  `.\workspace.cmd check`. Gate: all 27 steps, package-only consumer, exact examples,
  six prior paired profiles and explicit
  `.\.venv\Scripts\python.exe scripts/freeze_release.py --verify core-generation-v0` pass;
  commit explicit paths, then qualify the exact clean source with
  `.\workspace.cmd check --only csharp` and inspect clean source/corpus provenance.
  Root records exact checkpoint/failed attempts and reconciles parent/index before retiring
  this leaf. Continue SDK.9a context document/representation, ranking/deduplication,
  selection/packing and history work; SDK.6c/8–12 and release/publication gates remain open.

## Resume

Resume at CACHE.1 on the source baseline above. No implementation is present yet. Source,
controls and docs/package briefs have disjoint owners; shared plan ticks and every native
build are serialized by root. The accepted artifact contract is supporting review evidence;
the settled behavior and executable gates are written here so implementation does not
depend on reconstructing chat history.
