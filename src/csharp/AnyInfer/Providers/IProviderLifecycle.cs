using AnyInfer.Capabilities;

namespace AnyInfer.Providers;

/// <summary>Provides optional explicit discovery and health operations for a provider adapter.</summary>
/// <remarks>
/// The client calls these only from its explicit model-listing and health calls; an adapter that does not
/// implement this interface makes those calls fail with <see cref="UnsupportedInputException"/>.
/// </remarks>
public interface IProviderLifecycle
{
    /// <summary>Lists the provider's currently discovered models.</summary>
    /// <param name="cancellationToken">Cancels the listing request.</param>
    /// <returns>
    /// Listed models. Facts a listing reports belong at <see cref="Provenance.Discovered"/> provenance; the client
    /// records them as given, so an implementation reports only what the listing states.
    /// </returns>
    ValueTask<IReadOnlyList<DiscoveredModel>> ListModelsAsync(CancellationToken cancellationToken = default);

    /// <summary>Gets the provider's current health observation.</summary>
    /// <param name="cancellationToken">Cancels the readiness check.</param>
    /// <returns>A cheap readiness observation; reachability does not prove that generation will succeed.</returns>
    ValueTask<Health> HealthAsync(CancellationToken cancellationToken = default);
}
