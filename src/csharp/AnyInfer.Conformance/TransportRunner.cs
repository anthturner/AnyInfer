using System.Numerics;
using AnyInfer.Json;
using AnyInfer.Providers;

namespace AnyInfer.Conformance;

/// <summary>Executes released transport inputs through the real OpenAI-compatible adapter without expected data.</summary>
internal static class TransportRunner
{
    private const string Buffered = "buffered";

    internal static async Task<TransportRun> RunAsync(
        string caseId,
        TransportFixtureInput input,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(caseId);
        ArgumentNullException.ThrowIfNull(input);

        var fixtureInput = RequireObject(input.Input, "input");
        var configuration = ReadConfiguration(RequireObject(fixtureInput, "adapter_config"));
        using var handler = new ScriptedHttpMessageHandler(
            RequireArray(input.Responses, "responses"),
            configuration.Headers.Keys);
        var nativeAdapter = new OpenAIChatAdapter(
            configuration.BaseUrl,
            configuration.ApiKey,
            configuration.Headers,
            handler);
        await using var adapter = new RecordingHttpAdapter(nativeAdapter, handler);

        return input.Kind switch
        {
            "adapter" => await RunDirectAsync(
                caseId,
                input,
                adapter,
                handler,
                RequireObject(fixtureInput, "wire"),
                cancellationToken).ConfigureAwait(false),
            "core_http" => await RunCoreAsync(
                caseId,
                input,
                configuration.ProviderId,
                adapter,
                handler,
                RequireObject(fixtureInput, "operation"),
                cancellationToken).ConfigureAwait(false),
            _ => throw new TransportHarnessException("The transport fixture kind is not executable."),
        };
    }

    private static async Task<TransportRun> RunDirectAsync(
        string caseId,
        TransportFixtureInput input,
        RecordingHttpAdapter adapter,
        ScriptedHttpMessageHandler handler,
        JsonObject wire,
        CancellationToken cancellationToken)
    {
        var events = new List<AdapterEvent>();
        ProviderException? terminalException = null;
        var terminalStage = "complete";
        try
        {
            await foreach (var adapterEvent in adapter.GenerateAsync(
                ReadWireRequest(wire),
                cancellationToken).ConfigureAwait(false))
            {
                events.Add(adapterEvent);
            }
        }
        catch (ProviderException exception)
        {
            terminalException = exception;
            terminalStage = exception.Phase ?? "adapter";
        }

        await adapter.DisposeAsync().ConfigureAwait(false);
        EnsureCompleted(handler, adapter);
        return new TransportRun(
            caseId,
            input,
            handler.Exchanges,
            adapter.WireRequests,
            adapter.CallCount,
            handler.ActualRequestCount,
            handler.RemainingResponses,
            Core: null,
            DirectEvents: Array.AsReadOnly(events.ToArray()),
            TerminalException: terminalException,
            TerminalStage: terminalStage,
            HandlerDisposed: handler.IsDisposed);
    }

    private static async Task<TransportRun> RunCoreAsync(
        string caseId,
        TransportFixtureInput input,
        string providerId,
        RecordingHttpAdapter adapter,
        ScriptedHttpMessageHandler handler,
        JsonObject operation,
        CancellationToken cancellationToken)
    {
        var request = RequireObject(operation, "request");
        var route = RequireObject(operation, "route");
        var consumeMode = OptionalString(request, "consume") ?? Buffered;
        var clock = new VirtualClock(0);
        var client = new AsyncClient([new ProviderRegistration(providerId, adapter)], clock);
        var setup = new NativeExecutionSetup(
            client,
            clock,
            NativeRunner.ReadOperationRequest(request, route, consumeMode),
            () => adapter.CallCount,
            () => adapter.RemainingEntries);
        var core = await NativeRunner.RunPreparedAsync(
            caseId,
            input,
            consumeMode,
            setup,
            cancellationToken).ConfigureAwait(false);

        await adapter.DisposeAsync().ConfigureAwait(false);
        EnsureCompleted(handler, adapter);
        return new TransportRun(
            caseId,
            input,
            handler.Exchanges,
            adapter.WireRequests,
            adapter.CallCount,
            handler.ActualRequestCount,
            handler.RemainingResponses,
            core,
            DirectEvents: [],
            TerminalException: null,
            TerminalStage: "core",
            HandlerDisposed: handler.IsDisposed);
    }

    private static void EnsureCompleted(ScriptedHttpMessageHandler handler, RecordingHttpAdapter adapter)
    {
        if (handler.RemainingResponses != 0)
        {
            throw new TransportHarnessException("The transport fixture has unconsumed scripted responses.");
        }

        foreach (var exchange in handler.Exchanges)
        {
            if (!exchange.ResponseDisposed || !exchange.ContentDisposed ||
                exchange.CreatedStreamCount != exchange.DisposedStreamCount ||
                exchange.AutomaticSerializationRequested)
            {
                throw new TransportHarnessException("The native HTTP exchange did not close its owned resources.");
            }
        }

        if (adapter.RemainingEntries != 0)
        {
            throw new TransportHarnessException("The recording adapter retained scripted responses.");
        }

        if (!handler.IsDisposed)
        {
            throw new TransportHarnessException("The native HTTP handler was not disposed.");
        }
    }

    private static TransportConfiguration ReadConfiguration(JsonObject configuration)
    {
        var headers = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (var property in RequireObject(configuration, "headers").Properties)
        {
            headers.Add(property.Name, RequireString(property.Value, "header"));
        }

        _ = ReadNumber(Require(configuration, "timeout_s"), "timeout_s");
        return new TransportConfiguration(
            RequireString(Require(configuration, "provider_id"), "provider_id"),
            new Uri(RequireString(Require(configuration, "base_url"), "base_url"), UriKind.Absolute),
            RequireString(Require(configuration, "api_key"), "api_key"),
            headers);
    }

    private static WireRequest ReadWireRequest(JsonObject wire) => new(
        RequireString(Require(wire, "model"), "model"),
        RequireArray(wire, "messages").Items.Select(ReadMessage),
        ReadSampling(RequireObject(wire, "sampling")),
        schema: null,
        mechanism: OptionalString(wire, "mechanism"),
        stream: RequireBoolean(Require(wire, "stream"), "stream"),
        timeoutS: ReadNumber(Require(wire, "timeout_s"), "timeout_s"),
        maxResponseBytes: ReadInt32(Require(wire, "max_response_bytes"), "max_response_bytes"));

    private static Message ReadMessage(JsonValue value)
    {
        var message = RequireObject(value, "message");
        var role = RequireString(Require(message, "role"), "role");
        if (message.TryGetValue("text", out var text))
        {
            return new Message(role, [new TextPart(ReadText(text, "text"))]);
        }

        return new Message(role, RequireArray(message, "parts").Items.Select(ReadPart));
    }

    private static ContentPart ReadPart(JsonValue value)
    {
        var part = RequireObject(value, "part");
        var kind = RequireString(Require(part, "kind"), "kind");
        return part.TryGetValue("text", out var text)
            ? new TextPart(RequireString(text, "text"))
            : new UnsupportedContentPart(kind, part);
    }

    private static Sampling ReadSampling(JsonObject value) => new(
        temperature: ReadNullableNumber(Optional(value, "temperature"), "temperature"),
        topP: ReadNullableNumber(Optional(value, "top_p"), "top_p"),
        maxOutputTokens: ReadNullableInt32(Optional(value, "max_output_tokens"), "max_output_tokens"),
        stop: ReadStop(Optional(value, "stop")),
        seed: ReadNullableInt64(Optional(value, "seed"), "seed"),
        presencePenalty: ReadNullableNumber(Optional(value, "presence_penalty"), "presence_penalty"),
        frequencyPenalty: ReadNullableNumber(Optional(value, "frequency_penalty"), "frequency_penalty"));

    private static string ReadText(JsonValue value, string name) => value switch
    {
        JsonString text => text.Value,
        JsonArray values => string.Concat(values.Items.Select(item => RequireString(item, name))),
        _ => throw new InvalidOperationException($"Transport {name} must be text."),
    };

    private static IEnumerable<string>? ReadStop(JsonValue? value) => value switch
    {
        null or JsonNull => null,
        JsonArray values => values.Items.Select(item => RequireString(item, "stop")).ToArray(),
        _ => throw new InvalidOperationException("Transport stop must be an array or null."),
    };

    private static JsonValue? Optional(JsonObject value, string property) =>
        value.TryGetValue(property, out var result) ? result : null;

    private static string? OptionalString(JsonObject value, string property) => Optional(value, property) switch
    {
        null or JsonNull => null,
        JsonString text => text.Value,
        _ => throw new InvalidOperationException($"Transport {property} must be a string or null."),
    };

    private static JsonValue Require(JsonObject value, string property) =>
        Optional(value, property) ?? throw new InvalidOperationException($"Transport input requires {property}.");

    private static JsonObject RequireObject(JsonObject value, string property) =>
        Require(value, property) as JsonObject ?? throw new InvalidOperationException($"Transport {property} must be an object.");

    private static JsonObject RequireObject(JsonValue value, string property) =>
        value as JsonObject ?? throw new InvalidOperationException($"Transport {property} must be an object.");

    private static JsonArray RequireArray(JsonObject value, string property) =>
        Require(value, property) as JsonArray ?? throw new InvalidOperationException($"Transport {property} must be an array.");

    private static JsonArray RequireArray(JsonValue value, string property) =>
        value as JsonArray ?? throw new InvalidOperationException($"Transport {property} must be an array.");

    private static string RequireString(JsonValue value, string property) =>
        value is JsonString text ? text.Value : throw new InvalidOperationException($"Transport {property} must be a string.");

    private static bool RequireBoolean(JsonValue value, string property) =>
        value is JsonBoolean boolean ? boolean.Value : throw new InvalidOperationException($"Transport {property} must be a boolean.");

    private static int ReadInt32(JsonValue value, string property) =>
        ReadNullableInt32(value, property) ?? throw new InvalidOperationException($"Transport {property} must be an integer.");

    private static int? ReadNullableInt32(JsonValue? value, string property)
    {
        if (value is null or JsonNull)
        {
            return null;
        }

        if (value is JsonInteger integer && integer.Value >= int.MinValue && integer.Value <= int.MaxValue)
        {
            return (int)integer.Value;
        }

        throw new InvalidOperationException($"Transport {property} must be an Int32 or null.");
    }

    private static long? ReadNullableInt64(JsonValue? value, string property)
    {
        if (value is null or JsonNull)
        {
            return null;
        }

        if (value is JsonInteger integer && integer.Value >= long.MinValue && integer.Value <= long.MaxValue)
        {
            return (long)integer.Value;
        }

        throw new InvalidOperationException($"Transport {property} must be an Int64 or null.");
    }

    private static double? ReadNullableNumber(JsonValue? value, string property) =>
        value is null or JsonNull ? null : ReadNumber(value, property);

    private static double ReadNumber(JsonValue value, string property) => value switch
    {
        JsonInteger integer => (double)integer.Value,
        JsonNumber number => number.Value,
        _ => throw new InvalidOperationException($"Transport {property} must be a number."),
    };

    private sealed record TransportConfiguration(
        string ProviderId,
        Uri BaseUrl,
        string ApiKey,
        IReadOnlyDictionary<string, string> Headers);
}

/// <summary>Retains actual native transport execution facts for later projection and comparison.</summary>
internal sealed record TransportRun(
    string CaseId,
    TransportFixtureInput Input,
    IReadOnlyList<RecordedHttpExchange> Exchanges,
    IReadOnlyList<WireRequest> WireRequests,
    int AdapterCallCount,
    int ActualHttpRequestCount,
    int RemainingResponses,
    NativeRun? Core,
    IReadOnlyList<AdapterEvent> DirectEvents,
    ProviderException? TerminalException,
    string TerminalStage,
    bool HandlerDisposed);
