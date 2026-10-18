using AnyInfer;
using AnyInfer.Capabilities;
using AnyInfer.Catalog;
using AnyInfer.Providers;

namespace AnyInfer.Examples;

/// <summary>Shows pure catalog, capability, and pricing queries without dispatching a request.</summary>
public static class CatalogExample
{
    /// <summary>Resolves an alias and reads its assembled metadata without constructing an adapter.</summary>
    public static CatalogObservation Inspect(
        global::AnyInfer.Catalog.Catalog catalog,
        PricingTable pricingTable,
        ProviderSettings settings,
        ProviderRegistry registry)
    {
        ArgumentNullException.ThrowIfNull(catalog);
        ArgumentNullException.ThrowIfNull(pricingTable);
        ArgumentNullException.ThrowIfNull(settings);
        ArgumentNullException.ThrowIfNull(registry);

        using var client = new Client([settings], registry, catalog: catalog, pricingTable: pricingTable);
        var target = client.Resolve("tier");
        var capabilities = client.Capabilities("tier");
        return new CatalogObservation(target, capabilities, capabilities.Pricing);
    }
}

/// <summary>Contains the immutable public facts returned by <see cref="CatalogExample"/>.</summary>
public sealed record CatalogObservation(
    ResolvedTarget Target,
    ModelCapabilities Capabilities,
    Sourced<Pricing>? Pricing);
