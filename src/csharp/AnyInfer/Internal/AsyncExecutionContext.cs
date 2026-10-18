namespace AnyInfer.Internal;

/// <summary>Tracks asynchronous client-owned callbacks that cannot join their own client.</summary>
internal static class AsyncExecutionContext
{
    private static readonly AsyncLocal<State?> Active = new();

    internal static AsyncClient? CurrentAsyncClient => Active.Value?.AsyncClient;

    internal static Client? CurrentSyncClient => Active.Value?.SyncClient;

    internal static IDisposable Push(AsyncClient asyncClient, Client? syncClient = null)
    {
        ArgumentNullException.ThrowIfNull(asyncClient);
        var previous = Active.Value;
        Active.Value = new State(asyncClient, syncClient ?? previous?.SyncClient);
        return new Scope(previous);
    }

    private sealed record State(AsyncClient AsyncClient, Client? SyncClient);

    private sealed class Scope : IDisposable
    {
        private readonly State? _previous;
        private bool _disposed;

        internal Scope(State? previous) => _previous = previous;

        public void Dispose()
        {
            if (_disposed) return;
            _disposed = true;
            Active.Value = _previous;
        }
    }
}
