using AnyInfer.Core;
using AnyInfer.Internal;
using System.Runtime.ExceptionServices;
using AnyInfer.Providers;

namespace AnyInfer;

/// <summary>Owns provider adapters and creates lazy generation operations.</summary>
public sealed class AsyncClient : IAsyncDisposable
{
    private readonly ProviderRegistry _registry;
    private readonly IOperationClock _clock;
    private readonly RouteState _health;
    private readonly object _gate = new();
    private readonly HashSet<GenerationStream> _activeStreams = [];
    private bool _disposed;
    private Task? _disposeTask;

    /// <summary>Creates a client over immutable provider registrations.</summary>
    public AsyncClient(IEnumerable<ProviderRegistration> providers)
        : this(providers, new SystemOperationClock())
    {
    }

    internal AsyncClient(IEnumerable<ProviderRegistration> providers, IOperationClock clock)
    {
        _registry = new ProviderRegistry(providers);
        _clock = clock ?? throw new ArgumentNullException(nameof(clock));
        _health = new RouteState(_clock);
    }

    internal RouteState Health => _health;

    /// <summary>Consumes this client's single streaming execution path to its terminal result.</summary>
    public Task<GenerationResult> GenerateAsync(GenerationRequest request, CancellationToken cancellationToken = default) =>
        GenerateAsync(request, capture: null, cancellationToken: cancellationToken);

    internal async Task<GenerationResult> GenerateAsync(
        GenerationRequest request,
        OperationCapture? capture,
        CancellationToken cancellationToken = default)
    {
        await using var stream = StreamAsync(request, capture, cancellationToken);
        await foreach (var _ in stream.WithCancellation(cancellationToken).ConfigureAwait(false))
        {
        }

        return stream.Result ?? throw new InvalidOperationException("Generation completed without a terminal result.");
    }

    /// <summary>Creates a lazy single-consumer generation stream.</summary>
    public GenerationStream StreamAsync(GenerationRequest request, CancellationToken cancellationToken = default) =>
        StreamAsync(request, capture: null, cancellationToken: cancellationToken);

    internal GenerationStream StreamAsync(
        GenerationRequest request,
        OperationCapture? capture,
        CancellationToken cancellationToken = default)
    {
        ThrowIfDisposed();
        var normalized = RequestNormalizer.Normalize(request);
        GenerationStream? stream = null;
        stream = new GenerationStream(
            token => RunStreamAsync(normalized, request.Route, capture, stream!, token),
            cancellationToken,
            RemoveActiveStream);
        lock (_gate)
        {
            ThrowIfDisposed();
            _activeStreams.Add(stream);
        }

        return stream;
    }

    /// <inheritdoc />
    public ValueTask DisposeAsync()
    {
        lock (_gate)
        {
            if (_disposeTask is null)
            {
                _disposed = true;
                _disposeTask = DisposeCoreAsync(_activeStreams.ToArray());
                _activeStreams.Clear();
            }

            return new ValueTask(_disposeTask);
        }
    }

    private async Task DisposeCoreAsync(GenerationStream[] streams)
    {
        await Task.Yield();
        Exception? failure = null;
        foreach (var stream in streams)
        {
            try
            {
                await stream.DisposeAsync().ConfigureAwait(false);
            }
            catch (Exception exception)
            {
                failure ??= exception;
            }
        }

        foreach (var adapter in _registry.Adapters)
        {
            try
            {
                await adapter.DisposeAsync().ConfigureAwait(false);
            }
            catch (Exception exception)
            {
                failure ??= exception;
            }
        }

        if (failure is not null)
        {
            System.Runtime.ExceptionServices.ExceptionDispatchInfo.Capture(failure).Throw();
        }
    }
    private async IAsyncEnumerable<GenerationEvent> RunStreamAsync(
        NormalizedRequest normalized,
        Route route,
        OperationCapture? capture,
        GenerationStream stream,
        [System.Runtime.CompilerServices.EnumeratorCancellation] CancellationToken cancellationToken)
    {
        try
        {
            await foreach (var generationEvent in GenerationCore.ExecuteAsync(
                normalized,
                route,
                _registry,
                _health,
                _clock,
                capture,
                stream,
                cancellationToken).WithCancellation(cancellationToken).ConfigureAwait(false))
            {
                yield return generationEvent;
            }
        }
        finally
        {
            RemoveActiveStream(stream);
        }
    }

    private void RemoveActiveStream(GenerationStream stream)
    {
        lock (_gate)
        {
            _activeStreams.Remove(stream);
        }
    }
    private void ThrowIfDisposed()
    {
        lock (_gate)
        {
            if (_disposed)
            {
                throw new ObjectDisposedException(nameof(AsyncClient));
            }
        }
    }
}
