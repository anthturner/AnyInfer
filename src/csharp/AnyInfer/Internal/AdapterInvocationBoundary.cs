using AnyInfer.Providers;
using AnyInfer.Schema;

namespace AnyInfer.Internal;

internal static class AdapterInvocationBoundary
{
    internal static IAsyncEnumerable<AdapterEvent> InvokeAsync(
        IProviderAdapter adapter,
        WireRequest request,
        OperationContext operation,
        EntryRole role,
        NativeAssessment? repairAssessment = null,
        CancellationToken cancellationToken = default) =>
        InvokeIterator(adapter, request, operation, role, repairAssessment, cancellationToken);

    private static async IAsyncEnumerable<AdapterEvent> InvokeIterator(
        IProviderAdapter adapter,
        WireRequest request,
        OperationContext operation,
        EntryRole role,
        NativeAssessment? repairAssessment,
        [System.Runtime.CompilerServices.EnumeratorCancellation] CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(adapter);
        ArgumentNullException.ThrowIfNull(request);
        ArgumentNullException.ThrowIfNull(operation);

        var entry = operation.BeginEntry(request, role, repairAssessment);
        var timeout = new EntryTimeoutScope(entry, cancellationToken, operation.EntryTimeProvider);
        using IDisposable? identity = request.UsesModernSchema
            ? CancellationIdentityContext.Push(timeout.Token, CancellationIdentityContext.Resolve(cancellationToken))
            : null;
        IAsyncEnumerator<AdapterEvent>? enumerator = null;
        try
        {
            IAsyncEnumerable<AdapterEvent> adapterEvents;
            try
            {
                adapterEvents = adapter.GenerateAsync(request, timeout.Token);
                enumerator = adapterEvents.GetAsyncEnumerator(timeout.Token);
                timeout.Enter();
            }
            catch (Exception exception)
            {
                throw RecordTerminalFailure(exception, entry, timeout, cancellationToken, request.Stream);
            }

            while (true)
            {
                bool moved;
                try
                {
                    moved = await enumerator.MoveNextAsync();
                }
                catch (Exception exception)
                {
                    throw RecordTerminalFailure(exception, entry, timeout, cancellationToken, request.Stream);
                }

                if (!moved)
                {
                    break;
                }

                var adapterEvent = enumerator.Current;
                entry.RecordAdapterEvent(adapterEvent);
                yield return adapterEvent;
            }
        }
        finally
        {
            Exception? cleanupFailure = null;
            if (enumerator is not null)
            {
                timeout.CleanupStart();
                try
                {
                    await enumerator.DisposeAsync();
                }
                catch (Exception exception)
                {
                    cleanupFailure = RecordTerminalFailure(exception, entry, timeout, cancellationToken, request.Stream);
                }
                finally
                {
                    timeout.CleanupEnd();
                }
            }

            await timeout.DisposeAsync().ConfigureAwait(false);
            if (cleanupFailure is not null)
            {
                System.Runtime.ExceptionServices.ExceptionDispatchInfo.Capture(cleanupFailure).Throw();
            }

            if (timeout.DeferredFailure is { } timerFailure && entry.TerminalFailure is null)
            {
                System.Runtime.ExceptionServices.ExceptionDispatchInfo.Capture(timerFailure).Throw();
            }
        }
    }

    private static Exception RecordTerminalFailure(
        Exception nativeFailure,
        EntryContext entry,
        EntryTimeoutScope timeout,
        CancellationToken callerToken,
        bool stream)
    {
        if (nativeFailure is OperationCanceledException && callerToken.IsCancellationRequested)
        {
            entry.RecordFailure(nativeFailure, nativeFailure);
            return nativeFailure;
        }

        if (nativeFailure is OperationCanceledException && timeout.IsExpired)
        {
            var timeoutFailure = new ProviderException(
                "The adapter entry exceeded its configured timeout.",
                "transport",
                retryable: true,
                phase: stream ? "stream" : "generate",
                nativeInner: nativeFailure);
            entry.RecordFailure(nativeFailure, timeoutFailure);
            return timeoutFailure;
        }

        entry.RecordFailure(nativeFailure, nativeFailure);
        return nativeFailure;
    }
}
