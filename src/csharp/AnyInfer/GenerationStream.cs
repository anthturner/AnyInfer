using AnyInfer.Internal;

namespace AnyInfer;

/// <summary>Represents one lazy generation operation and its ordered public events.</summary>
public sealed class GenerationStream : IAsyncEnumerable<GenerationEvent>, IAsyncDisposable
{
    private readonly Func<CancellationToken, IAsyncEnumerable<GenerationEvent>> _factory;
    private readonly CancellationTokenSource _closeSource = new();
    private readonly object _gate = new();
    private readonly Action<GenerationStream>? _onClosed;
    private StreamEnumerator? _enumerator;
    private Task? _disposeTask;
    private bool _claimed;
    private bool _closed;
    private bool _succeeded;
    private bool _consumerClosing;
    private int _closeNotified;
    private GenerationResult? _result;
    private OperationContext? _operation;

    internal GenerationStream(
        Func<CancellationToken, IAsyncEnumerable<GenerationEvent>> factory,
        CancellationToken callerCancellation,
        Action<GenerationStream>? onClosed = null)
    {
        _factory = factory ?? throw new ArgumentNullException(nameof(factory));
        CallerCancellation = callerCancellation;
        _onClosed = onClosed;
    }

    internal CancellationToken CallerCancellation { get; }

    /// <summary>Gets the winning result after successful terminal completion.</summary>
    public GenerationResult? Result
    {
        get
        {
            lock (_gate)
            {
                return _result;
            }
        }
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
    public IAsyncEnumerator<GenerationEvent> GetAsyncEnumerator(CancellationToken cancellationToken = default)
    {
        lock (_gate)
        {
            if (_closed)
            {
                return Empty().GetAsyncEnumerator(cancellationToken);
            }

            if (_claimed)
            {
                throw new InvalidOperationException("A GenerationStream has a single consumer.");
            }

            _claimed = true;
            var linked = CancellationTokenSource.CreateLinkedTokenSource(
                CallerCancellation,
                cancellationToken,
                _closeSource.Token);
            _enumerator = new StreamEnumerator(this, _factory(linked.Token).GetAsyncEnumerator(linked.Token), linked);
            return _enumerator;
        }
    }

    /// <inheritdoc />
    public ValueTask DisposeAsync()
    {
        lock (_gate)
        {
            if (_disposeTask is null)
            {
                _closed = true;
                _closeSource.Cancel();
                _disposeTask = DisposeCoreAsync(_enumerator);
            }

            return new ValueTask(_disposeTask);
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

    internal void PublishSuccess(GenerationResult result)
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

    private async Task DisposeCoreAsync(StreamEnumerator? enumerator)
    {
        await Task.Yield();
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
    }

    private void NotifyClosed()
    {
        if (Interlocked.Exchange(ref _closeNotified, 1) == 0)
        {
            _onClosed?.Invoke(this);
        }
    }

    private static async IAsyncEnumerable<GenerationEvent> Empty()
    {
        await Task.CompletedTask.ConfigureAwait(false);
        yield break;
    }

    private sealed class StreamEnumerator : IAsyncEnumerator<GenerationEvent>
    {
        private readonly GenerationStream _owner;
        private readonly IAsyncEnumerator<GenerationEvent> _inner;
        private readonly CancellationTokenSource _linked;
        private readonly SemaphoreSlim _moveGate = new(1, 1);
        private readonly object _disposeGate = new();
        private Task? _disposeTask;
        private Exception? _closeTimeMoveFailure;
        private int _disposed;

        internal StreamEnumerator(GenerationStream owner, IAsyncEnumerator<GenerationEvent> inner, CancellationTokenSource linked)
        {
            _owner = owner;
            _inner = inner;
            _linked = linked;
        }

        public GenerationEvent Current => _inner.Current;

        public async ValueTask<bool> MoveNextAsync()
        {
            await _moveGate.WaitAsync().ConfigureAwait(false);
            try
            {
                if (Volatile.Read(ref _disposed) != 0)
                {
                    return false;
                }

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
            _linked.Cancel();
            Exception? disposalFailure = null;
            await _moveGate.WaitAsync().ConfigureAwait(false);
            try
            {
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
