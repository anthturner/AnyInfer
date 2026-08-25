# Run manifests

A run manifest is the portable explanation of one generation. It records the route that
won, attempts and fallback, structured-output and cache mechanisms, context reductions,
capability provenance, usage, cost, and timing. It is derived from the same typed events
and final result the client already produces; it is not another measurement or log
stream.

Every buffered `Generation` carries `generation.manifest` by default. A stream exposes
its current manifest through `stream.manifest`, including after cancellation. Set
`manifests=False` on the client to avoid allocating manifests, or pass `manifest=False`
on one call.

```python
result = client.generate("Summarize this", target="medium")
print(result.manifest.to_json())
```

The default record contains shapes and decisions, never prompts, completions, schemas,
tool arguments, or document bodies. `manifest_payloads=True` is an explicit client-wide
opt-in; captured strings still pass through
[credential redaction](credentials.md). AnyInfer never writes manifests — callers decide
whether and where to serialize them.

## Why manifests make useful golden files

Model prose changes. Routing and policy decisions should not change accidentally. The
testing helper removes request IDs and wall-clock fields, then compares the stable
remainder with a checked-in JSON file. See
[the offline testing guide](../guides/testing-your-app.md#regression-test-inference-behavior)
and the [complete example](../examples/golden-manifest.md). For the related question
"did my request's *resolution* change across targets", see the
[portability diff](../guides/comparing-targets.md).

## The format

The canonical, machine-readable JSON Schema ships in the package:

```python
import jsonschema
import anyinfer as ai

jsonschema.validate(generation.manifest.to_dict(), ai.manifest_json_schema())
```

The schema requires the format, request identity, request summary, route, usage, and
timing facets; other facets describe capabilities, attempts, structured output, prompt
caching, context reduction, dropped parameters, notes, and explicitly opted-in payloads.
Cost values are decimal strings or `null`, and capability facts retain their
[provenance](capabilities.md).

This is a pre-1.0 contract. The top-level `format` is currently `"1"`, and readers must
ignore unknown keys: adding a field does not change the format, while changing an
existing field's meaning does.

!!! tip "Key takeaways"
    - A manifest explains one generation's decisions — route, mechanisms, reductions,
      provenance — and is payload-free unless you opt in.
    - The library never writes manifests to disk; serialization is the caller's call.
    - Manifests make good golden files because the testing helper strips the volatile
      fields, leaving only decisions that should not change accidentally.

## See also

<div class="anyinfer-see-also" markdown>

- [Test your application offline](../guides/testing-your-app.md): manifests as golden
  files.
- [Regression-test fallback and repair](../examples/golden-manifest.md): the runnable
  example.
- [Telemetry](telemetry.md): the live event channel manifests are derived from.

</div>
