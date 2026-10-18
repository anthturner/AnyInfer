using AnyInfer.Internal;
using AnyInfer.Manifest;

namespace AnyInfer;

/// <summary>Represents one lazy generation operation and its ordered public events.</summary>
public sealed class AsyncStream : IAsyncEnumerable<StreamEvent>, IAsyncDisposable
{
    private readonly AsyncClient _client;
    private readonly Client? _syncClient;
    private readonly Func<CancellationToken, IAsyncEnumerable<StreamEvent>> _factory;
    private readonly CancellationTokenSource _closeSource = new();
    private readonly CancellationToken _closeToken;
    private readonly object _gate = new();
    private readonly Action<AsyncStream>? _onClosed;
    private StreamEnumerator? _enumerator;
    private Task? _disposeTask;
    private Task<Exception?>? _closeSignal;
    private bool _claimed;
    private bool _closed;
    private bool _succeeded;
    private bool _consumerClosing;
    private int _closeRequested;
    private int _closeNotified;
    private Generation? _result;
    private OperationContext? _operation;
    private readonly RequestTelemetry? _telemetry;
    private StreamOperationLease? _publicLease;

    internal AsyncStream(
        AsyncClient client,
        Client? syncClient,
        Func<CancellationToken, IAsyncEnumerable<StreamEvent>> factory,
        CancellationToken callerCancellation,
        Action<AsyncStream>? onClosed = null,
        RequestTelemetry? telemetry = null)
    {
        _client = client ?? throw new ArgumentNullException(nameof(client));
        _syncClient = syncClient;
        _factory = factory ?? throw new ArgumentNullException(nameof(factory));
        _closeToken = _closeSource.Token;
        CallerCancellation = callerCancellation;
        _onClosed = onClosed;
        _telemetry = telemetry;
    }

    internal CancellationToken CallerCancellation { get; }
    internal RequestTelemetry? Telemetry => _telemetry;

    /// <summary>Gets the immutable partial or terminal manifest when telemetry capture is enabled.</summary>
    public RunManifest? Manifest
    {
        get
        {
            lock (_gate)
            {
                return _result?.Manifest ?? _telemetry?.Partial;
            }
        }
    }

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
        bool beganBeforeClose;
        lock (_gate)
        {
            beganBeforeClose = !_closed;
        }

        await foreach (var _ in this.WithCancellation(cancellationToken).ConfigureAwait(false))
        {
        }

        ThrowIfCollectedCloseInterrupted(beganBeforeClose);
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
        Volatile.Write(ref _closeRequested, 1);
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
            if (_telemetry is null)
            {
                var linked = CancellationTokenSource.CreateLinkedTokenSource(CallerCancellation, cancellationToken, _closeToken);
                using var frozenContext = AsyncExecutionContext.Push(_client, _syncClient);
                using var frozenIdentity = CancellationIdentityContext.Push(linked.Token, CallerCancellation);
                _enumerator = new StreamEnumerator(this, _factory(linked.Token).GetAsyncEnumerator(linked.Token), linked);
                return _enumerator;
            }

            var lease = new StreamOperationLease(
                this,
                _client,
                _syncClient,
                CallerCancellation,
                cancellationToken,
                _closeToken,
                IsCloseRequested);
            _publicLease = lease;
            using var context = AsyncExecutionContext.Push(_client, _syncClient);
            using var identity = CancellationIdentityContext.Push(lease.Token, CallerCancellation);
            _enumerator = new StreamEnumerator(this, _factory(lease.Token).GetAsyncEnumerator(lease.Token), lease);
            return _enumerator;
        }
    }

    /// <summary>
    /// Closes this stream. A Public SDK callback running for this same stream must return before
    /// disposing it; dispose from outside that callback instead.
    /// </summary>
    public ValueTask DisposeAsync()
    {
        ThrowIfOwnedSelfDispose();
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
        Volatile.Write(ref _closeRequested, 1);
        lock (_gate)
        {
            _closed = true;
            return _closeSignal ??= Task.Run(SignalCloseCore);
        }
    }

    internal bool IsOwnedPublicExecution => _telemetry is not null && ReferenceEquals(StreamExecutionContext.Current, this);

    internal CancellationToken? CancelledParentToken => _publicLease?.CancelledParentToken;

    private bool IsCloseRequested() => Volatile.Read(ref _closeRequested) != 0;

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

    internal Generation? CommitSuccess(Generation result, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(result);
        if (_telemetry is null)
        {
            PublishSuccess(result);
            return result;
        }

        PreparedCompletion prepared;
        Generation committed;
        lock (_gate)
        {
            if (_closed || _consumerClosing)
            {
                return null;
            }

            ThrowOwnedCancellation(cancellationToken);
            prepared = _telemetry.PrepareCompletion(result);
            committed = result.WithManifest(prepared.Manifest);
            _succeeded = true;
            _result = committed;
        }

        using (AsyncExecutionContext.Push(_client, _syncClient))
        using (StreamExecutionContext.Push(this))
        using (_syncClient is null ? null : SyncExecutionContext.Push(_syncClient))
        {
            _telemetry.Complete(prepared);
        }
        return committed;
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
            using var streamContext = StreamExecutionContext.Push(this);
            using var syncContext = _syncClient is null ? null : SyncExecutionContext.Push(_syncClient);
            _closeSource.Cancel();
            return null;
        }
        catch (Exception exception)
        {
            return exception;
        }
    }

    private void ThrowIfCollectedCloseInterrupted(bool beganBeforeClose)
    {
        CancellationToken cancellation;
        lock (_gate)
        {
            if (!beganBeforeClose || !_closed || _result is not null)
            {
                return;
            }

            cancellation = CallerCancellation.IsCancellationRequested
                ? CallerCancellation
                : _closeToken;
        }

        throw new OperationCanceledException(cancellation);
    }

    private void ThrowOwnedCancellation(CancellationToken effective)
    {
        _publicLease?.ThrowIfParentCancelled();
        if (!effective.IsCancellationRequested)
        {
            return;
        }

        throw new OperationCanceledException(CallerCancellation.IsCancellationRequested ? CallerCancellation : effective);
    }

    private void ThrowIfOwnedSelfDispose()
    {
        if (IsOwnedPublicExecution)
        {
            throw new InvalidOperationException("A public stream cannot be disposed from its own callback. Dispose it after the callback returns.");
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
        private readonly StreamOperationLease? _lease;
        private readonly CancellationTokenSource? _linked;
        private readonly SemaphoreSlim _moveGate = new(1, 1);
        private readonly object _disposeGate = new();
        private Task? _disposeTask;
        private Exception? _closeTimeMoveFailure;
        private int _disposed;

        internal StreamEnumerator(AsyncStream owner, IAsyncEnumerator<StreamEvent> inner, StreamOperationLease lease)
        {
            _owner = owner;
            _inner = inner;
            _lease = lease;
        }

        internal StreamEnumerator(AsyncStream owner, IAsyncEnumerator<StreamEvent> inner, CancellationTokenSource linked)
        {
            _owner = owner;
            _inner = inner;
            _linked = linked;
        }

        private CancellationToken Token => _lease?.Token ?? _linked!.Token;

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
                using var stream = StreamExecutionContext.Push(_owner);
                using var identity = CancellationIdentityContext.Push(Token, _owner.CallerCancellation);
                _owner._telemetry?.Start();
                _lease?.ThrowIfParentCancelled();
                return await _inner.MoveNextAsync().ConfigureAwait(false);
            }
            catch (Exception exception)
            {
                if (exception is AnyInferException failure)
                {
                    using var context = AsyncExecutionContext.Push(_owner._client, _owner._syncClient);
                    using var stream = StreamExecutionContext.Push(_owner);
                    using var syncContext = _owner._syncClient is null ? null : SyncExecutionContext.Push(_owner._syncClient);
                    _owner._telemetry?.Fail(failure);
                }

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
            _owner.ThrowIfOwnedSelfDispose();
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
            Task<Exception?>? signal = null;
            Exception? signalFailure = null;
            if (_lease is not null)
            {
                signal = _lease.SignalCancelAsync();
            }
            else
            {
                try
                {
                    using var context = AsyncExecutionContext.Push(_owner._client, _owner._syncClient);
                    _linked!.Cancel();
                }
                catch (Exception exception)
                {
                    signalFailure = exception;
                }
            }
            Exception? disposalFailure = null;
            await _moveGate.WaitAsync().ConfigureAwait(false);
            try
            {
                using var context = AsyncExecutionContext.Push(_owner._client, _owner._syncClient);
                using var stream = StreamExecutionContext.Push(_owner);
                await _inner.DisposeAsync().ConfigureAwait(false);
            }
            catch (OperationCanceledException) when (Token.IsCancellationRequested)
            {
            }
            catch (Exception exception)
            {
                disposalFailure = exception;
            }
            finally
            {
                _moveGate.Release();
                _owner.PublishFailure();
            }

            try
            {
                if (signal is not null)
                {
                    await signal.ConfigureAwait(false);
                }

                if (_lease is not null)
                {
                    await _lease.DisposeAsync().ConfigureAwait(false);
                }
                else
                {
                    _linked!.Dispose();
                }
            }
            catch (Exception exception)
            {
                disposalFailure ??= exception;
            }

            disposalFailure ??= signalFailure;
            _owner.NotifyClosed();
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
            _owner.IsClosing && !(exception is OperationCanceledException cancellation
                && (Token.IsCancellationRequested || _lease?.IsOwnedParentCancellation(cancellation) == true));
    }
}
