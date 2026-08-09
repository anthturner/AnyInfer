# Arena mode — many targets, one request, one chosen answer

**Scope:** an `ArenaPolicy` on the client and on `GenerationRequest` that sends **one**
request — or **one tool loop** — to **N** targets concurrently, keeps every candidate with
its usage, cost, timing, and schema validity, and applies a caller-chosen selection
strategy: deterministic, or a single extra call that judges or synthesizes. Available
identically from the Python SDK, `anyinfer run`, and the sidecar. Ships in the core.
**Goal:** make "ask three engines and take the best answer" a supported, measured,
announced operation instead of an `asyncio.gather` an application writes badly.
**Non-goal:** adaptive routing, quality learning, leaderboards, persistent rankings, or
anything that changes what a *later* `generate()` picks.

**Audience for this plan:** contributors editing the existing files directly. Code audit is
as of **2026-08-09, re-taken late the same day** after TEST_KIT, PROMPT_CACHE_PLACEMENT,
THIRD_PARTY_PROVIDERS, RATE_GOVERNANCE, SPEND_LEDGER, and MCP_TOOL_SOURCE all landed. Line
anchors were re-synced against the tree at that point; they drifted within hours of first
being written, so **re-verify before starting each task** is a live instruction here, not
boilerplate.

**Authority:** DESIGN.md §2 (non-goals — "not an agent framework… no multi-agent
constructs", "no load balancing or cost/latency-adaptive routing", "no prompt templating"
— all three amended or narrowed by this plan), §5, §9 (structured output), §11 (routing),
§14 (telemetry), §15 (shared configuration), §16 (sync facade), §20 item 1 (estimator,
budget, gating), §22 (sidecar surface and invariants), §27 (**policy lives at the client
layer so every frontend inherits it** — the governing precedent); ADR-001, ADR-003,
ADR-006, ADR-009, ADR-011, ADR-012 (request-level policy object, adapters only spell it —
the closest structural precedent), ADR-013.

**Related plans:** SPEND_LEDGER was a **hard prerequisite** (§5 decision 4) and has
**shipped** — `SpendPolicy` and `SpendLedger` are the ceiling arena must respect, and its
plan file is deleted. That prerequisite is *not* fully discharged: the ceiling leaks under
concurrency, which is the one condition arena guarantees. §5 decision 4 carries the detail,
and carries it alone now that the ledger's own plan file is gone. MCP_TOOL_SOURCE had to capture tool annotations for
§2.8's gate — **discharged**: `ToolSpec.annotations` exists
([types/requests.py:181](../src/anyinfer/types/requests.py#L181)), populated from
`readOnlyHint` ([mcp/toolset.py:301](../src/anyinfer/mcp/toolset.py#L301)) and documented
as untrusted hints, so ordering constraint 8 in the index is met. [SIDECAR_CORPUS_CONTEXT.md](SIDECAR_CORPUS_CONTEXT.md) and
[MULTIMODAL_INPUTS.md](MULTIMODAL_INPUTS.md) are the two other parity gaps this plan's
review surfaced; both are independent of it.

**Governance intent: three non-goals are in play and the amendment must address each by
name, before code (`AR.1`).** This is the most non-goal-adjacent plan in `plans/`, and the
honest framing is not "arena is not multi-agent" — it *is* a multi-candidate construct —
but "arena is a fixed shape with a call ceiling known before dispatch, no planning, no
memory, no cross-candidate influence, and no feedback into target selection". That is the
argument `distill` won (a bounded map/reduce that spends inference calls) and
`compact_history` won (mechanical arithmetic over fixed rules), applied to a fan-out across
targets rather than across chunks. Two clauses do the real work:

1. **Arena never informs routing.** The moment a past arena outcome changes which target a
   later request goes to, this has become cost/latency-adaptive routing — a reversal to
   argue, not a config option.
2. **Candidates never see each other.** No candidate reads another's tool results, partial
   output, or answer, and nothing is judged mid-loop. Selecting *between* finished
   candidates is comparison; selecting which branch to *continue* is planning, and that is
   the line between this and an agent framework.

---

## 1. Motivation and evidence

The parts that make cross-target comparison honest already exist here and nowhere else in
one place:

- **Usage and timing are defined identically across providers.** TTFT is measured
  centrally at the first visible delta, not by each adapter (§14; `Timing.first_token_ms`).
  An app comparing two engines by hand compares two definitions.
- **Cost is tri-state and provenance-gated.** `compute_cost` refuses `default`-provenance
  pricing ([capabilities/pricing.py:28](../src/anyinfer/capabilities/pricing.py#L28)), so
  "cheapest candidate" is either a real answer or an honest *unknown*, never a fabricated
  `$0.00`.
- **Structured output is validated client-side against the original schema** (§9). This is
  what makes arena more than vibes: with a schema set, N candidates are N validated
  objects, and agreement between them is **exact and computable** — no judge model, no
  similarity metric, no taste.
- **Each candidate can itself be a full route.** Retry, fallback, and the health gate
  already work per target; an arena candidate is a `Route`, not a bare call, for free.
- **`benchmark.py` already runs one prompt across targets** and stores normalized
  `Measurement`s ([benchmark.py:113](../src/anyinfer/benchmark.py#L113)). Arena is that
  machinery when the *answers* matter, not just the rates.

**On demand, stated plainly.** Unlike ADR-011, this plan has **no named consumer**;
`anyinfer.context` shipped because Frisket and mote-cli each had working code to port.
Arena is being built as a differentiator on a deliberate bet — that the consumer apps are
the place to *discover* where multi-target comparison earns its cost, and that it cannot be
discovered while the capability does not exist. That is risk R5 accepted knowingly, on the
same terms as ADR-013, and the mitigation is the same: inert unless configured, so the cost
of being wrong falls entirely on whoever turns it on. What this rules out is the reverse
justification — arena must not be defended later by pointing at usage it created.

## 2. Design

### 2.1 Placement: the client layer, because that is where parity lives

Arena is a **policy object on the client and on the request**, not a standalone module and
not a frontend feature:

```python
@dataclass(frozen=True, slots=True)
class ArenaPolicy:
    """Fan one request out to many targets and choose among the answers."""

    targets: tuple[Target, ...]
    strategy: Literal["first_valid", "consensus", "cheapest", "fastest",
                      "judge", "synthesize"] = "first_valid"
    judge_target: Target | None = None      # required by judge/synthesize
    instructions: str | None = None         # replaces the default rubric wholesale
    concurrency: int = 4
    min_candidates: int = 1
    reveal_targets: bool = False
    memoize_tools: Literal["read_only", "all", "opt_in", "off"] = "read_only"
```

Passed as `AsyncClient(arena=…)` / `Client(arena=…)`, per request as
`GenerationRequest.arena`, and returned on the result as `Generation.arena: ArenaResult |
None`. It governs `generate`, `stream`, **and `run_tools`** (§2.9).

This is §27's rule applied unchanged. That section settled the question for
`HistoryPolicy` in one sentence — the router owns overflow "at the **client** layer, which
is why the Python API, the CLI, and the sidecar have always behaved identically about it:
all three are the same `AsyncClient` wearing different skins" — and the shared-config
docstring says the same about the mechanism: *"Pass to `Client` or `AsyncClient` as
`history=`; every frontend built on that client then behaves identically"*
([config/__init__.py:86](../src/anyinfer/config/__init__.py#L86)). Anything placed beside
the client instead of inside it is a capability one frontend has and the others do not,
which is exactly the pigeonholing this plan exists to avoid.

Two consequences worth naming, because they are improvements rather than costs:

- **ADR-009 survives intact.** The sidecar does not implement arena. It decodes an
  `anyinfer_arena` object into `GenerationRequest.arena` and hands the request to the
  client — the same shape `_decode_history` already is
  ([serve/openai_codec.py:233](../src/anyinfer/serve/openai_codec.py#L233)). A module
  beside the client would have forced the codec to *call* an orchestrator, which is the
  second core ADR-009 forbids. The parity requirement and ADR-009 point the same way.
- **The sync facade gets real concurrency.** `distill_sync` runs sequentially because it
  accepts any sync client by structural protocol and has no loop to schedule on
  ([context/distill.py:236](../src/anyinfer/context/distill.py#L236)). `Client` owns a
  background event loop (§16), so `Client(arena=…)` fans out concurrently and matches
  `AsyncClient` exactly. Placement removes an asymmetry rather than adding one.

`Route` is untouched: it stays an ordered fallback chain where the first success wins.
Arena is the orthogonal thing that deliberately does not stop at the first success, and
each of its candidates *is* a `Route`.

### 2.2 Types

```python
@dataclass(frozen=True, slots=True)
class Candidate:
    """One target's answer, or its failure. Never discarded."""

    target: ResolvedTarget
    generation: Generation | None       # None iff the route for this target failed
    error: ErrorInfo | None             # redacted, bounded — the standard fields
    valid: bool | None                  # schema validity; None when the request had no schema
    elapsed_ms: float
    rounds: int | None = None           # tool-loop rounds; None for single-shot
    tool_calls: int = 0                 # dispatched, excluding memoized hits


@dataclass(frozen=True, slots=True)
class ArenaResult:
    """Every candidate, what was chosen, and what the whole thing cost."""

    candidates: tuple[Candidate, ...]   # target order, always complete
    winner: Candidate | None            # None when nothing was selectable
    strategy: str                       # the strategy that actually ran, post-degradation
    agreement: int | None               # consensus group size; None when not applicable
    synthesized: Generation | None      # present only when a synthesis call ran
    calls: int                          # generation calls actually spent
    memoized_tool_calls: int = 0        # dispatches avoided by §2.8
    usage: Usage = Usage()              # merged across every call, judge included

    def summary(self) -> str: ...       # one line, content-free
```

The winning text, usage, and timing are promoted onto the returned `Generation`, so an
arena result is a drop-in for a normal one; `Generation.arena` carries the evidence.

**The load-bearing rule: `winner` never replaces `candidates`.** A selection is an
opinion; the candidates are the evidence. Returning only the winner would make a wrong pick
invisible, which is the failure mode this feature exists to expose.

### 2.3 Deterministic strategies (no extra call)

| Strategy | Rule | Requires |
|---|---|---|
| `first_valid` *(default)* | Target order; first candidate that succeeded and, with a schema, validated | — |
| `consensus` | Group by canonical JSON of `Generation.structured` (sorted keys, no whitespace); largest group wins; ties by target order | `request.schema` |
| `cheapest` | Lowest `usage.cost_usd` among valid candidates; unknown cost never sorts as zero — it is excluded, and if *all* are unknown the strategy degrades | trusted pricing |
| `fastest` | Lowest `timing.total_ms` among valid candidates | — |

`consensus` is the strategy worth building this for, and it is exactly as strong as the
schema is: three engines independently producing the same validated object is evidence no
single call can give you, and it costs no extra tokens. It is **refused, not emulated, for
free text.** Consensus over prose needs a similarity metric, and a lexical one would set
exactly the quality expectations risk R8 warns about; the library will not invent one.

Degradation is announced, never silent: a strategy that cannot apply (no schema, all costs
unknown, no valid candidates) falls back to `first_valid`, records the fact in
`ArenaResult.strategy`, and emits `ParameterDropped` — the existing degradation event used
for its existing purpose.

### 2.4 The judge, and the prompt-language boundary

`judge` and `synthesize` spend **one** additional call at an explicit `judge_target`.
Fixed shape, ceiling known before dispatch — the property that lets this sit beside
`distill` rather than beside a planner.

- **`judge`** sends the candidates with a forced schema (`{"pick": <index>, "why": <str>}`),
  so the judge's own output is validated by machinery already in the core. An unparseable
  or out-of-range pick degrades to the deterministic strategy rather than raising — a judge
  that fails is not an outage.
- **`synthesize`** asks for a merged answer, returned in `ArenaResult.synthesized`
  *alongside* the candidates and a deterministic `winner`.

The library supplies the **mechanical candidate envelope** only —
`<candidate index="1">…</candidate>` blocks carrying `format="1"`, mirroring
[context/envelope.py](../src/anyinfer/context/envelope.py) — plus one documented default
instruction string, the same carve-out `distill`'s `_MAP_INSTRUCTIONS` /
`_REDUCE_INSTRUCTIONS` already hold
([context/distill.py:51](../src/anyinfer/context/distill.py#L51)). The rubric is the
caller's: `instructions=` replaces the default wholesale. Apps still own all prompt
language; the library owns one data format.

Two rules on the envelope, both about not rigging the comparison:

1. **Candidates are anonymized by default.** No provider id, model name, or cost appears in
   the judge's prompt. A judge told one answer came from a famous model is not judging the
   answer. `reveal_targets=True` exists for callers who want the opposite.
2. **Order is target order, and nothing is shuffled.** Position bias is real and is
   documented rather than papered over: shuffling trades a known bias for
   irreproducibility, and every other reduction in this library is deterministic on purpose
   (§26, stable prompt prefixes).

### 2.5 Execution, cost, and failure

- Concurrency is capped (`concurrency`, default 4) and each candidate runs its own `Route`,
  so per-target retry, fallback, and the health gate apply unchanged. The per-provider
  pacer already sits underneath (`routing/limits.py`, wired into the attempt path as
  `AttemptPacing`) and needs no arena awareness.
- **`min_candidates` (default 1)** decides partial failure. Below it, raise
  `AllTargetsFailedError` carrying every candidate's attempt trail — the existing error,
  the existing shape. At or above it, the arena succeeds with failures recorded in
  `candidates`.
- Cancellation cancels the remaining candidates; a candidate that has already produced a
  `Generation` is kept.
- **Cost is N× at minimum and must look like it.** The preflight estimate is the summed
  per-target estimate over the same machinery `client.budget()` uses
  ([_client/async_client.py:1160](../src/anyinfer/_client/async_client.py#L1160)), judge
  call included. Over the tool loop the ceiling is `N × max_rounds + 1`, which is why a
  sound spend ceiling is a prerequisite rather than an adjacency: `SpendPolicy` is the
  *only* one arena gets (§5 decision 3), and it is not yet sound under concurrency.

**The existing spend guard does not hold under fan-out, and arena must fix it rather than
inherit it.** `_check_spend`
([_client/async_client.py:1906](../src/anyinfer/_client/async_client.py#L1906)) is
per-target and runs inside the dispatch of one resolved target. Under an arena that fails
twice:

1. `max_request_usd` is checked against each candidate separately. Five candidates at
   $0.90 each pass a $1.00 per-request ceiling and spend $4.50 — while the caller made
   *one* request. The ceiling stops meaning what its name says.
2. `max_total_usd` compares `ledger.totals().cost + estimate`, and the ledger only moves as
   requests *complete*. Candidates dispatch concurrently, so every one of them reads the
   same pre-arena total and each individually passes. That is a race, not a definitional
   quibble, and the tool loop compounds it by `max_rounds`.

So arena performs **one summed check for the whole run before any candidate dispatches**,
and the per-candidate checks are subordinate to it. `max_request_usd` is documented to mean
the request the caller made — the entire arena — not each candidate's share.
- Telemetry: one new event, `ArenaCompleted` (content-free — target count, strategy,
  agreement, calls, memoized-call count, whether synthesis ran). It must be added to the
  OTel bridge in the same change, since the bridge drops unmapped members silently
  (ADR-006); `tests/test_otel_bridge.py` enforces this.

### 2.6 Parity across the three surfaces

One capability, four spellings, no frontend that has to say "use the SDK for that". Every
field of `ArenaPolicy`, memoization included, is reachable from all four:

| Surface | Spelling |
|---|---|
| **SDK** | `Client(arena=ArenaPolicy(...))`, or per request `GenerationRequest.arena` |
| **Shared config** | an `arena` block on `AnyInferConfig`, parsed by `_parse_arena` beside `_parse_history` ([config/__init__.py:392](../src/anyinfer/config/__init__.py#L392)) — a default policy plus **named arenas** |
| **CLI** | `anyinfer run --arena a,b,c --arena-strategy consensus --memoize-tools read-only`, or `--arena-name panel` |
| **Sidecar** | `anyinfer_arena` extra-body object, decoded into `GenerationRequest.arena`; **or** a named arena in the `model` string |

The named-arena path is what makes the daemon genuinely equal rather than
equal-if-your-client-can-send-extra-fields. §22 already says the `model` field may name "a
named route configured server-side"; a named arena occupies the same slot, so
`model: "panel"` from any stock OpenAI client runs the three-target consensus the operator
configured — no client changes, no extension support, no SDK. That is the parity case that
actually matters, because the clients pointed at a sidecar are usually not ours.

Flags are generated from the dataclass, following `_add_tuning_flags`
([cli.py:1109](../src/anyinfer/cli.py#L1109)), which already does this for `ContextTuning`
(§26), so the block key, the flag, and the keyword argument cannot come to name different
things. AR.12 makes that a property the suite enforces.

**One adjacent gap is *not* fixed here.** Corpus reduction is still SDK/CLI-only, and
multimodal content parts still have nowhere to go. Both are real parity gaps, both are
independent of arena, and both now have their own plans
([SIDECAR_CORPUS_CONTEXT.md](SIDECAR_CORPUS_CONTEXT.md),
[MULTIMODAL_INPUTS.md](MULTIMODAL_INPUTS.md)).

### 2.7 The OpenAI response shape

- **Non-streaming:** the winner (or the synthesis) becomes `choices[0]` exactly as a normal
  completion does. The full candidate set is attached as an `anyinfer_arena` object on the
  response body. Stock clients ignore unknown top-level fields and see one ordinary answer;
  AnyInfer-aware clients get the evidence. Candidates are **not** mapped onto `choices[]`:
  `choices` are alternatives a caller is invited to pick from, and a UI rendering four of
  them has undone the selection the arena just performed. `n` keeps its OpenAI meaning and
  never triggers an arena.
- **Streaming:** deterministic strategies cannot stream a winner that has not been chosen
  yet, so the arena emits the winner as a single delta plus the terminal chunk — precisely
  the buffered-provider degradation ADR-001 already defines, no new contract. `synthesize`
  streams its synthesis call naturally. Either way TTFT honestly reflects the whole arena,
  and the terminal chunk carries the `anyinfer_arena` extension.

### 2.8 Tool-call deduplication within a run

When candidates run tools, two of them asking a server the *identical* question should get
one answer, not two. Scope is the run, not a process-wide cache with a TTL: within one
arena every candidate is supposed to be reasoning about the same world state, so a rolling
source that returns different results to identical calls mid-run does not preserve
fidelity — it corrupts the comparison, and makes `agreement` a measure of the server's
churn rather than of the models. Run-scoping needs no TTL because it makes no bet about
elapsed time.

- **Placement:** the dispatch point in `ToolRegistry`
  ([_client/tools.py:187](../src/anyinfer/_client/tools.py#L187)), not the MCP client. MCP
  is a tool *source* (ADR-013); a `@ai.tool` Python function has the identical problem in
  an arena, and one memo covers both.
- **Key:** tool name plus canonical JSON of the arguments — the same canonicalization
  consensus grouping uses (§2.3), so there is one definition of "the same call".
- **Single-flight, not post-hoc.** Identical calls already in flight share one future. In a
  concurrent fan-out most duplicates race, and a memo that only fills on completion misses
  them.
- **Lifetime is the arena run**, shared across candidates *and* across rounds within a
  candidate. Outside an arena, `run_tools` is unchanged — a plain loop that calls the same
  tool twice still dispatches twice, because a model re-checking a value deliberately is
  not a duplicate to be optimized away.
- Errors are never memoized; a failure is not an answer.
- Hits are announced on `ArenaResult.memoized_tool_calls` and in telemetry — a call that
  did not happen must be visible.

**Default `read_only`, configurable on every surface.** Memoize when the tool declares
itself read-only or the caller marked it cacheable; everything else executes once per
candidate. `all`, `opt_in`, and `off` are available through the SDK field, the config
block, and the CLI/sidecar spellings of §2.6 — the setting is part of the parity contract,
not an SDK-only knob. MCP's `readOnlyHint` / `idempotentHint` annotations are the natural
input, with the spec's own caveat that they are untrusted server-supplied hints: adequate
to gate an optimization, never a security decision.
Annotation capture **has shipped**: the field names are verified into `contracts/mcp.md`
rather than assumed, so this gate has its input already.

**Fuzzy matching is refused, and the refusal is recorded here so it is not re-proposed.**
Near-identical arguments (`find_work_item("SOA Platform", "azure infrastructure")` vs
`… "infrastructure in azure"`) are near-identical only if that parameter is a full-text
query; if it is an exact tag, a saved-filter name, or a query fragment, they are different
calls. A schema states an argument's type, never its semantics, and the server author
promised nothing either way. The failure is silent — a wrong hit raises nothing, feeds one
candidate evidence it did not ask for, and inflates the agreement figure — and the
similarity metric it would need is the one §2.3 already refuses for text consensus, for
risk R8's reasons. It would also delete the signal being paid for: when one model's
differently-phrased query surfaces something another's did not, that difference *is* the
finding.

### 2.9 Arena over the tool loop

`run_tools` with an `ArenaPolicy` runs **N independent loops**, not N calls. Each candidate
keeps its own message history, makes its own tool calls, and stops on its own — one may
finish in two rounds while another runs eight, and both are complete candidates.

The boundary that keeps this from being an agent framework is **no cross-candidate
influence**:

- Selection applies to the **final** assistant turn of each loop, once every loop has
  ended. Nothing is judged mid-loop.
- No candidate sees another's tool results, partial output, or answer. The only thing they
  share is the memo table of §2.8, which returns *the same answer to the same question* —
  it never carries one candidate's reasoning to another.
- No candidate is pruned early because another looks better. Choosing which branch to
  continue is planning; comparing finished branches is not.

`max_rounds` applies per candidate, so the generation-call ceiling is `N × max_rounds`
(plus one for a judge) and is knowable before dispatch — the property the governance
argument rests on. It is also a much larger number than the single-shot case, which is why
§5 decision 4 makes a concurrency-correct `SpendPolicy` a gate on this plan.

### 2.10 Packaging

Core, not an extra. Arena is stdlib-only and adds no dependency, so it ships like
`benchmark.py`. This is also the parity-safe answer: the standalone `anyinfer-serve` binary
bundles a fixed set of extras (ADR-010), so anything behind one risks being present in the
SDK and absent from the daemon — the exact asymmetry §2.6 exists to prevent.

## 3. Tasks

**AR.1 — governance amendment** in DESIGN.md, reviewed before code: a §2 clarification
naming all three non-goals (agent framework, adaptive routing, prompt templating), a §27
extension recording that arena is client-layer policy for the same reason `HistoryPolicy`
is, and an ADR in §23 (number taken in landing order). The ADR states the fixed shape, the
known-before-dispatch call ceiling, the anonymized envelope, the no-cross-candidate-
influence rule of §2.9, and — the operative clause — that arena results never inform target
selection.

**AR.2 — shared usage merge.** `_merge_usage`
([context/distill.py:499](../src/anyinfer/context/distill.py#L499)) is private and arena
needs identical arithmetic. Promote it to a shared internal rather than copying it; a
second implementation of "sum usage, keep unknowns unknown" is a second place for the
coerce-`None`-to-zero bug. *Acceptance:* distill's existing tests pass unmoved.

**AR.3 — `ArenaPolicy` / `Candidate` / `ArenaResult` + fan-out in `AsyncClient`.**
Per-target `Route`, concurrency cap, `min_candidates`, cancellation, `Generation.arena`.
*Acceptance:* new `tests/test_arena.py` covers: one target failing leaves the arena
successful with a recorded `ErrorInfo`; all failing raises `AllTargetsFailedError` with
every attempt trail; cancellation stops pending candidates and keeps completed ones;
`calls` equals the target count.

**AR.4 — sync facade parity.** `Client(arena=…)` fans out concurrently on the facade's own
loop (ADR-002 — no sync-only path, and no async-only capability either). *Acceptance:*
`tests/test_sync_client.py` gains a parity case asserting the sync path runs candidates
concurrently, not sequentially.

**AR.5 — deterministic strategies.** `first_valid`, `consensus`, `cheapest`, `fastest`,
plus announced degradation. *Acceptance:* consensus over three `ScriptedProvider` targets
(`anyinfer.testing`), two agreeing, selects the pair and reports `agreement == 2`; unknown cost is never treated as
zero; `consensus` without a schema degrades to `first_valid` and emits `ParameterDropped`;
canonical-JSON grouping is key-order insensitive.

**AR.6 — candidate envelope.** `format="1"`, anonymized by default, deterministic order,
`reveal_targets` opt-in. *Acceptance:* a golden-text test; the rendered envelope contains
no provider id or model name unless revealed.

**AR.7 — `judge` and `synthesize`.** Forced pick schema, degradation on an unusable
verdict, `instructions=` override. *Acceptance:* a judge returning an out-of-range index
degrades rather than raises; `calls == N + 1`; merged `usage` includes the judge call;
`candidates` are all still present when `synthesized` is set.

**AR.8 — `ArenaCompleted` event + OTel bridge.** Both in one change. *Acceptance:*
`tests/test_otel_bridge.py` passes with the union extended; the event carries no payload.

**AR.9 — config block + named arenas.** `_parse_arena`, `AnyInferConfig.arena` and
`AnyInferConfig.arenas`, unknown keys rejected (§15 rule). *Acceptance:* a file with a
misspelled key fails loudly; a named arena round-trips; the block is documented in the
configuration reference.

**AR.10 — CLI.** `--arena`, `--arena-strategy`, `--judge-target`, `--arena-name`,
`--memoize-tools`, flags generated from the dataclass; `--stats` gains a per-candidate
table (cost, TTFT, total, rounds, valid); `--dry-run` reports the call ceiling and summed
cost range. *Acceptance:* the table prints unknown cost as unknown; `--dry-run --arena`
spends nothing (the scripted provider records zero requests).

**AR.11 — sidecar codec.** `anyinfer_arena` decode beside `_decode_history`; named-arena
resolution in the `model` string; `anyinfer_arena` response extension; the streaming rule
of §2.7. **No orchestration in `serve/`.** *Acceptance:* a round-trip codec test; a stock
OpenAI client with no extension support gets a valid single-choice completion from a named
arena; `serve/` imports no arena orchestrator, because there is none.

**AR.12 — parity test.** One test asserting every field of `ArenaPolicy` is reachable from
the config block, a CLI flag, and the sidecar decoder — failing when a field is added to
one and not the others, the way `test_otel_bridge.py` fails when the event union drifts
from the bridge. *Acceptance:* adding a field to `ArenaPolicy` without wiring all three
surfaces fails the suite.

**AR.13 — arena over `run_tools` (§2.9).** N independent loops, per-candidate `max_rounds`,
final-turn selection, `rounds` and `tool_calls` on `Candidate`. *Acceptance:* candidates
that end in different round counts all complete; no candidate's messages contain another's
tool results; a candidate that exhausts `max_rounds` is a recorded failure rather than
sinking the arena; the call ceiling is not exceeded.

**AR.14 — run-scoped tool memoization (§2.8).** Single-flight dispatch in `ToolRegistry`,
canonical-argument keying, the four `memoize_tools` modes across all surfaces, hit counts
on `ArenaResult` and in telemetry. *Acceptance:* two candidates issuing byte-identical
calls produce one dispatch and two identical results; arguments differing only in key order
hit; arguments differing in *value* always miss; a raising tool is retried by the second
caller rather than served a memoized failure; a non-annotated tool under `read_only`
dispatches once per candidate; a plain `run_tools` call outside an arena memoizes nothing.

**AR.17 — account for candidates that failed.** A candidate whose route was exhausted has
no `Generation`, so it contributes nothing to `ArenaResult.usage` — yet its attempts cost
money. Merging only over successes produces a total that reads authoritative and understates
by exactly the failures, which is R-SL1's "false authority" in a new place. Compounding it,
`AttemptCompleted` is emitted only on success in this codebase (SPEND_LEDGER's recorded
`SL.6` deviation), so retry and repair spend is invisible to observers too and the ledger
cannot backfill it. *Acceptance:* an arena where one candidate fails after two paid attempts
reports those tokens somewhere a caller can find them, or reports the total as **unknown** —
never as a confident number that omits them; the choice between those two is made explicitly
in AR.1's amendment rather than falling out of the implementation.

**AR.16 — run-level spend guard.** An arena-aware entry point beside `_check_spend` that
takes the summed estimate for the whole run (candidates plus judge, and `N × max_rounds`
where the tool loop applies) and refuses **before any candidate dispatches**; per-candidate
checks become subordinate to it. Coordinate with whoever owns `capabilities/ledger.py` —
this is a change to their surface, not a private arena concern. *Acceptance:* an arena
whose candidates individually pass `max_request_usd` but whose total exceeds it is refused
with zero provider calls (the scripted provider records none); two concurrent arenas cannot
both pass a `max_total_usd` that only one of them fits; the error names the summed estimate
and the candidate count, not a single target's share.

**AR.15 — docs.** A concepts page: what arena is for, why consensus needs a schema, why the
candidates are always returned, the N× cost in the first paragraph, and the `N × max_rounds`
multiplier where the tool loop is discussed. Show the structured-consensus case first — it
is the one defensible without a judge — and show the same run in all three surfaces side by
side, which is the claim this plan is making.

## 4. Risks

- **R-AR1 — "best" is not measurable.** A synthesized answer can be worse than the best
  candidate, and a judge can pick wrong. Mitigate: candidates are always returned, the
  default strategy is deterministic, `synthesized` is additive rather than replacing, and
  the docs say all three in plain words.
- **R-AR2 — non-goal creep.** The next asks are a persistent leaderboard, routing weighted
  by past arena wins, `n`-as-arena in the sidecar, and mid-loop judging. Each is a different
  non-goal. Mitigate: AR.1 names them; `ArenaResult` is returned, never stored; the policy
  object holds no state across calls; §2.9's no-cross-candidate-influence rule is in the
  ADR, not just this plan.
- **R-AR3 — cost and rate pressure.** Arena multiplies spend and concurrent load by N, and
  by `N × max_rounds` over the tool loop. Mitigate: concurrency cap, summed preflight
  estimate, honest `--dry-run`, and `SpendPolicy` in place before arena ships (§5).
- **R-AR4 — false confidence from consensus.** Models sharing a training bias agree
  wrongly, and `agreement == 3` reads as certainty. Mitigate: `agreement` is a count, never
  a confidence score; the docs state that agreement measures convergence, not correctness.
- **R-AR5 — judge bias.** Position, verbosity, and brand. Mitigate: anonymization by
  default, documented position bias, and a judge whose own output is schema-validated.
- **R-AR6 — a policy object on the core request path.** Placement buys parity at the cost
  of a field every consumer now carries. Mitigate: `GenerationRequest.arena` is `None`
  unless asked, exactly as `cache` and `history` are; no adapter, no `Route`, and no
  provider sees it; an unconfigured client behaves precisely as it does today.
- **R-AR7 — the sidecar makes arena look free.** A named arena hides an N× bill behind one
  `model` string, and the client that sent it cannot see the fan-out. Mitigate: a working
  ceiling exists before exposure is possible (§5 decision 4 — the reservation fix is part of
  that gate, since a ceiling that leaks under concurrency is not one); the response
  extension always carries the candidate count and merged usage; `ArenaCompleted` fires
  server-side whether or not the client understands the extension.
- **R-AR8 — shipped ahead of demand (R5 restated, accepted).** No named consumer; built as
  a differentiator to be evaluated in the consumer apps. Mitigate: inert unless configured,
  so the cost of being wrong falls on whoever enables it. The plan states its own falsifier
  — if no consumer app finds a use within a release cycle of it being available, that is
  evidence to remove it, and arena must not be justified by usage it manufactured.
- **R-AR9 — N× side effects through the tool loop.** Three candidates each calling
  `create_work_item(...)` create three work items. This is a hazard of fanning out a *loop*
  rather than a call. Mitigate: memoization defaults to read-only tools only, so a
  non-idempotent tool is never silently collapsed *or* silently multiplied without the
  caller having chosen the fan-out; the docs state the multiplier where the tool loop and
  arena meet; `Candidate.tool_calls` makes the real dispatch count visible after the fact.

## 5. Decisions

**Resolved 2026-08-09 (user).**

1. **SDK, CLI, and sidecar are at capability parity** — by config file, CLI argument, or
   whatever else it takes. No developer should be pushed onto a surface they would rather
   not use because a capability exists only there. This settles placement: arena is
   client-layer policy (§2.1) with all four spellings of §2.6, and AR.12 makes parity a
   property the suite enforces rather than a promise the docs make. It supersedes an earlier
   draft that excluded the sidecar.
2. **Arena covers `run_tools`, not just single-shot generation** (§2.9), with the
   no-cross-candidate-influence rule as the governing boundary and §2.8 memoization as its
   companion.
3. **Both halves ship: deterministic strategies and the judge/synthesize call** (AR.5 and
   AR.7 together). Cost ceilings are `SpendPolicy`'s job — arena grows no ceiling of its
   own, so there is one mechanism for spend limits rather than two.
4. **SPEND_LEDGER lands first.** Since decision 3 makes `SpendPolicy` the only ceiling, and
   §2.9 raises the multiplier to `N × max_rounds`, arena cannot ship complete until that
   ceiling exists. This is a hard prerequisite, not a preference.

   **Status, re-audited 2026-08-09 (late).** SPEND_LEDGER shipped and its plan file has been
   deleted per the index's completed-plan convention: `capabilities/ledger.py`, `SpendPolicy`,
   `SpendLimitError`, pre-dispatch `_check_spend`
   ([_client/async_client.py:1906](../src/anyinfer/_client/async_client.py#L1906)),
   `client.spend()`, and CLI wiring all exist, and `SL.1`'s §2 clarification is committed.
   **The ceiling is nonetheless not sound under concurrency**, and this plan is now the only
   place that records it, because the finding was written into `SPEND_LEDGER.md` as `SL.9`
   shortly before that file was removed:

   > `ledger.py` holds a `threading.Lock` around its totals and has no reservation
   > mechanism. `_check_spend` compares `ledger.totals().cost + estimate` against
   > `max_total_usd`, and the ledger only moves when a request *completes*. Two concurrent
   > requests therefore both read the same pre-flight total and both pass. The fix is to
   > reserve the estimate at check time, release it on completion (replacing it with actual
   > usage), and compare `spent + reserved + estimate` under the existing lock. The test has
   > to dispatch **concurrently** — the sequential one passes either way, which is exactly
   > why it must not be the only one.

   So arena is not blocked by SPEND_LEDGER *existing*; it is blocked by SPEND_LEDGER being
   correct under fan-out. Both that reservation fix and `AR.16` are part of the prerequisite
   rather than follow-ons, and whoever picks arena up owns getting the fix scheduled with the
   ledger's author rather than routing around it.
5. **Core, not an extra** (§2.10).
6. **No named consumer, and that is deliberate** — arena is a differentiator whose value is
   to be discovered by trying it in the consumer apps. R-AR8 records the falsifier.
7. **Two adjacent parity gaps get their own plans** rather than being absorbed here:
   [SIDECAR_CORPUS_CONTEXT.md](SIDECAR_CORPUS_CONTEXT.md) and
   [MULTIMODAL_INPUTS.md](MULTIMODAL_INPUTS.md).

No decision is outstanding; `AR.1` is writable now, since SPEND_LEDGER's `SL.1`
clarification is committed and the two amendments can no longer give different answers about
the same §2 boundary. The ADR takes the next free number — the last in DESIGN.md §23 is
**ADR-013**, so Tier 3's start at **ADR-014**.

Three things gate the first line of code, and only the first is arena's own work:

| Gate | Owner | State |
|---|---|---|
| `AR.1` amendment written and reviewed | this plan | not started |
| Spend ceiling correct under concurrency (decision 4) | ledger author | **open, and now recorded only here** |
| `AR.17`'s accounting choice made in the amendment, not the implementation | this plan | not started |

The MCP annotation dependency is discharged, and `anyinfer.testing`'s `ScriptedProvider` is
the test vehicle throughout — both landed since this plan was first written.
