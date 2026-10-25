using AnyInfer.Json;

namespace AnyInfer.Examples.Cases;

/// <summary>Executes the registered-tool recipes published in the tool-loop guide.</summary>
internal static class ToolLoopGuideCases
{
    private static readonly IReadOnlyDictionary<string, int> Stock = new Dictionary<string, int> { ["ABC-1234"] = 3 };

    [ExampleCase("tool-declaration.delegate-schema")]
    internal static async Task DelegateSchema()
    {
        var tool = ToolDeclarationExample.Search();
        ExampleSupport.Require(tool.Name == "search_docs"
            && tool.Spec.Description == "Search the documentation index."
            && JsonWriter.Write(tool.Spec.Parameters) == """{"type":"object","properties":{"query":{"type":"string"},"limit":{"type":"integer"}},"required":["query"],"additionalProperties":false}""",
            $"The delegate binder produced {JsonWriter.Write(tool.Spec.Parameters)}.");

        var registry = new ToolRegistry([tool]);
        var found = await registry.DispatchAsync(new ToolCall("call-1", "search_docs", Arguments("""{"query":"fallback"}""")));
        var badArgument = await registry.DispatchAsync(new ToolCall("call-2", "search_docs", Arguments("""{"query":"fallback","page":2}""")));
        ExampleSupport.Require(found is { CallId: "call-1", Content: "[\"guides/fallback.md\"]", IsError: false }
            && badArgument is { IsError: true, Content: "ArgumentException: Unknown tool argument 'page'." }
            && registry.Dispatched == 2,
            "The bound delegate did not render its result or report an invalid argument as an error result.");
    }

    [ExampleCase("tool-declaration.explicit-spec")]
    internal static async Task ExplicitSpec()
    {
        var registry = new ToolRegistry([ToolDeclarationExample.Inventory(Stock)]);
        var known = await registry.DispatchAsync(new ToolCall("call-1", "check_stock", Arguments("""{"sku":"ABC-1234"}""")));
        var unknownSku = await registry.DispatchAsync(new ToolCall("call-2", "check_stock", Arguments("""{"sku":"XYZ-0000"}""")));
        ExampleSupport.Require(known is { Content: """{"sku":"ABC-1234","units":3}""", IsError: false }
            && unknownSku is { Content: "KeyNotFoundException: Unknown SKU XYZ-0000.", IsError: true },
            "The explicit tool did not render JSON output or convert its failure into an error result.");
        await GuideScripts.ExpectThrowsAsync<ToolLoopException>(
            () => registry.DispatchAsync(new ToolCall("call-3", "delete_stock", Arguments("{}"))),
            "A registry dispatched a tool name that was never registered.");
        ExampleSupport.Require(registry.Dispatched == 2, "An unknown tool name was counted as a dispatch.");
    }

    [ExampleCase("tool-failure.error-result-reaches-model")]
    internal static async Task ErrorResultReachesModel()
    {
        var handler = new GuideScripts.ChatHandler(
            GuideScripts.ToolCall("call-1", "check_stock", """{"sku":"XYZ-0000"}"""),
            GuideScripts.Text("That SKU does not exist."));
        var answer = await ToolFailureExample.AnswerAsync(GuideScripts.Instance(handler), ExampleSupport.Target, Stock);
        ExampleSupport.Require(answer == "That SKU does not exist." && handler.RequestCount == 2,
            "A failing tool ended the loop instead of answering the model.");
        using var first = handler.Request(0);
        using var second = handler.Request(1);
        var declared = first.RootElement.GetProperty("tools")[0].GetProperty("function");
        var feedback = second.RootElement.GetProperty("messages").EnumerateArray().Last();
        ExampleSupport.Require(declared.GetProperty("name").GetString() == "check_stock"
            && declared.GetProperty("parameters").GetProperty("properties").GetProperty("sku").GetProperty("pattern").GetString() == "^[A-Z]{3}-[0-9]{4}$"
            && feedback.GetProperty("role").GetString() == "tool"
            && feedback.GetProperty("tool_call_id").GetString() == "call-1"
            && feedback.GetProperty("content").GetString() == "KeyNotFoundException: Unknown SKU XYZ-0000.",
            "The handler failure was not returned to the model as the tool result.");
    }

    [ExampleCase("tool-failure.unknown-tool")]
    internal static async Task UnknownTool()
    {
        var handler = new GuideScripts.ChatHandler(GuideScripts.ToolCall("call-1", "delete_stock", "{}"));
        var answer = await ToolFailureExample.AnswerAsync(GuideScripts.Instance(handler), ExampleSupport.Target, Stock);
        ExampleSupport.Require(answer == "The assistant could not finish: The model called an unknown tool 'delete_stock'. Registered tools: check_stock"
            && handler.RequestCount == 1,
            $"An unknown tool was reported as '{answer}'.");
    }

    [ExampleCase("tool-failure.round-budget")]
    internal static async Task RoundBudget()
    {
        var stock = new CountingStock(Stock);
        var handler = new GuideScripts.ChatHandler(
            GuideScripts.ToolCall("call-1", "check_stock", """{"sku":"ABC-1234"}"""),
            GuideScripts.ToolCall("call-2", "check_stock", """{"sku":"ABC-1234"}"""));
        var answer = await ToolFailureExample.AnswerAsync(GuideScripts.Instance(handler), ExampleSupport.Target, stock, maxRounds: 2);
        ExampleSupport.Require(answer == "The assistant could not finish: The tool loop ran 2 rounds without a final answer. Raise maxRounds, or simplify the tools so the model converges."
            && handler.RequestCount == 2
            && stock.Lookups == 2,
            $"An exhausted round budget was reported as '{answer}' after {stock.Lookups} lookups.");
    }

    [ExampleCase("tool-failure.zero-rounds")]
    internal static async Task ZeroRounds()
    {
        var handler = new GuideScripts.ChatHandler();
        var answer = await ToolFailureExample.AnswerAsync(GuideScripts.Instance(handler), ExampleSupport.Target, Stock, maxRounds: 0);
        ExampleSupport.Require(answer.StartsWith("The assistant could not finish: The tool loop ran 0 rounds", StringComparison.Ordinal)
            && handler.RequestCount == 0,
            "A zero round budget generated before failing.");
    }

    [ExampleCase("tool-cancellation.completes")]
    internal static async Task CancellationCompletes()
    {
        var handler = new GuideScripts.ChatHandler(
            GuideScripts.ToolCall("call-1", "read_forecast", """{"city":"Boston"}"""),
            GuideScripts.Text("Yes, bring an umbrella."));
        var cancellable = false;
        var generation = await ToolCancellationExample.RunAsync(
            GuideScripts.Instance(handler),
            ExampleSupport.Target,
            (city, token) =>
            {
                cancellable = token.CanBeCanceled;
                return Task.FromResult(city == "Boston" ? "rain" : "unknown");
            });
        using var first = handler.Request(0);
        using var second = handler.Request(1);
        ExampleSupport.Require(generation is { Text: "Yes, bring an umbrella.", FinishReason: "stop" }
            && cancellable
            && first.RootElement.GetProperty("tools")[0].GetProperty("function").GetProperty("parameters").GetRawText()
                == """{"type":"object","properties":{"city":{"type":"string"}},"required":["city"],"additionalProperties":false}"""
            && second.RootElement.GetProperty("messages").EnumerateArray().Last().GetProperty("content").GetString() == "rain"
            && handler.DisposeCount == 1,
            "The forecast tool did not receive a cancellable token or feed its result back.");
    }

    [ExampleCase("tool-cancellation.cancelled-inside-handler")]
    internal static async Task CancelledInsideHandler()
    {
        var handler = new GuideScripts.ChatHandler(GuideScripts.ToolCall("call-1", "read_forecast", """{"city":"Boston"}"""));
        var started = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var observed = false;
        using var cancellation = new CancellationTokenSource();
        var running = ToolCancellationExample.RunAsync(
            GuideScripts.Instance(handler),
            ExampleSupport.Target,
            async (_, token) =>
            {
                started.TrySetResult();
                try
                {
                    await Task.Delay(Timeout.Infinite, token);
                    return "never";
                }
                catch (OperationCanceledException)
                {
                    observed = token.IsCancellationRequested;
                    throw;
                }
            },
            cancellation.Token);
        await started.Task.WaitAsync(TimeSpan.FromSeconds(30));
        cancellation.Cancel();
        var failure = await GuideScripts.ExpectThrowsAsync<OperationCanceledException>(
            () => running,
            "Cancelling the loop while a handler ran did not surface as OperationCanceledException.");
        ExampleSupport.Require(observed
            && failure.CancellationToken == cancellation.Token
            && handler.RequestCount == 1
            && handler.DisposeCount == 1,
            "The handler did not observe cancellation, or the loop kept generating after it.");
    }

    [ExampleCase("tool-loop.sync-facade")]
    internal static Task SyncFacade()
    {
        var handler = new global::ToolLoopHandler();
        var result = SyncToolLoopExample.Run(GuideScripts.Instance(handler), ExampleSupport.Target);
        ExampleSupport.Require(result.Generation is { Text: "Boston is clear.", FinishReason: "stop" }
            && result.HandlerCalls == 1
            && handler.RequestCount == 2
            && handler.DisposeCount == 1,
            "The synchronous tool loop did not complete its two-round conversation.");
        return Task.CompletedTask;
    }

    private static JsonObject Arguments(string json) => (JsonObject)JsonReader.Read(json);

    /// <summary>Counts stock lookups so a case can see each dispatch, including the final permitted round's.</summary>
    private sealed class CountingStock(IReadOnlyDictionary<string, int> inner) : IReadOnlyDictionary<string, int>
    {
        public int Lookups { get; private set; }
        public int this[string key] => inner[key];
        public IEnumerable<string> Keys => inner.Keys;
        public IEnumerable<int> Values => inner.Values;
        public int Count => inner.Count;
        public bool ContainsKey(string key) => inner.ContainsKey(key);
        public IEnumerator<KeyValuePair<string, int>> GetEnumerator() => inner.GetEnumerator();
        System.Collections.IEnumerator System.Collections.IEnumerable.GetEnumerator() => GetEnumerator();

        public bool TryGetValue(string key, out int value)
        {
            Lookups++;
            return inner.TryGetValue(key, out value);
        }
    }
}
