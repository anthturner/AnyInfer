using System.Numerics;
using AnyInfer.Core;
using AnyInfer.Internal;
using AnyInfer.Json;
using AnyInfer.Providers;

namespace AnyInfer.Conformance;

/// <summary>Runs raw released core inputs through the held native client without expected data.</summary>
internal static class NativeRunner
{
    private const string Buffered = "buffered";
    private const string NoAdvance = "close_without_advance";
    private const string CloseTwice = "close_twice_after_end";
    private const string CancelPrefix = "stream_cancel_after_events:";

    internal static async Task<NativeRun> RunAsync(
        string caseId,
        CoreFixtureInput input,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(caseId);
        ArgumentNullException.ThrowIfNull(input);

        var primary = await RunOneAsync(caseId, input, ConsumeMode(input.Request), cancellationToken).ConfigureAwait(false);
        if (string.Equals(caseId, "streaming/buffered-equals-streamed", StringComparison.Ordinal))
        {
            var mirror = await RunOneAsync(caseId, input, Buffered, cancellationToken).ConfigureAwait(false);
            return primary with { Mirror = mirror };
        }

        return primary;
    }

    private static async Task<NativeRun> RunOneAsync(
        string caseId,
        CoreFixtureInput input,
        string consumeMode,
        CancellationToken cancellationToken)
    {
        return await RunPreparedAsync(
            caseId,
            input,
            consumeMode,
            CreateSetup(input, consumeMode),
            cancellationToken).ConfigureAwait(false);
    }

    internal static async Task<NativeRun> RunPreparedAsync(
        string caseId,
        FixtureInput input,
        string consumeMode,
        NativeExecutionSetup setup,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(caseId);
        ArgumentNullException.ThrowIfNull(input);
        ArgumentException.ThrowIfNullOrWhiteSpace(consumeMode);
        ArgumentNullException.ThrowIfNull(setup);

        var capture = new OperationCapture();
        try
        {
            await using var client = setup.Client;
            if (consumeMode == Buffered)
            {
                try
                {
                    var result = await client.GenerateAsync(setup.Request, capture, cancellationToken).ConfigureAwait(false);
                    return Complete(caseId, input, consumeMode, [], result, null, "buffered", false, capture, setup);
                }
                catch (AnyInferException exception)
                {
                    return Complete(caseId, input, consumeMode, [], null, exception, "buffered", false, capture, setup);
                }
            }

            return await ConsumeStreamAsync(caseId, input, consumeMode, setup, capture, cancellationToken).ConfigureAwait(false);
        }
        catch (AnyInferException exception)
        {
            return Complete(caseId, input, consumeMode, [], null, exception, "construction", false, capture, setup);
        }
    }

    private static async Task<NativeRun> ConsumeStreamAsync(
        string caseId,
        FixtureInput input,
        string consumeMode,
        NativeExecutionSetup setup,
        OperationCapture capture,
        CancellationToken cancellationToken)
    {
        var events = new List<GenerationEvent>();
        await using var stream = setup.Client.StreamAsync(setup.Request, capture, cancellationToken);
        if (consumeMode == NoAdvance)
        {
            await stream.DisposeAsync().ConfigureAwait(false);
            return Complete(caseId, input, consumeMode, events, stream.Result, null, "close", false, capture, setup);
        }

        var cancelAfter = CancellationCount(consumeMode);
        var closeTwiceAfterEnd = consumeMode == CloseTwice;
        using var driverCancellation = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        var deliberateCancellation = false;
        try
        {
            await foreach (var generationEvent in stream.WithCancellation(driverCancellation.Token).ConfigureAwait(false))
            {
                events.Add(generationEvent);
                if (cancelAfter is { } limit && new BigInteger(events.Count) >= limit)
                {
                    deliberateCancellation = true;
                    driverCancellation.Cancel();
                }
            }

            if (closeTwiceAfterEnd)
            {
                await stream.DisposeAsync().ConfigureAwait(false);
                await stream.DisposeAsync().ConfigureAwait(false);
            }

            return Complete(caseId, input, consumeMode, events, stream.Result, null, "stream", false, capture, setup);
        }
        catch (OperationCanceledException exception) when (deliberateCancellation && driverCancellation.IsCancellationRequested && !cancellationToken.IsCancellationRequested)
        {
            return Complete(caseId, input, consumeMode, events, stream.Result, exception, "stream", true, capture, setup);
        }
        catch (AnyInferException exception)
        {
            return Complete(caseId, input, consumeMode, events, stream.Result, exception, "stream", false, capture, setup);
        }
    }

    private static NativeRun Complete(
        string caseId,
        FixtureInput input,
        string consumeMode,
        IReadOnlyList<GenerationEvent> events,
        GenerationResult? result,
        Exception? terminalException,
        string terminalStage,
        bool deliberateCancellation,
        OperationCapture capture,
        NativeExecutionSetup setup,
        NativeRun? mirror = null) =>
        new(
            caseId,
            input,
            consumeMode,
            Array.AsReadOnly(events.ToArray()),
            result,
            terminalException,
            terminalStage,
            deliberateCancellation,
            capture,
            setup.Clock,
            setup.AdapterCallCount(),
            setup.RemainingEntries(),
            mirror);

    private static NativeExecutionSetup CreateSetup(CoreFixtureInput input, string consumeMode)
    {
        var clock = new VirtualClock(ReadClockSeconds(input.Clock));
        // A fresh, intentionally unreleased gate lets the fixture's own consumption mode
        // exercise native cancellation without turning await_release into a harness fault.
        var adapter = FixtureAdapter.Create(RequireArray(input.Adapter, "script"), new FixtureGates());
        var capabilities = ReadCapabilities(input.Adapter);
        var ceiling = ReadNullableInt32(Optional(input.Adapter, "max_repair_attempts"), "max_repair_attempts");
        var registration = new ProviderRegistration("fixture", adapter, capabilities, ceiling);
        var client = new AsyncClient([registration], clock);
        foreach (var preset in RequireArray(input.Adapter, "health_preset").Items)
        {
            var value = RequireObject(preset, "health preset");
            client.Health.SeedFailure(ParseTarget(RequireString(Require(value, "target"), "target")), ReadNumber(Require(value, "failed_at_ms"), "failed_at_ms") / 1000d);
        }

        var request = ReadOperationRequest(input.Request, input.Route, consumeMode);
        return new NativeExecutionSetup(client, clock, request, () => adapter.CallCount, () => adapter.RemainingEntries);
    }

    internal static GenerationRequest ReadOperationRequest(JsonObject request, JsonObject route, string consumeMode)
    {
        var messages = RequireArray(request, "messages").Items.Select(ReadMessage).ToArray();
        var schema = Optional(request, "schema") is JsonNull or null ? null : Optional(request, "schema");
        var sampling = Optional(request, "sampling") is { } samplingValue ? ReadSampling(RequireObject(samplingValue, "sampling")) : null;
        var repair = Optional(request, "repair") is { } repairValue
            ? new RepairOptions(ReadInt32(Require(RequireObject(repairValue, "repair"), "max_attempts"), "max_attempts"))
            : null;
        var timeout = ReadNullableNumber(Optional(request, "timeout_s"), "timeout_s");
        var maxBytes = ReadNullableInt32(Optional(request, "max_response_bytes"), "max_response_bytes");
        return new GenerationRequest(messages, ReadRoute(route), sampling, repair, schema, timeoutS: timeout, maxResponseBytes: maxBytes, stream: consumeMode != Buffered);
    }

    private static Message ReadMessage(JsonValue value)
    {
        var message = RequireObject(value, "message");
        var role = RequireString(Require(message, "role"), "role");
        if (message.TryGetValue("text", out var text))
        {
            return new Message(role, [new TextPart(ReadText(text, "text"))]);
        }

        var parts = RequireArray(message, "parts").Items.Select(partValue =>
        {
            var part = RequireObject(partValue, "part");
            var kind = RequireString(Require(part, "kind"), "kind");
            if (string.Equals(kind, "text", StringComparison.Ordinal))
            {
                return (ContentPart)new TextPart(RequireString(Require(part, "text"), "text"));
            }

            return new UnsupportedContentPart(kind, part);
        });
        return new Message(role, parts);
    }

    private static Sampling ReadSampling(JsonObject value) => new(
        temperature: ReadNullableNumber(Optional(value, "temperature"), "temperature"),
        topP: ReadNullableNumber(Optional(value, "top_p"), "top_p"),
        maxOutputTokens: ReadNullableInt32(Optional(value, "max_output_tokens"), "max_output_tokens"),
        stop: ReadStop(Optional(value, "stop")),
        seed: ReadNullableInt64(Optional(value, "seed"), "seed"),
        presencePenalty: ReadNullableNumber(Optional(value, "presence_penalty"), "presence_penalty"),
        frequencyPenalty: ReadNullableNumber(Optional(value, "frequency_penalty"), "frequency_penalty"));

    private static Route ReadRoute(JsonObject value)
    {
        var targets = RequireArray(value, "targets").Items.Select(item => RequireString(item, "target"));
        var retry = Optional(value, "retry") is { } retryValue
            ? ReadRetry(RequireObject(retryValue, "retry"))
            : null;
        var healthGate = Optional(value, "health_gate") is JsonBoolean gate ? gate.Value : true;
        var ttl = ReadNullableNumber(Optional(value, "health_ttl_s"), "health_ttl_s") ?? 30;
        return new Route(targets, retry, healthGate, ttl);
    }

    private static RetryPolicy ReadRetry(JsonObject value)
    {
        var defaults = new RetryPolicy();
        var maxAttempts = Optional(value, "max_attempts") is { } maxAttemptsValue
            ? ReadInt32(maxAttemptsValue, "max_attempts")
            : defaults.MaxAttempts;
        var backoffBase = Optional(value, "backoff_base_s") is { } backoffBaseValue
            ? ReadNumber(backoffBaseValue, "backoff_base_s")
            : defaults.BackoffBaseS;
        var backoffMaximum = Optional(value, "backoff_max_s") is { } backoffMaximumValue
            ? ReadNumber(backoffMaximumValue, "backoff_max_s")
            : defaults.BackoffMaxS;
        return new RetryPolicy(maxAttempts, backoffBase, backoffMaximum);
    }

    private static IReadOnlyDictionary<string, StructuredOutputProfile> ReadCapabilities(JsonObject adapter)
    {
        var result = new Dictionary<string, StructuredOutputProfile>(StringComparer.Ordinal);
        foreach (var model in RequireObject(adapter, "models").Properties)
        {
            var capabilities = RequireObject(Require(RequireObject(model.Value, "model"), "capabilities"), "capabilities");
            result.Add(model.Name, new StructuredOutputProfile(
                RequireBoolean(Require(capabilities, "grammar"), "grammar"),
                RequireBoolean(Require(capabilities, "json_schema"), "json_schema"),
                RequireBoolean(Require(capabilities, "json_mode"), "json_mode")));
        }

        return result;
    }

    private static double ReadClockSeconds(JsonObject? clock) => clock is null
        ? 0
        : ReadNumber(Require(clock, "start_ms"), "start_ms") / 1000d;

    private static Target ParseTarget(string raw)
    {
        var colon = raw.IndexOf(':');
        if (colon < 0)
        {
            return new Target(raw, string.Empty);
        }

        return new Target(raw[..colon], raw[(colon + 1)..].Trim());
    }

    private static string ConsumeMode(JsonObject request) => Optional(request, "consume") is JsonString text ? text.Value : Buffered;

    private static BigInteger? CancellationCount(string consumeMode)
    {
        if (!consumeMode.StartsWith(CancelPrefix, StringComparison.Ordinal))
        {
            return null;
        }

        return BigInteger.Parse(consumeMode.AsSpan(CancelPrefix.Length), System.Globalization.CultureInfo.InvariantCulture);
    }

    private static string ReadText(JsonValue value, string name) => value switch
    {
        JsonString text => text.Value,
        JsonArray values => string.Concat(values.Items.Select(item => RequireString(item, name))),
        _ => throw new InvalidOperationException($"Fixture {name} must be text."),
    };

    private static IEnumerable<string>? ReadStop(JsonValue? value) => value switch
    {
        null or JsonNull => null,
        JsonArray values => values.Items.Select(item => RequireString(item, "stop")).ToArray(),
        _ => throw new InvalidOperationException("Fixture stop must be an array or null."),
    };

    private static JsonValue? Optional(JsonObject value, string property) => value.TryGetValue(property, out var result) ? result : null;

    private static JsonValue Require(JsonObject value, string property) => Optional(value, property) ?? throw new InvalidOperationException($"Fixture requires {property}.");

    private static JsonObject RequireObject(JsonValue value, string name) => value as JsonObject ?? throw new InvalidOperationException($"Fixture {name} must be an object.");

    private static JsonObject RequireObject(JsonObject value, string name) => Require(value, name) as JsonObject ?? throw new InvalidOperationException($"Fixture {name} must be an object.");

    private static JsonArray RequireArray(JsonObject value, string name) => Require(value, name) as JsonArray ?? throw new InvalidOperationException($"Fixture {name} must be an array.");

    private static string RequireString(JsonValue value, string name) => value is JsonString text ? text.Value : throw new InvalidOperationException($"Fixture {name} must be a string.");

    private static bool RequireBoolean(JsonValue value, string name) => value is JsonBoolean boolean ? boolean.Value : throw new InvalidOperationException($"Fixture {name} must be a boolean.");

    private static int ReadInt32(JsonValue value, string name) => ReadNullableInt32(value, name) ?? throw new InvalidOperationException($"Fixture {name} must be an integer.");

    private static int? ReadNullableInt32(JsonValue? value, string name)
    {
        if (value is null or JsonNull)
        {
            return null;
        }

        if (value is JsonInteger integer && integer.Value >= int.MinValue && integer.Value <= int.MaxValue)
        {
            return (int)integer.Value;
        }

        throw new InvalidOperationException($"Fixture {name} must be an Int32 or null.");
    }

    private static long? ReadNullableInt64(JsonValue? value, string name)
    {
        if (value is null or JsonNull)
        {
            return null;
        }

        if (value is JsonInteger integer && integer.Value >= long.MinValue && integer.Value <= long.MaxValue)
        {
            return (long)integer.Value;
        }

        throw new InvalidOperationException($"Fixture {name} must be an Int64 or null.");
    }

    private static double ReadNumber(JsonValue value, string name) => value switch
    {
        JsonInteger integer => (double)integer.Value,
        JsonNumber number => number.Value,
        _ => throw new InvalidOperationException($"Fixture {name} must be a number."),
    };

    private static double? ReadNullableNumber(JsonValue? value, string name) => value is null or JsonNull
        ? null
        : ReadNumber(value, name);

}

internal sealed record NativeExecutionSetup(
    AsyncClient Client,
    VirtualClock Clock,
    GenerationRequest Request,
    Func<int> AdapterCallCount,
    Func<int> RemainingEntries);

/// <summary>Retains actual native execution facts for development-only projection and comparison.</summary>
internal sealed record NativeRun(
    string CaseId,
    FixtureInput Input,
    string ConsumeMode,
    IReadOnlyList<GenerationEvent> Events,
    GenerationResult? Result,
    Exception? TerminalException,
    string TerminalStage,
    bool DeliberateCancellation,
    OperationCapture Capture,
    VirtualClock Clock,
    int AdapterCallCount,
    int RemainingScriptEntries,
    NativeRun? Mirror = null);
