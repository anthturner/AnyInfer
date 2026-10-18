using PeterO.Numbers;

namespace AnyInfer;

/// <summary>Represents refusal before dispatch because a caller-set spend ceiling would be crossed.</summary>
public sealed class SpendLimitException : AnyInferException
{
    /// <summary>Initializes a spend-limit refusal and preserves its known accounting facts.</summary>
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

    /// <summary>Gets the crossed ceiling, when known.</summary>
    public EDecimal? LimitUsd { get; }
    /// <summary>Gets completed spend observed before refusal, when known.</summary>
    public EDecimal? SpentUsd { get; }
    /// <summary>Gets the refused request estimate, when known.</summary>
    public EDecimal? EstimatedUsd { get; }
}
