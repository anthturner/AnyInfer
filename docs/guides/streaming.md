# Stream to a terminal

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
numbers from different backends are directly comparable.

## Show fallback as it happens

```python
for event in stream:
    match event:
        case ai.AttemptFailed(record=record):
            print(f"[{record.target} failed: {record.error.type_name}]")
        case ai.TextDelta(text=t):
            print(t, end="", flush=True)
```

## Concurrency

Both clients support many concurrent independent streams. The sync facade runs one
background event loop, so streams started from different threads overlap rather than
serializing behind each other.

See [the event stream](../concepts/events.md) for the ordering guarantees you can rely on.
