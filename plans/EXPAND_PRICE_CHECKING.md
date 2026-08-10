# Expand deterministic pricing drift checking

**Status:** not started.

**Scope:** expand the weekly pricing drift check from one OpenRouter-specific comparison
into a deterministic, multi-source audit of the bundled pricing table. The first milestone
covers the existing OpenRouter mappings plus the public machine-readable Chutes and Avian
catalogs, produces a structured drift/coverage report, and makes every priced provider's
automation status explicit. Later milestones add sources only when their units, model-id
mapping, currency, region, and tier can be normalized without guessing.

**Goal:** make stale prices visible across materially more of the providers AnyInfer
supports while preserving the existing trust split: machines detect possible drift;
provider-owned documentation and a human-reviewed pull request authorize a price change.

**Non-goals:** automatically changing prices; claiming complete coverage of all 86
compatibility presets; scraping arbitrary HTML; converting currencies; flattening regional,
deployment, cache, batch, long-context, search-fee, subscription, credit, character, or DBU
pricing into a number the current table cannot represent; using one provider's price for
another provider that happens to serve the same model; adding provider SDKs; changing
runtime pricing provenance or cost arithmetic.

**Audience for this plan:** contributors editing the workflow, maintenance scripts, bundled
pricing data, tests, contract guidance, and repository setup documentation. Code audit is as
of **2026-08-09**; re-run the inventory before implementation because model catalogs and
the local working tree may have moved.

**Authority:** [DESIGN.md](../DESIGN.md) §7 and ADR-005 (provenance-tagged pricing), §14
(cost is computed only from trusted capability data), §21 R6 (bundled data staleness), and
§23 ADR-007 (no provider SDKs); [AGENTS.md](../AGENTS.md) (real verification dates, no
invented rates, provider-and-model keying); [contracts/DRIFT-CHECK.md](../contracts/DRIFT-CHECK.md)
(the deterministic tripwire is not the authority for an edit).

**Working-tree prerequisite:** `.github/workflows/pricing-refresh.yml` currently has an
uncommitted bootstrap fix that installs the project in both fresh runners before the
library-backed validator runs. Preserve or land that fix before this plan: without it the
workflow stops at `ModuleNotFoundError: httpx2` and none of the expanded checking executes.

---

## 1. Baseline and evidence

The current table and checker have already outgrown one another:

| Baseline, audited 2026-08-09 | Count |
|---|---:|
| Provider keys in `pricing.json` | 30 |
| Bundled pricing entries | 294 |
| Entries with `openrouter_id` | 10 |
| Deterministically checked entries | 10 (3.4%) |
| Providers represented in the deterministic check | 2 (`openai`, `anthropic`) |
| Deterministic source implementations | 1 (OpenRouter) |
| Hosted compatibility presets in the registry | 86 |

The 294-entry denominator is not a target for blind automation. Several entries can only be
verified from provider pages, several providers expose prices only after authentication,
and several pricing systems cannot be represented by two USD-per-million-token fields. The
important defect is that the repository cannot currently distinguish those cases from an
accidental omission.

Specific findings from the code audit:

1. `scripts/check_pricing_drift.py` fetches exactly one endpoint and contains one parser.
   `find_drift()` silently skips every entry without `openrouter_id`; it reports neither a
   coverage count nor a reason.
2. All ten checked entries use OpenRouter, a valuable secondary signal but not the
   provider-owned authority required for a pricing edit.
3. `pricing.json` contains 30 provider sections, including dedicated adapters (`gemini`,
   `deepseek`, `xai`, `cohere`, `bedrock`, and `vertex`) and compatibility presets such as
   `chutes` and `avian`.
4. Chutes has 13 bundled entries and an unauthenticated model catalog whose contract
   snapshot records per-token USD prompt/completion fields. Avian has 10 bundled entries
   and an unauthenticated catalog whose snapshot records flat USD-per-million input/output
   fields. They are the best first native sources: public, machine-readable, exact provider
   prices, and small enough to fixture comprehensively.
5. Several other model listings report pricing but require credentials or carry dimensions
   the table does not encode. Examples include xAI's richer language-model listing,
   SambaNova, Baseten, Nscale, Qianfan, and Nebius. A scheduled check must not quietly gain
   a new secret requirement.
6. The workflow's proposal prompt is hard-coded to OpenAI and Anthropic URLs. Even if the
   deterministic script were expanded today, the proposal stage would not know how to
   verify or describe another source safely.
7. The table's `_comment` block has become a second, stale provider inventory: it describes
   some providers as absent even though sections for them are now present. Coverage policy
   needs a machine-checked representation; prose should explain rules, not enumerate live
   state.
8. `scripts/check_pricing_drift.py` has no dedicated offline unit suite. Its network parser,
   normalization, missing-model behavior, exit codes, and GitHub output behavior are only
   exercised when the scheduled workflow runs.
9. `Pricing` can represent cache-read and cache-write rates, but the bundled table currently
   records only input and output. This plan must not accidentally treat a cache rate or a
   provider tool/search fee as ordinary output tokens.
10. The top-level `generated` date is not validated. An implementation must define whether
    it means “the document changed” or “every entry was re-verified”; it cannot be allowed
    to launder old entry dates into apparent freshness.

### Terms used by this plan

- **Authority:** the provider's own pricing documentation or provider-owned machine-readable
  catalog. Only authority can justify changing a price or `last_verified`.
- **Direct checker:** a parser for a provider-owned machine-readable source (for example,
  Chutes checking `chutes:*`).
- **Secondary checker:** a third-party signal such as OpenRouter that can trigger review but
  cannot by itself authorize an edit to another provider's price.
- **Observation:** a normalized, source-labelled pair of input/output rates obtained from
  one upstream record without changing bundled data.
- **Coverage policy:** the explicit status for each provider in the pricing table:
  `direct`, `secondary`, `manual`, `authenticated`, `unrepresentable`, or `deferred`.
- **Drift:** a comparable upstream observation differs from the bundled value, or an exact
  mapped model disappeared. An unavailable source is a check failure, not drift and not a
  clean result.

---

## 2. Invariants

These are acceptance constraints, not implementation suggestions.

1. **Provider plus model remains the key.** `together:deepseek-ai/...` and
   `deepinfra:deepseek-ai/...` are different products with potentially different prices.
   OpenRouter's price for an open-weight model must never be copied into either.
2. **Detection never edits.** The deterministic phase reads bundled data and writes only a
   report artifact and `$GITHUB_OUTPUT`. It never modifies `pricing.json`, a source URL, or
   a verification date.
3. **Authority and tripwire remain distinct.** A secondary mismatch opens a verification
   task; it does not become the new price. A direct API observation is stronger evidence,
   but the proposal still confirms it against provider-owned documentation before editing.
4. **No fabricated freshness.** Adding a checker mapping, migrating metadata, or observing
   “no drift” does not advance `last_verified`. That date changes only when a contributor
   actually verifies that entry's values against its recorded provider source on that date.
5. **Exact model identity only.** Source implementations use exact IDs or an explicit
   checked mapping. No lowercase matching, punctuation stripping, prefix guessing, display
   name matching, or “closest model” behavior.
6. **`Decimal` from strings, end to end.** No JSON price passes through `float`. Each source
   normalizes its documented unit directly into USD per one million tokens.
7. **Dimensions must agree.** A comparison is valid only when currency, unit, token side,
   service tier, region/deployment scope, and context-length tier match what the bundled
   entry claims. An unrepresentable dimension is reported, not flattened.
8. **Missing differs from unavailable.** A mapped model absent from a successful source
   response is drift. DNS failure, timeout, 429, 5xx, malformed JSON, oversized response,
   or an upstream schema change is check failure (exit 2).
9. **No false green from partial execution.** Every checker enabled for the scheduled run
   must complete. If one required source fails, the run publishes its partial report and
   fails; it does not print “no drift.”
10. **No new secrets in the default schedule.** Milestone one uses public endpoints only.
    Authenticated checks, if later approved, are opt-in manual-dispatch sources with named
    secrets and explicit repository setup documentation.
11. **Bounded network behavior.** Hard-coded HTTPS origins, a descriptive user agent,
    bounded response bytes, one timeout policy, and no caller-supplied URL or JSONPath.
12. **Offline tests are authoritative for parser behavior.** Ordinary CI uses captured,
    minimized fixtures. Live source probes are opt-in and never make the main test suite
    network-dependent.
13. **Unchecked is visible.** Every provider present in `pricing.json` has an explicit
    coverage policy and reason. Adding a 31st provider without one fails validation.
14. **Local and non-token pricing stay out.** Local zeroes continue to come from capability
    assembly; subscriptions, credits, DBUs, characters, images, audio, and regional custom
    deployments remain unknown unless the table gains an explicit representation in a
    separately approved change.

---

## 3. Proposed architecture

Keep the public runtime path unchanged. This is repository maintenance tooling, not a
provider adapter or a second capability system.

```text
pricing.json
    │
    ├── validate table + coverage policy
    │
    └── select entries per checker
            │
            ├── OpenRouter parser (secondary)
            ├── Chutes parser (direct)
            └── Avian parser (direct)
                    │
                    ▼
          normalized observations (Decimal)
                    │
                    ▼
           pure comparator + classifications
                    │
             ┌──────┴──────┐
             ▼             ▼
       human summary   JSON report artifact
                             │
                             ▼
                 proposal verifies provider pages
```

### 3.1 Internal types

Put the source-neutral records in `scripts/pricing_check.py` or a small
`scripts/pricing_check/` package; keep `scripts/check_pricing_drift.py` as the stable CLI
entry point used by contributors and Actions.

```python
@dataclass(frozen=True, slots=True)
class BundledRate:
    provider: str
    model: str
    input_per_1m: Decimal
    output_per_1m: Decimal
    last_verified: str
    authority_url: str

@dataclass(frozen=True, slots=True)
class RateObservation:
    checker: str
    authority: Literal["direct", "secondary"]
    upstream_id: str
    input_per_1m: Decimal
    output_per_1m: Decimal
    currency: str
    tier: str
    evidence_url: str

@dataclass(frozen=True, slots=True)
class DriftFinding:
    status: Literal[
        "match", "price-drift", "upstream-missing", "not-comparable",
        "unchecked", "source-failed"
    ]
    bundled: BundledRate
    observation: RateObservation | None
    reason: str
```

The comparator is pure: bundled values plus observations in, ordered findings out. Network
fetching and parsing live outside it. This makes every money decision fixture-testable.

### 3.2 Source interface

Each checker owns only four things:

1. its hard-coded origin and endpoint;
2. how it selects bundled entries;
3. how it parses one source schema and converts documented units;
4. whether it is direct or secondary evidence.

Use one fetch per source per run. Parse functions accept already-decoded mappings and return
`dict[upstream_id, RateObservation]`, so tests never mock sockets. The first three selectors
are deliberately simple:

- OpenRouter selects entries with the existing `openrouter_id` and looks them up by that
  exact value.
- Chutes selects the `chutes` provider section and uses each bundled `model` as the exact
  upstream ID.
- Avian selects the `avian` provider section and uses each bundled `model` as the exact
  upstream ID.

Do not introduce a generic URL/JSONPath mini-language. Source schemas are protocols, and
protocol translation belongs in reviewed code with fixtures. If a later source uses a
different ID, add a narrow optional `check_ids` mapping beside the entry only after a live
audit proves the mapping; do not build that schema speculatively in milestone one.

### 3.3 Coverage policy

Add a declarative `PROVIDER_POLICIES` registry in the maintenance tooling. It must contain
one row for every provider key in `pricing.json` and include:

```python
ProviderPricingPolicy(
    provider="chutes",
    mode="direct",
    checker="chutes-models",
    reason="public provider-owned model listing exposes comparable USD token rates",
)
```

For manual/authenticated/unrepresentable/deferred rows, `checker` is empty and `reason` is
required. `scripts/validate_pricing.py` (or a sibling validation function it calls) fails on
an unknown provider, missing reason, unknown checker, or a policy claiming direct coverage
that selects no entries. This replaces the brittle provider inventory in `_comment` with a
machine-checked one; the comment remains a short statement of invariants and points to the
coverage report.

Coverage is reported at two levels:

- entry coverage: checked entries / bundled entries, broken down by direct and secondary;
- provider posture: direct, secondary, manual, authenticated, unrepresentable, deferred.

Do not set a global “100%” gate. Set a non-regression gate after milestone one: checked
entries and direct-provider count may not decrease unless a source is deliberately removed
with an updated reason and review.

### 3.4 Structured report

Add `--report PATH` and `--format text|json` while preserving the current default human
output. JSON is versioned independently from `pricing.json`:

```json
{
  "format_version": 1,
  "checked_at": "2026-08-09T18:00:00Z",
  "summary": {
    "bundled_entries": 294,
    "checked_entries": 33,
    "direct_entries": 23,
    "secondary_entries": 10,
    "drift": 0,
    "source_failures": 0
  },
  "sources": [],
  "findings": [],
  "coverage": []
}
```

`checked_at` records the check execution, not verification of any price. Reports are sorted
by `(provider, model, checker)` and serialized with stable key order so the same fixtures
produce byte-identical output apart from an injected clock. Do not include response headers,
credentials, or full upstream payloads.

### 3.5 Exit codes

Retain the current contract and make it source-aware:

- `0`: every enabled source succeeded and no comparable entry drifted;
- `1`: every enabled source succeeded and at least one price drift or mapped-model removal
  was found;
- `2`: validation, source fetch, source schema, currency/unit, or report-writing failure.

Unchecked/manual entries do not make a run fail; they are visible in coverage. A source
failure always outranks drift for the process exit code because the run is incomplete, but
the report retains any drift already found.

---

## 4. Provider rollout matrix

This matrix is a routing plan, not a claim that the listed prices are current. Every source
must be re-verified when its task starts.

| Provider | Entries | Proposed deterministic posture | Phase | Constraint |
|---|---:|---|---|---|
| OpenAI | 6 | OpenRouter secondary (existing); provider page remains authority | 1 | Correct `source` to provider-owned documentation only after real re-verification |
| Anthropic | 4 | OpenRouter secondary (existing); provider page remains authority | 1 | Long-context/cache tiers are outside the current two-rate check |
| Chutes | 13 | Direct public model listing | 1 | Parse USD token fields only; ignore TAO, image, and non-token dimensions |
| Avian | 10 | Direct public model listing | 1 | Parse `*_per_million` strings exactly; include cache only in a later scoped change |
| Gemini | 6 | Candidate OpenRouter secondary plus manual provider authority | 2 | Prompt-length tiers make exact comparability a gate |
| Mistral | 4 | Candidate OpenRouter secondary plus manual provider authority | 2 | Exact first-party model mapping only |
| DeepSeek | 2 | Candidate OpenRouter secondary plus direct pricing page | 2 | Cache-hit and cache-miss rates must not be conflated |
| xAI | 5 | Candidate OpenRouter secondary; authenticated direct listing later | 2/3 | Tiered pricing and server-side tool fees are not ordinary token rates |
| Cohere | 3 | Candidate OpenRouter secondary plus manual provider authority | 2 | Exact first-party model mapping only |
| Perplexity | 4 | Secondary/manual | 2 | Per-request search fees remain outside the comparison |
| Moonshot | 4 | Secondary/manual | 2 | Verify international product, currency, and model spelling |
| Cerebras | 3 | Manual until a stable public machine source is proven | 3 | Do not use another host's price for the same open model |
| SambaNova | 6 | Authenticated provider listing | 3 | No scheduled secret by default |
| Together | 6 | Manual or provider-owned catalog if one proves stable | 3 | OpenRouter prices are not Together prices |
| Fireworks | 6 | Manual or provider-owned catalog if one proves stable | 3 | Deployment/serverless tiers must match |
| DeepInfra | 5 | Candidate provider model listing | 3 | Confirm authentication and source units before enabling |
| Baseten | 6 | Authenticated provider listing | 3 | No scheduled secret by default; dedicated tiers differ |
| Z.ai | 5 | Manual | 3 | No model listing recorded in the preset contract |
| DashScope | 4 | Manual | 3 | Region, currency, cache, and thinking rates vary |
| MiniMax | 4 | Manual | 3 | No model listing recorded in the preset contract |
| AI21 | 2 | Manual | 3 | Verify hosted product rather than self-hosted Jamba |
| Venice | 105 | Deferred source-specific audit | 3 | Large blast radius; prove one schema and sample before all 105 entries |
| Reka | 3 | Manual | 3 | Model-page and pricing-page names may differ |
| Upstage | 4 | Manual | 3 | Published rates exclude VAT in some contexts |
| Arcee | 1 | Manual | 3 | Image-rendered or otherwise non-machine-readable pricing is not scraped |
| DigitalOcean | 54 | Manual until a stable structured source exists | 3 | Do not make the weekly job depend on an HTML table parser |
| Qianfan | 3 | Authenticated/direct listing candidate | 3 | Confirm USD unit and international endpoint; no FX conversion |
| StepFun | 5 | Manual | 3 | Audio/realtime dimensions show why text-only comparison needs a gate |
| Bedrock | 5 | Deferred public AWS Price List parser | 4 | Region and SKU dimensions cannot be ignored under a provider+model-only key |
| Vertex | 6 | Manual/deferred | 4 | Global vs regional and prompt-length tiers differ |

Providers deliberately absent from `pricing.json` remain outside the denominator. Examples
include Azure Foundry (region/deployment-specific), Copilot products (subscription/premium
requests), OpenRouter (live discovered pricing), local engines (genuine zero), and
credit/DBU/character-based enterprise products. The coverage report should list these only
as table-level exclusions if useful; it must not manufacture zero or a converted USD rate.

### Why Chutes and Avian first

Together they raise deterministic coverage from 10 to 33 entries and from two providers to
four, while adding two independent provider-owned checkers. More importantly, they exercise
both unit shapes the framework needs: per-token strings and per-million strings. They prove
the multi-source architecture before the project commits to a regional price-list parser or
authenticated workflow secrets.

### Safe OpenRouter expansion rule

OpenRouter backfill is appropriate only for a first-party provider/model pair where the
listing ID and pricing semantics are exact and the provider's own page remains the authority.
It is not appropriate for infrastructure providers serving open-weight models. During phase
2, generate a candidate list from the live OpenRouter catalog, but require a human to approve
each exact mapping before adding `openrouter_id`; never auto-match by model name.

---

## 5. Tasks

### Phase 0 — freeze the contract and baseline

**EPC.0 — re-audit immediately before code.** Recount pricing providers, entries,
`openrouter_id` mappings, and preset/dedicated-provider inventory. Diff the workflow and
pricing files against this plan's audit date. Record the new counts in the implementation
PR, not by changing old `last_verified` dates. *Acceptance:* a checked-in test computes the
coverage baseline from data rather than duplicating `294` in code.

**EPC.1 — state the trust split in canonical guidance.** Update
`contracts/DRIFT-CHECK.md` so it describes multiple deterministic sources, direct versus
secondary evidence, source-failure semantics, and the rule that the provider-owned page is
still verified before an edit. Update the workflow header comment to the same language.
*Acceptance:* no documentation says OpenRouter alone is the authority for an OpenAI,
Anthropic, or other provider entry.

### Phase 1 — multi-source framework and first direct sources

**EPC.2 — extract pure comparison and reporting records.** Refactor
`check_pricing_drift.py` into fetch/parse/select/compare/report layers. Keep the current CLI
path and exit codes. *Acceptance:* the comparator is tested with in-memory `Decimal` values
and imports no networking module.

**EPC.3 — implement bounded source fetching.** One standard-library HTTPS helper with a
hard response cap, timeout, user agent, status handling, and deterministic JSON decoding.
Source URLs remain constants in code. *Acceptance:* tests cover timeout, HTTP failure,
oversized response, malformed JSON, and a successful empty payload without making network
calls.

**EPC.4 — preserve OpenRouter behavior through the new interface.** Move its parser behind
the source interface without changing which entries it checks or how exact rates compare.
*Acceptance:* the ten current mappings produce the same match/drift/missing conclusions from
a frozen fixture as the pre-refactor implementation.

**EPC.5 — add the Chutes direct checker.** Verify the current contract and live schema,
capture a minimized fixture with a real capture date, parse only comparable USD text-token
fields, and select exact `chutes` IDs. *Acceptance:* all currently bundled Chutes entries are
either matched or reported as drift/missing; none is silently skipped; TAO and unrelated
modalities cannot enter the normalized rate.

**EPC.6 — add the Avian direct checker.** Repeat the same process for the documented
per-million fields and exact `avian` IDs. *Acceptance:* all currently bundled Avian entries
are accounted for, and a unit test would fail if the parser accidentally multiplied a
per-million number by one million again.

**EPC.7 — add coverage policy and validation.** Declare every current pricing provider's
posture and reason. Shorten `_comment` to stable rules instead of a provider inventory.
Validate the top-level `generated` date and define it as the date the document was emitted,
not proof that every entry was verified. *Acceptance:* adding a provider section without a
policy fails; metadata-only edits do not update entry dates; contradictions between prose
and data are removed.

**EPC.8 — add a versioned JSON report.** Implement `--report`, stable ordering, injected
clock for tests, source summaries, entry findings, and coverage. Human output remains concise
and names checker plus evidence type. *Acceptance:* golden report tests are byte-stable and
contain no upstream payload or headers.

### Phase 1 workflow integration

**EPC.9 — make the report the handoff artifact.** The check job writes the JSON report even
on exit 1 or 2 and uploads it with `if: always()`. It sets `drift=true` only for exit 1 and
fails on exit 2. The proposal job downloads the exact report instead of re-running a moving
upstream comparison. *Acceptance:* proposal input identifies provider, model, bundled rates,
observed rates, checker, authority class, and evidence URL for every finding.

**EPC.10 — generalize the proposal prompt.** Remove hard-coded OpenAI/Anthropic branching.
For each report finding, require verification on that provider's own current pricing page;
allow a direct checker URL as evidence but still require the human-readable provider source
to be cited in the PR. Explicitly forbid changing an entry when dimensions do not match.
*Acceptance:* a fixture report containing OpenAI, Chutes, and Avian findings produces an
actionable prompt without treating OpenRouter as authority.

**EPC.11 — tighten workflow permissions and concurrency.** Give the check job read-only
contents permission; grant contents/pull-request writes only to the proposal job. Add a
workflow concurrency group so two scheduled/manual refreshes do not race to open competing
branches. *Acceptance:* deterministic checking needs no write token.

### Phase 2 — conservative secondary expansion

**EPC.12 — audit OpenRouter candidates for first-party providers.** Start with Gemini,
Mistral, DeepSeek, xAI, Cohere, Perplexity, and Moonshot. For every candidate, verify exact
ID, provider identity, standard tier, and input/output semantics against the provider's own
page before adding metadata. *Acceptance:* every new mapping has a provider-owned authority
URL; no infrastructure-provider/open-model price is inferred from OpenRouter.

**EPC.13 — correct authority URLs without laundering dates.** Existing OpenAI and Anthropic
entries currently name OpenRouter as `source`. On the next actual provider-page verification,
replace those with provider-owned URLs and update only the entries genuinely checked that
day. *Acceptance:* no bulk date bump and no claim that moving metadata constitutes price
verification.

### Phase 3 — source-by-source additions

**EPC.14 — add a source only through a source admission checklist.** Required evidence:
stable endpoint, owner, auth posture, exact ID mapping, currency, unit, tiers, cache/search
fees, response-size bound, failure behavior, contract snapshot citation, fixture, and policy
update. *Acceptance:* a checklist section appears in the implementation PR for each source;
missing answers defer the source rather than guess.

**EPC.15 — authenticated sources remain opt-in.** If SambaNova, Baseten, Nscale, Qianfan,
xAI, or another source needs a credential, add it only to manual dispatch behind a distinct
input/secret and document it in `docs/contributing/repository-setup.md`. Public-source checks
still run without it. *Acceptance:* the Monday schedule remains green in a repository with
none of those optional secrets configured.

**EPC.16 — gate Bedrock and Vertex on representability.** Before parsing AWS or Google price
catalogs, decide how a provider+model key states region and tier. If the current table cannot
identify the compared SKU exactly, leave the source deferred or remove misleading bundled
entries in a separately reviewed pricing change. *Acceptance:* no “default region” is
invented in checker code.

### Documentation and maintenance completion

**EPC.17 — document contributor operation.** Add commands for text output, JSON report,
live opt-in source probes, fixture refresh, exit codes, and interpreting direct versus
secondary findings. State that a clean tripwire is not a new verification date. Link from
repository setup and the pricing/cost concept page where appropriate.

**EPC.18 — add a non-regression gate.** After phase 1 lands, pin the minimum direct and total
coverage counts in terms of data-derived policy: at least 23 direct entries (Chutes + Avian),
at least 33 total checked entries, four checked providers, and three source implementations.
Intentional decreases require updating the policy reason and the gate in one reviewed change.

---

## 6. Test plan

All ordinary tests are offline.

### Source parser fixtures

For OpenRouter, Chutes, and Avian, include minimized JSON fixtures containing:

- one exact matching model;
- one mismatched rate;
- one unrelated model that must be ignored;
- a missing/malformed pricing object;
- zero/free or non-text records where the source can return them;
- source-specific alternate currency or cache fields that must not be mistaken for standard
  input/output;
- enough envelope structure to detect an upstream field rename.

Each fixture carries a comment or adjacent metadata file with its real capture date and
source URL. Refreshing a fixture is not refreshing bundled prices.

### Unit tests

1. Per-token to per-million normalization uses `Decimal` and exact expected strings.
2. Per-million sources are not scaled twice.
3. Exact model identity is case-sensitive and punctuation-sensitive.
4. Match, input-only drift, output-only drift, both-side drift, and upstream disappearance
   classify separately.
5. A source outage yields exit 2; it never becomes “all mapped models vanished.”
6. One failed required source plus one successful drift produces a partial report and exit 2.
7. Human and JSON renderers contain the same findings.
8. Stable ordering is independent of source response order.
9. Coverage counts distinguish direct and secondary entries without double-counting an entry
   checked by both.
10. Every provider key in `pricing.json` has exactly one coverage policy.
11. Every direct policy selects at least one entry and names a registered checker.
12. Manual/authenticated/unrepresentable/deferred policies require a nonempty reason.
13. `generated` and `last_verified` reject future or invalid dates, but a clean check does not
    alter either.
14. Existing `PricingTable` lookup and cost tests remain unchanged; maintenance metadata does
    not affect runtime provenance.
15. The checker works from a source checkout on Python 3.11 through 3.14.

### Workflow tests

- A shell-level test or checked helper verifies exit 0/1/2 handling and `$GITHUB_OUTPUT`.
- A fixture report is uploaded/downloaded under the same filename the proposal prompt reads.
- The proposal job is skipped on exit 0, runs on exit 1, and does not run on exit 2.
- Manual `force_propose` is documented: it may run with no drift report, but must create an
  explicit empty/manual report rather than assuming OpenRouter findings.
- Permissions are asserted from workflow text if the repository already has workflow-policy
  tests; otherwise validate with `actionlint` in the implementation PR.

### Optional live probes

Provide `python scripts/check_pricing_drift.py --live-source chutes-models` (and equivalents)
for maintainers. Live probes print source schema/coverage diagnostics, never full payloads,
never write fixtures automatically, and are excluded from `workspace check`.

---

## 7. File-by-file change map

| Path | Planned responsibility |
|---|---|
| `scripts/check_pricing_drift.py` | Stable CLI, source orchestration, exit codes, GitHub output |
| `scripts/pricing_check.py` or `scripts/pricing_check/` | Frozen records, pure comparator, source registry, coverage policy, renderers |
| `scripts/validate_pricing.py` | Table-date checks plus coverage-policy consistency |
| `src/anyinfer/capabilities/pricing.json` | Rates and authority URLs; shorter stable rule comment; no automatic edits |
| `tests/test_pricing_drift.py` | Offline parser/comparator/report/exit tests |
| `tests/fixtures/pricing/` | Minimized real source envelopes with capture metadata |
| `.github/workflows/pricing-refresh.yml` | Dependency bootstrap, report artifact handoff, generic proposal prompt, scoped permissions |
| `contracts/DRIFT-CHECK.md` | Multi-source trust model and failure semantics |
| `contracts/openai-compat-presets.md` | Update only when a live source audit changes a recorded protocol fact |
| `docs/contributing/repository-setup.md` | Optional authenticated-source secrets and manual-dispatch behavior |
| `docs/concepts/cost.md` | Explain automated drift coverage and its limits without exposing internal plan IDs |

No provider adapter changes are expected in phase 1. If implementation discovers that a
provider's runtime discovery parser is wrong, that becomes a separate adapter + contract +
conformance change; the pricing checker must not smuggle runtime wire behavior into a
maintenance script.

---

## 8. Risks and mitigations

- **R-EPC1 — aggregator laundering.** A secondary rate looks authoritative once printed
  beside a provider name. Mitigation: every observation and report field carries
  `direct|secondary`; proposal text says what can authorize an edit.
- **R-EPC2 — same model, different seller.** Open-weight model IDs recur across Together,
  Fireworks, DeepInfra, Chutes, and others. Mitigation: provider+model keying, exact source
  selectors, and the phase-2 prohibition on infrastructure-provider OpenRouter mappings.
- **R-EPC3 — tier collapse.** Gemini/Claude long context, xAI high-context tiers, cache
  discounts, batch, priority, and search tools can all make two correct price tables differ.
  Mitigation: `not-comparable` classification and admission checklist; never pick the lower
  or “standard-looking” number heuristically.
- **R-EPC4 — false green during outage.** A broad exception handler can turn a broken source
  into zero observations. Mitigation: explicit source completion records and exit 2 on every
  required-source failure.
- **R-EPC5 — source schema drift.** A provider renames `prompt` to `input` and the parser
  silently skips it. Mitigation: fixture envelope tests plus “selected zero entries” as a
  schema failure for a direct policy, not valid emptiness.
- **R-EPC6 — noisy catalogs.** Venice (105 entries) and DigitalOcean (54) can dominate a
  report and PR. Mitigation: source admission in small phases, grouped summaries, and no
  bulk source until sampled IDs and dimensions are proven.
- **R-EPC7 — authenticated-check fragility.** Expired keys make the weekly workflow red.
  Mitigation: public sources only on schedule; authenticated checks opt-in and separately
  reported.
- **R-EPC8 — verification-date laundering.** A contributor may update all dates because a
  checker matched. Mitigation: explicit invariant, prompt rule, tests that checker is
  read-only, and PR body listing exactly which provider pages were opened.
- **R-EPC9 — HTML parser maintenance.** Provider pages redesign frequently and may render
  client-side. Mitigation: no general HTML scraping; retain the web-assisted human proposal
  stage for manual providers.
- **R-EPC10 — report treated as billing truth.** The JSON artifact may be consumed outside
  the workflow. Mitigation: format docs label observations as drift evidence, not verified
  billing data; it is not published as a runtime artifact.
- **R-EPC11 — duplicated protocol logic.** Chutes/Avian source parsing in a script may later
  differ from runtime discovery. Mitigation: phase 1 checker parsing stays maintenance-only;
  if the runtime should consume the same fields, extract a provider-owned pure parser in a
  separate reviewed change and cover both call sites.
- **R-EPC12 — stale coverage prose.** The current `_comment` inventory already contradicts
  the data. Mitigation: declarative policies plus validation; prose states only stable rules.

---

## 9. Milestones and acceptance

### Milestone 1 — useful expansion, public sources only

Complete EPC.0 through EPC.11 and EPC.17–EPC.18.

Acceptance:

- the current 10 OpenRouter mappings still behave identically;
- all 13 bundled Chutes and all 10 bundled Avian entries are accounted for by direct
  provider-owned checkers;
- at least 33 entries, four providers, and three source implementations are covered;
- every one of the 30 pricing providers has an explicit policy and reason;
- the workflow uploads a structured report and hands that exact report to proposal;
- source outages fail rather than pass or propose bogus removals;
- no rate, authority URL, `generated`, or `last_verified` value changes without real live
  provider verification;
- all parser/comparator/workflow tests pass offline.

### Milestone 2 — first-party secondary signals

Complete EPC.12–EPC.13 for only the candidates that survive exact live verification.

Acceptance:

- total coverage increases without treating hosted open-model sellers as interchangeable;
- every new `openrouter_id` has an exact mapping and a provider-owned authority URL;
- any candidate with mismatched tiers/currency/identity stays manual with a written reason.

### Milestone 3 — selective provider-owned sources

Complete EPC.14–EPC.16 source by source. There is no provider-count quota.

Acceptance:

- each admitted source has a contract citation, fixture, unit proof, failure tests, and
  coverage policy;
- the scheduled workflow still requires no optional provider credentials;
- Bedrock/Vertex remain deferred unless the compared region/tier is explicit and honest.

---

## 10. Decisions

Settled for implementation:

1. **Build a multi-source detector, not an updater.** No deterministic source writes prices.
2. **Start with Chutes and Avian.** Their public provider-owned listings provide the highest
   coverage gain with the least ambiguity and no secrets.
3. **Keep OpenRouter as secondary evidence.** It remains useful and expands only through
   exact first-party mappings; it never authorizes another provider's price.
4. **Keep the current CLI filename and exit codes.** Existing contributor and workflow
   commands remain valid.
5. **Keep phase 1 standard-library-only.** The workflow installs AnyInfer for validation,
   but the network checker needs no new dependency and no provider SDK.
6. **Do not generalize pricing data schema prematurely.** OpenRouter uses the existing
   `openrouter_id`; Chutes and Avian use exact provider model IDs. Add explicit alternate
   check IDs only when a verified source actually needs them.
7. **Make coverage policy declarative and exhaustive.** A priced provider cannot be silently
   unchecked.
8. **Fail closed on incomplete sources.** Any enabled-source failure produces exit 2 and no
   proposal run, while retaining a diagnostic report.
9. **Pass a report artifact between jobs.** The proposal verifies the same observations the
   deterministic job evaluated rather than re-fetching a moving catalog.
10. **Do not expand dimensions in this plan.** Cache, batch, long-context, search/tool,
    regional, subscription, credit, audio/image, and non-USD pricing need separate data-model
    decisions before checking.
11. **A clean check does not refresh a date.** `checked_at`, `generated`, and
    `last_verified` remain distinct facts.
12. **Delete this plan when complete.** Per `plans/README.md`, decisions that land belong in
    code, tests, DESIGN/contract guidance, and docs; a completed local plan should not remain
    as stale instructions.
