using PeterO.Numbers;

namespace AnyInfer;

/// <summary>Represents refusal before dispatch because a caller-set spend ceiling would be crossed.</summary>
/// <remarks>
/// A <see cref="SpendPolicy"/> also raises it when a target's cost cannot be estimated and
/// <see cref="SpendPolicy.OnUnknown"/> is <c>refuse</c>; <see cref="EstimatedUsd"/> is then
/// <see langword="null"/>. The category is always <c>spend_limit</c>, the phase <c>generate</c>
/// (also for embedding and rerank requests), and the refusal is never retryable. No provider
/// request is sent for a refused attempt.
/// </remarks>
public sealed class SpendLimitException : AnyInferException
{
    /// <summary>Initializes a spend-limit refusal and preserves its known accounting facts.</summary>
    /// <param name="message">Refusal message; registered secrets are redacted.</param>
    /// <param name="limitUsd">The ceiling that would be crossed, in US dollars, or <see langword="null"/> when unknown.</param>
    /// <param name="spentUsd">Spend already recorded before the refusal, in US dollars, or <see langword="null"/> when unknown.</param>
    /// <param name="estimatedUsd">Estimated cost of the refused request, in US dollars, or <see langword="null"/> when it could not be estimated.</param>
    /// <param name="hint">Actionable next step for the caller, redacted; <see langword="null"/> for none.</param>
    /// <exception cref="ArgumentNullException"><paramref name="message"/> is <see langword="null"/>.</exception>
    public SpendLimitException(
        string message,
        EDecimal? limitUsd = null,
        EDecimal? spentUsd = null,
        EDecimal? estimatedUsd = null,
        string? hint = null)
        : base(message, "spend_limit", false, "generate", hint: hint)
    {
        LimitUsd = limitUsd;
        SpentUsd = spentUsd;
        EstimatedUsd = estimatedUsd;
    }

    /// <summary>Gets the crossed ceiling in US dollars, when known.</summary>
    public EDecimal? LimitUsd { get; }
    /// <summary>Gets completed spend in US dollars observed before refusal, when known.</summary>
    public EDecimal? SpentUsd { get; }
    /// <summary>Gets the refused request estimate in US dollars, when known.</summary>
    public EDecimal? EstimatedUsd { get; }
}
