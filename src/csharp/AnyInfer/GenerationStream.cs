using AnyInfer.Internal;

namespace AnyInfer;

/// <summary>Represents one lazy generation operation and its ordered public events.</summary>
public sealed class AsyncStream : IAsyncEnumerable<StreamEvent>, IAsyncDisposable
{
    private readonly AsyncClient _client;
    private readonly Client? _syncClient;
    private readonly Func<CancellationToken, IAsyncEnumerable<StreamEvent>> _factory;
    private readonly CancellationTokenSource _closeSource = new();
    private readonly object _gate = new();
    private readonly Action<AsyncStream>? _onClosed;
    private StreamEnumerator? _enumerator;
    private Task? _disposeTask;
    private Task<Exception?>? _closeSignal;
    private bool _claimed;
    private bool _closed;
    private bool _succeeded;
    private bool _consumerClosing;
    private int _closeNotified;
    private Generation? _result;
    private OperationContext? _operation;

    internal AsyncStream(
        AsyncClient client,
        Client? syncClient,
        Func<CancellationToken, IAsyncEnumerable<StreamEvent>> factory,
        CancellationToken callerCancellation,
        Action<AsyncStream>? onClosed = null)
    {
        _client = client ?? throw new ArgumentNullException(nameof(client));
        _syncClient = syncClient;
        _factory = factory ?? throw new ArgumentNullException(nameof(factory));
        CallerCancellation = callerCancellation;
        _onClosed = onClosed;
    }

    internal CancellationToken CallerCancellation { get; }

    /// <summary>Gets the winning result after successful terminal completion.</summary>
    public Generation Result
    {
        get
        {
            lock (_gate)
            {
                return _result ?? throw new InvalidOperationException(
                    "The stream has no successful terminal generation. Consume it to completion first.");
            }
        }
    }

    internal Generation? ObservedResult
    {
        get
        {
            lock (_gate)
            {
                return _result;
            }
        }
    }

    /// <summary>Consumes this stream once and returns its successful terminal generation.</summary>
    public async Task<Generation> CollectAsync(CancellationToken cancellationToken = default)
    {
        await foreach (var _ in this.WithCancellation(cancellationToken).ConfigureAwait(false))
        {
        }

        return Result;
    }

    internal bool IsClosing
    {
        get
        {
            lock (_gate)
            {
                return _closed || _consumerClosing;
            }
        }
    }

    internal OperationContext? Operation
    {
        get
        {
            lock (_gate)
            {
                return _operation;
            }
        }
    }

    internal void NoteConsumerClosing()
    {
        lock (_gate)
        {
            _consumerClosing = true;
        }
    }

    /// <inheritdoc />
    public IAsyncEnumerator<StreamEvent> GetAsyncEnumerator(CancellationToken cancellationToken = default)
    {
        lock (_gate)
        {
            if (_closed)
            {
                return Empty().GetAsyncEnumerator(cancellationToken);
            }

            if (_claimed)
            {
                throw new InvalidOperationException("A AsyncStream has a single consumer.");
            }

            _claimed = true;
            var linked = CancellationTokenSource.CreateLinkedTokenSource(
                CallerCancellation,
                cancellationToken,
                _closeSource.Token);
            using var context = AsyncExecutionContext.Push(_client, _syncClient);
            _enumerator = new StreamEnumerator(this, _factory(linked.Token).GetAsyncEnumerator(linked.Token), linked);
            return _enumerator;
        }
    }

    /// <inheritdoc />
    public ValueTask DisposeAsync()
    {
        var signal = BeginCloseAsync();
        lock (_gate)
        {
            if (_disposeTask is null)
            {
                _disposeTask = DisposeCoreAsync(_enumerator, signal);
            }

            return new ValueTask(_disposeTask);
        }
    }

    internal Task<Exception?> BeginCloseAsync()
    {
        lock (_gate)
        {
            _closed = true;
            return _closeSignal ??= Task.Run(SignalCloseCore);
        }
    }

    internal void BeginOperation(OperationContext operation)
    {
        ArgumentNullException.ThrowIfNull(operation);
        lock (_gate)
        {
            _operation ??= operation;
            if (!ReferenceEquals(_operation, operation))
            {
                throw new InvalidOperationException("A stream cannot change operations.");
            }
        }
    }

    internal void PublishSuccess(Generation result)
    {
        ArgumentNullException.ThrowIfNull(result);
        lock (_gate)
        {
            if (_closed)
            {
                return;
            }

            _succeeded = true;
            _result = result;
        }
    }

    internal void PublishFailure()
    {
        lock (_gate)
        {
            if (!_succeeded)
            {
                _result = null;
            }
        }
    }

    private async Task DisposeCoreAsync(StreamEnumerator? enumerator, Task<Exception?> signal)
    {
        Exception? failure = await signal.ConfigureAwait(false);
        try
        {
            if (enumerator is not null)
            {
                await enumerator.DisposeAsync().ConfigureAwait(false);
            }
        }
        finally
        {
            _closeSource.Dispose();
            NotifyClosed();
        }

        if (failure is not null)
        {
            System.Runtime.ExceptionServices.ExceptionDispatchInfo.Capture(failure).Throw();
        }
    }

    private Exception? SignalCloseCore()
    {
        try
        {
            using var asyncContext = AsyncExecutionContext.Push(_client, _syncClient);
            using var syncContext = _syncClient is null ? null : SyncExecutionContext.Push(_syncClient);
            _closeSource.Cancel();
            return null;
        }
        catch (Exception exception)
        {
            return exception;
        }
    }

    private void NotifyClosed()
    {
        if (Interlocked.Exchange(ref _closeNotified, 1) == 0)
        {
            _onClosed?.Invoke(this);
        }
    }

    private static async IAsyncEnumerable<StreamEvent> Empty()
    {
        await Task.CompletedTask.ConfigureAwait(false);
        yield break;
    }

    private sealed class StreamEnumerator : IAsyncEnumerator<StreamEvent>
    {
        private readonly AsyncStream _owner;
        private readonly IAsyncEnumerator<StreamEvent> _inner;
        private readonly CancellationTokenSource _linked;
        private readonly SemaphoreSlim _moveGate = new(1, 1);
        private readonly object _disposeGate = new();
        private Task? _disposeTask;
        private Exception? _closeTimeMoveFailure;
        private int _disposed;

        internal StreamEnumerator(AsyncStream owner, IAsyncEnumerator<StreamEvent> inner, CancellationTokenSource linked)
        {
            _owner = owner;
            _inner = inner;
            _linked = linked;
        }

        public StreamEvent Current => _inner.Current;

        public async ValueTask<bool> MoveNextAsync()
        {
            await _moveGate.WaitAsync().ConfigureAwait(false);
            try
            {
                if (Volatile.Read(ref _disposed) != 0)
                {
                    return false;
                }

                using var context = AsyncExecutionContext.Push(_owner._client, _owner._syncClient);
                return await _inner.MoveNextAsync().ConfigureAwait(false);
            }
            catch (Exception exception)
            {
                if (ShouldRetainCloseFailure(exception))
                {
                    lock (_disposeGate)
                    {
                        _closeTimeMoveFailure ??= exception;
                    }
                }

                throw;
            }
            finally
            {
                _moveGate.Release();
            }
        }

        public ValueTask DisposeAsync()
        {
            lock (_disposeGate)
            {
                if (_disposeTask is null)
                {
                    Volatile.Write(ref _disposed, 1);
                    _disposeTask = DisposeCoreAsync();
                }

                return new ValueTask(_disposeTask);
            }
        }

        private async Task DisposeCoreAsync()
        {
            _owner.NoteConsumerClosing();
            using (AsyncExecutionContext.Push(_owner._client, _owner._syncClient))
            {
                _linked.Cancel();
            }
            Exception? disposalFailure = null;
            await _moveGate.WaitAsync().ConfigureAwait(false);
            try
            {
                using var context = AsyncExecutionContext.Push(_owner._client, _owner._syncClient);
                await _inner.DisposeAsync().ConfigureAwait(false);
            }
            catch (OperationCanceledException) when (_linked.IsCancellationRequested)
            {
            }
            catch (Exception exception)
            {
                disposalFailure = exception;
            }
            finally
            {
                _moveGate.Release();
                _linked.Dispose();
                _moveGate.Dispose();
                _owner.PublishFailure();
            }

            if (disposalFailure is not null)
            {
                System.Runtime.ExceptionServices.ExceptionDispatchInfo.Capture(disposalFailure).Throw();
            }

            Exception? moveFailure;
            lock (_disposeGate)
            {
                moveFailure = _closeTimeMoveFailure;
            }

            if (moveFailure is not null)
            {
                System.Runtime.ExceptionServices.ExceptionDispatchInfo.Capture(moveFailure).Throw();
            }
        }

        private bool ShouldRetainCloseFailure(Exception exception) =>
            _owner.IsClosing && !(exception is OperationCanceledException && _linked.IsCancellationRequested);
    }
}
