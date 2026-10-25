namespace AnyInfer.Examples;

/// <summary>Configures route policy and reads what each target attempt did.</summary>
public static class RouteFailureExample
{
    // --8<-- [start:default-route]
    /// <summary>Generates through a client-wide default route; the call itself names no target or route.</summary>
    public static async Task<Generation> GenerateWithDefaultRouteAsync(
        IEnumerable<ProviderSettings> providers,
        IEnumerable<string> targets,
        CancellationToken cancellationToken = default)
    {
        await using var client = new AsyncClient(providers, route: new Route(targets));
        return await client.GenerateAsync("Say hello.", cancellationToken: cancellationToken);
    }
    // --8<-- [end:default-route]

    // --8<-- [start:attempts]
    /// <summary>Renders the attempt trail of a successful generation, one target attempt per line.</summary>
    public static IReadOnlyList<string> DescribeAttempts(Generation generation)
    {
        var lines = new List<string>();
        foreach (var attempt in generation.Attempts)
        {
            lines.Add($"{attempt.Target}: {attempt.Outcome}");
            if (attempt.Error?.Snapshot() is { } error)
            {
                lines.Add($"   {error.TypeName}: {error.Detail}");
            }
        }

        return lines;
    }
    // --8<-- [end:attempts]

    // --8<-- [start:total-failure]
    /// <summary>Generates through a route and reports every attempt when all of its targets fail.</summary>
    /// <returns>The winning generation, or <see langword="null"/> when no target succeeded.</returns>
    public static async Task<Generation?> TryGenerateAsync(
        AsyncClient client,
        Route route,
        TextWriter alerts,
        CancellationToken cancellationToken = default)
    {
        try
        {
            return await client.GenerateAsync("Say hello.", route: route, cancellationToken: cancellationToken);
        }
        catch (AllTargetsFailedException failure)
        {
            foreach (var attempt in failure.Attempts)
            {
                alerts.WriteLine($"{attempt.Target}: {attempt.Outcome}: {attempt.Error?.Snapshot().Detail}");
            }

            return null;
        }
    }
    // --8<-- [end:total-failure]

    // --8<-- [start:context-window]
    /// <summary>Sends a context-window overflow to larger models instead of down the general chain.</summary>
    public static Route OverflowAware(IEnumerable<string> targets, IEnumerable<string> largerContextTargets) =>
        new(targets, contextWindowTargets: largerContextTargets);
    // --8<-- [end:context-window]

    // --8<-- [start:retry]
    /// <summary>Tries each target up to three times, backing off 0.5 s, then 1 s, capped at 30 s.</summary>
    public static Route Patient(IEnumerable<string> targets) =>
        new(targets, retry: new Retry(MaxAttempts: 3, BackoffBaseS: 0.5, BackoffMaxS: 30));
    // --8<-- [end:retry]

    // --8<-- [start:health]
    /// <summary>Attempts every target on every call, even one that failed moments ago.</summary>
    public static Route Ungated(IEnumerable<string> targets) =>
        new(targets, healthGate: false);
    // --8<-- [end:health]
}
