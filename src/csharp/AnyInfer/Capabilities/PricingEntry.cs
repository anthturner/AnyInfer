namespace AnyInfer.Capabilities;

/// <summary>Describes one exact or prefix-priced model row.</summary>
public sealed record PricingEntry
{
    /// <summary>Creates a verified pricing row.</summary>
    /// <param name="model">Exact model ID or a valid boundary-prefix model ID.</param>
    /// <param name="pricing">Nonnegative quoted pricing facts.</param>
    /// <param name="lastVerified">Source verification date text.</param>
    /// <param name="source">Provider source URL or identifying source text.</param>
    /// <param name="openRouterId">Optional OpenRouter identifier.</param>
    public PricingEntry(string model, Pricing pricing, string lastVerified, string source, string openRouterId = "")
    {
        Model = model ?? throw new ArgumentNullException(nameof(model));
        Pricing = pricing ?? throw new ArgumentNullException(nameof(pricing));
        LastVerified = lastVerified ?? throw new ArgumentNullException(nameof(lastVerified));
        Source = source ?? throw new ArgumentNullException(nameof(source));
        OpenRouterId = openRouterId ?? throw new ArgumentNullException(nameof(openRouterId));
    }

    /// <summary>Gets the exact or boundary-prefix model spelling.</summary>
    public string Model { get; }
    /// <summary>Gets the verified nonnegative price facts.</summary>
    public Pricing Pricing { get; }
    /// <summary>Gets the source verification date text.</summary>
    public string LastVerified { get; }
    /// <summary>Gets the source URL or identifying source text.</summary>
    public string Source { get; }
    /// <summary>Gets the optional OpenRouter identifier.</summary>
    public string OpenRouterId { get; }
}
