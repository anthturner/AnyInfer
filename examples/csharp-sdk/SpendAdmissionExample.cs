using AnyInfer.Capabilities;
using PeterO.Numbers;

namespace AnyInfer.Examples;

/// <summary>Refuses requests before dispatch once a caller-set spend ceiling would be crossed.</summary>
public static class SpendAdmissionExample
{
    // --8<-- [start:client]
    /// <summary>Creates a client that admits a request only when its estimated cost fits the ceilings.</summary>
    /// <param name="settings">The provider instance to call.</param>
    /// <param name="model">The model whose price the application asserts.</param>
    /// <param name="pricing">The model's price per million input and output tokens, as the application verified it.</param>
    /// <param name="ledger">The caller-owned ledger that holds recorded spend and in-flight reservations.</param>
    /// <returns>A client the caller owns and disposes.</returns>
    public static AsyncClient CreateClient(ProviderSettings settings, string model, Pricing pricing, SpendLedger ledger)
    {
        ArgumentNullException.ThrowIfNull(settings);
        var priced = new ModelCapabilities(pricing: new Sourced<Pricing>(pricing, Provenance.Override));
        return new AsyncClient(
            [settings],
            ledger: ledger,
            spendPolicy: new SpendPolicy(
                maxTotalUsd: EDecimal.FromString("0.05"),
                maxRequestUsd: EDecimal.FromString("0.02"),
                onUnknown: "refuse"),
            capabilityOverrides: new Dictionary<string, IReadOnlyDictionary<string, ModelCapabilities>>
            {
                [settings.InstanceId] = new Dictionary<string, ModelCapabilities> { [model] = priced },
            });
    }
    // --8<-- [end:client]

    // --8<-- [start:admit]
    /// <summary>Generates a reply, or returns the refusal when a spend ceiling would be crossed.</summary>
    /// <param name="client">A client from <see cref="CreateClient"/>.</param>
    /// <param name="target">A <c>provider:model</c> target.</param>
    /// <param name="prompt">The prompt text.</param>
    /// <param name="cancellationToken">Cancels the call.</param>
    /// <returns>The result, or the refusal; a refused request sent nothing.</returns>
    public static async Task<AdmissionOutcome> TryGenerateAsync(
        AsyncClient client,
        string target,
        string prompt,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(client);
        try
        {
            var generation = await client.GenerateAsync(
                prompt,
                target: target,
                sampling: new Sampling(maxOutputTokens: 256),
                cancellationToken: cancellationToken);
            return new AdmissionOutcome(generation, Refusal: null);
        }
        catch (SpendLimitException refusal)
        {
            return new AdmissionOutcome(Generation: null, refusal);
        }
    }
    // --8<-- [end:admit]
}

/// <summary>Contains either an admitted result or the spend refusal that prevented dispatch.</summary>
public sealed record AdmissionOutcome(Generation? Generation, SpendLimitException? Refusal);
