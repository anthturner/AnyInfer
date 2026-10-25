namespace AnyInfer;

/// <summary>Identifies the vector space in which one embedding result may be compared.</summary>
public sealed record EmbeddingSpace
{
    /// <summary>Initializes an immutable vector-space identity.</summary>
    /// <param name="providerId">The identifier of the provider instance that produced the vectors.</param>
    /// <param name="model">The concrete resolved model identifier.</param>
    /// <param name="modelRevision">The provider-reported model revision, or <see langword="null"/> when unknown.</param>
    /// <param name="dimensions">The vector dimensionality, or <see langword="null"/> when unknown.</param>
    /// <param name="inputIntentAware">Whether the input intent affects the produced vectors.</param>
    /// <param name="normalized">Whether vectors are unit-normalized, or <see langword="null"/> when undocumented.</param>
    /// <param name="compatibilityId">
    /// A caller-asserted identity under which spaces count as compatible regardless of provider
    /// and model, or <see langword="null"/>.
    /// </param>
    /// <exception cref="ArgumentNullException"><paramref name="providerId"/> or <paramref name="model"/> is <see langword="null"/>.</exception>
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
    /// <remarks>
    /// Spaces are compatible when both carry the same non-null <see cref="CompatibilityId"/>, or
    /// when <see cref="ProviderId"/>, <see cref="Model"/> and <see cref="ModelRevision"/> are all
    /// equal under ordinal comparison, with two unknown revisions counting as equal. Dimensions,
    /// normalization and intent awareness are not compared.
    /// </remarks>
    /// <param name="other">The space to compare with.</param>
    /// <returns><see langword="true"/> when the spaces are compatible; <see langword="false"/> when <paramref name="other"/> is <see langword="null"/>.</returns>
    public bool CompatibleWith(EmbeddingSpace other)
    {
        return other is not null
            && ((CompatibilityId is not null && CompatibilityId == other.CompatibilityId)
                || (ProviderId == other.ProviderId
                    && Model == other.Model
                    && ModelRevision == other.ModelRevision));
    }
}
