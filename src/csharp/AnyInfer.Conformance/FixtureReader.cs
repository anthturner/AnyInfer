using AnyInfer.Json;

namespace AnyInfer.Conformance;

/// <summary>Reads the explicitly released fixture inputs from their verified byte snapshots.</summary>
internal static class FixtureReader
{
    private static readonly HashSet<string> CoreMembers = new(StringComparer.Ordinal)
    {
        "fixture_version", "id", "family", "profile", "description", "extension", "clock",
        "request", "route", "adapter", "expected",
    };

    private static readonly HashSet<string> TransportMembers = new(StringComparer.Ordinal)
    {
        "fixture_version", "id", "family", "profile", "description", "extension", "kind",
        "input", "responses", "expected",
    };

    /// <summary>Reads fixture rows in the sealed inventory order without discovering files from disk.</summary>
    internal static IReadOnlyList<FixtureDocument> ReadFixtures(ReleaseAssets assets)
    {
        ArgumentNullException.ThrowIfNull(assets);
        var files = new Dictionary<string, ReleaseFile>(StringComparer.Ordinal);
        foreach (var file in assets.Files)
        {
            if (!files.TryAdd(file.RelativePath, file))
            {
                throw new InvalidOperationException("Release contains duplicate fixture file paths.");
            }
        }

        var documents = new List<FixtureDocument>();
        var seenPaths = new HashSet<string>(StringComparer.Ordinal);
        foreach (var entry in assets.Cases)
        {
            if (entry.Kind != FixtureKind.Fixture)
            {
                continue;
            }

            if (entry.RelativePath is null || !seenPaths.Add(entry.RelativePath))
            {
                throw new InvalidOperationException("Fixture inventory contains a missing or duplicate path.");
            }

            if (!files.TryGetValue(entry.RelativePath, out var file))
            {
                throw new InvalidOperationException("Fixture inventory path is absent from the verified release assets.");
            }

            try
            {
                if (JsonReader.Read(file.Bytes.Span) is not JsonObject document)
                {
                    throw new InvalidOperationException("Fixture document root must be an object.");
                }

                documents.Add(ReadFixture(entry, document));
            }
            catch (FormatException)
            {
                throw InvalidFixture(entry.RelativePath);
            }
            catch (InvalidOperationException)
            {
                throw InvalidFixture(entry.RelativePath);
            }
        }

        return documents.AsReadOnly();
    }

    private static FixtureDocument ReadFixture(InventoryCase entry, JsonObject document)
    {
        var isTransport = document.TryGetValue("kind", out var kindValue);
        ValidateClosedObject(document, isTransport ? TransportMembers : CoreMembers, "fixture");
        ValidateIdentity(entry, document);
        _ = RequireString(Require(document, "description"), "description");
        if (document.TryGetValue("extension", out var extension))
        {
            _ = RequireString(extension, "extension");
        }

        var expected = RequireObject(document, "expected");

        if (!isTransport)
        {
            ValidateCoreEnvelope(document);
            return new FixtureDocument(
                entry,
                new CoreFixtureInput(
                    RequireObject(document, "request"),
                    RequireObject(document, "route"),
                    RequireObject(document, "adapter"),
                    document.TryGetValue("clock", out var clockValue) ? RequireObject(clockValue, "clock") : null),
                expected);
        }

        var kind = RequireString(kindValue!, "kind");
        if (!string.Equals(kind, "adapter", StringComparison.Ordinal) &&
            !string.Equals(kind, "core_http", StringComparison.Ordinal))
        {
            throw new InvalidOperationException("Transport fixture kind is not supported by the reader.");
        }

        ValidateTransportEnvelope(document, kind);
        return new FixtureDocument(
            entry,
            new TransportFixtureInput(kind, Require(document, "input"), Require(document, "responses")),
            expected);
    }

    private static void ValidateIdentity(InventoryCase entry, JsonObject document)
    {
        if (!string.Equals(RequireString(Require(document, "fixture_version"), "fixture_version"), "0", StringComparison.Ordinal) ||
            !string.Equals(RequireString(Require(document, "id"), "id"), entry.Id, StringComparison.Ordinal) ||
            !string.Equals(RequireString(Require(document, "family"), "family"), entry.Family, StringComparison.Ordinal) ||
            !string.Equals(RequireString(Require(document, "profile"), "profile"), "core-generation", StringComparison.Ordinal))
        {
            throw new InvalidOperationException("Fixture identity does not match its sealed inventory row.");
        }
    }

    private static void ValidateCoreEnvelope(JsonObject document)
    {
        ValidateRequest(RequireObject(document, "request"), allowExtendedConsume: true);
        ValidateRoute(RequireObject(document, "route"));
        ValidateAdapter(RequireObject(document, "adapter"));
        if (document.TryGetValue("clock", out var clock))
        {
            ValidateClock(RequireObject(clock, "clock"));
        }
    }

    private static void ValidateTransportEnvelope(JsonObject document, string kind)
    {
        var input = RequireObject(document, "input");
        ValidateKeys(input, "adapter_config", "wire", "operation");
        var hasWire = input.TryGetValue("wire", out var wire);
        var hasOperation = input.TryGetValue("operation", out var operation);
        if (!input.TryGetValue("adapter_config", out var config))
        {
            throw new InvalidOperationException("Transport fixture requires adapter_config.");
        }

        ValidateAdapterConfig(RequireObject(config, "adapter_config"));
        if (kind == "adapter")
        {
            if (!hasWire || hasOperation)
            {
                throw new InvalidOperationException("Adapter transport fixture requires wire only.");
            }

            ValidateWire(RequireObject(wire!, "wire"));
        }
        else
        {
            if (hasWire || !hasOperation)
            {
                throw new InvalidOperationException("Core HTTP fixture requires operation only.");
            }

            var operationObject = RequireObject(operation!, "operation");
            ValidateKeys(operationObject, "request", "route");
            ValidateRequest(RequireObject(operationObject, "request"), allowExtendedConsume: false);
            ValidateRoute(RequireObject(operationObject, "route"));
        }

        if (Require(document, "responses") is not JsonArray responses)
        {
            throw new InvalidOperationException("Transport responses must be an array.");
        }

        foreach (var response in responses.Items)
        {
            ValidateTransportResponse(response);
        }
    }

    private static void ValidateRequest(JsonObject request, bool allowExtendedConsume)
    {
        ValidateKeys(request, "messages", "schema", "sampling", "repair", "timeout_s", "max_response_bytes", "consume");
        if (!request.TryGetValue("messages", out var messagesValue) || messagesValue is not JsonArray messages)
        {
            throw new InvalidOperationException("Fixture request requires messages.");
        }

        foreach (var message in messages.Items)
        {
            ValidateMessage(message);
        }

        if (request.TryGetValue("sampling", out var sampling))
        {
            ValidateSampling(RequireObject(sampling, "sampling"));
        }

        if (request.TryGetValue("repair", out var repair))
        {
            var repairObject = RequireObject(repair, "repair");
            ValidateKeys(repairObject, "max_attempts");
            if (repairObject.TryGetValue("max_attempts", out var attempts) && attempts is not JsonInteger)
            {
                throw new InvalidOperationException("Fixture repair max_attempts must be an integer.");
            }
        }

        if (request.TryGetValue("timeout_s", out var timeout) && timeout is not JsonNull and not JsonInteger and not JsonNumber ||
            request.TryGetValue("max_response_bytes", out var maxBytes) && maxBytes is not JsonInteger)
        {
            throw new InvalidOperationException("Fixture request limits have invalid types.");
        }

        if (request.TryGetValue("consume", out var consume))
        {
            var mode = RequireString(consume, "consume");
            if (!allowExtendedConsume && mode is not "buffered" and not "stream" ||
                allowExtendedConsume && mode is not "buffered" and not "stream" &&
                    !IsCancelAfterEventsMode(mode) &&
                    mode is not "close_without_advance" and not "close_twice_after_end")
            {
                throw new InvalidOperationException("Fixture consume mode is unsupported.");
            }
        }
    }

    private static void ValidateMessage(JsonValue value)
    {
        var message = RequireObject(value, "message");
        var hasText = message.TryGetValue("text", out var text);
        var hasParts = message.TryGetValue("parts", out var parts);
        if (hasText == hasParts)
        {
            throw new InvalidOperationException("Fixture message requires exactly text or parts.");
        }

        ValidateKeys(message, "role", "text", "parts");
        _ = RequireString(Require(message, "role"), "role");
        if (hasText)
        {
            if (text is JsonString)
            {
                return;
            }

            if (text is not JsonArray strings || strings.Items.Any(static item => item is not JsonString))
            {
                throw new InvalidOperationException("Fixture message text must be a string or string array.");
            }

            return;
        }

        if (parts is not JsonArray partsArray || partsArray.Items.Count == 0)
        {
            throw new InvalidOperationException("Fixture message parts must be a nonempty array.");
        }

        foreach (var partValue in partsArray.Items)
        {
            var part = RequireObject(partValue, "part");
            _ = RequireString(Require(part, "kind"), "kind");
            var hasPartText = part.TryGetValue("text", out var partText);
            var hasUrl = part.TryGetValue("url", out var url);
            ValidateKeys(part, "kind", "text", "url", "media_type");
            if (hasPartText == hasUrl)
            {
                throw new InvalidOperationException("Fixture part has an invalid shape.");
            }

            _ = RequireString(hasPartText ? partText! : url!, hasPartText ? "text" : "url");
            if (part.TryGetValue("media_type", out var mediaType))
            {
                _ = RequireString(mediaType, "media_type");
            }
        }
    }

    private static void ValidateSampling(JsonObject sampling)
    {
        ValidateKeys(sampling, "temperature", "top_p", "presence_penalty", "frequency_penalty", "max_output_tokens", "seed", "stop");
        foreach (var property in sampling.Properties)
        {
            var allowed = property.Name is "max_output_tokens" or "seed"
                ? property.Value is JsonNull or JsonInteger
                : property.Name == "stop"
                    ? IsStringArrayOrNull(property.Value)
                    : property.Value is JsonNull or JsonInteger or JsonNumber;
            if (!allowed)
            {
                throw new InvalidOperationException("Fixture sampling value has an invalid type.");
            }
        }
    }

    private static void ValidateRoute(JsonObject route)
    {
        ValidateKeys(route, "targets", "retry", "health_gate", "health_ttl_s");
        if (!route.TryGetValue("targets", out var targetsValue) || targetsValue is not JsonArray targets || targets.Items.Count == 0 || targets.Items.Any(static item => item is not JsonString))
        {
            throw new InvalidOperationException("Fixture route requires string targets.");
        }

        if (route.TryGetValue("retry", out var retry))
        {
            var retryObject = RequireObject(retry, "retry");
            ValidateKeys(retryObject, "max_attempts", "backoff_base_s", "backoff_max_s");
            foreach (var property in retryObject.Properties)
            {
                if (property.Name == "max_attempts" ? property.Value is not JsonInteger : property.Value is not JsonInteger and not JsonNumber)
                {
                    throw new InvalidOperationException("Fixture retry value has an invalid type.");
                }
            }
        }

        if (route.TryGetValue("health_gate", out var healthGate) && healthGate is not JsonBoolean ||
            route.TryGetValue("health_ttl_s", out var healthTtl) && healthTtl is not JsonInteger and not JsonNumber)
        {
            throw new InvalidOperationException("Fixture health values have invalid types.");
        }
    }

    private static void ValidateAdapter(JsonObject adapter)
    {
        ValidateKeys(adapter, "max_repair_attempts", "models", "health_preset", "script");
        if (!adapter.TryGetValue("max_repair_attempts", out var maximum) || maximum is not JsonNull and not JsonInteger ||
            !adapter.TryGetValue("models", out var modelsValue) || modelsValue is not JsonObject models ||
            !adapter.TryGetValue("health_preset", out var healthPreset) || healthPreset is not JsonArray presets ||
            !adapter.TryGetValue("script", out var scriptValue) || scriptValue is not JsonArray script)
        {
            throw new InvalidOperationException("Fixture adapter has an invalid shape.");
        }

        foreach (var model in models.Properties)
        {
            var metadata = RequireObject(model.Value, "model metadata");
            ValidateKeys(metadata, "capabilities");
            var capabilities = RequireObject(Require(metadata, "capabilities"), "capabilities");
            ValidateKeys(capabilities, "grammar", "json_schema", "json_mode");
            foreach (var required in new[] { "grammar", "json_schema", "json_mode" })
            {
                if (!capabilities.TryGetValue(required, out var flag) || flag is not JsonBoolean)
                {
                    throw new InvalidOperationException("Fixture model capabilities are incomplete.");
                }
            }
        }

        foreach (var presetValue in presets.Items)
        {
            var preset = RequireObject(presetValue, "health preset");
            ValidateKeys(preset, "target", "failed_at_ms");
            _ = RequireString(Require(preset, "target"), "target");
            if (Require(preset, "failed_at_ms") is not JsonInteger)
            {
                throw new InvalidOperationException("Fixture health preset failed_at_ms must be an integer.");
            }
        }

        FixtureScriptValidation.ValidateScript(script);
    }

    private static void ValidateClock(JsonObject clock)
    {
        ValidateKeys(clock, "start_ms");
        if (Require(clock, "start_ms") is not JsonInteger)
        {
            throw new InvalidOperationException("Fixture clock start_ms must be an integer.");
        }
    }

    private static void ValidateAdapterConfig(JsonObject config)
    {
        ValidateKeys(config, "provider_id", "base_url", "api_key", "headers", "timeout_s");
        foreach (var required in new[] { "provider_id", "base_url", "api_key" })
        {
            _ = RequireString(Require(config, required), required);
        }

        var headers = RequireObject(Require(config, "headers"), "headers");
        if (headers.Properties.Any(static property => property.Value is not JsonString) ||
            Require(config, "timeout_s") is not JsonInteger and not JsonNumber)
        {
            throw new InvalidOperationException("Transport adapter configuration has invalid types.");
        }
    }

    private static void ValidateWire(JsonObject wire)
    {
        ValidateKeys(wire, "model", "messages", "sampling", "mechanism", "stream", "timeout_s", "max_response_bytes");
        _ = RequireString(Require(wire, "model"), "model");
        if (Require(wire, "messages") is not JsonArray messages ||
            Require(wire, "sampling") is not JsonObject sampling ||
            Require(wire, "stream") is not JsonBoolean ||
            Require(wire, "timeout_s") is not JsonInteger and not JsonNumber ||
            Require(wire, "max_response_bytes") is not JsonInteger)
        {
            throw new InvalidOperationException("Transport wire has invalid types.");
        }

        foreach (var message in messages.Items)
        {
            ValidateMessage(message);
        }

        ValidateSampling(sampling);
        var mechanism = Require(wire, "mechanism");
        if (mechanism is not JsonNull && (mechanism is not JsonString text || text.Value != "prompt"))
        {
            throw new InvalidOperationException("Transport wire mechanism is invalid.");
        }
    }

    private static void ValidateTransportResponse(JsonValue value)
    {
        var response = RequireObject(value, "response");
        ValidateKeys(response, "status", "headers", "byte_chunks");
        if (Require(response, "status") is not JsonInteger || Require(response, "headers") is not JsonObject headers || Require(response, "byte_chunks") is not JsonArray chunks ||
            headers.Properties.Any(static property => property.Value is not JsonString))
        {
            throw new InvalidOperationException("Transport response has invalid types.");
        }

        foreach (var chunkValue in chunks.Items)
        {
            var chunk = RequireObject(chunkValue, "byte chunk");
            ValidateKeys(chunk, "bytes");
            var encoded = RequireString(Require(chunk, "bytes"), "bytes");
            try
            {
                _ = Convert.FromBase64String(encoded);
            }
            catch (FormatException)
            {
                throw new InvalidOperationException("Transport byte chunk is not base64.");
            }
        }
    }

    private static void ValidateClosedObject(JsonObject value, ISet<string> allowed, string label)
    {
        foreach (var property in value.Properties)
        {
            if (!allowed.Contains(property.Name))
            {
                throw new InvalidOperationException($"{label} contains an unrecognized member.");
            }
        }
    }

    private static void ValidateKeys(JsonObject value, params string[] allowed) => ValidateClosedObject(value, new HashSet<string>(allowed, StringComparer.Ordinal), "fixture object");

    private static AssetValidationException InvalidFixture(string relativePath) =>
        new("fixture", relativePath, "Fixture execution envelope is invalid.");

    private static JsonValue Require(JsonObject value, string property) =>
        value.TryGetValue(property, out var result)
            ? result
            : throw new InvalidOperationException($"Fixture requires {property}.");

    private static JsonObject RequireObject(JsonObject value, string property) => Require(value, property) is JsonObject result
        ? result
        : throw new InvalidOperationException($"Fixture {property} must be an object.");

    private static JsonObject RequireObject(JsonValue value, string property) => value is JsonObject result
        ? result
        : throw new InvalidOperationException($"Fixture {property} must be an object.");

    private static string RequireString(JsonValue value, string property) => value is JsonString result
        ? result.Value
        : throw new InvalidOperationException($"Fixture {property} must be a string.");

    private static bool IsStringArrayOrNull(JsonValue value) => value is JsonNull ||
        value is JsonArray array && array.Items.All(static item => item is JsonString);

    private static bool IsCancelAfterEventsMode(string mode)
    {
        const string Prefix = "stream_cancel_after_events:";
        if (!mode.StartsWith(Prefix, StringComparison.Ordinal) || mode.Length == Prefix.Length)
        {
            return false;
        }

        var suffix = mode.AsSpan(Prefix.Length);
        if (suffix[0] is < '1' or > '9')
        {
            return false;
        }

        foreach (var character in suffix[1..])
        {
            if (character is < '0' or > '9')
            {
                return false;
            }
        }

        return true;
    }
}

/// <summary>Separates the executable fixture input from comparator-only expected data.</summary>
internal sealed record FixtureDocument(InventoryCase Case, FixtureInput Input, JsonObject Expected);

/// <summary>Represents raw executable fixture input without interpreting expected observations.</summary>
internal abstract record FixtureInput;

/// <summary>Represents a core fixture's raw request, route, and adapter envelopes.</summary>
internal sealed record CoreFixtureInput(JsonObject Request, JsonObject Route, JsonObject Adapter, JsonObject? Clock = null) : FixtureInput;

/// <summary>Represents a transport fixture's raw input and response script.</summary>
internal sealed record TransportFixtureInput(string Kind, JsonValue Input, JsonValue Responses) : FixtureInput;
