# Integrate the Python SDK

Use the SDK when AnyInfer runs inside a Python application. It exposes typed requests and
results, the complete event stream, in-process telemetry, provider capabilities, and the
tool loop without an HTTP hop.

## Configure the client

For deployed applications, keep provider identity and routing in the
[shared configuration file](../reference/configuration.md):

```python
import anyinfer as ai

config = ai.load_config("anyinfer.json")

with ai.Client(config.providers, route=config.route) as client:
    result = client.generate("Give me a two-sentence status summary.")
    print(result.text)
```

For a small script, construct the same settings directly:

```python
providers = [
    ai.ProviderSettings.of(
        "anthropic",
        api_key="env://ANTHROPIC_API_KEY",
    )
]

with ai.Client(providers) as client:
    result = client.generate("Hello", target="anthropic:claude-sonnet-4-5")
```

Credential references are resolved when an adapter is first used and registered for
redaction. Prefer `env://` or `credential://` references to literals in source code and
configuration files.

## Sync or async

`AsyncClient` is the native implementation. `Client` is its thread-safe synchronous
facade; both accept the same arguments and return the same domain types.

=== "Async"

    ```python
    async with ai.AsyncClient(config.providers, route=config.route) as client:
        result = await client.generate("Explain the result.")
    ```

=== "Sync"

    ```python
    with ai.Client(config.providers, route=config.route) as client:
        result = client.generate("Explain the result.")
    ```

Choose `AsyncClient` inside an async application. Choose `Client` for synchronous programs;
do not create a client per request. A client owns connection pools and any supervised local
servers, so close it with a context manager or an explicit `close()`/`aclose()` call.

## Generate or stream

`generate()` drains the event stream and returns a `Generation`. `stream()` exposes events
as they arrive and retains the final result after the stream ends:

```python
with client.stream("Write one sentence.", target="medium") as stream:
    for event in stream:
        if isinstance(event, ai.TextDelta):
            print(event.text, end="", flush=True)

generation = stream.result
```

Use the result's `usage`, `timing`, `attempts`, and `warnings` fields instead of parsing
provider payloads. Raw payload retention is off by default.

## Handle failures

All public failures derive from `AnyInferError` and carry structured fields. Branch on
those fields when behavior matters; show `hint` to the operator:

```python
try:
    result = client.generate("Hello", target="medium")
except ai.AnyInferError as exc:
    logger.error("generation failed during %s: %s", exc.phase, exc)
    if exc.hint:
        logger.info("next step: %s", exc.hint)
```

## Next steps

- [Stream typed events](streaming.md)
- [Add a fallback chain](fallback.md)
- [Enforce a JSON schema](structured-output.md)
- [Run the tool loop](tool-loop.md)
- [Observe requests](observability.md)
- [SDK reference](../reference/api/README.md)
