using AnyInfer.Json;
using AnyInfer.Providers;

namespace AnyInfer.Capabilities;

/// <summary>Builds pure prompt-cache recommendations from a request and selected target facts.</summary>
public static class CachePlanning
{
    /// <summary>Segment sentinel for tool declarations.</summary>
    public const int ToolsSegment = -2;

    /// <summary>Segment sentinel for the joined system block.</summary>
    public const int SystemSegment = -1;

    /// <summary>Plans prompt-cache placement without dispatching, mutating a request, or performing I/O.</summary>
    public static CachePlan Plan(
        GenerationRequest request,
        CachePolicy? policy,
        ModelCapabilities capabilities,
        ProviderDescriptor descriptor,
        ITokenEstimator estimator)
    {
        ArgumentNullException.ThrowIfNull(request);
        ArgumentNullException.ThrowIfNull(capabilities);
        ArgumentNullException.ThrowIfNull(descriptor);
        ArgumentNullException.ThrowIfNull(estimator);

        if (policy is null || !policy.Active)
        {
            return new CachePlan();
        }

        var mechanism = descriptor.CacheMechanism;
        if (mechanism is null)
        {
            return new CachePlan(reasons: ["the target declares no prompt-cache mechanism"]);
        }

        if (mechanism == CacheMechanism.Explicit &&
            (capabilities.Features.Value & Feature.CachePlacement) == 0)
        {
            return new CachePlan(reasons: ["the target's capabilities do not include cache placement"]);
        }

        return mechanism == CacheMechanism.Implicit
            ? PlanImplicit(request, policy, estimator)
            : PlanExplicit(request, policy, descriptor, estimator);
    }

    private static CachePlan PlanImplicit(
        GenerationRequest request,
        CachePolicy policy,
        ITokenEstimator estimator)
    {
        long estimated = 0;
        if (policy.IncludeSystem)
        {
            estimated = checked(estimated + SystemTokens(request, estimator));
        }

        if (policy.IncludeTools)
        {
            estimated = checked(estimated + ToolsTokens(request, estimator));
        }

        var lastStable = LastStableMessage(request);
        if (lastStable is not null)
        {
            estimated = checked(estimated + StablePrefixTokens(request, estimator, lastStable.Value));
        }

        return new CachePlan(
            CacheMechanism.Implicit,
            estimatedCacheableTokens: estimated,
            reasons: ["the target caches stable prefixes without being asked"]);
    }

    private static CachePlan PlanExplicit(
        GenerationRequest request,
        CachePolicy policy,
        ProviderDescriptor descriptor,
        ITokenEstimator estimator)
    {
        var floor = Math.Max(policy.MinSegmentTokens, descriptor.CacheMinTokens);
        var budget = Math.Min(policy.MaxMarks, descriptor.CacheMaxMarks == 0
            ? policy.MaxMarks
            : descriptor.CacheMaxMarks);
        var reasons = new List<string>();
        var candidates = new List<CacheMark>();

        if (policy.IncludeTools && request.Tools.Count > 0)
        {
            candidates.Add(new CacheMark(ToolsSegment, ToolsTokens(request, estimator)));
        }

        if (policy.IncludeSystem)
        {
            var systemTokens = SystemTokens(request, estimator);
            if (systemTokens != 0)
            {
                candidates.Add(new CacheMark(SystemSegment, systemTokens));
            }
        }

        var lastStable = LastStableMessage(request);
        if (lastStable is not null)
        {
            var prefixTokens = StablePrefixTokens(request, estimator, lastStable.Value);
            if (prefixTokens != 0)
            {
                candidates.Add(new CacheMark(lastStable.Value, prefixTokens));
            }
        }

        var worthwhile = candidates.Where(candidate => candidate.EstimatedTokens >= floor).ToArray();
        if (worthwhile.Length < candidates.Count)
        {
            reasons.Add($"segments under {floor} tokens are not worth a mark");
        }

        if (worthwhile.Length == 0)
        {
            return new CachePlan(reasons: reasons.Count == 0
                ? ["nothing large enough to cache"]
                : reasons);
        }

        var chosen = worthwhile.OrderByDescending(static mark => mark.EstimatedTokens).ToArray();
        if (chosen.Length > budget)
        {
            reasons.Add($"the target accepts at most {budget} marks");
            chosen = chosen[..budget];
        }

        var ordered = chosen.OrderBy(static mark => mark.Segment).ToArray();
        long estimated = 0;
        foreach (var mark in ordered)
        {
            estimated = checked(estimated + mark.EstimatedTokens);
        }

        return new CachePlan(
            CacheMechanism.Explicit,
            ordered,
            estimated,
            reasons);
    }

    private static long SystemTokens(GenerationRequest request, ITokenEstimator estimator)
    {
        var text = string.Join("\n", request.Messages
            .Where(static message => string.Equals(message.Role, "system", StringComparison.Ordinal))
            .Select(static message => string.Concat(message.Content.OfType<Text>().Select(static part => part.Value))));
        return text.Length == 0 ? 0 : Estimate(estimator, text);
    }

    private static long ToolsTokens(GenerationRequest request, ITokenEstimator estimator)
    {
        if (request.Tools.Count == 0)
        {
            return 0;
        }

        var declarations = new JsonArray(request.Tools.Select(static tool => new JsonObject(
        [
            new JsonProperty("name", new JsonString(tool.Name)),
            new JsonProperty("description", new JsonString(tool.Description)),
            new JsonProperty("parameters", tool.Parameters),
        ])));
        return Estimate(estimator, JsonWriter.WriteAccounting(declarations, indent: null));
    }

    private static long StablePrefixTokens(
        GenerationRequest request,
        ITokenEstimator estimator,
        int lastStable)
    {
        long total = 0;
        for (var index = 0; index <= lastStable; index++)
        {
            var message = request.Messages[index];
            if (!string.Equals(message.Role, "system", StringComparison.Ordinal))
            {
                total = checked(total + Estimate(estimator,
                    string.Concat(message.Content.OfType<Text>().Select(static part => part.Value))));
            }
        }
        return total;
    }

    private static int? LastStableMessage(GenerationRequest request)
    {
        var nonSystem = request.Messages
            .Select(static (message, index) => (message, index))
            .Where(static item => !string.Equals(item.message.Role, "system", StringComparison.Ordinal))
            .Select(static item => item.index)
            .ToArray();
        return nonSystem.Length < 2 ? null : nonSystem[^2];
    }

    private static long Estimate(ITokenEstimator estimator, string text)
    {
        var estimate = estimator.Estimate(text) ?? throw new InvalidOperationException("Token estimator returned null.");
        return estimate.Tokens;
    }
}
