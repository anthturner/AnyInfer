namespace AnyInfer.Providers;

/// <summary>Reranks document batches for a provider that supports reranking.</summary>
public interface IReranksText
{
    /// <summary>Runs one buffered reranking batch.</summary>
    ValueTask<RerankWireResult> RerankAsync(
        RerankWireRequest request,
        CancellationToken cancellationToken = default);
}