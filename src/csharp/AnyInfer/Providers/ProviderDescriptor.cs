using System.Collections.ObjectModel;

namespace AnyInfer.Providers;

/// <summary>Immutable provider metadata and a lazy adapter factory.</summary>
public sealed record ProviderDescriptor
{
    public ProviderDescriptor(
        string id,
        string displayName,
        Func<ProviderConfig, CancellationToken, ValueTask<IProviderAdapter>> factory,
        IEnumerable<string>? aliases = null,
        ProviderSetupSpec? setup = null,
        string? defaultBaseUrl = null,
        bool requiresBaseUrl = false,
        IReadOnlyDictionary<string, StructuredOutputProfile>? modelCapabilities = null,
        int? maxRepairAttempts = null)
    {
        Id = ProviderSettings.NormalizeId(id, nameof(id));
        ArgumentException.ThrowIfNullOrEmpty(displayName);
        DisplayName = displayName;
        Factory = factory ?? throw new ArgumentNullException(nameof(factory));
        var copiedAliases = (aliases ?? []).Select(alias => ProviderSettings.NormalizeId(alias, nameof(aliases))).ToArray();
        if (copiedAliases.Distinct(StringComparer.Ordinal).Count() != copiedAliases.Length || copiedAliases.Contains(Id, StringComparer.Ordinal))
        {
            throw new ArgumentException("Provider aliases must be unique and differ from the provider ID.", nameof(aliases));
        }

        Aliases = Array.AsReadOnly(copiedAliases);
        Setup = setup ?? new ProviderSetupSpec();
        DefaultBaseUrl = defaultBaseUrl;
        RequiresBaseUrl = requiresBaseUrl;
        ModelCapabilities = new ReadOnlyDictionary<string, StructuredOutputProfile>(
            (modelCapabilities ?? new Dictionary<string, StructuredOutputProfile>())
                .ToDictionary(static pair => pair.Key, static pair => pair.Value, StringComparer.Ordinal));
        if (maxRepairAttempts < 0)
        {
            throw new ArgumentOutOfRangeException(nameof(maxRepairAttempts));
        }

        MaxRepairAttempts = maxRepairAttempts;
    }

    /// <summary>Gets the canonical provider descriptor ID.</summary>
    public string Id { get; }
    /// <summary>Gets the descriptor display name.</summary>
    public string DisplayName { get; }
    /// <summary>Gets the lazy factory, invoked only when a selected target first needs an adapter.</summary>
    public Func<ProviderConfig, CancellationToken, ValueTask<IProviderAdapter>> Factory { get; }
    /// <summary>Gets immutable normalized descriptor aliases.</summary>
    public IReadOnlyList<string> Aliases { get; }
    /// <summary>Gets declarative setup metadata.</summary>
    public ProviderSetupSpec Setup { get; }
    /// <summary>Gets the optional default provider API base URL.</summary>
    public string? DefaultBaseUrl { get; }
    /// <summary>Gets whether setup requires a base URL after defaults are applied.</summary>
    public bool RequiresBaseUrl { get; }
    /// <summary>Gets immutable model capability metadata.</summary>
    public IReadOnlyDictionary<string, StructuredOutputProfile> ModelCapabilities { get; }
    /// <summary>Gets the optional descriptor repair-attempt ceiling.</summary>
    public int? MaxRepairAttempts { get; }
}
