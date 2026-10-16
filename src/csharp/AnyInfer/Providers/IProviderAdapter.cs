namespace AnyInfer.Providers;

public interface IProviderAdapter : IAsyncDisposable
{
    IAsyncEnumerable<AdapterEvent> GenerateAsync(WireRequest request, CancellationToken cancellationToken = default);
}
