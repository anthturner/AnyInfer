using AnyInfer.Capabilities;
using PeterO.Numbers;

namespace AnyInfer.Examples.Cases;

/// <summary>Executes and asserts spend admission: within ceilings, over a ceiling, and unknown cost.</summary>
internal static class SpendAdmissionCases
{
    private static readonly Pricing Price = new(EDecimal.FromString("2"), EDecimal.FromString("4"));

    /// <summary>A priced request within both ceilings is sent and its cost is recorded in the caller's ledger.</summary>
    [ExampleCase("spend-admission.within-ceilings")]
    internal static async Task WithinCeilings()
    {
        var ledger = new SpendLedger();
        var transport = new RecipeChatHandler(inputTokens: 1_000, outputTokens: 500);
        await using (var client = SpendAdmissionExample.CreateClient(Settings(transport), "demo", Price, ledger))
        {
            var outcome = await SpendAdmissionExample.TryGenerateAsync(client, ExampleSupport.Target, "Say hello.");
            ExampleSupport.Require(
                outcome is { Refusal: null, Generation.Text: "hello" }
                && outcome.Generation.Usage?.CostUsd?.CompareTo(EDecimal.FromString("0.004")) == 0
                && client.Spend().Cost.CompareTo(EDecimal.FromString("0.004")) == 0
                && ledger.Reserved().IsZero
                && transport.Requests == 1
                && transport.Bodies[0].GetProperty("max_tokens").GetInt32() == 256,
                "A request within its ceilings was not sent, priced, and recorded.");
        }
    }

    /// <summary>Once recorded spend would cross the total ceiling, the next request is refused before dispatch.</summary>
    [ExampleCase("spend-admission.ceiling-refuses-before-dispatch")]
    internal static async Task CeilingRefusesBeforeDispatch()
    {
        var ledger = new SpendLedger();
        var transport = new RecipeChatHandler(inputTokens: 20_000, outputTokens: 5_000);
        await using (var client = SpendAdmissionExample.CreateClient(Settings(transport), "demo", Price, ledger))
        {
            var first = await SpendAdmissionExample.TryGenerateAsync(client, ExampleSupport.Target, "Summarize the report.");
            var second = await SpendAdmissionExample.TryGenerateAsync(client, ExampleSupport.Target, "Summarize it again.");
            ExampleSupport.Require(
                first is { Refusal: null }
                && second is { Generation: null, Refusal: { } refusal }
                && refusal.LimitUsd?.CompareTo(EDecimal.FromString("0.05")) == 0
                && refusal.SpentUsd?.CompareTo(EDecimal.FromString("0.06")) == 0
                && refusal.EstimatedUsd is not null
                && refusal.Category == "spend_limit"
                && !refusal.Retryable
                && transport.Requests == 1,
                "A request over the total ceiling was not refused before dispatch with its accounting facts.");
        }

        var unsent = new RecipeChatHandler();
        await using (var client = SpendAdmissionExample.CreateClient(Settings(unsent), "demo", Price, new SpendLedger()))
        {
            var oversized = await SpendAdmissionExample.TryGenerateAsync(client, ExampleSupport.Target, new string('x', 80_000));
            ExampleSupport.Require(
                oversized.Refusal is { LimitUsd: var perRequest, EstimatedUsd: not null }
                && perRequest?.CompareTo(EDecimal.FromString("0.02")) == 0
                && unsent.Requests == 0,
                "A request whose own estimate exceeds the per-request ceiling was not refused.");
        }
    }

    /// <summary>With onUnknown "refuse", a target without trusted pricing is refused and nothing is sent.</summary>
    [ExampleCase("spend-admission.unknown-cost-refused")]
    internal static async Task UnknownCostRefused()
    {
        var transport = new RecipeChatHandler();
        await using (var client = SpendAdmissionExample.CreateClient(Settings(transport), "priced-model", Price, new SpendLedger()))
        {
            var outcome = await SpendAdmissionExample.TryGenerateAsync(client, ExampleSupport.Target, "Say hello.");
            ExampleSupport.Require(
                outcome is { Generation: null, Refusal.EstimatedUsd: null }
                && transport.Requests == 0
                && client.Spend().Requests == 0,
                "A request whose cost cannot be estimated was not refused before dispatch.");
        }
    }

    private static ProviderSettings Settings(HttpMessageHandler transport) =>
        ExampleSupport.WithTransport(SettingsExample.Create(ExampleSupport.BaseUrl), transport);
}
