using System.Globalization;
using System.Numerics;
using AnyInfer.Json;
using AnyInfer.Schema;

namespace AnyInfer.Conformance;

/// <summary>Compares a frozen expected envelope only after native execution has completed.</summary>
internal static class Comparison
{
    internal static DevelopmentComparison Compare(FixtureDocument fixture, NativeRun run)
    {
        ArgumentNullException.ThrowIfNull(fixture);
        ArgumentNullException.ThrowIfNull(run);
        if (fixture.Input is not CoreFixtureInput coreInput)
        {
            return new DevelopmentComparison("error", EmptyObservation(), "fixture has no core comparison input");
        }

        return CompareCore(new CoreComparisonContext(fixture.Case.Id, fixture.Expected, coreInput.Request), run);
    }

    internal static DevelopmentComparison CompareCore(CoreComparisonContext context, NativeRun run)
    {
        ArgumentNullException.ThrowIfNull(context);
        ArgumentNullException.ThrowIfNull(run);
        if (!string.Equals(context.CaseId, run.CaseId, StringComparison.Ordinal))
        {
            return new DevelopmentComparison("error", EmptyObservation(), "core comparison and native run identities differ");
        }

        try
        {
            ValidateContextBinding(context, run);
            var observation = Projection.Project(run);
            if (run.Mirror is not null)
            {
                var mirror = Projection.ProjectMirror(run.Mirror);
                var mirrorMismatch = CompareMirror(observation, mirror);
                if (mirrorMismatch is not null)
                {
                    return new DevelopmentComparison("fail", observation, mirrorMismatch);
                }
            }

            ValidateExpectedEnvelope(context.Expected);
            var mismatch = CompareExpected(context, run, observation);
            return mismatch is null
                ? new DevelopmentComparison("pass", observation)
                : new DevelopmentComparison("fail", observation, mismatch);
        }
        catch (ObservationUnavailableException exception)
        {
            return new DevelopmentComparison("error", EmptyObservation(), exception.Message);
        }
        catch (InvalidOperationException exception)
        {
            return new DevelopmentComparison("error", EmptyObservation(), exception.Message);
        }
    }

    private static string? CompareExpected(CoreComparisonContext context, NativeRun run, JsonObject observation)
    {
        var expected = context.Expected;
        if (!TryProperty(expected, "status", out var status) || status is not JsonString { Value: "observed" })
        {
            return "expected status is not observed";
        }

        if (!TryProperty(observation, "status", out var actualStatus) || !JsonEquality.TypeAwareEquals(status, actualStatus))
        {
            return "observation status differs";
        }

        foreach (var property in expected.Properties)
        {
            if (property.Name is "status" or "calls" or "events" or "outcome")
            {
                continue;
            }

            if (!TryProperty(observation, property.Name, out var actual))
            {
                return "observation lacks " + property.Name;
            }

            var mismatch = property.Name switch
            {
                "clock_advances_ms" => CompareArray(property.Value, actual, JsonEquality.NumericControlEquals, "clock_advances_ms"),
                "telemetry" => CompareTelemetry(property.Value, actual),
                "accounting" => JsonEquality.TypeAwareEquals(property.Value, actual) ? null : "accounting differs",
                _ => JsonEquality.TypeAwareEquals(property.Value, actual) ? null : property.Name + " differs",
            };
            if (mismatch is not null)
            {
                return mismatch;
            }
        }

        if (!TryProperty(expected, "calls", out var expectedCalls) || !TryProperty(observation, "calls", out var actualCalls))
        {
            return "calls are missing";
        }

        var callsMismatch = CompareCalls(context, run, expectedCalls, actualCalls);
        if (callsMismatch is not null)
        {
            return callsMismatch;
        }

        if (!TryProperty(expected, "events", out var expectedEvents) || !TryProperty(observation, "events", out var actualEvents))
        {
            return "events are missing";
        }

        var eventsMismatch = CompareEvents(expectedEvents, actualEvents);
        if (eventsMismatch is not null)
        {
            return eventsMismatch;
        }

        if (!TryProperty(expected, "outcome", out var expectedOutcome) || !TryProperty(observation, "outcome", out var actualOutcome))
        {
            return "outcome is missing";
        }

        return CompareOutcome(context, expectedOutcome, actualOutcome);
    }

    private static string? CompareCalls(CoreComparisonContext context, NativeRun run, JsonValue expectedValue, JsonValue actualValue)
    {
        if (expectedValue is not JsonArray expected || actualValue is not JsonArray actual || expected.Items.Count != actual.Items.Count)
        {
            return "calls differ in count or shape";
        }

        var entries = run.Capture.Entries;
        if (entries.Count != actual.Items.Count)
        {
            throw new ObservationUnavailableException("call projection lacks captured entry identities");
        }

        for (var index = 0; index < expected.Items.Count; index++)
        {
            if (expected.Items[index] is not JsonObject expectedCall || actual.Items[index] is not JsonObject actualCall)
            {
                return "call " + index.ToString(CultureInfo.InvariantCulture) + " has an invalid shape";
            }

            foreach (var property in expectedCall.Properties)
            {
                if (property.Name is "messages" or "issues" or "timeout_s" or "max_response_bytes")
                {
                    continue;
                }

                if (!TryProperty(actualCall, property.Name, out var actualProperty) ||
                    !JsonEquality.TypeAwareEquals(property.Value, actualProperty))
                {
                    return CallDetail(index, property.Name);
                }
            }

            if (!TryProperty(expectedCall, "timeout_s", out var expectedTimeout) ||
                !TryProperty(actualCall, "timeout_s", out var actualTimeout) ||
                !JsonEquality.NumericControlEquals(expectedTimeout, actualTimeout))
            {
                return CallDetail(index, "timeout_s");
            }

            if (!TryProperty(expectedCall, "max_response_bytes", out var expectedLimit) ||
                !TryProperty(actualCall, "max_response_bytes", out var actualLimit) ||
                !JsonEquality.TypeAwareEquals(expectedLimit, actualLimit))
            {
                return CallDetail(index, "max_response_bytes");
            }

            if (!TryProperty(expectedCall, "messages", out var expectedMessages) ||
                !TryProperty(actualCall, "messages", out var actualMessages))
            {
                return CallDetail(index, "messages");
            }

            var messagesMismatch = CompareMessages(context, run, index, expected, actual, expectedMessages, actualMessages);
            if (messagesMismatch is not null)
            {
                return messagesMismatch;
            }

            var expectedCorrection = TryProperty(expectedCall, "role", out var role) && role is JsonString { Value: "correction" };
            if (expectedCorrection)
            {
                if (!TryProperty(expectedCall, "issues", out var expectedIssues) ||
                    !TryProperty(actualCall, "issues", out var actualIssues) ||
                    !JsonEquality.TypeAwareEquals(expectedIssues, actualIssues))
                {
                    return CallDetail(index, "issues");
                }
            }
            else if (actualCall.TryGetValue("issues", out _))
            {
                return CallDetail(index, "issues");
            }
        }

        return null;
    }

    private static string? CompareMessages(
        CoreComparisonContext context,
        NativeRun run,
        int index,
        JsonArray expectedCalls,
        JsonArray actualCalls,
        JsonValue expectedValue,
        JsonValue actualValue)
    {
        if (expectedValue is JsonString { Value: var sameAs })
        {
            if (sameAs.StartsWith("same_as_call_", StringComparison.Ordinal) && !TrySameAs(sameAs, out var reference))
            {
                throw new ObservationUnavailableException("expected same_as_call reference has invalid syntax");
            }

            if (TrySameAs(sameAs, out reference))
            {
                if (reference >= index || reference < 0 || reference >= actualCalls.Items.Count ||
                    actualCalls.Items[reference] is not JsonObject referenced ||
                    !TryProperty(referenced, "messages", out var referenceMessages))
                {
                    throw new ObservationUnavailableException("expected same_as_call reference is self, forward, or out of range");
                }

                return JsonEquality.TypeAwareEquals(referenceMessages, actualValue)
                    ? null
                    : CallDetail(index, "same_as_call");
            }
        }

        if (expectedValue is not JsonArray expected || actualValue is not JsonArray actual || expected.Items.Count != actual.Items.Count)
        {
            return CallDetail(index, "messages");
        }

        for (var messageIndex = 0; messageIndex < expected.Items.Count; messageIndex++)
        {
            if (expected.Items[messageIndex] is not JsonObject expectedMessage || actual.Items[messageIndex] is not JsonObject actualMessage ||
                !TryProperty(expectedMessage, "role", out var expectedRole) ||
                !TryProperty(actualMessage, "role", out var actualRole) ||
                !JsonEquality.TypeAwareEquals(expectedRole, actualRole) ||
                !TryProperty(expectedMessage, "text", out var expectedText) ||
                !TryProperty(actualMessage, "text", out var actualText) || actualText is not JsonString actualString)
            {
                return CallDetail(index, "messages");
            }

            var expanded = ExpandTypedCoreMessageContent(context, run, index, messageIndex, expectedText);
            if (!string.Equals(expanded, actualString.Value, StringComparison.Ordinal))
            {
                return CallDetail(index, "messages");
            }
        }

        return null;
    }

    internal static string ExpandTypedCoreMessageContent(
        CoreComparisonContext context,
        NativeRun run,
        int callIndex,
        int messageIndex,
        JsonValue expected)
    {
        ArgumentNullException.ThrowIfNull(context);
        ArgumentNullException.ThrowIfNull(run);
        ValidateContextBinding(context, run);
        if (callIndex < 0 || callIndex >= run.Capture.Entries.Count)
        {
            throw new ObservationUnavailableException("typed core marker has no captured entry");
        }

        var entry = run.Capture.Entries[callIndex];
        if (messageIndex < 0 || messageIndex >= entry.Request.Messages.Count)
        {
            throw new ObservationUnavailableException("typed core marker has no captured message");
        }

        if (expected is JsonString literal)
        {
            return literal.Value;
        }

        if (expected is not JsonArray segments)
        {
            throw new ObservationUnavailableException("expected message text is malformed");
        }

        var pieces = new List<string>();
        var schemaMarkers = 0;
        var feedbackMarkers = 0;
        for (var segmentIndex = 0; segmentIndex < segments.Items.Count; segmentIndex++)
        {
            var segment = segments.Items[segmentIndex];
            if (segment is JsonString text)
            {
                pieces.Add(text.Value);
                continue;
            }

            if (segment is not JsonObject marker || marker.Properties.Count != 1)
            {
                throw new ObservationUnavailableException("expected message marker has an invalid shape");
            }

            var property = marker.Properties[0];
            if (property.Name == "$schema_prompt" && property.Value is JsonBoolean { Value: true })
            {
                schemaMarkers++;
                if (schemaMarkers > 1 || !context.OriginalRequest.TryGetValue("schema", out var schema) || schema is JsonNull ||
                    entry.Request.Schema is null ||
                    entry.Request.Mechanism is not ("prompt" or "json_mode") ||
                    messageIndex != LastMessageIndex(entry.Request.Messages, "system") ||
                    segmentIndex != segments.Items.Count - 1 ||
                    !JsonEquality.SchemaEquals(schema, entry.Request.Schema) ||
                    !IsInjectedSchemaPrompt(entry.Request.Messages[messageIndex], schema))
                {
                    throw new ObservationUnavailableException("schema marker lacks original schema evidence");
                }

                pieces.Add(SchemaPromptRenderer.Render(schema));
                continue;
            }

            if (property.Name == "$repair_feedback" && property.Value is JsonBoolean { Value: true })
            {
                feedbackMarkers++;
                if (feedbackMarkers > 1 || callIndex < 0 || entry.Role != AnyInfer.Internal.EntryRole.Correction || entry.RepairAssessment is null ||
                    messageIndex != LastMessageIndex(entry.Request.Messages, "user") ||
                    !run.Capture.Repairs.Any(preparation => ReferenceEquals(preparation.Assessment, entry.RepairAssessment)) ||
                    !HasFixedRepairFeedbackContext(segments, segmentIndex) ||
                    !IsRepairFeedbackMessage(entry.Request.Messages[messageIndex], entry.RepairAssessment))
                {
                    throw new ObservationUnavailableException("repair marker lacks causal native assessment evidence");
                }

                pieces.Add(RepairFeedback(entry.RepairAssessment));
                continue;
            }

            throw new ObservationUnavailableException("expected message marker is outside its typed scope");
        }

        return string.Concat(pieces);
    }

    private static string RepairFeedback(NativeAssessment assessment)
    {
        return string.Join("\n", assessment.Messages.Select(static message => "- " + message));
    }

    private static int LastMessageIndex(IReadOnlyList<Message> messages, string role)
    {
        for (var index = messages.Count - 1; index >= 0; index--)
        {
            if (string.Equals(messages[index].Role, role, StringComparison.Ordinal))
            {
                return index;
            }
        }

        return -1;
    }

    private static bool IsInjectedSchemaPrompt(Message message, JsonValue schema)
    {
        if (!string.Equals(message.Role, "system", StringComparison.Ordinal))
        {
            return false;
        }

        var prompt = SchemaPromptRenderer.Render(schema);
        var text = MessageText(message);
        return string.Equals(text, prompt, StringComparison.Ordinal) ||
               text.EndsWith("\n\n" + prompt, StringComparison.Ordinal);
    }

    private static bool HasFixedRepairFeedbackContext(JsonArray segments, int markerIndex)
    {
        const string prefix = "Your previous response did not match the required JSON schema. Errors:\n";
        const string suffix = "\nRespond again with ONLY a corrected JSON value that satisfies the schema. No prose, no code fences.";
        if (!segments.Items.Take(markerIndex).All(static segment => segment is JsonString) ||
            !segments.Items.Skip(markerIndex + 1).All(static segment => segment is JsonString))
        {
            return false;
        }

        var before = string.Concat(segments.Items.Take(markerIndex).OfType<JsonString>().Select(static text => text.Value));
        var after = string.Concat(segments.Items.Skip(markerIndex + 1).OfType<JsonString>().Select(static text => text.Value));
        return string.Equals(before, prefix, StringComparison.Ordinal) &&
               string.Equals(after, suffix, StringComparison.Ordinal);
    }

    private static bool IsRepairFeedbackMessage(Message message, NativeAssessment assessment)
    {
        const string prefix = "Your previous response did not match the required JSON schema. Errors:\n";
        const string suffix = "\nRespond again with ONLY a corrected JSON value that satisfies the schema. No prose, no code fences.";
        return string.Equals(message.Role, "user", StringComparison.Ordinal) &&
               string.Equals(MessageText(message), prefix + RepairFeedback(assessment) + suffix, StringComparison.Ordinal);
    }

    private static string MessageText(Message message)
    {
        return string.Concat(message.Content.Select(part => part is TextPart text
            ? text.Text
            : throw new ObservationUnavailableException("captured marker message has non-text content")));
    }

    private static string? CompareTelemetry(JsonValue expected, JsonValue actual)
    {
        if (expected is not JsonObject expectedObject || actual is not JsonObject actualObject)
        {
            return "telemetry differs";
        }

        foreach (var name in new[] { "repair_attempted", "parameter_dropped" })
        {
            if (!TryProperty(expectedObject, name, out var expectedList) ||
                !TryProperty(actualObject, name, out var actualList))
            {
                return "telemetry." + name + " differs";
            }

            var mismatch = CompareArray(expectedList, actualList, JsonEquality.TypeAwareEquals, "telemetry." + name);
            if (mismatch is not null)
            {
                return mismatch;
            }
        }

        return null;
    }

    private static string? CompareEvents(JsonValue expected, JsonValue actual)
    {
        if (expected is not JsonArray expectedEvents || actual is not JsonArray actualEvents ||
            expectedEvents.Items.Count != actualEvents.Items.Count)
        {
            return "events differs in count or shape";
        }

        for (var index = 0; index < expectedEvents.Items.Count; index++)
        {
            var expectedEvent = expectedEvents.Items[index];
            var actualEvent = actualEvents.Items[index];
            if (expectedEvent is JsonObject { Properties.Count: 1 } expectedObject &&
                actualEvent is JsonObject { Properties.Count: 1 } actualObject &&
                string.Equals(expectedObject.Properties[0].Name, "usage_update", StringComparison.Ordinal) &&
                string.Equals(actualObject.Properties[0].Name, "usage_update", StringComparison.Ordinal))
            {
                if (!UsageEquals(expectedObject.Properties[0].Value, actualObject.Properties[0].Value))
                {
                    return "events differs at " + index.ToString(CultureInfo.InvariantCulture);
                }

                continue;
            }

            if (!JsonEquality.TypeAwareEquals(expectedEvent, actualEvent))
            {
                return "events differs at " + index.ToString(CultureInfo.InvariantCulture);
            }
        }

        return null;
    }

    private static string? CompareOutcome(CoreComparisonContext context, JsonValue expected, JsonValue actual)
    {
        if (expected is not JsonObject expectedObject || actual is not JsonObject actualObject ||
            expectedObject.Properties.Count != 1 || actualObject.Properties.Count != 1)
        {
            return "outcome differs";
        }

        var expectedProperty = expectedObject.Properties[0];
        var actualProperty = actualObject.Properties[0];
        if (!string.Equals(expectedProperty.Name, actualProperty.Name, StringComparison.Ordinal))
        {
            return "outcome kind differs";
        }

        return expectedProperty.Name switch
        {
            "result" => CompareResult(context, expectedProperty.Value, actualProperty.Value),
            "error" => CompareError(expectedProperty.Value, actualProperty.Value),
            "none" => JsonEquality.TypeAwareEquals(expectedProperty.Value, actualProperty.Value) ? null : "outcome.none differs",
            _ => "outcome has an unknown kind",
        };
    }

    private static string? CompareResult(CoreComparisonContext context, JsonValue expected, JsonValue actual)
    {
        if (expected is not JsonObject expectedResult || actual is not JsonObject actualResult ||
            !HasExactMembers(expectedResult, ResultMembers) || !HasExactMembers(actualResult, ResultMembers))
        {
            return "result differs";
        }

        foreach (var property in expectedResult.Properties)
        {
            if (!TryProperty(actualResult, property.Name, out var actualProperty))
            {
                return "result lacks " + property.Name;
            }

            var matches = property.Name switch
            {
                "structured" => JsonEquality.SchemaEquals(property.Value, actualProperty),
                "usage" => UsageEquals(property.Value, actualProperty),
                "timing" => TimingEquals(property.Value, actualProperty),
                _ => JsonEquality.TypeAwareEquals(property.Value, actualProperty),
            };
            if (!matches)
            {
                return "result." + property.Name + " differs";
            }
        }

        if (string.Equals(context.CaseId, "extraction/duplicate-key-last-value-first-position", StringComparison.Ordinal) &&
            !RootMemberOrderMatches(expectedResult, actualResult))
        {
            return "result.structured root-member order differs";
        }

        return null;
    }

    private static string? CompareError(JsonValue expected, JsonValue actual)
    {
        if (expected is not JsonObject expectedError || actual is not JsonObject actualError ||
            !HasRequiredMembers(expectedError, ErrorMembers) || !HasRequiredMembers(actualError, ErrorMembers))
        {
            return "error differs";
        }

        if (TryProperty(expectedError, "category", out var category) && category is JsonString { Value: "schema_violation" } &&
            (!TryProperty(expectedError, "issues", out _) || !TryProperty(actualError, "issues", out _)))
        {
            return "error.issues differs";
        }

        foreach (var property in expectedError.Properties)
        {
            if (!TryProperty(actualError, property.Name, out var actualProperty))
            {
                return "error." + property.Name + " differs";
            }

            var equal = property.Name == "retry_after_s"
                ? JsonEquality.NumericControlEquals(property.Value, actualProperty)
                : JsonEquality.TypeAwareEquals(property.Value, actualProperty);
            if (!equal)
            {
                return "error." + property.Name + " differs";
            }
        }

        return null;
    }

    private static readonly string[] ResultMembers =
    [
        "text", "structured", "target", "finish_reason", "usage", "timing",
        "structured_mechanism", "repair_attempts", "attempts", "warnings",
    ];

    private static readonly string[] UsageMembers =
    [
        "input_tokens", "output_tokens", "total_tokens", "cache_read_tokens", "cache_write_tokens", "reasoning_tokens",
    ];

    private static readonly string[] TimingMembers = ["first_token_ms", "total_ms"];
    private static readonly string[] ErrorMembers =
    ["category", "retryable", "retry_after_s", "http_status", "phase"];

    private static bool HasExactMembers(JsonObject value, IReadOnlyCollection<string> names)
    {
        return value.Properties.Count == names.Count && value.Properties.All(property => names.Contains(property.Name, StringComparer.Ordinal));
    }

    private static bool HasRequiredMembers(JsonObject value, IReadOnlyCollection<string> names)
    {
        return names.All(name => value.TryGetValue(name, out _));
    }

    private static bool RootMemberOrderMatches(JsonObject expectedResult, JsonObject actualResult)
    {
        if (!TryProperty(expectedResult, "structured", out var expectedStructured) ||
            !TryProperty(actualResult, "structured", out var actualStructured) ||
            expectedStructured is not JsonObject expectedObject || actualStructured is not JsonObject actualObject ||
            expectedObject.Properties.Count != actualObject.Properties.Count)
        {
            return false;
        }

        for (var index = 0; index < expectedObject.Properties.Count; index++)
        {
            if (!string.Equals(expectedObject.Properties[index].Name, actualObject.Properties[index].Name, StringComparison.Ordinal))
            {
                return false;
            }
        }

        return true;
    }
    internal static bool UsageEquals(JsonValue expected, JsonValue actual)
    {
        if (expected is JsonNull)
        {
            return actual is JsonNull;
        }

        if (expected is not JsonObject expectedUsage || actual is not JsonObject actualUsage ||
            actualUsage.Properties.Count != UsageMembers.Length ||
            !actualUsage.Properties.All(property => UsageMembers.Contains(property.Name, StringComparer.Ordinal)) ||
            expectedUsage.Properties.Any(property => !UsageMembers.Contains(property.Name, StringComparer.Ordinal)))
        {
            return false;
        }

        foreach (var name in UsageMembers)
        {
            if (!actualUsage.TryGetValue(name, out var actualValue))
            {
                return false;
            }

            if (expectedUsage.TryGetValue(name, out var expectedValue))
            {
                if (!JsonEquality.TypeAwareEquals(expectedValue, actualValue))
                {
                    return false;
                }
            }
            else if (actualValue is not JsonNull)
            {
                return false;
            }
        }

        return true;
    }
    private static bool TimingEquals(JsonValue expected, JsonValue actual)
    {
        if (expected is not JsonObject expectedTiming || actual is not JsonObject actualTiming ||
            !HasExactMembers(expectedTiming, TimingMembers) || !HasExactMembers(actualTiming, TimingMembers))
        {
            return false;
        }

        foreach (var name in TimingMembers)
        {
            if (!expectedTiming.TryGetValue(name, out var expectedValue) || !actualTiming.TryGetValue(name, out var actualValue))
            {
                return false;
            }

            if (expectedValue is JsonString { Value: "present" })
            {
                if (actualValue is not JsonNumber)
                {
                    return false;
                }
            }
            else if (expectedValue is JsonString { Value: "non_null" })
            {
                if (actualValue is JsonNull)
                {
                    return false;
                }
            }
            else if (expectedValue is JsonString { Value: "null" })
            {
                if (actualValue is not JsonNull)
                {
                    return false;
                }
            }
            else if (!JsonEquality.TypeAwareEquals(expectedValue, actualValue))
            {
                return false;
            }
        }

        return true;
    }
    private static string? CompareMirror(JsonObject primary, JsonObject mirror)
    {
        if (!TryProperty(primary, "calls", out var primaryCalls) ||
            !TryProperty(mirror, "calls", out var mirrorCalls) ||
            !MirrorCallsEqual(primaryCalls, mirrorCalls))
        {
            return "buffered mirror calls differ";
        }

        if (!TryProperty(primary, "telemetry", out var primaryTelemetry) ||
            !TryProperty(mirror, "telemetry", out var mirrorTelemetry) ||
            !JsonEquality.TypeAwareEquals(primaryTelemetry, mirrorTelemetry))
        {
            return "buffered mirror telemetry differs";
        }

        if (!TryProperty(primary, "clock_advances_ms", out var primaryClock) ||
            !TryProperty(mirror, "clock_advances_ms", out var mirrorClock) ||
            CompareArray(primaryClock, mirrorClock, JsonEquality.NumericControlEquals, "clock") is not null)
        {
            return "buffered mirror clock advances differ";
        }

        if (!TryProperty(primary, "outcome", out var primaryOutcome) ||
            !TryProperty(mirror, "outcome", out var mirrorOutcome) ||
            !MirrorOutcomeEquals(primaryOutcome, mirrorOutcome))
        {
            return "buffered mirror outcome differs";
        }

        return null;
    }

    private static bool MirrorCallsEqual(JsonValue primary, JsonValue mirror)
    {
        if (primary is not JsonArray primaryCalls || mirror is not JsonArray mirrorCalls || primaryCalls.Items.Count != mirrorCalls.Items.Count)
        {
            return false;
        }

        for (var index = 0; index < primaryCalls.Items.Count; index++)
        {
            if (primaryCalls.Items[index] is not JsonObject primaryCall || mirrorCalls.Items[index] is not JsonObject mirrorCall ||
                primaryCall.Properties.Count != mirrorCall.Properties.Count)
            {
                return false;
            }

            foreach (var property in primaryCall.Properties)
            {
                if (!TryProperty(mirrorCall, property.Name, out var other))
                {
                    return false;
                }

                var equal = property.Name == "timeout_s"
                    ? JsonEquality.NumericControlEquals(property.Value, other)
                    : JsonEquality.TypeAwareEquals(property.Value, other);
                if (!equal)
                {
                    return false;
                }
            }
        }

        return true;
    }
    private static bool MirrorOutcomeEquals(JsonValue primary, JsonValue mirror)
    {
        if (primary is not JsonObject primaryObject || mirror is not JsonObject mirrorObject ||
            primaryObject.Properties.Count != 1 || mirrorObject.Properties.Count != 1 ||
            !string.Equals(primaryObject.Properties[0].Name, mirrorObject.Properties[0].Name, StringComparison.Ordinal))
        {
            return false;
        }

        if (primaryObject.Properties[0].Name != "result")
        {
            return JsonEquality.TypeAwareEquals(primary, mirror);
        }

        if (primaryObject.Properties[0].Value is not JsonObject primaryResult || mirrorObject.Properties[0].Value is not JsonObject mirrorResult)
        {
            return false;
        }

        foreach (var property in primaryResult.Properties)
        {
            if (!TryProperty(mirrorResult, property.Name, out var other))
            {
                return false;
            }

            if (property.Name == "timing")
            {
                if (!TimingPresenceEquals(property.Value, other))
                {
                    return false;
                }

                continue;
            }

            var equal = property.Name switch
            {
                "structured" => JsonEquality.SchemaEquals(property.Value, other),
                "usage" => UsageEquals(property.Value, other),
                _ => JsonEquality.TypeAwareEquals(property.Value, other),
            };
            if (!equal)
            {
                return false;
            }
        }

        return primaryResult.Properties.Count == mirrorResult.Properties.Count;
    }

    private static bool TimingPresenceEquals(JsonValue primary, JsonValue mirror)
    {
        if (primary is not JsonObject primaryTiming || mirror is not JsonObject mirrorTiming ||
            primaryTiming.Properties.Count != mirrorTiming.Properties.Count)
        {
            return false;
        }

        foreach (var property in primaryTiming.Properties)
        {
            if (!TryProperty(mirrorTiming, property.Name, out var other) ||
                (property.Value is JsonNull) != (other is JsonNull))
            {
                return false;
            }
        }

        return true;
    }
    private static string? CompareArray(JsonValue expected, JsonValue actual, Func<JsonValue, JsonValue, bool> equals, string name)
    {
        if (expected is not JsonArray expectedItems || actual is not JsonArray actualItems || expectedItems.Items.Count != actualItems.Items.Count)
        {
            return name + " differs";
        }

        for (var index = 0; index < expectedItems.Items.Count; index++)
        {
            if (!equals(expectedItems.Items[index], actualItems.Items[index]))
            {
                return name + " differs at " + index.ToString(CultureInfo.InvariantCulture);
            }
        }

        return null;
    }

    private static bool TrySameAs(string text, out int zeroBasedIndex)
    {
        const string prefix = "same_as_call_";
        zeroBasedIndex = -1;
        if (!text.StartsWith(prefix, StringComparison.Ordinal))
        {
            return false;
        }

        var digits = text[prefix.Length..];
        if (digits.Length == 0 ||
            digits[0] == '0' ||
            digits.Any(static character => character is < '0' or > '9') ||
            !int.TryParse(digits, NumberStyles.None, CultureInfo.InvariantCulture, out var oneBased))
        {
            return false;
        }

        zeroBasedIndex = oneBased - 1;
        return true;
    }

    private static bool TryProperty(JsonObject value, string name, out JsonValue property)
    {
        if (value.TryGetValue(name, out var found))
        {
            property = found;
            return true;
        }

        property = JsonNull.Instance;
        return false;
    }

    private static void ValidateContextBinding(CoreComparisonContext context, NativeRun run)
    {
        var actualRequest = run.Input switch
        {
            CoreFixtureInput coreInput => coreInput.Request,
            TransportFixtureInput transportInput => TransportOperationRequest(transportInput),
            _ => throw new ObservationUnavailableException("native run has an unsupported core comparison input"),
        };

        if (!ReferenceEquals(context.OriginalRequest, actualRequest))
        {
            throw new ObservationUnavailableException("core comparison request is not the native run input");
        }
    }

    private static JsonObject TransportOperationRequest(TransportFixtureInput input)
    {
        if (input.Input is not JsonObject transportInput ||
            !transportInput.TryGetValue("operation", out var operationValue) || operationValue is not JsonObject operation ||
            !operation.TryGetValue("request", out var requestValue) || requestValue is not JsonObject request)
        {
            throw new ObservationUnavailableException("transport core comparison has no original operation request");
        }

        return request;
    }

    private static void ValidateExpectedEnvelope(JsonObject expected)
    {
        var allowed = new HashSet<string>(StringComparer.Ordinal)
        {
            "status", "calls", "clock_advances_ms", "telemetry", "events", "outcome", "accounting",
        };
        if (expected.Properties.Any(property => !allowed.Contains(property.Name)))
        {
            throw new ObservationUnavailableException("expected envelope has unknown comparison fields");
        }
    }

    private static JsonObject EmptyObservation() => new([]);
    private static string CallDetail(int index, string member) => "calls[" + index.ToString(CultureInfo.InvariantCulture) + "]." + member + " differs";
}

internal sealed record CoreComparisonContext(string CaseId, JsonObject Expected, JsonObject OriginalRequest);

internal sealed record DevelopmentComparison(string Verdict, JsonObject Observation, string? Detail = null);
