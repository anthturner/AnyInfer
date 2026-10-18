using AnyInfer.Json;
using AnyInfer.Providers;
using AnyInfer.Schema;

namespace AnyInfer.Core;

internal sealed record NormalizedRequest(
    IReadOnlyList<Message> Messages,
    Sampling Sampling,
    JsonValue? Schema,
    int RepairBudget,
    double? TimeoutS,
    int MaxResponseBytes,
    bool Stream);

internal static class RequestNormalizer
{
    internal static NormalizedRequest Normalize(GenerationRequest request, bool allowTargetAliases = false)
    {
        ArgumentNullException.ThrowIfNull(request);
        RequestAdmission.Validate(request, allowTargetAliases);

        var messages = request.Messages
            .Select(static message => new Message(
                message.Role,
                [new Text(string.Concat(message.Content.Cast<Text>().Select(static part => part.Value)))]))
            .ToArray();
        var sourceSampling = request.Sampling;
        var normalizedSampling = new Sampling(
            temperature: sourceSampling?.Temperature,
            topP: sourceSampling?.TopP,
            maxOutputTokens: sourceSampling?.MaxOutputTokens,
            stop: sourceSampling?.Stop is { Count: > 0 } stop ? stop : null,
            seed: sourceSampling?.Seed,
            presencePenalty: sourceSampling?.PresencePenalty,
            frequencyPenalty: sourceSampling?.FrequencyPenalty);

        return new NormalizedRequest(
            Array.AsReadOnly(messages),
            normalizedSampling,
            request.Schema,
            Math.Max(0, request.Repair?.MaxAttempts ?? 0),
            request.TimeoutS,
            request.MaxResponseBytes ?? 1_048_576,
            request.Stream);
    }

    internal static WireRequest CreateWireRequest(
        NormalizedRequest normalized,
        ResolvedProvider resolved,
        IReadOnlyList<Message>? messages = null)
    {
        ArgumentNullException.ThrowIfNull(normalized);
        ArgumentNullException.ThrowIfNull(resolved);
        var callerMessages = messages ?? normalized.Messages;
        var wireMessages = callerMessages
            .Select(static message => new Message(message.Role, message.Content))
            .ToArray();
        string? mechanism = null;
        if (normalized.Schema is { } schema)
        {
            mechanism = SelectMechanism(resolved.Capabilities);
            if (mechanism is "prompt" or "json_mode")
            {
                wireMessages = SchemaPromptRenderer.InjectPrompt(wireMessages, schema).ToArray();
            }
        }

        return new WireRequest(
            resolved.Target.Model,
            wireMessages,
            normalized.Sampling,
            normalized.Schema,
            mechanism,
            normalized.Stream,
            normalized.TimeoutS ?? resolved.Settings.TimeoutS,
            normalized.MaxResponseBytes);
    }

    private static string SelectMechanism(StructuredOutputProfile capabilities) =>
        capabilities.Grammar ? "grammar" :
        capabilities.JsonSchema ? "json_schema" :
        capabilities.JsonMode ? "json_mode" :
        "prompt";
}
