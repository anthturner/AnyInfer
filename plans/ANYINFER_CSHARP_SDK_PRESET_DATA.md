# Generate inert native compatibility-preset data

Resume from the first unchecked box. This SDK.8a preparation consumes the accepted Python
inventory and generates private typed C# metadata. It registers no provider, changes no
public API or operation support, and does not complete SDK.8a/6c. Registration, connection
settings/model-inventory parity, mixed operations and provider certification remain required.

## Accepted predecessor and decisions

- Private dialect source is qualified at `1f5e821ad0a4e4fd8e387af5005975ad4fbe387c`,
  tree `b3524b491b9c12796740e7f15e07fa27d1c4a211`; plan-only acceptance is
  `243fb6cfa38fdd9e7f632c98915d407e4ddc2c95`. All 24 workspace steps, clean registered
  C# gate, five shared pairs, package/examples and Frozen 102 passed. Preserve those inputs.
- Input is `maintenance/provider-parity/python-builtins.json`, validated against its schema
  and actual selected source through `scripts/export_python_provider_parity.py`.
  Current SHA is `47c2f58b2f4a8f9d0586c6f8ff92a171de485ef7cc73dfe496a679180e132b16`.
  It currently contains 86 `family="compat_preset"` rows and 20 dedicated rows. Derive current
  membership from validated source, not a hardcoded historical count. Dedicated rows are not
  emitted. Preserve the fixed historical baseline record rather than equating live counts.
- Use generated C# source, not a production JSON resource/parser. Native records/enums cover
  the metadata; symbolic reasoning bindings stay visible and no runtime dependency is added.
  Production must never read maintenance JSON or execute Python callable references.
- The effective `/descriptor` is authoritative for derived setup/capability fields. Do not
  reimplement Python `_setup_spec` in the generator or inject documented sampling defaults
  into requests. Raw `/preset` supplies the three dialect choices and reasoning style.
- Two non-neutral source fields have no native counterpart: `honors_connection_settings=true`
  and `model_inventory="served"`. Retain both explicitly as source facts. They do not become
  native support claims. Native proxy/TLS/client-certificate configuration and inventory-kind
  semantics are required before preset registration can claim full parity; handler injection
  does not waive that work. All generated rows retain two pending requirements named
  `connection-settings` and `model-inventory`.
- The four source embedding presets and Groq batch remain visible in `SourceOperations`.
  Native implemented operations are always exactly the singleton Generation. No generator or
  static initializer registers the table, constructs an adapter, resolves a key, or does I/O.

## Exact private shape and factory

Production owner adds only `src/csharp/AnyInfer/Providers/CompatPresetData.cs` and
`CompatPresetReasoning.cs`. Generated output is
`src/csharp/AnyInfer/Providers/CompatPresetTable.g.cs`, emitted only by the coordinator after
the generator is held. All types and members below are internal; record properties are
get-only and collections snapshot their inputs.

1. `CompatPresetSourceFacts` constructor:
   `(string id, IEnumerable<string> sourceOperations, bool sourceHonorsConnectionSettings,
   string sourceModelInventory, IEnumerable<string> contractDependencies,
   string sourceFactoryTarget)`. Expose PascalCase properties with those exact names.
   Source operations are an ordinal-sorted, unique read-only string list using the closed
   vocabulary `generation`, `embedding`, `rerank`, `batch`, containing generation. They are
   deliberately not the native operation enum/set. Dependencies are copied in source order.
   For this v1 projection require true connection support and `served` inventory kind as source
   facts; a different source value requires contract review, not a substituted default.
2. `CompatPresetGenerationRow` constructor:
   `(string id, string displayName, IEnumerable<string> aliases, string? defaultBaseUrl,
   bool requiresBaseUrl, ProviderLocality locality, ProviderSetupSpec setup,
   ModelCapabilities defaultCapabilities, IEnumerable<string> ignoredParameters,
   OpenAICompatDialectOptions dialect, CompatPresetReasoningStyle reasoningStyle,
   IEnumerable<InferenceOperation> implementedOperations)`. Require exactly one supplied
   operation, Generation; reject empty, duplicate, extra, embedding or batch entries before
   materializing a descriptor. Expose `Descriptor`, `Dialect`, `ReasoningStyle`.
3. The row constructs the actual `ProviderDescriptor` centrally, using copied metadata,
   singleton generation operations and `CompatPresetReasoning.Translate` for its style.
   Its lazy factory calls only `OpenAIChatAdapter.Create(config, dialect, token)` and sets
   `PoolOwnsConfiguredTransport=true`. It forwards existing ProviderConfig base URL, provider
   identity, key, headers, timeout, transport and pool ownership through that factory; retain
   its API-version/nonempty-options refusal and cancellation. Do not copy a Python factory
   into executable data or generate a separate lambda policy for each provider.
4. `CompatPresetDefinition(CompatPresetSourceFacts source,
   CompatPresetGenerationRow generation)` exposes `Source` and `Generation`, checks their IDs
   agree, and exposes immutable `PendingNativeParity` equal to
   `["connection-settings", "model-inventory"]`. This makes the non-neutral native gaps visible.
5. `CompatPresetTable` is an internal static partial class. The generated file exposes
   `SchemaVersion=1`, `GeneratorVersion=1`, the actual input `InventorySha256` string and
   read-only `Rows` ordered by source ID. Its initializer only builds metadata. Default
   `ProviderRegistry.CreateDefault()` and its IDs/aliases stay unchanged and disjoint from
   all generated IDs and aliases. An explicit later registration leaf owns changing that guard.

`CompatPresetReasoningStyle` is a closed internal enum: `None`, `Effort`, `EffortMinLow`,
`EffortThreeLevel`, `EffortMinNamed`, `ReasoningObject`. Unknown enum values are rejected.
`CompatPresetReasoning.Translate(style, string? effort)` returns immutable native JsonObject:

| Style | null | `none` | `minimal` | other supplied normalized strings |
| --- | --- | --- | --- | --- |
| None | `{}` | `{}` | `{}` | `{}` |
| Effort | `{}` | `{"reasoning_effort":"none"}` | `{"reasoning_effort":"minimal"}` | same supplied effort |
| EffortMinLow | `{}` | `{}` | `{"reasoning_effort":"low"}` | same supplied effort |
| EffortThreeLevel | `{}` | `{}` | `{"reasoning_effort":"low"}` | same supplied effort |
| EffortMinNamed | `{}` | `{"reasoning_effort":"min"}` | `{"reasoning_effort":"min"}` | same supplied effort |
| ReasoningObject | `{}` | `{"reasoning":{"enabled":false}}` | `{"reasoning":{"effort":"minimal"}}` | nested effort with supplied string |

For the four effort styles, “same supplied effort” means `{"reasoning_effort":effort}`.
Preserve Python's functions exactly; do not add model-specific clamping or replace core-owned
normalized request validation. Keep the two currently equal min-low/three-level styles distinct.

## Closed source projection

Actual JSON Pointers use numeric row indices `/providers/<index>/...`; ID-selected row
notation in source-map artifacts is descriptive only. The complete row has exactly
`id`, `family`, `contract_dependencies`, `descriptor`, `preset`. Validate known shape/types
with the inventory schema and reject unknown/unmapped non-neutral fields in the projection.

| Source under each compat row | Generated/native destination |
| --- | --- |
| row id and descriptor id | Source.Id and Generation.Descriptor.Id, required equal |
| contract_dependencies | Source.ContractDependencies, exact ordered strings |
| descriptor operations | Source.SourceOperations in exact canonical order; never native flags |
| honors_connection_settings / model_inventory | Source source-prefixed facts, pending requirements above |
| factory | Validate partial kind, target, empty args and sole preset_ref keyword; retain target as Source.SourceFactoryTarget |
| display_name / aliases / locality / default_base_url / requires_base_url | Corresponding descriptor values, aliases ordered, nullable URL preserved |
| setup fields | Every ordered key/label/kind/required/help_text/placeholder/env_var/advanced/default_value/choices member into SetupField |
| setup model_selection / host_shorthand / any_of / requirement_note | ProviderSetupSpec, including null vs present HostShorthand and ordered nested arrays |
| default_capabilities features | Named native flags and exact Sourced provenance |
| default_temperature / default_top_p | Nullable Sourced<double>, exact provenance; AI21 catalog facts remain metadata |
| ignored_parameters | Ordered descriptor list |
| preset auth_header / models_listing / output_tokens_field | Exact private OpenAICompatDialectOptions |
| preset reasoning + descriptor reasoning_translator | Closed style/callable agreement, then the native style enum/helper |

Raw preset field set is exactly: `accepts_api_key`, `aliases`, `auth_header`, `base_url`,
`base_url_example`, `base_url_hint`, `batches`, `default_port`, `default_temperature`,
`default_top_p`, `display_name`, `embeddings`, `features`, `id`, `ignored_parameters`,
`key_env`, `locality`, `models_listing`, `note`, `output_tokens_field`, `reasoning`,
`requires_api_key`, `requires_base_url`. Input byte equality with a freshly rendered validated
inventory establishes actual raw/effective derivation. The generator takes derived values
from descriptor setup/capabilities; it does not duplicate setup policy. Raw key_env, credential
predicates, URL hints/examples and default_port are represented by those effective fields.
`accepts_api_key` remains UI metadata, not runtime key suppression. Raw note stays in the
maintenance inventory/contracts; it is intentionally not runtime descriptor data.

Validate both source factory targets: `anyinfer.providers.presets.PresetCompatAdapter` or
`anyinfer.providers.presets.PresetEmbeddingAdapter`; the second must agree with raw embeddings
and the source operation set. Require `args=[]` and only
`keywords={"preset":{"kind":"preset_ref","id":<same id>}}`. Closed reasoning targets are
the six `anyinfer.providers.presets` callables `_no_reasoning`, `_translate_effort`,
`_translate_effort_min_low`, `_translate_effort_three_level`, `_translate_effort_min_named`,
`_translate_reasoning_object`, agreeing respectively with null and the five raw styles.
No target string is invoked, imported by target name, or evaluated.

Remaining descriptor values must match this literal current neutral shape; reject drift
rather than lose it. Mapped native fields use the same defaults and are compared by native tests:

```json
{
  "static_capabilities": {}, "static_embedding_capabilities": {}, "static_rerank_capabilities": {},
  "max_repair_attempts": null, "cache_mechanism": null, "cache_max_marks": 0, "cache_min_tokens": 0,
  "server_tools": [], "governs_own_transport": false,
  "token_calibration": {"multiplier": 1.0, "overhead_tokens": 0, "tokenizer": null, "tokenizer_provenance": "default"},
  "rate_limit_headers": {"requests_remaining": "", "requests_reset": "", "tokens_remaining": "", "tokens_reset": "", "limit_requests": "", "limit_tokens": ""},
  "supports_sessions": false, "model_puller": null, "uses_catalog": false,
  "reports_diagnostics": false, "derived_from": null, "grammar_needs_prompt_injection": false
}
```

Other default-capability members `context_window`, `max_output_tokens`, `pricing`, `local`,
`operations`, `embedding` are currently null and guarded as such. Native-only
StructuredOutputProfiles stays empty. Preserve explicit setup empty strings, choices, any_of,
requirement_note and null host shorthand. Admit only current closed locality/provenance/feature
vocabularies using explicit name maps; do not cast unknown bits, stringify unknown values or
discard null/provenance. Existing schema validators remain authoritative for JSON types.

## Generator and independent proof

Add `scripts/generate_csharp_compat_presets.py` with
`--input` defaulting to the maintenance snapshot and required mutually exclusive
`--output PATH` or `--check PATH`. Before projection, use the accepted inventory validator
and require input raw bytes equal fresh `render_inventory().encode("utf-8")`. That proves
selected imports, actual source closure/digests and raw/effective graph without invoking an
adapter or translator. Strictly reject BOM, CRLF, duplicate keys, nonfinite JSON and stale
source bytes. Keep pure projection/render functions separately testable.

Emit deterministic UTF-8/BOM-free/LF C# with one terminal LF, stable ID order, exact literals,
immutable constructors and generated header/source inventory digest/version. C# string escaping
must handle quotes, slashes, controls and Unicode safely; no executable source from input strings.
`--check` compares raw bytes, never rewrites. `--output` is the only output mutation.
Production contains no maintenance paths or runtime file reads.
Emit setup/capabilities through the existing `ProviderSetupSpec`, `SetupField`,
`HostShorthand`, `ModelCapabilities` and `Sourced<T>` constructors with named arguments.
No new conversion/helper API is required. The generator can emit calls to the exact private
row constructors above while their implementation is in progress; source-file arrival is
not an additional rendering dependency.

Python controls in `tests/test_csharp_compat_preset_data.py` render to a fresh temporary path
and require exact checked-file byte equality; test stale/CRLF/BOM bytes without rewrite,
unknown fields/styles/flags/provenance, non-neutral drift, source/effective mismatch, source
operation/factory mismatch, reordered metadata, null/provenance change and hostile literals.
Separate byte-admission and pure-projection tests so a generic checksum failure cannot hide
a missing field-map assertion. Import direct modules after adding scripts to sys.path.

Independent native controls in `AnyInfer.Tests/CompatPresetDataTests.cs` parse the maintenance
inventory ONLY in tests with an independently authored System.Text.Json reader, not generator
projection code or a generated expected-output helper. Join every actual compiled row by ID
and compare every listed field/order/null/provenance, neutral native defaults and source-only
fact. Assert the input raw SHA/version and exact live preset membership. Include semantic
reader negative probes for changed null/provenance/list order/source operations, constructor
rejection of non-singleton implemented operations, immutable snapshots, unknown native style,
and default-registry ID+alias disjointness from all generated IDs+aliases.

Use literal expected JSON for all six translators across null/none/minimal/low/medium/high/xhigh.
Actual configured public AsyncClient wire controls select table rows covering x-api-key,
alternate token spelling, no-listing health, host shorthand/setup/default endpoint and each
reasoning style; use custom registries and offline transports only. Prove no sampling-default
injection, caller override and exact disposal. Descriptor/table construction must stay inert.
These are data/factory controls, never live-provider or default-registration evidence.

## Execution checklist and ownership

- [x] **PGEN.0** Coordinator: close cold contract critique before production work. Gate: exact
  field/factory map, source-only gaps, enforced singleton/disjointness and independent byte+
  compiled semantic joins resolve the earlier two P1s/P2; no unsupported provider claim.
  > NOTE: Exact contract rereview closes all prior P1/P2s: complete field/factory projection,
  > source-only non-neutral gaps, generation-only constructor/default-registry boundaries,
  > and independent canonical source/checked-byte/compiled semantic joins. Native no-listing
  > mechanics were already qualified by DIALECT; reasoning behavior is controlled by this leaf.
- [x] **PGEN.1** Native owner: own only CompatPresetData.cs and CompatPresetReasoning.cs,
  assigned artifact and minimal box NOTE after rereading. Implement the exact private types,
  immutable constructors, factory and translators. Gate: held source/diff check and independent
  source review clean; no native commands by worker.
  > NOTE: Held source supplies immutable source facts, generation-only descriptor rows, fixed
  > pending parity requirements, the inert partial table anchor, and all six closed reasoning
  > translations. It has no registration, maintenance-file access, credential resolution or
  > adapter construction at metadata initialization. Independent source review is bounded
  > clean; generated-row compilation and execution remain the separate PGEN.4 gate.
- [x] **PGEN.2** Python owner: own only generator, its Python test file, workspace.py and
  tests/test_workspace.py. Add generator --check to the C# phase immediately after SDK-version
  check and before restore; lint the script. Update causal command-order/count controls.
  Gate: focused new generator tests and affected workspace controls plus Ruff pass; root emits
  the actual generated C# file after both owners hold. Never hand-edit generated data.
  > NOTE: Generator validates raw canonical inventory/source closure before projection,
  > emits typed collections and safely escaped literals through existing constructors, and
  > registers a C# `--check` before restore. Root emitted the checked table; final generator
  > controls pass 11/0/0 with no skipped equality control, affected workspace controls pass 3/0,
  > and independent generator review closes all P1/P2s. Native compilation remains PGEN.4.
- [x] **PGEN.3** Independent native controls owner: own only CompatPresetDataTests.cs and
  artifact/minimal NOTE. Gate: independent reader covers all compiled rows and actual factory
  witnesses above, source review clean; no .NET/build/native/test commands by worker.
  > NOTE: Held independent controls parse the maintenance inventory directly in the test assembly,
  > verify every compiled compat row, closed factory/reasoning source joins, and table-selected
  > offline public-client factory witnesses. After retained first-gate diagnostics, public theory
  > data exposes the style as an integer, sourced-value parsing has no type/member collision, and
  > bearer plus host shorthand are asserted through the generated factory. Retained second-gate
  > analyzer diagnostics use predicate-aware xUnit assertions and an explicit non-null source fact.
  > Retained third-gate controls compare feature flags as an ordinal set and mutate a complete
  > inventory row to reach the embedding-only operation guard. Retained fifth-gate feature names
  > now use a closed explicit 17-member native-to-source map. Final source review is clean;
  > coordinator sixth native gate passes 67/67 with zero failures/errors/skips.
- [x] **PGEN.4** Coordinator: emit generated table, apply exact LF attribute for generated
  source, then serialize native compile/targeted tests. Retain first diagnostics and route
  minimal corrections. Gate: all new native tests and existing CompatDialectTests pass;
  generator --check and independent source/control reviews close without unresolved P1/P2.
  > NOTE: Root emitted safe-literal table SHA 77cdb54f404eae7870820694a05b494cb83a4629f7171efd9944469628f31793
  > under its exact LF attribute. Generator controls pass 11/0/0, workspace controls 3/0,
  > and `.tmp-tests/preset-data-native-sixth` records 67/0/0. All prior failed attempts are
  > retained; bounded source/generator/control reviews close every reported P1/P2.
- [x] **PGEN.5** Coordinator: run coherent full workspace once, snapshot owned/protected
  digests, then commit explicit owned paths. Gate: all steps, prior source-stamped profiles,
  package/examples and docs pass; no declaration/released/profile/user-file drift.
  > NOTE: `.tmp-tests/preset-data-full-first` passes all 25 steps in 190.4 seconds,
  > including 1014 native unit and 93 conformance controls, all prior paired profiles,
  > docs, package consumer and examples. Coherence facts report 162 unchanged held/protected
  > inputs, including user files. The explicit source commit records this gate; clean-source
  > qualification remains PGEN.6, separate from this development acceptance.
- [x] **PGEN.6** Coordinator: fresh clean managed checkout of explicit executable source;
  exact registered C# gate including generator check and Frozen DEVELOPMENT 102/0/0/0.
  Gate: clean before/after and exact HEAD/tree/source/input hashes, independent evidence review.
  > NOTE: Executable `60e39c9ef011d9cbc3a03a61f330e3366e964558`, tree
  > `a451153446bc4798c0b2e31a4d0c804109f3abaf`, qualifies in fresh managed checkout
  > `feature-preset-data-clean-60e39c9`, attempt `local-preset-data-60e39c9e-20261023T053917Z`/1.
  > Exact registered C# gate passes all 12 steps in 75.8 seconds, with 1014 unit/93
  > conformance controls, all five pairs revision-matched/source_dirty=false, generator
  > checked bytes, package and examples. Frozen DEVELOPMENT/UNRELEASED is 102/0/0/0
  > against unchanged release SHA 16122cca198d9e688d3c4b5724ac11f0324a4390d8e8589e443fe04a48e81391.
  > Log SHA 5056367cf23153a21588d17a1213afa3d97368ebf7529d2edde4c2bf908542ed and
  > Frozen SHA 439e722e3d6a8a76cfd15e28985838c59fc372eacfc4d5899a30c9c62403e996
  > were independently recomputed. Initial/final clean commit/tree agree; evidence review is clean.
- [x] **PGEN.7** Coordinator: reconcile plans with accepted executable versus plan-only commit.
  Gate: default registry still four descriptors/seven bindings, all 122 pending operation
  memberships and 235 API rows remain open; resume native connection-settings/model-inventory
  contract and researched registration, without a generation-only provider waiver.
  > NOTE: This plan-only acceptance follows the qualified executable commit above and does
  > not replace its evidence identity. All 86 compat rows remain inert, with fixed pending
  > connection-settings/model-inventory requirements. Parent SDK.8a/6c/8b-c/9–12 and all 235
  > root API rows remain unchecked. Resume native connection-settings/model-inventory contract;
  > no preset is registered and no mixed-operation, live-provider or release claim is made.

Workers are not alone: do not revert others. Reread this shared file before minimal box/NOTE
edits. Root owns generated output, .gitattributes, shared reconciliation, Git and all heavy
native/full/clean gates. Workers run only named focused Python checks, no Git mutation,
.NET/restore/build/pack/native/full suites. Preserve user-owned uv.lock and v/cache/nodeids,
accepted declarations, all shared/released profile bytes and historical baseline. A new data
file or compiling row is not an implemented provider; the default registry boundary is firm.
