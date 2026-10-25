namespace AnyInfer.Providers;

/// <summary>Generates text events for one normalized provider request.</summary>
/// <remarks>
/// This is a translation-only protocol: one call translates one <see cref="WireRequest"/> into one provider
/// exchange and its response into <see cref="AdapterEvent"/> values. Routing, retries, fallback,
/// structured-output repair, pricing, and telemetry belong to the client, so an implementation does not retry
/// or switch targets itself.
/// </remarks>
public interface IGeneratesText
{
    /// <summary>Runs one generation and yields normalized adapter events.</summary>
    /// <param name="request">Normalized request for one attempt.</param>
    /// <param name="cancellationToken">
    /// Cancels the exchange; the client also cancels it when the attempt's timeout expires and reports that as a
    /// retryable timeout.
    /// </param>
    /// <returns>
    /// Events in provider order, normally ending with one <see cref="AdapterFinal"/>. Provider failures should
    /// surface as <see cref="ProviderException"/> subtypes so the client can classify them.
    /// </returns>
    IAsyncEnumerable<AdapterEvent> GenerateAsync(
        WireRequest request,
        CancellationToken cancellationToken = default);
}