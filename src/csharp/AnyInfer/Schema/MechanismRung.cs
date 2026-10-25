namespace AnyInfer.Schema;

/// <summary>Describes one structured-output mechanism and why it was or was not available.</summary>
public sealed record MechanismRung
{
    /// <summary>Initializes an immutable mechanism rung.</summary>
    /// <param name="mechanism">
    /// The mechanism spelling; manifests produced by the SDK use <c>grammar</c>,
    /// <c>json_schema</c>, <c>json_mode</c> and <c>prompt</c>.
    /// </param>
    /// <param name="available">Whether the mechanism was available for the target.</param>
    /// <param name="reason">
    /// Why the mechanism was unavailable, not chosen, or chosen through a compatibility fallback;
    /// empty (the default) when no explanation applies.
    /// </param>
    /// <exception cref="ArgumentNullException"><paramref name="mechanism"/> or <paramref name="reason"/> is <see langword="null"/>.</exception>
    public MechanismRung(string mechanism, bool available, string reason = "")
    {
        Mechanism = mechanism ?? throw new ArgumentNullException(nameof(mechanism));
        Available = available;
        Reason = reason ?? throw new ArgumentNullException(nameof(reason));
    }

    /// <summary>Gets the mechanism spelling.</summary>
    public string Mechanism { get; }

    /// <summary>Gets whether the mechanism was available.</summary>
    public bool Available { get; }

    /// <summary>Gets why the mechanism was unavailable or selected.</summary>
    public string Reason { get; }
}
