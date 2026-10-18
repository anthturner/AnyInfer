namespace AnyInfer;

/// <summary>Identifies the vector space in which one embedding result may be compared.</summary>
public sealed record EmbeddingSpace
{
    /// <summary>Initializes an immutable vector-space identity.</summary>
    public EmbeddingSpace(string providerId, string model, string? modelRevision = null, int? dimensions = null, bool inputIntentAware = false, bool? normalized = null, string? compatibilityId = null)
    {
        ProviderId = providerId ?? throw new ArgumentNullException(nameof(providerId));
        Model = model ?? throw new ArgumentNullException(nameof(model));
        ModelRevision = modelRevision;
        Dimensions = dimensions;
        InputIntentAware = inputIntentAware;
        Normalized = normalized;
        CompatibilityId = compatibilityId;
    }

    /// <summary>Gets the producing provider identifier.</summary>
    public string ProviderId { get; }

    /// <summary>Gets the concrete resolved model identifier.</summary>
    public string Model { get; }

    /// <summary>Gets the provider-reported revision, when known.</summary>
    public string? ModelRevision { get; }

    /// <summary>Gets the returned vector dimensionality, when known.</summary>
    public int? Dimensions { get; }

    /// <summary>Gets whether input intent affects the embedding space.</summary>
    public bool InputIntentAware { get; }

    /// <summary>Gets whether vectors are unit-normalized, when documented.</summary>
    public bool? Normalized { get; }

    /// <summary>Gets a caller-asserted compatibility identity, when supplied.</summary>
    public string? CompatibilityId { get; }

    /// <summary>Returns whether this and another space may be safely compared.</summary>
    public bool CompatibleWith(EmbeddingSpace other)
    {
        return other is not null
            && ((CompatibilityId is not null && CompatibilityId == other.CompatibilityId)
                || (ProviderId == other.ProviderId
                    && Model == other.Model
                    && ModelRevision == other.ModelRevision));
    }
}
