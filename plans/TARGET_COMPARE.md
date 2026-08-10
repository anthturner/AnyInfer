# `compare()` — portability preflight that spends nothing

**Scope:** `client.compare(request, targets=[...])`, returning a frozen `TargetComparison`
per target that reports what *this specific request* would become there — parameters
dropped, structured-output mechanism chosen and rungs rejected, cache placement available,
context fit against a provenance-tagged window, and a tri-state cost estimate — issuing
**zero** provider calls. **Goal:** turn the conformance matrix from a documentation table
into a runtime answer about the caller's own request. **Non-goal:** choosing a target.
`compare()` returns data; the router's policy is unchanged and never consults it.

**Audience for this plan:** contributors editing the existing files directly. Code audit is
as of **2026-08-09**; re-verify before starting each task.

**Authority:** DESIGN.md §2 (non-goals — **the load-balancing clause this plan
clarifies**), §7 (capability model), §9 (structured output), §11 (routing), §20 open
question 1 (budgeting, resolved), §24 (conformance matrix); ADR-003 (adapters translate),
ADR-005 (provenance), ADR-012 (cache placement).

**Governance intent: the §2 clarification must draw the line at *consumption*, not at
computation.** "No load balancing or cost/latency-adaptive routing" is a constraint on how
the router *chooses*, not on what the library may *report*. `compare()` computes facts and
hands them to a human or an application; the moment the client itself reads a comparison to
pick a target, that is adaptive routing and a reversal to argue, not a config option. This
is the same boundary the pacing clarification already drew — "the moment pacing informs
target selection it has become load balancing" — and the amendment should cite it and
extend it in one sentence rather than inventing a new formulation.

---

## 1. Motivation and evidence

**The README already makes the claim this plan implements.** "Portability is verified
behavior, not a provider count. Contract snapshots and a shared conformance suite document
what each adapter actually supports and surface dropped parameters or degraded mechanisms
instead of hiding them." Today that surfacing happens *during a call*, as
[`ParameterDropped`](../src/anyinfer/events/telemetry.py#L225) events a caller sees only
after committing to the request. Before the call there is a static matrix in DESIGN.md §24
and a docs page — organized by adapter, not by the caller's request.

The question a developer actually has is not "does Bedrock support tools" but **"what
happens to *my* request over there"** — my schema, my sampling, my 40k of context, my cache
marks. Nothing answers that.

**The decisive finding of the code audit: every input already exists as a pure function.**
`compare()` is assembly, not a subsystem:

| What it reports | Existing pure function | Network |
|---|---|---|
| parameters dropped + reason | [`dropped_parameters(request, descriptor, capabilities)`](../src/anyinfer/_client/wire.py#L127) | none |
| structured mechanism chosen | [`choose_mechanism(caps)`](../src/anyinfer/schema/mechanism.py#L28) | none |
| context fit / budget | [`build_context_budget`](../src/anyinfer/capabilities/budget.py#L124), [`check_context_fit`](../src/anyinfer/capabilities/gating.py#L65) | none |
| cache placement plan | `AsyncClient._plan_cache` ([async_client.py:1843](../src/anyinfer/_client/async_client.py#L1843)) | none |
| cost estimate | `AsyncClient._estimate_request_cost` ([async_client.py:1962](../src/anyinfer/_client/async_client.py#L1962)) | none |
| capabilities + provenance | [`capabilities_for`](../src/anyinfer/capabilities/assemble.py#L36) | cached; opt-in refresh |

`dropped_parameters` is the load-bearing one, and it is already core-side rather than
adapter-side — the client calls it at
[async_client.py:1632](../src/anyinfer/_client/async_client.py#L1632) and emits the events
itself. ADR-003 made that choice for a different reason, and this feature is the dividend:
because adapters only translate, the drop set is knowable without asking an adapter
anything.

So `compare()` is: resolve N targets, call six existing functions per target, return a
frozen record. No new dependency, no new policy, no wire traffic, no spend.

**It is also the cheap half of arena.** NEW_ARENA_MODE spends N calls to compare *outputs*.
`compare()` spends nothing to compare *behaviour*, and needs the same "resolve a request
against N targets without dispatching" plumbing. Building it first de-risks `AR.*` and
gives the arena plan a preflight to show alongside its results.

## 2. Shape

```python
comparisons = client.compare(request, targets=["anthropic:claude-sonnet-4-5",
                                               "ollama:qwen3:8b", "medium"])
for c in comparisons:
    print(c.target, c.fits, c.structured_mechanism, [d.parameter for d in c.dropped])
```

```
TargetComparison  (frozen, slots)
  requested / resolved     Target, ResolvedTarget | None
  resolvable               False + reason when the target is unknown or unconfigured
  fits                     bool | None    -- None when the window is unknown, never a guess
  budget                   ContextBudget  -- the existing type, unchanged
  structured_mechanism     Mechanism | None
  mechanism_rungs          ((Feature, bool, reason), ...)  -- the ladder, rung by rung
  dropped                  (DroppedParameter, ...)         -- parameter + reason
  cache                    CachePlacement | None
  cost                     CostEstimate | None             -- tri-state, Decimal
  capability_provenance    Mapping[str, Provenance]        -- per fact consumed
  notes                    (str, ...)
```

**Three rules keep it honest.**

*Unknown stays unknown.* A `default`-provenance window yields `fits=None`, exactly as the
gate refuses to fire on one ([gating.py](../src/anyinfer/capabilities/gating.py)). A
comparison that quietly presented an estimated window as a verdict would be the
`Sourced[T]`-collapsing mistake AGENTS.md warns about, in a new place.

*Comparison is not dispatch.* No adapter is constructed, no health probe runs, no discovery
request fires. `compare(..., refresh=True)` may repopulate discovered capabilities and is
the one path that touches the network — off by default, and it lists models rather than
generating.

*Ordering is caller-supplied.* Results come back in the order the caller passed them.
`compare()` does not sort by cost, latency, or fitness, because a ranked list is a
recommendation and a recommendation one line from `route=` is adaptive routing with extra
steps. The docs show `sorted(...)` in the caller's own code instead — the choice stays
visible and outside the library.

## 3. Tasks

**TC.1 — the §2 clarification, before any code.** One paragraph extending the pacing
clarification: reporting is not selecting; the client never consumes a comparison; a
built-in "pick the best" helper is a reversal to argue. *Acceptance:* DESIGN.md §2 amended
and cross-referenced from §11; no ADR number needed — this is a clarification of an
existing non-goal, matching how RATE_GOVERNANCE and SPEND_LEDGER were handled.

**TC.2 — `TargetComparison` and friends.** New `src/anyinfer/compare.py`; frozen,
`slots=True`, `to_dict()`. Reuses `ContextBudget`, `CostEstimate`, `Mechanism`, `Sourced`
rather than restating them. *Acceptance:* no new representation of a fact that already has
one.

**TC.3 — `AsyncClient.compare` + sync facade.** Async-first per ADR-002. Extracts the
comparison core from the existing preflight call sites so the gate and `compare()` cannot
disagree — **refactor to share, do not copy**. *Acceptance:* a test asserts that for a
request the gate rejects, `compare()` independently reports `fits=False` for the same
target; a mutation to the shared helper breaks both.

**TC.4 — mechanism ladder introspection.** `choose_mechanism` currently returns the winner;
`compare()` needs the rejected rungs and why. Extend it to optionally return the trail,
leaving the existing signature intact. *Acceptance:* a target with `JSON_MODE` but not
`JSON_SCHEMA` reports the `JSON_SCHEMA` rung rejected with a reason naming the missing
feature.

**TC.5 — unresolvable targets are data, not exceptions.** An unknown provider, a
missing credential, or a model absent from a configured provider comes back as
`resolvable=False` with a reason. *Acceptance:* comparing four targets where two are
unconfigured returns four records and raises nothing — a comparison that dies on its worst
entry is useless for the case it exists to serve.

**TC.6 — CLI: `anyinfer compare`.** Takes the same request-shaping flags as `anyinfer run`
(`--schema`, `--tool`, `--messages`, sampling, `--context-*`), plus `--target` repeated.
Prints a target-per-column table; `--json` emits the records. *Acceptance:* the flag set is
generated from the same source as `run`'s where they overlap, so the two cannot drift;
`--json` round-trips through `to_dict`/`from_dict`.

**TC.7 — sidecar parity.** Comparison is not a completion, so it is not `/v1/chat/
completions`. Add `POST /v1/anyinfer/compare` taking an OpenAI-shaped request body plus a
`targets` array. This is a new namespaced route rather than an extension, and TC.1 should
note that `/v1/anyinfer/*` is now a declared namespace for non-OpenAI verbs so the next one
does not re-litigate it. **No comparison logic in `serve/`.** *Acceptance:* `serve/` calls
`client.compare` and serializes; the OpenAI-shaped routes are untouched; the four §22
invariants still hold.

**TC.8 — parity test.** Every field of `TargetComparison` reachable from the SDK, the CLI,
and the sidecar route, in the shape `AR.12` establishes. *Acceptance:* one test, three
surfaces, identical records for identical input.

**TC.9 — docs.** A guide page framed as *"will my request survive a target change?"*, the
reference entry, and a runnable example against the scripted provider. Cross-link from the
conformance matrix page: the matrix says what an adapter supports, `compare()` says what
*your request* gets. State plainly that the library will not rank the results and why.

## 4. Risks

- **R-TC1 — "just pick the best one for me."** The single most likely feature request, and
  granting it crosses the §2 line. Mitigate: TC.1 names it as a reversal to argue; the docs
  show caller-side `sorted()` so the capability is obviously available *to the app* and
  obviously not in the library.
- **R-TC2 — false confidence.** `compare()` reports what the *core* will do. It cannot
  predict a provider-side refusal, a model-specific quirk outside the capability model, or
  a 400 nobody has catalogued. Mitigate: the docs say what it does not cover, and
  `verify()` remains the answer for "does this actually work" — one bounded real request,
  which is the honest complement.
- **R-TC3 — provenance laundering.** A table with a number in every cell reads as
  authoritative regardless of provenance. Mitigate: the CLI renderer marks `default`-sourced
  values distinctly and `fits=None` renders as `unknown`, never as a dash the eye reads as
  "fine".
- **R-TC4 — drift from the real path.** If `compare()` reimplements the gate, the two will
  disagree within two releases and the feature becomes a liar. Mitigate: TC.3's shared
  extraction is the requirement, and its test asserts agreement rather than trusting it.

## 5. Decisions

**Proposed 2026-08-09.** Cheap enough to be worth building on its own merits, and it
de-risks arena's target-resolution plumbing, so the recommended slot is **immediately
before NEW_ARENA_MODE**.

Open, and worth settling in TC.1:

1. **`/v1/anyinfer/compare` versus an extension.** A namespaced route is cleaner than
   overloading chat completions, but it is the first non-OpenAI verb on the sidecar and sets
   a precedent. Recommendation: **take it deliberately** and declare the namespace in TC.1
   — arena and manifest queries will both want one, and three ad-hoc answers is worse than
   one decision made now.
2. **Does `compare()` accept a `GenerationRequest` or the same kwargs as `generate()`?**
   Recommendation: both, via the existing `_build_request` path, so the comparison is
   provably about the request that would actually be sent rather than a hand-built lookalike.
3. **Relationship to `plan()`.** `anyinfer.context.plan()` dry-runs reduction strategies;
   `compare()` dry-runs targets. They compose (reduce, then compare) and should share
   vocabulary in the docs. Whether they should share a *type* is deferred — probably not,
   since one is corpus-shaped and one is target-shaped.
