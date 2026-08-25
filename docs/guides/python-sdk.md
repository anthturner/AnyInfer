# Integrate the Python SDK

Use the SDK when AnyInfer runs inside a Python application.
[Quickstart](quickstart.md) is the fastest path to a first result; this page is the
reference for embedding the SDK properly — the client lifecycle and the error handling a
long-lived application needs.

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

## One client, reused, then closed

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

Choose `AsyncClient` inside an async application and `Client` in a synchronous one.
Create one client and reuse it; do not create one per request. Since a client owns
connection pools and any supervised local servers, close it with a context manager or an
explicit `close()`/`aclose()` call. One client serves many conversations — continuity
across turns is a [session](../concepts/sessions.md) concern, not a client-lifecycle
one.

`generate()` returns the finished result; to consume events as they arrive, see
[streaming](streaming.md).

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

The [error catalog](../reference/errors.md) lists every exception, when it is raised,
and what the user will see.

!!! tip "Key takeaways"
    - `AsyncClient` is the native implementation; `Client` is its thread-safe
      synchronous facade over the same surface.
    - Create one client, reuse it, and close it: it owns connection pools and any
      supervised local servers.
    - Catch `AnyInferError`, branch on its structured fields, and surface `hint`.

## See also

<div class="anyinfer-see-also" markdown>

- [Quickstart](quickstart.md): from `pip install` to a working result.
- [Stream typed events](streaming.md): consuming the event stream.
- [Sessions](../concepts/sessions.md): continuity across conversation turns.
- [Clients and streams](../reference/api/client.md): the full client API.
- [Error catalog](../reference/errors.md): every exception and its fields.

</div>
