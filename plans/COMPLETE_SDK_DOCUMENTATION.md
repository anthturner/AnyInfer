# Complete the multi-SDK documentation

**Resume from the first unchecked box. Read this whole file, `AGENTS.md`, and
`DESIGN.md` first.** Each phase ends in a test gate. Record departures beside the
affected box as `> NOTE:` entries and reconcile this checklist after every work wave.

Status: **in progress**. A later 2026-10-25 request authorized implementing this plan on
`feature/language-neutral-foundation` (committing and pushing to that branch) and adapting the
site to the user-supplied brand kit v2. Publication (R6.B) remains separately unauthorized.

## Starting point and settled decisions

The MkDocs-to-Docusaurus port, visual polish, and initial C# documentation pass are
implemented. The completed plans `MIGRATE_DOCS.md`, `POLISH_DOCS_DESIGN.md`, and
`UPDATE_CSHARP_DOCS.md` are retired; the original migration design is recoverable in
Git at `2520b7596d622974430a54af587a8b973298109f:plans/MIGRATE_DOCS.md`.
Their outstanding documentation and publication obligations are retained here.

Current implementation:

- Author prose in the existing `docs/` tree. `website/navigation.json` supplies the
  curated navigation; `scripts/docs_common.py` supplies page/SDK/route metadata.
- `scripts/prepare_docs.py::prepare()` stages content under
  `website/.generated/{shared,python,csharp}/`; it prepares `docs/index.md` separately
  as `home.mdx`. Keep one authored source per page and preserve existing source paths.
- `scripts/generate_python_reference.py::render_symbol()` expands the existing Python
  `:::` markers with Griffe. C# currently has an authored semantic reference at
  `docs/reference/csharp-sdk.md`; it has no generated API reference or complete native
  documentation-coverage gate yet.
- `scripts/build_docs.py` owns build/prepare/preview. Production output is root `site/`.
  `scripts/export_docs.py` adds redirects, SDK/version metadata, and agent exports;
  Pagefind indexes the final HTML; `scripts/check_docs_site.py` validates it.
- Shared docs use `/`, Python uses `/python/`, and C# uses `/csharp/`. Preserve
  `/csharp/reference/` for authored semantics and use `/csharp/api/` for generated API.
  Historical aliases and fragments in `tests/fixtures/docs_migration/legacy.json`
  remain supported. Do not replace that fixture with a new baseline to mask failures.
- Python remains the supported published SDK. C# is an independent native .NET 8
  prerelease, currently locally packaged as `0.1.0-proof`, without a runtime Python
  dependency. It is not published to NuGet and does not claim full parity. Read versions
  from package metadata rather than adding another authored version constant.
- Keep GitHub Pages, `anyinfer.dev`, static local search, the supplied brand assets,
  explicit light/dark modes, and the current responsive layouts. No paid service,
  application server, or second DocFX website is needed.
- Independent SDK versions remain the model. Do not invent historical releases or
  create empty production archives. A future language gets a separate SDK registration,
  not a translation locale; this plan does not select another language.
- Generated C# reference remains the selected direction. Use pinned, repository-local
  DocFX metadata extraction, initially its Markdown output, then integrate that content
  into Docusaurus. Do not substitute a hand-maintained symbol table for full coverage.
- Native runtime/provider/configuration semantics are outside this plan. Add source
  comments and build-only extraction/coverage tools where needed, not inference policy.
  Never widen frozen specification releases or mark parity milestones from doc coverage.

This is a documentation leaf of [the C# SDK parent](ANYINFER_CSHARP_SDK.md), especially
SDK.12a. That parent also includes implementation/qualification work. Do not check
SDK.12a, SDK.12b, SDK.12c, or API-parity rows merely because the current prerelease is
well documented. Unsupported journeys must be identified honestly; a documentation
plan cannot implement them by describing them.

## Completion means

1. Every documented, supported C# integration journey has an accessible recipe with
   executable native source and offline assertions. Python-only journeys say so.
2. The entire intended public native library surface has generated signatures,
   meaningful source documentation, cross-links, and coverage evidence, including
   individual overloads/constructors/operators. A class-name list is insufficient.
3. Every published authored page has been reviewed for language-specific assumptions;
   package/provider/platform/support claims agree with executable evidence.
4. Generated content participates in navigation, local search, SDK/version selection,
   agent exports, preview, CI, and Pages without breaking existing routes or layout.
5. Publication and recovery are separately recorded once the authorized branch process
   reaches the public site. Local implementation or a feature-branch push is not cutover.

## Execution checklist

### R0 — Inventory the work against the current native SDK

- [x] **R0.A — Capture scope and classify every page.** Re-read the current C# source,
  `docs/concepts/foundation.md`, `docs/reference/csharp-sdk.md`, the C# parent plan,
  `plans/SDK_FOUNDATION_ALIGNMENT.md`, and `plans/SDK_CONTEXT_PRIMITIVES.md`.
  Enumerate the actual pages from `website/navigation.json` and
  `scripts/docs_common.py::build_pages()`. Produce a review inventory at
  `maintenance/documentation/page-coverage.json` with one row per authored published
  source: source path, `shared|python|csharp|mixed` content scope, evidence/example
  paths, review status, and any unsupported native journey. Record repository-only
  indexes and root README separately. This is a coverage/review ledger, not another
  router: continue deriving route/SDK/version values from the existing manifest.
  Add `tests/test_documentation_coverage.py` to reject missing, duplicate, stale, or
  unreviewed rows and missing cited evidence. List exact exclusions with reasons.
  Do not turn a keyword search or the 235-row Python parity ledger into proof of native
  documentation completeness. **Test gate:** the inventory matches the actual source
  set; coverage controls demonstrate missing/stale rows fail; existing docs tests pass.
  > NOTE: Ledger checked by `scripts/check_documentation_coverage.py` (used by
  > `tests/test_documentation_coverage.py`). "Stale" means a row for a source the site no
  > longer publishes; evidence must exist and must cite every `--8<--` include of the page.
  > Rows start `review: "pending"`; `require_reviewed` stays `false` until R6.A flips it (or
  > run the script with `--require-reviewed`). Repository-only entrypoints and exclusions
  > (AGENTS.md, CLAUDE.md, Copilot shim, DESIGN.md, plans/, tests/fixtures/) are listed with
  > reasons. Classification found 84 python, 17 mixed, 4 shared, 4 csharp pages.

- [x] **R0.B — Prove and pin the extraction toolchain.** Inspect
  `src/csharp/global.json`, `Directory.Build.props`, and `AnyInfer/AnyInfer.csproj`.
  Carry forward DocFX **2.81.0 as the initial candidate**, not a claim of installed or
  verified compatibility. Verify that exact package/version and .NET 8 compatibility
  against the official package/release and a local representative extraction. If it
  cannot be restored or rendered correctly, select an explicitly verified exact pin
  and record the reason/evidence here; never silently use `latest`.
  Put the local tool manifest at **`.config/dotnet-tools.json`**, so invocation from
  `src/csharp/` finds it while honoring the repository SDK pin. Put metadata settings
  in `website/docfx.json`, targeting only `src/csharp/AnyInfer/AnyInfer.csproj`, not
  `AnyInfer.sln` or test/probe/example/observer projects. Prefer `outputFormat: markdown`;
  if Markdown cannot retain required UIDs or signatures, record a bounded fallback to
  managed-reference metadata plus a deterministic renderer, retaining DocFX extraction.
  Stage raw output/cache under `website/.cache/csharp-reference/`, outside `.generated/`
  because preparation replaces/removes stale staged files. Exercise generic/nested
  types, nullable/ref parameters, async streams, overloads, records, XML `cref` links,
  and a long signature before selecting the renderer. Example commands, run from
  `src/csharp/` after the manifest exists: `dotnet tool restore --tool-manifest
  ../../.config/dotnet-tools.json` and `dotnet tool run docfx -- metadata
  ../../website/docfx.json`. Restore is an explicit setup step; normal builds must not
  download an unpinned executable. **Test gate:** the pinned tool extracts only the
  intended assembly with all representative constructs and a repeatable UID inventory.
  > NOTE: DocFX 2.81.0 verified: the package ships a net8.0 tool build; it restores and runs
  > under SDK 8.0.425 and extracts only `AnyInfer.csproj` (255 managed-reference items),
  > byte-identically across repeated runs. Markdown output does not retain canonical XML
  > documentation IDs (anchors become lossy underscore forms), so the bounded fallback is
  > used: `outputFormat: mref` YAML plus the deterministic Python renderer, still extracted by
  > DocFX. That adds build-only `PyYAML==6.0.3` (hash-locked in `website/requirements.lock`
  > and the `dev` extra). `disableGitFeatures: false` supplies repository-relative source
  > paths and lines; the branch-specific `source.remote` block is ignored. The representative
  > fixture is `tests/fixtures/csharp-reference/ReferenceFixture/` (generic and nested types,
  > ref/out/in/params, async streams, overloads, records, operators and conversions, crefs,
  > a long signature, obsolete members, `inheritdoc`, and two deliberate documentation gaps).

### R1 — Make native API documentation coverage measurable

- [x] **R1.A — Add a complete documentation symbol inventory.** Reuse the existing
  assembly boundary in `src/csharp/AnyInfer.Maintenance/PublicApi.cs`: it scans
  `typeof(AnyInfer.AsyncClient).Assembly.GetExportedTypes()` with `DeclaredOnly`.
  Its existing `--public-api --output PATH` projection collapses overloads to names
  and omits constructors/operators; it is useful corroboration, not full doc coverage.
  Preserve that command and its parity consumers unchanged. Add a separate
  `DocumentationInventory.cs` and `--documentation-api --output PATH` branch in the
  maintenance program, or an equally explicit independent Roslyn inventory, emitting
  canonical XML documentation IDs with signatures. Cover exported types, applicable
  public/protected declared members, constructors, overloads, generic arity, properties,
  indexers, fields/enum values, events, and operators/conversions. Resolve inherited and
  compiler-generated record members deliberately; document a narrow, reasoned exclusion
  policy and test it. An undocumented API must not disappear via a broad filter.
  Add native tests/fixtures for these cases and `scripts/check_csharp_docs.py` plus
  `tests/test_csharp_reference.py` for inventory-to-generated-output coverage. Keep
  this checker independent of the Python-equivalence evidence ledger.
  **Test gate:** a missing constructor/overload/member and a broken UID mapping each
  fail a negative control; the real assembly has zero unexplained coverage omissions.
  > NOTE: `DocumentationInventory.cs` reflects over the built assembly; its IDs match the
  > compiler's XML documentation IDs on every fixture member, including nested constructed
  > generics. Exclusions: accessors, enum `value__`, runtime delegate members, static
  > constructors, members unreachable through sealed or non-public types, and compiler
  > synthesized record members (value equality, `ToString`/`PrintMembers`, `Deconstruct`,
  > copy constructor, `EqualityContract`, `<Clone>$`); a declared record member is kept.
  > Implicit constructors are deliberately kept, so a type must declare and document them.
  > The inventory found what CS1591 never reports: undocumented positional record parameters
  > and implicit constructors. Native tests: `AnyInfer.Tests/DocumentationInventoryTests.cs`.

- [ ] **R1.B — Complete XML comments and retain the package boundary.** Enable
  `GenerateDocumentationFile` for `src/csharp/AnyInfer/AnyInfer.csproj` only. Author
  meaningful summaries, parameter/return/exception documentation, lifetime/cancellation
  semantics, and supported limits for the real public native API. Work in disjoint
  namespace batches: clients/streams/events/types; config/credentials/connections;
  catalog/capabilities/providers; schema/tools; accounting/policies/manifests; then only
  context surfaces that current implementation evidence supports. Respect
  `TreatWarningsAsErrors`; do not globally suppress CS1591 or downgrade compiler
  warnings to get a green build. A temporary extraction-only diagnostic relaxation
  during inventory discovery is not an accepted final gate. Expand coverage rules to
  catch empty/placeholder summaries, stale `cref`, and user-facing internal decision
  identifiers. Verify XML documentation is present in the intended library package,
  while DocFX, its assemblies/config/cache and rendered site remain build-only.
  **Test gate:** native build, documentation coverage, targeted namespace tests and
  package-content/consumer checks pass with no unexplained missing-doc diagnostics.

### R2 — Render and integrate the complete C# reference

- [ ] **R2.A — Build the reference adapter.** Add
  `scripts/generate_csharp_reference.py` with a structured result containing generated
  pages, original source paths, and canonical symbol-to-URL/fragment maps. Do not feed
  C# names through the Python `render_symbol()` function. Keep the authored semantic
  guide at `docs/reference/csharp-sdk.md` and link it to the generated index.
  Generate `/csharp/api/` plus one type page per stable type UID under
  `/csharp/api/<type-slug>/`. Define/test one deterministic readable slug function:
  fully qualified names, explicit generic arity, nested-type normalization, and a hard
  collision error. Derive overload-specific anchors from canonical signature IDs
  (for example `member-` plus the first 16 SHA-256 hex digits); keep the map authoritative
  and fail collisions. Render readable C# signatures, type parameters, inheritance,
  interfaces, summaries/remarks, parameters/returns/exceptions, examples and obsolete
  status. Convert DocFX `xref`/XML links into native site links or deliberate external
  framework links; unresolved `AnyInfer` UIDs are errors. Preserve full signatures while
  containing horizontal scrolling; do not leak workstation paths into source links.
  **Test gate:** fixture and real extraction/render tests, including escaping/generics,
  overload anchors, XML links, collisions and independent R1 coverage, pass.

- [ ] **R2.B — Integrate staging, preview, exports and publication builds.** Extend
  `scripts/prepare_docs.py::prepare()` and `scripts/docs_common.py` to merge generated
  C# pages with authored pages, accounting for them in the manifest and stale-file
  cleanup. Generated pages belong to the `csharp` docs plugin and its independent
  version; they need native source links rather than misleading Markdown edit URLs.
  Update `website/plugins/sidebars.ts`, `website/navigation.json`,
  `website/docusaurus.config.ts` and the authored reference index without duplicating
  API lists manually. Update `scripts/build_docs.py` to extract native content before
  Docusaurus, one native build at a time. Cache by native source/comments, project/props,
  SDK/tool pins and generator/filter configuration; invalidate each input correctly.
  Extend preview watching to native `.cs`, `.csproj`, relevant props, `global.json`,
  tool manifest and `website/docfx.json`, ignoring `bin/obj/.cache/.generated` loops.
  Preserve incremental writes and Windows directory-watcher behavior.
  Extend `scripts/export_docs.py`, `scripts/check_docs_site.py` and their tests so
  generated native pages are reachable, indexed with C# version/status, included in
  real article-only `llms.txt`/full/section outputs, and checked for links/fragments.
  Keep the existing **800,000-byte section budget**: split native export sections
  deterministically if needed instead of truncating API content or silently raising it.
  Add .NET setup/tool restore before docs generation in `.github/workflows/ci.yml` and
  `docs-site.yml`; keep Node/Python pins and existing Pages artifact/concurrency/domain
  safeguards. Add the checker to `workspace.py` and cover its ordering in
  `tests/test_workspace.py`. **Test gate:** strict production build plus cold/warm
  generation, source-change preview, static artifact, search/export and negative tests
  all pass; generated type pages appear in C# navigation and Pagefind results.

### R3 — Complete the C# learning path and executable recipes

- [ ] **R3.A — Finish native installation and first call.** Add focused authored
  `docs/guides/csharp-installation.md` and `docs/guides/csharp-quickstart.md`, register
  exact `/csharp/installation/` and `/csharp/quickstart/` routes in the existing metadata
  system, and add them to C# navigation. Preserve `/csharp/` as the SDK overview and
  all current entrypoint/legacy links. Teach .NET/SDK prerequisites, source-checkout
  project references and the current local-package option only as actually verified.
  Distinguish core `AnyInfer` exports from `AnyInfer.Examples` helper source.
  Include a complete first buffered call, cancellation, async/sync disposal and a
  credential-free offline path. Do not invent `dotnet add package AnyInfer` on public
  NuGet. Add/update canonical examples under `examples/csharp-sdk/` and assert them
  in its existing `Program.cs` runner; documentation includes that source rather than
  a second handwritten C# copy. Link the new path from home, indexes, Downloads,
  Python quickstart and migration map, preserving prior Python tab/fragment behavior.
  **Test gate:** a fresh temporary consumer follows the written steps, all new source
  examples run offline, snippet/link checks and desktop/mobile entrypoint tests pass.

- [ ] **R3.B — Complete the core task guides.** Audit and extend existing shared
  `docs/guides/{streaming,structured-output,fallback,tool-loop}.md`, plus
  `docs/guides/{csharp-sdk,python-to-csharp}.md`, with equivalent task-oriented native
  instructions where implemented. Cover buffered/streamed results and error/early-exit
  paths, schema/deserialization and native limits, route/default/failure/attempt handling,
  and registered tool handlers/delegate/cancellation/round-budget semantics. Reuse
  `GenerationExample`, `SyncGenerationExample`, `StreamingExample`,
  `SyncStreamingExample`, `StructuredOutputExample`, `RoutingExample` and
  `ToolLoopExample`; add narrowly named source examples only for missing journeys.
  Provide actual C# follow-on recipes, not just a C# tab followed by Python-only advice.
  Keep unsupported Pydantic/MCP/Python decorator behavior explicitly Python-specific.
  **Test gate:** every added recipe compiles and executes an asserted offline path,
  including representative failure/cancellation, and the language tabs/links render.

- [ ] **R3.C — Complete retrieval, configuration and operational SDK recipes.** Add
  native recipes for rich requests, embedding/reranking, configuration/credentials/TLS,
  pure metadata vs discovery/health/probes, observers/manifests, explicit pricing/budgets,
  ledger ownership, and request policies to the relevant existing guides or C# pages.
  Use the existing `RichGenerationExample`, `RetrievalExample`, `TeiExample`,
  `JinaExample`, `ConfigurationExample`, `ConnectionExample`, `CatalogExample`,
  `LifecycleExample`, `ProbeExample`, `SetupExample`, `TelemetryExample`,
  `ManifestExample`, `AccountingExample`, and `RequestPolicyExample` as canonical source.
  Check actual registrations before selecting a target; inert preset data is not an
  implemented binding. Preserve unknown cost/usage and bounded accounting semantics,
  native schema/TLS differences, caller-owned resource rules, and live-vs-offline
  evidence distinctions. Do not teach unimplemented local supervision, sessions,
  reduction/history pipelines, batch jobs, OpenTelemetry, keyring or MCP as native C#.
  **Test gate:** exact snippets run offline with substantive assertions; configuration
  and connection examples retain their documented no-network/inert boundaries.

- [ ] **R3.D — Add a coherent native cookbook.** Add source-linked, complete programs
  and authored pages at `docs/examples/csharp-{generation,streaming,tools,retrieval,
  observability,policies}.md`, using `/csharp/examples/<topic>/` routes. Combine the
  existing verified primitives into realistic native journeys without reimplementing
  orchestration in samples. Extend `examples/csharp-sdk/Program.cs` (or a dedicated
  nonpackable runner under that directory) so every published program is selected and
  asserted offline. Keep hosted setup optional and accurately labeled; no credentials
  are required by CI. Add `tests/test_csharp_docs_examples.py` to check that authored
  C# examples use canonical executable source and that every declared recipe has a
  runner case; distinguish generated API signatures from runnable code examples.
  Update `docs/examples/README.md` to present both cookbooks. Mark each page complete
  in the R0 ledger only after its recipe has executed. **Test gate:** full native
  example runner and independent snippet-to-runner controls pass; no orphan recipe or
  duplicate authored C# code is accepted.

### R4 — Review every remaining page for language scope and accuracy

- [ ] **R4.A — Review concepts and reference semantics.** Work through every R0 row,
  including `docs/concepts/{foundation,targets,events,routing,structured-output,
  capabilities,multimodal-inputs,embeddings,credentials,telemetry,run-manifests,
  budgeting,cost,context-reduction,local,sessions}.md` and
  `docs/reference/{README,configuration,errors,conformance-matrix,csharp-sdk}.md`.
  Keep shared behavioral explanations language-neutral where true; identify Python
  implementation APIs/examples and native exceptions where they differ. Add useful
  native examples/cross-links for supported behavior instead of repeating disclaimers.
  Keep Python error/conformance inventories labeled and derive native inventories from
  the new API generator. Inspect context source/evidence at execution time: standalone
  primitives/settings must not be described as request-path reducers or qualified parity.
  Preserve every existing route/fragment when a heading changes. **Test gate:** all
  concept/reference rows are reviewed with source evidence, mirrored claims agree,
  legacy anchors pass, and an independent claim review has no unresolved findings.

- [ ] **R4.B — Review all other public and contributor surfaces.** Complete the R0
  inventory across root `README.md`, `docs/{index,README,why-anyinfer}.md`, all remaining
  guides/examples/providers/sidecar pages, contributor setup/releasing/testing/architecture,
  `src/csharp/README.md`, and homepage/navbar/footer/search/404 components under
  `website/src/`. Scope provider/platform/package counts and guarantees to the SDK they
  actually describe; link canonical inventories instead of duplicating counts.
  Reconcile outward agent integration text through `docs/agents/INTEGRATION.md` and
  existing generators/shims, not independently authored instruction copies. Inspect
  final `llms` exports for correct languages, versions, substantive native API content,
  and the absence of internal decision identifiers. Keep runtime-specific Python
  sidecar/operator instructions useful rather than forcing fictitious C# counterparts.
  **Test gate:** all published/authored rows and repository-only entrypoints are reviewed;
  generated-index, agent/shim, example, link and source-documentation gates pass.

### R5 — Make independent SDK versioning operational

- [ ] **R5.A — Implement the real snapshot workflow without inventing history.**
  Extend `scripts/build_docs.py` with `snapshot --sdk python|csharp --version VERSION`,
  validating the actual outgoing SDK metadata and fully prepared reference/symbol maps
  before invoking the corresponding Docusaurus docs-plugin snapshot. Use SDK-prefixed
  `python_versions.json` / `csharp_versions.json`, versioned docs and sidebars; shared
  docs remain unversioned. Archive native generated API bodies with their source/version
  maps, not markers that regenerate old APIs from today's assembly. Verify one SDK's
  snapshot leaves the other's versions/routes unchanged and search/export metadata
  remains correct. Test with isolated fixture versions, never fake public release history.
  Update contributor/releasing guidance with the exact outgoing-version procedure.
  Do not create production snapshots until an actual SDK release calls for them.
  **Test gate:** independent snapshot/restore fixtures, archived links, version selector,
  generated-reference identity, local search and section exports pass for each SDK.

### R6 — Final acceptance, public cutover and recovery

- [ ] **R6.A — Verify the exact completed artifact and reconcile scope.** Re-read this
  plan and the coverage ledger; require zero unreviewed sources, zero unexplained
  native public-symbol omissions and zero unexecuted supported recipes. Run
  `.venv/Scripts/python.exe workspace.py check`, `npm --prefix website run typecheck`,
  focused native-reference/example controls and production browser acceptance, one
  heavy operation at a time. Re-run the exact compiled C# examples using
  `dotnet run --project ../../examples/csharp-sdk/AnyInfer.Examples.csproj
  --configuration Release` from `src/csharp/`. Browser tests use the already-built
  static artifact on loopback and cover both SDK first-call paths, generated overload
  links, shared concepts, legacy fragments, scoped local search, independent versions,
  full-height mobile drawers and long code/tables at 320/390/768/1024/1440 widths in
  both themes. Add browser acceptance to the Pages build as well as CI so the uploaded
  artifact is the tested one. Preserve branding and keyboard/screen-reader behavior.
  Record exact revision/tree and artifact receipt, source-qualified limitations and
  any unrelated full-gate failure rather than declaring the entire suite green.
  **Test gate:** documentation-specific gates and artifact/browser acceptance all pass;
  full-gate outcomes and independent content/coverage review are explicitly recorded.

- [ ] **R6.B — Publish through the existing branch process and prove recovery.** This
  carries forward the migration's unexecuted publication/recovery work. When separately
  authorized, use `feature/* -> develop -> main` and the existing Pages workflow;
  a push to the feature branch alone is not publication. Before cutover, record a
  recoverable last-good deployment/artifact and source revision. If an old artifact has
  expired, retain/rebuild its exact source with locked tools in isolation and rehearse
  serving it locally. Preserve domain/DNS, artifact naming, cleanup and concurrency
  safeguards. After deployment, smoke `https://anyinfer.dev/`: homepage, Downloads,
  one shared concept, Python/C# entry and generated reference, a legacy URL+fragment,
  scoped local search, version links, `llms.txt`, and a native section bundle. Roll back
  by redeploying the recorded artifact or a reviewed revert plus normal Pages rebuild,
  never by resetting unrelated SDK work or rewriting Git history. **Test gate:** public
  smoke succeeds and the recovery record names a concrete deployable artifact/revision
  with the tested restoration procedure.

- [ ] **R6.C — Reconcile parent plans and retire this leaf.** Record which documentation
  outcomes are complete in `plans/README.md` and the C# parent's SDK.12a notes. Close
  that parent only if its full supported-journey/parity prerequisites are also satisfied;
  leave implementation/platform/release qualification open otherwise. Rewrite durable
  authoring/build/release guidance into contributor docs in its own terms; no `docs/`
  page should link here. Remove this plan only after its actual acceptance/publication
  work is complete or its remaining boxes are explicitly handed to another active plan.
  **Test gate:** no unfinished box is lost, no durable plan link remains, and all plan
  links resolve after retirement.

## Coordination and validation rules

Coordinator owns tool/version choices, manifest/routing integration, shared locks/config,
final gates, Git, and checklist reconciliation. Delegate read-only inventories and
well-specified namespace/recipe batches. Assign disjoint files; workers preserve others'
changes and never touch Git. Serialize native builds, generation and full suites. A worker
ticks only its assigned boxes after re-reading this file and records deviations in place.

Avoid changing source paths just for neatness. Add the minimum SDK registration/routing
hooks needed for new native pages; do not build a speculative fourth-language generator.
Extend tests at actual failure boundaries (coverage, snippet execution, xrefs, metadata,
layout), not assertions that merely mirror implementation strings.

When stopping partway, record the first unfinished box, exact commit/tree and remaining
failure here. Initial resume point is **R0.A**. No unchecked phase has been implemented
by the request that created this plan.

## Primary tool references

The following official references support the extraction design; verify the selected
binary in R0.B rather than assuming a live documentation page proves a particular pin:

- [DocFX metadata configuration](https://dotnet.github.io/docfx/reference/docfx-json-reference.html#metadata)
  describes project selection and `mref`, `apiPage`, and Markdown output formats.
- [DocFX .NET API extraction](https://dotnet.github.io/docfx/docs/dotnet-api-docs.html)
  covers source-project and assembly/XML extraction.
- [Docusaurus independent docs instances](https://docusaurus.io/docs/docs-multi-instance)
  and [versioning](https://docusaurus.io/docs/versioning) describe the SDK archive model.
- [Pagefind filters](https://pagefind.app/docs/filtering/) describe the static SDK/version
  filtering already used by this site.
