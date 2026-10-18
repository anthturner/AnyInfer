using AnyInfer.Internal;
using PeterO.Numbers;

namespace AnyInfer.Capabilities;

/// <summary>Computes known generation and operation costs from trusted capability pricing.</summary>
public static class PricingCalculator
{
    /// <summary>Computes generation cost from reported usage, or returns null when it cannot be known.</summary>
    public static EDecimal? ComputeCost(Usage usage, ModelCapabilities? capabilities)
    {
        ArgumentNullException.ThrowIfNull(usage);
        if (!TrustedPricing(capabilities, out var pricing) || usage.InputTokens is null || usage.OutputTokens is null)
        {
            return null;
        }

        var toolCost = ServerToolCost(usage, pricing);
        if (toolCost is null)
        {
            return null;
        }

        var outputCost = AccountingDecimal.Price(pricing.OutputPer1M, usage.OutputTokens.Value);
        return AccountingDecimal.Add(AccountingDecimal.Add(InputCost(usage, pricing), outputCost), toolCost);
    }

    /// <summary>Returns a copy with cost filled only when a provider did not already report one.</summary>
    public static Usage WithCost(Usage usage, ModelCapabilities? capabilities)
    {
        ArgumentNullException.ThrowIfNull(usage);
        if (usage.CostUsd is not null || ComputeCost(usage, capabilities) is not { } cost)
        {
            return usage;
        }

        return CopyWithCost(usage, cost);
    }

    /// <summary>Computes an operation-specific cost from trusted capability pricing.</summary>
    public static EDecimal? ComputeOperationCost(Usage usage, ModelCapabilities? capabilities, InferenceOperation operation)
    {
        ArgumentNullException.ThrowIfNull(usage);
        if (!TrustedPricing(capabilities, out var pricing))
        {
            return null;
        }

        if (operation == InferenceOperation.Embedding)
        {
            var tokens = usage.InputTokens ?? usage.TotalTokens;
            return tokens is null ? null : AccountingDecimal.Price(pricing.InputPer1M, tokens.Value);
        }

        if (operation == InferenceOperation.Rerank)
        {
            return usage.SearchUnits is null || pricing.PerSearchUnit is null
                ? null
                : AccountingDecimal.Multiply(EDecimal.FromInt64(usage.SearchUnits.Value), pricing.PerSearchUnit);
        }

        return ComputeCost(usage, capabilities);
    }

    /// <summary>Returns a copy with an operation-specific cost only when no provider cost exists.</summary>
    public static Usage WithOperationCost(Usage usage, ModelCapabilities? capabilities, InferenceOperation operation)
    {
        ArgumentNullException.ThrowIfNull(usage);
        if (usage.CostUsd is not null || ComputeOperationCost(usage, capabilities, operation) is not { } cost)
        {
            return usage;
        }

        return CopyWithCost(usage, cost);
    }

    /// <summary>Estimates a request cost range from trusted rates and explicit output reserve.</summary>
    public static CostEstimate? EstimateCost(RequestEstimate estimate, long outputReserveTokens, Sourced<Pricing>? pricing)
    {
        ArgumentNullException.ThrowIfNull(estimate);
        if (pricing is null || !Trusted(pricing.Provenance))
        {
            return null;
        }

        var rates = pricing.Value;
        var low = AccountingDecimal.Price(rates.InputPer1M, estimate.Floor);
        var high = AccountingDecimal.Add(
            AccountingDecimal.Price(rates.InputPer1M, estimate.Tokens),
            AccountingDecimal.Price(rates.OutputPer1M, outputReserveTokens));
        return new CostEstimate(low, high, rates.Currency);
    }

    private static Usage CopyWithCost(Usage usage, EDecimal cost) => new(
        InputTokens: usage.InputTokens,
        OutputTokens: usage.OutputTokens,
        TotalTokens: usage.TotalTokens,
        CacheReadTokens: usage.CacheReadTokens,
        CacheWriteTokens: usage.CacheWriteTokens,
        ReasoningTokens: usage.ReasoningTokens,
        CostUsd: cost,
        SearchUnits: usage.SearchUnits,
        ServerToolUses: usage.ServerToolUses);

    private static bool TrustedPricing(ModelCapabilities? capabilities, out Pricing pricing)
    {
        if (capabilities?.Pricing is { } source && Trusted(source.Provenance))
        {
            pricing = source.Value;
            return true;
        }

        pricing = null!;
        return false;
    }

    private static bool Trusted(Provenance provenance) => provenance is Provenance.Catalog or Provenance.Discovered or Provenance.Probed or Provenance.Override;

    private static EDecimal? ServerToolCost(Usage usage, Pricing pricing)
    {
        var total = EDecimal.Zero;
        foreach (var (kind, uses) in usage.ServerToolUses)
        {
            if (!pricing.PerServerToolUse.TryGetValue(kind, out var rate))
            {
                return null;
            }

            total = AccountingDecimal.Add(total, AccountingDecimal.Multiply(EDecimal.FromInt64(uses), rate));
        }

        return total;
    }

    private static EDecimal InputCost(Usage usage, Pricing pricing)
    {
        var inputTokens = usage.InputTokens!.Value;
        var readTokens = usage.CacheReadTokens ?? 0;
        var writeTokens = usage.CacheWriteTokens ?? 0;
        EDecimal total;
        if (pricing.CacheReadPer1M is null || readTokens <= 0)
        {
            total = AccountingDecimal.Price(pricing.InputPer1M, inputTokens);
        }
        else
        {
            var uncached = inputTokens > readTokens ? checked(inputTokens - readTokens) : inputTokens;
            total = AccountingDecimal.Add(
                AccountingDecimal.Price(pricing.InputPer1M, uncached),
                AccountingDecimal.Price(pricing.CacheReadPer1M, readTokens));
        }

        return pricing.CacheWritePer1M is not null && writeTokens > 0
            ? AccountingDecimal.Add(total, AccountingDecimal.Price(pricing.CacheWritePer1M, writeTokens))
            : total;
    }
}
