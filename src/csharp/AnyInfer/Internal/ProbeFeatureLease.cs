using System.Runtime.ExceptionServices;

namespace AnyInfer.Internal;

/// <summary>Owns one raw capability-probe deadline and its client-context cancellation signal.</summary>
internal sealed class ProbeFeatureLease : IAsyncDisposable
{
    private const double MaximumTimeoutS = (uint.MaxValue - 1) / 1000d;
    private readonly AsyncClient _owner;
    private readonly Client? _syncOwner;
    private readonly CancellationToken _operationToken;
    private readonly CancellationToken _callerIdentity;
    private readonly Action<Exception> _onSignalFailure;
    private readonly CancellationTokenSource _source = new();
    private readonly Timer _timer;
    private readonly CancellationTokenRegistration _parentRegistration;
    private readonly object _gate = new();
    private Task<Exception?>? _signal;
    private bool _finalizing;
    private int _timeoutOrigin;

    internal ProbeFeatureLease(
        double timeoutS,
        AsyncClient owner,
        Client? syncOwner,
        CancellationToken operationToken,
        CancellationToken callerIdentity,
        Action<Exception> onSignalFailure)
    {
        ValidateTimeout(timeoutS);
        _owner = owner ?? throw new ArgumentNullException(nameof(owner));
        _syncOwner = syncOwner;
        _operationToken = operationToken;
        _callerIdentity = callerIdentity;
        _onSignalFailure = onSignalFailure ?? throw new ArgumentNullException(nameof(onSignalFailure));
        Token = _source.Token;
        _timer = new Timer(static state => ((ProbeFeatureLease)state!).OnTimeout(), this, Timeout.InfiniteTimeSpan, Timeout.InfiniteTimeSpan);
        _parentRegistration = operationToken.UnsafeRegister(static state => ((ProbeFeatureLease)state!).PublishSignal(timeoutOrigin: false), this);
        _timer.Change(TimeSpan.FromSeconds(timeoutS), Timeout.InfiniteTimeSpan);
    }

    internal CancellationToken Token { get; }
    internal bool TimeoutOrigin => Volatile.Read(ref _timeoutOrigin) != 0;

    internal static void ValidateTimeout(double timeoutS)
    {
        if (!double.IsFinite(timeoutS) || timeoutS <= 0 || timeoutS > MaximumTimeoutS)
        {
            throw new ArgumentOutOfRangeException(nameof(timeoutS));
        }
    }

    internal bool IsOwnedTimeout(OperationCanceledException exception) =>
        TimeoutOrigin &&
        exception.CancellationToken == Token &&
        !_operationToken.IsCancellationRequested &&
        !_callerIdentity.IsCancellationRequested;

    internal void ThrowIfOperationOrCallerCancelled()
    {
        if (_callerIdentity.IsCancellationRequested)
        {
            throw new OperationCanceledException(_callerIdentity);
        }

        _operationToken.ThrowIfCancellationRequested();
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
        try
        {
            await _timer.DisposeAsync().ConfigureAwait(false);
        }
        catch (Exception exception)
        {
            failure = exception;
        }

        try
        {
            await _parentRegistration.DisposeAsync().ConfigureAwait(false);
        }
        catch (Exception exception)
        {
            failure ??= exception;
        }

        if (signal is not null)
        {
            Exception? signalFailure;
            try
            {
                signalFailure = await signal.ConfigureAwait(false);
            }
            catch (Exception exception)
            {
                signalFailure = exception;
            }

            failure ??= signalFailure;
        }

        try
        {
            _source.Dispose();
        }
        catch (Exception exception)
        {
            failure ??= exception;
        }

        if (failure is not null)
        {
            ExceptionDispatchInfo.Capture(failure).Throw();
        }
    }

    private void OnTimeout()
    {
        PublishSignal(timeoutOrigin: true);
    }

    private void PublishSignal(bool timeoutOrigin)
    {
        lock (_gate)
        {
            if (_finalizing || _signal is not null)
            {
                return;
            }

            if (timeoutOrigin)
            {
                Volatile.Write(ref _timeoutOrigin, 1);
            }

            _signal ??= Task.Run(SignalCore);
        }
    }

    private Exception? SignalCore()
    {
        try
        {
            using var asyncContext = AsyncExecutionContext.Push(_owner, _syncOwner);
            using var syncContext = _syncOwner is null ? null : SyncExecutionContext.Push(_syncOwner);
            using var identity = CancellationIdentityContext.Push(Token, _callerIdentity);
            _source.Cancel();
            return null;
        }
        catch (Exception exception)
        {
            _onSignalFailure(exception);
            return exception;
        }
    }
}
