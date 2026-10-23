# Correct current preset authentication before the native data port

Resume from the first unchecked box. This is a bounded SDK.8a prerequisite under the
existing full-core implementation authorization. It corrects two researched Python preset
declarations before those facts become native preset data. It does not complete SDK.8a,
add native bindings, or certify live provider availability.

## Accepted starting point and scope

- Inventory source: `830673e56437a695ae26f579d7ca264139b7b0ba`, tree
  `35f35ca6a6a76291c0fe0fdf82affa6e4499cd88`; plan-only acceptance:
  `a8fd38b3fe995de685f7f366d85353e887729e50`. The inventory leaf is complete.
- Follow `contracts/NEW-PROVIDER.md` and `contracts/PROPAGATE-CHANGE.md`. Research and
  independent critique are retained under task artifacts
  `csharp-sdk/sdk-eight-providers/{preset-auth-research,preset-auth-contract-review}`.
  Root fetched the current primary references independently on 2026-10-23 UTC.
- Reka's current chat and model-list references both document
  `Authorization: Bearer <key>` at `https://api.reka.ai/v1`:
  `https://docs.reka.ai/chat/api-reference/create-chat-completion` and
  `https://docs.reka.ai/chat/api-reference/list-models`.
  Adopt `auth_header="bearer"` for this preset. Whether the service still accepts
  undocumented X-Api-Key, a current release/changelog pin, and a machine-readable current
  API/auth schema remain unverified; do not invent them or claim live verification.
- Lemonade stable `v2026.43.3`, commit
  `b48d190a9b00a417fda9cbf206fcec5691e5578b`, documents optional HTTP Bearer auth when
  `LEMONADE_API_KEY` is set. Root inspected the pinned config docs and HTTP auth source:
  `https://github.com/lemonade-sdk/lemonade/blob/b48d190a9b00a417fda9cbf206fcec5691e5578b/docs/guide/configuration/README.md`
  and `src/cpp/server/server.cpp` at the same revision. The release page is
  `https://github.com/lemonade-sdk/lemonade/releases/tag/v2026.43.3`.
  Adopt `accepts_api_key=True`, `key_env="LEMONADE_API_KEY"`, keep
  `requires_api_key=False` and the existing Bearer transport. The RC evidence is
  supplementary, not the supported version boundary. A real pinned-server probe remains
  explicitly unverified; a mock transport is not a live-server certification.
- `accepts_api_key` continues to control generic setup-field presence. Do not introduce
  rejection/omission of manually configured keys, a new auth policy, an admin credential,
  environment auto-discovery, query injection, or privilege behavior.
- Preserve TabbyAPI's x-api-key dialect and Docker Model Runner's absent setup field.
  Explicit caller headers keep their existing precedence. No new operation/capability,
  model catalog, pricing, output default, URL, or non-auth quirk is adopted here.
- This is provider-specific wire/setup metadata with no shared normalized-spec delta.
  Frozen release assets, expectations and all accepted profile assets stay byte-identical.
  Current C# has neither Reka nor Lemonade/preset bindings; record them as unsupported,
  retain the registered C# gate, and do not imply native provider support.
- New immutable declaration: `maintenance/changes/compat-preset-auth.json`, id
  `compat-preset-auth`. Use the actual versioned change schema/implementation registry,
  contract `contracts/openai-compat-presets.md`, inference generation, adopted/no_delta,
  Python updated with all four registered Python gates, C# unsupported with its registered
  csharp-workspace gate and the precise absent-binding rationale. Source entries identify
  the exact fetched Reka pages and stable Lemonade docs/source/tag. The declaration records
  required work, never passed outcomes. Do not edit it after committing a qualifying input.

## Execution checklist

- [x] **AUTH.0** Coordinator: classify the current evidence and settle the narrow adoption.
  Gate: both Reka references agree; Lemonade stable docs/source agree; bounded critique's
  two P2s are included, and unknown/live facts stay explicit.
  > NOTE: The two P2 corrections add Lemonade's conventional key_env and account for the
  > generated conformance-matrix/PINV witnesses plus default/caller-override controls.
- [x] **AUTH.1** Contract author: own only `contracts/openai-compat-presets.md` and the new
  immutable declaration, plus minimal updates to this box after re-reading. Correct the
  shared auth summary and the two auth statements with per-entry auth-rechecked date and
  cited current sources. Preserve unrelated historical findings/dates; mark them as not
  rechecked if needed. Explain HTTP versus WebSocket query auth and named unverified gaps.
  Gate: declaration schema validates and independent contract critique closes before code.
  > NOTE: Author handoff records Reka's current documented chat/models Bearer auth and
  > Lemonade stable v2026.43.3 optional HTTP Bearer auth at
  > b48d190a9b00a417fda9cbf206fcec5691e5578b. The contract retains earlier non-auth dates
  > as not rechecked, distinguishes WebSocket query compatibility, and names the remaining
  > Reka/live-server gaps. `compat-preset-auth.json` validates against
  > `maintenance/change.schema.json`; `validate_contracts.py` intentionally excludes the
  > fleet-level preset contract. Rereview adds the planned `workspace.py` and
  > `tests/test_workspace.py` closure, names the unlocated Reka provenance/schema evidence,
  > and distinguishes unchanged shared-spec inventories from the regenerated Python parity
  > witness. Independent exact correction rereview closes the two P1s and one P2;
  > this contract-only gate is complete. Runtime implementation and qualification remain open.
- [x] **AUTH.2** Preset implementer after AUTH.1: own only
  `src/python/anyinfer/providers/presets.py` and `tests/test_presets.py`. Apply the settled
  Reka/Lemonade fields and remove obsolete public docstring/note claims without adapter
  logic changes. Gate: actual mock `/models` and chat requests prove Reka Bearer/default
  and caller override, Lemonade with/without optional key and no query injection; setup
  field is optional/advanced with correct env/placeholder; preserve Tabby x-api-key and DMR
  no-field/direct-key behavior. Run the narrow preset test module and targeted Ruff only.
  > NOTE: Reka now declares Bearer; its public-client control captures `/models`, chat, and a
  > caller Authorization override. Lemonade declares optional `LEMONADE_API_KEY` setup and
  > captures keyless/keyed `/models` calls with no query injection. The DMR control retains no
  > setup field while permitting direct configured Bearer input. Focused pytest passed 130 at
  > `.tmp-tests/preset-auth-implementation/junit.xml`; targeted Ruff format/check and scoped
  > diff check passed. AUTH.3 owns the matrix renderer, generated witnesses, and broader gates.
- [x] **AUTH.3** Coordinator: serialize existing generators after all source edits:
  provider index, conformance matrix, then provider-parity exporter and `--check`.
  Inspect the generated diff and retain all historical baseline fields and operation flags.
  Gate: stale-claim scan, preset/inventory/maintenance focused controls, independent actual
  source review, and coherent full `workspace.py check`; no broad generated content drift.
  > NOTE: Root owns the `workspace.py` quirk-axis replacement from Reka to TabbyAPI;
  > an independent controls author owns only the causal `tests/test_workspace.py` control.
  > The source/declaration closure includes both files. This preserves actual x-api-key
  > coverage after Reka switches to Bearer, and the matrix remains generator-produced.
  > NOTE: Actual collector/render control passes 1/1; the preset module passes 130/130.
  > Serialized provider-index generation leaves docs/providers/all.md unchanged; matrix
  > generation changes only its actual date and representative row/prose. Fresh exporter
  > --check and 48 inventory/binding/maintenance controls pass at
  > .tmp-tests/preset-auth-generated-first. Snapshot SHA
  > 47c2f58b2f4a8f9d0586c6f8ff92a171de485ef7cc73dfe496a679180e132b16 retains 106/129/49;
  > only the two adopted provider rows and two raw source hashes differ. Full workspace
  > and independent source review remain pending before committing the explicit input set.
  > NOTE: Independent actual source/witness review is bounded clean. Root's coherent full
  > workspace passes all 24 steps in 181.0s at
  > .tmp-tests/preset-auth-full-first/workspace.txt. All 11 held input digests and eight
  > protected file digests match after execution; no unrelated/generated changes occurred.
  > The earlier pending note records sequence only. Root is committing the explicit source
  > set before the fresh clean registered/Frozen qualification in AUTH.4.
- [x] **AUTH.4** Coordinator: commit explicit owned paths, then qualify the immutable
  declaration in a fresh clean selected checkout through both registered producers, all
  five registered gates and pure aggregation. Verify exact declaration/registry/source/run
  bindings; preserve prior profiles and run Frozen DEVELOPMENT 102/0/0/0 with release hash
  unchanged. Gate: clean before/after, independent evidence review and no false local/live
  verification claim. Parent SDK.8a/6c/8b-c and all root API rows remain unchecked.
  > NOTE: Explicit source set is committed at
  > c3d0e9a0d26bd253d58620f4bca623c02fac3d85, tree
  > 1c7c12b0c0e0704a940e68adfaed9d1374f1f1e1. Fresh managed checkout
  > feature-preset-auth-clean-c3d0e9a starts clean and matches declaration SHA
  > d261e8f00e048fe6df5dafbb25f89f7f283bb273e0c1c3997b5296ce1ac9e4e1.
  > The independently reviewed operator now requires every one of all five gate records
  > to pass with exit zero, even for unsupported/unbound C# presets. Real attempt 1,
  > local-preset-auth-c3d0e9a0-20261023T041723Z, passes all five registered gates and pure
  > aggregation, with matching two inventory/two verification records and clean state
  > before/after. Aggregate SHA
  > a7b00ba5d66ae0d22bf1ceb9603bb4f9230396683d3ed404ba337a5ddaf6fa74;
  > Frozen DEVELOPMENT 102/0/0/0 report SHA
  > 9112b6088f05939ec2a2dd25081c75a958fc51d949c8a4de0e696493a431d008,
  > unchanged release input 16122cca198d9e688d3c4b5724ac11f0324a4390d8e8589e443fe04a48e81391.
  > Independent evidence review is bounded clean. C# workspace continuity (11/11 steps,
  > prior profile pairs/package/examples) passes; native Reka/Lemonade bindings remain absent.
- [x] **AUTH.5** Coordinator: record the accepted source separately from plan-only
  reconciliation and resume the reviewed native preset runtime contract. Gate: the pending
  129-operation inventory remains visible and no generation-only provider waiver appears.
  > NOTE: Accepted executable source remains c3d0e9a0d26bd253d58620f4bca623c02fac3d85;
  > this plan-only reconciliation does not replace it. Inventory is still 106 providers/
  > 129 Python operations versus seven native bindings, with 122 pending. Parent SDK.8a,
  > SDK.6c/8b-c and all 235 root API rows stay unchecked. Resume the native preset data/
  > runtime boundary under the existing full-core authorization; no new go-ahead is needed.

## Ownership and resume

Workers are not alone: re-read shared plans before minimal box updates, add a `> NOTE:` for
deviations, and never change another owner's files or Git state. Root owns shared plans,
LF attributes, generated witnesses, explicit commits, .NET/native/full/clean gates and final
acceptance. Use `.venv/Scripts/python.exe`, disabled cacheprovider, fresh ignored JUnit/temp
paths and an external pytest basetemp for full/clean qualification. Preserve user-owned
`uv.lock` and `v/cache/nodeids`. This leaf is complete at accepted source checkpoint
`c3d0e9a0d26bd253d58620f4bca623c02fac3d85`. Resume parent SDK.8a's reviewed native
preset runtime/data contract; source qualification remains separate from plan-only acceptance.
