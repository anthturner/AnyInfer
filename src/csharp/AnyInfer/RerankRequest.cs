using AnyInfer.Internal;
using AnyInfer.Json;

namespace AnyInfer;

/// <summary>One immutable request to rank documents against a query.</summary>
public sealed record RerankRequest
{
    /// <summary>Creates an immutable reranking request from copies of its documents and options.</summary>
    /// <remarks>
    /// Only argument shape is checked here. When the request runs, a document count above the
    /// provider's batch limit requires both <see cref="BatchPolicy.AllowSplit"/> and
    /// <see cref="BatchPolicy.RerankCrossBatch"/>; otherwise the client raises
    /// <see cref="ConfigException"/>. Without a known or overridden limit, more than 1000
    /// documents are refused.
    /// </remarks>
    /// <param name="query">The non-empty query text.</param>
    /// <param name="documents">
    /// The documents to rank, in order; at least one is required and identifiers must be unique
    /// under ordinal comparison. The sequence is copied.
    /// </param>
    /// <param name="topN">
    /// The maximum number of ranked items to request, or <see langword="null"/> for the provider
    /// default. When the request is split into batches, it applies within each batch.
    /// </param>
    /// <param name="timeoutS">The timeout in seconds for each provider attempt, or <see langword="null"/> for 120 seconds.</param>
    /// <param name="maxResponseBytes">The response-body size cap in bytes given to the adapter; defaults to 8 MiB.</param>
    /// <param name="metadata">Caller metadata reported to telemetry observers, or <see langword="null"/> for none. The map is copied.</param>
    /// <param name="providerOptions">
    /// Extra adapter options keyed by provider instance identifier, or <see langword="null"/> for
    /// none; each attempt passes only the map for its own provider instance. The maps are copied.
    /// </param>
    /// <param name="batch">The batching policy, or <see langword="null"/> for <see cref="BatchPolicy"/> defaults.</param>
    /// <param name="returnDocuments">Whether to copy each ranked document's text into <see cref="RankedItem.Text"/>.</param>
    /// <param name="retainRaw">Whether to keep the provider's raw response payload on <see cref="RerankResult.Raw"/>.</param>
    /// <exception cref="ArgumentNullException"><paramref name="query"/> or <paramref name="documents"/> is <see langword="null"/>.</exception>
    /// <exception cref="ArgumentException">
    /// <paramref name="query"/> is empty; <paramref name="documents"/> is empty, contains
    /// <see langword="null"/> or repeats an identifier; or a map contains a <see langword="null"/>
    /// key or value.
    /// </exception>
    /// <exception cref="ArgumentOutOfRangeException"><paramref name="topN"/> is zero or negative.</exception>
    public RerankRequest(
        string query,
        IEnumerable<RerankDocument> documents,
        int? topN = null,
        double? timeoutS = null,
        int maxResponseBytes = 8 * 1024 * 1024,
        IReadOnlyDictionary<string, string>? metadata = null,
        IReadOnlyDictionary<string, IReadOnlyDictionary<string, JsonValue>>? providerOptions = null,
        BatchPolicy? batch = null,
        bool returnDocuments = false,
        bool retainRaw = false)
    {
        Query = query ?? throw new ArgumentNullException(nameof(query));
        if (Query.Length == 0)
        {
            throw new ArgumentException("Rerank queries must not be empty.", nameof(query));
        }

        ArgumentNullException.ThrowIfNull(documents);
        Documents = ImmutableValues.List(documents, nameof(documents));
        if (Documents.Count == 0)
        {
            throw new ArgumentException("Rerank requests must contain at least one document.", nameof(documents));
        }

        if (topN is <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(topN));
        }

        if (Documents.Select(static document => document.Id).Distinct(StringComparer.Ordinal).Count() != Documents.Count)
        {
            throw new ArgumentException("Rerank document identifiers must be unique.", nameof(documents));
        }

        TopN = topN;
        TimeoutS = timeoutS;
        MaxResponseBytes = maxResponseBytes;
        Metadata = ImmutableValues.Map(metadata, nameof(metadata));
        ProviderOptions = SnapshotProviderOptions(providerOptions);
        Batch = batch ?? new BatchPolicy();
        ReturnDocuments = returnDocuments;
        RetainRaw = retainRaw;
    }

    /// <summary>Gets the query text.</summary>
    public string Query { get; }
    /// <summary>Gets copied request documents in caller order.</summary>
    public IReadOnlyList<RerankDocument> Documents { get; }
    /// <summary>Gets the requested top-N limit, or <see langword="null"/> when unset.</summary>
    public int? TopN { get; }
    /// <summary>Gets the supplied timeout, or <see langword="null"/> for the default.</summary>
    public double? TimeoutS { get; }
    /// <summary>Gets the public response-body cap in bytes.</summary>
    public int MaxResponseBytes { get; }
    /// <summary>Gets copied caller metadata.</summary>
    public IReadOnlyDictionary<string, string> Metadata { get; }
    /// <summary>Gets copied provider-instance option maps.</summary>
    public IReadOnlyDictionary<string, IReadOnlyDictionary<string, JsonValue>> ProviderOptions { get; }
    /// <summary>Gets the request batching policy.</summary>
    public BatchPolicy Batch { get; }
    /// <summary>Gets whether ranked item text should be echoed.</summary>
    public bool ReturnDocuments { get; }
    /// <summary>Gets whether a provider raw payload should be retained.</summary>
    public bool RetainRaw { get; }
    /// <summary>Gets the effective provider timeout in seconds.</summary>
    public double EffectiveTimeoutS => TimeoutS ?? 120d;

    private static IReadOnlyDictionary<string, IReadOnlyDictionary<string, JsonValue>> SnapshotProviderOptions(
        IReadOnlyDictionary<string, IReadOnlyDictionary<string, JsonValue>>? values)
    {
        var entries = new List<KeyValuePair<string, IReadOnlyDictionary<string, JsonValue>>>();
        IEnumerable<KeyValuePair<string, IReadOnlyDictionary<string, JsonValue>>> source =
            values is null
                ? Array.Empty<KeyValuePair<string, IReadOnlyDictionary<string, JsonValue>>>()
                : values;
        foreach (var pair in source)
        {
            if (pair.Value is null)
            {
                throw new ArgumentException("Provider option maps cannot contain null values.", nameof(values));
            }

            entries.Add(new KeyValuePair<string, IReadOnlyDictionary<string, JsonValue>>(
                pair.Key,
                ImmutableValues.Map(pair.Value, nameof(values))));
        }

        return ImmutableValues.Map(entries, nameof(values));
    }
}