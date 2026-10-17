using System.Collections;
using System.Runtime.ExceptionServices;
using System.Threading.Channels;
using AnyInfer.Internal;

namespace AnyInfer;

/// <summary>Provides a bounded, single-consumer synchronous view of an asynchronous stream.</summary>
public sealed class SyncStream : IEnumerable<StreamEvent>, IDisposable
{
    private readonly Client _client;
    private readonly AsyncStream _inner;
    private readonly CancellationToken _lifetime;
    private readonly Action<SyncStream> _onClosed;
    private readonly CancellationTokenSource _close = new();
    private readonly Channel<StreamEvent> _events = Channel.CreateBounded<StreamEvent>(
        new BoundedChannelOptions(256) { FullMode = BoundedChannelFullMode.Wait, SingleReader = true, SingleWriter = true });
    private readonly object _gate = new();
    private readonly Task _pump;
    private bool _claimed;
    private bool _closed;
    private Task? _closeTask;
    private TaskCompletionSource<Exception?>? _signalCompletion;
    private Generation? _observedResult;
    private ExceptionDispatchInfo? _failure;

    internal SyncStream(Client client, AsyncStream inner, CancellationToken lifetime, Action<SyncStream> onClosed)
    {
        _client = client ?? throw new ArgumentNullException(nameof(client));
        _inner = inner ?? throw new ArgumentNullException(nameof(inner));
        _lifetime = lifetime;
        _onClosed = onClosed ?? throw new ArgumentNullException(nameof(onClosed));
        _pump = Task.Run(PumpAsync);
    }

    /// <summary>Gets the terminal generation after a consumer has observed <see cref="StreamEnded"/>.</summary>
    public Generation Result
    {
        get
        {
            lock (_gate)
            {
                return _observedResult ?? throw new InvalidOperationException(
                    "The stream has no observed terminal generation. Consume it to completion first.");
            }
        }
    }

    /// <summary>Drains this stream once and returns its terminal generation.</summary>
    public Generation Collect(CancellationToken cancellationToken = default)
    {
        Claim();
        try
        {
            while (MoveNext(cancellationToken, out _))
            {
            }

            return Result;
        }
        catch
        {
            Dispose();
            throw;
        }
        finally
        {
            if (!IsClosed)
            {
                Dispose();
            }
        }
    }

    /// <inheritdoc />
    public IEnumerator<StreamEvent> GetEnumerator()
    {
        Claim();
        return new Enumerator(this);
    }

    /// <inheritdoc />
    IEnumerator IEnumerable.GetEnumerator() => GetEnumerator();

    /// <inheritdoc />
    public void Dispose() => CloseAsync().GetAwaiter().GetResult();

    internal Task<Exception?> SignalCloseAsync()
    {
        TaskCompletionSource<Exception?> completion;
        lock (_gate)
        {
            _closed = true;
            if (_signalCompletion is not null)
            {
                return _signalCompletion.Task;
            }

            completion = _signalCompletion = new TaskCompletionSource<Exception?>(TaskCreationOptions.RunContinuationsAsynchronously);
        }

        _ = Task.Run(() => SignalCore(completion));
        return completion.Task;
    }

    private void SignalCore(TaskCompletionSource<Exception?> completion)
    {
        Exception? failure = null;
        try
        {
            using var context = SyncExecutionContext.Push(_client);
            _close.Cancel();
        }
        catch (Exception exception)
        {
            failure = exception;
        }

        completion.TrySetResult(failure);
    }

    internal Task CloseAsync()
    {
        lock (_gate)
        {
            if (_closeTask is null)
            {
                _closeTask = Task.Run(CloseCoreAsync);
            }

            return _closeTask;
        }
    }

    private async Task CloseCoreAsync()
    {
        Exception? failure = await SignalCloseAsync().ConfigureAwait(false);
        try
        {
            await _pump.ConfigureAwait(false);
        }
        catch (Exception exception)
        {
            failure ??= exception;
        }

        try
        {
            await _inner.DisposeAsync().ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (_close.IsCancellationRequested || _lifetime.IsCancellationRequested)
        {
        }
        catch (Exception exception)
        {
            failure ??= exception;
        }
        finally
        {
            _onClosed(this);
            _close.Dispose();
        }

        if (failure is not null)
        {
            ExceptionDispatchInfo.Capture(failure).Throw();
        }
    }

    private async Task PumpAsync()
    {
        using var context = SyncExecutionContext.Push(_client);
        using var linked = CancellationTokenSource.CreateLinkedTokenSource(
            _close.Token,
            _lifetime,
            _inner.CallerCancellation);
        try
        {
            await using var enumerator = _inner.GetAsyncEnumerator(linked.Token);
            while (await enumerator.MoveNextAsync().ConfigureAwait(false))
            {
                try
                {
                    await _events.Writer.WriteAsync(enumerator.Current, linked.Token).ConfigureAwait(false);
                }
                catch (OperationCanceledException) when (
                    _inner.CallerCancellation.IsCancellationRequested &&
                    !_close.IsCancellationRequested &&
                    !_lifetime.IsCancellationRequested)
                {
                    throw new OperationCanceledException(_inner.CallerCancellation);
                }
            }
        }
        catch (OperationCanceledException) when (_close.IsCancellationRequested || _lifetime.IsCancellationRequested)
        {
        }
        catch (Exception exception)
        {
            _failure = ExceptionDispatchInfo.Capture(exception);
        }
        finally
        {
            _events.Writer.TryComplete();
        }
    }

    private void Claim()
    {
        lock (_gate)
        {
            if (_closed)
            {
                throw new ObjectDisposedException(nameof(SyncStream));
            }

            if (_claimed)
            {
                throw new InvalidOperationException("A SyncStream has a single consumer.");
            }

            _claimed = true;
        }
    }

    private bool MoveNext(CancellationToken cancellationToken, out StreamEvent current)
    {
        lock (_gate)
        {
            if (_closed)
            {
                current = null!;
                return false;
            }
        }

        while (true)
        {
            if (_events.Reader.TryRead(out current!))
            {
                if (current is StreamEnded ended)
                {
                    lock (_gate)
                    {
                        _observedResult = ended.Result;
                    }
                }

                return true;
            }

            bool canRead;
            try
            {
                canRead = _events.Reader.WaitToReadAsync().AsTask().WaitAsync(cancellationToken).GetAwaiter().GetResult();
            }
            catch (OperationCanceledException)
            {
                _ = SignalCloseAsync();
                throw;
            }

            if (!canRead)
            {
                _failure?.Throw();
                current = null!;
                return false;
            }
        }
    }

    private bool IsClosed
    {
        get
        {
            lock (_gate)
            {
                return _closed;
            }
        }
    }

    private sealed class Enumerator : IEnumerator<StreamEvent>
    {
        private readonly SyncStream _owner;
        private bool _disposed;

        internal Enumerator(SyncStream owner) => _owner = owner;

        public StreamEvent Current { get; private set; } = null!;

        object IEnumerator.Current => Current;

        public bool MoveNext()
        {
            if (_disposed)
            {
                return false;
            }

            var moved = _owner.MoveNext(CancellationToken.None, out var current);
            Current = current;
            return moved;
        }

        public void Reset() => throw new NotSupportedException("A SyncStream cannot be reset.");

        public void Dispose()
        {
            if (_disposed)
            {
                return;
            }

            _disposed = true;
            _owner.Dispose();
        }
    }
}
