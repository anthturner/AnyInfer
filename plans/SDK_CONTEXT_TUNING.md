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
- [ ] **CTUNE.1 — Implement the immutable settings record.** Own only
  `src/csharp/AnyInfer/Context/ContextTuning.cs` and
  `src/csharp/AnyInfer.Tests/ContextTuningTests.cs`. Meaningful public controls cover all
  defaults/recommended changes, every validation family/endpoints/nonfinite input,
  strict mapping types and unknown names, nullable merge overrides, original preservation,
  ranking predicate independence and mapping round trip. Reuse existing native JSON types
  without adding a serializer or config policy. Gate from `src/csharp/`:
  `dotnet test AnyInfer.Tests/AnyInfer.Tests.csproj --no-restore -m:1 --filter FullyQualifiedName~ContextTuningTests`
  passes with zero compiler warnings. Leave heavy gates to root.
- [ ] **CTUNE.2 — Define independent shared tuning evidence.** Before observer/checker
  implementation, settle an input-only `context-tuning-v1` development contract under
  `tests/fixtures/context-tuning-v1/` with literal operations/default/recommended/mapping/
  merge operands and no expected SDK outputs. Exact schema/observation fields, provenance,
  native-range exceptions and permitted error-name mapping must be reviewed and byte-frozen
  before observers are dispatched. Gate: schema/case closure and adversarial contract
  controls pass; no fixture lookup or semantic implementation is hidden in a verifier.
- [ ] **CTUNE.3 — Execute independent public observers.** After CTUNE.2's exact paths and
  protocol are recorded, implement native/Python observers and strict comparison through
  `scripts/_csharp_observation.py`. Add the native development observer project and workspace
  gate only after independent review; preserve the existing implementation registry and
  every sealed/development profile. Gate: actual public settings observations match on all
  shared cases, explicit native range controls are observed, malformed/missing/extra/stale
  observations fail closed. This does not qualify a whole context strategy.
- [ ] **CTUNE.4 — Document and qualify the bounded feature.** Describe the native settings
  API and current standalone scope in the C# reference; do not claim context request/config
  support. Root updates the parent resume note and subsystem inventory, preserving all 235
  root completion marks. Gate: independent source/control review, serialized full workspace,
  package-only consumer, frozen integrity and explicit-path commit pass. Record the exact
  checkpoint and next SDK.9a document/ranking/selection work before retiring this leaf.

## Resume

Start at CTUNE.0 after the catalog vocabulary slice's ALIGN.5b qualification. The current
audit/checker checkpoint is `8ce6bc0`; check Git for ongoing catalog changes before editing.
No context implementation is yet accepted, and this plan authorizes no sealed release,
package publication or data-authority migration.
