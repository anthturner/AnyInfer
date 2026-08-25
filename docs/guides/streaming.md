# Stream to a terminal

A stream yields typed [events](../concepts/events.md) while the request runs: text deltas,
reasoning, timing marks, and attempt failures. This page shows the patterns a terminal
frontend needs; the full event vocabulary is in the [API reference](../reference/api/README.md).

=== "Sync"

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

=== "Async"

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

## Use the context manager

Leaving the block early cancels the in-flight request. Without it, an abandoned stream keeps
generating — and, on a hosted provider, keeps billing:

```python
with client.stream(prompt, target=target) as stream:
    for event in stream:
        if isinstance(event, ai.TextDelta):
            print(event.text, end="", flush=True)
            if user_pressed_escape():
                break  # the request is cancelled on the way out
```

## Show thinking separately

Reasoning models emit a separate channel, excluded from the answer text:

```python
for event in stream:
    match event:
        case ai.ReasoningDelta(text=t):
            print(dim(t), end="", flush=True)
        case ai.TextDelta(text=t):
            print(t, end="", flush=True)
```

## Measure time to first token

```python
for event in stream:
    if isinstance(event, ai.TimingMark) and event.name == "first_token":
        print(f"[{event.at_ms:.0f} ms] ", end="", flush=True)
```

TTFT is measured by the core against `time.monotonic()`, identically for every provider, so
numbers from different backends are directly comparable. To export timings to a metrics
system rather than print them, see [observability](observability.md).

## Show fallback as it happens

When a [fallback chain](fallback.md) is in play, `AttemptFailed` events let you show the
switch as it happens rather than leaving the user staring at a stalled cursor:

```python
for event in stream:
    match event:
        case ai.AttemptFailed(record=record):
            print(f"[{record.target} failed: {record.error.type_name}]")
        case ai.TextDelta(text=t):
            print(t, end="", flush=True)
```

!!! tip "Key takeaways"
    - Use the context-manager form; leaving the block early cancels the in-flight request
      instead of letting a hosted provider keep generating and billing.
    - Reasoning text arrives as `ReasoningDelta`, a channel separate from the answer, so
      you can dim it or drop it without parsing anything.
    - TTFT is measured by the core, not the provider, so numbers from different backends
      are directly comparable.
    - `AttemptFailed` events surface retries and fallback while they happen, not after.

## See also

<div class="anyinfer-see-also" markdown>

- [The event stream](../concepts/events.md): the ordering guarantees you can rely on.
- [Add a fallback chain](fallback.md): the routing behind `AttemptFailed`.
- [Observe requests](observability.md): exporting these events instead of printing them.
- [API reference](../reference/api/README.md): every event type and its fields.

</div>
