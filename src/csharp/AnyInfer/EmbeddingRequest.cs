using AnyInfer.Capabilities;
using AnyInfer.Internal;
using AnyInfer.Json;

namespace AnyInfer;

/// <summary>One immutable request to embed ordered text inputs.</summary>
public sealed record EmbeddingRequest
{
    /// <summary>Creates an embedding request with the source-compatible defaults.</summary>
    public EmbeddingRequest(
        IEnumerable<string> inputs,
        EmbeddingInputIntent? inputType = null,
        int? dimensions = null,
        EmbeddingSpace? expectedSpace = null,
        double? timeoutS = null,
        int maxResponseBytes = 64 * 1024 * 1024,
        IReadOnlyDictionary<string, string>? metadata = null,
        IReadOnlyDictionary<string, IReadOnlyDictionary<string, JsonValue>>? providerOptions = null,
        BatchPolicy? batch = null,
        bool retainRaw = false,
        bool allowIncompatibleFallback = false)
    {
        ArgumentNullException.ThrowIfNull(inputs);
        Inputs = ImmutableValues.List(inputs, nameof(inputs));
        if (Inputs.Count == 0)
        {
            throw new ArgumentException("Embedding requests must contain at least one input.", nameof(inputs));
        }

        InputType = inputType;
        Dimensions = dimensions;
        ExpectedSpace = expectedSpace;
        TimeoutS = timeoutS;
        MaxResponseBytes = maxResponseBytes;
        Metadata = ImmutableValues.Map(metadata, nameof(metadata));
        ProviderOptions = SnapshotProviderOptions(providerOptions);
        Batch = batch ?? new BatchPolicy();
        RetainRaw = retainRaw;
        AllowIncompatibleFallback = allowIncompatibleFallback;
    }

    /// <summary>Gets copied input strings in caller order.</summary>
    public IReadOnlyList<string> Inputs { get; }
    /// <summary>Gets the optional embedding input intent.</summary>
    public EmbeddingInputIntent? InputType { get; }
    /// <summary>Gets the optional requested output dimensionality.</summary>
    public int? Dimensions { get; }
    /// <summary>Gets the optional expected result space.</summary>
    public EmbeddingSpace? ExpectedSpace { get; }
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
    /// <summary>Gets whether a provider raw payload should be retained.</summary>
    public bool RetainRaw { get; }
    /// <summary>Gets whether unproven cross-space fallback is permitted.</summary>
    public bool AllowIncompatibleFallback { get; }
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