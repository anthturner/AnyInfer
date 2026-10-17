namespace AnyInfer.Examples;

/// <summary>Runs a configured route with ordered fallback targets.</summary>
public static class RoutingExample
{
    /// <summary>Generates through the supplied route and returns the successful terminal result.</summary>
    public static async Task<Generation> RunAsync(
        IEnumerable<ProviderSettings> providers,
        Route route,
        CancellationToken cancellationToken = default)
    {
        await using var client = new AsyncClient(providers);
        return await client.GenerateAsync("Say hello.", route: route, cancellationToken: cancellationToken);
    }
}
