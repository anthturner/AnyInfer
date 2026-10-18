namespace AnyInfer.Schema;

/// <summary>Describes one structured-output mechanism and why it was or was not available.</summary>
public sealed record MechanismRung
{
    /// <summary>Initializes an immutable mechanism rung.</summary>
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
