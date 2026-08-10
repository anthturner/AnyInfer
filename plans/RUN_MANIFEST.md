# The run manifest — one artifact that explains a call

**Scope:** a versioned, serializable `RunManifest` assembled from data the engine already
computes, returned from `Generation`, printed by `anyinfer run --trace`, carried by the
sidecar as an `anyinfer_manifest` response extension, and assertable as a golden file by
`anyinfer.testing`. **Goal:** make the decisions AnyInfer already takes — which target,
which structured-output mechanism, which cache placement, what got dropped, what got
reduced, what it cost, and on what provenance — a thing a developer can *hold*, diff, and
regress-test. **Non-goal:** a log format, an APM product, a durable store, or a second
source of truth about what happened.

**Audience for this plan:** contributors editing the existing files directly. Code audit is
as of **2026-08-09**; re-verify before starting each task.

---

## Status — 🚧 in progress, as of 2026-08-09

**Landed and green: RM.1 through RM.8, and RM.9's library half.** The whole suite passes
(`tests/test_manifest.py`, 26 cases) and `mkdocs build --strict` is clean.
`tests/test_workspace.py::TestBuild::test_all_builds_wheel_then_both_native_bundles` still
fails for the pre-existing broken `mkdocs.exe` shim, unrelated to this work. `ruff check
src/` reports only the 15 pre-existing `src/demo_app/` findings.

**Where to resume, in order:**

1. **RM.9's shipped example** — `docs/examples/` needs the golden-file example test that
   asserts an application's fallback-and-repair behaviour offline and is executed by
   `tests/test_docs_examples.py`. The helper, the `normalize()` rule, the
   `anyinfer_golden_manifest` fixture, and `--update-manifests` all exist; only the
   worked example is missing.
2. **RM.10 — docs**, none of which are written: a concepts page, the golden-file guide
   section (lead with it), the JSON Schema in the reference, and the `anyinfer_manifest`
   extension in the serve manual.
3. **Two acceptance criteria have no dedicated test**, though the code paths are landed
   and exercised indirectly: `anyinfer run --trace` / `--trace-json` (RM.5) wants a case in
   `tests/test_cli_run.py`, and the sidecar extension (RM.6) wants one in
   `tests/test_serve_app.py` asserting that a request *without* the field gets a
   byte-identical response and that the streaming frame lands before `[DONE]`.

**Files this landed in:** `src/anyinfer/manifest.py` (new, the whole subsystem),
`src/anyinfer/testing/manifests.py` (new), `src/anyinfer/testing/{__init__,plugin}.py`,
`src/anyinfer/_client/{async_client,sync_client}.py`, `src/anyinfer/types/results.py`,
`src/anyinfer/schema/mechanism.py` (`MECHANISM_LADDER` made public),
`src/anyinfer/serve/{app,openai_codec}.py`, `src/anyinfer/cli.py`,
`src/anyinfer/__init__.py`, `DESIGN.md` (§14 pointer, ADR-014), `tests/test_manifest.py`
(new).

### Deviations taken

- **`Generation.manifest` is a field, not a method.** Every other fact on `Generation` is
  a field — `attempts`, `usage`, `warnings` — and a record that is already assembled by
  the time the result exists has nothing to compute on access. `None` when manifests are
  off reads exactly as the plan's `manifest()` returning `None` would.
- **Payload opt-in is a client flag (`manifest_payloads=True`), not a `manifest(payloads=True)`
  call.** The manifest is built eagerly as the run proceeds, so the decision has to be
  known before the first event; and making it a client-level setting keeps it *independent*
  of observer payload opt-in, so a manifest cannot start carrying prompt text because some
  unrelated telemetry sink asked for it.
- **Payload strings live in their own `payloads` facet**, `None` unless asked for, rather
  than being nulled fields spread across the other facets. That makes "the default manifest
  is safe to paste into a public issue tracker" a structural property one assertion can
  check, instead of a promise about the contents of a dozen fields.
- **`--trace` reports a successful run only.** A failed one raises before a `Generation`
  exists, and the manifest is reachable only through a stream handle, which the buffered
  path does not have. Carrying the record on the exception is a real improvement and a
  wider change than this plan; the CLI's existing per-target failure trail covers the case
  meanwhile.
- **The builder is registered by `request_id` on the client and fed from `_emit`.** The
  two events that carry no `request_id` — a history compaction and the prefix-stability
  diagnostic — are handed the builder explicitly, because correlating them would mean
  guessing between concurrent runs. `AsyncClient.generate` now closes the routed generator
  explicitly (`contextlib.aclosing`), since returning out of an `async for` abandons it and
  the cleanup that unregisters the run would otherwise wait for a garbage collection.
- **`SyncStream` builds its `AsyncStream` on the calling thread** rather than inside the
  loop-side pump, so `SyncStream.manifest` can answer before the first event exists.
  Nothing in `AsyncClient.stream()` awaits and an async generator binds no loop until it is
  first iterated, so this is safe — and it is what makes a cancelled sync stream able to
  report on itself.

**Authority:** DESIGN.md §2 (goal 3, uniform observability), §7 (capability provenance),
§9 (structured output), §14 (telemetry and events), §22 (sidecar surface and its four
invariants), §26 (reduction metadata); ADR-005 (provenance), ADR-006 (**the ADR this plan
extends**), ADR-009 (the sidecar is a codec), ADR-012 (cache placement).

**Governance intent: ADR-006 makes typed in-process events *the* telemetry contract, and
this plan adds a second representation of the same facts. The amendment must say why that
is not a fork.** The answer is that the manifest is *derived*, never parallel: it is a
terminal projection of one request's event sequence plus the `Generation` it produced, with
no field that cannot be computed from those two. Events remain the contract for *observers
watching a system*; the manifest is the contract for *a developer holding one call*. The
ADR must state the derivation rule, and `RM.8` must enforce it with a test, or this becomes
exactly the fork the ADR exists to prevent.

---

## 1. Motivation and evidence

**Every fact is already computed. None of it is assembled.**

[`Generation`](../src/anyinfer/types/results.py#L207) carries `attempts`,
`structured_mechanism`, `cache_mechanism`, `repair_attempts`, `usage`, `timing`, and
`warnings`. [`events/telemetry.py`](../src/anyinfer/events/telemetry.py) defines twenty
typed events — `TargetResolved`, `RetryScheduled`, `FallbackTriggered`, `RepairAttempted`,
`ParameterDropped`, `ContextReduced`, `CachePlanned`, `RateLimitWaited`, `UsageEstimated`,
and the rest. The capability layer tags every window, price, and feature flag with
`catalog | discovered | probed | default`.

A developer who wants the whole story of one call today must subscribe an observer before
dispatch, correlate by `request_id`, and reimplement the join themselves. If they did not
subscribe *before* the call, the story is gone — `Generation` keeps the outcome, not the
reasoning.

**The sidecar cannot tell that story at all.** [`serve/app.py`](../src/anyinfer/serve/app.py)
exposes four routes (`chat_completions`, `models`, `health`, `unsupported`) and no
observability surface whatsoever. The codec knows two inbound extensions — `anyinfer_cache`
and `anyinfer_history` ([openai_codec.py:58,68](../src/anyinfer/serve/openai_codec.py#L58))
— and nothing outbound beyond the OpenAI response shape. A developer on the standalone
binary gets every provider, route, and mechanism, and *zero* insight into which ones fired.

**That is a parity defect, and the Tier 3 review missed it.** Arena, corpus context, and
multimodal inputs all close *request*-side gaps. The result side was never audited. The
parity requirement does not distinguish: a capability that exists only in Python pushes
developers onto a surface they did not choose.

**Why this is the differentiator and not plumbing.** A gateway can log a request and a
response, because that is all it owns. It cannot report *"`json_schema` was unavailable on
this target so the mechanism degraded to prompt injection, one repair attempt was spent,
and the context window backing that decision was a default, not a catalogue value"* —
because it does not make those decisions. AnyInfer does, and the manifest is the only
artifact in this product category that could exist. It is also the missing half of
TEST_KIT: a manifest is a **golden file**, and golden manifests let an application
regression-test its *inference behaviour* — route, mechanism, repair budget, reduction —
rather than the model's prose, which is untestable. Nobody else can offer that, because
nobody else owns the boundary.

## 2. Shape

One frozen dataclass tree in a new `src/anyinfer/manifest.py`, `format="1"`, mirroring the
context envelope's versioning rule (§26): the version bumps when an existing field's
meaning changes, not when a field is added, because a reader that ignores unknown keys
survives additions.

```
RunManifest
  format, anyinfer_version, request_id
  request     RequestFacet    role counts, message/char/token estimate, schema present +
                              schema digest, tool names, sampling, timeout, budgets.
                              Shape and fingerprints — never payloads.
  route       RouteFacet      requested Target, resolved target, the full chain considered,
                              why each was skipped (health, context window, content policy)
  capability  CapabilityFacet every Sourced[...] value the call actually consumed, each with
                              its provenance verbatim — never collapsed (AGENTS.md warning)
  attempts    (AttemptFacet,) per attempt: target, outcome, ErrorInfo, timing, retry reason,
                              the wait actually taken, whether pacing delayed it
  structured  SchemaFacet     mechanism requested vs chosen vs used, ladder rungs rejected
                              and why, repair attempts, validation errors per repair
  cache       CacheFacet      plan, marks placed, mechanism spelled, reported hit accounting
  context     ContextFacet    ContextReduced summaries: strategy, omissions, `complete`
  dropped     (Dropped,)      parameter + reason, from the events already emitted
  usage/cost  UsageFacet      tri-state cost, estimate vs actual, cache-split accounting
  timing      TimingFacet     TTFT, total, phases
  notes       (str,)          warnings and ProviderDiagnostic messages
```

**Payload policy follows ADR-006 exactly: content-free by default.** No prompt text, no
completion text, no tool arguments, no document contents. A schema is recorded as a SHA-256
digest plus its title, not its body. `manifest(payloads=True)` mirrors the existing
`subscribe(payloads=True)` opt-in and routes every string through
[`redaction.redact`](../src/anyinfer/redaction.py) on the way out. The default manifest must
be safe to paste into a public issue tracker, and `RM.7` asserts that.

**Assembly is a reducer over the event stream.** The client already dispatches every event
through `EventDispatcher`; a `ManifestBuilder` is an internal observer scoped to one
`request_id`, folded into the same path that builds `AttemptBuffer`. It costs one small
object per in-flight request and no extra work per event. `Generation.manifest()` returns
the finished record; when manifests are disabled (`AsyncClient(manifests=False)`) the
builder is never constructed and `manifest()` returns `None`.

**Rendering is separate from the record.** `anyinfer.manifest.render(m) -> str` produces the
human tree the CLI prints. The record is data; the renderer is presentation; the CLI owns
neither. This is the same split as `Reduction` and its envelope.

## 3. Tasks

- [x] **RM.1** — ADR-014 in DESIGN.md §23, pointer in §14
- [x] **RM.2** — `manifest.py`: types + `ManifestBuilder`
- [x] **RM.3** — `Generation.manifest` + client wiring (see deviations)
- [x] **RM.4** — provenance fidelity
- [x] **RM.5** — CLI `--trace` / `--trace-json` *(no dedicated CLI test yet)*
- [x] **RM.6** — sidecar `anyinfer_manifest` *(no dedicated sidecar test yet)*
- [x] **RM.7** — redaction and payload discipline
- [x] **RM.8** — the derivation test, over seven scripted scenarios
- [ ] **RM.9** — helper, `normalize()`, fixture and `--update-manifests` are landed; the
      shipped `docs/examples/` example test is **not**
- [ ] **RM.10** — docs: none written

**RM.1 — the ADR, before any code.** Extends ADR-006. States: the manifest is derived from
events and `Generation` and adds no new source of truth; it is content-free by default on
the same terms as events; it is not written anywhere by default; the sidecar carries it as
a codec projection, not as a telemetry channel. Names the derivation rule that `RM.8`
tests. *Acceptance:* DESIGN.md §23 gains the ADR and §14 gains a pointer; no user-facing
text cites the number.

**RM.2 — `manifest.py`: types + `ManifestBuilder`.** Frozen dataclasses, `slots=True`,
`to_dict()`/`from_dict()`, `format="1"`. Builder folds events by `request_id`.
*Acceptance:* a scripted-provider call with a forced fallback, a mechanism degradation, and
one repair produces a manifest naming all three; round-trips through `to_dict`/`from_dict`
unchanged.

**RM.3 — `Generation.manifest()` + client wiring.** Opt-out flag on `AsyncClient`/`Client`,
per-request override. *Acceptance:* `manifests=False` allocates no builder (assert via a
counter, not a timing); default-on adds no event subscription visible to callers.

**RM.4 — provenance fidelity.** Every `Sourced[T]` the call consumed appears with its
provenance intact. *Acceptance:* a probed window and a default window are distinguishable
in the manifest; a test asserts no field collapses `Sourced` to a bare value.

**RM.5 — CLI: `anyinfer run --trace` / `--trace-json`.** Human tree to stderr, JSON to
stdout or a path. Reuses `--json`'s existing conventions. *Acceptance:* `--trace-json`
output validates against the shipped JSON Schema; `--trace` renders a fallback + repair run
legibly in 80 columns.

**RM.6 — sidecar: `anyinfer_manifest`.** A response extension on the non-streaming body and
a terminal SSE frame before `[DONE]` on the streaming path. Off unless the request opts in,
so a stock OpenAI client sees a byte-identical response — ADR-009 invariant 1.
**No assembly logic in `serve/`**: it serializes `Generation.manifest()` and nothing else.
*Acceptance:* `serve/` imports only the manifest *types*; a stock client's response is
unchanged with the extension absent; the streaming frame is ignorable by a reader that does
not know it.

**RM.7 — redaction and payload discipline.** *Acceptance:* a run whose prompt, schema, tool
arguments, and provider error detail all contain a registered secret produces a default
manifest containing none of them, and a `payloads=True` manifest with every one redacted.
This test is the one that keeps the feature safe to recommend.

**RM.8 — the derivation test (the ADR's enforcement).** A run recorded through both a
subscribed observer and the manifest builder must agree: every attempt, drop, reduction,
and mechanism decision present in one is present in the other. *Acceptance:* a property
test over scripted scenarios — fallback chains, repair loops, rate-limit waits, context
reductions — asserting the two representations do not diverge.

**RM.9 — `anyinfer.testing.assert_manifest_matches`.** The golden-file helper, plus
`normalize()` to drop volatile fields (wall-clock, durations, request ids) so a golden is
stable. Ships a pytest fixture and an `--update-manifests` flag on the plugin.
*Acceptance:* a documented example test in `docs/examples/` that asserts an application's
fallback-and-repair behaviour offline, runs in CI, and fails loudly when the route changes.

**RM.10 — docs.** A concepts page (what the manifest is, and that it is derived), a guide
section on golden-file testing, the JSON Schema in the reference, and the sidecar extension
in the serve manual. Lead the guide with the golden-file workflow — it is the reason to
care, and the diagnostic use follows from it.

## 4. Risks

- **R-RM1 — it becomes a log format.** The moment someone asks for "manifests written to a
  directory with rotation", the library has grown a durable store, which §2 rules out.
  Mitigate: no I/O in the subsystem at all; the caller serializes. Named as out of scope in
  RM.1, not just here.
- **R-RM2 — payload leakage.** The manifest touches every string in a request. Mitigate:
  RM.7, and the default is content-free rather than opt-out redaction.
- **R-RM3 — golden brittleness.** Timings and ids make naive goldens fail every run, and a
  test suite that fails constantly gets deleted. Mitigate: `normalize()` is part of RM.9,
  not an afterthought; the shipped example uses it.
- **R-RM4 — drift from events.** Two representations diverge unless something forbids it.
  Mitigate: RM.8 is the whole answer, and it is why the ADR states a derivation rule rather
  than a description.
- **R-RM5 — the sidecar surface grows.** An outbound extension invites `/v1/anyinfer/runs`,
  a query API, retention. Mitigate: response-scoped only, stateless, named permanently out
  of scope in RM.1 — the same fence SIDECAR_CORPUS_CONTEXT puts around corpus storage.

## 5. Decisions

**Proposed 2026-08-09** on the strength of the surface audit above; the sidecar
observability gap is a confirmed parity defect regardless of whether the manifest is the
chosen fix.

Open, and worth settling in RM.1:

1. **Default on or off?** On costs one object per request and makes `--trace` work without
   a restart, which is most of the diagnostic value. Off is the more conservative reading of
   "nothing happens uninvited". Recommendation: **on**, because it allocates nothing
   observable and writes nothing — the invited/uninvited line in this codebase has always
   been about *spend and side effects*, and this has neither.
2. **Does `stream()` expose a manifest?** The record is terminal, so a streaming caller gets
   it only after the stream drains. Either the stream's final event carries it or the caller
   keeps a handle. Recommendation: a handle on the stream object, so cancellation still
   yields a partial manifest — which is exactly what a cancelled call most needs.
3. **Schema publication.** Shipping a JSON Schema makes the manifest an external contract
   earlier than 1.0 might want. Recommendation: ship it, marked pre-1.0 alongside the rest
   of the API, since a golden-file feature whose format is undocumented is not usable.
