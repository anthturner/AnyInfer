using AnyInfer.Providers;
using PeterO.Numbers;

namespace AnyInfer.Capabilities;

internal static class CapabilityAssembler
{
    internal static ModelCapabilities Assemble(ProviderDescriptor descriptor, string instanceId, string model, IReadOnlyDictionary<string, ModelCapabilities>? discovered, IReadOnlyDictionary<string, ModelCapabilities>? probed, PricingTable pricing, IReadOnlyDictionary<string, ModelCapabilities>? overrides, ProviderLocality locality)
    {
        if (string.Equals(model, "auto", StringComparison.OrdinalIgnoreCase))
        {
            var names = descriptor.StaticCapabilities.Keys.Concat(discovered?.Keys ?? []).Concat(probed?.Keys ?? []).Where(static name => !string.Equals(name, "auto", StringComparison.OrdinalIgnoreCase)).Distinct(StringComparer.Ordinal).ToArray();
            return names.Length == 0 ? descriptor.DefaultCapabilities : ModelCapabilities.Conjunction(names.Select(name => Assemble(descriptor, instanceId, name, discovered, probed, pricing, overrides, locality)).ToArray());
        }
        var result = descriptor.DefaultCapabilities;
        if (descriptor.StaticCapabilities.TryGetValue(model, out var stat)) result = result.Overlay(stat);
        var price = pricing.Lookup(instanceId, model);
        if (price is not null && price.Outranks(result.Pricing)) result = ReplacePricing(result, price);
        if (discovered is not null && discovered.TryGetValue(model, out var found)) result = result.Overlay(found);
        if (probed is not null && probed.TryGetValue(model, out var measured)) result = result.Overlay(measured);
        if (locality == ProviderLocality.Local && result.Pricing is null) result = ReplacePricing(result, new Sourced<Pricing>(new Pricing(EDecimal.Zero, EDecimal.Zero), Provenance.Catalog));
        if (overrides is not null && overrides.TryGetValue(model, out var configured)) result = ApplyOverride(result, configured);
        return result;
    }

    private static ModelCapabilities ApplyOverride(ModelCapabilities value, ModelCapabilities configured)
    {
        return new ModelCapabilities(
            Override(configured.ContextWindow) ?? value.ContextWindow,
            Override(configured.MaxOutputTokens) ?? value.MaxOutputTokens,
            configured.Features.Value == Feature.None ? value.Features : new Sourced<Feature>(configured.Features.Value, Provenance.Override),
            Override(configured.Pricing) ?? value.Pricing,
            Override(configured.DefaultTemperature) ?? value.DefaultTemperature,
            Override(configured.DefaultTopP) ?? value.DefaultTopP,
            configured.Local ?? value.Local,
            Override(configured.Operations) ?? value.Operations,
            value.Embedding);
    }

    private static ModelCapabilities ReplacePricing(ModelCapabilities value, Sourced<Pricing> pricing) =>
        new(value.ContextWindow, value.MaxOutputTokens, value.Features, pricing, value.DefaultTemperature,
            value.DefaultTopP, value.Local, value.Operations, value.Embedding);

    private static Sourced<T>? Override<T>(Sourced<T>? value) =>
        value is null ? null : new Sourced<T>(value.Value, Provenance.Override);
}
