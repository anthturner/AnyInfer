---
kind: review
title: Review of the rewritten language-neutral foundation plan
---

# Review of the rewritten foundation plan

> **Snapshot review.** Findings below concern the exact document hashes recorded at
> the end of the original review. The user subsequently selected a planning amendment;
> follow-up decisions and dispositions are recorded below. The master remains the only
> execution plan, and no implementation is authorized by this review.

**Reviewed:** 2026-10-15. **Python source HEAD:**
`13b9e65acfb01038464069ca5fa80f50a9df035c`.
**Scope:** static review of the active master, specification draft, supporting audits,
and current Python implementation. No implementation, fixtures, runtime probes, or tests
were created or run. The master and specification draft were left unchanged.

The Python → Python+C# → additional native languages roadmap remains coherent. The
rewrite makes substantial scope choices: accounting moves to M3, W1 is closed by excluding
the affected inputs, malformed-schema comparison is broadened and simplified, and the
private capture design is replaced with a structured-issue seam. This review treats those
choices as intentional; it does not recommend restoring the previous plan wholesale.

**Original snapshot disposition:** useful direction, but not ready to execute M1 as written. R1 and R2
conflict with preserving current Python behavior. R3–R8 need explicit dispositions before
their affected contracts and fixtures are frozen. This review is not an execution checklist
or an approval to implement; the [master](../ANYINFER_LANGUAGE_NEUTRAL_FOUNDATION.md) owns
execution status.

## Findings in priority order

### R1 — High: the proposed Issue cannot reproduce current Python strings

**Where:** master M1.1; specification §7.

M1.1 makes `validate` render its string tuple solely from `Issue(rule, instance_path,
schema_path, params)`, while requiring byte-identical current feedback. The specified
`type` issue keeps the instance's kind, rather than its value. Validating `"x"` and `"y"`
against `{"type":"integer"}` therefore produces the same portable issue, but current
Python produces different messages. `enum` also renders the actual offending value.
Malformed JSON and invalid schemas retain native exception detail that their proposed
parameter-free issues discard.

This is information loss, not a renderer implementation detail. Current
`src/anyinfer/schema/validate.py:109–123` preserves `SchemaError.message` and each selected
`ValidationError.message`; the installed `jsonschema/_keywords.py:269–287` constructs
`enum` and `type` messages from the actual instance. The new path also serves Python's
broader schemas, including keywords outside the portable subset, so subset-only rendering
must not replace the existing behavior for those callers.

**Minimum amendment:** retain a lossless native assessment/rendered message alongside
the portable issue projection. Keep the native selected strings as the existing API and
repair input. Define how rules outside the portable subset pass through unchanged, and
verify compatibility across those rules as well as the admitted subset.

### R2 — High: unknown-keyword rejection conflicts with the native Python oracle

**Where:** specification §4, unknown-keyword row; master A15 and M1.1.

The draft requires an unknown schema keyword to fail with `unsupported_input` before
inference and explicitly denies an extension exception. Current Python accepts, for
example, `{"type":"object","vendor-note":true}` and can return a valid `{}` response.
It has no schema-admission preflight: `_client/generation.py:1050–1065` reaches validation
after adapter consumption, and `schema/validate.py:109–117` delegates to `jsonschema`.
The installed validator filters its assertion implementations to recognized keywords
(`jsonschema/validators.py:293–296`); an unknown keyword is ignored.

Consequently the native Python oracle cannot satisfy this normative rule while keeping
current behavior. The 66-case inventory contains no unknown-keyword case, so a green run
would currently hide this mismatch.

**Minimum amendment:** put these inputs outside v0's guarantees, or define an honest
Python extension treatment. If rejection is intended to become new Python behavior,
classify and separately authorize that change. Do not manufacture rejection in the
conformance driver. Add a boundary case that demonstrates the selected treatment.

### R3 — High: the common repair fixture still requires Python-specific wording

**Where:** specification §7, §14 example and comparison rules; master A6.

Section 7 allows each language to render its own issue wording, but §14 stores the entire
Python correction message literally and requires each adapter entry's messages to match.
Its required-property example embeds `<root>: 'age' is a required property`. A C#
implementation using different permitted wording would fail that comparison despite
matching the issues and exact outer template.

There is also a narrower evidence problem with A6's recomputation. Equality of rendered
strings does not establish typed issue identity. Current `_describe` renders the path
`["a.b"]` identically to `["a","b"]`. With the same invalid value at both locations,
the messages can be identical while the schema/instance paths and selection order differ.
Revalidating captured text and comparing only the resulting prose cannot prove which
typed occurrences the production validation actually selected.

**Minimum amendment:** give repair suffixes an explicit semantic expectation in the common
fixture format: exact outer template and message/history placement, ordered portable
issues, and implementation-local rendering checks. Preserve literal Python feedback in
Python-specific compatibility evidence. Observe the actual selected assessment from the
production helper invocation where typed identity is claimed; a small call-local seam
may suffice without restoring the entire old capture design. Add a dotted-key/nested-path
collision case to verify that the chosen seam proves more than prose equality.

### R4 — High: the release identity does not bind the specification or reference

**Where:** master A1, A13, M1.7 and M1.G; specification §15–15.1.

The release file hashes fixtures and schemas, but does not hash the normative specification
or reference manifest. `reference_manifest` is only a path. Editing the normative contract
or the interpreter/dependency/warning-policy declaration can therefore leave the same
`release_sha256` valid. That is weaker than the promised immutable shared foundation.

The oracle also reports only `git_revision`, with no clean-worktree requirement or source
content identity. M0, M1.1 and M1.5 intentionally change Python before the oracle run;
an uncommitted run can report the old HEAD while executing different source. An import
location check helps locate the code but does not bind its contents.

**Minimum amendment:** bind the normative text and reference manifest into the release
identity, and require an identified clean reference revision or an explicit content-bound
source snapshot. State the oracle preflight that enforces the chosen environment binding.
Keep production dependency ranges separate from the reference environment. A minimal
manifest is reasonable, but its reproducibility claim must match what is actually bound.

### R5 — Medium: report completeness and upstream maintenance lack enforceable rules

**Where:** master M1.G, M2.G and M4.G; specification §15–16.

The stated gates compare verdicts and require zero failures/errors, but never require an
exact, unique case-ID set derived from the release. Empty reports, a matching subset, or
duplicate IDs are not expressly invalid. The report schema example and counts alone do
not establish that every mandatory case ran. Extension exceptions also need to be limited
to the explicitly marked boundary cases and their declared feature names.

The rewrite retains a freeze command but drops the previously requested upstream
maintenance deliverable. It does not assign rules for compatible versus breaking changes,
reference rebaselining, per-implementation supported revisions, or retaining usable old
releases. Fixture paths are not revisioned: changing an existing fixture and writing a
new release file would invalidate the old release in that checkout unless a retrieval or
retention mechanism is defined.

**Minimum amendment:** require drivers/comparison to reject missing, duplicate, extra,
wrong-release, and improperly exempted cases; validate counts and report schemas; forbid
a successful port gate with failures/errors. Assign a short upstream-maintenance policy
before independent releases: change classification, review requirements, immutable release
retrieval, reference changes, and supported-revision declarations. This can remain small
and tool-neutral.

### R6 — Medium: transport fixtures cannot express the required HTTP case or prove requests

**Where:** specification §14 transport format and §17 transport inventory; master M1.6/M2.5.

The transport format supplies base64 frames directly to the stream parser, but the inventory
includes `non-sse-error-body-status-503`. That case needs an HTTP status and response headers,
which the input format does not carry. Python checks status and Content-Type before entering
the SSE parser (`providers/openai_compat.py:312–332`). A body alone cannot prove HTTP error
classification; the driver must not take the status from the expected outcome.

The same fixtures only assert incoming bytes → adapter events. M2.5 nevertheless uses them
as the gate for an actual OpenAI-compatible adapter. A C# adapter could pass parsing while
sending incorrect messages, sampling, or stream settings in its POST. Those transformations
are material Python adapter behavior (`openai_compat.py:153–200`, `300–310`, `411–432`).

**Minimum amendment:** add an explicit HTTP response envelope with status, headers, and
body chunks, plus outbound fake-transport expectations for the bounded adapter contract.
Cover buffered and streamed requests, message projection, supplied/omitted sampling, and
the selected prompt mechanism. Keep parser-only tests as a distinct layer if useful.

### R7 — Medium: several mandatory behaviors have no corresponding conformance evidence

**Where:** specification §2, §3, §7 and §17; master M1.5/M2.2.

The profile promises a per-entry timeout and byte limit, but expected calls do not compare
either wire field, the adapter script has no suspension action, and the inventory has no
limit/reset cases. The virtual clock controls health and backoff only; Python's timeout uses
`asyncio.timeout` (`_client/generation.py:883–919`), while response byte enforcement belongs
to the actual adapter/transport. Advancing the proposed clock does not exercise either.

Other concrete gaps are the normative lazy invalid-second-target rule and failing-rule
comparisons for `const`, numeric bounds, `maxLength`, and item-count bounds. A single valid
full-subset schema does not prove issue identity, parameters, or selection when those rules
fail. C#-only unit coverage does not establish agreement with Python's oracle.

**Minimum amendment:** map mandatory rules to named common cases before fixing the corpus
count. Include compared timeout/byte fields, a deterministic native timeout/suspension
strategy and correction reset case, raw-byte limit cases at the transport boundary, the
deferred invalid target, and negative issue cases for the admitted rules. Alternatively
narrow the promised v0 behavior explicitly rather than implying coverage from a green run.

### R8 — Medium: tagged observation values collide with ordinary admitted JSON objects

**Where:** master A9; specification §13.

Tagged forms are interpreted in expected observation positions, but there is no literal-object
escape. For example, the admitted schema `{"const":{"$codepoints":[65]}}` can accept the
ordinary response object `{"$codepoints":[65]}`. Its natural `expected.structured` encoding
then denotes a tagged string instead of that object. The same problem exists for a literal
`{"$special":"NaN"}` object. Excluding nonfinite response literals or lone surrogates does
not exclude these ordinary objects.

**Minimum amendment:** make the encoding injective with an explicit literal-object escape
or a fully typed value envelope. A smaller v0 alternative is to defer tag interpretation
alongside the excluded values and use ordinary JSON observations for this release. Add a
literal reserved-key object case before enabling tags.

## Small execution corrections

- M0.1's exhaustive path inventory and named-file-only gate omit the shard READMEs. Their
  editable-install commands use the old paths: `src/anyinfer-store/README.md:14`,
  `src/anyinfer-shared/README.md:19`, and `src/anyinfer-confidential/README.md:13–14`.
  Name these files and permit their path edits during the move.
- The §4 layout table places the broken fixture at
  `tests/testing/portable/bad_fixtures/missing-expected.json`, while M1.3 correctly places
  it under `bad_fixtures/core-generation/`. Use one literal path.
- A4's claim that a single adapter invocation boundary is *all* later accounting needs is
  stronger than the deferred design establishes. Keep the boundary as a useful hook;
  reserve the actual lifecycle, usage-provenance, no-entry-operation, and terminal-outcome
  observation decisions for M3 rather than promising that they require no other seams.

## Confirmed fit and review limits

- The documented original-message repair construction, latest-only correction history,
  same-target correction, local budget/clamp, and restart/reset behavior match the current
  `_run_attempt` / `_route_events` control flow. The post-content protocol-error guard
  remains active across corrections within the same route attempt.
- The current/next/future language roadmap, independent native drivers, separation of the
  Python product from the bounded C# proof, and a separately gated accounting tranche are
  structurally consistent. This review does not reopen the selected source layout or
  `net8.0` target.
- Static Markdown checking resolved all 135 local links in the reviewed planning tree.
  This checks file targets, not headings or future implementation paths.
- Two independent delegated read-only reviews covered native semantics/conformance and
  source-layout effects. The coordinator checked the material findings against the actual
  documents and source. No new native observations or conformance pass are claimed.

The active documents were untracked at review time. Their SHA-256 identities below bind
the reviewed text independently of the Python source HEAD:

```text
README.md
9AAFE067E5C3E1399B1A3E4F2CDDA042D0C2775BE98E79C9FD1EEF11565C5B28
ANYINFER_LANGUAGE_NEUTRAL_FOUNDATION.md
58F5837ABE69AEF450731A3BE7E1DDB06E35F0E764E11A92FEA29EEC693F715B
SPECIFICATION_DRAFT.md
22DF5F8C337C14D5DBCA16FA0AFEE3778883EF7B982D85300951107921CCF135
```

## Follow-up decisions — 2026-10-15

The user requested that adjustments be called out and choices presented before changing
the active plan. The structured responses selected:

- **Repair evidence:** use the smaller lossless seam unless it significantly complicates
  SDK integration or development; otherwise restore the earlier capture design. The
  coordinator selected the smaller seam because it is private conformance infrastructure,
  adds no caller setup, and retains the native selected assessment rather than replaying
  validation. Its bounded evidence/isolation gates remain mandatory. Failure to meet those
  gates triggers reassessment against the archived full design.
- **Unknown keywords:** declare an explicit Python extension, preserving native Python's
  behavior and distinguishing boundary cases from core conformance passes.
- **Proof scope:** expand the bounded proof to cover its stated limits and outgoing HTTP
  behavior. Coverage determines the case inventory; a fixed fixture count is not the gate.

The proposed release/report integrity, observation-encoding, and path corrections accompany
those choices. They are planning changes only. Native behavior, implementation, and fixture
creation still require execution of the master plan's separately authorized phases.

## Planning dispositions after amendment

These findings are addressed in the active planning text. They are not claims that the
future implementation or corpus has passed its gates.

| Finding | Planned resolution and verification owner |
|---|---|
| R1 — lossless native feedback | A6/M1.1 retain actual selected native strings and occurrence metadata, with portable projection beside them. Compatibility/capture tests have their own `tests/test_schema_capture.py` gate before the portable driver exists. |
| R2 — unknown keywords | A15 and specification §4 declare `schema.unknown_keywords_ignored`; its boundary case cannot become a fake native Python rejection. |
| R3 — repair comparison/evidence | Specification §§7/8/14 separate implementation-local bullets from shared issues/template expectations. Source assessments and later correction entries have separate ordinals linked by assessment reference; actual invocation evidence replaces replay. |
| R4 — reference/release binding | A13/M1.7 bind a clean committed reference source/environment. M1.G hashes normative text, inventory, schemas, fixtures, reference manifest and environment artifact; reference revision A and later retrieval record B are distinct. |
| R5 — complete reports/maintenance | M1.2U owns maintenance policy; M1.3–M1.5 own inventory/coverage/report verification. M1.G and port gates require complete unique cases, valid hashes/counts, permitted extensions, and no failures/errors. Old releases remain reconstructible. |
| R6 — HTTP proof | Specification §14 distinguishes adapter and real-core HTTP cases, uses ordered independent response inputs, and checks actual outgoing requests plus functional byte enforcement. M1.6/M2.5 own both directions of the proof. |
| R7 — coverage gaps | Specification §17 names the additional negative-rule, parsing, usage, lazy-target, native timeout, cleanup and byte-reset cases/predicates. A machine-readable inventory and explicit staged/full coverage gates replace a fixed case count. Annotation forms also match the installed Draft 2020-12 meta-schema: strings for title/description/comment, arrays for examples; malformed forms retain late handling. |
| R8 — value-tag collisions | A9/§13 use ordinary JSON in v0; reserved-looking object keys remain literal data. Exotic values and an injective future codec are deferred together. |
| Small execution corrections | M0 names shard README edits; the broken-fixture path is consistent; M3 owns remaining accounting seams. |

The amendment's cold review additionally found missing normative promotion of the fixture
protocol and a missing explicit C# counterpart to Python timer evidence. Both now have
owners and shared predicates. Bootstrap checks also corrected three sequencing problems:
M1.1 no longer requires M1.5's directory; pre-freeze observations do not claim a nonexistent
release identity; and M2.4 does not require M2.5's HTTP implementation. M1.G creates the
candidate identity before producing the first qualified Python report; M2.5 produces the
first complete C# report.

The final delegated read-only consistency review reported no remaining material blocker.
Coordinator checks verified local Markdown targets, parseable JSON examples, unchecked
future boxes, and unchanged tracked source. No implementation, fixtures, native probes,
runtime test run, commit, or release was produced. The active master remains the only
execution checklist; the planning pass is ready for another model's independent review.
