namespace AnyInfer.Capabilities;

/// <summary>Builds pure context budgets and explicit pre-dispatch fit decisions.</summary>
public static class ContextBudgeting
{
    /// <summary>Gets the default response-token reserve.</summary>
    public const long DefaultOutputReserveTokens = 4_096;

    /// <summary>Gets the fractional context-window safety headroom.</summary>
    public const double HeadroomFraction = 0.05;

    /// <summary>Gets the minimum safety headroom.</summary>
    public const long MinimumHeadroomTokens = 256;

    /// <summary>Gets the maximum safety headroom.</summary>
    public const long MaximumHeadroomTokens = 8_192;

    /// <summary>Computes clamped default headroom from a known context-window count.</summary>
    public static long HeadroomFor(long contextWindowTokens)
    {
        var candidate = checked((long)Math.Ceiling(contextWindowTokens * HeadroomFraction));
        return Math.Max(MinimumHeadroomTokens, Math.Min(MaximumHeadroomTokens, candidate));
    }

    /// <summary>Builds a pure context budget without dispatching, validating schemas, or resolving a provider.</summary>
    public static ContextBudget BuildContextBudget(
        GenerationRequest request,
        ModelCapabilities? capabilities,
        ITokenEstimator? estimator = null,
        TokenCalibration? calibration = null,
        long? outputReserveTokens = null,
        long? headroomTokens = null)
    {
        ArgumentNullException.ThrowIfNull(request);
        var window = capabilities?.ContextWindow;
        var reserve = ResolveReserve(request, capabilities, outputReserveTokens);
        long headroom;
        if (headroomTokens is { } explicitHeadroom)
        {
            if (explicitHeadroom < 0)
            {
                throw new ArgumentOutOfRangeException(nameof(headroomTokens), "Safety headroom must not be negative.");
            }

            headroom = explicitHeadroom;
        }
        else
        {
            headroom = window is null ? 0 : HeadroomFor(window.Value);
        }

        return new ContextBudget(
            window,
            TokenEstimation.EstimateRequest(request, estimator, calibration),
            reserve,
            headroom,
            capabilities?.Pricing);
    }

    /// <summary>Returns a context-length error only when a trusted whole-window lower bound is provably exceeded.</summary>
    public static ContextLengthException? ContextGateError(ContextBudget budget, string? provider = null, string? model = null)
    {
        ArgumentNullException.ThrowIfNull(budget);
        var window = budget.ContextWindow;
        if (budget.Estimate.UnpricedParts != 0 || window is null || !Trusted(window.Provenance) || budget.Estimate.Floor <= window.Value)
        {
            return null;
        }

        var name = model ?? "the model";
        var detail = $"request needs at least {budget.Estimate.Floor} input tokens (preflight estimate), exceeding {name}'s {window.Value}-token context window ({ProvenanceName(window.Provenance)})";
        return new ContextLengthException(
            detail,
            provider: provider,
            detail: detail,
            hint: "shorten the prompt, or set Route.context_window_targets so overflow falls back to a larger-context model");
    }

    /// <summary>Builds a budget and throws its explicit context-length refusal when one is proven.</summary>
    public static ContextBudget CheckContextFit(
        GenerationRequest request,
        ModelCapabilities? capabilities,
        ITokenEstimator? estimator = null,
        TokenCalibration? calibration = null,
        long? outputReserveTokens = null,
        string? provider = null,
        string? model = null)
    {
        var budget = BuildContextBudget(request, capabilities, estimator, calibration, outputReserveTokens);
        var error = ContextGateError(budget, provider, model);
        if (error is not null)
        {
            throw error;
        }

        return budget;
    }

    private static long ResolveReserve(GenerationRequest request, ModelCapabilities? capabilities, long? explicitReserve)
    {
        if (explicitReserve is { } reserve)
        {
            if (reserve < 0)
            {
                throw new ArgumentOutOfRangeException(nameof(explicitReserve), "Output reserve must not be negative.");
            }

            return reserve;
        }

        if (request.Sampling?.MaxOutputTokens is { } requested)
        {
            return requested;
        }

        return capabilities?.MaxOutputTokens is { } maximum
            ? Math.Min(DefaultOutputReserveTokens, maximum.Value)
            : DefaultOutputReserveTokens;
    }

    private static bool Trusted(Provenance provenance) => provenance is Provenance.Catalog or Provenance.Discovered or Provenance.Probed or Provenance.Override;

    private static string ProvenanceName(Provenance provenance) => provenance.ToString().ToLowerInvariant();
}
