using AnyInfer.Capabilities;
using PeterO.Numbers;

namespace AnyInfer.Examples;

/// <summary>
/// A metered multi-tenant summarizer: explicit prices and context windows, a spend ceiling enforced
/// before dispatch, a caller-owned ledger persisted to a caller-chosen store, client-side pacing, and
/// a context-window fallback, with self-hosted work whose cost stays unknown.
/// </summary>
public static class CookbookPoliciesExample
{
    private static readonly Sampling Summary = new(temperature: 0, maxOutputTokens: 300);

    /// <summary>A hosted gateway serving two models, paced client-side, and a self-hosted server.</summary>
    public static IReadOnlyList<ProviderSettings> Providers { get; } =
    [
        ProviderSettings.Of(
            "openai-compat",
            "https://llm-gateway.example/v1",
            apiKey: "env://LLM_GATEWAY_KEY",
            alias: "gateway",
            limits: new RateLimits(maxConcurrent: 2, minIntervalS: 0.25, respectHeaders: false)),
        ProviderSettings.Of("openai-compat", "http://127.0.0.1:8000/v1", alias: "lab"),
    ];

    /// <summary>
    /// Prices and context windows the application has verified for the gateway's models. Nothing is
    /// assumed for the self-hosted server, so its cost stays unknown rather than free.
    /// </summary>
    public static IReadOnlyDictionary<string, IReadOnlyDictionary<string, ModelCapabilities>> Facts { get; } =
        new Dictionary<string, IReadOnlyDictionary<string, ModelCapabilities>>
        {
            ["gateway"] = new Dictionary<string, ModelCapabilities>
            {
                ["small"] = Priced(contextWindow: 8_192, inputPer1M: "0.20", outputPer1M: "0.60"),
                ["large"] = Priced(contextWindow: 131_072, inputPer1M: "1.00", outputPer1M: "4.00"),
            },
        };

    /// <summary>The default route: the small model, moving to the large one only when the input cannot fit.</summary>
    public static Route Metered { get; } = new(["gateway:small"], contextWindowTargets: ["gateway:large"]);

    /// <summary>The route for tenants whose documents stay on the self-hosted server.</summary>
    public static Route SelfHosted { get; } = new(["lab:qwen3-8b"]);

    /// <summary>Summarizes a batch under a spend ceiling and adds this run's spend to the store.</summary>
    /// <param name="providers">The provider instances the routes name.</param>
    /// <param name="jobs">The documents to summarize, in order.</param>
    /// <param name="storePath">The accounting file the application keeps across runs.</param>
    /// <param name="bucket">The store bucket this run's spend is added to, such as a month.</param>
    /// <param name="budgetUsd">The most this run may spend, counting reservations for requests in flight.</param>
    /// <param name="output">Where the run report is written, such as <see cref="Console.Out"/>.</param>
    /// <param name="refuseUnknownCost">Whether a request whose cost cannot be estimated is refused instead of sent.</param>
    /// <param name="cancellationToken">Cancels the remaining work.</param>
    /// <returns>Per-job outcomes, this run's ledger snapshots and the persisted store.</returns>
    public static async Task<CookbookMeteredRun> RunAsync(
        IEnumerable<ProviderSettings> providers,
        IReadOnlyList<CookbookJob> jobs,
        string storePath,
        string bucket,
        EDecimal budgetUsd,
        TextWriter output,
        bool refuseUnknownCost = false,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(jobs);
        ArgumentNullException.ThrowIfNull(output);
        var ledger = new SpendLedger();
        var outcomes = new List<CookbookJobOutcome>();
        await using (var client = new AsyncClient(
            providers,
            capabilityOverrides: Facts,
            ledger: ledger,
            spendPolicy: new SpendPolicy(
                maxTotalUsd: budgetUsd,
                maxRequestUsd: EDecimal.FromString("0.04"),
                onUnknown: refuseUnknownCost ? "refuse" : "allow"),
            cachePolicy: new CachePolicy(CacheMode.Auto)))
        {
            foreach (var job in jobs)
            {
                var route = job.SelfHosted ? SelfHosted : Metered;
                var prompt = "Summarize this document in three sentences.\n\n" + job.Document;

                // A pure preflight: no adapter is built and nothing is sent.
                var plan = client.Budget(prompt, route.Targets[0], sampling: Summary);
                try
                {
                    var generation = await client.GenerateAsync(
                        prompt,
                        route: route,
                        sampling: Summary,
                        metadata: new Dictionary<string, string> { ["tenant"] = job.Tenant },
                        cancellationToken: cancellationToken);

                    // Time the gateway's client-side rate limit held this request before dispatch.
                    var queuedMs = generation.Timing?.Phases.GetValueOrDefault("queued_ms") ?? 0;
                    outcomes.Add(new CookbookJobOutcome(job.Id, plan.Fits, plan.EstimatedCost?.High, generation.Target?.ToString(), generation.Usage?.CostUsd, queuedMs, generation.CacheMechanism, null));
                    await output.WriteLineAsync($"{job.Id} [{job.Tenant}] {generation.Target}: {Money(generation.Usage?.CostUsd)}");
                }
                catch (SpendLimitException refused)
                {
                    // Refused before dispatch: no provider request was sent for this job.
                    outcomes.Add(new CookbookJobOutcome(job.Id, plan.Fits, plan.EstimatedCost?.High, null, null, 0, null, refused));
                    await output.WriteLineAsync($"{job.Id} [{job.Tenant}] refused: {Money(refused.SpentUsd)} spent, next up to {Money(refused.EstimatedUsd)}, ceiling {Money(refused.LimitUsd)}");
                }
            }
        }

        var totals = ledger.Totals();
        var store = new SpendStore(storePath);
        store.Accumulate(ledger, bucket);
        await output.WriteLineAsync($"run: {Money(totals.Cost)} over {totals.Requests} request(s); {totals.UnknownRequests} with unknown cost");
        return new CookbookMeteredRun(outcomes, totals, ledger.ByTarget(), ledger.ByLabel("tenant"), store.Load());
    }

    private static ModelCapabilities Priced(int contextWindow, string inputPer1M, string outputPer1M) => new(
        contextWindow: new Sourced<int>(contextWindow, Provenance.Override),
        pricing: new Sourced<Pricing>(
            new Pricing(EDecimal.FromString(inputPer1M), EDecimal.FromString(outputPer1M)),
            Provenance.Override));

    private static string Money(EDecimal? amount) => amount is null ? "unknown" : $"${amount.ToString()}";
}

/// <summary>One document to summarize for one tenant.</summary>
/// <param name="Id">The application's job ID.</param>
/// <param name="Tenant">The tenant the spend is attributed to.</param>
/// <param name="Document">The document text.</param>
/// <param name="SelfHosted">Whether the tenant's documents must stay on the self-hosted server.</param>
public sealed record CookbookJob(string Id, string Tenant, string Document, bool SelfHosted = false);

/// <summary>What happened to one job.</summary>
/// <param name="JobId">The application's job ID.</param>
/// <param name="FitsFirstTarget">Whether the preflight found that the input fits the route's first target, when knowable.</param>
/// <param name="EstimatedHighUsd">The preflight's upper cost estimate on the first target, when priced.</param>
/// <param name="ServedBy">The target that served the job, or <see langword="null"/> when refused.</param>
/// <param name="CostUsd">The served request's cost from reported usage and trusted prices, or <see langword="null"/> when unknown.</param>
/// <param name="QueuedMs">Milliseconds the client-side rate limit held the request before dispatch.</param>
/// <param name="Cache">The cache mechanism that engaged, or <see langword="null"/> when none did.</param>
/// <param name="Refusal">The spend refusal, when the job was not sent.</param>
public sealed record CookbookJobOutcome(
    string JobId,
    bool? FitsFirstTarget,
    EDecimal? EstimatedHighUsd,
    string? ServedBy,
    EDecimal? CostUsd,
    double QueuedMs,
    CacheMechanism? Cache,
    SpendLimitException? Refusal);

/// <summary>One metered run.</summary>
/// <param name="Jobs">Per-job outcomes, in order.</param>
/// <param name="Totals">This run's completed spend.</param>
/// <param name="ByTarget">This run's spend per served target.</param>
/// <param name="ByTenant">This run's spend per tenant label.</param>
/// <param name="Stored">Every bucket in the store after this run was added.</param>
public sealed record CookbookMeteredRun(
    IReadOnlyList<CookbookJobOutcome> Jobs,
    SpendTotals Totals,
    IReadOnlyDictionary<string, SpendTotals> ByTarget,
    IReadOnlyDictionary<string, SpendTotals> ByTenant,
    IReadOnlyDictionary<string, SpendTotals> Stored);
