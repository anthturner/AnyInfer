# Rate limits

AnyInfer has always *reacted* to a rate limit correctly: a 429 is a retryable error, the
provider's `Retry-After` is honoured, and backoff rises to the server's advice rather than
guessing at it. What it did not do is *anticipate* one — an `asyncio.gather` over a hundred
requests sent a hundred requests, took a wall of 429s, and only then backed off, having
already spent the provider's patience.

Client-side pacing is the other half. It is **opt-in**: with no limits configured, a request
is dispatched exactly as it was before this existed.

## What this is, and what it is not

| It does | It never does |
|---|---|
| Bound how many requests one provider instance has in flight | Share limits across processes or hosts |
| Delay a request when the provider's own headers say the window is nearly spent | Enforce a quota the provider did not state |
| Report every wait as a typed event and as `queued_ms` | Choose a *different* target because one is busy |

That last column is the important one. This paces **one process**. There is no shared state,
no coordination between workers, and no parameter that would accept any. A limiter that
routed around a throttled provider would be load balancing, and one that enforced an
organization's budget would be a control plane; AnyInfer is neither, deliberately.

## Configuring it

Limits belong to a **provider instance**, not to the application — a rate limit is a
property of an account at a provider, so two instances on two keys have two independent
allowances:

```python
import anyinfer as ai

client = ai.Client(
    [
        ai.ProviderSettings.of(
            "openai",
            api_key="env://OPENAI_API_KEY",
            limits=ai.RateLimits(max_concurrent=8, requests_per_minute=300),
        ),
    ]
)
```

The same thing in a configuration file, which the CLI and the sidecar read too:

```json
{
  "providers": [
    {
      "id": "openai",
      "api_key": "env://OPENAI_API_KEY",
      "limits": {
        "max_concurrent": 8,
        "requests_per_minute": 300,
        "reserve_fraction": 0.1
      }
    }
  ]
}
```

| Field | Default | What it does |
|---|---|---|
| `max_concurrent` | unbounded | Most requests in flight at once. The permit is held for the whole exchange, streaming included |
| `requests_per_minute` | unset | Sustained rate, enforced as a token bucket, so a small burst is allowed and then paced |
| `min_interval_s` | `0` | Smallest gap between two dispatches, for providers that object to bursts regardless of rate |
| `respect_headers` | `true` | Slow down when the provider's own headers say its window is nearly spent |
| `reserve_fraction` | `0` | Fraction of the provider's stated allowance to leave untouched |

`reserve_fraction` matters whenever this process is not the only consumer of the key.
Spending down to the last request in a window means whichever *other* consumer arrives next
is the one that gets throttled.

## Learning from the provider

Providers publish their state on every response. Which headers they use is a wire fact, so
it is declared on the provider descriptor and recorded in that provider's contract snapshot
rather than branched on by name in the core. Two dialects ship today:

| Provider | Reset format |
|---|---|
| OpenAI | Durations — `1s`, `6m0s` |
| Anthropic | RFC 3339 instants |

Every derived wait is clamped, so a skewed clock costs a bounded pause rather than a hang.
A provider that declares no dialect is paced by the bounds you configured and nothing else —
a smaller, reliable promise, rather than a guessed header name that silently reads
nothing forever.

If you ask for `respect_headers` where it cannot work — a provider that publishes no
headers, or one whose adapter talks through a vendor SDK, so its responses are never ours to
read — you get a `ParameterDropped` event saying so. A policy that quietly does nothing is
the degradation this library refuses to perform in silence.

## Seeing the wait

A paced request looks slow, so the wait is reported twice over: once in the event stream
and once in the result, where a caller can attribute it without a debugger.

```python
result = client.generate(prompt, target="openai:gpt-5")
result.timing.phases.get("queued_ms")  # present only when this request waited
```

```python
def observer(event):
    if isinstance(event, ai.RateLimitWaited):
        print(f"{event.provider_id} held a request {event.waited_s:.2f}s ({event.reason})")
    if isinstance(event, ai.RateLimitObserved):
        print(f"{event.provider_id} has {event.requests_remaining} requests left")


client.events.subscribe(observer)
```

`reason` is one of `concurrency`, `interval`, or `provider-headers`, so a slow fan-out can
be attributed to the bound that actually caused it.

`anyinfer doctor --config anyinfer.json` prints the configured limits for the same reason:
pacing is invisible from the outside, and "why is this slow" should be answerable in one
place.

## One interaction worth knowing

Queue time counts against the request's own `timeout_s`. A request that cannot be dispatched
inside its own timeout fails as a timeout, which is the literal reading of "how long until I
get an answer", but it does mean that aggressive pacing and a tight timeout will fight each
other. Raise `timeout_s` when you pace hard.

## Related

- [Cost and spending](cost.md): the other ceiling a client can carry
- [Routing and fallback](routing.md): what happens after a limit is hit anyway
- [`RateLimits`](../reference/api/capabilities.md#anyinfer.RateLimits): the full field reference
