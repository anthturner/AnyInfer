using AnyInfer.Capabilities;
using AnyInfer.Json;

namespace AnyInfer.Examples;

/// <summary>Uses explicit request-policy values without creating a tool-execution loop.</summary>
public static class RequestPolicyExample
{
    /// <summary>Runs one caller-configured generation with explicit spend, routing, cache, and raw-tool inputs.</summary>
    public static async Task<RequestPolicyObservation> RunAsync(
        ProviderSettings settings,
        string target,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(settings);
        ArgumentException.ThrowIfNullOrWhiteSpace(target);

        var ledger = new SpendLedger();
        var tool = new ToolSpec(
            "lookup_weather",
            "Reads a weather observation.",
            new JsonObject([
                new JsonProperty("type", new JsonString("object")),
                new JsonProperty("properties", new JsonObject([
                    new JsonProperty("city", new JsonObject([
                        new JsonProperty("type", new JsonString("string")),
                    ])),
                ])),
            ]));
        var route = new Route([target], contextWindowTargets: [target]);
        var rawCall = new ToolCall("call-1", tool.Name, new JsonObject([
            new JsonProperty("city", new JsonString("Boston")),
        ]));
        var rawResult = new ToolResult(rawCall.Id, "clear", isError: false);
        var request = new GenerationRequest(
            [
                Message.System("Answer concisely."),
                new Message("assistant", [rawCall]),
                new Message("tool", [rawResult]),
                Message.User("What is the weather?"),
            ],
            route,
            stream: true,
            tools: [tool],
            cache: new CachePolicy(CacheMode.Off));

        await using var client = new AsyncClient(
            [settings],
            ledger: ledger,
            spendPolicy: new SpendPolicy(),
            cachePolicy: new CachePolicy());
        var deltas = new List<ToolCallDelta>();
        await using var stream = client.StreamAsync(request, cancellationToken);
        await foreach (var item in stream.WithCancellation(cancellationToken))
        {
            if (item is ToolCallDelta delta)
            {
                deltas.Add(delta);
            }
        }

        return new RequestPolicyObservation(
            stream.Result,
            client.Spend(),
            request.Route,
            request.Cache!,
            tool,
            rawCall,
            rawResult,
            deltas);
    }
}

/// <summary>Contains immutable facts from one request-policy demonstration.</summary>
public sealed record RequestPolicyObservation(
    Generation Generation,
    SpendTotals Totals,
    Route Route,
    CachePolicy RequestCache,
    ToolSpec Tool,
    ToolCall RawCall,
    ToolResult RawResult,
    IReadOnlyList<ToolCallDelta> ToolDeltas);
