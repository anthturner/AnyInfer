using System.Text.Json;
using AnyInfer;
using AnyInfer.Capabilities;
using AnyInfer.Json;
using AnyInfer.Manifest;
using AnyInfer.Providers;

internal static class Projection
{
    internal static JsonObject Embedding(EmbeddingResult result, IEnumerable<ScriptedRetrievalAdapter> adapters, IEnumerable<JsonObject> factories, RecordingObserver observer, IEnumerable<JsonObject>? ledger, IEnumerable<JsonObject> resources) => Value(
        Operation("embedding", "ok", FixtureJson.Object(
            ("target", Target(result.Target)),
            ("vectors", FixtureJson.Array(result.Vectors.Select(Vector))),
            ("space", Space(result.Space)),
            ("usage", Usage(result.Usage)),
            ("timing", Timing(result.Timing)),
            ("warnings", FixtureJson.Array(result.Warnings.Select(FixtureJson.String))),
            ("raw", result.Raw ?? FixtureJson.Null())), FixtureJson.Null(), result.Attempts), adapters, factories, observer, ledger, result.Manifest, resources);

    internal static JsonObject Rerank(RerankResult result, IEnumerable<ScriptedRetrievalAdapter> adapters, IEnumerable<JsonObject> factories, RecordingObserver observer, IEnumerable<JsonObject>? ledger, IEnumerable<JsonObject> resources) => Value(
        Operation("rerank", "ok", FixtureJson.Object(
            ("target", Target(result.Target)),
            ("items", FixtureJson.Array(result.Items.Select(Item))),
            ("usage", Usage(result.Usage)),
            ("timing", Timing(result.Timing)),
            ("warnings", FixtureJson.Array(result.Warnings.Select(FixtureJson.String))),
            ("raw", result.Raw ?? FixtureJson.Null())), FixtureJson.Null(), result.Attempts), adapters, factories, observer, ledger, result.Manifest, resources);

    internal static JsonObject Failure(Exception exception, IEnumerable<ScriptedRetrievalAdapter> adapters, IEnumerable<JsonObject> factories, RecordingObserver observer, IEnumerable<JsonObject>? ledger, string kind, IEnumerable<JsonObject> resources, bool callerCancellation) =>
        Value(exception is OperationCanceledException && callerCancellation
            ? Cancelled(kind)
            : Operation(kind, "error", FixtureJson.Null(), Error(exception), Attempts(exception)), adapters, factories, observer, ledger, null, resources,
            exception is AllTargetsFailedException aggregate
                ? FixtureJson.Array(aggregate.BatchFailures.Select(BatchFailure))
                : FixtureJson.Null());

    internal static JsonObject EmbeddingWire(JsonElement script, int stepOrdinal, string instance, EmbeddingWireRequest request, long enteredOrder, long terminalOrder, string outcome, JsonValue response, JsonValue failure) => FixtureJson.Object(
        ("selector_id", FixtureJson.String(script.GetProperty("id").GetString()!)),
        ("step_ordinal", FixtureJson.Integer(stepOrdinal)),
        ("instance", FixtureJson.String(instance)), ("target", Target(new ResolvedTarget(instance, request.Model))),
        ("kind", FixtureJson.String("embedding")), ("entered_order", FixtureJson.Integer(enteredOrder)), ("terminal_order", FixtureJson.Integer(terminalOrder)),
        ("request", FixtureJson.Object(
            ("model", FixtureJson.String(request.Model)), ("inputs", FixtureJson.Array(request.Inputs.Select(FixtureJson.String))),
            ("input_type", request.InputType is null ? FixtureJson.Null() : FixtureJson.String(InputType(request.InputType.Value))),
            ("dimensions", OptionalInteger(request.Dimensions)), ("timeout_s", FixtureJson.Number(request.TimeoutS)),
            ("max_response_bytes", FixtureJson.Integer(request.MaxResponseBytes)), ("extra_options", Object(request.ExtraOptions)))),
        ("outcome", FixtureJson.String(outcome)), ("response", response), ("failure", failure));

    internal static JsonObject RerankWire(JsonElement script, int stepOrdinal, string instance, RerankWireRequest request, long enteredOrder, long terminalOrder, string outcome, JsonValue response, JsonValue failure) => FixtureJson.Object(
        ("selector_id", FixtureJson.String(script.GetProperty("id").GetString()!)),
        ("step_ordinal", FixtureJson.Integer(stepOrdinal)),
        ("instance", FixtureJson.String(instance)), ("target", Target(new ResolvedTarget(instance, request.Model))),
        ("kind", FixtureJson.String("rerank")), ("entered_order", FixtureJson.Integer(enteredOrder)), ("terminal_order", FixtureJson.Integer(terminalOrder)),
        ("request", FixtureJson.Object(
            ("model", FixtureJson.String(request.Model)), ("query", FixtureJson.String(request.Query)),
            ("documents", FixtureJson.Array(request.Documents.Select(document => FixtureJson.Object(("index", FixtureJson.Integer(document.Index)), ("text", FixtureJson.String(document.Text)))))),
            ("top_n", OptionalInteger(request.TopN)), ("timeout_s", FixtureJson.Number(request.TimeoutS)),
            ("max_response_bytes", FixtureJson.Integer(request.MaxResponseBytes)), ("extra_options", Object(request.ExtraOptions)))),
        ("outcome", FixtureJson.String(outcome)), ("response", response), ("failure", failure));

    internal static JsonValue EmbeddingResponse(JsonElement response) => FixtureJson.Object(
        ("vectors", FixtureJson.Array(response.GetProperty("vectors").EnumerateArray().Select(vector => FixtureJson.Array(vector.EnumerateArray().Select(value => FixtureJson.Number(value.GetDouble())))))),
        ("model", OptionalString(response, "model")), ("dimensions", OptionalInteger(response, "dimensions")),
        ("normalized", OptionalBoolean(response, "normalized")), ("usage", OptionalUsage(response.GetProperty("usage"))),
        ("phases", Object(response.GetProperty("phases").EnumerateObject().ToDictionary(pair => pair.Name, pair => FixtureJson.Number(pair.Value.GetDouble()), StringComparer.Ordinal))),
        ("raw", OptionalRaw(response.GetProperty("raw"))));

    internal static JsonValue EmbeddingResponse(EmbeddingWireResult response) => FixtureJson.Object(
        ("vectors", FixtureJson.Array(response.Vectors.Select(vector => FixtureJson.Array(vector.Select(FixtureJson.Number))))),
        ("model", OptionalString(response.Model)), ("dimensions", OptionalInteger(response.Dimensions)),
        ("normalized", OptionalBoolean(response.Normalized)), ("usage", response.Usage is null ? FixtureJson.Null() : Usage(response.Usage)),
        ("phases", Object(response.Phases.ToDictionary(pair => pair.Key, pair => FixtureJson.Number(pair.Value), StringComparer.Ordinal))),
        ("raw", response.Raw ?? FixtureJson.Null()));

    internal static JsonValue RerankResponse(JsonElement response) => FixtureJson.Object(
        ("items", FixtureJson.Array(response.GetProperty("items").EnumerateArray().Select(item => FixtureJson.Object(("index", FixtureJson.Integer(item.GetProperty("index").GetInt32())), ("score", FixtureJson.Number(item.GetProperty("score").GetDouble())))))),
        ("model", OptionalString(response, "model")), ("usage", OptionalUsage(response.GetProperty("usage"))), ("raw", OptionalRaw(response.GetProperty("raw"))));

    internal static JsonValue RerankResponse(RerankWireResult response)
    {
        var items = response.Items.Select(item => FixtureJson.Object(
            ("index", FixtureJson.Integer(item.Index)), ("score", FixtureJson.Number(item.Score))));
        return FixtureJson.Object(
            ("items", FixtureJson.Array(items)), ("model", OptionalString(response.Model)),
            ("usage", response.Usage is null ? FixtureJson.Null() : Usage(response.Usage)),
            ("raw", response.Raw ?? FixtureJson.Null()));
    }

    internal static JsonValue Error(Exception exception)
    {
        if (exception is SpendLimitException limit)
        {
            return FixtureJson.Object(
                ("runtime_type", FixtureJson.String(limit.GetType().Name)), ("message", FixtureJson.String(Redaction.Redact(limit.Message))),
                ("provider", OptionalString(limit.Provider)), ("phase", OptionalString(limit.Phase)),
                ("retryable", FixtureJson.Boolean(limit.Retryable)), ("http_status", OptionalInteger(limit.HttpStatus)),
                ("retry_after_s", OptionalNumber(limit.RetryAfterS)), ("detail", OptionalString(limit.Detail)), ("hint", OptionalString(limit.Hint)),
                ("limit_usd", OptionalMoney(limit.LimitUsd)), ("spent_usd", OptionalMoney(limit.SpentUsd)), ("estimated_usd", OptionalMoney(limit.EstimatedUsd)));
        }

        if (exception is AnyInferException typed)
        {
            return FixtureJson.Object(
                ("runtime_type", FixtureJson.String(typed.GetType().Name)), ("message", FixtureJson.String(Redaction.Redact(typed.Message))),
                ("provider", OptionalString(typed.Provider)), ("phase", OptionalString(typed.Phase)),
                ("retryable", FixtureJson.Boolean(typed.Retryable)), ("http_status", OptionalInteger(typed.HttpStatus)),
                ("retry_after_s", OptionalNumber(typed.RetryAfterS)), ("detail", OptionalString(typed.Detail)), ("hint", OptionalString(typed.Hint)));
        }

        return FixtureJson.Object(
            ("runtime_type", FixtureJson.String(exception.GetType().Name)), ("message", FixtureJson.String(Redaction.Redact(exception.Message))),
            ("provider", FixtureJson.Null()), ("phase", FixtureJson.Null()), ("retryable", FixtureJson.Boolean(false)),
            ("http_status", FixtureJson.Null()), ("retry_after_s", FixtureJson.Null()), ("detail", FixtureJson.Null()), ("hint", FixtureJson.Null()));
    }

    private static JsonObject Value(JsonObject operation, IEnumerable<ScriptedRetrievalAdapter> adapters, IEnumerable<JsonObject> factories, RecordingObserver observer, IEnumerable<JsonObject>? ledger, RunManifest? manifest, IEnumerable<JsonObject> resources, JsonValue? batchFailures = null) => FixtureJson.Object(
        ("operation", operation), ("factories", FixtureJson.Array(factories)), ("wires", FixtureJson.Array(adapters.SelectMany(adapter => adapter.Wires))),
        ("telemetry", FixtureJson.Array(observer.Events)), ("ledger", ledger is null ? FixtureJson.Null() : FixtureJson.Array(ledger)),
        ("manifest", manifest is null ? FixtureJson.Null() : Manifest(manifest)), ("resources", FixtureJson.Array(resources)), ("batch_failures", batchFailures ?? FixtureJson.Null()));

    private static JsonObject Operation(string kind, string outcome, JsonValue result, JsonValue error, IEnumerable<AttemptRecord> attempts) => FixtureJson.Object(
        ("kind", FixtureJson.String(kind)), ("outcome", FixtureJson.String(outcome)), ("result", result), ("error", error),
        ("attempts", FixtureJson.Array(attempts.Select(Attempt))), ("request_relation", FixtureJson.String("operation")), ("cancellation_relation", FixtureJson.String("none")));

    private static JsonObject Cancelled(string kind) => FixtureJson.Object(
        ("kind", FixtureJson.String(kind)), ("outcome", FixtureJson.String("cancelled")),
        ("result", FixtureJson.Null()), ("error", FixtureJson.Null()), ("attempts", FixtureJson.Array([])),
        ("request_relation", FixtureJson.String("operation")), ("cancellation_relation", FixtureJson.String("caller_cancelled")));

    private static IEnumerable<AttemptRecord> Attempts(Exception exception) => exception is AllTargetsFailedException aggregate ? aggregate.Attempts : [];
    private static JsonValue BatchFailure(BatchFailure value) => FixtureJson.Object(
        ("batch_index", FixtureJson.Integer(value.BatchIndex)), ("item_count", FixtureJson.Integer(value.ItemCount)),
        ("succeeded", FixtureJson.Boolean(value.Succeeded)), ("error", OptionalString(value.Error)));
    private static JsonValue Attempt(AttemptRecord record) => FixtureJson.Object(("target", record.Target is null ? FixtureJson.Null() : Target(record.Target)), ("outcome", FixtureJson.String(record.Outcome)), ("error", record.Error is null ? FixtureJson.Null() : Snapshot(record.Error.Snapshot())), ("timing", record.Timing is null ? FixtureJson.Null() : Timing(record.Timing)));
    private static JsonValue Target(ResolvedTarget target) => FixtureJson.Object(("provider_id", FixtureJson.String(target.ProviderId)), ("model", FixtureJson.String(target.Model)), ("via_alias", OptionalString(target.ViaAlias)));
    private static JsonValue Vector(EmbeddingVector vector) => FixtureJson.Array(vector.Values.Select(FixtureJson.Number));
    private static JsonValue Item(RankedItem item) => FixtureJson.Object(("index", FixtureJson.Integer(item.Index)), ("document_id", FixtureJson.String(item.DocumentId)), ("score", FixtureJson.Number(item.Score)), ("text", OptionalString(item.Text)));
    private static JsonValue Usage(Usage value) => FixtureJson.Object(
        ("input_tokens", OptionalInteger(value.InputTokens)), ("output_tokens", OptionalInteger(value.OutputTokens)), ("total_tokens", OptionalInteger(value.TotalTokens)),
        ("cache_read_tokens", OptionalInteger(value.CacheReadTokens)), ("cache_write_tokens", OptionalInteger(value.CacheWriteTokens)), ("reasoning_tokens", OptionalInteger(value.ReasoningTokens)),
        ("cost_usd", value.CostUsd is null ? FixtureJson.Null() : FixtureJson.String(value.CostUsd.ToString())), ("search_units", OptionalInteger(value.SearchUnits)),
        ("server_tool_uses", Object(value.ServerToolUses.ToDictionary(pair => pair.Key, pair => FixtureJson.Integer(pair.Value), StringComparer.Ordinal))));
    private static JsonValue Timing(Timing value) => FixtureJson.Object(("started_at", FixtureJson.Number(value.StartedAt)), ("first_token_ms", OptionalNumber(value.FirstTokenMs)), ("total_ms", FixtureJson.Number(value.TotalMs)), ("output_tokens_per_s", OptionalNumber(value.OutputTokensPerS)), ("phases", Object(value.Phases.ToDictionary(pair => pair.Key, pair => FixtureJson.Number(pair.Value), StringComparer.Ordinal))));
    private static JsonValue Space(EmbeddingSpace value) => FixtureJson.Object(("provider_id", FixtureJson.String(value.ProviderId)), ("model", FixtureJson.String(value.Model)), ("model_revision", OptionalString(value.ModelRevision)), ("dimensions", OptionalInteger(value.Dimensions)), ("input_intent_aware", FixtureJson.Boolean(value.InputIntentAware)), ("normalized", OptionalBoolean(value.Normalized)), ("compatibility_id", OptionalString(value.CompatibilityId)));
    private static JsonValue Snapshot(ErrorInfo value) => FixtureJson.Object(("runtime_type", FixtureJson.String(value.TypeName)), ("provider", OptionalString(value.Provider)), ("phase", OptionalString(value.Phase)), ("retryable", FixtureJson.Boolean(value.Retryable)), ("http_status", OptionalInteger(value.HttpStatus)), ("detail", OptionalString(value.Detail)));
    internal static JsonObject LedgerSnapshot(AnyInfer.Capabilities.SpendLedger ledger, string label) => FixtureJson.Object(
        ("label", FixtureJson.String(label)), ("reserved", FixtureJson.String(ledger.Reserved().ToString())),
        ("totals", Totals(ledger.Totals())));
    private static JsonValue Totals(AnyInfer.Capabilities.SpendTotals value) => FixtureJson.Object(
        ("cost", FixtureJson.String(value.Cost.ToString())), ("currency", FixtureJson.String(value.Currency)),
        ("requests", FixtureJson.Integer(value.Requests)), ("unknown_requests", FixtureJson.Integer(value.UnknownRequests)),
        ("input_tokens", FixtureJson.Integer(value.InputTokens)), ("output_tokens", FixtureJson.Integer(value.OutputTokens)),
        ("cache_read_tokens", FixtureJson.Integer(value.CacheReadTokens)));
    private static JsonValue Manifest(RunManifest value) => FixtureJson.Object(
        ("request_relation", FixtureJson.String("operation")), ("format", FixtureJson.String(value.Format)), ("complete", FixtureJson.Boolean(value.Complete)), ("operation", FixtureJson.String(value.Operation)),
        ("route", FixtureJson.Object(("requested", FixtureJson.Array(value.Route.Requested.Select(FixtureJson.String))), ("resolved", OptionalString(value.Route.Resolved)), ("considered", FixtureJson.Array(value.Route.Considered.Select(step => FixtureJson.Object(("target", FixtureJson.String(step.Target)), ("outcome", FixtureJson.String(step.Outcome)), ("reason", FixtureJson.String(step.Reason)))))))),
        ("attempts", FixtureJson.Array(value.Attempts.Select(attempt => FixtureJson.Object(("target", FixtureJson.String(attempt.Target)), ("attempt_number", FixtureJson.Integer(attempt.AttemptNumber)), ("outcome", FixtureJson.String(attempt.Outcome)), ("error", attempt.Error is null ? FixtureJson.Null() : Snapshot(attempt.Error)), ("first_token_ms", OptionalNumber(attempt.FirstTokenMs)), ("total_ms", OptionalNumber(attempt.TotalMs)), ("queued_ms", OptionalNumber(attempt.QueuedMs)), ("retry_reason", OptionalString(attempt.RetryReason)), ("retry_delay_s", OptionalNumber(attempt.RetryDelayS)), ("paced_s", Object(attempt.PacedS.ToDictionary(pair => pair.Key, pair => FixtureJson.Number(pair.Value), StringComparer.Ordinal))))))),
        ("usage", FixtureJson.Object(("input_tokens", OptionalInteger(value.Usage.InputTokens)), ("output_tokens", OptionalInteger(value.Usage.OutputTokens)), ("total_tokens", OptionalInteger(value.Usage.TotalTokens)), ("cache_read_tokens", OptionalInteger(value.Usage.CacheReadTokens)), ("cache_write_tokens", OptionalInteger(value.Usage.CacheWriteTokens)), ("reasoning_tokens", OptionalInteger(value.Usage.ReasoningTokens)), ("cost_usd", OptionalString(value.Usage.CostUsd)), ("estimated_fields", Object(value.Usage.EstimatedFields.ToDictionary(pair => pair.Key, pair => FixtureJson.String(pair.Value), StringComparer.Ordinal))), ("search_units", OptionalInteger(value.Usage.SearchUnits)))),
        ("timing", FixtureJson.Object(("first_token_ms", OptionalNumber(value.Timing.FirstTokenMs)), ("total_ms", OptionalNumber(value.Timing.TotalMs)), ("output_tokens_per_s", OptionalNumber(value.Timing.OutputTokensPerS)), ("phases", Object(value.Timing.Phases.ToDictionary(pair => pair.Key, pair => FixtureJson.Number(pair.Value), StringComparer.Ordinal))))),
        ("notes", FixtureJson.Array(value.Notes.Select(FixtureJson.String))), ("embedding_space", value.EmbeddingSpace is null ? FixtureJson.Null() : Space(value.EmbeddingSpace)), ("payloads", FixtureJson.Null()));
    private static JsonObject Object(IReadOnlyDictionary<string, JsonValue> values) => FixtureJson.Object(values.Select(pair => (pair.Key, pair.Value)).ToArray());
    private static JsonValue OptionalRaw(JsonElement value) => value.ValueKind == JsonValueKind.Null ? FixtureJson.Null() : FixtureJson.Read(value);
    private static JsonValue OptionalUsage(JsonElement value) => value.ValueKind == JsonValueKind.Null ? FixtureJson.Null() : Usage(ReadUsage(value));
    private static JsonValue OptionalString(JsonElement value, string name) => value.GetProperty(name).ValueKind == JsonValueKind.Null ? FixtureJson.Null() : FixtureJson.String(value.GetProperty(name).GetString()!);
    private static JsonValue OptionalString(string? value) => value is null ? FixtureJson.Null() : FixtureJson.String(value);
    private static JsonValue OptionalInteger(JsonElement value, string name) => value.GetProperty(name).ValueKind == JsonValueKind.Null ? FixtureJson.Null() : FixtureJson.Integer(value.GetProperty(name).GetInt32());
    private static JsonValue OptionalInteger(int? value) => value is null ? FixtureJson.Null() : FixtureJson.Integer(value.Value);
    private static JsonValue OptionalInteger(long? value) => value is null ? FixtureJson.Null() : FixtureJson.Integer(value.Value);
    private static JsonValue OptionalBoolean(JsonElement value, string name) => value.GetProperty(name).ValueKind == JsonValueKind.Null ? FixtureJson.Null() : FixtureJson.Boolean(value.GetProperty(name).GetBoolean());
    private static JsonValue OptionalBoolean(bool? value) => value is null ? FixtureJson.Null() : FixtureJson.Boolean(value.Value);
    private static JsonValue OptionalNumber(double? value) => value is null ? FixtureJson.Null() : FixtureJson.Number(value.Value);
    private static JsonValue OptionalMoney(PeterO.Numbers.EDecimal? value) => value is null ? FixtureJson.Null() : FixtureJson.String(value.ToString());
    private static string InputType(EmbeddingInputIntent value) => value.ToString().ToLowerInvariant();
    private static Usage ReadUsage(JsonElement value) => new(NegativeOne(value, "input_tokens"), NegativeOne(value, "output_tokens"), NegativeOne(value, "total_tokens"), NegativeOne(value, "cache_read_tokens"), NegativeOne(value, "cache_write_tokens"), NegativeOne(value, "reasoning_tokens"), CostUsd: null, SearchUnits: NegativeOne(value, "search_units"), ServerToolUses: value.GetProperty("server_tool_uses").EnumerateObject().ToDictionary(pair => pair.Name, pair => pair.Value.GetInt64(), StringComparer.Ordinal));
    private static long? NegativeOne(JsonElement value, string name) => value.GetProperty(name).ValueKind == JsonValueKind.Null ? null : value.GetProperty(name).GetInt64();
}
