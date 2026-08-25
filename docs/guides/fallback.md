# Add a fallback chain

A `Route` names the targets to try in order and the retry policy for each; the full
semantics live in [routing](../concepts/routing.md).

```python
import anyinfer as ai

route = ai.Route(
    targets=(
        "anthropic:claude-sonnet-4-5",  # preferred
        "openai:gpt-5",  # if Anthropic is unavailable
        "ollama:qwen3:8b",  # last resort, always local
    ),
    retry=ai.Retry(max_attempts=2),
)

result = client.generate(prompt, route=route)
print("served by", result.target)
```

## Set a default route once

```python
client = ai.Client(providers, route=ai.Route(targets=("medium", "small")))
result = client.generate(prompt)  # no target= needed
```

## Inspect what happened

```python
for attempt in result.attempts:
    print(f"{attempt.target}: {attempt.outcome}")
    if attempt.error:
        print(f"   {attempt.error.type_name}: {attempt.error.detail}")
```

<div class="terminal" markdown>
```text
anthropic:claude-sonnet-4-5: failed
   ProviderUnavailableError: provider returned HTTP 503
openai:gpt-5: ok
```
</div>

The trail is also visible while a request runs: a [stream](streaming.md) emits an
`AttemptFailed` event at the moment a target fails, so a UI can show the switch instead of
a stalled cursor.

## Handle total failure

```python
try:
    result = client.generate(prompt, route=route)
except ai.AllTargetsFailedError as error:
    for attempt in error.attempts:
        alert(f"{attempt.target}: {attempt.error and attempt.error.detail}")
```

Since a chain only proves itself when things fail, the
[test kit](testing-your-app.md) can script those failures offline: a provider that 503s
once and then answers exercises this exact path in CI.

## Route by failure class

A context overflow needs a *bigger* model, not another same-sized one:

```python
route = ai.Route(
    targets=("openai:gpt-5-mini", "openai:gpt-5"),
    context_window_targets=("anthropic:claude-sonnet-4-5",),
)
```

When a `ContextLengthError` occurs, the router switches to that chain instead of continuing
down the general one.

## Tune retry behavior

```python
ai.Retry(
    max_attempts=3,
    backoff_base_s=0.5,  # 0.5s, then 1s, then 2s...
    backoff_max_s=30.0,  # ...capped here
)
```

A server's `Retry-After` is honored when it is longer than the computed backoff, but the
sleep is still capped at `backoff_max_s`.

By default, auth failures and context overflows are not retried — repeating them cannot
succeed, and the budget is better spent on the next target. Override when you know your
provider better:

```python
ai.Retry(retry_on=lambda error: error.retryable or error.http_status == 409)
```

## Health gating

A target that recently failed with a transport or availability error is skipped for
`health_ttl_s` seconds, so one dead endpoint does not cost every subsequent request its full
timeout. Skipped attempts appear in the trail as `skipped_unhealthy`. Turn it off with
`health_gate=False` when you want every target attempted regardless.

## A good default shape

Put a local model last. When every hosted provider is unreachable — an outage, a captive
portal, an expired card — a local fallback is the difference between degraded and down:

```python
ai.Route(targets=("medium", "llama-cpp:qwen2.5-3b-instruct-q4-k-m"))
```

!!! tip "Key takeaways"
    - Targets are tried strictly in order, and `result.attempts` records what happened to
      every one, so a slow or rerouted request is explainable after the fact.
    - Auth failures and context overflows are not retried by default, because repeating
      them cannot succeed; `retry_on=` overrides the predicate when you know better.
    - `context_window_targets` sends an overflow to a bigger model instead of down the
      general chain, where a same-sized target would fail identically.
    - A local model at the end of the chain keeps your application degraded rather than
      down when every hosted provider is unreachable.

## See also

<div class="anyinfer-see-also" markdown>

- [Routing and rate limits](../concepts/routing.md): the full route semantics, including
  what per-call `target=` does and does not override.
- [Stream to a terminal](streaming.md): rendering `AttemptFailed` as it happens.
- [Test your application offline](testing-your-app.md): scripting failures to prove the
  chain works.

</div>
