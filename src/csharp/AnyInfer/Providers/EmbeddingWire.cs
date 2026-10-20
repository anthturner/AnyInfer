using AnyInfer.Capabilities;
using AnyInfer.Internal;
using AnyInfer.Json;

namespace AnyInfer.Providers;

/// <summary>One resolved provider embedding batch.</summary>
public sealed record EmbeddingWireRequest
{
    /// <summary>Creates a copied provider embedding request.</summary>
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
public sealed record EmbeddingWireResult
{
    /// <summary>Creates a copied, deliberately permissive provider embedding response.</summary>
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
    /// <summary>Gets copied provider phase timings.</summary>
    public IReadOnlyDictionary<string, double> Phases { get; }
    /// <summary>Gets the immutable raw provider payload, when present.</summary>
    public JsonValue? Raw { get; }
}