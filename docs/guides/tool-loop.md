# Run the Tool Loop

The tool loop runs the generate, call tools, feed results back cycle for you, with bounded
rounds and normalized errors. Both SDKs provide it: Python's `run_tools` takes decorated or
plain functions, and the C# prerelease SDK's `AsyncClient.RunToolsAsync` (and its
synchronous facade `Client.RunTools`) takes explicitly registered `Tool` handlers. Python
decorators and MCP tool sources are Python-only; each section below says which form it
describes.

=== "Python"

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

=== "C# SDK (prerelease)"

    ```csharp
    --8<-- "examples/csharp-sdk/ToolLoopExample.cs"
    ```

Both return the final round's generation: the first round whose finish reason is not
`tool_calls`. Its usage, timing, attempts, and manifest describe that final model round only,
not a sum across the loop.

## Register .NET Tool Handlers {#c-sdk-proof}

In C#, a [`Tool`](/csharp/api/anyinfer.tool/) pairs a provider-visible
[`ToolSpec`](/csharp/api/anyinfer.toolspec/) declaration with the handler that runs it.
Registering a tool is caller authorization: the loop dispatches only names you registered, and
a later tool with the same name replaces the earlier one in its position. There are two ways
to build one.

`Tool.From` binds a CLR delegate. The schema comes from the target method's parameters, the
name from the method unless you pass `name:`, and the description from `description:` or the
method's `[Description]` attribute. Parameters with default values are optional, and the
generated schema sets `additionalProperties` to `false`. Pass a name for a lambda, whose method
name is compiler-generated:

```csharp
--8<-- "examples/csharp-sdk/ToolDeclarationExample.cs:delegate"
```

When the model calls the tool, the binder converts the call's JSON arguments to the delegate's
parameter types, supplies the loop's token to a `CancellationToken` parameter, awaits a
returned `Task` or `ValueTask`, and renders the result for the model: `null` becomes empty
text, a string is used as is, a JSON-shaped value (a `JsonValue`, number, Boolean, list, array,
or string-keyed dictionary) becomes compact JSON, and anything else uses its `ToString()`.

For a schema the binder cannot express, or a handler outside the supported signatures,
construct the `Tool` from an explicit `ToolSpec` and a tagged-JSON callback. The callback
receives the model's arguments as an `AnyInfer.Json.JsonObject` and the call's
`CancellationToken`. The declared schema is sent to the model but is not checked against the
arguments for you:

```csharp
--8<-- "examples/csharp-sdk/ToolDeclarationExample.cs:explicit-spec"
```

The loop is provider-neutral: it runs over the typed tool-call events any generation adapter
reports. The built-in OpenAI-compatible chat adapter, which also serves the registered
Cerebras, Hyperbolic, and Nscale presets, speaks the OpenAI-compatible tool-call dialect.

## Python Tool Handlers {#python-tool-handlers}

The Python `@ai.tool` decorator, shown at the top of this page, derives the JSON schema from
your signature and the description from your docstring, so a tool is declared once rather than
kept in sync with a hand-written schema. Plain functions work too:
`run_tools(tools=[my_function])` wraps them automatically. The decorator is Python-only.

## Supported Parameter Types

=== "Python"

    `str`, `int`, `float`, `bool`, `list`, `dict`, their parameterized forms (`list[str]`), and
    `Optional[T]`. Anything else raises `ToolLoopError` when the tool is declared, before a
    schema that misdescribes the tool ever reaches a model.

    Parameters with defaults are optional; the rest are required.

=== "C#"

    `string`, `bool`, `int`, `long`, `BigInteger`, `double`, `JsonValue`, `JsonObject`,
    `JsonArray`, and `object`; a nullable form of any of these; and a one-dimensional array,
    `List<T>`, `IReadOnlyList<T>`, `Dictionary<string, T>`, or `IReadOnlyDictionary<string, T>`
    of a supported type. One `CancellationToken` parameter receives the loop's token, and a final
    `params` array always receives an empty array; neither appears in the schema. Any other
    parameter type, a `ref`, `out`, or pointer parameter, a generic method, or an `async void`
    method makes `Tool.From` throw `ToolLoopException` when the tool is declared.

    Parameters with default values are optional; the rest are required. At call time, an
    unknown or missing required argument, or a value of the wrong JSON type, throws
    `ArgumentException` inside the handler, which reaches the model as an error result.

## Errors Reach the Model, Not You

A tool that raises becomes an error-flagged result the model can react to:

=== "Python"

    ```python
    @ai.tool
    def fetch(url: str) -> str:
        """Fetch a URL."""
        return httpx2.get(url).text  # may raise
    ```

    The model sees `ConnectError: connection refused` as a tool result and can apologize, try
    a different URL, or give up — all ordinary conversation.

=== "C#"

    The stock tool above throws `KeyNotFoundException` for an unknown SKU. Any handler exception
    other than `OperationCanceledException` is caught and returned to the model as an
    error-flagged result whose text is the exception type name and message, here
    `KeyNotFoundException: Unknown SKU XYZ-0000.`, and the loop continues with the next round.

Only loop-level faults raise to you: an unknown tool, or an exhausted round budget. In C# both
are a [`ToolLoopException`](/csharp/api/anyinfer.toolloopexception/), whose `Hint` names the
remedy (for an unknown tool, the registered names):

```csharp
--8<-- "examples/csharp-sdk/ToolFailureExample.cs:loop-failure"
```

## Cancel a Running Tool {#cancel-a-running-tool}

In C#, the loop's cancellation token reaches the handler that is running, so a tool doing I/O
can stop with the rest of the request. Declare a `CancellationToken` parameter and pass it on:

```csharp
--8<-- "examples/csharp-sdk/ToolCancellationExample.cs:handler"
```

Cancelling the token passed to `RunToolsAsync` while the handler waits makes the handler's
operation throw; the loop does not turn `OperationCanceledException` into a tool result, starts
no further round, and throws `OperationCanceledException` carrying your token. In Python,
the loop follows ordinary task cancellation of the coroutine awaiting `run_tools`.

## The Round Bound

`max_rounds` (C# `maxRounds`, default 8) bounds the loop, because a model that keeps calling
tools would otherwise never terminate:

=== "Python"

    ```python
    try:
        result = client.run_tools(prompt, tools=tools, target=target, max_rounds=4)
    except ai.ToolLoopError as error:
        log.warning("%s (%s)", error.detail, error.hint)
    ```

=== "C#"

    The `AnswerAsync` recipe above catches the C# form. A round counts one generation. The final
    permitted round still dispatches the calls it returns, and then `ToolLoopException` reports
    that the rounds ended with tool calls pending. A `maxRounds` below 1 throws
    `ToolLoopException` before anything is generated.

## Execution Is Sequential

Both SDKs dispatch tool calls one at a time, in the order the model requested, and a repeated
call in a later round runs again. Calls are never run in parallel: each handler starts after the
previous one returns, so a slow tool delays the rest of its round.

## Naming and Overrides

=== "Python"

    ```python
    @ai.tool(name="search_docs", description="Search the documentation index.")
    def search(query: str, limit: int = 10) -> list: ...
    ```

=== "C#"

    Pass `name:` and `description:` to `Tool.From`, or put a `[Description]` attribute on the
    method, as `ToolDeclarationExample.Search` does above. An explicit `ToolSpec` states both
    directly.

## Async

=== "Python"

    ```python
    result = await async_client.run_tools(prompt, tools=[read_file], target=target)
    ```

=== "C#"

    `RunToolsAsync` is the native form. `Client.RunTools` is its synchronous facade, which
    blocks until the loop ends:

    ```csharp
    --8<-- "examples/csharp-sdk/SyncToolLoopExample.cs"
    ```

## Safety

The loop executes whatever the model asks for, within the tools you provide. Treat tool
implementations as a security boundary: validate paths, bound sizes and durations, and do
not expose a tool that runs arbitrary commands unless that is genuinely your intent.

## Tools from an MCP Server

!!! note "Python only"
    MCP tool sources, the `mcp` configuration block, and the fake MCP server are part of the
    Python SDK. The C# SDK has no MCP client, and its configuration loader refuses an `mcp`
    block.

Model Context Protocol servers distribute tools (filesystems, databases, internal APIs)
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

### Describing Servers in Configuration

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

### What Is Not Supported

- **Sampling**: a server asking the client to run a generation. Honoring that would let a
  remote server drive inference through your credentials, so it is not implemented.
- **Prompts, resources, and roots**: out of scope; this integration is a tool source.
- **AnyInfer as an MCP server**: non-Python clients reach your models through the
  [OpenAI-compatible sidecar](../serve/README.md) instead.

### Trust

Tool results enter the model's context, and the server decides what they say. That is the
prompt-injection surface every tool has; connecting a server you do not control widens it,
and `allow_tools`/`deny_tools` narrow what a server may expose. Annotations such as
"read-only" are the server's claims, not guarantees: AnyInfer captures them on
`ToolSpec.annotations` so your code can reason about them, and never grants access, skips a
step, or auto-approves anything because a server said it was safe.

### Testing It

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

!!! tip "Key Takeaways"
    - A tool is declared once: the schema comes from the Python signature or the C# delegate's
      parameters, and an unsupported parameter type fails at declaration rather than
      misdescribing the tool to a model.
    - A raising tool becomes a result the model reacts to in conversation; only an unknown
      tool or an exhausted round budget raises to your code.
    - In C#, the loop's cancellation token reaches the running handler, and cancellation is
      never converted into a tool result.
    - MCP servers (Python only) plug in as tool sources with identical loop semantics, and
      configuration entries stay inert until you connect them.
    - Tool results are a prompt-injection surface and server annotations are unverified
      claims: narrow exposure with `allow_tools`/`deny_tools` and validate inside your
      tool implementations.

## See Also

<div class="anyinfer-see-also" markdown>

- [A local tool agent](../examples/local-tool-agent.md): the loop end to end against a
  local model.
- [Test your application offline](testing-your-app.md): scripted providers and the fake
  MCP server.
- [Configuration](../reference/configuration.md): the `mcp` block the CLI and sidecar
  share.

</div>
