using System.Collections.Frozen;
using System.Collections.ObjectModel;
using AnyInfer.Capabilities;
using AnyInfer.Json;

namespace AnyInfer.Providers;

/// <summary>Immutable provider metadata and a lazy adapter factory.</summary>
public sealed record ProviderDescriptor
{
    public ProviderDescriptor(
        string id,
        string displayName,
        Func<ProviderConfig, CancellationToken, ValueTask<IAsyncDisposable>> factory,
        IEnumerable<string>? aliases = null,
        ProviderSetupSpec? setup = null,
        string? defaultBaseUrl = null,
        bool requiresBaseUrl = false,
        IReadOnlyDictionary<string, StructuredOutputProfile>? structuredOutputProfiles = null,
        int? maxRepairAttempts = null,
        ProviderLocality locality = ProviderLocality.Hosted,
        ModelCapabilities? defaultCapabilities = null,
        IReadOnlyDictionary<string, ModelCapabilities>? staticCapabilities = null,
        IEnumerable<InferenceOperation>? operations = null,
        IReadOnlyDictionary<string, EmbeddingCapabilities>? staticEmbeddingCapabilities = null,
        IReadOnlyDictionary<string, RerankCapabilities>? staticRerankCapabilities = null,
        TokenCalibration? tokenCalibration = null,
        RateLimitHeaders? rateLimitHeaders = null,
        CacheMechanism? cacheMechanism = null,
        int cacheMaxMarks = 0,
        long cacheMinTokens = 0,
        bool governsOwnTransport = false,
        Func<string?, JsonObject>? reasoningTranslator = null,
        IEnumerable<string>? ignoredParameters = null,
        IEnumerable<string>? serverTools = null,
        ModelInventoryKind modelInventory = ModelInventoryKind.Served,
        bool honorsConnectionSettings = true)
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
        StructuredOutputProfiles = new ReadOnlyDictionary<string, StructuredOutputProfile>(
            (structuredOutputProfiles ?? new Dictionary<string, StructuredOutputProfile>())
                .ToDictionary(static pair => pair.Key, static pair => pair.Value, StringComparer.Ordinal));
        if (maxRepairAttempts < 0)
        {
            throw new ArgumentOutOfRangeException(nameof(maxRepairAttempts));
        }

        MaxRepairAttempts = maxRepairAttempts;
        if (!Enum.IsDefined(locality)) throw new ArgumentOutOfRangeException(nameof(locality));
        Locality = locality;
        DefaultCapabilities = defaultCapabilities ?? new ModelCapabilities();
        StaticCapabilities = Copy(staticCapabilities);
        Operations = (operations ?? [InferenceOperation.Generation]).ToFrozenSet();
        StaticEmbeddingCapabilities = Copy(staticEmbeddingCapabilities);
        StaticRerankCapabilities = Copy(staticRerankCapabilities);
        foreach (var operation in Operations)
        {
            if (!Enum.IsDefined(operation))
            {
                throw new ArgumentOutOfRangeException(nameof(operations));
            }
        }

        TokenCalibration = tokenCalibration ?? new TokenCalibration();
        RateLimitHeaders = rateLimitHeaders ?? new RateLimitHeaders();
        if (cacheMechanism is { } mechanism && !Enum.IsDefined(mechanism))
        {
            throw new ArgumentOutOfRangeException(nameof(cacheMechanism));
        }

        if (cacheMaxMarks < 0)
        {
            throw new ArgumentOutOfRangeException(nameof(cacheMaxMarks));
        }

        if (cacheMinTokens < 0)
        {
            throw new ArgumentOutOfRangeException(nameof(cacheMinTokens));
        }

        CacheMechanism = cacheMechanism;
        CacheMaxMarks = cacheMaxMarks;
        CacheMinTokens = cacheMinTokens;
        GovernsOwnTransport = governsOwnTransport;
        ReasoningTranslator = reasoningTranslator ?? (static _ => new JsonObject([]));
        IgnoredParameters = Array.AsReadOnly((ignoredParameters ?? []).Select(static value => value ?? throw new ArgumentException("Ignored parameters cannot contain null references.")).ToArray());
        ServerTools = (serverTools ?? []).Select(static value => value ?? throw new ArgumentException("Server tools cannot contain null references.")).ToFrozenSet(StringComparer.Ordinal);
        if (!Enum.IsDefined(modelInventory))
        {
            throw new ArgumentOutOfRangeException(nameof(modelInventory));
        }

        ModelInventory = modelInventory;
        HonorsConnectionSettings = honorsConnectionSettings;
    }

    /// <summary>Gets the canonical provider descriptor ID.</summary>
    public string Id { get; }
    /// <summary>Gets the descriptor display name.</summary>
    public string DisplayName { get; }
    /// <summary>Gets the lazy factory, invoked only when a selected target first needs an adapter.</summary>
    public Func<ProviderConfig, CancellationToken, ValueTask<IAsyncDisposable>> Factory { get; }
    /// <summary>Gets immutable normalized descriptor aliases.</summary>
    public IReadOnlyList<string> Aliases { get; }
    /// <summary>Gets declarative setup metadata.</summary>
    public ProviderSetupSpec Setup { get; }
    /// <summary>Gets the optional default provider API base URL.</summary>
    public string? DefaultBaseUrl { get; }
    /// <summary>Gets whether setup requires a base URL after defaults are applied.</summary>
    public bool RequiresBaseUrl { get; }
    /// <summary>Gets immutable structured-output profiles keyed by exact model name.</summary>
    public IReadOnlyDictionary<string, StructuredOutputProfile> StructuredOutputProfiles { get; }
    /// <summary>Gets the optional descriptor repair-attempt ceiling.</summary>
    public int? MaxRepairAttempts { get; }
    /// <summary>Gets the descriptor's default locality.</summary>
    public ProviderLocality Locality { get; }
    /// <summary>Gets baseline facts for models without a static row.</summary>
    public ModelCapabilities DefaultCapabilities { get; }
    /// <summary>Gets immutable static facts keyed by exact model name.</summary>
    public IReadOnlyDictionary<string, ModelCapabilities> StaticCapabilities { get; }
    /// <summary>Gets immutable declared operations, defaulting to generation.</summary>
    public IReadOnlySet<InferenceOperation> Operations { get; }
    /// <summary>Gets static embedding facts keyed by exact model name.</summary>
    public IReadOnlyDictionary<string, EmbeddingCapabilities> StaticEmbeddingCapabilities { get; }
    /// <summary>Gets static rerank facts keyed by exact model name.</summary>
    public IReadOnlyDictionary<string, RerankCapabilities> StaticRerankCapabilities { get; }
    /// <summary>Gets provider token calibration metadata, defaulting to identity calibration.</summary>
    public TokenCalibration TokenCalibration { get; }
    /// <summary>Gets declared rate-limit header names, empty when the provider declares none.</summary>
    public RateLimitHeaders RateLimitHeaders { get; }
    /// <summary>Gets the provider's optional prompt-cache mechanism.</summary>
    public CacheMechanism? CacheMechanism { get; }
    /// <summary>Gets the provider cache-mark ceiling, or zero to use the request policy ceiling.</summary>
    public int CacheMaxMarks { get; }
    /// <summary>Gets the provider cache-mark token floor, or zero to use the request policy floor.</summary>
    public long CacheMinTokens { get; }
    /// <summary>Gets whether the adapter owns its HTTP transport and requires an outer pacing slot.</summary>
    public bool GovernsOwnTransport { get; }
    /// <summary>Gets the descriptor translation from normalized reasoning effort to wire fields.</summary>
    public Func<string?, JsonObject> ReasoningTranslator { get; }
    /// <summary>Gets immutable parameter names this descriptor intentionally ignores.</summary>
    public IReadOnlyList<string> IgnoredParameters { get; }
    /// <summary>Gets provider-run tool kinds the descriptor can place on the wire.</summary>
    public IReadOnlySet<string> ServerTools { get; }
    /// <summary>Gets the descriptive category of model inventory this descriptor exposes.</summary>
    public ModelInventoryKind ModelInventory { get; }
    /// <summary>Gets whether this descriptor honors SDK-owned connection settings.</summary>
    public bool HonorsConnectionSettings { get; }
    // Cooperative factory contract: only the pool disposes an opted-in configured handler.
    internal bool PoolOwnsConfiguredTransport { get; init; }

    private static IReadOnlyDictionary<string, TValue> Copy<TValue>(IReadOnlyDictionary<string, TValue>? values) =>
        new ReadOnlyDictionary<string, TValue>(new Dictionary<string, TValue>(values ?? new Dictionary<string, TValue>(), StringComparer.Ordinal));
}
