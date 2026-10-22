# Provider change propagation plan

> Resume from the first unchecked box. The user authorized both TEI and provider-change
> propagation implementations on 2026-10-22: implement both, in parallel where possible.
> Implementation and focused independent reviews are accepted through P6.2. Resume at P6.3
> for the full repository gate, source commit and isolated clean-source replay.

**Status:** implementation authorized; focused lanes accepted as noted below, integration open.
**Baseline (historical plan source):** `acdc94469f86eca0a67f9226fbc2c7ae6a7e7bf8`.
**Current source HEAD:** `acdc94469f86eca0a67f9226fbc2c7ae6a7e7bf8`.
**Scope:** connect upstream provider drift review to coordinated changes across the shared
language-neutral specification and registered language implementations.

## Settled decisions

- Treat `specification/` as the normative basis for cross-language behavior. A detected
  provider change does not automatically become a shared requirement or a new capability.
- Add one tool-neutral canonical procedure at `contracts/PROPAGATE-CHANGE.md`, linking
  drift detection to the existing immutable release and compatibility rules in
  `specification/MAINTENANCE.md`. Link both `contracts/DRIFT-CHECK.md` and
  `contracts/NEW-PROVIDER.md` to it; keep skills and prompts as pointers.
- `specification/MAINTENANCE.md` is itself hashed by sealed `core-generation-v0`. Do not
  edit it or any other frozen release asset. A shared behavior change requires a new
  candidate profile/release/cases and independent review. A wire-only translation that
  preserves normalized behavior updates contracts, affected adapters, and tests with an
  explicit rationale that there is no shared-spec delta.
- Persist each reviewed change as an immutable input declaration at
  `maintenance/changes/<id>.json`, validated by `maintenance/change.schema.json`. It records
  real source URLs, fetch dates and version pins; provider/operation deltas; adopted versus
  informational disposition; shared-spec impact; candidate paths/release IDs when applicable;
  and per-implementation declared status, rationale, owned paths and required gate IDs. It
  contains no execution result, output/log hash, or claimed verification completion. The
  runner hashes these raw input bytes and the registry; it never rewrites either input.
- Actual outcomes live only in versioned inventory, verification and run-report artifacts
  under ignored `.tmp-tests/provider-change/<id>/<run-id>/` and matching CI artifacts. Add
  `maintenance/run-report.schema.json`: the report references input and child artifact hashes,
  while children bind to input/registry and run/source identity; no reciprocal hashing or
  committed current-head run evidence. Downstream validation derives completion from these
  artifacts, never from declaration status text. Qualified candidate A/B evidence remains
  governed by `specification/MAINTENANCE.md`, separate from transient maintenance evidence.
- An `unsupported` implementation status must correspond to an actually absent binding,
  not merely a declarative label. `unaffected` requires reviewed rationale. Validation can
  check structure and inventory consistency, but cannot decide whether prose is semantically
  correct. Shared-core impact runs the applicable implementation/profile gates even if a
  provider binding is absent.
- Maintain implementation registration in `maintenance/implementations.json` and its
  schema, outside the frozen specification. Registration carries ID, language, root,
  exporter/verifier argv and gate IDs, and only profile claims actually declared by that
  implementation. Add versioned `maintenance/binding-inventory.schema.json` and
  `maintenance/verification.schema.json`; both are version 1. Add version 1
  `maintenance/run-report.schema.json` for aggregation. Inventory and verification artifacts
  carry `schema_version`, `implementation_id`, trusted PR head identity, actual evaluated
  source commit/tree (full commit, dirty flag, and controlled source-input fingerprint),
  registry SHA-256, raw change-input SHA-256, workflow-run identity and producer identity.
  Inventory carries declarations; verification carries required gate IDs, status, exit code,
  and output/log hashes. The run report references the raw input and child artifact hashes,
  without a cycle.
  Provider/operation inventories come from side-effect-free language exporters, not a second
  hand-maintained binding list. These inventories prove declared descriptors/bindings only;
  they do not prove factories or runtime protocols work. Independent qualifying tests/public
  calls provide that evidence; metadata alone never establishes provider support or release
  support. Exporters must not use credentials, factories, network,
  discovery, or load models. Python entrypoint: `scripts/export_python_provider_bindings.py`.
  C# exporter: isolated, non-packable
  `src/csharp/AnyInfer.Maintenance/{AnyInfer.Maintenance.csproj,Program.cs}`, based on
  public registry metadata. A new language adds registration, exporter, and verifier; generic
  planning code must not acquire Python/C# branches. A descriptor or report alone does not
  establish support or release readiness. A shared asset consumed by both languages may have
  no C# source diff; record the shared changed path and each consumer's verification rather
  than duplicating files or making gratuitous per-language edits.
- Every exported provider/operation declaration also names dependency snapshot paths using
  stable repository-relative contract IDs. This includes inherited base dialects and
  provider/preset snapshots. Exporters derive dependencies from actual registration and
  adapter composition through a bounded checked mapping; add no public SDK fields and no
  duplicate operation inventory. Generic planning expands changed contract paths through
  dependency closure before membership/status checks. Missing dependency mapping rejects or
  blocks; it can never silently mark a binding unaffected. Whole-snapshot matching is the
  conservative default; section hints cannot narrow closure without explicit reviewed scope.
  Non-inference snapshots (MCP, Hugging Face) receive an explicit out-of-binding-scope or
  blocked disposition, never fabricated inference operations or silent omission.
- `scripts/check_provider_change.py` is pure validation/planning: it consumes the immutable
  change declaration plus independently supplied expected CI/source context and versioned
  inventory, verification and run-report artifacts. It never executes commands. It checks
  schemas, IDs/references, artifact provenance/freshness against current PR head, evaluated
  checkout commit/tree, run, raw input and registry, inventory
  membership, dependency closure, contradictory statuses, changed-path coverage and
  verification completeness. Completeness means process/evidence coverage, not semantic
  proof inferred from metadata or rationale prose. Reject self-claimed/stale evidence.
  Dirty preparation evidence is unqualified; a candidate reference requires clean committed
  source under existing rules.
- `scripts/run_provider_change_checks.py` is the sole controlled dispatcher. It executes
  only argv and gate IDs from `maintenance/implementations.json`, against validated local
  roots/platform; it accepts no executable command from a change record. The record is an
  immutable declaration only: the runner hashes its raw bytes and registry, never modifies
  them, and writes outcomes only to ignored `.tmp-tests/provider-change/<id>/<run-id>/` plus
  CI artifacts. It collects trusted PR head identity separately from actual evaluated
  checkout commit/tree, and binds versioned inventory/verification/report artifacts to both,
  the run, input and registry. Keep this execution separate from pure validation. Do not add
  an expected-answer/policy calculator, price logic, broad normalizer, or silent hash changes.
- Keep deterministic drift selection and reachability stages. Extend the proposal stage to
  follow the canonical procedure and create one coordinated **draft** PR against `develop`
  containing the snapshot, adopted candidate basis when needed, affected language changes
  and tests, and structured impact record. Preserve the existing authenticated CI action,
  backend and secrets; introduce no new model/backend/credentials or costly model escalation.
  Never auto-merge. Incomplete/failed work remains draft or blocked and cannot be reported as
  complete. Do not open a PR when there is no adopted or otherwise meaningful change.
- New capability, unverifiable sources, and blocked implementation work receive truthful
  dispositions. A new upstream capability is not auto-adopted. Unsupported existing
  bindings remain explicit pending gaps; do not require a new port in every PR.
- Candidate lifecycle is explicit: `draft_prepared` may write proposed normative/schema/input
  assets only at new paths and an unqualified preparation record under `maintenance/`; it
  must not generate a qualified release manifest or reference expectations. Only a separate
  `qualified_candidate` path may generate candidate evidence, following the exact sequence
  in `specification/MAINTENANCE.md`: commit implementation, driver, normative text and inputs
  cleanly at A; produce real clean reference/environment evidence; generate candidate
  manifest/assets at B; run the complete Python corpus and every claiming native report with
  zero failures; obtain independent review. No automatic sealing/tag/publication, no changes
  to old hashed assets, and dirty proposal edits cannot satisfy the sequence. Incomplete
  work remains draft/blocked. Proposal and declaration status never self-claims qualification
  or completion; downstream aggregation derives these from the required same-run artifacts.
- The proposal path cannot weaken its own control-plane validators, workflow, registry, or
  sealed-asset safeguards to pass. Registered source/shared-candidate paths and records are
  allowed; changes that require new workflow/validator/registry policy become blocked
  follow-up review rather than self-approved bypass. Preserve existing CI executor, secrets,
  and cost posture; no model/backend migration.
- Add the `propagate-provider-change` entrypoint only in the existing Codex, Claude, and
  Copilot shim families after checking their exact local conventions. Each invokes the
  canonical procedure without duplicating it. Outward generated instructions remain
  versioned/derived; do not put ADR identifiers in public text.
- C# is limited to current generic chat proof and planned TEI; do not imply full provider
  parity. Shared-core impact still triggers every applicable implementation/profile gate.
- Preserve frozen retrieval32, policy29, accounting42+2 and Frozen102 profiles/evidence.
  Adjacent pricing/catalog jobs may reuse the procedure only when relevant; do not rework
  them as part of initial provider-drift hookup.

## Existing anchors and constraints

- `contracts/DRIFT-CHECK.md`: canonical upstream snapshot audit and report classifications.
- `contracts/NEW-PROVIDER.md`: research-first contract/provider addition procedure.
- `specification/MAINTENANCE.md`: sealed release, compatibility, candidate release, and
  independent-review requirements. It is frozen by `core-generation-v0`.
- `.github/workflows/contract-drift.yml`: deterministic selector followed by Claude
  proposal job; currently audit-only contract edits, PR to `develop`, no auto-merge.
- `.agents/skills/check-provider-drift/SKILL.md` and
  `.github/prompts/check-provider-drift.prompt.md`: existing thin drift shims.
- `tests/test_contract_drift.py`, `tests/test_agent_instructions.py`, and CI contract,
  fixture, conformance, docs, and C# proof gates are candidate guard locations. Confirm exact
  conventions and registrations during implementation; do not assume every guard belongs in
  these files.
- `scripts/validate_contracts.py::NOT_SNAPSHOTS` owns the excluded-file list; its
  `snapshots()` function feeds both structural validation and
  `scripts/check_contract_drift.py` selection. Add `PROPAGATE-CHANGE.md` to this exclusion
  set and extend
  `tests/test_contract_drift.py::TestSelection.test_procedure_documents_are_not_audited_as_snapshots`
  for the filename. Preserve selector algorithm and prior meaningful provider membership.
- C# integration must add `src/csharp/AnyInfer.Maintenance` to `src/csharp/AnyInfer.sln`
  and explicitly build/run its exporter shape/determinism check through the existing C#
  workspace phase in `workspace.py`, `tests/test_workspace.py`, and
  `.github/workflows/ci.yml`. In CI, the single Python 3.11 `gates` job emits deterministic
  Python inventory and its registered gate evidence; `native-csharp` emits C# inventory and
  registered evidence. Pure validation runs downstream only, on these artifacts; the early
  contracts gate checks schema/input shape only. If suite evidence is required, use exactly
  the existing `test` job's `ubuntu-latest`/Python 3.11 leg, wrapping its existing command
  through the dispatcher once; do not duplicate the suite, and leave other matrix legs' present
  coverage intact.
- Add a `provider-change` aggregation job in `.github/workflows/ci.yml`, depending on `changes`,
  `gates`, `native-csharp`, and `test` when its suite evidence is required. The `gates` job
  uploads `provider-change-python-inventory` and
  `provider-change-python-gates-verification`. If suite evidence is required, the existing
  `test` job's `ubuntu-latest`/Python 3.11 leg uploads
  `provider-change-python-suite-verification` (a distinct name). `native-csharp` uploads
  `provider-change-csharp-inventory` and `provider-change-csharp-verification`. The consumer
  requires all applicable exact names from the same workflow run and emits
  `provider-change-run-report`; missing artifacts fail. Bind every artifact and consumer to
  the trusted PR head identity AND actual evaluated checkout/source commit and tree. On pull
  requests, record `pull_request.head.sha` independently from actual `HEAD`/tree and validate
  the latter against the explicit trusted evaluation target. Under the current default PR merge
  checkout, actual `HEAD` may legitimately equal `github.sha`; never substitute that merge SHA
  for PR-head identity or silently change checkout policy. Registry and raw input hashes, run
  identity, and all source identities must agree. Explicitly add
  `provider-change` to `ci-ok` needs and require its success whenever applicable, so the generic
  skipped-job allowance cannot bypass it. New maintenance/registry/procedure/exporter paths
  trigger applicable jobs. Future languages add a real producer and aggregation dependency;
  the generic planner remains language-agnostic.
- `specification/README.md` describes profiles, releases, implementation drivers and
  reports. `AGENTS.md` and `plans/ANYINFER_CSHARP_SDK.md` bound current Python/C# claims.

## Implementation sequence

Each phase ends with its stated gate. A gate must report actual commands and results; no
current test or release claim is implied by this plan.

### Phase 0 — Baseline and frozen inputs

- [x] **P0.1** Re-read `AGENTS.md`, `DESIGN.md`, the two maintenance discovery reports,
  `contracts/DRIFT-CHECK.md`, `contracts/NEW-PROVIDER.md`,
  `specification/MAINTENANCE.md`, relevant existing shim/workflow/test paths, and the C# SDK
  scope plan. Do not inspect actual observer outputs. Record the source HEAD and working-tree
  state; preserve unrelated work already present, including the uncommitted TEI plans and
  other user changes.
  > NOTE: Required docs and current shim/workflow/test paths were reviewed. Captured HEAD
  > is `acdc94469f86eca0a67f9226fbc2c7ae6a7e7bf8`; see the P0 baseline artifact at
  > `epics/a4822703-eee2-44cb-960c-47b3ae3d4c73/artifacts/provider-maintenance/execution/baseline/index.md`
  > for the working-tree snapshot. No observer outputs were inspected.
- [x] **P0.2** Identify precisely which assets `core-generation-v0` hashes and establish
  guards that none are edited by this work. Preserve retrieval32, policy29, accounting42+2,
  and Frozen102 evidence.
  > NOTE: The `core-generation-v0` manifest names 106 assets; the read-only SHA-256
  > comparison matched all 106. The manifest includes `specification/MAINTENANCE.md`.
  > Exact frozen paths/hashes and verification results are in the P0 baseline artifact
  > linked above.
- [x] **P0.3** Map existing command/test/CI/shim conventions and confirm public Python and C#
  binding metadata names from source, without inferring support from future plans or reports.
  **Gate:** review baseline map and frozen asset list; run only the existing targeted
  read-only structural checks needed to establish the baseline, with commands/results recorded.
  > NOTE: The baseline map and checks are recorded in the P0 baseline artifact. Project-
  > interpreter frozen release verification passed. The first structural check found nine
  > missing template sections/date in the concurrent TEI contract rewrite; after its owner
  > restored the required structure, the project-interpreter validator passed all 22 snapshots.
  > The frozen baseline map and structural gate are accepted; Phase 1 is released.

### Phase 1 — Canonical procedure and data contracts

- [x] **P1.1** Add `contracts/PROPAGATE-CHANGE.md` defining evidence capture, classifications,
  adopt/informational decisions, shared-spec versus wire-only paths, per-implementation
  accounting, completeness rules, review, and coordinated draft PR outcomes. Link it from
  `DRIFT-CHECK.md` and `NEW-PROVIDER.md`; do not duplicate the full procedure there.
  > NOTE: Canonical procedure and links are saved; independent review accepted the lifecycle,
  > thin entrypoints and control-plane safeguards. Schema disposition alignment closed in
  > P1.2; exporters are under independent review and execution/CI integration remains open.
- [x] **P1.2** Define `maintenance/change.schema.json`,
  `maintenance/implementations.schema.json`, `maintenance/binding-inventory.schema.json`,
  `maintenance/verification.schema.json`, and `maintenance/run-report.schema.json`, plus
  `maintenance/implementations.json`.
  Keep these outside `specification/` and avoid any change to frozen hashed assets.
  Schema fields must support the settled persistent evidence and status model, stable IDs,
  path ownership, candidate release references, and registered command argv/gate IDs. Set
  schema versions and define provenance-envelope, source-identity, record/input identity,
  producer, workflow-run, declaration/dependency, verifier result and hash-reference fields
  precisely enough for a third language implementation without inventing additional
  semantics. Inventory, verification and run-report schemas are version 1.
  > NOTE: Independent review accepted the closed v1 schemas after format, disposition,
  > actual Git-ID versus content-hash, and mandatory runtime-gate corrections. Fresh focused
  > evidence records 23 passes with no JUnit failures/errors/skips; frozen hashes remain intact.
- [x] **P1.3** Define `maintenance/changes/<id>.json` examples/fixtures only where tests need
  them. They are immutable committed input declarations with declared statuses/rationales,
  paths and required gate IDs; they contain no generated outcomes or output/log hashes.
  Examples must use synthetic/non-secret facts and must not represent fictional verification
  as real. **Gate:** JSON Schema/input validation and contract-snapshot structural validation;
  verify frozen manifest hashes remain unchanged.
  > NOTE: The hypothetical input lives only in `tests/fixtures/provider-change/`; no adopted
  > synthetic record remains under production `maintenance/changes/`. Existing C# OpenAI
  > generation is modeled as present, not unsupported. P3 owns actual-inventory rejection
  > of an unsupported declaration for an existing binding.

### Phase 2 — Binding exporters, dependency closure and registration

> NOTE: The common exporter CLI is registered argv followed by `--context PATH --output PATH`.
> Context is a binding-inventory-v1 envelope with dispatcher producer and empty bindings;
> exporters preserve provenance and replace only producer and actual declarations. Context
> does not establish qualification; the pure validator checks independently trusted run/source
> facts. P3 can be implemented against this held schema seam while P2 review/integration runs.

- [x] **P2.1** Implement the Python exporter at `scripts/export_python_provider_bindings.py`
  using actual public provider/operation registrations. It must be side-effect-free and emit
  deterministic versioned inventory without credentials, factories, network, discovery or
  model loads. Each provider/operation declaration includes all dependent snapshot IDs,
  including inherited/base dialect and provider/preset contract IDs, derived via actual
  registration/composition and a bounded checked mapping.
  > NOTE: Independent review accepted deterministic actual-registration export and complete
  > checked dependency mappings; focused evidence records 4 passes. The non-inference
  > scope extension is independently accepted with 24 schema tests. C# exporter has 5
  > focused passes and solution registration; its explicit workspace export gate remains open.
- [x] **P2.2** Implement the isolated non-packable C# exporter in
  `src/csharp/AnyInfer.Maintenance/AnyInfer.Maintenance.csproj` and `Program.cs`, using public
  registry metadata. Add the project to `src/csharp/AnyInfer.sln` and explicitly register a
  deterministic build/run/export-shape check in the existing native C# workspace/CI flow.
  Verify its declared current scope accurately; missing provider bindings remain
  unsupported/pending gaps, including TEI until implemented.
  > NOTE: Root C# workspace gate passes all 9 steps on 2026-10-22, including the new
  > nonqualifying deterministic exporter-shape check. The full solution records 815 unit
  > and 93 conformance passes; accounting, request-policy, retrieval, NuGet and examples
  > remain green. TEI declaration export is now actual metadata, not a planned binding;
  > runtime support is established separately by its own controls/live evidence.
- [x] **P2.3** Register Python and C# roots, exporter/verifier argv and only actually declared
  profile claims. Add a synthetic third language fixture to prove generic registration and
  planning do not rely on Python/C# conditionals. Keep declared-binding inventory separate
  from runtime qualification evidence. Add dependency closure for provider/preset snapshots
  and inherited shared dialects; missing dependency mapping rejects/blocks. Include
  non-inference snapshot routing. **Gate:** deterministic exporter output, output schema,
  dependency closure tests, and the explicit C# exporter check in the native C# workspace
  gate.

### Phase 3 — Controlled check runner, pure planner and negative controls

> NOTE: Implementation review found that existing `portable_release_assets.load_release_assets`
> deliberately accepts only core-generation/v0 and its fixed inventory. Candidate qualification
> must not loosen that sealed reader or apply it to a new profile revision. P3 is authorized to
> add a separate private pure candidate reader and `maintenance/candidate-evidence.schema.json`:
> explicit candidate inventory/normative/schema assets, closed raw-byte hashes, complete report-v0
> corpus checks, and separately trusted A/reference/B/execution/review facts supplied through
> expected context. Canonical metadata/hash validity never attests execution. Unsupported future
> evidence grammar fails closed. Draft declarations remain immutable and never self-qualify;
> no release writer, sealing or frozen-asset edits are authorized. Independent review must close
> this additional seam before P3 acceptance.

> NOTE: Runner source review required its production CLI to pin the canonical
> `maintenance/implementations.json`; alternate test manifests are confined to a private injection
> seam. Focused evidence records 11 passes; the alternate-command negative is being strengthened
> to target exporter execution. Timeout/signal/spawn failures retain diagnostics and fail closed
> rather than inventing a nonnegative successful exit. CI and proposal wiring have distinct owners.

- [x] **P3.1** Implement `scripts/run_provider_change_checks.py` as the sole dispatcher.
  Read commands/gate IDs only from the registered implementation manifest, validate roots and
  platform, run argv without shell interpolation, and collect current source/command facts.
  Hash but never rewrite immutable change input and registry. Emit inventory/verification
  artifacts bound to trusted PR head SHA AND actual checkout commit/tree, raw input/registry
  hashes, workflow-run identity and producer. Keep local output under ignored
  `.tmp-tests/provider-change/<id>/<run-id>/`; never write run outcomes into committed inputs.
  > NOTE: Independent source/oracle review accepted the canonical-registry CLI guard,
  > private synthetic injection seam, immutable-source checks and honest failure handling.
  > The alternate exporter-command refusal control is closed; focused runner/proposal batch
  > records 22 passes. Proposal-tree/selection safeguards remain separately open under P5.
- [x] **P3.2** Implement `scripts/check_provider_change.py` as pure validation/planning over
  schemas, records, registry, independently supplied expected source/CI context, versioned
  artifacts, changed paths, dependency closure, candidate references and verification
  evidence. Reject stale/mismatched/self-claimed artifacts. Validate evidence coverage without
  claiming semantic correctness from declarations or rationale prose. Verify artifact run,
  head and checkout/source identities against trusted CI context; require same-run child
  artifacts and matching raw input/registry hashes. A clean input replay produces the same
  validation result and does not mutate the input.
- [x] **P3.3** Add `tests/test_provider_change_propagation.py` for valid wire-only/no-basis-delta
  change, normative candidate change with all applicable registered implementation checks,
  shared-core impact when a provider binding is absent, unsupported status with absent binding,
  and rejection when a binding exists. Check reviewed unaffected rationale is present without
  pretending prose semantics can be mechanically inferred. For shared paths consumed by
  multiple languages, allow one shared changed path while requiring each consumer's own
  qualifying verification; do not require duplicate language source edits.
- [x] **P3.4** Add controls for third-language registration, stale/missing binding inventory,
  stale source evidence, skipped/failed verification, invalid/missing references, status/path
  contradictions, changed-path coverage, accidental frozen-file mutation, new capability
  auto-adoption, no-change/no-PR, and no hardcoded floating live values. **Gate:** focused
  propagation tests and relevant schema/contract checks pass; intentionally invalid fixtures
  fail for the expected structural reason. Add dependency-closure positive cases for
  shared-OpenAI/preset sections and inherited mixins, and a negative case omitting a dependent
  binding. Add explicit out-of-binding-scope/blocked cases for MCP and Hugging Face snapshots.
  Also reject missing required producer/artifact, wrong workflow run, wrong trusted PR head,
  wrong evaluated checkout commit/tree, any mismatch among input/registry hashes, and runner
  attempts to mutate the committed input. **Gate:** focused checks prove valid same-run
  artifacts pass and each missing/mismatched/replay case fails without changing input bytes.

  > NOTE: Independent validator and acceptance reviews are closed. The private candidate
  > reader binds the exact classified asset set, unique embedded inventory records, complete
  > canonical report-v0 results and independently supplied A/reference/B/run/review identities.
  > Canonical assets resolve from checkout ROOT; generated reports resolve from the external
  > wrapper. Retained candidate controls record 18 passes and one Windows symlink-capability
  > skip. The acceptance batch records 29 passes and that same capability skip; the final
  > planner-only batch records 13 passes, independently rejecting false unaffected statuses
  > for preset fragments and inherited dialects. Third-language registration, both non-inference
  > snapshots, absent unsupported bindings and mandatory shared-core gates are covered.

### Phase 4 — User-facing entrypoints and repository guards

> NOTE: The qualified-candidate positive path needs an accountable input route rather than
> being permanently unreachable in CI. The existing `ci.yml` workflow_dispatch now accepts an
> all-or-nothing production input path, local candidate-evidence path and operator-supplied
> expected qualification JSON. Only manual dispatch may supply these facts; PR/push drafts
> remain unqualified without them. The manual run activates the same required producer shards,
> records its actor/run/evaluation target separately, and never derives expected execution or
> review facts from the declaration or wrapper. This adds no workflow, model, credential or
> sealing authority. Source review and final gate remain required.

> NOTE: The evidence wrapper/reports refer to committed B and cannot themselves be required
> as inputs committed in B. Manual qualification therefore selects a prior Actions artifact
> bundle explicitly, downloads it into a confined ignored directory with read-only artifact
> access, and supplies independent operator facts separately. Canonical release assets remain
> checkout-root-relative under `specification/`; generated reports resolve relative to the
> external wrapper. No proposed code is executed or tracked file overwritten during retrieval.
> Missing artifacts, unsafe paths or any provenance/hash mismatch block qualification.

- [x] **P4.1** Add `propagate-provider-change` thin entrypoints in the exact existing Codex,
  Claude and Copilot shim families, after confirming the local Claude/prompt paths and format.
  Each points to `contracts/PROPAGATE-CHANGE.md`; no entrypoint restates policy.
- [x] **P4.2** Extend existing shim/instruction tests only where their actual conventions
  require it. Ensure generated/outward instruction versioning and no-ADR checks remain intact.
  > NOTE: The three thin entrypoints, instruction tests and procedure exclusion are saved;
  > focused drift/instruction run reported 32 passes, with skill validation and independent
  > source review clean. P4.3 remains open for actual workspace and CI aggregation wiring.
- [x] **P4.3** Add pure impact validation to existing contracts/CI guards where it fits; reuse
  language jobs for exporter and real language gates. Extend `scripts/validate_contracts.py`
  `NOT_SNAPSHOTS` with `PROPAGATE-CHANGE.md`, and extend
  `tests/test_contract_drift.py::TestSelection.test_procedure_documents_are_not_audited_as_snapshots`
  so the new procedure is excluded from snapshot validation and deterministic selection.
  Preserve existing selector algorithm and provider membership. Add new maintenance paths to
  applicable CI path filters/gate couplings. In `.github/workflows/ci.yml`, add a
  `provider-change` aggregation job requiring `changes`, `gates`, `native-csharp`, and `test`
  whenever suite evidence is required. `gates` is one Python 3.11 job and produces Python
  inventory/registered gate evidence. It uploads `provider-change-python-inventory` and
  `provider-change-python-gates-verification`. When suite evidence is required, use only
  `test`'s `ubuntu-latest`/Python 3.11 leg, wrapping its existing command once through the
  dispatcher; that leg uploads the distinct `provider-change-python-suite-verification`.
  Do not duplicate the suite or change other matrix coverage. `native-csharp` produces C#
  inventory/registered evidence and uploads `provider-change-csharp-inventory` and
  `provider-change-csharp-verification`. The consumer requires all applicable exact artifact
  names from that same workflow run and emits `provider-change-run-report`. Missing any
  required gates/suite/C# artifact fails. Pure validation runs downstream only; the early
  contracts gate validates schemas/input shape only. Bind all artifacts to trusted PR head
  identity AND actual evaluated checkout commit/tree. For pull requests, record
  `pull_request.head.sha` independently and validate actual `HEAD`/tree against the explicit
  trusted evaluation target. Under the existing default PR merge checkout, `HEAD` may
  legitimately equal `github.sha`; do not substitute the merge SHA for PR-head identity or
  change checkout policy.
  Explicitly include the job in `ci-ok` needs and require success whenever applicable so the
  generic skipped-job allowance cannot bypass it. Future languages need a real producer and
  aggregation dependency; generic planning stays language-agnostic. Do not add guessed gate
  counts. **Gate:** focused instruction/propagation/drift tests, contracts input guard,
  workspace/C# gate and CI path-filter/`ci-ok` coverage checks.

  > NOTE: Independent CI review is closed. The existing producers run registered shards
  > once, aggregate exact same-run artifacts, and require applicable success in ci-ok.
  > The manual five-input handoff retrieves an external evidence bundle read-only and keeps
  > operator facts separate. Focused CI controls record 14 passes; root's nine-step C# gate
  > passes. Workspace lint includes all five maintenance scripts, with 21 focused workspace
  > controls passing. Full repository acceptance remains P6.3.

### Phase 5 — Coordinated drift proposal integration

> NOTE: Adversarial review exposed same-runner environment mutation as a bypass of post-model
> validation. Publication is therefore isolated into a fresh trusted job within the existing
> workflow. The model retains the same executor/authentication/budget and prepares edits with
> read-only repository authority; the fresh job receives the existing publication permissions,
> independently retrieves the original selection and treats every proposed bundle byte as
> untrusted. It rejects protected paths before materialization or code import, executes only
> baseline-owned validation, and commits only validated paths. No proposed code executes there.
> This narrows model authority without expanding publication scope; no automatic merge or
> release qualification is introduced. The complete staged/unstaged/untracked view and honest
> no-change/draft outcomes remain required.

- [x] **P5.1** Update `.github/workflows/contract-drift.yml` proposal instructions to follow
  both canonical procedures. Preserve deterministic selected snapshot set, authenticated
  action/backend/secrets, bounded budget, real citations/dates, and audit of every selected
  item. Remove the conflicting contract-only prohibition only for this explicitly scoped
  coordinated proposal path.
- [x] **P5.2** Make one draft PR against `develop` include contract edits, adopted candidate
  specification assets at new paths when warranted, affected implementation changes and
  tests, and the immutable input declaration only. Run outcomes stay in generated ignored
  files and same-run CI artifacts, never committed in `maintenance/changes/<id>.json`.
  Candidate lifecycle must distinguish
  `draft_prepared` from `qualified_candidate`; this workflow may prepare only an unqualified
  draft and must never create qualified release manifests/reference expectations or claim
  that dirty edits satisfy clean committed evidence. No silent release sealing, no
  auto-merge, and no PR for no adopted/meaningful change.
- [x] **P5.3** Ensure `NEW-CAPABILITY`, `UNVERIFIABLE`, blocked, failed and incomplete results
  are recorded honestly. A provider snapshot can be updated only with cited source evidence;
  adapter wire changes require transport/conformance coverage; candidate shared behavior
  changes require candidate release and independent review. **Gate:** workflow/static guard
  tests and a credential-free dry-run or fixture simulation prove no-change/no-PR and
  incomplete/blocked outcomes remain drafts or blocked. Attempts by the proposal to weaken
  its validators, workflow, registry or sealed-asset safeguards must be blocked for follow-up
  review rather than allowed as self-approval. Downstream provider-change aggregation derives
  qualification/completion; neither the committed declaration nor proposal can assert it.

  > NOTE: Independent publisher review is closed after adversarial fixes. A fresh trusted
  > job validates the complete staged/unstaged/untracked bundle against the original
  > selection and baseline before materializing bytes. Existing immutable declarations
  > cannot be overwritten or deleted. Only new normative Markdown, schema JSON, inventory
  > JSON and fixture inputs can be drafted; new release/reference/report/qualification/seal
  > outputs and control-plane edits reject before writes. Retained final proposal evidence
  > records 33 passes; no live model, remote PR, sealing or publication was executed.

### Phase 6 — End-to-end acceptance

- [x] **P6.1** Exercise synthetic cases end to end: wire-only change with explicit no-delta;
  adopted normative change requiring registered implementation checks; absent C# provider
  binding retained as a gap; a third synthetic language; and incomplete evidence. Do not
  use live provider values as expected test data. Include valid draft-prepared state and a
  separate qualified-candidate fixture enforcing clean A/reference/B/complete-report/review
  ordering; shared-base dependency expansion; and an attempted control-plane bypass rejected.
- [x] **P6.2** Independent reviewer checks the procedure, schemas, genericity, exporter safety,
  workflow permissions/cost boundaries, truthful support claims, and frozen release assets.
  Address findings before marking complete.
  > NOTE: Cold reviews close all P1/P2 findings across schemas, exporters, dispatcher,
  > pure candidate validation, generic planning, CI artifact handoff, fresh trusted publishing,
  > public delivery and focused acceptance controls. Frozen assets have no source diff.
  > No actual future candidate release is created or qualified; synthetic positive evidence
  > tests the supported grammar and trusted-fact joins. The real TEI record is wire-only.
- [ ] **P6.3** Run the repository's required final gate `python workspace.py check` once after
  all changes are integrated, plus any workflow validation required by repository convention.
  Verify clean source acceptance for any candidate specification release without sealing or
  publishing it absent separate authorization. **Gate:** all required checks pass, reviewer
  approves, frozen asset hashes are unchanged, and remaining gaps are explicitly recorded.
  > NOTE: First root full gate (`6a2563c4-372a-45e3-a444-a8968ab12293`) passed 20 of 22
  > steps but exposed a stale native-CI assertion and a TEI test cancellation-observer race.
  > Both are retained as failed evidence; no full-gate success is claimed. Frozen release
  > verification still passes with manifest SHA-256 `16122cca198d9e688d3c4b5724ac11f0324a4390d8e8589e443fe04a48e81391`.
  > The exact test-only fixes have clean cold review; the repeated full 22-step root gate
  > passes in 137.5s, including 815 native unit and 93 conformance tests. Commit and isolated
  > clean-source replay remain open; no remote workflow or qualified release is claimed.
  > Clean replay of initial source `3834e8e7387bf26637f5965a77ffd5125b0f82fb` then exposed
  > the exporter's hidden prebuild assumption. Its five executable controls now live in the
  > existing native inventory gate after an explicit solution build; the ordinary Python
  > suite has no .NET dependency. Counts remain 9 C# / 22 total. Targeted boundary and native
  > checker runs pass; full verification of a new source checkpoint remains required.
  > The corrected boundary has clean cold review; root's repeated full 22-step gate passes
  > in 156.1s. Isolated verification of the next committed source checkpoint remains open.

## Work ownership and sequencing

| Lane | Owned paths/responsibility | Dependency |
|---|---|---|
| Canonical procedure | `contracts/PROPAGATE-CHANGE.md`, minimal links in the two canonical procedures | Phase 0 complete |
| Data contracts | `maintenance/*.json` schemas, registry and synthetic records | Phase 1 design agreed; disjoint from procedure prose |
| Exporters | Python script; isolated C# maintenance project and solution registration | Registry fields settled; distinct language paths |
| Runner | `scripts/run_provider_change_checks.py`, registered argv/gates and artifact production | Schemas and registry settled |
| Validator | Pure `scripts/check_provider_change.py`, focused tests | Schemas and exporter artifact shape settled |
| CI aggregation | `provider-change` job and same-run artifact wiring in `.github/workflows/ci.yml`, `ci-ok` coupling | Runner artifacts and validator contract settled |
| Shims and CI | existing shim families, instruction tests, drift workflow, workspace and CI gates | Procedure/validator behavior settled |
| Coordinator | Resolve cross-lane conflicts, review claims, preserve root Git state, run final gate | All lanes integrated |

Parallelize only disjoint path owners after shared interfaces are settled. Serialize schema,
registry and workflow integration; re-read shared manifests immediately before a minimal edit.
Run heavy builds and the full gate serially, by the coordinator. Sub-agents do not change Git
state; root coordinator alone may commit by explicit path, after separate authorization.

## Deferred boundaries

- No full C# provider parity, forced port, or inference from a planned adapter.
- No broad pricing/catalog refresh redesign; reuse only if a finding is relevant.
- No silent oracle regeneration, release sealing, merge, publish, or unsupported claim.
- No unchecked contract dependency closure, stale verification artifact, or self-approved
  control-plane policy change.
- No change to provider breadth, normalized semantics, or upstream capability adoption policy.
- Implement TEI and provider-change propagation under the user's 2026-10-22 authorization;
  proceed in parallel where paths are disjoint.
