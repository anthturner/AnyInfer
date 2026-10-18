namespace AnyInfer.Internal;

/// <summary>Tracks the precise public stream whose owned execution is invoking callbacks.</summary>
internal static class StreamExecutionContext
{
    private static readonly AsyncLocal<AsyncStream?> CurrentStream = new();

    internal static AsyncStream? Current => CurrentStream.Value;

    internal static IDisposable Push(AsyncStream stream)
    {
        ArgumentNullException.ThrowIfNull(stream);
        var previous = CurrentStream.Value;
        CurrentStream.Value = stream;
        return new Scope(previous);
    }

    private sealed class Scope(AsyncStream? previous) : IDisposable
    {
        private AsyncStream? _previous = previous;
        public void Dispose()
        {
            CurrentStream.Value = _previous;
            _previous = null;
        }
    }
}
