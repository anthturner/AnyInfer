# Accounting v1 development profile

Status: development, not a released parity claim. This is separate from the frozen
core-generation-v0 release. The executable checklist is maintained by the coordinator;
this document defines observations and domain boundaries, not milestone completion.

## Authority and execution

Behavioral authority is Python source at
`199c3f833e568334b629edd7d89f41a3b76efe2a`, principally capabilities/pricing.py,
estimate.py, budget.py, gating.py and ledger.py; routing/limits.py; Usage and SpendPolicy
in types; and the real client generation path. C# runs production native code independently.
Neither runtime delegates accounting to the other. Verification may orchestrate both.

Inputs under tests/fixtures/accounting-v1 are shared data, with stable case IDs, literal
request/usage/pricing/provenance/policy/clock/action operands and no expected verdicts.
Native and Python observers consume the same data and emit their actual observations.
Production calculators, estimators, budgets, ledger/store and limiter APIs are the only
semantic implementations. Fixture consumers must not implement a second calculator,
serializer, router, formatter or baseline lookup.

This profile qualifies the representable native domain. Retrieval/tool-loop producers,
offered tools, rich multimodal inputs, automatic request admission and HTTP pacing wiring
are not implemented merely by qualifying pure helper vectors. They add real public-path
cases in their owning milestones. The released core-generation corpus is not extended or
rewritten to make these observations pass.

## Count and money domain

- Native counts are signed Int64, with checked arithmetic and conversion. Existing model
  capability windows and max-output fields remain Int32. Python unbounded integer results
  outside these ranges are explicit native-range controls, not claimed shared results.
  Arbitrary JSON facts retain their native BigInteger boundary.
- Money is Python Decimal / PeterO.Numbers EDecimal directly. Native parsing is exact,
  context-free; owned operations apply precision 28, HalfEven, Emin -999999, Emax 999999,
  unclamped exponents, trapping InvalidOperation, DivisionByZero and Overflow. Neither
  runtime may inherit a caller's mutable arithmetic context for these observations.
- Every arithmetic operation and enumeration order is observable; reassociation is not
  allowed. Tokens/rate cost evaluates `(count / 1000000) * rate`, not rate-first.
- A null value remains unknown. Numeric zero, signed/scaled zero and unknown are not
  interchangeable. Do not normalize strings to make cost/persistence mismatches disappear.
- Direct money values retain the permissive source domain, including negative/nonfinite
  facts. Source-owned catalog/policy comparisons retain their actual restrictions/traps;
  no blanket finite/nonnegative layer is added.

Money projection uses Python str(Decimal) and native invariant EDecimal.ToString. The
2026-10-18 qualification observes 28 jointly parsed text/state cases and 120 concurrent
text cases with no differences, including scaled/signed zeros, adjusted -6/-7 cutoffs,
28+ digits, raw exponents through +/-2147483647 and signed quiet/signaling NaNs/payloads.
This is corpus evidence, not proof over every possible vendor numeric representation.

There is an explicit input lexical difference: Python Decimal("1_000") accepts and renders
1000; context-free EDecimal.FromString rejects it. Canonical strings emitted by either
store never contain underscores. Native store decoding accepts its documented typed
EDecimal lexical domain; it does not emulate incidental Python int()/str() coercions or
promise every hand-authored Python Decimal spelling. Malformed/lexical/range controls are
reported separately from canonical shared persistence vectors, never normalized away.

## Observable semantics

### Usage and generation cost

Normalized fills an absent total only when both input/output are known; native sum overflow
throws instead of wrapping. An explicit total short-circuits that sum. Merge overlays
later non-null fields and empties the tool-use map, as Python does. Sum retains a dimension
only if every nonempty input reports it; money additions use the owned context.

ComputeCost requires trusted pricing plus input/output. Trusted provenance is catalog,
discovered, probed, override; default is untrusted. Price server-tool uses first in input
map enumeration order, returning unknown for an unpriced kind; compute output next; then
input + output + tools left to right. Cache read split uses input-read only when input>read,
otherwise input. Missing read rate prices full input; missing write rate skips its optional
supplement. WithCost preserves any non-null provider cost and copies all other Usage facts.
Embedding uses input then total fallback; rerank uses search units. These are pure helpers
until actual operation producers are implemented.

Final Generation usage is the winning adapter entry. A retry, fallback or schema repair
starts a fresh usage buffer; discarded entries are not added to the result. A completed
request's result, completion telemetry, manifest and ledger must agree on that final usage
and cost. Raw probes and cancelled/failed requests do not become completed-request charges.
No observation claims to reconstruct a provider invoice or all-wire aggregate.

### Estimates and budgets

Heuristic planning tokens are ceil(ceil(UTF8bytes/3)*multiplier), floor is
min(UTF8bytes//8,tokens), and each message adds four planning-only tokens. Finite positive
multiplier validation is source-backed. Message text is concatenated without separators.
Explicitly unsupported native nontext parts increment UnpricedParts without guessed text.
Schema inputs use insertion-order ASCII JSON with default Python separators; custom
estimator call order and exact strings are observed. No schema validation or dispatch is
performed by sizing. Boolean schema sizing is a native extension outside object-rooted
Python schema vectors. Envelope calibration changes only planning count, never floor.

Output reserve priority is explicit, request cap, then min(4096, known model cap). Headroom
is explicit or ceil(window*0.05) clamped to [256,8192]; unknown window has zero headroom.
Default-provenance windows can support planning, but never gate. Unpriced parts make
remaining/fits/estimated-cost unknown. The refusal gate compares only floor against a
trusted whole window, ignoring reserve/headroom; it is explicitly invoked in this phase.
Client Budget remains inert: no lifecycle reservation, credentials, adapter or telemetry.
Python's facade distinction is retained: async Budget/Spend after close are pure, whereas
sync Budget/Spend check closed state before estimator/work.

### Ledger, reservations and store

Only RequestCompleted records a request. RequestStarted metadata can label it; RequestFailed
clears correlation/reservation. Release removes a reservation only. Overall, per-target and
per-label snapshots are immutable, ordinal and first-seen ordered. Unknown requests are
counted alongside known spend rather than silently represented as free requests.

Reservation under one state lock evaluates: previous=get(id,0); reserved=sum(all,0)-previous;
spent=totals.Cost; compare spent+reserved+estimate to ceiling. Rejection retains the old
reservation; acceptance replaces it. Float approximation/reassociation is forbidden.
Native concurrency observations prove ceilings and release, not cross-process quotas.
Manual reservation against a pre-start partial-manifest ID is released even when the stream
closes without its first pull, with zero request-start event/adapter activity.

Store v1 has format_version=1 and insertion-ordered buckets. Cost is a decimal string,
never a JSON number. Missing/foreign/unreadable file yields empty; invalid buckets are
skipped; native typed/range rules are explicit. Only updating an existing bucket requires
currency equality. Updating does not refresh insertion age; beyond 512 buckets evict oldest.
Writing is explicit UTF-8/no BOM, indent 2, ASCII, no trailing newline, same-directory
temporary plus atomic replacement. Unique temporary names are a native strengthening over
Python's fixed .tmp. Atomic readability does not imply lossless concurrent read-modify-write
from threads on one instance or from multiple processes; callers serialize if needed.
Python Path.write_text uses the host newline: CRLF on Windows and LF on Unix. Native
Store matches that file behavior; its in-memory JSON formatter remains LF. Store byte
vectors compare on the same host platform. Observers read raw file bytes and decode UTF-8
without newline conversion or automatic BOM removal. A portable JSON value does not imply
byte-identical files across operating systems.

### Pacing state

Omitted limits mean no limiter; bare RateLimits enables header respect; disabling headers
with no bounds is inert. Validate actual source comparisons, not invented finite guards.
One limiter acquires concurrency before pacing and holds its lease until caller disposal.
Bucket capacity=max(1,RPM/60), refill=RPM/60, starts full. Interval/bucket/header delays
compete with source tuple ordering. Provider-header cumulative wait is capped at 60 seconds;
configured intervals are not. Remaining+reset enables a window; limit supplies reserve floor.
Partial header observations retain absent facts; reads do not consume or mutate windows.

Use virtual monotonic/UTC time and readiness to observe dispatch/waits, not real sleeps or
schedule-derived expected timings. Wait reports run outside state locks after waiting and
before the next recompute/dispatch consumption. A throwing callback releases a permit and
cannot invent dispatch spend. Observe callback faults do not erase already-observed headers.
Parent cancellation unwinds queued acquire/lease state. HTTP body ownership is a later real
transport case; these primitive observations alone do not prove it.

## Output and comparison rules

The observer envelope identifies profile version, runtime/source revision and stable case
ID. Required fields are profile="accounting-v1", runtime="python"/"csharp",
source_revision (lowercase 40-hex), source_dirty (bool), corpus_sha256 (lowercase 64-hex,
from exact parsed input bytes), and observations. Python records its executed source Git
identity. Native records compiled SDK AnyInferSourceRevision metadata and the observation
console's compiled AccountingSourceDirty metadata, never a runtime Git substitute.
Default orchestration builds with explicit source revision/dirty properties before run.
Missing/mismatched source or input stamps fail closed, including evidence-only --compare.
Revision plus a dirty flag does not identify every working-tree snapshot; dirty reports
remain development evidence, never a clean release or proof of all dirty source contents.

Case observations contain actual public values/action outcomes. Stable money strings,
nulls, integers, booleans, enum/provenance spellings, ordered action logs and independent
persisted bytes are compared directly. JSON map presentation order may be ignored only
when the contract declares logical map equality; enumeration/addition/persistence order is
not ignored. No rounding or decimal normalization is permitted in the verifier.
Terminal observer envelopes compare parsed JSON types and values, including integer versus
floating-point versus boolean distinctions. Whitespace and fixed/scientific float notation
in that envelope are presentation, not byte-equality operands. Money strings and embedded
raw Store bytes retain their exact lexical comparison; this does not normalize those values.

Native error names may map to their declared Python semantic counterparts: configured
argument/range errors, typed ContextLength/SpendLimit errors and decimal trap causes. Use
structured error types/fields or public trap codes, never diagnostic text matching. Caller
cancellation and original source identity have dedicated native causal controls rather than
cross-language object equality. Native-only lexical/range/unsupported-producer controls
must be labelled as such; their exclusions cannot turn a missing shared case into a pass.

Dynamic request IDs and wall/monotonic instants are not equality operands across executions.
Observe correlation/order from actual events and verify the relationships independently;
never replace the real request ID before checking all associated facts. Concurrent tests
compare invariants and complete result multisets only when order is explicitly unspecified.

The verifier fails on missing/extra IDs, errors from an observer, or any declared shared
projection mismatch. Reports include corpus/source hashes and exact executable revision.
No released acceptance report is generated from an uncommitted executable, and no existing
frozen release/report is overwritten. Future profile changes require explicit contract and
case review rather than editing expected data to fit output.
