# Provider Drift Check — Canonical Procedure

Tool-agnostic procedure for auditing the contract snapshots in this directory against each
provider's *current* public API. Entry points: Claude Code skill `check-provider-drift`,
Copilot prompt `.github/prompts/check-provider-drift.prompt.md`, or any agent following this
file directly.

## Purpose

`contracts/<provider>.md` records the exact upstream protocol details AnyInfer depends
on. Providers change their APIs; this procedure is the semi-automated path to noticing before
users do. It complements (does not replace) the conformance suite: conformance proves *our
code matches our claims*; drift checking proves *our claims still match upstream*.

## Procedure

For each in-scope contract file:

0. **`openai-compat-presets.md` is many providers in one file.** The presets share one
   adapter and therefore one snapshot; run steps 1–7 per *section* of that file, and report
   per provider. Its sections inherit the base dialect from `openai-compat.md`, so only the
   recorded deltas (base URL, auth spelling, output-token field, model listing, reasoning
   translation, ignored parameters) are in scope for each.
1. **Read the snapshot fully.** Note its `Last verified` date and version pins.
2. **Fetch every URL under `Upstream sources`.** If a page is moved/renamed, search for the
   current location and record the corrected URL in the proposed update. If a source is
   unreachable (auth wall, bot block, outage), mark everything that depended on it
   `UNVERIFIABLE` — never guess.
3. **Compare each assertion** in the `Wire contract` section (endpoints, methods, auth
   headers, version pins, request fields sent, response fields read, streaming framing,
   pagination, error shapes) and each item in `Watchlist` against the live documentation.
4. **Classify each assertion:**
   - `OK` — live docs still match the snapshot.
   - `DRIFT` — upstream changed something we depend on (endpoint, field, header, framing,
     version). Highest severity; adapters may be broken or degraded.
   - `DEPRECATION` — we depend on something now marked deprecated/sunset (include the
     announced timeline if published).
   - `NEW-CAPABILITY` — upstream added something relevant to our normalized feature set
     (e.g. native structured output where we currently emulate, new usage fields, new
     streaming event types). Not urgent; feeds the capability matrix and roadmap.
   - `UNVERIFIABLE` — could not check, with the reason.
5. **Write the report** (format below), most severe first.
6. **Propose updates; do not silently apply.** Proposals may include: contract-file edits
   (with citations), adapter follow-up work items, conformance-matrix cell changes
   (DESIGN.md §24), and capability-catalog updates. A plain drift *check* is read-only;
   apply proposals only when the operator asks.
7. **`Last verified` discipline:** update a snapshot's `Last verified` line (date + what it
   was verified against) only for providers actually verified this run.

## Report format

```markdown
# Provider Drift Report — <date>

## Summary
| Provider | OK | DRIFT | DEPRECATION | NEW-CAPABILITY | UNVERIFIABLE |
|---|---|---|---|---|---|

## Findings (most severe first)
### <provider>: <one-line finding>            [DRIFT|DEPRECATION|NEW-CAPABILITY]
- Snapshot says: <quoted assertion>
- Live docs say: <what changed> (source: <url>, fetched <date>)
- Impact: <which adapter behavior / conformance cell / capability entry is affected>
- Proposed action: <contract edit / adapter work item / matrix update>

## Unverifiable
- <provider>: <assertion> — <reason>

## Proposed contract edits
<diff-style or bullet proposals per file>
```

## Pricing drift

## Non-inference sources

One snapshot in this directory is not an inference provider: **`huggingface.md`** records the
weights-source API that model acquisition depends on (repository listings, commit resolution,
file digests, and the redirect behavior that governs where a token may be sent). It is
audited by the same procedure, for the same reason — it is a third-party HTTP protocol the
library depends on, and it moves.

Its deterministic tripwire is the weekly `catalog-refresh` workflow
(`scripts/check_catalog_drift.py`), which HEADs every pinned file, compares every recorded
Ollama manifest digest, and checks the pinned llama-server release assets. A manual run of
this procedure covers what that script cannot: the *shape* of the API — field names, the
meaning of `lfs.oid`, pagination, and the redirect origin rule.

## The pricing table

The bundled pricing table (`src/anyinfer/capabilities/pricing.json`) is drift-checked on
its own automated track — the weekly `pricing-refresh` workflow — and does not need to be
covered by a manual run of this procedure. For reference, its rules mirror this file's:

- The deterministic tripwire (`scripts/check_pricing_drift.py`) has multiple sources.
  Chutes and Avian use their provider-owned public model catalogs as direct evidence;
  OpenRouter is a secondary signal for exact mapped OpenAI and Anthropic entries. Direct
  evidence is stronger, but the *authority* for an edit remains the provider's current
  human-readable pricing documentation, verified before a pull request is proposed.
- A successful source response with an exact mapped model missing is drift. A timeout,
  rate limit, HTTP failure, oversized response, malformed payload, or schema failure makes
  the check incomplete. Incomplete checks publish a partial report and fail; they never
  turn an outage into a clean result or a list of removed models.
- Every provider in the bundled table has an explicit coverage posture in
  `scripts/pricing_check.py`: direct, secondary, manual, authenticated, unrepresentable,
  or deferred. Unchecked entries stay visible without guessing a rate or dimension.
- Prices are keyed by provider **and** model — the same model on a different engine may
  cost differently, so a price is never copied across providers. Azure AI Foundry stays
  out of the table (region/deployment-specific; the Azure retail prices API,
  `https://prices.azure.com/api/retail/prices`, is the app-side source), and the Copilots
  stay out because they bill by subscription, not per token.
- `last_verified` dates are real verification dates — the same never-fabricate rule as
  contract snapshots. `checked_at` is when a report ran and `generated` is when the table
  document was emitted; neither refreshes an entry. Entries that cannot be verified are
  left untouched.

### Admitting another pricing source

A new deterministic source is admitted only when its implementation and review record all
of the following: the provider-owned endpoint and authentication posture; a stable exact
provider/model identity mapping; currency and price unit; every tier, region, cache,
long-context, batch, and fee dimension that can change the rate; a bounded failure model;
an exact-`Decimal` parser fixture; the coverage policy; and the provider-owned page that
remains the authority for a proposed edit. A missing dimension is classified as
unrepresentable, not approximated.

Authenticated catalogs are opt-in and never required by the default weekly schedule.
Bedrock and Vertex pricing remain unrepresentable until provider, model, region, tier, and
all material price dimensions can be keyed without inventing a default region. Secondary
catalog candidates likewise remain manual unless both exact identity and the complete rate
shape are verified against provider-owned documentation; moving an authority URL alone
never changes `last_verified`.

## Cadence and hygiene

- **Automated cadence: the weekly `contract-drift` workflow** (Mondays 07:00 UTC),
  which is the scheduled track for this procedure and mirrors the shape the pricing and
  catalog refreshes already use. Its deterministic stage
  (`scripts/check_contract_drift.py`) reads no provider documentation at all: it ranks
  snapshots by whether they have ever been verified against live upstream docs, then by
  age, fetches each selected snapshot's own cited source URLs to catch pages that have
  404'd, and hands a bounded selection to a Claude session that runs *this file* against
  them. Selection is bounded per run so cost is predictable and every snapshot comes up
  on a guaranteed rotation; the report names what it deferred, because a check that
  silently audits four of twenty-two reads as "we checked" when it did not.
- Run it manually against a specific snapshot at any time — before a milestone release,
  or when a provider announces changes — via the entry points at the top of this file.
  `workflow_dispatch` on the workflow also takes a larger `budget` to audit more per run.
- **This lane needs no provider accounts.** A snapshot records what a provider
  *publishes*, not what an authenticated call returns, so auditing one is a
  documentation-reading task. That is why it is the verification track that scales to
  every provider without buying anything.
- Local engines (Ollama, llama.cpp) drift via GitHub releases rather than API docs; check
  their release notes since the pinned version recorded in the snapshot.
- Findings that require code changes become tracked work items; this procedure never edits
  adapter code directly.
