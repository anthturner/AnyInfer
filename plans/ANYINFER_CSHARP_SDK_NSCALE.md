# Nscale native generation registration

Resume from the first unchecked box. This executes a bounded part of SDK.8a in
`ANYINFER_CSHARP_SDK.md`; it does not complete provider breadth or the SDK.
Root owns decisions, contracts, generated inputs, shared plans, Git and serial gates.

## Settled scope and evidence boundary

- Baseline is plan-only commit `34cc497ca4fbc793da2af19b35a10a9c2746b09c`, tree
  `3f263ba3367c6bb2f01737a3918ba7b47bb1f9c0`. The qualified SSE executable is
  `d388e6832c0436d9aae3f884ca753cff3837bf0e`, tree
  `faf3154e8091a617902dfc1c97d4482886d4d881`. Preserve its accepted and failed evidence.
- Port only the existing Python `nscale` generation descriptor through the existing
  guarded `SelectReviewedGenerationPreset("nscale")` seam. No Python production or
  preset fields change, no dedicated adapter/dialect/provider branch, no public API,
  capability widening, reasoning-history implementation or new dependency.
- Research fetched 2026-10-24 is recorded before code in
  `contracts/openai-compat-presets.md#nscale`. Current operation pages embed OpenAPI
  3.0.0/info.version1.26.0 and document chat/model endpoints, Bearer service-token
  auth, request fields and typed message/delta/model/usage shapes. There is no
  concrete schema contradiction with the existing generic adapter. This bounded
  admission is faithful Python parity plus offline controls, not hosted certification.
- Exact SSE bytes/terminator, terminal usage timing, reasoning values beyond example
  medium, model features, replay requirements and retry headers remain unverified.
  `text/event-stream` and `stream_options.include_usage` are documented; a literal
  `data:`/DONE example is not. Do not invent it. Native EOF completion removes the
  prior mandatory-DONE discrepancy without establishing upstream behavior.
- Keep `https://inference.api.nscale.com/v1`, Bearer, library convention
  `NSCALE_API_KEY`, `max_tokens`, reasoning effort passthrough and existing features.
  Official examples use `NSCALE_SERVICE_TOKEN`; callers may supply an explicit env
  reference. Use only medium in the new scripted reasoning example; do not imply
  every normalized value is accepted. Tools use auto/none; required is documented
  unsupported. No new local forced-tool policy belongs in this tranche.
- The schema's `reasoning_content` is not preserved by the current generic codecs.
  Disclose this existing limit without asserting a Nscale replay requirement or
  expanding typed history. Account model IDs and live capabilities remain dynamic.
- This selects an existing Python binding without an adopted upstream wire change.
  The contract refresh clarifies documentation and unknowns. No structured upstream
  change declaration, shared-spec/frozen edit, runner/publisher/CI-policy change or
  registered Python/C# propagation claim is needed. Full workspace and the original
  registered C# workspace command still gate actual executable acceptance.
- Baseline defaults were six descriptors/nine bindings/120 pending source memberships.
  Qualified result is seven/ten/119. Python stays 106 descriptors/129 bindings; the
  generated table stays 86 rows. SDK.8a, SDK.6c, SDK.8b–c, SDK.9–12 and all 235 public
  API inventory rows remain open. No authenticated provider traffic or publication.

## Ownership and execution

Workers are not alone: preserve peer edits, never mutate Git, and touch only their
named files. Use `traycer-implement` and `.venv/Scripts/python.exe`. Static Python
checks are Ruff check/format-check and py_compile on owned Python files; whitespace
check all owned paths. No worker runs tests, builds, generators, package/network
operations or heavy gates unless separately assigned. Root runs shared resources
serially. Shared checklist writes require a sole root lease after the owner re-reads
this whole file; tick only the assigned box with a minimal `> NOTE:`.
Never stage, alter, move or remove root `uv.lock` or `v/`.

- [x] **NSC.0 — Research and cold scope critique (root).** Refresh only the Nscale
  contract section from this session's official references, marking every unresolved
  fact and keeping implementation limits distinct. Obtain independent critique of
  this leaf, snapshot, actual source/generated row and evidence boundary. **Gate:**
  no unresolved P1/P2 affecting faithful, bounded native admission.
  > NOTE: Independent scope/source-schema critique is bounded clean after making
  > the exact 16-path map explicit and distinguishing the new test from extensions.
  > Streaming, reasoning and hosted unknowns remain unchanged; no runtime evidence
  > is implied. Dispatch the three disjoint source owners next.
- [x] **NSC.1 — Registration and binding witness (implementation worker).** Own only
  `src/csharp/AnyInfer/Providers/ProviderRegistry.cs`,
  `src/csharp/AnyInfer.Maintenance/Program.cs`, and
  `scripts/check_csharp_binding_inventory.py`. Add only the reviewed Nscale row to
  CreateDefault. Preserve selector guards, collisions and all other registrations.
  Add the literal dependency list `contracts/openai-compat-presets.md`,
  `contracts/openai-compat-presets.md#nscale`, `contracts/openai-compat.md` to the
  maintenance switch and exact sorted ten-binding witness. Keep fragment-aware path
  validation and unsupported-provider rejection unchanged. **Gate:** static checks,
  cold source review and root's actual exporter/compile gates in NSC.4 pass.
  > NOTE: Source/binding review is bounded clean; focused 67 and actual full 25
  > exporter/compile gates passed at source `952b678d2dc020075c09bc6f8d11e2879fc992bd`.
  > Separate clean actual review and NSC.5 acceptance remain pending.
- [x] **NSC.2 — Independent public controls (test worker).** Create only
  `src/csharp/AnyInfer.Tests/NscaleRegistrationTests.cs`. Extend the existing
  `src/csharp/AnyInfer.Tests/CerebrasRegistrationTests.cs`,
  `src/csharp/AnyInfer.Tests/HyperbolicRegistrationTests.cs`, and
  `src/csharp/AnyInfer.Tests/CompatPresetDataTests.cs`. Follow the existing real
  default-registry/factory seams. Assert exact seven IDs/ten bindings, actual Nscale
  generated descriptor identity, source/setup/auth/default URL/features/generation-only
  state, and all remaining rows/aliases inert. Adjust old admitted sets/counts only.
  Do not edit the inventory digest until root supplies the regenerated literal.
  Prove GET models/health are bodyless HTTPS api calls to `/v1/models` with Bearer,
  account model ID extraction, buffered generation, and streaming at clean EOF
  without requiring DONE. Assert actual `stream_options.include_usage`, final
  reported usage and absent usage staying unknown in separate scripted cases.
  Assert max_tokens, no max_completion_tokens, medium reasoning passthrough and
  tools auto under existing feature semantics. Add no provider-side schema/forced-
  tool/capability promise. Cover unsupported retrieval/no send, shared 401 and size
  classification, lazy explicit credential resolution, caller cancellation and
  borrowed handler disposal using existing helpers/patterns. New waits use linked
  15-second deadlines, no sleeps or ambient credentials. **Gate:** cold controls
  review and root's focused compilation/TRX in NSC.4 pass.
  > NOTE: Cold controls review is clean; focused 67 includes Nscale5/Cerebras4/
  > Hyper4/Compat47/ownership7 and full 25 passed 1,135 unit/93 conformance.
  > Actual clean 12 plus 67 controls passed at
  > `952b678d2dc020075c09bc6f8d11e2879fc992bd`/`f5ddbe6d8f12bb9c04ee2b84bb393800908593f8`
  > with independent actual review clean. No hosted claim.
- [x] **NSC.3 — Docs and consumers (consumer worker).** Own
  `docs/guides/csharp-sdk.md`, `docs/reference/csharp-sdk.md`,
  `docs/guides/python-to-csharp.md`, new `examples/csharp-sdk/NscaleExample.cs`,
  `examples/csharp-sdk/Program.cs`, and `scripts/check_csharp_package.py`. Add a
  source-linked ordinary default-client example using
  `ProviderSettings.Of("nscale", apiKey: ..., transport: ...)`, no base URL override,
  and scripted `nscale:meta-llama/Llama-3.1-8B-Instruct`. Default env reference matches
  the descriptor; executable verification injects a literal offline key. Extend
  the existing runner and independent package-only consumer with exact URI/auth/
  model/result/usage/disposal assertions. Update exhaustive registered-preset prose
  to Cerebras/Hyperbolic/Nscale; all other generated rows remain inert. State the
  example ID is not an account catalog guarantee, hosted traffic is unverified,
  exact stream/reasoning limits remain as above, and other broader SDK work stays
  open. No duplicated handwritten C# block or docs-to-plan link. **Gate:** static
  checks, cold docs/consumer review, Release examples, isolated package consumer and
  strict docs phases pass in NSC.4.
  > NOTE: The effort-assertion P1 was fixed in the example and package consumer and
  > independently re-reviewed. Focused rebuilt Release examples, actual full 25
  > isolated package-consumer/examples/strict-docs, and exact clean 12
  > package/examples passed at `952b678d2dc020075c09bc6f8d11e2879fc992bd`/
  > `f5ddbe6d8f12bb9c04ee2b84bb393800908593f8` with independent clean review.
  > Hosted behavior remains unverified.
- [x] **NSC.4 — Metadata and held-source acceptance (root).** Canonically regenerate
  `maintenance/provider-parity/python-builtins.json` then
  `src/csharp/AnyInfer/Providers/CompatPresetTable.g.cs`. Require provider structures
  and the 49-source-path set to be unchanged: only the existing preset-contract
  source digest and resulting inventory pin may change. Supply only the new
  inventory digest to NSC.2's test owner. Check the provider-index generator for
  byte-identical output; no Python preset note changes are authorized. Inspect
  focused native TRX and Release examples plus independent source/controls/docs/
  provenance critique. Then run one coherent `.venv/Scripts/python.exe workspace.py
  check`, retaining primary Python JUnit, original output, five actual paired
  reports and Frozen summary only. Use a separately named reviewed ignored gate
  wrapper, not modifications to accepted SSE/Hyperbolic/Cerebras proof files.
  Record failures honestly. **Gate:** all applicable phases pass, actual source/Git/
  helper/input/pin maps unchanged before/after, fixed source counts verified.
  > NOTE: Canonical regeneration is provenance-only: same provider/non-source data
  > and 49 source paths, only the existing preset-contract source digest changed.
  > Inventory SHA is `f52e835ddc2e9afc62c8796279a1f44dd82faf38f6e2fe894000323d76c7ce7d`;
  > table changes only that pin. Provider-index regeneration is byte-identical.
  > All 16 literal source paths exist and match the separate ignored wrapper's LEAF;
  > root user pins and changed-path scope pass. Independent source/docs/provenance/
  > wrapper review and every runtime gate remain pending.
  > NOTE: All held source/controls/docs/provenance and wrapper reviews are now
  > bounded clean. Review found nested reasoning assertions in the two consumers;
  > both were corrected to top-level reasoning_effort and re-reviewed before any
  > gate execution. Focused-first passes 67 native cases (Nscale5/Cerebras4/
  > Hyperbolic4/Compat47/ownership7) plus rebuilt Release examples, zero skips.
  > All 1,278 guarded inputs, 16 normalized bodies, Git state, helpers and user pins
  > remain unchanged. Actual facts SHA is
  > `59530772b2208488da263886e1a0b40793634476ac222f7ad1d63dde0c99306a`.
  > Full and clean executable acceptance remain pending.
  > NOTE: Full-first now passes all 25 workspace steps: 4,536 Python passes and
  > 10 documented platform skips, 1,135 native unit / 93 conformance cases, package
  > consumer, Release examples and strict docs. Five paired profiles pass with
  > 42/29/32/43/10 matches and zero mismatches; Frozen summary is unchanged
  > DEVELOPMENT/UNRELEASED 102/0/0/0. All 1,278 maps, 16 leaf bodies, helpers,
  > Git state and user pins agree before/after. Facts SHA is
  > `413816d47f51379a0ce5468c0207936007a9f444ed4c897fe4d8942dc8ee0be1`;
  > primary JUnit `c5bb4099a72fb2cab26eb10c4999c2ecb7c0edc36ee34b2025fb2caffd26cf69`.
  > This held-source run is dirty at baseline34cc497, not clean acceptance.
  > Independent actual full-evidence review and clean qualification are pending.
  > NOTE: Independent actual full-evidence review is now bounded clean with no
  > P1/P2; it confirms the exact primary reports, guards and dirty-held-source limit.
  > Clean qualification remains separate. Hold all tracked inputs and plan leases
  > unchanged during that run, then reconcile the source-owner checklists.
- [x] **NSC.5 — Clean executable qualification (root).** Commit exactly the 16
  functional paths below, create a clean checkout at that commit/tree, assert
  selected imports via external root Python and controlled PYTHONPATH, and run the
  selected original `workspace.py check --only csharp`. Require all 12 steps,
  source-clean paired profiles, package/examples and Frozen; additionally run
  no-build/no-restore joined TRX for Nscale/Cerebras/Hyperbolic/Compat controls.
  Frozen output must be under the selected checkout's `.tmp-tests`, not a root
  attempt path. Bind all 16 normalized root/selected source bodies, each checkout's
  actual full tracked/nonignored map and Git root/state, root-only user pins and
  reviewed helper bytes before/finally. Root and selected maps may differ in
  membership but must individually remain stable. Scrub Git environment overrides.
  **Gate:** clean same commit/tree, no drift or missing evidence, independent actual
  evidence review clean. Preserve all prior accepted/failed records.
  > NOTE: Exactly the 16 functional paths are committed at
  > `952b678d2dc020075c09bc6f8d11e2879fc992bd`, tree
  > `f5ddbe6d8f12bb9c04ee2b84bb393800908593f8`. Plans and root user files are
  > separate. Fresh checkout is
  > `C:/Users/antho/.traycer/worktrees/anthturner__anyinfer/feature-nscale-clean-952b678`.
  > Clean execution and independent acceptance are next; do not claim them yet.
  > NOTE: Clean-first is independently accepted with no P1/P2. The selected checkout
  > is clean at the exact commit/tree above; selected import and all12 C# steps pass
  > with1,135 unit/93 conformance, package/examples, the joined67 focused controls,
  > five paired profiles42/29/32/43/10 (zero mismatches) and Frozen DEVELOPMENT102/0/0/0.
  > Root1,278 and selected1,275 tracked/nonignored maps are individually stable;
  > all16 normalized functional bodies, Git roots/states, helper identities and root
  > pins agree. Observer-bearing paired reports identify clean source952b678.
  > Actual facts SHA is `2091e415775fc762387b9fcf80ad3d656eb8f281325c04e792916cd08cb9ebb9`;
  > log `7ddbaccb88e1b1fe7d84ea22eb76e765ba977f75a7d85b7b07526338af819c51`;
  > targeted TRX `5d7b172b048b947c79f4f827429242c49e16c46874c075d0eed79ffd56345e9f`.
  > This final acceptance supersedes the intermediate pending notes above. All
  > worker checklist leases are returned; source and historical evidence are unchanged.
- [x] **NSC.6 — Plan-only reconciliation (root).** Re-read this whole leaf and parent;
  record qualified executable identity, actual counts/gates and remaining unknowns
  in both and active SDK artifacts. Cold-critique the records, then tick this box
  and simultaneously close artifact status. Commit only the two plans separately.
  **Gate:** source and reconciliation identities remain distinct; broad milestones
  remain open; root user inputs and historical evidence unchanged.
  > NOTE: Cold five-record critique is bounded clean after labelling the older
  > parent6/9/120 count as the Hyperbolic checkpoint. Current7/10/119, qualified
  > executable identity and actual full/clean evidence agree. Close both active
  > records with this checklist and commit only the two plans; no gate rerun is
  > needed for this plan-only update. All broader SDK/API rows remain open.

## Exact functional paths

Bind exactly these 16 paths in both root/selected normalized source maps:

1. `contracts/openai-compat-presets.md`
2. `src/csharp/AnyInfer/Providers/ProviderRegistry.cs`
3. `src/csharp/AnyInfer.Maintenance/Program.cs`
4. `scripts/check_csharp_binding_inventory.py`
5. `src/csharp/AnyInfer.Tests/NscaleRegistrationTests.cs` (new)
6. `src/csharp/AnyInfer.Tests/CerebrasRegistrationTests.cs`
7. `src/csharp/AnyInfer.Tests/HyperbolicRegistrationTests.cs`
8. `src/csharp/AnyInfer.Tests/CompatPresetDataTests.cs`
9. `docs/guides/csharp-sdk.md`
10. `docs/reference/csharp-sdk.md`
11. `docs/guides/python-to-csharp.md`
12. `examples/csharp-sdk/NscaleExample.cs` (new)
13. `examples/csharp-sdk/Program.cs`
14. `scripts/check_csharp_package.py`
15. `maintenance/provider-parity/python-builtins.json`
16. `src/csharp/AnyInfer/Providers/CompatPresetTable.g.cs`

No Python production, specification/release, validator, CI, lockfile or generated
provider-index change is included. If a required unexpected source change appears,
stop and return it to root for a scope decision before modifying it.

Root focused native filter is
`FullyQualifiedName~NscaleRegistrationTests|FullyQualifiedName~CerebrasRegistrationTests|FullyQualifiedName~HyperbolicRegistrationTests|FullyQualifiedName~CompatPresetDataTests|FullyQualifiedName~ConfiguredTransportOwnershipTests`.
Run from `src/csharp` with `dotnet test AnyInfer.Tests/AnyInfer.Tests.csproj --no-restore
-m:1`, retain TRX, and join results to definitions requiring every named registration
class. Release example project is `../../examples/csharp-sdk/AnyInfer.Examples.csproj`
from that cwd. Root owns actual argv/output directories and JUnit capture.

## Resume

NSC.0–6 are complete with independent consistency critique. The qualified executable is
`952b678d2dc020075c09bc6f8d11e2879fc992bd`, tree
`f5ddbe6d8f12bb9c04ee2b84bb393800908593f8`. Do not rerun passing gates without a
new cause. Resume further researched SDK.8a
registration. Native defaults are7/10/119; Python106/129 and86 generated rows stay
fixed. Inception/Upstage remain research only. SDK.8a, SDK.6c, SDK.8b–c, SDK.9–12 and
all235 public API rows remain open. No hosted or release/publication claim follows.
