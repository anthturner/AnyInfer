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
    /// <param name="contextWindowTokens">Context window in tokens.</param>
    /// <returns>
    /// <see cref="HeadroomFraction"/> of the window rounded up, clamped to
    /// [<see cref="MinimumHeadroomTokens"/>, <see cref="MaximumHeadroomTokens"/>].
    /// </returns>
    public static long HeadroomFor(long contextWindowTokens)
    {
        var candidate = checked((long)Math.Ceiling(contextWindowTokens * HeadroomFraction));
        return Math.Max(MinimumHeadroomTokens, Math.Min(MaximumHeadroomTokens, candidate));
    }

    /// <summary>Builds a pure context budget without dispatching, validating schemas, or resolving a provider.</summary>
    /// <param name="request">Request to estimate.</param>
    /// <param name="capabilities">
    /// Target capabilities supplying the context window, maximum output, and pricing facts with their provenance;
    /// <see langword="null"/> leaves all three unknown.
    /// </param>
    /// <param name="estimator">Token estimator, or <see langword="null"/> for the built-in <see cref="HeuristicTokenEstimator"/>.</param>
    /// <param name="calibration">Provider envelope calibration, or <see langword="null"/> for none.</param>
    /// <param name="outputReserveTokens">
    /// Response reserve; <see langword="null"/> uses the request's maximum output tokens, else
    /// <see cref="DefaultOutputReserveTokens"/> capped by a known maximum output.
    /// </param>
    /// <param name="headroomTokens">
    /// Safety headroom; <see langword="null"/> uses <see cref="HeadroomFor"/> when a window is known and zero otherwise.
    /// </param>
    /// <returns>A budget whose window, allowance, and fit stay unknown when no context window is known.</returns>
    /// <exception cref="ArgumentNullException"><paramref name="request"/> is <see langword="null"/>.</exception>
    /// <exception cref="ArgumentOutOfRangeException"><paramref name="outputReserveTokens"/> or <paramref name="headroomTokens"/> is negative.</exception>
    /// <exception cref="InvalidOperationException"><paramref name="estimator"/> returned <see langword="null"/>.</exception>
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
    /// <remarks>
    /// Only a window with catalog, discovered, probed, or override provenance can gate, and only the estimate's
    /// low-biased floor is compared against the whole window, without reserve or headroom. A
    /// <see cref="Provenance.Default"/> window or an estimate with unpriced content parts never gates.
    /// </remarks>
    /// <param name="budget">Budget to check.</param>
    /// <param name="provider">Provider identity recorded on the error, or <see langword="null"/>.</param>
    /// <param name="model">Model name used in the error message, or <see langword="null"/> for a generic name.</param>
    /// <returns>An unthrown <see cref="ContextLengthException"/>, or <see langword="null"/> when the request may fit.</returns>
    /// <exception cref="ArgumentNullException"><paramref name="budget"/> is <see langword="null"/>.</exception>
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
    /// <remarks>Uses the default headroom; see <see cref="BuildContextBudget"/> and <see cref="ContextGateError"/>.</remarks>
    /// <param name="request">Request to estimate.</param>
    /// <param name="capabilities">Target capabilities, or <see langword="null"/> when unknown.</param>
    /// <param name="estimator">Token estimator, or <see langword="null"/> for the built-in heuristic.</param>
    /// <param name="calibration">Provider envelope calibration, or <see langword="null"/> for none.</param>
    /// <param name="outputReserveTokens">Response reserve, or <see langword="null"/> for the derived default.</param>
    /// <param name="provider">Provider identity recorded on a refusal, or <see langword="null"/>.</param>
    /// <param name="model">Model name used in a refusal message, or <see langword="null"/>.</param>
    /// <returns>The budget, when no trusted refusal is proven.</returns>
    /// <exception cref="ContextLengthException">The estimate's floor exceeds a trusted context window.</exception>
    /// <exception cref="ArgumentNullException"><paramref name="request"/> is <see langword="null"/>.</exception>
    /// <exception cref="ArgumentOutOfRangeException"><paramref name="outputReserveTokens"/> is negative.</exception>
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
