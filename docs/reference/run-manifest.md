# Run manifest format

`RunManifest.to_dict()` and `RunManifest.to_json()` serialize the format accepted by
`RunManifest.from_dict()`. The canonical, machine-readable JSON Schema ships in the Python
package and is returned as a plain mapping:

```python
import jsonschema
import anyinfer as ai

jsonschema.validate(generation.manifest.to_dict(), ai.manifest_json_schema())
```

The schema requires the format, request identity, request summary, route, usage, and timing
facets. Other facets describe capabilities, attempts, structured output, prompt caching,
context reduction, dropped parameters, notes, and explicitly opted-in payloads. Cost values
are decimal strings or `null`; capability facts retain their provenance.

This is a pre-1.0 contract. Consumers must ignore unknown object properties. The `format`
value changes when an existing field changes meaning, not when a new field is added.

See [run manifests](../concepts/run-manifests.md) for the derivation and privacy rules.
