namespace AnyInfer.Examples;

/// <summary>Runs a bounded registered-tool conversation through the public async client.</summary>
public static class ToolLoopExample
{
    /// <summary>Registers one bounded tool and returns the final generation within at most two rounds.</summary>
    public static async Task<ToolLoopObservation> RunAsync(
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
            return ReadWeather(city);
        }), name: "read_weather", description: "Returns one bounded offline weather observation.");
        await using var client = new AsyncClient([settings]);
        var generation = await client.RunToolsAsync(
            "What is the weather in Boston?",
            [weather],
            target: target,
            maxRounds: 2,
            cancellationToken: cancellationToken);
        return new ToolLoopObservation(generation, handlerCalls);
    }

    private static string ReadWeather(string city) => city == "Boston" ? "clear" : "unknown";
}

/// <summary>Contains the terminal tool-loop generation and the application handler invocation count.</summary>
public sealed record ToolLoopObservation(Generation Generation, int HandlerCalls);
