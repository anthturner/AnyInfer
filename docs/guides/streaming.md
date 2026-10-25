# Stream Typed Events

A stream yields typed [events](../concepts/events.md) while the request runs: text deltas,
reasoning, timing marks, and attempt failures. This page shows the patterns a terminal
frontend needs; the full event vocabulary is in the [API reference](../reference/api/README.md).

=== "Python sync"

    ```python
    import anyinfer as ai

    client = ai.Client([ai.ProviderSettings.of("ollama")])

    with client.stream("Explain TCP slow start.", target="ollama:qwen3:8b") as stream:
        for event in stream:
            if isinstance(event, ai.TextDelta):
                print(event.text, end="", flush=True)

        result = stream.result
        print(
            f"\n\n{result.usage.output_tokens} tokens, "
            f"first token in {result.timing.first_token_ms:.0f} ms"
        )
    ```

=== "Python async"

    ```python
    import anyinfer as ai

    async with ai.AsyncClient([ai.ProviderSettings.of("ollama")]) as client:
        async with client.stream("Explain TCP slow start.", target="ollama:qwen3:8b") as stream:
            async for event in stream:
                if isinstance(event, ai.TextDelta):
                    print(event.text, end="", flush=True)

            result = stream.result
            print(
                f"\n\n{result.usage.output_tokens} tokens, "
                f"first token in {result.timing.first_token_ms:.0f} ms"
            )
    ```

=== "C# SDK (prerelease)"

    ```csharp
    --8<-- "examples/csharp-sdk/StreamingExample.cs"
    ```

=== "C# SDK sync facade (prerelease)"

    ```csharp
    --8<-- "examples/csharp-sdk/SyncStreamingExample.cs"
    ```

In C#, an [`AsyncStream`](/csharp/api/anyinfer.asyncstream/) is disposed with `await using`
and a [`SyncStream`](/csharp/api/anyinfer.syncstream/) with `using`; both keep the
cancellation token passed when they were created. The recipes below show the Python form
beside the native C# form, and the C#-only sections cover result, failure, and synchronous
stream semantics; every C# recipe is executed offline by the example runner. Model discovery
and health checks are separate explicit calls, covered in the
[C# SDK guide](csharp-sdk.md#list-models-and-check-health).

## Buffered or Streamed {#buffered-or-streamed}

A buffered call and a stream run the same execution path, including retries, fallback, and
schema repair. The buffered call waits and returns only the terminal result; the stream hands
you every event first and keeps the same terminal result for the end. In C#,
`GenerateAsync` (or `Client.Generate`) returns the [`Generation`](/csharp/api/anyinfer.generation/)
directly:

```csharp
--8<-- "examples/csharp-sdk/GenerationExample.cs"
```

A C# stream holds its terminal result in three equivalent places once it completes
successfully: the `StreamEnded` event's `Result`, the stream's `Result` property, and the
return value of `CollectAsync` (`Collect` on a `SyncStream`), which drains the stream for you.
Before successful completion, `Result` throws `InvalidOperationException`; it never returns a
partial generation. A stream has a single consumer: enumerating it a second time throws
`InvalidOperationException`.

The two C# stream types start differently. `AsyncClient.StreamAsync` is lazy: nothing is sent
until you start enumerating it. `Client.Stream` starts generating as soon as it is created and
buffers up to 256 events ahead of a slow consumer.

## Stop a Stream Early {#use-the-context-manager}

Leaving the loop early cancels the in-flight request. Without that, an abandoned stream keeps
generating — and, on a hosted provider, keeps billing.

=== "Python"

    Use the context-manager form; leaving the block early cancels the request:

    ```python
    with client.stream(prompt, target=target) as stream:
        for event in stream:
            if isinstance(event, ai.TextDelta):
                print(event.text, end="", flush=True)
                if user_pressed_escape():
                    break  # the request is cancelled on the way out
    ```

=== "C#"

    Breaking or returning out of `await foreach` disposes the enumerator, which cancels the
    request and releases the response; `await using` then disposes the stream:

    ```csharp
    --8<-- "examples/csharp-sdk/StreamEarlyExitExample.cs:async"
    ```

After an early exit the stream has no terminal result, so `Result` throws. Cancelling the
token you passed to `StreamAsync` or `WithCancellation` instead makes the loop throw
`OperationCanceledException` whose `CancellationToken` is your token; the response is released
the same way. Disposing the client also cancels its open streams.

## Show Thinking Separately

Reasoning models emit a separate channel, excluded from the answer text:

=== "Python"

    ```python
    for event in stream:
        match event:
            case ai.ReasoningDelta(text=t):
                print(dim(t), end="", flush=True)
            case ai.TextDelta(text=t):
                print(t, end="", flush=True)
    ```

=== "C#"

    ```csharp
    --8<-- "examples/csharp-sdk/StreamEventsExample.cs:thinking"
    ```

In C#, reasoning reaches the stream only from an adapter that reports it. The built-in
OpenAI-compatible chat adapter, which also serves the registered Cerebras, Hyperbolic, and
Nscale presets, does not emit `ReasoningDelta` or `CitationDelta` events; an
application-owned adapter supplied through `AsyncClient.FromAdapters` can. The example runner
exercises this recipe with such an adapter.

## Measure Time to First Token

=== "Python"

    ```python
    for event in stream:
        if isinstance(event, ai.TimingMark) and event.name == "first_token":
            print(f"[{event.at_ms:.0f} ms] ", end="", flush=True)
    ```

=== "C#"

    ```csharp
    --8<-- "examples/csharp-sdk/StreamEventsExample.cs:first-token"
    ```

TTFT is measured by the core against a monotonic clock, identically for every provider, so
numbers from different backends are directly comparable. Each attempt, and each schema-repair
round trip, starts with its own `attempt_start` mark at 0 ms and reports its own
`first_token` mark relative to that start; the result's `Timing.FirstTokenMs` is the winning
attempt's value. To export timings to a metrics system rather than print them, see
[observability](observability.md).

## Show Fallback as It Happens

When a [fallback chain](fallback.md) is in play, `AttemptFailed` events allow you to show
the switch as it happens rather than leaving the user staring at a stalled cursor:

=== "Python"

    ```python
    for event in stream:
        match event:
            case ai.AttemptFailed(record=record):
                print(f"[{record.target} failed: {record.error.type_name}]")
            case ai.TextDelta(text=t):
                print(t, end="", flush=True)
    ```

=== "C#"

    ```csharp
    --8<-- "examples/csharp-sdk/StreamEventsExample.cs:fallback"
    ```

Deltas from an attempt that later fails are delivered before its `AttemptFailed` event. A
frontend that must show only the winning answer should treat each `attempt_start` timing mark
as a fresh start, or render `Result.Text` at the end.

## Read Every Event Type {#read-every-event-type}

The C# event records all derive from [`StreamEvent`](/csharp/api/anyinfer.streamevent/), so one
`switch` covers them:

```csharp
--8<-- "examples/csharp-sdk/StreamEventsExample.cs:describe"
```

| C# event | Meaning |
|---|---|
| `TimingMark(Name, AtMs)` | `attempt_start` (0 ms) or `first_token`, in milliseconds since that attempt started. |
| `TextDelta(Text)` | A fragment of the visible answer. |
| `ReasoningDelta(Text)` | A fragment of reasoning, excluded from `Generation.Text`. |
| `CitationDelta(Citation)` | A complete citation; the result collects them in `Generation.Citations`. |
| `ToolCallDelta(Index, CallId, Name, ArgumentsFragment)` | Part of a model-requested tool call; correlate fragments by `Index`. |
| `ServerToolDelta` | A lifecycle update from a provider-run tool such as web search. |
| `UsageUpdate(Usage)` | A usage report; it may arrive mid-stream and more than once. |
| `AttemptFailed(Record)` | A target attempt failed; its `AttemptRecord` says why, and a retry or fallback may follow. |
| `StreamEnded(Result)` | Terminal and exactly once: the same `Generation` that `Result` returns. |

A `ToolCallDelta` is how a streamed tool call arrives; the assembled calls are in
`Generation.ToolCalls`, and a stream does not run them. To execute registered handlers, use
the [tool loop](tool-loop.md).

## Handle Stream Failures {#handle-stream-failures}

A failure that ends the request is thrown by the enumeration itself, after the events that
preceded it. It is never delivered as an event, and no `StreamEnded` follows it.

```csharp
--8<-- "examples/csharp-sdk/StreamEventsExample.cs:failure"
```

In C#:

- An argument or route problem is thrown when you create the stream: `StreamAsync` with no
  target, route, or client default route throws `ConfigException` before anything is sent.
- `AllTargetsFailedException` is thrown after the last `AttemptFailed` event when every target
  failed; its `Attempts` lists each one.
- `SchemaViolationException` (an exhausted [repair budget](structured-output.md)) and
  `SpendLimitException` (a [spend policy](csharp-sdk.md#apply-request-policy-explicitly)
  refusal) are thrown the same way.
- A stream that breaks after it has already emitted content throws `StreamProtocolException`
  instead of moving on to another target, because the text you have shown cannot be retracted.
- Cancellation throws `OperationCanceledException`.

In every failure case `Result` throws `InvalidOperationException`.

## The Synchronous Stream {#the-synchronous-stream}

`Client.Stream` returns a `SyncStream`, a bounded single-consumer view for callers without
`async`. It starts generating when created, so create it only when you are about to read it.
Finishing the `foreach` disposes the stream and keeps its observed result readable; leaving the
loop early disposes the stream too, which cancels the generation and waits for it to stop:

```csharp
--8<-- "examples/csharp-sdk/StreamEarlyExitExample.cs:sync"
```

`SyncStream.Collect` drains the stream, returns its result, and disposes it; a disposed
`SyncStream` cannot be enumerated again (`ObjectDisposedException`). A failure or a
cancellation of the token passed to `Stream` is thrown by the enumeration after the events
buffered before it.

!!! tip "Key Takeaways"
    - Stop reading through the language's own lifetime construct (the context manager in
      Python, leaving `await foreach` or `foreach` in C#) and the in-flight request is
      cancelled instead of a hosted provider continuing to generate and bill.
    - Reasoning text arrives as `ReasoningDelta`, a channel separate from the answer, so
      you can dim it or drop it without parsing anything.
    - TTFT is measured by the core, not the provider, so numbers from different backends
      are directly comparable.
    - `AttemptFailed` events surface retries and fallback while they happen, not after; a
      request that cannot succeed raises from the loop instead of ending with `StreamEnded`.

## See Also

<div class="anyinfer-see-also" markdown>

- [The event stream](../concepts/events.md): the ordering guarantees you can rely on.
- [Add a fallback chain](fallback.md): the routing behind `AttemptFailed`.
- [Observe requests](observability.md): exporting these events instead of printing them.
- [API reference](../reference/api/README.md): every Python event type and its fields; the
  [C# API reference](/csharp/api/) lists the native records.

</div>
