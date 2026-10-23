using System.Diagnostics;
using System.Runtime.CompilerServices;
using System.Text;
using AnyInfer.Capabilities;
using AnyInfer.Events;
using AnyInfer.Internal;
using AnyInfer.Json;
using AnyInfer.Providers;
using AnyInfer.Schema;
using AnyInfer.Routing;
using PeterO.Numbers;

namespace AnyInfer.Core;

internal static class GenerationCore
{
    internal static async IAsyncEnumerable<StreamEvent> ExecuteAsync(
        NormalizedRequest request,
        Route route,
        ProviderPool registry,
        TargetMetadataResolver targetResolver,
        TargetResolutionProfile resolutionProfile,
        RouteState health,
        IOperationClock clock,
        OperationCapture? capture,
        AsyncStream stream,
        GenerationPolicyContext? policyContext,
        [EnumeratorCancellation] CancellationToken cancellationToken,
        bool retainRaw = false)
    {
        var operation = new OperationContext(capture, policyContext?.EntryTimeProvider);
        stream.BeginOperation(operation);
        var telemetry = stream.Telemetry;
        var attempts = new List<AttemptRecord>();
        var visitedTargets = new HashSet<(string ProviderId, string Model)>();
        PendingFallback? pendingFallback = null;
        var pendingTargets = new Queue<string>(route.Targets);

        try
        {
            while (pendingTargets.TryDequeue(out var rawTarget))
            {
                cancellationToken.ThrowIfCancellationRequested();

                if (pendingFallback is { } pending)
                {
                    telemetry?.Emit(new FallbackTriggered(
                        telemetry.RequestId,
                        pending.Target,
                        rawTarget,
                        pending.Error));
                    pendingFallback = null;
                }

                var metadata = targetResolver.Resolve(rawTarget, resolutionProfile);
                if (!visitedTargets.Add((metadata.Target.ProviderId, metadata.Target.Model)))
                {
                    continue;
                }

                telemetry?.Emit(new TargetResolved(telemetry.RequestId, metadata.Target));

                if (route.HealthGate && health.IsUnhealthy(metadata.Target, route.HealthTtlS))
                {
                    attempts.Add(new AttemptRecord(metadata.Target, "skipped_unhealthy"));
                    continue;
                }

                var resolved = registry.Materialize(metadata);
                Func<CancellationToken?>? cancelledParentToken = resolutionProfile == TargetResolutionProfile.PublicSdk
                    ? () => stream.CancelledParentToken
                    : null;
                var callerIdentity = resolutionProfile == TargetResolutionProfile.PublicSdk
                    ? stream.CallerCancellation
                    : default;
                var adapter = await registry.GetAdapterAsync(
                    resolved,
                    cancellationToken,
                    cancelledParentToken,
                    callerIdentity).ConfigureAwait(false);
                if (resolved.Descriptor is { } descriptor && !descriptor.Operations.Contains(InferenceOperation.Generation))
                {
                    throw new ConfigException(
                        "The selected provider does not declare generation support.",
                        resolved.Target.ProviderId,
                        hint: "Configure a provider descriptor that declares generation support.");
                }
                if (adapter is not IGeneratesText generatesText)
                {
                    throw new ConfigException(
                        "The selected provider does not implement generation support.",
                        resolved.Target.ProviderId,
                        hint: "Configure a provider adapter that implements IGeneratesText.");
                }
                telemetry?.NoteCapabilities(metadata);
                var pacing = resolutionProfile == TargetResolutionProfile.PublicSdk
                    ? registry.GetPacing(resolved)
                    : default;

                var effectiveRepairs = EffectiveRepairBudget(request, resolved, operation, capture, telemetry);
                var contextRedirected = false;
                for (var attemptNumber = 1; attemptNumber <= Math.Max(1, route.Retry.MaxAttempts); attemptNumber++)
                {
                    var attemptStopwatch = Stopwatch.StartNew();
                    var attemptStartedAt = Stopwatch.GetTimestamp() / (double)Stopwatch.Frequency;
                    var publicSdk = request.SchemaProfile == SchemaExecutionProfile.ModernSdk;
                    var routeState = new RouteAttemptState();
                    telemetry?.Emit(new AttemptStarted(telemetry.RequestId, resolved.Target, attemptNumber));
                    ProviderException? admissionError = null;
                    try
                    {
                        RichGenerationPolicy.ValidateInputs(request, metadata, resolved);
                        if (attemptNumber == 1) RichGenerationPolicy.EmitDroppedParameters(request, metadata, resolved, telemetry);
                        EnforceSpend(policyContext, metadata, resolved, telemetry);
                        CheckContextGate(policyContext, metadata, resolved, telemetry);
                    }
                    catch (ProviderException error)
                    {
                        admissionError = error;
                    }

                    if (admissionError is not null)
                    {
                        var disposition = RecordFailure(
                            admissionError,
                            resolved.Target,
                            attempts,
                            attemptNumber,
                            route.Retry,
                            contentEmitted: false,
                            health: health,
                            timing: publicSdk ? new Timing(attemptStartedAt, totalMs: attemptStopwatch.Elapsed.TotalMilliseconds) : null);
                        yield return new AttemptFailed(disposition.Attempt);
                        pendingFallback = new PendingFallback(resolved.Target, admissionError.Snapshot());
                        contextRedirected = admissionError is ContextLengthException && ReplaceWithContextWindowTargets(route, pendingTargets, visitedTargets, targetResolver, resolutionProfile);
                        break;
                    }

                    var cachePlan = PlanCache(policyContext, metadata, resolved, telemetry);
                    var cacheMarks = cachePlan.Marks.Select(static mark => mark.Segment).ToArray();
                    var wireRequest = RequestNormalizer.CreateWireRequest(request, resolved, cacheMarks: cacheMarks, capabilities: metadata.ResolvedCapabilities);
                    if (resolutionProfile == TargetResolutionProfile.PublicSdk && pacing.Limiter?.UnsupportedHeadersReason is { } headersReason)
                    {
                        telemetry?.Emit(new ParameterDropped(
                            telemetry.RequestId,
                            resolved.Target,
                            "limits.respect_headers",
                            headersReason));
                    }
                    var current = CreateEntry(
                        generatesText,
                        wireRequest,
                        operation,
                        stream,
                        resolved.Target,
                        EntryRole.Original,
                        null,
                        routeState,
                        cancellationToken,
                        telemetry,
                        request.SchemaProfile == SchemaExecutionProfile.ModernSdk,
                        pacing,
                        cancelledParentToken,
                        retainRaw);

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
                            health,
                            publicSdk ? current.BuildTiming() : null);
                        yield return new AttemptFailed(disposition.Attempt);
                        if (current.Error.Category == "stream_protocol" && routeState.ContentEmitted)
                        {
                            throw current.Error;
                        }

                        if (disposition.ShouldRetry)
                        {
                            var delay = RouteState.BackoffSeconds(route.Retry, attemptNumber, current.Error.RetryAfterS);
                            telemetry?.Emit(new RetryScheduled(telemetry.RequestId, resolved.Target, attemptNumber, delay, current.Error.Snapshot()));
                            await DelayAsync(delay, clock, cancellationToken).ConfigureAwait(false);
                            continue;
                        }

                        pendingFallback = new PendingFallback(resolved.Target, current.Error.Snapshot());
                        if (current.Error.Category == "context_length")
                        {
                            contextRedirected = ReplaceWithContextWindowTargets(route, pendingTargets, visitedTargets, targetResolver, resolutionProfile);
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
                        var assessment = request.SchemaProfile == SchemaExecutionProfile.FrozenV0
                            ? FrozenSchemaValidator.AssessResponse(
                                request.Schema.JsonSchema,
                                current.Text,
                                operation.OperationId,
                                current.Entry.Ordinal)
                            : await SchemaValidator.AssessResponseAsync(
                                request.Schema,
                                current.Text,
                                operation.OperationId,
                                current.Entry.Ordinal,
                                request.SchemaValidation,
                                resolved.Target.ProviderId,
                                cancellationToken).ConfigureAwait(false);
                        var callerCancellation = CancellationIdentityContext.Resolve(cancellationToken);
                        if (callerCancellation.IsCancellationRequested)
                        {
                            throw new OperationCanceledException(callerCancellation);
                        }
                        cancellationToken.ThrowIfCancellationRequested();
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
                        telemetry?.NoteRepairText(current.Text);
                        telemetry?.Emit(new RepairAttempted(
                            telemetry.RequestId,
                            resolved.Target,
                            repairs,
                            current.Entry.Request.Mechanism,
                            assessment.Messages,
                            telemetry.WantsPayloads ? current.Text : null));
                        var preparation = RepairBuilder.Build(request.Messages, current.Text, assessment);
                        capture?.RecordRepair(operation.OperationId, preparation);
                        capture?.RecordTelemetry(
                            operation.OperationId,
                            new TelemetryObservation("repair_attempted", AttemptNumber: repairs));
                        current = CreateEntry(
                            generatesText,
                            RequestNormalizer.CreateWireRequest(request, resolved, preparation.Messages, cacheMarks: cacheMarks, capabilities: metadata.ResolvedCapabilities),
                            operation,
                            stream,
                            resolved.Target,
                            EntryRole.Correction,
                            assessment,
                            routeState,
                            cancellationToken,
                            telemetry,
                            request.SchemaProfile == SchemaExecutionProfile.ModernSdk,
                            pacing,
                            cancelledParentToken,
                            retainRaw);

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
                            health,
                            publicSdk ? current.BuildTiming() : null);
                        yield return new AttemptFailed(disposition.Attempt);
                        if (current.Error.Category == "stream_protocol" && routeState.ContentEmitted)
                        {
                            throw current.Error;
                        }

                        if (disposition.ShouldRetry)
                        {
                            var delay = RouteState.BackoffSeconds(route.Retry, attemptNumber, current.Error.RetryAfterS);
                            telemetry?.Emit(new RetryScheduled(telemetry.RequestId, resolved.Target, attemptNumber, delay, current.Error.Snapshot()));
                            await DelayAsync(delay, clock, cancellationToken).ConfigureAwait(false);
                            restartOriginal = true;
                        }
                        else
                        {
                            pendingFallback = new PendingFallback(resolved.Target, current.Error.Snapshot());
                            if (current.Error.Category == "context_length")
                            {
                                contextRedirected = ReplaceWithContextWindowTargets(route, pendingTargets, visitedTargets, targetResolver, resolutionProfile);
                            }
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
                    // FrozenV0 has always exposed the winning entry's observed timing too.
                    // ModernSdk additionally projects that same entry timing into its attempt trail.
                    var winningTiming = current.BuildTiming();
                    attempts.Add(new AttemptRecord(resolved.Target, "ok", timing: publicSdk ? winningTiming : null));
                    health.Clear(resolved.Target);
                    var winningUsage = NormalizeWinningUsage(current.Usage, publicSdk);
                    if (publicSdk && winningUsage is not null)
                    {
                        winningUsage = PricingCalculator.WithCost(winningUsage, metadata.ResolvedCapabilities);
                    }

                    var toolCalls = current.ToolCalls;
                    var finishReason = toolCalls.Count > 0 && current.FinishReason == "stop"
                        ? "tool_calls"
                        : current.FinishReason;
                    var result = new Generation(
                        current.Text,
                        structured,
                        resolved.Target,
                        finishReason,
                        winningUsage,
                        winningTiming,
                        current.Entry.Request.Mechanism,
                        repairs,
                        attempts,
                        current.Warnings,
                        toolCalls: toolCalls,
                        raw: retainRaw && publicSdk ? current.Raw : null,
                        logprobs: current.Logprobs,
                        citations: current.Citations,
                        serverToolUses: current.ServerToolUses);
                    telemetry?.Emit(new AttemptCompleted(
                        telemetry.RequestId,
                        resolved.Target,
                        result.Usage ?? new Usage(),
                        result.Timing ?? new Timing(),
                        result.FinishReason ?? ""));
                    var committed = stream.CommitSuccess(result, cancellationToken);
                    if (committed is null)
                    {
                        yield break;
                    }

                    yield return new StreamEnded(committed);
                    yield break;
                }

                if (contextRedirected)
                {
                    continue;
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
        IGeneratesText adapter,
        WireRequest wireRequest,
        OperationContext operation,
        AsyncStream stream,
        ResolvedTarget target,
        EntryRole role,
        NativeAssessment? assessment,
        RouteAttemptState routeState,
        CancellationToken cancellationToken,
        RequestTelemetry? telemetry,
        bool publicSdk,
        PacingSelection pacing,
        Func<CancellationToken?>? cancelledParentToken,
        bool retainRaw) =>
        new(
            adapter,
            wireRequest,
            operation,
            target,
            role,
            assessment,
            routeState,
            cancellationToken,
            () => stream.IsClosing,
            telemetry,
            publicSdk,
            pacing,
            cancelledParentToken,
            retainRaw);

    private static void EnforceSpend(
        GenerationPolicyContext? policyContext,
        TargetMetadata metadata,
        ResolvedProvider resolved,
        RequestTelemetry? telemetry)
    {
        if (policyContext?.SpendPolicy is not { Active: true } policy)
        {
            return;
        }

        var ledger = policyContext.Ledger ?? throw new InvalidOperationException("An active spend policy requires a spend ledger.");
        var estimate = metadata.ResolvedCapabilities?.Pricing is null
            ? null
            : ContextBudgeting.BuildContextBudget(
                policyContext.Request,
                metadata.ResolvedCapabilities,
                policyContext.Estimator,
                new TokenCalibration()).EstimatedCost?.High;
        var spent = ledger.Totals().Cost;
        if (estimate is null)
        {
            if (policy.OnUnknown == "refuse")
            {
                throw new SpendLimitException(
                    $"the cost of a request to {resolved.Target} cannot be estimated",
                    UnknownSpendLimit(policy),
                    spent,
                    hint: "this target has no trusted pricing; set onUnknown='allow' to send it anyway, or supply pricing as a capability override");
            }

            return;
        }

        if (policy.MaxRequestUsd is { } requestLimit && AccountingDecimal.Compare(estimate, requestLimit) > 0)
        {
            throw new SpendLimitException(
                $"a request to {resolved.Target} could cost {estimate}, above the per-request ceiling of {requestLimit}",
                requestLimit,
                spent,
                estimate,
                "shorten the prompt, cap max_output_tokens, or raise max_request_usd");
        }

        if (policy.MaxTotalUsd is not { } totalLimit)
        {
            return;
        }

        var requestId = telemetry?.RequestId ?? throw new InvalidOperationException("Public spend enforcement requires request telemetry.");
        var reservation = ledger.Reserve(requestId, estimate, totalLimit);
        if (!reservation.Accepted)
        {
            throw new SpendLimitException(
                $"this client has spent {reservation.Spent}, reserved {reservation.Reserved}, and the next request could cost {estimate}, above the ceiling of {totalLimit}",
                totalLimit,
                reservation.Spent,
                estimate,
                "raise max_total_usd, or reset the ledger to start a new budget");
        }
    }

    private static EDecimal? UnknownSpendLimit(SpendPolicy policy)
    {
        if (policy.MaxRequestUsd is { } requestLimit && AccountingDecimal.Compare(requestLimit, EDecimal.Zero) != 0)
        {
            return requestLimit;
        }

        return policy.MaxTotalUsd;
    }

    private static void CheckContextGate(
        GenerationPolicyContext? policyContext,
        TargetMetadata metadata,
        ResolvedProvider resolved,
        RequestTelemetry? telemetry)
    {
        if (policyContext?.ContextGate != true)
        {
            return;
        }

        ContextBudgeting.CheckContextFit(
            policyContext.Request,
            metadata.ResolvedCapabilities,
            policyContext.Estimator,
            metadata.Descriptor?.TokenCalibration,
            provider: resolved.Target.ProviderId,
            model: resolved.Target.Model);
        telemetry?.Emit(new UsageEstimated(
            telemetry.RequestId,
            resolved.Target,
            "input_tokens",
            "pre-dispatch context-gate estimate"));
    }

    private static bool ReplaceWithContextWindowTargets(
        Route route,
        Queue<string> pendingTargets,
        HashSet<(string ProviderId, string Model)> visitedTargets,
        TargetMetadataResolver targetResolver,
        TargetResolutionProfile resolutionProfile)
    {
        if (route.ContextWindowTargets.Count == 0)
        {
            return false;
        }

        pendingTargets.Clear();
        foreach (var target in route.ContextWindowTargets)
        {
            var metadata = targetResolver.Resolve(target, resolutionProfile);
            if (!visitedTargets.Contains((metadata.Target.ProviderId, metadata.Target.Model)))
            {
                pendingTargets.Enqueue(target);
            }
        }

        return true;
    }

    private static CachePlan PlanCache(
        GenerationPolicyContext? policyContext,
        TargetMetadata metadata,
        ResolvedProvider resolved,
        RequestTelemetry? telemetry)
    {
        if (policyContext is null || policyContext.CachePolicy is not { Active: true } policy)
        {
            return new CachePlan();
        }

        var plan = metadata.Descriptor is null
            ? new CachePlan(reasons: ["the target declares no prompt-cache mechanism"])
            : CachePlanning.Plan(
                policyContext.Request,
                policy,
                metadata.ResolvedCapabilities ?? new ModelCapabilities(),
                metadata.Descriptor,
                policyContext.Estimator ?? new HeuristicTokenEstimator());

        if (plan.Mechanism == CacheMechanism.Implicit &&
            policyContext.PrefixChanged(resolved.Target, plan.PrefixSignature(policyContext.Request)))
        {
            telemetry?.Emit(new ProviderDiagnostic(
                resolved.Target,
                new Diagnostic(
                    "cache.prefix-unstable",
                    "info",
                    "the cacheable prefix changed since the last request to this target, so the provider's prompt cache will not be hit")));
        }

        if (!plan.Active)
        {
            telemetry?.Emit(new ParameterDropped(
                telemetry.RequestId,
                resolved.Target,
                "cache.mode",
                plan.Reasons.FirstOrDefault() ?? "no cacheable segment"));
        }
        else if (policy.Mode == CacheMode.Explicit && plan.Mechanism == CacheMechanism.Implicit)
        {
            telemetry?.Emit(new ParameterDropped(
                telemetry.RequestId,
                resolved.Target,
                "cache.mode",
                "the target offers implicit caching, not explicit marks"));
        }

        if (plan.Active)
        {
            telemetry?.Emit(new CachePlanned(
                telemetry.RequestId,
                resolved.Target,
                plan.Mechanism!.Value.ToString().ToLowerInvariant(),
                plan.Marks.Count,
                plan.EstimatedCacheableTokens));
        }

        return plan;
    }
    private static int EffectiveRepairBudget(
        NormalizedRequest request,
        ResolvedProvider resolved,
        OperationContext operation,
        OperationCapture? capture,
        RequestTelemetry? telemetry)
    {
        var requested = request.RepairBudget;
        var ceiling = resolved.MaxRepairAttempts;
        if (ceiling is { } maximum && maximum < requested)
        {
            var reason = $"{resolved.Target.ProviderId} allows at most {maximum} schema-repair round trip(s); {requested} requested";
            capture?.RecordTelemetry(
                operation.OperationId,
                new TelemetryObservation("parameter_dropped", "repair.max_attempts", reason));
            telemetry?.Emit(new ParameterDropped(telemetry.RequestId, resolved.Target, "repair.max_attempts", reason));
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
        RouteState health,
        Timing? timing)
    {
        var protocolAfterContent = failure.Category == "stream_protocol" && contentEmitted;
        var shouldRetry = !protocolAfterContent && CanRetry(failure, attemptNumber, policy);
        var attempt = new AttemptRecord(target, shouldRetry ? "retried" : "failed", failure, timing);
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
        double delay,
        IOperationClock clock,
        CancellationToken cancellationToken)
    {
        if (delay > 0)
        {
            await clock.DelayAsync(delay, cancellationToken).ConfigureAwait(false);
        }
    }

    private static Usage? OverlayUsage(Usage? existing, Usage? overlay, bool publicSdk)
    {
        if (overlay is null)
        {
            return existing;
        }

        if (publicSdk)
        {
            return existing is null ? overlay : existing.Merge(overlay);
        }

        return new Usage(
            overlay.InputTokens ?? existing?.InputTokens,
            overlay.OutputTokens ?? existing?.OutputTokens,
            overlay.TotalTokens ?? existing?.TotalTokens,
            overlay.CacheReadTokens ?? existing?.CacheReadTokens,
            overlay.CacheWriteTokens ?? existing?.CacheWriteTokens,
            overlay.ReasoningTokens ?? existing?.ReasoningTokens);
    }

    private static Usage? NormalizeWinningUsage(Usage? usage, bool publicSdk)
    {
        if (publicSdk)
        {
            return usage?.Normalized();
        }

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
    private sealed record PendingFallback(ResolvedTarget Target, ErrorInfo Error);

    private sealed class RouteAttemptState
    {
        internal bool ContentEmitted { get; set; }
    }

    private sealed class EntrySession
    {
        private readonly IGeneratesText _adapter;
        private readonly WireRequest _request;
        private readonly OperationContext _operation;
        private readonly ResolvedTarget _target;
        private readonly EntryRole _role;
        private readonly NativeAssessment? _assessment;
        private readonly RouteAttemptState _routeState;
        private readonly CancellationToken _cancellationToken;
        private readonly Func<bool> _suppressCloseCancellation;
        private readonly RequestTelemetry? _telemetry;
        private readonly bool _publicSdk;
        private readonly PacingSelection _pacing;
        private readonly Func<CancellationToken?>? _cancelledParentToken;
        private AttemptPacing? _attemptPacing;
        private readonly StringBuilder _text = new();
        private readonly Dictionary<int, ToolCallBuffer> _toolCalls = [];
        private readonly List<string> _warnings = [];
        private readonly List<Citation> _citations = [];
        private readonly List<ServerToolUse> _serverToolUses = [];
        private IReadOnlyList<TokenLogprob> _logprobs = [];
        private IReadOnlyDictionary<string, double> _providerPhases = new Dictionary<string, double>();
        private EntryContext? _entry;
        private ProviderException? _error;
        private Usage? _usage;
        private string? _finishReason;
        private readonly bool _retainRaw;
        private JsonValue? _raw;
        private bool _sawAdapterUsage;
        private bool _sawTerminalUsage;
        private bool _firstContent;
        private bool _clean;
        private readonly Stopwatch _entryStopwatch = Stopwatch.StartNew();
        private readonly double _startedAt = System.Diagnostics.Stopwatch.GetTimestamp() / (double)System.Diagnostics.Stopwatch.Frequency;
        private double? _firstTokenMilliseconds;

        internal EntrySession(
            IGeneratesText adapter,
            WireRequest request,
            OperationContext operation,
            ResolvedTarget target,
            EntryRole role,
            NativeAssessment? assessment,
            RouteAttemptState routeState,
            CancellationToken cancellationToken,
            Func<bool> suppressCloseCancellation,
            RequestTelemetry? telemetry,
            bool publicSdk,
            PacingSelection pacing,
            Func<CancellationToken?>? cancelledParentToken,
            bool retainRaw)
        {
            _adapter = adapter;
            _request = request;
            _operation = operation;
            _target = target;
            _role = role;
            _assessment = assessment;
            _routeState = routeState;
            _cancellationToken = cancellationToken;
            _suppressCloseCancellation = suppressCloseCancellation;
            _telemetry = telemetry;
            _publicSdk = publicSdk;
            _pacing = pacing;
            _cancelledParentToken = cancelledParentToken;
            _retainRaw = retainRaw;
        }

        internal EntryContext Entry => _entry ?? throw new InvalidOperationException("The entry did not begin.");
        internal ProviderException? Error => _error;
        internal string Text => _text.ToString();
        internal Usage? Usage => _usage;
        internal string? FinishReason => _finishReason;
        internal JsonValue? Raw => _raw;
        internal double StartedAt => _startedAt;
        internal double? FirstTokenMilliseconds => _firstTokenMilliseconds;
        internal double TotalMilliseconds => _entryStopwatch.Elapsed.TotalMilliseconds;
        internal double QueuedMilliseconds => _attemptPacing?.WaitedMs ?? 0;
        internal IReadOnlyList<ToolCall> ToolCalls => BuildToolCalls();
        internal IReadOnlyList<string> Warnings => _warnings;
        internal IReadOnlyList<Citation> Citations => _citations;
        internal IReadOnlyList<ServerToolUse> ServerToolUses => _serverToolUses;
        internal IReadOnlyList<TokenLogprob> Logprobs => _logprobs;
        internal IReadOnlyDictionary<string, double> ProviderPhases => _providerPhases;

        internal Timing BuildTiming()
        {
            var totalMilliseconds = TotalMilliseconds;
            return new Timing(
                StartedAt,
                FirstTokenMilliseconds,
                totalMilliseconds,
                OutputTokensPerSecond(Usage, FirstTokenMilliseconds, totalMilliseconds),
                ProviderPhases.Concat(QueuedMilliseconds > 0
                    ? [new KeyValuePair<string, double>("queued_ms", QueuedMilliseconds)]
                    : []));
        }

        internal async IAsyncEnumerable<StreamEvent> ReadAsync([EnumeratorCancellation] CancellationToken cancellationToken)
        {
            IAsyncEnumerator<AdapterEvent>? enumerator = null;
            Task<ReadStep>? pending = null;
            RateLimitLease? outerLease = null;
            _attemptPacing = _pacing.Limiter is null ? null : new AttemptPacing(_telemetry?.RequestId ?? string.Empty, _target);
            try
            {
                ThrowIfParentCancelled();
                if (_pacing.UsesOuterSlot && _pacing.Limiter is not null)
                {
                    outerLease = await _pacing.Limiter
                        .AcquireAsync(_cancellationToken, _cancelledParentToken)
                        .ConfigureAwait(false);
                    ThrowIfParentCancelled();
                }

                enumerator = AdapterInvocationBoundary
                    .InvokeAsync(_adapter, _request, _operation, _role, _assessment, _cancellationToken, _cancelledParentToken)
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
                    Exception? cleanupFailure = null;
                    if (enumerator is not null)
                    {
                        try
                        {
                            await enumerator.DisposeAsync().ConfigureAwait(false);
                        }
                        catch (Exception exception)
                        {
                            cleanupFailure = exception;
                        }
                    }

                    if (outerLease is not null)
                    {
                        try
                        {
                            await outerLease.DisposeAsync().ConfigureAwait(false);
                        }
                        catch (Exception exception)
                        {
                            cleanupFailure ??= exception;
                        }
                    }

                    try
                    {
                        _attemptPacing?.Dispose();
                    }
                    catch (Exception exception)
                    {
                        cleanupFailure ??= exception;
                    }

                    if (cleanupFailure is not null)
                    {
                        System.Runtime.ExceptionServices.ExceptionDispatchInfo.Capture(cleanupFailure).Throw();
                    }
                }

                if (pendingFailure is not null)
                {
                    System.Runtime.ExceptionServices.ExceptionDispatchInfo.Capture(pendingFailure).Throw();
                }
            }
        }

        private void ThrowIfParentCancelled()
        {
            var parent = _cancelledParentToken?.Invoke();
            if (parent is { } token)
            {
                throw new OperationCanceledException(token);
            }
        }

        internal IEnumerable<StreamEvent> FinalUsageEvents()
        {
            if (_clean && !_sawAdapterUsage && _sawTerminalUsage && _usage is not null)
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
            _attemptPacing?.Detach();
            switch (adapterEvent)
            {
                case AdapterTextDelta textDelta:
                    foreach (var timing in MarkFirstContent()) yield return timing;

                    _text.Append(textDelta.Text);
                    yield return new TextDelta(textDelta.Text);
                    break;
                case AdapterReasoningDelta reasoning:
                    foreach (var timing in MarkFirstContent()) yield return timing;
                    yield return new ReasoningDelta(reasoning.Text);
                    break;
                case AdapterCitationDelta citation:
                    _citations.Add(citation.Citation);
                    yield return new CitationDelta(citation.Citation);
                    break;
                case AdapterServerToolDelta tool:
                    yield return new ServerToolDelta(tool.Kind, tool.Status, tool.Sources, tool.Output, tool.Detail);
                    break;
                case AdapterToolCallDelta toolDelta:
                    if (!_publicSdk)
                    {
                        break;
                    }
                    foreach (var timing in MarkFirstContent()) yield return timing;
                    if (!_toolCalls.TryGetValue(toolDelta.Index, out var buffer))
                    {
                        buffer = new ToolCallBuffer(toolDelta.Index);
                        _toolCalls.Add(toolDelta.Index, buffer);
                    }
                    buffer.Absorb(toolDelta);
                    yield return new ToolCallDelta(toolDelta.Index, toolDelta.CallId, toolDelta.Name, toolDelta.ArgumentsFragment);
                    break;
                case AdapterUsage usage:
                    _sawAdapterUsage = true;
                    _usage = OverlayUsage(_usage, usage.Usage, _publicSdk);
                    yield return new UsageUpdate(usage.Usage);
                    break;
                case AdapterFinal final:
                    _finishReason = final.FinishReason;
                    _sawTerminalUsage = final.Usage is not null;
                    _usage = OverlayUsage(_usage, final.Usage, _publicSdk);
                    _raw = _retainRaw ? final.Raw : null;
                    _providerPhases = final.Phases;
                    _logprobs = final.Logprobs;
                    _serverToolUses.Clear();
                    _serverToolUses.AddRange(final.ServerToolUses);
                    if (final.ServerToolUses.Count != 0)
                    {
                        var serverToolUses = new Dictionary<string, long>(StringComparer.Ordinal);
                        foreach (var use in final.ServerToolUses)
                        {
                            serverToolUses[use.Kind] = use.Uses;
                        }

                        _usage = (_usage ?? new Usage()) with { ServerToolUses = serverToolUses };
                    }
                    break;
            }
        }

        private IEnumerable<StreamEvent> MarkFirstContent()
        {
            if (_firstContent) yield break;
            _firstContent = true;
            _routeState.ContentEmitted = true;
            var firstTokenMilliseconds = _entryStopwatch.Elapsed.TotalMilliseconds;
            _firstTokenMilliseconds = firstTokenMilliseconds;
            _telemetry?.Emit(new FirstToken(_telemetry.RequestId, _target, firstTokenMilliseconds));
            yield return new TimingMark("first_token", firstTokenMilliseconds);
        }

        private IReadOnlyList<ToolCall> BuildToolCalls()
        {
            var calls = new List<ToolCall>(_toolCalls.Count);
            foreach (var (_, buffer) in _toolCalls.OrderBy(static item => item.Key)) calls.Add(buffer.Build(_warnings));
            return calls;
        }

        private sealed class ToolCallBuffer
        {
            private readonly int _index;
            private string? _callId;
            private string? _name;
            private readonly StringBuilder _arguments = new();
            internal ToolCallBuffer(int index) => _index = index;
            internal void Absorb(AdapterToolCallDelta delta)
            {
                if (!string.IsNullOrEmpty(delta.CallId)) _callId = delta.CallId;
                if (!string.IsNullOrEmpty(delta.Name)) _name = delta.Name;
                _arguments.Append(delta.ArgumentsFragment);
            }
            internal ToolCall Build(List<string> warnings)
            {
                var arguments = new JsonObject([]);
                var text = _arguments.ToString().Trim();
                if (text.Length > 0)
                {
                    try
                    {
                        if (JsonReader.ReadModern(text) is JsonObject objectArguments) arguments = objectArguments;
                        else warnings.Add($"tool call {_name ?? _index.ToString()} arguments were not a JSON object; using an empty argument object");
                    }
                    catch (FormatException)
                    {
                        warnings.Add($"tool call {_name ?? _index.ToString()} had unparseable arguments; using an empty argument object");
                    }
                }
                return new ToolCall(_callId ?? $"call_{_index}", _name ?? string.Empty, arguments);
            }
        }

        private sealed record ReadStep(bool Moved, AdapterEvent? Event, ProviderException? Error);
    }
}
