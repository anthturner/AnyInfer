using System.Reflection;
using System.Security.Cryptography;
using System.Text.Json;
using AnyInfer;
using AnyInfer.Capabilities;
using AnyInfer.Events;
using AnyInfer.Json;
using AnyInfer.Manifest;
using AnyInfer.Providers;

return await RichGenerationProgram.RunAsync(args).ConfigureAwait(false);

/// <summary>Independent public-API recorder for the frozen rich-generation profile.</summary>
internal static class RichGenerationProgram
{
    private const string Profile = "rich-generation-v1";
    private const string FrozenSha256 = "9cff7a50fbfd553ebcfed25186173579fff582796721d0e83cc656e116cc1777";

    internal static async Task<int> RunAsync(string[] args)
    {
        if (args.Length is not (2 or 3) || (args.Length == 3 && args[2] != "--diagnose"))
            throw new ArgumentException("Usage: AnyInfer.RichGeneration INPUT OUTPUT [--diagnose].");
        var diagnosticOnly = args.Length == 3;
        var input = await File.ReadAllBytesAsync(args[0]).ConfigureAwait(false);
        ValidateInput(input);
        if (CorpusSha256(input) != FrozenSha256) throw new FormatException("The rich-generation input is not the frozen corpus.");
        using var document = JsonDocument.Parse(input);
        var observations = new List<object>();
        var unknownEvents = new List<object>();
        var caseErrors = new List<object>();
        var completedCaseIds = new List<string>();
        foreach (var item in document.RootElement.GetProperty("cases").EnumerateArray())
        {
            if (!diagnosticOnly)
            {
                observations.Add(await ExecuteCaseAsync(item, diagnosticOnly: false, unknownEvents: unknownEvents).ConfigureAwait(false));
                continue;
            }
            var caseId = item.GetProperty("id").GetString()!;
            try
            {
                _ = await ExecuteCaseAsync(item, diagnosticOnly: true, unknownEvents: unknownEvents).ConfigureAwait(false);
                completedCaseIds.Add(caseId);
            }
            catch (Exception error)
            {
                caseErrors.Add(RichProjection.Obj(("case_id", caseId), ("type", error.GetType().Name),
                    ("message", error.Message), ("inner_type", error.InnerException?.GetType().Name),
                    ("inner_message", error.InnerException?.Message)));
            }
        }
        var envelope = diagnosticOnly
            ? RichProjection.Obj(("diagnostic_only", true), ("profile", Profile), ("runtime", "csharp"),
                ("source_revision", SourceRevision()), ("source_dirty", SourceDirty()), ("corpus_sha256", CorpusSha256(input)),
                ("unknown_events", unknownEvents), ("case_errors", caseErrors), ("completed_case_ids", completedCaseIds))
            : RichProjection.Obj(("profile", Profile), ("runtime", "csharp"), ("source_revision", SourceRevision()),
                ("source_dirty", SourceDirty()), ("corpus_sha256", CorpusSha256(input)), ("observations", observations));
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(args[1]))!);
        await File.WriteAllTextAsync(args[1], JsonSerializer.Serialize(envelope, new JsonSerializerOptions { WriteIndented = true }) + "\n").ConfigureAwait(false);
        return 0;
    }

    private static async Task<object> ExecuteCaseAsync(JsonElement item, bool diagnosticOnly, List<object> unknownEvents)
    {
        var observed = new List<TelemetryEvent>();
        try { return await ExecuteCaseCoreAsync(item, observed).ConfigureAwait(false); }
        finally
        {
            if (diagnosticOnly)
                RichProjection.CaptureUnknownTelemetry(item.GetProperty("id").GetString()!, observed, unknownEvents);
        }
    }

    private static async Task<object> ExecuteCaseCoreAsync(JsonElement item, List<TelemetryEvent> observed)
    {
        var id = item.GetProperty("id").GetString()!;
        var kind = item.GetProperty("kind").GetString()!;
        var requestInput = item.GetProperty("request");
        var procedure = item.GetProperty("procedure");
        var entry = procedure.GetProperty("name").GetString()!;
        var events = new List<object>();
        var wires = new List<object>();
        var cleanup = new List<object>();
        var scriptedAdapters = new Dictionary<string, ScriptedGenerationAdapter>(StringComparer.Ordinal);
        var httpHandlers = new Dictionary<string, ScriptedHttpHandler>(StringComparer.Ordinal);
        var consumedIds = new List<string>();
        Generation? result = null;
        Exception? failure = null;
        RunManifest? manifest = null;
        GenerationRequest? request = null;

        try { request = BuildRequest(requestInput); }
        catch (Exception error) when (error is ArgumentException or FormatException or JsonException) { failure = error; }

        if (kind == "generation" && request is not null)
        {
            var descriptors = new List<ProviderDescriptor>();
            var settings = new List<ProviderSettings>();
            var defaultRegistry = ProviderRegistry.CreateDefault();
            foreach (var descriptorInput in item.GetProperty("descriptors").EnumerateArray())
            {
                var providerId = descriptorInput.GetProperty("id").GetString()!;
                var model = descriptorInput.GetProperty("model").GetString()!;
                var scripts = item.GetProperty("scripts").EnumerateArray().Where(script => script.GetProperty("provider").GetString() == providerId).ToArray();
                var transports = scripts.Select(static script => script.GetProperty("transport").GetString()!).Distinct(StringComparer.Ordinal).ToArray();
                if (transports.Length > 1) throw new FormatException("One descriptor cannot mix adapter and HTTP scripts.");
                var hasHttp = transports.Length == 1
                    ? transports[0] == "http"
                    : descriptorInput.GetProperty("wire_support").EnumerateArray().Any(static x => x.GetString() == "openai");
                Func<ProviderConfig, CancellationToken, ValueTask<IAsyncDisposable>> factory;
                if (hasHttp)
                {
                    var script = scripts.FirstOrDefault(static x => x.GetProperty("transport").GetString() == "http");
                    var handler = new ScriptedHttpHandler(providerId, script.ValueKind == JsonValueKind.Undefined ? null : script,
                        (scriptId, body) =>
                        {
                            consumedIds.Add(scriptId);
                            wires.Add(RichProjection.Obj(("transport", "http"), ("provider", providerId), ("model", model), ("body", RichProjection.HttpBody(body))));
                        },
                        (action, cleanupId) => cleanup.Add(RichProjection.Obj(("kind", action), ("id", cleanupId))));
                    httpHandlers.Add(providerId, handler);
                    factory = defaultRegistry.Get("openai-compat").Factory;
                    settings.Add(new ProviderSettings(providerId, baseUrl: "https://fixture.invalid/v1", transport: handler));
                }
                else
                {
                    factory = (_, _) =>
                    {
                        var adapter = new ScriptedGenerationAdapter(providerId, scripts,
                            (wire, script) =>
                            {
                                consumedIds.Add(script.GetProperty("id").GetString()!);
                                wires.Add(RichProjection.Obj(("transport", "adapter"), ("provider", providerId), ("model", wire.Model), ("request", RichProjection.Wire(wire))));
                            },
                            (action, cleanupId) => cleanup.Add(RichProjection.Obj(("kind", action), ("id", cleanupId))));
                        scriptedAdapters.Add(providerId, adapter);
                        return new ValueTask<IAsyncDisposable>(adapter);
                    };
                    settings.Add(new ProviderSettings(providerId));
                }
                var provenance = Enum.Parse<Provenance>(descriptorInput.GetProperty("features_provenance").GetString()!, ignoreCase: true);
                var features = Feature.None;
                foreach (var feature in descriptorInput.GetProperty("features").EnumerateArray()) features |= FeatureOf(feature.GetString()!);
                var capabilities = new ModelCapabilities(features: new Sourced<Feature>(features, provenance));
                var wireSupportsServer = descriptorInput.GetProperty("wire_support").EnumerateArray().Any(static x => x.GetString() == "server_tools");
                descriptors.Add(new ProviderDescriptor(providerId, providerId, factory,
                    defaultCapabilities: capabilities,
                    staticCapabilities: new Dictionary<string, ModelCapabilities>(StringComparer.Ordinal) { [model] = capabilities },
                    serverTools: wireSupportsServer ? ["web_search", "code_execution"] : []));
            }

            var sink = new CapturingObserver(observed);
            var clientInput = item.GetProperty("client");
            var contextGate = clientInput.GetProperty("context_gate").GetBoolean();
            global::AnyInfer.Catalog.Catalog? catalog = clientInput.GetProperty("use_default_catalog").GetBoolean()
                ? null : new global::AnyInfer.Catalog.Catalog();
            if (entry == "sync_generate")
            {
                var client = new Client(settings, new ProviderRegistry(descriptors), catalog: catalog,
                    observers: [sink], contextGate: contextGate, retainRaw: requestInput.GetProperty("retain_raw").GetBoolean());
                try { result = client.Generate(request, manifest: requestInput.GetProperty("manifest").GetBoolean()); manifest = result.Manifest; }
                catch (Exception error) { failure = error; }
                finally { client.Dispose(); cleanup.Add(RichProjection.Obj(("kind", "client_close"), ("id", "client"))); }
            }
            else
            {
                var client = new AsyncClient(settings, new ProviderRegistry(descriptors), catalog: catalog,
                    observers: [sink], contextGate: contextGate, retainRaw: requestInput.GetProperty("retain_raw").GetBoolean());
                using var callerCancellation = new CancellationTokenSource();
                await using var stream = client.StreamAsync(request, callerCancellation.Token, manifest: requestInput.GetProperty("manifest").GetBoolean());
                try
                {
                    if (entry is "async_stream_close" or "async_stream_cancel")
                    {
                        var consumeTask = ConsumeAsync(stream, events);
                        var adapter = await AwaitBarrierAdapterAsync(scriptedAdapters, consumeTask).ConfigureAwait(false);
                        await adapter.BarrierReady.WaitAsync(TimeSpan.FromSeconds(10)).ConfigureAwait(false);
                        if (entry == "async_stream_cancel") callerCancellation.Cancel();
                        else await stream.DisposeAsync().ConfigureAwait(false);
                        try { await consumeTask.ConfigureAwait(false); }
                        catch (OperationCanceledException) when (entry == "async_stream_close")
                        { cleanup.Add(RichProjection.Obj(("kind", "reader_cancelled"), ("id", "stream"))); }
                        catch (Exception error) { failure = error; }
                    }
                    else if (entry == "async_generate") result = await client.GenerateAsync(request, manifest: requestInput.GetProperty("manifest").GetBoolean()).ConfigureAwait(false);
                    else
                    {
                        await ConsumeAsync(stream, events).ConfigureAwait(false);
                        result = stream.Result;
                    }
                }
                catch (Exception error) { failure = error; }
                finally { manifest = result?.Manifest ?? stream.Manifest; }
                await stream.DisposeAsync().ConfigureAwait(false);
                await client.DisposeAsync().ConfigureAwait(false);
                cleanup.Add(RichProjection.Obj(("kind", "client_close"), ("id", "client")));
            }
            foreach (var handler in httpHandlers.Values) handler.Dispose();
        }

        var expected = procedure.GetProperty("script_ids").EnumerateArray().Select(static x => x.GetString()!).ToArray();
        if (!consumedIds.SequenceEqual(expected, StringComparer.Ordinal))
            throw new InvalidOperationException(
                $"Case {id} consumed scripts [{string.Join(",", consumedIds)}], expected [{string.Join(",", expected)}]. " +
                $"Public outcome: {(failure is null ? "no exception" : failure.GetType().Name + ": " + failure.Message)}.",
                failure);

        return RichProjection.Obj(("id", id), ("kind", kind),
            ("public", RichProjection.Obj(("entry_point", entry), ("events", events),
                ("result", result is null ? null : RichProjection.Result(result)), ("error", failure is null ? null : RichProjection.Error(failure)))),
            ("wire", RichProjection.Obj(("calls", wires))), ("cleanup", cleanup),
            ("telemetry", RichProjection.Obj(("events", observed.Select(RichProjection.Telemetry).ToArray()),
                ("manifest", RichProjection.Manifest(manifest)))));
    }

    private static async Task ConsumeAsync(AsyncStream stream, List<object> events)
    {
        var failedAttempts = 0;
        await foreach (var item in (IAsyncEnumerable<StreamEvent>)stream)
        {
            if (item is AttemptFailed) failedAttempts++;
            events.Add(RichProjection.Event(item, failedAttempts));
        }
    }

    private static async Task<ScriptedGenerationAdapter> AwaitBarrierAdapterAsync(Dictionary<string, ScriptedGenerationAdapter> adapters, Task consumeTask)
    {
        while (adapters.Count == 0 && !consumeTask.IsCompleted) await Task.Yield();
        if (adapters.Count != 1) throw new InvalidOperationException("A lifecycle case needs exactly one instantiated adapter.");
        return adapters.Values.Single();
    }

    private static Feature FeatureOf(string value) => value switch
    {
        "image" => Feature.Vision, "document" => Feature.Document, "audio" => Feature.AudioIn, "video" => Feature.VideoIn,
        "reasoning" => Feature.Reasoning, "logprobs" => Feature.Logprobs, "citations" => Feature.Citations, "tools" => Feature.Tools,
        "server_tools" => Feature.WebSearch | Feature.CodeExecution,
        _ => throw new FormatException("Unknown fixture feature: " + value),
    };

    private static GenerationRequest BuildRequest(JsonElement input)
    {
        var messages = input.GetProperty("messages").EnumerateArray().Select(BuildMessage).ToArray();
        var routeInput = input.GetProperty("route");
        var route = routeInput.ValueKind == JsonValueKind.Null
            ? new Route([input.GetProperty("target").GetString()!])
            : new Route(routeInput.GetProperty("targets").EnumerateArray().Select(static value => value.GetString()!),
                retry: new Retry(routeInput.GetProperty("retry").GetProperty("max_attempts").GetInt32()),
                healthGate: routeInput.GetProperty("health_gate").GetBoolean());
        var options = input.GetProperty("provider_options").EnumerateObject().ToDictionary(
            static property => property.Name,
            static property => (JsonObject)JsonReader.Read(property.Value.GetRawText()), StringComparer.Ordinal);
        var metadata = input.GetProperty("metadata").EnumerateObject().ToDictionary(static property => property.Name,
            static property => property.Value.GetString()!, StringComparer.Ordinal);
        var repairInput = input.GetProperty("repair");
        var schemaInput = input.GetProperty("schema");
        var entryPoint = input.GetProperty("entry_point").GetString();
        if (entryPoint is not ("astream" or "generate" or "validation")) throw new FormatException("Unknown request entry point.");
        var sampling = input.TryGetProperty("sampling", out var samplingInput) && samplingInput.ValueKind != JsonValueKind.Null
            ? new Sampling(OptionalDouble(samplingInput, "temperature"), OptionalDouble(samplingInput, "top_p"),
                OptionalInt(samplingInput, "max_output_tokens"),
                samplingInput.TryGetProperty("stop", out var stop) && stop.ValueKind != JsonValueKind.Null
                    ? stop.EnumerateArray().Select(static value => value.GetString()!) : null,
                OptionalLong(samplingInput, "seed"), OptionalDouble(samplingInput, "presence_penalty"),
                OptionalDouble(samplingInput, "frequency_penalty")) : null;
        var tools = input.TryGetProperty("tools", out var toolsInput) && toolsInput.ValueKind != JsonValueKind.Null
            ? toolsInput.EnumerateArray().Select(BuildTool).ToArray() : [];
        return new GenerationRequest(messages, route,
            sampling: sampling,
            repair: repairInput.ValueKind == JsonValueKind.Null ? null : new Repair(repairInput.GetProperty("max_attempts").GetInt32()),
            schema: schemaInput.ValueKind == JsonValueKind.Null ? null : new SchemaSpec(JsonReader.Read(schemaInput.GetProperty("json_schema").GetRawText()), schemaInput.GetProperty("name").GetString()!),
            timeoutS: OptionalDouble(input, "timeout_s"), maxResponseBytes: OptionalInt(input, "max_response_bytes"),
            stream: entryPoint == "astream", tools: tools, toolChoice: OptionalString(input, "tool_choice") ?? "auto",
            reasoning: NullableString(input, "reasoning"), providerOptions: options, metadata: metadata,
            logprobs: NullableInt(input, "logprobs"), citeDocuments: input.GetProperty("cite_documents").GetBoolean(),
            serverTools: input.GetProperty("server_tools").EnumerateArray().Select(static tool => new ServerToolSpec(tool.GetProperty("kind").GetString()!, NullableInt(tool, "max_uses"))),
            maxInputPartBytes: input.GetProperty("max_input_part_bytes").GetInt32(), maxInputBytes: input.GetProperty("max_input_bytes").GetInt32());
    }

    private static Message BuildMessage(JsonElement message) => new(message.GetProperty("role").GetString()!, message.GetProperty("content").EnumerateArray().Select(BuildPart));
    private static ToolSpec BuildTool(JsonElement tool)
    {
        var annotations = tool.TryGetProperty("annotations", out var value) && value.ValueKind != JsonValueKind.Null
            ? new ToolAnnotations(OptionalString(value, "title"), OptionalBool(value, "read_only"),
                OptionalBool(value, "destructive"), OptionalBool(value, "idempotent"), OptionalBool(value, "open_world"))
            : null;
        return new ToolSpec(tool.GetProperty("name").GetString()!, tool.GetProperty("description").GetString()!,
            (JsonObject)JsonReader.Read(tool.GetProperty("parameters").GetRawText()), annotations);
    }
    private static ContentPart BuildPart(JsonElement part) => part.GetProperty("type").GetString() switch
    {
        "text" => new Text(part.GetProperty("text").GetString()!),
        "tool_call" => new ToolCall(part.GetProperty("id").GetString()!, part.GetProperty("name").GetString()!, (JsonObject)JsonReader.Read(part.GetProperty("arguments").GetRawText())),
        "tool_result" => new ToolResult(part.GetProperty("call_id").GetString()!, part.GetProperty("content").GetString()!, part.GetProperty("is_error").GetBoolean()),
        "image" => new ImagePart(Bytes(part), NullableString(part, "url"), part.GetProperty("media_type").GetString()!, NullableString(part, "detail")),
        "document" => new DocumentPart(Bytes(part), NullableString(part, "url"), part.GetProperty("media_type").GetString()!, NullableString(part, "filename")),
        "audio" => new AudioPart(Bytes(part) ?? [], part.GetProperty("media_type").GetString()!),
        "video" => new VideoPart(Bytes(part), NullableString(part, "url"), part.GetProperty("media_type").GetString()!,
            NullableDouble(part, "start_offset_s"), NullableDouble(part, "end_offset_s"), NullableDouble(part, "fps")),
        _ => throw new FormatException("Unsupported fixture content part."),
    };

    private static byte[]? Bytes(JsonElement part)
    {
        var data = part.GetProperty("data");
        return data.ValueKind == JsonValueKind.Null ? null : Convert.FromBase64String(data.GetProperty("value").GetString()!);
    }
    private static string? NullableString(JsonElement value, string name) => value.GetProperty(name).ValueKind == JsonValueKind.Null ? null : value.GetProperty(name).GetString();
    private static int? NullableInt(JsonElement value, string name) => value.GetProperty(name).ValueKind == JsonValueKind.Null ? null : value.GetProperty(name).GetInt32();
    private static double? NullableDouble(JsonElement value, string name) => value.GetProperty(name).ValueKind == JsonValueKind.Null ? null : value.GetProperty(name).GetDouble();
    private static string? OptionalString(JsonElement value, string name) => value.TryGetProperty(name, out var item) && item.ValueKind != JsonValueKind.Null ? item.GetString() : null;
    private static int? OptionalInt(JsonElement value, string name) => value.TryGetProperty(name, out var item) && item.ValueKind != JsonValueKind.Null ? item.GetInt32() : null;
    private static long? OptionalLong(JsonElement value, string name) => value.TryGetProperty(name, out var item) && item.ValueKind != JsonValueKind.Null ? item.GetInt64() : null;
    private static double? OptionalDouble(JsonElement value, string name) => value.TryGetProperty(name, out var item) && item.ValueKind != JsonValueKind.Null ? item.GetDouble() : null;
    private static bool? OptionalBool(JsonElement value, string name) => value.TryGetProperty(name, out var item) && item.ValueKind != JsonValueKind.Null ? item.GetBoolean() : null;

    internal static void ValidateInput(ReadOnlySpan<byte> input)
    {
        if (input.StartsWith(new byte[] { 0xef, 0xbb, 0xbf })) throw new FormatException("The input must be UTF-8 without BOM.");
        RejectDuplicateKeys(input);
        using var document = JsonDocument.Parse(input.ToArray(), new JsonDocumentOptions { AllowTrailingCommas = false, CommentHandling = JsonCommentHandling.Disallow });
        var root = document.RootElement;
        if (root.GetProperty("profile").GetString() != Profile) throw new FormatException("Unexpected rich-generation profile.");
        var ids = new HashSet<string>(StringComparer.Ordinal);
        foreach (var item in root.GetProperty("cases").EnumerateArray())
            if (!ids.Add(item.GetProperty("id").GetString()!)) throw new FormatException("Duplicate rich-generation case ID.");
    }

    private static void RejectDuplicateKeys(ReadOnlySpan<byte> input)
    {
        var reader = new Utf8JsonReader(input, new JsonReaderOptions { CommentHandling = JsonCommentHandling.Disallow });
        var names = new Stack<HashSet<string>>();
        while (reader.Read())
        {
            if (reader.TokenType == JsonTokenType.StartObject) names.Push(new HashSet<string>(StringComparer.Ordinal));
            else if (reader.TokenType == JsonTokenType.EndObject) names.Pop();
            else if (reader.TokenType == JsonTokenType.PropertyName && !names.Peek().Add(reader.GetString()!))
                throw new FormatException("Duplicate JSON object key.");
        }
    }

    internal static string CorpusSha256(ReadOnlySpan<byte> input) => Convert.ToHexString(SHA256.HashData(input)).ToLowerInvariant();
    internal static string SourceRevision()
    {
        var value = typeof(AsyncClient).Assembly.GetCustomAttributes<AssemblyMetadataAttribute>()
            .SingleOrDefault(static attribute => attribute.Key == "AnyInferSourceRevision")?.Value;
        return value is { Length: 40 } && value.All(static c => c is >= '0' and <= '9' or >= 'a' and <= 'f')
            ? value : throw new InvalidOperationException("AnyInferSourceRevision metadata is required.");
    }
    internal static bool SourceDirty()
    {
        var value = Assembly.GetEntryAssembly()?.GetCustomAttributes<AssemblyMetadataAttribute>()
            .SingleOrDefault(static attribute => attribute.Key == "RichGenerationSourceDirty")?.Value;
        return bool.TryParse(value, out var dirty) ? dirty : throw new InvalidOperationException("RichGenerationSourceDirty metadata is required.");
    }

    private sealed class CapturingObserver(List<TelemetryEvent> events) : IObserver
    {
        public void OnEvent(TelemetryEvent value) => events.Add(value);
    }
}
