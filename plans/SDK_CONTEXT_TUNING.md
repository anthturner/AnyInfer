# Native context tuning foundation

**Resume from the first unchecked box.** This is the first bounded SDK.9a context slice,
authorized by the user's autonomous SDK parity request. Read `AGENTS.md`, DESIGN's context
sections, `ANYINFER_CSHARP_SDK.md`, `SDK_FOUNDATION_ALIGNMENT.md` and this entire file before
editing. Root owns Git and serialized heavy gates. Preserve other agents' work.

## Scope and authority

Port `src/python/anyinfer/context/settings.py` and its public settings behavior into native
`AnyInfer.Context.ContextTuning`. Python source/tests are behavioral authority; the Python
root inventory remains pinned at `199c3f833e568334b629edd7d89f41a3b76efe2a`. The settings
module is unchanged by checkpoint `8ce6bc0`. No Python runtime dependency, new package,
provider behavior, filesystem collection or network access is introduced.

This closes only a native settings prerequisite. Reduction strategies, history reduction,
request-path context policy and the shared config `context` block remain unavailable until
their own ports. Do not expose settings as proof those algorithms run. SDK.9a/9b and final
SDK.11c remain unchecked. Frozen `core-generation-v0` assets and existing five development
profiles are unchanged.

## Settled native contract

Create `src/csharp/AnyInfer/Context/ContextTuning.cs`, a public sealed immutable record with
an explicit constructor, get-only properties, XML documentation and the following defaults.
Use normal PascalCase members and camelCase constructor arguments; mapping keys retain the
exact Python snake_case spellings. Counts use signed Int64 with checked mapping conversion,
consistent with the existing native count domain; out-of-range native inputs must fail
explicitly, never wrap, clamp or fabricate shared equality with Python's unbounded integers.

| Python key | Native property / type | Default | Validation |
|---|---|---|---|
| `collapse_duplicates` | `CollapseDuplicates` / bool | true | strict bool in mappings |
| `near_duplicate_threshold` | `NearDuplicateThreshold` / double | 0.0 | finite, inclusive 0..1 |
| `shingle_size` | `ShingleSize` / long | 5 | at least 1 |
| `selection_order` | `SelectionOrder` / string | `rank` | exact ordinal `rank` or `density` |
| `diversity` | `Diversity` / double | 0.0 | finite, inclusive 0..1 |
| `split_identifiers` | `SplitIdentifiers` / bool | false | strict bool in mappings |
| `query_expansion` | `QueryExpansion` / bool | false | strict bool in mappings |
| `expansion_terms` | `ExpansionTerms` / long | 8 | at least 0 |
| `feedback_documents` | `FeedbackDocuments` / long | 5 | at least 0 |
| `expansion_weight` | `ExpansionWeight` / double | 0.4 | finite, nonnegative |
| `salience_weight` | `SalienceWeight` / double | 0.0 | finite, nonnegative |
| `salience_damping` | `SalienceDamping` / double | 0.85 | finite, inclusive 0..1 |
| `salience_iterations` | `SalienceIterations` / long | 20 | at least 1 |
| `compact_fallback` | `CompactFallback` / bool | false | strict bool in mappings |
| `chunk_tokens` | `ChunkTokens` / long | 512 | at least 1 |
| `rollup_share` | `RollupShare` / double | 0.45 | strictly between 0 and 1 |
| `carry_over_bonus` | `CarryOverBonus` / double | 0.0 | finite, nonnegative |

- `DefaultChunkTokens` is public constant 512. Static `Default` is the immutable default
  instance; static `SelectionOrders` is an immutable ordered list `["rank", "density"]`.
- `Recommended()` changes only near duplicate threshold=.9, selection order=`density`,
  diversity=.25, split identifiers/query expansion=true, salience weight=.5,
  compact fallback=true, carry over bonus=.5; other values keep their defaults.
- `RankingIsDefault` tests only `!SplitIdentifiers && !QueryExpansion && SalienceWeight == 0
  && CarryOverBonus == 0`, matching Python, including its treatment of unrelated settings.
- `FromMapping(AnyInfer.Json.JsonObject)` rejects unknown keys, wrong types and invalid
  values. Bool is never an integer/number. Integer fields reject decimal JSON numbers,
  even `1.0`; double fields accept integer/number JSON values. Do not coerce strings or null.
  Constructor validation uses native argument exceptions naming the affected field.
- `ToMapping()` returns a new immutable native `JsonObject` with all 17 snake_case fields
  and their actual typed values. `Merged(JsonObject overrides)` drops null overrides,
  including unknown null keys, then applies strict mapping validation to non-null entries.
  With no applied overrides it returns this instance. Preserve defaults and validation;
  never change the original instance or accept unchecked record `with` assignments.
- Numeric validation must reject NaN/infinities where Python rejects them. Signed zero and
  inclusive/exclusive endpoints retain source behavior. The native double domain is
  explicit; no culture-dependent parsing or formatting.

## Execution checklist

- [x] **CTUNE.0 — Review the bounded contract.** Independently critique this plan against
  Python settings/tests and native JSON/value conventions. Gate: resolve actionable API,
  validation, mapping and scope contradictions before implementation. Ordinary native
  typing is not a requirement to emulate invalid Python runtime annotation bypasses.
  > NOTE: Independent source/JSON-convention critique accepted the exact 17 defaults,
  > recommended delta, narrow ranking predicate, checked native domain and null-override
  > behavior. Review artifact: `sdk-foundation-alignment/context-tuning-plan-review`.
- [x] **CTUNE.1 — Implement the immutable settings record.** Own only
  `src/csharp/AnyInfer/Context/ContextTuning.cs` and
  `src/csharp/AnyInfer.Tests/ContextTuningTests.cs`. Meaningful public controls cover all
  defaults/recommended changes, every validation family/endpoints/nonfinite input,
  strict mapping types and unknown names, nullable merge overrides, original preservation,
  ranking predicate independence and mapping round trip. Reuse existing native JSON types
  without adding a serializer or config policy. Gate from `src/csharp/`:
  `dotnet test AnyInfer.Tests/AnyInfer.Tests.csproj --no-restore -m:1 --filter FullyQualifiedName~ContextTuningTests`
  passes with zero compiler warnings. Leave heavy gates to root.
  > NOTE: Completed 2026-10-24: native immutable settings/mapping model and independently
  > expanded controls pass 24 targeted cases with zero compiler warnings. All 17 public
  > properties carry XML documentation. Independent source/control review is accepted in
  > `sdk-foundation-alignment/context-tuning-source-review`; paired evidence/full
  > qualification remain separate in CTUNE.2–4.
- [x] **CTUNE.2 — Define independent shared tuning evidence.** Before observer/checker
  implementation, settle an input-only `context-tuning-v1` development contract under
  `tests/fixtures/context-tuning-v1/` with literal operations/default/recommended/mapping/
  merge operands and no expected SDK outputs. Exact schema/observation fields, provenance,
  native-range exceptions and permitted error-name mapping must be reviewed and byte-frozen
  before observers are dispatched. Gate: schema/case closure and adversarial contract
  controls pass; no fixture lookup or semantic implementation is hidden in a verifier.
  > NOTE: The contract was settled in the Traycer artifact named in Resume. Root
  > requested an exact literal input book, corrected `python`/`csharp` identities and
  > closed success/error field/domain rules. Cold critique required an executable
  > observation schema, decoded integer/bool controls beyond JSON Schema, and an invalid
  > selection-order string. The revised contract has 58 cases (57 shared, one native-range
  > boundary). Root also corrected a schema conditional that excluded merge errors.
  > Independent critique and actual asset/control review are accepted in
  > `sdk-foundation-alignment/context-tuning-evidence-contract-review`. The four files are
  > byte-frozen below; 12 independent pure controls and Ruff check/format pass. CTUNE.3 may
  > now author observers/checker against this fixed protocol. No paired execution has run.
  > Gate sequencing: CTUNE.2 validates and freezes the literal corpus/schemas with pure
  > schema/case controls. CTUNE.3 implements and tests checker-level decoded scalar checks;
  > a JSON Schema integer alone must never be treated as that stricter control.

  | Frozen development asset | Actual SHA-256 |
  |---|---|
  | `inputs.json` | `122298b5b1631317db9aa93e428faa81a00ece6da9ba9694026a57cd050b30e6` |
  | `schema.json` | `f8c79b38bff6f0acbed27c74e6112806a6fa927124d56890a7b253b566ec4884` |
  | `observations.schema.json` | `9ee537e939ced40c3f81ba6e19d7988daff5dc3682ed64ccef4a572334182e86` |
  | `README.md` | `484edc6784e2c7db87ed0e0a808d549f31910ffdde42ab2d2c6c0d7bdf43843c` |
  - [x] **CTUNE.2a — Materialize the reviewed assets.** After critique closure, copy the
    exact contract to `tests/fixtures/context-tuning-v1/{inputs.json,schema.json,
    observations.schema.json,README.md}` as UTF-8 without BOM and with LF newlines.
    Gate: 58 ordinal-unique IDs, 57 shared / one native-range case, all input cases validate
    structurally, both standalone Draft 2020-12 schemas validate, and actual SHA-256
    digests are recorded before observers/checker code starts. No expected SDK outputs.
    > NOTE: Completed 2026-10-24. The reviewed literal inputs and standalone schemas were
    > copied byte-for-byte to `tests/fixtures/context-tuning-v1/` as UTF-8 LF files. Pure
    > validation found 58 ordinal-unique IDs (57 shared, one native-range), accepted the
    > input schema, and checked both Draft 2020-12 schemas. Asset SHA-256 values are in the
    > fixture README; its completed-file SHA-256 is
    > `484edc6784e2c7db87ed0e0a808d549f31910ffdde42ab2d2c6c0d7bdf43843c`
    > and is intentionally not self-embedded.
  - [x] **CTUNE.2b — Independently test the schema/corpus contract.** Own
    `tests/test_context_tuning_profile.py`. Exercise case/domain/key closure, both schema
    definitions, valid merge/non-merge success and error variants, incorrect payload shapes,
    native-range allowance and raw input distinctions such as `1.0` in the wrong-type case.
    Do not implement SDK settings or duplicate its default map as an outcome oracle.
    Gate: `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests/test_context_tuning_profile.py`
    and Ruff pass. Schema's deliberate inability to reject integral floats is recorded;
    CTUNE.3 controls must reject those decoded values before qualification.
    > NOTE: Completed 2026-10-24. The independent pure controls pass 12 cases and Ruff;
    > they verify the closed 58-case input book, both Draft 2020-12 schemas, structural
    > success/error witnesses, and the documented integral-float schema limitation without
    > importing SDK settings or deriving outcomes. Root independently verified all four
    > fixture SHA-256 values before this checkbox was marked.
- [x] **CTUNE.3 — Execute independent public observers.** After CTUNE.2's exact paths and
  protocol are recorded, implement native/Python observers and strict comparison through
  `scripts/_csharp_observation.py`. Add the native development observer project and workspace
  gate only after independent review; preserve the existing implementation registry and
  every sealed/development profile. Gate: actual public settings observations match on all
  shared cases, explicit native range controls are observed, malformed/missing/extra/stale
  observations fail closed. This does not qualify a whole context strategy.
  - [x] **CTUNE.3a — Independent Python observer.** Own only
    `scripts/observe_python_context_tuning.py`. Use public Python settings calls and actual
    dictionary/identity/sign observations, the reviewed `--observe INPUT OUTPUT` CLI and
    common provenance envelope. No SDK outcome/default calculation or native invocation.
    Gate: all literal cases are actually observed; targeted observer controls and Ruff pass.
    > NOTE: Completed 2026-10-24. Public Python calls directly observe all 58 literal cases;
    > Ruff check/format pass. Independent source review accepts the actual mapping,
    > round-trip, identity, sign and provenance projections. Root's fresh paired run is
    > `.tmp-tests/context-tuning/run-20ikmyh3`; it observes 57 shared matches and the separate
    > Python-success/native-overflow boundary. This is development evidence on a dirty tree.
  - [x] **CTUNE.3b — Independent native observer.** Own only the new nonpackable
    `src/csharp/AnyInfer.ContextTuning/{AnyInfer.ContextTuning.csproj,Program.cs}`. Use public
    native settings APIs; a typed JSON codec may preserve raw integer/float types and create
    `JsonInteger(BigInteger)` for the native-range operand before calling `FromMapping`.
    Never reject that operand in an infrastructure Int64 parser or fabricate a settings
    exception. CLI takes `INPUT OUTPUT`; source/dirty metadata follow existing observers
    with `ContextTuningSourceDirty`. Root owns solution registration and restore/build slot.
    Gate: zero-warning project build and actual complete native observations pass review.
    > NOTE: Completed 2026-10-24. Root registered/restored the nonpackable observer; the
    > source-stamped targeted build passes with zero warnings/errors. Actual observations
    > agree with Python on all 57 shared cases; the oversized integer reaches public
    > `FromMapping` and raises `ArgumentException` at operation. Source review confirms
    > projection/codec failures stay outside public-error capture. No sealed assets change.
  - [x] **CTUNE.3c — Strict checker and independent controls.** Own checker
    `scripts/check_csharp_context_tuning.py` separately from controls
    `tests/test_csharp_context_tuning.py`. Reuse `_csharp_observation.RunnerConfig` with
    Python path above, native project `AnyInfer.ContextTuning`, csproj
    `AnyInfer.ContextTuning/AnyInfer.ContextTuning.csproj`, and dirty property above.
    Gate: malformed/stale/extra/missing/type/conflicting evidence fails closed; explicitly
    reject input version `1.0`, observed count/default-chunk `1.0`, and bool-as-integer.
    Compare all real public observations within the seven permitted float paths only;
    report the observed native range boundary separately. No blanket normalization.
    > NOTE: Completed 2026-10-24. Independent controls pass 28 cases and Ruff check/format.
    > Real CLI launch, strict decoded scalars/provenance, complete coverage, merge shapes,
    > error boundaries and signed-zero loss/gain are controlled. Review repairs separate
    > the mapping-derived sign list from round-trip sign preservation and retain signs in
    > base snapshots. Fresh real pairing still passes 57 shared cases plus one separately
    > observed native range boundary. No outcomes/defaults are calculated by the checker.
  - [x] **CTUNE.3d — Integrate reviewed qualification.** Root adds the native project to
    `src/csharp/AnyInfer.sln`, registers the checker in `workspace.py` after tool-loop
    observations and before the binding inventory, and adds its scripts to `LINT_PATHS`.
    Update exact ordered commands/count controls in `tests/test_workspace.py` (27 total
    workspace steps, 14 C# steps). Gate: real paired run and focused workspace controls
    pass; CTUNE.4 owns the final serialized full gate and commit.
    > NOTE: Completed 2026-10-24. Solution registration and exact workspace/lint ordering
    > pass independent review; 72 focused workspace controls and Ruff check/format pass.
    > The gate now has 27 steps, including 14 native steps. CTUNE.3a–d source/control and
    > actual paired-evidence acceptance is recorded in Traycer
    > `sdk-foundation-alignment/context-tuning-observer-review`. Full qualification follows.
- [ ] **CTUNE.4 — Document and qualify the bounded feature.** Describe the native settings
  API and current standalone scope in the C# reference; do not claim context request/config
  support. Root updates the parent resume note and subsystem inventory, preserving all 235
  root completion marks. Extend `scripts/check_csharp_package.py`'s isolated consumer with
  public settings/default/recommended/mapping/merge checks. Gate: independent source/control
  review, serialized full workspace,
  package-only consumer, frozen integrity and explicit-path commit pass. Record the exact
  checkpoint and next SDK.9a document/ranking/selection work before retiring this leaf.
  > NOTE: Independent source/control, package-consumer and documentation reviews are
  > accepted. Full serialized shell `0403707d-9ded-4c33-aebc-c6b1ae3525ba` passes all 27
  > steps in 259.6s, including 1,160 native unit / 93 conformance tests, all six paired
  > development profiles, the external package consumer, exact examples and strict docs.
  > It uses a fresh pytest cache under `.tmp-tests/pytest-cache/ctune-full-20261024`.
  > The earlier shell `cbd3d59e-dbb4-4562-ba1c-c0cd3c5a5f5f` is retained as failed: four
  > pytest phases hit the known access-denied root `.pytest_cache` during teardown; all
  > native stages passed. No source/test/frozen-input change was made for the retry.
  > Frozen v0 verification retains SHA-256
  > `16122cca198d9e688d3c4b5724ac11f0324a4390d8e8589e443fe04a48e81391`.
  > Explicit-path source commit and clean-revision native qualification remain to finish
  > this box. SDK.9a/9b, global root completion marks and publication remain open.

## Resume

Resume at CTUNE.4's explicit-path source commit and clean qualification after the full gate,
accepted CTUNE.0/2/3 reviews, CTUNE.1's targeted gate and ALIGN.5b
qualification. The catalog/plan checkpoint is `028450eb4cc40d9b25a7bfff30d3ceeb5ab36234`;
the preceding audit/checker checkpoint is `8ce6bc0`. Check Git before editing.
The settings implementation and development evidence assets are uncommitted. A fresh paired
run has 57 shared matches plus one separately observed range boundary; the working-tree full
workspace passes all 27 steps. CTUNE.2's accepted contract is
in Traycer artifact `sdk-foundation-alignment/context-tuning-evidence-contract`; preserve
the frozen bytes above during CTUNE.3. This plan authorizes no sealed release,
package publication or data-authority migration.
