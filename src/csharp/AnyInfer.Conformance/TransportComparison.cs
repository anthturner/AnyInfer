using AnyInfer.Json;

namespace AnyInfer.Conformance;

/// <summary>Compares released transport expectations only after actual transport execution.</summary>
internal static class TransportComparison
{
    internal static DevelopmentComparison Compare(FixtureDocument fixture, TransportRun run)
    {
        ArgumentNullException.ThrowIfNull(fixture);
        ArgumentNullException.ThrowIfNull(run);
        if (fixture.Input is not TransportFixtureInput input || !ReferenceEquals(input, run.Input) ||
            !string.Equals(fixture.Case.Id, run.CaseId, StringComparison.Ordinal))
        {
            return new DevelopmentComparison("error", Empty(), "transport fixture and run identities differ");
        }

        try
        {
            var observation = TransportProjection.Project(run);
            var mismatch = CompareExpected(fixture.Case.Id, fixture.Expected, input, run, observation);
            return mismatch is null
                ? new DevelopmentComparison("pass", observation)
                : new DevelopmentComparison("fail", observation, mismatch);
        }
        catch (ObservationUnavailableException exception)
        {
            return new DevelopmentComparison("error", Empty(), exception.Message);
        }
        catch (InvalidOperationException exception)
        {
            return new DevelopmentComparison("error", Empty(), exception.Message);
        }
    }

    private static string? CompareExpected(
        string caseId,
        JsonObject expected,
        TransportFixtureInput input,
        TransportRun run,
        JsonObject observation)
    {
        RequireClosed(expected, "status", "http_requests", "wire_limits", "core", "adapter_outcome");
        if (!Value(expected, "status", out var status) || status is not JsonString { Value: "observed" } ||
            !Value(observation, "status", out var observedStatus) || !JsonEquality.TypeAwareEquals(status, observedStatus))
        {
            return "transport status differs";
        }

        if (!Value(expected, "http_requests", out var expectedRequests) ||
            !Value(observation, "http_requests", out var actualRequests))
        {
            throw new ObservationUnavailableException("transport request observations are absent");
        }

        var requestMismatch = CompareRequests(caseId, input, expected, run, expectedRequests, actualRequests);
        if (requestMismatch is not null)
        {
            return requestMismatch;
        }

        if (!Value(expected, "wire_limits", out var expectedLimits) || !Value(observation, "wire_limits", out var actualLimits))
        {
            throw new ObservationUnavailableException("transport wire limits are absent");
        }

        var limitMismatch = CompareLimits(expectedLimits, actualLimits);
        if (limitMismatch is not null)
        {
            return limitMismatch;
        }

        if (input.Kind == "core_http")
        {
            if (expected.TryGetValue("adapter_outcome", out _) ||
                !Value(expected, "core", out var expectedCore) ||
                !Value(observation, "core", out _) || run.Core is null)
            {
                throw new ObservationUnavailableException("core transport comparison lacks its core observation");
            }

            var originalRequest = OperationRequest(input);
            var coreComparison = Comparison.CompareCore(
                new CoreComparisonContext(caseId, RequireObject(expectedCore, "core"), originalRequest),
                run.Core);
            return coreComparison.Verdict switch
            {
                "pass" => null,
                "fail" => "core." + (coreComparison.Detail ?? "differs"),
                "error" => throw new ObservationUnavailableException("core comparison evidence is unavailable: " + coreComparison.Detail),
                _ => throw new ObservationUnavailableException("core comparison returned an unsupported verdict"),
            };
        }

        if (expected.TryGetValue("core", out _) || !Value(expected, "adapter_outcome", out var expectedOutcome) ||
            !Value(observation, "adapter_outcome", out var actualOutcome))
        {
            throw new ObservationUnavailableException("direct transport comparison lacks adapter outcome");
        }

        return CompareAdapterOutcome(expectedOutcome, actualOutcome);
    }

    private static string? CompareRequests(
        string caseId,
        TransportFixtureInput input,
        JsonObject expectedEnvelope,
        TransportRun run,
        JsonValue expectedValue,
        JsonValue actualValue)
    {
        if (expectedValue is not JsonArray expected || actualValue is not JsonArray actual ||
            expected.Items.Count != actual.Items.Count || expected.Items.Count != run.Exchanges.Count)
        {
            return "http requests differ in count or shape";
        }

        for (var index = 0; index < expected.Items.Count; index++)
        {
            if (expected.Items[index] is not JsonObject expectedRequest || actual.Items[index] is not JsonObject actualRequest)
            {
                return RequestDetail(index, "shape");
            }

            RequireClosed(expectedRequest, "method", "path", "headers", "body", "stream");
            foreach (var name in new[] { "method", "path", "headers", "stream" })
            {
                if (!Value(expectedRequest, name, out var expectedPart) || !Value(actualRequest, name, out var actualPart) ||
                    !JsonEquality.TypeAwareEquals(expectedPart, actualPart))
                {
                    return RequestDetail(index, name);
                }
            }

            if (!Value(expectedRequest, "body", out var expectedBody) || !Value(actualRequest, "body", out var actualBody) ||
                expectedBody is not JsonObject expectedObject || actualBody is not JsonObject actualObject)
            {
                return RequestDetail(index, "body");
            }

            var bodyMismatch = CompareBody(caseId, input, expectedEnvelope, run, index, expectedObject, actualObject);
            if (bodyMismatch is not null)
            {
                return bodyMismatch;
            }
        }

        return null;
    }

    private static string? CompareBody(
        string caseId,
        TransportFixtureInput input,
        JsonObject expectedEnvelope,
        TransportRun run,
        int callIndex,
        JsonObject expected,
        JsonObject actual)
    {
        foreach (var property in expected.Properties)
        {
            if (property.Name == "messages")
            {
                continue;
            }

            if (!Value(actual, property.Name, out var other) || !JsonEquality.TypeAwareEquals(property.Value, other))
            {
                return RequestDetail(callIndex, "body." + property.Name);
            }
        }

        if (expected.Properties.Count != actual.Properties.Count ||
            !Value(expected, "messages", out var expectedMessages) || !Value(actual, "messages", out var actualMessages) ||
            expectedMessages is not JsonArray expectedItems || actualMessages is not JsonArray actualItems ||
            expectedItems.Items.Count != actualItems.Items.Count)
        {
            return RequestDetail(callIndex, "body.messages");
        }

        if (input.Kind != "core_http")
        {
            return JsonEquality.TypeAwareEquals(expectedMessages, actualMessages) ? null : RequestDetail(callIndex, "body.messages");
        }

        var core = run.Core ?? throw new ObservationUnavailableException("core transport has no native core run");
        var originalRequest = OperationRequest(input);
        var context = new CoreComparisonContext(caseId, expectedEnvelope, originalRequest);
        ValidateCoreCallBinding(run, core, callIndex);
        for (var messageIndex = 0; messageIndex < expectedItems.Items.Count; messageIndex++)
        {
            if (expectedItems.Items[messageIndex] is not JsonObject expectedMessage ||
                actualItems.Items[messageIndex] is not JsonObject actualMessage ||
                !Value(expectedMessage, "role", out var expectedRole) || !Value(actualMessage, "role", out var actualRole) ||
                !JsonEquality.TypeAwareEquals(expectedRole, actualRole) ||
                !Value(expectedMessage, "content", out var expectedContent) ||
                !Value(actualMessage, "content", out var actualContent) || actualContent is not JsonString actualText)
            {
                return RequestDetail(callIndex, "body.messages");
            }

            var expanded = Comparison.ExpandTypedCoreMessageContent(context, core, callIndex, messageIndex, expectedContent);
            if (!string.Equals(expanded, actualText.Value, StringComparison.Ordinal))
            {
                return RequestDetail(callIndex, "body.messages");
            }
        }

        return null;
    }

    private static void ValidateCoreCallBinding(TransportRun run, NativeRun core, int index)
    {
        if (index < 0 || index >= run.Exchanges.Count || index >= run.WireRequests.Count || index >= core.Capture.Entries.Count ||
            !ReferenceEquals(run.Exchanges[index].BoundWireRequest, run.WireRequests[index]) ||
            !ReferenceEquals(run.WireRequests[index], core.Capture.Entries[index].Request))
        {
            throw new ObservationUnavailableException("transport body marker lacks actual core wire provenance");
        }
    }

    private static string? CompareAdapterOutcome(JsonValue expectedValue, JsonValue actualValue)
    {
        if (expectedValue is not JsonObject expected || actualValue is not JsonObject actual)
        {
            throw new ObservationUnavailableException("adapter outcome has an invalid shape");
        }

        var expectedEvents = Value(expected, "events", out var expectedEventValue);
        var expectedError = Value(expected, "error", out var expectedErrorValue);
        var actualEvents = Value(actual, "events", out var actualEventValue);
        var actualError = Value(actual, "error", out var actualErrorValue);
        if (expectedEvents == expectedError || actualEvents == actualError)
        {
            throw new ObservationUnavailableException("adapter outcome does not have one terminal branch");
        }

        if (expected.Properties.Count != 1 || actual.Properties.Count != 1)
        {
            throw new ObservationUnavailableException("adapter outcome has unknown members");
        }

        if (expectedEvents != actualEvents)
        {
            return "adapter outcome branch differs";
        }

        return expectedEvents
            ? CompareAdapterEvents(expectedEventValue, actualEventValue)
            : CompareAdapterError(expectedErrorValue, actualErrorValue);
    }

    private static string? CompareAdapterEvents(JsonValue expectedValue, JsonValue actualValue)
    {
        if (expectedValue is not JsonArray expected || actualValue is not JsonArray actual)
        {
            throw new ObservationUnavailableException("adapter outcome events have an invalid shape");
        }

        if (expected.Items.Count != actual.Items.Count)
        {
            return "adapter outcome events differ in count";
        }

        for (var index = 0; index < expected.Items.Count; index++)
        {
            if (expected.Items[index] is not JsonObject expectedEvent || actual.Items[index] is not JsonObject actualEvent ||
                expectedEvent.Properties.Count != 1 || actualEvent.Properties.Count != 1)
            {
                throw new ObservationUnavailableException("adapter event has an invalid shape");
            }

            var expectedProperty = expectedEvent.Properties[0];
            var actualProperty = actualEvent.Properties[0];
            if (!string.Equals(expectedProperty.Name, actualProperty.Name, StringComparison.Ordinal))
            {
                return AdapterEventDetail(index);
            }

            var equal = expectedProperty.Name switch
            {
                "text_delta" => CompareTextDelta(expectedProperty.Value, actualProperty.Value),
                "usage" => Comparison.UsageEquals(expectedProperty.Value, actualProperty.Value),
                "final" => CompareAdapterFinal(expectedProperty.Value, actualProperty.Value),
                _ => throw new ObservationUnavailableException("adapter event has an unknown member"),
            };
            if (!equal)
            {
                return AdapterEventDetail(index);
            }
        }

        return null;
    }

    private static bool CompareTextDelta(JsonValue expectedValue, JsonValue actualValue)
    {
        if (expectedValue is not JsonObject expected || actualValue is not JsonObject actual ||
            !HasOnly(expected, "text") || !HasOnly(actual, "text") ||
            !Value(expected, "text", out var expectedText) || !Value(actual, "text", out var actualText) ||
            expectedText is not JsonString || actualText is not JsonString)
        {
            throw new ObservationUnavailableException("adapter text delta has an invalid shape");
        }

        return JsonEquality.TypeAwareEquals(expectedText, actualText);
    }

    private static bool CompareAdapterFinal(JsonValue expectedValue, JsonValue actualValue)
    {
        if (expectedValue is not JsonObject expected || actualValue is not JsonObject actual ||
            !HasOnly(expected, "finish_reason", "usage") || !HasOnly(actual, "finish_reason", "usage") ||
            !Value(expected, "finish_reason", out var expectedReason) || !Value(actual, "finish_reason", out var actualReason) ||
            !Value(expected, "usage", out var expectedUsage) || !Value(actual, "usage", out var actualUsage))
        {
            throw new ObservationUnavailableException("adapter final has an invalid shape");
        }

        return JsonEquality.TypeAwareEquals(expectedReason, actualReason) && Comparison.UsageEquals(expectedUsage, actualUsage);
    }

    private static string? CompareAdapterError(JsonValue expectedValue, JsonValue actualValue)
    {
        if (expectedValue is not JsonObject expected || actualValue is not JsonObject actual ||
            !HasOnly(expected, "category", "retryable", "retry_after_s", "http_status", "phase") ||
            !HasOnly(actual, "category", "retryable", "retry_after_s", "http_status", "phase"))
        {
            throw new ObservationUnavailableException("adapter error has an invalid shape");
        }

        foreach (var name in new[] { "category", "retryable", "http_status", "phase" })
        {
            if (!Value(expected, name, out var expectedPart) || !Value(actual, name, out var actualPart) ||
                !JsonEquality.TypeAwareEquals(expectedPart, actualPart))
            {
                return "adapter error differs";
            }
        }

        return Value(expected, "retry_after_s", out var expectedRetry) && Value(actual, "retry_after_s", out var actualRetry) &&
               JsonEquality.NumericControlEquals(expectedRetry, actualRetry)
            ? null
            : "adapter error differs";
    }

    private static string? CompareLimits(JsonValue expectedValue, JsonValue actualValue)
    {
        if (expectedValue is not JsonArray expected || actualValue is not JsonArray actual || expected.Items.Count != actual.Items.Count)
        {
            return "wire limits differ";
        }

        for (var index = 0; index < expected.Items.Count; index++)
        {
            if (expected.Items[index] is not JsonObject expectedLimit || actual.Items[index] is not JsonObject actualLimit ||
                !Value(expectedLimit, "timeout_s", out var timeout) || !Value(actualLimit, "timeout_s", out var actualTimeout) ||
                !JsonEquality.NumericControlEquals(timeout, actualTimeout) ||
                !Value(expectedLimit, "max_response_bytes", out var maximum) || !Value(actualLimit, "max_response_bytes", out var actualMaximum) ||
                !JsonEquality.TypeAwareEquals(maximum, actualMaximum))
            {
                return "wire_limits[" + index.ToString(System.Globalization.CultureInfo.InvariantCulture) + "] differs";
            }
        }

        return null;
    }

    private static JsonObject OperationRequest(TransportFixtureInput input)
    {
        if (input.Input is not JsonObject inputObject || !Value(inputObject, "operation", out var operationValue) ||
            operationValue is not JsonObject operation || !Value(operation, "request", out var request) || request is not JsonObject requestObject)
        {
            throw new ObservationUnavailableException("transport core input has no original request");
        }

        return requestObject;
    }

    private static JsonObject RequireObject(JsonValue value, string detail) => value as JsonObject
        ?? throw new ObservationUnavailableException(detail + " must be an object");

    private static void RequireClosed(JsonObject value, params string[] allowed)
    {
        var members = new HashSet<string>(allowed, StringComparer.Ordinal);
        if (value.Properties.Any(property => !members.Contains(property.Name)))
        {
            throw new ObservationUnavailableException("transport expected envelope has an unknown member");
        }
    }

    private static bool Value(JsonObject value, string name, out JsonValue found)
    {
        if (value.TryGetValue(name, out var result))
        {
            found = result;
            return true;
        }

        found = JsonNull.Instance;
        return false;
    }

    private static bool HasOnly(JsonObject value, params string[] names)
    {
        return value.Properties.Count == names.Length &&
               value.Properties.All(property => names.Contains(property.Name, StringComparer.Ordinal));
    }

    private static string RequestDetail(int index, string member) => "http_requests[" + index.ToString(System.Globalization.CultureInfo.InvariantCulture) + "]." + member + " differs";
    private static string AdapterEventDetail(int index) => "adapter_outcome.events[" + index.ToString(System.Globalization.CultureInfo.InvariantCulture) + "] differs";
    private static JsonObject Empty() => new([]);
}
