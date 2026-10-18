using AnyInfer.Capabilities;

namespace AnyInfer.Providers;

/// <summary>Provides optional explicit discovery and health operations for a provider adapter.</summary>
public interface IProviderLifecycle
{
    /// <summary>Lists the provider's currently discovered models.</summary>
    ValueTask<IReadOnlyList<DiscoveredModel>> ListModelsAsync(CancellationToken cancellationToken = default);

    /// <summary>Gets the provider's current health observation.</summary>
    ValueTask<Health> HealthAsync(CancellationToken cancellationToken = default);
}
