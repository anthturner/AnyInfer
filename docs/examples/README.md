# Examples

Small, complete programs; not fragments. Each one is a pattern the library was designed
around, and the shape of every example is exercised against the in-process fake providers
in CI (`tests/test_docs_examples.py`), so what you read here is what actually runs.

| Example | What it shows |
|---|---|
| [Structured summaries with a fallback chain](summarize-with-fallback.md) | Schema-validated output, bounded repair, multi-provider fallback, and the attempt trail |
| [A local tool-calling assistant](local-tool-agent.md) | The `@ai.tool` decorator, the tool loop, streaming, and running fully local |
| [Distill a corpus](distill-a-corpus.md) | Map/reduce over material that will never fit, with cost preflight and a deterministic reducer |
| [Regression-test fallback and repair](golden-manifest.md) | A golden run manifest that asserts inference behaviour instead of model prose |
| [Compare targets without spending](compare-targets.md) | Preflight fit, degradation, and mechanism choices in caller order |
| [Semantic search over a small corpus](semantic-search.md) | Embedding a corpus, index/query space safety, and reranking — with your own in-memory similarity math |

If you are new to the library, read the [Quickstart](../guides/quickstart.md) first —
these examples assume you know what a [target](../concepts/targets.md) is.
