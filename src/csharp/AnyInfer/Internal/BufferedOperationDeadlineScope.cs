namespace AnyInfer.Internal;

/// <summary>Owns an operation-neutral deadline token and safely joins its timer callback.</summary>
internal sealed class BufferedOperationDeadlineScope : IAsyncDisposable
{
    private readonly CancellationTokenSource _deadlineSource;
    private readonly CancellationTokenSource _linkedSource;
    private readonly CancellationTokenRegistration _expiryRegistration;
    private readonly AsyncClient? _asyncOwner;
    private readonly Client? _syncOwner;
    private readonly CancellationToken _callerIdentity;
    private readonly object _timerGate = new();
    private ITimer? _timer;
    private TaskCompletionSource<Exception?>? _timerCompletion;
    private Exception? _deferredFailure;
    private bool _timerDisposing;
    private int _disposeStarted;

    internal BufferedOperationDeadlineScope(
        double timeoutS,
        CancellationToken lifecycleToken,
        CancellationToken callerIdentity,
        TimeProvider? timeProvider = null)
    {
        _asyncOwner = AsyncExecutionContext.CurrentAsyncClient;
        _syncOwner = AsyncExecutionContext.CurrentSyncClient ?? SyncExecutionContext.CurrentClient;
        _callerIdentity = CancellationIdentityContext.Resolve(callerIdentity);
        _deadlineSource = new CancellationTokenSource();
        _linkedSource = CancellationTokenSource.CreateLinkedTokenSource(lifecycleToken, _deadlineSource.Token);
        _expiryRegistration = _deadlineSource.Token.Register(static state => ((BufferedOperationDeadlineScope)state!).OnExpired(), this);

        try
        {
            _timer = (timeProvider ?? TimeProvider.System).CreateTimer(
                static state => ((BufferedOperationDeadlineScope)state!).OnTimer(),
                this,
                TimeSpan.FromSeconds(timeoutS),
                Timeout.InfiniteTimeSpan);
        }
        catch
        {
            DisposeArmingResources();
            throw;
        }
    }

    internal CancellationToken Token => _linkedSource.Token;

    internal bool IsExpired => _deadlineSource.IsCancellationRequested;

    internal Exception? DeferredFailure => Volatile.Read(ref _deferredFailure);

    public async ValueTask DisposeAsync()
    {
        if (Interlocked.Exchange(ref _disposeStarted, 1) != 0)
        {
            return;
        }

        ITimer? timer;
        Task<Exception?>? callbackTask;
        lock (_timerGate)
        {
            _timerDisposing = true;
            timer = _timer;
            _timer = null;
            callbackTask = _timerCompletion?.Task;
        }

        TryDispose(timer);
        if (callbackTask is not null)
        {
            try
            {
                RetainFailure(await callbackTask.ConfigureAwait(false));
            }
            catch (Exception exception)
            {
                RetainFailure(exception);
            }
        }

        TryDispose(_expiryRegistration);
        TryDispose(_linkedSource);
        TryDispose(_deadlineSource);
    }

    private void OnTimer()
    {
        TaskCompletionSource<Exception?> completion;
        lock (_timerGate)
        {
            if (_timerDisposing)
            {
                return;
            }

            completion = _timerCompletion ??= new TaskCompletionSource<Exception?>(
                TaskCreationOptions.RunContinuationsAsynchronously);
        }

        Exception? failure = null;
        try
        {
            using var asyncScope = _asyncOwner is null
                ? null
                : AsyncExecutionContext.Push(_asyncOwner, _syncOwner);
            using var syncScope = _syncOwner is null ? null : SyncExecutionContext.Push(_syncOwner);
            using var identity = CancellationIdentityContext.Push(_linkedSource.Token, _callerIdentity);
            _deadlineSource.Cancel();
        }
        catch (Exception exception)
        {
            failure = exception;
            RetainFailure(exception);
        }
        finally
        {
            completion.TrySetResult(failure);
        }
    }

    private void OnExpired()
    {
    }

    private void DisposeArmingResources()
    {
        TryDispose(_timer);
        TryDispose(_expiryRegistration);
        TryDispose(_linkedSource);
        TryDispose(_deadlineSource);
    }

    private void TryDispose(IDisposable? disposable)
    {
        if (disposable is null)
        {
            return;
        }

        try
        {
            disposable.Dispose();
        }
        catch (Exception exception)
        {
            RetainFailure(exception);
        }
    }

    private void RetainFailure(Exception? failure)
    {
        if (failure is not null)
        {
            Interlocked.CompareExchange(ref _deferredFailure, failure, null);
        }
    }
}