namespace AnyInfer.Capabilities;

/// <summary>Identifies the evidence backing a capability fact.</summary>
public enum Provenance
{
    /// <summary>A descriptor fallback rather than collected evidence.</summary>
    Default = 0,

    /// <summary>A bundled catalog fact.</summary>
    Catalog = 1,

    /// <summary>A provider model-listing fact.</summary>
    Discovered = 2,

    /// <summary>An explicitly requested probe result.</summary>
    Probed = 3,

    /// <summary>An application-supplied correction.</summary>
    Override = 4,
}

/// <summary>
/// Pairs a capability value with its evidence provenance.
/// </summary>
/// <remarks>
/// This record does not deep-freeze an arbitrary <typeparamref name="T"/> value. Capability
/// records that own collections snapshot their inputs before placing them in a sourced value.
/// </remarks>
/// <typeparam name="T">Type of the capability value, such as a token count, feature flags, or pricing.</typeparam>
public sealed record Sourced<T>
{
    /// <summary>Creates a sourced value with a closed provenance value.</summary>
    /// <param name="value">Capability value; reference values are stored without copying.</param>
    /// <param name="provenance">
    /// Evidence behind the value. The default, <see cref="Provenance.Default"/>, marks a placeholder rather than
    /// a fact; pass the provenance that matches where the value came from.
    /// </param>
    /// <exception cref="ArgumentOutOfRangeException"><paramref name="provenance"/> is not a defined value.</exception>
    public Sourced(T value, Provenance provenance = Provenance.Default)
    {
        CapabilityValidation.RequireDefinedProvenance(provenance, nameof(provenance));
        Value = value;
        Provenance = provenance;
    }

    /// <summary>Gets the value paired with provenance; arbitrary reference values are not copied here.</summary>
    public T Value { get; }

    /// <summary>Gets the evidence provenance.</summary>
    public Provenance Provenance { get; }

    /// <summary>Returns whether this fact may replace another fact during assembly.</summary>
    /// <param name="other">Fact currently held, or <see langword="null"/> when none is known.</param>
    /// <returns>
    /// <see langword="true"/> when <paramref name="other"/> is <see langword="null"/> or this provenance is at least
    /// as strong; provenance strength increases from default through catalog, discovered, and probed to override.
    /// </returns>
    public bool Outranks(Sourced<T>? other) => other is null || Provenance >= other.Provenance;
}

internal static class CapabilityValidation
{
    internal static void RequireDefinedProvenance(Provenance provenance, string parameterName)
    {
        if (!Enum.IsDefined(provenance))
        {
            throw new ArgumentOutOfRangeException(parameterName);
        }
    }
}
