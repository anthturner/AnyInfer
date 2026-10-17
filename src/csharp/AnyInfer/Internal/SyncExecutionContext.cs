namespace AnyInfer.Internal;

/// <summary>Tracks client-owned callbacks that cannot synchronously join their own client.</summary>
internal static class SyncExecutionContext
{
    private static readonly AsyncLocal<Client?> ActiveClient = new();

    internal static Client? CurrentClient => ActiveClient.Value;

    internal static IDisposable Push(Client client)
    {
        ArgumentNullException.ThrowIfNull(client);
        var previous = ActiveClient.Value;
        ActiveClient.Value = client;
        return new Scope(previous);
    }

    private sealed class Scope : IDisposable
    {
        private readonly Client? _previous;
        private bool _disposed;

        internal Scope(Client? previous) => _previous = previous;

        public void Dispose()
        {
            if (_disposed)
            {
                return;
            }

            _disposed = true;
            ActiveClient.Value = _previous;
        }
    }
}
