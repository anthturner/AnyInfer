using System.Collections.ObjectModel;
using AnyInfer.Capabilities;

namespace AnyInfer.Providers;

/// <summary>Collision-safe registry of immutable provider descriptors.</summary>
/// <remarks>
/// Registering a descriptor makes its identifier and aliases resolvable; it invokes no factory and performs no
/// I/O. All members are safe to call concurrently. A client built from a registry copies its descriptors when
/// the client is created, so later registrations do not affect existing clients.
/// </remarks>
public sealed class ProviderRegistry
{
    private readonly object _gate = new();
    private Dictionary<string, ProviderDescriptor> _descriptors = new(StringComparer.Ordinal);
    private Dictionary<string, string> _identifiers = new(StringComparer.Ordinal);

    /// <summary>Creates a registry holding the supplied descriptors.</summary>
    /// <param name="descriptors">Descriptors to register in order; <see langword="null"/> creates an empty registry.</param>
    /// <exception cref="ArgumentNullException">A descriptor is <see langword="null"/>.</exception>
    /// <exception cref="ArgumentException">Two descriptors share an identifier or alias.</exception>
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
    /// <param name="descriptor">Descriptor whose identifier and aliases must not collide with any registered identifier or alias.</param>
    /// <exception cref="ArgumentNullException"><paramref name="descriptor"/> is <see langword="null"/>.</exception>
    /// <exception cref="ArgumentException">The descriptor's identifier or an alias is already registered; the registry is unchanged.</exception>
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
    /// <param name="providerId">Provider identifier or alias; normalized with <see cref="NormalizeProviderId"/>.</param>
    /// <returns>The registered descriptor.</returns>
    /// <exception cref="ArgumentNullException"><paramref name="providerId"/> is <see langword="null"/>.</exception>
    /// <exception cref="ArgumentException"><paramref name="providerId"/> is blank.</exception>
    /// <exception cref="ConfigException">No registered descriptor has that identifier or alias.</exception>
    public ProviderDescriptor Get(string providerId)
    {
        var canonical = ResolveId(providerId);
        lock (_gate)
        {
            return _descriptors[canonical];
        }
    }

    /// <summary>Reports whether a canonical ID or alias is registered.</summary>
    /// <param name="providerId">Provider identifier or alias; normalized with <see cref="NormalizeProviderId"/>.</param>
    /// <returns><see langword="true"/> when the identifier or alias is registered.</returns>
    /// <exception cref="ArgumentNullException"><paramref name="providerId"/> is <see langword="null"/>.</exception>
    /// <exception cref="ArgumentException"><paramref name="providerId"/> is blank.</exception>
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
    /// <param name="providerId">Provider identifier or alias; normalized with <see cref="NormalizeProviderId"/>.</param>
    /// <returns>The canonical identifier of the registered descriptor.</returns>
    /// <exception cref="ArgumentNullException"><paramref name="providerId"/> is <see langword="null"/>.</exception>
    /// <exception cref="ArgumentException"><paramref name="providerId"/> is blank.</exception>
    /// <exception cref="ConfigException">No registered descriptor has that identifier or alias.</exception>
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
    /// <param name="value">Identifier to normalize.</param>
    /// <returns>The identifier trimmed, lower-cased, and with underscores replaced by hyphens.</returns>
    /// <exception cref="ArgumentNullException"><paramref name="value"/> is <see langword="null"/>.</exception>
    /// <exception cref="ArgumentException"><paramref name="value"/> is blank after trimming.</exception>
    public static string NormalizeProviderId(string value) => ProviderSettings.NormalizeId(value, nameof(value));

    /// <summary>Creates the bounded built-in descriptor registry.</summary>
    /// <remarks>
    /// The registry contains the chat-only <c>openai-compat</c> generation descriptor, the <c>tei</c>,
    /// <c>voyage</c>, and <c>jina</c> embedding and rerank descriptors, and the reviewed <c>cerebras</c>,
    /// <c>hyperbolic</c>, and <c>nscale</c> generation presets served through the shared chat adapter. Other
    /// compatibility-preset data bundled in the assembly is inert and not registered. Each call returns a new,
    /// independent registry.
    /// </remarks>
    /// <returns>A new registry holding the built-in descriptors.</returns>
    public static ProviderRegistry CreateDefault() => new([
        new ProviderDescriptor(
            "openai-compat",
            "OpenAI-compatible",
            static (config, cancellationToken) => new ValueTask<IAsyncDisposable>(OpenAIChatAdapter.Create(config, cancellationToken)),
            aliases: ["openai-compatible", "oai-compat"],
            setup: new ProviderSetupSpec([
                new SetupField("base_url", "Base URL", "endpoint", required: true),
                new SetupField("api_key", "API key", "secret"),
            ]),
            requiresBaseUrl: true)
        {
            PoolOwnsConfiguredTransport = true,
        },
        new ProviderDescriptor(
            "tei",
            "Text Embeddings Inference",
            static (config, cancellationToken) => new ValueTask<IAsyncDisposable>(TeiAdapter.Create(config, cancellationToken)),
            aliases: ["text-embeddings-inference"],
            setup: new ProviderSetupSpec([
                new SetupField("base_url", "Base URL", "endpoint", required: false, advanced: true, defaultValue: "http://127.0.0.1:8080", helpText: "Defaults to the local TEI server."),
                new SetupField("api_key", "API key", "secret", required: false, advanced: true, placeholder: "env://TEI_API_KEY or a literal key", envVar: "TEI_API_KEY", helpText: "Only when the TEI server was started with an API key."),
            ], modelSelection: "discover-or-manual"),
            defaultBaseUrl: "http://127.0.0.1:8080",
            locality: ProviderLocality.Local,
            operations: [InferenceOperation.Embedding, InferenceOperation.Rerank])
        {
            PoolOwnsConfiguredTransport = true,
        },
        new ProviderDescriptor(
            "voyage",
            "Voyage AI",
            static (config, cancellationToken) => new ValueTask<IAsyncDisposable>(VoyageAdapter.Create(config, cancellationToken)),
            aliases: ["voyageai"],
            setup: new ProviderSetupSpec([
                new SetupField("api_key", "API key", "secret", required: true, placeholder: "env://VOYAGE_API_KEY or a literal key", envVar: "VOYAGE_API_KEY", helpText: "Accepts a literal, env://VAR, or credential://system/name."),
                new SetupField("base_url", "Base URL", "endpoint", required: false, advanced: true, defaultValue: "https://api.voyageai.com/v1", helpText: "Defaults to https://api.voyageai.com/v1."),
            ], modelSelection: "manual-only"),
            defaultBaseUrl: "https://api.voyageai.com/v1",
            locality: ProviderLocality.Hosted,
            operations: [InferenceOperation.Embedding, InferenceOperation.Rerank],
            staticEmbeddingCapabilities: new Dictionary<string, EmbeddingCapabilities>(StringComparer.Ordinal)
            {
                ["voyage-4-large"] = new(maxBatchInputs: 1_000, inputIntents: [EmbeddingInputIntent.Query, EmbeddingInputIntent.Document]),
                ["voyage-4"] = new(maxBatchInputs: 1_000, inputIntents: [EmbeddingInputIntent.Query, EmbeddingInputIntent.Document]),
                ["voyage-4-lite"] = new(maxBatchInputs: 1_000, inputIntents: [EmbeddingInputIntent.Query, EmbeddingInputIntent.Document]),
                ["voyage-3-large"] = new(maxBatchInputs: 1_000, inputIntents: [EmbeddingInputIntent.Query, EmbeddingInputIntent.Document]),
                ["voyage-3.5"] = new(maxBatchInputs: 1_000, inputIntents: [EmbeddingInputIntent.Query, EmbeddingInputIntent.Document]),
                ["voyage-3.5-lite"] = new(maxBatchInputs: 1_000, inputIntents: [EmbeddingInputIntent.Query, EmbeddingInputIntent.Document]),
                ["voyage-code-3"] = new(maxBatchInputs: 1_000, inputIntents: [EmbeddingInputIntent.Query, EmbeddingInputIntent.Document]),
                ["voyage-finance-2"] = new(maxBatchInputs: 1_000, inputIntents: [EmbeddingInputIntent.Query, EmbeddingInputIntent.Document]),
                ["voyage-law-2"] = new(maxBatchInputs: 1_000, inputIntents: [EmbeddingInputIntent.Query, EmbeddingInputIntent.Document]),
            },
            staticRerankCapabilities: new Dictionary<string, RerankCapabilities>(StringComparer.Ordinal)
            {
                ["rerank-2.5"] = new(maxDocuments: 1_000, nativeTopN: true),
                ["rerank-2.5-lite"] = new(maxDocuments: 1_000, nativeTopN: true),
                ["rerank-2"] = new(maxDocuments: 1_000, nativeTopN: true),
                ["rerank-2-lite"] = new(maxDocuments: 1_000, nativeTopN: true),
            })
        {
            PoolOwnsConfiguredTransport = true,
        },
        new ProviderDescriptor(
            "jina",
            "Jina AI",
            static (config, cancellationToken) => new ValueTask<IAsyncDisposable>(JinaAdapter.Create(config, cancellationToken)),
            aliases: ["jinaai"],
            setup: new ProviderSetupSpec([
                new SetupField("api_key", "API key", "secret", required: true, placeholder: "env://JINA_API_KEY or a literal key", envVar: "JINA_API_KEY", helpText: "Accepts a literal, env://VAR, or credential://system/name."),
                new SetupField("base_url", "Base URL", "endpoint", required: false, advanced: true, defaultValue: "https://api.jina.ai/v1", helpText: "Defaults to https://api.jina.ai/v1."),
            ], modelSelection: "manual-only"),
            defaultBaseUrl: "https://api.jina.ai/v1",
            locality: ProviderLocality.Hosted,
            operations: [InferenceOperation.Embedding, InferenceOperation.Rerank],
            staticEmbeddingCapabilities: new Dictionary<string, EmbeddingCapabilities>(StringComparer.Ordinal)
            {
                ["jina-embeddings-v3"] = new(inputIntents: [EmbeddingInputIntent.Query, EmbeddingInputIntent.Document, EmbeddingInputIntent.Classification, EmbeddingInputIntent.Clustering]),
                ["jina-embeddings-v4"] = new(inputIntents: [EmbeddingInputIntent.Query, EmbeddingInputIntent.Document]),
                ["jina-embeddings-v5-text-small"] = new(dimensions: 1_024, dimensionChoices: [32, 64, 128, 256, 512, 1_024], maxInputTokens: 32_768, inputIntents: [EmbeddingInputIntent.Query, EmbeddingInputIntent.Document, EmbeddingInputIntent.Classification, EmbeddingInputIntent.Clustering]),
                ["jina-embeddings-v5-omni-small"] = new(dimensions: 1_024, dimensionChoices: [32, 64, 128, 256, 512, 1_024], maxInputTokens: 32_768, inputIntents: [EmbeddingInputIntent.Query, EmbeddingInputIntent.Document, EmbeddingInputIntent.Classification, EmbeddingInputIntent.Clustering]),
                ["jina-embeddings-v5-text-nano"] = new(dimensions: 768, dimensionChoices: [32, 64, 128, 256, 512, 768], maxInputTokens: 8_192, inputIntents: [EmbeddingInputIntent.Query, EmbeddingInputIntent.Document, EmbeddingInputIntent.Classification, EmbeddingInputIntent.Clustering]),
                ["jina-embeddings-v5-omni-nano"] = new(dimensions: 768, dimensionChoices: [32, 64, 128, 256, 512, 768], maxInputTokens: 8_192, inputIntents: [EmbeddingInputIntent.Query, EmbeddingInputIntent.Document, EmbeddingInputIntent.Classification, EmbeddingInputIntent.Clustering]),
            },
            staticRerankCapabilities: new Dictionary<string, RerankCapabilities>(StringComparer.Ordinal)
            {
                ["jina-reranker-v3"] = new(nativeTopN: true),
                ["jina-reranker-v3.5"] = new(nativeTopN: true),
                ["jina-reranker-m0"] = new(nativeTopN: true),
                ["jina-reranker-v2-base-multilingual"] = new(nativeTopN: true),
            })
        {
            PoolOwnsConfiguredTransport = true,
        },
        SelectReviewedGenerationPreset("cerebras"),
        SelectReviewedGenerationPreset("hyperbolic"),
        SelectReviewedGenerationPreset("nscale"),
    ]);

    private static ProviderDescriptor SelectReviewedGenerationPreset(string presetId)
    {
        var row = CompatPresetTable.Rows.Single(
            definition => string.Equals(definition.Source.Id, presetId, StringComparison.Ordinal));
        if (!row.Source.SourceOperations.SequenceEqual(["generation"], StringComparer.Ordinal))
        {
            throw new InvalidOperationException("A reviewed compatibility preset must have generation as its only source operation.");
        }

        if (!row.Generation.Descriptor.Operations.SequenceEqual([InferenceOperation.Generation]))
        {
            throw new InvalidOperationException("A reviewed compatibility preset must have generation as its only native operation.");
        }

        if (row.PendingNativeParity.Count != 0)
        {
            throw new InvalidOperationException("A reviewed compatibility preset cannot have pending native parity work.");
        }

        return row.Generation.Descriptor;
    }
}
