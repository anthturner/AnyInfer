using AnyInfer.Json;
using AnyInfer.Providers;
using AnyInfer.Schema;
using AnyInfer.Capabilities;

namespace AnyInfer.Core;

internal sealed record NormalizedRequest(
    IReadOnlyList<Message> Messages,
    IReadOnlyList<ToolSpec> Tools,
    string ToolChoice,
    Sampling Sampling,
    SchemaSpec? Schema,
    int RepairBudget,
    double? TimeoutS,
    int MaxResponseBytes,
    string? Reasoning,
    IReadOnlyDictionary<string, JsonObject> ProviderOptions,
    IReadOnlyDictionary<string, string> Metadata,
    int? Logprobs,
    bool CiteDocuments,
    IReadOnlyList<ServerToolSpec> ServerTools,
    bool Stream,
    SchemaExecutionProfile SchemaProfile,
    SchemaValidationOptions? SchemaValidation);

internal static class RequestNormalizer
{
    internal static NormalizedRequest Normalize(GenerationRequest request, bool allowTargetAliases = false, SchemaExecutionProfile schemaProfile = SchemaExecutionProfile.FrozenV0, SchemaValidationOptions? schemaValidation = null)
    {
        ArgumentNullException.ThrowIfNull(request);
        RequestAdmission.Validate(request, allowTargetAliases, schemaProfile);

        var messages = schemaProfile == SchemaExecutionProfile.FrozenV0
            ? request.Messages
                .Select(static message => new Message(
                    message.Role,
                    [new Text(string.Concat(message.Content.Cast<Text>().Select(static part => part.Value)))]))
                .ToArray()
            : request.Messages.Select(static message => new Message(message.Role, message.Content)).ToArray();
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
            request.Tools,
            request.ToolChoice,
            normalizedSampling,
            request.Schema,
            Math.Max(0, request.Repair?.MaxAttempts ?? 0),
            request.TimeoutS,
            request.MaxResponseBytes ?? 1_048_576,
            request.Reasoning,
            request.ProviderOptions,
            request.Metadata,
            request.Logprobs,
            request.CiteDocuments,
            request.ServerTools,
            request.Stream,
            schemaProfile,
            schemaValidation);
    }

    internal static WireRequest CreateWireRequest(
        NormalizedRequest normalized,
        ResolvedProvider resolved,
        IReadOnlyList<Message>? messages = null,
        IEnumerable<ToolSpec>? tools = null,
        string? toolChoice = null,
        IEnumerable<int>? cacheMarks = null,
        ModelCapabilities? capabilities = null)
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
                wireMessages = (normalized.SchemaProfile == SchemaExecutionProfile.ModernSdk ? SchemaPromptRenderer.InjectPromptModern(wireMessages, schema.JsonSchema) : SchemaPromptRenderer.InjectPrompt(wireMessages, schema.JsonSchema)).ToArray();
            }
        }

        return new WireRequest(
            resolved.Target.Model,
            wireMessages,
            normalized.Sampling,
            normalized.SchemaProfile == SchemaExecutionProfile.ModernSdk && mechanism is not ("grammar" or "json_schema") ? null : normalized.Schema?.JsonSchema,
            mechanism,
            normalized.Stream,
            normalized.TimeoutS ?? resolved.Settings.TimeoutS,
            normalized.MaxResponseBytes,
            normalized.SchemaProfile == SchemaExecutionProfile.ModernSdk ? normalized.Schema?.Name : normalized.Schema?.Name ?? "response",
            normalized.SchemaProfile == SchemaExecutionProfile.ModernSdk,
            tools ?? normalized.Tools,
            toolChoice ?? normalized.ToolChoice,
            cacheMarks,
            reasoningWire: resolved.Descriptor is null || normalized.Reasoning is null || !RichGenerationPolicy.Allows(capabilities, Feature.Reasoning)
                ? new JsonObject([])
                : resolved.Descriptor.ReasoningTranslator(normalized.Reasoning),
            serverTools: normalized.ServerTools,
            citeDocuments: normalized.CiteDocuments && RichGenerationPolicy.Allows(capabilities, Feature.Citations),
            logprobs: RichGenerationPolicy.Allows(capabilities, Feature.Logprobs) ? normalized.Logprobs : null,
            extraOptions: ProviderOptions(normalized.ProviderOptions, resolved.Target.ProviderId));
    }

    private static JsonObject ProviderOptions(IReadOnlyDictionary<string, JsonObject> options, string providerId)
    {
        var merged = new Dictionary<string, JsonValue>(StringComparer.Ordinal);
        if (options.TryGetValue("*", out var wildcard)) foreach (var item in wildcard.Properties) merged[item.Name] = item.Value;
        if (options.TryGetValue(providerId, out var specific)) foreach (var item in specific.Properties) merged[item.Name] = item.Value;
        return new JsonObject(merged.Select(static item => new JsonProperty(item.Key, item.Value)));
    }

    private static string SelectMechanism(StructuredOutputProfile capabilities) =>
        capabilities.Grammar ? "grammar" :
        capabilities.JsonSchema ? "json_schema" :
        capabilities.JsonMode ? "json_mode" :
        "prompt";
}
