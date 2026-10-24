# Hyperbolic endpoint migration and native registration

Resume from the first unchecked box. This executes a bounded tranche of SDK.8a;
the parent provider milestone and overall SDK remain incomplete. Root owns decisions,
Git, contract text, generated metadata, shared plans and all heavy execution.

## Settled contract

- Baseline executable: `a51f58461416ed869a2f7d8699deb04903be0086`, tree
  `094f2d6f19dcf7607d9b675c26f7f641c239728f`. Its Cerebras plan reconciliation is
  the separate `94f348c04838d57d3eca26aecde1155ca267fde5`.
- Adopt the current provider-owned migration notice: replace the default
  `https://api.hyperbolic.xyz/v1` with **`https://api.hyperbolic.ai/inference/v1`**.
  The old host is explicitly decommissioned. Requests must retain `/inference/v1`
  when appending `models` and `chat/completions`.
- Root fetched the official overview, text API reference, errors and changelog on
  **2026-10-24** and refreshed only the Hyperbolic section of
  `contracts/openai-compat-presets.md` before production implementation. Sources:
  `https://www.hyperbolic.ai/docs/inference/overview`,
  `https://www.hyperbolic.ai/docs/inference/text-apis`,
  `https://www.hyperbolic.ai/docs/inference/errors`,
  `https://www.hyperbolic.ai/docs/changelog` and `/docs/llms.txt`.
- Preserve existing Python behavior fields: Bearer auth, `HYPERBOLIC_API_KEY`,
  generation-only operations, model listing, `max_tokens`, no reasoning translator,
  existing feature provenance and empty ignored-parameter list. Do not infer capabilities
  from a model name or add key-prefix/account validation. New documentation about tools,
  schema and reasoning stays model-specific information, not a capability expansion.
  Correct the stale descriptive note to `Open-model serving; reasoning output varies by
  model.` because current docs distinguish separate reasoning fields from inline thinking.
  This is explanatory metadata; it does not change feature flags or translation.
- The reference explicitly documents SSE `data:` chunks, `[DONE]`, and a final usage
  chunk when `stream_options.include_usage=true`. Keep the shared adapter's existing
  stream behavior. No dedicated provider dialect or vendor SDK is justified.
- Hosted behavior remains unverified. Keep the conflicting 401-envelope documentation,
  exact streaming errors, retry/rate header names, deployed model availability and any
  additional version pin in the contract watchlist. No provider call, credential,
  static catalog, model ceiling or pricing pin is part of this tranche.
- This corrects wire addressing while preserving normalized behavior. No new shared
  specification profile/release or frozen-asset change is required. Record the adopted
  finding and affected binding closure under `contracts/PROPAGATE-CHANGE.md`; use only
  the existing declaration schema, implementation registry and registered runners.
  A requirement to weaken or change control-plane policy is a separate blocker.
- Execution boundary: this is the user's existing coordinator-directed SDK work, not
  the scheduled contract-drift proposal/publisher flow. The latter's
  `scripts/check_provider_change_proposal.py` deliberately rejects metadata and scripts
  outside registered roots. Its module/check docstrings and
  `.github/workflows/contract-drift.yml` capture/publish jobs define that untrusted bundle
  boundary; it is not called by `run_provider_change_checks.py`,
  `check_provider_change.py`, or the normal `ci.yml` propagation path. We do not submit
  this tranche to that automated publisher or claim its guard accepted it. Do not edit
  that guard, its allowlist/tests, implementation registry, schemas, command runner or CI.
  Root's explicit path inventory, canonical regeneration, independent source review and
  full/clean source maps provide the local changed-path accounting. Registered runners
  and the pure aggregate still verify binding closure and actual same-run gate evidence.
  Adding exact binding expectations/package-consumer coverage is implementation data/test
  maintenance, not permission to weaken policy. This distinction must receive separate
  cold review before HYP.1–3 dispatch. Any later automated publishing remains outside scope.
- Add only the generated Hyperbolic descriptor to the default C# registry, using the
  existing private `SelectReviewedGenerationPreset` guard and shared OpenAIChatAdapter.
  Keep exact source/native generation-only and empty-pending admission. No new public API.
- Before acceptance native defaults are **5 descriptors / 8 bindings**, with 121 pending
  source operation memberships. The intended result is **6 / 9 / 120**. Python stays
  **106 descriptors / 129 bindings**; the generated table stays **86 rows**.
  All other inert rows, mixed operations and broader SDK milestones remain open.
- Preserve the accepted redirect/ownership/cancellation/TLS boundaries and historical
  native external-close five-second diagnostic. This provider tranche does not close them.

## Ownership and execution rules

Workers are not alone in the tree. Preserve peer changes, re-read each shared file
immediately before a minimal edit and never change Git state. No worker edits generated
files, shared manifests or plans without an explicit root lease. Each worker owns its box;
report source-ready first, then re-read this whole leaf and tick only the leased box after
root verifies its named gate. Record any deviation as a `> NOTE:` beside that box.
Root serializes generators, native builds, package work and full suites. Source checks
may run concurrently only on disjoint owned paths. No broad test weakening or expectation
regeneration to hide failures. Use the selected `.venv/Scripts/python.exe`.

- [x] **HYP.0 — Adopted evidence and execution contract (root).** Complete the refreshed
  Hyperbolic snapshot and this leaf; account for Python Hyperbolic generation, the newly
  selected native binding and inherited shared chat dependencies in a schema-valid impact
  declaration. Keep declaration input separate from run outcomes.
  The declaration is `maintenance/changes/hyperbolic-base-url.json`, scoped to the
  exact `contracts/openai-compat-presets.md#hyperbolic` dependency so unrelated presets
  are not falsely classified as endpoint changes. Required registered gates are
  Python contracts/fixtures/conformance/tests and native `csharp-workspace`.
  > NOTE: Initial critique correctly observed that the scheduled proposal guard rejects
  > required generated/script paths. Root inspected the guard's actual call sites and the
  > registered runner/aggregate: that publisher is not the execution path for this SDK
  > tranche. Separate cold review withdrew the prior P1 and found the recorded execution
  > boundary bounded clean. No guard acceptance, changed allowlist or automated PR
  > publication is claimed. Contract/declaration/counts and actual registered gates are
  > independently reviewed; production implementation can now proceed.
  Verify inventory/source closure and exact count arithmetic. Obtain cold contract/plan review.
  Gate: no unresolved dialect or control-plane contradiction; snapshot precedes production
  code, hosted gaps are explicit and affected registered gates are named.
- [x] **HYP.1 — Minimal production and binding changes (implementation worker).** Own
  `src/python/anyinfer/providers/presets.py` (Hyperbolic base URL and the exact explanatory
  note above only),
  `src/csharp/AnyInfer/Providers/ProviderRegistry.cs`,
  `src/csharp/AnyInfer.Maintenance/Program.cs`, and
  `scripts/check_csharp_binding_inventory.py`. Add
  `SelectReviewedGenerationPreset("hyperbolic")`; retain the existing private guards.
  Add the literal dependencies `contracts/openai-compat-presets.md`,
  `contracts/openai-compat-presets.md#hyperbolic`, `contracts/openai-compat.md` to the
  maintenance switch, preserving physical-path-before-fragment validation and exact output.
  The checker asserts the exact sorted nine bindings; do not widen generic registration.
  Gate: scoped Ruff/format/py_compile and whitespace checks, cold source review, root solution
  compilation and real nine-binding exporter check.
  > NOTE: Root's source review identified the retained inline-thinking note as broader
  > than current model-specific docs. The exact descriptive correction above is adopted;
  > all behavior fields remain fixed. Include it in independent metadata-diff review.
  > NOTE: Source review, focused batch, and the actual full-second exporter/compile gates pass;
  > clean and registered acceptance remain pending HYP.5.
- [x] **HYP.2 — Independent public controls (controls worker).** Own
  `tests/test_presets.py`, `src/csharp/AnyInfer.Tests/HyperbolicRegistrationTests.cs` (new),
  `src/csharp/AnyInfer.Tests/CerebrasRegistrationTests.cs`, and
  `src/csharp/AnyInfer.Tests/CompatPresetDataTests.cs`. Python must use public AsyncClient
  with implicit preset URL and scripted transport: listing, buffered and streaming
  generation all retain the full new prefix; assert Bearer, `max_tokens`, absence of
  `max_completion_tokens`/`reasoning_effort`, include_usage and actual final usage.
  Native controls use the real default factory, with exact six IDs/nine bindings,
  generated descriptor/setup/source metadata, generation-only admission, all remaining
  rows and aliases inert, `/inference/v1/models` GET and `/inference/v1/chat/completions`
  POST. Cover buffered/SSE final usage, error/size behavior, unsupported retrieval without
  send, explicit lazy credentials, cancellation identity and borrowed-handler disposal.
  Reuse established public behavior; don't manufacture a schema capability. All waits
  must be finite and readiness-driven. Update the existing Cerebras/default inert-row
  assertions minimally to admit exactly the two reviewed rows. Root alone supplies the
  regenerated inventory hash once stable. Gate: independent causal review and root's
  retained targeted Python/native runs pass, with no hosted-service claim.
  > NOTE: The prescribed two P2 deltas were independently and root reviewed. The first
  > focused run passed 131 Python and 129 native cases, including four Hyperbolic and four
  > Cerebras controls, with zero skips; full-second passed 1117 unit and 93 conformance.
  > Clean and registered acceptance remain pending HYP.5.
- [x] **HYP.3 — Docs and executable delivery (docs worker).** Own
  `docs/guides/csharp-sdk.md`, `docs/reference/csharp-sdk.md`,
  `docs/guides/python-to-csharp.md`, `examples/csharp-sdk/HyperbolicExample.cs` (new),
  `examples/csharp-sdk/Program.cs`, and `scripts/check_csharp_package.py`.
  Show ordinary `ProviderSettings.Of("hyperbolic", apiKey: "env://HYPERBOLIC_API_KEY")`
  and a discovered model target. The executable offline example may use the documentation's
  `glm-5.3-flash` identifier with an explicit no-static-catalog qualification. Validate the
  new default URI prefix/auth/body/result/disposal in the exact source-included example
  and isolated package-only consumer. Preserve the Cerebras example. Describe both reviewed
  presets and distinguish them from all remaining inert rows. Include the endpoint migration
  and hosted-unverified status; do not reference plans from docs or duplicate a snippet that
  cannot execute. Gate: scoped Ruff/format/py_compile/whitespace, independent review, root
  Release examples, isolated consumer and strict docs pass.
  > NOTE: Source/docs review is clean. First focused Release examples passed; the
  > full-second actual isolated package-only consumer, examples, and strict docs passed.
  > Hosted traffic and HYP.5 clean/registered acceptance remain pending.
- [x] **HYP.4 — Canonical metadata and held-source qualification (root).** After all
  contract/production/docs source bytes stabilize, export
  `maintenance/provider-parity/python-builtins.json` with
  `scripts/export_python_provider_parity.py`, then generate
  `src/csharp/AnyInfer/Providers/CompatPresetTable.g.cs` with
  `scripts/generate_csharp_compat_presets.py`. Prove Python descriptor/binding/row counts
  stay106/129/86; only the adopted Hyperbolic URL/setup, explanatory note and source
  provenance may change.
  Root updates the independent expected inventory digest after reviewing semantic diff.
  Check generated provider index/matrix consistency; do not rewrite unchanged artifacts.
  Prepare reviewed, hash-bound proof operators with current metadata pins. Run targeted
  controls, generator check, actual binding exporter, examples/package and applicable
  registered gate components; then one coherent full `workspace.py check`. Obtain the
  formal producer/aggregate evidence in HYP.5 because it requires a clean committed source.
  Retain
  JUnit totals/skip reasons, all registered step outcomes, native/conformance totals,
  five paired reports and explicit Frozen DEVELOPMENT102/0/0/0. Guard all protected
  input bytes and Git identity before/after, including operator helpers and user files.
  Gate: all required checks pass with bounded independent evidence review. Preserve every
  failed attempt as failed; no concurrent heavy suite or reduced-suite completion claim.
  > NOTE: The parallel source wave is held. Canonical regeneration produces inventory
  > `70460ceb665b43f9e9d8251d55495019c9b3e5c72051428b9544918818330b74` and table
  > `fdee9e96ba55ce0f14a75e23cd9d0a3b3b2b4fff487455f7151e9bd1e0736471`.
  > Root's structural comparison retains106/129/86 and all105 other provider records;
  > exactly five Hyperbolic URL/setup values and its note change. The49-source set is
  > unchanged; only contract/presets.py digests change and all match current bytes.
  > Evidence: `.tmp-tests/hyperbolic-metadata-diff.json`; prior raw inputs are retained in
  > `.tmp-tests/hyperbolic-metadata-before/`. Cold review found only two control/comment
  > gaps, closed by exact scheme/host/auth assertions for model/health and provider-specific
  > Cerebras summary wording. The first focused batch passes131 Python cases,129 native
  > cases (including4 Hyperbolic/4 Cerebras/47 preset-data) and Release examples, with zero
  > skips/failures and1275 source maps/exact18 bodies/Git state unchanged. Evidence:
  > `.tmp-tests/hyperbolic-focused-first/`. Full and clean gates remain pending.
  > NOTE: `hyperbolic-full-first` is a retained failure:23/25 steps pass, with the
  > main Python suite and docs-example check both rejecting the stale generated provider
  > index after the explanatory note changed. JUnit records4542 cases/1failure/10platform
  > skips; native1117/conformance93, five profiles, package/examples and strict docs build
  > pass. Source/Git guards have no drift; Frozen was not run. Root canonically regenerated
  > `docs/providers/all.md`; its only diff is the Hyperbolic note. This adds that generated
  > doc path to the declaration and explicit source set (19 functional paths). Inventory
  > and table hashes above remain unchanged. Run a fresh full second attempt; do not
  > relabel the first failure or rerun unaffected focused tests for this generated prose.
  > NOTE: The targeted `docs-check` phase passes after canonical index regeneration;
  > evidence is `.tmp-tests/hyperbolic-docs-correction/`. The clean proof maps/declaration
  > now cover19 paths. The second full attempt uses the unchanged reviewed full operator,
  > common, capture and phase bytes; only the held source/input snapshots advance.
  > NOTE: `hyperbolic-full-second` passes all25 steps:4532 Python passes/10 documented
  > platform skips,1117 native unit/93 conformance, five paired reports42/29/32/43/10,
  > strict docs/package/examples and Frozen DEVELOPMENT102/0/0/0 at unchanged release
  >16122...1391. All1279 maps and Git state match; no changed/unavailable/guard errors.
  > Independent actual full evidence review is bounded clean. Summary:
  > `.tmp-tests/hyperbolic-full-second-summary.json`. The first failure remains retained.
- [x] **HYP.5 — Explicit source checkpoint and clean proof (root).** Commit only this
  tranche's explicit completed source/contract/tests/docs/generated/declaration paths after
  the full gate. Never stage `uv.lock` or `v/cache/nodeids`. Create a fresh clean checkout
  at exact source commit/tree; bind current raw metadata/factory/helper hashes plus root
  versus selected normalized functional source bodies. Run the registered C# and affected
  propagation gates, explicit Hyperbolic/Cerebras/redirect controls, actual package-only
  consumer and examples, and Frozen102. Retain final clean identity and all source maps.
  Gate: real same-source evidence and independent clean review; no hosted/release claim.
  > NOTE: Exactly19 reviewed functional source paths are committed at
  > `b4456054d0d3f6d79113d04714b5c8baf99f2518`, tree
  > `9fcf09fe47641d58d683466beadbabc29155055b`; plans and user files are excluded.
  > Fresh selected checkout:
  > `C:/Users/antho/.traycer/worktrees/anthturner__anyinfer/feature-hyperbolic-clean-b445605`.
  > Initial status is clean. Actual clean C# qualification passes all12 steps,1117 unit/
  >93 conformance, five paired reports42/29/32/43/10,56 redirect controls and8 explicit
  > Hyperbolic/Cerebras controls, package/examples and Frozen DEVELOPMENT102/0/0/0.
  > All1270 selected maps,19 normalized bodies, root user pins and both Git states match;
  > independent evidence review is bounded clean. Evidence: root
  > `.tmp-tests/hyperbolic-clean-first-hyperbolic-clean-root/` and selected
  > `.tmp-tests/local-redirect-b4456054-20261024T112757Z/`.
  > NOTE: The first registered attempt is invalid, not acceptance: pytest parsed raw
  > Windows backslashes in its option string, creating a malformed local temporary tree.
  > The original runner correctly rejected changed controlled inputs; JUnit records4542
  > cases/26 failures/10 skips. All1270 original paths and19 declared source bodies stay
  > unchanged. Root preserved the generated tree with a checked same-volume move into
  > selected `.tmp-tests/failed-registered-first-pytest`, restoring clean status at the
  > same source commit/tree without deletion or rewriting failed evidence. Relocation facts:
  > `.tmp-tests/hyperbolic-registered-first-temp-relocation.json`. The ignored wrapper now
  > uses quoted POSIX path tokens and an exact shlex roundtrip assertion; retry only after
  > exact independent review, using short label `hypreg2`. HYP.5 remains open until actual
  > registered producer/aggregate proof passes. Keep source, plans and helpers fixed during
  > each serial run; outside-Git artifact updates only.
  > NOTE: Before retry, root also corrected the wrapper's report lookup to use the original
  > runner's actual appended `provider-change/<change-id>/<run-id>` directory under each
  > distinct output base. Exact wrapper `f989fcd48802c7c1d07d561adfac14f1c61480e587b868a89a303ea06e65f4f2`
  > passes independent path-map/argument review. No original runner, checker, policy or
  > source byte changes. The `hypreg2` retry uses that admitted buffer at the same source A.
  > NOTE: `hypreg2` executes both original registered producers and the pure aggregate
  > successfully. Its primary JUnit has4532 passes/10 documented skips/0 failures/errors;
  > both contexts bind clean source A, the same run/attempt and actual required passed gates.
  > All1270 maps,19 source bodies, Git states and root user pins match before/after.
  > The wrapper nevertheless remains invalid as written: its only false final predicate is
  > the expected absence of root-only `uv.lock` and `v/cache/nodeids` from the selected
  > checkout. Both unavailable lists contain exactly those two paths; no other path is
  > unavailable. Root and independent review classify this as an external-input boundary
  > error in the ignored wrapper, not a gate or source failure. Preserve that invalid record.
  > A separate, reviewed, hash-bound admission receipt may reuse the actual producer and
  > aggregate evidence only after verifying those exact absences, independent root pins,
  > all other guards and report identities, and rerunning the original pure aggregate.
  > No heavy gate rerun, source change, policy bypass or relabeling is warranted. Receipt
  > input manifest: `.tmp-tests/hypreg2-admission-inputs.json`, SHA
  > `15658c065d271e677efb8bee617df8c74ea12e430224ec255e1d91d53b4d2a86`.
  > HYP.5 stays open until the receipt is independently reviewed and actually admitted.
  > NOTE: Final admission is complete with bounded-clean independent code and actual
  > evidence reviews. The reviewed verifier is `db9bac1a...155af8e`; root receipt
  > `.tmp-tests/hypreg2-admission-c881918201b517cf868028e1/receipt.json`, SHA
  > `add9cbb6dfffd257f13106ad0d345726b746973d6ad27c3bee9099a68617e4e8`, records
  > qualification-complete/no errors. All20 input hashes,1270 selected hashes,19 normalized
  > bodies, root pins and both Git states match before/after; selected stays clean at A.
  > The unchanged original checker exits0 and reproduces aggregate
  > `74df0fe290c17b7871bc605a68bed8e32c3923e5b0d5eea468444299d32e5889` exactly.
  > Both original producers and aggregate bind `hypreg2-registered` attempt1/source A;
  > all five actual gate logs independently match their recorded hashes. Inventories have
  >129 Python and9 native bindings with exact Hyperbolic dependencies. Original full-first,
  > registered-first and wrapper-invalid records remain preserved, not relabeled. This
  > admits source A for native6 descriptors/9 bindings/120 pending memberships; Python
  >106/129 and86 generated rows remain unchanged. Hosted traffic is unverified.
- [x] **HYP.6 — Reconcile (root).** Record accepted executable commit/tree, actual counts,
  exact evidence paths and preserved limits in this leaf, parent and active registration
  artifact. Mark six/nine/120 only after qualification. Leave SDK.8a, broader milestones and
  API completeness rows unchecked. Commit plans separately from qualified executable source.
  Gate: bounded parent/leaf/artifact consistency review and explicit plan-only commit.
  > NOTE: HYP.5 is accepted at executable `b4456054d0d3f6d79113d04714b5c8baf99f2518`,
  > tree `9fcf09fe47641d58d683466beadbabc29155055b`. Parent and active artifacts are
  > reconciled to6/9/120 with the exact full, clean and registered receipt evidence. The
  > independent four-file consistency critique is bounded clean. This checked leaf and the
  > parent form a separate two-plan reconciliation record; executable and user files are
  > excluded. SDK.8a, SDK.6c/8b-c/9–12 and all235 API rows remain open. Resume researched
  > SDK.8a registration; Baseten and Inference.net remain unadopted research.

## Commands and resume record

Native commands run from `src/csharp` under `global.json` SDK8.0.426.
Root's initial targeted native filter is
`FullyQualifiedName~HyperbolicRegistrationTests|FullyQualifiedName~CerebrasRegistrationTests|FullyQualifiedName~CompatPresetDataTests|FullyQualifiedName~OpenAIChatTests|FullyQualifiedName~ConfiguredTransportOwnershipTests|FullyQualifiedName~Redirect`.
Python controls use selected Python and `tests/test_presets.py`, with JUnit in a fresh
ignored output directory. Regeneration uses `--output` with the two canonical paths above;
check the table with `--check`. The real binding check is selected Python
`scripts/check_csharp_binding_inventory.py` from root; it takes no guessed flags.
Registered propagation runs selected Python `scripts/run_provider_change_checks.py
--input maintenance/changes/hyperbolic-base-url.json --registry maintenance/implementations.json
--implementation <anyinfer-python|anyinfer-csharp> --output-dir <ignored-per-implementation-dir>
--trusted-pr-head <exact-source-A> --run-id <one-shared-run-id> --run-attempt 1`.
Use different output roots for the two producers but the same run ID/attempt, source and
immutable input/registry bytes. The runner creates its own nested `provider-change` path;
do not patch it or fake a context. After both producers pass on a clean source A, invoke
the pure `scripts/check_provider_change.py` with their real context/inventory/verification
paths and the explicit changed-path list. Require an actual complete report; dirty held
evidence remains diagnostic only. Never identify these local run IDs as a GitHub CI run.
Release examples use `dotnet run --project ../../examples/csharp-sdk/AnyInfer.Examples.csproj
--configuration Release`. Full gate is selected Python `workspace.py check` through the
reviewed bound capture mechanism. Frozen uses `dotnet run --project AnyInfer.Conformance
--no-build --no-restore -- --root <specification> --development --output <retained-json>`.

2026-10-24: HYP.0–6 are complete. Resume the parent SDK.8a researched registration work.
This plan-only reconciliation remains separate from the qualified executable. Qualification is
complete at executable `b4456054d0d3f6d79113d04714b5c8baf99f2518`, tree
`9fcf09fe47641d58d683466beadbabc29155055b`. Full25, clean12-step C# and actual registered
Python/C# producer/aggregate evidence pass, with bounded independent reviews and the
separate admitted receipt above. Native registration is6 descriptors/9 bindings/120 pending
memberships; Python106/129 and86 generated rows are unchanged. Earlier failures and the
wrapper-invalid record stay retained. The bounded independent reconciliation critique passes;
Baseten/Inference.net are research only. Hosted traffic and broader SDK readiness remain
unverified. No gate rerun is needed for a subsequent plan-only commit.
