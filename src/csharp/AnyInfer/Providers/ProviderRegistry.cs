using System.Collections.ObjectModel;

namespace AnyInfer.Providers;

/// <summary>Collision-safe registry of immutable provider descriptors.</summary>
public sealed class ProviderRegistry
{
    private readonly object _gate = new();
    private Dictionary<string, ProviderDescriptor> _descriptors = new(StringComparer.Ordinal);
    private Dictionary<string, string> _identifiers = new(StringComparer.Ordinal);

    public ProviderRegistry(IEnumerable<ProviderDescriptor>? descriptors = null)
    {
        foreach (var descriptor in descriptors ?? [])
        {
            Register(descriptor);
        }
    }

    /// <summary>Gets an immutable sorted snapshot of registered provider descriptors.</summary>
    public IReadOnlyList<ProviderDescriptor> Descriptors
    {
        get
        {
            lock (_gate)
            {
                return Array.AsReadOnly(_descriptors.Values.OrderBy(static descriptor => descriptor.Id, StringComparer.Ordinal).ToArray());
            }
        }
    }

    /// <summary>Registers one collision-free provider descriptor.</summary>
    public void Register(ProviderDescriptor descriptor)
    {
        ArgumentNullException.ThrowIfNull(descriptor);
        lock (_gate)
        {
            if (_descriptors.ContainsKey(descriptor.Id))
            {
                throw new ArgumentException("A provider with this ID is already registered.", nameof(descriptor));
            }

            var identifiers = new[] { descriptor.Id }.Concat(descriptor.Aliases).ToArray();
            foreach (var identifier in identifiers)
            {
                if (_identifiers.ContainsKey(identifier))
                {
                    throw new ArgumentException("Provider IDs and aliases must be globally unique.", nameof(descriptor));
                }
            }

            var nextDescriptors = new Dictionary<string, ProviderDescriptor>(_descriptors, StringComparer.Ordinal)
            {
                [descriptor.Id] = descriptor,
            };
            var nextIdentifiers = new Dictionary<string, string>(_identifiers, StringComparer.Ordinal);
            foreach (var identifier in identifiers)
            {
                nextIdentifiers.Add(identifier, descriptor.Id);
            }

            _descriptors = nextDescriptors;
            _identifiers = nextIdentifiers;
        }
    }

    /// <summary>Gets a descriptor by canonical ID or registered alias.</summary>
    public ProviderDescriptor Get(string providerId)
    {
        var canonical = ResolveId(providerId);
        lock (_gate)
        {
            return _descriptors[canonical];
        }
    }

    /// <summary>Reports whether a canonical ID or alias is registered.</summary>
    public bool Has(string providerId)
    {
        ArgumentNullException.ThrowIfNull(providerId);
        var normalized = NormalizeProviderId(providerId);
        lock (_gate)
        {
            return _identifiers.ContainsKey(normalized);
        }
    }

    /// <summary>Resolves a canonical descriptor ID from an ID or alias.</summary>
    public string ResolveId(string providerId)
    {
        ArgumentNullException.ThrowIfNull(providerId);
        var normalized = NormalizeProviderId(providerId);
        lock (_gate)
        {
            if (_identifiers.TryGetValue(normalized, out var canonical))
            {
                return canonical;
            }
        }

        throw new ConfigException(
            "The target cannot be configured.",
            detail: "Target provider is not registered.",
            hint: "Use a registered provider:model target.");
    }

    /// <summary>Normalizes a provider ID according to the public settings contract.</summary>
    public static string NormalizeProviderId(string value) => ProviderSettings.NormalizeId(value, nameof(value));

    /// <summary>Creates the bounded built-in descriptor registry.</summary>
    public static ProviderRegistry CreateDefault() => new([
        new ProviderDescriptor(
            "openai-compat",
            "OpenAI-compatible",
            static (config, cancellationToken) => new ValueTask<IProviderAdapter>(OpenAIChatAdapter.Create(config, cancellationToken)),
            aliases: ["openai-compatible", "oai-compat"],
            setup: new ProviderSetupSpec([
                new SetupField("base_url", "Base URL", "endpoint", required: true),
                new SetupField("api_key", "API key", "secret"),
            ]),
            requiresBaseUrl: true)
        {
            PoolOwnsConfiguredTransport = true,
        },
    ]);
}
