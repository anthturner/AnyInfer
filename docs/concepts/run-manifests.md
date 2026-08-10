# Run manifests

A run manifest is the portable explanation of one generation. It records the route that
won, attempts and fallback, structured-output and cache mechanisms, context reductions,
capability provenance, usage, cost, and timing. It is derived from the same typed events
and final result the client already produces; it is not another measurement or log stream.

Every buffered `Generation` carries `generation.manifest` by default. A stream exposes its
current manifest through `stream.manifest`, including after cancellation. Set
`manifests=False` on the client to avoid allocating manifests, or pass `manifest=False` on
one call.

```python
result = client.generate("Summarize this", target="medium")
print(result.manifest.to_json())
```

The default record contains shapes and decisions, never prompts, completions, schemas, tool
arguments, or document bodies. `manifest_payloads=True` is an explicit client-wide opt-in;
captured strings still pass through credential redaction. AnyInfer never writes manifests.
Callers decide whether and where to serialize them.

## Why manifests make useful golden files

Model prose changes. Routing and policy decisions should not change accidentally. The
testing helper removes request IDs and wall-clock fields, then compares the stable remainder
with a checked-in JSON file. See [the offline testing guide](../guides/testing-your-app.md#regression-test-inference-behaviour)
and the [complete example](../examples/golden-manifest.md).

## Format compatibility

The top-level `format` is currently `"1"`. Readers must ignore unknown keys: adding a field
does not change the format, while changing an existing field's meaning does. The executable
schema is returned by `anyinfer.manifest_json_schema()` and documented in the
[run-manifest reference](../reference/run-manifest.md).
