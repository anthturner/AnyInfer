using AnyInfer.Config;
using AnyInfer.Credentials;
using AnyInfer.Internal;
using AnyInfer.Json;
using AnyInfer.Providers;
using System.Runtime.ExceptionServices;

namespace AnyInfer;

/// <summary>Provides a synchronous facade over one lifetime-owned asynchronous client.</summary>
public sealed class Client : IDisposable
{
    private readonly AsyncClient _inner;
    private readonly CancellationTokenSource _lifetime = new();
    private readonly object _gate = new();
    private readonly HashSet<SyncStream> _streams = [];
    private readonly HashSet<TaskCompletionSource> _operations = [];
    private bool _closing;
    private Task? _disposeTask;
    private TaskCompletionSource<Exception?>? _lifetimeSignalCompletion;

    /// <summary>Creates a synchronous client over immutable provider settings and descriptor metadata.</summary>
    public Client(
        IEnumerable<ProviderSettings>? providers = null,
        ProviderRegistry? registry = null,
        ResolverChain? resolver = null,
        Route? route = null,
        Repair? repair = null)
        : this(new AsyncClient(providers, registry, resolver, route, repair))
    {
    }

    private Client(AsyncClient inner) => _inner = inner ?? throw new ArgumentNullException(nameof(inner));

    /// <summary>Creates a synchronous client over externally constructed adapters.</summary>
    public static Client FromAdapters(IEnumerable<ProviderRegistration> providers) => new(AsyncClient.FromAdapters(providers));

    /// <summary>Creates a synchronous client from inert parsed configuration.</summary>
    public static Client FromConfig(AnyInferConfig config, ProviderRegistry? registry = null, ResolverChain? resolver = null) =>
        new(AsyncClient.FromConfig(config, registry, resolver));

    /// <summary>Generates a terminal result from an explicit request.</summary>
    public Generation Generate(GenerationRequest request, CancellationToken cancellationToken = default) =>
        RunOperation(token => _inner.GenerateAsync(request, token), cancellationToken);

    /// <summary>Generates a terminal result from one user prompt.</summary>
    public Generation Generate(string prompt, string? target = null, Route? route = null, Sampling? sampling = null,
        Repair? repair = null, JsonValue? schema = null, string? schemaMechanism = null, double? timeoutS = null,
        int? maxResponseBytes = null, CancellationToken cancellationToken = default) =>
        RunOperation(token => _inner.GenerateAsync(prompt, target, route, sampling, repair, schema, schemaMechanism, timeoutS, maxResponseBytes, token), cancellationToken);

    /// <summary>Generates a terminal result from caller messages.</summary>
    public Generation Generate(IEnumerable<Message> messages, string? target = null, Route? route = null,
        Sampling? sampling = null, Repair? repair = null, JsonValue? schema = null, string? schemaMechanism = null,
        double? timeoutS = null, int? maxResponseBytes = null, CancellationToken cancellationToken = default) =>
        RunOperation(token => _inner.GenerateAsync(messages, target, route, sampling, repair, schema, schemaMechanism, timeoutS, maxResponseBytes, token), cancellationToken);

    /// <summary>Creates an eager-pump synchronous stream from an explicit request.</summary>
    public SyncStream Stream(GenerationRequest request, CancellationToken cancellationToken = default) =>
        CreateStream(() => _inner.StreamAsync(request, cancellationToken));

    /// <summary>Creates an eager-pump synchronous stream from one user prompt.</summary>
    public SyncStream Stream(string prompt, string? target = null, Route? route = null, Sampling? sampling = null,
        Repair? repair = null, JsonValue? schema = null, string? schemaMechanism = null, double? timeoutS = null,
        int? maxResponseBytes = null, CancellationToken cancellationToken = default) =>
        CreateStream(() => _inner.StreamAsync(prompt, target, route, sampling, repair, schema, schemaMechanism, timeoutS, maxResponseBytes, cancellationToken));

    /// <summary>Creates an eager-pump synchronous stream from caller messages.</summary>
    public SyncStream Stream(IEnumerable<Message> messages, string? target = null, Route? route = null,
        Sampling? sampling = null, Repair? repair = null, JsonValue? schema = null, string? schemaMechanism = null,
        double? timeoutS = null, int? maxResponseBytes = null, CancellationToken cancellationToken = default) =>
        CreateStream(() => _inner.StreamAsync(messages, target, route, sampling, repair, schema, schemaMechanism, timeoutS, maxResponseBytes, cancellationToken));

    /// <inheritdoc />
    public void Dispose()
    {
        if (ReferenceEquals(SyncExecutionContext.CurrentClient, this))
        {
            throw new InvalidOperationException("A Client cannot be disposed from an active client-owned callback.");
        }

        Task disposal;
        lock (_gate)
        {
            if (_disposeTask is null)
            {
                _closing = true;
                disposal = _disposeTask = Task.Run(DisposeCoreAsync);
            }
            else
            {
                disposal = _disposeTask;
            }
        }

        disposal.GetAwaiter().GetResult();
    }

    private Generation RunOperation(Func<CancellationToken, Task<Generation>> operation, CancellationToken callerCancellation)
    {
        ArgumentNullException.ThrowIfNull(operation);
        var reservation = ReserveOperation();
        try
        {
            return Task.Run(async () =>
            {
                using var context = SyncExecutionContext.Push(this);
                using var linked = CancellationTokenSource.CreateLinkedTokenSource(callerCancellation, _lifetime.Token);
                return await operation(linked.Token).ConfigureAwait(false);
            }).GetAwaiter().GetResult();
        }
        finally
        {
            CompleteOperation(reservation);
        }
    }

    private SyncStream CreateStream(Func<AsyncStream> create)
    {
        ArgumentNullException.ThrowIfNull(create);
        var reservation = ReserveOperation();
        AsyncStream? inner = null;
        SyncStream? stream = null;
        try
        {
            using (SyncExecutionContext.Push(this))
            {
                inner = create();
            }

            lock (_gate)
            {
                ThrowIfClosing();
            }

            stream = new SyncStream(this, inner, _lifetime.Token, RemoveStream);
            lock (_gate)
            {
                ThrowIfClosing();
                _streams.Add(stream);
                var published = stream;
                stream = null;
                return published;
            }
        }
        catch
        {
            if (stream is not null)
            {
                _ = stream.SignalCloseAsync();
                stream.CloseAsync().GetAwaiter().GetResult();
            }
            else if (inner is not null)
            {
                DisposeInner(inner);
            }

            throw;
        }
        finally
        {
            CompleteOperation(reservation);
        }
    }

    private TaskCompletionSource ReserveOperation()
    {
        var reservation = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        lock (_gate)
        {
            ThrowIfClosing();
            _operations.Add(reservation);
        }

        return reservation;
    }

    private void CompleteOperation(TaskCompletionSource reservation)
    {
        lock (_gate)
        {
            _operations.Remove(reservation);
        }

        reservation.TrySetResult();
    }

    private async Task DisposeCoreAsync()
    {
        SyncStream[] streams;
        Task[] operations;
        lock (_gate)
        {
            streams = _streams.ToArray();
            _streams.Clear();
            operations = _operations.Select(static reservation => reservation.Task).ToArray();
        }

        var lifetimeSignal = SignalLifetimeAsync();
        var signals = new Task<Exception?>[streams.Length];
        for (var index = 0; index < streams.Length; index++)
        {
            signals[index] = streams[index].SignalCloseAsync();
        }

        Exception? failure = await lifetimeSignal.ConfigureAwait(false);
        var signalFailures = await Task.WhenAll(signals).ConfigureAwait(false);
        foreach (var signalFailure in signalFailures)
        {
            failure ??= signalFailure;
        }

        foreach (var stream in streams)
        {
            try
            {
                await stream.CloseAsync().ConfigureAwait(false);
            }
            catch (Exception exception)
            {
                failure ??= exception;
            }
        }

        try
        {
            await Task.WhenAll(operations).ConfigureAwait(false);
            await _inner.DisposeAsync().ConfigureAwait(false);
        }
        catch (Exception exception)
        {
            failure ??= exception;
        }
        finally
        {
            _lifetime.Dispose();
        }

        if (failure is not null)
        {
            ExceptionDispatchInfo.Capture(failure).Throw();
        }
    }

    private Task<Exception?> SignalLifetimeAsync()
    {
        TaskCompletionSource<Exception?> completion;
        lock (_gate)
        {
            if (_lifetimeSignalCompletion is not null)
            {
                return _lifetimeSignalCompletion.Task;
            }

            completion = _lifetimeSignalCompletion = new TaskCompletionSource<Exception?>(TaskCreationOptions.RunContinuationsAsynchronously);
        }

        _ = Task.Run(() => SignalLifetimeCore(completion));
        return completion.Task;
    }

    private void SignalLifetimeCore(TaskCompletionSource<Exception?> completion)
    {
        Exception? failure = null;
        try
        {
            using var context = SyncExecutionContext.Push(this);
            _lifetime.Cancel();
        }
        catch (Exception exception)
        {
            failure = exception;
        }

        completion.TrySetResult(failure);
    }

    private void RemoveStream(SyncStream stream)
    {
        lock (_gate)
        {
            _streams.Remove(stream);
        }
    }

    private static void DisposeInner(AsyncStream inner) =>
        Task.Run(async () => await inner.DisposeAsync().ConfigureAwait(false)).GetAwaiter().GetResult();

    private void ThrowIfClosing()
    {
        if (_closing)
        {
            throw new ObjectDisposedException(nameof(Client));
        }
    }
}
