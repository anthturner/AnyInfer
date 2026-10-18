using AnyInfer.Capabilities;
using AnyInfer.Json;
using AnyInfer.Routing;
using PeterO.Numbers;

namespace AnyInfer.Examples;

/// <summary>Uses explicit pricing, budgeting, ledger, store, and standalone pacing helpers.</summary>
public static class AccountingExample
{
    /// <summary>Runs one caller-configured generation and records only caller-selected accounting state.</summary>
    public static async Task<AccountingObservation> RunAsync(
        ProviderSettings settings,
        string target,
        string storePath,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(settings);
        ArgumentException.ThrowIfNullOrWhiteSpace(target);
        ArgumentException.ThrowIfNullOrWhiteSpace(storePath);

        var trustedPricing = new ModelCapabilities(
            pricing: new Sourced<Pricing>(
                new Pricing(EDecimal.FromString("2"), EDecimal.FromString("4")),
                Provenance.Catalog));
        var defaultPricing = new ModelCapabilities(
            pricing: new Sourced<Pricing>(
                new Pricing(EDecimal.FromString("2"), EDecimal.FromString("4")),
                Provenance.Default));
        var freePricing = new ModelCapabilities(
            pricing: new Sourced<Pricing>(new Pricing(EDecimal.Zero, EDecimal.Zero), Provenance.Catalog));
        var usage = new Usage(InputTokens: 1_000, OutputTokens: 500);
        var pricedUsage = PricingCalculator.WithCost(usage, trustedPricing);
        var unknownCost = PricingCalculator.ComputeCost(usage, defaultPricing);
        var freeUsage = PricingCalculator.WithCost(usage, freePricing);

        var request = new GenerationRequest(
            [new Message("user", [new Text("Count this request."), new UnsupportedContentPart("image", new JsonObject([]))])],
            new Route([target]));
        var ledger = new SpendLedger();
        ContextBudget budget;
        Generation generation;
        await using (var client = new AsyncClient([settings], ledger: ledger))
        {
            budget = client.Budget(request, target, outputReserveTokens: 32);
            generation = await client.GenerateAsync(
                "Count this request.",
                target: target,
                cancellationToken: cancellationToken).ConfigureAwait(false);
        }

        var storeWasAbsent = !File.Exists(storePath);
        var store = new SpendStore(storePath);
        store.Accumulate(ledger);
        var persisted = store.Load();

        var limiter = new RateLimiter(new RateLimits(maxConcurrent: 1, respectHeaders: false));
        await using (var firstLease = await limiter.AcquireAsync(cancellationToken).ConfigureAwait(false))
        {
        }

        await using (var secondLease = await limiter.AcquireAsync(cancellationToken).ConfigureAwait(false))
        {
        }

        return new AccountingObservation(
            pricedUsage,
            unknownCost,
            freeUsage,
            budget,
            TokenEstimation.EstimateRequest(request),
            generation,
            ledger.Totals(),
            persisted,
            storeWasAbsent,
            File.Exists(storePath));
    }
}

/// <summary>Contains immutable outputs from one explicit accounting demonstration.</summary>
public sealed record AccountingObservation(
    Usage PricedUsage,
    EDecimal? UnknownCost,
    Usage FreeUsage,
    ContextBudget Budget,
    RequestEstimate RequestEstimate,
    Generation Generation,
    SpendTotals Totals,
    IReadOnlyDictionary<string, SpendTotals> Persisted,
    bool StoreWasAbsent,
    bool StoreWritten);
