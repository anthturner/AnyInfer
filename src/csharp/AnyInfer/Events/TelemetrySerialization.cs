using AnyInfer.Json;
using PeterO.Numbers;

namespace AnyInfer.Events;

/// <summary>Closed-family event projection and payload stripping.</summary>
internal static class TelemetrySerialization
{
    internal static JsonObject ToDictionary(TelemetryEvent value) => value switch
    {
        RequestStarted e => Obj("RequestStarted", ("request_id", S(e.RequestId)), ("targets", A(e.Targets.Select(S))), ("metadata", M(e.Metadata)), ("prompt_text", N(e.PromptText)), ("operation", S(e.Operation))),
        ArenaCompleted e => Obj("ArenaCompleted", ("request_id", S(e.RequestId)), ("target_count", I(e.TargetCount)), ("strategy", S(e.Strategy)), ("agreement", NI(e.Agreement)), ("calls", I(e.Calls)), ("memoized_tool_calls", I(e.MemoizedToolCalls)), ("synthesized", B(e.Synthesized))),
        TargetResolved e => Obj("TargetResolved", ("request_id", S(e.RequestId)), ("target", Target(e.Target))),
        AttemptStarted e => Obj("AttemptStarted", ("request_id", S(e.RequestId)), ("target", Target(e.Target)), ("attempt_number", I(e.AttemptNumber))),
        FirstToken e => Obj("FirstToken", ("request_id", S(e.RequestId)), ("target", Target(e.Target)), ("at_ms", D(e.AtMs))),
        AttemptCompleted e => Obj("AttemptCompleted", ("request_id", S(e.RequestId)), ("target", Target(e.Target)), ("usage", Usage(e.Usage)), ("timing", Timing(e.Timing)), ("finish_reason", S(e.FinishReason))),
        RetryScheduled e => Obj("RetryScheduled", ("request_id", S(e.RequestId)), ("target", Target(e.Target)), ("attempt_number", I(e.AttemptNumber)), ("delay_s", D(e.DelayS)), ("error", Error(e.Error))),
        FallbackTriggered e => Obj("FallbackTriggered", ("request_id", S(e.RequestId)), ("from_target", Target(e.FromTarget)), ("to_target", S(e.ToTarget)), ("error", e.Error is null ? Z() : Error(e.Error))),
        RepairAttempted e => Obj("RepairAttempted", ("request_id", S(e.RequestId)), ("target", Target(e.Target)), ("attempt_number", I(e.AttemptNumber)), ("mechanism", N(e.Mechanism)), ("errors", A(e.Errors.Select(S))), ("raw_text", N(e.RawText))),
        RequestCompleted e => Obj("RequestCompleted", ("request_id", S(e.RequestId)), ("target", Target(e.Target)), ("usage", Usage(e.Usage)), ("timing", Timing(e.Timing)), ("repair_attempts", I(e.RepairAttempts)), ("response_text", N(e.ResponseText))),
        RequestFailed e => Obj("RequestFailed", ("request_id", S(e.RequestId)), ("error", Error(e.Error))),
        ParameterDropped e => Obj("ParameterDropped", ("request_id", S(e.RequestId)), ("target", Target(e.Target)), ("parameter", S(e.Parameter)), ("reason", S(e.Reason))),
        ProviderDiagnostic e => Obj("ProviderDiagnostic", ("target", e.Target is null ? Z() : Target(e.Target)), ("diagnostic", Diagnostic(e.Diagnostic)), ("request_id", N(e.RequestId))),
        UsageEstimated e => Obj("UsageEstimated", ("request_id", S(e.RequestId)), ("target", Target(e.Target)), ("field_name", S(e.FieldName)), ("method", S(e.Method))),
        ContextReduced e => Obj("ContextReduced", ("strategy", S(e.Strategy)), ("representation", S(e.Representation)), ("candidate_count", I(e.CandidateCount)), ("selected_count", I(e.SelectedCount)), ("omitted_count", I(e.OmittedCount)), ("estimated_tokens", I(e.EstimatedTokens)), ("max_tokens", I(e.MaxTokens)), ("binding_constraints", A(e.BindingConstraints.Select(S))), ("calls", I(e.Calls))),
        CachePlanned e => Obj("CachePlanned", ("request_id", S(e.RequestId)), ("target", Target(e.Target)), ("mechanism", S(e.Mechanism)), ("mark_count", I(e.MarkCount)), ("estimated_cacheable_tokens", L(e.EstimatedCacheableTokens))),
        RateLimitWaited e => Obj("RateLimitWaited", ("request_id", S(e.RequestId)), ("provider_id", S(e.ProviderId)), ("waited_s", D(e.WaitedS)), ("reason", S(e.Reason)), ("target", e.Target is null ? Z() : Target(e.Target))),
        RateLimitObserved e => Obj("RateLimitObserved", ("provider_id", S(e.ProviderId)), ("requests_remaining", NL(e.RequestsRemaining)), ("tokens_remaining", NL(e.TokensRemaining)), ("resets_in_s", ND(e.ResetsInS))),
        ServerLifecycle e => Obj("ServerLifecycle", ("server_id", S(e.ServerId)), ("state", S(e.State)), ("detail", S(e.Detail))),
        DownloadProgress e => Obj("DownloadProgress", ("artifact_id", S(e.ArtifactId)), ("downloaded_bytes", L(e.DownloadedBytes)), ("total_bytes", NL(e.TotalBytes)), ("done", B(e.Done)), ("phase", S(e.Phase)), ("file_index", I(e.FileIndex)), ("file_count", I(e.FileCount)), ("filename", S(e.Filename)), ("session_bytes", L(e.SessionBytes))),
        BatchSubmitted e => Obj("BatchSubmitted", ("batch_id", S(e.BatchId)), ("target", Target(e.Target)), ("line_count", I(e.LineCount))),
        BatchCompleted e => Obj("BatchCompleted", ("batch_id", S(e.BatchId)), ("target", Target(e.Target)), ("status", S(e.Status)), ("completed", I(e.Completed)), ("failed", I(e.Failed))),
        CredentialRotated e => Obj("CredentialRotated", ("provider", S(e.Provider)), ("trigger", S(e.Trigger))),
        _ => throw new ArgumentOutOfRangeException(nameof(value)),
    };

    internal static TelemetryEvent StripPayloads(TelemetryEvent value) => value switch
    {
        RequestStarted e => new RequestStarted(e.RequestId, e.Targets, e.Metadata, null, e.Operation),
        RepairAttempted e => new RepairAttempted(e.RequestId, e.Target, e.AttemptNumber, e.Mechanism, e.Errors, null),
        RequestCompleted e => e with { ResponseText = null },
        _ => value,
    };

    private static JsonObject Obj(string kind, params (string Key, JsonValue Value)[] values) => new([new JsonProperty("event", S(kind)), .. values.Select(pair => new JsonProperty(pair.Key, pair.Value))]);
    private static JsonValue S(string value) => new JsonString(Redaction.Redact(value));
    private static JsonValue N(string? value) => value is null ? Z() : S(value);
    private static JsonValue B(bool value) => new JsonBoolean(value);
    private static JsonValue I(int value) => new JsonInteger(value);
    private static JsonValue L(long value) => new JsonInteger(value);
    private static JsonValue NI(int? value) => value is null ? Z() : I(value.Value);
    private static JsonValue NL(long? value) => value is null ? Z() : L(value.Value);
    private static JsonValue D(double value) => new JsonNumber(value);
    private static JsonValue ND(double? value) => value is null ? Z() : D(value.Value);
    private static JsonValue Z() => JsonNull.Instance;
    private static JsonArray A(IEnumerable<JsonValue> values) => new(values);
    private static JsonObject M(IReadOnlyDictionary<string, string> values) { var map = new Dictionary<string, JsonValue>(StringComparer.Ordinal); foreach (var pair in values) map[Redaction.Redact(pair.Key)] = S(pair.Value); return new(map.Select(pair => new JsonProperty(pair.Key, pair.Value))); }
    private static JsonObject Target(ResolvedTarget value) => new([new JsonProperty("provider_id", S(value.ProviderId)), new JsonProperty("model", S(value.Model)), new JsonProperty("via_alias", N(value.ViaAlias))]);
    private static JsonObject Error(ErrorInfo value) => new([new JsonProperty("type_name", S(value.TypeName)), new JsonProperty("provider", N(value.Provider)), new JsonProperty("phase", N(value.Phase)), new JsonProperty("retryable", B(value.Retryable)), new JsonProperty("http_status", NI(value.HttpStatus)), new JsonProperty("detail", N(value.Detail))]);
    private static JsonObject Diagnostic(Diagnostic value) => new([new JsonProperty("code", S(value.Code)), new JsonProperty("severity", S(value.Severity)), new JsonProperty("message", S(value.Message))]);
    private static JsonObject Timing(Timing value) => new([new JsonProperty("started_at", D(value.StartedAt)), new JsonProperty("first_token_ms", ND(value.FirstTokenMs)), new JsonProperty("total_ms", D(value.TotalMs)), new JsonProperty("output_tokens_per_s", ND(value.OutputTokensPerS)), new JsonProperty("phases", new JsonObject(value.Phases.Select(pair => new JsonProperty(Redaction.Redact(pair.Key), D(pair.Value))))) ]);
    private static JsonObject Usage(Usage value) => new([new JsonProperty("input_tokens", NL(value.InputTokens)), new JsonProperty("output_tokens", NL(value.OutputTokens)), new JsonProperty("total_tokens", NL(value.TotalTokens)), new JsonProperty("cache_read_tokens", NL(value.CacheReadTokens)), new JsonProperty("cache_write_tokens", NL(value.CacheWriteTokens)), new JsonProperty("reasoning_tokens", NL(value.ReasoningTokens)), new JsonProperty("cost_usd", value.CostUsd is null ? Z() : S(value.CostUsd.ToString())), new JsonProperty("search_units", NL(value.SearchUnits)), new JsonProperty("server_tool_uses", new JsonObject(value.ServerToolUses.Select(pair => new JsonProperty(Redaction.Redact(pair.Key), L(pair.Value))))) ]);
}
