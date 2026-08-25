# A Local Tool-Calling Assistant

An assistant that answers questions about your project by calling Python functions you
hand it. It does not run offline as written: it needs a running
[Ollama](../providers/ollama.md) with `qwen3:8b` pulled. Since that is the only
requirement, nothing leaves your machine and no API key is involved; the same program
points at any hosted provider by changing the target string.

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
feeds the result back, and loops until the model produces a final answer (bounded: a
runaway loop raises `ToolLoopError` rather than spinning). To stream the answer token by
token instead of waiting for it, see [streaming](../guides/streaming.md); nothing else
about the program changes.

## What to Notice

- `@ai.tool` derives the wire schema from the signature: name, docstring, and type hints
  become the provider-facing tool spec, and `read_file.spec` shows exactly what the model
  is told.
- The loop lives in the core, not your code. `run_tools` handles the call → execute →
  feed-back cycle identically on every provider that supports tools; the
  [conformance matrix](../reference/conformance-matrix.md) says which do.
- If `qwen3:8b` is not pulled yet, or you would rather have AnyInfer supervise a
  `llama-server` for you, the [local inference guide](../guides/local-inference.md)
  covers the end-to-end path, including picking a model tier that fits your hardware.

## See Also

<div class="anyinfer-see-also" markdown>

- [Run the tool loop](../guides/tool-loop.md): rounds, bounds, and error handling.
- [Stream to a terminal](../guides/streaming.md): the same conversation, token by token.
- [Run a local model end to end](../guides/local-inference.md): pulling models and
  supervised `llama-server`.

</div>
