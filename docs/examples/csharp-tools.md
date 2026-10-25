# Run a Tool-Calling Assistant

An order-support assistant in native C#. The model can look up an order and quote a refund through
two registered tools with typed arguments. The SDK runs the bounded loop: it advertises the tools,
binds each call's JSON arguments to the handler's parameters, runs the calls in order, returns
their results to the model, and stops at the round budget. The caller's cancellation token reaches
the handler that is running, and handler failures go back to the model as text instead of ending
the conversation.

## Before You Start

- The .NET 8 SDK and a reference to the local C# prerelease, as described in
  [Install the C# SDK](../guides/csharp-installation.md), and the first call from the
  [C# quickstart](../guides/csharp-quickstart.md). The C# SDK is a locally packaged
  `0.1.0-proof` prerelease, not a NuGet package.
- Nothing else to run it offline. Against a real model, use a target whose endpoint accepts
  OpenAI-style tool calls; the built-in chat adapter speaks that dialect.

## The Program

```csharp
--8<-- "examples/csharp-sdk/CookbookToolsExample.cs"
```

## How It Works

- **A delegate is the declaration.** `Tool.From` reads the handler's parameters to build the tool's
  JSON Schema: `orderId` becomes a required string, `units` a required integer, and
  `includeShipping` an optional boolean because it has a default value. The schema sets
  `additionalProperties` to `false`. The `CancellationToken` parameter is not advertised; the loop
  supplies the call's token. Local functions keep the handlers next to the application state they
  use, here the order store and the tool-use log.
- **Registration is authorization.** Only the two registered tools can run. A call to any other
  name ends the loop with `ToolLoopException`, and so does a model that is still calling tools
  after `maxRounds` rounds; the last permitted round's calls still run first.
- **Failures are conversation, not exceptions.** When a handler throws, or the model's arguments do
  not bind to the parameter types, the loop returns `ExceptionType: message` to the model as that
  call's result and continues. The built-in chat adapter sends that text as the tool message
  content. `OperationCanceledException` is the exception that is not converted.
- **Calls run one at a time.** Several calls in one round run in the order the model returned them,
  and all their results are appended before the next round.
- **The result is the final round.** `RunToolsAsync` returns the first generation that is not
  asking for tools; its usage describes that round only. The caller-owned `SpendLedger` subscribes
  to the client's telemetry and totals every round, which is how the program reports requests and
  tokens for the whole conversation.

## Offline Run

The example runner scripts the model's tool calls and asserts what the handlers and the model saw.
The cases are in `examples/csharp-sdk/Cases/CookbookToolsCases.cs`; from `src/csharp`, run:

```bash
dotnet run --project ../../examples/csharp-sdk/AnyInfer.Examples.csproj --configuration Release
```

The `cookbook.tools.*` cases check that:

- both tools are declared on every round with the generated parameter schemas, and the token
  parameter is absent;
- two lookups in one round run in order, the unknown order's `KeyNotFoundException` reaches the
  model as `KeyNotFoundException: Order Z-999 does not exist.`, the refund quote binds `units` and
  `includeShipping`, and the ledger totals three rounds;
- a string where an integer is expected never reaches the handler, while the handler's own
  range check does, and both return to the model;
- four rounds of tool calls end with `ToolLoopException` after four handler runs, and a call to an
  unregistered tool ends the loop without running anything;
- cancelling the caller's token while a handler waits on the order store cancels that wait and
  surfaces as `OperationCanceledException` carrying the caller's token;
- the client disposes its transport once.

## Before Production

- Treat every registered tool as code the model may run with any arguments it chooses. Validate in
  the handler, as `QuoteRefund` does, and keep side-effecting tools behind your own authorization.
- Keep handler failures informative but safe: the message text goes to the model.
- Choose `maxRounds` for the longest legitimate conversation, and handle `ToolLoopException` as the
  signal that the model did not converge.
- Pass a request-scoped cancellation token so an abandoned request also stops its tools.
- For a tool signature outside the delegate binder's supported types, construct `Tool` from an
  explicit `ToolSpec` and a JSON callback.

Python's `@ai.tool` decorator and MCP tool sources are Python features; the C# surface is
`Tool.From`, `Tool`, and `ToolRegistry`.

## See Also

<div class="anyinfer-see-also" markdown>

- [Run the tool loop](../guides/tool-loop.md#c-sdk-proof) for the loop's rules in both SDKs.
- [Meter spend across tenants](csharp-policies.md) for ledgers beyond one conversation.
- API: [`Tool`](/csharp/api/anyinfer.tool/), [`ToolRegistry`](/csharp/api/anyinfer.toolregistry/),
  [`ToolSpec`](/csharp/api/anyinfer.toolspec/),
  [`ToolResult`](/csharp/api/anyinfer.toolresult/),
  [`ToolLoopException`](/csharp/api/anyinfer.toolloopexception/),
  [`AsyncClient`](/csharp/api/anyinfer.asyncclient/),
  [`SpendLedger`](/csharp/api/anyinfer.capabilities.spendledger/).
- The Python version of this pattern: [A local tool-calling assistant](local-tool-agent.md).

</div>
