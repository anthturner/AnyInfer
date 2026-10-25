# Add a Fallback Chain

A `Route` names the targets to try in order and the retry policy for each; the full
semantics live in [routing](../concepts/routing.md).

=== "Python"

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

=== "C# SDK (prerelease)"

    ```csharp
    --8<-- "examples/csharp-sdk/RoutingExample.cs"
    ```

`RoutingExample.RunAsync` accepts a native [`Route`](/csharp/api/anyinfer.route/), passes the
caller cancellation token to `GenerateAsync`, and returns the winning
[`Generation`](/csharp/api/anyinfer.generation/); `Generation.Target` names the target that
served it. A C# route's targets are `provider:model` strings in which the provider is a
configured instance ID, a registered provider ID or alias, or a catalog alias, so two
instances of one adapter (for example two OpenAI-compatible endpoints with the aliases
`primary` and `backup`) can back up each other. Each recipe below shows the Python form and
the native C# form, which the example runner executes offline. Model listing and health
checks are separate explicit calls rather than route policy; see the
[C# lifecycle example](csharp-sdk.md#list-models-and-check-health).

## Set a Default Route Once

=== "Python"

    ```python
    client = ai.Client(providers, route=ai.Route(targets=("medium", "small")))
    result = client.generate(prompt)  # no target= needed
    ```

=== "C#"

    ```csharp
    --8<-- "examples/csharp-sdk/RouteFailureExample.cs:default-route"
    ```

In C#, a call that names a single `target` instead of a route still uses the default route's
`Retry`, health-gate, and health-TTL settings; a call that passes its own `route` replaces the
default entirely. A version 1 [configuration file](python-to-csharp.md#shared-configuration)
supplies the same default through `default_route` when you create the client with
`AsyncClient.FromConfig`; that route is a target list with the default retry policy and health
gate. Embedding and rerank calls have their own optional defaults: the `operationRoutes`
argument (`operation_routes` in configuration) accepts only embedding and rerank keys, and a
generation call never uses them.

## Inspect What Happened

=== "Python"

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

=== "C#"

    ```csharp
    --8<-- "examples/csharp-sdk/RouteFailureExample.cs:attempts"
    ```

    <div class="terminal" markdown>
    ```text
    primary:demo: failed
       ProviderUnavailableException: The OpenAI-compatible service returned HTTP 503.
    backup:demo: ok
    ```
    </div>

Each C# [`AttemptRecord`](/csharp/api/anyinfer.attemptrecord/) has the resolved `Target`, an
`Outcome` (`ok`, `retried`, `failed`, or `skipped_unhealthy`), the typed `Error` for a failed or
retried attempt, and the attempt's `Timing` when it was measured. `Error.Snapshot()` returns a
credential-safe summary with the exception type name and bounded detail.

The trail is also visible while a request runs: a [stream](streaming.md) emits an
`AttemptFailed` event at the moment a target fails, so a UI can show the switch instead of
a stalled cursor.

## Handle Total Failure

=== "Python"

    ```python
    try:
        result = client.generate(prompt, route=route)
    except ai.AllTargetsFailedError as error:
        for attempt in error.attempts:
            alert(f"{attempt.target}: {attempt.error and attempt.error.detail}")
    ```

=== "C#"

    ```csharp
    --8<-- "examples/csharp-sdk/RouteFailureExample.cs:total-failure"
    ```

In C#, [`AllTargetsFailedException`](/csharp/api/anyinfer.alltargetsfailedexception/) is
thrown only after every target has been tried or skipped; its `Attempts` lists each attempt
in order. A failure that is not about target availability ends the call without trying the
next target: a schema violation after the repair budget, a spend-policy refusal, a stream
that breaks after emitting content, and cancellation.

Since a chain only proves itself when things fail, the
[test kit](testing-your-app.md) can script those failures offline: a provider that 503s
once and then answers exercises this exact path in CI. The C# recipes on this page are
verified the same way, with a scripted HTTP handler in place of each provider.

## Route by Failure Class

A context overflow needs a *bigger* model, not another same-sized one:

=== "Python"

    ```python
    route = ai.Route(
        targets=("openai:gpt-5-mini", "openai:gpt-5"),
        context_window_targets=("anthropic:claude-sonnet-4-5",),
    )
    ```

=== "C#"

    ```csharp
    --8<-- "examples/csharp-sdk/RouteFailureExample.cs:context-window"
    ```

When a `ContextLengthError` (C# `ContextLengthException`) occurs, the router switches to that
chain instead of continuing down the general one. In C#, the client's context gate records the
same failure before dispatch when a request's estimated input provably exceeds the target's
trusted context window, so the request moves to the context-window chain without being sent;
pass `contextGate: false` to the client to send such requests anyway.

## Tune Retry Behavior

=== "Python"

    ```python
    ai.Retry(
        max_attempts=3,
        backoff_base_s=0.5,  # 0.5s, then 1s, then 2s...
        backoff_max_s=30.0,  # ...capped here
    )
    ```

=== "C#"

    ```csharp
    --8<-- "examples/csharp-sdk/RouteFailureExample.cs:retry"
    ```

`max_attempts` (C# `MaxAttempts`) counts attempts on each target, including the first. A
server's `Retry-After` is honored when it is longer than the computed backoff, but the
sleep is still capped at `backoff_max_s` (`BackoffMaxS`).

By default, auth failures and context overflows are not retried: repeating them cannot
succeed, and the budget is better spent on the next target. In Python, override when you know
your provider better:

```python
ai.Retry(retry_on=lambda error: error.retryable or error.http_status == 409)
```

The C# `Retry` has no predicate. It retries a failure the provider classified as retryable
(rate limits, timeouts and other transport failures, and 5xx unavailability), never an
authentication failure or a context overflow.

## Health Gating

A target that recently failed with a transport or availability error is skipped for
`health_ttl_s` seconds, so one dead endpoint does not cost every subsequent request its full
timeout. Skipped attempts appear in the trail as `skipped_unhealthy`. Turn it off with
`health_gate=False` when you want every target attempted regardless. In C# the settings are
`healthGate` and `healthTtlS` (30 seconds by default), and the health state belongs to one
client:

```csharp
--8<-- "examples/csharp-sdk/RouteFailureExample.cs:health"
```

## A Good Default Shape

Put a local model last. When every hosted provider is unreachable (an outage, a captive
portal, an expired card), a local fallback is the difference between degraded and down:

```python
ai.Route(targets=("medium", "llama-cpp:qwen2.5-3b-instruct-q4-k-m"))
```

That Python target asks AnyInfer to run the local model itself. The C# SDK does not supervise
local runtimes; to put a local model last in a C# route, point an `openai-compat` instance at
an OpenAI-compatible server you run yourself and add its target at the end.

!!! tip "Key Takeaways"
    - Targets are tried strictly in order, and the result's attempts record what happened to
      every one, so a slow or rerouted request is explainable after the fact.
    - Auth failures and context overflows are not retried by default, because repeating
      them cannot succeed; Python's `retry_on=` overrides the predicate when you know better.
    - Context-window targets send an overflow to a bigger model instead of down the
      general chain, where a same-sized target would fail identically.
    - A local model at the end of the chain keeps your application degraded rather than
      down when every hosted provider is unreachable.

## See Also

<div class="anyinfer-see-also" markdown>

- [Routing and rate limits](../concepts/routing.md): the full route semantics, including
  what per-call `target=` does and does not override.
- [Stream to a terminal](streaming.md): rendering `AttemptFailed` as it happens.
- [Test your application offline](testing-your-app.md): scripting failures to prove the
  chain works.

</div>
