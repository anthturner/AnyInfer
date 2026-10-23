# Complete provider declaration inventory for C# parity

Resume from the first unchecked box. This is the inventory portion of SDK.8a in
`ANYINFER_CSHARP_SDK.md`, under the existing authorization to finish both core SDKs.
It does not complete SDK.8a's preset runtime port, SDK.8b dedicated adapters, SDK.8c
public certification helpers, or the remaining mixed-operation SDK.6c bindings.

## Starting facts and boundaries

- Qualified executable predecessor: `b315ef73173b81ace643c41e95f4e6339db636b6`, tree
  `7e00ab8f148f255b94c77b5c8673370a04ad2833`. Plan-only reconciliation:
  `1c9e01618b71adc66930fb9cfa4df8c456943cc4`.
- Python baseline remains `199c3f833e568334b629edd7d89f41a3b76efe2a`. Actual offline
  enumeration of `anyinfer.providers.builtin_descriptors()` yields 106 descriptors:
  20 dedicated and 86 presets, with 103 generation, 16 embedding, 5 rerank and 5 batch
  bindings (129 total). TEI, Voyage and Jina declare retrieval only, not generation.
  The 86 preset IDs/order are unchanged from baseline; field-level baseline comparison
  remains explicit work below. Root also verified these counts in an offline git-archive
  copy of the baseline, using the selected interpreter and an import-path guard; retained
  proof is `.tmp-tests/provider-baseline-199c3f-20261023T030622Z/baseline-counts.json`.
  Counts describe declaration inventory, not runtime-support certification.
- Keep every declared operation visible. Four presets also embed (together, fireworks,
  deepinfra, mistral); groq also declares batch. A partial native operation port cannot
  be labeled complete provider parity. Current native registry breadth stays unchanged
  in this leaf. This inventory contains declaration facts, not behavioral certification.
- Preserve released assets/comparators, all accepted profiles, maintenance declarations,
  registry producer contracts and protected user files `uv.lock` and `v/cache/nodeids`.
  No new provider wire fact, date, capability or native implementation is invented here.
- Source authority is the actual descriptor/preset graph, not a hand-maintained provider
  list. Reuse `scripts/export_python_provider_bindings.py::_builtins` and `_dependencies`
  for fail-closed builtin membership and checked contract dependency closure. Do not
  duplicate that contract map or weaken existing producer behavior/schema.
- Read `DESIGN.md`, `AGENTS.md`, provider declarations, the existing maintenance exporter
  and relevant tests before code. Later runtime changes separately follow
  `contracts/NEW-PROVIDER.md`, with current official research before wire implementation.

## Accepted inventory v1 contract

Owned new paths are `scripts/export_python_provider_parity.py`,
`tests/test_provider_parity_inventory.py`, and
`maintenance/provider-parity/{python-builtins.schema.json,python-builtins.json}`.
The production SDK does not import this material. The checked snapshot supports reviewed
data-generation and parity planning; it does not claim adapters have passed any gate.

The envelope has exactly these required members:

- `schema_version`: integer 1; `purpose`: literal `provider-parity-inventory`.
- `python_baseline`: exactly this closed record, all members required, no extras:
  `{"revision":"199c3f833e568334b629edd7d89f41a3b76efe2a","descriptor_count":106,"operation_counts":{"generation":103,"embedding":16,"rerank":5,"batch":5}}`.
  Revision is a string; counts are integers excluding bool. These independently observed
  historical values identify the comparison baseline, not the current source commit or
  native support. Derive current descriptor/operation counts independently from `_builtins`
  and verify that the rendered `providers` encode exactly that complete graph. Current
  declarations are bound by the source records and fresh `--check` byte comparison; do
  not silently replace baseline counts with current counts if future declarations change.
- `sources`: sorted unique records `{path, sha256}` with repository-relative slash paths
  and actual raw SHA-256. Its membership must equal the exact union defined below;
  omitted/extra paths, duplicate paths, absent files or changed hashes reject. Never hash
  the generated snapshot into itself.
  Do not embed HEAD/dirty/time/absolute paths in this committed deterministic snapshot;
  actual source bytes are bound by `sources`, avoiding a self-referential commit pin.
- `providers`: sorted by canonical `id`. Each closed record has `id`, `family`
  (`dedicated` or `compat_preset`), `contract_dependencies`, `descriptor`, and `preset`.
  Dependencies come from the existing authoritative function and remain sorted.
  `descriptor` contains every stored `ProviderDescriptor` field under its Python name.
  `preset` is the complete `CompatPreset` data for a preset row, otherwise explicit null.

Derive the complete source-path set mechanically, before hashing:

1. Fixed files: `scripts/export_python_provider_parity.py`,
   `maintenance/provider-parity/python-builtins.schema.json`,
   `scripts/export_python_provider_bindings.py`,
   `src/python/anyinfer/providers/__init__.py`,
   `src/python/anyinfer/providers/presets.py`, `src/python/anyinfer/registry.py`,
   `src/python/anyinfer/types/capabilities.py`, and
   `src/python/anyinfer/types/operations.py`.
2. For every literal module name in `anyinfer.providers._BUILTIN_MODULES`, include
   `src/python/anyinfer/providers/<module-name-with-dots-as-slashes>.py` regardless of
   optional import availability. Missing imports still fail `_builtins` membership;
   source closure does not excuse or silently skip them.
3. Include the defining source file of every class in the exporter's explicit
   `_SUPPORTED_DATACLASSES`/schema-type mapping, even when a nested value is null or
   unused by current descriptors. This mapping must cover every declared nested data
   shape in the schema; field names must equal actual `dataclasses.fields` for each
   type. Unknown types or changed field sets fail until explicitly reviewed. Include
   the defining source module for each supported non-dataclass enum/flag type too.
4. Include defining source modules of every actual callable/partial target reached
   recursively during descriptor/preset encoding; do not invoke targets. A partial's
   wrapped callable, args and keyword values participate in this traversal.
5. Union every file returned by `_dependencies` for every actual descriptor, removing
   only the `#heading` fragment after the existing helper validates it.

Resolve all paths to existing repository-contained source files; module sources must
be `.py`, not bytecode or external installed modules. Normalize once to relative slash
paths, deduplicate and sort. Validate equality of the document's source-path set against
this freshly derived set, then each raw hash. No manually curated per-provider source
list or unchecked extra path is accepted.
All currently hashed source paths and inventory JSON have scoped LF checkout rules in
`.gitattributes`; hash the actual LF file bytes, without newline normalization in the
exporter. Root verified the 47 pre-existing source files' LF bytes exactly equal HEAD
and refreshed their working files; no source content or contract date changed.

Serialization is declaration data only:

- Include every stored dataclass member, including default, empty and null values.
  Derived properties such as normalized `identifiers` are not additional stored fields.
  Use actual dataclass field sets as a completeness check; newly added/unsupported source
  fields or runtime types must fail until the reviewed encoding/schema is extended.
- Preserve tuple/list order, including aliases, setup fields, choices, any-of groups,
  ignored parameters, dimension choices and input intents. Sort set/frozenset string
  values lexically. Encode `Feature` flags as lexically sorted declared member names,
  with zero as `[]`; reject unnamed bits. Preserve `Sourced` value and provenance.
- Sort string-keyed mappings, retaining empty mappings. Preserve finite floats as JSON
  numbers and ints as JSON integers, distinguishing bool; never coerce or round them.
  Encode finite `Decimal` as exact `str(value)` in its schema-typed decimal field, never
  through float. Reject nonfinite numbers and unsupported values.
- A plain callable is `{kind: 'callable', target: '<module>.<qualname>'}`. A partial is
  `{kind: 'partial', target: '<wrapped module>.<qualname>', args: [...], keywords: {...}}`.
  Preserve bound data without invoking any factory, translator or hook. A bound preset
  may use `{kind: 'preset_ref', id: ...}` only after checking it matches that row's full
  canonical preset value. Other bound data uses the same explicit supported encoding;
  unexpected callable instances/types fail. Never use repr, memory addresses or guessed
  adapter behavior as identity. Null model-puller stays null.
- The Draft 2020-12 schema is closed at every fixed record/dataclass shape; dynamic
  model/pricing maps use typed values. Nullable nested declarations remain explicit.
  Include every reachable declared supporting data shape, or fail with a precise source
  ambiguity before implementation rather than silently omitting it.
- Emit UTF-8 without BOM, LF, sorted JSON object keys, indent 2 and one final newline.
  No credentials/environment values, endpoint contact, adapter construction, entry-point
  discovery, translation execution or external process belongs in generation.

CLI: `python scripts/export_python_provider_parity.py --output PATH` renders the complete
current inventory. `--check PATH` validates the stored document and compares it with a
fresh in-memory rendering; stale bytes/source hashes or malformed data fail nonzero without
rewriting the file. The two modes are mutually exclusive. Resolve repository/import
authority to this checkout's `src/python`, with clear refusal for a foreign import.

## Execution checklist

- [x] **PINV.0** Coordinator: cold review the v1 encoding and source closure against actual
  descriptor/setup/capability/preset contracts. Settle any field/type ambiguity before
  source edits. Gate: independent bounded critique closes, without treating inventory as
  runtime support or whole SDK.8 acceptance.
  > NOTE: Cold review's baseline-shape and source-closure P1s are resolved by the exact
  > historical record and mechanically derived path union above. The corrected contract
  > rereview is bounded clean. Root's isolated baseline import verifies the historical
  > 106/129 counts; separate read-only normalized graph comparison found no descriptor
  > or preset data-field drift against the pinned baseline. Runtime wire corrections
  > made since that baseline are not claims of declaration-data drift or provider parity.
- [x] **PINV.1** Inventory implementer: own the four new source/schema/snapshot/test paths
  above. Export the complete current graph, closed schema, deterministic bytes and check
  mode; compare baseline declaration fields through read-only Git and record meaningful
  drift explicitly. Do not construct adapters or change existing exporters. Gate: focused
  pytest for exact graph/dependency/field completeness, deterministic ordering, all encoding
  types, null/empty/defaults, unknown bits/types, callable/partial data and no invocation,
  missing builtin/alias collision, foreign import, nonfinite and stale snapshot mutations;
  targeted Ruff check/format and source-only diff check.
  > NOTE: The checked snapshot renders 106 declaration rows and 129 operation memberships
  > (103 generation, 16 embedding, 5 rerank, 5 batch), with 49 mechanically derived source
  > records. It reuses the existing `_builtins`/`_dependencies` authority without invoking
  > adapters or callbacks. The retained baseline normalized-graph comparison remains the
  > bounded field-drift evidence; this implementation does not make a new runtime claim.
  > NOTE: Reopened after independent review found four P1s missed by the initial 9-pass
  > gate: live counts tied to historical baseline, CRLF accepted by read_text normalization,
  > open Sourced values/overlapping partial integer schema, and missing LF checkout policy
  > for raw source hashes. Root's CRLF CLI probe returned 0 incorrectly; retained proof
  > is .tmp-tests/provider-inventory-root-20261023T032602Z/facts.json. Root's scoped LF
  > policy now covers all 49 sources and restores existing committed bytes; exporter,
  > schema, causal controls and fresh snapshot require correction/review before acceptance.
  > NOTE: Repaired gate keeps `python_baseline` historical while deriving current rows and
  > operation totals solely from `_builtins`; it compares raw UTF-8 bytes, rejects BOM/CRLF/
  > duplicate/nonfinite JSON, uses field-specific closed `Sourced` schemas, and admits only
  > LF-attributed, CR-free hashed source files. Focused corrected controls: 20 passed.
- [x] **PINV.2** Independent reviewer: inspect actual source/schema/snapshot and controls,
  including a deliberate source-field or metadata corruption mutation. Gate: no missing
  builtin/operation/alias/setup/auth/preset fact, no duplicated dependency policy, no
  executable callback or certification oracle and no unsupported claim; P1/P2 closed.
  > NOTE: Independent narrow rereview closes all four retained P1s. Corrected source,
  > schema and snapshot have 20 focused controls passing; root independently verifies
  > snapshot SHA d7a92216958018d155184e6690d9fbb92254e01233f82bc03b3411446313ac34,
  > 106 rows/129 operations/49 raw source hashes. Workspace lint registration's causal
  > control passes 1/1 with Ruff clean. Full workspace and clean checkout remain PINV.3.
- [x] **PINV.3** Coordinator: add exporter to existing workspace lint paths and causal
  workspace controls only after the export works. Inspect exact full 106/129 inventory
  against actual source and accepted native gaps; commit explicit owned paths after the
  appropriate coherent workspace gate. Gate: deterministic `--check`, focused workspace
  controls, full workspace and no released/profile/declaration changes.
  > NOTE: Root's held-source full gate passes all 24 steps in 178.0 seconds at
  > .tmp-tests/provider-inventory-full-first/workspace.txt; source-input digests,
  > protected files and released/declaration bytes are unchanged after execution.
  > The nine explicit owned paths are committed at
  > 830673e56437a695ae26f579d7ca264139b7b0ba, tree
  > 35f35ca6a6a76291c0fe0fdf82affa6e4499cd88. Fresh managed checkout
  > feature-provider-inventory-clean-830673e passes deterministic --check and 20 focused
  > controls in 15.41s, with dirty=false before/after, the same snapshot digest and all
  > 49 actual raw source hashes matching. Evidence is its
  > .tmp-tests/provider-inventory-clean-root/{facts.json,commands.log,junit.xml}.
  > Independent evidence-only review is bounded clean; this qualifies declarations only.
- [x] **PINV.4** Coordinator: reconcile only the completed inventory portion of SDK.8a;
  retain parent SDK.8a/b/c and SDK.6c unchecked. The next reviewed execution contract must
  cover native metadata/adapter seams and full preset operation flags before runtime port.
  Gate: every remaining provider operation stays assigned, with no generation-only waiver.
  > NOTE: The derived task-artifact operation matrix retains all 106 providers and 129
  > Python bindings against seven currently declared native bindings; 122 remain pending.
  > Parent SDK.8a/b/c and SDK.6c stay unchecked, as do all 235 root API inventory rows.
  > Current official research flags stale Reka/Lemonade auth declarations for adjudication
  > under NEW-PROVIDER/PROPAGATE-CHANGE before native preset runtime implementation.

## Ownership and resume

Workers re-read this plan immediately before minimal checklist updates and add `> NOTE:`
for deviations. Each brief owns disjoint paths; the coordinator owns shared plans,
workspace registration, Git and serial native/full gates. No worker mutates Git or runs
.NET, full suites or live traffic. Use the explicit `.venv/Scripts/python.exe`, fresh
ignored basetemp/JUnit paths and disabled cacheprovider. Artifacts are under
`csharp-sdk/sdk-eight-providers/` in the task. This inventory leaf is complete at source
commit `830673e56437a695ae26f579d7ca264139b7b0ba`; subsequent plan-only acceptance does
not replace that executable identity. Resume parent SDK.8a with the reviewed native preset
data/runtime contract and current auth findings; no provider runtime parity is accepted here.
