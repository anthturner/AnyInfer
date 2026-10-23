using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using JsonNode = System.Text.Json.Nodes.JsonNode;
using System.Net;
using System.Net.Http;
using AnyInfer.Capabilities;
using AnyInfer.Json;
using AnyInfer.Providers;
using AnyInfer.Routing;
using Xunit;
using JsonProperty = AnyInfer.Json.JsonProperty;

namespace AnyInfer.Tests;

/// <summary>Independent controls for generated, inert compatibility-preset metadata.</summary>
public sealed class CompatPresetDataTests
{
    private const string InventorySha256 = "47c2f58b2f4a8f9d0586c6f8ff92a171de485ef7cc73dfe496a679180e132b16";

    [Fact]
    public void Generated_table_joins_every_compat_row_to_independent_source_facts()
    {
        var bytes = File.ReadAllBytes(InventoryPath());
        Assert.Equal(InventorySha256, Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant());
        var expected = ReadCompatRows(bytes);

        Assert.Equal(1, CompatPresetTable.SchemaVersion);
        Assert.Equal(2, CompatPresetTable.GeneratorVersion);
        Assert.Equal(InventorySha256, CompatPresetTable.InventorySha256);
        Assert.Equal(expected.Select(static row => row.Id).OrderBy(static id => id, StringComparer.Ordinal),
            CompatPresetTable.Rows.Select(static row => row.Source.Id));

        foreach (var source in expected)
        {
            var actual = Assert.Single(CompatPresetTable.Rows, row => row.Source.Id == source.Id);
            var descriptor = actual.Generation.Descriptor;
            Assert.Equal(source.Id, descriptor.Id);
            Assert.Equal(source.DisplayName, descriptor.DisplayName);
            Assert.Equal(source.Aliases, descriptor.Aliases);
            Assert.Equal(source.DefaultBaseUrl, descriptor.DefaultBaseUrl);
            Assert.Equal(source.RequiresBaseUrl, descriptor.RequiresBaseUrl);
            Assert.Equal(source.Locality, descriptor.Locality.ToString().ToLowerInvariant());
            Assert.Equal(source.ContractDependencies, actual.Source.ContractDependencies);
            Assert.Equal(source.SourceOperations.OrderBy(static operation => operation, StringComparer.Ordinal), actual.Source.SourceOperations);
            Assert.True(actual.Source.SourceHonorsConnectionSettings);
            Assert.Equal(source.ModelInventory, actual.Source.SourceModelInventory);
            Assert.Equal(ToInventoryKind(source.ModelInventory), descriptor.ModelInventory);
            Assert.Equal(source.FactoryTarget, actual.Source.SourceFactoryTarget);
            Assert.Equal(source.ReasoningStyle, actual.Generation.ReasoningStyle);
            Assert.Equal(["connection-settings"], actual.PendingNativeParity);
            Assert.Equal([InferenceOperation.Generation], descriptor.Operations);
            Assert.Empty(descriptor.StaticCapabilities);
            Assert.Empty(descriptor.StaticEmbeddingCapabilities);
            Assert.Empty(descriptor.StaticRerankCapabilities);
            Assert.Empty(descriptor.StructuredOutputProfiles);
            Assert.Empty(descriptor.ServerTools);
            Assert.False(descriptor.GovernsOwnTransport);
            Assert.Null(descriptor.MaxRepairAttempts);
            Assert.Null(descriptor.CacheMechanism);
            Assert.Equal(0, descriptor.CacheMaxMarks);
            Assert.Equal(0, descriptor.CacheMinTokens);
            Assert.True(descriptor.TokenCalibration.IsIdentity);
            Assert.Null(descriptor.TokenCalibration.Tokenizer);
            Assert.Equal(Provenance.Default, descriptor.TokenCalibration.TokenizerProvenance);
            Assert.False(descriptor.RateLimitHeaders.Declared);
            Assert.Equal("", descriptor.RateLimitHeaders.RequestsRemaining);
            Assert.Equal("", descriptor.RateLimitHeaders.RequestsReset);
            Assert.Equal("", descriptor.RateLimitHeaders.TokensRemaining);
            Assert.Equal("", descriptor.RateLimitHeaders.TokensReset);
            Assert.Equal("", descriptor.RateLimitHeaders.LimitRequests);
            Assert.Equal("", descriptor.RateLimitHeaders.LimitTokens);
            Assert.True(actual.Generation.Dialect is not null);
            Assert.Equal(source.AuthHeader, actual.Generation.Dialect.AuthHeader);
            Assert.Equal(source.ModelsListing, actual.Generation.Dialect.ModelsListing);
            Assert.Equal(source.OutputTokensField, actual.Generation.Dialect.OutputTokensField);
            Assert.Equal(source.IgnoredParameters, descriptor.IgnoredParameters);
            Assert.Equal(source.SetupFields, descriptor.Setup.Fields.Select(FieldText));
            Assert.Equal(source.ModelSelection, descriptor.Setup.ModelSelection);
            Assert.Equal(source.HostShorthand, descriptor.Setup.HostShorthand is null ? null : $"{descriptor.Setup.HostShorthand.Scheme}:{descriptor.Setup.HostShorthand.DefaultPort}");
            Assert.Equal(source.AnyOf, descriptor.Setup.AnyOf.Select(static group => string.Join("|", group)));
            Assert.Equal(source.RequirementNote, descriptor.Setup.RequirementNote);
            Assert.Equal(source.FeatureProvenance, descriptor.DefaultCapabilities.Features.Provenance.ToString().ToLowerInvariant());
            Assert.Equal(source.Features.OrderBy(static feature => feature, StringComparer.Ordinal), Enum.GetValues<Feature>().Where(flag => flag != Feature.None && descriptor.DefaultCapabilities.Features.Value.HasFlag(flag)).Select(static flag => ToSourceFeature(flag)).OrderBy(static feature => feature, StringComparer.Ordinal));
            AssertSourced(source.DefaultTemperature, descriptor.DefaultCapabilities.DefaultTemperature);
            AssertSourced(source.DefaultTopP, descriptor.DefaultCapabilities.DefaultTopP);
            foreach (var effort in new string?[] { null, "none", "minimal", "low", "medium", "high", "xhigh" })
                Assert.Equal(ExpectedReasoning(source.ReasoningStyle, effort), JsonWriter.Write(descriptor.ReasoningTranslator(effort)));
        }
    }

    [Fact]
    public void Source_reader_rejects_semantic_projection_mutations()
    {
        Assert.ThrowsAny<Exception>(() => ReadCompatRows(Encoding.UTF8.GetBytes("{\"providers\":[{\"id\":\"x\",\"family\":\"compat_preset\",\"contract_dependencies\":[],\"descriptor\":{},\"preset\":null}]}")));
        var valid = File.ReadAllText(InventoryPath());
        var operationsMutation = JsonNode.Parse(valid)!.AsObject();
        var firstCompat = operationsMutation["providers"]!.AsArray()
            .Select(static item => item!.AsObject())
            .First(static item => item["family"]!.GetValue<string>() == "compat_preset");
        var operations = firstCompat["descriptor"]!["operations"]!.AsArray();
        operations.Clear();
        operations.Add("embedding");
        Assert.Throws<InvalidOperationException>(() => ReadCompatRows(Encoding.UTF8.GetBytes(operationsMutation.ToJsonString())));
        Assert.Throws<InvalidOperationException>(() => ReadCompatRows(Encoding.UTF8.GetBytes(valid.Replace("\"kind\": \"preset_ref\"", "\"kind\": \"not-a-preset-ref\"", StringComparison.Ordinal))));
        Assert.Throws<InvalidOperationException>(() => ReadCompatRows(Encoding.UTF8.GetBytes(valid.Replace("\"preset\": {", "\"other\": {}, \"preset\": {", StringComparison.Ordinal))));
        Assert.Throws<InvalidOperationException>(() => ReadCompatRows(Encoding.UTF8.GetBytes(valid.Replace("\"model_inventory\": \"served\"", "\"model_inventory\": \"available\"", StringComparison.Ordinal))));

        var source = ReadCompatRows(Encoding.UTF8.GetBytes(valid));
        var temperatureRow = source.First(static value => value.DefaultTemperature is not null);
        var temperatureCompiled = CompatPresetTable.Rows.Single(value => value.Source.Id == temperatureRow.Id);
        Assert.ThrowsAny<Exception>(() => AssertSourced(temperatureRow.DefaultTemperature! with { Provenance = "default" }, temperatureCompiled.Generation.Descriptor.DefaultCapabilities.DefaultTemperature));
        Assert.ThrowsAny<Exception>(() => Assert.Equal((double?)null, temperatureCompiled.Generation.Descriptor.DefaultCapabilities.DefaultTemperature?.Value));
        var aliasesRow = source.First(static value => value.Aliases.Count > 1);
        var aliasesCompiled = CompatPresetTable.Rows.Single(value => value.Source.Id == aliasesRow.Id);
        Assert.ThrowsAny<Exception>(() => Assert.Equal(aliasesRow.Aliases.Reverse(), aliasesCompiled.Generation.Descriptor.Aliases));
    }

    [Fact]
    public void Native_constructors_reject_non_singleton_operations_and_snapshot_inputs()
    {
        var setup = new ProviderSetupSpec();
        var capabilities = new ModelCapabilities();
        var dialect = new OpenAICompatDialectOptions();
        Assert.Throws<ArgumentException>(() => new CompatPresetGenerationRow("fixture", "Fixture", [], null, false,
            ProviderLocality.Hosted, setup, capabilities, [], dialect, CompatPresetReasoningStyle.None, [], ModelInventoryKind.Served));
        Assert.Throws<ArgumentException>(() => new CompatPresetGenerationRow("fixture", "Fixture", [], null, false,
            ProviderLocality.Hosted, setup, capabilities, [], dialect, CompatPresetReasoningStyle.None,
            [InferenceOperation.Generation, InferenceOperation.Embedding], ModelInventoryKind.Served));
        Assert.Throws<ArgumentOutOfRangeException>(() => CompatPresetReasoning.Translate((CompatPresetReasoningStyle)99, null));

        var actual = CompatPresetTable.Rows[0];
        var descriptor = actual.Generation.Descriptor;
        var mismatchedInventory = new CompatPresetGenerationRow(descriptor.Id, descriptor.DisplayName, descriptor.Aliases,
            descriptor.DefaultBaseUrl, descriptor.RequiresBaseUrl, descriptor.Locality, descriptor.Setup,
            descriptor.DefaultCapabilities, descriptor.IgnoredParameters, actual.Generation.Dialect,
            actual.Generation.ReasoningStyle, [InferenceOperation.Generation], ModelInventoryKind.Available);
        Assert.Throws<ArgumentException>(() => new CompatPresetDefinition(actual.Source, mismatchedInventory));

        var operations = new List<string> { "generation", "embedding" };
        var dependencies = new List<string> { "contracts/example.md" };
        var source = new CompatPresetSourceFacts("fixture", operations, true, "served", dependencies, "factory");
        operations.Clear();
        dependencies.Clear();
        Assert.Equal(["embedding", "generation"], source.SourceOperations);
        Assert.Equal(["contracts/example.md"], source.ContractDependencies);
    }

    [Fact]
    public async Task Generated_rows_drive_configured_public_client_wire_and_cleanup()
    {
        var rows = CompatPresetTable.Rows;
        var selected = new[]
        {
            rows.First(row => row.Generation.Dialect.AuthHeader == "x-api-key" && row.Generation.Descriptor.DefaultBaseUrl is not null),
            rows.First(row => row.Generation.Dialect.OutputTokensField == "max_completion_tokens" && row.Generation.Descriptor.DefaultBaseUrl is not null),
            rows.First(row => !row.Generation.Dialect.ModelsListing && row.Generation.Descriptor.DefaultBaseUrl is not null),
            rows.First(row => row.Generation.Descriptor.Setup.HostShorthand is not null && row.Generation.Descriptor.DefaultBaseUrl is not null),
        }.Concat(Enum.GetValues<CompatPresetReasoningStyle>().Select(style => rows.First(row => row.Generation.ReasoningStyle == style && row.Generation.Descriptor.DefaultBaseUrl is not null)))
            .DistinctBy(static row => row.Source.Id)
            .ToArray();

        foreach (var row in selected)
        {
            var descriptor = row.Generation.Descriptor;
            var handler = new PresetRecordingHandler(Chat());
            var authHeader = row.Generation.Dialect.AuthHeader == "bearer" ? "authorization" : row.Generation.Dialect.AuthHeader;
            var configuredBaseUrl = descriptor.Setup.HostShorthand?.Expand("fixture.invalid");
            var headers = new Dictionary<string, string> { [authHeader.ToUpperInvariant()] = "caller-wins", ["x-extra"] = "retained" };
            var client = new AsyncClient([ProviderSettings.Of(descriptor.Id, configuredBaseUrl, "fixture-key", headers: headers, transport: handler)],
                new ProviderRegistry([descriptor]), contextGate: false);
            try
            {
                var request = new GenerationRequest([new Message("user", [new Text("hello")])],
                    new Route([$"{descriptor.Id}:fixture-model"], healthGate: false),
                    new Sampling(maxOutputTokens: 7), reasoning: "medium",
                    providerOptions: new Dictionary<string, JsonObject> { [descriptor.Id] = new([new JsonProperty("max_tokens", new JsonInteger(11))]) });
                Assert.Equal("ok", (await client.GenerateAsync(request)).Text);
                var captured = Assert.Single(handler.Requests);
                Assert.StartsWith(configuredBaseUrl ?? descriptor.DefaultBaseUrl!, captured.Uri.AbsoluteUri, StringComparison.Ordinal);
                Assert.Equal("caller-wins", captured.Headers[authHeader]);
                Assert.NotEqual("Bearer fixture-key", captured.Headers[authHeader]);
                Assert.Equal("retained", captured.Headers["x-extra"]);
                Assert.False(captured.Body.RootElement.TryGetProperty("temperature", out _));
                if (row.Generation.Dialect.OutputTokensField != "max_tokens")
                    Assert.False(captured.Body.RootElement.TryGetProperty("max_tokens", out _));
                Assert.Equal(11, captured.Body.RootElement.GetProperty(row.Generation.Dialect.OutputTokensField).GetInt32());
                AssertReasoningWire(captured.Body.RootElement, row.Generation.ReasoningStyle, "medium");
                if (descriptor.Setup.HostShorthand is { } shorthand)
                    Assert.Equal($"{shorthand.Scheme}://fixture.invalid:{shorthand.DefaultPort}", configuredBaseUrl);
                if (row.Generation.Dialect.ModelsListing)
                {
                    continue;
                }

                Assert.Empty(await client.ModelsAsync(descriptor.Id));
                Assert.True((await client.HealthAsync(descriptor.Id)).Ok);
                Assert.Single(handler.Requests);
            }
            finally
            {
                await client.DisposeAsync();
            }
            Assert.Equal(1, handler.DisposeCalls);
        }
    }

    [Fact]
    public void Default_registry_identifiers_are_disjoint_from_inert_table()
    {
        var builtInIdentifiers = ProviderRegistry.CreateDefault().Descriptors
            .SelectMany(static descriptor => new[] { descriptor.Id }.Concat(descriptor.Aliases))
            .ToHashSet(StringComparer.Ordinal);
        var tableIdentifiers = CompatPresetTable.Rows
            .SelectMany(static row => new[] { row.Generation.Descriptor.Id }.Concat(row.Generation.Descriptor.Aliases))
            .ToArray();
        Assert.Equal(tableIdentifiers.Length, tableIdentifiers.Distinct(StringComparer.Ordinal).Count());
        Assert.DoesNotContain(tableIdentifiers, builtInIdentifiers.Contains);
    }

    [Theory]
    [MemberData(nameof(ReasoningCases))]
    public void Reasoning_translations_remain_literal(int style, string? effort, string expected)
    {
        Assert.Equal(expected, JsonWriter.Write(CompatPresetReasoning.Translate((CompatPresetReasoningStyle)style, effort)));
    }

    public static IEnumerable<object?[]> ReasoningCases()
    {
        var efforts = new string?[] { null, "none", "minimal", "low", "medium", "high", "xhigh" };
        foreach (var style in Enum.GetValues<CompatPresetReasoningStyle>())
        {
            foreach (var effort in efforts)
            {
                yield return [(int)style, effort, ExpectedReasoning(style, effort)];
            }
        }
    }

    private static string ExpectedReasoning(CompatPresetReasoningStyle style, string? effort)
    {
        if (effort is null || style == CompatPresetReasoningStyle.None) return "{}";
        return style switch
        {
            CompatPresetReasoningStyle.Effort => $"{{\"reasoning_effort\":\"{effort}\"}}",
            CompatPresetReasoningStyle.EffortMinLow or CompatPresetReasoningStyle.EffortThreeLevel => effort == "none" ? "{}" : $"{{\"reasoning_effort\":\"{(effort == "minimal" ? "low" : effort)}\"}}",
            CompatPresetReasoningStyle.EffortMinNamed => $"{{\"reasoning_effort\":\"{(effort is "none" or "minimal" ? "min" : effort)}\"}}",
            CompatPresetReasoningStyle.ReasoningObject when effort == "none" => "{\"reasoning\":{\"enabled\":false}}",
            CompatPresetReasoningStyle.ReasoningObject => $"{{\"reasoning\":{{\"effort\":\"{effort}\"}}}}",
            _ => throw new InvalidOperationException(),
        };
    }

    private static CompatPresetReasoningStyle ToReasoningStyle(string target) => target switch
    {
        "anyinfer.providers.presets._no_reasoning" => CompatPresetReasoningStyle.None,
        "anyinfer.providers.presets._translate_effort" => CompatPresetReasoningStyle.Effort,
        "anyinfer.providers.presets._translate_effort_min_low" => CompatPresetReasoningStyle.EffortMinLow,
        "anyinfer.providers.presets._translate_effort_three_level" => CompatPresetReasoningStyle.EffortThreeLevel,
        "anyinfer.providers.presets._translate_effort_min_named" => CompatPresetReasoningStyle.EffortMinNamed,
        "anyinfer.providers.presets._translate_reasoning_object" => CompatPresetReasoningStyle.ReasoningObject,
        _ => throw new InvalidOperationException("The source reasoning translator is not closed."),
    };

    private static string? ReasoningLiteral(CompatPresetReasoningStyle style) => style switch
    {
        CompatPresetReasoningStyle.None => null,
        CompatPresetReasoningStyle.Effort => "effort",
        CompatPresetReasoningStyle.EffortMinLow => "effort-min-low",
        CompatPresetReasoningStyle.EffortThreeLevel => "effort-three-level",
        CompatPresetReasoningStyle.EffortMinNamed => "effort-min-named",
        CompatPresetReasoningStyle.ReasoningObject => "reasoning-object",
        _ => throw new InvalidOperationException(),
    };

    private static ModelInventoryKind ToInventoryKind(string value) => value switch
    {
        "served" => ModelInventoryKind.Served,
        "available" => ModelInventoryKind.Available,
        "installed" => ModelInventoryKind.Installed,
        _ => throw new InvalidOperationException("The source model inventory is not closed."),
    };

    private static void AssertReasoningWire(JsonElement body, CompatPresetReasoningStyle style, string effort)
    {
        switch (style)
        {
            case CompatPresetReasoningStyle.None:
                Assert.False(body.TryGetProperty("reasoning", out _));
                Assert.False(body.TryGetProperty("reasoning_effort", out _));
                break;
            case CompatPresetReasoningStyle.ReasoningObject:
                Assert.Equal(effort, body.GetProperty("reasoning").GetProperty("effort").GetString());
                break;
            default:
                Assert.Equal(effort, body.GetProperty("reasoning_effort").GetString());
                break;
        }
    }

    private static IReadOnlyList<SourceRow> ReadCompatRows(byte[] bytes)
    {
        using var document = JsonDocument.Parse(bytes);
        var rows = new List<SourceRow>();
        foreach (var row in document.RootElement.GetProperty("providers").EnumerateArray())
        {
            if (row.GetProperty("family").GetString() != "compat_preset") continue;
            var descriptor = row.GetProperty("descriptor");
            var preset = row.GetProperty("preset");
            if (preset.ValueKind != JsonValueKind.Object || descriptor.GetProperty("id").GetString() != row.GetProperty("id").GetString() ||
                !descriptor.GetProperty("honors_connection_settings").GetBoolean() || descriptor.GetProperty("model_inventory").GetString() != "served" ||
                !descriptor.GetProperty("operations").EnumerateArray().Any(value => value.GetString() == "generation"))
                throw new InvalidOperationException("The test-only source projection is not a compatibility generation row.");
            var factory = descriptor.GetProperty("factory");
            if (factory.GetProperty("kind").GetString() != "partial" || factory.GetProperty("args").GetArrayLength() != 0 ||
                factory.GetProperty("keywords").EnumerateObject().Count() != 1 ||
                factory.GetProperty("keywords").GetProperty("preset").GetProperty("kind").GetString() != "preset_ref" ||
                factory.GetProperty("keywords").GetProperty("preset").GetProperty("id").GetString() != row.GetProperty("id").GetString())
                throw new InvalidOperationException("The source factory does not retain a matching preset reference.");
            var factoryTarget = factory.GetProperty("target").GetString()!;
            if (factoryTarget is not "anyinfer.providers.presets.PresetCompatAdapter" and not "anyinfer.providers.presets.PresetEmbeddingAdapter")
                throw new InvalidOperationException("The source factory target is not a closed preset adapter.");
            var reasoningStyle = ToReasoningStyle(descriptor.GetProperty("reasoning_translator").GetProperty("target").GetString()!);
            var rawReasoning = NullableString(preset.GetProperty("reasoning"));
            if (rawReasoning != ReasoningLiteral(reasoningStyle)) throw new InvalidOperationException("Raw preset reasoning and descriptor callable disagree.");
            var capabilities = descriptor.GetProperty("default_capabilities");
            var features = capabilities.GetProperty("features");
            var setup = descriptor.GetProperty("setup");
            rows.Add(new SourceRow(
                row.GetProperty("id").GetString()!, Strings(row.GetProperty("contract_dependencies")), Strings(descriptor.GetProperty("operations")),
                factoryTarget, descriptor.GetProperty("display_name").GetString()!, Strings(descriptor.GetProperty("aliases")),
                NullableString(descriptor.GetProperty("default_base_url")), descriptor.GetProperty("requires_base_url").GetBoolean(), descriptor.GetProperty("locality").GetString()!, descriptor.GetProperty("model_inventory").GetString()!,
                preset.GetProperty("auth_header").GetString()!, preset.GetProperty("models_listing").GetBoolean(), preset.GetProperty("output_tokens_field").GetString()!,
                Strings(descriptor.GetProperty("ignored_parameters")), setup.GetProperty("fields").EnumerateArray().Select(FieldText).ToArray(), setup.GetProperty("model_selection").GetString()!,
                setup.GetProperty("host_shorthand").ValueKind == JsonValueKind.Null ? null : $"{setup.GetProperty("host_shorthand").GetProperty("scheme").GetString()}:{setup.GetProperty("host_shorthand").GetProperty("default_port").GetInt32()}",
                setup.GetProperty("any_of").EnumerateArray().Select(group => string.Join("|", Strings(group))).ToArray(), setup.GetProperty("requirement_note").GetString()!,
                Strings(features.GetProperty("value")), features.GetProperty("provenance").GetString()!, SourceNumberFrom(capabilities.GetProperty("default_temperature")), SourceNumberFrom(capabilities.GetProperty("default_top_p")), reasoningStyle));
        }
        return rows;
    }

    private static string FieldText(SetupField field) => $"{field.Key}\u001f{field.Label}\u001f{field.Kind}\u001f{field.Required}\u001f{field.HelpText}\u001f{field.Placeholder}\u001f{field.EnvVar}\u001f{field.Advanced}\u001f{field.DefaultValue}\u001f{string.Join("|", field.Choices)}";
    private static string FieldText(JsonElement field) => $"{field.GetProperty("key").GetString()}\u001f{field.GetProperty("label").GetString()}\u001f{field.GetProperty("kind").GetString()}\u001f{field.GetProperty("required").GetBoolean()}\u001f{field.GetProperty("help_text").GetString()}\u001f{field.GetProperty("placeholder").GetString()}\u001f{field.GetProperty("env_var").GetString()}\u001f{field.GetProperty("advanced").GetBoolean()}\u001f{field.GetProperty("default_value").GetString()}\u001f{string.Join("|", Strings(field.GetProperty("choices")))}";
    private static IReadOnlyList<string> Strings(JsonElement element) => element.EnumerateArray().Select(static value => value.GetString()!).ToArray();
    private static string? NullableString(JsonElement element) => element.ValueKind == JsonValueKind.Null ? null : element.GetString();
    private static SourceNumber? SourceNumberFrom(JsonElement element) => element.ValueKind == JsonValueKind.Null ? null : new(element.GetProperty("value").GetDouble(), element.GetProperty("provenance").GetString()!);
    private static void AssertSourced(SourceNumber? expected, Sourced<double>? actual)
    {
        Assert.Equal(expected is null, actual is null);
        if (expected is not null)
        {
            Assert.Equal(expected.Value, actual!.Value);
            Assert.Equal(expected.Provenance, actual.Provenance.ToString().ToLowerInvariant());
        }
    }
    private static string ToSourceFeature(Feature feature) => feature switch
    {
        Feature.Streaming => "STREAMING",
        Feature.JsonSchema => "JSON_SCHEMA",
        Feature.Grammar => "GRAMMAR",
        Feature.JsonMode => "JSON_MODE",
        Feature.Tools => "TOOLS",
        Feature.Reasoning => "REASONING",
        Feature.SystemPrompt => "SYSTEM_PROMPT",
        Feature.CacheUsage => "CACHE_USAGE",
        Feature.CachePlacement => "CACHE_PLACEMENT",
        Feature.Vision => "VISION",
        Feature.Document => "DOCUMENT",
        Feature.AudioIn => "AUDIO_IN",
        Feature.Logprobs => "LOGPROBS",
        Feature.VideoIn => "VIDEO_IN",
        Feature.Citations => "CITATIONS",
        Feature.WebSearch => "WEB_SEARCH",
        Feature.CodeExecution => "CODE_EXECUTION",
        _ => throw new ArgumentOutOfRangeException(nameof(feature)),
    };
    private static string InventoryPath()
    {
        for (var directory = new DirectoryInfo(AppContext.BaseDirectory); directory is not null; directory = directory.Parent)
        {
            var path = Path.Combine(directory.FullName, "maintenance", "provider-parity", "python-builtins.json");
            if (File.Exists(path)) return path;
        }
        throw new FileNotFoundException("Could not locate maintenance/provider-parity/python-builtins.json.");
    }

    private static HttpResponseMessage Chat() => new(HttpStatusCode.OK)
    {
        Content = new StringContent("{\"choices\":[{\"message\":{\"content\":\"ok\"},\"finish_reason\":\"stop\"}]}", Encoding.UTF8, "application/json"),
    };

    private sealed class PresetRecordingHandler(params HttpResponseMessage[] responses) : HttpMessageHandler
    {
        private readonly Queue<HttpResponseMessage> _responses = new(responses);
        internal List<CapturedRequest> Requests { get; } = [];
        internal int DisposeCalls { get; private set; }

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            var headers = request.Headers.Concat(request.Content!.Headers)
                .ToDictionary(static pair => pair.Key.ToLowerInvariant(), static pair => string.Join(",", pair.Value), StringComparer.Ordinal);
            Requests.Add(new CapturedRequest(request.RequestUri!, headers, JsonDocument.Parse(await request.Content.ReadAsStringAsync(cancellationToken))));
            return _responses.Dequeue();
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing) DisposeCalls++;
            base.Dispose(disposing);
        }
    }

    private sealed record CapturedRequest(Uri Uri, IReadOnlyDictionary<string, string> Headers, JsonDocument Body);

    private sealed record SourceNumber(double Value, string Provenance);
    private sealed record SourceRow(string Id, IReadOnlyList<string> ContractDependencies, IReadOnlyList<string> SourceOperations, string FactoryTarget,
        string DisplayName, IReadOnlyList<string> Aliases, string? DefaultBaseUrl, bool RequiresBaseUrl, string Locality, string ModelInventory, string AuthHeader,
        bool ModelsListing, string OutputTokensField, IReadOnlyList<string> IgnoredParameters, IReadOnlyList<string> SetupFields, string ModelSelection,
        string? HostShorthand, IReadOnlyList<string> AnyOf, string RequirementNote, IReadOnlyList<string> Features, string FeatureProvenance,
                SourceNumber? DefaultTemperature, SourceNumber? DefaultTopP, CompatPresetReasoningStyle ReasoningStyle);
}
