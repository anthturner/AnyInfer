# Expose native model-inventory metadata

Resume from the first unchecked box. This is the descriptive model-inventory prerequisite
within SDK.8a. Existing authorization covers executing the core SDK plan. It adds no
provider registration, model-management engine, connection support or discovery filtering.

## Qualified predecessor and source contract

- Inert preset source `60e39c9ef011d9cbc3a03a61f330e3366e964558`, tree
  `a451153446bc4798c0b2e31a4d0c804109f3abaf`, passed all 25 development steps, clean
  registered 12-step C# gate, 1014 unit/93 conformance controls, five source-clean pairs,
  generator byte equality, package/examples and Frozen 102. Plan-only acceptance is
  `c839f8f4afbeadeb476c45430fc3a538308da5b9`.
- Python `src/python/anyinfer/registry.py::ProviderDescriptor.model_inventory` is a literal
  `available|installed|served`, default `served`. It describes what list_models returns;
  the core does not filter results by it. Python demo consumers use the label, which is
  why retaining it solely in native maintenance source facts does not complete the field.
- `models_listing` is a different private dialect setting. Do not change it, health,
  listing HTTP behavior, operations, routing, source capabilities or model discovery.
- Current accepted inventory is `maintenance/provider-parity/python-builtins.json`, SHA
  `47c2f58b2f4a8f9d0586c6f8ff92a171de485ef7cc73dfe496a679180e132b16`.
  All 86 compat source rows declare served; the source-facts guard remains closed to that
  current value. Do not rewrite Python inventory/schema or broaden a source drift guard.

## Settled native shape

Add public `ModelInventoryKind` in
`src/csharp/AnyInfer/Providers/ModelInventoryKind.cs`, namespace `AnyInfer.Providers`:

- `Served = 0`: models exposed by an already-running engine; this is the default.
- `Available = 1`: catalog of models that could be run.
- `Installed = 2`: provider-owned on-disk store.

Give the type and each member XML documentation. These are descriptive categories, not
provenance tags or implemented-operation flags. Unknown enum values are rejected.

Append optional `ModelInventoryKind modelInventory = ModelInventoryKind.Served` after the
existing final `serverTools` constructor parameter in `ProviderDescriptor`. Validate with
`Enum.IsDefined`, then expose get-only documented `ModelInventory` of this type. Existing
positional calls remain compatible. Do not add `HonorsConnectionSettings` yet: the native
connection implementation still does not exist, and this leaf must not advertise it.

Append a REQUIRED `ModelInventoryKind modelInventory` parameter after implementedOperations
in internal `CompatPresetGenerationRow`. Pass it into the actual ProviderDescriptor
constructor. The generated row must supply the source value explicitly, not rely on the
public default. `CompatPresetDefinition` checks the descriptor category agrees with
Source.SourceModelInventory, alongside its existing ID agreement. Its immutable
PendingNativeParity becomes exactly `["connection-settings"]` only after this real mapping
exists. Keep SourceModelInventory/SourceHonorsConnectionSettings in source facts.

The table remains inert and outside the default registry. No constructor/static initializer
does I/O or builds an adapter. Default registry remains four descriptors/seven bindings;
all 122 unimplemented operation memberships remain pending.

## Generator and independent observations

Update `scripts/generate_csharp_compat_presets.py` to explicitly render the category from
each effective descriptor through a closed literal map to the native enum. Existing
source-facts validation continues rejecting compat drift away from served. Do not infer
the category from ModelsListing or hardcode a default unrelated to source.

Keep SchemaVersion=1 (the input schema is unchanged), bump GeneratorVersion to 2, retain
actual InventorySha256 and stable ordering/UTF-8/LF/ASCII escaping. Root alone re-emits
`src/csharp/AnyInfer/Providers/CompatPresetTable.g.cs`. Preserve the exact LF attribute.

Extend `tests/test_csharp_compat_preset_data.py` with direct projection/render assertions
for the explicit enum argument and closed drift rejection, plus GeneratorVersion=2.
Preserve its actual checked-file byte comparison; never silently skip it once the checked
file exists. During an owner-only edit before root re-emission, run only selected new
controls and state that checked-file equality awaits re-emission.

Update independent `AnyInfer.Tests/CompatPresetDataTests.cs`: map the JSON descriptor's
model_inventory independently to the public enum and compare every compiled row; assert
actual descriptor, retained source fact, and remaining connection-settings pending list.
Change existing private constructor calls explicitly; keep other all-row/factory controls.
Add actual-source category mutation/projection disagreement negatives. Do not import the
Python generator or create a generated expected-output helper for native comparison.

New `AnyInfer.Tests/ModelInventoryTests.cs` controls public default/all three categories,
unknown-value rejection, immutable metadata and unchanged implemented operations. Use a
custom registry/configured AsyncClient and offline lifecycle adapter to prove all three
categories leave the actual discovered model IDs unchanged. No provider/default registration.

The isolated package consumer in `scripts/check_csharp_package.py` must compile against
public ModelInventoryKind and ProviderDescriptor.ModelInventory using PackageReference-only
local feed, asserting default and explicit categories without network calls. Add the causal
generated-consumer check in `tests/test_csharp_packaging.py`, preserving prior consumers.
Native execution remains root-owned. Document the field concisely in
`docs/reference/csharp-sdk.md` as metadata applications may inspect; no plan/ADR references
or inference that setting Available starts a runtime or downloads models.

## Checklist and disjoint ownership

- [x] **MINV.0** Root: obtain independent cold contract critique of this exact leaf before
  production edits. Gate: default/closed enum, explicit source projection, descriptive-only
  behavior, source-only remaining connection requirement and no-registration boundary agree.
  > NOTE: Bounded cold contract review is clean: closed/default category, explicit source
  > projection and agreement, metadata-only lifecycle behavior and inert registry boundary
  > resolve without P1/P2. TLS/connection/redirect and broader SDK work remain open.
- [x] **MINV.1** Native owner: only ModelInventoryKind.cs, ProviderDescriptor.cs and
  CompatPresetData.cs plus assigned artifact/minimal NOTE. Gate: held source/diff check
  and bounded independent source review; no native/.NET/test commands by owner.
  > NOTE: Held source adds the public closed descriptive enum, append-only Served-default
  > descriptor parameter/property validation, explicit generated-row category forwarding,
  > source/native category agreement, and the remaining connection-settings-only pending
  > marker. Registry, lifecycle/listing, operations, HTTP and I/O are unchanged. Scoped
  > whitespace check and independent source review passed. Compiler/package/full/clean
  > execution remains the separate root gates below.
- [x] **MINV.2** Generator/package owner: only generate_csharp_compat_presets.py,
  test_csharp_compat_preset_data.py, check_csharp_package.py and test_csharp_packaging.py.
    Gate: named focused Python controls and Ruff pass; root emits actual generated table.
    Do not edit workspace.py, accepted inventory, generated C# or native source.
  > NOTE: Held MINV.2 source maps the closed descriptor inventory literal to an explicit
  > `ModelInventoryKind` row argument after implemented operations, bumps only generator
  > version to 2, and adds isolated package-consumer public metadata witnesses. Root still
  > owns regenerated bytes and the native/package execution gates.
- [x] **MINV.3** Independent controls owner: only CompatPresetDataTests.cs and new
  ModelInventoryTests.cs plus artifact/minimal NOTE. Gate: independent joins/mutations and
  public configured lifecycle semantics are source-reviewed clean; no .NET/native execution.
  > NOTE: Held controls join every generated descriptor category to the independently parsed
  > source field, require GeneratorVersion 2 and connection-settings as the sole pending parity,
  > and reject source category drift plus native/source definition disagreement. Public controls
  > cover default, all closed values, invalid enum rejection, unchanged generation operations and
  > custom-registry offline discovery/health IDs. Cold review's factory/full-health/disposal
  > observability correction is closed; each category proves one factory and one disposal.
  > Independent source review is clean and root first native gate passes all 69 cases.
- [x] **MINV.4** Docs owner: only docs/reference/csharp-sdk.md plus artifact/minimal NOTE
  after native APIs hold. Gate: source-linked claims exact, no filter/registration/SDK-ready
  claim; root retains strict docs execution.
  > NOTE: Reference docs now define the default Served category and the Available/Installed
  > meanings, with the separate descriptive-only boundary checked against the held enum,
  > descriptor and compat mapping. Targeted docs search found no conflicting inventory
  > wording. Independent source review is bounded clean; strict docs execution remains
  > in the root full gate. No docs build or .NET/test commands were run by the owner.
- [x] **MINV.5** Root: emit table, run full focused Python controls and serialized native
  ModelInventoryTests|CompatPresetDataTests|CompatDialectTests plus required package proof.
  Gate: all new controls pass with actual explicit table mapping, no skipped byte control,
  independent source/generator/control/docs reviews closed; preserve failed-first evidence.
  > NOTE: Root emitted GeneratorVersion2 table SHA
  > 3ed02395c0c7040f6e43044ad32166f28e44ac8224361a76b73420ce5bd9f9a5. Full generator
  > controls pass 11/0/0 with checked-byte equality, first native gate passes 69/0/0,
  > and isolated local-feed NuGet consumer compiles/runs with zero warnings/errors.
  > All source/generator/control/docs review P1/P2s are closed. No native correction needed.
- [x] **MINV.6** Root: coherent full workspace over held source/protected inputs, then explicit
  owned-path executable commit. Gate: all25 steps, prior paired profiles, package/examples,
  docs and user/declaration/profile/release hashes preserved.
  > NOTE: `.tmp-tests/model-inventory-full-first` passes all 25 steps in 236.0 seconds,
  > including 1016 native unit and 93 conformance cases, prior paired profiles, strict docs,
  > package-only consumer and examples. Coherence facts retain 163 unchanged held/protected
  > inputs, including user files. Explicit source commit follows this gate; clean-source
  > qualification remains MINV.7 and is not implied by development acceptance.
- [x] **MINV.7** Root: fresh managed clean checkout of that executable source, exact registered
  C# gate and Frozen DEVELOPMENT102/0/0/0. Gate: source identity/clean state before-after,
  generated bytes, unchanged inventory/release, independent evidence-only review.
  > NOTE: Executable source afb3f86acfefd5a15f80de2389d4b0e0396e3a2b, tree
  > d47d9a135207d335411c06609bda58dd95cba9f1, is clean before/after fresh managed
  > qualification local-model-inventory-afb3f86a-20261023T061441Z. Exact registered C#
  > command passes all 12 steps, 1016 unit/93 conformance cases, five source-clean pairs,
  > generator byte equality, package/examples and Frozen DEVELOPMENT 102/0/0/0. Log SHA
  > 387cff4e974b4242bbdcd552500b521e8ea46c0d45c0db13f4250b09d4c91e50; Frozen SHA
  > 1d03fad7f829bd6c0a0632318e609984831354f6b7fd9e0351dc998e412dd8cb. Independent
  > evidence-only review is bounded clean. Inventory/release/protected bytes are unchanged.
- [x] **MINV.8** Root: reconcile parent/leaf and separately commit plan-only acceptance.
  Gate: current executable qualification remains distinct, default registry4/7 unchanged,
  SDK8a/6c/8b-c/9–12 and all235API rows open. Resume native connection-settings contract,
  with redirect parity explicitly tracked before researched preset registration.
  > NOTE: This plan-only acceptance record preserves qualified executable afb3f86...
  > separately from reconciliation. Only descriptive inventory metadata closes;
  > connection settings remain the sole inert-row parity requirement. Default registry4/7,
  > 122 pending operation memberships and all235 root API rows are unchanged. Resume
  > connection/TLS/proxy/client-cert/secret-handling design and redirect parity before
  > researched registration. The separate plan-only commit identity is retained in the
  > task artifact after commit; it does not replace the executable qualification identity.

Owners are not alone. Do not revert others. Reread this shared checklist before minimal
box/NOTE changes, and keep file ownership disjoint. Workers never mutate Git or run
.NET/build/restore/native/full suites. Root owns generated output, Git, all heavy gates,
clean-source qualification and reconciliation. Preserve user-owned uv.lock and v/cache/nodeids,
accepted declarations/registry, all shared/released profile bytes and historical baseline.

The broader connection design is not settled by this metadata leaf. It must retain full
proxy/verify/client-cert source requirements, injected-transport takeover, all four HTTP
construction paths and secret-handling obligations. Redirect default mismatch remains an
explicit readiness item, not an accepted permanent difference or a file-only TLS waiver.
