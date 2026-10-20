using System.Runtime.ExceptionServices;
using AnyInfer.Capabilities;
using AnyInfer.Events;
using AnyInfer.Internal;
using AnyInfer.Json;
using AnyInfer.Providers;
using PeterO.Numbers;

namespace AnyInfer.Core;

/// <summary>Runs buffered embedding and reranking work without constructing generation streams.</summary>
internal static class RetrievalCore
{
    internal sealed class OwnedCallerDeadlineCancellationException : OperationCanceledException
    {
        internal OwnedCallerDeadlineCancellationException(CancellationToken callerIdentity)
            : base(callerIdentity)
        {
        }
    }

    private sealed record ChunkSlot<T>(
        int Index,
        int ItemCount,
        T? Result,
        IReadOnlyList<AttemptRecord> Attempts,
        Exception? Failure);

    internal sealed record EmbeddingOutcome(
        IReadOnlyList<EmbeddingVector> Vectors,
        ResolvedTarget Target,
        EmbeddingSpace Space,
        Usage Usage,
        Timing Timing,
        IReadOnlyList<AttemptRecord> Attempts,
        IReadOnlyList<string> Warnings,
        JsonValue? Raw);

    internal sealed record RerankOutcome(
        IReadOnlyList<RankedItem> Items,
        ResolvedTarget Target,
        Usage Usage,
        Timing Timing,
        IReadOnlyList<AttemptRecord> Attempts,
        IReadOnlyList<string> Warnings,
        JsonValue? Raw);

    internal static async Task<EmbeddingOutcome> EmbedAsync(
        EmbeddingRequest request,
        Route route,
        ProviderPool pool,
        TargetMetadataResolver resolver,
        RouteState health,
        IOperationClock clock,
        CapabilityStore capabilities,
        CancellationToken lifecycleToken,
        CancellationToken callerIdentity,
        Action<TelemetryEvent>? emit,
        string requestId,
        TimeProvider? timeProvider)
    {
        var attempts = new List<AttemptRecord>();
        var warnings = new List<string>();
        ProviderException? lastFailure = null;
        ResolvedTarget? firstTarget = null;
        for (var routePosition = 0; routePosition < route.Targets.Count; routePosition++)
        {
            var rawTarget = route.Targets[routePosition];
            lifecycleToken.ThrowIfCancellationRequested();
            var metadata = resolver.Resolve(rawTarget, TargetResolutionProfile.PublicSdk);
            emit?.Invoke(new TargetResolved(requestId, metadata.Target));
            firstTarget ??= metadata.Target;
            if (route.HealthGate && health.IsUnhealthy(metadata.Target, route.HealthTtlS))
            {
                attempts.Add(new AttemptRecord(metadata.Target, "skipped_unhealthy"));
                continue;
            }

            if (firstTarget is not null && !request.AllowIncompatibleFallback &&
                (firstTarget.ProviderId != metadata.Target.ProviderId || firstTarget.Model != metadata.Target.Model))
            {
                throw new ConfigException("Embedding fallback must keep the same provider and model unless explicitly allowed.", metadata.Target.ProviderId);
            }

            var resolved = pool.Materialize(metadata);
            var adapter = await pool.GetAdapterAsync(resolved.State, lifecycleToken, callerIdentity).ConfigureAwait(false);
            ValidateOperation(resolved, adapter, InferenceOperation.Embedding);
            if (adapter is not IEmbedsText embeddingAdapter)
            {
                throw new ConfigException("The selected provider does not implement embedding support.", resolved.Target.ProviderId);
            }

            var facts = capabilities.EmbeddingCapabilitiesFor(metadata.Descriptor, resolved.Target.ProviderId, resolved.Target.Model, pool.EffectiveLocality(metadata));
            AddIntentWarning(request.InputType, facts, resolved.Target, warnings);
            var limit = request.Batch.MaxItemsOverride ?? facts?.MaxBatchInputs;
            if (limit is null && request.Inputs.Count > 2048)
            {
                throw new ConfigException("The embedding request exceeds the operation's unknown 2048-input ceiling.", resolved.Target.ProviderId);
            }

            List<IReadOnlyList<string>> chunks = limit is null ? [request.Inputs] : Chunk(request.Inputs, limit.Value);
            if (chunks.Count > 1 && !request.Batch.AllowSplit)
            {
                throw new ConfigException("The embedding request exceeds the selected provider batch limit.", resolved.Target.ProviderId);
            }

            try
            {
                var batchStarted = clock.NowSeconds;
                var slots = await RunChunksAsync(
                    chunks,
                    request.Batch.MaxConcurrency,
                    lifecycleToken,
                    (inputs, index, chunkAttempts) => EmbedChunkAsync(embeddingAdapter, request, resolved, inputs, index, route, health, clock, lifecycleToken, callerIdentity, emit, requestId, chunkAttempts, timeProvider)).ConfigureAwait(false);
                RethrowNonProviderFailure(slots);
                if (FirstProviderFailure(slots) is { } providerFailure)
                {
                    if (chunks.Count > 1)
                    {
                        AppendBatchAttempts(attempts, slots, resolved.Target);
                        var batchFailures = BatchFailures(slots);
                        health.MarkFailed(resolved.Target);
                        emit?.Invoke(new RequestFailed(requestId, providerFailure.Snapshot()));
                        throw BatchFailureException(resolved.Target, attempts, batchFailures);
                    }

                    attempts.Add(new AttemptRecord(resolved.Target, "failed", providerFailure));
                    throw providerFailure;
                }
                attempts.AddRange(slots.SelectMany(static slot => slot.Attempts));
                var results = slots.Select(static slot => slot.Result!).ToArray();

                var vectors = new List<EmbeddingVector>();
                int? dimensions = null;
                EmbeddingSpace? space = null;
                for (var chunkIndex = 0; chunkIndex < results.Length; chunkIndex++)
                {
                    var result = results[chunkIndex];
                    var chunk = chunks[chunkIndex];
                    if (result.Vectors.Count == 0)
                    {
                        throw new ConfigException("The provider returned no embedding vectors.", resolved.Target.ProviderId);
                    }

                    if (result.Vectors.Count != chunk.Count)
                    {
                        throw new ConfigException(
                            $"provider '{resolved.Target.ProviderId}' returned {result.Vectors.Count} vectors for a batch of {chunk.Count} inputs",
                            resolved.Target.ProviderId);
                    }

                    foreach (var vector in result.Vectors)
                    {
                        if (vector.Count == 0 || vector.Any(static value => !double.IsFinite(value)))
                        {
                            throw new ConfigException("The provider returned a malformed embedding vector.", resolved.Target.ProviderId);
                        }

                        dimensions ??= vector.Count;
                        if (dimensions != vector.Count)
                        {
                            throw new ConfigException("The provider returned embedding vectors with inconsistent dimensions.", resolved.Target.ProviderId);
                        }

                        vectors.Add(new EmbeddingVector(vector));
                    }

                    var chunkSpace = new EmbeddingSpace(
                        resolved.Target.ProviderId,
                        result.Model ?? resolved.Target.Model,
                        dimensions: result.Dimensions ?? result.Vectors[0].Count,
                        normalized: result.Normalized);
                    if (space is not null && !space.Equals(chunkSpace))
                    {
                        throw new ConfigException("The provider reported inconsistent embedding spaces across the internal batches of one request.", resolved.Target.ProviderId);
                    }

                    space ??= chunkSpace;
                }

                if (vectors.Count != request.Inputs.Count)
                {
                    throw new ConfigException("The provider returned a different number of embedding vectors than requested.", resolved.Target.ProviderId);
                }

                var commonSpace = space ?? throw new ConfigException("The provider returned no embedding vectors.", resolved.Target.ProviderId);
                if (request.ExpectedSpace is not null && !commonSpace.CompatibleWith(request.ExpectedSpace))
                {
                    throw new ConfigException("The provider returned embeddings from an incompatible vector space.", resolved.Target.ProviderId);
                }

                if (firstTarget is not null &&
                    (firstTarget.ProviderId != resolved.Target.ProviderId || firstTarget.Model != resolved.Target.Model))
                {
                    warnings.Add($"embedding fallback served by {resolved.Target} could not be proven compatible with the route's primary target {firstTarget}; these vectors are not safely comparable with vectors from that target");
                }

                var usage = Usage.Sum(results.Select(static result => result.Usage ?? new Usage()));
                usage = PricingCalculator.WithOperationCost(usage, metadata.ResolvedCapabilities, InferenceOperation.Embedding);
                health.Clear(resolved.Target);
                var timing = chunks.Count == 1
                    ? attempts.Last(static attempt => attempt.Outcome == "ok").Timing ?? new Timing()
                    : new Timing(totalMs: (clock.NowSeconds - batchStarted) * 1000d);
                return new EmbeddingOutcome(vectors, resolved.Target, commonSpace, usage, timing, attempts, warnings, request.RetainRaw ? CombineRaw(results.Select(static result => result.Raw)) : null);
            }
            catch (ProviderException failure)
            {
                lastFailure = failure;
                health.MarkFailed(resolved.Target);
                if (routePosition + 1 < route.Targets.Count)
                {
                    emit?.Invoke(new FallbackTriggered(requestId, resolved.Target, route.Targets[routePosition + 1], failure.Snapshot()));
                }
            }
        }

        if (lastFailure is not null)
        {
            emit?.Invoke(new RequestFailed(requestId, lastFailure.Snapshot()));
        }

        throw new AllTargetsFailedException("Every embedding target failed.", attempts, detail: lastFailure?.Detail, nativeInner: lastFailure);
    }

    internal static async Task<RerankOutcome> RerankAsync(
        RerankRequest request,
        Route route,
        ProviderPool pool,
        TargetMetadataResolver resolver,
        RouteState health,
        IOperationClock clock,
        CapabilityStore capabilities,
        CancellationToken lifecycleToken,
        CancellationToken callerIdentity,
        Action<TelemetryEvent>? emit,
        string requestId,
        TimeProvider? timeProvider)
    {
        var attempts = new List<AttemptRecord>();
        var warnings = new List<string>();
        ProviderException? lastFailure = null;
        for (var routePosition = 0; routePosition < route.Targets.Count; routePosition++)
        {
            var rawTarget = route.Targets[routePosition];
            lifecycleToken.ThrowIfCancellationRequested();
            var metadata = resolver.Resolve(rawTarget, TargetResolutionProfile.PublicSdk);
            emit?.Invoke(new TargetResolved(requestId, metadata.Target));
            if (route.HealthGate && health.IsUnhealthy(metadata.Target, route.HealthTtlS))
            {
                attempts.Add(new AttemptRecord(metadata.Target, "skipped_unhealthy"));
                continue;
            }

            var resolved = pool.Materialize(metadata);
            var adapter = await pool.GetAdapterAsync(resolved.State, lifecycleToken, callerIdentity).ConfigureAwait(false);
            ValidateOperation(resolved, adapter, InferenceOperation.Rerank);
            if (adapter is not IReranksText rerankAdapter)
            {
                throw new ConfigException("The selected provider does not implement reranking support.", resolved.Target.ProviderId);
            }

            var facts = capabilities.RerankCapabilitiesFor(metadata.Descriptor, resolved.Target.Model);
            var limit = request.Batch.MaxItemsOverride ?? facts?.MaxDocuments;
            if (limit is null && request.Documents.Count > 1000)
            {
                throw new ConfigException("The rerank request exceeds the operation's unknown 1000-document ceiling.", resolved.Target.ProviderId);
            }

            List<IReadOnlyList<RerankDocument>> chunks = limit is null ? [request.Documents] : Chunk(request.Documents, limit.Value);
            if (chunks.Count > 1 && (!request.Batch.AllowSplit || !request.Batch.RerankCrossBatch))
            {
                throw new ConfigException("The rerank request exceeds the selected provider batch limit and cross-batch reranking is disabled.", resolved.Target.ProviderId);
            }

            try
            {
                var batchStarted = clock.NowSeconds;
                if (chunks.Count > 1)
                {
                    var warning = $"rerank request was split into {chunks.Count} batches of at most {limit} documents for {resolved.Target}; scores are comparable only within each batch — this result concatenates chunk-local rankings and is not a provider-certified global ordering";
                    if (request.TopN is not null)
                    {
                        warning += $"; top_n={request.TopN} was applied within each batch, not globally";
                    }

                    warnings.Add(warning);
                }

                var slots = await RunChunksAsync(
                    chunks,
                    request.Batch.MaxConcurrency,
                    lifecycleToken,
                    (documents, index, chunkAttempts) => RerankChunkAsync(rerankAdapter, request, resolved, documents, index, route, health, clock, lifecycleToken, callerIdentity, emit, requestId, chunkAttempts, timeProvider)).ConfigureAwait(false);
                RethrowNonProviderFailure(slots);
                if (FirstProviderFailure(slots) is { } providerFailure)
                {
                    if (chunks.Count > 1)
                    {
                        AppendBatchAttempts(attempts, slots, resolved.Target);
                        var batchFailures = BatchFailures(slots);
                        health.MarkFailed(resolved.Target);
                        emit?.Invoke(new RequestFailed(requestId, providerFailure.Snapshot()));
                        throw BatchFailureException(resolved.Target, attempts, batchFailures);
                    }

                    attempts.Add(new AttemptRecord(resolved.Target, "failed", providerFailure));
                    throw providerFailure;
                }
                attempts.AddRange(slots.SelectMany(static slot => slot.Attempts));
                var responses = slots.Select((slot, index) => (Documents: chunks[index], Result: slot.Result!)).ToArray();

                var items = new List<RankedItem>();
                foreach (var response in responses)
                {
                    var allowed = response.Documents.Select(document => OriginalIndex(request.Documents, document)).ToHashSet();
                    var seen = new HashSet<int>();
                    foreach (var item in response.Result.Items)
                    {
                        if (!double.IsFinite(item.Score) || !allowed.Contains(item.Index) || !seen.Add(item.Index))
                        {
                            throw new ConfigException("The provider returned an invalid rerank item.", resolved.Target.ProviderId);
                        }

                        var document = request.Documents[item.Index];
                        items.Add(new RankedItem(item.Index, document.Id, item.Score, request.ReturnDocuments ? document.Text : null));
                    }
                }

                var usage = Usage.Sum(responses.Select(static response => response.Result.Usage ?? new Usage()));
                usage = PricingCalculator.WithOperationCost(usage, metadata.ResolvedCapabilities, InferenceOperation.Rerank);
                health.Clear(resolved.Target);
                var timing = chunks.Count == 1
                    ? attempts.Last(static attempt => attempt.Outcome == "ok").Timing ?? new Timing()
                    : new Timing(totalMs: (clock.NowSeconds - batchStarted) * 1000d);
                return new RerankOutcome(items, resolved.Target, usage, timing, attempts, warnings, request.RetainRaw ? CombineRaw(responses.Select(static response => response.Result.Raw)) : null);
            }
            catch (ProviderException failure)
            {
                lastFailure = failure;
                health.MarkFailed(resolved.Target);
                if (routePosition + 1 < route.Targets.Count)
                {
                    emit?.Invoke(new FallbackTriggered(requestId, resolved.Target, route.Targets[routePosition + 1], failure.Snapshot()));
                }
            }
        }

        if (lastFailure is not null)
        {
            emit?.Invoke(new RequestFailed(requestId, lastFailure.Snapshot()));
        }

        throw new AllTargetsFailedException("Every rerank target failed.", attempts, detail: lastFailure?.Detail, nativeInner: lastFailure);
    }

    private static async Task<EmbeddingWireResult> EmbedChunkAsync(
        IEmbedsText adapter, EmbeddingRequest request, ResolvedProvider resolved, IReadOnlyList<string> inputs, int batchIndex,
        Route route, RouteState health, IOperationClock clock, CancellationToken lifecycleToken, CancellationToken callerIdentity,
        Action<TelemetryEvent>? emit, string requestId, List<AttemptRecord> attempts, TimeProvider? timeProvider)
    {
        var wire = new EmbeddingWireRequest(resolved.Target.Model, inputs, request.InputType, request.Dimensions,
            request.EffectiveTimeoutS, request.MaxResponseBytes, ExtraOptions(request.ProviderOptions, resolved.Target.ProviderId));
        return await InvokeWithRetryAsync(
            token => adapter.EmbedAsync(wire, token), static result => result.Usage, static result => result.Phases, resolved.Target, route, health, clock, lifecycleToken, callerIdentity, emit, requestId, attempts,
            request.EffectiveTimeoutS, timeProvider, "embedding").ConfigureAwait(false);
    }

    private static async Task<RerankWireResult> RerankChunkAsync(
        IReranksText adapter, RerankRequest request, ResolvedProvider resolved, IReadOnlyList<RerankDocument> documents, int batchIndex,
        Route route, RouteState health, IOperationClock clock, CancellationToken lifecycleToken, CancellationToken callerIdentity,
        Action<TelemetryEvent>? emit, string requestId, List<AttemptRecord> attempts, TimeProvider? timeProvider)
    {
        var wire = new RerankWireRequest(resolved.Target.Model, request.Query,
            documents.Select(document => new RerankWireDocument(OriginalIndex(request.Documents, document), document.Text)), request.TopN,
            request.EffectiveTimeoutS, request.MaxResponseBytes, ExtraOptions(request.ProviderOptions, resolved.Target.ProviderId));
        return await InvokeWithRetryAsync(
            token => adapter.RerankAsync(wire, token), static result => result.Usage, null, resolved.Target, route, health, clock, lifecycleToken, callerIdentity, emit, requestId, attempts,
            request.EffectiveTimeoutS, timeProvider, "rerank").ConfigureAwait(false);
    }

    private static async Task<T> InvokeWithRetryAsync<T>(
        Func<CancellationToken, ValueTask<T>> invoke, Func<T, Usage?> usage, Func<T, IReadOnlyDictionary<string, double>>? phases, ResolvedTarget target, Route route, RouteState health, IOperationClock clock,
        CancellationToken lifecycleToken, CancellationToken callerIdentity, Action<TelemetryEvent>? emit, string requestId,
        List<AttemptRecord> attempts, double timeoutS, TimeProvider? timeProvider, string operation)
    {
        ProviderException? last = null;
        for (var attempt = 1; attempt <= route.Retry.MaxAttempts; attempt++)
        {
            lifecycleToken.ThrowIfCancellationRequested();
            emit?.Invoke(new AttemptStarted(requestId, target, attempt));
            var started = clock.NowSeconds;
            Exception? sourceFailure = null;
            BufferedOperationDeadlineScope? deadline = null;
            Task<T>? providerTask = null;
            var invocationDeadlineToken = default(CancellationToken);
            try
            {
                deadline = new BufferedOperationDeadlineScope(timeoutS, lifecycleToken, callerIdentity, timeProvider);
                invocationDeadlineToken = deadline.Token;
                providerTask = invoke(deadline.Token).AsTask();
                var result = await providerTask.WaitAsync(deadline.Token).ConfigureAwait(false);
                var timing = new Timing(startedAt: started, totalMs: (clock.NowSeconds - started) * 1000d, phases: phases?.Invoke(result));
                attempts.Add(new AttemptRecord(target, "ok", timing: timing));
                emit?.Invoke(new AttemptCompleted(requestId, target, usage(result) ?? new Usage(), timing, "stop"));
                return result;
            }
            catch (OperationCanceledException exception) when (
                deadline?.IsExpired == true &&
                exception.CancellationToken == deadline.Token &&
                !callerIdentity.IsCancellationRequested &&
                !lifecycleToken.IsCancellationRequested)
            {
                sourceFailure = new ProviderException("The provider operation exceeded its configured timeout.", "timeout", true, operation, provider: target.ProviderId, nativeInner: exception);
            }
            catch (Exception exception)
            {
                sourceFailure = exception;
            }
            finally
            {
                if (providerTask is not null)
                {
                    try
                    {
                        await providerTask.ConfigureAwait(false);
                    }
                    catch (Exception providerFailure) when (ReplaceTimeoutWithProvider(sourceFailure, providerFailure, deadline!.Token))
                    {
                        sourceFailure = providerFailure;
                    }
                    catch
                    {
                        // A prior provider/body failure remains authoritative.
                    }
                }
                if (deadline is not null)
                {
                    await deadline.DisposeAsync().ConfigureAwait(false);
                    if (sourceFailure is null && deadline.DeferredFailure is { } deferred)
                    {
                        ExceptionDispatchInfo.Capture(deferred).Throw();
                    }
                }
            }

            if (sourceFailure is not ProviderException)
            {
                if (sourceFailure is OperationCanceledException cancellation &&
                    cancellation.CancellationToken == invocationDeadlineToken &&
                    callerIdentity.IsCancellationRequested)
                {
                    throw new OwnedCallerDeadlineCancellationException(callerIdentity);
                }

                ExceptionDispatchInfo.Capture(sourceFailure!).Throw();
            }

            var failure = (ProviderException)sourceFailure!;
            last = failure;
            var timingFailure = new Timing(startedAt: started, totalMs: (clock.NowSeconds - started) * 1000d);
            var retry = failure.Retryable && attempt < route.Retry.MaxAttempts;
            attempts.Add(new AttemptRecord(target, retry ? "retried" : "failed", failure, timingFailure));
            if (!retry)
            {
                throw failure;
            }

            var delay = RouteState.BackoffSeconds(route.Retry, attempt, failure.RetryAfterS);
            emit?.Invoke(new RetryScheduled(requestId, target, attempt, delay, failure.Snapshot()));
            await clock.DelayAsync(delay, lifecycleToken).ConfigureAwait(false);
        }

        throw (Exception?)last ?? new InvalidOperationException("A retrieval retry loop completed without an outcome.");
    }

    private static async Task<IReadOnlyList<ChunkSlot<T>>> RunChunksAsync<TItem, T>(
        IReadOnlyList<IReadOnlyList<TItem>> chunks,
        int maxConcurrency,
        CancellationToken lifecycleToken,
        Func<IReadOnlyList<TItem>, int, List<AttemptRecord>, Task<T>> invoke)
    {
        using var slots = new SemaphoreSlim(Math.Min(maxConcurrency, chunks.Count));
        var workers = chunks.Select((items, index) => RunChunkAsync(items, index, slots, lifecycleToken, invoke)).ToArray();
        await Task.WhenAll(workers).ConfigureAwait(false);
        return workers.Select(static worker => worker.Result).OrderBy(static slot => slot.Index).ToArray();
    }

    private static bool ReplaceTimeoutWithProvider(Exception? sourceFailure, Exception providerFailure, CancellationToken deadlineToken)
    {
        if (sourceFailure is null)
        {
            return true;
        }

        return sourceFailure is ProviderException { Category: "timeout" } &&
            (providerFailure is not OperationCanceledException cancellation || cancellation.CancellationToken != deadlineToken);
    }

    private static async Task<ChunkSlot<T>> RunChunkAsync<TItem, T>(
        IReadOnlyList<TItem> items,
        int index,
        SemaphoreSlim slots,
        CancellationToken lifecycleToken,
        Func<IReadOnlyList<TItem>, int, List<AttemptRecord>, Task<T>> invoke)
    {
        var attempts = new List<AttemptRecord>();
        var entered = false;
        try
        {
            await slots.WaitAsync(lifecycleToken).ConfigureAwait(false);
            entered = true;
            var result = await invoke(items, index, attempts).ConfigureAwait(false);
            return new ChunkSlot<T>(index, items.Count, result, attempts, null);
        }
        catch (Exception failure)
        {
            return new ChunkSlot<T>(index, items.Count, default, attempts, failure);
        }
        finally
        {
            if (entered)
            {
                slots.Release();
            }
        }
    }

    private static IReadOnlyList<BatchFailure> BatchFailures<T>(IReadOnlyList<ChunkSlot<T>> slots) =>
        slots.Select(slot => new BatchFailure(
            slot.Index,
            slot.ItemCount,
            slot.Failure is null,
            slot.Failure is ProviderException provider ? provider.Detail : null)).ToArray();

    private static void AppendBatchAttempts<T>(List<AttemptRecord> attempts, IReadOnlyList<ChunkSlot<T>> slots, ResolvedTarget target)
    {
        foreach (var slot in slots)
        {
            if (slot.Failure is ProviderException failure)
            {
                attempts.Add(new AttemptRecord(target, "failed", failure));
            }
            else
            {
                attempts.AddRange(slot.Attempts);
            }
        }
    }

    private static AllTargetsFailedException BatchFailureException(
        ResolvedTarget target,
        IReadOnlyList<AttemptRecord> attempts,
        IReadOnlyList<BatchFailure> batchFailures)
    {
        var failed = batchFailures.Count(static failure => !failure.Succeeded);
        return new AllTargetsFailedException(
            $"{failed} of {batchFailures.Count} internal batches failed for {target}",
            attempts,
            hint: "batched requests are all-or-error; batch_failures records every chunk's outcome, including the spend of the ones that succeeded",
            batchFailures: batchFailures);
    }

    private static void RethrowNonProviderFailure<T>(IReadOnlyList<ChunkSlot<T>> slots)
    {
        foreach (var slot in slots)
        {
            if (slot.Failure is not null and not ProviderException)
            {
                ExceptionDispatchInfo.Capture(slot.Failure).Throw();
            }
        }

    }

    private static ProviderException? FirstProviderFailure<T>(IReadOnlyList<ChunkSlot<T>> slots) =>
        slots.Select(static slot => slot.Failure).OfType<ProviderException>().FirstOrDefault();

    private static void ValidateOperation(ResolvedProvider resolved, IAsyncDisposable adapter, InferenceOperation operation)
    {
        if (resolved.Descriptor is { } descriptor && !descriptor.Operations.Contains(operation))
        {
            throw new ConfigException($"The selected provider does not declare {operation.ToString().ToLowerInvariant()} support.", resolved.Target.ProviderId);
        }

        var supported = operation switch
        {
            InferenceOperation.Embedding => adapter is IEmbedsText,
            InferenceOperation.Rerank => adapter is IReranksText,
            _ => false,
        };
        if (!supported)
        {
            throw new ConfigException($"The selected provider does not implement {operation.ToString().ToLowerInvariant()} support.", resolved.Target.ProviderId);
        }
    }

    internal static void EnforceEmbeddingSpend(
        EmbeddingRequest request,
        ModelCapabilities? capabilities,
        ResolvedTarget target,
        string requestId,
        SpendPolicy? policy,
        SpendLedger? ledger,
        ITokenEstimator? estimator)
    {
        if (policy is not { Active: true })
        {
            return;
        }

        var counter = estimator ?? new HeuristicTokenEstimator();
        long tokens = 0;
        foreach (var input in request.Inputs)
        {
            tokens = checked(tokens + (counter.Estimate(input) ?? throw new InvalidOperationException("Token estimator returned null.")).Tokens);
        }

        var estimate = PricingCalculator.ComputeOperationCost(new Usage(InputTokens: tokens), capabilities, InferenceOperation.Embedding);
        EnforceSpend(target, requestId, estimate, policy, ledger);
    }

    internal static void EnforceUnknownSpend(ResolvedTarget target, string requestId, SpendPolicy? policy, SpendLedger? ledger)
    {
        if (policy is { Active: true })
        {
            EnforceSpend(target, requestId, estimate: null, policy, ledger);
        }
    }

    private static void EnforceSpend(ResolvedTarget target, string requestId, EDecimal? estimate, SpendPolicy policy, SpendLedger? ledger)
    {
        var activeLedger = ledger ?? throw new InvalidOperationException("An active spend policy requires a spend ledger.");
        var spent = activeLedger.Totals().Cost;
        if (estimate is null)
        {
            if (policy.OnUnknown == "refuse")
            {
                throw new SpendLimitException(
                    $"the cost of a request to {target} cannot be estimated",
                    UnknownSpendLimit(policy),
                    spent,
                    hint: "this target has no trusted pricing; set onUnknown='allow' to send it anyway, or supply pricing as a capability override");
            }

            return;
        }

        if (policy.MaxRequestUsd is { } requestLimit && AccountingDecimal.Compare(estimate, requestLimit) > 0)
        {
            throw new SpendLimitException(
                $"a request to {target} could cost {estimate}, above the per-request ceiling of {requestLimit}",
                requestLimit, spent, estimate,
                "shorten the input, or raise max_request_usd");
        }

        if (policy.MaxTotalUsd is not { } totalLimit)
        {
            return;
        }

        var reservation = activeLedger.Reserve(requestId, estimate, totalLimit);
        if (!reservation.Accepted)
        {
            throw new SpendLimitException(
                $"this client has spent {reservation.Spent}, reserved {reservation.Reserved}, and the next request could cost {estimate}, above the ceiling of {totalLimit}",
                totalLimit, reservation.Spent, estimate,
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

    private static IReadOnlyDictionary<string, JsonValue> ExtraOptions(
        IReadOnlyDictionary<string, IReadOnlyDictionary<string, JsonValue>> values,
        string providerId) =>
        values.TryGetValue(providerId, out var selected)
            ? selected
            : new Dictionary<string, JsonValue>();

    private static List<IReadOnlyList<T>> Chunk<T>(IReadOnlyList<T> values, int limit)
    {
        if (limit <= 0)
        {
            throw new ConfigException("The provider declared an invalid batch limit.");
        }

        var chunks = new List<IReadOnlyList<T>>();
        for (var index = 0; index < values.Count; index += limit)
        {
            chunks.Add(Array.AsReadOnly(values.Skip(index).Take(Math.Min(limit, values.Count - index)).ToArray()));
        }

        return chunks;
    }

    private static JsonValue? CombineRaw(IEnumerable<JsonValue?> values)
    {
        var snapshot = values.ToArray();
        return snapshot.Length == 1
            ? snapshot[0]
            : new JsonArray(snapshot.Select(static value => value ?? JsonNull.Instance));
    }

    private static int OriginalIndex(IReadOnlyList<RerankDocument> documents, RerankDocument document)
    {
        for (var index = 0; index < documents.Count; index++)
        {
            if (ReferenceEquals(documents[index], document))
            {
                return index;
            }
        }

        throw new InvalidOperationException("The rerank batch did not preserve its source document identity.");
    }
    private static void AddIntentWarning(
        EmbeddingInputIntent? inputType,
        EmbeddingCapabilities? facts,
        ResolvedTarget target,
        List<string> warnings)
    {
        if (inputType is null || facts is null)
        {
            return;
        }

        var spelling = inputType.Value.ToString().ToLowerInvariant();
        if (facts.InputIntents.Count == 0)
        {
            warnings.Add($"{target} does not distinguish embedding input intents; input_type='{spelling}' has no effect on this target");
        }
        else if (!facts.InputIntents.Contains(inputType.Value))
        {
            var supported = string.Join(", ", facts.InputIntents.Select(static value => value.ToString().ToLowerInvariant()));
            warnings.Add($"{target} does not support input_type='{spelling}' (supported: {supported}); the provider's own handling applies");
        }
    }
}
