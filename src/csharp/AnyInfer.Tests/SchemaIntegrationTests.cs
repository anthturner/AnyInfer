using System.Numerics;
using System.Net;
using System.Net.Http;
using System.Runtime.CompilerServices;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using AnyInfer;
using AnyInfer.Json;
using AnyInfer.Providers;
using AnyInfer.Schema;
using Xunit;

namespace AnyInfer.Tests;

public sealed class SchemaIntegrationTests
{
    [Fact]
    public async Task Public_client_forwards_schema_name_and_repairs_once_on_the_same_target()
    {
        var adapter = new ScriptedAdapter((call, token) => call == 1
            ? Events(token, new AdapterTextDelta("{\"age\":\"wrong\"}"), new AdapterFinal("stop"))
            : Events(token, new AdapterTextDelta("{\"age\":7}"), new AdapterFinal("stop")));
        var schema = new SchemaSpec(JsonReader.Read("{\"type\":\"object\",\"required\":[\"age\"],\"properties\":{\"age\":{\"type\":\"integer\"}}}"), "age-response");
        await using var client = AsyncClient.FromAdapters([new ProviderRegistration("alpha", adapter)]);

        var result = await client.GenerateAsync("age", target: "alpha:model", schema: schema, repair: new Repair(1));

        Assert.Equal("{\"age\":7}", result.Text);
        Assert.Equal(1, result.RepairAttempts);
        Assert.Equal(2, adapter.Requests.Count);
        Assert.All(adapter.Requests, request => Assert.Equal("age-response", request.SchemaName));
        Assert.Equal("alpha", result.Target!.ProviderId);
        Assert.Equal("{\"age\":\"wrong\"}", Render(adapter.Requests[1].Messages[^2]));
        Assert.Contains("required JSON schema", Render(adapter.Requests[1].Messages[^1]), StringComparison.Ordinal);
    }

    [Fact]
    public async Task Public_modern_generation_retains_an_arbitrary_integer_under_a_noncomparing_schema_without_widening_frozen_json()
    {
        const string literal = "10000000000000000000000000000000000000000000000000000000000000000000000";
        var expected = BigInteger.Parse(literal);
        var adapter = new ScriptedAdapter((_, token) => Events(token, new AdapterTextDelta(literal), new AdapterFinal("stop")));
        var schema = SchemaSpec.FromJson("{}");
        await using var client = AsyncClient.FromAdapters([new ProviderRegistration("alpha", adapter)]);

        var result = await client.GenerateAsync("large integer", target: "alpha:model", schema: schema);

        Assert.Equal(expected, Assert.IsType<JsonInteger>(result.Structured).Value);
        Assert.Throws<FormatException>(() => JsonReader.Read(literal));
        Assert.Throws<ArgumentOutOfRangeException>(() => JsonWriter.Write(new JsonInteger(expected)));
        Assert.Single(adapter.Requests);
    }

    [Fact]
    public async Task Public_builtin_modern_schema_wire_preserves_a_decimal_range_integer_const_and_schema_name()
    {
        const string literal = "100000000000000000000";
        var expected = BigInteger.Parse(literal);
        var handler = new ModernSchemaWireHandler("{\"choices\":[{\"message\":{\"content\":" + JsonSerializer.Serialize(literal) + "},\"finish_reason\":\"stop\"}]}");
        var builtin = ProviderRegistry.CreateDefault().Get("openai-compat");
        var factoryCalls = 0;
        var registry = new ProviderRegistry([
            new ProviderDescriptor(
                builtin.Id,
                builtin.DisplayName,
                (bound, cancellationToken) =>
                {
                    factoryCalls++;
                    Assert.Same(handler, bound.Transport);
                    var settings = ProviderSettings.Of(
                        bound.EngineId,
                        bound.BaseUrl,
                        bound.ApiKey,
                        bound.ApiVersion,
                        bound.Headers,
                        bound.Options,
                        bound.TimeoutS,
                        bound.Transport,
                        bound.ProviderId == bound.EngineId ? null : bound.ProviderId);
                    return builtin.Factory(new ProviderConfig(settings, bound.EngineId, bound.ApiKey, bound.Options), cancellationToken);
                },
                aliases: builtin.Aliases,
                setup: builtin.Setup,
                defaultBaseUrl: builtin.DefaultBaseUrl,
                requiresBaseUrl: builtin.RequiresBaseUrl,
                structuredOutputProfiles: new Dictionary<string, StructuredOutputProfile>
                {
                    ["model"] = new StructuredOutputProfile(JsonSchema: true),
                },
                maxRepairAttempts: builtin.MaxRepairAttempts,
                locality: builtin.Locality,
                defaultCapabilities: builtin.DefaultCapabilities,
                staticCapabilities: builtin.StaticCapabilities,
                operations: builtin.Operations,
                staticEmbeddingCapabilities: builtin.StaticEmbeddingCapabilities,
                staticRerankCapabilities: builtin.StaticRerankCapabilities,
                tokenCalibration: builtin.TokenCalibration,
                rateLimitHeaders: builtin.RateLimitHeaders),
        ]);
        var schema = new SchemaSpec(SchemaSpec.FromJson("{\"const\":" + literal + "}").JsonSchema, "large-integer-wire");
        var client = new AsyncClient(
            [ProviderSettings.Of("openai-compat", "https://fixture.invalid/v1", "fixture-secret", transport: handler, alias: "wired")],
            registry);

        try
        {
            var result = await client.GenerateAsync("large integer", target: "wired:model", schema: schema);

            Assert.Equal(expected, Assert.IsType<JsonInteger>(result.Structured).Value);
            Assert.Equal(1, factoryCalls);
            Assert.NotNull(handler.Body);
            var body = handler.Body!.RootElement;
            Assert.Equal("json_schema", body.GetProperty("response_format").GetProperty("type").GetString());
            var jsonSchema = body.GetProperty("response_format").GetProperty("json_schema");
            Assert.Equal("large-integer-wire", jsonSchema.GetProperty("name").GetString());
            Assert.Equal(literal, jsonSchema.GetProperty("schema").GetProperty("const").GetRawText());
            Assert.False(jsonSchema.GetProperty("strict").GetBoolean());
        }
        finally
        {
            await client.DisposeAsync();
        }

        Assert.True(handler.IsDisposed);
    }

    [Fact]
    public async Task Public_builtin_modern_json_mode_wires_json_object_and_injects_the_canonical_schema_prompt()
    {
        var handler = new ModernSchemaWireHandler("{\"choices\":[{\"message\":{\"content\":\"7\"},\"finish_reason\":\"stop\"}]}");
        var builtin = ProviderRegistry.CreateDefault().Get("openai-compat");
        var registry = new ProviderRegistry([
            new ProviderDescriptor(
                builtin.Id,
                builtin.DisplayName,
                (bound, cancellationToken) =>
                {
                    Assert.Same(handler, bound.Transport);
                    var settings = ProviderSettings.Of(
                        bound.EngineId,
                        bound.BaseUrl,
                        bound.ApiKey,
                        bound.ApiVersion,
                        bound.Headers,
                        bound.Options,
                        bound.TimeoutS,
                        bound.Transport,
                        bound.ProviderId == bound.EngineId ? null : bound.ProviderId);
                    return builtin.Factory(new ProviderConfig(settings, bound.EngineId, bound.ApiKey, bound.Options), cancellationToken);
                },
                aliases: builtin.Aliases,
                setup: builtin.Setup,
                defaultBaseUrl: builtin.DefaultBaseUrl,
                requiresBaseUrl: builtin.RequiresBaseUrl,
                structuredOutputProfiles: new Dictionary<string, StructuredOutputProfile>
                {
                    ["model"] = new StructuredOutputProfile(JsonMode: true),
                },
                maxRepairAttempts: builtin.MaxRepairAttempts,
                locality: builtin.Locality,
                defaultCapabilities: builtin.DefaultCapabilities,
                staticCapabilities: builtin.StaticCapabilities,
                operations: builtin.Operations,
                staticEmbeddingCapabilities: builtin.StaticEmbeddingCapabilities,
                staticRerankCapabilities: builtin.StaticRerankCapabilities,
                tokenCalibration: builtin.TokenCalibration,
                rateLimitHeaders: builtin.RateLimitHeaders),
        ]);
        var client = new AsyncClient(
            [ProviderSettings.Of("openai-compat", "https://fixture.invalid/v1", "fixture-secret", transport: handler, alias: "wired")],
            registry);

        try
        {
            var result = await client.GenerateAsync("json mode", target: "wired:model", schema: SchemaSpec.FromJson("{\"type\":\"integer\"}"));

            Assert.Equal(new BigInteger(7), Assert.IsType<JsonInteger>(result.Structured).Value);
            Assert.NotNull(handler.Body);
            var body = handler.Body!.RootElement;
            var responseFormat = body.GetProperty("response_format");
            Assert.Equal("json_object", responseFormat.GetProperty("type").GetString());
            Assert.False(responseFormat.TryGetProperty("json_schema", out _));
            var messages = body.GetProperty("messages");
            Assert.Equal("system", messages[0].GetProperty("role").GetString());
            Assert.Equal("Respond with ONLY a JSON value matching this JSON Schema. No prose. Schema:\n{\n  \"type\": \"integer\"\n}", messages[0].GetProperty("content").GetString());
        }
        finally
        {
            await client.DisposeAsync();
        }

        Assert.True(handler.IsDisposed);
    }

    [Fact]
    public async Task Public_generation_maps_out_of_range_const_evaluation_to_terminal_schema_error_before_repair_or_fallback()
    {
        const string literal = "10000000000000000000000000000000000000000000000000000000000000000000000";
        var first = new ScriptedAdapter((_, token) => Events(token, new AdapterTextDelta(literal), new AdapterFinal("stop")));
        var fallback = new ScriptedAdapter((_, token) => Events(token, new AdapterTextDelta("unexpected"), new AdapterFinal("stop")));
        var schema = SchemaSpec.FromJson("{\"const\":" + literal + "}");
        await using var client = AsyncClient.FromAdapters([new ProviderRegistration("alpha", first), new ProviderRegistration("beta", fallback)]);

        var error = await Assert.ThrowsAsync<SchemaEvaluationException>(() => client.GenerateAsync(
            "out of range", route: new Route(["alpha:model", "beta:model"], new Retry(2, 0, 0)), schema: schema, repair: new Repair(1)));

        Assert.IsType<FormatException>(error.NativeInner);
        Assert.Equal("validate", error.Phase);
        Assert.False(error.Retryable);
        Assert.Equal("alpha", error.Provider);
        Assert.Single(first.Requests);
        Assert.Empty(fallback.Requests);
    }

    [Fact]
    public async Task Retriever_format_exception_escapes_unchanged_without_repair_or_fallback()
    {
        var planted = new FormatException("retriever format failure");
        var first = new ScriptedAdapter((_, token) => Events(token, new AdapterTextDelta("1"), new AdapterFinal("stop")));
        var fallback = new ScriptedAdapter((_, token) => Events(token, new AdapterTextDelta("unexpected"), new AdapterFinal("stop")));
        var schema = SchemaSpec.Coerce(JsonReader.Read("{\"$ref\":\"urn:test:format-retriever\"}"));
        await using var client = AsyncClient.FromAdapters(
            [new ProviderRegistration("alpha", first), new ProviderRegistration("beta", fallback)],
            new SchemaValidationOptions(retrieve: (_, _) => ValueTask.FromException<JsonValue?>(planted)));

        var escaped = await Assert.ThrowsAsync<FormatException>(() => client.GenerateAsync(
            "format", route: new Route(["alpha:model", "beta:model"], new Retry(2, 0, 0)), schema: schema, repair: new Repair(1)));

        Assert.Same(planted, escaped);
        Assert.Single(first.Requests);
        Assert.Empty(fallback.Requests);
    }

    [Fact]
    public async Task Terminal_reference_failure_happens_before_repair_retry_or_route_fallback()
    {
        var first = new ScriptedAdapter((_, token) => Events(token, new AdapterTextDelta("{}"), new AdapterFinal("stop")));
        var fallback = new ScriptedAdapter((_, token) => Events(token, new AdapterTextDelta("{\"unexpected\":true}"), new AdapterFinal("stop")));
        var schema = SchemaSpec.Coerce(JsonReader.Read("{\"$ref\":\"urn:test:missing\"}"));
        await using var client = AsyncClient.FromAdapters(
            [new ProviderRegistration("alpha", first), new ProviderRegistration("beta", fallback)],
            new SchemaValidationOptions());

        var error = await Assert.ThrowsAsync<SchemaReferenceException>(() => client.GenerateAsync(
            "schema", route: new Route(["alpha:model", "beta:model"], new Retry(3, 0, 0)), schema: schema, repair: new Repair(3)));

        Assert.Equal(new Uri("urn:test:missing"), error.ResourceUri);
        Assert.Single(first.Requests);
        Assert.Empty(fallback.Requests);
    }

    [Fact]
    public async Task Public_client_uses_registered_and_explicitly_retrieved_references_without_default_fetch()
    {
        var registeredAdapter = new ScriptedAdapter((_, token) => Events(token, new AdapterTextDelta("2"), new AdapterFinal("stop")));
        var retrievedAdapter = new ScriptedAdapter((_, token) => Events(token, new AdapterTextDelta("3"), new AdapterFinal("stop")));
        var registeredSchema = SchemaSpec.Coerce(JsonReader.Read("{\"$ref\":\"urn:test:registered\"}"));
        var retrievedSchema = SchemaSpec.Coerce(JsonReader.Read("{\"$ref\":\"urn:test:retrieved\"}"));
        var registeredRetrievals = 0;
        var registeredOptions = new SchemaValidationOptions(
            new Dictionary<Uri, JsonValue>
            {
                [new Uri("urn:test:registered")] = JsonReader.Read("{\"type\":\"integer\",\"minimum\":1}"),
            },
            retrieve: (_, _) =>
            {
                Interlocked.Increment(ref registeredRetrievals);
                return ValueTask.FromResult<JsonValue?>(null);
            });
        var retrievals = 0;
        var retrievedOptions = new SchemaValidationOptions(retrieve: (uri, token) =>
        {
            Assert.Equal(new Uri("urn:test:retrieved"), uri);
            Assert.False(token.IsCancellationRequested);
            Interlocked.Increment(ref retrievals);
            return ValueTask.FromResult<JsonValue?>(JsonReader.Read("{\"type\":\"integer\",\"minimum\":1}"));
        });
        await using var registered = AsyncClient.FromAdapters([new ProviderRegistration("alpha", registeredAdapter)], registeredOptions);
        await using var retrieved = AsyncClient.FromAdapters([new ProviderRegistration("alpha", retrievedAdapter)], retrievedOptions);

        var registeredResult = await registered.GenerateAsync("registered", target: "alpha:model", schema: registeredSchema);
        var retrievedResult = await retrieved.GenerateAsync("retrieved", target: "alpha:model", schema: retrievedSchema);

        Assert.Equal("2", registeredResult.Text);
        Assert.Equal("3", retrievedResult.Text);
        Assert.Equal(0, registeredRetrievals);
        Assert.Equal(1, retrievals);
        Assert.Single(registeredAdapter.Requests);
        Assert.Single(retrievedAdapter.Requests);
    }

    [Fact]
    public async Task Explicit_retriever_callback_fault_and_cancellation_preserve_their_original_identity()
    {
        var schema = SchemaSpec.Coerce(JsonReader.Read("{\"$ref\":\"urn:test:missing\"}"));
        var callbackFault = new InvalidOperationException("retriever fault");
        var faultOptions = new SchemaValidationOptions(retrieve: (_, _) => ValueTask.FromException<JsonValue?>(callbackFault));
        using var cancellation = new CancellationTokenSource();
        var cancellationOptions = new SchemaValidationOptions(retrieve: (_, _) =>
        {
            cancellation.Cancel();
            return ValueTask.FromResult<JsonValue?>(JsonReader.Read("{\"type\":\"integer\"}"));
        });

        var fault = await Assert.ThrowsAsync<InvalidOperationException>(() => SchemaValidator.ValidateAsync(JsonReader.Read("1"), schema, faultOptions));
        var cancelled = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => SchemaValidator.ValidateAsync(JsonReader.Read("1"), schema, cancellationOptions, cancellation.Token));

        Assert.Same(callbackFault, fault);
        Assert.Equal(cancellation.Token, cancelled.CancellationToken);
    }

    [Fact]
    public async Task Retriever_thrown_operation_cancellation_escapes_unchanged_before_repair_or_fallback()
    {
        using var source = new CancellationTokenSource();
        source.Cancel();
        var planted = new OperationCanceledException("retriever cancellation", innerException: null, source.Token);
        var first = new ScriptedAdapter((_, token) => Events(token, new AdapterTextDelta("1"), new AdapterFinal("stop")));
        var fallback = new ScriptedAdapter((_, token) => Events(token, new AdapterTextDelta("unexpected"), new AdapterFinal("stop")));
        var schema = SchemaSpec.Coerce(JsonReader.Read("{\"$ref\":\"urn:test:cancelled-retriever\"}"));
        await using var client = AsyncClient.FromAdapters(
            [new ProviderRegistration("alpha", first), new ProviderRegistration("beta", fallback)],
            new SchemaValidationOptions(retrieve: (_, _) => ValueTask.FromException<JsonValue?>(planted)));

        var escaped = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => client.GenerateAsync(
            "cancelled", route: new Route(["alpha:model", "beta:model"], new Retry(2, 0, 0)), schema: schema, repair: new Repair(1)));

        Assert.Same(planted, escaped);
        Assert.Equal(source.Token, escaped.CancellationToken);
        Assert.Single(first.Requests);
        Assert.Empty(fallback.Requests);
    }

    [Fact]
    public async Task Retriever_late_success_after_caller_cancellation_cannot_publish_assessment_repair_or_result()
    {
        var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var adapter = new ScriptedAdapter((_, token) => Events(token, new AdapterTextDelta("1"), new AdapterFinal("stop")));
        using var caller = new CancellationTokenSource();
        var options = new SchemaValidationOptions(retrieve: async (_, _) =>
        {
            entered.TrySetResult();
            await release.Task.ConfigureAwait(false);
            return JsonReader.Read("{\"type\":\"integer\"}");
        });
        var schema = SchemaSpec.Coerce(JsonReader.Read("{\"$ref\":\"urn:test:late\"}"));
        await using var client = AsyncClient.FromAdapters([new ProviderRegistration("alpha", adapter)], options);

        var pending = client.GenerateAsync("late", target: "alpha:model", schema: schema, cancellationToken: caller.Token);
        await entered.Task.WaitAsync(TimeSpan.FromSeconds(5));
        caller.Cancel();
        release.TrySetResult();
        var cancelled = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending);

        Assert.Equal(caller.Token, cancelled.CancellationToken);
        Assert.Single(adapter.Requests);
        Assert.Equal(0, adapter.DisposeCalls);
    }

    [Fact]
    public async Task Retriever_late_success_after_caller_cancellation_cannot_start_assessment_repair_or_fallback()
    {
        var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var first = new ScriptedAdapter((_, token) => Events(token, new AdapterTextDelta("\"wrong\""), new AdapterFinal("stop")));
        var fallback = new ScriptedAdapter((_, token) => Events(token, new AdapterTextDelta("1"), new AdapterFinal("stop")));
        using var caller = new CancellationTokenSource();
        var options = new SchemaValidationOptions(retrieve: async (_, _) =>
        {
            entered.TrySetResult();
            await release.Task.ConfigureAwait(false);
            return JsonReader.Read("{\"type\":\"integer\"}");
        });
        var schema = SchemaSpec.Coerce(JsonReader.Read("{\"$ref\":\"urn:test:late-invalid\"}"));
        await using var client = AsyncClient.FromAdapters(
            [new ProviderRegistration("alpha", first), new ProviderRegistration("beta", fallback)],
            options);

        var pending = client.GenerateAsync(
            "late invalid",
            route: new Route(["alpha:model", "beta:model"], new Retry(2, 0, 0)),
            schema: schema,
            repair: new Repair(1),
            cancellationToken: caller.Token);
        await entered.Task.WaitAsync(TimeSpan.FromSeconds(5));
        caller.Cancel();
        release.TrySetResult();
        var cancelled = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending);

        Assert.Equal(caller.Token, cancelled.CancellationToken);
        Assert.Single(first.Requests);
        Assert.Empty(fallback.Requests);
    }

    [Fact]
    public async Task Retriever_unsafe_callback_cannot_self_dispose_async_or_captured_sync_client()
    {
        var asyncEntered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var asyncRelease = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var asyncFailure = new TaskCompletionSource<Exception?>(TaskCreationOptions.RunContinuationsAsynchronously);
        AsyncClient? asyncClient = null;
        var schema = SchemaSpec.Coerce(JsonReader.Read("{\"$ref\":\"urn:test:self\"}"));
        var asyncAdapter = new ScriptedAdapter((_, token) => Events(token, new AdapterTextDelta("1"), new AdapterFinal("stop")));
        var asyncOptions = new SchemaValidationOptions(retrieve: async (_, token) =>
        {
            using var registration = token.UnsafeRegister(static state =>
            {
                var callback = ((AsyncClient Client, TaskCompletionSource<Exception?> Failure))state!;
                try
                {
                    callback.Client.DisposeAsync().AsTask().GetAwaiter().GetResult();
                    callback.Failure.TrySetResult(null);
                }
                catch (Exception exception)
                {
                    callback.Failure.TrySetResult(exception);
                }
            }, (asyncClient!, asyncFailure));
            asyncEntered.TrySetResult();
            await asyncRelease.Task.ConfigureAwait(false);
            return JsonReader.Read("{\"type\":\"integer\"}");
        });
        asyncClient = AsyncClient.FromAdapters([new ProviderRegistration("alpha", asyncAdapter)], asyncOptions);

        var pendingAsync = asyncClient.GenerateAsync("self", target: "alpha:model", schema: schema);
        await asyncEntered.Task.WaitAsync(TimeSpan.FromSeconds(5));
        var externalAsyncClose = asyncClient.DisposeAsync().AsTask();
        var asyncCallback = await asyncFailure.Task.WaitAsync(TimeSpan.FromSeconds(5));
        asyncRelease.TrySetResult();
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pendingAsync);
        await externalAsyncClose;
        Assert.IsType<InvalidOperationException>(asyncCallback);
        Assert.Equal(1, asyncAdapter.DisposeCalls);

        var syncEntered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var syncRelease = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var syncFailure = new TaskCompletionSource<Exception?>(TaskCreationOptions.RunContinuationsAsynchronously);
        Client? syncClient = null;
        var syncAdapter = new ScriptedAdapter((_, token) => Events(token, new AdapterTextDelta("1"), new AdapterFinal("stop")));
        var syncOptions = new SchemaValidationOptions(retrieve: async (_, token) =>
        {
            using var registration = token.UnsafeRegister(static state =>
            {
                var callback = ((Client Client, TaskCompletionSource<Exception?> Failure))state!;
                try
                {
                    callback.Client.Dispose();
                    callback.Failure.TrySetResult(null);
                }
                catch (Exception exception)
                {
                    callback.Failure.TrySetResult(exception);
                }
            }, (syncClient!, syncFailure));
            syncEntered.TrySetResult();
            await syncRelease.Task.ConfigureAwait(false);
            return JsonReader.Read("{\"type\":\"integer\"}");
        });
        syncClient = Client.FromAdapters([new ProviderRegistration("alpha", syncAdapter)], syncOptions);

        var pendingSync = Task.Run(() => syncClient.Generate("self", target: "alpha:model", schema: schema));
        await syncEntered.Task.WaitAsync(TimeSpan.FromSeconds(5));
        var externalSyncClose = Task.Run(syncClient.Dispose);
        var syncCallback = await syncFailure.Task.WaitAsync(TimeSpan.FromSeconds(5));
        syncRelease.TrySetResult();
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pendingSync);
        await externalSyncClose;
        Assert.IsType<InvalidOperationException>(syncCallback);
        Assert.Equal(1, syncAdapter.DisposeCalls);
    }

    [Fact]
    public async Task Regex_timeout_is_terminal_before_repair_or_fallback_and_retriever_timeout_identity_is_preserved()
    {
        var timedOut = new ScriptedAdapter((_, token) => Events(token, new AdapterTextDelta(JsonWriter.Write(new JsonString(new string('a', 4_096) + "!"))), new AdapterFinal("stop")));
        var fallback = new ScriptedAdapter((_, token) => Events(token, new AdapterTextDelta("unexpected"), new AdapterFinal("stop")));
        var catastrophic = SchemaSpec.Coerce(JsonReader.Read("{\"pattern\":\"^(a+)+$\"}"));
        await using var client = AsyncClient.FromAdapters(
            [new ProviderRegistration("alpha", timedOut), new ProviderRegistration("beta", fallback)],
            new SchemaValidationOptions(regexTimeout: TimeSpan.FromMilliseconds(1)));

        var error = await Assert.ThrowsAsync<SchemaEvaluationException>(() => client.GenerateAsync(
            "timeout", route: new Route(["alpha:model", "beta:model"], new Retry(2, 0, 0)), schema: catastrophic, repair: new Repair(1)));

        Assert.IsType<RegexMatchTimeoutException>(error.NativeInner);
        Assert.Single(timedOut.Requests);
        Assert.Empty(fallback.Requests);

        var catastrophicPropertyInstance = new JsonObject([
            new AnyInfer.Json.JsonProperty(new string('a', 16_384) + "!", new JsonInteger(1)),
        ]);
        var propertyTimedOut = new ScriptedAdapter((_, token) => Events(token, new AdapterTextDelta(JsonWriter.Write(catastrophicPropertyInstance)), new AdapterFinal("stop")));
        var propertyFallback = new ScriptedAdapter((_, token) => Events(token, new AdapterTextDelta("unexpected"), new AdapterFinal("stop")));
        var catastrophicProperty = SchemaSpec.Coerce(JsonReader.Read("{\"type\":\"object\",\"patternProperties\":{\"^(a+)+$\":{\"type\":\"integer\"}}}"));
        await using var propertyClient = AsyncClient.FromAdapters(
            [new ProviderRegistration("alpha", propertyTimedOut), new ProviderRegistration("beta", propertyFallback)],
            new SchemaValidationOptions(regexTimeout: TimeSpan.FromMilliseconds(50)));

        var propertyError = await Assert.ThrowsAsync<SchemaEvaluationException>(() => propertyClient.GenerateAsync(
            "property timeout", route: new Route(["alpha:model", "beta:model"], new Retry(2, 0, 0)), schema: catastrophicProperty, repair: new Repair(1)));

        Assert.IsType<RegexMatchTimeoutException>(propertyError.NativeInner);
        Assert.Single(propertyTimedOut.Requests);
        Assert.Empty(propertyFallback.Requests);

        var callbackTimeout = new RegexMatchTimeoutException("^(a+)+$", "aaaa!", TimeSpan.FromMilliseconds(1));
        var referenceSchema = SchemaSpec.Coerce(JsonReader.Read("{\"$ref\":\"urn:test:callback-timeout\"}"));
        var callbackAdapter = new ScriptedAdapter((_, token) => Events(token, new AdapterTextDelta("1"), new AdapterFinal("stop")));
        await using var callbackClient = AsyncClient.FromAdapters(
            [new ProviderRegistration("alpha", callbackAdapter)],
            new SchemaValidationOptions(retrieve: (_, _) => ValueTask.FromException<JsonValue?>(callbackTimeout)));

        var propagated = await Assert.ThrowsAsync<RegexMatchTimeoutException>(() => callbackClient.GenerateAsync("callback", target: "alpha:model", schema: referenceSchema));

        Assert.Same(callbackTimeout, propagated);
        Assert.Single(callbackAdapter.Requests);
    }

    [Fact]
    public async Task Public_request_keeps_modern_schema_validation_late_after_extraction()
    {
        var adapter = new ScriptedAdapter((_, token) => Events(token, new AdapterTextDelta("not json"), new AdapterFinal("stop")));
        var malformed = new SchemaSpec(JsonReader.Read("{\"type\":17}"));
        await using var client = AsyncClient.FromAdapters([new ProviderRegistration("alpha", adapter)]);

        var error = await Assert.ThrowsAsync<SchemaViolationException>(() => client.GenerateAsync("schema", target: "alpha:model", schema: malformed));

        Assert.Equal("no_json_candidate", error.Issues[0].Rule);
        Assert.Single(adapter.Requests);
    }

    private static string Render(Message message) => string.Concat(message.Content.OfType<Text>().Select(static part => part.Value));

    private sealed class ScriptedAdapter : IProviderAdapter
    {
        private readonly Func<int, CancellationToken, IAsyncEnumerable<AdapterEvent>> _script;

        internal ScriptedAdapter(Func<int, CancellationToken, IAsyncEnumerable<AdapterEvent>> script) => _script = script;

        internal List<WireRequest> Requests { get; } = [];
        internal int DisposeCalls { get; private set; }

        public IAsyncEnumerable<AdapterEvent> GenerateAsync(WireRequest request, CancellationToken cancellationToken = default)
        {
            Requests.Add(request);
            return _script(Requests.Count, cancellationToken);
        }

        public ValueTask DisposeAsync()
        {
            DisposeCalls++;
            return ValueTask.CompletedTask;
        }
    }

    private sealed class ModernSchemaWireHandler(string responseBody) : HttpMessageHandler
    {
        internal JsonDocument? Body { get; private set; }
        internal bool IsDisposed { get; private set; }

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Assert.Equal(HttpMethod.Post, request.Method);
            Assert.Equal("/v1/chat/completions", request.RequestUri!.AbsolutePath);
            Assert.NotNull(request.Content);
            Body = JsonDocument.Parse(await request.Content.ReadAsByteArrayAsync(cancellationToken));
            return new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(responseBody, Encoding.UTF8, "application/json"),
            };
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing) IsDisposed = true;
            base.Dispose(disposing);
        }
    }

    private static async IAsyncEnumerable<AdapterEvent> Events(
        [EnumeratorCancellation] CancellationToken cancellationToken,
        params AdapterEvent[] events)
    {
        foreach (var item in events)
        {
            cancellationToken.ThrowIfCancellationRequested();
            yield return item;
            await Task.Yield();
        }
    }
}
