# Add a fallback chain

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

## Handle total failure

```python
try:
    result = client.generate(prompt, route=route)
except ai.AllTargetsFailedError as error:
    for attempt in error.attempts:
        alert(f"{attempt.target}: {attempt.error and attempt.error.detail}")
```

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

By default, auth failures and context overflows are **not** retried — repeating them cannot
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

See [routing](../concepts/routing.md) for the full semantics.
