namespace AnyInfer.Capabilities;

/// <summary>Represents one request's estimated input size against an optional model context window.</summary>
public sealed record ContextBudget
{
    /// <summary>Initializes an immutable context budget without substituting unknown capacity or cost.</summary>
    public ContextBudget(
        Sourced<int>? contextWindow,
        RequestEstimate estimate,
        long outputReserveTokens,
        long headroomTokens,
        Sourced<Pricing>? pricing = null)
    {
        ContextWindow = contextWindow;
        Estimate = estimate ?? throw new ArgumentNullException(nameof(estimate));
        OutputReserveTokens = outputReserveTokens;
        HeadroomTokens = headroomTokens;
        Pricing = pricing;
    }

    /// <summary>Gets the known context-window fact and provenance, or null when unknown.</summary>
    public Sourced<int>? ContextWindow { get; }

    /// <summary>Gets the component estimate for this request.</summary>
    public RequestEstimate Estimate { get; }

    /// <summary>Gets the response-token reserve used for planning.</summary>
    public long OutputReserveTokens { get; }

    /// <summary>Gets the safety headroom used for planning.</summary>
    public long HeadroomTokens { get; }

    /// <summary>Gets pricing evidence available for preflight cost estimation.</summary>
    public Sourced<Pricing>? Pricing { get; }

    /// <summary>Gets input allowance, or null when no context window is known.</summary>
    public long? InputAllowanceTokens
    {
        get
        {
            if (ContextWindow is null)
            {
                return null;
            }

            return Math.Max(0, checked((long)ContextWindow.Value - OutputReserveTokens - HeadroomTokens));
        }
    }

    /// <summary>Gets planning allowance remaining, or null when capacity or input coverage is unknown.</summary>
    public long? RemainingTokens
    {
        get
        {
            if (Estimate.UnpricedParts != 0 || InputAllowanceTokens is not { } allowance)
            {
                return null;
            }

            return checked(allowance - Estimate.Tokens);
        }
    }

    /// <summary>Gets whether the planning estimate fits, or null when the comparison is unknowable.</summary>
    public bool? Fits => RemainingTokens is { } remaining ? remaining >= 0 : null;

    /// <summary>Gets the preflight cost range, or null when input coverage or trusted pricing is unavailable.</summary>
    public CostEstimate? EstimatedCost => Estimate.UnpricedParts != 0
        ? null
        : PricingCalculator.EstimateCost(Estimate, OutputReserveTokens, Pricing);
}
