# Three small signal gaps left by the demo thread

**Scope:** three narrowly-scoped core additions, unrelated to each other except that all
three were surfaced by the same source (the UI_MODIFICATIONS demo-overhaul thread hitting a
place where the core does not yet report something it plausibly could) and are small enough
to land together: (1) a warmth/cold-start signal on `Measurement`, (2) a reasoning-aware
`verify()` probe, (3) provenance-tagged provider sampling defaults
(`default_temperature`/`default_top_p`) on `ModelCapabilities`, consumed by the demo's
existing "provider default" hint machinery. **Non-goal:** a default-reasoning-effort signal
— dropped from scope, see Decisions.

**Audience for this plan:** contributors editing the existing files directly. Code audit is
as of **2026-08-09**; re-verify before starting each task, especially against the
concurrently-active core session's diffs (see Coordination below).

**Authority:** DESIGN.md §7 (capability model — the `ModelCapabilities`/`Sourced` code
block this plan extends), ADR-005 (layered, provenance-tagged capability metadata — the
existing pattern this plan reuses rather than reinvents), §2 non-goals (never present an
estimated value as authoritative — governs items 2 and 3 directly).

**Governance intent:** no new ADR. Item 3 amends the `ModelCapabilities` code block already
documented in §7 (two additive `Sourced[float] | None` fields, same shape as
`context_window`/`max_output_tokens`) — that is a routine extension of ADR-005's existing
pattern, not a new architectural decision. Items 1 and 2 touch nothing documented in
DESIGN.md (`Measurement` and `verify()` are implementation-level, not core domain types) and
need no amendment.

**Origin:** `plans/UI_MODIFICATIONS.md`'s "Notes for the core maintenance thread" (items 1–2)
and its Gaps section item "No surface for provider sampling defaults" (item 3). That plan's
own scope was locked to `src/demo_app/`; these three are what it left for this thread. See
`plans/README.md`'s "UI_MODIFICATIONS is not this thread's work" note.

---

## Coordination

The working tree currently carries unrelated uncommitted changes from a concurrent session
(MCP support, spend ledger, `routing/limits.py`, additive fields on `ProviderDescriptor` and
`RateLimitHeaders` in `registry.py`/`types/capabilities.py`). Checked at plan-authoring time:
none of that diff touches `Measurement`, `verification.py`, `Feature`, `Sourced`, or
`ModelCapabilities.overlay()` — the three tasks below are clear of it. `registry.py` and
`types/capabilities.py` will receive edits from both threads in different fields; re-run
`git diff` on those two files immediately before editing to confirm the gap still holds.

## 1. Benchmark warmth signal

### Motivation

`Measurement` ([benchmark.py:143](../src/anyinfer/benchmark.py#L143)) has no field recording
whether the engine had the model resident when a run started. The demo works around this
with a ×2 warm/cold protocol (`Engine.benchmark_pair()`, Phase E4 of UI_MODIFICATIONS). A
real signal is better: Ollama's terminal response already reports `load_duration`, and the
adapter already captures it — it just isn't read on the benchmark path.

### Design

- `providers/ollama.py:451` already maps `load_duration` (wire) → `phases["model_load_ms"]`
  in `absorb_final()`. No adapter change needed for Ollama.
- Add `Measurement.model_load_ms: float | None = None` to the frozen dataclass
  ([benchmark.py:164](../src/anyinfer/benchmark.py#L164)), documented the same way as the
  existing rate fields: `None` means *not measured*, not zero.
- `measurement_from()` ([benchmark.py:281](../src/anyinfer/benchmark.py#L281)) gains a
  `model_load_ms: float | None = None` parameter, passed straight through (no derived
  arithmetic — unlike `prefill_tokens_per_s`, this is a direct provider-reported duration,
  not something computed from it).
- `AsyncClient.benchmark()` ([async_client.py:696](../src/anyinfer/_client/async_client.py#L696))
  reads `result.timing.phases.get("model_load_ms")` alongside the existing
  `phases.get("prefill_ms")` read and passes it through.
- Plain field, not `Sourced` — consistent with the rest of `Measurement`, which already
  represents "measured or not" via `None` rather than multi-source provenance (no
  `Measurement` field uses `Sourced` today).
- **llama.cpp supervised runtime:** open question, not blocking. `src/anyinfer/local/`
  needs a follow-up check for an equivalent signal (`llama-server` slot/timing state) before
  this task closes for that runtime; ship Ollama-only first if nothing surfaces there.
- `to_json()`/`from_json()` need no changes — both use `asdict`/keyword construction
  generically and pick up the new field automatically.
- CLI `benchmark` command inherits the field for free (it renders `Measurement` fields it
  already has, per AGENTS.md's CLI-delegates-to-core rule) — add it to whatever prints the
  measurement table.

### Tasks

**CS.1 — `Measurement.model_load_ms` + plumbing.** Field, `measurement_from()` parameter,
`AsyncClient.benchmark()` read, CLI `benchmark` output line. *Acceptance:* a test asserts a
scripted Ollama-shaped `load_duration` flows through to `Measurement.model_load_ms`; a test
asserts a provider with no such phase yields `None`, not `0.0`.

**CS.2 — demo consumption (optional follow-up, not required to close this task).** The
demo's `Engine.benchmark_pair()` ×2 protocol can stay as-is (it's still the only signal for
non-Ollama targets) but could prefer the real field when present. Not scheduled here —
`src/demo_app/` is a different workstream's paths per AGENTS.md; flag it back if wanted.

**CS.3 — llama.cpp signal check.** Grep `src/anyinfer/local/` for timing/slot state from
`llama-server`; either wire an equivalent `model_load_ms` phase or document explicitly that
this runtime has none.

---

## 2. Reasoning-aware `verify()`

### Motivation

`client.verify("ollama:qwen3:4b")` returns `ok=False`, detail `"the provider answered with
empty text"` ([verification.py:142](../src/anyinfer/verification.py#L142)) — the thinking
model spends its `VERIFY_MAX_OUTPUT_TOKENS=64` budget on reasoning tokens before it would
otherwise say `OK`. `gemma3:4b` (a grammar-mechanism, non-reasoning model) verifies fine. The
probe is not reasoning-aware at all today.

### Design

- `Feature.REASONING` already exists and already gates reasoning-effort wiring elsewhere
  (`_model_takes_reasoning`, [wire.py:98](../src/anyinfer/_client/wire.py#L98)) — reuse it as
  the gate here rather than inventing a second signal.
- In `AsyncClient.verify()` ([async_client.py:429](../src/anyinfer/_client/async_client.py#L429)),
  check the resolved target's capabilities for `Feature.REASONING` before building the
  `Sampling` for the probe request. If present, raise `max_output_tokens` for that one call —
  proposed starting point **4× `VERIFY_MAX_OUTPUT_TOKENS`** (256), to be confirmed empirically
  against `ollama:qwen3:4b` before landing (see Decisions — this needs a live check, not a
  guess).
- `VERIFY_MAX_OUTPUT_TOKENS` itself stays the published constant (`verification.py:60`) — the
  raise is local to the reasoning branch, not a global change, since a non-reasoning probe
  spending 256 tokens to say `OK` would be a regression in probe cost.
- `judge_reply()` ([verification.py:117](../src/anyinfer/verification.py#L117)) may also need
  to tolerate a reasoning preamble ahead of the structured `reply` field, depending on what
  the raised budget alone fixes — check whether the raised budget resolves it before changing
  grading logic; only touch `judge_reply()` if it doesn't.
- No new dataclass fields; `Verification` is unchanged.

### Tasks

**CS.4 — reasoning-aware probe budget.** Gate on `Feature.REASONING`, raise
`max_output_tokens` for that branch only. *Acceptance:* a scripted reasoning-model fixture
(long thinking preamble + trailing `OK`) passes verification; a scripted non-reasoning model
still uses the unmodified 64-token budget (test asserts the `Sampling` sent, not just the
outcome).

**CS.5 — live confirmation.** Run against real `ollama:qwen3:4b` per the plan's own
precedent (UI_MODIFICATIONS D3) to confirm 256 is enough headroom before landing; adjust the
constant if not.

---

## 3. Provider sampling defaults

### Motivation

`context_window` and `max_output_tokens` are provenance-tagged (`Sourced[int]`) on
`ModelCapabilities`; temperature/top-p have no equivalent, so the demo's sampling tooltips
say "provider default" with no number
([main_window.py:947-969](../src/demo_app/main_window.py#L947-L969)) rather than inventing
one. This is the intended behavior *today*, not a bug — but the gap is real: some providers
do document a stated default (e.g. OpenAI's API reference states `temperature` defaults to
`1`), and there is currently no honest way to surface that.

### Design

- Extend `ModelCapabilities` ([types/capabilities.py:224](../src/anyinfer/types/capabilities.py#L224))
  with `default_temperature: Sourced[float] | None = None` and
  `default_top_p: Sourced[float] | None = None` — same shape, same `None`-means-unknown
  convention as `context_window`/`max_output_tokens`.
  Add matching arms to `overlay()` ([capabilities.py:250](../src/anyinfer/types/capabilities.py#L250))
  via the existing `_stronger()` helper — no new merge logic needed.
- `conjunction()` ([capabilities.py:265](../src/anyinfer/types/capabilities.py#L265)) needs a
  decision: sampling defaults aren't a "tightest numeric bound" concept the way
  `context_window` is (min() doesn't mean anything for "which default temperature applies
  across candidate models"). Proposed: **omit both fields from the conjunction result**
  (`None`) rather than force a numeric reduction that doesn't correspond to reality — a
  delegating provider (Copilot's `"auto"`) reporting an invented "tightest" default would be
  exactly the kind of guess ADR-005 forbids.
  **Reasoning effort is explicitly out of scope** — see Decisions.
- **Provenance in practice:** almost always `"catalog"` — a descriptor's
  `default_capabilities` states what the provider's own docs say (per the Data sourcing
  decision below), not something discovered or probed at runtime. A provider whose docs
  don't state a default leaves both fields `None`; this is expected, not a gap to fill later.
- **Which providers get populated, and how:** only from each provider's official API
  documentation, and only where it states a literal default value. Cite the source (doc URL
  or exact doc wording) in a comment beside the value and in that provider's
  `contracts/<id>.md` snapshot, per AGENTS.md's "new wire behaviour updates the contract
  snapshot" convention — even though this isn't wire behavior, it's a factual claim about the
  provider that needs the same verifiability trail. Do not populate a value from general
  knowledge or inference; if the docs don't say it explicitly, leave `None`.

### Demo consumption (in scope for this plan, per the requester)

- `EngineBar` gains `default_temperature_detected()` / `default_top_p_detected()`, mirroring
  `max_output_tokens_detected()` ([engine_bar.py:387](../src/demo_app/widgets/engine_bar.py#L387))
  exactly — same discovered-model lookup pattern.
- `main_window._refresh_default_hints()` ([main_window.py:947](../src/demo_app/main_window.py#L947))
  extends to call both, following the existing `if detected is None: ... else: ...` shape
  already used for `max_output_tokens` — set `special_value_text`/tooltip with the real
  number and provenance when present, keep the current "provider default" + unreported-note
  tooltip when not. This directly closes the loop the plan doc's own note pointed at
  (`_refresh_default_hints()` named as "the single place that would consume it").
- `reasoning_effort` combo ([main_window.py:326](../src/demo_app/main_window.py#L326)) is
  **not** touched — no core field exists for it (Decisions: dropped from scope), so its
  tooltip keeps saying the value is provider-side and unreported.

### Tasks

**CS.6 — `ModelCapabilities` fields + `overlay()`/`conjunction()`.** *Acceptance:* a test
asserts `overlay()` picks the stronger-provenance sampling default field-by-field (mirroring
the existing `context_window` overlay test); a test asserts `conjunction()` returns `None`
for both fields across mixed candidates rather than a computed number.

**CS.7 — populate at least one provider, with citation.** Pick the provider(s) whose docs
most plainly state a default (OpenAI is the obvious first candidate: `temperature` default
`1`, per its API reference). Cite the source in-code and in `contracts/openai.md`.
*Acceptance:* a test asserts the descriptor's `default_capabilities` carries the value with
`provenance="catalog"`.

**CS.8 — demo hint wiring.** `EngineBar` accessors + `_refresh_default_hints()` extension,
per Demo consumption above. *Acceptance:* an existing-style demo test (mirroring whatever
covers `max_output_tokens_detected()` today) asserts the tooltip shows the real number when
the selected model's descriptor states one, and falls back to the current unreported-note
text otherwise.

---

## Testing

Each of CS.1, CS.4, CS.6 needs unit coverage in the module's existing test file
(`tests/test_benchmark.py`, `tests/test_verification.py` or wherever `verify()` is covered,
`tests/test_capabilities.py` or equivalent) before its live-check task (CS.3, CS.5) or
provider task (CS.7) is attempted — mirrors the plan-README's stated ordering (test kit
patterns before feature-specific harnesses). CS.8 is a `tests/demo_app/` change and stays
scoped to `src/demo_app/`/`tests/demo_app/` boundaries per AGENTS.md.

## Risks

- **R-CS1 — guessing a sampling default.** The entire point of item 3 is not to do this;
  the "only from provider docs, cite the source" rule in CS.7 is the guardrail. A future
  contributor adding a second provider must follow the same rule, not copy a plausible
  number from memory.
- **R-CS2 — reasoning probe budget wrong in either direction.** Too low and the fix doesn't
  fix qwen3:4b; too high and every reasoning-model verify costs meaningfully more per call.
  CS.5's live check exists specifically to catch this before landing, not after.
- **R-CS3 — concurrent-session collision.** Low risk per the Coordination section, but
  `registry.py`/`types/capabilities.py` are shared files — re-check `git diff` immediately
  before editing, not just at plan-authoring time.

## 4. Decisions (2026-08-09)

1. **Reasoning-effort default is dropped from scope.** It doesn't fit the `Sourced[float]`
   shape (`temperature`/`top_p` are numeric; reasoning effort is a provider-specific
   enum/string, or absent entirely), and providers rarely document a numeric or canonical
   default for it the way they do for temperature. Revisit only if a provider is found to
   state one plainly and a caller asks for it.
2. **Sampling defaults are populated only from explicit provider documentation, never
   inferred, probed, or guessed.** Matches the "never present an estimated value as
   authoritative" non-goal. A provider with no stated default stays `None` indefinitely —
   that is the correct, final state for it, not a gap awaiting more research.
3. **Demo wiring (CS.8) is in scope for this plan**, at the requester's direction, even
   though it touches `src/demo_app/` — a narrow, additive extension of code the
   UI_MODIFICATIONS plan already built and explicitly pointed back at this thread
   (`_refresh_default_hints()`), not a reopening of that plan's own scope.
4. **`Measurement.model_load_ms` is a plain optional field, not `Sourced`.** It's a direct
   measured duration from one request, not a multi-provenance capability estimate — consistent
   with every other `Measurement` field.
5. **`conjunction()` returns `None` for both new sampling-default fields** rather than a
   computed reduction, because no numeric reduction across candidate models' defaults is a
   real fact about a delegating provider's actual behavior.
