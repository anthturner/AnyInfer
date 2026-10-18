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
public sealed record Sourced<T>
{
    /// <summary>Creates a sourced value with a closed provenance value.</summary>
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
