# Portability diff tool (follow-on plan)

> **Status:** implemented and tested 2026-08-12, same day as the plan. Sketched from the
> same differentiation brainstorm as `TIERED_ENCRYPTED_PLANS.md`, but scoped separately:
> this is not a confidentiality feature, it's built on the existing determinism/validation
> story (`compare()`, deterministic workstream construction) and has no dependency on the
> confidentiality tiers plan.
> **Plan date:** 2026-08-12.
> **Authority:** living implementation plan, not an architecture decision. It packages an
> existing public surface (`anyinfer.compare`) into a diffable artifact; it proposes no new
> decision-making, ranking, or routing behavior and therefore does not touch DESIGN.md's
> "no load balancing" / "compare() reports, never ranks" boundary (§2 non-goals) — see §1.

## Implementation status (2026-08-12)

Delivered in one session, following §5's order exactly, gate-passing throughout:

1. **Fixture schema** — `FIXTURE_SCHEMA_VERSION = 1` in `anyinfer.compare_diff`:
   `{schema_version, fixtures: [{id, request: {messages: [{role, text}]}, targets: [...]}]}`.
   Scoped to messages only for v1, not the full `GenerationRequest` surface (schema/tools/
   sampling) — additive, so a future version can extend `request` without breaking
   existing files, matching the "additive, not breaking" requirement.
2. **`load_fixtures()`/`snapshot()`** — implemented exactly as specified: `snapshot()`
   persists `TargetComparison.to_dict()` verbatim, keyed by fixture id then target string,
   no new result data model.
3. **`diff()`** — a generic recursive structural differ (handles nested dicts and
   position-matched lists, e.g. the `dropped` parameter list), reusing `compare()`'s own
   field names in every summary line rather than inventing new vocabulary.
4. **CLI** — `anyinfer compare --snapshot`, `--diff BASELINE CURRENT` (exit 1 on any
   difference, CI-friendly), and `--diff-request ID --diff-target-a A --diff-target-b B`
   (the ad hoc, no-baseline-file customer-facing mode), all thin wrappers over the same
   three library functions, sharing the existing `compare` subcommand and its request-
   shaping flags rather than a separate command.
5. **Illustrative fixture** — `fixtures/compare-diff/fixtures.json` (two fixtures, three
   real providers: `openai`, `anthropic`, `ollama`) plus a checked-in
   `baseline.snapshot.json`. Credential presence, not validity, is all `compare()`'s
   resolution needs (it never dispatches) — the fixture uses obviously-fake API key
   strings, documented as such in `fixtures/compare-diff/README.md`.
6. **CI regression check** — `tests/test_compare_diff_regression.py`, part of this repo's
   own gate-passing test suite: snapshots the illustrative fixtures live and diffs against
   the checked-in baseline, failing with the rendered diff text on any drift; a second test
   asserts every illustrative target stays resolvable (catching a typo'd target id or a
   provider rename silently going unnoticed).
7. **Docs** — `docs/reference/api/compare-diff.md` (full API reference) and a new section
   in `docs/guides/comparing-targets.md` walking through both use cases, presented as a
   matched pair with the Confidentiality Tiers doc per this plan's own §5 item 7.

**Open question from §6 not resolved here** (deliberately, per its own framing —
"worth scoping only after both tools exist independently"): whether snapshot/diff should
become the mechanized backbone of part of `contracts/DRIFT-CHECK.md`'s procedure. Both
tools now exist independently; that scoping question is left for whoever picks it up next.

## 1. What problem this answers

`compare.py`'s module docstring already states its contract precisely: "assembles decisions
the core already makes... never ranks targets... caller order is preserved deliberately."
`TargetComparison` is therefore already a deterministic, structured record of what a given
request becomes on a given target — mechanism rungs, dropped parameters, cache plan, cost
estimate, fit against budget — as a plain, JSON-safe (`to_dict()`) value.

What's missing is treating that record as something to *diff*, not just something to
compute once and read. Two concrete needs came out of the brainstorm:

1. **Regression detection**: does a code change (adapter update, dependency bump, provider
   preset change) silently alter what the same fixed request becomes on the same target?
   Today that's only checkable by re-reading `compare()` output by eye.
2. **Portability reporting**: when a customer is deciding whether to move a workload from
   provider A to provider B, "here's a diff of exactly what changes" (a dropped parameter,
   a weaker structured-output mechanism, a cache-plan loss, a cost delta) is a much stronger
   answer than prose documentation of feature parity.

Both needs are served by the same primitive: snapshot `TargetComparison.to_dict()` output
for a fixed set of requests against a fixed set of targets, and diff two snapshots
structurally.

## 2. Relationship to provider drift checking — complementary, not overlapping

`contracts/DRIFT-CHECK.md` audits whether AnyInfer's *claims* about a provider's wire
protocol still match that provider's *current public docs* — an external-facing check. This
tool audits whether AnyInfer's own *decisions* (mechanism selection, parameter dropping,
cache planning, cost estimation) for a *fixed* request are stable over time and across a
code change — an internal, mechanical check with no network calls to a provider's docs
involved. A drift-check failure means "the world changed and our contract snapshot is
stale." A portability-diff failure means "our own code changed what it decides, and nobody
noticed." They can share output format conventions but are otherwise independent tools.

## 3. Scope

### Included
- A snapshot command/function that runs `compare()` (or `compare()`'s embedding-target
  sibling) over a set of example requests against a set of targets, and serializes each
  `TargetComparison.to_dict()` (or `EmbeddingTargetComparison.to_dict()`) result to a stable
  JSON file.
- A diff command/function that takes two snapshots and reports, per request × target pair:
  fields that changed, fields that appeared/disappeared, and a plain-language summary line
  per change (e.g. "structured output mechanism dropped from `native` to `prompted`" —
  reusing the vocabulary `compare()` and `manifest.DroppedParameter` already use, not a new
  one).
- A CI-friendly mode: exit non-zero if a diff against a checked-in baseline snapshot is
  non-empty, so a regression is caught in review rather than discovered by a customer.
- A customer-facing mode: given two target names and one request, print the human-readable
  diff directly (no baseline file needed) — this is the "should I move from A to B" report.
- **Decided (2026-08-12): the fixture set (which requests, which targets) is a public,
  vendor-extensible surface, not an internal-only fixed list.** A vendor embedding AnyInfer
  defines their own fixtures against their own real request shapes and target list — their
  regression risk is their own requests, not AnyInfer's illustrative examples. Concretely
  this means the fixture format is a **documented, versioned schema** (not an ad hoc internal
  file), described in §5 item 1, with its own compatibility expectations: a fixture file that
  validates against schema version N should keep validating across patch/minor releases of
  this tool, the same stability discipline AnyInfer's other public wire/data contracts get.

### Explicitly excluded
- Any ranking, scoring, or recommendation ("target B is better") — the diff reports facts in
  caller order, exactly as `compare()` already does; adding a verdict would cross the same
  boundary pacing-informed routing would (DESIGN.md §2).
- Live provider calls of any kind — this only ever calls `compare()`, which is explicitly
  no-dispatch. A snapshot is deterministic given the same code and config, not a live probe.
- Auditing whether a provider's *external* documentation changed — that's
  `contracts/DRIFT-CHECK.md`'s job (§2), not this tool's.
- Persisting or transmitting snapshot data anywhere by default — snapshots are local files
  the caller owns, checked into their own repo/CI if they want history, exactly as any other
  test fixture would be.

## 4. Packaging

This has no prompt-content dependency and no confidentiality-tier dependency, so it lives as
a module inside `anyinfer` core (a natural neighbor to `compare.py` — working name
`anyinfer.compare_diff`), never a separate distribution.

**Decided (2026-08-12): library function and CLI ship together, not sequenced.** Since the
fixture set is now a public, vendor-extensible surface (§3), a programmatic API is required
from day one anyway — a vendor's own CI calling this as part of their build needs a function,
not a subprocess wrapping a CLI. The CLI (`anyinfer compare --snapshot` / `anyinfer compare
--diff`, per the existing `anyinfer` script entry point) is a thin wrapper over the same
public functions (`anyinfer.compare_diff.snapshot()`, `anyinfer.compare_diff.diff()`,
`anyinfer.compare_diff.load_fixtures()`), so there is exactly one implementation either
surface calls — the same "one source of truth" discipline
`TIERED_ENCRYPTED_PLANS.md` §4 applies to `confidential_execution_status()`.

## 5. Suggested implementation order

1. Define the **public, versioned fixture schema** (§3's decided scope): a documented file
   format (JSON or YAML) describing `{id, request: <GenerationRequest-shaped fields>,
   targets: [target strings]}` entries, plus a schema version field so a vendor's fixture
   file can declare compatibility explicitly. This is the one genuinely new public contract
   this tool introduces, and — being public — it needs the same "changes are additive/
   versioned, not silently breaking" discipline as any other AnyInfer wire contract.
2. Implement `anyinfer.compare_diff.load_fixtures()` (parses and validates the schema from
   item 1) and `snapshot()` (runs `compare()`/its embedding sibling over loaded fixtures,
   serializes each `TargetComparison.to_dict()` / `EmbeddingTargetComparison.to_dict()` to a
   stable JSON file) — no new result data model, just persistence of the existing one.
3. Implement `diff()`: structural diff between two snapshot files, reusing `compare()`'s own
   field vocabulary for the change descriptions rather than inventing new terminology.
4. Wire the CLI subcommands (`--snapshot`, `--diff`, `--diff <targetA> <targetB> --request <id>`
   for the ad hoc customer-facing mode) as thin calls into the item 2/3 functions, per §4's
   "one implementation, two surfaces" decision.
5. Ship AnyInfer's own small illustrative fixture file (not exhaustive — a demonstration of
   the schema, per §3's "small and illustrative" framing) alongside the public schema, so
   there's a working example a vendor can copy rather than writing one from the schema doc
   alone.
6. Add a CI check in this repo's own test/lint gates using that fixture file: snapshot, diff
   against a checked-in baseline, fail on unexpected drift — this both exercises the tool and
   gives the project itself a regression guard for free.
7. Document the customer-facing "portability report" use case alongside the Confidentiality
   Tiers doc from `TIERED_ENCRYPTED_PLANS.md` §5 — both are the same kind of asset (a
   falsifiable fact sheet instead of prose marketing), worth presenting as a matched pair.

## 6. Open questions for the owner, deferred to when this plan is picked up

Resolved 2026-08-12 by direct interview (fixture ownership/extensibility, CLI-vs-library
sequencing) — see the "Decided" call-outs in §3–§4. Genuinely still open:

- Whether snapshot/diff should also become the mechanized backbone of part of
  `contracts/DRIFT-CHECK.md`'s procedure (e.g., auto-detecting when a contract update changes
  `compare()` output, prompting a drift-check run) — worth scoping only after both tools
  exist independently, per §2's "complementary, not overlapping" framing.
- Exact fixture schema versioning/compatibility policy (item 1 above) — how strict "additive,
  not breaking" is enforced (schema validation tooling, a compatibility test suite) isn't
  designed yet, just committed to as a requirement.
