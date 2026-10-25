using AnyInfer.Capabilities;

namespace AnyInfer.Examples;

/// <summary>Sends a long prompt to a large-context target only when the usual target's window is too small.</summary>
public static class ContextWindowRouteExample
{
    // --8<-- [start:route]
    /// <summary>Generates through a route whose context-window fallback is a separate, larger-context target.</summary>
    /// <param name="providers">The provider instances both targets name.</param>
    /// <param name="capabilities">
    /// Trusted facts that include each target's context window, keyed by provider instance and then by model.
    /// </param>
    /// <param name="usualTarget">The target ordinary prompts use.</param>
    /// <param name="largeContextTarget">The target used only when the prompt provably does not fit the usual target.</param>
    /// <param name="prompt">The prompt text.</param>
    /// <param name="cancellationToken">Cancels the call.</param>
    /// <returns>The result, whose <see cref="Generation.Target"/> shows which target served it.</returns>
    public static async Task<Generation> GenerateAsync(
        IEnumerable<ProviderSettings> providers,
        IReadOnlyDictionary<string, IReadOnlyDictionary<string, ModelCapabilities>> capabilities,
        string usualTarget,
        string largeContextTarget,
        string prompt,
        CancellationToken cancellationToken = default)
    {
        await using var client = new AsyncClient(providers, capabilityOverrides: capabilities);
        var route = new Route([usualTarget], contextWindowTargets: [largeContextTarget]);
        return await client.GenerateAsync(prompt, route: route, cancellationToken: cancellationToken)
            .ConfigureAwait(false);
    }
    // --8<-- [end:route]
}
