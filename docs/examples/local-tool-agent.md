# A local tool-calling assistant

An assistant that answers questions about your project by calling Python functions you
hand it — running entirely against a local Ollama model, so nothing leaves your machine
and no API key is involved. The same program points at any hosted provider by changing
the target string.

```python
"""assistant.py — `python assistant.py "what does pyproject.toml declare?"`"""

import sys
from pathlib import Path

import anyinfer as ai


@ai.tool
def read_file(path: str) -> str:
    """Read a file from the current project directory."""
    return Path(path).read_text(encoding="utf-8")


@ai.tool
def list_files(pattern: str = "*") -> str:
    """List project files matching a glob pattern."""
    return "\n".join(str(p) for p in Path.cwd().glob(pattern))


client = ai.Client([ai.ProviderSettings.of("ollama")])

result = client.run_tools(
    sys.argv[1],
    tools=[read_file, list_files],
    target="ollama:qwen3:8b",
)

print(result.text)
```

The model decides when to call `read_file` or `list_files`; AnyInfer runs the function,
feeds the result back, and loops until the model produces a final answer (bounded — a
runaway loop raises `ToolLoopError` rather than spinning).

## Streaming the same conversation

For interactive use, stream tokens as they arrive instead of waiting for the full
answer. Streaming and non-streaming are the same primitive — a
[typed event stream](../concepts/events.md), so nothing else about the program changes:

```python
with client.stream("Explain this project's layout", target="ollama:qwen3:8b") as stream:
    for event in stream:
        if isinstance(event, ai.TextDelta):
            print(event.text, end="", flush=True)
    result = stream.result  # usage, timing, and the attempt trail, same as generate()

print(
    f"\n\n[{result.usage.output_tokens} tokens, first token in {result.timing.first_token_ms} ms]"
)
```

## What to notice

- **`@ai.tool` derives the wire schema from the signature**: name, docstring, and type
  hints become the provider-facing tool spec. `read_file.spec` is inspectable if you want
  to see exactly what the model is told. See [the tool loop](../guides/tool-loop.md).
- **The loop lives in the core, not your code.** `run_tools` handles the call → execute →
  feed-back cycle identically on every provider that supports tools (the
  [conformance matrix](../reference/conformance-matrix.md) says which do).
- **Local is not a second-class citizen.** If `qwen3:8b` is not pulled yet, or you would
  rather have AnyInfer supervise a `llama-server` for you, the
  [local inference guide](../guides/local-inference.md) covers the end-to-end path —
  including letting the library pick a model tier that fits your hardware.

Related guides: [Run the tool loop](../guides/tool-loop.md) ·
[Stream to a terminal](../guides/streaming.md) ·
[Run a model locally, end to end](../guides/local-inference.md)
