namespace AnyInfer.Providers;

/// <summary>Generates text events for one normalized provider request.</summary>
public interface IGeneratesText
{
    /// <summary>Runs one generation and yields normalized adapter events.</summary>
    IAsyncEnumerable<AdapterEvent> GenerateAsync(
        WireRequest request,
        CancellationToken cancellationToken = default);
}