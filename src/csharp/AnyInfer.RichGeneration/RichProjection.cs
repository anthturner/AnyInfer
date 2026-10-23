using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Encodings.Web;
using AnyInfer;
using AnyInfer.Events;
using AnyInfer.Json;
using AnyInfer.Manifest;
using AnyInfer.Providers;

/// <summary>Projects only public observations; no fixture result is used as an oracle.</summary>
internal static class RichProjection
{
    private static readonly JsonSerializerOptions CanonicalStrings = new() { Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping };
    internal static Dictionary<string, object?> Obj(params (string Key, object? Value)[] fields) => fields.ToDictionary(static x => x.Key, static x => x.Value, StringComparer.Ordinal);
    internal static string Hash(ReadOnlySpan<byte> bytes) => Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
    internal static object? Raw(JsonValue? value) => value is null ? null : JsonSerializer.Deserialize<object>(JsonWriter.Write(value));
    internal static object? Raw(JsonElement value) => JsonSerializer.Deserialize<object>(value.GetRawText());

    // The public builtin's outgoing JSON is captured before this evidence-only projection.
    // Keep media metadata in place while publishing inline bytes by length and digest.
    internal static object? HttpBody(JsonElement value) => HttpBodyValue(value);

    private static object? HttpBodyValue(JsonElement value)
    {
        if (value.ValueKind == JsonValueKind.Object)
        {
            var projected = new Dictionary<string, object?>(StringComparer.Ordinal);
            foreach (var property in value.EnumerateObject())
            {
                var item = property.Value;
                if ((property.Name is "data" or "file_data") && item.ValueKind == JsonValueKind.String &&
                    TryMediaBytes(item.GetString()!, out var bytes))
                    projected.Add(property.Name, Obj(("byte_evidence", ByteEvidence(bytes))));
                else projected.Add(property.Name, HttpBodyValue(item));
            }
            return projected;
        }
        if (value.ValueKind == JsonValueKind.Array) return value.EnumerateArray().Select(HttpBodyValue).ToArray();
        if (value.ValueKind == JsonValueKind.String)
        {
            var text = value.GetString()!;
            if (text.StartsWith("data:", StringComparison.Ordinal) && text.Contains(";base64,", StringComparison.Ordinal))
            {
                if (!TryMediaBytes(text, out var bytes)) throw new FormatException("Invalid inline HTTP media data URL.");
                return Obj(("byte_evidence", ByteEvidence(bytes)));
            }
        }
        return Raw(value);
    }

    private static object ByteEvidence(byte[] bytes) => Obj(("length", bytes.Length), ("sha256", Hash(bytes)));
    private static bool TryMediaBytes(string value, out byte[] bytes)
    {
        var encoded = value.StartsWith("data:", StringComparison.Ordinal) && value.Contains(";base64,", StringComparison.Ordinal)
            ? value[(value.IndexOf(',') + 1)..] : value;
        try { bytes = Convert.FromBase64String(encoded); return true; }
        catch (FormatException) { bytes = []; return false; }
    }

    private static string Canon(JsonElement value) => value.ValueKind switch
    {
        JsonValueKind.Object => "{" + string.Join(",", value.EnumerateObject().OrderBy(static x => x.Name, StringComparer.Ordinal)
            .Select(x => JsonSerializer.Serialize(x.Name, CanonicalStrings) + ":" + Canon(x.Value))) + "}",
        JsonValueKind.Array => "[" + string.Join(",", value.EnumerateArray().Select(Canon)) + "]",
        JsonValueKind.String => JsonSerializer.Serialize(value.GetString(), CanonicalStrings),
        JsonValueKind.Number => value.GetRawText(),
        JsonValueKind.True => "true",
        JsonValueKind.False => "false",
        _ => "null",
    };

    internal static object Data(JsonValue value)
    {
        using var parsed = JsonDocument.Parse(JsonWriter.Write(value));
        return Data(parsed.RootElement);
    }

    internal static object Data(JsonElement value)
    {
        var canonical = Canon(value);
        return Obj(("canonical_json", canonical), ("sha256", Hash(Encoding.UTF8.GetBytes(canonical))));
    }

    private static object? Bytes(IReadOnlyList<byte>? value) => value is null ? null : Obj(("length", value.Count), ("sha256", Hash(value.ToArray())));
    internal static object Target(ResolvedTarget value) => Obj(("provider_id", value.ProviderId), ("model", value.Model), ("via_alias", value.ViaAlias));
    internal static object? TargetOrNull(ResolvedTarget? value) => value is null ? null : Target(value);
    private static object TargetText(string? value)
    {
        if (value is null) throw new InvalidOperationException("A present target was expected.");
        var split = value.Split(':', 2);
        return Obj(("provider_id", split[0]), ("model", split.Length == 2 ? split[1] : ""), ("via_alias", null));
    }

    internal static object Error(Exception error) => error is AnyInferException sdk
        ? Obj(("type_name", sdk.GetType().Name), ("provider", sdk.Provider), ("phase", sdk.Phase), ("retryable", sdk.Retryable),
            ("retry_after_s", sdk.RetryAfterS), ("http_status", sdk.HttpStatus), ("detail", sdk.Detail), ("hint", sdk.Hint))
        : Obj(("type_name", error.GetType().Name), ("provider", null), ("phase", null), ("retryable", false),
            ("retry_after_s", null), ("http_status", null), ("detail", error.Message), ("hint", null));

    private static object ErrorInfo(AnyInfer.ErrorInfo value) => Obj(("type_name", value.TypeName), ("provider", value.Provider),
        ("phase", value.Phase), ("retryable", value.Retryable), ("retry_after_s", null), ("http_status", value.HttpStatus), ("detail", value.Detail), ("hint", null));

    internal static object Timing(Timing? value) => Obj(("first_token_present", value?.FirstTokenMs is not null),
        ("total_present", value is not null), ("phase_order", value?.Phases.Keys.ToArray() ?? []));
    internal static object Usage(Usage? value) => Obj(("input_tokens", value?.InputTokens), ("output_tokens", value?.OutputTokens),
        ("total_tokens", value?.TotalTokens), ("cache_read_tokens", value?.CacheReadTokens), ("cache_write_tokens", value?.CacheWriteTokens),
        ("reasoning_tokens", value?.ReasoningTokens), ("cost_usd", value?.CostUsd?.ToString()), ("search_units", value?.SearchUnits),
        ("server_tool_uses", (value?.ServerToolUses ?? new Dictionary<string, long>()).OrderBy(static x => x.Key, StringComparer.Ordinal)
            .Select(static x => Obj(("kind", x.Key), ("uses", x.Value))).ToArray()));
    private static object Citation(Citation value) => Obj(("start_index", value.StartIndex), ("end_index", value.EndIndex),
        ("quoted_text", value.QuotedText), ("document_index", value.DocumentIndex), ("title", value.Title), ("uri", value.Uri));
    private static object ServerUse(ServerToolUse value) => Obj(("kind", value.Kind), ("uses", value.Uses));
    private static object Logprob(TokenLogprob value) => Obj(("token", value.Token), ("logprob", value.Logprob),
        ("top", value.Top.Select(Logprob).ToArray()), ("bytes", value.Bytes?.Select(static b => (int)b).ToArray()));
    private static object ToolCall(ToolCall value) => Obj(("id", value.Id), ("name", value.Name), ("arguments", Data(value.Arguments)));
    private static object Attempt(AttemptRecord value, int index) => Obj(("target", TargetOrNull(value.Target)), ("attempt_number", index),
        ("outcome", value.Outcome), ("error", value.Error is null ? null : ErrorInfo(value.Error.Snapshot())), ("timing", Timing(value.Timing)));

    internal static object Result(Generation value) => Obj(("text", value.Text), ("tool_calls", value.ToolCalls.Select(ToolCall).ToArray()),
        ("target", TargetOrNull(value.Target)), ("finish_reason", value.FinishReason), ("usage", Usage(value.Usage)),
        ("logprobs", value.Logprobs.Select(Logprob).ToArray()), ("citations", value.Citations.Select(Citation).ToArray()),
        ("server_tool_uses", value.ServerToolUses.Select(ServerUse).ToArray()), ("raw", Raw(value.Raw)),
        ("timing", Timing(value.Timing)), ("attempts", value.Attempts.Select((attempt, index) => Attempt(attempt, index + 1)).ToArray()),
        ("warnings", value.Warnings));

    internal static object Event(StreamEvent value, int failedAttemptNumber) => value switch
    {
        TextDelta e => Obj(("type", "TextDelta"), ("text", e.Text)),
        ReasoningDelta e => Obj(("type", "ReasoningDelta"), ("text", e.Text)),
        ToolCallDelta e => Obj(("type", "ToolCallDelta"), ("index", e.Index), ("call_id", e.CallId), ("name", e.Name), ("arguments_fragment", e.ArgumentsFragment)),
        CitationDelta e => Obj(("type", "CitationDelta"), ("citation", Citation(e.Citation))),
        ServerToolDelta e => Obj(("type", "ServerToolDelta"), ("kind", e.Kind), ("status", e.Status),
            ("sources", e.Sources.Select(static source => Obj(("url", source.Url), ("title", source.Title))).ToArray()),
            ("output", e.Output), ("detail", e.Detail)),
        UsageUpdate e => Obj(("type", "UsageUpdate"), ("usage", Usage(e.Usage))),
        TimingMark e => Obj(("type", "TimingMark"), ("name", e.Name)),
        AttemptFailed e => Obj(("type", "AttemptFailed"), ("record", Attempt(e.Record, failedAttemptNumber))),
        StreamEnded e => Obj(("type", "StreamEnded"), ("result", Result(e.Result))),
        _ => throw new InvalidOperationException("Unknown public generation event: " + value.GetType().Name),
    };

    private static object Part(ContentPart value) => value switch
    {
        Text p => Obj(("type", "text"), ("text", p.Value)),
        ToolCall p => Obj(("type", "tool_call"), ("id", p.Id), ("name", p.Name), ("arguments", Data(p.Arguments))),
        ToolResult p => Obj(("type", "tool_result"), ("call_id", p.CallId), ("content", p.Content), ("is_error", p.IsError)),
        ImagePart p => Obj(("type", "image"), ("data", Bytes(p.Data)), ("url", p.Url), ("media_type", p.MediaType), ("detail", p.Detail)),
        DocumentPart p => Obj(("type", "document"), ("data", Bytes(p.Data)), ("url", p.Url), ("media_type", p.MediaType), ("filename", p.Filename)),
        AudioPart p => Obj(("type", "audio"), ("data", Bytes(p.Data)), ("media_type", p.MediaType)),
        VideoPart p => Obj(("type", "video"), ("data", Bytes(p.Data)), ("url", p.Url), ("media_type", p.MediaType),
            ("start_offset_s", p.StartOffsetS), ("end_offset_s", p.EndOffsetS), ("fps", p.Fps)),
        _ => throw new InvalidOperationException("Unknown wire message part: " + value.GetType().Name),
    };

    internal static object Wire(WireRequest value) => Obj(("model", value.Model),
        ("messages", value.Messages.Select(static message => Obj(("role", message.Role), ("content", message.Content.Select(Part).ToArray()))).ToArray()),
        ("sampling", Obj(("temperature", value.Sampling.Temperature), ("top_p", value.Sampling.TopP),
            ("max_output_tokens", value.Sampling.MaxOutputTokens), ("stop", value.Sampling.Stop ?? []), ("seed", value.Sampling.Seed),
            ("presence_penalty", value.Sampling.PresencePenalty), ("frequency_penalty", value.Sampling.FrequencyPenalty))),
        ("reasoning_wire", Data(value.ReasoningWire)), ("mechanism", value.Mechanism),
        ("wire_schema", value.Schema is null ? null : Data(value.Schema)), ("schema_name", value.SchemaName),
        ("tools", value.Tools.Select(static tool => Obj(("name", tool.Name), ("description", tool.Description),
            ("parameters", Data(tool.Parameters)), ("annotations", Obj(("title", tool.Annotations.Title),
                ("read_only", tool.Annotations.ReadOnly), ("destructive", tool.Annotations.Destructive),
                ("idempotent", tool.Annotations.Idempotent), ("open_world", tool.Annotations.OpenWorld))))).ToArray()),
        ("tool_choice", value.ToolChoice), ("stream", value.Stream), ("timeout_s", value.TimeoutS),
        ("max_response_bytes", value.MaxResponseBytes), ("cache_marks", value.CacheMarks),
        ("server_tools", value.ServerTools.Select(static tool => Obj(("kind", tool.Kind), ("max_uses", tool.MaxUses))).ToArray()),
        ("cite_documents", value.CiteDocuments), ("logprobs", value.Logprobs), ("extra_options", Data(value.ExtraOptions)),
        ("session_state", value.SessionState is null
            ? Obj(("state", "null"))
            : Obj(("state", "value"), ("value", Data(value.SessionState)))));

    internal static object Evidence(JsonValue value, string surface)
    {
        var paths = new List<string>();
        var leaves = new List<(string Path, string Value)>();
        Visit(value, "", paths, leaves);
        PrivacyPublicationGuard.AssertSafe(surface, leaves);
        return Obj(("field_paths", paths.OrderBy(static p => p, StringComparer.Ordinal).ToArray()),
            ("string_leaves", leaves.OrderBy(static p => p.Path, StringComparer.Ordinal).Select(static p =>
            {
                var leaf = PrivacyPublicationGuard.Evidence(p.Path, p.Value);
                return Obj(("path", leaf.Path), ("utf8_length", leaf.Utf8Length), ("sha256", leaf.Sha256));
            }).ToArray()));
    }

    private static void Visit(JsonValue value, string path, List<string> paths, List<(string Path, string Value)> leaves)
    {
        switch (value)
        {
            case JsonObject obj:
                foreach (var property in obj.Properties)
                {
                    var child = PrivacyPublicationGuard.Pointer(path, property.Name);
                    paths.Add(child); Visit(property.Value, child, paths, leaves);
                }
                break;
            case JsonArray array:
                for (var i = 0; i < array.Items.Count; i++)
                {
                    var child = PrivacyPublicationGuard.Pointer(path, i.ToString(System.Globalization.CultureInfo.InvariantCulture));
                    paths.Add(child); Visit(array.Items[i], child, paths, leaves);
                }
                break;
            case JsonString text: leaves.Add((path, text.Value)); break;
        }
    }

    internal static object Telemetry(TelemetryEvent value)
    {
        // Inspect the actual product serialization before selecting a stable projection.
        // An unknown event must never evade the publication guard or disappear from output.
        var evidence = Evidence(value.ToDictionary(), "telemetry:" + value.GetType().Name);
        object stable = value switch
        {
            RequestStarted e => Obj(("event", "RequestStarted"), ("request_id", e.RequestId), ("targets", e.Targets),
                ("metadata", e.Metadata.OrderBy(static p => p.Key, StringComparer.Ordinal).Select(static p => Obj(("key", p.Key), ("value", p.Value))).ToArray()),
                ("operation", e.Operation), ("prompt_text", e.PromptText)),
            TargetResolved e => Obj(("event", "TargetResolved"), ("request_id", e.RequestId), ("target", Target(e.Target))),
            AttemptStarted e => Obj(("event", "AttemptStarted"), ("request_id", e.RequestId), ("target", Target(e.Target)), ("attempt_number", e.AttemptNumber)),
            UsageEstimated e => Obj(("event", "UsageEstimated"), ("request_id", e.RequestId), ("target", Target(e.Target)),
                ("field_name", e.FieldName), ("method", e.Method)),
            RetryScheduled e => Obj(("event", "RetryScheduled"), ("request_id", e.RequestId), ("target", Target(e.Target)),
                ("attempt_number", e.AttemptNumber), ("delay_s", e.DelayS), ("error", ErrorInfo(e.Error))),
            FirstToken e => Obj(("event", "FirstToken"), ("request_id", e.RequestId), ("target", Target(e.Target)), ("at_ms_present", true)),
            AttemptCompleted e => Obj(("event", "AttemptCompleted"), ("request_id", e.RequestId), ("target", Target(e.Target)),
                ("usage", Usage(e.Usage)), ("timing", Timing(e.Timing)), ("finish_reason", e.FinishReason)),
            RequestCompleted e => Obj(("event", "RequestCompleted"), ("request_id", e.RequestId), ("target", Target(e.Target)),
                ("usage", Usage(e.Usage)), ("timing", Timing(e.Timing)), ("repair_attempts", e.RepairAttempts), ("response_text", e.ResponseText)),
            RepairAttempted e => Obj(("event", "RepairAttempted"), ("request_id", e.RequestId), ("target", Target(e.Target)),
                ("attempt_number", e.AttemptNumber), ("mechanism", e.Mechanism), ("errors", e.Errors), ("raw_text", e.RawText)),
            FallbackTriggered e => Obj(("event", "FallbackTriggered"), ("request_id", e.RequestId), ("from_target", Target(e.FromTarget)),
                ("to_target", e.ToTarget), ("error", e.Error is null ? null : ErrorInfo(e.Error))),
            ParameterDropped e => Obj(("event", "ParameterDropped"), ("request_id", e.RequestId), ("target", Target(e.Target)),
                ("parameter", e.Parameter), ("reason", e.Reason)),
            RequestFailed e => Obj(("event", "RequestFailed"), ("request_id", e.RequestId), ("error", ErrorInfo(e.Error))),
            _ => throw new InvalidOperationException("Unrepresented actual telemetry event: " + value.GetType().Name),
        };
        return Obj(("stable", stable), ("serialized", evidence));
    }

    internal static void CaptureUnknownTelemetry(string caseId, IEnumerable<TelemetryEvent> events, List<object> unknownEvents)
    {
        foreach (var value in events)
        {
            var serialized = value.ToDictionary();
            _ = Evidence(serialized, "telemetry:" + value.GetType().Name);
            if (!RepresentedTelemetry(value))
                unknownEvents.Add(Obj(("case_id", caseId), ("event_type", value.GetType().Name), ("serialized", Raw(serialized))));
        }
    }

    private static bool RepresentedTelemetry(TelemetryEvent value) => value is
        RequestStarted or TargetResolved or AttemptStarted or UsageEstimated or RetryScheduled or FirstToken or AttemptCompleted or
        RequestCompleted or RepairAttempted or FallbackTriggered or ParameterDropped or RequestFailed;

    internal static object? Manifest(RunManifest? value)
    {
        if (value is null) return null;
        var request = value.Request;
        return Obj(("operation", value.Operation), ("target", value.Route.Resolved is null ? null : TargetText(value.Route.Resolved)),
            ("request", Obj(("message_count", request.MessageCount),
                ("role_counts", request.RoleCounts.OrderBy(static p => p.Key, StringComparer.Ordinal)
                    .Select(static p => Obj(("role", p.Key), ("count", p.Value))).ToArray()),
                ("schema_present", request.SchemaPresent), ("schema_name", request.SchemaName),
                ("tool_names", request.ToolNames), ("tool_choice", request.ToolChoice), ("metadata_keys", request.MetadataKeys))),
            ("payloads", value.Payloads is null ? "null" : "present"), ("serialized", Evidence(value.ToDictionary(), "manifest")));
    }
}
