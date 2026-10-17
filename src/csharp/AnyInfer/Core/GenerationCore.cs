using System.Diagnostics;
using System.Runtime.CompilerServices;
using System.Text;
using AnyInfer.Internal;
using AnyInfer.Json;
using AnyInfer.Providers;
using AnyInfer.Schema;

namespace AnyInfer.Core;

internal static class GenerationCore
{
    internal static async IAsyncEnumerable<StreamEvent> ExecuteAsync(
        NormalizedRequest request,
        Route route,
        ProviderRegistry registry,
        RouteState health,
        IOperationClock clock,
        OperationCapture? capture,
        AsyncStream stream,
        [EnumeratorCancellation] CancellationToken cancellationToken)
    {
        var operation = new OperationContext(capture);
        stream.BeginOperation(operation);
        var attempts = new List<AttemptRecord>();
        var visitedTargets = new HashSet<ResolvedTarget>();

        try
        {
            foreach (var rawTarget in route.Targets)
            {
                cancellationToken.ThrowIfCancellationRequested();
                var resolved = registry.Resolve(rawTarget);
                if (!visitedTargets.Add(resolved.Target))
                {
                    continue;
                }

                if (route.HealthGate && health.IsUnhealthy(resolved.Target, route.HealthTtlS))
                {
                    attempts.Add(new AttemptRecord(resolved.Target, "skipped_unhealthy"));
                    continue;
                }

                var effectiveRepairs = EffectiveRepairBudget(request, resolved, operation, capture);
                for (var attemptNumber = 1; attemptNumber <= Math.Max(1, route.Retry.MaxAttempts); attemptNumber++)
                {
                    var routeState = new RouteAttemptState();
                    var current = CreateEntry(
                        resolved.Registration.Adapter,
                        RequestNormalizer.CreateWireRequest(request, resolved),
                        operation,
                        stream,
                        EntryRole.Original,
                        null,
                        routeState,
                        cancellationToken);

                    await foreach (var generationEvent in current.ReadAsync(cancellationToken).ConfigureAwait(false))
                    {
                        yield return generationEvent;
                    }

                    if (current.Error is not null)
                    {
                        var disposition = RecordFailure(
                            current.Error,
                            resolved.Target,
                            attempts,
                            attemptNumber,
                            route.Retry,
                            routeState.ContentEmitted,
                            health);
                        yield return new AttemptFailed(disposition.Attempt);
                        if (current.Error.Category == "stream_protocol" && routeState.ContentEmitted)
                        {
                            throw current.Error;
                        }

                        if (disposition.ShouldRetry)
                        {
                            await DelayAsync(route.Retry, attemptNumber, current.Error, clock, cancellationToken).ConfigureAwait(false);
                            continue;
                        }

                        break;
                    }

                    foreach (var usageEvent in current.FinalUsageEvents())
                    {
                        yield return usageEvent;
                    }

                    var repairs = 0;
                    var restartOriginal = false;
                    while (request.Schema is not null)
                    {
                        var assessment = SchemaValidator.AssessResponse(
                            request.Schema,
                            current.Text,
                            operation.OperationId,
                            current.Entry.Ordinal);
                        operation.RecordAssessment(assessment);
                        if (assessment.IsValid)
                        {
                            break;
                        }

                        if (repairs >= effectiveRepairs)
                        {
                            throw new SchemaViolationException("The response did not satisfy the requested schema.", assessment.Issues);
                        }

                        repairs++;
                        var preparation = RepairBuilder.Build(request.Messages, current.Text, assessment);
                        capture?.RecordRepair(operation.OperationId, preparation);
                        capture?.RecordTelemetry(
                            operation.OperationId,
                            new TelemetryObservation("repair_attempted", AttemptNumber: repairs));
                        current = CreateEntry(
                            resolved.Registration.Adapter,
                            RequestNormalizer.CreateWireRequest(request, resolved, preparation.Messages),
                            operation,
                            stream,
                            EntryRole.Correction,
                            assessment,
                            routeState,
                            cancellationToken);

                        await foreach (var generationEvent in current.ReadAsync(cancellationToken).ConfigureAwait(false))
                        {
                            yield return generationEvent;
                        }

                        if (current.Error is null)
                        {
                            foreach (var usageEvent in current.FinalUsageEvents())
                            {
                                yield return usageEvent;
                            }

                            continue;
                        }

                        var disposition = RecordFailure(
                            current.Error,
                            resolved.Target,
                            attempts,
                            attemptNumber,
                            route.Retry,
                            routeState.ContentEmitted,
                            health);
                        yield return new AttemptFailed(disposition.Attempt);
                        if (current.Error.Category == "stream_protocol" && routeState.ContentEmitted)
                        {
                            throw current.Error;
                        }

                        if (disposition.ShouldRetry)
                        {
                            await DelayAsync(route.Retry, attemptNumber, current.Error, clock, cancellationToken).ConfigureAwait(false);
                            restartOriginal = true;
                        }

                        break;
                    }

                    if (restartOriginal)
                    {
                        continue;
                    }

                    if (current.Error is not null)
                    {
                        break;
                    }

                    var structured = request.Schema is null ? null : operation.LastAssessment?.Structured;
                    attempts.Add(new AttemptRecord(resolved.Target, "ok"));
                    health.Clear(resolved.Target);
                    var totalMilliseconds = current.TotalMilliseconds;
                    var firstTokenMilliseconds = current.FirstTokenMilliseconds;
                    var result = new Generation(
                        current.Text,
                        structured,
                        resolved.Target,
                        current.FinishReason,
                        NormalizeWinningUsage(current.Usage),
                        new Timing(
                            current.StartedAt,
                            firstTokenMilliseconds,
                            totalMilliseconds,
                            OutputTokensPerSecond(current.Usage, firstTokenMilliseconds, totalMilliseconds)),
                        current.Entry.Request.Mechanism,
                        repairs,
                        attempts,
                        []);
                    stream.PublishSuccess(result);
                    yield return new StreamEnded(result);
                    yield break;
                }
            }

            throw new AllTargetsFailedException("Every resolved target failed.", attempts);
        }
        finally
        {
            operation.Complete();
        }
    }

    private static EntrySession CreateEntry(
        IProviderAdapter adapter,
        WireRequest wireRequest,
        OperationContext operation,
        AsyncStream stream,
        EntryRole role,
        NativeAssessment? assessment,
        RouteAttemptState routeState,
        CancellationToken cancellationToken) =>
        new(adapter, wireRequest, operation, role, assessment, routeState, cancellationToken, () => stream.IsClosing);
    private static int EffectiveRepairBudget(
        NormalizedRequest request,
        ResolvedProvider resolved,
        OperationContext operation,
        OperationCapture? capture)
    {
        var requested = request.RepairBudget;
        var ceiling = resolved.Registration.MaxRepairAttempts;
        if (ceiling is { } maximum && maximum < requested)
        {
            var reason = $"{resolved.Registration.ProviderId} allows at most {maximum} schema-repair round trip(s); {requested} requested";
            capture?.RecordTelemetry(
                operation.OperationId,
                new TelemetryObservation("parameter_dropped", "repair.max_attempts", reason));
            return maximum;
        }

        return requested;
    }

    private static FailureDisposition RecordFailure(
        ProviderException failure,
        ResolvedTarget target,
        List<AttemptRecord> attempts,
        int attemptNumber,
        Retry policy,
        bool contentEmitted,
        RouteState health)
    {
        var protocolAfterContent = failure.Category == "stream_protocol" && contentEmitted;
        var shouldRetry = !protocolAfterContent && CanRetry(failure, attemptNumber, policy);
        var attempt = new AttemptRecord(target, shouldRetry ? "retried" : "failed", failure);
        attempts.Add(attempt);
        if (!shouldRetry && !protocolAfterContent && ShouldMarkUnhealthy(failure))
        {
            health.MarkFailed(target);
        }

        return new FailureDisposition(attempt, shouldRetry);
    }

    private static bool CanRetry(ProviderException error, int attempt, Retry policy) =>
        error.Retryable && error.Category is not ("auth" or "context_length") && attempt < Math.Max(1, policy.MaxAttempts);

    private static bool ShouldMarkUnhealthy(ProviderException error) =>
        error.Category is "transport" or "provider_unavailable";

    private static async ValueTask DelayAsync(
        Retry policy,
        int attemptNumber,
        ProviderException error,
        IOperationClock clock,
        CancellationToken cancellationToken)
    {
        var delay = RouteState.BackoffSeconds(policy, attemptNumber, error.RetryAfterS);
        if (delay > 0)
        {
            await clock.DelayAsync(delay, cancellationToken).ConfigureAwait(false);
        }
    }

    private static Usage? OverlayUsage(Usage? existing, Usage? overlay)
    {
        if (overlay is null)
        {
            return existing;
        }

        return new Usage(
            overlay.InputTokens ?? existing?.InputTokens,
            overlay.OutputTokens ?? existing?.OutputTokens,
            overlay.TotalTokens ?? existing?.TotalTokens,
            overlay.CacheReadTokens ?? existing?.CacheReadTokens,
            overlay.CacheWriteTokens ?? existing?.CacheWriteTokens,
            overlay.ReasoningTokens ?? existing?.ReasoningTokens);
    }

    private static Usage? NormalizeWinningUsage(Usage? usage)
    {
        if (usage is null || usage.TotalTokens is not null || usage.InputTokens is null || usage.OutputTokens is null)
        {
            return usage;
        }

        return new Usage(
            usage.InputTokens,
            usage.OutputTokens,
            checked(usage.InputTokens.Value + usage.OutputTokens.Value),
            usage.CacheReadTokens,
            usage.CacheWriteTokens,
            usage.ReasoningTokens);
    }

    private static double? OutputTokensPerSecond(Usage? usage, double? firstTokenMs, double totalMs)
    {
        if (usage?.OutputTokens is not { } tokens || tokens <= 0 || firstTokenMs is null || totalMs <= firstTokenMs.Value)
        {
            return null;
        }

        return tokens / ((totalMs - firstTokenMs.Value) / 1000d);
    }

    private sealed record FailureDisposition(AttemptRecord Attempt, bool ShouldRetry);

    private sealed class RouteAttemptState
    {
        internal bool ContentEmitted { get; set; }
    }

    private sealed class EntrySession
    {
        private readonly IProviderAdapter _adapter;
        private readonly WireRequest _request;
        private readonly OperationContext _operation;
        private readonly EntryRole _role;
        private readonly NativeAssessment? _assessment;
        private readonly RouteAttemptState _routeState;
        private readonly CancellationToken _cancellationToken;
        private readonly Func<bool> _suppressCloseCancellation;
        private readonly StringBuilder _text = new();
        private EntryContext? _entry;
        private ProviderException? _error;
        private Usage? _usage;
        private string? _finishReason;
        private bool _sawAdapterUsage;
        private bool _firstContent;
        private bool _clean;
        private readonly Stopwatch _entryStopwatch = Stopwatch.StartNew();
        private readonly double _startedAt = System.Diagnostics.Stopwatch.GetTimestamp() / (double)System.Diagnostics.Stopwatch.Frequency;
        private double? _firstTokenMilliseconds;

        internal EntrySession(
            IProviderAdapter adapter,
            WireRequest request,
            OperationContext operation,
            EntryRole role,
            NativeAssessment? assessment,
            RouteAttemptState routeState,
            CancellationToken cancellationToken,
            Func<bool> suppressCloseCancellation)
        {
            _adapter = adapter;
            _request = request;
            _operation = operation;
            _role = role;
            _assessment = assessment;
            _routeState = routeState;
            _cancellationToken = cancellationToken;
            _suppressCloseCancellation = suppressCloseCancellation;
        }

        internal EntryContext Entry => _entry ?? throw new InvalidOperationException("The entry did not begin.");
        internal ProviderException? Error => _error;
        internal string Text => _text.ToString();
        internal Usage? Usage => _usage;
        internal string? FinishReason => _finishReason;
        internal double StartedAt => _startedAt;
        internal double? FirstTokenMilliseconds => _firstTokenMilliseconds;
        internal double TotalMilliseconds => _entryStopwatch.Elapsed.TotalMilliseconds;

        internal async IAsyncEnumerable<StreamEvent> ReadAsync([EnumeratorCancellation] CancellationToken cancellationToken)
        {
            IAsyncEnumerator<AdapterEvent>? enumerator = null;
            Task<ReadStep>? pending = null;
            try
            {
                enumerator = AdapterInvocationBoundary
                    .InvokeAsync(_adapter, _request, _operation, _role, _assessment, _cancellationToken)
                    .GetAsyncEnumerator(_cancellationToken);
                pending = ReadStepAsync(enumerator);
                _entry = _operation.LastEntry ?? throw new InvalidOperationException("The boundary did not create an entry.");
                yield return new TimingMark("attempt_start", 0);

                while (true)
                {
                    var step = await pending.ConfigureAwait(false);
                    pending = null;
                    if (step.Error is not null)
                    {
                        _error = step.Error;
                        yield break;
                    }

                    if (!step.Moved)
                    {
                        await enumerator.DisposeAsync().ConfigureAwait(false);
                        enumerator = null;
                        _clean = true;
                        yield break;
                    }

                    foreach (var generationEvent in Project(step.Event!))
                    {
                        yield return generationEvent;
                    }

                    pending = ReadStepAsync(enumerator);
                }
            }
            finally
            {
                Exception? pendingFailure = null;
                try
                {
                    if (pending is not null)
                    {
                        try
                        {
                            var step = await pending.ConfigureAwait(false);
                            if (step.Error is not null)
                            {
                                pendingFailure = step.Error;
                            }
                        }
                        catch (OperationCanceledException) when (_suppressCloseCancellation())
                        {
                        }
                    }
                }
                finally
                {
                    if (enumerator is not null)
                    {
                        await enumerator.DisposeAsync().ConfigureAwait(false);
                    }
                }

                if (pendingFailure is not null)
                {
                    System.Runtime.ExceptionServices.ExceptionDispatchInfo.Capture(pendingFailure).Throw();
                }
            }
        }

        internal IEnumerable<StreamEvent> FinalUsageEvents()
        {
            if (_clean && !_sawAdapterUsage && _usage is not null)
            {
                yield return new UsageUpdate(_usage);
            }
        }

        private static async Task<ReadStep> ReadStepAsync(IAsyncEnumerator<AdapterEvent> enumerator)
        {
            try
            {
                var moved = await enumerator.MoveNextAsync().ConfigureAwait(false);
                return moved ? new ReadStep(true, enumerator.Current, null) : new ReadStep(false, null, null);
            }
            catch (ProviderException error)
            {
                return new ReadStep(false, null, error);
            }
        }

        private IEnumerable<StreamEvent> Project(AdapterEvent adapterEvent)
        {
            switch (adapterEvent)
            {
                case AdapterTextDelta textDelta:
                    if (!_firstContent)
                    {
                        _firstContent = true;
                        _routeState.ContentEmitted = true;
                        var firstTokenMilliseconds = _entryStopwatch.Elapsed.TotalMilliseconds;
                        _firstTokenMilliseconds = firstTokenMilliseconds;
                        yield return new TimingMark("first_token", firstTokenMilliseconds);
                    }

                    _text.Append(textDelta.Text);
                    yield return new TextDelta(textDelta.Text);
                    break;
                case AdapterUsage usage:
                    _sawAdapterUsage = true;
                    _usage = OverlayUsage(_usage, usage.Usage);
                    yield return new UsageUpdate(usage.Usage);
                    break;
                case AdapterFinal final:
                    _finishReason = final.FinishReason;
                    _usage = OverlayUsage(_usage, final.Usage);
                    break;
            }
        }

        private sealed record ReadStep(bool Moved, AdapterEvent? Event, ProviderException? Error);
    }
}
