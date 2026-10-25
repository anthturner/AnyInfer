# Examples

Small, complete programs, not fragments. Each one is a pattern the library was designed around.
The [Python cookbook](#python-cookbook) programs are exercised in CI against the in-process fake
providers (`tests/test_docs_examples.py`); the [C# cookbook](#c-cookbook) programs are static
classes whose methods the offline example runner calls and asserts, so they drop into an existing
.NET application rather than running as their own `Main`. Whether a program runs offline as
written, and against what, is stated on each page.

## Python Cookbook

| Example | What it shows |
|---|---|
| [Structured summaries with a fallback chain](summarize-with-fallback.md) | Schema-validated output, bounded repair, multi-provider fallback, and the attempt trail |
| [A local tool-calling assistant](local-tool-agent.md) | The `@ai.tool` decorator, the tool loop, and running fully local |
| [Distill a corpus](distill-a-corpus.md) | Map/reduce over material that will never fit, with cost preflight and a deterministic reducer |
| [Regression-test a fallback chain](golden-manifest.md) | A golden run manifest that asserts inference behavior instead of model prose |
| [Semantic search over a small corpus](semantic-search.md) | Embedding a corpus, index/query space safety, and reranking, with your own in-memory similarity math |

## C# Cookbook

Complete native .NET programs for the C# prerelease SDK. Each page includes source that the offline
example runner (`examples/csharp-sdk/AnyInfer.Examples.csproj`) executes and asserts against
scripted HTTP responses; running against hosted providers is optional on every page. Start with
[installation](../guides/csharp-installation.md) and the [C# quickstart](../guides/csharp-quickstart.md).

| Example | What it shows |
|---|---|
| [Summarize with configured fallback](csharp-generation.md) | Version 1 JSON configuration, a two-target route with retry and the health gate, schema-validated output deserialized into a record, and the attempt trail |
| [Stream to a console with cancellation](csharp-streaming.md) | Rendering text deltas, Ctrl+C and deadline cancellation, restarting after a mid-stream failure, and the synchronous stream |
| [Run a tool-calling assistant](csharp-tools.md) | Two typed `Tool.From` handlers, the round budget, handler errors returned to the model, and cancellation reaching a running handler |
| [Search a corpus with embeddings and reranking](csharp-retrieval.md) | Batched embedding under caller-owned IDs, embedding-space checks, and reranking with TEI, Voyage, or Jina |
| [Build an audit trail from telemetry and manifests](csharp-observability.md) | A typed observer, a JSONL sink, payload opt-in, and partial, terminal, validated, and rendered run manifests |
| [Meter spend across tenants](csharp-policies.md) | Explicit prices and context windows, spend ceilings, a caller-owned ledger and store, pacing, context-window fallback, and unknown cost |

## More

Comparing targets without spending anything is a guide rather than an example; see
[compare targets without spending](../guides/comparing-targets.md).

If you are new to the library, read the [Quickstart](../guides/quickstart.md) first;
these examples assume you know what a [target](../concepts/targets.md) is.
