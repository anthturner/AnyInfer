using AnyInfer.Capabilities;
using AnyInfer.Events;
using AnyInfer.Internal;

namespace AnyInfer.Core;

/// <summary>Applies model-scoped rich-generation capability rules before adapter dispatch.</summary>
internal static class RichGenerationPolicy
{
    internal static bool Allows(ModelCapabilities? capabilities, Feature feature)
    {
        return capabilities is null ||
            capabilities.Features.Provenance is not (Provenance.Catalog or Provenance.Discovered or Provenance.Probed or Provenance.Override) ||
            capabilities.Features.Value.HasFlag(feature);
    }

    internal static void ValidateInputs(NormalizedRequest request, TargetMetadata metadata, ResolvedProvider resolved)
    {
        var required = request.Messages.SelectMany(static message => message.Content).Select(static part => part switch
        {
            ImagePart => Feature.Vision,
            DocumentPart => Feature.Document,
            AudioPart => Feature.AudioIn,
            VideoPart => Feature.VideoIn,
            _ => Feature.None,
        }).Aggregate(Feature.None, static (current, next) => current | next);
        if (required != Feature.None && !Allows(metadata.ResolvedCapabilities, required))
        {
            var available = metadata.ResolvedCapabilities?.Features.Value ?? Feature.None;
            var labels = new[]
            {
                (Feature.Vision, "vision"),
                (Feature.Document, "document"),
                (Feature.AudioIn, "audio_in"),
                (Feature.VideoIn, "video_in"),
            }
            .Where(item => required.HasFlag(item.Item1) && !available.HasFlag(item.Item1))
            .Select(static item => item.Item2);
            throw new UnsupportedInputException($"{resolved.Target} does not support attached {string.Join(", ", labels)} input", resolved.Target.ProviderId, hint: "choose a model whose capabilities include the required input modality");
        }

        if (request.ServerTools.Count == 0)
        {
            return;
        }
        var descriptor = resolved.Descriptor;
        var requested = request.ServerTools.Select(static tool => tool.Kind).ToHashSet(StringComparer.Ordinal);
        var unspeakable = requested.Where(kind => descriptor is null || !descriptor.ServerTools.Contains(kind)).OrderBy(static kind => kind, StringComparer.Ordinal).ToArray();
        if (unspeakable.Length > 0)
        {
            throw new UnsupportedInputException($"{resolved.Target.ProviderId} has no wire form for the requested server-side tool(s): {string.Join(", ", unspeakable)}", resolved.Target.ProviderId, hint: "choose a provider that runs these itself, or drop server_tools");
        }

        var requiredToolFeatures = new Dictionary<string, Feature>(StringComparer.Ordinal)
        {
            ["web_search"] = Feature.WebSearch,
            ["code_execution"] = Feature.CodeExecution,
        };
        var unavailable = requested
            .Where(kind => requiredToolFeatures.TryGetValue(kind, out var feature) && !Allows(metadata.ResolvedCapabilities, feature))
            .OrderBy(static kind => kind, StringComparer.Ordinal)
            .ToArray();
        if (unavailable.Length > 0)
        {
            throw new UnsupportedInputException($"{resolved.Target} cannot run the requested server-side tool(s): {string.Join(", ", unavailable)}", resolved.Target.ProviderId, hint: "choose a model whose capabilities include them, or drop server_tools");
        }
    }

    internal static void EmitDroppedParameters(NormalizedRequest request, TargetMetadata metadata, ResolvedProvider resolved, RequestTelemetry? telemetry)
    {
        if (telemetry is null)
        {
            return;
        }
        var dropped = new Dictionary<string, string>(StringComparer.Ordinal);
        void Add(string name, bool supplied, Feature feature)
        {
            if (supplied && !Allows(metadata.ResolvedCapabilities, feature))
            {
                var provider = resolved.Descriptor?.Id ?? resolved.Target.ProviderId;
                var scope = metadata.ResolvedCapabilities is null ? "models" : "model";
                var detail = name switch
                {
                    "reasoning" => $"{provider}'s {scope} does not support reasoning effort, so it was not sent",
                    "cite_documents" => $"{provider}'s {scope} does not attribute answers to supplied documents, so no citations were requested",
                    "logprobs" => $"{provider}'s {scope} does not report token log-probabilities, so none were requested",
                    _ => throw new ArgumentOutOfRangeException(nameof(name)),
                };
                dropped.TryAdd(name, detail);
            }
        }
        Add("reasoning", request.Reasoning is not null, Feature.Reasoning);
        Add("cite_documents", request.CiteDocuments, Feature.Citations);
        Add("logprobs", request.Logprobs is not null, Feature.Logprobs);
        if (resolved.Descriptor is { } descriptor)
        {
            var supplied = new Dictionary<string, object?>(StringComparer.Ordinal)
            {
                ["temperature"] = request.Sampling.Temperature,
                ["top_p"] = request.Sampling.TopP,
                ["max_output_tokens"] = request.Sampling.MaxOutputTokens,
                ["stop"] = request.Sampling.Stop is { Count: > 0 } stop ? stop : null,
                ["seed"] = request.Sampling.Seed,
                ["presence_penalty"] = request.Sampling.PresencePenalty,
                ["frequency_penalty"] = request.Sampling.FrequencyPenalty,
                ["logprobs"] = request.Logprobs,
                ["cite_documents"] = request.CiteDocuments ? true : null,
                ["server_tools.max_uses"] = request.ServerTools.Select(static tool => tool.MaxUses).FirstOrDefault(static uses => uses is not null),
                ["reasoning"] = request.Reasoning,
                ["tools"] = request.Tools.Count == 0 ? null : request.Tools,
            };
            foreach (var name in descriptor.IgnoredParameters)
            {
                if (supplied.TryGetValue(name, out var value) && value is not null)
                {
                    dropped.TryAdd(name, $"{descriptor.Id} accepts but ignores {name}");
                }
            }
        }
        foreach (var item in dropped)
        {
            telemetry.Emit(new ParameterDropped(telemetry.RequestId, resolved.Target, item.Key, item.Value));
        }
    }
}
