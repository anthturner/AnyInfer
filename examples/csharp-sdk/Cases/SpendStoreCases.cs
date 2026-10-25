using AnyInfer.Capabilities;
using PeterO.Numbers;

namespace AnyInfer.Examples.Cases;

/// <summary>Executes and asserts the shared-ledger, tenant-label, and period-store recipe.</summary>
internal static class SpendStoreCases
{
    /// <summary>Two clients share one ledger; an unpriced request is counted as unknown, never as free.</summary>
    [ExampleCase("spend-store.shared-ledger")]
    internal static async Task SharedLedger()
    {
        var ledger = new SpendLedger();
        var priced = new RecipeChatHandler(inputTokens: 1_000, outputTokens: 500);
        var unpriced = new RecipeChatHandler(inputTokens: 1_000, outputTokens: 500);
        var pricing = new Dictionary<string, IReadOnlyDictionary<string, ModelCapabilities>>
        {
            ["priced"] = new Dictionary<string, ModelCapabilities>
            {
                ["demo"] = new(pricing: new Sourced<Pricing>(
                    new Pricing(EDecimal.FromString("2"), EDecimal.FromString("4")), Provenance.Override)),
            },
        };
        await using (var first = new AsyncClient([Settings("priced", priced)], ledger: ledger, capabilityOverrides: pricing))
        await using (var second = new AsyncClient([Settings("unpriced", unpriced)], ledger: ledger))
        {
            var known = await SpendStoreExample.GenerateForTenantAsync(first, "priced:demo", "tenant-a", "Say hello.");
            var unknown = await SpendStoreExample.GenerateForTenantAsync(second, "unpriced:demo", "tenant-b", "Say hello.");
            ExampleSupport.Require(
                known.Usage?.CostUsd?.CompareTo(EDecimal.FromString("0.004")) == 0 && unknown.Usage is { CostUsd: null },
                "Priced and unpriced results did not report known and unknown cost.");
        }

        var totals = ledger.Totals();
        var byTenant = ledger.ByLabel("tenant");
        ExampleSupport.Require(
            totals.Requests == 2
            && totals.UnknownRequests == 1
            && !totals.Complete
            && totals.Cost.CompareTo(EDecimal.FromString("0.004")) == 0
            && byTenant["tenant-a"] is { Requests: 1, UnknownRequests: 0 }
            && byTenant["tenant-b"] is { Requests: 1, UnknownRequests: 1 }
            && priced.Bodies.Concat(unpriced.Bodies).All(static body => !body.ToString().Contains("tenant", StringComparison.Ordinal)),
            "The shared ledger did not separate known cost, unknown requests, and tenant labels, or a label reached the wire.");
        ExampleSupport.Require(priced.Disposals == 1 && unpriced.Disposals == 1, "A client disposed a transport it did not own, or missed its own.");
    }

    /// <summary>Closing a period adds totals to its bucket and resets the ledger, so totals are never added twice.</summary>
    [ExampleCase("spend-store.period-buckets")]
    internal static void PeriodBuckets()
    {
        WithDirectory(directory =>
        {
            var path = Path.Combine(directory, "accounting", "spend.json");
            var store = new SpendStore(path);
            ExampleSupport.Require(!File.Exists(path) && store.Load().Count == 0, "Creating a store touched its path.");

            var ledger = new SpendLedger();
            var target = new ResolvedTarget("priced", "demo");
            ledger.Record(target, new Usage(InputTokens: 10, OutputTokens: 5, CostUsd: EDecimal.FromString("0.25")));
            var first = SpendStoreExample.ClosePeriod(ledger, store, "2026-10");
            ledger.Record(target, new Usage(InputTokens: 10, OutputTokens: 5, CostUsd: EDecimal.FromString("0.25")));
            ledger.Record(target, new Usage(InputTokens: 10, OutputTokens: 5));
            var second = SpendStoreExample.ClosePeriod(ledger, store, "2026-10");
            var third = SpendStoreExample.ClosePeriod(ledger, store, "2026-11");
            ExampleSupport.Require(
                first["2026-10"] is { Requests: 1, UnknownRequests: 0 }
                && second["2026-10"] is { Requests: 3, UnknownRequests: 1, InputTokens: 30 }
                && second["2026-10"].Cost.CompareTo(EDecimal.FromString("0.5")) == 0
                && third["2026-11"].Requests == 0
                && ledger.Totals().Requests == 0
                && File.Exists(path),
                "Closing periods did not accumulate each bucket once and reset the ledger.");

            var euros = new SpendLedger("EUR");
            euros.Record(target, new Usage(InputTokens: 1, OutputTokens: 1, CostUsd: EDecimal.One));
            var mismatch = RecipeSupport.Capture(() => SpendStoreExample.ClosePeriod(euros, store, "2026-10"));
            ExampleSupport.Require(
                mismatch is ArgumentException && euros.Totals().Requests == 1,
                "A currency mismatch was accepted, or the ledger was reset after a failed accumulation.");
        });
    }

    /// <summary>A store keeps at most 512 buckets and uses its path literally.</summary>
    [ExampleCase("spend-store.bucket-cap-and-literal-path")]
    internal static void BucketCapAndLiteralPath()
    {
        WithDirectory(directory =>
        {
            var store = new SpendStore(Path.Combine(directory, "spend.json"));
            var ledger = new SpendLedger();
            IReadOnlyDictionary<string, SpendTotals> buckets = new Dictionary<string, SpendTotals>();
            for (var index = 0; index <= 512; index++)
            {
                ledger.Record(new ResolvedTarget("priced", "demo"), new Usage(InputTokens: 1, OutputTokens: 1));
                buckets = SpendStoreExample.ClosePeriod(ledger, store, $"bucket-{index:D3}");
            }

            ExampleSupport.Require(
                buckets.Count == 512 && !buckets.ContainsKey("bucket-000") && buckets.ContainsKey("bucket-512"),
                "The store did not drop its earliest bucket when a 513th was added.");
        });

        var home = new SpendStore("~/anyinfer-spend.json");
        ExampleSupport.Require(
            home.Path == "~/anyinfer-spend.json" && home.Load().Count == 0,
            "A store path beginning with ~ was not kept literally.");
    }

    private static ProviderSettings Settings(string alias, HttpMessageHandler transport) =>
        ProviderSettings.Of("openai-compat", ExampleSupport.BaseUrl, transport: transport, alias: alias);

    private static void WithDirectory(Action<string> body)
    {
        var directory = Path.Combine(Path.GetTempPath(), $"anyinfer-spend-{Guid.NewGuid():N}");
        try
        {
            body(directory);
        }
        finally
        {
            if (Directory.Exists(directory))
            {
                Directory.Delete(directory, recursive: true);
            }
        }
    }
}
