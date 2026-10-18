using AnyInfer.Internal;
using PeterO.Numbers;

namespace AnyInfer;

/// <summary>Defines optional caller-owned spend ceilings for a client.</summary>
public sealed record SpendPolicy
{
    /// <summary>Creates an immutable spend policy.</summary>
    public SpendPolicy(EDecimal? maxTotalUsd = null, EDecimal? maxRequestUsd = null, string onUnknown = "allow")
    {
        ValidateCeiling(maxTotalUsd, nameof(maxTotalUsd));
        ValidateCeiling(maxRequestUsd, nameof(maxRequestUsd));
        if (onUnknown is not ("allow" or "refuse"))
        {
            throw new ArgumentException("onUnknown must be 'allow' or 'refuse'.", nameof(onUnknown));
        }

        MaxTotalUsd = maxTotalUsd;
        MaxRequestUsd = maxRequestUsd;
        OnUnknown = onUnknown;
    }

    /// <summary>Gets the cumulative client ceiling, or <see langword="null"/> when unbounded.</summary>
    public EDecimal? MaxTotalUsd { get; }
    /// <summary>Gets the single-request estimate ceiling, or <see langword="null"/> when unbounded.</summary>
    public EDecimal? MaxRequestUsd { get; }
    /// <summary>Gets whether unknown preflight costs are allowed or refused.</summary>
    public string OnUnknown { get; }
    /// <summary>Gets whether this policy can refuse a request.</summary>
    public bool Active => MaxTotalUsd is not null || MaxRequestUsd is not null || OnUnknown == "refuse";

    private static void ValidateCeiling(EDecimal? value, string name)
    {
        if (value is not null && AccountingDecimal.Compare(value, EDecimal.Zero) < 0)
        {
            throw new ArgumentOutOfRangeException(name, "Spend ceilings cannot be negative.");
        }
    }
}
