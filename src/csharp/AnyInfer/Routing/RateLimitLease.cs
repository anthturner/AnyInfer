namespace AnyInfer.Routing;

/// <summary>Represents one acquired rate-limit permit.</summary>
public sealed class RateLimitLease : IDisposable, IAsyncDisposable
{
    private Action? _release;

    internal RateLimitLease(Action release)
    {
        _release = release ?? throw new ArgumentNullException(nameof(release));
    }

    /// <summary>Releases the permit at most once.</summary>
    public void Dispose() => Interlocked.Exchange(ref _release, null)?.Invoke();

    /// <summary>Asynchronously releases the permit at most once.</summary>
    public ValueTask DisposeAsync()
    {
        Dispose();
        return ValueTask.CompletedTask;
    }
}
