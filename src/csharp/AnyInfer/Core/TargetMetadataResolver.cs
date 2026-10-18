using AnyInfer.Capabilities;
using AnyInfer.Catalog;
using AnyInfer.Providers;

namespace AnyInfer.Core;

internal enum TargetResolutionProfile { FrozenV0, PublicSdk }

internal sealed class TargetMetadataResolver
{
    private readonly AnyInfer.Catalog.Catalog _catalog;
    private readonly ProviderRegistry? _registry;
    private readonly Func<IReadOnlyList<CatalogProviderBinding>> _bindings;
    private readonly ProviderPool _pool;
    private readonly CapabilityStore? _capabilities;

    internal TargetMetadataResolver(
        AnyInfer.Catalog.Catalog catalog,
        ProviderRegistry? registry,
        Func<IReadOnlyList<CatalogProviderBinding>> bindings,
        ProviderPool pool,
        CapabilityStore? capabilities = null)
    {
        _catalog = catalog;
        _registry = registry;
        _bindings = bindings;
        _pool = pool;
        _capabilities = capabilities;
    }

    internal TargetMetadata Resolve(string rawTarget, TargetResolutionProfile profile)
    {
        TargetMetadata resolved;
        if (profile == TargetResolutionProfile.FrozenV0)
        {
            return _pool.ResolveMetadata(rawTarget);
        }

        if (rawTarget.Contains(':'))
        {
            resolved = _pool.ResolveMetadata(rawTarget);
        }
        else
        {
            if (_registry is null)
            {
                throw new ConfigException("Catalog aliases require descriptor metadata.");
            }

            var target = _catalog.ResolveTarget(rawTarget, _registry, _bindings());
            resolved = _pool.ResolveMetadata(target);
        }

        return ApplyMeasuredStructuredOutput(resolved);
    }

    private TargetMetadata ApplyMeasuredStructuredOutput(TargetMetadata metadata)
    {
        if (_capabilities is null)
        {
            return metadata;
        }

        var capabilities = _capabilities.CapabilitiesFor(
            metadata.Descriptor,
            metadata.Target.ProviderId,
            metadata.Target.Model,
            _pool.EffectiveLocality(metadata));
        var features = capabilities.Features;
        if (features.Value == Feature.None && features.Provenance == Provenance.Default)
        {
            return metadata with { ResolvedCapabilities = capabilities };
        }

        return metadata with
        {
            ResolvedCapabilities = capabilities,
            Capabilities = new StructuredOutputProfile(
                features.Value.HasFlag(Feature.Grammar),
                features.Value.HasFlag(Feature.JsonSchema),
                features.Value.HasFlag(Feature.JsonMode)),
        };
    }
}
