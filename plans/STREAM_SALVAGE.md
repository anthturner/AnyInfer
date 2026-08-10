# Mid-stream salvage — resuming a generation that died in flight

**Scope:** an opt-in router behaviour that, when a stream fails after partial content has
arrived, resumes from the salvaged text via an assistant-prefill continuation instead of
discarding it and re-generating from zero. **Goal:** stop throwing away the expensive half
of a long generation because the connection dropped at 85%. **Non-goal:** salvaging
structured output, tool calls, or reasoning traces — the feasibility work below shows all
three are unrecoverable by this mechanism, and the plan treats that as a permanent boundary
rather than a later milestone.

**Audience for this plan:** contributors editing the existing files directly. Code audit is
as of **2026-08-09**; the feasibility probe was run **2026-08-09** against a live Ollama
0.32.6 on `127.0.0.1:11434`. Re-verify both before starting each task.

**Authority:** DESIGN.md §2 (non-goals), §6 (streaming event model), §9 (structured
output), §11 (routing), §20 open question 3 (cancellation semantics); ADR-001 (event-stream
primitive), ADR-003 (adapters translate — salvage is router policy, never adapter control
flow), ADR-005 (provenance).

**Governance intent: this is the first feature that makes a `Generation` an artifact of
more than one provider call, and the ADR must own that plainly.** Every other retry in this
codebase discards the failed attempt and asks again; the caller receives one model's
uninterrupted answer. A salvaged result is *stitched* — a prefix from attempt 1 and a
continuation from attempt 2, joined at a boundary the library chose. That is a different
kind of object, and the ADR must (a) require it be opt-in, (b) require it be labelled on
the result and in the event stream so no caller is surprised, and (c) enumerate the refusal
cases as contract rather than as implementation detail. If salvage is ever on by default,
the library has silently changed what "one answer" means.

---

## 1. Feasibility: what the probe established

Run 2026-08-09 against Ollama 0.32.6, model `gemma3:4b`, greedy settings
(`temperature=0, seed=42, top_k=1`), plus `qwen3:4b` for the reasoning case. Four probe
rounds; the scripts are reproduced by `SS.2` as a permanent harness.

### 1.1 The partial always survives, and a crash looks like a clean close

A stream was cut after 30 chunks two ways: a graceful close, and a raw socket `RST` via
`SO_LINGER(1, 0)` — the process-crash shape. Both left the client holding **the identical
165 characters**, and in both cases the partial was a true prefix of the uninterrupted
output. There is no torn-frame or partial-UTF-8 hazard at the NDJSON layer to design
around; whatever the client accumulated is intact and correct.

### 1.2 Greedy decoding is not reproducible, so "matches the uninterrupted run" is the wrong bar

Five uninterrupted greedy runs of the same prompt:

| | run 0 | run 1 | run 2 | run 3 | run 4 |
|---|---|---|---|---|---|
| chars | 1143 | 1141 | 1141 | 1141 | 1141 |

Pairwise agreement prefixes: `978, 978, 978, 978, 1143, 1143, 1143, 1143, 1143, 1143` —
six of ten pairs byte-identical, four diverging at 978 characters (86% through). **The
engine does not reproduce itself at temperature 0.** Any acceptance criterion of the form
"the stitched output equals what an uninterrupted run would have produced" is therefore
unmeetable and must not be written. The correct bar is *the seam is clean and the result is
coherent*, which is what the rest of this section measures.

### 1.3 The seam is the whole engineering problem, and the fix is a two-line rule

A dropped connection does not wait for a word boundary. Three prefill strategies at five
cut points, `V1` raw partial, `V2` drop the trailing partial word but keep the whitespace,
`V3` drop the trailing partial word **and** strip the trailing whitespace:

| cut | partial ends | V1 raw | V2 trim+space | V3 trim+strip |
|---|---|---|---|---|
| 60 | `…organized da` | `daťabase` — non-ASCII splice | `organized 2D structure` | `organized data structure` |
| 137 | `…table. Imagi` | `Imagiine` | `table. ⏎⏎Imagine` | `table. Imagine a phone book` |
| 165 | `…instead of` | `instead of flipping` | `instead ⏎⏎of flipping` | `instead of flipping` |
| 300 | `…works similar` | `similarily,` | `works ⏎⏎on a similar` | `works similarly,` |
| 512 | `…database automa` | `automaically` | `database irst checks` | `database automatically` |
| | **clean seams** | **1 / 5** | **1 / 5** | **5 / 5** |

`V1` welds fragments into non-words whenever the cut lands mid-word, because the prefill is
re-tokenized and the model continues from a boundary that does not align with the cut.
`V2` removes that corruption and introduces a worse one: ending a prefill on a trailing
space is a known-pathological tokenizer position — in BPE the space belongs to the
*following* token — and four of five `V2` resumes opened with a spurious paragraph break or
ate a leading character (`database irst checks`).

`V3` is clean at every cut point, and in four of five it reconstructed the original word
exactly (`data structure`, `Imagine`, `similarly`, `automatically`). **The rule is: trim
back past any trailing partial token, then `rstrip()`.** That is the entire mitigation, and
it converts the feature from unusable to correct.

*Honest note on method:* the probe's automated seam checker scored `V2` at 2/5 because it
only detected welded words and leading newlines. It passed `database irst checks`, which is
plainly broken. The table above reports the by-eye score. `SS.2`'s harness must assert on
the seam directly rather than on heuristics that a human then has to re-check.

### 1.4 Salvage is worthless unless the resume budget is capped

Same model, a 600-token essay, connection dropped at 85%:

| | output tokens generated | wall clock | vs. full retry |
|---|---|---|---|
| uninterrupted | 600 | 4.05 s | — |
| resume, uncapped `num_predict` | 344 | 2.53 s | **43%** avoided |
| resume, capped at `600 − 509 salvaged` | 91 | 1.00 s | **85%** avoided |

Given the prefill, the model does not know how much of its budget is already spent: handed
a fresh 600-token allowance it wrote another 344 and produced a *longer* answer than
requested (~853 tokens stitched). Capping the continuation at the original budget minus the
salvaged estimate restores the expected economics and the expected length. **The resume
must inherit the remaining budget, not the original one.**

The salvaged text is re-sent as input — 539 prompt tokens, 65 ms. Cheap in time and
cheaper per token than output on every hosted provider, but **not free**, and the docs must
say so rather than implying salvage is pure profit.

### 1.5 Three cases are unrecoverable, permanently

**Structured output cannot be salvaged by continuation.** A 619-character JSON body was
truncated at 309 characters and resumed with the schema still attached. The model restarted
the object from `{`, producing `<partial><a complete second object>` — unparseable.
Grammar-constrained decoding has no resume: the constraint state machine restarts at its
initial state and the prefill does not restore it. Since §9 guarantees that a
schema-carrying request returns a validated result, salvage must **refuse** any request
carrying a schema and fall through to the ordinary retry path. §1.6 tests the obvious way
around this and refuses it too, on stronger grounds.

**An interrupted reasoning trace salvages nothing.** `qwen3:4b`, 40 chunks in: 158
characters of `thinking`, **zero** characters of visible content. The expensive part had
been paid for and was entirely unrecoverable — the thinking channel cannot be prefilled
back, and there was no visible text to prefill instead. For thinking models, salvage is
inert until visible content begins and must not be attempted before then.

**Tool calls follow the structured-output argument** and are refused on the same grounds.
This was not probed directly; the plan treats it as refused-by-default and `SS.9` records
that it is an assumption, not a measurement.

### 1.6 Re-deriving structured output instead of continuing it — tested, and refused

If a truncated JSON body cannot be *continued*, the natural next idea is to stop trying and
**re-derive** it: take what arrived, and convert it into a schema-valid object with a second
call. Probed 2026-08-09 with a six-field, all-required schema. It decomposes into three
distinct mechanisms with three different answers.

**Where a truncation actually lands.** Grammar-constrained generation emits properties in
schema order, so a cut always loses a *suffix* of the fields. At every depth tested the
casualty was the same one:

| cut | fields that arrived | required fields missing |
|---|---|---|
| 25% | name, founded_year, member_cities, primary_goods | `decline_reason`, `summary` |
| 50% | + decline_reason | `summary` |
| 75% | + decline_reason | `summary` |
| 90% | + decline_reason | `summary` |
| 97% | + decline_reason | `summary` |

Even at **97%** — 777 of 802 characters — the object is still missing a required field,
because the field being written when the stream died is by definition incomplete. This is
structural, not bad luck.

**Deterministic structural completion is honest but rarely sufficient.** Closing the open
string and containers with no model call at all produced parseable JSON at every cut point,
with every surviving value byte-identical to the baseline. It fabricates nothing, because it
adds nothing. But it can only produce a *schema-valid* object when every required field
precedes the cut — which, for an all-required schema, is almost never. Its real value is
therefore not recovery; see `SS.12`.

**Two claims from the first pass on this are retracted.** The first pass handed the
fragment back *without the original question* and *with the schema attached*, then reported
that the model fabricated the missing field despite being told not to. Both halves of that
setup were the error. With `summary` in `required`, grammar-constrained decoding **cannot
terminate the object without emitting one** — the instruction was unfollowable, not ignored
— and with the question withheld the model had no legitimate source to draw on even if it
could have. It also blamed the prose→JSON conversion for turning `1230` into `1300` without
checking what the prose said. Re-probed 2026-08-09 with those controls in place; the
corrected results follow, and they change the conclusion.

**Conversion is lossless for structured values and lossy only for long free text.**
Rendering the baseline object to labelled text and converting it straight back, with nothing
else varying, round-tripped **five of six fields byte-identically** — including
`founded_year: 1230` and `["Lübeck", "Hamburg", "Bremen", "Cologne"]` exactly. Only
`summary`, a multi-sentence string, came back rephrased. Scalars, integers, and lists
survive a prose round trip; long prose fields get re-summarized.

**The `1230 → 1300` claim was wrong and is withdrawn.** The control shows the unconstrained
prose answer mentions **no year at all** and names **none** of the four cities. The
conversion did not corrupt those values; the prose never contained them, and the
grammar then forced a required `integer` and a required array into existence. That is a
sharper finding than the one it replaces: **the fabrication risk is not a property of any
particular pipeline — it is what happens whenever a required field has no source in that
call's input.**

**With the original question in context, both recovery shapes preserve everything and
generate the missing field legitimately.** Two variants at a 55% cut, where `name`,
`founded_year`, `member_cities`, `primary_goods`, and `decline_reason` had arrived and
`summary` had not:

| | output tokens | the five salvaged fields | `summary` |
|---|---|---|---|
| full retry (baseline) | 186 | regenerated | regenerated |
| **round trip** — fragment → prose → unconstrained continuation → convert | 319 | **all five preserved exactly** | generated by a continuation that had the question |
| **single step** — fragment + question → schema | 175 | **all five preserved exactly** | generated with the question in context |

Both work. The round trip's continuation even picked up the labelled rendering's pattern and
opened with `**Summary:**` on its own. Neither invented anything, because neither was asked
to produce a field it had no basis for.

**And that is exactly why it still should not ship.** The condition that makes recovery
honest — *the recovery call receives the same inputs the original had* — is also the
condition that destroys its economics. Unlike prose salvage, where the continuation emits
only the missing tail, a structured recovery **must re-emit the entire object** at the
conversion step regardless of how much survived. So the output-token saving is bounded by
the cost of *deriving* the content rather than *serialising* it: 175 versus 186 tokens here,
a 6% difference that is inside the noise, and the round trip is 72% *more* expensive than
simply asking again. Meanwhile the input cost of carrying the original context is the same
as a retry's, because it is the same context.

The two properties are coupled, and neither ordering escapes it:

- **Carry the original context** → honest, and you have paid a retry's input cost to save
  almost no output tokens.
- **Omit it to save the input cost** → the grammar forces every required field into
  existence with no source, and the result is a fluent, schema-valid fabrication that
  passes every check this library performs.

The second is the worst failure mode available here: a wrong answer that is
indistinguishable from a right one. The first is a retry with extra steps. **Refused in
SS.1 on the coupling, not on a fabrication measurement** — the honest version is merely
pointless, and the version worth having is unsafe. This reasoning is what SS.1 must record,
because the naive version of the idea looks good precisely until both controls are applied.

The genuine residue is `SS.12`: the salvaged fields *are* recoverable exactly, and reporting
them to the caller costs nothing and invents nothing.

**Two-phase generation remains a real pattern with a real price, and it is the caller's
call.** Splitting a long structured request into an unconstrained prose phase and a short
conversion phase makes the expensive half salvageable by the `V3` path — the drop lands in
prose, which §1.3 recovers cleanly. The price is now measured properly: not conversion
corruption, but that **unconstrained prose omits what the schema will later require**, and
the conversion then has to invent it. An application choosing this pattern must ask for the
required facts explicitly in phase 1, or it has moved the fabrication rather than removed
it. That is a documented pattern with a documented trap (`SS.11`), never a transformation
the router performs on a caller's behalf.

### 1.7 Constraints that span the seam — the hypothesis, and why it did not hold

A reasonable worry: some requests carry structure a resume cannot honour. An enumeration has
a *count*. "List five things, then compare them" has a *predecessor*. "Exactly 100 words" is
a *global budget*. If the continuation cannot see the rule, it should break it. Probed
2026-08-09; **the worry is largely unfounded, and the reason is instructive.**

| probe | request | cut | stitched result |
|---|---|---|---|
| D1 | "exactly 5 facts, numbered 1–5" | 30% (2 items held) | 5 items, numbered 1–5, no duplicates |
| D1 | same | 55% (3 items held) | 5 items — continuation closed item 3 and opened `4.` correctly |
| D1 | same | 80% | 5 items, sequential, clean |
| D3 | "…then compare them" | 35% | 5 items **and** the comparison paragraph; the continuation emitted its own `**Paragraph Comparing and Co…**` heading |
| D2 | same | 88%, mid-comparison | comparison continued coherently, closing with "all five facts…" |
| D4 | "exactly 100 words" | 60% | 98 words uninterrupted → 101 uncapped, 95 budget-capped |

**Why it holds: the prefill carries prior output forward, so any dependency on prior output
is satisfied by construction.** The original messages are re-sent, so the *rule* is present;
the salvaged text is re-sent, so *progress against the rule* is present. The model recounts
from what it can see. This is the same property that makes the seam work at all, applied to
semantics instead of tokens.

**Which relocates the real boundary, and sharpens it.** Salvage is unsafe precisely when the
generation depended on state that is in **neither** the original messages **nor** the
salvaged visible text. That set is small, and — importantly — it is *structurally
enumerable* rather than a matter of prompt meaning:

1. the reasoning channel, dropped and un-prefillable (§1.5, measured);
2. grammar or tool-call state, which does not resume (§1.5, measured);
3. provider-side hidden state such as a resumed session.

**All three are things the core already knows about a response** — whether reasoning deltas
arrived, whether a schema or tools were attached, whether a session handle applies. So the
detection the hypothesis asks for is available, and it is available *without inspecting the
prompt*. That matters: classifying a request by reading its text would be a semantic
heuristic, it would be wrong on the cases that matter most, and prompt inspection sits
against the §2 prompt-templating boundary. `SS.7`'s refusal checks already cover this set;
what this probe changes is the *justification* — they are not conservative guesses, they are
the complete list.

*Limits of this evidence, stated plainly:* one model, one engine, three prompt shapes, three
cut points. D3's cut landed after the enumeration was already complete, so "cut mid-list in
a dependent request" is untested. D4's two-word overshoot is within the noise of a model
that missed its own 100-word target by two words uninterrupted. `SS.2` should carry D1–D4 as
live-mode cases so the claim widens with the evidence rather than ahead of it.

### 1.8 Verdict

**Real, worth building, and narrower than it first appears.** It applies to plain text
generation with no schema and no active reasoning channel, using a `V3`-trimmed prefill and
a budget-capped continuation. Within that slice the probe shows clean seams at every cut
point tested and 85% of output tokens avoided on a late drop. Outside it, the honest answer
is a full retry, and the library should give that answer loudly rather than stitching
something it cannot stand behind.

The structured-output boundary holds, on two independent grounds. Continuation fails on
grammar state (§1.5). And re-derivation, which §1.6 shows *does* work correctly under
controls, is caught in a coupling: it is honest only when the recovery call carries the
original context, and once it does it saves 6% of output tokens against a plain retry —
while the cheaper variant that drops the context produces schema-valid fabrications no
check in this library can catch. The one honest and worthwhile thing to do with a partial
structured answer is hand it to the caller and let them decide — `SS.12`.

**The largest open risk is portability, and it is now known to be worse than assumed.**
Everything above is one engine (Ollama 0.32.6) and one model family. Assistant-prefill
continuation is a provider capability, not a universal one — and the trend is against it:
**Anthropic removed last-assistant-turn prefill from its entire current model line** (400 on
Opus 5, Sonnet 5, Fable 5, and the 4.6–4.8 family; surviving only on legacy models), and
OpenAI's Responses API never had an equivalent — its contract snapshot records a cacheable
prompt prefix, which is an unrelated mechanism
([contracts/openai.md:26](../contracts/openai.md#L26)). That leaves local engines and the
OpenAI-compatible long tail, whose behaviour is per-server and untested. `SS.0` is the gate;
`SS.3` makes the capability a declared per-descriptor flag with a contract line per adapter,
so a provider that cannot continue an assistant turn is never asked to.

## 2. Shape

Salvage is **router policy**, in `routing/`, beside retry and fallback. Adapters gain
nothing but a descriptor flag — ADR-003 holds.

```python
client = ai.Client(providers, salvage=ai.Salvage(max_resumes=1, min_salvaged_tokens=256))
```

```
Salvage  (frozen, slots)          -- absent by default; absence means today's behaviour
  max_resumes            int = 1     resumes per request, not per attempt
  min_salvaged_tokens    int = 256   below this, a retry is simpler and about as cheap
  require_boundary       bool = True the V3 trim; False is for experiments, not production
```

Result and event surface:

- `Generation.salvaged: SalvageRecord | None` — resume count, salvaged/regenerated token
  split, and **`spans`**: for each contiguous run of the answer, which attempt produced it,
  its character range, and how many characters the `V3` trim discarded at the seam before
  it. This is `Sourced[T]` applied to text — every part of a stitched answer says where it
  came from, as fact rather than as an estimate. It is deliberately **not** a confidence
  score; see §5.
- A new `StreamSalvaged` telemetry event, content-free like every other, carrying the same
  counts.
- The run manifest (see [RUN_MANIFEST.md](RUN_MANIFEST.md)) gains a salvage facet. A
  stitched answer is exactly the kind of thing a developer must be able to see after the
  fact, and these two plans should land in that order for that reason.

Refusal is explicit and observable: when salvage is configured but declined — schema
present, tools present, reasoning-only content so far, provider cannot prefill, below
`min_salvaged_tokens` — the router emits `ParameterDropped("salvage", reason)` and retries
normally. Silence here would be the worst outcome, since the caller would believe salvage
was protecting them.

## 3. Tasks

**SS.0 — the go/no-go spike, before the ADR and before anything else.** Every measurement in
§1 is Ollama over loopback, and **a dropped connection over loopback is rare** — the failure
this feature exists to recover from happens on hosted providers over real networks. So the
question that decides whether to build it is one §1 never touched: *does assistant-prefill
continuation work on hosted providers?*

**Partially answered already, and the answer is bad. Anthropic removed last-assistant-turn
prefill across its entire current line: it returns HTTP 400 on Claude Opus 5, Sonnet 5,
Fable 5, Opus 4.8, Opus 4.7, Opus 4.6, and Sonnet 4.6.** It survives only on legacy models
(Opus 4.5, Sonnet 4.5, Haiku 4.5, and older). Anthropic's own documented replacement for
this plan's exact use case — *"continuing an interrupted response"* — is to move the
continuation into a **user** turn (*"Your previous response was interrupted and ended with
[last text]. Continue from there."*). That is strategy **C** from §1.3, the one the probe
measured as producing a visibly degraded seam.

So the hosted picture as it stands:

| Provider | Trailing assistant turn | Source |
|---|---|---|
| Ollama (native `/api/chat` and `/v1`) | **continues**, byte-identical across both dialects | measured 2026-08-09 (§1.3, §1.7) |
| Anthropic, current models | **400 — removed** | vendor docs, 2026-08-09; unverified against the live API |
| Anthropic, legacy models | continues | vendor docs; not a basis to build on |
| OpenAI Responses API | no equivalent | vendor docs |
| OpenAI-compatible presets (Groq, Together, vLLM, TGI…) | **unknown** — each runs its own templating server; the §1.8 dialect experiment shows the wire shape imposes nothing either way | untested |

**The revised spike is therefore a different question**, and it is the one worth spending
credentials on: *on a current frontier model, is the user-turn continuation Anthropic
documents good enough?* §1.3 measured strategy C on a 4B local model, where it was clearly
worse than prefill; a frontier model may follow *"continue from exactly where this stops"*
cleanly. If it does, salvage has a second mechanism and the plan widens. If it seams as
badly there as it did locally, Anthropic is out and the remaining candidates are
self-hosted stacks and the OpenAI-compatible long tail. Run §1.3's five cut points through
strategy C against Claude Sonnet 5 or Opus 5, and score the seams by the same rule.

*Decision rule, fixed in advance so the result is not rationalised after the fact:*

- **Three or more hosted providers continue cleanly** (by either mechanism) → build the plan
  as written.
- **Only one or two** → do not build the router feature. Land `SS.12` alone (it is
  independent and useful), and record the spike result here so the question is closed rather
  than reopened annually.

*Acceptance:* the table above completed with real dates and a live-API check of the
Anthropic row (documentation is not a measurement), the user-turn-continuation seam scores,
an entry in each adapter's contract snapshot, and a written go or no-go. Nothing else in
this plan starts until this task answers. Cost is a handful of tiny requests.

**SS.1 — the ADR, after SS.0 says go.** A salvaged `Generation` is stitched from more than one
call; opt-in; labelled on the result and in the events; refusal cases are contract, not
implementation. Enumerates §1.5's three refusals and states that structured output is
permanently out of scope — **for two independent reasons, both measured**: grammar state
does not resume (§1.5), and re-derivation is caught in the honesty/economics coupling of
§1.6. The ADR must record that coupling **as an argument, not as a verdict**, and must state
plainly that re-derivation *works* when the recovery call carries the original context — it
is refused for being pointless in that form and unsafe in the cheaper one, not for being
broken. A future contributor will propose this in good faith, will test the version that
works, and will be right that it works; the ADR has to answer the version that works.
*Acceptance:* DESIGN.md §23 gains the ADR (number taken in landing order), §11
cross-references it; no ADR number appears in user-facing text.

**SS.2 — the feasibility harness, landed.** Port the probe rounds into `tests/` as a
live-mode-only suite plus a scripted-provider offline equivalent. Assert on the seam
directly — no welded word, no injected paragraph break, prefix preserved verbatim — rather
than on the heuristics §1.3 flagged as unreliable. Carry §1.7's D1–D4 constraint cases too,
and add the one that probe missed: **a cut genuinely mid-enumeration in a request with a
dependent tail.** *Acceptance:* the offline suite runs in CI with no credentials; the live
suite reproduces the §1.3 and §1.7 tables against a real Ollama and is skipped without one.

**SS.3 — `ProviderDescriptor.supports_assistant_prefill` + contract verification.** A
declared capability, defaulting **False**, turned on only for adapters where a contract line
records the verification and its date. Ollama is the one adapter this plan may enable, on
the evidence above. *Acceptance:* every enabled adapter has a `contracts/<id>.md` entry with
a real `last_verified` date; no adapter is enabled on inference from documentation alone.

**SS.4 — the trim rule as a tested pure function.** `routing/salvage.py::safe_prefix(text)
-> tuple[str, str]` implementing `V3`. Pure, no I/O, exhaustively tested — mid-word,
mid-multi-byte-character, trailing whitespace runs, text that is entirely one token,
CJK and other scripts without spaces. *Acceptance:* the §1.3 cut points are regression
cases; a text with no whitespace at all declines to salvage rather than returning an empty
prefix.

**SS.5 — router integration.** Salvage sits in the attempt loop in
[`_routed_stream`](../src/anyinfer/_client/async_client.py#L1266), consuming the partial
already accumulated in `AttemptBuffer`. Interacts correctly with fallback (a salvaged prefix
belongs to *its* target and must not be prefilled into a different provider after a
fallback — the same rule `session_applies` already enforces) and with `max_resumes`.
*Acceptance:* a scripted provider that fails mid-stream twice produces one salvage, one
ordinary retry, and an attempt trail that shows both.

**SS.6 — budget inheritance.** The continuation's `max_tokens` is the original budget minus
the salvaged estimate, floored at a small minimum. *Acceptance:* the §1.4 measurement is a
test — an uncapped resume must fail it, so the regression cannot silently return.

**SS.7 — refusals are events, and the refusal set is complete rather than cautious.** Each
decline reason emits and is asserted. §1.7 establishes *why* this set and no more: salvage
is unsafe exactly when the continuation's inputs are not reconstructible from the original
messages plus the salvaged text, and the three cases where that holds — reasoning channel,
grammar/tool state, provider-side session state — are all detectable from the response the
core already has, with no prompt inspection. *Acceptance:* a schema-carrying request with
salvage configured emits the refusal and returns a validated result by the ordinary path; a
comment records the completeness argument so the set is not "hardened" later by adding
semantic guesses about prompt content.

**SS.8 — streaming semantics.** A salvaged stream must not re-emit the salvaged prefix to a
caller who already received it, and must emit a `StreamSalvaged` marker at the seam so a
consumer reconstructing text does not double it. This is the §22 invariant-2 question
(event-stream sufficiency for chunk reconstruction) and it must be answered explicitly.
*Acceptance:* a consumer that concatenates `TextDelta`s across a salvaged stream gets the
stitched text exactly once; the sidecar's SSE reconstruction is byte-correct.

**SS.9 — tool-call refusal, recorded as an assumption.** Refuse and document; note in the
plan record that §1.5's tool-call claim is reasoned from the structured-output result, not
measured. *Acceptance:* a comment and a test naming it as an assumption to revisit.

**SS.10 — parity.** `Salvage` reachable from the config file, an `anyinfer run --salvage*`
flag, and an `anyinfer_salvage` sidecar extension, per `AR.12`'s four-spellings pattern.

**SS.11 — docs.** A guide section that leads with the boundary, not the benefit: what
salvage does, the three things it refuses and why, that the salvaged text is re-billed as
input, and that a stitched answer is not the answer an uninterrupted call would have given.
Include the §1.3 table — it is the most convincing evidence the feature is engineered
rather than hopeful. **Plus a short "if you need a long structured generation to survive a
drop" pattern**: split it into an unconstrained prose phase (salvageable) and a short
conversion phase (cheap to retry), with §1.6's real trap stated — unconstrained prose omits
what the schema will later require, and the constrained conversion then invents it, so the
required facts must be asked for explicitly in phase 1. Presented as the caller's
architectural choice, with the trade-off stated, and explicitly *not* something the library
will do for them.

**SS.12 — `SchemaValidationError.partial` — the honest half of the re-shape idea.** When a
structured request fails after partial content arrived, attach the deterministically
completed fragment (§1.6) and the list of required fields that never arrived. Pure, no model
call, no added information — it reports what was received and what was not. *Acceptance:*
the §1.6 cut table is a regression test; every surviving value is byte-identical to what the
provider sent; a fragment with no complete member yields `partial=None` rather than a
guess; the field list distinguishes "arrived" from "missing" and never infers a value for
the latter. This is small, safe, and useful on its own — an application can decide to accept
five of six fields, and the library never decides that for it.

## 4. Risks

- **R-SS1 — a stitched answer is presented as a whole one.** The core hazard. Mitigate:
  `Generation.salvaged`, the telemetry event, the manifest facet, and opt-in. A caller who
  never configured salvage can never receive a stitched result.
- **R-SS2 — portability is one engine deep.** §1.8. Mitigate: SS.3's default-False
  capability flag; no adapter enabled without a dated contract line.
- **R-SS3 — quality regression at the seam on untested models.** Five cut points on one 4B
  model is thin evidence for a general claim. Mitigate: SS.2's live suite is the widening
  mechanism; the guide states the evidence base honestly rather than claiming generality.
- **R-SS4 — economics inverted on short generations.** Re-sending a large salvaged prefix as
  input to save a handful of output tokens can cost more than a retry. Mitigate:
  `min_salvaged_tokens` defaults conservatively; the docs give the arithmetic.
- **R-SS5 — interaction with the prompt cache.** A resume changes the prompt (it now carries
  an assistant turn), which may invalidate a cached prefix and interacts with
  `_check_prefix_stability` ([async_client.py:1977](../src/anyinfer/_client/async_client.py#L1977)).
  Unexamined. Mitigate: SS.5 must measure it, and if a resume routinely busts the cache the
  economics in §1.4 need restating.
- **R-SS6 — scope creep toward "continue this for me".** Salvage is failure recovery; a
  general continuation API is a prompt-construction feature and a §2 non-goal. Mitigate:
  named out of scope in SS.1.
- **R-SS7 — the re-shape idea returns, and half-tested it looks like a win.** "Just ask the
  model to fix up the truncated JSON" is obvious and reasonable, and §1.6 shows the careful
  version genuinely preserves every salvaged field. Someone will build it, measure it on a
  self-contained prompt, and see it work. The trap is that the safe configuration saves
  ~6% and the configuration that saves anything real produces schema-valid fabrications
  nothing here can detect. Mitigate: SS.1 records the *coupling* rather than a
  fabrication anecdote, and concedes up front that the mechanism works — a rejection that
  overstates its case is the one that gets overturned by the first contributor who tests it
  properly.
- **R-SS9 — a confidence score gets added later.** The §5 refusal will be revisited, most
  likely as "just expose the logprobs" or "just sample it twice". Mitigate: the refusal is
  argued in SS.1 on *what the signals measure* rather than on effort, and `spans` ships as
  the honest alternative so the need it comes from is already met. A score added on top of
  `spans` would also be strictly worse than `spans`, since it replaces a fact with a guess.
- **R-SS8 — `SS.12`'s partial mistaken for an answer.** A partial object that parses invites
  a caller to use it without checking which fields are real. Mitigate: it is attached to an
  *error*, never returned as a `Generation`; the missing-field list is required reading in
  the type's docstring; and it is never schema-validated, because passing validation is
  exactly the wrong signal to send about it.

## 5. Decisions

**Feasibility settled 2026-08-09 by measurement:** build it, narrowly. The `V3` trim rule
and budget inheritance are non-negotiable requirements, not optimizations — without either,
the feature is actively harmful (`V1` corrupts text; an uncapped resume saves 43% instead of
85% and overruns the requested length).

**Structured-output recovery settled 2026-08-09 by measurement (user proposal), after one
retraction.** The suggestion was to stop continuing the JSON and instead re-derive it —
render what survived to prose, continue in prose, convert the paragraph back. The first
probe of it was set up badly: it withheld the original question *and* attached the schema,
so the grammar forced a required field into existence with no source, and the resulting
"it fabricates" conclusion was an artifact. It also blamed the conversion for a wrong year
the prose had never contained.

Re-probed with controls, **the proposed pipeline works**: all five salvaged fields came back
byte-identical, including the exact city list, and the missing field was generated by a
continuation that had the original question. The refusal therefore rests on the coupling in
§1.6, not on fabrication — honest recovery costs a retry's input to save 6% of its output,
and the cheap variant fabricates undetectably. Deterministic structural completion is the
honest residue and becomes `SS.12`. Two-phase generation stays an application pattern in
`SS.11`, with its real trap documented: unconstrained prose omits what the schema will later
require, so the facts have to be asked for explicitly in phase 1.

**Ordering: last of the Tier 4 three, and gated on `SS.0`.** RUN_MANIFEST and TARGET_COMPARE
are both cheap, safe, and differentiating on their own. This one is none of those things: it
puts new control flow in the attempt loop — the most safety-critical code in the library —
for a feature that fires rarely, and its value is entirely contingent on a portability fact
nobody has checked. Build the other two first regardless of how `SS.0` lands.

**A note for whoever reads this next and feels the plan is a catalogue of failures.** It
reads that way because four *extensions* were probed to destruction: structured continuation
(§1.5), structured re-derivation (§1.6), seam-spanning constraints (§1.7, which turned out
fine), and confidence scoring (§5). The core mechanism passed every test it was given —
5/5 clean seams, 85% of output tokens recovered, constraints intact across the seam. Those
are not competing results; they are a boundary drawn tightly around something that works.
The honest risk is `SS.0`, and it is a different question from any of them.

**No confidence score on a salvage. Settled 2026-08-09; the reasoning belongs in SS.1
because it will be asked again.** The request was for a standardized score separating
plausible salvages from fabricated ones. It is refused, for three reasons that compound:

- **It would be an estimate wearing a number's clothes.** A `confidence: 0.87` on a
  stitched answer is exactly the "estimated value presented as authoritative" that ADR-005
  exists to forbid and that AGENTS.md names as a standing trap. It would also become the
  most-trusted field in the result *because* it looks quantitative, which is the worst
  possible outcome for a value nothing can substantiate.
- **No available signal measures what the score would claim to measure.** Token logprobs
  measure fluency, and fabrications are characteristically high-confidence; most providers
  do not expose them at all, so the field would carry `default` provenance on most targets
  and the tri-state rule would render it unusable anyway. Seam perplexity detects "the model
  lost the thread", not "the model is confidently wrong".
- **The one technique that does work costs more than the thing it protects.** Sampling the
  continuation k times and scoring agreement is real and effective — and it is k× the price
  of the salvage, which was itself a saving over a retry. This is the §1.6 coupling for the
  third time: any veracity mechanism affordable enough to be worth adding is too weak to
  trust, and any mechanism strong enough to trust costs more than simply asking again and
  getting a clean answer instead of a scored one.

**What ships instead is `spans` (§2): provenance, not confidence.** "Characters 0–2680 came
verbatim from attempt 1; 6 characters were discarded at a word boundary; 2680–3155 came from
attempt 2" is a fact the library can state without qualification, it is the same discipline
`Sourced[T]` applies everywhere else, and it lets a caller apply whatever policy they want —
including refusing stitched answers outright. A caller who genuinely needs veracity has two
honest options that already exist and price themselves openly: a full retry, or arena's
judge call.

Open, and worth settling in SS.1:

1. **Should `max_resumes` default above 1?** A flapping connection could salvage repeatedly,
   compounding seams and drifting from any single coherent answer. Recommendation: **1**,
   with the seam count on the record so a caller raising it can see the cost.
2. **Does salvage apply to non-streaming `generate()`?** Non-streaming is the drained stream
   (ADR-001), so the partial exists internally even when the caller sees none. Salvaging it
   is defensible and invisible. Recommendation: **yes**, on the same opt-in — refusing would
   make the two paths differ for no reason a caller could articulate.
3. **`min_salvaged_tokens` default.** 256 is a guess shaped by the 4B measurements.
   Recommendation: hold it until SS.2's live suite covers a hosted provider with real
   input/output pricing, then set it from the arithmetic rather than from intuition.
