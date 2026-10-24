# Shared foundation and SDK parity alignment

**Resume from the first unchecked box.** Read this file, the
[SDK parent](ANYINFER_CSHARP_SDK.md), the
[API inventory](CSHARP_SDK_API_PARITY.md), and the
[foundation master](language-neutral-foundation/ANYINFER_LANGUAGE_NEUTRAL_FOUNDATION.md)
before the corresponding work. Each phase ends in a test gate. Record deviations beside
the affected box as `> NOTE:` lines; do not mark a parent milestone complete from this leaf.

## Authorization and settled boundaries

On 2026-10-24 the user requested an audit of the foundation, Python, and C#, accurate
documentation of multiple language SDKs, plan coverage for the gaps, and an initial burn-down.
This resumes bounded audit/documentation work after the earlier branch-handoff pause.
It does not select another provider or language, authorize publication, or change existing
behavioral exceptions. Full Python core-library parity in phases remains the destination.

> NOTE: On 2026-10-24 the user explicitly authorized continuing the burn-down autonomously
> until Python and C# are both usable SDKs with matching strategies and features under
> predominantly similar native conventions. ALIGN.3 is the next slice, not the stopping
> point for the run. Continue through the remaining SDK plan after each verified slice;
> preserve explicit semantic differences as visible work/decisions rather than silently
> counting them as identical behavior. Publication, sealed-release changes and changes to
> asset authority retain their existing separate gates.

Audit baseline: `ea85ddd42f418cdf81f55638a2e8afd0af848daf` on
`feature/language-neutral-foundation`. The last qualified executable remains
`952b678d2dc020075c09bc6f8d11e2879fc992bd`; documentation work does not replace that
clean-source evidence.

| Finding | Evidence and implication |
|---|---|
| Python and C# are not at full parity. | `maintenance/provider-parity/python-builtins.json` and `scripts/export_python_provider_parity.py` enumerate 106 Python descriptors / 129 operation memberships. `scripts/check_csharp_binding_inventory.py` independently checks 7 native descriptors / 10 bindings. The 119 remaining memberships describe provider breadth, not a percentage of SDK behavior. |
| C# has progressed beyond the original proof. | Accepted SDK.1–7 cover native sync/async calls, configuration/credentials, catalog/capabilities, modern schema, telemetry/manifests, bounded accounting/policies, retrieval and rich generation/tool loops. `src/csharp/AnyInfer/AsyncClient.cs`, `Client.cs`, `Internal/ToolLoop.cs` and their tests are current implementation evidence; old proof-only absence claims are stale. |
| The foundational specification is bounded. | `specification/releases/core-generation-v0.json` seals a 102-case profile. Later SDK development profiles and paired observers do not widen that release or complete foundation M3.1. Never edit any asset hashed by the sealed manifest. |
| Shared data already feeds independent SDKs. | `src/csharp/AnyInfer/AnyInfer.csproj` embeds Python-owned catalog/model/pricing JSON; `scripts/generate_csharp_compat_presets.py` generates inert native preset data. Build-time Python tooling is accepted. An inert row is not a registered adapter, an operation claim, or live qualification. |
| A cross-implementation maintenance registry exists. | `maintenance/implementations.json` registers native exporters and gates. C# currently has an empty `profile_claims` list. Preserve this field's actual meaning; historical bounded proof evidence is not permission to add a current release claim. |
| The root API inventory is not a progress meter. | Its 235 rows intentionally await their complete assigned semantics and SDK.11c reconciliation. Type existence or a passed narrow profile cannot check them wholesale. |
| The public overview is stale. | README, documentation indexes and contributor architecture still describe only the small proof; some deny implemented sync, accounting, rich input or tool-loop features. Detailed SDK pages have advanced unevenly. |

There is no required `basis/` directory. The existing roots are `specification/`,
`contracts/`, `maintenance/`, and language implementations under `src/`. Relocating
Python-owned assets would be a new authority decision, not a correction implied by a path.
No new registry, cross-language runtime, vendor SDK, or generated policy implementation is
needed for this reconciliation.

## Execution checklist

Commands below run from the repository root in PowerShell, using the existing repository
virtual environment. `workspace.cmd` selects that same environment; do not substitute an
unqualified ambient Python interpreter. Native commands, when needed by a later slice,
run from `src/csharp/` so its SDK pin applies. Heavy checks remain serialized.

- [x] **ALIGN.1 — Verify the audit baseline.** Reconcile the native default registrations
  and declaration exporters with the existing provider inventory; record which API/profile
  and release claims are actually present. Preserve all 235 root rows and the 15 open SDK
  milestone boxes. Gate:
  `.\.venv\Scripts\python.exe scripts/export_python_provider_parity.py --check maintenance/provider-parity/python-builtins.json`,
  `.\.venv\Scripts\python.exe scripts/freeze_release.py --verify core-generation-v0`, static root-export/table coverage,
  and the existing registered binding witness in the final workspace gate pass. No new
  qualification claim is inferred from that witness.
  > NOTE: Verified 2026-10-24 at documentation baseline ea85ddd. The Python exporter check
  > passes; static AST/table comparison finds exactly 235 unique matching exports and 15
  > open parent SDK boxes. Registry inspection confirms both implementations and C#'s empty
  > profile-claim list. The full 25-step workspace run passes, including the independent
  > native binding witness. Frozen release verification retains SHA-256
  > `16122cca198d9e688d3c4b5724ac11f0324a4390d8e8589e443fe04a48e81391`.

- [x] **ALIGN.2 — Correct the foundation and SDK documentation.** Add
  `docs/concepts/foundation.md` as the public explanation of normative behavior, shared
  declarative/build-time data, independent SDK execution and observed conformance. Link it
  from `mkdocs.yml`, `docs/concepts/README.md`, and overview pages. Reconcile repeated
  claims in root README, AGENTS/DESIGN, documentation indexes, contributor architecture/proof,
  C# SDK/migration/reference and `src/csharp/README.md`. Keep Python release support and
  C# development status explicit; existing executable snippets, schema/TLS exceptions and
  hosted-verification limits remain accurate. Gate: independent claim review,
  `.\workspace.cmd check` (including strict docs, exact compiled examples, package-only consumer
  and all native/development profiles), plan-link checks, frozen integrity and clean diff.
  This closes the documentation correction only; SDK.12a remains open for full reference
  and cookbook coverage.
  > NOTE: Completed 2026-10-24. Independent changed-line and plan review has no remaining
  > actionable findings (Traycer artifact `sdk-foundation-alignment/review`). Full workspace
  > shell `004fc6ea-6784-4cf3-b275-897432d5c2ba` exits 0: all 25 steps pass in 258.7s,
  > including 4,536 Python passes / 10 documented platform skips, 1,135 native unit and 93
  > conformance passes, all five paired SDK profiles, inert-data/binding checks, isolated
  > NuGet consumer and exact compiled examples. After final wording corrections, the
  > docs-check/docs-build rerun passes all four steps (50 Python examples, 462 documented
  > exports, links across 170 Markdown files, strict site build); all 15 agent-instruction
  > controls pass. Plan links and frozen hashes verify. Runtime source, executable examples
  > and sealed specification assets are unchanged. This is working-tree verification,
  > not a new qualified clean-source report or package publication.

- [x] **ALIGN.3 — Make API reconciliation executable (SDK.11c).** Extend
  `plans/CSHARP_SDK_API_PARITY.md` with a separate evidence ledger for the existing 235
  rows: exact native equivalent or language-specific mapping, implementing milestone,
  source/test evidence, and partial/deferred/difference status. Preserve final-completion
  checkboxes until the entire assigned behavior is qualified. Add
  `scripts/check_sdk_api_parity.py` with controls in `tests/test_sdk_api_parity.py` that
  compares the pinned Python AST inventory and
  requires a unique classified ledger row for each name; verify cited native symbols and
  paths, and make unsupported cases explicit. Do not mistake symbol coverage for semantic
  equivalence. Register the checker in `workspace.py` only after independent review.
  Gate: `.\.venv\Scripts\python.exe -m pytest tests/test_sdk_api_parity.py` covers
  missing/duplicate/unassigned/stale-symbol negatives; the public native migration tests,
  existing checks and package/examples remain green. Record any deliberate
  Python baseline update and its inventory diff before changing baseline expectations.

  - [x] **ALIGN.3a — Freeze the ledger/checker contract.** Keep the original root-export
    completion table intact. Add a separate, machine-checked 235-row evidence table in
    `plans/CSHARP_SDK_API_PARITY.md`, with statuses `implemented`, `partial`, `deferred`,
    and `different`, explicit native public symbol IDs, source/test paths, assigned
    milestone and remaining semantic gaps. Pin the existing Python source baseline and
    compare literal AST exports/import mappings without importing the SDK. Gate: the
    coordinator records the row grammar, status meaning and independent native-symbol
    witness before disjoint ledger/checker implementation begins.
    > NOTE: Contract settled 2026-10-24. The separate Markdown ledger has exactly seven
    > columns: Python export, Status, C# public symbols, Native source, Test evidence,
    > Milestone, Scope and remaining gap. Status `different` means an explicit semantic
    > difference, not ordinary PascalCase/Exception/delegate idioms; `implemented` remains
    > scoped to its named surface and cited behavior. IDs use `T:` plus reflection FullName
    > or `M:`/`P:`/`F:`/`E:` plus owner and declared public member name; overload signatures
    > are intentionally not certified. Generic backtick IDs use double-backtick Markdown
    > spans. Multiple IDs/paths use `<br>`. Deferred rows have no invented native equivalent.
    > The checker pins the existing AST export/import signature without importing Python
    > SDK code or requiring Git history at runtime. It checks separate exact coverage,
    > classification, evidence paths and actual native public identity; semantic truth
    > still requires the independent evidence review.
    > The nonpackable existing `AnyInfer.Maintenance` tool gains only a separate
    > `--public-api --output FILE` metadata projection. It reflects public exported SDK
    > types and declared public members without constructing providers or invoking getters;
    > existing `--context/--output` provider-binding behavior is preserved. No dependency,
    > SDK execution or sealed-asset change is needed. Checker, ledger and controls have
    > disjoint owners; root owns workspace registration and final acceptance.
  - [x] **ALIGN.3b — Populate the evidence ledger.** Read actual native source and tests
    for each row; no status follows only from a renamed type or milestone label. Preserve
    all 235 final-completion boxes. Gate: all baseline names have exactly one evidence row,
    deferred/partial/different cases explain what remains, and independent review samples
    every subsystem and all deliberate differences.
    > NOTE: The initial automatic type-name draft was rejected: public
    > existence and a generic nearby test are not per-export behavioral evidence. The
    > mapping was split into core/types/errors/client (119 rows), capabilities/catalog/
    > config/credentials/registry (49), and events/manifests/other areas (67). The retained
    > native witness is `.tmp-tests/sdk-api-parity/public-api.json` (2,083 public IDs).
    > All three replacement fragments pass name/ID/path checks and semantic review.
    > Final ledger integrator 9adb3309-18a6-4f51-9c2a-fe635e06c04c owns only the inventory
    > file, merging the three `*-evidence.json` fragments under that ignored directory.
    > Semantic review by 4112765c-89c1-4809-b1ad-535c4ce994c1 accepted the final merge.
    > Final counts are 172 implemented, 25 partial, 37 deferred and one different. All 235
    > original completion marks remain unchecked. Source adjudication corrected false gaps:
    > both SDKs omit server-tool maps in Usage Merge/Sum; native catalog parsing already
    > validates the closed category vocabulary, but does not publicly expose that set.
  - [x] **ALIGN.3c — Implement and test the checker.** Add the named Python checker and
    negative controls; use a native maintenance-only public-symbol projection if required
    to reject private/comment/token lookalikes. Do not change SDK execution semantics or
    the existing provider-binding export. Gate: missing/duplicate/unassigned/baseline-drift,
    nonexistent paths, stale/private native symbols and malformed status controls fail
    closed; the real ledger and public native migration tests pass.
    > NOTE: Checker/native projection are implemented by 8d685a5b-8e7b-439e-b290-953b7c4bb2e8;
    > independent controls by 45178bbe-c364-4946-b10d-5149934b4d95. Latest targeted controls
    > pass 39 cases with one explicit Windows symlink-privilege skip. Review corrections
    > include the independently recomputed AST fingerprint
    > `bd7aa30216f5586f8399e1fee6e7d4dcb7cd3e3c5c4cca6b0abd8f005e301243`, baseline
    > metadata, malformed/duplicate table handling, generic IDs, test-path roots and actual
    > projection validation. The first real CLI exposed emitted record `<Clone>$` methods;
    > the grammar now admits that exact method-only form and rejects malformed/non-method
    > lookalikes. Real build/projection/ledger CLI passes; native public migration tests
    > pass inside the full solution gate. No SDK runtime behavior changed.
  - [x] **ALIGN.3d — Review and integrate.** After independent review, register the checker
    in the existing workspace C# phase and lint inputs with updated command/count controls.
    Gate: full serialized workspace, package/examples, frozen integrity and plan links
    pass; record the exact resume point and leave SDK.11c/global parity open while their
    remaining semantic work exists.
    > NOTE: Independent merged-ledger/checker/workspace review is accepted in Traycer
    > `sdk-foundation-alignment/align-3-review`. Full serialized shell
    > `60c184de-e77f-4822-84ce-2a5625862f32` exits 0: all 26 steps pass in 260.6s,
    > including 4,575 Python passes / 11 platform skips (one new symlink-privilege control),
    > 1,135 native unit / 93 conformance passes, all five paired development profiles,
    > the actual 235-row checker, package-only consumer, exact examples and strict docs.
    > Frozen release integrity retains the ALIGN.1 hash; diff whitespace check passes.
    > This working-tree evidence does not replace the earlier qualified executable record
    > or close SDK.11c/global parity. The workspace phase now has 13 native steps.

- [x] **ALIGN.4 — Map broader behavior to foundation profiles.** Inventory the existing
  SDK accounting, request-policy, retrieval, rich-generation and tool-loop input corpora,
  independent observers/checkers and native-only boundary tests under `tests/fixtures/`,
  `scripts/check_csharp_*.py` and `src/csharp/AnyInfer.*`. Map implemented behavior and
  outstanding SDK.6c/8–12 work to current frozen coverage, development-only evidence, or
  absent shared evidence. Specify a reviewed successor-profile proposal only where needed;
  do not append later cases to v0 or silently promote development reports. Reuse
  `maintenance/implementations.json` and `contracts/PROPAGATE-CHANGE.md` rather than a
  parallel registry. Separately document existing asset ownership, generation, hashes and
  consumer checks; leave any proposed neutral-root migration as an explicit open decision.
  Gate: every claimed shared behavior has an identified contract/evidence boundary and
  reviewed maintenance path; new normative releases or asset authority changes wait for
  their specific decision. Foundation M3.1 retains its pinned historical accounting inputs
  and its separate approval gate.

  Development evidence inventory (2026-10-24; these rows are not release claims):

  | Behavior | Contract / input authority | Independent observers and comparison | Boundary |
  |---|---|---|---|
  | Frozen generation | `specification/core-generation.md`, `specification/releases/core-generation-v0.json` and its hashed corpus | Registered conformance machinery; native `AnyInfer.Conformance` development/final-report controls | Sealed 102-case profile only. C# registry `profile_claims` remains empty. |
  | Accounting | `specification/accounting-v1.md`, `tests/fixtures/accounting-v1/inputs.json` and `openai-compat-accounting.json` | `tests/test_accounting_parity.py`, `src/csharp/AnyInfer.Accounting/Program.cs`, `scripts/check_csharp_accounting.py` | 42 paired cases plus two native boundaries. Native count/money domain is explicit; this does not complete normative foundation M3.1. |
  | Request policy | `tests/fixtures/request-policy-v1/{inputs.json,schema.json,observations.schema.json}` | `tests/test_request_policy_parity.py`, `src/csharp/AnyInfer.RequestPolicy/Program.cs`, `scripts/check_csharp_request_policy.py` | 29 paired cases, including connected admission/lifecycle behavior. No separate released policy profile. |
  | Retrieval | `tests/fixtures/retrieval-v1/{inputs.json,schema.json,observations.schema.json}` | `tests/test_retrieval_parity.py`, `src/csharp/AnyInfer.Retrieval/RetrievalProgram.cs`, `scripts/check_csharp_retrieval.py` | 32 paired cases. Input batching is distinct from provider batch jobs; provider coverage is independently tracked. |
  | Rich generation | `tests/fixtures/rich-generation-v1/{inputs.json,schema.json,observations.schema.json,README.md}` | `scripts/observe_python_rich_generation.py`, `src/csharp/AnyInfer.RichGeneration/Program.cs`, `scripts/check_csharp_rich_generation.py` | 43 paired cases. Fixture/schema/README hashes are frozen by the development checker. |
  | Tool loop | `tests/fixtures/tool-loop-v1/{inputs.json,schema.json,observations.schema.json,README.md}` | `scripts/observe_python_tool_loop.py` / `_tool_loop_python.py`, `src/csharp/AnyInfer.ToolLoop/Program.cs`, `scripts/check_csharp_tool_loop.py` | 10 paired cases. Fixed bounded execution, not an agent framework. |

  `scripts/_csharp_observation.py` verifies exact input-byte digests and matching runtime
  source/corpus provenance. The profile-specific controls reject missing/extra cases,
  malformed observations and unauthorized normalization. Existing independent producers
  and checkers remain separate. Provider binding evidence still runs through
  `maintenance/implementations.json` and the existing propagation runner/aggregate;
  `scripts/check_csharp_binding_inventory.py` remains a nonqualifying shape witness.

  | Shared data | Current authority / native consumption | Existing closure and remaining evidence |
  |---|---|---|
  | Catalog defaults, model catalog, pricing | `src/python/anyinfer/catalog/default.json`, `catalog/models.json`, `capabilities/pricing.json`; `src/csharp/AnyInfer/AnyInfer.csproj` embeds their bytes under explicit resource names | Native `CatalogTests` / `PricingTableTests` exercise resource names and parsed values; the package-only consumer proves runtime independence. No dedicated embedded-resource byte-identity check was found; add one before claiming that extra guarantee. |
  | Compatibility preset data | `maintenance/provider-parity/python-builtins.json` exported from Python; `scripts/generate_csharp_compat_presets.py` emits `src/csharp/AnyInfer/Providers/CompatPresetTable.g.cs` | Generator checks canonical input bytes, records inventory SHA-256 and compares exact generated bytes with `--check`; `CompatPresetDataTests` and `tests/test_csharp_compat_preset_data.py` check metadata/fields. Inert data does not register providers. |

  The recorded SHA-256 values below identify this audit snapshot, not new pins or a new
  owner. Existing generators remain the only writers of verified upstream data.

  | Asset | SHA-256 |
  |---|---|
  | `catalog/default.json` | `531b841699d6a0b73e2d2abe10f4abaacc1e4a62708bca309df6e80e3222c001` |
  | `catalog/models.json` | `a909373f17134ba92ffc01ac92e9a43dc87f9f732904456814fcbb4b3213e2b9` |
  | `capabilities/pricing.json` | `2603a68e81b6ee89042325ad926d72104846f78a14fb8413859b92d22ad57a6e` |
  | `maintenance/provider-parity/python-builtins.json` | `f52e835ddc2e9afc62c8796279a1f44dd82faf38f6e2fe894000323d76c7ce7d` |
  | `src/csharp/AnyInfer/Providers/CompatPresetTable.g.cs` | `a795ff211257373f66f88ee794931313e0946ab6acb51f19ab82cfd250142ce6` |

  Context/history strategies, supervised local lifecycle/acquisition, sessions, arenas,
  evaluation/benchmarks, provider batch jobs and optional integrations lack corresponding
  broad paired profiles. SDK.9/10/11 must add input-only development contracts and independent
  native/Python observations as those features are ported; reuse the existing provenance,
  validation and maintenance paths. SDK.8 provider additions still require current protocol
  research. Native schema/TLS and numeric-domain exceptions retain their existing limits;
  new tests do not silently remove them. A successor normative release is a separate reviewed
  proposal after development evidence exists. Neutral-root asset migration remains an open
  authority decision, with no migration selected by this audit.
  > NOTE: Independent artifact critique accepted the evidence map, all cited paths/case
  > counts and all five SHA-256 snapshots. Existing equality/closure checks and authority
  > boundaries are retained. The ALIGN.3 full workspace run verifies the mapped existing
  > profiles; the absent subsystem profiles remain implementation work, not release claims.

- [ ] **ALIGN.5 — Resume the remaining SDK work from evidence.** Use ALIGN.3/4 to refine
  the parent SDK.6c/8–12 slices without re-creating completed leaves. SDK.8a remains the
  provider execution resume point: select a provider through `contracts/NEW-PROVIDER.md`
  research before any new binding. Context/history (SDK.9), native local lifecycle
  (SDK.10), session/arena/evaluation/batch and optional integrations (SDK.11), and compiled
  reference/runtime/release qualification (SDK.12) remain explicit gaps. Gate: the next
  bounded brief names its owned files, shared behavioral evidence and targeted tests;
  parent gates close only after actual implementation, independent review and the full
  serialized workspace gate. Publication requires its existing separate authorization.

  - [x] **ALIGN.5a — Expose the existing catalog category vocabulary.** Add public static
    `AnyInfer.Catalog.Catalog.BestAtCategories` as an immutable ordinal `IReadOnlySet<string>`
    over the existing 14 categories in `src/csharp/AnyInfer/Catalog/Catalog.cs`, using the
    .NET 8 BCL frozen set. The parser must use that same set; do not add a second vocabulary
    or change constructor/parser validation, order or normalization. Extend
    `src/csharp/AnyInfer.Tests/CatalogTests.cs` to prove the exact Python `BEST_AT` set,
    case-sensitive membership, immutability and parser use. Describe the accessor in
    `docs/reference/csharp-sdk.md`; leave Python behavior and shared JSON untouched.
    Gate: targeted `CatalogTests` pass with zero native warnings. Independent source review
    and qualification belong to ALIGN.5b. Root then updates only the
    ledger's `BEST_AT` evidence after the fresh public reflection contains the accessor.
    > NOTE: Completed 2026-10-24: exposed the existing 14-category vocabulary as an ordinal
    > frozen `IReadOnlySet<string>` and made the parser consume that same authority; targeted
    > `CatalogTests` passed with zero native warnings.
  - [x] **ALIGN.5b — Qualify the catalog gap closure and continue SDK.9.** Gate the coherent
    accessor/docs/ledger slice with independent source review, the real evidence checker
    and serialized full workspace,
    preserve frozen assets, then commit explicit paths. Proceed to a source-backed SDK.9a
    context/history implementation checklist and independent shared development evidence;
    the catalog accessor alone does not close SDK.4a again, SDK.9, SDK.11c or full parity.
    > NOTE: Catalog source review is accepted in Traycer
    > `sdk-foundation-alignment/catalog-vocabulary-review`. Full serialized shell
    > `b4e4fc0a-5f2e-4609-8111-b7ebc62f3e96` passes all 26 steps in 271.6s,
    > including 1,136 native unit / 93 conformance tests, the five paired profiles,
    > package-only consumer, exact examples and docs. The accessor appears in the actual
    > public reflection and BEST_AT is now implemented. Subsequent source adjudication
    > correctly marks Generation/GenerationRequest partial for absent cache/context/arena/
    > history members, and limits stream descriptions to generation. Final real checker
    > passes at 171 implemented / 26 partial / 37 deferred / one different; these evidence
    > corrections are not a runtime regression or a completion percentage. All root
    > completion marks and 15 parent SDK milestones stay open.
  - [ ] **ALIGN.5c — Port and qualify context tuning.** Execute the first unchecked box in
    [native context tuning](SDK_CONTEXT_TUNING.md), the bounded SDK.9a prerequisite. Its
    CTUNE.0 contract critique is accepted; resume CTUNE.1. Gate: actual native settings,
    independent shared development observations, documentation and the leaf's full gates
    pass before this box closes. Continue the remaining context document/representation,
    ranking/deduplication, selection/packing and history ports after this bounded leaf.

## Handoff

ALIGN.1–4 and ALIGN.5a/b are complete. The autonomous run resumes at **ALIGN.5c / CTUNE.1** on
`feature/language-neutral-foundation`, base commit
`8ce6bc0` (audit, documentation, evidence ledger and checker checkpoint). The preceding
baseline was `ea85ddd42f418cdf81f55638a2e8afd0af848daf`. Recheck Git status and preserve any
ongoing ALIGN.5 edits before continuing. The last separately qualified executable remains
the source checkpoint recorded above; the new checkpoint has the working-tree full gate
recorded under ALIGN.3d.
ALIGN.4 does not authorize changing sealed normative assets or moving data authority.
The coordinator owns Git state and heavy checks; workers own disjoint paths and targeted
checks. No runtime source change is required for the initial documentation correction.
