using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using AnyInfer;
using AnyInfer.Json;
using AnyInfer.Providers;

return await ToolLoopObserver.RunAsync(args).ConfigureAwait(false);

/// <summary>Independent public API recorder for the bounded tool-loop corpus.</summary>
internal static class ToolLoopObserver
{
    private const string Profile = "tool-loop-v1";
    private const string FrozenSha256 = "4693fca5c88e2c3ca129b7197b819c5c55bfbe11d2621135184bb7bfcfbad5a9";
    private static readonly UTF8Encoding StrictUtf8 = new(false, true);
    private static readonly string[] ExpectedIds = ["tools-final-no-calls", "tools-one-call", "tools-ordered-calls",
        "tools-repeated-id", "tools-duplicate-name", "tools-round-exhaustion", "tools-zero-rounds",
        "tools-negative-rounds", "tools-unknown-name", "tools-sync-path"];

    internal static async Task<int> RunAsync(string[] args)
    {
        if (args.Length != 2) throw new ArgumentException("Usage: AnyInfer.ToolLoop INPUT OUTPUT.");
        var bytes = await File.ReadAllBytesAsync(args[0]).ConfigureAwait(false);
        var sha = Hash(bytes);
        if (sha != FrozenSha256) throw new FormatException("The tool-loop input is not the frozen corpus.");
        if (bytes.AsSpan().StartsWith(new byte[] { 0xef, 0xbb, 0xbf })) throw new FormatException("The input must not have a BOM.");
        if (bytes.Contains((byte)'\r') || bytes.Length == 0 || bytes[^1] != (byte)'\n') throw new FormatException("The input must use LF and end with LF.");
        _ = StrictUtf8.GetString(bytes);
        RejectDuplicateKeys(bytes);
        using var input = JsonDocument.Parse(bytes, new JsonDocumentOptions { AllowTrailingCommas = false, CommentHandling = JsonCommentHandling.Disallow });
        var root = input.RootElement;
        if (root.GetProperty("profile").GetString() != Profile) throw new FormatException("Unexpected profile.");
        var cases = root.GetProperty("cases").EnumerateArray().ToArray();
        var scripts = root.GetProperty("scripts").EnumerateArray().ToArray();
        if (cases.Length != 10 || scripts.Length != 10) throw new FormatException("The frozen profile requires ten cases and scripts.");
        var ids = new HashSet<string>(StringComparer.Ordinal);
        var scriptById = new Dictionary<string, JsonElement>(StringComparer.Ordinal);
        foreach (var script in scripts)
            if (!scriptById.TryAdd(script.GetProperty("id").GetString()!, script)) throw new FormatException("Duplicate script ID.");
        for (var i = 0; i < cases.Length; i++)
        {
            var item = cases[i];
            if (!ids.Add(item.GetProperty("id").GetString()!)) throw new FormatException("Duplicate case ID.");
            if (item.GetProperty("id").GetString() != ExpectedIds[i]) throw new FormatException("Case IDs are not in frozen profile order.");
            if (item.GetProperty("script_id").GetString() != scripts[i].GetProperty("id").GetString() ||
                !scriptById.ContainsKey(item.GetProperty("script_id").GetString()!)) throw new FormatException("Script reference is not its ordered literal script.");
            ValidateCase(item);
        }
        var observations = new List<object>(cases.Length);
        foreach (var item in cases)
            observations.Add(await ObserveAsync(item, scriptById[item.GetProperty("script_id").GetString()!]).ConfigureAwait(false));
        var envelope = Obj(("profile", Profile), ("runtime", "csharp"), ("source_revision", SourceRevision()),
            ("source_dirty", SourceDirty()), ("corpus_sha256", sha), ("observations", observations));
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(args[1]))!);
        await File.WriteAllTextAsync(args[1], JsonSerializer.Serialize(envelope, new JsonSerializerOptions { WriteIndented = true }) + "\n").ConfigureAwait(false);
        return 0;
    }

    private static async Task<object> ObserveAsync(JsonElement item, JsonElement script)
    {
        var literal = item.GetProperty("request");
        var clientInput = item.GetProperty("client");
        var target = literal.GetProperty("target").GetString()!;
        var routeInput = clientInput.GetProperty("route");
        var route = new Route([target], new Retry(routeInput.GetProperty("retry").GetProperty("max_attempts").GetInt32()),
            healthGate: routeInput.GetProperty("health_gate").GetBoolean());
        var messages = literal.GetProperty("messages").EnumerateArray().Select(static message =>
            new Message(message.GetProperty("role").GetString()!, message.GetProperty("content").EnumerateArray()
                .Select(static part => (ContentPart)new Text(part.GetProperty("text").GetString()!)))).ToArray();
        var request = new GenerationRequest(messages, route, toolChoice: literal.GetProperty("tool_choice").GetString()!);
        var calls = new List<object>();
        var registrations = item.GetProperty("registrations").EnumerateArray().ToArray();
        var counters = new int[registrations.Length];
        var tools = new List<Tool>(registrations.Length);
        for (var i = 0; i < registrations.Length; i++)
        {
            var index = i;
            var registration = registrations[i];
            var specInput = registration.GetProperty("spec");
            var spec = new ToolSpec(specInput.GetProperty("name").GetString()!, specInput.GetProperty("description").GetString()!,
                (JsonObject)JsonReader.Read(specInput.GetProperty("parameters").GetRawText()));
            var handler = registration.GetProperty("handler");
            if (handler.GetProperty("kind").GetString() == "counter") counters[i] = handler.GetProperty("start").GetInt32();
            tools.Add(new Tool(spec, handler.GetProperty("async").GetBoolean()
                ? async (arguments, cancellationToken) =>
                {
                    cancellationToken.ThrowIfCancellationRequested();
                    await Task.Yield();
                    return Invoke(index, spec.Name, handler, arguments, counters, calls);
                }
                : (arguments, cancellationToken) =>
                {
                    cancellationToken.ThrowIfCancellationRequested();
                    return ValueTask.FromResult(Invoke(index, spec.Name, handler, arguments, counters, calls));
                }));
        }

        using var transport = new ToolScriptHandler(script);
        var settings = new ProviderSettings("openai-compat", baseUrl: "https://fixture.invalid/v1", transport: transport);
        global::AnyInfer.Catalog.Catalog? catalog = clientInput.GetProperty("use_default_catalog").GetBoolean()
            ? null : new global::AnyInfer.Catalog.Catalog();
        var contextGate = clientInput.GetProperty("context_gate").GetBoolean();
        var entry = literal.GetProperty("entry_point").GetString()!;
        Generation? result = null;
        ToolLoopException? error = null;
        if (entry == "sync_run_tools")
        {
            using var client = new Client([settings], catalog: catalog, contextGate: contextGate, route: route);
            try { result = client.RunTools(request, tools, literal.GetProperty("max_rounds").GetInt32()); }
            catch (ToolLoopException exception) { error = exception; }
        }
        else
        {
            await using var client = new AsyncClient([settings], catalog: catalog, contextGate: contextGate, route: route);
            try { result = await client.RunToolsAsync(request, tools, literal.GetProperty("max_rounds").GetInt32()).ConfigureAwait(false); }
            catch (ToolLoopException exception) { error = exception; }
        }
        if (transport.Consumed != script.GetProperty("responses").GetArrayLength())
            throw new InvalidOperationException($"Case {item.GetProperty("id").GetString()} consumed {transport.Consumed} of {script.GetProperty("responses").GetArrayLength()} scripted responses; public outcome: {error?.GetType().Name}: {error?.Message}", error);
        var publicResult = result is null ? null : Obj(("text", result.Text), ("finish_reason", result.FinishReason),
            ("target", result.Target is null ? throw new InvalidOperationException("Successful result has no resolved target.")
                : Obj(("provider_id", result.Target.ProviderId), ("model", result.Target.Model))),
            ("usage", Obj(("input_tokens", result.Usage?.InputTokens), ("output_tokens", result.Usage?.OutputTokens),
                ("total_tokens", result.Usage?.TotalTokens))));
        var publicError = error is null ? null : Obj(("type", error.GetType().Name), ("message", error.Message),
            ("detail", (error as AnyInferException)?.Detail), ("hint", (error as AnyInferException)?.Hint));
        return Obj(("id", item.GetProperty("id").GetString()),
            ("public", Obj(("entry_point", entry), ("result", publicResult), ("error", publicError))),
            ("requests", transport.Requests), ("handler_calls", calls));
    }

    private static object? Invoke(int index, string name, JsonElement handler, JsonObject arguments, int[] counters, List<object> calls)
    {
        object? output = handler.GetProperty("kind").GetString() switch
        {
            "constant" => NativeValue(JsonReader.Read(handler.GetProperty("value").GetRawText())),
            "echo" => arguments.TryGetValue(handler.GetProperty("argument").GetString()!, out var value)
                ? NativeValue(value) : null,
            "counter" => ++counters[index],
            _ => throw new FormatException("Unknown literal handler kind."),
        };
        calls.Add(Obj(("registration_index", index), ("name", name),
            ("arguments", JsonSerializer.Deserialize<object>(JsonWriter.Write(arguments))), ("returned_data", output)));
        return output;
    }

    private static object? NativeValue(JsonValue value) => value switch
    {
        JsonNull => null,
        JsonBoolean boolean => boolean.Value,
        JsonString text => text.Value,
        JsonInteger integer => integer.Value >= long.MinValue && integer.Value <= long.MaxValue
            ? (object)(long)integer.Value : integer.Value,
        JsonNumber number => number.Value,
        JsonArray array => array.Items.Select(NativeValue).ToArray(),
        JsonObject obj => obj.Properties.ToDictionary(static property => property.Name,
            static property => NativeValue(property.Value), StringComparer.Ordinal),
        _ => throw new FormatException("Unknown tagged JSON value."),
    };

    private static void ValidateCase(JsonElement item)
    {
        var request = item.GetProperty("request");
        if (request.GetProperty("entry_point").GetString() is not ("async_run_tools" or "sync_run_tools")) throw new FormatException("Unknown entry point.");
        _ = request.GetProperty("max_rounds").GetInt32();
        if (request.GetProperty("tool_choice").GetString() != "auto") throw new FormatException("Unknown tool choice.");
        foreach (var message in request.GetProperty("messages").EnumerateArray())
        {
            if (message.GetProperty("role").GetString() is not ("system" or "user" or "assistant")) throw new FormatException("Unknown initial role.");
            foreach (var part in message.GetProperty("content").EnumerateArray())
                if (part.GetProperty("type").GetString() != "text") throw new FormatException("Unknown initial part.");
        }
    }

    private static void RejectDuplicateKeys(ReadOnlySpan<byte> bytes)
    {
        var reader = new Utf8JsonReader(bytes, new JsonReaderOptions { AllowTrailingCommas = false, CommentHandling = JsonCommentHandling.Disallow });
        var stack = new Stack<HashSet<string>>();
        while (reader.Read())
        {
            if (reader.TokenType == JsonTokenType.StartObject) stack.Push(new HashSet<string>(StringComparer.Ordinal));
            else if (reader.TokenType == JsonTokenType.EndObject) stack.Pop();
            else if (reader.TokenType == JsonTokenType.PropertyName && !stack.Peek().Add(reader.GetString()!)) throw new FormatException("Duplicate JSON key.");
        }
    }

    private static string Hash(ReadOnlySpan<byte> bytes) => Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
    private static string SourceRevision()
    {
        var value = typeof(AsyncClient).Assembly.GetCustomAttributes<AssemblyMetadataAttribute>()
            .SingleOrDefault(static attribute => attribute.Key == "AnyInferSourceRevision")?.Value;
        return value is { Length: 40 } && value.All(static c => c is >= '0' and <= '9' or >= 'a' and <= 'f')
            ? value : throw new InvalidOperationException("AnyInferSourceRevision metadata is required.");
    }
    private static bool SourceDirty()
    {
        var value = Assembly.GetEntryAssembly()?.GetCustomAttributes<AssemblyMetadataAttribute>()
            .SingleOrDefault(static attribute => attribute.Key == "ToolLoopSourceDirty")?.Value;
        return bool.TryParse(value, out var dirty) ? dirty : throw new InvalidOperationException("ToolLoopSourceDirty metadata is required.");
    }
    private static Dictionary<string, object?> Obj(params (string Key, object? Value)[] fields) =>
        fields.ToDictionary(static field => field.Key, static field => field.Value, StringComparer.Ordinal);

    private sealed class ToolScriptHandler(JsonElement script) : HttpMessageHandler
    {
        private int _next;
        internal int Consumed => Volatile.Read(ref _next);
        internal List<object> Requests { get; } = [];

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            var index = Interlocked.Increment(ref _next) - 1;
            var responses = script.GetProperty("responses");
            if ((uint)index >= (uint)responses.GetArrayLength()) throw new InvalidOperationException("Unscripted tool-loop HTTP request.");
            var body = request.Content is null ? "" : await request.Content.ReadAsStringAsync(cancellationToken).ConfigureAwait(false);
            using var parsed = JsonDocument.Parse(body);
            var outgoing = parsed.RootElement;
            Requests.Add(Obj(("model", outgoing.GetProperty("model").GetString()),
                ("messages", outgoing.GetProperty("messages").EnumerateArray().Select(ProjectMessage).ToArray()),
                ("tools", outgoing.GetProperty("tools").EnumerateArray().Select(static tool => JsonSerializer.Deserialize<object>(tool.GetRawText())).ToArray()),
                ("tool_choice", outgoing.GetProperty("tool_choice").GetString())));
            var literal = responses[index];
            var message = Obj(("role", "assistant"), ("content", literal.GetProperty("text").GetString()),
                ("tool_calls", literal.GetProperty("tool_calls").EnumerateArray().Select(static call => Obj(
                    ("id", call.GetProperty("id").GetString()), ("type", "function"),
                    ("function", Obj(("name", call.GetProperty("name").GetString()), ("arguments", call.GetProperty("arguments").GetRawText()))))).ToArray()));
            var payload = Obj(("id", "tool-loop-script"), ("object", "chat.completion"),
                ("choices", new[] { Obj(("index", 0), ("message", message), ("finish_reason", literal.GetProperty("finish_reason").GetString())) }),
                ("usage", literal.TryGetProperty("usage", out var usage) ? JsonSerializer.Deserialize<object>(usage.GetRawText()) : null));
            return new HttpResponseMessage(System.Net.HttpStatusCode.OK)
            {
                Content = new StringContent(JsonSerializer.Serialize(payload), Encoding.UTF8, "application/json"),
            };
        }

        private static object ProjectMessage(JsonElement message)
        {
            var role = message.GetProperty("role").GetString()!;
            var content = message.GetProperty("content");
            if (role == "tool") return Obj(("role", role), ("tool_call_id", message.GetProperty("tool_call_id").GetString()),
                ("content", content.GetString()));
            if (role == "assistant" && message.TryGetProperty("tool_calls", out var calls))
                return Obj(("role", role), ("content", content.ValueKind == JsonValueKind.Null ? null : content.GetString()),
                    ("tool_calls", calls.EnumerateArray().Select(static call => JsonSerializer.Deserialize<object>(call.GetRawText())).ToArray()));
            return Obj(("role", role), ("content", content.GetString()));
        }
    }
}
