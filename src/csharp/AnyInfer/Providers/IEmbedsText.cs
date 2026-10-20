namespace AnyInfer.Providers;

/// <summary>Embeds text batches for a provider that supports embedding.</summary>
public interface IEmbedsText
{
    /// <summary>Runs one buffered embedding batch.</summary>
    ValueTask<EmbeddingWireResult> EmbedAsync(
        EmbeddingWireRequest request,
        CancellationToken cancellationToken = default);
}