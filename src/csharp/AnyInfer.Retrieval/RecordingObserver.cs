using AnyInfer;
using AnyInfer.Events;
using AnyInfer.Json;

internal sealed class RecordingObserver : IObserver
{
    private readonly CaptureOrder _order;
    private readonly object _gate = new();
    private readonly List<JsonObject> _events = [];
    private string? _requestId;
    private Exception? _correlationFailure;

    internal RecordingObserver(CaptureOrder order) => _order = order ?? throw new ArgumentNullException(nameof(order));

    internal IReadOnlyList<JsonObject> Events
    {
        get { lock (_gate) return _events.ToArray(); }
    }

    public void OnEvent(TelemetryEvent telemetryEvent)
    {
        ArgumentNullException.ThrowIfNull(telemetryEvent);
        lock (_gate)
        {
            RecordRequestId(RequestId(telemetryEvent));
            JsonObject? captured = telemetryEvent switch
            {
                RequestStarted started => FixtureJson.Object(("type", FixtureJson.String("RequestStarted")), ("order", FixtureJson.Integer(_order.Next())), ("request_relation", FixtureJson.String("operation")), ("targets", FixtureJson.Array(started.Targets.Select(FixtureJson.String))), ("metadata", Object(started.Metadata.ToDictionary(pair => pair.Key, pair => FixtureJson.String(pair.Value), StringComparer.Ordinal))), ("operation", FixtureJson.String(started.Operation))),
                TargetResolved resolved => FixtureJson.Object(("type", FixtureJson.String("TargetResolved")), ("order", FixtureJson.Integer(_order.Next())), ("request_relation", FixtureJson.String("operation")), ("target", Target(resolved.Target))),
                AttemptStarted started => FixtureJson.Object(("type", FixtureJson.String("AttemptStarted")), ("order", FixtureJson.Integer(_order.Next())), ("request_relation", FixtureJson.String("operation")), ("target", Target(started.Target)), ("attempt", FixtureJson.Integer(started.AttemptNumber))),
                AttemptCompleted completed => FixtureJson.Object(("type", FixtureJson.String("AttemptCompleted")), ("order", FixtureJson.Integer(_order.Next())), ("request_relation", FixtureJson.String("operation")), ("target", Target(completed.Target)), ("usage", Usage(completed.Usage)), ("timing", Timing(completed.Timing)), ("finish_reason", FixtureJson.String(completed.FinishReason))),
                RetryScheduled retry => FixtureJson.Object(("type", FixtureJson.String("RetryScheduled")), ("order", FixtureJson.Integer(_order.Next())), ("request_relation", FixtureJson.String("operation")), ("target", Target(retry.Target)), ("attempt", FixtureJson.Integer(retry.AttemptNumber)), ("delay_s", FixtureJson.Number(retry.DelayS)), ("error", Snapshot(retry.Error))),
                FallbackTriggered fallback => FixtureJson.Object(("type", FixtureJson.String("FallbackTriggered")), ("order", FixtureJson.Integer(_order.Next())), ("request_relation", FixtureJson.String("operation")), ("from_target", Target(fallback.FromTarget)), ("to_target", FixtureJson.String(fallback.ToTarget)), ("error", fallback.Error is null ? FixtureJson.Null() : Snapshot(fallback.Error))),
                RequestCompleted completed => FixtureJson.Object(("type", FixtureJson.String("RequestCompleted")), ("order", FixtureJson.Integer(_order.Next())), ("request_relation", FixtureJson.String("operation")), ("target", Target(completed.Target)), ("usage", Usage(completed.Usage)), ("timing", Timing(completed.Timing)), ("repair_attempts", FixtureJson.Integer(completed.RepairAttempts))),
                RequestFailed failed => FixtureJson.Object(("type", FixtureJson.String("RequestFailed")), ("order", FixtureJson.Integer(_order.Next())), ("request_relation", FixtureJson.String("operation")), ("error", Snapshot(failed.Error))),
                _ => null,
            };
            if (captured is not null) _events.Add(captured);
        }
    }

    internal void ValidateCorrelation(AnyInfer.Manifest.RunManifest? manifest)
    {
        lock (_gate)
        {
            if (_correlationFailure is not null) throw new InvalidOperationException("Telemetry request identifiers do not describe one operation.", _correlationFailure);
            if (manifest is not null && _requestId is not null && !string.Equals(manifest.RequestId, _requestId, StringComparison.Ordinal))
            {
                throw new InvalidOperationException("Manifest and telemetry request identifiers disagree.");
            }
        }
    }

    private void RecordRequestId(string? requestId)
    {
        if (requestId is null) return;
        if (_requestId is null) _requestId = requestId;
        else if (!string.Equals(_requestId, requestId, StringComparison.Ordinal)) _correlationFailure ??= new InvalidOperationException("Telemetry request identifiers disagree.");
    }

    private static string? RequestId(TelemetryEvent value) => value switch
    {
        RequestStarted item => item.RequestId,
        TargetResolved item => item.RequestId,
        AttemptStarted item => item.RequestId,
        AttemptCompleted item => item.RequestId,
        RetryScheduled item => item.RequestId,
        FallbackTriggered item => item.RequestId,
        RequestCompleted item => item.RequestId,
        RequestFailed item => item.RequestId,
        _ => null,
    };

    private static JsonObject Target(ResolvedTarget target) => FixtureJson.Object(("provider_id", FixtureJson.String(target.ProviderId)), ("model", FixtureJson.String(target.Model)), ("via_alias", target.ViaAlias is null ? FixtureJson.Null() : FixtureJson.String(target.ViaAlias)));
    private static JsonObject Snapshot(ErrorInfo error) => FixtureJson.Object(("runtime_type", FixtureJson.String(error.TypeName)), ("provider", error.Provider is null ? FixtureJson.Null() : FixtureJson.String(error.Provider)), ("phase", error.Phase is null ? FixtureJson.Null() : FixtureJson.String(error.Phase)), ("retryable", FixtureJson.Boolean(error.Retryable)), ("http_status", error.HttpStatus is null ? FixtureJson.Null() : FixtureJson.Integer(error.HttpStatus.Value)), ("detail", error.Detail is null ? FixtureJson.Null() : FixtureJson.String(error.Detail)));
    private static JsonObject Usage(Usage value) => FixtureJson.Object(("input_tokens", Long(value.InputTokens)), ("output_tokens", Long(value.OutputTokens)), ("total_tokens", Long(value.TotalTokens)), ("cache_read_tokens", Long(value.CacheReadTokens)), ("cache_write_tokens", Long(value.CacheWriteTokens)), ("reasoning_tokens", Long(value.ReasoningTokens)), ("cost_usd", value.CostUsd is null ? FixtureJson.Null() : FixtureJson.String(value.CostUsd.ToString())), ("search_units", Long(value.SearchUnits)), ("server_tool_uses", Object(value.ServerToolUses.ToDictionary(pair => pair.Key, pair => FixtureJson.Integer(pair.Value), StringComparer.Ordinal))));
    private static JsonObject Timing(Timing value) => FixtureJson.Object(("started_at", FixtureJson.Number(value.StartedAt)), ("first_token_ms", Number(value.FirstTokenMs)), ("total_ms", FixtureJson.Number(value.TotalMs)), ("output_tokens_per_s", Number(value.OutputTokensPerS)), ("phases", Object(value.Phases.ToDictionary(pair => pair.Key, pair => FixtureJson.Number(pair.Value), StringComparer.Ordinal))));
    private static JsonObject Object(IReadOnlyDictionary<string, JsonValue> values) => FixtureJson.Object(values.Select(pair => (pair.Key, pair.Value)).ToArray());
    private static JsonValue Long(long? value) => value is null ? FixtureJson.Null() : FixtureJson.Integer(value.Value);
    private static JsonValue Number(double? value) => value is null ? FixtureJson.Null() : FixtureJson.Number(value.Value);
}
