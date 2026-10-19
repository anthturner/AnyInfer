using System.Numerics;
using AnyInfer.Json;
using AnyInfer.Schema;

namespace AnyInfer.Manifest;

/// <summary>Implements the explicit format-one manifest JSON boundary.</summary>
internal static class ManifestSerialization
{
    internal static JsonObject Encode(RunManifest manifest) => Obj(
        ("format", Text(manifest.Format)), ("anyinfer_version", Text(manifest.AnyinferVersion)),
        ("request_id", Text(manifest.RequestId)), ("complete", Bool(manifest.Complete)),
        ("request", Request(manifest.Request)), ("route", Route(manifest.Route)),
        ("capability", Capability(manifest.Capability)), ("attempts", Array(manifest.Attempts.Select(Attempt))),
        ("structured", Schema(manifest.Structured)), ("cache", Cache(manifest.Cache)),
        ("context", Context(manifest.Context)), ("dropped", Array(manifest.Dropped.Select(Dropped))),
        ("usage", Usage(manifest.Usage)), ("timing", Timing(manifest.Timing)),
        ("notes", Array(manifest.Notes.Select(Text))), ("payloads", manifest.Payloads is null ? Nil() : Payloads(manifest.Payloads)),
        ("operation", Text(manifest.Operation)), ("embedding_space", manifest.EmbeddingSpace is null ? Nil() : Embedding(manifest.EmbeddingSpace)));

    internal static RunManifest Decode(JsonObject data)
    {
        ArgumentNullException.ThrowIfNull(data);
        return new RunManifest(
            format: String(data, "format", "1"), anyinferVersion: String(data, "anyinfer_version", ""), requestId: String(data, "request_id", ""), complete: Boolean(data, "complete", false),
            request: Facet(data, "request", Request, static () => new RequestFacet()), route: Facet(data, "route", Route, static () => new RouteFacet()), capability: Facet(data, "capability", Capability, static () => new CapabilityFacet()),
            attempts: Array(data, "attempts", Attempt), structured: Facet(data, "structured", Schema, static () => new SchemaFacet()), cache: Facet(data, "cache", Cache, static () => new CacheFacet()), context: Facet(data, "context", Context, static () => new ContextFacet()),
            dropped: Array(data, "dropped", Dropped), usage: Facet(data, "usage", Usage, static () => new UsageFacet()), timing: Facet(data, "timing", Timing, static () => new TimingFacet()),
            notes: Array(data, "notes", value => RequiredString(value)), payloads: NullableFacet(data, "payloads", Payloads),
            operation: String(data, "operation", "generation"), embeddingSpace: NullableFacet(data, "embedding_space", Embedding));
    }

    private static JsonObject Request(RequestFacet value) => Obj(
        ("message_count", Int(value.MessageCount)), ("role_counts", Map(value.RoleCounts, Int)), ("char_count", Int(value.CharCount)), ("estimated_tokens", NullableInt(value.EstimatedTokens)),
        ("schema_present", Bool(value.SchemaPresent)), ("schema_name", NullableText(value.SchemaName)), ("schema_digest", NullableText(value.SchemaDigest)), ("tool_names", Array(value.ToolNames.Select(Text))),
        ("tool_choice", Text(value.ToolChoice)), ("sampling", Map(value.Sampling, static value => value)), ("reasoning", NullableText(value.Reasoning)), ("timeout_s", NullableDouble(value.TimeoutS)),
        ("repair_budget", Int(value.RepairBudget)), ("metadata_keys", Array(value.MetadataKeys.Select(Text))));

    private static RequestFacet Request(JsonObject value) => new(
        messageCount: Int(value, "message_count", 0), roleCounts: Map(value, "role_counts", RequiredInt), charCount: Int(value, "char_count", 0), estimatedTokens: NullableInt(value, "estimated_tokens"),
        schemaPresent: Boolean(value, "schema_present", false), schemaName: NullableString(value, "schema_name"), schemaDigest: NullableString(value, "schema_digest"), toolNames: Array(value, "tool_names", RequiredString),
        toolChoice: String(value, "tool_choice", "auto"), sampling: Map(value, "sampling", static item => item), reasoning: NullableString(value, "reasoning"), timeoutS: NullableDouble(value, "timeout_s"),
        repairBudget: Int(value, "repair_budget", 0), metadataKeys: Array(value, "metadata_keys", RequiredString));

    private static JsonObject Route(RouteFacet value) => Obj(("requested", Array(value.Requested.Select(Text))), ("resolved", NullableText(value.Resolved)), ("considered", Array(value.Considered.Select(RouteStep))));
    private static RouteFacet Route(JsonObject value) => new(Array(value, "requested", RequiredString), NullableString(value, "resolved"), Array(value, "considered", RouteStep));
    private static JsonObject RouteStep(RouteStep value) => Obj(("target", Text(value.Target)), ("outcome", Text(value.Outcome)), ("reason", Text(value.Reason)));
    private static RouteStep RouteStep(JsonObject value) => new(String(value, "target"), String(value, "outcome"), String(value, "reason", ""));

    private static JsonObject Capability(CapabilityFacet value) => Obj(("target", Text(value.Target)), ("facts", Array(value.Facts.Select(Fact))));
    private static CapabilityFacet Capability(JsonObject value) => new(String(value, "target", ""), Array(value, "facts", Fact));
    private static JsonObject Fact(SourcedFact value) => Obj(("name", Text(value.Name)), ("value", value.Value), ("provenance", Text(value.Provenance)));
    private static SourcedFact Fact(JsonObject value) => new(String(value, "name"), Present(value, "value"), String(value, "provenance"));

    private static JsonObject Attempt(AttemptFacet value) => Obj(("target", Text(value.Target)), ("attempt_number", Int(value.AttemptNumber)), ("outcome", Text(value.Outcome)), ("error", value.Error is null ? Nil() : Error(value.Error)), ("first_token_ms", NullableDouble(value.FirstTokenMs)), ("total_ms", NullableDouble(value.TotalMs)), ("queued_ms", NullableDouble(value.QueuedMs)), ("retry_reason", NullableText(value.RetryReason)), ("retry_delay_s", NullableDouble(value.RetryDelayS)), ("paced_s", Map(value.PacedS, Double)));
    private static AttemptFacet Attempt(JsonObject value) => new(String(value, "target"), Int(value, "attempt_number", 1), String(value, "outcome", "ok"), NullableFacet(value, "error", Error), NullableDouble(value, "first_token_ms"), NullableDouble(value, "total_ms"), NullableDouble(value, "queued_ms"), NullableString(value, "retry_reason"), NullableDouble(value, "retry_delay_s"), Map(value, "paced_s", RequiredDouble));

    private static JsonObject Error(ErrorInfo value) => Obj(("type_name", Text(value.TypeName)), ("provider", NullableText(value.Provider)), ("phase", NullableText(value.Phase)), ("retryable", Bool(value.Retryable)), ("http_status", value.HttpStatus is null ? Nil() : Int(value.HttpStatus.Value)), ("detail", NullableText(value.Detail)));
    private static ErrorInfo Error(JsonObject value) => new(String(value, "type_name"), NullableString(value, "provider"), NullableString(value, "phase"), Boolean(value, "retryable", false), NullableInt(value, "http_status"), NullableString(value, "detail"));

    private static JsonObject Schema(SchemaFacet value) => Obj(("requested", Bool(value.Requested)), ("chosen", NullableText(value.Chosen)), ("used", NullableText(value.Used)), ("ladder", Array(value.Ladder.Select(Rung))), ("repair_attempts", Int(value.RepairAttempts)), ("repairs", Array(value.Repairs.Select(Repair))), ("validated", Bool(value.Validated)));
    private static SchemaFacet Schema(JsonObject value) => new(Boolean(value, "requested", false), NullableString(value, "chosen"), NullableString(value, "used"), Array(value, "ladder", Rung), Int(value, "repair_attempts", 0), Array(value, "repairs", Repair), Boolean(value, "validated", false));
    private static JsonObject Rung(MechanismRung value) => Obj(("mechanism", Text(value.Mechanism)), ("available", Bool(value.Available)), ("reason", Text(value.Reason)));
    private static MechanismRung Rung(JsonObject value) => new(String(value, "mechanism"), Boolean(value, "available", false), String(value, "reason", ""));
    private static JsonObject Repair(RepairRecord value) => Obj(("attempt_number", Int(value.AttemptNumber)), ("mechanism", NullableText(value.Mechanism)), ("errors", Array(value.Errors.Select(Text))));
    private static RepairRecord Repair(JsonObject value) => new(Int(value, "attempt_number"), NullableString(value, "mechanism"), Array(value, "errors", RequiredString));

    private static JsonObject Cache(CacheFacet value) => Obj(("policy_mode", NullableText(value.PolicyMode)), ("mechanism", NullableText(value.Mechanism)), ("mark_count", Int(value.MarkCount)), ("estimated_cacheable_tokens", Int(value.EstimatedCacheableTokens)), ("read_tokens", NullableLong(value.ReadTokens)), ("write_tokens", NullableLong(value.WriteTokens)));
    private static CacheFacet Cache(JsonObject value) => new(NullableString(value, "policy_mode"), NullableString(value, "mechanism"), Int(value, "mark_count", 0), Long(value, "estimated_cacheable_tokens", 0), NullableLong(value, "read_tokens"), NullableLong(value, "write_tokens"));

    private static JsonObject Context(ContextFacet value) => Obj(("reductions", Array(value.Reductions.Select(Reduction))));
    private static ContextFacet Context(JsonObject value) => new(Array(value, "reductions", Reduction));
    private static JsonObject Reduction(ReductionRecord value) => Obj(("strategy", Text(value.Strategy)), ("representation", Text(value.Representation)), ("candidate_count", Int(value.CandidateCount)), ("selected_count", Int(value.SelectedCount)), ("omitted_count", Int(value.OmittedCount)), ("estimated_tokens", Int(value.EstimatedTokens)), ("max_tokens", Int(value.MaxTokens)), ("binding_constraints", Array(value.BindingConstraints.Select(Text))), ("calls", Int(value.Calls)), ("complete", Bool(value.Complete)));
    private static ReductionRecord Reduction(JsonObject value) => new(String(value, "strategy"), String(value, "representation"), Int(value, "candidate_count", 0), Int(value, "selected_count", 0), Int(value, "omitted_count", 0), Int(value, "estimated_tokens", 0), Int(value, "max_tokens", 0), Array(value, "binding_constraints", RequiredString), Int(value, "calls", 0), Boolean(value, "complete", true));
    private static JsonObject Dropped(DroppedParameter value) => Obj(("target", Text(value.Target)), ("parameter", Text(value.Parameter)), ("reason", Text(value.Reason)));
    private static DroppedParameter Dropped(JsonObject value) => new(String(value, "target"), String(value, "parameter"), String(value, "reason"));

    private static JsonObject Usage(UsageFacet value) => Obj(("input_tokens", NullableLong(value.InputTokens)), ("output_tokens", NullableLong(value.OutputTokens)), ("total_tokens", NullableLong(value.TotalTokens)), ("cache_read_tokens", NullableLong(value.CacheReadTokens)), ("cache_write_tokens", NullableLong(value.CacheWriteTokens)), ("reasoning_tokens", NullableLong(value.ReasoningTokens)), ("cost_usd", NullableText(value.CostUsd)), ("estimated_fields", Map(value.EstimatedFields, Text)), ("search_units", NullableLong(value.SearchUnits)));
    private static UsageFacet Usage(JsonObject value) => new(NullableLong(value, "input_tokens"), NullableLong(value, "output_tokens"), NullableLong(value, "total_tokens"), NullableLong(value, "cache_read_tokens"), NullableLong(value, "cache_write_tokens"), NullableLong(value, "reasoning_tokens"), NullableString(value, "cost_usd"), Map(value, "estimated_fields", RequiredString), NullableLong(value, "search_units"));
    private static JsonObject Timing(TimingFacet value) => Obj(("first_token_ms", NullableDouble(value.FirstTokenMs)), ("total_ms", NullableDouble(value.TotalMs)), ("output_tokens_per_s", NullableDouble(value.OutputTokensPerS)), ("phases", Map(value.Phases, Double)));
    private static TimingFacet Timing(JsonObject value) => new(NullableDouble(value, "first_token_ms"), NullableDouble(value, "total_ms"), NullableDouble(value, "output_tokens_per_s"), Map(value, "phases", RequiredDouble));
    private static JsonObject Payloads(PayloadFacet value) => Obj(("prompt_text", NullableText(value.PromptText)), ("response_text", NullableText(value.ResponseText)), ("schema_body", NullableText(value.SchemaBody)), ("tool_arguments", Array(value.ToolArguments.Select(Text))), ("repair_texts", Array(value.RepairTexts.Select(Text))));
    private static PayloadFacet Payloads(JsonObject value) => new(NullableString(value, "prompt_text"), NullableString(value, "response_text"), NullableString(value, "schema_body"), Array(value, "tool_arguments", RequiredString), Array(value, "repair_texts", RequiredString));
    private static JsonObject Embedding(EmbeddingSpace value) => Obj(("provider_id", Text(value.ProviderId)), ("model", Text(value.Model)), ("model_revision", NullableText(value.ModelRevision)), ("dimensions", NullableInt(value.Dimensions)), ("input_intent_aware", Bool(value.InputIntentAware)), ("normalized", value.Normalized is null ? Nil() : Bool(value.Normalized.Value)), ("compatibility_id", NullableText(value.CompatibilityId)));
    private static EmbeddingSpace Embedding(JsonObject value) => new(String(value, "provider_id"), String(value, "model"), NullableString(value, "model_revision"), NullableInt(value, "dimensions"), Boolean(value, "input_intent_aware", false), NullableBool(value, "normalized"), NullableString(value, "compatibility_id"));

    private static JsonObject Obj(params (string Name, JsonValue Value)[] values) => new(values.Select(static pair => new JsonProperty(pair.Name, pair.Value)));
    private static JsonArray Array(IEnumerable<JsonValue> values) => new(values);
    private static JsonString Text(string value) => new(value);
    private static JsonBoolean Bool(bool value) => new(value);
    private static JsonInteger Int(int value) => new(value);
    private static JsonInteger Int(long value) => new(value);
    private static JsonNumber Double(double value) => new(value);
    private static JsonValue Nil() => JsonNull.Instance;
    private static JsonValue NullableText(string? value) => value is null ? Nil() : Text(value);
    private static JsonValue NullableInt(int? value) => value is null ? Nil() : Int(value.Value);
    private static JsonValue NullableLong(long? value) => value is null ? Nil() : Int(value.Value);
    private static JsonValue NullableDouble(double? value) => value is null ? Nil() : Double(value.Value);
    private static JsonObject Map<T>(IReadOnlyDictionary<string, T> values, Func<T, JsonValue> encode) => new(values.Select(pair => new JsonProperty(pair.Key, encode(pair.Value))));

    private static T Facet<T>(JsonObject data, string name, Func<JsonObject, T> decode, Func<T> fallback) where T : class => data.TryGetValue(name, out var item) ? item is JsonNull ? throw Invalid(name) : decode(Object(item)) : fallback();
    private static T? NullableFacet<T>(JsonObject data, string name, Func<JsonObject, T> decode) where T : class => !data.TryGetValue(name, out var item) || item is JsonNull ? null : decode(Object(item));
    private static IReadOnlyList<T> Array<T>(JsonObject data, string name, Func<JsonObject, T> decode) => !data.TryGetValue(name, out var item) ? [] : Array(item).Items.Select(value => decode(Object(value))).ToArray();
    private static IReadOnlyList<T> Array<T>(JsonObject data, string name, Func<JsonValue, T> decode) => !data.TryGetValue(name, out var item) ? [] : Array(item).Items.Select(decode).ToArray();
    private static IReadOnlyDictionary<string, T> Map<T>(JsonObject data, string name, Func<JsonValue, T> decode) => !data.TryGetValue(name, out var item) ? new Dictionary<string, T>(StringComparer.Ordinal) : Object(item).Properties.ToDictionary(property => property.Name, property => decode(property.Value), StringComparer.Ordinal);
    private static JsonObject Object(JsonValue value) => value as JsonObject ?? throw Invalid("object");
    private static JsonArray Array(JsonValue value) => value as JsonArray ?? throw Invalid("array");
    private static JsonValue Present(JsonObject value, string name) => value.TryGetValue(name, out var item) ? item : throw Invalid(name);
    private static string String(JsonObject value, string name, string? fallback = null) => !value.TryGetValue(name, out var item) ? fallback ?? throw Invalid(name) : RequiredString(item);
    private static string? NullableString(JsonObject value, string name) => !value.TryGetValue(name, out var item) || item is JsonNull ? null : RequiredString(item);
    private static bool Boolean(JsonObject value, string name, bool fallback) => !value.TryGetValue(name, out var item) ? fallback : item is JsonBoolean boolean ? boolean.Value : throw Invalid(name);
    private static bool? NullableBool(JsonObject value, string name) => !value.TryGetValue(name, out var item) || item is JsonNull ? null : item is JsonBoolean boolean ? boolean.Value : throw Invalid(name);
    private static int Int(JsonObject value, string name, int? fallback = null) => !value.TryGetValue(name, out var item) ? fallback ?? throw Invalid(name) : RequiredInt(item);
    private static long Long(JsonObject value, string name, long? fallback = null) => !value.TryGetValue(name, out var item) ? fallback ?? throw Invalid(name) : RequiredLong(item);
    private static int? NullableInt(JsonObject value, string name) => !value.TryGetValue(name, out var item) || item is JsonNull ? null : RequiredInt(item);
    private static long? NullableLong(JsonObject value, string name) => !value.TryGetValue(name, out var item) || item is JsonNull ? null : RequiredLong(item);
    private static double? NullableDouble(JsonObject value, string name) => !value.TryGetValue(name, out var item) || item is JsonNull ? null : RequiredDouble(item);
    private static string RequiredString(JsonValue value) => value is JsonString text ? text.Value : throw Invalid("string");
    private static int RequiredInt(JsonValue value) => value is JsonInteger integer && integer.Value >= int.MinValue && integer.Value <= int.MaxValue ? (int)integer.Value : throw Invalid("integer");
    private static long RequiredLong(JsonValue value) => value is JsonInteger integer && integer.Value >= long.MinValue && integer.Value <= long.MaxValue ? (long)integer.Value : throw Invalid("integer");
    private static double RequiredDouble(JsonValue value)
    {
        if (value is JsonNumber number)
        {
            return number.Value;
        }

        if (value is JsonInteger integer)
        {
            var converted = (double)integer.Value;
            return double.IsFinite(converted) ? converted : throw Invalid("number");
        }

        throw Invalid("number");
    }
    private static FormatException Invalid(string field) => new($"Manifest field '{field}' has an invalid value.");
}
