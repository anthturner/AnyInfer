# SDK reference

Generated from the docstrings of every public symbol in `anyinfer` — coverage is a CI
gate, so nothing here is an empty page. The core surface is importable from the
top-level package; the local, serve, and testing subsystems from their subpackages:

```python
import anyinfer as ai
```

| Page | Covers |
|---|---|
| [Clients and streams](client.md) | `Client`, `AsyncClient`, streams, `ProviderSettings`, the `@tool` decorator |
| [Requests and messages](requests.md) | `GenerationRequest`, messages, sampling, schemas, tool specs |
| [Results and stream events](results.md) | `Generation`, usage, timing, the typed event stream |
| [Routing](routing.md) | `Route`, `Retry`, target resolution |
| [Capabilities](capabilities.md) | Provenance-tagged model capabilities and pricing |
| [Context reduction](context.md) | Fitting a document corpus to a token budget |
| [Telemetry and redaction](telemetry.md) | Observers, telemetry events, redaction, the OpenTelemetry bridge |
| [Registry, catalog, credentials](registry.md) | Provider descriptors, the model catalog, credential resolvers |
| [Configuration](configuration.md) | The shared JSON loader and validated config object |
| [Local inference](local.md) | `anyinfer.local`: hardware, backends, tuning, downloads, supervision |
| [Serve](serve.md) | `anyinfer.serve`: the embeddable frontend and its OpenAI codec |
| [Testing utilities](testing.md) | `anyinfer.testing`: fakes, cassettes, the conformance suite |
| [Errors](errors.md) | The exception hierarchy and its structured fields |

If you are looking for *how to use* these rather than their signatures, start with the
[concepts](../../concepts/README.md) and [guides](../../guides/README.md).
