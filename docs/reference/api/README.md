# Python API Reference {#sdk-reference}

The Python SDK's API, generated from the docstrings of every public symbol in `anyinfer`
and its add-on distributions; coverage is a CI gate, so nothing here is an empty page. The
C# SDK has its own [generated API reference](/csharp/api/). The core surface is importable
from the top-level package; the context, evaluate, local, serve, and testing subsystems
from their subpackages:

```python
import anyinfer as ai
```

| Page | Covers |
|---|---|
| [Clients and streams](client.md) | `Client`, `AsyncClient`, streams, `ProviderSettings`, the `@tool` decorator |
| [Requests and messages](requests.md) | `GenerationRequest`, messages, sampling, schemas, tool specs |
| [Results and stream events](results.md) | `Generation`, usage, timing, the typed event stream |
| [Routing](routing.md) | `Route`, `Retry`, target resolution |
| [Embeddings and reranking](embeddings.md) | The `embed()`/`rerank()` request and result types, embedding spaces, batch policy |
| [Capabilities](capabilities.md) | Provenance-tagged model capabilities and pricing |
| [Context reduction](context.md) | Fitting a document corpus to a token budget |
| [Telemetry and redaction](telemetry.md) | Observers, telemetry events, redaction, the OpenTelemetry bridge |
| [Registry, catalog, credentials](registry.md) | Provider descriptors, the model catalog, credential resolvers |
| [Configuration](configuration.md) | The shared JSON loader and validated config object |
| [Local inference](local.md) | `anyinfer.local`: hardware, backends, tuning, downloads, supervision |
| [Serve](serve.md) | `anyinfer.serve`: the embeddable frontend and its OpenAI codec |
| [Testing utilities](testing.md) | `anyinfer.testing`: fakes, cassettes, the conformance suite |
| [Confidentiality add-ons](confidential.md) | `anyinfer_confidential` and `anyinfer_shared`: sealed templates and the relay, separate distributions |
| [Portability diff](compare-diff.md) | `anyinfer.evaluate.compare_diff`: snapshot `compare()` output and diff two snapshots |
| [Vector store add-on](vector-store.md) | `anyinfer_store`: the small-scale embedded vector store, a separate distribution |
| [Errors](errors.md) | The exception hierarchy and its structured fields |

For *how to use* these rather than their signatures, start with the
[concepts](../../concepts/README.md) and [guides](../../guides/README.md).
