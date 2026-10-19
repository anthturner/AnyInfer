# Unknown-price automatic spend admission parity

Resume from the first unchecked box. This is the bounded source follow-up discovered by
POL.5 under ANYINFER_CSHARP_SDK_POLICIES.md. Root owns decisions, shared gates and Git.
Owner c708; do not revert other agents' edits or run native processes.

## Settled behavior

Python authority is src/python/anyinfer/_client/spend.py `_estimate_request_cost`:
missing capabilities or pricing returns None before build_context_budget. Native
Core/GenerationCore.cs `EnforceSpend` currently always builds a budget and invokes the
configured estimator even when price is absent. With contextGate false, unknown/allow
must dispatch without an automatic spend estimate; unknown/refuse must throw the direct
SpendLimitException without invoking that estimator. With contextGate true, the later
context gate retains its independent estimator behavior. Public Budget remains a pure
estimation query and is unchanged.

Only skip the automatic spend-budget call when resolved capabilities/pricing are absent.
When pricing exists, preserve identity calibration, unpriced-part handling, estimator
source exception identity, ceiling equality, reservation replacement and unknown policy
selection. Do not change admission/event order, routing, cleanup, Frozen paths or output
profiles. Known-to-unknown reservation retention until terminal cleanup stays unchanged.

## Ownership and checks

- Own src/csharp/AnyInfer/Core/GenerationCore.cs only within EnforceSpend, new
  src/csharp/AnyInfer.Tests/UnknownSpendEstimationTests.cs, and this leaf.
- Use actual public AsyncClient/descriptors/adapters/SpendPolicy and an injected counting
  or throwing estimator; no alternate calculator, internal admission shortcut or observer
  changes. Read DESIGN.md and the parent plan before editing.
- Root alone runs compilation, tests, preservation and actual stamped comparison.

- [x] **U.1** Add the missing-price guard before automatic spend budgeting, leaving the
  existing unknown/allow/refuse branches and all priced behavior intact. Gate: source
  trace against Python and SAVED/HELD; no author process/Git action.
- [x] **U.2** Add public controls for missing pricing with context gate off under allow
  (success, zero estimator calls) and refuse (direct SpendLimitException, no Generate,
  zero estimator calls); with gate on, actual later context estimator behavior remains.
  Include a priced estimator sentinel identity control. Re-read/tick owned boxes and NOTE
  deviations. Gate: test/source trace and SAVED/HELD; root runs focused checks.
- [x] **U.3** Root obtains cold source review, compiles/runs focused tests, then batches
  the coherent full native/unit/conformance and preserved accounting/Frozen gates. Fresh
  independent profile observations must reflect the corrected call order without history
  normalization. Parent POL.5 and full/clean-revision acceptance remain separate.

> NOTE: U.1/U.2 are source-held. The allow controls use an active cumulative ceiling so the
> missing-pricing guard, rather than inactive-policy short-circuiting, proves the zero-call path.

> NOTE: Root accepts U.3's bounded source gate: cold review is clean; four unknown-price
> controls pass in the coherent 22-test focused batch, followed by 679 native unit and
> 93 conformance passes with zero compiler warnings/errors. Fresh accounting is 42 shared
> plus two observed native boundaries, and FrozenV0 is 102/102 DEVELOPMENT/UNRELEASED with
> tracked assets unchanged. Fresh independent Python/native handoff traces both capture
> two initial estimator inputs and one context-only unknown fallback input, retain the
> same known reservation until terminal cleanup, then release it. Raw terminal histories
> retain Python's separate manifest-estimation suffix. POL.5 comparison remains open.
