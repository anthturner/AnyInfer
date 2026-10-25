namespace AnyInfer.Examples;

/// <summary>Runs the bounded registered-tool conversation through the synchronous facade.</summary>
public static class SyncToolLoopExample
{
    /// <summary>Registers one tool and blocks until the loop returns its final generation.</summary>
    public static ToolLoopObservation Run(
        ProviderSettings settings,
        string target,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(settings);
        ArgumentException.ThrowIfNullOrWhiteSpace(target);
        var handlerCalls = 0;
        var weather = Tool.From((Func<string, string>)(city =>
        {
            handlerCalls++;
            return city == "Boston" ? "clear" : "unknown";
        }), name: "read_weather", description: "Returns one bounded offline weather observation.");
        using var client = new Client([settings]);
        var generation = client.RunTools(
            "What is the weather in Boston?",
            [weather],
            target: target,
            maxRounds: 2,
            cancellationToken: cancellationToken);
        return new ToolLoopObservation(generation, handlerCalls);
    }
}
