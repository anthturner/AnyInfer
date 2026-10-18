using AnyInfer.Providers;

namespace AnyInfer.Capabilities;

internal sealed class CapabilityStore
{
    private readonly object _gate = new();
    private readonly PricingTable _pricing;
    private readonly IReadOnlyDictionary<string, IReadOnlyDictionary<string, ModelCapabilities>> _overrides;
    private readonly Dictionary<string, Dictionary<string, ModelCapabilities>> _discovered = new(StringComparer.Ordinal);
    private readonly Dictionary<string, Dictionary<string, ModelCapabilities>> _probed = new(StringComparer.Ordinal);

    internal CapabilityStore(PricingTable? pricing = null, IReadOnlyDictionary<string, IReadOnlyDictionary<string, ModelCapabilities>>? overrides = null)
    {
        _pricing = pricing ?? PricingTable.LoadDefault();
        _overrides = CopyOverrides(overrides);
    }

    internal void RecordDiscovery(string instanceId, IReadOnlyList<DiscoveredModel> models)
    {
        lock (_gate)
        {
            var layer = _discovered.TryGetValue(instanceId, out var existing) ? existing : _discovered[instanceId] = new(StringComparer.Ordinal);
            foreach (var model in models) if (model.Capabilities is not null) layer[model.Id] = model.Capabilities;
        }
    }

    internal void RecordProbe(string instanceId, string model, ModelCapabilities capabilities)
    {
        ArgumentNullException.ThrowIfNull(instanceId);
        ArgumentNullException.ThrowIfNull(model);
        ArgumentNullException.ThrowIfNull(capabilities);
        lock (_gate)
        {
            var layer = _probed.TryGetValue(instanceId, out var existing)
                ? existing
                : _probed[instanceId] = new Dictionary<string, ModelCapabilities>(StringComparer.Ordinal);
            layer[model] = capabilities;
        }
    }

    internal bool? DiscoveredHasModel(string instanceId, string model)
    {
        lock (_gate) return _discovered.TryGetValue(instanceId, out var layer) ? layer.ContainsKey(model) : null;
    }

    internal void Invalidate(string? instanceId = null)
    {
        lock (_gate)
        {
            if (instanceId is null) { _discovered.Clear(); _probed.Clear(); }
            else { _discovered.Remove(instanceId); _probed.Remove(instanceId); }
        }
    }

    internal ModelCapabilities CapabilitiesFor(ProviderDescriptor? descriptor, string instanceId, string model, ProviderLocality locality)
    {
        lock (_gate)
        {
            _discovered.TryGetValue(instanceId, out var discovered);
            _probed.TryGetValue(instanceId, out var probed);
            _overrides.TryGetValue(instanceId, out var configured);
            if (descriptor is null)
            {
                var result = new ModelCapabilities();
                if (discovered is not null && discovered.TryGetValue(model, out var found)) result = result.Overlay(found);
                if (probed is not null && probed.TryGetValue(model, out var measured)) result = result.Overlay(measured);
                if (configured is not null && configured.TryGetValue(model, out var overrideValue)) result = result.Overlay(overrideValue);
                return result;
            }
            return CapabilityAssembler.Assemble(descriptor, instanceId, model, discovered, probed, _pricing, configured, locality);
        }
    }

    private static IReadOnlyDictionary<string, IReadOnlyDictionary<string, ModelCapabilities>> CopyOverrides(IReadOnlyDictionary<string, IReadOnlyDictionary<string, ModelCapabilities>>? values)
    {
        var copied = new Dictionary<string, IReadOnlyDictionary<string, ModelCapabilities>>(StringComparer.Ordinal);
        foreach (var pair in values ?? new Dictionary<string, IReadOnlyDictionary<string, ModelCapabilities>>())
        {
            var key = ProviderSettings.NormalizeId(pair.Key, nameof(values));
            if (!copied.TryAdd(key, new Dictionary<string, ModelCapabilities>(pair.Value, StringComparer.Ordinal))) throw new ArgumentException("Capability override instance keys cannot collide after normalization.", nameof(values));
        }
        return copied;
    }
}
