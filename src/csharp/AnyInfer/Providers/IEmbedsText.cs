namespace AnyInfer.Providers;

/// <summary>Embeds text batches for a provider that supports embedding.</summary>
/// <remarks>
/// This is a translation-only protocol: one call translates one batch into one provider exchange. Batching,
/// retries, fallback, pricing, and result validation belong to the client, so an implementation does not retry
/// or switch targets itself.
/// </remarks>
public interface IEmbedsText
{
    /// <summary>Runs one buffered embedding batch.</summary>
    /// <param name="request">Resolved batch to send.</param>
    /// <param name="cancellationToken">
    /// Cancels the exchange; the client also cancels it when the attempt's timeout expires.
    /// </param>
    /// <returns>The provider's vectors and reported facts, before client validation.</returns>
    ValueTask<EmbeddingWireResult> EmbedAsync(
        EmbeddingWireRequest request,
        CancellationToken cancellationToken = default);
}