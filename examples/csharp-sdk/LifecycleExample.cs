using AnyInfer;
using AnyInfer.Capabilities;

namespace AnyInfer.Examples;

/// <summary>Shows explicit model discovery and health checks through the public clients.</summary>
public static class LifecycleExample
{
    /// <summary>Lists models and reads health through an asynchronous client that it owns.</summary>
    public static async Task<LifecycleObservation> RunAsync(
        ProviderSettings settings,
        string providerId,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(settings);
        ArgumentException.ThrowIfNullOrWhiteSpace(providerId);

        await using var client = new AsyncClient([settings]);
        var models = await client.ModelsAsync(providerId, cancellationToken: cancellationToken).ConfigureAwait(false);
        var health = await client.HealthAsync(providerId, cancellationToken).ConfigureAwait(false);
        return new LifecycleObservation(models, health);
    }

    /// <summary>Lists models and reads health through a synchronous client that it owns.</summary>
    public static LifecycleObservation Run(
        ProviderSettings settings,
        string providerId,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(settings);
        ArgumentException.ThrowIfNullOrWhiteSpace(providerId);

        using var client = new Client([settings]);
        var models = client.Models(providerId, cancellationToken: cancellationToken);
        var health = client.Health(providerId, cancellationToken);
        return new LifecycleObservation(models, health);
    }
}

/// <summary>Contains immutable public model-list and health observations.</summary>
public sealed record LifecycleObservation(IReadOnlyList<DiscoveredModel> Models, Health Health);
