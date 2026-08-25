# Examples

Small, complete programs, not fragments. Each one is a pattern the library was designed
around. The shape of every example is exercised in CI against the in-process fake
providers (`tests/test_docs_examples.py`); whether a program runs offline as written, and
against what, is stated on each page.

| Example | What it shows |
|---|---|
| [Structured summaries with a fallback chain](summarize-with-fallback.md) | Schema-validated output, bounded repair, multi-provider fallback, and the attempt trail |
| [A local tool-calling assistant](local-tool-agent.md) | The `@ai.tool` decorator, the tool loop, and running fully local |
| [Distill a corpus](distill-a-corpus.md) | Map/reduce over material that will never fit, with cost preflight and a deterministic reducer |
| [Regression-test fallback and repair](golden-manifest.md) | A golden run manifest that asserts inference behavior instead of model prose |
| [Semantic search over a small corpus](semantic-search.md) | Embedding a corpus, index/query space safety, and reranking, with your own in-memory similarity math |

Comparing targets without spending anything is a guide rather than an example; see
[Will my request survive a target change?](../guides/comparing-targets.md)

If you are new to the library, read the [Quickstart](../guides/quickstart.md) first;
these examples assume you know what a [target](../concepts/targets.md) is.
