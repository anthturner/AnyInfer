namespace AnyInfer.Internal;

internal sealed class EntryTimeoutScope : IAsyncDisposable
{
    private readonly EntryContext _entry;
    private readonly CancellationTokenSource _timeoutSource;
    private readonly CancellationTokenSource _linkedSource;
    private readonly CancellationTokenRegistration _expiryRegistration;
    private int _disposeStarted;
    private int _isDisposed;

    internal EntryTimeoutScope(EntryContext entry, CancellationToken callerToken)
    {
        _entry = entry ?? throw new ArgumentNullException(nameof(entry));
        ContextId = Guid.NewGuid();
        EffectiveTimeoutS = entry.Request.TimeoutS;
        _timeoutSource = new CancellationTokenSource();
        _linkedSource = CancellationTokenSource.CreateLinkedTokenSource(callerToken, _timeoutSource.Token);
        _expiryRegistration = _timeoutSource.Token.Register(OnExpired);
        entry.Timeout = this;
        entry.Capture?.RecordEntry(entry);
        Record("created");
        _timeoutSource.CancelAfter(TimeSpan.FromSeconds(EffectiveTimeoutS));
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

    internal void Enter() => Record("entered");
    internal void CleanupStart() => Record("cleanup_start");
    internal void CleanupEnd() => Record("cleanup_end");

    public ValueTask DisposeAsync()
    {
        if (Interlocked.Exchange(ref _disposeStarted, 1) != 0)
        {
            return ValueTask.CompletedTask;
        }

        Record("exited");
        _expiryRegistration.Dispose();
        _linkedSource.Dispose();
        _timeoutSource.Dispose();
        Volatile.Write(ref _isDisposed, 1);
        Record("disposed");
        return ValueTask.CompletedTask;
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
