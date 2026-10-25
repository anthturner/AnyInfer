using AnyInfer.Capabilities;

namespace AnyInfer.Examples;

/// <summary>
/// Shares one caller-owned ledger between clients, labels spend by tenant, and persists each period's
/// totals in a caller-selected store.
/// </summary>
public static class SpendStoreExample
{
    // --8<-- [start:record]
    /// <summary>Generates one response whose spend the ledger groups under a tenant label.</summary>
    /// <param name="client">A client constructed with the application's shared <see cref="SpendLedger"/>.</param>
    /// <param name="target">A <c>provider:model</c> target.</param>
    /// <param name="tenant">The tenant label; it is reported to the ledger and never sent to the provider.</param>
    /// <param name="prompt">The prompt text.</param>
    /// <param name="cancellationToken">Cancels the call.</param>
    /// <returns>The buffered result, whose usage cost is <see langword="null"/> when it cannot be priced.</returns>
    public static Task<Generation> GenerateForTenantAsync(
        AsyncClient client,
        string target,
        string tenant,
        string prompt,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(client);
        return client.GenerateAsync(
            prompt,
            target: target,
            metadata: new Dictionary<string, string> { ["tenant"] = tenant },
            cancellationToken: cancellationToken);
    }
    // --8<-- [end:record]

    // --8<-- [start:period]
    /// <summary>Adds the ledger's totals to one store bucket, then starts the next period empty.</summary>
    /// <param name="ledger">The shared ledger; the application owns it.</param>
    /// <param name="store">A store at a path the application chose.</param>
    /// <param name="period">The bucket name, such as <c>2026-10</c>.</param>
    /// <returns>Every bucket the store now holds.</returns>
    public static IReadOnlyDictionary<string, SpendTotals> ClosePeriod(SpendLedger ledger, SpendStore store, string period)
    {
        ArgumentNullException.ThrowIfNull(ledger);
        ArgumentNullException.ThrowIfNull(store);
        // Accumulate adds totals without resetting the ledger, so reset it to avoid adding them twice.
        store.Accumulate(ledger, bucket: period);
        ledger.Reset();
        return store.Load();
    }
    // --8<-- [end:period]
}
