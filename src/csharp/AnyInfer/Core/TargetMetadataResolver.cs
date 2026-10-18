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

    internal TargetMetadataResolver(AnyInfer.Catalog.Catalog catalog, ProviderRegistry? registry, Func<IReadOnlyList<CatalogProviderBinding>> bindings, ProviderPool pool)
    {
        _catalog = catalog; _registry = registry; _bindings = bindings; _pool = pool;
    }

    internal TargetMetadata Resolve(string rawTarget, TargetResolutionProfile profile)
    {
        if (profile == TargetResolutionProfile.FrozenV0 || rawTarget.Contains(':')) return _pool.ResolveMetadata(rawTarget);
        if (_registry is null) throw new ConfigException("Catalog aliases require descriptor metadata.");
        var target = _catalog.ResolveTarget(rawTarget, _registry, _bindings());
        return _pool.ResolveMetadata(target);
    }
}
