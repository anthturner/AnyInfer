# Examples

Small, complete programs — not fragments. Each one is a pattern the library was designed
around, and the shape of every example is exercised against the in-process fake providers
in CI (`tests/test_docs_examples.py`), so what you read here is what actually runs.

| Example | What it shows |
|---|---|
| [Structured summaries with a fallback chain](summarize-with-fallback.md) | Schema-validated output, bounded repair, multi-provider fallback, and the attempt trail |
| [A local tool-calling assistant](local-tool-agent.md) | The `@ai.tool` decorator, the tool loop, streaming, and running fully local |
| [Distill a corpus](distill-a-corpus.md) | Map/reduce over material that will never fit, with cost preflight and a deterministic reducer |

If you are new to the library, read the [Quickstart](../guides/quickstart.md) first —
these examples assume you know what a [target](../concepts/targets.md) is.
