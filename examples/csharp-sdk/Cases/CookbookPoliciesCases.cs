using System.Text.Json;
using PeterO.Numbers;

namespace AnyInfer.Examples.Cases;

/// <summary>Runs the metered multi-tenant summarizer offline.</summary>
internal static class CookbookPoliciesCases
{
    // About 85 KB: its conservative token floor provably exceeds the small model's 8,192-token window.
    private static readonly string LongDocument = string.Concat(Enumerable.Repeat("Quarterly shipping volumes rose across every region. ", 1_600));

    [ExampleCase("cookbook.policies.metered-batch")]
    internal static async Task MeteredBatch()
    {
        var gateway = new CookbookScriptedHandler(
            CookbookReplies.Chat("Acme summary.", 1_200, 250),
            CookbookReplies.Chat("Globex summary.", 25_000, 280));
        var lab = new CookbookScriptedHandler(CookbookReplies.Chat("Initech summary.", 900, 200));
        using var store = new TemporaryStore();
        var output = new StringWriter();
        CookbookMeteredRun run;
        using (new CookbookEnvironment(("LLM_GATEWAY_KEY", "offline-gateway-key")))
        {
            run = await CookbookPoliciesExample.RunAsync(
                Offline(gateway, lab),
                [
                    new CookbookJob("j1", "acme", "The board approved the new office."),
                    new CookbookJob("j2", "globex", LongDocument),
                    new CookbookJob("j3", "initech", "Internal roadmap notes.", SelfHosted: true),
                    new CookbookJob("j4", "globex", LongDocument),
                ],
                store.Path,
                "2026-10",
                Usd("0.05"),
                output);
        }

        var (j1, j2, j3, j4) = (run.Jobs[0], run.Jobs[1], run.Jobs[2], run.Jobs[3]);
        // Prices are the caller's override facts: 1,200 x $0.20/M + 250 x $0.60/M, and 25,000 x $1/M + 280 x $4/M.
        ExampleSupport.Require(j1 is { FitsFirstTarget: true, ServedBy: "gateway:small", Refusal: null, Cache: null }
            && Same(j1.CostUsd, "0.00039")
            && j2 is { FitsFirstTarget: false, ServedBy: "gateway:large", Refusal: null }
            && Same(j2.CostUsd, "0.02612")
            && j2.QueuedMs > 150,
            "The small model did not serve the short job, or the context gate did not move the long one to the large model.");
        ExampleSupport.Require(j3 is { FitsFirstTarget: null, EstimatedHighUsd: null, ServedBy: "lab:qwen3-8b", CostUsd: null, Refusal: null },
            "The self-hosted job's unknown window and cost were not left unknown.");
        ExampleSupport.Require(j4 is { ServedBy: null, Refusal: { Category: "spend_limit" } refusal }
            && Same(refusal.LimitUsd, "0.05")
            && Same(refusal.SpentUsd, "0.02651")
            && refusal.EstimatedUsd!.CompareTo(Usd("0.02349")) > 0,
            "The second long job was not refused before dispatch by the run's spend ceiling.");

        // Exactly three requests were sent, each with the gateway's resolved credential reference.
        ExampleSupport.Require(gateway.Requests.Select(static request => request.Json().GetProperty("model").GetString()).SequenceEqual(["small", "large"])
            && gateway.Requests.All(static request => request.Authorization == "Bearer offline-gateway-key")
            && lab.Requests.Count == 1
            && lab.Requests[0].Authorization is null
            && gateway.DisposeCount == 1
            && lab.DisposeCount == 1,
            "The batch sent a refused request, or a credential reached the wrong server.");

        // The ledger counts the unknown-cost request instead of treating it as free.
        ExampleSupport.Require(run.Totals is { Requests: 3, UnknownRequests: 1, Complete: false, InputTokens: 27_100, OutputTokens: 730 }
            && Same(run.Totals.Cost, "0.02651")
            && run.ByTarget.Keys.SequenceEqual(["gateway:small", "gateway:large", "lab:qwen3-8b"])
            && run.ByTarget["lab:qwen3-8b"] is { UnknownRequests: 1, Complete: false }
            && run.ByTenant.Keys.SequenceEqual(["acme", "globex", "initech"])
            && Same(run.ByTenant["globex"].Cost, "0.02612")
            && run.Stored.Keys.SequenceEqual(["2026-10"])
            && run.Stored["2026-10"] == run.Totals
            && output.ToString().Contains("j4 [globex] refused: $0.0265100 spent, next up to $", StringComparison.Ordinal)
            && output.ToString().Contains("run: $0.0265100 over 3 request(s); 1 with unknown cost", StringComparison.Ordinal),
            "Ledger snapshots, labels or the persisted bucket disagree with the requests that were sent.");
    }

    [ExampleCase("cookbook.policies.store-across-runs")]
    internal static async Task StoreAcrossRuns()
    {
        using var store = new TemporaryStore();
        CookbookMeteredRun october, november;
        using (new CookbookEnvironment(("LLM_GATEWAY_KEY", "offline-gateway-key")))
        {
            var first = new CookbookScriptedHandler(CookbookReplies.Chat("One.", 1_000, 100));
            october = await CookbookPoliciesExample.RunAsync(
                Offline(first, new CookbookScriptedHandler()),
                [new CookbookJob("a", "acme", "First document.")],
                store.Path, "2026-10", Usd("1"), new StringWriter());

            // A document too large for the per-request ceiling is refused on every target; nothing is sent.
            var second = new CookbookScriptedHandler(CookbookReplies.Chat("Two.", 2_000, 100));
            november = await CookbookPoliciesExample.RunAsync(
                Offline(second, new CookbookScriptedHandler()),
                [
                    new CookbookJob("b", "acme", "Second document."),
                    new CookbookJob("c", "acme", string.Concat(Enumerable.Repeat(LongDocument, 2))),
                ],
                store.Path, "2026-10", Usd("1"), new StringWriter());
            ExampleSupport.Require(first.Requests.Count == 1 && second.Requests.Count == 1,
                "A request over the per-request ceiling was sent.");
        }

        // Each run owns a fresh ledger; the store adds them into the bucket the caller named.
        using var persisted = JsonDocument.Parse(File.ReadAllText(store.Path));
        ExampleSupport.Require(october.Totals.Requests == 1
            && november.Totals.Requests == 1
            && november.Jobs[1].Refusal is { LimitUsd: { } limit } && Same(limit, "0.04")
            && november.Stored["2026-10"] is { Requests: 2, InputTokens: 3_000, OutputTokens: 200, UnknownRequests: 0 } stored
            && Same(stored.Cost, "0.00072")
            && persisted.RootElement.GetProperty("format_version").GetInt32() == 1,
            "The store did not accumulate both runs into one version 1 bucket.");
    }

    [ExampleCase("cookbook.policies.refuse-unknown-cost")]
    internal static async Task RefuseUnknownCost()
    {
        using var store = new TemporaryStore();
        var gateway = new CookbookScriptedHandler(CookbookReplies.Chat("Priced.", 1_000, 100));
        var lab = new CookbookScriptedHandler();
        CookbookMeteredRun run;
        using (new CookbookEnvironment(("LLM_GATEWAY_KEY", "offline-gateway-key")))
        {
            run = await CookbookPoliciesExample.RunAsync(
                Offline(gateway, lab),
                [new CookbookJob("p", "acme", "Priced work."), new CookbookJob("u", "initech", "Unpriced work.", SelfHosted: true)],
                store.Path, "2026-10", Usd("1"), new StringWriter(), refuseUnknownCost: true);
        }

        // With no trusted price there is no estimate to admit, so strict metering refuses before sending.
        ExampleSupport.Require(run.Jobs[0] is { ServedBy: "gateway:small", Refusal: null }
            && run.Jobs[1] is { ServedBy: null, Refusal: { EstimatedUsd: null, Category: "spend_limit" } }
            && lab.Requests.Count == 0
            && run.Totals is { Requests: 1, UnknownRequests: 0, Complete: true },
            "Strict metering sent a request whose cost could not be estimated.");
    }

    private static ProviderSettings[] Offline(HttpMessageHandler gateway, HttpMessageHandler lab)
    {
        var transports = new Dictionary<string, HttpMessageHandler> { ["gateway"] = gateway, ["lab"] = lab };
        return CookbookPoliciesExample.Providers.Select(provider => ExampleSupport.WithTransport(provider, transports[provider.InstanceId])).ToArray();
    }

    private static EDecimal Usd(string value) => EDecimal.FromString(value);

    private static bool Same(EDecimal? actual, string expected) => actual is not null && actual.CompareTo(Usd(expected)) == 0;

    private sealed class TemporaryStore : IDisposable
    {
        internal string Path { get; } = System.IO.Path.Combine(System.IO.Path.GetTempPath(), $"anyinfer-cookbook-{Guid.NewGuid():N}.json");

        public void Dispose()
        {
            if (File.Exists(Path)) File.Delete(Path);
        }
    }
}
