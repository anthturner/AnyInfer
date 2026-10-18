using System.Runtime.ExceptionServices;

namespace AnyInfer.Internal;

/// <summary>Schedules stream child cancellation away from caller cancellation registrations.</summary>
internal sealed class StreamOperationLease : IAsyncDisposable
{
    private readonly AsyncClient _owner;
    private readonly AsyncStream _stream;
    private readonly Client? _syncOwner;
    private readonly CancellationToken _callerIdentity;
    private readonly CancellationToken _iteratorCancellation;
    private readonly CancellationToken _closeCancellation;
    private readonly Func<bool> _closeRequested;
    private readonly CancellationTokenSource _source = new();
    private readonly CancellationTokenRegistration[] _registrations;
    private readonly object _gate = new();
    private Task<Exception?>? _signal;
    private bool _finalizing;

    internal StreamOperationLease(
        AsyncStream stream,
        AsyncClient owner,
        Client? syncOwner,
        CancellationToken callerIdentity,
        CancellationToken iteratorCancellation,
        CancellationToken closeCancellation,
        Func<bool> closeRequested)
    {
        _stream = stream ?? throw new ArgumentNullException(nameof(stream));
        _owner = owner ?? throw new ArgumentNullException(nameof(owner));
        _syncOwner = syncOwner;
        _callerIdentity = callerIdentity;
        _iteratorCancellation = iteratorCancellation;
        _closeCancellation = closeCancellation;
        _closeRequested = closeRequested ?? throw new ArgumentNullException(nameof(closeRequested));
        Token = _source.Token;
        _registrations =
        [
            callerIdentity.UnsafeRegister(static state => ((StreamOperationLease)state!).PublishSignal(), this),
            iteratorCancellation.UnsafeRegister(static state => ((StreamOperationLease)state!).PublishSignal(), this),
            closeCancellation.UnsafeRegister(static state => ((StreamOperationLease)state!).PublishSignal(), this),
        ];
    }

    internal CancellationToken Token { get; }

    internal Task<Exception?> SignalCancelAsync() => PublishSignal();

    /// <summary>Gets the first cancelled parent token in the stream operation's cancellation priority.</summary>
    internal CancellationToken? CancelledParentToken
    {
        get
        {
            if (_callerIdentity.IsCancellationRequested)
            {
                return _callerIdentity;
            }

            if (_iteratorCancellation.IsCancellationRequested)
            {
                return _iteratorCancellation;
            }

            return _closeCancellation.IsCancellationRequested || _closeRequested() ? _closeCancellation : null;
        }
    }

    /// <summary>Returns whether an exception carries any parent cancellation owned by this lease.</summary>
    internal bool IsOwnedParentCancellation(OperationCanceledException exception)
    {
        ArgumentNullException.ThrowIfNull(exception);
        var token = exception.CancellationToken;
        return (_callerIdentity.IsCancellationRequested && token == _callerIdentity)
            || (_iteratorCancellation.IsCancellationRequested && token == _iteratorCancellation)
            || ((_closeCancellation.IsCancellationRequested || _closeRequested()) && token == _closeCancellation);
    }

    internal void ThrowIfParentCancelled()
    {
        if (CancelledParentToken is { } cancelled)
        {
            throw new OperationCanceledException(cancelled);
        }
    }

    public async ValueTask DisposeAsync()
    {
        Task<Exception?>? signal;
        lock (_gate)
        {
            _finalizing = true;
            signal = _signal;
        }

        Exception? failure = null;
        foreach (var registration in _registrations)
        {
            try { await registration.DisposeAsync().ConfigureAwait(false); }
            catch (Exception exception) { failure ??= exception; }
        }

        if (signal is not null)
        {
            Exception? signalFailure;
            try { signalFailure = await signal.ConfigureAwait(false); }
            catch (Exception exception) { signalFailure = exception; }
            failure ??= signalFailure;
        }

        try { _source.Dispose(); }
        catch (Exception exception) { failure ??= exception; }

        if (failure is not null)
        {
            ExceptionDispatchInfo.Capture(failure).Throw();
        }
    }

    private Task<Exception?> PublishSignal()
    {
        lock (_gate)
        {
            if (_finalizing)
            {
                return Task.FromResult<Exception?>(null);
            }

            return _signal ??= Task.Run(SignalCore);
        }
    }

    private Exception? SignalCore()
    {
        try
        {
            using var stream = StreamExecutionContext.Push(_stream);
            using var asyncContext = AsyncExecutionContext.Push(_owner, _syncOwner);
            using var syncContext = _syncOwner is null ? null : SyncExecutionContext.Push(_syncOwner);
            using var identity = CancellationIdentityContext.Push(Token, _callerIdentity);
            _source.Cancel();
            return null;
        }
        catch (Exception exception)
        {
            return exception;
        }
    }

}
