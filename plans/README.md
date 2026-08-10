# Plans

**Local working notes.** `plans/` is gitignored as of the documentation restructure, so
nothing here is tracked or reviewed in a PR. [DESIGN.md](../DESIGN.md) remains the
authoritative architecture document: where a plan disagrees with a stated goal, non-goal,
or ADR, DESIGN.md wins until the plan lands its amendment. Each file states its own
authority, governance intent, and the date its code audit was taken.

Scope and the open questions were settled on **2026-08-09**; every plan now ends in a
**Decisions** section rather than open questions. All four original governance items are
approved to proceed, and MCP is approved to build rather than to wait for a consumer.
**Four plans were added later the same day** from the parity review — see Tier 3, and
**three more the same day again** from a differentiation review — see Tier 4.

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

**As of 2026-08-09: eleven complete, one in progress, five not started** (seventeen plans
in all, counting the three Tier 4 additions). The governance amendments (both ADRs
and both §2 clarifications) are landed, and were already committed to `main` by the
concurrent session's `7024ce3` rather than sitting in the working tree.

## Where the second 2026-08-09 run stopped — read this first

The second implementation sitting started the remaining six in the Ordering section's
sequence and got through most of the first. **RUN_MANIFEST is 🚧, not ✅**, and its file is
therefore still on disk with a Status section at the top listing exactly what is left. In
short: tasks RM.1–RM.8 are landed and green, RM.9's library half is landed, and **RM.9's
shipped example and all of RM.10's documentation are not written**. Two acceptance
criteria (the `--trace` CLI case and the sidecar-extension case) have landed code and no
dedicated test. Its deviations — seven of them — are recorded in that file rather than
here, because the file has not been deleted yet.

**ADR-014 is taken.** RUN_MANIFEST landed its ADR first, as required, so the next ADR
number is **ADR-015**. The Tier 3/Tier 4 governance tables below still say "Tier 3 ADRs
start at ADR-014"; that is now wrong, and the numbers go in landing order from 015.

**The five untouched plans start from their own text**, in this order: TARGET_COMPARE →
NEW_ARENA_MODE → STREAM_SALVAGE → SIDECAR_CORPUS_CONTEXT → MULTIMODAL_INPUTS. Their code
audits predate the manifest work, which touched files several of them name — re-run
`git diff` against `_client/async_client.py` (a `ManifestBuilder` is now threaded through
the routed loop and `_emit` takes an optional builder), `_client/sync_client.py`,
`types/results.py` (`Generation` has a new trailing field), `serve/openai_codec.py` (a
third `anyinfer_*` extension), and `cli.py` (two new `run` flags) before starting.

**After the six plans, two follow-up items are outstanding** and were requested during the
run: the demo app should cover the new functionality where appropriate, and the
documentation needs a consistency pass against everything that actually landed. Neither
has been started.

## Where the first 2026-08-09 implementation run stopped

Four plans were carried to done in one sitting, in the index's own order: **INIT_COMMAND,
AGENT_LEGIBILITY, SERVICE_INSTALL, CAPABILITY_SIGNAL_GAPS**. Each one's file is deleted and
its deviations are recorded below. Nothing was left half-applied: every task in those four
is landed, tested, and green, and no plan was started and abandoned partway.

**Six plans were untouched at the end of the first sitting** — see the section above for
where the second one got to. Their code audits are as of the date they were written; the four landings above touched files several of them name, so re-run `git diff`
against those files before starting — in particular `cli.py` (three new verbs: `init`,
`agents-md`, `serve install|uninstall|status`), `types/capabilities.py` (two new
`ModelCapabilities` fields), `config/__init__.py` (a writer and one new root key), and
`benchmark.py` (one new `Measurement` field).

**Documentation was swept at the end of the run, not left to the plans' own tasks.**
Every new surface is reachable from a page a reader would actually find: `init`,
`agents-md`, and the reasoning-aware probe in [the CLI guide](../docs/guides/cli.md);
`serve install` in [running as a service](../docs/serve/running-as-a-service.md) and the
downloads page; `discover()` in [the local subsystem](../docs/concepts/local.md); the
config writer in [the configuration reference](../docs/reference/configuration.md);
sampling defaults in [capabilities](../docs/concepts/capabilities.md); `model_load_ms`
beside the other measurements; `SetupField.env_var` in
[writing a provider](../docs/guides/custom-providers.md), which is where an adapter author
will look for it. Both new guide pages are linked from `docs/README.md`,
`docs/guides/README.md`, and the nav.

**A pitch page was added on top of the plans**, at the user's request:
[docs/why-anyinfer.md](../docs/why-anyinfer.md). Five capabilities that are genuinely
unusual, then a comparison matrix whose columns are *categories* of tool rather than named
products — a category claim can be checked against what the category is for, a product
claim goes stale in a week. It is datestamped **2026-08-09**, says so above the table,
tells the reader to verify a specific tool rather than trust the generalization, and ends
with four honest "no" rows and a section of commands that check every AnyInfer claim on the
page. Its counts were taken from the repository, not from memory: ten certified matrix
rows (not seventeen), twenty contract snapshots (not twenty-three), five provenances (not
four).

**Three things a reader should not mistake for regressions:**

- `tests/test_workspace.py::TestBuild::test_all_builds_wheel_then_both_native_bundles`
  fails in this environment and did so before any of this work. Its `docs` phase shells out
  to `.venv/Scripts/mkdocs.exe`, which exits 1 with no output here while
  `python -m mkdocs build --strict` succeeds — a broken console-script shim, not a docs
  problem.
- `ruff check .` reports 22 findings, all of them in `src/demo_app/` and
  `tests/demo_app/` and all of them pre-existing (unsorted imports, an unsorted `__all__`,
  three missing docstrings, two long lines). Those paths belong to the concurrent session,
  so they were left alone rather than reformatted underneath it.
- The docstring gate reports `src/anyinfer/manifest.py: public name 'schema_digest' not in
  __all__`. That file is untracked and appeared mid-run: the other thread is implementing
  RUN_MANIFEST as this was written. Not this run's work, and not this run's to fix.

**A completed plan's file is deleted, not archived.** A finished plan that stays on disk
gets read later as if it still described work to do, and its "code audit as of" date rots
into a claim about the present. What it decided lives in the code, its tests, DESIGN.md, and
the contract snapshots; what it *deviated on* is recorded below, which is the only part a
deleted file would otherwise take with it.

Nine deviations were taken deliberately:

- **CAPABILITY_SIGNAL_GAPS** — three, and one of them is a corrected design.

  - **`CS.4`'s trusted-provenance gate was wrong, and the live check (`CS.5`) is what
    caught it.** As drafted, the probe raised its output budget only for a target whose
    reasoning flag came from a trusted source. Every real Ollama model reports its
    features at `default`, so the gate would never have fired for the thinking models the
    task exists for — `ollama:gpt-oss:20b` on this machine confirmed it: budget 64, gate
    inert. The shipped rule keys on the flag whatever its provenance, because this
    decision moves a *ceiling* rather than making a claim: a model answering in six tokens
    spends six either way, and the larger cap costs more only for a model that was going
    to be truncated — one that would have failed the probe regardless. `openai-compat`,
    whose feature set has no reasoning flag, still gets 64.
  - **`CS.7` populated `ai21`, not OpenAI.** The rule is "only from documentation, cite
    the source", and no upstream documentation is reachable from here to verify against —
    inventing a `last_verified` date is the one thing AGENTS.md forbids outright. AI21 is
    the single provider whose sampling defaults are *already* recorded in a dated contract
    snapshot (`openai-compat-presets.md`, verified 2026-08-07: temperature 0.4, top_p
    1.0), so it is the one that could be populated honestly today. The mechanism carries
    any provider; a drift run is what adds the next one.
  - **`CS.3` wired llama.cpp rather than documenting an absence.** The supervised runtime
    has no per-request load duration, but it does have a `starting → ready` interval, and
    that interval *is* the cold start. `ServerHandle` now records it and hands it over
    once, to the request that caused the start; every later request on that server is warm
    by definition.

- **SERVICE_INSTALL** — six, all forced by what the three service managers actually do.

  - `ServiceDefinition` carries `install_commands` / `uninstall_commands` /
    `status_commands` — tuples of commands, not one each. No manager registers a service
    in a single step (systemd wants a daemon-reload before an enable), and a singular
    field would have printed something that does not work.
  - Rendering is over `PurePath`, not `Path`. `Path.is_absolute()` answers for the
    interpreter's own platform, which would make a systemd unit un-renderable from a
    Windows machine — and rendering all three from any one of them is the whole point of
    keeping generation pure.
  - Windows writes **no** token file, taking `SI.4`'s "or decline to write the file and
    instruct instead" branch. A POSIX mode is meaningless there, and a secret file that
    looks protected is worse than none; the command prints the `setx` line instead, which
    puts the value where the OS already guards it.
  - `--system` prints and writes *nothing* — not even the definition. Its target
    directory needs root anyway, so writing half of it as the user would leave a file the
    operator then has to move.
  - macOS routes through a one-line `/bin/sh` wrapper when, and only when, a token is
    configured. launchd has no `EnvironmentFile`, and its `EnvironmentVariables`
    dictionary lives in the plist — exactly where the token must not go.
  - `SI.5`'s packaging assertion covers the function that populates the archive layout
    rather than a built archive. PyInstaller does not run in the suite; what the test
    pins instead is the property that matters — the `INSTALL.txt` text comes from the same
    renderer the command uses, so the download and the command cannot disagree.

- **AGENT_LEGIBILITY** — three, each a strengthening rather than a change of scope.

  - The `ADR-` leak check runs in the mkdocs hook as well as in a test, so a leak fails
    `mkdocs build --strict` rather than only the suite. The generated files are the ones
    read in a stranger's repository; the build is the last place that can stop them.
  - `docs/agents/INTEGRATION.md` is in the site nav rather than sitting outside it. It is
    the thing consumers are told to copy, so it needs a published URL, and a docs file
    outside the nav is a `--strict` warning waiting to happen.
  - `AL.3`'s coverage is enforced, not just written: a test counts the trap-table rows the
    renderer emits and fails if that number and the number of `test_agents_md_row_*` tests
    disagree, so a new row cannot land as an unchecked claim.

- **INIT_COMMAND** — five, none of them a change of intent.

  - The discovery module is `local/discovery.py`, not `local/discover.py`. A module whose
    name equals a function the package re-exports shadows itself on the package, which is
    the exact trap `registry.py` documents beside `default_registry`: it breaks
    introspection, mkdocstrings, and `monkeypatch.setattr` in tests.
  - The generated starter is `starter.py`, not `example.py`, and the template lives in
    `src/anyinfer/_starter.py` rather than in the examples directory — it has to ship in
    the wheel, so `init` still works from an installed package. The checked-in runnable
    copy is `docs/examples/starter.py`, asserted byte-identical to the template, and the
    generated file's `run()` is executed in CI against a scripted provider.
  - `dumps_config(comments=True)` required teaching the loader one root key, `_comment`,
    so that what the writer emits is something the loader accepts. Round-trip holds.
  - `DiscoveredProvider` carries `credential_key`/`credential_ref` beyond the plan's
    sketch, and `endpoint_candidates()` sits beside `discover()`. The first two are what a
    config writer needs to write a reference without re-deriving it; the third is what
    R-IN2's "the summary names every endpoint it contacted" needs, and it also collapses
    the four engines that share port 8080 into one probe.
  - `init` writes a provider only when evidence alone is enough to construct it. A
    provider that also needs a per-account base URL (Azure) becomes a printed note rather
    than a half-written entry that fails on first use.

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
provenance-tagged surface for provider sampling defaults. All three have landed
(CAPABILITY_SIGNAL_GAPS, file removed), including the narrow, requester-directed extension
back into `src/demo_app/`'s `_refresh_default_hints()` for the third — the one place that
plan pointed at. That is the only edit this thread has made under `src/demo_app/`.

## Tier 1 — the differentiators

| | Plan | What it adds | Why it differentiates |
|---|---|---|---|
| ✅ | TEST_KIT (file removed) | `anyinfer.testing` as a supported kit for *applications*: scripted providers, fault injection, a pytest plugin | Nobody else lets an app unit-test its own fallback, repair, and reduction paths offline. The machinery already exists for our conformance suite |
| ✅ | PROMPT_CACHE_PLACEMENT (file removed) | Core decides *where* the prompt cache is marked; adapters spell it | We already measure and price caching and cannot cause it. Same mechanism-ladder shape as structured output |
| ✅ | INIT_COMMAND (file removed) | `anyinfer init` — detect, recommend, write a valid config and a runnable starter | The first five minutes currently end in the configuration reference instead of a working call |
| ✅ | AGENT_LEGIBILITY (file removed) | `llms.txt`, `anyinfer agents-md`, a distributable integration skill | A coding agent's default guess for this library is an OpenAI clone, which is exactly what it is not |
| ✅ | THIRD_PARTY_PROVIDERS (file removed) | Template, `anyinfer conform`, visible plugin-load diagnostics | Turns provider *breadth* from a counting contest into "your adapter passes the same suite ours do" |

## Tier 2 — deepening the same boundary

| | Plan | What it adds | Note |
|---|---|---|---|
| ✅ | RATE_GOVERNANCE (file removed) | Per-provider pacing from the rate-limit headers we already receive | We honour `Retry-After` on the way *down* and anticipate nothing on the way up |
| ✅ | SPEND_LEDGER (file removed) | In-process spend rollup plus an optional preflight ceiling | Cost is already tri-state and `Decimal`; accumulating it correctly is subtle enough to ship once |
| ✅ | MCP_TOOL_SOURCE (file removed) | MCP servers as a source of `ToolSpec`s for the existing tool loop | Adds a tool *source*, not loop semantics. Spoken directly, with a pinned contract snapshot |
| ✅ | SERVICE_INSTALL (file removed) | systemd / launchd / scheduled-task definitions for the sidecar | Finishes the "no Python required" path at a service that survives a reboot |
| ✅ | CAPABILITY_SIGNAL_GAPS (file removed) | `Measurement.model_load_ms`, a reasoning-aware `verify()` probe, provenance-tagged `default_temperature`/`default_top_p` | The three loose ends UI_MODIFICATIONS left for the core thread |

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

## Tier 4 — explaining the boundary we already own (added 2026-08-09)

One question produced these three: **in a marketplace where every library claims provider
breadth, what can AnyInfer offer that a competitor structurally cannot copy?** Not another
subsystem — the answer each time was to *expose a decision the core already makes*. A
gateway can log a request and a response because that is all it owns; it cannot report a
mechanism-ladder degradation, a provenance-tagged window, or a reduction's omissions,
because it does not make those calls. These plans turn that asymmetry into surface.

The review also found a parity defect Tier 3 missed. Tier 3 audited the **request** side
and closed three gaps there. Nobody audited the **result** side: all twenty typed telemetry
events are Python-only, and `serve/app.py` has four routes and no observability surface at
all. A developer on the standalone binary gets every provider, route, and mechanism, and no
way to see which fired.

| | Plan | What it adds | Why it differentiates |
|---|---|---|---|
| 🚧 | [RUN_MANIFEST.md](RUN_MANIFEST.md) | One versioned, content-free artifact per call: route, mechanism, cache, drops, reduction, provenance, cost — plus golden-file assertions in `anyinfer.testing` | The manifest is a *golden file*, so an app can regression-test its inference **behaviour** rather than the model's prose. Also the fix for the result-side parity defect |
| ⬜ | [TARGET_COMPARE.md](TARGET_COMPARE.md) | `client.compare(request, targets=[...])` — what *this* request becomes on each target, spending nothing | Turns the conformance matrix from a documentation table into a runtime answer. Every input is already a pure function; it is assembly, not a subsystem |
| ⬜ | [STREAM_SALVAGE.md](STREAM_SALVAGE.md) | Resume a generation that died mid-stream from the salvaged text instead of re-generating from zero | Nobody does this. **Feasibility measured, not assumed** — see that plan's §1. **Gated on `SS.0`, and the gate is now leaning no**: Anthropic removed assistant prefill from its whole current line (400), OpenAI Responses never had it, and the local engines where it does work are exactly where dropped connections are rarest. Build the other two first regardless |

**STREAM_SALVAGE is the one with empirical backing already done.** Five probe rounds on
2026-08-09 established that it works, that it is narrower than it looks (structured output,
tool calls, and reasoning traces are permanently unrecoverable), and that two specific
rules — trim the prefill past any partial token *and* strip trailing whitespace; inherit
the remaining output budget rather than the original — are the difference between clean
seams at 5/5 cut points and corrupted text at 1/5. That evidence is in the plan rather than
in anyone's memory, which is the point of writing it down.

Rounds five and six tested the obvious way around the structured-output boundary —
re-derive the object instead of continuing it. Round five concluded it fabricates; **round
six retracted that**, because round five had withheld the original question *and* attached
the schema, so the grammar forced a required field into existence with no source. Tested
properly, the pipeline works: every salvaged field returns byte-identical and the missing
one is generated legitimately. It is still refused, on better grounds — honest recovery
costs a retry's input to save 6% of its output, while the cheaper variant produces
schema-valid fabrications nothing in this library can detect. `SS.1` records that coupling
*as an argument*, and concedes the mechanism works, because a rejection that overstates its
case is the one a future contributor overturns by testing it properly. The honest residue
became `SS.12`.

Round seven tested whether constraints spanning the seam survive a resume — item counts,
dependent tails, global length caps — and found they do, because the prefill carries prior
output forward, so the rule is in the messages and the progress is in the salvaged text.
That **narrows** the risk surface: salvage is unsafe only where the generation depended on
state in neither, which is the three cases already refused, all detectable from the response
without inspecting the prompt. The plan also refuses a **confidence score** on a salvage —
no available signal measures veracity, and the one technique that does costs more than
simply retrying. `spans` ships instead: which characters came from which attempt, as fact
rather than as a guess.

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

Tier 4 adds three more — one clarification and two ADRs, none written yet:

| | Plan | Amendment it writes first | Task |
|---|---|---|---|
| ✅ | RUN_MANIFEST | An ADR *extending* ADR-006 — landed as **ADR-014**: the manifest is derived from events and `Generation`, never a parallel source of truth, and stays content-free by default on the same terms | `RM.1` |
| ⬜ | TARGET_COMPARE | A §2 clarification extending the pacing one: reporting is not selecting, and a built-in "pick the best" is a reversal to argue | `TC.1` |
| ⬜ | STREAM_SALVAGE | An ADR: a salvaged `Generation` is stitched from more than one call — opt-in, labelled on the result and in events, with the three refusal cases as contract | `SS.1` |

TARGET_COMPARE's clarification lands **with or after** NEW_ARENA_MODE's: arena's names
adaptive routing as a non-goal and compare's draws the reporting/selecting line inside it.
Same rule as the first pair — one boundary, one answer.

ADR numbers are **not** assigned here; they are taken in landing order, as the
context-reduction plan did. The last ADR in DESIGN.md §23 is now **ADR-013**, so the three
Tier 3 ADRs start at ADR-014 and Tier 4's two follow them. **Superseded:** RUN_MANIFEST
landed first and took ADR-014, so the remaining ADRs start at **ADR-015**.

### Decisions carried across plans

- **Opt-in over on-by-default** — `GenerationRequest.cache` defaults to `None`,
  `SpendPolicy` and `RateLimits` are inert unless configured. Every one of these changes
  what a provider bills; none of them is an inference to act on uninvited.
- **One test namespace** — `anyinfer.testing` holds the conformance suite, the scripted
  provider, the pytest fixtures, and the fake MCP server, under one stability promise.
- **The library writes no files the user did not name** — `init` prints `.gitignore`
  advice rather than editing it, `agents-md` prints rather than installing, and
  `serve install` shows the unit before writing it.
- **Where a plan rests on a claim about model or provider behaviour, measure it first and
  put the numbers in the plan** — STREAM_SALVAGE §1 is a probe result against a live engine,
  not a design sketch, and it changed the design twice: the obvious mitigation turned out to
  make the seam worse, and the obvious economics turned out to be half of what capping the
  resume budget delivers. Neither would have surfaced from reasoning about it.

## Ordering

Constraints 1–4 are discharged: TEST_KIT, THIRD_PARTY_PROVIDERS, PROMPT_CACHE_PLACEMENT,
SPEND_LEDGER, MCP_TOOL_SOURCE, and RATE_GOVERNANCE all landed in that order, and
INIT_COMMAND, AGENT_LEGIBILITY, SERVICE_INSTALL, and CAPABILITY_SIGNAL_GAPS have since
landed too. RUN_MANIFEST is under way (see the status section at the top). **The live
constraints are 5 through 12**, and the remaining sequence is
RUN_MANIFEST (finish) → TARGET_COMPARE → NEW_ARENA_MODE → STREAM_SALVAGE →
SIDECAR_CORPUS_CONTEXT → MULTIMODAL_INPUTS.

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
6. **SERVICE_INSTALL was independent** of everything else and landed on its own.
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
10. **TARGET_COMPARE before NEW_ARENA_MODE.** Both need "resolve a request against N targets
    without dispatching". `compare()` builds that plumbing for zero calls and zero spend;
    arena then inherits it and gets a preflight to show beside its results. Reversed, arena
    builds it under a cost ceiling and `compare()` refactors it afterward.
11. **RUN_MANIFEST before STREAM_SALVAGE — a hard prerequisite.** A salvaged answer is
    stitched from two calls, and `SS.1` requires that be visible after the fact. The manifest
    is where it becomes visible; without it, salvage ships a labelled field nothing renders.
    **And STREAM_SALVAGE is gated on its own `SS.0` besides** — a credential-cheap spike
    checking whether hosted providers support assistant-prefill continuation at all. If
    fewer than three do, the router feature is not built and only `SS.12` lands. That spike
    can run at any time; it does not need its slot in this sequence to be reached first.
12. **RUN_MANIFEST is the strongest candidate to pull forward** ahead of AGENT_LEGIBILITY if
    the marketing surface matters sooner than the agent surface. It is the only plan here
    that is simultaneously a differentiator, a parity fix, and the completion of TEST_KIT's
    thesis — and it depends on nothing unlanded. The sequence above is conservative, not
    load-bearing, on this point.

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
