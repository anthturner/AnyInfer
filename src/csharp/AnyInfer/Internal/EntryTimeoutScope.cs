namespace AnyInfer.Internal;

internal sealed class EntryTimeoutScope : IAsyncDisposable
{
    private readonly EntryContext _entry;
    private readonly CancellationTokenSource _timeoutSource;
    private readonly CancellationTokenSource _linkedSource;
    private readonly CancellationTokenRegistration _expiryRegistration;
    private readonly TimeProvider? _entryTimeProvider;
    private readonly AsyncClient? _asyncOwner;
    private readonly Client? _syncOwner;
    private readonly AsyncStream? _streamOwner;
    private readonly CancellationToken _callerIdentity;
    private readonly object _timerGate = new();
    private ITimer? _timer;
    private TaskCompletionSource<Exception?>? _timerCompletion;
    private Exception? _deferredFailure;
    private bool _timerDisposing;
    private int _disposeStarted;
    private int _isDisposed;

    internal EntryTimeoutScope(EntryContext entry, CancellationToken callerToken, TimeProvider? entryTimeProvider = null)
    {
        _entry = entry ?? throw new ArgumentNullException(nameof(entry));
        ContextId = Guid.NewGuid();
        EffectiveTimeoutS = entry.Request.TimeoutS;
        _entryTimeProvider = entryTimeProvider;
        _asyncOwner = AsyncExecutionContext.CurrentAsyncClient;
        _syncOwner = AsyncExecutionContext.CurrentSyncClient ?? SyncExecutionContext.CurrentClient;
        _streamOwner = StreamExecutionContext.Current;
        _callerIdentity = CancellationIdentityContext.Resolve(callerToken);
        _timeoutSource = new CancellationTokenSource();
        _linkedSource = CancellationTokenSource.CreateLinkedTokenSource(callerToken, _timeoutSource.Token);
        _expiryRegistration = _timeoutSource.Token.Register(OnExpired);
        entry.Timeout = this;
        entry.Capture?.RecordEntry(entry);
        Record("created");
        try
        {
            if (_entryTimeProvider is null)
            {
                _timeoutSource.CancelAfter(TimeSpan.FromSeconds(EffectiveTimeoutS));
            }
            else
            {
                _timer = _entryTimeProvider.CreateTimer(OnTimer, null, TimeSpan.FromSeconds(EffectiveTimeoutS), Timeout.InfiniteTimeSpan);
            }
        }
        catch
        {
            DisposeArmingResources();
            throw;
        }

        Record("configured");
    }

    internal Guid ContextId { get; }
    internal double EffectiveTimeoutS { get; }
    internal CancellationToken Token => _linkedSource.Token;
    internal CancellationToken TimeoutToken => _timeoutSource.Token;
    internal CancellationTokenSource TimeoutSource => _timeoutSource;
    internal CancellationTokenSource LinkedSource => _linkedSource;
    internal bool IsExpired => _timeoutSource.IsCancellationRequested;
    internal bool IsDisposed => Volatile.Read(ref _isDisposed) != 0;
    internal Exception? DeferredFailure => Volatile.Read(ref _deferredFailure);

    internal void Enter() => Record("entered");
    internal void CleanupStart() => Record("cleanup_start");
    internal void CleanupEnd() => Record("cleanup_end");

    public async ValueTask DisposeAsync()
    {
        if (Interlocked.Exchange(ref _disposeStarted, 1) != 0)
        {
            return;
        }

        Record("exited");
        ITimer? timer;
        Task<Exception?>? timerTask;
        lock (_timerGate)
        {
            _timerDisposing = true;
            timer = _timer;
            _timer = null;
            timerTask = _timerCompletion?.Task;
        }

        TryDispose(timer);
        if (timerTask is not null)
        {
            try
            {
                var timerFailure = await timerTask.ConfigureAwait(false);
                RetainFailure(timerFailure);
            }
            catch (Exception exception)
            {
                RetainFailure(exception);
            }
        }

        TryDispose(_expiryRegistration);
        TryDispose(_linkedSource);
        TryDispose(_timeoutSource);
        Volatile.Write(ref _isDisposed, 1);
        Record("disposed");
    }

    private void OnTimer(object? state)
    {
        TaskCompletionSource<Exception?> completion;
        lock (_timerGate)
        {
            if (_timerDisposing)
            {
                return;
            }

            completion = _timerCompletion ??= new TaskCompletionSource<Exception?>(TaskCreationOptions.RunContinuationsAsynchronously);
        }

        Exception? failure = null;
        try
        {
            using var asyncScope = _asyncOwner is null ? null : AsyncExecutionContext.Push(_asyncOwner, _syncOwner);
            using var syncScope = _syncOwner is null ? null : SyncExecutionContext.Push(_syncOwner);
            using var streamScope = _streamOwner is null ? null : StreamExecutionContext.Push(_streamOwner);
            using var identity = CancellationIdentityContext.Push(_linkedSource.Token, _callerIdentity);
            _timeoutSource.Cancel();
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

    private void DisposeArmingResources()
    {
        TryDispose(_timer);
        TryDispose(_expiryRegistration);
        TryDispose(_linkedSource);
        TryDispose(_timeoutSource);
        Volatile.Write(ref _isDisposed, 1);
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

    private void OnExpired()
    {
        Record("expired");
    }

    private void Record(string name)
    {
        _entry.Capture?.RecordLifecycle(_entry.OperationId, _entry.Ordinal, name);
    }
}
