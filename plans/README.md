# Plans

**Local working notes.** `plans/` is gitignored as of the documentation restructure, so
nothing here is tracked or reviewed in a PR. [DESIGN.md](../DESIGN.md) remains the
authoritative architecture document: where a plan disagrees with a stated goal, non-goal,
or ADR, DESIGN.md wins until the plan lands its amendment. Each file states its own
authority, governance intent, and the date its code audit was taken.

Scope and the open questions were settled on **2026-08-09**; every plan now ends in a
**Decisions** section rather than open questions. All four original governance items are
approved to proceed, and MCP is approved to build rather than to wait for a consumer.
**Four plans were added later the same day** from the parity review — see Tier 3.

The first nine plans share one thesis. **"Batteries included" is not a defensible claim on
its own** — every comparable library says it, and as a quantity contest it pulls toward the
non-goals in DESIGN.md §2. The defensible version is narrower: *the parts an application
would otherwise hand-roll around inference, inside one boundary, with verified behaviour*.
Two of these plans are the differentiators (a library you can **test** and **extend**);
the rest deepen the boundary that already exists.

## Status legend

Each plan below carries a marker. Status is judged against the plan's own acceptance
criteria, not against "code exists" — a plan is complete only when its gates are green and
its deviations are written down.

| | Meaning |
|---|---|
| ✅ | **Complete.** Landed, gates green. Any deliberate deviation is noted beside it |
| 🚧 | **In progress.** Some tasks landed; the rest are still open |
| ❌ | **Errored.** Landed work that does not meet its own acceptance criteria and needs rework. *Nothing is in this state* |
| ❓ | **Questions outstanding.** Blocked on a decision, not on effort. *Nothing is in this state* |
| ⬜ | **Not started** |

**As of 2026-08-09: seven complete, six not started.** The governance amendments (both ADRs
and both §2 clarifications) are landed, and were already committed to `main` by the
concurrent session's `7024ce3` rather than sitting in the working tree.

**A completed plan's file is deleted, not archived.** A finished plan that stays on disk
gets read later as if it still described work to do, and its "code audit as of" date rots
into a claim about the present. What it decided lives in the code, its tests, DESIGN.md, and
the contract snapshots; what it *deviated on* is recorded below, which is the only part a
deleted file would otherwise take with it.

Five deviations were taken deliberately:

- **TEST_KIT** — `tests/support.py` keeps `FakeOpenAIServer`, which is that plan's own
  carve-out for wire-dialect tests. The scripted provider replaces it nowhere it was right.
- **PROMPT_CACHE_PLACEMENT** — `PC.8` (a caching column in the conformance matrix) is
  deferred; it needs a new capability flag on every adapter and a change to the matrix
  shape. No cache pricing rates were invented: `Pricing.cache_read_per_1m` defaults to
  `None`, so arithmetic is unchanged wherever a rate is unknown.
- **SPEND_LEDGER** — `SL.6` assumed superseded attempts emit `AttemptCompleted`; this
  codebase emits it only on success, so retry and repair spend is invisible to observers.
  Documented in `SpendLedger`'s docstring rather than papered over.

  **Known defect, not a deviation — the ceiling does not hold under concurrency.**
  `_check_spend` compares `ledger.totals().cost + estimate` against `max_total_usd`, and the
  ledger only moves when a request *completes*, so two concurrent requests both read the same
  pre-flight total and both pass. `AsyncClient` is required to support many concurrent
  streams (§22 invariant 4), so this is the normal case. Fix: reserve the estimate at check
  time, release on completion, compare `spent + reserved + estimate` under the lock
  `ledger.py` already holds — and dispatch **concurrently** in the test, since the sequential
  one passes either way. Recorded here and in
  [NEW_ARENA_MODE.md](NEW_ARENA_MODE.md) §5 decision 4 because it was written into
  `SPEND_LEDGER.md` immediately before that file was deleted, and a defect in landed work is
  precisely what the deletion convention is not supposed to lose.
- **MCP_TOOL_SOURCE** — `MT.7` assumed an `anyinfer tools` verb that does not exist, and
  wiring MCP into `anyinfer run` would break the CLI's rule that it never executes tools.
  Shipped as `anyinfer mcp list` (discovery only).
- **RATE_GOVERNANCE** — three. `ProviderSettings.limits` is `RateLimits | None` rather than
  a default-constructed `RateLimits()`, so "no pacing" is spelled by absence, matching every
  other opt-in policy; a bare `RateLimits()` then honestly means "pace me by what the
  provider reports". Rate-limit *reset* headers are read in the RFC 3339 form as well as the
  duration form — the plan inherited `parse_retry_after`'s refusal of absolute timestamps,
  but every derived wait here is clamped, and refusing would have made header pacing inert
  for Anthropic, which states its window that way. And `RG.4`'s non-HTTP fallback is driven
  by a new `ProviderDescriptor.governs_own_transport` flag rather than by naming Copilot.

**UI_MODIFICATIONS is not this thread's work.** The concurrent session owns
`src/demo_app/` and `tests/demo_app/` and carried that plan to done itself; nothing here
should touch those paths without asking first. It left two requests for the core thread — a
warmth signal on `Measurement` (whether the engine had the model loaded when a run started,
so the demo can stop working around it with a ×2 protocol), and a reasoning-aware `verify()`
probe (`ollama:qwen3:4b` fails verification because a thinking model spends its output budget
on reasoning under the structured probe) — plus its Gaps section flagged a third: no
provenance-tagged surface for provider sampling defaults. All three are now scoped in
[CAPABILITY_SIGNAL_GAPS.md](CAPABILITY_SIGNAL_GAPS.md), including a narrow, requester-directed
extension back into `src/demo_app/`'s existing `_refresh_default_hints()` for the third.

## Tier 1 — the differentiators

| | Plan | What it adds | Why it differentiates |
|---|---|---|---|
| ✅ | TEST_KIT (file removed) | `anyinfer.testing` as a supported kit for *applications*: scripted providers, fault injection, a pytest plugin | Nobody else lets an app unit-test its own fallback, repair, and reduction paths offline. The machinery already exists for our conformance suite |
| ✅ | PROMPT_CACHE_PLACEMENT (file removed) | Core decides *where* the prompt cache is marked; adapters spell it | We already measure and price caching and cannot cause it. Same mechanism-ladder shape as structured output |
| ⬜ | [INIT_COMMAND.md](INIT_COMMAND.md) | `anyinfer init` — detect, recommend, write a valid config and a runnable starter | The first five minutes currently end in the configuration reference instead of a working call |
| ⬜ | [AGENT_LEGIBILITY.md](AGENT_LEGIBILITY.md) | `llms.txt`, `anyinfer agents-md`, a distributable integration skill | A coding agent's default guess for this library is an OpenAI clone, which is exactly what it is not |
| ✅ | THIRD_PARTY_PROVIDERS (file removed) | Template, `anyinfer conform`, visible plugin-load diagnostics | Turns provider *breadth* from a counting contest into "your adapter passes the same suite ours do" |

## Tier 2 — deepening the same boundary

| | Plan | What it adds | Note |
|---|---|---|---|
| ✅ | RATE_GOVERNANCE (file removed) | Per-provider pacing from the rate-limit headers we already receive | We honour `Retry-After` on the way *down* and anticipate nothing on the way up |
| ✅ | SPEND_LEDGER (file removed) | In-process spend rollup plus an optional preflight ceiling | Cost is already tri-state and `Decimal`; accumulating it correctly is subtle enough to ship once |
| ✅ | MCP_TOOL_SOURCE (file removed) | MCP servers as a source of `ToolSpec`s for the existing tool loop | Adds a tool *source*, not loop semantics. Spoken directly, with a pinned contract snapshot |
| ⬜ | [SERVICE_INSTALL.md](SERVICE_INSTALL.md) | systemd / launchd / scheduled-task definitions for the sidecar | Finishes the "no Python required" path at a service that survives a reboot |
| ⬜ | [CAPABILITY_SIGNAL_GAPS.md](CAPABILITY_SIGNAL_GAPS.md) | `Measurement.model_load_ms`, a reasoning-aware `verify()` probe, provenance-tagged `default_temperature`/`default_top_p` | The three loose ends UI_MODIFICATIONS left for the core thread |

## Tier 3 — capability parity across SDK, CLI, and sidecar (added 2026-08-09)

One requirement produced the first three: **the three integration surfaces are at capability
parity**, by config file, CLI argument, or whatever else it takes, so no developer is
pushed onto a surface they would rather not use because a capability exists only there.
The mechanism already existed — client-layer policy plus a config block, a CLI flag, and an
`anyinfer_*` request extension — and §27 had already written down the principle for
`HistoryPolicy`. These plans apply it, and the review that produced them found two gaps
that had nothing to do with the feature that started it.

| | Plan | What it adds | Parity role |
|---|---|---|---|
| ⬜ | [NEW_ARENA_MODE.md](NEW_ARENA_MODE.md) | Fan one request or tool loop out to N targets; keep every candidate; choose deterministically or with one judge call | The forcing function. Establishes the four-spellings pattern and the test that enforces it |
| ⬜ | [SIDECAR_CORPUS_CONTEXT.md](SIDECAR_CORPUS_CONTEXT.md) | Stateless `anyinfer_context` extension so a non-Python client can reach the reduction subsystem | Closes the gap §27 left, on corrected reasoning |
| ⬜ | [MULTIMODAL_INPUTS.md](MULTIMODAL_INPUTS.md) | Activates the reserved image/document/audio content parts | The largest gap: a stock client's PDF has nowhere to go, and it is an ADR-009 invariant-1 violation |
| ✅ | UI_MODIFICATIONS (file removed) | Demo app overhaul: an in-app "how is this built?" help system, coverage of the full public surface, visual polish | Not a parity plan — it is where parity gets *demonstrated*. Owned end to end by the concurrent session and shipped through Phase G at `896202c` |

## Governance: approved 2026-08-09, and each writes its amendment first

All four are approved to proceed. Each must land its DESIGN.md amendment **before** its
code, in the style of the `compact_history` clarification — flag, don't pick silently.
**All four are written**; the two ADRs took numbers ADR-012 and ADR-013:

| | Plan | Amendment it writes first | Task |
|---|---|---|---|
| ✅ | PROMPT_CACHE_PLACEMENT | An ADR: request-level cache policy, descriptor-declared mechanisms, degradation as a typed event — landed as **ADR-012** | before `PC.1` |
| ✅ | RATE_GOVERNANCE | A §2 clarification separating in-process pacing from "no load balancing" and "not a control plane" | `RG.1` |
| ✅ | SPEND_LEDGER | A §2 clarification separating a caller-owned in-process ledger from "organization spend limits" | `SL.1` |
| ✅ | MCP_TOOL_SOURCE | An ADR covering "a tool source is not an agent framework" and "we speak MCP directly, no SDK" (ADR-007's rule), plus `contracts/mcp.md` — landed as **ADR-013** | `MT.1` |

RATE_GOVERNANCE and SPEND_LEDGER wrote their clarifications **in one change**, as required —
they make the same argument about the same non-goal boundary, and splitting them invites two
different answers to one question.

The Tier 3 plans add three more, on the same terms — none written yet:

| | Plan | Amendment it writes first | Task |
|---|---|---|---|
| ⬜ | NEW_ARENA_MODE | A §2 clarification naming three non-goals (agent framework, adaptive routing, prompt templating), a §27 extension, and an ADR | `AR.1` |
| ⬜ | SIDECAR_CORPUS_CONTEXT | A §27 rewrite separating "never collected it" from "must not decide what is safe to send" | `SC.1` |
| ⬜ | MULTIMODAL_INPUTS | A §2 amendment activating the reserved *input* parts while restating the output non-goals, plus an ADR | `MM.1` |

NEW_ARENA_MODE's clarification lands **with or after** SPEND_LEDGER's: both amend the same
§2 boundary, and the same rule applies as to the first pair.

ADR numbers are **not** assigned here; they are taken in landing order, as the
context-reduction plan did. The last ADR in DESIGN.md §23 is now **ADR-013**, so the three
Tier 3 ADRs start at ADR-014.

### Decisions carried across plans

- **Opt-in over on-by-default** — `GenerationRequest.cache` defaults to `None`,
  `SpendPolicy` and `RateLimits` are inert unless configured. Every one of these changes
  what a provider bills; none of them is an inference to act on uninvited.
- **One test namespace** — `anyinfer.testing` holds the conformance suite, the scripted
  provider, the pytest fixtures, and the fake MCP server, under one stability promise.
- **The library writes no files the user did not name** — `init` prints `.gitignore`
  advice rather than editing it, `agents-md` prints rather than installing, and
  `serve install` shows the unit before writing it.

## Ordering

Constraints 1–4 are discharged: TEST_KIT, THIRD_PARTY_PROVIDERS, PROMPT_CACHE_PLACEMENT,
SPEND_LEDGER, MCP_TOOL_SOURCE, and RATE_GOVERNANCE all landed in that order. **The live
constraints are 5 through 9**, and the remaining sequence is INIT_COMMAND →
AGENT_LEGIBILITY → SERVICE_INSTALL → NEW_ARENA_MODE → SIDECAR_CORPUS_CONTEXT →
MULTIMODAL_INPUTS.

1. **TEST_KIT first.** Its scripted provider is the test vehicle for INIT_COMMAND (`IN.2`),
   THIRD_PARTY_PROVIDERS (`TP.4`), RATE_GOVERNANCE (`RG.3`), SPEND_LEDGER (`SL.4`), and
   MCP_TOOL_SOURCE (`MT.4`). Building those first means writing throwaway harnesses five
   times.
2. **THIRD_PARTY_PROVIDERS shares TK.6** (conformance as a documented external entry
   point). Implement it once, in that plan.
3. **PROMPT_CACHE_PLACEMENT before SPEND_LEDGER.** `PC.6` changes cost arithmetic
   (cache-read tokens must not be billed as full-price input) and `SL.2` sums the result.
   Reversed, the ledger's tests encode the wrong total.
4. **MCP_TOOL_SOURCE after TEST_KIT.** `MT.4` needs the scripted provider, and `MT.4b`
   contributes the fake MCP server back into the same package — so the kit's shape should
   be settled before a second fake lands in it. Its subprocess supervision (`MT.3`) should
   be written by whoever last touched `local/server.py`, or with its tests open.
5. **AGENT_LEGIBILITY last among Tier 1.** `AL.2` renders the live verb and provider list,
   so running it after `init` and `conform` exist avoids regenerating the fragment.
6. **SERVICE_INSTALL is independent** of everything else and can land whenever.
7. **SPEND_LEDGER before NEW_ARENA_MODE — a hard prerequisite, not a preference.** Arena
   takes no cost ceiling of its own, so `SpendPolicy` is the only one it gets; and because
   arena covers the tool loop, the ceiling it needs to respect is `N × max_rounds`, not N.
   A named arena exposed through the sidecar lets any client trigger that with one `model`
   string, so exposure cannot precede the guard.
8. **MCP_TOOL_SOURCE `MT.4a` before arena's `AR.14`.** Run-scoped tool memoization defaults
   to read-only-eligible tools; without annotation capture that gate has no input.
9. **SIDECAR_CORPUS_CONTEXT is independent of arena** — they share the parity principle and
   the four-spellings pattern, but no code. **MULTIMODAL_INPUTS wants a milestone, not a
   slot**: it is larger than arena and SPEND_LEDGER combined and should not be interleaved
   with them.

Governance amendments are not in this ordering: each is written before its own plan's
first code task, and the two §2 clarifications land together.

## Conventions these plans assume

Carried from AGENTS.md and DESIGN.md; each plan relies on them rather than restating them:

- Cross-cutting changes update every affected workstream in one change — a new config key
  means SDK, CLI, sidecar, reference docs, and examples together.
- New wire behaviour updates the provider's `contracts/<id>.md` in the same change, with a
  real `last_verified` date.
- Degradations are typed events, never silence (`ParameterDropped` and its kin).
- Nothing is written to disk or the network by default; durable stores are caller-owned,
  following `MeasurementStore`.
- New dependencies go behind extras with justification; no official provider SDKs.
- No ADR identifiers in user-facing text — which now includes anything
  AGENT_LEGIBILITY generates.
