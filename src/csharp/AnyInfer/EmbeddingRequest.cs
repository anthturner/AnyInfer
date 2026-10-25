using AnyInfer.Capabilities;
using AnyInfer.Internal;
using AnyInfer.Json;

namespace AnyInfer;

/// <summary>One immutable request to embed ordered text inputs.</summary>
public sealed record EmbeddingRequest
{
    /// <summary>Creates an immutable embedding request from copies of its inputs and options.</summary>
    /// <remarks>
    /// Only argument shape is checked here. The client enforces batching, the expected space and
    /// fallback compatibility when the request runs, raising <see cref="ConfigException"/> for a
    /// violation; without a known or overridden batch limit, a request with more than 2048 inputs
    /// is refused.
    /// </remarks>
    /// <param name="inputs">The texts to embed, in order; at least one is required. The sequence is copied.</param>
    /// <param name="inputType">
    /// The input intent, or <see langword="null"/> to leave it unspecified. When the target's
    /// capability facts show it does not distinguish intents, the result carries a warning.
    /// </param>
    /// <param name="dimensions">The requested output dimensionality, or <see langword="null"/> for the model default.</param>
    /// <param name="expectedSpace">
    /// The space the result must be compatible with under <see cref="EmbeddingSpace.CompatibleWith(EmbeddingSpace)"/>,
    /// or <see langword="null"/> for no check.
    /// </param>
    /// <param name="timeoutS">The timeout in seconds for each provider attempt, or <see langword="null"/> for 120 seconds.</param>
    /// <param name="maxResponseBytes">The response-body size cap in bytes given to the adapter; defaults to 64 MiB.</param>
    /// <param name="metadata">Caller metadata reported to telemetry observers, or <see langword="null"/> for none. The map is copied.</param>
    /// <param name="providerOptions">
    /// Extra adapter options keyed by provider instance identifier, or <see langword="null"/> for
    /// none; each attempt passes only the map for its own provider instance. The maps are copied.
    /// </param>
    /// <param name="batch">The batching policy, or <see langword="null"/> for <see cref="BatchPolicy"/> defaults.</param>
    /// <param name="retainRaw">Whether to keep the provider's raw response payload on <see cref="EmbeddingResult.Raw"/>.</param>
    /// <param name="allowIncompatibleFallback">
    /// Whether route fallback may move to a target with a different provider instance or model.
    /// When <see langword="false"/> (the default), such a fallback raises
    /// <see cref="ConfigException"/>; when <see langword="true"/>, it proceeds and the result
    /// carries a warning that its vectors may not be comparable with the primary target's.
    /// </param>
    /// <exception cref="ArgumentNullException"><paramref name="inputs"/> is <see langword="null"/>.</exception>
    /// <exception cref="ArgumentException">
    /// <paramref name="inputs"/> is empty or contains <see langword="null"/>, or a map contains a
    /// <see langword="null"/> key or value.
    /// </exception>
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