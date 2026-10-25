namespace AnyInfer.Providers;

/// <summary>Reranks document batches for a provider that supports reranking.</summary>
/// <remarks>
/// This is a translation-only protocol: one call translates one batch into one provider exchange. Batching,
/// retries, fallback, pricing, and result validation belong to the client, so an implementation does not retry
/// or switch targets itself.
/// </remarks>
public interface IReranksText
{
    /// <summary>Runs one buffered reranking batch.</summary>
    /// <param name="request">Resolved batch to send.</param>
    /// <param name="cancellationToken">
    /// Cancels the exchange; the client also cancels it when the attempt's timeout expires.
    /// </param>
    /// <returns>
    /// The provider's ranked items, each identified by its document's original caller index, before client
    /// validation.
    /// </returns>
    ValueTask<RerankWireResult> RerankAsync(
        RerankWireRequest request,
        CancellationToken cancellationToken = default);
}