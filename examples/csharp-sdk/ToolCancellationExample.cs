namespace AnyInfer.Examples;

/// <summary>Registers a tool handler that passes the loop's cancellation token to application I/O.</summary>
public static class ToolCancellationExample
{
    // --8<-- [start:handler]
    /// <summary>Runs a tool loop whose forecast tool forwards the loop's token to the forecast service.</summary>
    /// <param name="settings">The provider instance to generate with.</param>
    /// <param name="target">The target to generate with.</param>
    /// <param name="forecasts">The application's asynchronous forecast service.</param>
    /// <param name="cancellationToken">Cancels the loop, including a running forecast call.</param>
    public static async Task<Generation> RunAsync(
        ProviderSettings settings,
        string target,
        Func<string, CancellationToken, Task<string>> forecasts,
        CancellationToken cancellationToken = default)
    {
        // The CancellationToken parameter is not in the tool's schema: the loop supplies its own token.
        var forecast = Tool.From(
            (Func<string, CancellationToken, Task<string>>)((city, token) => forecasts(city, token)),
            name: "read_forecast",
            description: "Returns tomorrow's forecast for one city.");
        await using var client = new AsyncClient([settings]);
        return await client.RunToolsAsync(
            "Will it rain in Boston tomorrow?",
            [forecast],
            target: target,
            cancellationToken: cancellationToken);
    }
    // --8<-- [end:handler]
}
