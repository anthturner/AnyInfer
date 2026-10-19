# Unsupported rate-limit header diagnostic parity

Resume from the first unchecked box. This is a bounded POL.5 source follow-up under
ANYINFER_CSHARP_SDK_POLICIES.md. Owner c708; root owns decisions and all process gates.

## Settled behavior

Both public limiters already expose UnsupportedHeadersReason/unsupported_headers_reason.
For canonical openai-compat the descriptor has an empty header dialect. With active
limits and RespectHeaders true, neither runtime parses those undeclared provider headers;
configured concurrency/rpm/min-interval pacing still works. Python generation.py near881
emits ParameterDropped(request,target,"limits.respect_headers",reason) on the first
repair entry of each routed/retried attempt. Native currently never consumes its existing
UnsupportedHeadersReason property, so this typed diagnostic is missing.

Emit the same existing typed ParameterDropped from public generation at the corresponding
first-entry boundary, after admission/cache planning and before pacing/adapter entry. Use
the actual selected configured/injected limiter's existing reason. Emit once per outer
attempt, not again during schema repair. Do not emit on a pre-entry spend/context refusal
or on Frozen execution. Do not change limiter selection, header parsing, waits, permits,
timeouts, retry/repair policy, callback isolation or provider-only limiter observations.

## Ownership and checks

- Owner c708 also owns the concurrent unknown-price follow-up in the same GenerationCore
  file; serialize these changes within that owner. Own GenerationCore.cs only the bounded
  diagnostic placement/selected-limiter access, new
  src/csharp/AnyInfer.Tests/LimiterDiagnosticTests.cs and this leaf. An access seam change
  elsewhere requires a concrete source-backed root question before editing it.
- Use existing public ParameterDropped and public client/offline handler or descriptor
  fixtures. No observer/checker/corpus/schema changes, alternate parser or new API.
- Re-read files and preserve others. No author build/test/process/Git action.

- [x] **L.1** Add the source-aligned public diagnostic using the existing selected limiter
  and reason, with correct admission/entry/repair ordering. Gate: source trace to Python,
  scoped changes and SAVED/HELD without process execution.
- [x] **L.2** Add public controls for unsupported active header-respect diagnostic/order,
  declared headers or respectHeaders false silence, and no duplicate diagnostic on repair.
  Prove configured local pacing remains active through existing controls; do not fake a
  private queue witness. Re-read/tick owned boxes and NOTE deviations. Gate: static
  source/test trace and SAVED/HELD; root runs focused tests.
- [x] **L.2R** Add a retry control proving one `limits.respect_headers` diagnostic for each
  actual outer `AttemptStarted`; a failed first original entry followed by a successful
  second original entry must produce two diagnostics, while repair remains covered by L.2.
  Gate: SAVED/HELD test-only control; root runs the narrow diagnostic gate.
- [x] **L.3** Root cold-reviews and compiles/runs focused checks, then batches coherent full
  native/conformance and preserved profiles. Actual stamped traces must contain the real
  typed diagnostic; comparison must not waive or synthesize it.

> NOTE: L.1 emits the existing `ParameterDropped` after cache/wire construction and before
> entry pacing, guarded to PublicSdk and one outer retry attempt. L.2 covers the unsupported
> active dialect, declared/disabled silence, and repair non-duplication; root retains the
> focused pacing controls and all process gates.

> NOTE: L.2R keeps the diagnostic scoped to an outer retry attempt instead of hoisting it to
> generation scope: a retryable first adapter fault and a successful second original entry
> each require their own typed diagnostic.

> NOTE: L.2R locates events by their list positions rather than record value equality, since
> the two intentionally identical diagnostic records would otherwise both resolve to the
> first occurrence.

> NOTE: Root accepts L.3's bounded source gate: U/L source review and L.2R cold test closure
> are clean. The coherent source passes 679 native unit and 93 conformance tests, accounting
> 42 shared plus two observed native boundaries, and FrozenV0 102/102 DEVELOPMENT/UNRELEASED
> with tracked assets unchanged. Fresh independent traces each contain nine actual
> limits.respect_headers drops. After the full source gate, the new retry control required
> test-only iterator/analyzer mechanics and positional occurrence assertions; all four
> diagnostic tests now pass with no warnings/errors. Full workspace/independent comparison
> remain separate parent gates.
