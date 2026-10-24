# First native preset registration — Cerebras

Resume from the first unchecked box. This is a bounded SDK.8a execution leaf;
the parent SDK milestone stays unchecked after this one-provider tranche.
The coordinator owns Git, generated files, contract decisions and shared heavy gates.

## Settled scope and reasons

- Register **Cerebras only** in `ProviderRegistry.CreateDefault()`, reusing its existing
  generated descriptor and OpenAI chat adapter. No new public opt-in API, vendor SDK,
  Python runtime dependency, dialect flag or duplicated preset metadata.
- Reference executable: `4faf9ecb22206715e01f8bd2faff8a39defe5565`, tree
  `44f6f2499762f11280badf16039034e35604fc4d`; parent reconciliation `753f5ac`.
- Before qualification native defaults are four descriptors/seven operation bindings.
  The intended result is five/eight. Python stays 106 descriptors/129 bindings;
  generated preset rows stay 86. Pending source memberships become 121 only after acceptance.
- The selected row must have exactly source operation `generation`, exactly native
  `InferenceOperation.Generation`, and an empty `PendingNativeParity`. Fail construction
  if these conditions drift; do not silently register a partially implemented source row.
  Mixed-operation presets, Reka, SambaNova, Watsonx and all other inert rows stay excluded.
- Current official Cerebras documentation confirms `max_tokens` aliases
  `max_completion_tokens`; send only the existing `max_tokens` field. Version 2 is the
  default at `/v1`; no new mandatory version header is justified.
- Official OpenAPI-generated SDK types at revision
  `cacaf754daf384c7066e6584f06363b6f15f8599` expose `stream_options.include_usage`,
  resources forward it, and the SSE decoder recognizes `[DONE]`. These primary sources
  close the prior HTML evidence gap. They do not establish authenticated server behavior.
- Hosted Cerebras traffic is not live-verified. Keep model-specific tools/schema/reasoning,
  retry/header and exact error-payload limitations explicit. Do not invent model limits,
  static catalogs or pricing. Existing capability provenance is not a live certification.
- This registers existing shared generation semantics and corrects a wire snapshot.
  It changes no normalized core result or released corpus. No new normative release,
  sealed assets or dependency-floor change is needed. Refresh generated provenance when
  a hashed contract changes, while proving descriptor semantics remain unchanged.
- Preserve shared redirect policy, native TLS limits, ownership/cancellation and the
  historical external-close five-second diagnostic; this tranche does not close them.

## Ownership and gates

Workers are not alone in the tree. Re-read a shared file before any minimal edit,
preserve peers' changes and never mutate Git. Root serializes checklist write leases
and runs all compilation, tests, package work and broad gates. A worker reports its
box ready, then receives the checklist write lease before ticking that box.

- [x] **CPR.0 — Research and execution contract (root).** Refresh only the Cerebras
  section of `contracts/openai-compat-presets.md` using sources fetched 2026-10-24;
  retain an explicit hosted-unverified watchlist. Record primary SDK revision and
  source distinctions. Check this leaf against actual registry/exporter/factory seams.
  Gate: no unresolved wire contradiction affecting the selected dialect; exact source
  operations, contract dependencies and native count consequences are explicit.
  > NOTE: 2026-10-24 current primary HTML and pinned official SDK sources are saved;
  > independent Terra-high review found no P1/P2 in contract/registration scope. No
  > Python production or released-specification change is adopted. Hosted traffic
  > remains unverified. Root Release examples execute; the first targeted test compile
  > exposed two mechanical test-only errors, retained under `cerebras-focused-first`.
  > NOTE: The first full run passed 23/25 gateway steps, native1113/conformance93,
  > package/examples and strict docs. Seven Python freshness failures and the generated
  > preset check require the raw contract digest refresh; this is a failed full gate.
  > Canonical regeneration changes one of49 source digests and only the inventory SHA
  > in the generated table, with all descriptor facts equal. The source slice therefore
  > also owns `maintenance/provider-parity/python-builtins.json` and the generated
  > `CompatPresetTable.g.cs`; root updates proof pins and reruns the full gate.
- [x] **CPR.1 — Registration and maintenance binding (implementation worker).** Own
  `src/csharp/AnyInfer/Providers/ProviderRegistry.cs`,
  `src/csharp/AnyInfer/Providers/CompatPresetData.cs`,
  `src/csharp/AnyInfer.Maintenance/Program.cs`, and
  `scripts/check_csharp_binding_inventory.py`. Add a private reviewed-row admission
  helper with the source/native operation and pending-list guards above. Register only
  the generated Cerebras descriptor. Clarify that the table is separate data from which
  reviewed entries can be selected. Export dependencies for Cerebras exactly:
  `contracts/openai-compat-presets.md`, `contracts/openai-compat-presets.md#cerebras`,
  `contracts/openai-compat.md`. Resolve a dependency's physical file before `#` while
  retaining the full fragment-bearing value in output. Keep unsupported-provider
  rejection and all context/provenance validation. Update the exact sorted eight-binding
  expectation. Gate: source review, solution compilation and real maintenance exporter
  check; no provider-id branch in inference translation.
  > NOTE: Source/contract review, the real eight-binding exporter, solution compilation,
  > and the full gate passed under `cerebras-full-second`; clean acceptance is in CPR.5.
- [x] **CPR.2 — Independent native controls (controls worker).** Own
  `src/csharp/AnyInfer.Tests/CerebrasRegistrationTests.cs` and the registry-disjointness
  assertion in `CompatPresetDataTests.cs`. Test the default registry rather than manually
  registering a table row. Assert exact five IDs/eight bindings, generated descriptor
  metadata, aliases/setup/auth/default URL/source operations, inert remaining rows,
  generation-only admission and unsupported retrieval. Use actual public AsyncClient
  final factories with bounded scripted/loopback transport for buffered and streaming
  generation, final usage, reasoning minimal-to-low mapping, tool/schema wire shapes,
  listing and health, error classification/oversize refusal, lazy credentials/transport,
  cancellation and borrowed-handler ownership. Reuse established helpers without widening
  production interfaces. Do not weaken existing tests or treat offline responses as live
  service evidence. Gate: independent causal controls compile and pass with existing
  OpenAI/preset/config/ownership and redirect regression tests.
  > NOTE: Four Cerebras public-factory controls passed; the final full second run passed
  > native1113/conformance93 and 31 freshness controls, and independent controls review
  > was clean. Clean-checkout qualification is recorded in CPR.5.
- [x] **CPR.3 — Documentation and executable delivery (docs worker).** Own
  `docs/guides/csharp-sdk.md`, `docs/reference/csharp-sdk.md`,
  `docs/guides/python-to-csharp.md`, `examples/csharp-sdk/CerebrasExample.cs`,
  `examples/csharp-sdk/Program.cs`, and the external consumer text in
  `scripts/check_csharp_package.py`. Show native `cerebras:model` using ordinary
  ProviderSettings and explicit credential reference, with no generic-provider workaround.
  The exact included example runs offline in the existing example verifier, and the
  package-only consumer exercises default registration. State hosted traffic remains
  unverified and other presets remain unavailable. Do not alter Python provider counts,
  generated Python index/matrix or claim complete SDK support. Gate: exact examples and
  isolated package consumer execute; strict docs build succeeds.
  > NOTE: The exact source-linked Release example, isolated package-only consumer, and
  > strict docs all passed under `cerebras-full-second`; independent docs review was
  > clean. Hosted traffic remains unverified; clean qualification is recorded in CPR.5.
- [x] **CPR.4 — Review and held-source gate (root).** Inspect all worker diffs and run
  independent review, then serialize targeted native tests, generator `--check`, actual
  eight-binding exporter check and package/examples. Run the repository's full
  `workspace.py check` gateway with retained output, Python totals/skip reasons and
  source/Git guards. Record explicit Frozen DEVELOPMENT 102/0/0/0, native/conformance
  totals and the existing five paired reports. No concurrent heavy suites.
  Gate: all registered checks pass, no unexplained source drift, all prior behavior
  profiles and released specification assets remain unchanged.
  > NOTE: `cerebras-full-second` passes all25 checks:4531 Python passes/10 documented
  > platform skips,1113 native unit/93 conformance, five paired reports42/29/32/43/10,
  > package/examples/strict docs and Frozen DEVELOPMENT102/0/0/0. All1275 input maps
  > and source/Git state match. Independent full evidence review is bounded clean.
  > The earlier failed full run remains retained. No hosted or release claim follows.
- [x] **CPR.5 — Source checkpoint and clean qualification (root).** Commit only the
  explicit completed source paths after the full gate. Never stage `uv.lock` or
  `v/cache/nodeids`. In a fresh selected clean checkout, bind actual commit/tree and
  source hashes, run the registered C# gate, Cerebras-focused controls, isolated package
  consumer/examples and Frozen 102. Verify initial/final clean identity and source maps;
  retain failures as failures. Gate: independent review of actual clean evidence.
  > NOTE: Source `a51f58461416ed869a2f7d8699deb04903be0086`, tree
  > `094f2d6f19dcf7607d9b675c26f7f641c239728f`, qualifies from a fresh checkout.
  > All12 registered C# steps pass:1113unit/93conformance, five source-clean paired
  > reports42/29/32/43/10, generator/bindings/package/examples and Frozen102/0/0/0.
  > Additional redirect56 and Cerebras4 TRX controls pass. All1266 selected tracked
  > hashes,15 normalized root/selected source bodies, clean commit/tree/status and root
  > protected user inputs are unchanged. Independent clean evidence review is bounded
  > clean. Root evidence `.tmp-tests/cerebras-clean-first-cerebras-clean-root/`; selected
  > evidence `.tmp-tests/local-redirect-a51f5846-20261024T103333Z/` in the fresh worktree.
- [x] **CPR.6 — Reconcile (root).** Update this leaf, parent SDK plan and active artifact
  from achieved evidence, preserving executable identity separately from plan-only edits.
  Record five/eight and 121 pending only after qualification. Leave SDK.8a and all broader
  unimplemented milestones unchecked. Gate: bounded plan/evidence consistency review.
  > NOTE: Independent parent/leaf/artifact critique is bounded clean. The separate
  > two-plan reconciliation commit preserves source `a51f584` and its clean qualification.
  > Resume SDK.8a with Hyperbolic's researched endpoint migration and registration contract.

## Exact execution entry points

- Native commands run from `src/csharp` so `global.json` selects SDK 8.0.426.
- Targeted native command: `dotnet test AnyInfer.Tests/AnyInfer.Tests.csproj --no-restore
  --filter "FullyQualifiedName~CerebrasRegistrationTests|FullyQualifiedName~CompatPresetDataTests|FullyQualifiedName~OpenAIChatTests|FullyQualifiedName~ConfiguredTransportOwnershipTests|FullyQualifiedName~Redirect"`.
- Generator: selected `.venv/Scripts/python.exe scripts/generate_csharp_compat_presets.py
  --check src/csharp/AnyInfer/Providers/CompatPresetTable.g.cs` from repository root.
- Maintenance check: selected Python `scripts/check_csharp_binding_inventory.py` from
  repository root executes the actual binding exporter and checks the exact binding set.
- Examples: `dotnet run --project ../../examples/csharp-sdk/AnyInfer.Examples.csproj
  --configuration Release` from `src/csharp`.
- Full gate: selected Python `workspace.py check`, using the existing reviewed phase/capture
  wrappers only after binding their current hashes. Do not silently run a reduced suite.
- Frozen: `dotnet run --project AnyInfer.Conformance --no-build --no-restore -- --root
  <selected-specification> --development --output <retained-report>` from `src/csharp`.

## Resume record

2026-10-24: CPR.0–6 are complete; resume SDK.8a with the researched Hyperbolic endpoint
migration and native registration contract. Qualified executable checkpoint
`a51f58461416ed869a2f7d8699deb04903be0086`, tree
`094f2d6f19dcf7607d9b675c26f7f641c239728f`, contains exactly15 explicit source files;
plan edits and protected user inputs were excluded. A fresh selected worktree is at
`C:/Users/antho/.traycer/worktrees/anthturner__anyinfer/feature-cerebras-clean-a51f584`.
The verified-buffer launcher binds this exact commit/tree plus all15 normalized source
bodies. The registered C# gate, redirect preservation, Cerebras controls and Frozen102
pass with bounded independent evidence review. Default native registration is five/eight;
Python remains106 descriptors/129 bindings and86 generated preset rows, with121 source
operation memberships pending. The next work after the separate reconciliation commit is
SDK.8a further provider research/registration. Hyperbolic research found an upstream
endpoint migration requiring a coordinated Python/native wire-only correction before
registration; Inference.net stream-usage details remain unverified. Neither is registered.
