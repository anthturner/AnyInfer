using AnyInfer.Internal;
using PeterO.Numbers;

namespace AnyInfer.Capabilities;

/// <summary>Computes known generation and operation costs from trusted capability pricing.</summary>
/// <remarks>
/// Pricing is trusted only at catalog, discovered, probed, or override provenance; a
/// <see cref="Provenance.Default"/> price is a placeholder and never produces money. An unknown cost is
/// returned as <see langword="null"/>, never as zero. Amounts are in the pricing's currency.
/// </remarks>
public static class PricingCalculator
{
    /// <summary>Computes generation cost from reported usage, or returns null when it cannot be known.</summary>
    /// <remarks>
    /// Input is priced at the input rate, except that reported cache-read tokens use the cache-read rate when one
    /// is known; reported cache-write tokens add the cache-write rate when one is known; output uses the output
    /// rate; and each reported provider-run tool use adds its per-use price.
    /// </remarks>
    /// <param name="usage">Provider-reported usage.</param>
    /// <param name="capabilities">Target capabilities carrying pricing, or <see langword="null"/> when unknown.</param>
    /// <returns>
    /// The cost, or <see langword="null"/> when pricing is missing or untrusted, input or output tokens were not
    /// reported, or a reported tool use has no known price.
    /// </returns>
    /// <exception cref="ArgumentNullException"><paramref name="usage"/> is <see langword="null"/>.</exception>
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
    /// <param name="usage">Provider-reported usage.</param>
    /// <param name="capabilities">Target capabilities carrying pricing, or <see langword="null"/> when unknown.</param>
    /// <returns>
    /// <paramref name="usage"/> itself when it already has a cost or <see cref="ComputeCost"/> returns
    /// <see langword="null"/>; otherwise a copy whose cost is the computed amount.
    /// </returns>
    /// <exception cref="ArgumentNullException"><paramref name="usage"/> is <see langword="null"/>.</exception>
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
    /// <param name="usage">Provider-reported usage.</param>
    /// <param name="capabilities">Target capabilities carrying pricing, or <see langword="null"/> when unknown.</param>
    /// <param name="operation">
    /// Operation that produced the usage: embedding prices input tokens (or total tokens when input is not
    /// reported) at the input rate, rerank prices search units at the per-search-unit rate, and any other
    /// operation uses <see cref="ComputeCost"/>.
    /// </param>
    /// <returns>The cost, or <see langword="null"/> when pricing is missing or untrusted or the needed usage or rate is unknown.</returns>
    /// <exception cref="ArgumentNullException"><paramref name="usage"/> is <see langword="null"/>.</exception>
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
    /// <param name="usage">Provider-reported usage.</param>
    /// <param name="capabilities">Target capabilities carrying pricing, or <see langword="null"/> when unknown.</param>
    /// <param name="operation">Operation that produced the usage, as for <see cref="ComputeOperationCost"/>.</param>
    /// <returns>
    /// <paramref name="usage"/> itself when it already has a cost or the cost is unknown; otherwise a copy whose
    /// cost is the computed amount.
    /// </returns>
    /// <exception cref="ArgumentNullException"><paramref name="usage"/> is <see langword="null"/>.</exception>
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
    /// <remarks>
    /// The low end prices the estimate's floor as input with no output; the high end prices the planning
    /// estimate as input plus the full output reserve. Cache rates are not applied. The range is a preflight
    /// estimate and never reported spend.
    /// </remarks>
    /// <param name="estimate">Estimated input size of the request.</param>
    /// <param name="outputReserveTokens">Output tokens priced into the high end.</param>
    /// <param name="pricing">Pricing fact with its provenance, or <see langword="null"/> when unknown.</param>
    /// <returns>The cost range, or <see langword="null"/> when pricing is missing or untrusted.</returns>
    /// <exception cref="ArgumentNullException"><paramref name="estimate"/> is <see langword="null"/>.</exception>
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
