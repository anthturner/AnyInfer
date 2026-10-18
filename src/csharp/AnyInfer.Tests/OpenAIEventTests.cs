using System.Net;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using AnyInfer.Capabilities;
using AnyInfer.Credentials;
using AnyInfer.Events;
using AnyInfer.Json;
using AnyInfer.Providers;
using AnyInfer.Schema;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Public HTTP event and manifest observations over the shared input-only fixture.</summary>
public sealed class OpenAIEventTests
{
    private const string FixtureSecret = "SYNTHETIC-EVENT-SECRET";

    [Fact]
    public async Task Shared_event_fixture_drives_public_builtin_generation_repair_and_fallback()
    {
        var fixture = ReadFixture();
        var primary = new ScriptHandler("primary", Calls(fixture, "success", "repair-invalid", "repair-corrected", "retryable-primary", "retryable-primary-again"));
        var secondary = new ScriptHandler("secondary", Calls(fixture, "fallback-secondary"));
        var observer = new Collector();
        await using var client = CreateClient(fixture, new Dictionary<string, HttpMessageHandler> { ["primary"] = primary, ["secondary"] = secondary }, observer);

        Assert.Equal("primary", client.Resolve("primary:model").ProviderId);
        var inert = client.StreamAsync("not advanced", target: "primary:model");
        Assert.Empty(primary.Requests);
        Assert.Empty(secondary.Requests);
        await inert.DisposeAsync();

        var request = Object(fixture, "request");
        var schema = new SchemaSpec(Object(request, "schema"));
        var success = await client.GenerateAsync(Messages(request), target: Text(request, "success_target"), schema: schema);
        Assert.Equal("{\"answer\":\"café 𐀀\"}", success.Text);
        Assert.NotNull(success.Manifest);
        Assert.Null(success.Manifest!.Payloads);
        Assert.Null(success.Manifest.Usage.SearchUnits);
        AssertRequest(primary.Requests[0], "primary", body => Assert.Equal("json_schema", body.GetProperty("response_format").GetProperty("type").GetString()));

        var stream = client.StreamAsync(Messages(request), target: "primary:model", schema: schema, repair: new Repair(1));
        var streamEvents = new List<StreamEvent>();
        await foreach (var item in stream) streamEvents.Add(item);
        Assert.NotEmpty(streamEvents);
        var ended = Assert.IsType<StreamEnded>(streamEvents.Last());
        Assert.Equal(1, ended.Result.RepairAttempts);
        Assert.Equal("fixed", Assert.IsType<JsonString>(Assert.IsType<JsonObject>(ended.Result.Structured).Properties.Single().Value).Value);
        var repair = Assert.Single(observer.Events.OfType<RepairAttempted>());
        Assert.Null(repair.RawText);
        Assert.Equal("primary:model", repair.Target.ToString());
        AssertSubsequence(observer.Events.Where(item => item is not null && EventRequestId(item) == repair.RequestId).Select(static item => item.GetType()), typeof(RequestStarted), typeof(RepairAttempted), typeof(RequestCompleted));
        AssertRequest(primary.Requests[1], "primary", body =>
        {
            Assert.Equal("json_schema", body.GetProperty("response_format").GetProperty("type").GetString());
            Assert.True(body.GetProperty("stream").GetBoolean());
            Assert.True(body.GetProperty("stream_options").GetProperty("include_usage").GetBoolean());
        });
        AssertRequest(primary.Requests[2], "primary", body =>
        {
            Assert.Equal("json_schema", body.GetProperty("response_format").GetProperty("type").GetString());
            Assert.True(body.GetProperty("stream").GetBoolean());
            Assert.True(body.GetProperty("stream_options").GetProperty("include_usage").GetBoolean());
        });

        var route = new Route(["primary:model", "secondary:model"], retry: new Retry(MaxAttempts: 2, BackoffBaseS: 0, BackoffMaxS: 0));
        var fallback = await client.GenerateAsync(Messages(request), route: route);
        Assert.Equal("fallback ok", fallback.Text);
        var completions = observer.Events.OfType<RequestCompleted>().ToArray();
        Assert.NotEmpty(completions);
        var completed = completions.Last();
        AssertSubsequence(observer.Events.Where(item => EventRequestId(item) == completed.RequestId).Select(static item => item.GetType()), typeof(RequestStarted), typeof(RetryScheduled), typeof(FallbackTriggered), typeof(RequestCompleted));
        var fallbackFact = Assert.Single(observer.Events.OfType<FallbackTriggered>(), item => item.RequestId == completed.RequestId);
        Assert.Equal("primary:model", fallbackFact.FromTarget.ToString());
        Assert.Equal("secondary:model", fallbackFact.ToTarget);
        AssertRequest(primary.Requests[3], "primary", body => Assert.False(body.TryGetProperty("stream", out _)));
        AssertRequest(primary.Requests[4], "primary", body => Assert.False(body.TryGetProperty("stream", out _)));
        AssertRequest(secondary.Requests[0], "secondary", body => Assert.False(body.TryGetProperty("stream", out _)));
        Assert.Equal(["primary", "primary", "primary", "primary", "primary"], primary.Requests.Select(static item => item.Instance));
        Assert.Single(secondary.Requests);
        await client.DisposeAsync();
        Assert.Empty(primary.Remaining);
        Assert.Empty(secondary.Remaining);
        AssertHandlersDisposed(primary, secondary);
    }

    [Theory]
    [InlineData("ff", false, false, 0)]
    [InlineData("tf", true, false, 1)]
    [InlineData("ft", false, true, 0)]
    [InlineData("tt", true, true, 2)]
    public async Task Repair_payload_privacy_matrix_uses_fresh_public_builtin_clients(string matrix, bool manifestPayloads, bool observerPayloads, int expectedRepairTexts)
    {
        var fixture = ReadFixture();
        Redaction.RegisterSecret(FixtureSecret);
        var primary = new ScriptHandler("primary", Calls(fixture, $"matrix-{matrix}-invalid", $"matrix-{matrix}-corrected"));
        var payload = new Collector();
        var sibling = new Collector();
        await using var client = CreateClient(fixture, new Dictionary<string, HttpMessageHandler> { ["primary"] = primary }, manifestPayloads: manifestPayloads);
        client.Subscribe(sibling, payloads: false);
        client.Subscribe(payload, payloads: observerPayloads);
        var request = Object(fixture, "request");
        var result = await client.GenerateAsync(Messages(request), target: "primary:model", schema: new SchemaSpec(Object(request, "schema")), repair: new Repair(1));

        Assert.Equal("{\"answer\":\"fixed\"}", result.Text);
        Assert.Equal(1, result.RepairAttempts);
        Assert.Equal(expectedRepairTexts, result.Manifest?.Payloads?.RepairTexts.Count ?? 0);
        if (manifestPayloads)
        {
            Assert.DoesNotContain(FixtureSecret, Assert.IsType<string>(result.Manifest?.Payloads?.PromptText), StringComparison.Ordinal);
        }
        else
        {
            Assert.Null(result.Manifest?.Payloads);
        }
        var payloadStarted = Assert.Single(payload.Events.OfType<RequestStarted>());
        var siblingStarted = Assert.Single(sibling.Events.OfType<RequestStarted>());
        Assert.Null(siblingStarted.PromptText);
        if (observerPayloads)
        {
            Assert.DoesNotContain(FixtureSecret, Assert.IsType<string>(payloadStarted.PromptText), StringComparison.Ordinal);
        }
        else
        {
            Assert.Null(payloadStarted.PromptText);
        }
        var payloadRepair = Assert.Single(payload.Events.OfType<RepairAttempted>());
        var siblingRepair = Assert.Single(sibling.Events.OfType<RepairAttempted>());
        Assert.Equal(observerPayloads ? "not json" : null, payloadRepair.RawText);
        Assert.Null(siblingRepair.RawText);
        Assert.Equal(payloadRepair.RequestId, siblingRepair.RequestId);
        Assert.Empty(primary.Remaining);
        await client.DisposeAsync();
        AssertHandlersDisposed(primary);
    }

    [Fact]
    public async Task Disabled_manifest_does_not_capture_payloads_when_the_public_flag_is_true()
    {
        var fixture = ReadFixture();
        var primary = new ScriptHandler("primary", Calls(fixture, "matrix-disabled-invalid", "matrix-disabled-corrected"));
        await using var client = CreateClient(fixture, new Dictionary<string, HttpMessageHandler> { ["primary"] = primary }, manifests: false, manifestPayloads: true);
        var request = Object(fixture, "request");
        var result = await client.GenerateAsync(Messages(request), target: "primary:model", schema: new SchemaSpec(Object(request, "schema")), repair: new Repair(1));
        Assert.Null(result.Manifest);
        Assert.Empty(primary.Remaining);
        await client.DisposeAsync();
        AssertHandlersDisposed(primary);
    }

    [Fact]
    public async Task Secondary_alias_uses_its_own_json_schema_override_on_a_real_schema_request()
    {
        var fixture = ReadFixture();
        var secondary = new ScriptHandler("secondary", Calls(fixture, "fallback-secondary"));
        await using var client = CreateClient(fixture, new Dictionary<string, HttpMessageHandler> { ["secondary"] = secondary });
        var request = Object(fixture, "request");

        await Assert.ThrowsAsync<SchemaViolationException>(() => client.GenerateAsync(
            Messages(request),
            target: "secondary:model",
            schema: new SchemaSpec(Object(request, "schema"))));

        AssertRequest(Assert.Single(secondary.Requests), "secondary", body =>
            Assert.Equal("json_schema", body.GetProperty("response_format").GetProperty("type").GetString()));
        Assert.Empty(secondary.Remaining);
        await client.DisposeAsync();
        AssertHandlersDisposed(secondary);
    }

    [Fact]
    public async Task Public_generation_cancellation_and_close_join_real_builtin_send_and_body_reads()
    {
        var fixture = ReadFixture();
        var request = Object(fixture, "request");
        var schema = new SchemaSpec(Object(request, "schema"));

        var send = new BlockingSendHandler();
        await using (var client = CreateClient(fixture, new Dictionary<string, HttpMessageHandler> { ["primary"] = send }))
        using (var cancellation = new CancellationTokenSource())
        {
            var pending = client.GenerateAsync(Messages(request), target: "primary:model", schema: schema, cancellationToken: cancellation.Token);
            await send.Started.Task.WaitAsync(TimeSpan.FromSeconds(1));
            cancellation.Cancel();
            var observed = await AssertCancellationAsync(pending);
            Assert.Equal(cancellation.Token, observed.CancellationToken);
            await send.CancellationObserved.Task.WaitAsync(TimeSpan.FromSeconds(1));
            Assert.True(send.LastToken.CanBeCanceled);
            await DisposeWithinAsync(client);
        }
        Assert.True(send.Disposed);

        var read = new BlockingReadHandler();
        await using (var client = CreateClient(fixture, new Dictionary<string, HttpMessageHandler> { ["primary"] = read }))
        using (var cancellation = new CancellationTokenSource())
        {
            var pending = client.GenerateAsync(Messages(request), target: "primary:model", schema: schema, cancellationToken: cancellation.Token);
            await read.Content.ReadStarted.Task.WaitAsync(TimeSpan.FromSeconds(1));
            cancellation.Cancel();
            var observed = await AssertCancellationAsync(pending);
            Assert.Equal(cancellation.Token, observed.CancellationToken);
            await read.Content.CancellationObserved.Task.WaitAsync(TimeSpan.FromSeconds(1));
            Assert.True(read.Content.LastReadToken.CanBeCanceled);
        }
        AssertReadDisposed(read);

        var closingRead = new BlockingReadHandler();
        var closing = CreateClient(fixture, new Dictionary<string, HttpMessageHandler> { ["primary"] = closingRead });
        var active = closing.GenerateAsync(Messages(request), target: "primary:model", schema: schema);
        await closingRead.Content.ReadStarted.Task.WaitAsync(TimeSpan.FromSeconds(1));
        await DisposeWithinAsync(closing);
        Assert.True(closingRead.Content.CancellationObserved.Task.IsCompleted);
        await closingRead.Content.CancellationObserved.Task.WaitAsync(TimeSpan.FromSeconds(1));
        await AssertCancellationAsync(active);
        AssertReadDisposed(closingRead);
    }

    private static AsyncClient CreateClient(JsonObject fixture, IReadOnlyDictionary<string, HttpMessageHandler> handlers, IObserver? observer = null, bool manifestPayloads = false, bool manifests = true)
    {
        var builtin = ProviderRegistry.CreateDefault().Get("openai-compat");
        var registry = new ProviderRegistry([new ProviderDescriptor(builtin.Id, builtin.DisplayName, (bound, cancellationToken) =>
        {
            var handler = handlers[bound.ProviderId];
            var settings = ProviderSettings.Of(bound.EngineId, bound.BaseUrl, bound.ApiKey, bound.ApiVersion, bound.Headers, bound.Options, bound.TimeoutS, handler, bound.ProviderId == bound.EngineId ? null : bound.ProviderId);
            return builtin.Factory(new ProviderConfig(settings, bound.EngineId, bound.ApiKey, bound.Options), cancellationToken);
        }, builtin.Aliases, builtin.Setup, builtin.DefaultBaseUrl, builtin.RequiresBaseUrl, builtin.StructuredOutputProfiles, builtin.MaxRepairAttempts)]);
        return new AsyncClient(Instances(fixture).Where(settings => handlers.ContainsKey(settings.InstanceId)), registry, new ResolverChain([new FixtureResolver("env://ANYINFER_SDK_EVENT_TEST_KEY", "event-fixture-token")]), capabilityOverrides: Overrides(fixture, handlers.Keys), observers: observer is null ? null : [observer], manifests: manifests, manifestPayloads: manifestPayloads);
    }

    private static IReadOnlyDictionary<string, IReadOnlyDictionary<string, ModelCapabilities>> Overrides(JsonObject fixture, IEnumerable<string> configured)
    {
        var enabled = configured.ToHashSet(StringComparer.Ordinal);
        var result = new Dictionary<string, IReadOnlyDictionary<string, ModelCapabilities>>(StringComparer.Ordinal);
        foreach (var entry in Array(fixture, "capability_overrides").Items.Select(static value => Assert.IsType<JsonObject>(value)))
        {
            var target = Text(entry, "target").Split(':', 2);
            if (!enabled.Contains(target[0])) continue;
            var features = Feature.None;
            foreach (var feature in Array(entry, "features").Items) features |= FixtureFeature(Assert.IsType<JsonString>(feature).Value);
            result[target[0]] = new Dictionary<string, ModelCapabilities>(StringComparer.Ordinal) { [target[1]] = new ModelCapabilities(features: new Sourced<Feature>(features, Provenance.Override)) };
        }
        return result;
    }

    private static IEnumerable<ProviderSettings> Instances(JsonObject fixture) => Array(fixture, "instances").Items.Select(static value => Assert.IsType<JsonObject>(value)).Select(instance => ProviderSettings.Of(Text(instance, "adapter"), Text(instance, "base_url"), Text(instance, "credential"), headers: Headers(Object(instance, "headers")), timeoutS: Number(instance, "timeout_s"), alias: Text(instance, "id")));
    private static IEnumerable<FixtureCall> Calls(JsonObject fixture, params string[] ids) => Array(fixture, "calls").Items.Select(static value => Assert.IsType<JsonObject>(value)).Where(call => ids.Contains(Text(call, "id"), StringComparer.Ordinal)).Select(call => new FixtureCall(Text(call, "id"), Text(call, "instance"), checked((int)Integer(call, "status")), Text(Object(call, "headers"), "content-type"), Text(call, "body_utf8")));
    private static IReadOnlyList<Message> Messages(JsonObject request) => Array(request, "messages").Items.Select(static value => Assert.IsType<JsonObject>(value)).Select(message => Text(message, "role") switch { "system" => Message.System(Text(message, "content")), "user" => Message.User(Text(message, "content")), "assistant" => Message.Assistant(Text(message, "content")), _ => throw new Xunit.Sdk.XunitException("Unsupported fixture role.") }).ToArray();
    private static Feature FixtureFeature(string literal) => literal switch { "JSON_SCHEMA" => Feature.JsonSchema, _ => throw new Xunit.Sdk.XunitException($"Unsupported fixture feature '{literal}'.") };
    private static void AssertRequest(CapturedRequest request, string instance, Action<JsonElement> assertion) { Assert.Equal(HttpMethod.Post, request.Method); Assert.Equal("/v1/chat/completions", request.Path); Assert.Equal($"Bearer event-fixture-token", request.Headers["authorization"]); Assert.Equal(instance, request.Headers["x-event"]); Assert.Equal("application/json", request.ContentHeaders["content-type"]); using var document = JsonDocument.Parse(request.Body); Assert.Equal("model", document.RootElement.GetProperty("model").GetString()); assertion(document.RootElement); }
    private static void AssertSubsequence(IEnumerable<Type> actual, params Type[] expected) { var index = 0; foreach (var item in actual) if (index < expected.Length && item == expected[index]) index++; Assert.Equal(expected.Length, index); }
    private static string? EventRequestId(TelemetryEvent value) => value switch { RequestStarted item => item.RequestId, TargetResolved item => item.RequestId, AttemptStarted item => item.RequestId, AttemptCompleted item => item.RequestId, RetryScheduled item => item.RequestId, FallbackTriggered item => item.RequestId, RepairAttempted item => item.RequestId, RequestCompleted item => item.RequestId, _ => null };
    private static void AssertHandlersDisposed(params ScriptHandler[] handlers) { foreach (var handler in handlers) { Assert.All(handler.Responses, static response => Assert.True(response.Disposed)); Assert.True(handler.Disposed); } }
    private static void AssertReadDisposed(BlockingReadHandler handler) { Assert.True(handler.Response.Disposed); Assert.True(handler.Content.Disposed); Assert.True(handler.Content.StreamDisposed); Assert.True(handler.Disposed); }
    private static async Task<OperationCanceledException> AssertCancellationAsync(Task operation) => await Assert.ThrowsAnyAsync<OperationCanceledException>(() => operation.WaitAsync(TimeSpan.FromSeconds(1)));
    private static Task DisposeWithinAsync(AsyncClient client) => client.DisposeAsync().AsTask().WaitAsync(TimeSpan.FromSeconds(1));
    private static JsonObject ReadFixture() { for (var directory = new DirectoryInfo(AppContext.BaseDirectory); directory is not null; directory = directory.Parent) { var path = Path.Combine(directory.FullName, "tests", "fixtures", "sdk-events-v1", "openai-compat-events.json"); if (File.Exists(path)) return Assert.IsType<JsonObject>(JsonReader.Read(File.ReadAllText(path, Encoding.UTF8))); } throw new Xunit.Sdk.XunitException("The shared SDK event fixture was not found."); }
    private static JsonObject Object(JsonObject source, string name) => Assert.IsType<JsonObject>(Value(source, name));
    private static JsonArray Array(JsonObject source, string name) => Assert.IsType<JsonArray>(Value(source, name));
    private static string Text(JsonObject source, string name) => Assert.IsType<JsonString>(Value(source, name)).Value;
    private static double Number(JsonObject source, string name) => Assert.IsType<JsonNumber>(Value(source, name)).Value;
    private static System.Numerics.BigInteger Integer(JsonObject source, string name) => Assert.IsType<JsonInteger>(Value(source, name)).Value;
    private static JsonValue Value(JsonObject source, string name) => source.TryGetValue(name, out var value) ? value : throw new Xunit.Sdk.XunitException($"Fixture property '{name}' is missing.");
    private static IReadOnlyDictionary<string, string> Headers(JsonObject source) => source.Properties.ToDictionary(static item => item.Name, static item => Assert.IsType<JsonString>(item.Value).Value, StringComparer.Ordinal);

    private sealed record FixtureCall(string Id, string Instance, int Status, string ContentType, string Body);
    private sealed record CapturedRequest(string Instance, HttpMethod Method, string Path, IReadOnlyDictionary<string, string> Headers, IReadOnlyDictionary<string, string> ContentHeaders, byte[] Body);
    private sealed class Collector : IObserver { internal List<TelemetryEvent> Events { get; } = []; public void OnEvent(TelemetryEvent telemetryEvent) => Events.Add(telemetryEvent); }
    private sealed class FixtureResolver(string reference, string secret) : ICredentialResolver { public bool Handles(string candidate) => candidate == reference; public ValueTask<string> ResolveAsync(string candidate, CancellationToken cancellationToken = default) { cancellationToken.ThrowIfCancellationRequested(); return ValueTask.FromResult(secret); } }
    private sealed class ScriptHandler(string instance, IEnumerable<FixtureCall> calls) : HttpMessageHandler
    {
        private readonly Queue<FixtureCall> _calls = new(calls);
        internal List<CapturedRequest> Requests { get; } = [];
        internal List<TrackingResponse> Responses { get; } = [];
        internal IReadOnlyCollection<FixtureCall> Remaining => _calls;
        internal bool Disposed { get; private set; }
        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            var call = _calls.Count == 0 ? throw new Xunit.Sdk.XunitException("The input-only event script was exhausted.") : _calls.Dequeue();
            Assert.Equal(instance, call.Instance); Assert.NotNull(request.Content);
            Assert.Equal(string.Empty, request.RequestUri!.Query);
            Requests.Add(new CapturedRequest(instance, request.Method, request.RequestUri.AbsolutePath, request.Headers.ToDictionary(static item => item.Key.ToLowerInvariant(), static item => string.Join(',', item.Value), StringComparer.Ordinal), request.Content.Headers.ToDictionary(static item => item.Key.ToLowerInvariant(), static item => string.Join(',', item.Value), StringComparer.Ordinal), await request.Content.ReadAsByteArrayAsync(cancellationToken)));
            var response = new TrackingResponse((HttpStatusCode)call.Status) { Content = new ByteArrayContent(Encoding.UTF8.GetBytes(call.Body)) };
            response.Content.Headers.ContentType = MediaTypeHeaderValue.Parse(call.ContentType); Responses.Add(response); return response;
        }
        protected override void Dispose(bool disposing) { if (disposing) Disposed = true; base.Dispose(disposing); }
    }

    private sealed class BlockingSendHandler : HttpMessageHandler
    {
        internal TaskCompletionSource Started { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal TaskCompletionSource CancellationObserved { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal CancellationToken LastToken { get; private set; }
        internal bool Disposed { get; private set; }

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            LastToken = cancellationToken;
            Started.TrySetResult();
            try { await Task.Delay(Timeout.InfiniteTimeSpan, cancellationToken).ConfigureAwait(false); }
            catch (OperationCanceledException) { CancellationObserved.TrySetResult(); throw; }
            throw new Xunit.Sdk.XunitException("The cancellation-aware event send unexpectedly completed.");
        }

        protected override void Dispose(bool disposing) { if (disposing) Disposed = true; base.Dispose(disposing); }
    }

    private sealed class BlockingReadHandler : HttpMessageHandler
    {
        internal BlockingReadContent Content { get; } = new();
        internal TrackingResponse Response { get; } = new(HttpStatusCode.OK);
        internal bool Disposed { get; private set; }

        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Content.Headers.ContentType = MediaTypeHeaderValue.Parse("application/json");
            Response.Content = Content;
            return Task.FromResult<HttpResponseMessage>(Response);
        }

        protected override void Dispose(bool disposing) { if (disposing) Disposed = true; base.Dispose(disposing); }
    }

    private sealed class BlockingReadContent : HttpContent
    {
        internal TaskCompletionSource ReadStarted { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal TaskCompletionSource CancellationObserved { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal bool Disposed { get; private set; }
        internal bool StreamDisposed { get; private set; }
        internal CancellationToken LastReadToken { get; private set; }

        protected override bool TryComputeLength(out long length) { length = 0; return false; }
        protected override Task SerializeToStreamAsync(Stream stream, TransportContext? context) => Task.CompletedTask;
        protected override Task<Stream> CreateContentReadStreamAsync() => Task.FromResult<Stream>(new BlockingReadStream(this));
        protected override Task<Stream> CreateContentReadStreamAsync(CancellationToken cancellationToken) => Task.FromResult<Stream>(new BlockingReadStream(this));
        protected override void Dispose(bool disposing) { if (disposing) Disposed = true; base.Dispose(disposing); }

        private sealed class BlockingReadStream(BlockingReadContent owner) : Stream
        {
            public override bool CanRead => true;
            public override bool CanSeek => false;
            public override bool CanWrite => false;
            public override long Length => throw new NotSupportedException();
            public override long Position { get => throw new NotSupportedException(); set => throw new NotSupportedException(); }
            public override void Flush() { }
            public override Task FlushAsync(CancellationToken cancellationToken) => Task.CompletedTask;
            public override int Read(byte[] buffer, int offset, int count) => throw new NotSupportedException();
            public override async ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken cancellationToken = default)
            {
                owner.LastReadToken = cancellationToken;
                owner.ReadStarted.TrySetResult();
                try { await Task.Delay(Timeout.InfiniteTimeSpan, cancellationToken).ConfigureAwait(false); }
                catch (OperationCanceledException) { owner.CancellationObserved.TrySetResult(); throw; }
                return 0;
            }
            public override long Seek(long offset, SeekOrigin origin) => throw new NotSupportedException();
            public override void SetLength(long value) => throw new NotSupportedException();
            public override void Write(byte[] buffer, int offset, int count) => throw new NotSupportedException();
            protected override void Dispose(bool disposing) { if (disposing) owner.StreamDisposed = true; base.Dispose(disposing); }
        }
    }

    private sealed class TrackingResponse(HttpStatusCode status) : HttpResponseMessage(status) { internal bool Disposed { get; private set; } protected override void Dispose(bool disposing) { if (disposing) Disposed = true; base.Dispose(disposing); } }
}
