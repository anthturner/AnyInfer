using System.Text;
using System.Runtime.ExceptionServices;
using System.Numerics;
using AnyInfer.Core;
using AnyInfer.Internal;
using AnyInfer.Json;
using AnyInfer.Providers;
using AnyInfer.Schema;

namespace AnyInfer.Conformance;

/// <summary>Projects retained native execution facts into a comparison-only observation.</summary>
internal static class Projection
{
    internal static JsonObject Project(NativeRun run)
    {
        return ProjectCore(run, requireMirror: true);
    }

    internal static JsonObject ProjectMirror(NativeRun run)
    {
        return ProjectCore(run, requireMirror: false);
    }

    private static JsonObject ProjectCore(NativeRun run, bool requireMirror)
    {
        ArgumentNullException.ThrowIfNull(run);
        ValidateRun(run, requireMirror);

        var calls = ProjectCalls(run);
        var events = ProjectEvents(run.Events);
        var outcome = ProjectOutcome(run);
        var properties = new List<JsonProperty>
        {
            Property("status", String("observed")),
            Property("calls", new JsonArray(calls)),
            Property("clock_advances_ms", new JsonArray(run.Clock.DelaysSeconds.Select(ProjectMilliseconds))),
            Property("telemetry", ProjectTelemetry(run.Capture.Telemetry)),
            Property("events", new JsonArray(events)),
            Property("outcome", outcome),
            Property("accounting", JsonNull.Instance),
        };

        return new JsonObject(properties);
    }

    private static void ValidateRun(NativeRun run, bool requireMirror)
    {
        if (string.IsNullOrWhiteSpace(run.CaseId))
        {
            throw Unavailable("native run has no case identity");
        }

        if (!run.Capture.IsAvailable)
        {
            throw Unavailable("native capture is unavailable: " + string.Join("; ", run.Capture.UnavailableReasons));
        }

        var entries = run.Capture.Entries;
        if (entries.Count != run.AdapterCallCount)
        {
            throw Unavailable("captured entry count does not match adapter calls");
        }

        Guid? operationId = null;
        for (var index = 0; index < entries.Count; index++)
        {
            var entry = entries[index];
            if (entry.Ordinal != index + 1 || entry.OperationId == Guid.Empty || !ReferenceEquals(entry.Capture, run.Capture))
            {
                throw Unavailable("captured entry provenance is incomplete or unordered");
            }

            operationId ??= entry.OperationId;
            if (operationId != entry.OperationId)
            {
                throw Unavailable("captured entries belong to different operations");
            }
        }

        foreach (var assessment in run.Capture.Assessments)
        {
            if (operationId is not null && assessment.OperationId != operationId)
            {
                throw Unavailable("captured assessment belongs to another operation");
            }

            if (assessment.SelectedFindings.Any(selected => !assessment.AllFindings.Any(candidate => ReferenceEquals(candidate, selected))))
            {
                throw Unavailable("selected native findings are not retained from the actual assessment");
            }
        }

        var expectsMirror = string.Equals(run.CaseId, "streaming/buffered-equals-streamed", StringComparison.Ordinal);
        if (requireMirror && expectsMirror && run.Mirror is null)
        {
            throw Unavailable("buffered mirror is missing");
        }

        if (run.Mirror is not null)
        {
            if (!expectsMirror ||
                !string.Equals(run.Mirror.CaseId, run.CaseId, StringComparison.Ordinal) ||
                string.Equals(run.ConsumeMode, "buffered", StringComparison.Ordinal) ||
                !string.Equals(run.Mirror.ConsumeMode, "buffered", StringComparison.Ordinal) ||
                ReferenceEquals(run.Mirror, run) || ReferenceEquals(run.Mirror.Capture, run.Capture))
            {
                throw Unavailable("buffered mirror mode or capture identity is invalid");
            }

            var mirrorEntries = run.Mirror.Capture.Entries;
            if (entries.Any(entry => mirrorEntries.Any(other => ReferenceEquals(entry, other) || entry.OperationId == other.OperationId)))
            {
                throw Unavailable("buffered mirror did not retain fresh operation and entry identities");
            }
        }
    }
    private static IReadOnlyList<JsonValue> ProjectCalls(NativeRun run)
    {
        var entries = run.Capture.Entries;
        var repairs = run.Capture.Repairs;
        var calls = new List<JsonValue>(entries.Count);
        for (var index = 0; index < entries.Count; index++)
        {
            var entry = entries[index];
            var role = entry.Role switch
            {
                EntryRole.Original => "original",
                EntryRole.Correction => "correction",
                _ => throw Unavailable("captured entry has an unknown role"),
            };

            if (entry.Role == EntryRole.Original && entry.RepairAssessment is not null)
            {
                throw Unavailable("original entry retained a repair assessment");
            }

            if (entry.Request.Messages.Count == 0 && entry.Role == EntryRole.Correction)
            {
                throw Unavailable("correction entry has no wire messages");
            }

            var fields = new List<JsonProperty>
            {
                Property("model", String(entry.Request.Model)),
                Property("role", String(role)),
                Property("mechanism", NullableString(entry.Request.Mechanism)),
                Property("timeout_s", Number(entry.Request.TimeoutS)),
                Property("max_response_bytes", Integer(entry.Request.MaxResponseBytes)),
                Property("messages", ProjectMessages(entry.Request.Messages)),
            };

            if (entry.Role == EntryRole.Correction)
            {
                if (index == 0)
                {
                    throw Unavailable("correction entry has no source entry");
                }

                var assessment = entry.RepairAssessment ?? throw Unavailable("correction entry has no assessment");
                var source = entries[index - 1];
                if (!run.Capture.Assessments.Any(candidate => ReferenceEquals(candidate, assessment)) ||
                    assessment.OperationId != entry.OperationId ||
                    assessment.SourceEntryOrdinal != source.Ordinal ||
                    !assessment.SelectedFindings.All(selected => assessment.AllFindings.Any(candidate => ReferenceEquals(candidate, selected))))
                {
                    throw Unavailable("correction assessment provenance is inconsistent");
                }

                var preparations = repairs.Where(preparation => ReferenceEquals(preparation.Assessment, assessment)).ToArray();
                if (preparations.Length != 1 ||
                    !string.Equals(preparations[0].ResponseText, AdapterText(source), StringComparison.Ordinal) ||
                    !MessageListsEqual(PreparedWireMessages(preparations[0], entry.Request), entry.Request.Messages))
                {
                    throw Unavailable("correction preparation and wire request are not causally linked");
                }

                fields.Add(Property("issues", ProjectIssues(assessment.Issues)));
            }

            calls.Add(new JsonObject(fields));
        }

        return calls;
    }

    private static JsonArray ProjectMessages(IReadOnlyList<Message> messages)
    {
        var projected = new List<JsonValue>(messages.Count);
        foreach (var message in messages)
        {
            var text = new StringBuilder();
            foreach (var part in message.Content)
            {
                if (part is not Text textPart)
                {
                    throw Unavailable("entered wire message contains non-text content");
                }

                text.Append(textPart.Value);
            }

            projected.Add(new JsonObject([
                Property("role", String(message.Role)),
                Property("text", String(text.ToString())),
            ]));
        }

        return new JsonArray(projected);
    }

    private static JsonArray ProjectIssues(IReadOnlyList<Issue> issues)
    {
        return new JsonArray(issues.Select(ProjectIssue));
    }

    private static JsonObject ProjectIssue(Issue issue)
    {
        return new JsonObject([
            Property("rule", String(issue.Rule)),
            Property("instance_path", ProjectPath(issue.InstancePath)),
            Property("schema_path", ProjectPath(issue.SchemaPath)),
            Property("params", issue.Parameters),
        ]);
    }

    private static JsonValue ProjectPath(IReadOnlyList<object>? path)
    {
        if (path is null)
        {
            return JsonNull.Instance;
        }

        return new JsonArray(path.Select<object, JsonValue>(static segment => segment switch
        {
            string text => String(text),
            int index => Integer(index),
            _ => throw Unavailable("native issue path contains an unsupported segment"),
        }));
    }

    private static IReadOnlyList<JsonValue> ProjectEvents(IReadOnlyList<StreamEvent> events)
    {
        var projected = new List<JsonValue>();
        foreach (var generationEvent in events)
        {
            switch (generationEvent)
            {
                case TimingMark mark when mark.Name is "attempt_start" or "first_token":
                    projected.Add(new JsonObject([Property("timing_mark", String(mark.Name))]));
                    break;
                case TextDelta text:
                    if (projected.LastOrDefault() is JsonObject { } previous &&
                        previous.TryGetValue("text", out var previousText) && previousText is JsonString value)
                    {
                        projected[^1] = new JsonObject([Property("text", String(value.Value + text.Text))]);
                    }
                    else
                    {
                        projected.Add(new JsonObject([Property("text", String(text.Text))]));
                    }

                    break;
                case UsageUpdate usage:
                    projected.Add(new JsonObject([Property("usage_update", ProjectUsage(usage.Usage, includeNulls: true))]));
                    break;
                case AttemptFailed failed:
                    projected.Add(new JsonObject([Property("attempt_failed", ProjectAttempt(failed.Record, includeTarget: false, fullError: false))]));
                    break;
                case StreamEnded:
                    projected.Add(new JsonObject([Property("stream_ended", new JsonBoolean(true))]));
                    break;
                default:
                    throw Unavailable("native run emitted an unknown public event");
            }
        }

        return projected;
    }

    private static JsonObject ProjectTelemetry(IReadOnlyList<TelemetryObservation> telemetry)
    {
        var repairs = new List<JsonValue>();
        var dropped = new List<JsonValue>();
        foreach (var observation in telemetry)
        {
            switch (observation.Name)
            {
                case "repair_attempted":
                    if (observation.AttemptNumber is null)
                    {
                        throw Unavailable("repair telemetry lacks an attempt number");
                    }

                    repairs.Add(new JsonObject([Property("attempt_number", Integer(observation.AttemptNumber.Value))]));
                    break;
                case "parameter_dropped":
                    if (observation.Parameter is null)
                    {
                        throw Unavailable("parameter telemetry lacks its parameter name");
                    }

                    dropped.Add(new JsonObject([Property("parameter", String(observation.Parameter))]));
                    break;
                default:
                    throw Unavailable("native capture retained an unknown telemetry observation");
            }
        }

        return new JsonObject([
            Property("repair_attempted", new JsonArray(repairs)),
            Property("parameter_dropped", new JsonArray(dropped)),
        ]);
    }

    private static JsonObject ProjectOutcome(NativeRun run)
    {
        if (run.DeliberateCancellation)
        {
            if (run.TerminalException is not OperationCanceledException ||
                run.Result is not null ||
                run.Events.Any(static item => item is StreamEnded))
            {
                throw Unavailable("deliberate cancellation facts are inconsistent");
            }

            return new JsonObject([Property("error", ProjectCancelledError())]);
        }

        if (run.Result is not null)
        {
            if (run.TerminalException is not null)
            {
                throw Unavailable("native run retained both a result and a terminal exception");
            }

            return new JsonObject([Property("result", ProjectResult(run.Result))]);
        }

        if (run.TerminalException is not null)
        {
            if (run.TerminalException is OperationCanceledException || run.TerminalException is not AnyInferException)
            {
                ExceptionDispatchInfo.Capture(run.TerminalException).Throw();
            }

            return new JsonObject([Property("error", ProjectError(run.TerminalException))]);
        }

        if (run.ConsumeMode == "close_without_advance" && run.Events.Count == 0 && run.Capture.Entries.Count == 0)
        {
            return new JsonObject([Property("none", new JsonBoolean(true))]);
        }

        throw Unavailable("native run has no terminal outcome");
    }
    private static JsonObject ProjectCancelledError() => new([
        Property("category", String("cancelled")),
        Property("retryable", new JsonBoolean(false)),
        Property("retry_after_s", JsonNull.Instance),
        Property("http_status", JsonNull.Instance),
        Property("phase", JsonNull.Instance),
    ]);

    private static IReadOnlyList<Message> PreparedWireMessages(RepairPreparation preparation, WireRequest request)
    {
        var messages = preparation.Messages;
        if (request.Schema is not null && request.Mechanism is "prompt" or "json_mode")
        {
            messages = SchemaPromptRenderer.InjectPrompt(messages, request.Schema);
        }

        return messages;
    }
    private static string AdapterText(EntryContext entry)
    {
        return string.Concat(entry.AdapterEvents.OfType<AdapterTextDelta>().Select(static item => item.Text));
    }
    private static JsonObject ProjectResult(Generation result)
    {
        return new JsonObject([
            Property("text", String(result.Text)),
            Property("structured", result.Structured ?? JsonNull.Instance),
            Property("target", result.Target is null ? JsonNull.Instance : ProjectTarget(result.Target)),
            Property("finish_reason", NullableString(result.FinishReason)),
            Property("usage", ProjectUsage(result.Usage ?? new Usage(), includeNulls: true)),
            Property("timing", ProjectTiming(result.Timing)),
            Property("structured_mechanism", NullableString(result.StructuredMechanism)),
            Property("repair_attempts", Integer(result.RepairAttempts)),
            Property("attempts", new JsonArray(result.Attempts.Select(static attempt => ProjectAttempt(attempt, includeTarget: true, fullError: false)))),
            Property("warnings", new JsonArray(result.Warnings.Select(String))),
        ]);
    }

    private static JsonObject ProjectTarget(ResolvedTarget target) => new([
        Property("provider_id", String(target.ProviderId)),
        Property("model", String(target.Model)),
    ]);

    private static JsonObject ProjectTiming(Timing? timing) => new([
        Property("first_token_ms", timing?.FirstTokenMs is null ? JsonNull.Instance : Number(timing.FirstTokenMs.Value)),
        Property("total_ms", timing is null ? JsonNull.Instance : Number(timing.TotalMs)),
    ]);

    private static JsonObject ProjectAttempt(AttemptRecord attempt, bool includeTarget, bool fullError)
    {
        var fields = new List<JsonProperty>();
        if (includeTarget && attempt.Target is not null)
        {
            fields.Add(Property("target", String(attempt.Target.ProviderId + ":" + attempt.Target.Model)));
        }

        fields.Add(Property("outcome", String(attempt.Outcome)));
        if (attempt.Error is not null)
        {
            fields.Add(Property("error", fullError ? ProjectError(attempt.Error) : ProjectAttemptError(attempt.Error)));
        }

        return new JsonObject(fields);
    }

    private static JsonObject ProjectAttemptError(AnyInferException error) => new([
        Property("category", String(error.Category)),
    ]);

    private static JsonObject ProjectError(Exception exception)
    {
        if (exception is AnyInferException error)
        {
            var fields = new List<JsonProperty>
            {
                Property("category", String(error.Category)),
                Property("retryable", new JsonBoolean(error.Retryable)),
                Property("retry_after_s", error.RetryAfterS is null ? JsonNull.Instance : Number(error.RetryAfterS.Value)),
                Property("http_status", error.HttpStatus is null ? JsonNull.Instance : Integer(error.HttpStatus.Value)),
                Property("phase", NullableString(error.Phase)),
            };
            if (error is SchemaViolationException schemaViolation)
            {
                fields.Add(Property("issues", ProjectIssues(schemaViolation.Issues)));
            }

            return new JsonObject(fields);
        }

        if (exception is OperationCanceledException)
        {
            return new JsonObject([
                Property("category", String("cancelled")),
                Property("retryable", new JsonBoolean(false)),
                Property("retry_after_s", JsonNull.Instance),
                Property("http_status", JsonNull.Instance),
                Property("phase", JsonNull.Instance),
            ]);
        }

        throw Unavailable("native run terminated with an unprojectable exception");
    }

    private static JsonObject ProjectUsage(Usage usage, bool includeNulls)
    {
        var fields = new List<JsonProperty>();
        AddUsage("input_tokens", usage.InputTokens);
        AddUsage("output_tokens", usage.OutputTokens);
        AddUsage("total_tokens", usage.TotalTokens);
        AddUsage("cache_read_tokens", usage.CacheReadTokens);
        AddUsage("cache_write_tokens", usage.CacheWriteTokens);
        AddUsage("reasoning_tokens", usage.ReasoningTokens);
        return new JsonObject(fields);

        void AddUsage(string name, long? value)
        {
            if (includeNulls || value is not null)
            {
                fields.Add(Property(name, value is null ? JsonNull.Instance : Integer(value.Value)));
            }
        }
    }

    private static bool MessageListsEqual(IReadOnlyList<Message> left, IReadOnlyList<Message> right)
    {
        if (left.Count != right.Count)
        {
            return false;
        }

        for (var index = 0; index < left.Count; index++)
        {
            if (!string.Equals(left[index].Role, right[index].Role, StringComparison.Ordinal) ||
                left[index].Content.Count != right[index].Content.Count)
            {
                return false;
            }

            for (var part = 0; part < left[index].Content.Count; part++)
            {
                if (!Equals(left[index].Content[part], right[index].Content[part]))
                {
                    return false;
                }
            }
        }

        return true;
    }

    private static JsonValue ProjectMilliseconds(double seconds)
    {
        var milliseconds = seconds * 1000d;
        if (!double.IsFinite(milliseconds))
        {
            throw Unavailable("virtual clock retained a non-finite delay");
        }

        if (Math.Truncate(milliseconds) == milliseconds && milliseconds >= long.MinValue && milliseconds <= long.MaxValue)
        {
            return Integer((long)milliseconds);
        }

        return Number(milliseconds);
    }
    private static ObservationUnavailableException Unavailable(string detail) => new(detail);
    private static JsonProperty Property(string name, JsonValue value) => new(name, value);
    private static JsonString String(string value) => new(value);
    private static JsonInteger Integer(long value) => new(new BigInteger(value));
    private static JsonInteger Integer(int value) => new(new BigInteger(value));
    private static JsonNumber Number(double value) => new(value);
    private static JsonValue NullableString(string? value) => value is null ? JsonNull.Instance : String(value);
}

internal sealed class ObservationUnavailableException : Exception
{
    internal ObservationUnavailableException(string message)
        : base(message)
    {
    }
}
