using AnyInfer.Internal;
using PeterO.Numbers;

namespace AnyInfer;

/// <summary>Defines optional caller-owned spend ceilings for a client.</summary>
/// <remarks>
/// A client checks an active policy before dispatching a request, using an estimate of the
/// request's cost from trusted pricing, and refuses with <see cref="SpendLimitException"/>
/// before anything is sent. Cumulative spend is tracked in the client's
/// <see cref="AnyInfer.Capabilities.SpendLedger"/>, which the client creates when a policy is set
/// and no ledger is supplied. Amounts are US dollars.
/// </remarks>
public sealed record SpendPolicy
{
    /// <summary>Creates an immutable spend policy.</summary>
    /// <param name="maxTotalUsd">
    /// The cumulative ceiling across the ledger's recorded and reserved spend, including the next
    /// request's estimate, or <see langword="null"/> for no cumulative ceiling.
    /// </param>
    /// <param name="maxRequestUsd">
    /// The ceiling for one request's estimated cost, or <see langword="null"/> for no per-request
    /// ceiling.
    /// </param>
    /// <param name="onUnknown">
    /// <c>allow</c> (the default) sends a request whose cost cannot be estimated; <c>refuse</c>
    /// refuses it.
    /// </param>
    /// <exception cref="ArgumentOutOfRangeException">A ceiling is negative.</exception>
    /// <exception cref="ArgumentException"><paramref name="onUnknown"/> is neither <c>allow</c> nor <c>refuse</c>.</exception>
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
