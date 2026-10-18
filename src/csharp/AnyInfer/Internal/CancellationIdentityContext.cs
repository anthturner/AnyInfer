namespace AnyInfer.Internal;

/// <summary>Maps linked operation tokens to their original caller token for narrow cancellation identity reporting.</summary>
internal static class CancellationIdentityContext
{
    private static readonly AsyncLocal<State?> Current = new();

    internal static IDisposable Push(CancellationToken effectiveToken, CancellationToken callerIdentity)
    {
        var previous = Current.Value;
        Current.Value = new State(effectiveToken, Resolve(callerIdentity), previous);
        return new Scope(previous);
    }

    internal static CancellationToken Resolve(CancellationToken effectiveToken)
    {
        for (var state = Current.Value; state is not null; state = state.Parent)
        {
            if (state.EffectiveToken == effectiveToken)
            {
                return state.CallerIdentity;
            }
        }

        return effectiveToken;
    }

    private sealed record State(CancellationToken EffectiveToken, CancellationToken CallerIdentity, State? Parent);

    private sealed class Scope : IDisposable
    {
        private readonly State? _previous;
        private bool _disposed;

        internal Scope(State? previous) => _previous = previous;

        public void Dispose()
        {
            if (_disposed) return;
            _disposed = true;
            Current.Value = _previous;
        }
    }
}
