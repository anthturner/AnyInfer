# Run the tool loop

```python
import anyinfer as ai
from pathlib import Path

@ai.tool
def read_file(path: str) -> str:
    """Read a project file."""
    return Path(path).read_text(encoding="utf-8")

@ai.tool
def list_files(directory: str = ".") -> list:
    """List files in a directory."""
    return [p.name for p in Path(directory).iterdir()]

result = client.run_tools(
    "What does README.md say about installation?",
    tools=[read_file, list_files],
    target="anthropic:claude-sonnet-4-5",
    max_rounds=8,
)
print(result.text)
```

The decorator derives the JSON schema from your signature and the description from your
docstring, so a tool is declared once rather than kept in sync with a hand-written schema.

## Supported parameter types

`str`, `int`, `float`, `bool`, `list`, `dict`, their parameterized forms (`list[str]`), and
`Optional[T]`. Anything else raises `ToolLoopError` **when the tool is declared** — far
better than shipping a schema that misdescribes the tool to a model.

Parameters with defaults are optional; the rest are required.

## Errors reach the model, not you

A tool that raises becomes an error-flagged result the model can react to:

```python
@ai.tool
def fetch(url: str) -> str:
    """Fetch a URL."""
    return httpx2.get(url).text        # may raise
```

The model sees `ConnectError: connection refused` as a tool result and can apologize, try a
different URL, or give up — all ordinary conversation. Only loop-level faults raise to you:
an unknown tool, or an exhausted round budget.

## The round bound

`max_rounds` (default 8) bounds the loop, because a model that keeps calling tools would
otherwise never terminate:

```python
try:
    result = client.run_tools(prompt, tools=tools, target=target, max_rounds=4)
except ai.ToolLoopError as error:
    log.warning("%s (%s)", error.detail, error.hint)
```

## Execution is sequential

v1 dispatches tool calls one at a time, in the order the model requested. Parallel execution
is deliberately deferred: it raises cancellation and ordering questions that no current
consumer needs answered.

## Naming and overrides

```python
@ai.tool(name="search_docs", description="Search the documentation index.")
def search(query: str, limit: int = 10) -> list:
    ...
```

Plain functions work too — `run_tools(tools=[my_function])` wraps them automatically.

## Async

```python
result = await async_client.run_tools(prompt, tools=[read_file], target=target)
```

## Safety

The loop executes whatever the model asks for, within the tools you provide. Treat tool
implementations as a security boundary: validate paths, bound sizes and durations, and do
not expose a tool that runs arbitrary commands unless that is genuinely your intent.
