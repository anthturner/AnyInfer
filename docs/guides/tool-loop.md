# Run the tool loop

`run_tools` runs the generate, call tools, feed results back loop for you, with bounded
rounds and normalized errors:

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
`Optional[T]`. Anything else raises `ToolLoopError` when the tool is declared, before a
schema that misdescribes the tool ever reaches a model.

Parameters with defaults are optional; the rest are required.

## Errors reach the model, not you

A tool that raises becomes an error-flagged result the model can react to:

```python
@ai.tool
def fetch(url: str) -> str:
    """Fetch a URL."""
    return httpx2.get(url).text  # may raise
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

v1 dispatches tool calls one at a time, in the order the model requested. Parallel
execution is deferred: it raises cancellation and ordering questions that no current
consumer needs answered.

## Naming and overrides

```python
@ai.tool(name="search_docs", description="Search the documentation index.")
def search(query: str, limit: int = 10) -> list: ...
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

## Tools from an MCP server

Model Context Protocol servers distribute tools — filesystems, databases, internal APIs —
behind one protocol, and AnyInfer can use one as a source of tools for the loop above:

```bash
pip install "anyinfer[mcp]"
```

```python
from anyinfer.mcp import MCPServer, MCPToolset

async with await MCPToolset.connect(
    MCPServer(name="fs", command=("mcp-server-filesystem", "./docs")),
) as toolset:
    result = await client.run_tools(
        "Which guide explains fallback?",
        tools=toolset.tools,
        target="anthropic:claude-sonnet-4-5",
    )
```

`toolset.tools` are ordinary AnyInfer tools: same bounded rounds, same sequential dispatch,
same rule that a failing tool becomes a result the model can recover from. Names are
namespaced by server (`fs__read_file`), so two servers offering `search` do not collide.

### Describing servers in configuration

```json
{
  "format_version": 1,
  "providers": [{"id": "anthropic"}],
  "mcp": [
    {
      "name": "fs",
      "command": ["mcp-server-filesystem", "./docs"],
      "deny_tools": ["write_file"]
    }
  ]
}
```

Loading a [configuration file](../reference/configuration.md) never starts a server; the
entries are inert until you connect them. Both stdio `env` values and HTTP `headers` values
accept `env://` and `credential://` references, which resolve and register for redaction
only on connect. Inspect what a server offers without running anything:

```bash
anyinfer mcp list --config anyinfer.json
```

```
fs__read_file    Read a file from the allowed directory  [read-only — server's claim]
fs__list_dir     List entries in a directory             [read-only — server's claim]
```

### What is not supported

- **Sampling** — a server asking the client to run a generation. Honoring that would let a
  remote server drive inference through your credentials, so it is not implemented.
- **Prompts, resources, and roots** — out of scope; this integration is a tool source.
- **AnyInfer as an MCP server** — non-Python clients reach your models through the
  [OpenAI-compatible sidecar](../serve/README.md) instead.

### Trust

Tool results enter the model's context, and the server decides what they say. That is the
prompt-injection surface every tool has; connecting a server you do not control widens it,
and `allow_tools`/`deny_tools` narrow what a server may expose. Annotations such as
"read-only" are the server's claims, not guarantees: AnyInfer captures them on
`ToolSpec.annotations` so your code can reason about them, and never grants access, skips a
step, or auto-approves anything because a server said it was safe.

### Testing it

The [test kit](testing-your-app.md)'s in-process fake MCP server makes an MCP-fed tool loop
testable without a subprocess:

```python
from anyinfer.testing import FakeMCPServer, FakeMCPTool

fake = FakeMCPServer([FakeMCPTool("read_file", result="file contents")])
toolset = await MCPToolset.connect(
    MCPServer(name="fs", url="http://fake.invalid/mcp"),
    transport_factory=lambda _: fake.transport(),
)
```

!!! tip "Key takeaways"
    - A tool is declared once: the schema comes from the signature, the description from
      the docstring, and an unsupported parameter type fails at declaration rather than
      misdescribing the tool to a model.
    - A raising tool becomes a result the model reacts to in conversation; only an unknown
      tool or an exhausted `max_rounds` raises to your code.
    - MCP servers plug in as tool sources with identical loop semantics, and configuration
      entries stay inert until you connect them.
    - Tool results are a prompt-injection surface and server annotations are unverified
      claims: narrow exposure with `allow_tools`/`deny_tools` and validate inside your
      tool implementations.

## See also

<div class="anyinfer-see-also" markdown>

- [A local tool agent](../examples/local-tool-agent.md): the loop end to end against a
  local model.
- [Test your application offline](testing-your-app.md): scripted providers and the fake
  MCP server.
- [Configuration](../reference/configuration.md): the `mcp` block the CLI and sidecar
  share.

</div>
