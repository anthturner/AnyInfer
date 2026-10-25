using System.Collections.Frozen;
using System.Collections.ObjectModel;
using AnyInfer.Capabilities;
using AnyInfer.Json;

namespace AnyInfer.Providers;

/// <summary>Immutable provider metadata and a lazy adapter factory.</summary>
/// <remarks>
/// A descriptor is inert data until it is registered in a <see cref="ProviderRegistry"/> that a client uses;
/// constructing one performs no I/O and starts nothing.
/// </remarks>
public sealed record ProviderDescriptor
{
    /// <summary>Creates a validated, immutable provider descriptor, copying every collection argument.</summary>
    /// <param name="id">Canonical provider identifier; trimmed, lower-cased, and with underscores replaced by hyphens.</param>
    /// <param name="displayName">Human-readable provider name.</param>
    /// <param name="factory">
    /// Lazy adapter factory. A client calls it when a target on a configured instance first needs an adapter,
    /// passing the resolved <see cref="ProviderConfig"/> and a cancellation token, and reuses the adapter it
    /// returns. That adapter must implement <see cref="IGeneratesText"/>, <see cref="IEmbedsText"/>, or
    /// <see cref="IReranksText"/> for each declared operation, and may implement <see cref="IProviderLifecycle"/>;
    /// the client owns and disposes it.
    /// </param>
    /// <param name="aliases">Additional identifiers accepted for this provider, normalized like <paramref name="id"/>; <see langword="null"/> means none.</param>
    /// <param name="setup">Declarative setup metadata; <see langword="null"/> declares no fields.</param>
    /// <param name="defaultBaseUrl">Base URL used when an instance configures none, or <see langword="null"/>.</param>
    /// <param name="requiresBaseUrl">Whether a base URL must be present after <paramref name="defaultBaseUrl"/> is applied.</param>
    /// <param name="structuredOutputProfiles">
    /// Native structured-output mechanisms keyed by exact model name; a model without a row uses prompt-based
    /// structured output. <see langword="null"/> means none.
    /// </param>
    /// <param name="maxRepairAttempts">
    /// Ceiling on structured-output repair round trips, or <see langword="null"/> for no provider ceiling; a larger
    /// requested budget is lowered and reported as a dropped parameter.
    /// </param>
    /// <param name="locality">
    /// Where the provider normally runs. A <see cref="ProviderLocality.Local"/> provider reached through a
    /// non-loopback base URL is treated as remote, and a locally served model with no other price is priced at zero.
    /// </param>
    /// <param name="defaultCapabilities">Baseline facts for every model; <see langword="null"/> leaves every fact unknown.</param>
    /// <param name="staticCapabilities">Facts keyed by exact model name, layered over the baseline with the provenance they carry; <see langword="null"/> means none.</param>
    /// <param name="operations">Implemented inference operations; <see langword="null"/> declares generation only.</param>
    /// <param name="staticEmbeddingCapabilities">Embedding facts keyed by exact model name; <see langword="null"/> means none.</param>
    /// <param name="staticRerankCapabilities">Rerank facts keyed by exact model name; <see langword="null"/> means none.</param>
    /// <param name="tokenCalibration">Envelope token calibration; <see langword="null"/> uses identity calibration.</param>
    /// <param name="rateLimitHeaders">Rate-limit response header names; <see langword="null"/> declares none.</param>
    /// <param name="cacheMechanism">Prompt-cache mechanism, or <see langword="null"/> when the provider has none.</param>
    /// <param name="cacheMaxMarks">Maximum explicit cache marks per request, or zero to use the cache policy's ceiling.</param>
    /// <param name="cacheMinTokens">Minimum estimated tokens for a cache mark, or zero to use the cache policy's floor.</param>
    /// <param name="governsOwnTransport">
    /// Whether the adapter owns its HTTP transport, so configured pacing acquires a slot around each call instead
    /// of inside the SDK-created handler.
    /// </param>
    /// <param name="reasoningTranslator">
    /// Translation from a normalized reasoning effort to provider wire fields, applied only when the model may
    /// reason; <see langword="null"/> sends no reasoning fields.
    /// </param>
    /// <param name="ignoredParameters">
    /// Request parameter names, such as <c>temperature</c>, that the provider accepts but ignores; supplying one
    /// is reported as a dropped parameter. <see langword="null"/> means none.
    /// </param>
    /// <param name="serverTools">
    /// Provider-run tool kinds the adapter can place on the wire; a request for any other kind is refused before
    /// dispatch. <see langword="null"/> means none.
    /// </param>
    /// <param name="modelInventory">Descriptive category of the provider's model inventory; it changes no behavior.</param>
    /// <param name="honorsConnectionSettings">
    /// Whether configured proxy, TLS-verification, and client-certificate settings are supported; when
    /// <see langword="false"/>, an instance that sets them without supplying its own transport fails to build.
    /// </param>
    /// <exception cref="ArgumentNullException"><paramref name="id"/>, <paramref name="displayName"/>, or <paramref name="factory"/> is <see langword="null"/>.</exception>
    /// <exception cref="ArgumentException">
    /// <paramref name="id"/> is blank, <paramref name="displayName"/> is empty, aliases repeat or equal the
    /// identifier, or <paramref name="ignoredParameters"/> or <paramref name="serverTools"/> contains <see langword="null"/>.
    /// </exception>
    /// <exception cref="ArgumentOutOfRangeException">
    /// A count is negative, or <paramref name="locality"/>, an operation, <paramref name="cacheMechanism"/>, or
    /// <paramref name="modelInventory"/> is not a defined value.
    /// </exception>
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
    /// <summary>Gets baseline facts every model starts from; a model's static row is layered over them.</summary>
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
