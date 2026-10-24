# Native context documents, structure and chunks

**Resume from the first unchecked box.** This is the bounded ALIGN.5e / SDK.9a execution
leaf under the user's autonomous parity authorization. Read `AGENTS.md`, `DESIGN.md`,
`ANYINFER_CSHARP_SDK.md`, `SDK_FOUNDATION_ALIGNMENT.md` and this whole checklist first.
Root owns decisions, Git, shared integration and serialized native/full gates. Workers
own disjoint paths and may tick only their assigned box after re-reading this plan;
coordinate each minimal plan edit with root. Never revert another worker's edits.

Qualified executable base: `dc74a3985bd0393ae81f199ef2b6b7657cd242c0`.
Plan-only handoff: `0325872`. Python behavioral source remains checkpoint
`199c3f833e568334b629edd7d89f41a3b76efe2a` and the unchanged current
`src/python/anyinfer/context/{documents.py,structure.py,pack.py}`. Source/probe/contract
artifacts under Traycer `sdk-foundation-alignment/context-primitives-*` support review;
the settled execution requirements are written here rather than requiring chat recovery.

## Scope and settled behavior

Port caller-supplied context documents, language/generated-path/import/declaration helpers
and deterministic splitting. No filesystem I/O, ranking/cache/deduplication, reduction,
selection/envelopes, history, config/client integration, provider or request-policy changes.
Python behavior, existing shared asset ownership and sealed v0 bytes remain unchanged.
This slice does not complete SDK.9a, SDK.11c or full parity.

### Native API

All public types are in `AnyInfer.Context`, with XML summaries on every public member.
Use sealed records with get-only state and native null guards for required references.

- `ContextDocument(string path, string content, string sha256, bool pinned = false,
  string? language = null, string extract = "")` is inert: retain supplied digest, text,
  language and extract without hashing, validating digest syntax or inferring metadata.
  Properties: `Path`, `Content`, `Sha256`, `Pinned`, `Language`, `Extract`.
- `ContextDocument.Of(string path, string content, bool pinned = false,
  string? language = null, string? extract = null)` hashes strict UTF-8 to lower-case SHA-256,
  detects language only for null, derives extract only for null; explicit empty opts out.
  `long BytesLength` returns the strict UTF-8 byte count.
- Static `ContextStructure`: `DetectLanguage(string path) -> string?`,
  `IsGeneratedPath(string path) -> bool`,
  `ImportedNames(string content, string? language = null) -> IReadOnlyList<string>`,
  `StructuralExtract(string content, string? language) -> string`.
  Public constants: `MaxExtractChars = 12000`, `MaxSectionChars = 2000`,
  `SmallFileVerbatimBytes = 512`, `TruncationMarker = "[truncated structural extract]"`.
- `Chunk(ContextDocument document, string text, long index, long startLine, long endLine)`
  retains `Document`, `Text`, `Index`, `StartLine`, `EndLine`; do not add new semantic
  range validation to this inert Python-equivalent value.
- Static `ContextPacking`: `MinChunkTokens = 64` and
  `SplitDocument(ContextDocument document, long chunkTokens = ContextTuning.DefaultChunkTokens)
  -> IReadOnlyList<Chunk>`. Return a caller-immutable collection, in source order.
  Document/Chunk contain immutable strings/scalars/references; do not introduce generic
  snapshot or custom equality machinery. Preserve ordinary generated record behavior.

### Text, paths and patterns

- Successful shared text uses valid Unicode scalars. Count/slice code points rather than
  UTF-16 units or bytes. A UTF-16 pair is one scalar; a lone surrogate in a raw document
  is preserved/counts as one code point in pure splitting, never replaced with U+FFFD.
  Strict UTF-8 operations (`Of`, `BytesLength`, nonempty `StructuralExtract`) fail on
  malformed surrogate input. Raw constructors do not force encoding. Pure import/path
  helpers must not normalize malformed text into replacement characters.
- Implement POSIX path classification independently of the host filesystem. Follow
  `PurePosixPath(path.lower())` suffix/name/parts behavior, including trailing/repeated
  slashes, dot components, hidden files, `..`, and literal backslashes. Do not use
  `System.IO.Path` for these semantics. Use exact Python suffix/generated/noise tables.
- Preserve every language's finite declaration patterns from `structure.py`; review
  literal punctuation, anchors, alternation and greediness. A native Regex matcher may
  use explicit scalar-aware word/space/nonspace fragments. Never use raw native
  `\w`, `\s`, `\S`, `\b`, a general caller-regex translator, or shadow text substitution.
  Known post-word boundaries become a next-scalar non-word/end check, including Ruby
  `attr_\w+`. Word membership comes from the pinned table below.
- Python whitespace is exactly U+0009..000D, U+001C..001F, U+0020, U+0085, U+00A0,
  U+1680, U+2000..200A, U+2028/2029/202F, U+205F, U+3000. `rstrip` uses this set.
  `splitlines` recognizes CRLF as one separator, LF/CR/VT/FF/U+001C..001E/U+0085/
  U+2028/U+2029, with no artificial trailing empty line; U+001F is not a line separator.
- Empty extraction returns empty; content of at most 512 strict UTF-8 bytes returns
  verbatim before language lookup; larger unknown-language content returns empty.
  Matching lines are rstripped and joined with LF. Check the 2000-code-point section
  ceiling before appending a subsequent matching line (one line may overshoot);
  a nonmatch resets the run. Over 12000 code points, slice, rstrip and append LF+marker.
- Imports use the exact language-independent import-line/quoted-piece/ASCII segment
  patterns, noise set and first-seen ordering. The language parameter is ignored.
- Split budget is `max(1, chunkTokens * 3)` code points. Avoid long multiplication
  overflow: with content length N, budget 1 for nonpositive tokens or N=0; if positive
  tokens >= ceil(N/3), take the content without multiplying; otherwise multiply by 3.
  For an oversized remaining window, prefer its last literal LF+LF at index >= floor
  `budget/4`, then last LF at that floor, else hard-cut. Boundaries include their LF(s).
  Spans count LF only, start at 1, and use `EndLine = StartLine + LFcount`; next start is
  previous end. CRLF contains LF, but CRLF blank lines are not literal LF+LF.
  Empty input yields one empty chunk, index 0, lines 1..1. Merge a final chunk shorter
  than 192 code points into its predecessor once; preserve predecessor index/start and
  final end. Example tokens=1: initial `a😀b`, `cde`, `f` becomes final `a😀b`, `cdef`;
  merging is not recursive. Reassembly is lossless.

### Deterministic Unicode baseline

Native context word membership is pinned to actual Python **3.13.15 / UCD 15.1.0**
`re.fullmatch(r"\w", chr(value))`, over U+0000..10FFFF excluding surrogate values.
The exhaustive probe finds 138558 members; the native host category predicate misses
622 at U+2EBF0..2EE5D. Do not use host categories plus a patch. Python >=3.11 remains
supported, but its Unicode tables vary: this native claim names one exact evidence
baseline, not all Python minor versions. No existing asset authority is moved.

`scripts/generate_csharp_context_unicode.py` produces
`src/csharp/AnyInfer/Context/PythonWordRanges.g.cs`. Internal API agreed between owners:
`PythonWordRanges.Contains(int value)` and `PythonWordRanges.RangePairs` as a read-only
span of sorted inclusive start/end integer pairs; include baseline/version/payload digest
constants. Surrogates/out-of-domain values are not members. Lookup is a binary search.
The generated source also emits assembly metadata `AnyInferContextPythonBaseline`,
`AnyInferContextUnicodeVersion` and `AnyInferContextWordPayloadSha256` with those exact
baseline/digest values. Observers read compiled metadata without a new public API or
private behavioral test seam; canonical full-file checking covers these attributes.

Write mode refuses any other Python/UCD version; independently check actual regex versus
`isalnum() or '_'` over all valid scalars. Canonical ranges are ordered, nonoverlapping,
maximal contiguous inclusive ranges; freeze exact range/member counts and a canonical
payload SHA in generator constants after independently recomputing them. Canonical payload
is one ASCII `START-END\n` line per inclusive range, including singletons; each endpoint
is exactly six upper-case hex digits. Root's independent actual baseline scan finds
749 ranges / 138558 members and SHA-256
`95e8d8ae8857ac3d5576bf1efb4c94311692d2be6fc9c6d364c3ba0dc494e643`.
`--check`
never writes, never silently regenerates from the current interpreter, and compares
committed ranges with those independent pins and canonical full-file rendering. Under
the exact baseline it additionally exhaustively compares actual Python membership;
under other supported Python it reports only pinned-byte validation. Pin generated
source bytes to UTF-8/no-BOM/LF in `.gitattributes`; no self-declared hash can qualify itself.

Paired development qualification requires the exact baseline interpreter/UCD and refuses
other runtimes explicitly. Pin only CI's native-csharp observer lane to Python3.13.15;
preserve the Python SDK's supported runtime/test matrix. Explain this contributor gate.

## Execution checklist

- [x] **CP.0 — Cold-critique the settled contract and this leaf.** Root resolves findings
  against actual source/runtime evidence. Gate: independent artifact review accepts API,
  Unicode authority/provenance, surrogate boundaries, overflow/cut rules, POSIX paths,
  finite patterns and CI interpreter handling; no hidden behavior decision remains.
  > NOTE: Accepted 2026-10-24 in Traycer
  > `sdk-foundation-alignment/context-primitives-contract-review`. Actual Python execution
  > confirms the single tail merge and two-chunk emoji witness. Root independently scanned
  > every valid scalar to establish the 749-range / 138558-member canonical digest above.
- [ ] **CP.1 — Generate the native word table.** Own only the generator and generated
  `PythonWordRanges.g.cs`. Implement the API/provenance/write/check contract above and
  report exact counts/canonical serialization/digests to root for independent verification.
  Gate: baseline generation followed by nonwriting `--check`, Ruff check/format, and a
  narrow script compilation pass. Native compilation waits for root's single slot.
- [ ] **CP.2 — Port the native primitives.** Own only
  `src/csharp/AnyInfer/Context/{ContextDocument.cs,ContextStructure.cs,ContextPacking.cs,PythonText.cs}`.
  Use CP.1's agreed internal table API; do not refactor existing Citation/manifest/media
  semantics. Implement the complete settled behavior above with public XML docs and no
  dependencies or I/O. Gate after CP.1 and root's slot: from `src/csharp/`,
  `dotnet build AnyInfer/AnyInfer.csproj --no-restore -m:1`, zero warnings.
- [ ] **CP.3 — Independently control generation and public primitives.** Own only
  `tests/test_csharp_context_unicode.py` and
  `src/csharp/AnyInfer.Tests/ContextPrimitiveTests.cs`. Use Python source and literal
  expected results, not the implementation's defaults or reconstructed output oracle.
  Cover version guard, malformed/overlapping/nonmaximal/out-of-range ranges, count/hash/
  template tampering, no-write checks and nonbaseline check semantics. Native controls
  cover raw/factory document distinctions, exact digest/bytes, explicit empty overrides,
  every suffix/generated-path family and POSIX edge, import noise/order/quotes, every
  declaration family and negative body, section reset/overshoot/truncation, whitespace/
  splitlines, all chunk cut/span/tail thresholds, empty/default/nonpositive/long extremes,
  astral cuts and malformed text boundaries. Include word boundary representatives
  U+0301, U+2163, U+203F, U+10400 and U+2EBEF/2EBF0/2EE5D/2EE5E, actual padded C
  `int <U+2EBF0>() {` and `import<U+2EBF0> module` no-import case. Gate: targeted
  no-cache Python controls plus Ruff; after CP.2 and root's slot,
  `dotnet test AnyInfer.Tests/AnyInfer.Tests.csproj --no-restore -m:1 --filter FullyQualifiedName~ContextPrimitiveTests`.
- [ ] **CP.4 — Freeze independent development evidence before observers.** Artifact owner
  defines the literal input-only `context-primitives-v1` casebook and executable closed
  input/observation schemas; cold review first. Cases must exercise the CP.3 behavior
  families, all pattern languages and path/Unicode boundary examples, without expected
  outputs, copied SDK validators or hidden oracle data. Shared text is valid scalar data;
  malformed surrogate controls stay native/Python unit evidence, not invalid UTF-8 assets.
  Root then records exact case IDs/counts, kind/scalar rules, source/version/table digest
  fields, error capture stages, integer/boolean decoded-type constraints and hash pins here.
  Only after acceptance materialize
  `tests/fixtures/context-primitives-v1/{inputs.json,schema.json,observations.schema.json,README.md}`.
  Independent pure controls belong in `tests/test_context_primitives_profile.py`.
  Gate: both schemas validate; exact input closure and meaningful mutation/schema controls
  pass without SDK imports; raw bytes are frozen and LF-stable before observer authoring.
- [ ] **CP.5 — Observe and compare actual independent runtimes.** Separate owners:
  `scripts/observe_python_context_primitives.py`; nonpackable .NET8 project
  `src/csharp/AnyInfer.ContextPrimitives/{AnyInfer.ContextPrimitives.csproj,Program.cs}`;
  `scripts/check_csharp_context_primitives.py`; independent checker controls
  `tests/test_csharp_context_primitives.py`. Reuse only generic raw/provenance/runner
  infrastructure in `_csharp_observation.py`, not other profiles' semantic validators.
  Observe public calls without recreating defaults or expected outputs. Capture errors
  only around public API execution; codec/projection/infrastructure errors propagate.
  Compare exact IDs, strings, ordered lists, nullable fields and decoded integer/boolean
  types; reject malformed/extra/missing evidence and stale revision/dirty/corpus/schema/
  Unicode/table provenance. Enforce the exact baseline before claiming paired matches.
  Python provenance uses its actual interpreter/UCD and an actual full-domain regex payload
  digest; native provenance reads the generated metadata on the compiled SDK assembly.
  Gate: independent adversarial controls and direct-script `--help` smoke pass; root
  registers/restores/builds the observer in the sole native slot, then a fresh actual paired
  run has zero mismatches. No expectation-copying, normalization of differences or silent skips.
- [ ] **CP.6 — Integrate public usage and scoped evidence.** Root serializes edits to
  `src/csharp/AnyInfer.sln`, `.gitattributes`, `workspace.py`, `tests/test_workspace.py`,
  `.github/workflows/ci.yml`, `docs/reference/csharp-sdk.md`,
  `docs/contributing/csharp-proof.md`, `scripts/check_csharp_package.py`, and
  `plans/CSHARP_SDK_API_PARITY.md`. Register generated-data check and the new observer
  after existing context tuning, update exact workspace/CI command controls and lint
  inputs, and pin native lane interpreter. Add actual package-only consumer use of
  document factory, helpers and chunk reconstruction; qualify installed public APIs.
  Document standalone scope and Unicode baseline; retain missing reducers/history/config.
  Update only actually closed evidence rows using fresh public metadata and real tests;
  do not check the 235 original completion boxes or any SDK parent milestone.
  Gate: targeted workspace/packaging/control/link checks and real evidence checker pass;
  external consumer execution belongs to CP.7's full gate.
- [ ] **CP.7 — Review, qualify and continue the burn-down.** Cold-review source, finite
  patterns/generated table, controls, observers/checker, docs/package and ledger.
  Root runs one serialized `workspace.cmd check` with fresh pytest cache
  `.tmp-tests/pytest-cache/context-primitives-full`; verify sealed v0 explicitly with
  `.venv/Scripts/python.exe scripts/freeze_release.py --verify core-generation-v0`.
  Gate: every workspace step, prior six profiles and new primitive evidence, actual package
  consumer/examples and strict docs pass. Commit explicit paths; qualify exact clean
  source with `workspace.cmd check --only csharp` using another fresh cache. Inspect both
  runtimes' clean revision/dirty/hash/table provenance. Record failures and actual results,
  reconcile parent/index, then retire this leaf with a pinned Git source receipt.
  Continue SDK.9a ranking/deduplication, envelopes/selection/reducers and history; neither
  standalone primitives nor a finite profile closes all strategies or release support.

## Resume

Resume at CP.1/CP.2 implementation and independent CP.3 controls. CP.0 is accepted;
these owners may run concurrently on their disjoint files. Native builds and plan notes
stay serialized by root.
CP.4's contract work may proceed independently, but observers require the frozen asset/
control gate. Root retains source qualification `dc74a39` separately from this plan.
