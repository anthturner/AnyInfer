using AnyInfer.Manifest;

namespace AnyInfer.Core;

/// <summary>Builds the content-free terminal manifest for one buffered retrieval operation.</summary>
internal static class OperationManifestBuilder
{
    internal static RunManifest Build(
        string requestId,
        string operation,
        Route route,
        ResolvedTarget target,
        Usage usage,
        Timing timing,
        IReadOnlyList<AttemptRecord> attempts,
        IReadOnlyList<string> warnings,
        EmbeddingSpace? embeddingSpace = null)
    {
        ArgumentNullException.ThrowIfNull(requestId);
        ArgumentNullException.ThrowIfNull(operation);
        ArgumentNullException.ThrowIfNull(route);
        ArgumentNullException.ThrowIfNull(target);
        ArgumentNullException.ThrowIfNull(usage);
        ArgumentNullException.ThrowIfNull(timing);

        var facets = attempts.Select(attempt => new AttemptFacet(
            attempt.Target?.ToString() ?? "",
            outcome: attempt.Outcome,
            error: attempt.Error?.Snapshot(),
            totalMs: attempt.Timing?.TotalMs)).ToArray();
        return new RunManifest(
            format: ManifestUtilities.Format,
            anyinferVersion: global::AnyInfer.Internal.AnyInferVersion.Value,
            requestId: requestId,
            complete: true,
            route: new RouteFacet(
                route.Targets,
                target.ToString(),
                attempts.Select(attempt => new RouteStep(
                    attempt.Target?.ToString() ?? "",
                    attempt.Outcome,
                    attempt.Error?.Snapshot().Detail ?? ""))),
            attempts: facets,
            usage: new UsageFacet(
                inputTokens: usage.InputTokens,
                outputTokens: usage.OutputTokens,
                totalTokens: usage.TotalTokens,
                cacheReadTokens: usage.CacheReadTokens,
                cacheWriteTokens: usage.CacheWriteTokens,
                reasoningTokens: usage.ReasoningTokens,
                costUsd: usage.CostUsd?.ToString(),
                searchUnits: usage.SearchUnits),
            timing: new TimingFacet(totalMs: timing.TotalMs, phases: timing.Phases),
            notes: warnings,
            operation: operation,
            embeddingSpace: embeddingSpace);
    }
}
