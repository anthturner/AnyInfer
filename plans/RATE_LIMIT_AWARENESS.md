# Relay rate-limit awareness — pacing, admission control, and backoff headers

*Drafted 2026-08-25. Scope: `src/anyinfer-confidential/` (Relay, its ASGI wrapper) plus two
narrow, explicitly-flagged seams in core. Status: proposed, not started.*

This is an internal plan; ADR references are fine here and must not leak into anything
under `docs/` (AGENTS.md's no-ADR-identifiers rule).

---

## 0. Why, in five findings

Each of these is a fact about the code today, not a projection:

1. **Core's rate limiter is structurally inert behind the Relay.**
   `Relay._forward` ([relay.py](../src/anyinfer-confidential/src/anyinfer_confidential/relay.py))
   constructs a fresh `ai.AsyncClient([provider_settings])` per call and `aclose()`s it in
   the `finally`. `RateLimiter` state — token bucket, header-observed windows, the
   concurrency semaphore — lives per provider instance inside that client
   (`_client/providers.py:132`, `routing/limits.py`). Every forward call therefore paces
   against an empty limiter and discards the learned windows on return. The connection
   pool dies with it too: one TLS handshake per request.
2. **There is no resource isolation between tenants.** `RelayRegistry` isolates *routing*
   structurally, but one tenant's `asyncio.gather` fan-out can consume the whole process —
   the noisy-neighbour gap in "hosted Relay ops."
3. **`Relay.handle` can block the event loop — but only via one configuration.**
   `TemplateVault.render` is synchronous inside the coroutine (`sealed_template.py:207`),
   and it was *measured* before this plan sized anything (method in Appendix A): a
   realistic ~4 KB template renders in **p50 0.17 ms / p99 0.23 ms** — license Ed25519
   verify plus AES-GCM decrypt is sub-millisecond blocking, which the loop tolerates.
   The single real hazard is a **network-backed `revocation_checker`**: one synchronous
   HTTP round-trip stalls every in-flight request. So the fix is scoped to that path,
   not a blanket thread offload (a `to_thread` hop costs about as much as the render
   itself and would roughly halve the crypto path's ~6,000 renders/s/thread ceiling).
4. **The ASGI wrapper has no backpressure vocabulary.**
   [app.py](../src/anyinfer-confidential/src/anyinfer_confidential/app.py) maps every
   `RelayError` to 404 — including "mode='forward' requires provider_settings", which is
   a 400. There is no 429, no `Retry-After`, no rate-limit header on any response.
5. **Core already owns every parsing/emitting primitive we need.** Declared header
   dialects (`types/capabilities.py:113` `RateLimitHeaders`), three-spelling reset
   parsing (`routing/limits.py:68` `parse_reset_seconds`), `Retry-After` parsing that
   deliberately refuses HTTP-dates (`providers/http.py:100` `parse_retry_after`),
   `retry_after_s` as a structured error field (`errors.py`), and payload-free
   `RateLimitWaited` / `RateLimitObserved` telemetry events. The plan reuses all of them
   and invents no parallel vocabulary.

## 1. Invariants — what every phase must preserve

These are load-bearing promises in module docstrings and DESIGN.md §30; violating one is
a product change, not an implementation detail.

- **I1 — Zero retention stays structural.** No request or response body, slot value,
  assembled prompt, or credential is ever written to a durable store or held past the
  request that carried it. Everything this plan caches is *timing metadata*: token-bucket
  levels, window resets, latency samples, in-flight counts. The relay module docstring's
  claim ("nothing here opens a file or a database connection") must remain literally true.
- **I2 — Credentials are never stored.** `provider_settings` arrives fresh per call and
  dies with the call. Pooled pacing state is keyed by a **salted digest** of the key
  identity (salt generated per process at startup, held only in memory), never by the key
  itself, and the digest is never logged or emitted. The raw key continues through
  `register_secret` for redaction exactly as today.
- **I3 — Tenant isolation extends to emitted numbers.** `RelayRegistry.resolve`
  deliberately returns an identical error for "no such route" and "another tenant's
  route" so probes cannot enumerate tenants. A `Retry-After` or `RateLimit-Remaining`
  computed from *global* state would reopen that hole as a metadata side channel: tenant
  A polls in a loop and reads tenant B's traffic volume off the header. **Every number
  returned to a caller derives only from that tenant's own state** (per-tenant queue
  depth, per-`(tenant, target)` latency samples) — except provider-quota numbers in
  forward mode, which belong to the caller's own BYOK key and leak nothing.
- **I4 — `Relay` stays deployment-agnostic and HTTP-free.** Throttling surfaces from
  `Relay` as typed errors/fields; only `app.py` translates them to status codes and
  headers. An embedder without ASGI gets the same information as data.
- **I5 — Core's pacing philosophy is not quietly changed.** `routing/limits.py` states:
  no cross-process state, no quota the provider didn't state, never influences target
  choice, and shared state "would be a visible design change rather than a config
  option." The core seam in Phase 1 is exactly such a visible change — one explicit
  injection parameter — and everything else stays in the confidential package. Nothing
  in this plan does load balancing, and retries stay in core's router (never stacked at
  the Relay layer).
- **I6 — Nothing runs unless configured.** Mirroring `RateLimits`' inert-by-default
  contract: a Relay with no pacing pool and no admission limits configured dispatches
  exactly as today — no permit, no delay, no bookkeeping.
- **I7 — No new mandatory dependencies.** Everything here needs only stdlib +
  what the `relay` extra already carries (starlette). Ceilings reuse
  `MAX_HEADER_WAIT_S`; no new clamp constants without the same style of justification.

## 2. Phases

Ordered by payoff-per-line; each phase lands independently and `workspace check` gates
each one. Phase 0 and 1 are worth doing even if nothing later ever lands.

### Phase 0 — stop blocking the event loop; measure before sizing

*Prerequisite, not rate limiting — but every capacity number chosen later is wrong if
this isn't done first.*

- [ ] In `Relay.handle`, move the render off the loop:
      `prompt = await asyncio.to_thread(self._vault.render, route.template, **slots)`.
      `TemplateVault` needs a review for thread-safety first: `_last_revocation_ok` is
      the one piece of mutable state; guard it with a `threading.Lock` or make the
      offload serialize through a single worker.
- [ ] Add a benchmark note (not a test) recording assemble-mode throughput before/after
      on one core, so admission defaults in Phase 2 are picked from a measurement.
- [ ] Tests: concurrent `handle()` calls make progress while one render is slow
      (inject a slow `revocation_checker`); revocation state stays consistent under
      concurrency.

**Exit criterion:** a deliberately slow revocation check no longer stalls unrelated
in-flight requests.

### Phase 1 — pooled pacing state across forward calls

*The biggest win; fixes finding 1 without touching credential lifetime.*

**Core seam (small, explicit, flagged):** `AsyncClient` gains an optional
`limiters: Mapping[str, RateLimiter] | None = None` constructor parameter that pre-seeds
`self._limiters` (`_client/providers.py:132`). When supplied for a provider id, the
client wraps the transport with the *given* limiter instead of building a fresh one
(`_build wiring at providers.py:356-372`). This is the "visible design change" limits.py
reserves — one parameter, default `None`, zero behaviour change when absent. It also
keeps limiter semantics honest: limits.py says one limiter belongs to "an account at a
provider", and pooling by credential digest is precisely that identity.

**Confidential-package side:** new module
`src/anyinfer-confidential/src/anyinfer_confidential/pacing.py`:

```python
@dataclass(frozen=True, slots=True)
class PacingKey:
    credential_digest: str   # salted SHA-256 of key identity; salt is process-lifetime
    provider_id: str

class PacingPool:
    """Holds RateLimiter instances and latency samples across Relay calls.

    Timing metadata only — never a credential, prompt, slot value, or response.
    Bounded LRU (default ~256 keys) so an attacker cycling keys cannot grow it
    without bound; eviction just forgets pacing history, never correctness.
    """
    def limiter_for(self, key: PacingKey, limits: RateLimits, dialect: RateLimitHeaders) -> RateLimiter: ...
    def record_latency(self, tenant_id: str, target: str, service_s: float) -> None: ...
    def service_quantile(self, tenant_id: str, target: str) -> float | None: ...
```

- [ ] `Relay.__init__` gains `pacing: PacingPool | None = None` (I6: `None` = today's
      behaviour, bit-for-bit).
- [ ] `_forward` builds `PacingKey` from the salted digest + resolved provider id, gets
      the pooled limiter, passes it via the new `AsyncClient(limiters=...)` seam. The
      client itself remains per-call — construction stays cheap once pacing state
      survives; connection pooling is explicitly *out of scope* here because a pooled
      `httpx2` client would hold the credential in its auth state (I2).
- [ ] Default `reserve_fraction > 0` (suggest `0.1`) for pool-built limiters: the
      customer's own application is almost certainly the other consumer of that BYOK
      key, which is verbatim the case the field documents.
- [ ] Latency sampling: record only successful, non-throttled forward calls
      (self-reinforcement guard, needed by Phase 4). Fixed-size ring buffer per
      `(tenant, target)`, e.g. 64 samples — timing floats only (I1).
- [ ] Tests (`src/anyinfer-confidential/tests/test_pacing.py`): same digest+provider →
      same limiter across two calls; different keys → different limiters; window
      observed on call 1 paces call 2 (injectable clock/sleep, as limits.py tests do);
      LRU bound holds; digest never equals nor contains the raw key; pool holds no
      reference to `ProviderSettings` after `handle` returns (weakref assertion).

**Exit criterion:** two sequential forward calls with the same key share one token
bucket and one observed window; with `pacing=None` nothing changes.

### Phase 2 — admission control: bounded, fair, typed

*Queue waiting **callers**, never stored requests. Backpressure over buffering — a
durable job queue would store slot-fills and assembled prompts, which is a different
product with a weaker guarantee than §30.3 states (I1).*

- [ ] New frozen dataclass `TenantLimits(max_in_flight: int | None = None,
      max_waiting: int | None = None, max_wait_s: float = 10.0)` with `__post_init__`
      validation in `RateLimits`' style. All-defaults = inert (I6).
- [ ] `RelayRegistry` additionally holds `TenantLimits` per tenant
      (`set_limits(tenant_id, limits)` / `limits_for(tenant_id)`), and
      `load_registry()`'s JSON shape gains an optional per-tenant block, since that file
      is now the provisioning path:

      ```json
      { "tenants": { "acme": { "limits": {"max_in_flight": 8, "max_waiting": 32},
                               "routes": [ ... ] } } }
      ```

      Back-compat: a bare list under a tenant continues to mean routes-only. (Both
      shapes documented in the `load_registry` docstring; malformed limits raise the
      same `RelayError` path as malformed routes.)
- [ ] New typed signal in `relay.py`:

      ```python
      @dataclass(frozen=True, slots=True)
      class ThrottleInfo:
          reason: Literal["tenant-in-flight", "tenant-queue-full", "provider-window"]
          retry_after_s: float          # jittered, clamped; see Phase 4
          remaining: int | None         # tenant's own remaining admission, when known

      class RelayThrottled(RelayError):
          def __init__(self, info: ThrottleInfo): ...
      ```

- [ ] Admission in `Relay.handle`, before `resolve`: per-tenant in-flight counter; over
      the cap → wait bounded by `max_wait_s` with at most `max_waiting` waiters; full or
      timed out → raise `RelayThrottled` immediately (fast rejection, never unbounded
      growth). Caller disconnect/cancellation drops the waiter and the work evaporates —
      which is the zero-retention behaviour we want anyway.
- [ ] Fairness: round-robin across tenants with waiters, not global FIFO — one deque per
      waiting tenant, cycle over tenants when releasing. ~50 lines; the difference
      between "bounded" and "fair".
- [ ] Telemetry: reuse `RateLimitWaited` where it fits (forward-path provider waits
      already emit it); add one payload-free `RelayThrottled`-shaped event in the
      confidential package for admission rejections — tenant id and reason only, never
      slot content (I1).
- [ ] Tests: cap enforced; waiter admitted on release; queue-full rejects fast;
      round-robin interleaves two tenants (tenant B admitted while A has a backlog);
      cancellation frees the slot; zero-config path takes no lock and adds no await
      (I6); one tenant saturating its cap does not block another tenant's assemble call.

**Exit criterion:** a tenant at its cap gets `RelayThrottled` in O(ms) while other
tenants proceed unimpeded.

### Phase 3 — HTTP surface: error taxonomy, 429, and standard headers

*`app.py` only (I4).*

- [ ] Split the catch-all: introduce `RelayBadRequest(RelayError)` for the
      missing-`provider_settings` case (and any future validation error) → 400; route
      resolution failure stays 404 with its deliberately-uniform message; new
      `RelayThrottled` → 429. Mapping lives in one dict in `app.py`, not in `relay.py`.
- [ ] On 429: emit `Retry-After` as **bare integer seconds** (ceil of
      `info.retry_after_s`) — `parse_retry_after` refuses the HTTP-date spelling, so a
      date here would be silently dropped by our own client — plus IETF draft
      `RateLimit-Remaining` / `RateLimit-Reset` when `info` carries them. No bespoke
      `X-Relay-*` names.
- [ ] On **200**: when admission limits are configured, emit `RateLimit-Limit` /
      `RateLimit-Remaining` for the tenant's own admission budget — this is what lets a
      client slow down *before* the wall, the "avoidance half" argument limits.py makes.
      Values derive from the requesting tenant's state only (I3). When nothing is
      configured, no header is emitted: an empty dialect honestly declared beats a
      guessed one (the `RateLimitHeaders.declared` philosophy).
- [ ] Tests (extend `tests/test_relay.py` or a new `test_app.py` behind the `relay`
      extra): status mapping ×3; `Retry-After` is digits-only; header values for tenant
      A are identical whether tenant B is idle or saturated (the I3 regression test —
      this is the security property, so it gets its own test, not a side assertion);
      404 body remains identical for missing vs. other-tenant routes.

**Exit criterion:** the three error classes map to 400/404/429; a saturated tenant's
429 carries machine-usable backoff; no header leaks cross-tenant load.

### Phase 4 — computing `retry_after_s`: exact where known, estimated where not

Two sources, kept distinct in code because they answer different questions:

| Cause | Source | Estimated? |
|---|---|---|
| Provider window exhausted (forward mode) | the pooled limiter's header-observed windows — the provider's own number | no — pass through |
| Relay admission backlog | tenant queue depth × service-time quantile ÷ in-flight cap | yes |

- [ ] **Exact path:** when the pooled `RateLimiter` holds an observed reset for this
      key's provider, `ThrottleInfo.retry_after_s` is that value clamped by
      `MAX_HEADER_WAIT_S`. Returning it to the caller leaks nothing: it is their own
      BYOK key's quota (I3). Requires a small read-only accessor on `RateLimiter`
      exposing the nearest observed reset — second core seam, a property, no behaviour
      change.
- [ ] **Estimated path:** `estimate = (position_in_tenant_queue × service_quantile) /
      max_in_flight`, where `service_quantile` comes from Phase 1's ring buffer.
      Design decisions, each deliberate:
      - **Quantile, not mean** — suggest p75. LLM latency is heavy-tailed and dominated
        by output length; a mean gets dragged by tails. Bias high: too-early costs a
        rejected round-trip and a re-queue, too-late costs a little idle capacity.
      - **Samples come only from successful, non-throttled calls** (enforced at the
        recording site in Phase 1, asserted in a test here).
      - **Jitter is mandatory, not a refinement**: full jitter,
        `uniform(0.5 × estimate, estimate)`. An exact "3s" told to 200 waiters is a
        synchronized retry-storm generator.
      - **Cold start:** no samples yet → fall back to a fixed floor (suggest 1.0s
        jittered); never 0.
      - **Clamp** the final value to `[0.5s, MAX_HEADER_WAIT_S]`.
      - Assemble-mode admission rejections use the same estimator — there the
        service-time samples are the render path's, which Phase 0 made measurable.
- [ ] Tests: passthrough beats estimate when both exist; quantile math on a fixed
      sample set; jitter bounds; cold-start floor; clamps; samples from throttled calls
      are never recorded; estimator inputs are per-`(tenant, target)` — feeding tenant
      B's samples never moves tenant A's estimate (I3 again, at the estimator layer).

**Exit criterion:** 429s carry a `retry_after_s` that is provider-exact when the
provider said so, and a jittered per-tenant queueing estimate otherwise.

### Phase 5 — the free client: declare the Relay's own dialect

*The payoff for using standard header names: an AnyInfer client pointed at a Relay
paces itself with zero new client code.*

- [ ] Ship a `RateLimitHeaders` declaration for the Relay's emitted dialect
      (`requests_remaining="ratelimit-remaining"`, `requests_reset="ratelimit-reset"`)
      in the confidential package, importable by anything that fronts a Relay with an
      AnyInfer client, with a doc example wiring it into `RateLimits`-configured
      settings. Core is not modified: the Relay is not a provider and gets no
      descriptor; this is a convenience constant plus documentation.
- [ ] Round-trip test: a fake Relay endpoint emitting Phase 3 headers, an AnyInfer
      client configured with the declared dialect, assert `RateLimitObserved` fires and
      the second request waits — proving emit-side and parse-side agree on spelling.
      This test is the drift guard between the two phases; it lives with the
      confidential tests.

**Exit criterion:** the round-trip test passes — Relay-emitted headers are consumed by
core's limiter unmodified.

## 3. Cross-cutting obligations

- **Docs** (same change as the code that makes them true, per AGENTS.md):
  - DESIGN.md §30.3: a short addendum naming admission control and pacing as part of
    Tier 2's operational story, and stating the ceiling honestly — this bounds one
    process; it is not cross-process quota enforcement.
  - `docs/guides/confidentiality-tiers.md`: the Relay section gains the throttling
    behaviour, header dialect, and the tenant-isolation property of emitted numbers.
    Plain words, no ADR numbers.
  - Module docstrings in `relay.py` / `pacing.py` / `app.py` each state what they hold
    in memory and why it is metadata-only — the zero-retention claims are audited
    prose, so they must be updated in the same commit that changes what is held.
- **Redaction:** the digest salt and every digest stay out of logs, events, errors, and
  test fixtures. The raw key path (`register_secret`) is unchanged.
- **Gate:** `workspace check` before each phase's commit; fast track
  (`workspace test`) as the inner loop.
- **No new deps** (I7). Quantile over a 64-sample ring is a sort — no numpy.

## 4. Explicit non-goals

Recorded so their absence reads as decided, not forgotten — §30.6 style:

- **Durable work queue** — persisting slot-fills or assembled prompts contradicts I1;
  it would be a different product with a weaker §30.3.
- **Cross-process / distributed quota coordination** — belongs in a fronting gateway if
  a multi-process hosted Relay materializes; core's limits.py explicitly refuses it and
  this plan does not sneak it in behind a config option (I5).
- **Priority tiers between tenants** — fairness yes, priority no.
- **Relay-layer retries** — core's `Retry`/`Route` own retry; stacking a second layer
  is amplification.
- **Anything that routes around a busy provider** — load balancing, ruled out by
  limits.py's own docstring.
- **Token-based (as opposed to request-based) admission accounting** — the Relay would
  need to count prompt tokens, which means measuring content; request counts and the
  provider's own token headers (already read by `RateLimiter.observe`) cover the need
  without new content-touching code.

## 5. Open questions (answer before the phase that needs them)

1. **Phase 1, core seam spelling:** `AsyncClient(limiters=...)` vs. a
   snapshot/restore pair on `RateLimiter`. The injection parameter is simpler and keeps
   one limiter identity per account; snapshot/restore keeps `AsyncClient`'s signature
   untouched. Default: injection, unless core review objects.
2. **Phase 2 defaults:** ship with all limits `None` (pure opt-in), or have
   `build_app` warn when serving multi-tenant with no limits configured? Leaning: warn
   — a hosted deployment with no admission control is the exact gap that motivated
   this plan.
3. **Phase 3:** IETF draft header names are still pre-RFC
   (`draft-ietf-httpapi-ratelimit-headers`) — pin the spelling we emit in the docs page
   and treat any future RFC rename as a deliberate, versioned change.
4. **Which mode dominates in real deployments?** If it's assemble, Phase 0 + Phase 2
   are most of the value and Phase 1/4's provider-side work can trail. Worth checking
   before scheduling, not before starting Phase 0.
