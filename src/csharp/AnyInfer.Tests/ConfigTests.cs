using System.Runtime.CompilerServices;
using System.Net;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using AnyInfer.Config;
using AnyInfer.Credentials;
using AnyInfer.Json;
using AnyInfer.Providers;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Version-1 inert configuration parsing, serialization, and configured-client behavior.</summary>
public sealed class ConfigTests
{
    [Fact]
    public void V1_loads_is_strict_last_property_wins_and_ignores_only_documented_inert_demo_content()
    {
        var config = AnyInferConfig.Loads("""
            {
              "_comment": 7,
              "format_version": 1,
              "providers": [
                {"enabled": false, "not_a_real_key": {"anything": true}},
                {"id": "Primary", "adapter": "fake", "timeout_s": 1, "timeout_s": 2}
              ],
              "default_route": ["primary:model", "backup:model"],
              "repair": {"max_attempts": 1},
              "targets": {"demo": "inert"},
              "theme": ["also", "inert"]
            }
            """, Registry());

        Assert.Equal(AnyInferConfig.FormatVersion1, config.FormatVersion);
        var provider = Assert.Single(config.Providers);
        Assert.Equal("primary", provider.InstanceId);
        Assert.Equal("fake", provider.ProviderId);
        Assert.Equal(2, provider.TimeoutS);
        Assert.Equal(["primary:model", "backup:model"], config.Route!.Targets);
        Assert.Equal(1, config.Repair!.MaxAttempts);
    }

    [Theory]
    [InlineData("[]")]
    [InlineData("{\"format_version\":true}")]
    [InlineData("{\"format_version\":1.0}")]
    [InlineData("{\"unknown\":true}")]
    [InlineData("{\"providers\":{}}")]
    [InlineData("{\"default_route\":\"fake:model\"}")]
    [InlineData("{\"default_route\":{\"targets\":[\"fake:model\"],\"context_window_targets\":[\"larger:model\"]}}")]
    [InlineData("{\"context\":null}")]
    [InlineData("{\"history\":null}")]
    public void V1_loads_rejects_invalid_type_unknown_or_active_unsupported_policy(string document)
    {
        Assert.Throws<ConfigException>(() => AnyInferConfig.Loads(document, Registry()));
    }

    [Fact]
    public void V1_loads_rejects_oversize_invalid_utf16_and_duplicate_normalized_instances()
    {
        Assert.Throws<ConfigException>(() => AnyInferConfig.Loads(new string(' ', AnyInferConfig.MaximumBytes + 1), Registry()));
        Assert.Throws<ConfigException>(() => AnyInferConfig.Loads("\ud800", Registry()));
        Assert.Throws<ConfigException>(() => AnyInferConfig.Loads("""
            {"providers":[
              {"id":"Work_A", "adapter":"fake"},
              {"id":"work-a", "adapter":"fake"}
            ]}
            """, Registry()));
    }

    [Fact]
    public void Provider_identity_values_options_headers_timeout_route_and_repair_follow_the_v1_precedence_rules()
    {
        var config = AnyInferConfig.Loads("""
            {"providers":[{
                "id":"tenant_a", "adapter":"fake", "provider_id":"FAKE",
                "alias":"tenant-a",
                "base_url":null,
                "api_key":"",
                "values":{"base_url":"https://ignored.example", "api_key":"env://IGNORED", "region":"values-region", "token":"vault://inert"},
                "options":{"region":"options-region"},
                "headers":{"X-App":"configuration"}, "timeout_s":7.25
              }],
              "default_route":["tenant-a:model"],
              "repair":{"max_attempts":0}}
            """, Registry());

        var provider = Assert.Single(config.Providers);
        Assert.Equal("tenant-a", provider.InstanceId);
        Assert.Null(provider.BaseUrl);
        Assert.Null(provider.ApiKey);
        Assert.Equal("configuration", provider.Headers["X-App"]);
        Assert.Equal(7.25, provider.TimeoutS);
        Assert.Equal("options-region", StringProperty(Assert.IsType<JsonObject>(provider.Options), "region"));
        Assert.Equal("\"vault://inert\"", JsonWriter.Write(Assert.IsType<JsonObject>(provider.Options).Properties.Single(property => property.Name == "token").Value));
        Assert.Equal(0, config.Repair!.MaxAttempts);

        Assert.Null(AnyInferConfig.Loads("{\"repair\":null}", Registry()).Repair);
        Assert.Throws<ConfigException>(() => AnyInferConfig.Loads("{\"repair\":{\"max_attempts\":1.0}}", Registry()));
        Assert.Throws<ConfigException>(() => AnyInferConfig.Loads("{\"repair\":{\"max_attempts\":-1}}", Registry()));
        Assert.Throws<ConfigException>(() => AnyInferConfig.Loads("{\"repair\":{\"extra\":1}}", Registry()));
        Assert.Throws<ConfigException>(() => AnyInferConfig.Loads("{\"providers\":[{\"id\":\"fake\",\"headers\":{\"x\":1}}]}", Registry()));
        Assert.Throws<ConfigException>(() => AnyInferConfig.Loads("{\"providers\":[{\"id\":\"fake\",\"timeout_s\":0}]}", Registry()));
    }

    [Fact]
    public void Provider_limits_parse_as_an_opt_in_block_and_round_trip_with_changed_fields_only()
    {
        var configured = AnyInferConfig.Loads("""
            {"providers":[{"id":"fake","limits":{}}]}
            """, Registry());
        var defaults = Assert.IsType<RateLimits>(Assert.Single(configured.Providers).Limits);
        Assert.True(defaults.Active);
        Assert.Null(AnyInferConfig.Loads("{\"providers\":[{\"id\":\"fake\",\"limits\":null}]}", Registry()).Providers.Single().Limits);

        var parsed = AnyInferConfig.Loads("""
            {"providers":[{"id":"fake","limits":{
              "max_concurrent":2,"requests_per_minute":12.5,"min_interval_s":0.25,
              "respect_headers":false,"reserve_fraction":0.5
            }}]}
            """, Registry());
        var limits = Assert.IsType<RateLimits>(Assert.Single(parsed.Providers).Limits);
        Assert.Equal(2, limits.MaxConcurrent);
        Assert.Equal(12.5, limits.RequestsPerMinute);
        Assert.Equal(0.25, limits.MinIntervalS);
        Assert.False(limits.RespectHeaders);
        Assert.Equal(0.5, limits.ReserveFraction);
        Assert.Equal(limits, Assert.IsType<RateLimits>(Assert.Single(AnyInferConfig.Loads(parsed.Dumps(), Registry()).Providers).Limits));

        var defaultProvider = Assert.IsType<JsonObject>(Assert.Single(ArrayProperty(Assert.IsType<JsonObject>(JsonReader.Read(configured.Dumps())), "providers").Items));
        Assert.Empty(ObjectProperty(defaultProvider, "limits").Properties);

        var configuredProvider = Assert.IsType<JsonObject>(Assert.Single(ArrayProperty(Assert.IsType<JsonObject>(JsonReader.Read(parsed.Dumps())), "providers").Items));
        var serializedLimits = ObjectProperty(configuredProvider, "limits");
        Assert.Equal(
            ["max_concurrent", "min_interval_s", "requests_per_minute", "reserve_fraction", "respect_headers"],
            serializedLimits.Properties.Select(static property => property.Name));
        Assert.Equal(2, IntegerProperty(serializedLimits, "max_concurrent"));
        Assert.Equal(12.5, Assert.IsType<JsonNumber>(ValueProperty(serializedLimits, "requests_per_minute")).Value);
        Assert.Equal(0.25, Assert.IsType<JsonNumber>(ValueProperty(serializedLimits, "min_interval_s")).Value);
        Assert.False(Assert.IsType<JsonBoolean>(ValueProperty(serializedLimits, "respect_headers")).Value);
        Assert.Equal(0.5, Assert.IsType<JsonNumber>(ValueProperty(serializedLimits, "reserve_fraction")).Value);

        var partial = AnyInferConfig.Loads("{\"providers\":[{\"id\":\"fake\",\"limits\":{\"max_concurrent\":2}}]}", Registry());
        var partialProvider = Assert.IsType<JsonObject>(Assert.Single(ArrayProperty(Assert.IsType<JsonObject>(JsonReader.Read(partial.Dumps())), "providers").Items));
        var partialLimits = ObjectProperty(partialProvider, "limits");
        Assert.Equal("max_concurrent", Assert.Single(partialLimits.Properties).Name);
        Assert.Equal(2, IntegerProperty(partialLimits, "max_concurrent"));
    }

    [Theory]
    [InlineData("{\"providers\":[{\"id\":\"fake\",\"limits\":true}]}")]
    [InlineData("{\"providers\":[{\"id\":\"fake\",\"limits\":{\"unknown\":1}}]}")]
    [InlineData("{\"providers\":[{\"id\":\"fake\",\"limits\":{\"max_concurrent\":true}}]}")]
    [InlineData("{\"providers\":[{\"id\":\"fake\",\"limits\":{\"max_concurrent\":2147483648}}]}")]
    [InlineData("{\"providers\":[{\"id\":\"fake\",\"limits\":{\"requests_per_minute\":0}}]}")]
    [InlineData("{\"providers\":[{\"id\":\"fake\",\"limits\":{\"min_interval_s\":-1}}]}")]
    [InlineData("{\"providers\":[{\"id\":\"fake\",\"limits\":{\"respect_headers\":1}}]}")]
    [InlineData("{\"providers\":[{\"id\":\"fake\",\"limits\":{\"reserve_fraction\":1}}]}")]
    public void Provider_limits_are_strict_and_fail_closed(string document)
    {
        Assert.Throws<ConfigException>(() => AnyInferConfig.Loads(document, Registry()));
    }

    [Fact]
    public void Root_cache_is_strict_nullable_and_round_trips_its_declared_tuning()
    {
        var defaults = AnyInferConfig.Loads("{\"cache\":{}}", Registry());
        var defaultCache = Assert.IsType<CachePolicy>(defaults.Cache);
        Assert.Equal(CacheMode.Auto, defaultCache.Mode);
        Assert.Equal(1024, defaultCache.MinSegmentTokens);
        Assert.Equal(4, defaultCache.MaxMarks);
        Assert.True(defaultCache.IncludeTools);
        Assert.True(defaultCache.IncludeSystem);
        Assert.Equal(defaultCache, Assert.IsType<CachePolicy>(AnyInferConfig.Loads(defaults.Dumps(), Registry()).Cache));
        Assert.Null(AnyInferConfig.Loads("{\"cache\":null}", Registry()).Cache);
        Assert.Equal(CacheMode.Off, Assert.IsType<CachePolicy>(AnyInferConfig.Loads("{\"cache\":{\"mode\":\"off\"}}", Registry()).Cache).Mode);

        var configured = AnyInferConfig.Loads("""
            {"cache":{"mode":"explicit","min_segment_tokens":0,"max_marks":1,
            "include_tools":false,"include_system":false}}
            """, Registry());
        var cache = Assert.IsType<CachePolicy>(configured.Cache);
        Assert.Equal(CacheMode.Explicit, cache.Mode);
        Assert.Equal(0, cache.MinSegmentTokens);
        Assert.Equal(1, cache.MaxMarks);
        Assert.False(cache.IncludeTools);
        Assert.False(cache.IncludeSystem);
        Assert.Equal(cache, Assert.IsType<CachePolicy>(AnyInferConfig.Loads(configured.Dumps(), Registry()).Cache));

        var serializedDefaults = Assert.IsType<JsonObject>(JsonReader.Read(defaults.Dumps()));
        Assert.Empty(ObjectProperty(serializedDefaults, "cache").Properties);

        var serializedConfigured = Assert.IsType<JsonObject>(JsonReader.Read(configured.Dumps()));
        var serializedCache = ObjectProperty(serializedConfigured, "cache");
        Assert.Equal(
            ["include_system", "include_tools", "max_marks", "min_segment_tokens", "mode"],
            serializedCache.Properties.Select(static property => property.Name));
        Assert.Equal("explicit", StringProperty(serializedCache, "mode"));
        Assert.Equal(0, IntegerProperty(serializedCache, "min_segment_tokens"));
        Assert.Equal(1, IntegerProperty(serializedCache, "max_marks"));
        Assert.False(Assert.IsType<JsonBoolean>(ValueProperty(serializedCache, "include_tools")).Value);
        Assert.False(Assert.IsType<JsonBoolean>(ValueProperty(serializedCache, "include_system")).Value);

        var partial = AnyInferConfig.Loads("{\"cache\":{\"mode\":\"off\"}}", Registry());
        var partialCache = ObjectProperty(Assert.IsType<JsonObject>(JsonReader.Read(partial.Dumps())), "cache");
        Assert.Equal("mode", Assert.Single(partialCache.Properties).Name);
        Assert.Equal("off", StringProperty(partialCache, "mode"));
    }

    [Theory]
    [InlineData("{\"cache\":true}")]
    [InlineData("{\"cache\":{\"mode\":\"unexpected\"}}")]
    [InlineData("{\"cache\":{\"mode\":true}}")]
    [InlineData("{\"cache\":{\"min_segment_tokens\":true}}")]
    [InlineData("{\"cache\":{\"min_segment_tokens\":9223372036854775808}}")]
    [InlineData("{\"cache\":{\"min_segment_tokens\":-1}}")]
    [InlineData("{\"cache\":{\"max_marks\":true}}")]
    [InlineData("{\"cache\":{\"max_marks\":0}}")]
    [InlineData("{\"cache\":{\"include_tools\":1}}")]
    [InlineData("{\"cache\":{\"unknown\":true}}")]
    public void Root_cache_rejects_unknown_or_wrongly_typed_values(string document)
    {
        Assert.Throws<ConfigException>(() => AnyInferConfig.Loads(document, Registry()));
    }

    [Fact]
    public void Default_route_serialization_refuses_public_context_window_targets_that_v1_cannot_represent()
    {
        var config = new AnyInferConfig(route: new Route(["fake:model"], contextWindowTargets: ["larger:model"]));
        Assert.Throws<ConfigException>(() => config.Dumps());
    }

    [Fact]
    public void Loading_direct_api_key_validates_scheme_but_generic_secret_and_choice_options_remain_inert_until_selection()
    {
        var resolver = new CountingResolver();
        var chain = new ResolverChain([resolver]);
        var registry = Registry();

        Assert.Throws<ConfigException>(() => AnyInferConfig.Loads("{\"providers\":[{\"id\":\"fake\",\"api_key\":\"unhandled://key\"}]}", registry, chain));
        var config = AnyInferConfig.Loads("""
            {"providers":[{"id":"fake", "token":"vault://inert", "region":"invalid-choice"}]}
            """, registry, chain);

        Assert.Single(config.Providers);
        Assert.Equal(0, resolver.ResolveCalls);
    }

    [Fact]
    public async Task Selected_provider_validates_deferred_choice_before_constructing_an_adapter()
    {
        var factoryCalls = 0;
        var registry = new ProviderRegistry([
            new ProviderDescriptor("fake", "Fake", (_, _) =>
            {
                factoryCalls++;
                return ValueTask.FromResult<IAsyncDisposable>(new CountingAdapter());
            }, setup: new ProviderSetupSpec([
                new SetupField("region", "Region", "choice", choices: ["east", "west"]),
            ])),
        ]);
        var config = AnyInferConfig.Loads("""
            {"providers":[{"id":"fake", "region":"not-a-choice"}], "default_route":["fake:model"]}
            """, registry);

        await using var client = AsyncClient.FromConfig(config, registry);
        var stream = client.StreamAsync("configured");
        Assert.Equal(0, factoryCalls);

        await Assert.ThrowsAsync<ConfigException>(() => stream.CollectAsync());
        Assert.Equal(0, factoryCalls);
    }

    [Fact]
    public void Dumps_and_dump_preserve_credential_references_without_leaking_them_from_repr()
    {
        var config = new AnyInferConfig(
            [ProviderSettings.Of("fake", apiKey: "env://SDK2_CONFIG", alias: "tenant")],
            new Route(["tenant:model"]),
            new Repair(1));

        var text = config.Dumps(comments: true);
        Assert.Contains("env://SDK2_CONFIG", text, StringComparison.Ordinal);
        Assert.Contains("_comment", text, StringComparison.Ordinal);
        Assert.DoesNotContain("env://SDK2_CONFIG", config.ToString(), StringComparison.Ordinal);

        var root = Path.Combine(Path.GetTempPath(), $"anyinfer-config-{Guid.NewGuid():N}");
        Directory.CreateDirectory(root);
        try
        {
            var destination = Path.Combine(root, "config.json");
            config.Dump(destination);
            Assert.Equal(text, File.ReadAllText(destination));
            Assert.Throws<ConfigException>(() => config.Dump(destination));
            config.Dump(destination, force: true);
            Assert.Throws<ConfigException>(() => config.Dump(Path.Combine(root, "missing", "config.json")));
        }
        finally
        {
            Directory.Delete(root, recursive: true);
        }
    }

    [Fact]
    public void Load_is_the_only_explicit_file_operation_and_preserves_bounded_parse_behavior()
    {
        var root = Path.Combine(Path.GetTempPath(), $"anyinfer-config-load-{Guid.NewGuid():N}");
        Directory.CreateDirectory(root);
        try
        {
            var source = Path.Combine(root, "config.json");
            File.WriteAllText(source, "{\"providers\":[{\"id\":\"fake\"}],\"default_route\":[\"fake:model\"]}", new System.Text.UTF8Encoding(false));

            var config = AnyInferConfig.Load(source, Registry());
            Assert.Equal("fake:model", Assert.Single(config.Route!.Targets));
            Assert.Throws<ConfigException>(() => AnyInferConfig.Load(Path.Combine(root, "missing.json"), Registry()));
        }
        finally
        {
            Directory.Delete(root, recursive: true);
        }
    }

    [Fact]
    public async Task Parsed_config_client_is_inert_until_actual_iteration_then_resolves_builds_and_dispatches_once()
    {
        var resolver = new CountingResolver("env://SDK2_KEY", "resolved-secret");
        var chain = new ResolverChain([resolver]);
        var adapter = new CountingAdapter();
        var factoryCalls = 0;
        ProviderConfig? bound = null;
        var registry = new ProviderRegistry([
            new ProviderDescriptor("fake", "Fake", (config, _) =>
            {
                factoryCalls++;
                bound = config;
                return ValueTask.FromResult<IAsyncDisposable>(adapter);
            }, setup: new ProviderSetupSpec([
                new SetupField("token", "Token", "secret"),
                new SetupField("region", "Region", "choice", choices: ["east", "west"]),
            ]))]);
        var config = AnyInferConfig.Loads("""
            {"providers":[{
              "id":"tenant", "adapter":"fake", "api_key":"env://SDK2_KEY",
              "headers":{"X-App":"sdk2"}, "timeout_s":9,
              "token":"vault://inert", "region":"east"
            }], "default_route":["tenant:model"]}
            """, registry, chain);

        await using var client = AsyncClient.FromConfig(config, registry, chain);
        var stream = client.StreamAsync("configured");
        Assert.Equal(0, resolver.ResolveCalls);
        Assert.Equal(0, factoryCalls);
        Assert.Equal(0, adapter.GenerateCalls);

        Assert.Equal("configured", (await stream.CollectAsync()).Text);
        Assert.Equal(2, resolver.ResolveCalls);
        Assert.Equal(1, factoryCalls);
        Assert.Equal(1, adapter.GenerateCalls);
        Assert.Equal("tenant", bound!.ProviderId);
        Assert.Equal("resolved-secret", bound.ApiKey);
        Assert.Equal("sdk2", bound.Headers["X-App"]);
        Assert.Equal(9, bound.TimeoutS);
        Assert.Equal("\"resolved-option\"", JsonWriter.Write(Assert.IsType<JsonObject>(bound.Options).Properties.Single(property => property.Name == "token").Value));
        Assert.Equal("configured", adapter.LastRequest!.Messages.Single().Content.OfType<Text>().Single().Value);
        Assert.Equal("tenant", stream.Result.Target!.ProviderId);
    }

    [Fact]
    public async Task Shared_configured_generation_fixture_replays_its_exact_utf8_scripts_through_the_public_configured_client()
    {
        var fixture = ReadSharedFixture();
        var fixtureConfig = ObjectProperty(fixture, "config");
        var fixtureRequest = ObjectProperty(fixture, "request");
        var scripts = ObjectProperty(fixture, "scripts");
        var requests = new FixtureRecorder();
        var primaryHandler = new FixtureHandler("primary", Responses(scripts, "primary"), requests);
        var backupHandler = new FixtureHandler("backup", Responses(scripts, "backup"), requests);
        var resolver = new CountingResolver("env://ANYINFER_SDK_CONFIG_TEST_KEY", "configured-secret");
        var chain = new ResolverChain([resolver]);
        var factoryCalls = 0;
        var builtin = ProviderRegistry.CreateDefault().Get("openai-compat");
        var registry = new ProviderRegistry([
            new ProviderDescriptor(builtin.Id, builtin.DisplayName, (bound, cancellationToken) =>
            {
                factoryCalls++;
                var handler = bound.ProviderId switch
                {
                    "primary" => primaryHandler,
                    "backup" => backupHandler,
                    _ => throw new Xunit.Sdk.XunitException($"Unexpected configured provider '{bound.ProviderId}'."),
                };
                var injectedSettings = ProviderSettings.Of(
                    bound.EngineId,
                    bound.BaseUrl,
                    bound.ApiKey,
                    bound.ApiVersion,
                    bound.Headers,
                    bound.Options,
                    bound.TimeoutS,
                    handler,
                    bound.ProviderId == bound.EngineId ? null : bound.ProviderId);
                return builtin.Factory(new ProviderConfig(injectedSettings, bound.EngineId, bound.ApiKey, bound.Options), cancellationToken);
            }, builtin.Aliases, builtin.Setup, builtin.DefaultBaseUrl, builtin.RequiresBaseUrl, builtin.StructuredOutputProfiles, builtin.MaxRepairAttempts),
        ]);
        var config = AnyInferConfig.Loads(JsonWriter.Write(fixtureConfig), registry, chain);

        await using (var client = AsyncClient.FromConfig(config, registry, chain))
        {
            var stream = client.StreamAsync(
                StringProperty(fixtureRequest, "prompt"),
                schema: ObjectProperty(fixtureRequest, "schema"));
            Assert.Equal(0, resolver.ResolveCalls);
            Assert.Equal(0, factoryCalls);
            Assert.Equal(0, primaryHandler.SendCalls);
            Assert.Equal(0, backupHandler.SendCalls);

            var result = await stream.CollectAsync();
            Assert.Equal("{\"answer\":\"ok\"}", result.Text);
            Assert.Equal("backup", result.Target!.ProviderId);
            Assert.Equal(1, result.RepairAttempts);
            Assert.Equal(3, result.Usage!.InputTokens);
            Assert.Equal(4, result.Usage.OutputTokens);
            Assert.Equal(["primary", "primary", "backup"], result.Attempts.Select(attempt => attempt.Target!.ProviderId));
            Assert.Equal(2, resolver.ResolveCalls);
            Assert.Equal(2, factoryCalls);
            Assert.Equal(2, primaryHandler.SendCalls);
            Assert.Equal(2, backupHandler.SendCalls);
            Assert.Empty(primaryHandler.Remaining);
            Assert.Empty(backupHandler.Remaining);
            Assert.Equal(4, requests.Requests.Count);

            Assert.All(requests.Requests, request =>
            {
                Assert.Equal("/v1/chat/completions", request.Path);
                Assert.Equal("sdk-configuration-parity", request.Headers["x-app"]);
                Assert.Equal("Bearer configured-secret", request.Headers["authorization"]);
                Assert.Equal("model", DocumentStringProperty(request.Body, "model"));
            });
            Assert.Equal(["primary", "primary", "backup", "backup"], requests.Requests.Select(request => request.InstanceId));

            var originalMessages = DocumentMessages(requests.Requests[2].Body);
            var correctionMessages = DocumentMessages(requests.Requests[3].Body);
            Assert.Equal(originalMessages.Length + 2, correctionMessages.Length);
            for (var index = 0; index < originalMessages.Length; index++)
            {
                Assert.Equal(originalMessages[index].GetRawText(), correctionMessages[index].GetRawText());
            }

            Assert.Equal("assistant", correctionMessages[^2].GetProperty("role").GetString());
            Assert.Equal("not-json", correctionMessages[^2].GetProperty("content").GetString());
            Assert.Equal("user", correctionMessages[^1].GetProperty("role").GetString());
            var feedback = correctionMessages[^1].GetProperty("content").GetString()!;
            Assert.StartsWith("Your previous response did not match the required JSON schema. Errors:\n", feedback, StringComparison.Ordinal);
            Assert.EndsWith("Respond again with ONLY a corrected JSON value that satisfies the schema. No prose, no code fences.", feedback, StringComparison.Ordinal);
        }

        Assert.True(primaryHandler.IsDisposed);
        Assert.True(backupHandler.IsDisposed);
        Assert.All(primaryHandler.Responses.Concat(backupHandler.Responses), response => Assert.True(response.Disposed));
    }

    [Fact]
    public void Custom_resolver_callback_exceptions_are_not_reclassified_as_configuration_errors()
    {
        foreach (var expected in new Exception[]
        {
            new ArgumentException("custom handles"),
            new OverflowException("custom handles"),
            new OperationCanceledException("custom handles"),
        })
        {
            var resolver = new ThrowingHandlesResolver(expected);
            var chain = new ResolverChain([resolver]);
            var actual = Assert.ThrowsAny<Exception>(() =>
                AnyInferConfig.Loads("{\"providers\":[{\"id\":\"fake\",\"api_key\":\"custom://key\"}]}", Registry(), chain));
            Assert.Same(expected, actual);
            Assert.IsNotType<ConfigException>(actual);
        }
    }

    private static ProviderRegistry Registry() => new([
        new ProviderDescriptor("fake", "Fake", static (_, _) => ValueTask.FromResult<IAsyncDisposable>(new CountingAdapter()), setup: new ProviderSetupSpec([
            new SetupField("token", "Token", "secret"),
            new SetupField("region", "Region", "choice", choices: ["east", "west"]),
        ])),
    ]);

    private sealed class CountingResolver : ICredentialResolver
    {
        private readonly string? _reference;
        private readonly string? _value;

        internal CountingResolver(string? reference = null, string? value = null)
        {
            _reference = reference;
            _value = value;
        }

        internal int ResolveCalls { get; private set; }

        public bool Handles(string reference) => reference == _reference || reference.StartsWith("vault://", StringComparison.Ordinal);

        public ValueTask<string> ResolveAsync(string reference, CancellationToken cancellationToken = default)
        {
            cancellationToken.ThrowIfCancellationRequested();
            ResolveCalls++;
            return ValueTask.FromResult(reference == _reference ? _value! : "resolved-option");
        }
    }

    private sealed class ThrowingHandlesResolver : ICredentialResolver
    {
        private readonly Exception _failure;
        internal ThrowingHandlesResolver(Exception failure) => _failure = failure;
        public bool Handles(string reference) => throw _failure;
        public ValueTask<string> ResolveAsync(string reference, CancellationToken cancellationToken = default) => throw _failure;
    }

    private sealed class CountingAdapter : IProviderAdapter
    {
        internal int GenerateCalls { get; private set; }
        internal WireRequest? LastRequest { get; private set; }

        public async IAsyncEnumerable<AdapterEvent> GenerateAsync(WireRequest request, [EnumeratorCancellation] CancellationToken cancellationToken = default)
        {
            GenerateCalls++;
            LastRequest = request;
            yield return new AdapterTextDelta("configured");
            await Task.Yield();
            cancellationToken.ThrowIfCancellationRequested();
            yield return new AdapterFinal("stop");
        }

        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }

    private static JsonObject ReadSharedFixture()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null)
        {
            var candidate = Path.Combine(directory.FullName, "tests", "fixtures", "sdk-configuration-v1", "configured-generation.json");
            if (File.Exists(candidate))
            {
                return Assert.IsType<JsonObject>(JsonReader.Read(File.ReadAllText(candidate, Encoding.UTF8)));
            }

            directory = directory.Parent;
        }

        throw new Xunit.Sdk.XunitException("The shared SDK.2 configuration fixture was not found from the test base directory.");
    }

    private static IEnumerable<FixtureResponse> Responses(JsonObject scripts, string provider)
    {
        var entries = ArrayProperty(scripts, provider);
        foreach (var entry in entries.Items.Select(static item => Assert.IsType<JsonObject>(item)))
        {
            var headers = ObjectProperty(entry, "headers");
            yield return new FixtureResponse(
                checked((int)IntegerProperty(entry, "status")),
                StringProperty(headers, "content-type"),
                StringProperty(entry, "body_utf8"));
        }
    }

    private static JsonObject ObjectProperty(JsonObject source, string name) => Assert.IsType<JsonObject>(ValueProperty(source, name));
    private static JsonArray ArrayProperty(JsonObject source, string name) => Assert.IsType<JsonArray>(ValueProperty(source, name));
    private static string StringProperty(JsonObject source, string name) => Assert.IsType<JsonString>(ValueProperty(source, name)).Value;
    private static string DocumentStringProperty(JsonDocument source, string name) => source.RootElement.GetProperty(name).GetString() ?? throw new Xunit.Sdk.XunitException($"Request property '{name}' was null.");
    private static JsonElement[] DocumentMessages(JsonDocument source) => source.RootElement.GetProperty("messages").EnumerateArray().ToArray();
    private static System.Numerics.BigInteger IntegerProperty(JsonObject source, string name) => Assert.IsType<JsonInteger>(ValueProperty(source, name)).Value;
    private static JsonValue ValueProperty(JsonObject source, string name) => source.TryGetValue(name, out var value) ? value : throw new Xunit.Sdk.XunitException($"Missing fixture property '{name}'.");

    private sealed record FixtureResponse(int Status, string ContentType, string Body);

    private sealed record CapturedHttpRequest(string InstanceId, string Path, IReadOnlyDictionary<string, string> Headers, JsonDocument Body);

    private sealed class FixtureRecorder
    {
        internal List<CapturedHttpRequest> Requests { get; } = [];
    }

    private sealed class FixtureHandler(string instanceId, IEnumerable<FixtureResponse> responses, FixtureRecorder recorder) : HttpMessageHandler
    {
        private readonly Queue<FixtureResponse> _remaining = new(responses);

        internal int SendCalls { get; private set; }
        internal bool IsDisposed { get; private set; }
        internal IReadOnlyCollection<FixtureResponse> Remaining => _remaining;
        internal List<TrackingResponse> Responses { get; } = [];

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            SendCalls++;
            var script = _remaining.Count != 0
                ? _remaining.Dequeue()
                : throw new InvalidOperationException("The input-only fixture script was exhausted.");
            var headers = request.Headers.Concat(request.Content!.Headers)
                .ToDictionary(static item => item.Key.ToLowerInvariant(), static item => string.Join(",", item.Value), StringComparer.Ordinal);
            var body = JsonDocument.Parse(await request.Content.ReadAsByteArrayAsync(cancellationToken));
            recorder.Requests.Add(new CapturedHttpRequest(instanceId, request.RequestUri!.AbsolutePath, headers, body));

            var response = new TrackingResponse((HttpStatusCode)script.Status)
            {
                Content = new ByteArrayContent(Encoding.UTF8.GetBytes(script.Body)),
            };
            response.Content.Headers.ContentType = MediaTypeHeaderValue.Parse(script.ContentType);
            Responses.Add(response);
            return response;
        }

        protected override void Dispose(bool disposing)
        {
            IsDisposed = true;
            base.Dispose(disposing);
        }
    }

    private sealed class TrackingResponse(HttpStatusCode status) : HttpResponseMessage(status)
    {
        internal bool Disposed { get; private set; }

        protected override void Dispose(bool disposing)
        {
            Disposed = true;
            base.Dispose(disposing);
        }
    }
}
