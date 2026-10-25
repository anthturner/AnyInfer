using AnyInfer.Capabilities;
using AnyInfer.Internal;
using AnyInfer.Json;

namespace AnyInfer.Providers;

/// <summary>One resolved provider embedding batch.</summary>
/// <remarks>
/// The client builds one of these per batch after routing and batching; an <see cref="IEmbedsText"/> adapter
/// translates it into a single provider call.
/// </remarks>
public sealed record EmbeddingWireRequest
{
    /// <summary>Creates a copied provider embedding request.</summary>
    /// <param name="model">Concrete provider model identifier.</param>
    /// <param name="inputs">Batch inputs in order; copied, with <see langword="null"/> treated as empty.</param>
    /// <param name="inputType">Input intent to send, or <see langword="null"/> to send none.</param>
    /// <param name="dimensions">Requested output dimensions, or <see langword="null"/> for the model default.</param>
    /// <param name="timeoutS">Provider timeout in seconds.</param>
    /// <param name="maxResponseBytes">Maximum provider response-body size in bytes.</param>
    /// <param name="extraOptions">Provider-specific options to merge into the wire payload, copied; <see langword="null"/> means none.</param>
    /// <exception cref="ArgumentNullException"><paramref name="model"/> is <see langword="null"/>.</exception>
    /// <exception cref="ArgumentException"><paramref name="inputs"/> contains <see langword="null"/>, or <paramref name="extraOptions"/> contains a <see langword="null"/> value.</exception>
    public EmbeddingWireRequest(
        string model,
        IEnumerable<string> inputs,
        EmbeddingInputIntent? inputType = null,
        int? dimensions = null,
        double timeoutS = 120d,
        int maxResponseBytes = 1 * 1024 * 1024,
        IReadOnlyDictionary<string, JsonValue>? extraOptions = null)
    {
        Model = model ?? throw new ArgumentNullException(nameof(model));
        Inputs = ImmutableValues.List(inputs, nameof(inputs));
        InputType = inputType;
        Dimensions = dimensions;
        TimeoutS = timeoutS;
        MaxResponseBytes = maxResponseBytes;
        ExtraOptions = ImmutableValues.Map(extraOptions, nameof(extraOptions));
    }

    /// <summary>Gets the concrete provider model.</summary>
    public string Model { get; }
    /// <summary>Gets copied batch inputs in provider order.</summary>
    public IReadOnlyList<string> Inputs { get; }
    /// <summary>Gets the optional input intent.</summary>
    public EmbeddingInputIntent? InputType { get; }
    /// <summary>Gets the optional requested dimensions.</summary>
    public int? Dimensions { get; }
    /// <summary>Gets the provider timeout in seconds.</summary>
    public double TimeoutS { get; }
    /// <summary>Gets the provider response-body cap in bytes.</summary>
    public int MaxResponseBytes { get; }
    /// <summary>Gets copied provider-specific options.</summary>
    public IReadOnlyDictionary<string, JsonValue> ExtraOptions { get; }
}

/// <summary>One buffered embedding response before core validation.</summary>
/// <remarks>
/// The client, not the adapter, checks that the batch returned one vector per input with consistent dimensions
/// and finite components.
/// </remarks>
public sealed record EmbeddingWireResult
{
    /// <summary>Creates a copied, deliberately permissive provider embedding response.</summary>
    /// <param name="vectors">One vector per input, in input order; each vector is copied.</param>
    /// <param name="model">Provider-reported model, or <see langword="null"/> when not reported.</param>
    /// <param name="dimensions">Provider-reported dimensions, or <see langword="null"/> to use the first vector's length.</param>
    /// <param name="normalized">Whether the provider reports unit-normalized vectors, or <see langword="null"/> when unknown.</param>
    /// <param name="usage">Provider-reported usage, or <see langword="null"/> when none was reported.</param>
    /// <param name="phases">Provider-reported phase timings in milliseconds keyed by phase name; <see langword="null"/> means none.</param>
    /// <param name="raw">Raw provider payload, or <see langword="null"/>.</param>
    /// <exception cref="ArgumentNullException"><paramref name="vectors"/> or one of its vectors is <see langword="null"/>.</exception>
    public EmbeddingWireResult(
        IEnumerable<IEnumerable<double>> vectors,
        string? model = null,
        int? dimensions = null,
        bool? normalized = null,
        Usage? usage = null,
        IReadOnlyDictionary<string, double>? phases = null,
        JsonValue? raw = null)
    {
        ArgumentNullException.ThrowIfNull(vectors);
        Vectors = Array.AsReadOnly(vectors.Select(vector =>
        {
            ArgumentNullException.ThrowIfNull(vector);
            return (IReadOnlyList<double>)Array.AsReadOnly(vector.ToArray());
        }).ToArray());
        Model = model;
        Dimensions = dimensions;
        Normalized = normalized;
        Usage = usage;
        Phases = ImmutableValues.Map(phases, nameof(phases));
        Raw = raw;
    }

    /// <summary>Gets copied vector components before core shape and finite-value validation.</summary>
    public IReadOnlyList<IReadOnlyList<double>> Vectors { get; }
    /// <summary>Gets the provider-reported model, when present.</summary>
    public string? Model { get; }
    /// <summary>Gets provider-reported dimensions, when present.</summary>
    public int? Dimensions { get; }
    /// <summary>Gets the provider-reported normalization flag, when present.</summary>
    public bool? Normalized { get; }
    /// <summary>Gets provider-reported usage, when present.</summary>
    public Usage? Usage { get; }
    /// <summary>Gets copied provider phase timings in milliseconds.</summary>
    public IReadOnlyDictionary<string, double> Phases { get; }
    /// <summary>Gets the immutable raw provider payload, when present.</summary>
    public JsonValue? Raw { get; }
}