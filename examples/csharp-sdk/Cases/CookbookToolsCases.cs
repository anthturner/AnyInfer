using System.Text.Json;

namespace AnyInfer.Examples.Cases;

/// <summary>Runs the order-support assistant offline through its tool rounds and failure paths.</summary>
internal static class CookbookToolsCases
{
    private const string Target = "support:assistant";

    private static readonly CookbookInMemoryOrders Orders = new(
        new CookbookOrder("A-100", "delivered", 3, 1250, 499));

    [ExampleCase("cookbook.tools.typed-tools-and-handler-error")]
    internal static async Task TypedToolsAndHandlerError()
    {
        var handler = new CookbookScriptedHandler(
            CookbookReplies.ToolCalls(("call-1", "lookup_order", """{"orderId":"A-100"}"""), ("call-2", "lookup_order", """{"orderId":"Z-999"}""")),
            CookbookReplies.ToolCalls(("call-3", "quote_refund", """{"orderId":"A-100","units":2,"includeShipping":true}""")),
            CookbookReplies.Chat("A-100 was delivered; refunding 2 units with shipping is 29.99 USD. I could not find Z-999.", 60, 25));

        var reply = await CookbookToolsExample.AnswerAsync(
            [Settings(handler)], Target, Orders, "Refund two units of A-100 with shipping. Also, where is Z-999?");

        ExampleSupport.Require(reply is { Failure: null } && reply.Text!.StartsWith("A-100 was delivered", StringComparison.Ordinal)
            && reply.ToolUses.SequenceEqual(["lookup_order A-100", "lookup_order Z-999", "quote_refund A-100 x2 +shipping"])
            && reply.Totals is { Requests: 3, InputTokens: 100, OutputTokens: 41, UnknownRequests: 3 },
            "The assistant did not run both tools in order or did not total every round.");

        // Every round declares both tools with their generated schemas.
        var first = handler.Requests[0].Json();
        var tools = first.GetProperty("tools").EnumerateArray().Select(static tool => tool.GetProperty("function")).ToArray();
        var quote = tools[1].GetProperty("parameters");
        ExampleSupport.Require(tools.Select(static tool => tool.GetProperty("name").GetString()).SequenceEqual(["lookup_order", "quote_refund"])
            && tools[0].GetProperty("parameters").GetProperty("properties").GetProperty("orderId").GetProperty("type").GetString() == "string"
            && quote.GetProperty("properties").GetProperty("units").GetProperty("type").GetString() == "integer"
            && quote.GetProperty("properties").GetProperty("includeShipping").GetProperty("type").GetString() == "boolean"
            && quote.GetProperty("required").EnumerateArray().Select(static name => name.GetString()).SequenceEqual(["orderId", "units"])
            && !quote.GetProperty("additionalProperties").GetBoolean()
            && !quote.GetProperty("properties").TryGetProperty("token", out _),
            "The typed handler signatures did not become the declared tool schemas.");

        // The second round carries both results; the failed lookup is returned to the model as text.
        var second = ToolMessages(handler.Requests[1]);
        ExampleSupport.Require(second.Count == 2
            && second[0].CallId == "call-1"
            && JsonDocument.Parse(second[0].Content).RootElement.GetProperty("status").GetString() == "delivered"
            && second[1] == ("call-2", "KeyNotFoundException: Order Z-999 does not exist.")
            && ToolMessages(handler.Requests[2]).Last() == ("call-3", "Refund for 2 unit(s) of A-100: 29.99 USD.")
            && handler.Requests.Count == 3
            && handler.DisposeCount == 1,
            "Handler results or the handler failure were not returned to the model in call order.");
    }

    [ExampleCase("cookbook.tools.invalid-arguments")]
    internal static async Task InvalidArguments()
    {
        var handler = new CookbookScriptedHandler(
            CookbookReplies.ToolCalls(("call-1", "quote_refund", """{"orderId":"A-100","units":"two"}"""), ("call-2", "quote_refund", """{"orderId":"A-100","units":9}""")),
            CookbookReplies.Chat("Please tell me how many units to refund (at most 3)."));

        var reply = await CookbookToolsExample.AnswerAsync([Settings(handler)], Target, Orders, "Refund some of A-100.");

        // A mistyped argument never reaches the handler; a handler's own validation failure does. Both return to the model.
        var results = ToolMessages(handler.Requests[1]);
        ExampleSupport.Require(reply is { Failure: null, Text: "Please tell me how many units to refund (at most 3)." }
            && reply.ToolUses.SequenceEqual(["quote_refund A-100 x9"])
            && results.Count == 2
            && results[0].Content.StartsWith("ArgumentException: ", StringComparison.Ordinal)
            && results[1].Content.StartsWith("ArgumentOutOfRangeException: Order A-100 has 3 unit(s).", StringComparison.Ordinal),
            "Argument binding or handler validation failures were not returned to the model as tool results.");
    }

    [ExampleCase("cookbook.tools.round-budget")]
    internal static async Task RoundBudget()
    {
        var handler = new CookbookScriptedHandler(Enumerable.Range(1, 4)
            .Select(static round => CookbookReplies.ToolCalls(($"call-{round}", "lookup_order", """{"orderId":"A-100"}""")))
            .ToArray());

        var reply = await CookbookToolsExample.AnswerAsync([Settings(handler)], Target, Orders, "Where is A-100?");

        ExampleSupport.Require(reply is { Text: null, Failure: ToolLoopException { Category: "tool_loop" } }
            && reply.ToolUses.Count == 4
            && reply.Totals.Requests == 4
            && handler.Requests.Count == 4
            && handler.Remaining == 0
            && handler.DisposeCount == 1,
            "The fourth round's tool calls did not end the loop at its round budget.");
    }

    [ExampleCase("cookbook.tools.unknown-tool")]
    internal static async Task UnknownTool()
    {
        var handler = new CookbookScriptedHandler(
            CookbookReplies.ToolCalls(("call-1", "cancel_order", """{"orderId":"A-100"}""")));

        var reply = await CookbookToolsExample.AnswerAsync([Settings(handler)], Target, Orders, "Cancel A-100.");

        ExampleSupport.Require(reply is { Text: null, Failure: ToolLoopException failure }
            && failure.Message.Contains("cancel_order", StringComparison.Ordinal)
            && reply.ToolUses.Count == 0
            && handler.Requests.Count == 1,
            "A call to an unregistered tool was not refused.");
    }

    [ExampleCase("cookbook.tools.cancellation-reaches-handler")]
    internal static async Task CancellationReachesHandler()
    {
        var handler = new CookbookScriptedHandler(
            CookbookReplies.ToolCalls(("call-1", "lookup_order", """{"orderId":"A-100"}""")));
        var store = new StallingOrderStore();
        using var cancellation = new CancellationTokenSource();
        var answer = CookbookToolsExample.AnswerAsync([Settings(handler)], Target, store, "Where is A-100?", cancellation.Token);
        await store.Entered.Task.WaitAsync(TimeSpan.FromSeconds(10));
        cancellation.Cancel();

        Exception? failure = null;
        try
        {
            await answer;
        }
        catch (OperationCanceledException exception)
        {
            failure = exception;
        }

        ExampleSupport.Require(failure is OperationCanceledException cancelled
            && cancelled.CancellationToken == cancellation.Token
            && store.ObservedCancellation
            && handler.Requests.Count == 1
            && handler.DisposeCount == 1,
            "Caller cancellation did not reach the running handler or did not surface as cancellation.");
    }

    private static ProviderSettings Settings(HttpMessageHandler transport) =>
        ProviderSettings.Of("openai-compat", "https://support.offline/v1", transport: transport, alias: "support");

    private static List<(string CallId, string Content)> ToolMessages(CookbookRequest request) =>
        request.Json().GetProperty("messages").EnumerateArray()
            .Where(static message => message.GetProperty("role").GetString() == "tool")
            .Select(static message => (message.GetProperty("tool_call_id").GetString()!, message.GetProperty("content").GetString()!))
            .ToList();

    private sealed class StallingOrderStore : ICookbookOrderStore
    {
        internal TaskCompletionSource Entered { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);

        internal bool ObservedCancellation { get; private set; }

        public async Task<CookbookOrder?> FindAsync(string orderId, CancellationToken cancellationToken)
        {
            Entered.TrySetResult();
            try
            {
                await Task.Delay(Timeout.Infinite, cancellationToken);
            }
            catch (OperationCanceledException)
            {
                ObservedCancellation = true;
                throw;
            }

            return null;
        }
    }
}
